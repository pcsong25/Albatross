"""The exposition: the deterministic half of the readable paper.

The node-by-node document (:mod:`bp.render`) is the one that must never be
maintained by an agent, and it is not: it is regenerated from the node files every
time. But it reads like what it is — a dependency order of numbered nodes, each
with its hypotheses listed as ``(H1); (H2)`` and each cross-reference written as a
node id. That is exactly right for checking a development and wrong for reading
one. Nobody writes a paper that way.

So there is a second artifact, and this module owns everything about it that is
not a judgement:

*It is separate.* ``document.tex`` is unchanged and stays the source of truth. The
paper is built only when asked, kept under ``.bp/paper/``, and never regenerated
behind the user's back — the moment a node changes it is out of date, which is
why the draft stores the hashes it was written from and :func:`changes` says what
has moved since.

*It carries its own provenance.* An exposition can lose things: a lemma folded
into a proof, a hypothesis restated in words, an admitted step written as a
standing assumption. Those losses are recoverable only if the document says where
every node went, so the assembled paper always contains a code-generated note
under the title and an appendix mapping every active node to the section that
covers it. Neither is writable by an agent, and both survive whatever the prose
says.

*Every node is accounted for.* The outline assigns nodes to sections and each
section declares which of its nodes it stated and which it merged into prose.
Code enumerates the active graph and compares. A node the exposition silently
dropped is a ``PAP`` diagnostic, not a surprise the reader finds by noticing an
argument does not close.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from . import hash as hash_mod
from . import render
from .diagnostics import Diagnostic, err, warn
from .graph import Graph
from .load import atomic_write
from .paths import Project
from .propagate import OPEN, PROVED, PROVED_MODULO, UNSOUND
from .why import explain

#: Prefix for the LaTeX label the exposition puts on each node it states. Every
#: reference between sections goes through it — ``Lemma~\ref{paper:gclm.elb}`` —
#: which is what lets the prose name a lemma by number instead of by node id while
#: still being checkable: the label namespace is enumerable, so a reference to a
#: node that is not in the paper is a diagnostic rather than a ``??`` in the PDF.
LABEL_PREFIX = "paper:"

#: How the writer is asked to reference another node's statement, and therefore
#: what this module looks for when checking that those references resolve.
_REF_RE = re.compile(
    r"\\(?:ref|eqref|autoref|Cref|cref|pageref)\*?\{" + re.escape(LABEL_PREFIX) + r"([^}]*)\}"
)

DRAFT_NAME = "paper.json"
#: Bumped when a stored draft's shape changes. An older draft is not upgraded — it
#: is reported as unreadable and rebuilt, because a paper is one model call away and
#: a migration path for a build artifact is a liability nobody asked for.
DRAFT_VERSION = 1


def label_for(node_id: str) -> str:
    return LABEL_PREFIX + node_id


def section_label(index: int) -> str:
    """The label on the *n*-th section, so the appendix can point at it."""
    return f"{LABEL_PREFIX}sec{index}"


def references(text: str) -> list[str]:
    """Node ids this passage cross-references, in order of appearance."""
    return [m.group(1).strip() for m in _REF_RE.finditer(text)]


def has_label(text: str, node_id: str) -> bool:
    return f"\\label{{{label_for(node_id)}}}" in text


# --- the stored draft ---------------------------------------------------------


class Merge(BaseModel):
    """A node the exposition folded into prose rather than stating on its own.

    This is the readability win — a routine lemma belongs inside the proof that
    uses it, not as Lemma 7 — and it is also the thing most likely to lose
    something, so it is recorded per node with the writer's own account of where
    it went.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    where: str = ""


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading: str
    purpose: str = ""
    #: Nodes the outline assigned to this section. The enumeration everything else
    #: here is checked against.
    nodes: list[str] = Field(default_factory=list)
    tex: str = ""
    stated: list[str] = Field(default_factory=list)
    merged: list[Merge] = Field(default_factory=list)
    #: Where the exposition knowingly differs from the development.
    departures: list[str] = Field(default_factory=list)
    #: What it could not carry over faithfully. The honest answer to "this
    #: translation may lose accuracy" is a list, not a disclaimer.
    lost: list[str] = Field(default_factory=list)
    #: Set when the section has no text: the call failed, or the budget ran out.
    #: An empty section that says nothing would read as a section with nothing in
    #: it, so the assembled document prints this instead.
    failed: str = ""

    @property
    def accounted(self) -> set[str]:
        return set(self.stated) | {m.id for m in self.merged}


