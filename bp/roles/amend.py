"""The amender: adapt an existing decomposition to an edited parent.

The gap this fills was a real one. Editing a statement invalidates that node's
verification and its ancestors' — correctly — and leaves the children alone, also
correctly, since a child does not depend on its parent. But nothing anywhere said
*the four children may no longer cover this statement*, and the only tool for acting
on that was ``bp redo``: archive the whole subtree and decompose again, losing every
proof underneath. For "I tightened a hypothesis" that is the wrong instrument by an
order of magnitude.

So: one call that reads the parent as it now stands, the children as they stand, and
— when the history has it — the diff of what actually changed, and returns the
minimal set of changes. The design follows the same three rules as everything else
here.

*Code enumerates, the model judges.* Every existing child must come back with
exactly one verdict — ``keep``, ``edit`` or ``drop``. Silence about a child is
``AMD001`` and a repair round, because a lemma nobody mentioned is
indistinguishable from a lemma somebody forgot.

*The existing gate does the gating.* An amendment is assembled into a candidate
graph in memory and run through :func:`bp.discharge.check_discharge` and the
children-used check, exactly as a decomposition is. An amendment that leaves a
hypothesis unsourced is rejected before anything is written — which is the whole
point, since what a parent's edit changes *is* what its children can be given.

*Nothing is applied silently.* :func:`amend` writes nothing at all: it stores a
proposal and returns per-item diffs. :func:`apply_amendment` then applies only the
items the mathematician accepted, having first copied the subtree to ``attempts/``.
An agent editing a mathematician's lemma behind their back is what the rest of this
system refuses to do, and it would not stop being wrong just because it is usually
right.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .. import hash as hash_mod
from .. import history as history_mod
from .. import ops
from ..agents.base import CallMeta
from ..agents.registry import Registry
from ..checks import load_graph
from ..diagnostics import Diagnostic, err, warn
from ..graph import Graph
from ..load import atomic_write
from ..model import ID_RE, STATEMENT, Hypothesis, Node, Use, set_section
from ..paths import Project
from . import context
from .decompose import (
    HypothesisSpec,
    ProposedChild,
    UseSpec,
    assign_ids_for,
    check_candidate,
    child_node,
    resolve_slugs,
)

#: Its own role, inheriting from the decomposer, so a user can point it somewhere
#: cheaper than a full decomposition without touching Python.
ROLE = "amender"

PROPOSAL_NAME = "amend.json"
#: Bumped when the stored proposal's shape changes. An old one is refused rather
#: than migrated: re-proposing costs one call.
PROPOSAL_VERSION = 1

#: How much of each child's proof the amender sees. It decides about *statements*
#: and hypotheses and is explicitly forbidden from touching proofs, so the proof is
#: context for judging whether an edit is disruptive — not material to be rewritten.
CHILD_PROOF_CHARS = 900


# --- what the model returns ---------------------------------------------------


class ChildAmendment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="the existing child's node id, verbatim")
    action: Literal["keep", "edit", "drop"]
    why: str = Field(
        default="",
        description="one line, required for `edit` and `drop`: what about the "
        "parent's new statement forces this",
    )
    statement: str = Field(
        default="",
        description="for `edit`: the COMPLETE new statement, as LaTeX prose",
    )
    hypotheses: list[HypothesisSpec] = Field(
        default_factory=list,
        description="for `edit`: the COMPLETE new hypothesis list, not just the "
        "changed entries",
    )


class Amendment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["no-change", "amend", "redecompose"] = Field(
        description="`no-change` if the edit does not affect the decomposition; "
        "`amend` to propose changes; `redecompose` if patching would be dishonest"
    )
    assessment: str = Field(
        description="two or three sentences: what changed in the parent, and what it "
        "does to the decomposition"
    )
    children: list[ChildAmendment] = Field(
        default_factory=list, description="one entry per existing child, all of them"
    )
    new_children: list[ProposedChild] = Field(
        default_factory=list, description="lemmas the new statement needs and nothing "
        "existing provides"
    )
    reduction_proof: str = Field(
        default="", description="the parent's complete rewritten proof, if it changed"
    )
    reduction_changed: bool = False
    uses: dict[str, UseSpec] = Field(
        default_factory=dict,
        description="the complete discharge table, keyed by child id or by new "
        "child's slug",
    )
    notes: str = ""

    @property
    def amending(self) -> bool:
        return self.verdict == "amend"

    def by_id(self) -> dict[str, ChildAmendment]:
        return {c.id: c for c in self.children}

    @property
    def dropped(self) -> list[str]:
        return [c.id for c in self.children if c.action == "drop"]

    @property
    def edited(self) -> list[str]:
        return [c.id for c in self.children if c.action == "edit"]


# --- the proposal, as stored ---------------------------------------------------


class Item(BaseModel):
    """One reviewable change. The unit the mathematician accepts or rejects."""

    model_config = ConfigDict(extra="forbid")

    #: ``child:<id>``, ``new:<slug>`` or ``reduction``.
    key: str
    kind: Literal["edit", "drop", "new", "reduction"]
    node: str
    why: str = ""
    before: str = ""
    after: str = ""
    hypotheses_before: list[dict[str, str]] = Field(default_factory=list)
    hypotheses_after: list[dict[str, str]] = Field(default_factory=list)


class Proposal(BaseModel):
    """An amendment on disk, so applying it is a separate, cheap, offline act."""

    model_config = ConfigDict(extra="forbid")

    version: int = PROPOSAL_VERSION
    node: str
    proposed_at: str = ""
    verdict: str = "amend"
    assessment: str = ""
    notes: str = ""
    amendment: Amendment
    #: new child slug -> the node id it would get.
    ids: dict[str, str] = Field(default_factory=dict)
    items: list[Item] = Field(default_factory=list)
    #: What the parent and children said when this was proposed. Applying against
    #: text that has moved since would be applying a judgement about a different
    #: graph, so it is refused rather than attempted.
    fingerprint: dict[str, str] = Field(default_factory=dict)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    calls: int = 0

    @property
    def keys(self) -> list[str]:
        return [i.key for i in self.items]


class ProposalUnreadable(Exception):
    pass


def proposal_path(project: Project, node_id: str) -> Path:
    if not ID_RE.match(node_id):  # pragma: no cover - guarded upstream
        raise ValueError(f"not a node id: {node_id!r}")
    return project.state_dir / "amend" / f"{node_id}.json"


def save_proposal(project: Project, proposal: Proposal) -> Path:
    path = proposal_path(project, proposal.node)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(
        path, json.dumps(proposal.model_dump(), indent=2, ensure_ascii=False) + "\n"
    )
    return path


def load_proposal(project: Project, node_id: str) -> Proposal | None:
    path = proposal_path(project, node_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProposalUnreadable(f"{path} could not be read: {exc}") from exc
    if data.get("version") != PROPOSAL_VERSION:
        raise ProposalUnreadable(
            f"{path} was written by an older version of this tool. Run `bp amend "
            f"{node_id}` again; it is one call."
        )
    try:
        return Proposal.model_validate(data)
    except Exception as exc:  # noqa: BLE001 - the message is the product
        raise ProposalUnreadable(f"{path} is not a proposal this version understands: {exc}") from exc


def fingerprint(node: Node, graph: Graph) -> dict[str, str]:
    """The parent and its children, digested. What "still current" means here."""
    out = {node.id: f"{hash_mod.statement_hash(node)}/{hash_mod.proof_hash(node)}"}
    for cid in node.children:
        child = graph.get(cid)
        if child is not None:
            out[cid] = f"{hash_mod.statement_hash(child)}/{hash_mod.proof_hash(child)}"
    return out


def is_current(proposal: Proposal, node: Node, graph: Graph) -> bool:
    return proposal.fingerprint == fingerprint(node, graph)


# --- the deterministic checks -------------------------------------------------


def check_amendment(
    amendment: Amendment, node: Node, graph: Graph
) -> list[Diagnostic]:
    """``AMD001``–``AMD006``: is this amendment complete and self-consistent?

    Nothing here judges whether an edit is *right* — that is the mathematician's, one
    item at a time. What it guarantees is that every child was accounted for and that
    every proposed change carries the justification the reviewer needs.
    """
    out: list[Diagnostic] = []
    existing = list(node.children)
    seen: dict[str, ChildAmendment] = {}

    for entry in amendment.children:
        if entry.id not in existing:
            out.append(
                warn(
                    "AMD002",
                    node,
                    f"the amendment mentions {entry.id!r}, which is not a child of "
                    f"{node.id}; it is ignored",
                )
            )
            continue
        if entry.id in seen:
            out.append(
                warn(
                    "AMD002",
                    node,
                    f"{entry.id} is given two verdicts ({seen[entry.id].action} and "
                    f"{entry.action}); the first one stands",
                )
            )
            continue
        seen[entry.id] = entry
        if entry.action == "edit" and not entry.statement.strip():
            out.append(
                err(
                    "AMD003",
                    node,
                    f"{entry.id} is marked `edit` with no replacement statement",
                    hint="an `edit` carries the complete new statement, not a diff",
                )
            )
        if entry.action in {"edit", "drop"} and not entry.why.strip():
            out.append(
                err(
                    "AMD004",
                    node,
                    f"{entry.id} is marked `{entry.action}` with no reason",
                    hint="the mathematician accepts or rejects each change on its own, "
                    "so each one has to say what about the new statement forces it",
                )
            )

    missing = [c for c in existing if c not in seen]
    if missing:
        out.append(
            err(
                "AMD001",
                node,
                f"the amendment says nothing about {', '.join(missing)}",
                hint="every existing child needs a verdict — `keep` is the expected "
                "one and the cheapest. Silence about a lemma cannot be told apart "
                "from having forgotten it.",
            )
        )

    if amendment.amending and not (
        amendment.edited or amendment.dropped or amendment.new_children
        or amendment.reduction_changed
    ):
        out.append(
            err(
                "AMD005",
                node,
                "the verdict is `amend` but nothing is proposed to change",
                hint="return `no-change` instead — it is a useful answer and it saves "
                "the user a review",
            )
        )

    if amendment.reduction_changed and not amendment.reduction_proof.strip():
        out.append(
            err(
                "AMD006",
                node,
                "`reduction_changed` is set but no replacement proof was given",
            )
        )
    return out


# --- assembling the candidate -------------------------------------------------


def amended_child(child: Node, entry: ChildAmendment) -> Node:
    """A copy of ``child`` with the amendment's statement and hypotheses applied."""
    out = child.model_copy(deep=True)
    if entry.statement.strip():
        out.body = set_section(out.body, STATEMENT, entry.statement.strip())
    if entry.hypotheses:
        out.hypotheses = [Hypothesis(id=h.id, tex=h.tex) for h in entry.hypotheses]
    return out


