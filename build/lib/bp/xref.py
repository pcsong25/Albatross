"""Cross-references between nodes: the label index, and the checks it earns.

The renderer already puts every node into **one** LaTeX document, so a `\\label`
written in one node and an `\\eqref` written in another already resolve — LaTeX's
two passes see the whole thing at once. What was missing is everything that makes
that trustworthy:

* a `\\ref` to a label nothing defines is only a LaTeX **warning**. The build
  succeeds and the PDF prints `??`;
* a `\\label` defined twice is only a warning too. One silently wins, so a
  reference can resolve to *the wrong equation* with nothing said;
* the browser cannot resolve references at all — KaTeX renders `\\eqref{eq:main}`
  as the literal garbage `\\eqrefeq:m`;
* and a reference *across* nodes is a real dependency that the graph did not know
  about, so it was invisible to every check that reasons about dependencies.

This module is the missing half. It is a **derived index**, in exactly the sense
that :class:`bp.graph.Graph` is: recomputed from the node files on every load,
stored nowhere. That is deliberate, and it is the answer to the reasonable-sounding
suggestion of keeping a live unified ``.tex`` file — a stateful document would drift
from the graph, and the document is what the user reads.

The scope rule is the part worth reading twice. A reference is not merely a piece of
typesetting; it is a claim that one node's text depends on another's. The system's
whole model is that a child is verifiable **independently** — the verifier is handed
the children's statements as assumptions with no parent context at all — so a child
whose *statement* points at its parent's equation is not the self-contained lemma
the graph says it is. :func:`check_xref` says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .diagnostics import Diagnostic, err, warn
from .model import PROOF, STATEMENT, Node

#: ``\label{...}``. Anything else that defines a target — ``\tag`` does not, and
#: hyperref anchors are generated — is out of scope on purpose.
LABEL_RE = re.compile(r"\\label\s*\{([^}]*)\}")

#: The referencing commands worth understanding. ``cref``/``Cref`` come from
#: ``cleveref``, which a minimal TeX install does not ship — the check still reads
#: them, because a reference is a dependency whether or not the package is present.
REF_COMMANDS = (
    "ref",
    "eqref",
    "cref",
    "Cref",
    "cpageref",
    "autoref",
    "nameref",
    "pageref",
    "vref",
)
REF_RE = re.compile(
    r"\\(" + "|".join(REF_COMMANDS) + r")\s*\{([^}]*)\}"
)

#: A LaTeX comment runs to end of line, so a label inside one defines nothing and a
#: reference inside one references nothing. Stripping them first is what stops the
#: checks firing on text the author has already commented out.
_COMMENT_RE = re.compile(r"(?<!\\)%.*$", re.M)


def _live(text: str) -> str:
    return _COMMENT_RE.sub("", text)


@dataclass(frozen=True)
class Label:
    """One ``\\label`` and where it lives."""

    name: str
    node: str
    #: ``Statement`` or ``Proof``. The distinction is load-bearing: see ``XRF004``.
    section: str


@dataclass(frozen=True)
class Ref:
    """One reference, and where it was written."""

    name: str
    node: str
    section: str
    command: str


def labels_in(node: Node) -> list[Label]:
    out: list[Label] = []
    for section in (STATEMENT, PROOF):
        for m in LABEL_RE.finditer(_live(node.section(section))):
            name = m.group(1).strip()
            if name:
                out.append(Label(name=name, node=node.id, section=section))
    return out


def refs_in(node: Node) -> list[Ref]:
    out: list[Ref] = []
    for section in (STATEMENT, PROOF):
        for m in REF_RE.finditer(_live(node.section(section))):
            for name in m.group(2).split(","):
                name = name.strip()
                if name:
                    out.append(
                        Ref(
                            name=name,
                            node=node.id,
                            section=section,
                            command=m.group(1),
                        )
                    )
    return out


@dataclass
class Index:
    """Every label and reference in the active graph.

    Built by :func:`build`, thrown away with the graph. ``by_name`` maps a label to
    every node defining it — a list rather than a single node, because the duplicate
    case is exactly what ``XRF002`` reports.
    """

    labels: list[Label] = field(default_factory=list)
    refs: list[Ref] = field(default_factory=list)

    @property
    def by_name(self) -> dict[str, list[Label]]:
        out: dict[str, list[Label]] = {}
        for label in self.labels:
            out.setdefault(label.name, []).append(label)
        return out

    def define(self, name: str) -> Label | None:
        """The single definition of ``name``, or None if absent or ambiguous."""
        found = self.by_name.get(name) or []
        return found[0] if len(found) == 1 else None

    def refs_to(self, name: str) -> list[Ref]:
        return [r for r in self.refs if r.name == name]

    def edges(self) -> set[tuple[str, str]]:
        """``(referencing node, defining node)`` for every cross-node reference.

        A reference is a dependency the ``children`` relation does not record. This
        is what lets the checks reason about it.
        """
        out: set[tuple[str, str]] = set()
        for ref in self.refs:
            label = self.define(ref.name)
            if label is not None and label.node != ref.node:
                out.add((ref.node, label.node))
        return out


def build(graph) -> Index:
    index = Index()
    for node in graph.active.values():
        index.labels.extend(labels_in(node))
        index.refs.extend(refs_in(node))
    return index


def index_for(graph) -> Index:
    """:func:`build`, memoised on the graph object.

    The propagation sweep asks about staleness once per node, so building the index
    per call would make the sweep quadratic in the number of nodes. A ``Graph`` is
    rebuilt from the files on every load, so caching on it is caching for exactly as
    long as the answer is valid.
    """
    cached = getattr(graph, "_xref_index", None)
    if cached is None:
        cached = build(graph)
        try:
            graph._xref_index = cached
        except AttributeError:  # pragma: no cover - a graph that forbids attributes
            pass
    return cached


# --- the checks ---------------------------------------------------------------


def in_scope(graph, node_id: str) -> set[str]:
    """The nodes whose labels ``node_id`` may legitimately reference.

    Itself, plus every node it cites, transitively. *Not* its ancestors: a lemma
    whose text depends on the argument that uses it is not a lemma the verifier can
    read on its own, and the verifier is given exactly its cited children and
    nothing else.
    """
    return {node_id} | graph.descendants(node_id)


def check_xref(graph, index: Index | None = None) -> list[Diagnostic]:
    """``XRF001``–``XRF005`` over the whole graph.

    Whole-graph rather than per-node, because a reference and its label live in
    different files and neither node alone can tell whether the pair is sound.
    """
    index = index if index is not None else build(graph)
    d: list[Diagnostic] = []
    by_name = index.by_name

    for name, defs in sorted(by_name.items()):
        if len(defs) > 1:
            where = ", ".join(f"{x.node} ({x.section.lower()})" for x in defs)
            d.append(
                err(
                    "XRF002",
                    graph.get(defs[0].node),
                    f"`\\label{{{name}}}` is defined in more than one place: {where}",
                    hint="LaTeX only warns about this and then lets one of them win "
                    "silently, so a reference to it may point at the wrong equation. "
                    "Labels are global to the whole document — prefix them with the "
                    "node id, as in `\\label{" + defs[0].node + ":" + name + "}`.",
                )
            )

    for ref in index.refs:
        node = graph.get(ref.node)
        defs = by_name.get(ref.name) or []
        if not defs:
            d.append(
                err(
                    "XRF001",
                    node,
                    f"`\\{ref.command}{{{ref.name}}}` in the {ref.section.lower()} "
                    "refers to a label no node defines",
                    hint="LaTeX only warns about this: the document still builds and "
                    "prints `??` where the number should be. Either add "
                    f"`\\label{{{ref.name}}}` to the thing being referenced, or — if "
                    "this was written by an agent citing something that does not "
                    "exist — delete the reference and say what was meant.",
                )
            )
            continue

        label = defs[0]
        if label.node == ref.node:
            continue

        # XRF003 and XRF004 are **warnings**, and the reason is the severity rule
        # this codebase runs on: an error is for something silently *wrong*, a
        # warning for something legal that is almost always a mistake. A reference
        # like these resolves correctly and prints the right number — what is wrong
        # with it is the structure, and a check that blocked on structure would be
        # overruled by habit until nobody read this family at all.
        scope = in_scope(graph, ref.node)
        if label.node not in scope:
            if label.node in graph.ancestors(ref.node):
                d.append(
                    warn(
                        "XRF003",
                        node,
                        f"`\\{ref.command}{{{ref.name}}}` points at `{label.node}`, "
                        "which is a node that cites this one",
                        hint="this resolves and prints the right number, but two "
                        "things follow. The document reads dependencies-first, so the "
                        "reference points *forward* to something the reader has not "
                        "met. And the verifier reads this node with its own children "
                        "as assumptions and no parent context, so it will not know "
                        "what the reference means. The fix that removes both: move "
                        "the shared display or definition into its own node — a "
                        "`definition` reads well — and cite that node from both.",
                    )
                )
            else:
                d.append(
                    warn(
                        "XRF003",
                        node,
                        f"`\\{ref.command}{{{ref.name}}}` points at `{label.node}`, "
                        "which this node does not cite",
                        hint="the reference is a real dependency that the `children` "
                        "relation does not record, so nothing else in the system knows "
                        f"about it. Either add `{label.node}` to this node's "
                        "`children` (and give it a `uses` row), or move the "
                        "referenced material into a node both of them cite.",
                    )
                )
        elif label.section == PROOF:
            d.append(
                warn(
                    "XRF004",
                    node,
                    f"`\\{ref.command}{{{ref.name}}}` points inside the *proof* of "
                    f"`{label.node}`",
                    hint="a node's proof is private: what a citer may rely on is its "
                    "statement, and the verifier is only ever handed statements as "
                    "assumptions. Referencing another node's proof couples the two, so "
                    "rewriting that proof silently breaks this reference and nothing "
                    "reports it. Promote the step you need into a statement — its own "
                    f"node, or a display in `{label.node}`'s statement.",
                )
            )

    for label in index.labels:
        if not index.refs_to(label.name):
            d.append(
                warn(
                    "XRF005",
                    graph.get(label.node),
                    f"`\\label{{{label.name}}}` is never referenced",
                    hint="harmless, but it is usually either a leftover or a "
                    "reference somebody meant to write and did not",
                )
            )
    return d


def summarise(index: Index, graph) -> str:
    """A human listing, for ``bp labels``."""
    by_name = index.by_name
    if not by_name and not index.refs:
        return (
            "no \\label or \\ref anywhere in this project.\n\n"
            "Cross-references work: every node is rendered into one document, so a "
            "label written in one node resolves from another. What makes them safe "
            "is that a dangling or duplicated one is a hard error here (XRF001, "
            "XRF002) rather than a LaTeX warning nobody reads."
        )
    lines = [f"{len(by_name)} label(s), {len(index.refs)} reference(s):", ""]
    for name in sorted(by_name):
        defs = by_name[name]
        where = ", ".join(f"{x.node}/{x.section.lower()}" for x in defs)
        marker = "  DUPLICATE" if len(defs) > 1 else ""
        refs = index.refs_to(name)
        lines.append(f"  {name:<28} defined in {where}{marker}")
        for ref in refs:
            cross = "" if ref.node == defs[0].node else "  (cross-node)"
            lines.append(f"  {'':<28}   \\{ref.command} from {ref.node}{cross}")
        if not refs:
            lines.append(f"  {'':<28}   never referenced")

    dangling = sorted({r.name for r in index.refs if r.name not in by_name})
    if dangling:
        lines.append("")
        lines.append("referenced but never defined — these print ?? in the PDF:")
        for name in dangling:
            who = ", ".join(sorted({r.node for r in index.refs_to(name)}))
            lines.append(f"  {name:<28} referenced from {who}")
    return "\n".join(lines)


# --- resolved numbers, read back from LaTeX ------------------------------------

#: ``\newlabel{eq:main}{{1}{1}{\texttt {t}}{equation.1}{}}`` — the first braced
#: group after the name is the printed number, the second is the page.
_NEWLABEL_RE = re.compile(r"\\newlabel\{([^}]*)\}\{\{([^{}]*)\}\{([^{}]*)\}")


def numbers_from_aux(aux: str) -> dict[str, str]:
    """``{label: printed number}`` from a LaTeX ``.aux`` file.

    The numbers come from LaTeX itself rather than being predicted here. Predicting
    them would mean reimplementing LaTeX's counters — ``\\notag``, ``align`` with
    several lines, ``\\tag``, theorem counters shared across environments — and
    being subtly wrong about a number is worse than not showing one.
    """
    out: dict[str, str] = {}
    for m in _NEWLABEL_RE.finditer(aux):
        name, number = m.group(1), m.group(2).strip()
        if name and number and not name.startswith("node:"):
            out[name] = number
    return out


def resolved_numbers(project) -> dict[str, str]:
    """Numbers from the last compile, **only if that compile is still current**.

    Empty is a normal answer, not a failure: nobody has built a PDF yet, and callers
    show the defining node instead, which is the more useful half anyway.

    The staleness test is the point. A ``.aux`` is the artifact of whenever somebody
    last built a PDF; serving numbers out of it unconditionally means that adding a
    display equation to a node typeset earlier in reading order silently shifts every
    later number, and the browser goes on showing the old ones. A wrong number
    presented confidently is worse than no number, so the ``.aux`` has to be newer
    than every node file and the preamble.
    """
    aux = project.build_dir / "document.aux"
    if not aux.exists():
        return {}
    try:
        built = aux.stat().st_mtime
    except OSError:
        return {}

    sources = list(project.nodes_dir.rglob("*.md")) if project.nodes_dir.is_dir() else []
    if project.preamble_path.exists():
        sources.append(project.preamble_path)
    for source in sources:
        try:
            if source.stat().st_mtime > built:
                return {}
        except OSError:
            return {}

    try:
        return numbers_from_aux(aux.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return {}


def display_map(graph, project, index: Index | None = None) -> dict[str, dict[str, str]]:
    """What the browser needs to render a reference: ``{label: {node, number}}``.

    KaTeX cannot resolve a reference — it renders ``\\eqref{eq:main}`` as the
    literal string ``\\eqrefeq:m`` — so the browser substitutes before typesetting.
    It shows the number when a compile has produced one and the defining node
    always, because "defined in `gclm.blowup`" is more use to a reader of the graph
    than "(1)" is.
    """
    index = index if index is not None else build(graph)
    numbers = resolved_numbers(project)
    out: dict[str, dict[str, str]] = {}
    for name, defs in index.by_name.items():
        out[name] = {
            "node": defs[0].node,
            "section": defs[0].section.lower(),
            "number": numbers.get(name, ""),
            "duplicate": "yes" if len(defs) > 1 else "",
        }
    return out


def obligations_note(index: Index, node_id: str) -> str:
    """Context for a role: which cross-node references this node's text makes.

    Given to the verifier and the extractor, because a proof containing
    ``\\eqref{eq:coercivity}`` is unreadable without being told what that is, and a
    model that is not told will invent something.
    """
    mine = [r for r in index.refs if r.node == node_id]
    if not mine:
        return ""
    lines = ["## Cross-references in this node's text", ""]
    for ref in mine:
        label = index.define(ref.name)
        if label is None:
            lines.append(
                f"- `\\{ref.command}{{{ref.name}}}` — **refers to nothing that "
                "exists in this project.** Treat it as a gap, not as a fact."
            )
        elif label.node == node_id:
            lines.append(f"- `\\{ref.command}{{{ref.name}}}` — defined in this node.")
        else:
            lines.append(
                f"- `\\{ref.command}{{{ref.name}}}` — defined in the "
                f"{label.section.lower()} of `{label.node}`."
            )
    return "\n".join(lines)


__all__ = [
    "Index",
    "LABEL_RE",
    "Label",
    "REF_RE",
    "Ref",
    "build",
    "check_xref",
    "display_map",
    "in_scope",
    "labels_in",
    "numbers_from_aux",
    "obligations_note",
    "refs_in",
    "resolved_numbers",
    "summarise",
]