class Draft(BaseModel):
    """One built exposition, as stored. Rendering it makes no model call."""

    model_config = ConfigDict(extra="forbid")

    version: int = DRAFT_VERSION
    title: str
    abstract: str = ""
    built_at: str = ""
    target: str | None = None
    #: node id -> statement/proof digest at the time of writing. What makes
    #: "this paper is older than your development" answerable.
    fingerprint: dict[str, str] = Field(default_factory=dict)
    sections: list[Section] = Field(default_factory=list)
    #: Active nodes the outline never placed. They are named in the appendix as
    #: not included rather than quietly missing.
    unplaced: list[str] = Field(default_factory=list)
    #: The writer's own reservations about the exposition.
    notes: str = ""
    calls: int = 0
    cost_usd: float | None = None
    #: Diagnostics as found at build time, kept so the sheet can show them without
    #: re-deriving against a graph that may since have moved.
    diagnostics: list[Diagnostic] = Field(default_factory=list)

    @property
    def failed_sections(self) -> list[Section]:
        return [s for s in self.sections if s.failed]

    def placement(self) -> dict[str, tuple[int, str, str]]:
        """node id -> (section index, ``stated``/``merged``, where).

        The appendix is built from this, and so is the answer to the only question
        a reader of the paper can ask that the paper itself cannot answer: which
        node of the development is this passage?
        """
        out: dict[str, tuple[int, str, str]] = {}
        for i, section in enumerate(self.sections):
            for node_id in section.stated:
                out.setdefault(node_id, (i, "stated", ""))
            for merge in section.merged:
                out.setdefault(merge.id, (i, "merged", merge.where))
        return out


# --- persistence --------------------------------------------------------------


def draft_path(project: Project) -> Path:
    return project.paper_dir / DRAFT_NAME


def save(project: Project, draft: Draft) -> Path:
    path = draft_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, json.dumps(draft.model_dump(), indent=2, ensure_ascii=False) + "\n")
    return path


class DraftUnreadable(Exception):
    """A stored draft that cannot be loaded. Rebuild rather than migrate."""


def load(project: Project) -> Draft | None:
    """The stored draft, or None if this project has never built a paper."""
    path = draft_path(project)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DraftUnreadable(f"{path} could not be read: {exc}") from exc
    if data.get("version") != DRAFT_VERSION:
        raise DraftUnreadable(
            f"{path} was written by an older version of this tool "
            f"(draft version {data.get('version')!r}, this one writes {DRAFT_VERSION}). "
            "Build the paper again; nothing else is affected."
        )
    try:
        return Draft.model_validate(data)
    except Exception as exc:  # noqa: BLE001 - the message is the product
        raise DraftUnreadable(f"{path} is not a draft this version understands: {exc}") from exc


# --- staleness ----------------------------------------------------------------


def fingerprint(graph: Graph) -> dict[str, str]:
    """What every active node says, digested.

    Statement *and* proof: the exposition reproduces both, so a proof edit
    invalidates the paper exactly as a statement edit does. Computed rather than
    read from the frontmatter, so it is right even for a node whose stored hash
    has not been swept yet.
    """
    return {
        node.id: f"{hash_mod.statement_hash(node)}/{hash_mod.proof_hash(node)}"
        for node in graph.active.values()
    }


@dataclass
class Changes:
    """What has moved in the development since the paper was written."""

    changed: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def stale(self) -> bool:
        return bool(self.changed or self.added or self.removed)

    def sentence(self) -> str:
        if not self.stale:
            return "current with the development"
        bits = []
        if self.changed:
            bits.append(f"{len(self.changed)} node(s) edited")
        if self.added:
            bits.append(f"{len(self.added)} added")
        if self.removed:
            bits.append(f"{len(self.removed)} archived or removed")
        return "written before " + ", ".join(bits)


def changes(draft: Draft, graph: Graph) -> Changes:
    now = fingerprint(graph)
    then = draft.fingerprint
    return Changes(
        changed=sorted(k for k in then if k in now and now[k] != then[k]),
        added=sorted(k for k in now if k not in then),
        removed=sorted(k for k in then if k not in now),
    )


# --- the completeness checks --------------------------------------------------