def resolve_uses(
    amendment: Amendment, ids: dict[str, str], keep: set[str]
) -> dict[str, Use]:
    """The discharge table with new children's slugs rewritten to their ids.

    Keys naming a child that is not in the amended decomposition are dropped: the
    table describes what the reduction now cites, and a row for an archived lemma
    would be a claim about a dependency that no longer exists.
    """
    out: dict[str, Use] = {}
    for key, use in amendment.uses.items():
        target = ids.get(key, key)
        if target not in keep:
            continue
        discharges: dict[str, str] = {}
        for hyp_id, source in use.discharges.items():
            text = source.strip()
            if text.startswith("child:"):
                slug = text[len("child:") :].strip()
                if slug in ids:
                    text = f"child:{ids[slug]}"
            discharges[hyp_id] = text
        out[target] = Use(applied_to=use.applied_to, discharges=discharges)
    return out


def candidate_graph(
    graph: Graph, node: Node, amendment: Amendment, ids: dict[str, str]
) -> tuple[Graph, Node]:
    """The graph this amendment *would* produce, without writing anything."""
    by_id = amendment.by_id()
    kept_ids: list[str] = []
    members: list[Node] = []

    for cid in node.children:
        entry = by_id.get(cid)
        child = graph.get(cid)
        if child is None:
            continue
        if entry is not None and entry.action == "drop":
            continue
        kept_ids.append(cid)
        members.append(
            amended_child(child, entry) if entry and entry.action == "edit" else child
        )

    new_nodes = [child_node(c, ids[c.slug]) for c in amendment.new_children]
    final_ids = kept_ids + [ids[c.slug] for c in amendment.new_children]

    parent = node.model_copy(deep=True)
    parent.children = final_ids
    parent.uses = resolve_uses(amendment, ids, set(final_ids))
    if amendment.reduction_changed and amendment.reduction_proof.strip():
        parent.body = set_section(
            parent.body, "Proof", resolve_slugs(amendment.reduction_proof.strip(), ids)
        )

    touched = {node.id, *(n.id for n in members), *(n.id for n in new_nodes)}
    others = [n for n in graph if n.id not in touched and n.id not in amendment.dropped]
    return Graph([*others, parent, *members, *new_nodes]), parent


