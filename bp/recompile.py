"""``bp recompile`` — re-verify what needs it, then sweep.

A naive recompile re-runs the model tier over everything and becomes too
expensive to press. This one verifies only nodes that are **stale** or
**unverified with a proof**, and within that, works in an order that makes a
partial run useful: the path to the target first, shallow before deep.

Three properties matter more than the selection rule:

*The bill is previewable.* ``--dry-run`` lists the calls it would make and what
they would cost, before any of them happen. A budget you can only discover by
spending it is not a budget.

*Results write as they land.* Each node's verdict goes through ``ops`` as soon
as it is reached, so an interrupted run keeps everything it paid for.

*Resuming performs no duplicate paid work.* The job record names the completed
tasks; the obligation cache means even a task that is re-entered mostly hits
cache rather than the network.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import jobs, ops
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
PROOF_OUTPUT_TOKENS = 900
CONFIRM_OUTPUT_TOKENS = 150


@dataclass
class Task:
    node: str
    reason: str
    obligations: int
    cached: int
    panel: int

    @property
    def id(self) -> str:
        return f"verify:{self.node}"

    @property
    def calls(self) -> int:
        """Calls this task would make. Confirmation calls are unknowable in
        advance — they happen only for objections — so they are not counted, and
        the estimate says so rather than inventing a number."""
        return (self.obligations - self.cached) + self.panel


@dataclass
class Plan:
    tasks: list[Task] = field(default_factory=list)
    estimated_usd: float | None = 0.0
    unpriced_calls: int = 0

    @property
    def calls(self) -> int:
        return sum(t.calls for t in self.tasks)

    def describe(self) -> str:
        if not self.tasks:
            return "nothing to recompile: every active node is verified and current"
        lines = [f"{len(self.tasks)} node(s) to verify, {self.calls} model call(s):", ""]
        for task in self.tasks:
            cached = f", {task.cached} obligation(s) from cache" if task.cached else ""
            lines.append(
                f"  {task.node:<32} {task.reason:<22} "
                f"{task.calls} call(s){cached}"
            )
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
    """Path-to-target first, shallow before deep, then everything else.

    A partial run should leave the user closer to knowing about their theorem,
    not closer to knowing about an unrelated branch.
    """
    depth: dict[str, int] = {}
    target = graph.target
    if target is not None:
        frontier = [(target.id, 0)]
        while frontier:
            current, d = frontier.pop(0)
            if current in depth and depth[current] <= d:
                continue
            depth[current] = d
            node = graph.active.get(current)
            if node is None:
                continue
            frontier.extend((c, d + 1) for c in node.children if c in graph.active)
    return sorted(node_ids, key=lambda n: (depth.get(n, 10**6), n))


def plan(
    project: Project,
    *,
    registry: Registry | None = None,
    only: list[str] | None = None,
) -> Plan:
    """What a recompile would do, without doing any of it."""
    registry = registry or Registry(project)
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

    result = Plan()
    for node_id in order(graph, candidates):
        node = graph[node_id]
        records = [r for r in obligations_for(node, graph) if r["kind"] != "admitted"]
        cached = sum(1 for r in records if r["hash"] in cache)
        panel = sum(
            1
            for role in ("verifier_a", "verifier_b")
            if role in registry.config.roles
        )
        task = Task(
            node=node_id,
            reason=reasons[node_id],
            obligations=len(records),
            cached=cached,
            panel=panel if node.has_proof else 0,
        )
        result.tasks.append(task)

        # Price it from the prompts that would actually be sent.
        for record in records:
            if record["hash"] in cache:
                continue
            _accumulate(
                result,
                registry,
                "verifier_a",
                len(verify_role.obligation_prompt(record)) // CHARS_PER_TOKEN,
                OBLIGATION_OUTPUT_TOKENS,
            )
        if node.has_proof:
            size = (len(node.statement_section) + len(node.proof_section)) // CHARS_PER_TOKEN
            for role in ("verifier_a", "verifier_b"):
                if role in registry.config.roles:
                    _accumulate(result, registry, role, size, PROOF_OUTPUT_TOKENS)

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
    verified: list[str] = field(default_factory=list)
    flagged: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    stopped: str | None = None

    def describe(self) -> str:
        lines = [f"job {self.job.id}: {self.job.status}"]
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
) -> RecompileResult:
    """Verify every selected node, writing results as they land."""
    registry = registry or Registry(project)
    if budget is not None:
        registry.budget = budget

    if job is None:
        prepared = plan(project, registry=registry, only=only)
        job = jobs.Job.create(
            project,
            "recompile",
            [t.id for t in prepared.tasks],
            {"only": only, "calls": prepared.calls},
        )

    result = RecompileResult(job=job)
    for task_id in list(job.tasks):
        node_id = task_id.split(":", 1)[1]
        if job.is_done(task_id):
            result.skipped.append(node_id)
            continue
        try:
            report = verify_role.verify(project, node_id, registry=registry)
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
