"""Mutations. Every change to the graph goes through here.

Three rules hold for all of them:

*Nothing is destroyed.* Archiving replaces deletion; a node that is archived
keeps its file, its text and its history, and can be brought back.

*Computed fields are off limits.* :func:`_guard` refuses any authored write to a
field the sweep owns. That is enforced here rather than trusted, because the one
thing an agent must never be able to do is write its own global status.

*Every mutation is logged, then re-derived.* Write the file, sweep the graph,
persist the derived fields, append the event. An interrupted mutation leaves a
consistent file and a missing log line, never the reverse.
"""

from __future__ import annotations

import functools
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable

from . import events
from .checks import load_graph
from .graph import Graph
from .hash import certificate
from .load import (
    load_nodes,
    node_path,
    parse_node,
    persist_computed,
    quoted,
    set_frontmatter,
    write_node,
)
from .model import (
    COMPUTED_FIELDS,
    EXTRACTED_FIELDS,
    NOTES,
    PROOF,
    STATEMENT,
    VERIFICATION_FIELDS,
    Claim,
    Hypothesis,
    Node,
    Use,
    VerificationRecord,
    set_section,
)
from .paths import Project
from .propagate import sweep


#: Every mutation takes this. Writes are already atomic per file, but a
#: mutation is *read the graph, change it, sweep, write the derived fields* —
#: two of those interleaving would let one sweep persist values computed before
#: the other's edit. The web interface runs role calls on a worker thread while
#: the user edits, so this is a real ordering, not a hypothetical one.
#:
#: It is re-entrant (ops call other ops) and process-local. Two *processes* —
#: a UI and a CLI at once — are still unguarded; see the locking row in
#: UPGRADE.md.
_LOCK = threading.RLock()


def serialised(fn):
    """Run this mutation to completion before another one starts."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _LOCK:
            return fn(*args, **kwargs)

    return wrapper


class _Unset:
    pass


_UNSET = _Unset()


class OpError(Exception):
    """A mutation that would leave the graph inconsistent. Refused, not applied."""


class ComputedFieldError(OpError):
    """Someone tried to author a derived field."""


@dataclass
class Result:
    node: Node | None
    graph: Graph
    event: dict[str, Any]
    rewritten: list[str] = field(default_factory=list)


def _guard(key: str) -> None:
    if key in COMPUTED_FIELDS:
        raise ComputedFieldError(
            f"{key!r} is computed by the propagation sweep and must never be "
            "written by hand or from an agent response"
        )
    if key in VERIFICATION_FIELDS:
        raise ComputedFieldError(
            f"{key!r} is written only by a verification (ops.record_verification), "
            "which derives it from the verification record — no role may set it"
        )
    if key in EXTRACTED_FIELDS:
        raise ComputedFieldError(
            f"{key!r} is the claim ledger, written only by ops.record_ledger from an "
            "extraction of the current proof text"
        )


def open_graph(project: Project) -> Graph:
    graph, diagnostics, swept = load_graph(project)
    if not swept:
        raise OpError(
            "the children relation has a cycle, so nothing can be derived; "
            "run `bp check` and break the cycle first"
        )
    blocking = [d for d in diagnostics if d.severity == "error"]
    if blocking:
        raise OpError(
            "some node files could not be read:\n  "
            + "\n  ".join(d.message for d in blocking)
        )
    return graph


def set_authored(
    node: Node, key: str, value: Any, yaml_value: Any = _UNSET
) -> None:
    """Set one authored frontmatter field on both the model and the file map.

    Fields whose model type is a pydantic object (``hypotheses``, ``uses``) pass
    the model value and a plain ``yaml_value`` for the file, so the in-memory
    node stays typed and the file stays YAML.
    """
    _guard(key)
    setattr(node, key, value)
    set_frontmatter(node, key, value if yaml_value is _UNSET else yaml_value)


def _finish(
    project: Project,
    graph: Graph,
    node: Node | None,
    kind: str,
    payload: dict[str, Any],
    actor: str = "human",
) -> Result:
    sweep(graph)
    rewritten = [n.id for n in graph.nodes.values() if persist_computed(n)]
    event = events.append(
        project, kind, node.id if node else None, payload, actor=actor
    )
    return Result(node=node, graph=graph, event=event, rewritten=rewritten)


def stale_radius(graph: Graph, node_id: str) -> list[str]:
    """Which verifications a change to this node's statement would invalidate.

    Editing a statement invalidates two things: any verification *of* it, and any
    verification of a node that *cites* it, because the tool those proofs used
    changed underneath them. This walks that set so the user can see the blast
    radius before committing, not after.
    """
    hit: set[str] = set()
    frontier = [node_id]
    seen = {node_id}
    node = graph.get(node_id)
    if node is not None and node.verified_against:
        hit.add(node_id)
    while frontier:
        current = frontier.pop()
        for parent_id in graph.parents(current):
            if parent_id in seen:
                continue
            seen.add(parent_id)
            frontier.append(parent_id)
            parent = graph[parent_id]
            if parent.verified_against:
                hit.add(parent_id)
    return sorted(hit)


# --- creation ----------------------------------------------------------------

NEW_NODE_TEMPLATE = """---
id: {id}
role: {role}
children: []
strategy: null
difficulty: {difficulty}
lifecycle: active
local_status: unverified
flags: []
hypotheses: []
uses: {{}}
---

