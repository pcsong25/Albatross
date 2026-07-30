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
