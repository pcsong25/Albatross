"""The check runner: everything ``bp check`` knows how to complain about.

Three families live here — the children-used check, a couple of schema-hygiene
checks, and a drift check — plus the function that assembles all of them with
integrity (:mod:`bp.graph`), discharge (:mod:`bp.discharge`), the claim ledger
(:mod:`bp.ledger`) and cross-references (:mod:`bp.xref`) into one report.

Checks never mutate anything. They load, derive in memory, and describe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from . import discharge as discharge_mod
from . import ledger as ledger_mod
from . import xref as xref_mod
from .diagnostics import Diagnostic, err, sort_diagnostics, warn
from .graph import Graph, GraphError
from .load import computed_in_memory, computed_on_disk, load_nodes
from .model import PROOF, STATEMENT, Node, cites, known_frontmatter_keys
from .paths import Project
from .propagate import sweep


def children_used(node: Node) -> list[Diagnostic]:
    """``USE001`` — a declared child that the proof never mentions.

    Proofs cite children by id in the prose, so a declared child whose id does
    not appear in the Proof section was declared and then not used. That is a
    real and common decomposition failure: the agent proposed a lemma, wrote a
    reduction that does not need it, and the graph now claims a dependency that
    carries no weight.
    """
    d: list[Diagnostic] = []
    proof = node.proof_section
    if not proof.strip():
        return d
    for cid in node.children:
        if not cites(proof, cid):
            d.append(
                warn(
                    "USE001",
                    node,
                    f"child {cid} is declared but never cited in the proof",
                    hint="cite it in the prose where it is used, or drop it from "
                    "`children` — an unused child is a dependency that is not real",
                )
            )
    return d


#: A ``%`` that is not the first thing on its line. LaTeX comments the rest of the
#: line out, so ``improves by 5% in the interior, hence $x>0$`` loses everything
#: after the ``5`` — in a document that compiles cleanly.
_MIDLINE_PERCENT_RE = re.compile(r"^(?P<before>[^\n%]*[^\s%])(?<!\\)%", re.M)

#: Unescaped ``$``. ``\$`` is a literal dollar and ``$$`` opens display maths, so
#: both are removed before counting.
_ESCAPED_DOLLAR_RE = re.compile(r"\\\$")
_COMMENT_LINE_RE = re.compile(r"(?<!\\)%.*$", re.M)


def latex_fragment(text: str, where: str, node: Any = None) -> list[Diagnostic]:
    """``TEX001``–``TEX002`` over one passage of LaTeX, whoever wrote it.

    Split out of :func:`latex_text` so that anything holding authored or generated
    LaTeX can be checked the same way — the paper writer's sections are LaTeX with
    exactly these two failure modes and no node to hang them on. ``where`` names the
    passage for the message; ``node`` is optional and only decides which file the
    diagnostic points at.
    """
    d: list[Diagnostic] = []
    if not text.strip():
        return d

    for m in _MIDLINE_PERCENT_RE.finditer(text):
        fragment = m.group("before").strip()[-48:]
        d.append(
            warn(
                "TEX001",
                node,
                f"a mid-line `%` in the {where} comments out the rest of that "
                f"line: …{fragment}%",
                hint="LaTeX drops everything after it, and the document still "
                "compiles — so the text simply disappears from the PDF. Write "
                "`\\%` for a percent sign. A `%` at the start of a line is a "
                "deliberate comment and is not reported.",
            )
        )

    # Count dollars outside comments: a `%` really does comment out a `$`.
    live = _COMMENT_LINE_RE.sub("", text)
    dollars = _ESCAPED_DOLLAR_RE.sub("", live).count("$")
    if dollars % 2:
        d.append(
            err(
                "TEX002",
                node,
                f"the {where} has an odd number of `$` ({dollars}), so a maths "
                "delimiter is unclosed",
                hint="the document will not compile, and in the browser the "
                "scanner pairs the stray `$` with the next one and typesets the "
                "prose between them as mathematics. Write `\\$` for a literal "
                "dollar sign.",
            )
        )
    return d


def latex_text(node: Node) -> list[Diagnostic]:
    """``TEX001``–``TEX002``: the two ways authored LaTeX goes wrong in silence.

    Everything a user or an agent writes here is LaTeX, and the renderer passes it
    through — which is right, because escaping it would destroy it. The cost is that
    a mistake in it is not caught until ``pdflatex`` runs, and one of these two is
    not caught even then.
    """
    d: list[Diagnostic] = []
    for section in (STATEMENT, PROOF):
        d.extend(latex_fragment(node.section(section), section.lower(), node))
    return d


def target_examined(graph: Graph) -> list[Diagnostic]:
    """``TGT001``–``TGT002``: has anybody looked at the theorem itself?

    This is the layer that was simply absent, and the omission had a cost. A target
    theorem was written whose statement said "in the setting of Section
    \\ref{sec-space}" — a section that was never provided. Nothing examined the
    target when it was written; the decomposer split it into children that inherited
    the incoherence; the verifier passed their proofs. The statement of the thing the
    whole project is about had never been read by any part of the system.

    Every other check here is about a node's *relationships*. This one is about the
    root of the graph being self-contained before anything is built on it, which is
    the one place where getting it wrong invalidates everything downstream.
    """
    d: list[Diagnostic] = []
    targets = [n for n in graph.active.values() if n.target]
    for node in targets:
        if not node.statement_section.strip():
            continue
        if node.audited_against is None:
            d.append(
                warn(
                    "TGT001",
                    node,
                    "the target theorem's statement has never been audited",
                    hint="run `bp audit "
                    + node.id
                    + "` before decomposing it. Four fixed questions — is every "
                    "symbol bound, can the hypotheses be jointly satisfied, are the "
                    "quantifiers in the intended order, does a constant depend on "
                    "something it is treated as uniform in. Everything in the project "
                    "is built on this statement, so an ambiguity or a dangling "
                    "reference in it is inherited by every child and is much more "
                    "expensive to find later.",
                )
            )
        elif node.audited_against != node.statement_hash:
            d.append(
                warn(
                    "TGT002",
                    node,
                    "the target theorem's statement has been edited since it was "
                    "audited",
                    hint="run `bp audit "
                    + node.id
                    + "` again. The audit was about different words.",
                )
            )
    return d


def schema_hygiene(node: Node) -> list[Diagnostic]:
    """``SCH002``/``SCH003`` — cheap protection for hand-edited files."""
    d: list[Diagnostic] = []
    known = known_frontmatter_keys()
    extra = getattr(node, "model_extra", None) or {}
    for key in sorted(extra):
        d.append(
            warn(
                "SCH002",
                node,
                f"unknown frontmatter key {key!r}",
                hint="a misspelled key is accepted silently by YAML and would drop "
                f"whatever it holds; known keys are {', '.join(sorted(known))}",
            )
        )
    if node.local_status == "verified" and not node.has_proof and not node.children:
        d.append(
            warn(
                "SCH003",
                node,
                "marked verified but has no proof and no children",
                hint="if it is true by assumption say so with "
                "`local_status: assumption`; `verified` here would render as proved "
                "with nothing behind it",
            )
        )
    return d


def drift(graph: Graph) -> list[Diagnostic]:
    """``SYS001`` — the computed fields on disk disagree with a fresh sweep.

    Read-only commands never write, so a hand edit leaves the file's derived
    fields describing the previous state. That is harmless as long as it is
    visible, which is what this says.
    """
    d: list[Diagnostic] = []
    for node in graph.active.values():
        on_disk = computed_on_disk(node)
        fresh = computed_in_memory(node)
        differing = sorted(k for k in fresh if on_disk.get(k) != fresh[k])
        if differing:
            d.append(
                warn(
                    "SYS001",
                    node,
                    "computed fields in the file are out of date ("
                    + ", ".join(differing)
                    + ")",
                    hint="run `bp sweep` to rewrite them; every mutation through "
                    "`bp` does this automatically",
                )
            )
    return d


@dataclass
class Report:
    graph: Graph
    diagnostics: list[Diagnostic] = field(default_factory=list)
    swept: bool = True

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "warn"]

    @property
    def notes(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "info"]

    @property
    def ok(self) -> bool:
        return not self.errors


def load_graph(project: Project) -> tuple[Graph, list[Diagnostic], bool]:
    """Load every node, build the graph, and derive statuses in memory.

    Returns the graph, the load-time diagnostics, and whether the sweep ran. The
    sweep is skipped when the children relation has a cycle, because there is no
    order to sweep in; integrity reports the cycle.
    """
    nodes, load_errors = load_nodes(project)
    diagnostics = [
        err(
            "SCH001",
            None,
            f"{e.path.name}: {e.message}",
            hint="this file was skipped entirely, so anything citing it will look "
            "dangling",
        )
        for e in load_errors
    ]
    for d, e in zip(diagnostics, load_errors):
        d.file = str(e.path)

    graph = Graph(nodes)
    swept = True
    try:
        sweep(graph)
    except GraphError:
        swept = False
    return graph, diagnostics, swept


#: The deterministic check families, in the order the verification record lists
#: them. Names are part of the record's schema, so they are here rather than
#: spelled out in :mod:`bp.verification`.
FAMILIES = ("integrity", "children_used", "discharge", "ledger", "xref", "latex")


def for_node(graph: Graph, node: Node) -> dict[str, list[Diagnostic]]:
    """Every deterministic diagnostic about one node, grouped by family.

    This is what makes the verification record's ``deterministic`` block a fact
    rather than a claim: the same functions ``bp check`` runs, re-run for one
    node, family by family. Integrity is a whole-graph check, so it is filtered
    to the diagnostics that name this node.
    """
    integrity = [d for d in graph.integrity() if d.node == node.id]
    # Cross-references are inherently whole-graph — a label and the reference to it
    # live in different files — so this filters the graph-wide result the same way
    # integrity is filtered.
    xref = [d for d in xref_mod.check_xref(graph) if d.node == node.id]
    return {
        "integrity": integrity,
        "children_used": children_used(node),
        "discharge": discharge_mod.check_discharge(node, graph),
        "ledger": ledger_mod.check_ledger(node),
        "xref": xref,
        "latex": latex_text(node),
    }


def run(project: Project) -> Report:
    """Everything ``bp check`` runs, in the order a user wants to read it."""
    graph, diagnostics, swept = load_graph(project)
    diagnostics = list(diagnostics)
    diagnostics.extend(graph.integrity())

    for node in graph.active.values():
        diagnostics.extend(schema_hygiene(node))
        diagnostics.extend(latex_text(node))
        diagnostics.extend(children_used(node))
        diagnostics.extend(discharge_mod.check_discharge(node, graph))
        diagnostics.extend(ledger_mod.check_ledger(node))

    # Whole-graph, after the per-node pass: a reference and its label are in
    # different files, so neither node alone can tell whether the pair is sound.
    diagnostics.extend(xref_mod.check_xref(graph))
    diagnostics.extend(target_examined(graph))

    if swept:
        diagnostics.extend(drift(graph))

    return Report(graph=graph, diagnostics=sort_diagnostics(diagnostics), swept=swept)
