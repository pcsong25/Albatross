"""The decomposer: propose one level of decomposition, and repair it.

The load-bearing idea here is not the model call. It is that the model must
return a **complete discharge table** along with its children, and that the table
is checked deterministically before anything touches the graph.

That is the anti-gap device, and it is not a judgement: a model cannot fill in
`discharges` for every hypothesis of every lemma it cites without confronting
whether those lemmas actually cover the parent. Most insufficient decompositions
die at ``DIS011``, for free, before any verifier runs. Expect a substantial
fraction of first attempts to be rejected — that is the mechanism working, not
the model failing.

Two repair rounds, then the result is written anyway with its remaining
diagnostics reported. Writing it is the right call: this system's whole posture
is that debt is visible rather than hidden, the user can see exactly what is
wrong from ``bp check``, and nothing is destroyed if they archive it.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .. import ops
from ..agents.base import CallMeta
from ..agents.registry import Registry
from ..checks import children_used, load_graph
from ..diagnostics import Diagnostic, warn
from ..discharge import check_discharge
from ..graph import Graph
from ..model import Hypothesis, Node, Use, set_section
from ..paths import Project
from . import context

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

#: How many children a `decompose` verdict may propose. One is allowed because a
#: reduction to a single substantial lemma is a real decomposition — the content is
#: the reduction — and refusing it forced the model to invent two siblings it did not
#: believe in. Ten because a long argument with many independent estimates is an
#: ordinary shape for a real theorem. The prompt says when each end is right; the
#: bound only stops the two degenerate answers (nothing, and a hundred paragraphs).
MIN_CHILDREN = 1
MAX_CHILDREN = 10


class HypothesisSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="H1, H2, … unique within this child")
    tex: str = Field(description="a math-mode LaTeX fragment, without dollar signs")


class UseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    applied_to: str = Field(
        default="", description="the object this lemma is applied to, in LaTeX"
    )
    discharges: dict[str, str] = Field(
        default_factory=dict,
        description="child hypothesis id -> hypothesis:<id> | child:<slug> | "
        "proof:<text> | literature:<ref> | ADMITTED: <reason>",
    )


class ProposedChild(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(description="short kebab-case identifier, no project prefix")
    role: Literal["lemma", "proposition", "theorem", "definition", "assumption"] = "lemma"
    statement: str = Field(description="the statement, as LaTeX prose")
    difficulty: Literal["standard", "routine", "hard", "unknown"] = "unknown"
    hypotheses: list[HypothesisSpec] = Field(default_factory=list)
    notes: str = ""


class Decomposition(BaseModel):
    """Either a decomposition, or a reasoned refusal to produce one.

    The refusal is the point of the ``verdict`` field. Splitting a lemma that is
    already one step is not free: it costs a long call, and it leaves the user
    pruning nodes that should never have existed. Asking the model to judge that
    first — and to say so instead of inventing three children — is cheaper than
    any amount of prompt scolding about granularity.
    """

    model_config = ConfigDict(extra="forbid")

    verdict: Literal["decompose", "prove-directly", "already-atomic"] = Field(
        description="`decompose` if this node is worth breaking up. "
        "`prove-directly` if the argument is clear enough to just write out. "
        "`already-atomic` if it is a single step and splitting would only add "
        "bookkeeping."
    )
    assessed_difficulty: Literal["standard", "routine", "hard", "unknown"] = Field(
        description="your judgement of THIS node, not of its children"
    )
    assessment: str = Field(
        description="two or three sentences: how hard this is and why, and — if you "
        "are not decomposing — the shape of the argument you would write instead"
    )
    strategy: str = Field(
        default="", description="one line naming the shape of the argument"
    )
    children: list[ProposedChild] = Field(default_factory=list, max_length=MAX_CHILDREN)
    reduction_proof: str = Field(
        default="",
        description="the parent's proof, citing each child by `slug` in backticks. "
        "Required when the verdict is `decompose`.",
    )
    uses: dict[str, UseSpec] = Field(
        default_factory=dict, description="keyed by child slug"
    )
    notes: str = Field(
        default="",
        description="reservations, missing hypotheses, why this decomposition may "
        "be wrong — the user wants to hear these",
    )

    @model_validator(mode="after")
    def _shape_matches_verdict(self) -> "Decomposition":
        if self.verdict == "decompose":
            if not MIN_CHILDREN <= len(self.children) <= MAX_CHILDREN:
                raise ValueError(
                    f"a `decompose` verdict needs between {MIN_CHILDREN} and "
                    f"{MAX_CHILDREN} children; return `prove-directly` or "
                    "`already-atomic` if the node does not deserve any"
                )
            if not self.reduction_proof.strip():
                raise ValueError("a `decompose` verdict needs a reduction_proof")
        return self

    @property
    def decomposing(self) -> bool:
        return self.verdict == "decompose"


@dataclass
class ExpandResult:
    node: str
    children: list[str]
    decomposition: Decomposition | None
    diagnostics: list[Diagnostic] = field(default_factory=list)
    calls: list[CallMeta] = field(default_factory=list)
    rounds: int = 1
    archived_to: Path | None = None
    #: Set when the decomposer judged the node not worth decomposing and nothing
    #: was written. The user decides what happens next.
    declined: bool = False

    @property
    def clean(self) -> bool:
        return not any(d.severity == "error" for d in self.diagnostics)

    @property
    def verdict(self) -> str:
        return self.decomposition.verdict if self.decomposition else "decompose"

    @property
    def assessment(self) -> str:
        return self.decomposition.assessment if self.decomposition else ""


def statement_errors(graph: Graph, node: Node) -> list[Diagnostic]:
    """Deterministic errors in this node's *own* statement text.

    Only the families that describe the node's own words — a citation to nothing, a
    duplicated label, an unclosed dollar. Not the discharge or ledger families, which
    are about the decomposition that does not exist yet.
    """
    from .. import checks
    from .. import xref as xref_mod

    out = [d for d in xref_mod.check_xref(graph) if d.node == node.id]
    out.extend(checks.latex_text(node))
    return [d for d in out if d.severity == "error"]


def _refuse_incoherent(graph: Graph, node: Node, *, force: bool) -> None:
    """Do not build a decomposition on a statement that does not hold together.

    This is the cheapest place in the system to catch an incoherent statement, and it
    used to be the place that ignored it. A target citing a section nobody had written
    was decomposed into seven children, every one of which inherited the phrase; the
    checker did not ask about it, the verifier passed the proofs, and the cost of
    finding it later was the whole subtree.

    ``force`` overrides, because the user may be mid-edit and know better — but it is
    an override, not a default.
    """
    problems = statement_errors(graph, node)
    if not problems or force:
        return
    lines = [
        f"{node.id}'s own statement has {len(problems)} deterministic error(s), so "
        "decomposing it would build a whole subtree on text that does not hold "
        "together:",
        "",
    ]
    for d in problems:
        lines.append(f"  {d.code}: {d.message}")
        if d.hint:
            lines.append(f"      {d.hint}")
    lines.append("")
    lines.append(
        "Fix the statement first — `bp check` lists these — or pass --force if you "
        "know better. Every child inherits whatever is wrong here."
    )
    raise ops.OpError("\n".join(lines))


# --- prompt assembly ----------------------------------------------------------


FORCE_BLOCK = """## The user has overruled your assessment

