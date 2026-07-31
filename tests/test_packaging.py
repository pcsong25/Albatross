"""What a built wheel actually contains.

Everything the program loads by path — the Jinja template, the role prompts, the
whole web interface, the default `bp.yaml` — is package *data*. Omit any of it from
`pyproject.toml` and the source checkout keeps working perfectly while every
installed copy is broken, which is the worst possible place for a bug to hide:
invisible to the person who wrote it, fatal for everyone else.

The first version shipped only `templates/*.j2`. A `pip install` of it had no web
interface (`bp ui` served nothing) and no prompts (every role raised "missing
prompt file"). Hence this file.

Building a wheel is slow-ish, so it happens once per session and the checks share
it.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

#: Every file the program opens at runtime by path. One entry per `read_text`,
#: `FileSystemLoader`, or `StaticFiles` mount that reaches into the package.
REQUIRED = [
    "bp/templates/document.tex.j2",   # render.document
    "bp/templates/bp.yaml",           # cli.init writes this into a new project
    "bp/roles/prompts/decompose.md",  # roles/context.load_prompt
    "bp/roles/prompts/check_reduction.md",
    "bp/roles/prompts/check_triviality.md",
    "bp/roles/prompts/extract.md",
    "bp/roles/prompts/verify_obligation.md",
    "bp/roles/prompts/verify_claim.md",
    "bp/roles/prompts/verify_proof.md",
    "bp/roles/prompts/verify_confirm.md",
    "bp/roles/prompts/audit.md",
    "bp/roles/prompts/prove.md",
    "bp/roles/prompts/tidy_latex.md",
    "bp/ui/static/index.html",        # ui.app.index
    "bp/ui/static/app.js",            # the StaticFiles mount
    "bp/ui/static/style.css",
]


@pytest.fixture(scope="session")
def wheel_contents(tmp_path_factory) -> set[str]:
    out = tmp_path_factory.mktemp("wheel")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "wheel", str(REPO), "--no-deps", "-w", str(out)],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover
        pytest.skip(f"could not build a wheel: {exc}")
    wheels = list(out.glob("*.whl"))
    if not wheels:  # pragma: no cover
        pytest.skip(f"pip wheel produced nothing:\n{result.stdout}\n{result.stderr}")
    with zipfile.ZipFile(wheels[0]) as z:
        return set(z.namelist())


class TestWheel:
    @pytest.mark.parametrize("path", REQUIRED)
    def test_every_runtime_file_is_shipped(self, path, wheel_contents):
        assert path in wheel_contents, (
            f"{path} is loaded at runtime but is not in the wheel. Add its "
            "directory to [tool.setuptools.package-data] in pyproject.toml."
        )

    def test_every_prompt_on_disk_is_shipped(self, wheel_contents):
        """Not just the ones this file happens to list: a prompt added later must
        ship too, and nobody will remember to update REQUIRED."""
        on_disk = {
            f"bp/roles/prompts/{p.name}"
            for p in (REPO / "bp" / "roles" / "prompts").glob("*.md")
        }
        assert on_disk
        assert on_disk <= wheel_contents

    def test_every_static_asset_is_shipped(self, wheel_contents):
        on_disk = {
            f"bp/ui/static/{p.name}"
            for p in (REPO / "bp" / "ui" / "static").iterdir()
            if p.is_file()
        }
        assert on_disk
        assert on_disk <= wheel_contents


class TestShippedConfig:
    def test_the_default_config_parses_and_names_every_role(self):
        """`bp init` copies this file. If it does not load, a new project starts
        broken and the message is about YAML rather than about anything the user
        did."""
        from bp.agents.registry import ROLES, Config, DEFAULT_ROLES
        from ruamel.yaml import YAML

        text = (REPO / "bp" / "templates" / "bp.yaml").read_text(encoding="utf-8")
        data = YAML(typ="safe").load(text)
        roles = dict(DEFAULT_ROLES)
        roles.update(data["agents"]["roles"])
        config = Config(
            roles=roles, budget=data.get("budget") or {}, pricing=data.get("pricing") or {}
        )
        for role in ROLES:
            assert role in config.roles, f"the shipped bp.yaml does not configure {role}"

    def test_the_default_config_does_not_assume_a_subscription_cli(self):
        """A new user is far more likely to have an API key than a Codex login, and
        a default that cannot run is a default that teaches nothing."""
        text = (REPO / "bp" / "templates" / "bp.yaml").read_text(encoding="utf-8")
        assert "backend: claude_api" in text
        # Commented guidance about the other backends is welcome; configured
        # roles pointing at them are not.
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "codex_cli" not in stripped
            assert "scripted" not in stripped

    def test_it_warns_about_putting_both_verifiers_on_one_family(self):
        text = (REPO / "bp" / "templates" / "bp.yaml").read_text(encoding="utf-8")
        assert "DIFFERENT MODEL FAMILIES" in text.upper()


class TestTheRepositoryRootIsNotAProject:
    """The example used to live at the repository root, which meant `bp ui` there
    opened it as though it were live work, and a fresh clone looked like it shipped
    somebody's half-finished paper. Guarded, because moving it back would be easy to
    do by accident.
    """

    def test_the_root_has_no_nodes_directory(self):
        assert not (REPO / "nodes").exists()

    def test_project_discovery_refuses_at_the_root(self):
        from bp.paths import ProjectNotFound, find_project

        with pytest.raises(ProjectNotFound):
            find_project(REPO)

    def test_the_example_is_a_project(self):
        from bp.paths import find_project

        project = find_project(REPO / "examples" / "gclm")
        assert project.root == REPO / "examples" / "gclm"
        assert project.nodes_dir.is_dir()

    def test_the_example_says_it_is_unverified(self):
        """A fixture of plausible-looking mathematics needs to say so where a reader
        will see it, not only in a commit message."""
        readme = (REPO / "examples" / "gclm" / "README.md").read_text(encoding="utf-8")
        lowered = readme.lower()
        assert "not verified mathematics" in lowered
        assert "test fixture" in lowered
        assert "deliberately" in lowered

    def test_the_example_is_not_packaged(self):
        """It is documentation, not code: it must not land in a wheel."""
        from pathlib import Path

        import tomllib

        config = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
        include = config["tool"]["setuptools"]["packages"]["find"]["include"]
        assert include == ["bp*"]
        assert not any("example" in pattern for pattern in include)
