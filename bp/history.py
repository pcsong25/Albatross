"""Previous versions of authored text.

This exists because of a hole in non-negotiable #3. *Nothing is destroyed* was true
of nodes — archiving replaces deletion, ``redo`` copies the subtree to
``attempts/`` first, the event log is append-only — and false of the two fields the
user actually writes. ``ops._edit_section`` recorded ``chars_before``: a *count*. So
the previous wording of a statement existed nowhere, and the most ordinary question
after an edit — *what did I just change?* — had no answer anywhere in the system.

It matters twice over. Once for the obvious reason: a mathematician tightening a
hypothesis at eleven at night should be able to see what it was. And once because
the amender (:mod:`bp.roles.amend`) is being asked *what does this edit imply for
the children*, which is a much sharper question when the diff is available than when
it has to be inferred from the children themselves.

Snapshots are state, not project content, so they live under ``.bp/history/``. They
are plain text with no header, so ``diff`` works on them directly. The metadata —
when, by whom, which hashes — belongs to the event that caused the edit, and the
event records the snapshot's path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import events
from .load import atomic_write
from .model import ID_RE, PROOF, STATEMENT
from .paths import Project

#: Which sections are snapshotted, and the filename stem each uses. The two
#: authored prose fields, which are the two that were being destroyed.
SECTIONS = {STATEMENT: "statement", PROOF: "proof"}

DIRNAME = "history"


def node_dir(project: Project, node_id: str) -> Path:
    """Where one node's snapshots live.

    ``ID_RE`` admits only ``[A-Za-z0-9._-]``, so an id is safe as a directory name —
    but this is a path built from a value that arrives from outside, so it is checked
    rather than assumed.
    """
    if not ID_RE.match(node_id):
        raise ValueError(f"not a node id: {node_id!r}")
    return project.state_dir / DIRNAME / node_id


@dataclass(frozen=True)
class Revision:
    """One superseded version of one section."""

    node: str
    section: str
    seq: int
    path: Path

    @property
    def text(self) -> str:
        return self.path.read_text(encoding="utf-8")

    @property
    def saved_at(self) -> str:
        """When this version stopped being current, from the file's mtime.

        In the reader's own time zone, because this is display and nothing compares
        it. The authoritative record of the edit is the event; this is here so
        ``bp revisions`` can print something useful without joining the two.
        """
        stamp = datetime.fromtimestamp(self.path.stat().st_mtime, tz=timezone.utc)
        return events.local(stamp.isoformat(timespec="seconds"))

    def describe(self) -> str:
        words = len(self.text.split())
        return f"{self.seq:>4}  {self.section.lower():<10} {self.saved_at}  {words} words"


def _slug(section: str) -> str:
    try:
        return SECTIONS[section]
    except KeyError:
        raise ValueError(
            f"{section!r} is not a snapshotted section; the snapshotted ones are "
            + ", ".join(sorted(SECTIONS))
        ) from None


def revisions(
    project: Project, node_id: str, section: str | None = None
) -> list[Revision]:
    """Every superseded version, oldest first."""
    directory = node_dir(project, node_id)
    if not directory.is_dir():
        return []
    wanted = {_slug(section)} if section else set(SECTIONS.values())
    inverse = {v: k for k, v in SECTIONS.items()}
    out: list[Revision] = []
    for path in sorted(directory.glob("*.tex")):
        stem = path.stem
        seq_text, _, slug = stem.partition("-")
        if slug not in wanted or not seq_text.isdigit():
            continue
        out.append(
            Revision(node=node_id, section=inverse[slug], seq=int(seq_text), path=path)
        )
    # Grouped by section, then oldest first within it. Interleaving the two by
    # sequence number reads as one history when it is two.
    return sorted(out, key=lambda r: (r.section, r.seq))


def snapshot(project: Project, node_id: str, section: str, text: str) -> Path | None:
    """Keep ``text`` — the version being *replaced* — and return where it went.

    Returns ``None`` when there is nothing worth keeping: an empty section, which is
    what the prover replaces on its first pass and which would otherwise fill the
    directory with empty files.
    """
    if not text.strip():
        return None
    slug = _slug(section)
    directory = node_dir(project, node_id)
    directory.mkdir(parents=True, exist_ok=True)
    seq = 1 + max(
        (r.seq for r in revisions(project, node_id, section)),
        default=0,
    )
    path = directory / f"{seq:04d}-{slug}.tex"
    # Atomic, like every other write in this system: a snapshot half-written by a
    # crash would be a version of the text that never existed.
    atomic_write(path, text if text.endswith("\n") else text + "\n")
    return path


def previous(project: Project, node_id: str, section: str) -> str | None:
    """The most recently superseded version of this section, or None."""
    mine = revisions(project, node_id, section)
    return mine[-1].text if mine else None


def relative(project: Project, path: Path) -> str:
    """A snapshot path as it should appear in an event payload."""
    try:
        return str(path.relative_to(project.root))
    except ValueError:  # pragma: no cover - a path from outside the project
        return str(path)


__all__ = [
    "DIRNAME",
    "Revision",
    "SECTIONS",
    "node_dir",
    "previous",
    "relative",
    "revisions",
    "snapshot",
]