You have already judged this node not worth decomposing, and the mathematician
has asked for a decomposition anyway. They can see your reasoning and have
decided otherwise; it is their problem and their call.

Return `verdict: "decompose"` with between 1 and 10 children, a reduction proof
and a complete `uses` table. If the natural split is into few, small pieces, say
so in `notes` — but produce the decomposition."""


def build_prompt(
    graph: Graph, node: Node, hint: str | None, project=None, force: bool = False
) -> str:
    blocks = [
        context.preamble_block(project) if project is not None else "",
        context.setting(graph, node),
        context.node_block(node, heading="The node to decompose"),
        # What this node's own text cites, and whether those citations resolve. The
        # decomposer had none of this, which is how a statement citing a section
        # nobody had written was split into seven children that all inherited it.
        context.xref_block(graph, node),
        context.siblings_available(graph, node),
    ]
    if hint:
        blocks.append(
            "## The user's guidance\n\nThis is from the mathematician who owns the "
            "problem. Take it seriously; it is worth more than your own first "
            f"instinct about the strategy.\n\n{hint.strip()}"
        )
    if force:
        blocks.append(FORCE_BLOCK)
    return context.join(*blocks)


# --- candidate assembly and checking ------------------------------------------


def assign_ids(graph: Graph, node: Node, decomposition: Decomposition) -> dict[str, str]:
    """Map each proposed slug to a project-unique node id."""
    prefix = node.id.split(".")[0] if "." in node.id else node.id
    taken = set(graph.nodes)
    mapping: dict[str, str] = {}
    for child in decomposition.children:
        slug = child.slug.strip().lower()
        if not SLUG_RE.match(slug):
            slug = re.sub(r"[^a-z0-9-]+", "-", slug).strip("-") or "lemma"
        candidate = f"{prefix}.{slug}"
        n = 2
        while candidate in taken:
            candidate = f"{prefix}.{slug}-{n}"
            n += 1
        taken.add(candidate)
        mapping[child.slug] = candidate
    return mapping


def _child_node(child: ProposedChild, node_id: str) -> Node:
    body = (
        f"## Statement\n\n{child.statement.strip()}\n\n"
        f"## Proof\n\n\n\n## Notes\n\n{child.notes.strip()}\n"
    )
    return Node(
        id=node_id,
        role=child.role,
        difficulty=child.difficulty,
        hypotheses=[Hypothesis(id=h.id, tex=h.tex) for h in child.hypotheses],
        body=body,
    )


def resolve_discharges(use: UseSpec, ids: dict[str, str]) -> dict[str, str]:
    """Rewrite ``child:<slug>`` sources to ``child:<node id>``.

    The prompt asks for sibling references by slug, because the model does not
    know the project's id namespace and should not have to. Resolving the keys
    of ``uses`` while leaving the *values* alone was a real bug: every
    ``child:`` discharge came back as ``DIS014``, and a repair round was spent
    on a problem the system had invented.
    """
    out: dict[str, str] = {}
    for hyp_id, source in use.discharges.items():
        text = source.strip()
        if text.startswith("child:"):
            slug = text[len("child:") :].strip()
            if slug in ids:
                text = f"child:{ids[slug]}"
        out[hyp_id] = text
    return out


def resolved_uses(decomposition: Decomposition, ids: dict[str, str]) -> dict[str, Use]:
    return {
        ids[slug]: Use(
            applied_to=use.applied_to, discharges=resolve_discharges(use, ids)
        )
        for slug, use in decomposition.uses.items()
        if slug in ids
    }


def candidate_graph(
    graph: Graph, node: Node, decomposition: Decomposition, ids: dict[str, str]
) -> tuple[Graph, Node]:
    """Build the graph this decomposition *would* produce, without writing it.

    Checking before writing is what keeps a rejected decomposition out of the
    event log and out of the user's ``nodes/`` directory.
    """
    children = [
        _child_node(child, ids[child.slug]) for child in decomposition.children
    ]
    parent = node.model_copy(deep=True)
    parent.children = [ids[c.slug] for c in decomposition.children]
    parent.uses = resolved_uses(decomposition, ids)
    parent.body = _reduction_body(node, decomposition, ids)

    others = [n for n in graph if n.id != node.id]
    return Graph([*others, parent, *children]), parent


def _reduction_body(
    node: Node, decomposition: Decomposition, ids: dict[str, str]
) -> str:
    """The parent's body with the reduction written in and slugs resolved."""
    proof = decomposition.reduction_proof.strip()
    for slug, node_id in sorted(ids.items(), key=lambda kv: -len(kv[0])):
        proof = proof.replace(f"`{slug}`", f"`{node_id}`")
        proof = re.sub(
            rf"(?<![A-Za-z0-9_.\-`]){re.escape(slug)}(?![A-Za-z0-9_.\-`])",
            f"`{node_id}`",
            proof,
        )
    return set_section(node.body, "Proof", proof)