# --- diffs, for review --------------------------------------------------------


def items_for(
    amendment: Amendment, node: Node, graph: Graph, ids: dict[str, str]
) -> list[Item]:
    """One reviewable item per proposed change, in the order a reader wants them."""
    out: list[Item] = []
    by_id = amendment.by_id()
    for cid in node.children:
        entry = by_id.get(cid)
        child = graph.get(cid)
        if entry is None or child is None or entry.action == "keep":
            continue
        if entry.action == "drop":
            out.append(
                Item(
                    key=f"child:{cid}",
                    kind="drop",
                    node=cid,
                    why=entry.why,
                    before=child.statement_section.strip(),
                    after="",
                    hypotheses_before=[h.model_dump() for h in child.hypotheses],
                )
            )
            continue
        out.append(
            Item(
                key=f"child:{cid}",
                kind="edit",
                node=cid,
                why=entry.why,
                before=child.statement_section.strip(),
                after=entry.statement.strip(),
                hypotheses_before=[h.model_dump() for h in child.hypotheses],
                hypotheses_after=[h.model_dump() for h in entry.hypotheses],
            )
        )
    for proposed in amendment.new_children:
        out.append(
            Item(
                key=f"new:{proposed.slug}",
                kind="new",
                node=ids[proposed.slug],
                why=proposed.notes,
                before="",
                after=proposed.statement.strip(),
                hypotheses_after=[h.model_dump() for h in proposed.hypotheses],
            )
        )
    if amendment.reduction_changed and amendment.reduction_proof.strip():
        out.append(
            Item(
                key="reduction",
                kind="reduction",
                node=node.id,
                why="the reduction has to change to establish the new statement",
                before=node.proof_section.strip(),
                after=resolve_slugs(amendment.reduction_proof.strip(), ids),
            )
        )
    return out


