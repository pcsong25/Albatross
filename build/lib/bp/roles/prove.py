"""The prover: write a proof for an easy leaf.

Two constraints define this role.

**It runs on ``routine`` and ``standard`` leaves only.** Not because a model
could not attempt a hard lemma, but because the point of proving the cheap
leaves first is that they are a *falsification test on the strategy*: if a
bookkeeping lemma the decomposition requires turns out to be false, or to need a
hypothesis nobody has, the strategy is wrong and it cost a few cheap attempts
instead of three weeks. Spending the same effort on the hard leaf tells you
nothing you did not already know.

**It never sets ``local_status``.** The prover writes prose into the Proof
section and stops. Whether that prose is a proof is the verifier's judgement,
made separately, and the verifier is not told who wrote it. A role that could
both write a proof and mark it verified would be marking its own homework, and
the graph's colours would stop meaning anything.

A refusal is a result. ``attempted: false`` with a reason — the lemma needs an
idea, a hypothesis is missing, the statement looks false — is the most valuable
thing this role produces, because it is usually a fact about the decomposition
rather than about the lemma.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from .. import ops
from ..agents.base import CallMeta
from ..agents.registry import Registry
from ..checks import load_graph
from ..paths import Project
from . import context

PROVABLE = {"routine", "standard"}


class ProofDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempted: bool = Field(
        description="false if this is not in fact routine — say why in `reason`"
    )
    proof: str = Field(default="", description="the proof, as LaTeX prose")
    gaps: list[str] = Field(
        default_factory=list,
        description="steps you could not actually justify. Name them; do not paper "
        "over them.",
    )
    reason: str = Field(
        default="",
        description="when attempted is false: what is missing, what hypothesis is "
        "absent, or the counterexample",
    )


@dataclass
class ProveResult:
    node: str
    draft: ProofDraft | None = None
    written: bool = False
    calls: list[CallMeta] = field(default_factory=list)


def prove(
    project: Project,
    node_id: str,
    *,
    registry: Registry | None = None,
    force: bool = False,
    apply: bool = True,
) -> ProveResult:
    registry = registry or Registry(project)
    graph, _, swept = load_graph(project)
    if not swept:
        raise ops.OpError("the graph has a cycle; run `bp check` first")
    node = graph.get(node_id)
    if node is None:
        raise ops.OpError(f"no node {node_id!r}")
    if node.children and not force:
        raise ops.OpError(
            f"{node_id} has children; its proof is the reduction, which the "
            "decomposer writes. Use --force to override."
        )
    if node.difficulty not in PROVABLE and not force:
        raise ops.OpError(
            f"{node_id} is labelled {node.difficulty}; the prover runs on routine and "
            "standard leaves only. Relabel it, or use --force if you want the attempt "
            "anyway — a failed attempt on a hard leaf is not informative."
        )
    if node.has_proof and not force:
        raise ops.OpError(f"{node_id} already has a proof; use --force to replace it")

    agent = registry.agent("prover")
    user = context.join(
        context.preamble_block(project),
        context.setting(graph, node),
        context.node_block(node, heading="The lemma to prove", proof=False),
        context.siblings_available(graph, node),
    )
    draft, meta = agent.complete(
        context.load_prompt("prove"),
        user,
        ProofDraft,
        registry.config.role("prover").timeout,
    )
    result = ProveResult(node=node_id, draft=draft, calls=[meta])

    if not apply:
        return result

    if not draft.attempted:
        ops.add_note(
            project,
            node_id,
            f"Prover declined this lemma: {draft.reason.strip() or 'no reason given'}",
            actor="prover",
        )
        return result

    body = draft.proof.strip()
    if draft.gaps:
        body += "\n\n" + "\n".join(
            f"% GAP: {gap}" for gap in draft.gaps
        )
    ops.edit_proof(project, node_id, body, actor="prover")
    if draft.gaps:
        ops.add_note(
            project,
            node_id,
            "Prover left "
            + str(len(draft.gaps))
            + " unjustified step(s): "
            + "; ".join(draft.gaps),
            actor="prover",
        )
    result.written = True
    return result


def summarise(result: ProveResult) -> str:
    draft = result.draft
    if draft is None:
        return f"{result.node}: no draft"
    if not draft.attempted:
        return f"{result.node}: declined — {draft.reason}"
    lines = [
        f"{result.node}: proof written ({len(draft.proof)} chars). "
        "local_status is unchanged; run `bp verify` to have it checked."
    ]
    for gap in draft.gaps:
        lines.append(f"  gap: {gap}")
    return "\n".join(lines)


__all__ = ["PROVABLE", "ProofDraft", "ProveResult", "prove", "summarise"]