def check_candidate(candidate: Graph, parent: Node) -> list[Diagnostic]:
    """Everything the graph can say about a decomposition before it is written."""
    diagnostics = check_discharge(parent, candidate)
    diagnostics.extend(children_used(parent))
    return diagnostics


def unresolved_slugs(decomposition: Decomposition, ids: dict[str, str]) -> list[str]:
    """``uses`` keys that do not name a proposed child — a common model slip."""
    return sorted(set(decomposition.uses) - set(ids))


# --- the role -----------------------------------------------------------------


def expand(
    project: Project,
    node_id: str,
    *,
    hint: str | None = None,
    registry: Registry | None = None,
    repair_rounds: int = 2,
    apply: bool = True,
    force: bool = False,
) -> ExpandResult:
    """Decompose one node, one level, repairing against the discharge check.

    The decomposer may decline. When it judges the node too easy to be worth
    splitting it returns a verdict and an assessment instead of children, nothing
    is written, and the caller is left to choose — write the proof, or press on
    with ``force=True``.
    """
    registry = registry or Registry(project)
    agent = registry.agent("decomposer")
    system = context.load_prompt("decompose")

    graph, load_diagnostics, swept = load_graph(project)
    if not swept:
        raise ops.OpError("the graph has a cycle; run `bp check` before expanding")
    node = graph.get(node_id)
    if node is None:
        raise ops.OpError(f"no node {node_id!r}")
    if node.children:
        raise ops.OpError(
            f"{node_id} already has children ({', '.join(node.children)}). "
            "Use `bp redo` to archive them and decompose again."
        )
    _refuse_incoherent(graph, node, force=force)

    user = build_prompt(graph, node, hint, project, force)
    calls: list[CallMeta] = []
    decomposition: Decomposition | None = None
    diagnostics: list[Diagnostic] = []
    ids: dict[str, str] = {}
    rounds = 0

    for attempt in range(repair_rounds + 1):
        rounds = attempt + 1
        decomposition, meta = agent.complete(
            system, user, Decomposition, timeout=registry.config.role("decomposer").timeout
        )
        calls.append(meta)

        if not decomposition.decomposing and force:
            # Overruled, and it declined anyway. Do not write an empty
            # decomposition — say so and let the repair round press the point.
            diagnostics = [
                warn(
                    "DEC001",
                    node,
                    f"the decomposer returned `{decomposition.verdict}` even though a "
                    "decomposition was demanded: " + decomposition.assessment,
                )
            ]
            if attempt == repair_rounds:
                return ExpandResult(
                    node=node_id, children=[], decomposition=decomposition,
                    diagnostics=diagnostics, calls=calls, rounds=rounds, declined=True,
                )
            user = context.join(
                build_prompt(graph, node, hint, project, force=True),
                "Your previous reply declined again. Return a decomposition.",
            )
            continue

        if not decomposition.decomposing and not force:
            # It judged the node not worth splitting. Stop here: writing children
            # it does not believe in would be worse than the wait.
            result = ExpandResult(
                node=node_id, children=[], decomposition=decomposition,
                calls=calls, rounds=rounds, declined=True,
            )
            if apply:
                ops.add_note(
                    project, node_id,
                    f"Decomposer declined to split this ({decomposition.verdict}, "
                    f"assessed {decomposition.assessed_difficulty}): "
                    f"{decomposition.assessment}",
                    actor="decomposer",
                )
            return result

        ids = assign_ids(graph, node, decomposition)
        candidate, parent = candidate_graph(graph, node, decomposition, ids)
        diagnostics = check_candidate(candidate, parent)
        stray = unresolved_slugs(decomposition, ids)
        if stray:
            diagnostics.append(
                warn(
                    "DIS016",
                    parent,
                    f"`uses` mentions {', '.join(stray)}, which are not proposed children",
                )
            )

        if not any(d.severity == "error" for d in diagnostics):
            break
        if attempt == repair_rounds:
            break
        user = context.join(
            build_prompt(graph, node, hint, project, force),
            context.diagnostics_block(
                diagnostics, "Your previous decomposition was rejected"
            ),
            "Return a corrected decomposition. You may change the children, but the "
            "usual fix is a missing or wrongly-named entry in `uses`. If a hypothesis "
            "genuinely has no source, write `ADMITTED: <reason>` rather than dropping "
            "the entry.",
        )

    result = ExpandResult(
        node=node_id,
        children=[ids[c.slug] for c in decomposition.children] if decomposition else [],
        decomposition=decomposition,
        diagnostics=diagnostics,
        calls=calls,
        rounds=rounds,
    )
    if apply and decomposition is not None:
        _apply(project, node_id, decomposition, ids, hint)
    return result