# --- context ------------------------------------------------------------------


def _diff_block(project: Project, node: Node) -> str:
    """What the last edit to this statement actually changed.

    The whole reason :mod:`bp.history` exists. Without it the amender has to infer
    what moved by comparing the statement against the children, which is both more
    expensive and less accurate than being shown the two versions.
    """
    import difflib

    previous = history_mod.previous(project, node.id, STATEMENT)
    if previous is None:
        return (
            "## What changed\n\nNo earlier version of this statement was recorded, so "
            "the edit itself is not available — judge from the statement as it now "
            "reads against the children below."
        )
    current = node.statement_section
    if previous.strip() == current.strip():
        return ""
    diff = "\n".join(
        difflib.unified_diff(
            previous.splitlines(),
            current.splitlines(),
            fromfile="statement (before)",
            tofile="statement (now)",
            lineterm="",
        )
    )
    return (
        "## What changed\n\nThis is the most recent edit to the statement. Lines "
        "beginning `-` were removed, `+` added.\n\n"
        f"```diff\n{diff}\n```"
    )


def _child_block(graph: Graph, node: Node) -> str:
    lines = ["## The children, as they stand", ""]
    for cid in node.children:
        child = graph.get(cid)
        if child is None:
            lines.append(f"### `{cid}` — MISSING FROM THE PROJECT\n")
            continue
        proof = child.proof_section.strip()
        if len(proof) > CHILD_PROOF_CHARS:
            proof = proof[:CHILD_PROOF_CHARS].rstrip() + "\n\n[…truncated]"
        lines += [
            f"### `{cid}`",
            "",
            f"Role: {child.role}. Difficulty: {child.difficulty}. "
            f"Status: {child.global_status or '?'}. "
            + ("Has a proof." if proof else "NO PROOF WRITTEN."),
            "",
            "Hypotheses:",
            "\n".join(f"- {h.id}: {h.tex}" for h in child.hypotheses) or "(none)",
            "",
            "Statement:",
            "",
            child.statement_section.strip() or "(not written)",
            "",
            "Proof (for context — you may not change it):",
            "",
            proof or "(none written)",
            "",
        ]
    return "\n".join(lines).strip()


def build_prompt(
    project: Project, graph: Graph, node: Node, hint: str | None = None
) -> str:
    return context.join(
        context.preamble_block(project),
        context.setting(graph, node),
        context.node_block(node, heading="The node whose statement has been edited"),
        _diff_block(project, node),
        context.xref_block(graph, node),
        _child_block(graph, node),
        context.uses_block(node),
        context.siblings_available(graph, node),
        (
            "## The user's guidance\n\nThis is from the mathematician who made the "
            f"edit. Take it seriously.\n\n{hint.strip()}"
            if hint
            else ""
        ),
    )