def check_outline(assigned: dict[str, list[str]], graph: Graph) -> list[Diagnostic]:
    """``PAP001``–``PAP002``: does the outline place every node, exactly once?

    ``assigned`` maps section heading to the node ids it claims. This is the whole
    mechanism of this role: an outline is a judgement, and the only thing code can
    guarantee about it is that it left nothing out. A paper missing a lemma is not
    a formatting problem — the argument it belongs to no longer closes, and nothing
    downstream would notice.
    """
    out: list[Diagnostic] = []
    active = set(graph.active)
    seen: dict[str, str] = {}
    for heading, ids in assigned.items():
        for node_id in ids:
            if node_id not in active:
                out.append(
                    warn(
                        "PAP002",
                        node_id,
                        f"the outline puts {node_id} in section {heading!r}, but there "
                        "is no such active node",
                        hint="it may have been archived since. It is ignored.",
                    )
                )
                continue
            if node_id in seen:
                out.append(
                    warn(
                        "PAP002",
                        node_id,
                        f"{node_id} is assigned to two sections ({seen[node_id]!r} and "
                        f"{heading!r}); the first one keeps it",
                    )
                )
                continue
            seen[node_id] = heading
    missing = sorted(active - set(seen))
    if missing:
        out.append(
            err(
                "PAP001",
                None,
                f"the outline places {len(seen)} of {len(active)} nodes; it leaves out "
                + ", ".join(missing),
                hint="every node of the development has to go somewhere, even if only "
                "as a remark inside another proof. Unplaced nodes are listed in the "
                "paper's provenance appendix as not included.",
            )
        )
    return out


def check_section(section: Section, graph: Graph) -> list[Diagnostic]:
    """``PAP003``–``PAP006`` plus the LaTeX checks, over one written section."""
    from . import checks as checks_mod

    out: list[Diagnostic] = []
    where = f"section {section.heading!r}"
    if section.failed:
        out.append(
            err(
                "PAP006",
                None,
                f"{where} was not written: {section.failed}",
                hint="the paper says so in place of the section. Nothing is missing "
                "from the development; only this exposition of it is incomplete.",
            )
        )
        return out

    assigned = set(section.nodes)
    unaccounted = sorted(assigned - section.accounted)
    if unaccounted:
        out.append(
            err(
                "PAP003",
                None,
                f"{where} was given {len(assigned)} node(s) and accounts for "
                f"{len(section.accounted)}; it says nothing about "
                + ", ".join(unaccounted),
                hint="a node is either stated in the section — with its "
                f"`\\label{{{LABEL_PREFIX}<id>}}` — or declared as merged into some "
                "other passage. Silence is the one answer that is not allowed.",
            )
        )
    for node_id in section.stated:
        if not has_label(section.tex, node_id):
            out.append(
                err(
                    "PAP004",
                    node_id,
                    f"{where} says it states {node_id}, but the text has no "
                    f"`\\label{{{label_for(node_id)}}}`",
                    hint="without the label nothing else in the paper can reference "
                    "it by number, and this module cannot tell where it went.",
                )
            )
    for target in references(section.tex):
        if target not in graph.active:
            out.append(
                warn(
                    "PAP005",
                    target,
                    f"{where} references `{label_for(target)}`, which is not a node in "
                    "the project",
                    hint="LaTeX would print `??` for it. Either the id is wrong or the "
                    "reference is to something the exposition never stated.",
                )
            )
    out.extend(checks_mod.latex_fragment(section.tex, where))
    return out


def check(draft: Draft, graph: Graph) -> list[Diagnostic]:
    """Everything deterministic that can be said about a built paper."""
    out = check_outline({s.heading: s.nodes for s in draft.sections}, graph)
    for section in draft.sections:
        out.extend(check_section(section, graph))
    return out


# --- the provenance apparatus -------------------------------------------------


def _link(node_id: str) -> str:
    return f"\\texttt{{{render.escape(node_id)}}}"


def provenance_note(draft: Draft, graph: Graph) -> str:
    """The sentence under the title, written by code and by nothing else.

    A reader who does not know that the ordering, the wording and the choice of
    what to merge came from a language model cannot calibrate what they are
    reading. This says so, in one paragraph, in every built paper.
    """
    n = len(draft.fingerprint)
    parts = [
        "\\textit{Provenance.} The mathematics in this document comes from a "
        f"machine-checked proof development of {n} node"
        f"{'s' if n != 1 else ''}. The exposition does not: an agent chose the "
        "ordering, the wording, which lemmas to state and which to fold into the "
        "proofs that use them. It may therefore have lost detail the development "
        "carries. Appendix~\\ref{sec:bp-provenance} says where every node went, and "
        "the development itself remains the authority.",
    ]
    if draft.failed_sections:
        parts.append(
            f"\\textbf{{{len(draft.failed_sections)} section"
            f"{'s' if len(draft.failed_sections) != 1 else ''} could not be written}} "
            "and say so in place of their text."
        )
    return " ".join(parts)


