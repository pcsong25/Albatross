"""Where things live.

A *project* is a directory containing ``nodes/``. Everything the system writes
that is not a node lives under ``.bp/``. Commands find the project by walking up
from the working directory, the way ``git`` finds its repository, so you can run
``bp`` from anywhere inside it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

NODES_DIRNAME = "nodes"
STATE_DIRNAME = ".bp"
ENV_ROOT = "BP_ROOT"


class ProjectNotFound(Exception):
    pass


@dataclass(frozen=True)
class Project:
    root: Path

    @property
    def nodes_dir(self) -> Path:
        return self.root / NODES_DIRNAME

    @property
    def state_dir(self) -> Path:
        return self.root / STATE_DIRNAME

    @property
    def events_path(self) -> Path:
        return self.state_dir / "events.jsonl"

    @property
    def preamble_path(self) -> Path:
        """The user's own LaTeX preamble: macros, \\newcommands, packages.

        Optional. When present it is injected into the rendered document, shown
        to every agent as context, and parsed into KaTeX macros by the browser —
        so a statement written in the user's own notation reads correctly in all
        three places instead of only in their head.
        """
        return self.root / "preamble.tex"

    @property
    def attempts_dir(self) -> Path:
        """Where ``bp redo`` parks a subtree before regenerating it (L1)."""
        return self.root / "attempts"

    @property
    def build_dir(self) -> Path:
        return self.state_dir / "build"

    @property
    def paper_dir(self) -> Path:
        """Where the agent-written exposition is kept.

        Under ``.bp/`` rather than beside ``nodes/`` on purpose: it is a build
        artifact, not part of the project. The development is the source of truth
        and is regenerated from the node files every time; the paper is written
        once, when asked, and goes out of date the moment a node changes — which
        is why the draft is stored with the hashes it was written from.
        """
        return self.state_dir / "paper"

    def ensure_state(self) -> Path:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        return self.state_dir


def find_project(start: Path | str | None = None) -> Project:
    """Locate the project root.

    ``$BP_ROOT`` wins if set. Otherwise walk up from ``start`` (default: the
    working directory) looking for a ``nodes/`` directory.
    """
    env = os.environ.get(ENV_ROOT)
    if env:
        root = Path(env).expanduser().resolve()
        if not (root / NODES_DIRNAME).is_dir():
            raise ProjectNotFound(f"{ENV_ROOT}={root} has no {NODES_DIRNAME}/ directory")
        return Project(root)

    here = Path(start).resolve() if start else Path.cwd().resolve()
    if here.is_file():
        here = here.parent
    for candidate in [here, *here.parents]:
        if (candidate / NODES_DIRNAME).is_dir():
            return Project(candidate)
    raise ProjectNotFound(
        f"no {NODES_DIRNAME}/ directory in {here} or any parent; "
        f"run bp from inside a project, or set {ENV_ROOT}"
    )