def _apply(
    project: Project,
    node_id: str,
    decomposition: Decomposition,
    ids: dict[str, str],
    hint: str | None,
) -> None:
    """Write the decomposition through ``ops``, children first."""
    for child in decomposition.children:
        ops.add_node(
            project,
            ids[child.slug],
            role=child.role,
            statement=child.statement,
            notes=child.notes,
            difficulty=child.difficulty,
            hypotheses=[h.model_dump() for h in child.hypotheses],
            actor="decomposer",
        )

    ops.set_children(
        project, node_id, [ids[c.slug] for c in decomposition.children], actor="decomposer"
    )
    ops.set_uses(
        project,
        node_id,
        {
            cid: use.model_dump()
            for cid, use in resolved_uses(decomposition, ids).items()
        },
        actor="decomposer",
    )

    ops.edit_proof(
        project,
        node_id,
        _resolve_slugs(decomposition.reduction_proof, ids),
        actor="decomposer",
    )
    if decomposition.strategy.strip():
        graph = ops.open_graph(project)
        if not graph[node_id].strategy:
            ops.set_strategy(
                project, node_id, decomposition.strategy.strip(), actor="decomposer"
            )
    if decomposition.notes.strip():
        ops.add_note(
            project,
            node_id,
            f"Decomposer's reservations: {decomposition.notes.strip()}",
            actor="decomposer",
        )
    if hint:
        ops.add_note(project, node_id, f"Expanded with hint: {hint.strip()}")


