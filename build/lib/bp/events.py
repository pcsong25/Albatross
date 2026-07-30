"""The event log.

``.bp/events.jsonl`` is append-only and fsynced on every append. Nothing in the
system rewrites or truncates it. It exists so that the question "how did this
node get into this state?" always has an answer, and so that a mistake is
recoverable by reading rather than by memory.

v0 does not fold state from events — the node files are the state, and the log is
the history. That is the deliberate simplification; ``DESIGN.md`` §6 describes
the fold, and rebuilding it later needs only this file to have been honest all
along, which is why it is written from the first milestone.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Iterator

from .paths import Project


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append(
    project: Project,
    kind: str,
    node: str | None = None,
    payload: dict[str, Any] | None = None,
    actor: str = "human",
) -> dict[str, Any]:
    """Record one event. Returns the record as written."""
    event = {
        "uuid": str(uuid.uuid4()),
        "ts": now(),
        "kind": kind,
        "node": node,
        "actor": actor,
        "payload": payload or {},
    }
    project.ensure_state()
    line = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
    fd = os.open(project.events_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return event


def read(project: Project) -> list[dict[str, Any]]:
    return list(iter_events(project))


def iter_events(project: Project) -> Iterator[dict[str, Any]]:
    path = project.events_path
    if not path.exists():
        return
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                yield {
                    "uuid": None,
                    "ts": None,
                    "kind": "unreadable",
                    "node": None,
                    "actor": "system",
                    "payload": {"line": lineno, "text": line},
                }


def describe(event: dict[str, Any]) -> str:
    """One human-readable line. The History panel in L2 renders these."""
    node = event.get("node") or "-"
    kind = event.get("kind", "?")
    payload = event.get("payload") or {}
    detail = ""
    if kind == "add_node":
        detail = f"role={payload.get('role')}"
    elif kind in {"edit_statement", "edit_proof"}:
        detail = f"{payload.get('chars_before', '?')} -> {payload.get('chars_after', '?')} chars"
        if payload.get("stale_radius"):
            detail += f", staled {len(payload['stale_radius'])}"
    elif kind == "set_children":
        detail = f"{payload.get('before')} -> {payload.get('after')}"
    elif kind in {"admit", "set_assumption"}:
        detail = payload.get("reason", "")
    elif kind == "relabel":
        detail = f"{payload.get('before')} -> {payload.get('after')}"
    elif kind == "archive":
        detail = ", ".join(payload.get("nodes", []))
    elif kind == "add_note":
        detail = (payload.get("text") or "")[:60]
    elif kind == "verify":
        detail = f"verdict={payload.get('verdict')}"
    return f"{event.get('ts')}  {kind:<16} {node:<28} {detail}".rstrip()
