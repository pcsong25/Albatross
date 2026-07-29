"""The call log, which is also the replay cache.

Every model call is written to ``.bp/agent/<prompt_hash>.json`` with its full
prompt and its full response. Two things fall out of that, and both matter more
than the disk they cost:

*Tests are free and offline.* ``--replay`` resolves calls from the log instead
of the network. A recorded session replays exactly, so the role logic can be
tested without a key, without a bill, and without flakiness.

*The bill is auditable.* When a run costs more than expected, the log says which
role asked what, and what came back.

A replay miss is a loud error, never a quiet fallback to the network: a replay
run that silently went online would stop being either reproducible or free, and
would do so without saying so.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from ..load import atomic_write
from ..paths import Project
from .base import Completion


class CallLog:
    """Content-addressed store of model calls, keyed by prompt hash."""

    def __init__(self, directory: Path, enabled: bool = True):
        self.directory = directory
        self.enabled = enabled

    @classmethod
    def for_project(cls, project: Project, enabled: bool = True) -> "CallLog":
        return cls(project.state_dir / "agent", enabled=enabled)

    def path_for(self, digest: str) -> Path:
        return self.directory / f"{digest}.json"

    def get(self, digest: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        path = self.path_for(digest)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def put(
        self,
        digest: str,
        *,
        role: str,
        backend: str,
        model: str,
        system: str,
        user: str,
        completion: Completion,
    ) -> Path:
        record = {
            "prompt_hash": digest,
            "role": role,
            "backend": backend,
            "model": model,
            "system": system,
            "user": user,
            "completion": completion.model_dump(),
        }
        path = self.path_for(digest)
        self.directory.mkdir(parents=True, exist_ok=True)
        atomic_write(path, json.dumps(record, indent=2, ensure_ascii=False) + "\n")
        return path

    def __len__(self) -> int:
        if not self.directory.is_dir():
            return 0
        return sum(1 for _ in self.directory.glob("*.json"))

    def __iter__(self) -> Iterator[dict[str, Any]]:
        if not self.directory.is_dir():
            return
        for path in sorted(self.directory.glob("*.json")):
            try:
                yield json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in self:
            key = f"{record.get('role') or '?'}/{record.get('model') or '?'}"
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))


class NullLog(CallLog):
    """A log that records nothing. Used when a caller explicitly opts out."""

    def __init__(self) -> None:
        super().__init__(Path("/dev/null"), enabled=False)

    def get(self, digest: str) -> dict[str, Any] | None:
        return None

    def put(self, digest: str, **kwargs: Any) -> Path:  # type: ignore[override]
        return self.directory
