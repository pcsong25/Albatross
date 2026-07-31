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


#: The shipped example. It lives under ``examples/`` rather than at the repository
#: root so that the root is not itself a project — ``bp ui`` there used to open this
#: fixture as though it were live work, and a fresh clone looked like it shipped
#: somebody's half-finished paper.
EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "gclm"


@pytest.fixture
def fixture_project() -> Project:
    """The ten-node gCLM development shipped in ``examples/gclm/``.

    Illustrative and unverified — see its README. Two of its diagnostics are
    deliberate and are asserted by tests, so "fixing" the fixture breaks them.
    """
    return Project(EXAMPLE)


# --- L1 helpers ---------------------------------------------------------------


def scripted_registry(project: Project, log=None, **role_responses: Any):
    """A :class:`Registry` whose roles return canned replies.

    Roles not named get an empty script, so a role that makes an unexpected call
    fails loudly rather than reaching the network.
    """
    from bp.agents.log import NullLog
    from bp.agents.registry import Config, Registry, RoleConfig, ROLES

    roles = {}
    for role in ROLES:
        roles[role] = RoleConfig(
            backend="scripted",
            model=f"scripted-{role}",
            options={"responses": list(role_responses.get(role, []))},
        )
    config = Config(roles=roles)
    return Registry(project, config, log=log if log is not None else NullLog())


def json_reply(payload: Any, *, wrap: bool = False) -> str:
    """Serialise a scripted reply, optionally in the preamble+fence shape a CLI
    backend produces."""
    import json

    body = json.dumps(payload, ensure_ascii=False)
    if wrap:
        return f"Sure — here is the decomposition.\n\n```json\n{body}\n```\n\nHope that helps."
    return body