#: How many node ids the standing note lists before it stops naming them. A
#: development with sixty unfinished leaves would otherwise put a page of
#: identifiers under the title, and a note nobody reads is a note that is not there.
MAX_NAMED = 8


def _named(ids: list[str]) -> str:
    shown = [_link(i) for i in ids[:MAX_NAMED]]
    if len(ids) > MAX_NAMED:
        shown.append(f"and {len(ids) - MAX_NAMED} more")
    return ", ".join(shown)


def standing_items(graph: Graph) -> list[str]:
    """What the development says its own result rests on, as list items.

    Generated from the graph, never from the draft: the one thing an exposition must
    not be able to do is upgrade a conditional theorem to an unconditional one by
    writing more confident prose. Three claims, in order of what a reader needs —
    what the target's status is, what is stated here without proof, and how much of
    the rest nobody has checked.
    """
    items: list[str] = []
    target = graph.target
    if target is None:
        items.append(
            "No node of the development is marked as the target, so it states no "
            "overall result."
        )
    elif target.global_status == PROVED:
        items.append(
            f"The development records {_link(target.id)} as proved: it rests on no "
            "admitted step, no assumption and no unfinished lemma."
        )
    elif target.global_status == PROVED_MODULO:
        items.append(
            f"The development records {_link(target.id)} as holding "
            f"\\emph{{relative to}} {len(target.support)} item(s) it does not prove: "
            + _named(list(target.support))
            + "."
        )
    else:
        exp = explain(graph, target.id)
        # `resolve_refs` with nothing known: the explanation names nodes in
        # backticks, and a backtick pair in LaTeX is a quotation mark. An empty
        # `known` set turns each id into plain \texttt rather than a \hyperref at a
        # label this document does not contain — the paper has no `node:` anchors.
        items.append(
            f"The development does \\emph{{not}} record {_link(target.id)} as proved. "
            + render.resolve_refs(render.prose(exp.sentence), set())
        )

    # Every admitted or assumed node, wherever it sits. Not only the ones the target
    # happens to rest on: a reader of this document meets all of them, and each one
    # is a statement the development is taking on trust.
    for node in sorted(graph.active.values(), key=lambda n: n.id):
        if node.local_status not in {"admitted", "assumption"}:
            continue
        label = "assumption" if node.local_status == "assumption" else "admitted"
        reason = render.prose(node.status_reason) if node.status_reason else ""
        items.append(
            f"{_link(node.id)} is stated here without proof ({label})"
            + (f": {reason}" if reason else "")
            + "."
        )

    unfinished = sorted(
        n.id
        for n in graph.active.values()
        if (n.global_status or "").startswith("blocked")
        or n.global_status in {OPEN, UNSOUND}
    )
    if unfinished:
        items.append(
            f"{len(unfinished)} statement(s) in the development have no verified "
            "proof: " + _named(unfinished) + "."
        )
    return items


def counts_line(graph: Graph) -> str:
    counts: dict[str, int] = {}
    for node in graph.active.values():
        counts[node.global_status or "?"] = counts.get(node.global_status or "?", 0) + 1
    return "Development status: " + ", ".join(
        f"{v} {render.escape(k)}" for k, v in sorted(counts.items())
    ) + "."


def provenance_rows(draft: Draft, graph: Graph) -> list[str]:
    """One line per node of the development, saying where it ended up."""
    placement = draft.placement()
    rows: list[str] = []
    for node_id in sorted(set(draft.fingerprint) | set(graph.active)):
        node = graph.get(node_id)
        status = render.escape(node.global_status or "?") if node else "no longer in the project"
        entry = placement.get(node_id)
        if entry is None:
            where = "\\textbf{not included in this exposition}"
        else:
            index, how, note = entry
            section = draft.sections[index]
            head = render.prose(section.heading)
            if how == "stated":
                where = (
                    f"stated in \\S\\ref{{{section_label(index)}}} ({head}), "
                    f"as~\\ref{{{label_for(node_id)}}}"
                )
            else:
                where = f"merged into {head}" + (f" --- {render.prose(note)}" if note else "")
        rows.append(f"{_link(node_id)} ({status}): {where}")
    return rows


