"""The checker: two separate calls about a decomposition.

Two, not one. Asking a model "is this decomposition any good?" produces a
paragraph of impressions. Asking it two specific questions, in two calls with no
shared context, produces two specific answers:

1. Assuming every child is true, does the reduction establish the parent?
2. Is any child a restatement of the parent, or as hard as the parent?

The third question the earlier design asked — *are the needed hypotheses
available?* — is deliberately **not** asked here. It is answered better
elsewhere: completeness by :mod:`bp.discharge`, deterministically; entailment by
the verifier, one narrow obligation at a time. Asking it here too would produce
a third opinion about a question that already has a mechanical answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from ..agents.base import CallMeta
from ..agents.registry import Registry
from ..checks import load_graph
from ..ops import OpError
from ..paths import Project
from . import context


class Problem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    where: str = Field(description="which child, step or sentence this is about")
    quote: str = Field(default="", description="the exact text this applies to")
    why: str = Field(description="why it is a problem, in one or two sentences")
    confidence: str = Field(
        default="medium", description="low | medium | high — how sure you are"
    )


class CheckAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checked: list[str] = Field(
        description="what you actually went through, specifically. Required whether "
        "or not you found anything — an unexplained 'none found' is not an answer."
    )
    problems: list[Problem] = Field(
        default_factory=list, description="empty means none found"
    )


@dataclass
class CheckReport:
    node: str
    reduction: CheckAnswer | None = None
    triviality: CheckAnswer | None = None
    calls: list[CallMeta] = field(default_factory=list)

    @property
    def problems(self) -> list[tuple[str, Problem]]:
        out: list[tuple[str, Problem]] = []
        for label, answer in (("reduction", self.reduction), ("triviality", self.triviality)):
            if answer:
                out.extend((label, p) for p in answer.problems)
        return out

    @property
    def clean(self) -> bool:
        return not self.problems


def check_decomposition(
    project: Project, node_id: str, *, registry: Registry | None = None
) -> CheckReport:
    """Both checker calls on one node."""
    registry = registry or Registry(project)
    graph, _, swept = load_graph(project)
    if not swept:
        raise OpError("the graph has a cycle; run `bp check` first")
    node = graph.get(node_id)
    if node is None:
        raise OpError(f"no node {node_id!r}")
    if not node.children:
        raise OpError(f"{node_id} has no children, so there is no decomposition to check")

    agent = registry.agent("checker")
    timeout = registry.config.role("checker").timeout
    report = CheckReport(node=node_id)

    common = context.join(
        context.setting(graph, node),
        context.node_block(node, heading="The node"),
        context.children_block(graph, node),
    )

    reduction_user = context.join(common, context.uses_block(node))
    report.reduction, meta = agent.complete(
        context.load_prompt("check_reduction"), reduction_user, CheckAnswer, timeout
    )
    report.calls.append(meta)

    # A second, independent call — no shared context with the first, so an
    # error in the reduction cannot colour the judgement about triviality.
    report.triviality, meta = agent.complete(
        context.load_prompt("check_triviality"), common, CheckAnswer, timeout
    )
    report.calls.append(meta)
    return report


def summarise(report: CheckReport) -> str:
    lines = [f"{report.node}:"]
    for label, answer in (
        ("reduction", report.reduction),
        ("triviality", report.triviality),
    ):
        if answer is None:
            continue
        if answer.problems:
            lines.append(f"  {label}: {len(answer.problems)} problem(s)")
            for p in answer.problems:
                lines.append(f"    [{p.confidence}] {p.where}: {p.why}")
                if p.quote:
                    lines.append(f"      quoting: {p.quote[:160]}")
        else:
            lines.append(f"  {label}: none found, having checked —")
            for item in answer.checked:
                lines.append(f"    - {item}")
    return "\n".join(lines)


__all__ = ["CheckAnswer", "CheckReport", "Problem", "check_decomposition", "summarise"]