## Statement

{statement}

## Proof

{proof}

## Notes

{notes}
"""


@serialised
def add_node(
    project: Project,
    node_id: str,
    *,
    role: str = "lemma",
    statement: str = "",
    proof: str = "",
    notes: str = "",
    difficulty: str = "unknown",
    strategy: str | None = None,
    hypotheses: Iterable[dict[str, str]] | None = None,
    target: bool = False,
    parent: str | None = None,
    actor: str = "human",
) -> Result:
    """Create a node. Optionally attach it to a parent's ``children``."""
    project.nodes_dir.mkdir(parents=True, exist_ok=True)
    path = node_path(project, node_id)
    if path.exists():
        raise OpError(f"{path} already exists")

    existing, _ = load_nodes(project)
    if any(n.id == node_id for n in existing):
        raise OpError(f"a node with id {node_id!r} already exists")

    text = NEW_NODE_TEMPLATE.format(
        id=node_id,
        role=role,
        difficulty=difficulty,
        statement=statement.strip() or "% statement not written yet",
        proof=proof.strip(),
        notes=notes.strip(),
    )
    node = parse_node(text, path)
    if strategy:
        set_authored(node, "strategy", strategy)
    if target:
        set_authored(node, "target", True)
    if hypotheses:
        hyps = [Hypothesis(**dict(h)) for h in hypotheses]
        set_authored(
            node, "hypotheses", hyps, [h.model_dump() for h in hyps]
        )
    write_node(node, path)

    graph = open_graph(project)
    if parent is not None:
        parent_node = graph.get(parent)
        if parent_node is None:
            raise OpError(f"parent {parent!r} does not exist")
        if node_id not in parent_node.children:
            set_authored(parent_node, "children", [*parent_node.children, node_id])
            # Give the new child its row in the discharge table. Citing a child
            # with no row at all is `DIS010`, and a user who has just attached a
            # lemma by hand did not make that mistake — the system did. With the
            # row present, the checks say the useful thing instead: `DIS011`,
            # once per hypothesis that still needs a source.
            uses = dict(parent_node.uses)
            uses.setdefault(node_id, Use())
            set_authored(
                parent_node, "uses", uses,
                {c: u.model_dump() for c, u in uses.items()},
            )
            write_node(parent_node)
            graph = open_graph(project)

    return _finish(
        project,
        graph,
        graph.get(node_id),
        "add_node",
        {"role": role, "parent": parent, "difficulty": difficulty},
        actor=actor,
    )


# --- body edits ---------------------------------------------------------------


@serialised
def _edit_section(
    project: Project,
    node_id: str,
    section: str,
    text: str,
    kind: str,
    actor: str,
) -> Result:
    graph = open_graph(project)
    node = graph.get(node_id)
    if node is None:
        raise OpError(f"no node {node_id!r}")
    before = node.section(section)
    radius = stale_radius(graph, node_id) if section == STATEMENT else []
    node.body = set_section(node.body, section, text)
    write_node(node)
    return _finish(
        project,
        graph,
        node,
        kind,
        {
            "section": section,
            "chars_before": len(before),
            "chars_after": len(text),
            "stale_radius": radius,
        },
        actor=actor,
    )


@serialised
def edit_statement(
    project: Project, node_id: str, tex: str, actor: str = "human"
) -> Result:
    """Replace the Statement section.

    This is the one edit with a blast radius: it moves the statement hash, which
    invalidates this node's verification and every verification that cited it.
    The affected ids are in the event payload under ``stale_radius`` — show them
    to the user *before* committing.
    """
    return _edit_section(project, node_id, STATEMENT, tex, "edit_statement", actor)


