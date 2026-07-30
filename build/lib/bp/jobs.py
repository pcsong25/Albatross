"""Job records, so an interrupted run loses at most one task.

Any multi-step operation writes a record before doing any work, and updates it
after each task completes. The requirement is specific: token exhaustion, a
dropped network, ``Ctrl-C`` or a crash should cost at most the task that was in
flight, and resuming must perform **no duplicate paid work**.

Task granularity is one node's verification — fine enough that losing one is
cheap. The obligation cache means resumption is often nearly free even without
the job record; the record is what makes it reliable rather than lucky.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .load import atomic_write
from .paths import Project

RUNNING = "running"
DONE = "done"
INTERRUPTED = "interrupted"


def jobs_dir(project: Project) -> Path:
    return project.state_dir / "jobs"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Job:
    id: str
    kind: str
    params: dict[str, Any] = field(default_factory=dict)
    tasks: list[str] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    status: str = RUNNING
    started_at: str = ""
    finished_at: str | None = None
    notes: list[str] = field(default_factory=list)

    # --- persistence ---------------------------------------------------------

    def path(self, project: Project) -> Path:
        return jobs_dir(project) / f"{self.id}.json"

    def save(self, project: Project) -> Path:
        path = self.path(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(
            path,
            json.dumps(
                {
                    "id": self.id,
                    "kind": self.kind,
                    "params": self.params,
                    "tasks": self.tasks,
                    "completed": self.completed,
                    "status": self.status,
                    "started_at": self.started_at,
                    "finished_at": self.finished_at,
                    "notes": self.notes,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
        )
        return path

    @classmethod
    def create(
        cls, project: Project, kind: str, tasks: list[str], params: dict[str, Any] | None = None
    ) -> "Job":
        job = cls(
            id=f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}",
            kind=kind,
            params=params or {},
            tasks=list(tasks),
            started_at=_now(),
        )
        job.save(project)
        return job

    @classmethod
    def load(cls, project: Project, job_id: str) -> "Job":
        path = jobs_dir(project) / f"{job_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"no job {job_id!r} in {jobs_dir(project)}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**data)

    @classmethod
    def all(cls, project: Project) -> list["Job"]:
        directory = jobs_dir(project)
        if not directory.is_dir():
            return []
        out = []
        for path in sorted(directory.glob("*.json")):
            try:
                out.append(cls(**json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError, TypeError):
                continue
        return out

    @classmethod
    def latest_resumable(cls, project: Project) -> "Job | None":
        for job in reversed(cls.all(project)):
            if job.status != DONE and job.pending:
                return job
        return None

    # --- progress ------------------------------------------------------------

    @property
    def pending(self) -> list[str]:
        done = set(self.completed)
        return [t for t in self.tasks if t not in done]

    def is_done(self, task: str) -> bool:
        return task in set(self.completed)

    def complete(self, project: Project, task: str, note: str | None = None) -> None:
        """Mark one task done and persist immediately.

        Written after *every* task, not at the end. The whole point is that the
        file on disk is always at least as current as the paid work done.
        """
        if task not in set(self.completed):
            self.completed.append(task)
        if note:
            self.notes.append(note)
        self.save(project)

    def finish(self, project: Project, status: str = DONE) -> None:
        self.status = status
        self.finished_at = _now()
        self.save(project)

    def describe(self) -> str:
        return (
            f"{self.id}  {self.kind:<10} {self.status:<12} "
            f"{len(self.completed)}/{len(self.tasks)} task(s)  started {self.started_at}"
        )
