"""Test helpers: build a throwaway project from node specs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from bp.load import compose
from bp.paths import Project

DEFAULTS: dict[str, Any] = {
    "role": "lemma",
    "children": [],
    "strategy": None,
    "difficulty": "unknown",
    "lifecycle": "active",
    "local_status": "unverified",
    "flags": [],
    "hypotheses": [],
    "uses": {},
}


def write_node(
    project: Project,
    node_id: str,
    *,
    statement: str = "A statement.",
    proof: str = "",
    notes: str = "",
    **frontmatter: Any,
) -> Path:
    meta: dict[str, Any] = {"id": node_id, **DEFAULTS, **frontmatter}
    body = f"## Statement\n\n{statement}\n\n## Proof\n\n{proof}\n\n## Notes\n\n{notes}"
    path = project.nodes_dir / f"{node_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(compose(meta, body), encoding="utf-8")
    return path


@pytest.fixture
def project(tmp_path: Path) -> Project:
    p = Project(tmp_path)
    p.nodes_dir.mkdir(parents=True, exist_ok=True)
    return p


@pytest.fixture
def fixture_project() -> Project:
    """The real six-node development shipped in ``nodes/``."""
    return Project(Path(__file__).resolve().parent.parent)
