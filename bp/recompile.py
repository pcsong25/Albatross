"""``bp recompile`` — re-verify what needs it, at the depth you asked for, then sweep.

Agent-checking every claim is expensive. A node with a ten-claim proof runs roughly
fifteen calls at full depth, so a thirty-node graph is several hundred — which is
why recompile is **tiered** rather than being one thing you either can or cannot
afford:

======================  ==========================================================
``--level quick``       deterministic checks, whole-proof pass
``--level standard``    + extraction, ledger audit, obligation checks
``--level deep``        + per-claim checks, statement audits, confirmation on
                        everything
======================  ==========================================================

``quick`` is for iterating; ``standard`` is routine work; ``deep`` is what you run
before trusting a subtree or before writing it up. Which one produced a node's
green is recorded on the node, because a node verified at ``quick`` and one
verified at ``deep`` are not making the same claim.

Four properties matter more than the selection rule:

*The bill is previewable.* ``--dry-run`` lists the calls it would make and what
they would cost, before any of them happen. A budget you can only discover by
spending it is not a budget.

*Nothing is re-billed.* Every obligation and claim carries a content hash, and an
unchanged record is answered from cache. Editing one paragraph of a proof must not
re-verify the rest of it.

*Results write as they land.* Each node's verdict goes through ``ops`` as soon as
it is reached, so an interrupted run keeps everything it paid for, and ``bp resume``
re-queries nothing already done.

*Money is spent where it matters.* Nodes on the path to the target first, then the
frontier, then the rest — so a run stopped by ``--budget`` has bought the most
useful half.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import frontier as frontier_mod
from . import jobs, ledger as ledger_mod, ops, verification
from .agents.base import Budget, BudgetExceeded
from .agents.registry import Registry
from .checks import load_graph
from .discharge import obligations_for
from .graph import Graph
from .model import Node
from .paths import Project
from .propagate import BLOCKED_STALE, BLOCKED_UNVERIFIED
from .roles import verify as verify_role

#: Rough token cost of one call, for the dry-run estimate only. Prompts are
#: measured; the output side is a constant because it cannot be known in advance.
CHARS_PER_TOKEN = 4
OBLIGATION_OUTPUT_TOKENS = 200
CLAIM_OUTPUT_TOKENS = 200
EXTRACT_OUTPUT_TOKENS = 1200
PROOF_OUTPUT_TOKENS = 900
AUDIT_OUTPUT_TOKENS = 1200
CONFIRM_OUTPUT_TOKENS = 150


@dataclass
class Task:
    node: str
    reason: str
    level: str
    obligations: int = 0
    obligations_cached: int = 0
    claims: int = 0
    claims_cached: int = 0
    extract: int = 0
    audit: int = 0
    panel: int = 0
    batch: int = 1

    @property
    def id(self) -> str:
        return f"verify:{self.node}"

    @property
    def cached(self) -> int:
        return self.obligations_cached + self.claims_cached

    @property
    def calls(self) -> int:
        """Calls this task would make.

        Confirmation calls are unknowable in advance — one per objection, and how
        many objections there will be is exactly what the run is for — so they are
        not counted, and :meth:`Plan.describe` says so rather than inventing a
        number.
        """
        size = max(1, self.batch)
        fresh_ob = max(0, self.obligations - self.obligations_cached)
        fresh_cl = max(0, self.claims - self.claims_cached)
        batched = -(-fresh_ob // size) + -(-fresh_cl // size)
        return batched + self.extract + self.audit + self.panel


@dataclass
class Plan:
    level: str = verification.STANDARD
    batch: int = 1
    tasks: list[Task] = field(default_factory=list)
    estimated_usd: float | None = 0.0
    unpriced_calls: int = 0

    @property
    def calls(self) -> int:
        return sum(t.calls for t in self.tasks)

    def describe(self) -> str:
        if not self.tasks:
            return (
                f"nothing to recompile at level {self.level}: every active node is "
                "verified and current"
            )
        lines = [
            f"level {self.level}: {len(self.tasks)} node(s) to verify, "
            f"{self.calls} model call(s)"
            + (f", batched {self.batch} per call" if self.batch > 1 else ""),
            "",
        ]
        for task in self.tasks:
            parts = []
            if task.extract:
                parts.append("extract")
            if task.obligations:
                parts.append(f"{task.obligations} obligation(s)")
            if task.claims:
                parts.append(f"{task.claims} claim(s)")
            if task.panel:
                parts.append(f"{task.panel}-model whole-proof pass")
            if task.audit:
                parts.append("statement audit")
            cached = f", {task.cached} from cache" if task.cached else ""
            lines.append(
                f"  {task.node:<32} {task.reason:<22} {task.calls} call(s){cached}"
            )
            if parts:
                lines.append(f"  {'':<32} {'':<22} {', '.join(parts)}")
        lines.append("")
        if self.estimated_usd is not None and self.estimated_usd > 0:
            lines.append(f"estimated cost: ${self.estimated_usd:.2f}")
        if self.unpriced_calls:
            lines.append(
                f"{self.unpriced_calls} call(s) on a subscription backend, which "
                "reports no price — the call cap is what limits those"
            )
        lines.append(
            "confirmation calls are not included: they happen only for objections, "
            "and how many there will be is not knowable in advance"
        )
        return "\n".join(lines)


def needs_verification(node: Node) -> str | None:
    """Why this node would be re-verified, or None."""
    if node.global_status == BLOCKED_STALE:
        return "stale"
    if node.global_status == BLOCKED_UNVERIFIED:
        return "unverified"
    return None


def order(graph: Graph, node_ids: set[str]) -> list[str]:
    """Value ordering: path to the target first, then the frontier, then the rest.

    A partial run should leave the user closer to knowing about their theorem, not
    closer to knowing about an unrelated branch. Within the path to the target,
    shallow before deep, because a decomposition near the target may reshape
    everything under it. The frontier comes next because those are the nodes where
    work is actually possible right now; everything else is waiting on something.
    """
    depth = frontier_mod.depths(graph)
    on_frontier = {item.node: i for i, item in enumerate(frontier_mod.rank(graph))}

    def key(node_id: str) -> tuple[int, int, int, str]:
        if node_id in depth:
            return (0, depth[node_id], 0, node_id)
        if node_id in on_frontier:
            return (1, on_frontier[node_id], 0, node_id)
        return (2, 0, 0, node_id)

    return sorted(node_ids, key=key)


def plan(
    project: Project,
    *,
    registry: Registry | None = None,
    only: list[str] | None = None,
    level: str = verification.STANDARD,
    batch: int = 1,
) -> Plan:
    """What a recompile would do, without doing any of it."""
    registry = registry or Registry(project)
    jobs_at_level = verify_role.jobs_for(level)
    graph, _, swept = load_graph(project)
    if not swept:
        raise ops.OpError("the graph has a cycle; run `bp check` first")

    cache = verify_role.load_cache(project)
    candidates: set[str] = set()
    reasons: dict[str, str] = {}
    for node in graph.active.values():
        if only and node.id not in only:
            continue
        reason = needs_verification(node)
        if reason:
            candidates.add(node.id)
            reasons[node.id] = reason

    result = Plan(level=level, batch=max(1, batch))
    for node_id in order(graph, candidates):
        node = graph[node_id]
        task = Task(
            node=node_id,
            reason=reasons[node_id],
            level=level,
            batch=result.batch,
        )

        if "extract" in jobs_at_level and node.has_proof:
            # Extraction is skipped when the ledger already matches the proof on
            # file, because the ledger is a function of the proof text.
            if not node.claims or ledger_mod.ledger_is_stale(node):
                task.extract = 1
                _accumulate(
                    result,
                    registry,
                    "extractor",
                    (len(node.statement_section) + len(node.proof_section))
                    // CHARS_PER_TOKEN,
                    EXTRACT_OUTPUT_TOKENS,
                )

        if "obligations" in jobs_at_level:
            records = [
                r for r in obligations_for(node, graph) if r["kind"] != "admitted"
            ]
            task.obligations = len(records)
            task.obligations_cached = sum(1 for r in records if r["hash"] in cache)
            for record in records:
                if record["hash"] in cache:
                    continue
                _accumulate(
                    result,
                    registry,
                    "obligation",
                    len(verify_role.obligation_prompt(record)) // CHARS_PER_TOKEN,
                    OBLIGATION_OUTPUT_TOKENS,
                )

        if "claims" in jobs_at_level:
            records = ledger_mod.claim_obligations_for(node, graph)
            task.claims = len(records)
            task.claims_cached = sum(1 for r in records if r["hash"] in cache)
            for record in records:
                if record["hash"] in cache:
                    continue
                _accumulate(
                    result,
                    registry,
                    "obligation",
                    len(verify_role.claim_prompt(record)) // CHARS_PER_TOKEN,
                    CLAIM_OUTPUT_TOKENS,
                )

        if "whole_proof" in jobs_at_level and node.has_proof:
            size = (
                len(node.statement_section) + len(node.proof_section)
            ) // CHARS_PER_TOKEN
            for role in registry.config.panel:
                if role in registry.config.roles:
                    task.panel += 1
                    _accumulate(result, registry, role, size, PROOF_OUTPUT_TOKENS)

        if "audit" in jobs_at_level and node.statement_section.strip():
            task.audit = 1
            _accumulate(
                result,
                registry,
                "auditor",
                len(node.statement_section) // CHARS_PER_TOKEN,
                AUDIT_OUTPUT_TOKENS,
            )

        result.tasks.append(task)

    if result.unpriced_calls and not result.estimated_usd:
        # Every call is on a subscription backend: there is no dollar figure to
        # report, and reporting $0.00 would be a lie in the reassuring direction.
        result.estimated_usd = None
    return result


def _accumulate(
    result: Plan, registry: Registry, role: str, in_tokens: int, out_tokens: int
) -> None:
    try:
        agent = registry.agent(role)
    except Exception:
        return
    price = agent.estimate_usd(in_tokens, out_tokens)
    if price is None:
        result.unpriced_calls += 1
    elif result.estimated_usd is not None:
        result.estimated_usd += price


@dataclass
class RecompileResult:
    job: jobs.Job
    level: str = verification.STANDARD
    verified: list[str] = field(default_factory=list)
    flagged: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    stopped: str | None = None

    def describe(self) -> str:
        lines = [f"job {self.job.id}: {self.job.status} (level {self.level})"]
        if self.verified:
            lines.append(f"  verified: {', '.join(self.verified)}")
        if self.flagged:
            lines.append(f"  flagged:  {', '.join(self.flagged)}")
        if self.skipped:
            lines.append(f"  already done, skipped: {', '.join(self.skipped)}")
        if self.stopped:
            lines.append(f"  stopped: {self.stopped}")
            lines.append(f"  resume with: bp resume {self.job.id}")
        return "\n".join(lines)


def run(
    project: Project,
    *,
    registry: Registry | None = None,
    only: list[str] | None = None,
    job: jobs.Job | None = None,
    budget: Budget | None = None,
    level: str = verification.STANDARD,
    batch: int = 1,
) -> RecompileResult:
    """Verify every selected node, writing results as they land."""
    registry = registry or Registry(project)
    verify_role.jobs_for(level)  # reject an unknown level before spending anything
    if budget is not None:
        registry.budget = budget

    if job is None:
        prepared = plan(project, registry=registry, only=only, level=level, batch=batch)
        job = jobs.Job.create(
            project,
            "recompile",
            [t.id for t in prepared.tasks],
            {
                "only": only,
                "calls": prepared.calls,
                "level": level,
                "batch": max(1, batch),
            },
        )
    else:
        # Resuming: the level the run started at is part of the job, not of this
        # invocation. Finishing a `deep` run at `quick` would leave half the graph
        # claiming a scrutiny it did not get.
        level = job.params.get("level", level)
        batch = job.params.get("batch", batch)

    result = RecompileResult(job=job, level=level)
    for task_id in list(job.tasks):
        node_id = task_id.split(":", 1)[1]
        if job.is_done(task_id):
            result.skipped.append(node_id)
            continue
        try:
            report = verify_role.verify(
                project, node_id, registry=registry, level=level, batch=batch
            )
        except BudgetExceeded as exc:
            result.stopped = str(exc)
            job.finish(project, jobs.INTERRUPTED)
            return result
        except ops.OpError as exc:
            job.complete(project, task_id, f"{node_id}: skipped ({exc})")
            result.skipped.append(node_id)
            continue

        if report.verdict == "verified":
            result.verified.append(node_id)
        else:
            result.flagged.append(node_id)
        job.complete(project, task_id, f"{node_id}: {report.verdict}")

    ops.sweep_only(project)
    job.finish(project, jobs.DONE)
    return result


def resume(
    project: Project, job_id: str | None = None, *, registry: Registry | None = None
) -> RecompileResult:
    """Continue an interrupted run. Completed tasks are not re-queried."""
    job = (
        jobs.Job.load(project, job_id)
        if job_id
        else jobs.Job.latest_resumable(project)
    )
    if job is None:
        raise ops.OpError("no interrupted job to resume")
    job.status = jobs.RUNNING
    job.save(project)
    return run(project, registry=registry, job=job)