def _resolve_slugs(proof: str, ids: dict[str, str]) -> str:
    for slug, node_id in sorted(ids.items(), key=lambda kv: -len(kv[0])):
        proof = proof.replace(f"`{slug}`", f"`{node_id}`")
        proof = re.sub(
            rf"(?<![A-Za-z0-9_.\-`]){re.escape(slug)}(?![A-Za-z0-9_.\-`])",
            f"`{node_id}`",
            proof,
        )
    return proof


# --- redo ---------------------------------------------------------------------


def next_attempt_dir(project: Project, node_id: str) -> Path:
    n = 1
    while (project.attempts_dir / f"{node_id}-{n}").exists():
        n += 1
    return project.attempts_dir / f"{node_id}-{n}"


def redo(
    project: Project,
    node_id: str,
    *,
    hint: str | None = None,
    registry: Registry | None = None,
    repair_rounds: int = 2,
) -> ExpandResult:
    """Archive the current subtree and decompose again.

    The previous attempt's files are copied to ``attempts/<node>-<n>/`` *before*
    anything is archived, and the problems found with it are fed to the new
    attempt as negative context — a redo that does not know why the last one was
    rejected tends to produce the same thing again.
    """
    from .. import checks

    graph = ops.open_graph(project)
    node = graph.get(node_id)
    if node is None:
        raise ops.OpError(f"no node {node_id!r}")

    report = checks.run(project)
    problems = [d for d in report.diagnostics if d.node == node_id and d.severity != "info"]

    dest = next_attempt_dir(project, node_id)
    dest.mkdir(parents=True, exist_ok=True)
    for member_id in sorted({node_id} | graph.descendants(node_id)):
        member = graph.get(member_id)
        if member is not None and member.path is not None and member.path.exists():
            shutil.copy2(member.path, dest / member.path.name)

    for child_id in list(node.children):
        try:
            ops.archive(project, child_id, actor="decomposer")
        except ops.OpError:
            continue
    ops.set_uses(project, node_id, {}, actor="decomposer")

    previous = context.join(
        hint or "",
        context.diagnostics_block(problems, "Problems with the previous attempt")
        if problems
        else "",
        f"The previous attempt has been archived to `{dest}`. Do not reproduce it.",
    )
    result = expand(
        project,
        node_id,
        hint=previous,
        registry=registry,
        repair_rounds=repair_rounds,
    )
    result.archived_to = dest
    return result


def summarise(result: ExpandResult) -> str:
    if result.declined:
        d = result.decomposition
        return "\n".join([
            f"{result.node}: not decomposed ({d.verdict}, assessed {d.assessed_difficulty})",
            f"  {d.assessment}",
            "  Nothing was written. Generate a proof, relabel it, or expand with --force.",
        ])
    lines = [
        f"{result.node}: {len(result.children)} child(ren) in {result.rounds} round(s)"
    ]
    for child_id in result.children:
        lines.append(f"  - {child_id}")
    errors = [d for d in result.diagnostics if d.severity == "error"]
    if errors:
        lines.append(f"  {len(errors)} unresolved error(s) after repair:")
        for d in errors:
            lines.append(f"    {d.code}: {d.message}")
    return "\n".join(lines)


__all__ = [
    "Decomposition",
    "statement_errors",
    "ExpandResult",
    "HypothesisSpec",
    "ProposedChild",
    "UseSpec",
    "expand",
    "redo",
    "summarise",
]
