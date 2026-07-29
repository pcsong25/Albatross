"""Background jobs for the web interface.

A decomposition takes minutes through a subscription CLI. If an HTTP handler ran
one inline, the browser would sit on a dead socket and the user would not know
whether anything was happening — so role calls run on a worker thread, the
request returns a job id immediately, and the page polls.

Two things this deliberately does *not* try to be:

*It is not durable.* Job state lives in memory for the life of the server
process. Durability is already handled where it matters: results are written
through :mod:`bp.ops` as they land, `.bp/jobs/` records recompile progress, and
the call log means a re-run is mostly cache hits. Persisting the UI's own
spinner would add a second source of truth about work the graph already records.

*It is not a queue with a global lock.* One worker thread means one role call at
a time, and :func:`bp.ops.serialised` orders individual mutations — but a job
does **not** hold a lock across its whole body. Doing that froze every edit in
the interface for the minutes a decomposition takes, including edits to nodes the
job would never touch. Operations that would genuinely conflict are refused by
the endpoint, with the node's name in the message.
"""

from __future__ import annotations

import threading
import traceback
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"

#: How many finished jobs to keep for the history panel.
KEEP = 60


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Job:
    id: str
    kind: str
    node: str | None
    status: str = QUEUED
    #: What is happening right now, named so the user can see which agent is
    #: working rather than watching an anonymous spinner.
    step: str = "waiting for the worker"
    calls: int = 0
    started_at: str = field(default_factory=_now)
    finished_at: str | None = None
    result: Any = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "node": self.node,
            "status": self.status,
            "step": self.step,
            "calls": self.calls,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "error": self.error,
        }


class JobRunner:
    """One worker thread and a job table. Ordering of writes is bp.ops's job."""

    def __init__(self) -> None:
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bp-job")
        self._jobs: "OrderedDict[str, Job]" = OrderedDict()
        self._lock = threading.Lock()

    # --- inspection ----------------------------------------------------------

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    @property
    def active(self) -> list[Job]:
        return [j for j in self.all() if j.status in (QUEUED, RUNNING)]

    def busy_nodes(self) -> set[str]:
        return {j.node for j in self.active if j.node}

    # --- running -------------------------------------------------------------

    def submit(
        self,
        kind: str,
        node: str | None,
        work: Callable[["Job"], Any],
    ) -> Job:
        job = Job(id=uuid.uuid4().hex[:10], kind=kind, node=node)
        with self._lock:
            self._jobs[job.id] = job
            while len(self._jobs) > KEEP:
                oldest = next(iter(self._jobs))
                if self._jobs[oldest].status in (QUEUED, RUNNING):
                    break
                self._jobs.pop(oldest)
        self._pool.submit(self._run, job, work)
        return job

    def _run(self, job: Job, work: Callable[["Job"], Any]) -> None:
        job.status = RUNNING
        job.step = "starting"
        try:
            # No lock is held here. A decomposition runs for minutes, and holding
            # a write lock across it would freeze every edit in the interface —
            # including edits to nodes the job will never touch. Ordering is
            # handled where it belongs, per mutation, by `bp.ops.serialised`;
            # conflicting *operations* are refused by the endpoint instead.
            job.result = work(job)
            job.status = DONE
            job.step = "finished"
        except Exception as exc:  # noqa: BLE001 - the message is the product here
            job.status = FAILED
            job.step = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
            job.traceback = traceback.format_exc()  # type: ignore[attr-defined]
        finally:
            job.finished_at = _now()

    def shutdown(self) -> None:  # pragma: no cover - process teardown
        self._pool.shutdown(wait=False)


def progress(job: Job) -> Callable[[str, str, str], None]:
    """An observer for :class:`bp.agents.registry.Registry`.

    The agent layer calls this before every model call, which is how the page
    can say "verifier_a (opus) — checking an obligation" instead of showing an
    anonymous spinner for four minutes.
    """

    def observe(role: str, model: str, phase: str) -> None:
        if phase == "start":
            job.calls += 1
            job.step = f"{role} ({model}) — call {job.calls}"
        elif phase == "replay":
            job.step = f"{role} ({model}) — replayed from the log"

    return observe