def _departure_rows(draft: Draft) -> list[str]:
    rows: list[str] = []
    for section in draft.sections:
        for text in section.departures:
            rows.append(f"{render.prose(section.heading)}: {render.prose(text)}")
        for text in section.lost:
            rows.append(
                f"{render.prose(section.heading)} --- \\textbf{{not carried over}}: "
                + render.prose(text)
            )
    return rows


# --- assembly -----------------------------------------------------------------


def document(
    draft: Draft,
    graph: Graph,
    *,
    preamble: str = "",
    apparatus: bool = True,
    today: str | None = None,
) -> str:
    """The paper, as LaTeX.

    Deterministic and free: it makes no model call, so a draft can be re-rendered,
    re-compiled and re-downloaded as often as the user likes.

    ``apparatus=False`` drops the provenance note and the appendix, for a file that
    is going to a journal rather than to the author. It is opt-out rather than
    default because the note is the only thing in the document that a reader can
    use to calibrate it.
    """
    sections = []
    for i, section in enumerate(draft.sections):
        nodes_line = ""
        if section.failed and section.nodes:
            nodes_line = "It would have covered " + ", ".join(
                _link(n) for n in section.nodes
            ) + ", which remain in the development."
        sections.append(
            {
                # The heading is the writer's prose, so it passes through; only a
                # stray comment mark is defused.
                "heading": render.prose(section.heading),
                "label": section_label(i),
                "tex": render.prose(section.tex),
                "failed": render.prose(section.failed),
                "nodes_line": nodes_line,
            }
        )

    rows = provenance_rows(draft, graph) if apparatus else []
    departures = _departure_rows(draft) if apparatus else []
    if apparatus and draft.unplaced:
        departures.append(
            "\\textbf{Never placed by the outline, and therefore absent from this "
            "document:} " + ", ".join(_link(n) for n in draft.unplaced) + "."
        )

    template = render.template_env().get_template("paper.tex.j2")
    return template.render(
        title=render.prose(draft.title),
        date=today or date.today().isoformat(),
        preamble=preamble.strip(),
        # The status macros are no-ops in a paper: nothing here is tagged in the
        # margin. The apparatus this document carries is prose, not colour.
        clean=True,
        abstract=render.prose(draft.abstract),
        provenance_note=provenance_note(draft, graph) if apparatus else "",
        standing_items=standing_items(graph) if apparatus else [],
        counts=counts_line(graph) if apparatus else "",
        sections=sections,
        provenance_intro=(
            "Every node of the proof development, and where it appears above. The "
            "development is the authority: where this document and a node disagree, "
            "the node is right."
        )
        if rows
        else "",
        provenance_rows=rows,
        departure_rows=departures,
    )


# --- reporting ----------------------------------------------------------------


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def describe(draft: Draft, graph: Graph) -> str:
    """The paper, in the terminal."""
    delta = changes(draft, graph)
    lines = [
        f"{draft.title!r}",
        f"  built {draft.built_at} from {len(draft.fingerprint)} node(s), "
        f"{draft.calls} call(s)"
        + (f", ${draft.cost_usd:.2f}" if draft.cost_usd else ""),
        f"  {delta.sentence()}",
        "",
    ]
    placement = draft.placement()
    for i, section in enumerate(draft.sections, start=1):
        if section.failed:
            lines.append(f"  {i}. {section.heading} — NOT WRITTEN: {section.failed}")
            continue
        stated = len(section.stated)
        merged = len(section.merged)
        lines.append(
            f"  {i}. {section.heading} — {stated} stated, {merged} merged, "
            f"{len(section.tex.split())} words"
        )
        for text in section.lost:
            lines.append(f"       not carried over: {text}")
    missing = sorted(set(graph.active) - set(placement))
    if missing:
        lines += ["", "  not included: " + ", ".join(missing)]
    if delta.stale:
        lines += [
            "",
            "  the development has moved since this was written:",
        ]
        for group, ids in (
            ("edited", delta.changed),
            ("added", delta.added),
            ("gone", delta.removed),
        ):
            if ids:
                lines.append(f"    {group}: {', '.join(ids)}")
    return "\n".join(lines)


__all__ = [
    "Changes",
    "Draft",
    "DraftUnreadable",
    "DRAFT_VERSION",
    "LABEL_PREFIX",
    "Merge",
    "Section",
    "changes",
    "check",
    "check_outline",
    "check_section",
    "describe",
    "document",
    "draft_path",
    "fingerprint",
    "has_label",
    "label_for",
    "load",
    "now",
    "references",
    "save",
]