@serialised
def edit_proof(project: Project, node_id: str, tex: str, actor: str = "human") -> Result:
    return _edit_section(project, node_id, PROOF, tex, "edit_proof", actor)


@serialised
def add_note(project: Project, node_id: str, text: str, actor: str = "human") -> Result:
    """Append a paragraph to Notes. Notes are fed to agents as context."""
    graph = open_graph(project)
    node = graph.get(node_id)
    if node is None:
        raise OpError(f"no node {node_id!r}")
    stamp = events.now()
    existing = node.notes_section.strip()
    entry = f"*{stamp} — {actor}.* {text.strip()}"
    node.body = set_section(
        node.body, NOTES, f"{existing}\n\n{entry}".strip() if existing else entry
    )
    write_node(node)
    return _finish(project, graph, node, "add_note", {"text": text}, actor=actor)


# --- structure ---------------------------------------------------------------


@serialised
def set_children(
    project: Project, node_id: str, children: list[str], actor: str = "human"
) -> Result:
    graph = open_graph(project)
    node = graph.get(node_id)
    if node is None:
        raise OpError(f"no node {node_id!r}")
    before = list(node.children)

    seen: set[str] = set()
    for cid in children:
        if cid in seen:
            raise OpError(f"child {cid!r} listed twice")
        seen.add(cid)
        if cid == node_id:
            raise OpError(f"{node_id} cannot be its own child")
        child = graph.get(cid)
        if child is None:
            raise OpError(f"child {cid!r} does not exist — create it first")
        if child.lifecycle != "active":
            raise OpError(f"child {cid!r} is archived")
        if node_id in graph.descendants(cid) or cid in graph.ancestors(node_id):
            raise OpError(
                f"making {cid!r} a child of {node_id!r} would create a cycle"
            )

    set_authored(node, "children", list(children))
    write_node(node)
    return _finish(
        project,
        graph,
        node,
        "set_children",
        {"before": before, "after": list(children)},
        actor=actor,
    )


@serialised
def set_uses(
    project: Project,
    node_id: str,
    uses: dict[str, dict[str, Any]],
    actor: str = "human",
) -> Result:
    """Replace the discharge table.

    The table is validated for *shape* here; whether it is complete is
    :func:`bp.discharge.check_discharge`'s job, and whether each named source
    actually entails the hypothesis is the verifier's.
    """
    graph = open_graph(project)
    node = graph.get(node_id)
    if node is None:
        raise OpError(f"no node {node_id!r}")
    try:
        parsed = {cid: Use(**entry) for cid, entry in uses.items()}
    except Exception as exc:
        raise OpError(f"malformed uses table: {exc}") from exc
    set_authored(
        node, "uses", parsed, {cid: use.model_dump() for cid, use in parsed.items()}
    )
    write_node(node)
    return _finish(
        project, graph, node, "set_uses", {"children": sorted(parsed)}, actor=actor
    )


@serialised
def set_hypotheses(
    project: Project,
    node_id: str,
    hypotheses: list[dict[str, str]],
    actor: str = "human",
) -> Result:
    graph = open_graph(project)
    node = graph.get(node_id)
    if node is None:
        raise OpError(f"no node {node_id!r}")
    ids = [h.get("id") for h in hypotheses]
    if len(set(ids)) != len(ids):
        raise OpError("hypothesis ids must be unique within a node")
    try:
        hyps = [Hypothesis(**dict(h)) for h in hypotheses]
    except Exception as exc:
        raise OpError(f"malformed hypothesis list: {exc}") from exc
    set_authored(node, "hypotheses", hyps, [h.model_dump() for h in hyps])
    write_node(node)
    return _finish(
        project, graph, node, "set_hypotheses", {"ids": ids}, actor=actor
    )


@serialised
def set_strategy(
    project: Project, node_id: str, strategy: str | None, actor: str = "human"
) -> Result:
    """Set the free-text strategy hint. Fed to the decomposer on later attempts."""
    graph = open_graph(project)
    node = graph.get(node_id)
    if node is None:
        raise OpError(f"no node {node_id!r}")
    before = node.strategy
    set_authored(node, "strategy", strategy or None)
    write_node(node)
    return _finish(
        project,
        graph,
        node,
        "set_strategy",
        {"before": before, "after": strategy},
        actor=actor,
    )