# --- the role -----------------------------------------------------------------


@dataclass
class AmendReport:
    node: str
    proposal: Proposal | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)
    calls: list[CallMeta] = field(default_factory=list)
    rounds: int = 1
    path: Path | None = None

    @property
    def clean(self) -> bool:
        return not any(d.severity == "error" for d in self.diagnostics)

    @property
    def verdict(self) -> str:
        return self.proposal.verdict if self.proposal else "amend"

    @property
    def items(self) -> list[Item]:
        return self.proposal.items if self.proposal else []


def amend(
    project: Project,
    node_id: str,
    *,
    registry: Registry | None = None,
    hint: str | None = None,
    repair_rounds: int = 1,
) -> AmendReport:
    """Propose the minimal changes an edited parent implies. **Writes nothing.**

    The proposal is stored under ``.bp/amend/`` and applied — in whole or in part —
    by :func:`apply_amendment`.
    """
    registry = registry or Registry(project)
    agent = registry.agent(ROLE)
    timeout = registry.config.role(ROLE).timeout

    graph, load_diagnostics, swept = load_graph(project)
    if not swept:
        raise ops.OpError("the graph has a cycle; run `bp check` before amending")
    if any(d.severity == "error" for d in load_diagnostics):
        raise ops.OpError(
            "some node files could not be loaded, so the decomposition is not all "
            "here; run `bp check` and fix those first"
        )
    node = graph.get(node_id)
    if node is None:
        raise ops.OpError(f"no node {node_id!r}")
    if not node.children:
        raise ops.OpError(
            f"{node_id} has no children, so there is no decomposition to amend. "
            f"`bp expand {node_id}` makes one."
        )

    system = context.load_prompt("amend")
    user = build_prompt(project, graph, node, hint)
    report = AmendReport(node=node_id)
    amendment: Amendment | None = None
    diagnostics: list[Diagnostic] = []
    ids: dict[str, str] = {}

    for attempt in range(repair_rounds + 1):
        report.rounds = attempt + 1
        amendment, meta = agent.complete(system, user, Amendment, timeout)
        report.calls.append(meta)

        if not amendment.amending:
            # `no-change` and `redecompose` are answers, not failures, and neither
            # produces items to review.
            diagnostics = []
            break

        diagnostics = check_amendment(amendment, node, graph)
        ids = (
            assign_ids_for(graph, node, amendment.new_children)
            if amendment.new_children
            else {}
        )
        if not any(d.severity == "error" for d in diagnostics):
            candidate, parent = candidate_graph(graph, node, amendment, ids)
            diagnostics.extend(check_candidate(candidate, parent))
        if not any(d.severity == "error" for d in diagnostics):
            break
        if attempt == repair_rounds:
            break
        user = context.join(
            build_prompt(project, graph, node, hint),
            context.diagnostics_block(
                diagnostics, "Your previous amendment was rejected"
            ),
            "Return a corrected amendment. Every existing child needs exactly one "
            "verdict, and the `uses` table has to cover every hypothesis of every "
            "child the amended reduction cites — `ADMITTED: <reason>` where a source "
            "genuinely no longer exists, never a missing entry.",
        )

    assert amendment is not None
    report.diagnostics = diagnostics
    proposal = Proposal(
        node=node_id,
        proposed_at=_now(),
        verdict=amendment.verdict,
        assessment=amendment.assessment,
        notes=amendment.notes,
        amendment=amendment,
        ids=ids,
        items=items_for(amendment, node, graph, ids) if amendment.amending else [],
        fingerprint=fingerprint(node, graph),
        diagnostics=list(diagnostics),
        calls=len(report.calls),
    )
    report.proposal = proposal
    report.path = save_proposal(project, proposal)
    return report


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- applying -----------------------------------------------------------------


@dataclass
class ApplyResult:
    node: str
    applied: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    archived_to: Path | None = None
    edited: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    reduction: bool = False
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not any(d.severity == "error" for d in self.diagnostics)


def next_attempt_dir(project: Project, node_id: str) -> Path:
    n = 1
    while (project.attempts_dir / f"{node_id}-amend-{n}").exists():
        n += 1
    return project.attempts_dir / f"{node_id}-amend-{n}"


