"""The verifier: two jobs, kept apart, then a confirmation pass over both.

**Obligation checking.** Consume ``bp obligations <node>`` one record at a time.
Each is a self-contained question — does this source give this hypothesis, for
this object — with no proof search, no strategy, and no whole-proof context.
Narrow questions are where model judgement is most reliable, and the list is
generated deterministically by :mod:`bp.discharge`, so nothing is skipped because
a model failed to notice it needed checking. Results are cached on the
obligation hash, so editing one paragraph of a proof does not re-bill the rest.

**Whole-proof pass.** The statement, the proof, and the children's statements
*as assumptions*. Two backends from different families, no shared context. The
panel is a recall device: two models trained by the same lab miss the same
things, which is why ``verifier_a`` and ``verifier_b`` should not be the same
family.

**Confirmation.** Every objection from either job is re-presented with its
surrounding context, and dropped if the flaw dissolves. This pass is not
optional. Without it the output is mostly pedantry, the user stops reading it,
and the one real objection in the list goes with the rest.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .. import ops
from ..agents.base import AgentError, BudgetExceeded, CallMeta, ReplayMiss
from ..agents.registry import Registry
from ..checks import load_graph
from ..discharge import obligations_for
from ..load import atomic_write
from ..paths import Project
from . import context

CACHE_NAME = "obligations.json"


class ObligationVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entails: bool = Field(
        description="true only if the named source really gives the needed hypothesis "
        "for the stated object"
    )
    why: str = Field(description="one or two sentences")
    confidence: str = Field(default="medium", description="low | medium | high")


class Objection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str = Field(default="proof", description="statement | proof")
    quote: str = Field(description="the exact sentence or display this applies to")
    kind: str = Field(description="the class of error")
    why: str = Field(description="why it does not hold")
    confidence: str = Field(default="medium", description="low | medium | high")


class ProofVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checked: list[str] = Field(
        description="what you went through, step by step. Required either way."
    )
    objections: list[Objection] = Field(default_factory=list)


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upheld: bool
    why: str = Field(description="one sentence: the flaw, or what resolved it")


@dataclass
class Flag:
    """An objection that survived confirmation."""

    source: str
    section: str
    quote: str
    kind: str
    why: str
    raised_by: str

    def to_record(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "section": self.section,
            "quote": self.quote,
            "why": self.why,
            "raised_by": self.raised_by,
        }


@dataclass
class VerifyReport:
    node: str
    obligations_checked: int = 0
    obligations_cached: int = 0
    #: How many panel members actually answered. Zero means nothing verified
    #: this proof, which must never be recorded as ``verified``.
    panel_ran: int = 0
    flags: list[Flag] = field(default_factory=list)
    withdrawn: list[tuple[Flag, str]] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)
    calls: list[CallMeta] = field(default_factory=list)
    verdict: str = "verified"


# --- the obligation cache -----------------------------------------------------


def cache_path(project: Project) -> "Any":
    return project.state_dir / "verify" / CACHE_NAME


def load_cache(project: Project) -> dict[str, dict[str, Any]]:
    path = cache_path(project)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_cache(project: Project, cache: dict[str, dict[str, Any]]) -> None:
    path = cache_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, json.dumps(cache, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


# --- the role -----------------------------------------------------------------


def obligation_prompt(record: dict[str, Any]) -> str:
    """The whole question, self-contained. Deliberately carries no proof context."""
    return "\n".join(
        [
            "## The obligation",
            "",
            f"The proof of `{record['parent']}` cites `{record['child']}`.",
            f"That lemma is applied to: {record['applied_to'] or '(unstated)'}",
            "",
            f"**Needed** — hypothesis {record['hypothesis']} of `{record['child']}`:",
            "",
            f"$$ {record['needed']} $$",
            "",
            f"**Claimed source**: `{record['claimed_source']}`",
            "",
            "**What that source says**:",
            "",
            record["source_text"] or "(the source is free text, quoted above)",
        ]
    )


def verify_obligations(
    project: Project,
    node_id: str,
    *,
    registry: Registry | None = None,
    report: VerifyReport | None = None,
    use_cache: bool = True,
) -> VerifyReport:
    registry = registry or Registry(project)
    report = report or VerifyReport(node=node_id)
    graph, _, swept = load_graph(project)
    if not swept:
        raise ops.OpError("the graph has a cycle; run `bp check` first")
    node = graph.get(node_id)
    if node is None:
        raise ops.OpError(f"no node {node_id!r}")

    agent = registry.agent("verifier_a")
    timeout = registry.config.role("verifier_a").timeout
    system = context.load_prompt("verify_obligation")
    cache = load_cache(project) if use_cache else {}

    for record in obligations_for(node, graph):
        digest = record["hash"]
        if record["kind"] == "admitted":
            # Nothing to check: the author already said this is unsourced. It is
            # already visible debt through the sweep's admitted clamp.
            continue
        cached = cache.get(digest) if use_cache else None
        if cached is not None:
            verdict = ObligationVerdict(**cached["verdict"])
            report.obligations_cached += 1
        else:
            verdict, meta = agent.complete(
                system, obligation_prompt(record), ObligationVerdict, timeout
            )
            report.calls.append(meta)
            cache[digest] = {"id": record["id"], "verdict": verdict.model_dump()}
        report.obligations_checked += 1

        if verdict.entails:
            report.checked.append(
                f"{record['child']}.{record['hypothesis']} from {record['claimed_source']}"
            )
        else:
            report.flags.append(
                Flag(
                    source="obligation",
                    section="proof",
                    quote=f"{record['child']} hypothesis {record['hypothesis']}: "
                    f"{record['needed']}",
                    kind="hypothesis-unsatisfied",
                    why=verdict.why,
                    raised_by=f"{agent.role}:{agent.model}",
                )
            )

    if use_cache:
        save_cache(project, cache)
    return report


def verify_proof(
    project: Project,
    node_id: str,
    *,
    registry: Registry | None = None,
    report: VerifyReport | None = None,
    panel: tuple[str, ...] = ("verifier_a", "verifier_b"),
) -> VerifyReport:
    registry = registry or Registry(project)
    report = report or VerifyReport(node=node_id)
    graph, _, swept = load_graph(project)
    if not swept:
        raise ops.OpError("the graph has a cycle; run `bp check` first")
    node = graph.get(node_id)
    if node is None:
        raise ops.OpError(f"no node {node_id!r}")
    if not node.has_proof:
        raise ops.OpError(f"{node_id} has no proof to verify")

    system = context.load_prompt("verify_proof")
    user = context.join(
        context.preamble_block(project),
        context.node_block(node, heading="The claim and its proof"),
        context.children_block(graph, node)
        or "## The lemmas this proof cites\n\nNone — this is a leaf.",
        "The lemmas above are **assumptions**. Do not question whether they are "
        "true; each has its own node and its own verification.",
    )

    for role in panel:
        try:
            agent = registry.agent(role)
        except Exception:
            continue
        ok, _ = agent.available()
        if not ok and not agent.replay:
            continue
        try:
            verdict, meta = agent.complete(
                system, user, ProofVerdict, registry.config.role(role).timeout
            )
        except (BudgetExceeded, ReplayMiss):
            # Running out of budget is not a verifier declining to object. It
            # must reach the caller, or a recompile would sail past its cap and
            # mark everything verified on the way.
            raise
        except AgentError:
            # One panel member failing is survivable — the other still reads the
            # proof, and the absence shows in `checked`. Both failing is not,
            # and `verify` refuses to record a verdict in that case.
            continue
        report.panel_ran += 1
        report.calls.append(meta)
        report.checked.extend(f"[{role}] {item}" for item in verdict.checked)
        for objection in verdict.objections:
            report.flags.append(
                Flag(
                    source=f"proof:{role}",
                    section=objection.section,
                    quote=objection.quote,
                    kind=objection.kind,
                    why=objection.why,
                    raised_by=f"{role}:{agent.model}",
                )
            )
    return report


def confirm(
    project: Project,
    node_id: str,
    report: VerifyReport,
    *,
    registry: Registry | None = None,
) -> VerifyReport:
    """Re-present every objection with context; drop the ones that dissolve."""
    if not report.flags:
        return report
    registry = registry or Registry(project)
    graph, _, _ = load_graph(project)
    node = graph[node_id]
    agent = registry.agent("verifier_a")
    timeout = registry.config.role("verifier_a").timeout
    system = context.load_prompt("verify_confirm")

    surviving: list[Flag] = []
    for flag in report.flags:
        user = context.join(
            "## The objection",
            f"- Class: {flag.kind}\n- Section: {flag.section}\n"
            f"- Quoting: {flag.quote}\n- Why: {flag.why}",
            "## The context it was raised against",
            context.node_block(node, heading="The claim and its proof"),
            context.children_block(graph, node),
            context.uses_block(node),
        )
        try:
            outcome, meta = agent.complete(system, user, Confirmation, timeout)
        except (BudgetExceeded, ReplayMiss):
            raise
        except AgentError:
            surviving.append(flag)  # cannot confirm; err toward keeping it
            continue
        report.calls.append(meta)
        if outcome.upheld:
            flag.why = outcome.why or flag.why
            surviving.append(flag)
        else:
            report.withdrawn.append((flag, outcome.why))

    report.flags = surviving
    return report


def verify(
    project: Project,
    node_id: str,
    *,
    registry: Registry | None = None,
    obligations: bool = True,
    proof: bool = True,
    record: bool = True,
) -> VerifyReport:
    """Both jobs, then confirmation, then record the verdict."""
    registry = registry or Registry(project)
    report = VerifyReport(node=node_id)
    if obligations:
        verify_obligations(project, node_id, registry=registry, report=report)
    if proof:
        verify_proof(project, node_id, registry=registry, report=report)
        if report.panel_ran == 0:
            # Silence from every verifier is not agreement. Recording `verified`
            # here would turn a network outage into a green graph.
            raise AgentError(
                f"no verifier answered for {node_id}; refusing to record a verdict. "
                "Run `bp agents` to see which backends are usable."
            )
    confirm(project, node_id, report, registry=registry)

    report.verdict = "flagged" if report.flags else "verified"
    if record:
        ops.record_verification(
            project,
            node_id,
            report.verdict,
            [f.to_record() for f in report.flags],
            actor="verifier",
        )
        for flag, why in report.withdrawn:
            ops.add_note(
                project,
                node_id,
                f"Objection withdrawn on confirmation ({flag.kind}): {why}",
                actor="verifier",
            )
    return report


def summarise(report: VerifyReport) -> str:
    lines = [
        f"{report.node}: {report.verdict}",
        f"  obligations: {report.obligations_checked} checked "
        f"({report.obligations_cached} from cache)",
    ]
    if report.flags:
        lines.append(f"  {len(report.flags)} objection(s) upheld:")
        for flag in report.flags:
            lines.append(f"    [{flag.kind}] {flag.why}")
            if flag.quote:
                lines.append(f"      quoting: {flag.quote[:160]}")
    if report.withdrawn:
        lines.append(f"  {len(report.withdrawn)} objection(s) withdrawn on confirmation")
    if not report.flags and report.checked:
        lines.append("  no objection, having checked —")
        for item in report.checked[:20]:
            lines.append(f"    - {item}")
    return "\n".join(lines)


__all__ = [
    "Confirmation",
    "Flag",
    "Objection",
    "ObligationVerdict",
    "ProofVerdict",
    "VerifyReport",
    "confirm",
    "summarise",
    "verify",
    "verify_obligations",
    "verify_proof",
]