@serialised
def relabel(
    project: Project, node_id: str, difficulty: str, actor: str = "human"
) -> Result:
    graph = open_graph(project)
    node = graph.get(node_id)
    if node is None:
        raise OpError(f"no node {node_id!r}")
    if difficulty not in {"standard", "routine", "hard", "unknown"}:
        raise OpError(f"unknown difficulty {difficulty!r}")
    before = node.difficulty
    set_authored(node, "difficulty", difficulty)
    write_node(node)
    return _finish(
        project,
        graph,
        node,
        "relabel",
        {"before": before, "after": difficulty},
        actor=actor,
    )


# --- status ------------------------------------------------------------------


@serialised
def _set_status(
    project: Project,
    node_id: str,
    status: str,
    reason: str,
    kind: str,
    actor: str,
) -> Result:
    if not reason.strip():
        raise OpError(
            f"{kind} requires a reason — it is what the support certificate prints "
            "and what tells you later why this was left open"
        )
    graph = open_graph(project)
    node = graph.get(node_id)
    if node is None:
        raise OpError(f"no node {node_id!r}")
    set_authored(node, "local_status", status)
    set_authored(node, "status_reason", reason.strip())
    write_node(node)
    return _finish(project, graph, node, kind, {"reason": reason.strip()}, actor=actor)


def admit(project: Project, node_id: str, reason: str, actor: str = "human") -> Result:
    """Mark a node admitted: believed, not proved, and carried as visible debt."""
    return _set_status(project, node_id, "admitted", reason, "admit", actor)


def set_assumption(
    project: Project, node_id: str, reason: str, actor: str = "human"
) -> Result:
    """Mark a node an assumption: deliberately taken as given for this project."""
    return _set_status(project, node_id, "assumption", reason, "set_assumption", actor)


@serialised
def record_ledger(
    project: Project,
    node_id: str,
    claims: list[dict[str, Any]],
    proof_digest: str,
    actor: str = "extractor",
) -> Result:
    """The only writer of ``claims`` and ``claims_of``.

    The ledger is a computed field, so it does not go through
    :func:`set_authored`: it is written here, from an extraction of the proof text
    whose hash is recorded alongside it. When the proof moves, ``claims_of`` stops
    matching and ``LED100`` says the ledger is describing an earlier proof rather
    than letting a stale audit pass for a current one.
    """
    graph = open_graph(project)
    node = graph.get(node_id)
    if node is None:
        raise OpError(f"no node {node_id!r}")

    ids = [c.get("id") for c in claims]
    if len(set(ids)) != len(ids):
        raise OpError("claim ids must be unique within a node")
    try:
        parsed = [Claim(**dict(c)) for c in claims]
    except Exception as exc:
        raise OpError(f"malformed claim ledger: {exc}") from exc

    node.claims = parsed
    set_frontmatter(node, "claims", [c.model_dump() for c in parsed])
    node.claims_of = proof_digest
    set_frontmatter(node, "claims_of", quoted(proof_digest))
    write_node(node)
    return _finish(
        project,
        graph,
        node,
        "record_ledger",
        {
            "claims": len(parsed),
            "unsourced": sum(1 for c in parsed if not c.sourced),
        },
        actor=actor,
    )


@serialised
def record_verification(
    project: Project,
    node_id: str,
    verdict: str,
    flags: list[dict[str, Any]] | None = None,
    record: dict[str, Any] | None = None,
    actor: str = "verifier",
) -> Result:
    """The only writer of ``verified_against`` and ``verification``.

    On ``verified`` the node records this statement's hash and each child's hash
    as they stand now. Any later change to any of them makes the node stale,
    which is how a verification certificate is prevented from outliving the
    claim it certified.

    ``verdict`` is not an opinion a role hands in. It is derived from ``record``
    by :func:`bp.verification.implied_status`, and when a record is supplied this
    function checks that the two agree rather than trusting the caller — a role
    that could pass ``verified`` with a record full of confirmed objections would
    be setting ``local_status`` by the back door.
    """
    if verdict not in {"verified", "flagged"}:
        raise OpError(f"verdict must be 'verified' or 'flagged', not {verdict!r}")
    if record is not None:
        from .verification import implied_status

        try:
            parsed_record = VerificationRecord(**record)
        except Exception as exc:
            raise OpError(f"malformed verification record: {exc}") from exc
        implied = implied_status(parsed_record)
        if implied != verdict:
            raise OpError(
                f"the verification record for {node_id} implies {implied!r}, not "
                f"{verdict!r}. local_status is derived from the record; it is not a "
                "field a role gets to choose."
            )

    graph = open_graph(project)
    node = graph.get(node_id)
    if node is None:
        raise OpError(f"no node {node_id!r}")

    if verdict == "verified":
        set_authored(node, "local_status", "verified")
        set_authored(node, "flags", [])
        cert = certificate(node, graph)
        node.verified_against = cert
        set_frontmatter(
            node, "verified_against", {k: quoted(v) for k, v in cert.items()}
        )
    else:
        set_authored(node, "local_status", "flagged")
        set_authored(node, "flags", [dict(f) for f in (flags or [])])
    if record is not None:
        node.verification = parsed_record
        set_frontmatter(node, "verification", _yaml_record(parsed_record))
    write_node(node)
    return _finish(
        project,
        graph,
        node,
        "verify",
        {
            "verdict": verdict,
            "flags": len(flags or []),
            "level": (record or {}).get("level"),
        },
        actor=actor,
    )