def apply_amendment(
    project: Project,
    node_id: str,
    accept: list[str] | None = None,
    *,
    actor: str = "amender",
) -> ApplyResult:
    """Apply the accepted items of the stored proposal, and nothing else.

    ``accept`` is a list of item keys; ``None`` means all of them. The subtree is
    copied to ``attempts/<node>-amend-<n>/`` before the first write, so an amendment
    is recoverable in the same way a ``redo`` is.

    Refuses a proposal that was made against text which has since moved: applying it
    would be applying a judgement about a different graph.
    """
    proposal = load_proposal(project, node_id)
    if proposal is None:
        raise ops.OpError(
            f"no amendment has been proposed for {node_id}; run `bp amend {node_id}`"
        )
    if proposal.verdict != "amend":
        raise ops.OpError(
            f"the amendment for {node_id} is `{proposal.verdict}`, so there is nothing "
            "to apply"
        )

    graph = ops.open_graph(project)
    node = graph.get(node_id)
    if node is None:
        raise ops.OpError(f"no node {node_id!r}")
    if not is_current(proposal, node, graph):
        raise ops.OpError(
            f"the amendment for {node_id} was proposed against text that has changed "
            "since. Run `bp amend` again — applying it now would apply a judgement "
            "about a different graph."
        )

    wanted = set(proposal.keys if accept is None else accept)
    unknown = sorted(wanted - set(proposal.keys))
    if unknown:
        raise ops.OpError(
            f"the proposal for {node_id} has no item(s) {', '.join(unknown)}; it has "
            + (", ".join(proposal.keys) or "none")
        )

    result = ApplyResult(
        node=node_id,
        applied=[k for k in proposal.keys if k in wanted],
        rejected=[k for k in proposal.keys if k not in wanted],
    )
    if not result.applied:
        result.diagnostics = _node_diagnostics(project, node_id)
        return result

    # Copy first. Nothing in this system destroys, and an amendment that turns out
    # to be wrong should cost the same as a redo that turns out to be wrong: nothing.
    result.archived_to = _archive_subtree(project, graph, node_id)

    amendment = proposal.amendment
    by_id = amendment.by_id()
    by_key = {i.key: i for i in proposal.items}

    dropped: list[str] = []
    for cid in list(node.children):
        entry = by_id.get(cid)
        if entry is None or f"child:{cid}" not in wanted:
            continue
        if entry.action == "edit":
            ops.edit_statement(project, cid, entry.statement.strip(), actor=actor)
            if entry.hypotheses:
                ops.set_hypotheses(
                    project, cid, [h.model_dump() for h in entry.hypotheses], actor=actor
                )
            result.edited.append(cid)
        elif entry.action == "drop":
            dropped.append(cid)

    for proposed in amendment.new_children:
        key = f"new:{proposed.slug}"
        if key not in wanted:
            continue
        new_id = proposal.ids.get(proposed.slug) or by_key[key].node
        ops.add_node(
            project,
            new_id,
            role=proposed.role,
            statement=proposed.statement,
            notes=proposed.notes,
            difficulty=proposed.difficulty,
            hypotheses=[h.model_dump() for h in proposed.hypotheses],
            actor=actor,
        )
        result.added.append(new_id)

    # The children list and the discharge table are rebuilt from what was actually
    # accepted, not from what was proposed. A rejected `drop` keeps its child *and*
    # its existing `uses` row — otherwise rejecting one item would manufacture a
    # `DIS010` the user did not cause.
    final = [c for c in node.children if c not in dropped] + result.added
    table = {
        cid: use.model_dump()
        for cid, use in resolve_uses(amendment, proposal.ids, set(final)).items()
    }
    for cid in final:
        if cid not in table and cid in node.uses:
            table[cid] = {
                "applied_to": node.uses[cid].applied_to,
                "discharges": dict(node.uses[cid].discharges),
            }

    if final != list(node.children):
        ops.set_children(project, node_id, final, actor=actor)
    ops.set_uses(project, node_id, table, actor=actor)

    if "reduction" in wanted and "reduction" in by_key:
        ops.edit_proof(project, node_id, by_key["reduction"].after, actor=actor)
        result.reduction = True

    # Archived last: `ops.archive` strips the now-dangling citation from the parent,
    # so doing it before `set_children` would fight with the list we just wrote.
    for cid in dropped:
        try:
            ops.archive(project, cid, actor=actor)
        except ops.OpError:
            continue
        result.dropped.append(cid)

    if amendment.notes.strip():
        ops.add_note(
            project, node_id, f"Amender's notes: {amendment.notes.strip()}", actor=actor
        )

    result.diagnostics = _node_diagnostics(project, node_id)
    return result


