"""The check runner: everything ``bp check`` knows how to complain about.

Three families live here — the children-used check, a couple of schema-hygiene
checks, and a drift check — plus the function that assembles all of them with
integrity (:mod:`bp.graph`), discharge (:mod:`bp.discharge`) and the claim ledger
(:mod:`bp.ledger`) into one report.

Checks never mutate anything. They load, derive in memory, and describe.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import discharge as discharge_mod
from . import ledger as ledger_mod
from .diagnostics import Diagnostic, err, sort_diagnostics, warn
from .graph import Graph, GraphError
from .load import computed_in_memory, computed_on_disk, load_nodes
from .model import Node, cites, known_frontmatter_keys
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
FAMILIES = ("integrity", "children_used", "discharge", "ledger")


def for_node(graph: Graph, node: Node) -> dict[str, list[Diagnostic]]:
    """Every deterministic diagnostic about one node, grouped by family.

    This is what makes the verification record's ``deterministic`` block a fact
    rather than a claim: the same functions ``bp check`` runs, re-run for one
    node, family by family. Integrity is a whole-graph check, so it is filtered
    to the diagnostics that name this node.
    """
    integrity = [d for d in graph.integrity() if d.node == node.id]
    return {
        "integrity": integrity,
        "children_used": children_used(node),
        "discharge": discharge_mod.check_discharge(node, graph),
        "ledger": ledger_mod.check_ledger(node),
    }


def run(project: Project) -> Report:
    """Everything ``bp check`` runs, in the order a user wants to read it."""
    graph, diagnostics, swept = load_graph(project)
    diagnostics = list(diagnostics)
    diagnostics.extend(graph.integrity())

    for node in graph.active.values():
        diagnostics.extend(schema_hygiene(node))
        diagnostics.extend(children_used(node))
        diagnostics.extend(discharge_mod.check_discharge(node, graph))
        diagnostics.extend(ledger_mod.check_ledger(node))

    if swept:
        diagnostics.extend(drift(graph))

    return Report(graph=graph, diagnostics=sort_diagnostics(diagnostics), swept=swept)