def _yaml_record(record: VerificationRecord) -> dict[str, Any]:
    """The record as plain YAML values.

    ``checked_at`` is a timestamp string and must stay one: unquoted, YAML would
    read it back as a datetime, which is the same class of bug as an unquoted hex
    hash becoming a float.
    """
    data = record.model_dump()
    if data.get("checked_at"):
        data["checked_at"] = quoted(str(data["checked_at"]))
    return data


# --- archival ----------------------------------------------------------------


@serialised
def archive(
    project: Project, node_id: str, cascade: bool = True, actor: str = "human"
) -> Result:
    """Archive a node and, optionally, the descendants it orphans.

    Nothing is deleted: the files stay, the text stays, ``lifecycle`` becomes
    ``archived`` and the node leaves the active graph. Citations to it are
    removed from its parents — otherwise the graph would be permanently
    inconsistent — and the removals are recorded in the event so the change is
    reversible by reading the log.
    """
    graph = open_graph(project)
    node = graph.get(node_id)
    if node is None:
        raise OpError(f"no node {node_id!r}")
    if node.target:
        raise OpError("refusing to archive the target node")

    doomed = {node_id}
    if cascade:
        candidates = graph.descendants(node_id)
        changed = True
        while changed:
            changed = False
            for cid in sorted(candidates):
                if cid in doomed:
                    continue
                remaining = [p for p in graph.parents(cid) if p not in doomed]
                child = graph[cid]
                if not remaining and not child.target:
                    doomed.add(cid)
                    changed = True

    detached: list[tuple[str, str]] = []
    for parent_id in sorted(graph.active):
        parent = graph[parent_id]
        if parent_id in doomed:
            continue
        keep = [c for c in parent.children if c not in doomed]
        if keep != parent.children:
            detached.extend((parent_id, c) for c in parent.children if c in doomed)
            set_authored(parent, "children", keep)
            uses = {c: u for c, u in parent.uses.items() if c not in doomed}
            set_authored(
                parent, "uses", uses, {c: u.model_dump() for c, u in uses.items()}
            )
            write_node(parent)

    for cid in sorted(doomed):
        target_node = graph[cid]
        set_authored(target_node, "lifecycle", "archived")
        write_node(target_node)

    return _finish(
        project,
        graph,
        node,
        "archive",
        {
            "nodes": sorted(doomed),
            "detached": [f"{p} -> {c}" for p, c in sorted(detached)],
        },
        actor=actor,
    )


@serialised
def unarchive(project: Project, node_id: str, actor: str = "human") -> Result:
    graph = open_graph(project)
    node = graph.get(node_id)
    if node is None:
        raise OpError(f"no node {node_id!r}")
    set_authored(node, "lifecycle", "active")
    write_node(node)
    return _finish(project, graph, node, "unarchive", {}, actor=actor)


@serialised
def set_preamble(project: Project, text: str, actor: str = "human") -> Result:
    """Write the project preamble.

    Not a node mutation, but a project one, and it changes how every statement
    reads — so it goes through ops and lands in the event log like anything else.
    """
    from .load import atomic_write

    path = project.preamble_path
    before = path.read_text(encoding="utf-8") if path.exists() else ""
    atomic_write(path, text if text.endswith("\n") or not text else text + "\n")
    graph = open_graph(project)
    return _finish(
        project,
        graph,
        None,
        "set_preamble",
        {"chars_before": len(before), "chars_after": len(text)},
        actor=actor,
    )


def read_preamble(project: Project) -> str:
    path = project.preamble_path
    return path.read_text(encoding="utf-8") if path.exists() else ""


@serialised
def sweep_only(project: Project) -> tuple[Graph, list[str]]:
    """Re-derive and persist without changing anything authored."""
    graph = open_graph(project)
    rewritten = [n.id for n in graph.nodes.values() if persist_computed(n)]
    return graph, rewritten