def _archive_subtree(project: Project, graph: Graph, node_id: str) -> Path:
    dest = next_attempt_dir(project, node_id)
    dest.mkdir(parents=True, exist_ok=True)
    for member_id in sorted({node_id} | graph.descendants(node_id)):
        member = graph.get(member_id)
        if member is not None and member.path is not None and member.path.exists():
            shutil.copy2(member.path, dest / member.path.name)
    return dest


def _node_diagnostics(project: Project, node_id: str) -> list[Diagnostic]:
    """What the deterministic checks say about the node after applying.

    The honest report on a partial acceptance: taking two of four changes can leave a
    hypothesis unsourced, and the user should be told which rather than discovering it
    at the next `bp check`.
    """
    from .. import checks as checks_mod

    graph, _, swept = load_graph(project)
    if not swept or node_id not in graph.active:
        return []
    node = graph[node_id]
    out: list[Diagnostic] = []
    for family in checks_mod.for_node(graph, node).values():
        out.extend(family)
    # `for_node` feeds the verification record, so the DEC family is not in it. It is
    # exactly what the user wants to see here: after amending, is the decomposition
    # check current again? (It is not — the children moved.)
    out.extend(checks_mod.decomposition_checked(node, graph))
    return [d for d in out if d.severity != "info"]


# --- reporting ----------------------------------------------------------------


def summarise(report: AmendReport) -> str:
    proposal = report.proposal
    if proposal is None:
        return "nothing proposed"
    lines = [f"{report.node}: {proposal.verdict}", f"  {proposal.assessment}"]
    if proposal.verdict == "no-change":
        lines.append("  The decomposition still fits. Nothing to apply.")
    elif proposal.verdict == "redecompose":
        lines.append(
            f"  The amender declined to patch this. `bp redo {report.node}` archives "
            "the subtree and decomposes again."
        )
    for item in proposal.items:
        lines.append(f"  [{item.key}] {item.kind}: {item.why or '(no reason given)'}")
    kept = [
        c.id for c in proposal.amendment.children if c.action == "keep"
    ]
    if kept:
        lines.append(f"  unchanged: {', '.join(kept)}")
    errors = [d for d in proposal.diagnostics if d.severity == "error"]
    if errors:
        lines.append(f"  {len(errors)} unresolved problem(s) after repair:")
        for d in errors:
            lines.append(f"    {d.code}: {d.message}")
    if proposal.notes.strip():
        lines.append(f"  notes: {proposal.notes.strip()}")
    if proposal.items:
        lines.append(
            f"  nothing has been written. `bp amend {report.node} --apply` applies "
            "these; `--only <key>` applies some."
        )
    return "\n".join(lines)


def summarise_apply(result: ApplyResult) -> str:
    lines = [f"{result.node}: applied {len(result.applied)} of "
             f"{len(result.applied) + len(result.rejected)} item(s)"]
    if result.archived_to:
        lines.append(f"  subtree copied to {result.archived_to}")
    for label, ids in (
        ("edited", result.edited),
        ("archived", result.dropped),
        ("added", result.added),
    ):
        if ids:
            lines.append(f"  {label}: {', '.join(ids)}")
    if result.reduction:
        lines.append("  the reduction proof was replaced")
    if result.rejected:
        lines.append(f"  rejected: {', '.join(result.rejected)}")
    errors = [d for d in result.diagnostics if d.severity == "error"]
    if errors:
        lines.append(f"  {len(errors)} error(s) now:")
        for d in errors:
            lines.append(f"    {d.code}: {d.message}")
    lines.append(
        "  every edited child's verification is invalidated, which is correct — "
        "re-verify them."
    )
    return "\n".join(lines)


__all__ = [
    "Amendment",
    "AmendReport",
    "ApplyResult",
    "ChildAmendment",
    "Item",
    "Proposal",
    "ProposalUnreadable",
    "ROLE",
    "amend",
    "apply_amendment",
    "check_amendment",
    "fingerprint",
    "is_current",
    "items_for",
    "load_proposal",
    "proposal_path",
    "save_proposal",
    "summarise",
    "summarise_apply",
]
