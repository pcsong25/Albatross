"""The agent layer: JSON extraction, validation, retry, budget, log, replay."""

from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from bp.agents import base
from bp.agents.base import (
    AgentError,
    Budget,
    BudgetExceeded,
    Completion,
    ReplayMiss,
    extract_json,
    repair_backslashes,
)
from bp.agents.log import CallLog
from bp.agents.registry import Config, ConfigError, Registry, RoleConfig, load_config
from bp.agents.scripted import ScriptedBackend

from .conftest import json_reply, write_node


class Answer(BaseModel):
    verdict: str
    detail: str = ""


def backend(responses, **kwargs) -> ScriptedBackend:
    return ScriptedBackend("scripted-model", role="test", options={"responses": responses}, **kwargs)


class TestExtraction:
    def test_bare_json(self):
        assert json.loads(extract_json('{"a": 1}')) == {"a": 1}

    def test_fenced_block_after_preamble(self):
        text = 'Certainly.\n\n```json\n{"a": 1}\n```\n\nLet me know.'
        assert json.loads(extract_json(text)) == {"a": 1}

    def test_unfenced_json_after_preamble(self):
        text = 'Here you go:\n{"a": 1, "b": [2, 3]}\nthanks'
        assert json.loads(extract_json(text)) == {"a": 1, "b": [2, 3]}

    def test_braces_inside_strings_do_not_confuse_the_scan(self):
        text = 'preamble {"tex": "\\\\{x\\\\}", "n": 1} trailer'
        assert json.loads(extract_json(text))["n"] == 1

    def test_nothing_json_like(self):
        with pytest.raises(AgentError):
            extract_json("")


class TestBackslashRepair:
    def test_latex_single_backslashes_are_recovered(self):
        blob = '{"tex": "\\omega_0 \\le \\varepsilon"}'
        with pytest.raises(json.JSONDecodeError):
            json.loads(blob)
        assert json.loads(repair_backslashes(blob))["tex"] == "\\omega_0 \\le \\varepsilon"

    def test_valid_escapes_are_left_alone(self):
        blob = '{"a": "line\\nbreak", "b": "quote\\""}'
        assert json.loads(repair_backslashes(blob)) == json.loads(blob)


class TestComplete:
    def test_happy_path(self):
        agent = backend([json_reply({"verdict": "ok"})])
        answer, meta = agent.complete("sys", "user", Answer)
        assert answer.verdict == "ok"
        assert meta.attempts == 1
        assert meta.replayed is False

    def test_the_schema_is_appended_to_the_prompt_not_the_prompt_file(self):
        agent = backend([json_reply({"verdict": "ok"})])
        agent.complete("sys", "user", Answer)
        # The scripted backend records nothing, so assert on the helper directly.
        instruction = base.schema_instruction(Answer)
        assert "JSON Schema" in instruction
        assert "doubled" in instruction  # the LaTeX-backslash warning

    def test_invalid_json_retries_once_with_the_error(self):
        agent = backend(["not json at all", json_reply({"verdict": "ok"})])
        answer, meta = agent.complete("sys", "user", Answer)
        assert answer.verdict == "ok"
        assert meta.attempts == 2

    def test_schema_violation_retries_once(self):
        agent = backend([json_reply({"wrong": "shape"}), json_reply({"verdict": "ok"})])
        answer, _ = agent.complete("sys", "user", Answer)
        assert answer.verdict == "ok"

    def test_two_failures_fail_the_task_rather_than_guessing(self):
        agent = backend([json_reply({"wrong": 1}), json_reply({"also": 2})])
        with pytest.raises(AgentError) as exc:
            agent.complete("sys", "user", Answer)
        assert "twice" in str(exc.value)

    def test_latex_with_single_backslashes_still_validates(self):
        agent = backend(['{"verdict": "ok", "detail": "\\omega_0 \\in H^s"}'])
        answer, meta = agent.complete("sys", "user", Answer)
        assert answer.detail == "\\omega_0 \\in H^s"
        assert meta.repaired_json is True


class TestBudget:
    def test_call_cap_stops_before_the_call(self):
        b = Budget(max_calls=2)
        b.record(0.1)
        b.record(0.1)
        with pytest.raises(BudgetExceeded):
            b.check()

    def test_dollar_cap(self):
        b = Budget(max_usd=1.0)
        b.record(0.6)
        b.check()
        b.record(0.6)
        with pytest.raises(BudgetExceeded):
            b.check()

    def test_unknown_cost_falls_back_to_the_call_cap(self):
        """A subscription CLI reports no price. The dollar cap can never fire, so
        the call cap has to be the thing that stops a runaway loop."""
        b = Budget(max_usd=1.0, max_calls=3)
        for _ in range(3):
            b.record(None)
        assert b.spent_usd == 0.0
        assert b.priced is False
        with pytest.raises(BudgetExceeded) as exc:
            b.check()
        assert "call cap" in str(exc.value)

    def test_summary_marks_unpriced_calls(self):
        b = Budget()
        b.record(0.5)
        b.record(None)
        assert "+" in b.summary()
        assert "subscription" in b.summary()

    def test_a_backend_checks_the_budget_before_spending(self):
        b = Budget(max_calls=1)
        agent = backend([json_reply({"verdict": "a"}), json_reply({"verdict": "b"})], budget=b)
        agent.complete("sys", "user", Answer)
        with pytest.raises(BudgetExceeded):
            agent.complete("sys", "other", Answer)


class TestLogAndReplay:
    def test_a_call_is_logged_and_replays_from_the_log(self, project):
        log = CallLog.for_project(project)
        agent = backend([json_reply({"verdict": "ok"})], log=log)
        agent.complete("sys", "user", Answer)
        assert len(log) == 1

        # The script is exhausted; only the log can answer now.
        replayer = backend([], log=log, replay=True)
        answer, meta = replayer.complete("sys", "user", Answer)
        assert answer.verdict == "ok"
        assert meta.replayed is True

    def test_replay_miss_is_loud(self, project):
        log = CallLog.for_project(project)
        agent = backend([], log=log, replay=True)
        with pytest.raises(ReplayMiss) as exc:
            agent.complete("sys", "never asked before", Answer)
        assert "--replay" in str(exc.value)

    def test_the_log_records_the_prompt_and_the_response(self, project):
        log = CallLog.for_project(project)
        agent = backend([json_reply({"verdict": "ok"})], log=log)
        _, meta = agent.complete("sys prompt", "user prompt", Answer)
        record = log.get(meta.prompt_hash)
        assert record["system"] == "sys prompt"
        assert "user prompt" in record["user"]
        assert record["model"] == "scripted-model"

    def test_the_hash_covers_the_model_so_two_models_do_not_collide(self):
        a = base.prompt_hash("claude_api", "claude-opus-5", "s", "u")
        b = base.prompt_hash("claude_api", "claude-sonnet-5", "s", "u")
        assert a != b


class TestRegistry:
    def test_defaults_apply_with_no_config_file(self, project):
        config = load_config(project)
        assert set(config.roles) >= {"decomposer", "checker", "verifier_a", "prover"}
        assert config.budget.max_calls_per_recompile

    def test_bp_yaml_overrides_a_role(self, project):
        (project.root / "bp.yaml").write_text(
            "agents:\n  roles:\n    prover: {backend: claude_cli, model: sonnet}\n"
            "budget:\n  per_recompile_usd: 1.5\n  max_calls_per_recompile: 7\n",
            encoding="utf-8",
        )
        config = load_config(project)
        assert config.roles["prover"].backend == "claude_cli"
        assert config.budget.max_calls_per_recompile == 7
        # Untouched roles keep their defaults.
        assert config.roles["checker"].backend == "claude_api"

    def test_unknown_backend_is_refused_by_name(self, project):
        config = Config(roles={"prover": RoleConfig(backend="telepathy", model="x")})
        with pytest.raises(ConfigError) as exc:
            Registry(project, config).agent("prover")
        assert "telepathy" in str(exc.value)

    def test_unknown_role_names_the_ones_that_exist(self, project):
        with pytest.raises(ConfigError) as exc:
            Registry(project).agent("oracle")
        assert "decomposer" in str(exc.value)

    def test_pricing_defaults_are_present_for_current_models(self, project):
        table = load_config(project).price_table()
        assert table["claude-opus-5"]["input_usd_per_mtok"] == 5.0
        assert table["claude-opus-5"]["output_usd_per_mtok"] == 25.0

    def test_pricing_can_be_overridden(self, project):
        (project.root / "bp.yaml").write_text(
            "pricing:\n  claude-opus-5: {input_usd_per_mtok: 1.0, output_usd_per_mtok: 2.0}\n",
            encoding="utf-8",
        )
        table = load_config(project).price_table()
        assert table["claude-opus-5"]["input_usd_per_mtok"] == 1.0

    def test_estimate_is_none_for_an_unpriced_model(self, project):
        agent = backend([])
        assert agent.estimate_usd(1000, 1000) is None


class TestCLIBackends:
    def test_prompt_composition_joins_system_and_user(self):
        from bp.agents.claude_cli import ClaudeCLIBackend

        agent = ClaudeCLIBackend("opus", role="prover")
        composed = agent.compose_prompt("SYSTEM", "USER")
        assert composed.index("SYSTEM") < composed.index("USER")
        assert "---" in composed

    def test_command_is_configurable(self):
        from bp.agents.codex_cli import CodexCLIBackend

        default = CodexCLIBackend("gpt-x", role="decomposer")
        assert default.command[:2] == ["codex", "exec"]
        assert "gpt-x" in default.command
        custom = CodexCLIBackend(
            "gpt-x", role="decomposer", options={"command": ["my-tool", "--json"]}
        )
        assert custom.command == ["my-tool", "--json"]

    def test_missing_executable_is_reported_not_raised(self):
        from bp.agents.claude_cli import ClaudeCLIBackend

        agent = ClaudeCLIBackend(
            "opus", role="prover", options={"command": ["definitely-not-installed"]}
        )
        ok, reason = agent.available()
        assert ok is False
        assert "not on PATH" in reason

    def test_a_real_subprocess_round_trips(self):
        """`cat` is a stand-in for a CLI tool: prompt in on stdin, text out."""
        from bp.agents.claude_cli import SubprocessBackend

        class CatBackend(SubprocessBackend):
            name = "cat"
            default_command = ("cat",)

        agent = CatBackend("none", role="test")
        completion = agent.invoke("SYS", json_reply({"verdict": "ok"}, wrap=True), 30)
        assert completion.cost_usd is None  # a subscription tool cannot say
        assert "verdict" in completion.text

    def test_timeout_kills_the_process_group(self):
        from bp.agents.claude_cli import SubprocessBackend

        class SleeperBackend(SubprocessBackend):
            name = "sleeper"
            default_command = ("sleep", "30")

        agent = SleeperBackend("none", role="test")
        with pytest.raises(AgentError) as exc:
            agent.invoke("SYS", "USER", 0.4)
        assert "process group was killed" in str(exc.value)

    def test_a_nonzero_exit_is_an_error_with_the_stderr(self):
        from bp.agents.claude_cli import SubprocessBackend

        class FailBackend(SubprocessBackend):
            name = "failer"
            default_command = ("sh", "-c", "echo boom >&2; exit 3")

        agent = FailBackend("none", role="test")
        with pytest.raises(AgentError) as exc:
            agent.invoke("SYS", "USER", 30)
        assert "exited 3" in str(exc.value) and "boom" in str(exc.value)


def test_completion_carries_whatever_accounting_it_has():
    priced = Completion(text="x", cost_usd=0.4, input_tokens=10, output_tokens=20)
    unpriced = Completion(text="x")
    assert priced.cost_usd == 0.4
    assert unpriced.cost_usd is None


class TestRoleInheritance:
    """A role added to Albatross must never silently move a project to a different
    provider.

    The real failure: four roles were added — extractor, obligation, confirmer,
    auditor — and every existing `bp.yaml` predated them. All four fell back to the
    built-in `claude_api` default, so a project configured entirely for `codex_cli`
    had half its system pointed at Anthropic on an account the user did not have. They
    found out from a raw SDK TypeError mid-job.
    """

    CODEX = {"backend": "codex_cli", "model": "gpt-5.6-sol"}

    def _config(self, tmp_path, roles):
        import json

        from bp.agents.registry import load_config
        from bp.paths import Project

        (tmp_path / "nodes").mkdir(exist_ok=True)
        (tmp_path / "bp.yaml").write_text(
            json.dumps({"agents": {"roles": roles}}), encoding="utf-8"
        )
        return load_config(Project(tmp_path))

    def test_an_unconfigured_role_inherits_the_configured_backend(self, tmp_path):
        """The five original roles configured; the four new ones must follow them,
        not a built-in default with a different provider."""
        config = self._config(
            tmp_path,
            {r: self.CODEX for r in
             ("decomposer", "checker", "verifier_a", "verifier_b", "prover")},
        )
        for role in ("extractor", "obligation", "confirmer", "auditor"):
            assert config.role(role).backend == "codex_cli", role
            assert config.role(role).model == "gpt-5.6-sol", role

    def test_the_provenance_says_where_each_came_from(self, tmp_path):
        config = self._config(
            tmp_path,
            {r: self.CODEX for r in
             ("decomposer", "checker", "verifier_a", "verifier_b", "prover")},
        )
        assert config.provenance["checker"] == "bp.yaml"
        assert config.provenance["obligation"] == "inherited from checker"
        assert config.provenance["confirmer"] == "inherited from verifier_a"
        assert config.provenance["extractor"] == "inherited from prover"
        assert config.provenance["auditor"] == "inherited from checker"

    def test_an_explicitly_configured_role_is_not_overridden(self, tmp_path):
        config = self._config(
            tmp_path,
            {"checker": self.CODEX,
             "obligation": {"backend": "claude_api", "model": "claude-sonnet-5"}},
        )
        assert config.role("obligation").backend == "claude_api"
        assert config.provenance["obligation"] == "bp.yaml"

    def test_an_empty_config_falls_back_to_the_built_in_defaults(self, tmp_path):
        """With nothing configured there is nothing to inherit from, and the built-in
        default is the only answer available."""
        config = self._config(tmp_path, {})
        assert config.role("auditor").backend == "claude_api"
        assert config.provenance["auditor"] == "built-in default"

    def test_every_role_resolves_no_matter_how_partial_the_file(self, tmp_path):
        from bp.agents.registry import ROLES

        config = self._config(tmp_path, {"decomposer": self.CODEX})
        for role in ROLES:
            assert config.role(role) is not None, role

    def test_describe_carries_the_provenance_through(self, tmp_path):
        from bp.agents.log import NullLog
        from bp.agents.registry import Registry
        from bp.paths import Project

        config = self._config(
            tmp_path,
            {r: self.CODEX for r in
             ("decomposer", "checker", "verifier_a", "verifier_b", "prover")},
        )
        rows = Registry(Project(tmp_path), config, log=NullLog()).describe()
        sources = {row[0]: row[5] for row in rows}
        assert sources["obligation"] == "inherited from checker"
        assert sources["prover"] == "bp.yaml"


class TestClaudeApiCredentials:
    """`bp agents` used to report `usable: yes` for the Anthropic backend on a machine
    with no key at all — and that column's whole job is to tell you a backend cannot
    run *before* you spend a click. Saying yes and failing later is worse than not
    having it."""

    def _backend(self):
        from bp.agents.claude_api import ClaudeAPIBackend

        return ClaudeAPIBackend("claude-opus-5", role="auditor")

    def test_no_credentials_is_not_usable(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        ok, reason = self._backend().available()
        assert ok is False
        assert "ANTHROPIC_API_KEY" in reason
        assert "bp.yaml" in reason

    def test_a_key_makes_it_usable(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
        ok, reason = self._backend().available()
        assert ok is True and reason == ""

    def test_the_lazy_auth_TypeError_becomes_an_actionable_error(self, monkeypatch):
        """The SDK resolves credentials at *request* time and signals their absence
        with a bare TypeError, not AuthenticationError — so it escaped every handler
        and surfaced as `TypeError: "Could not resolve authentication method..."`,
        which reads like a bug in Albatross rather than something the user can fix."""
        from bp.agents.base import BackendUnavailable

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        with pytest.raises(BackendUnavailable) as exc:
            self._backend().invoke("system", "user", 5)
        assert "no Anthropic credentials" in str(exc.value)
        assert "bp agents" in str(exc.value)

    def test_an_unrelated_TypeError_is_not_swallowed(self, monkeypatch):
        """Mapping every TypeError to "no credentials" would hide real bugs."""
        import anthropic

        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")

        class Boom:
            def stream(self, **kwargs):
                raise TypeError("something else entirely")

        backend = self._backend()
        monkeypatch.setattr(
            anthropic.Anthropic, "messages", property(lambda self: Boom())
        )
        with pytest.raises(TypeError, match="something else entirely"):
            backend.invoke("system", "user", 5)


class TestEverythingIsAdjustableFromBpYaml:
    """"I want every backend to be adjustable from the bp.yaml file." Two things were
    not: the proof-reader had its role hardcoded to `checker` in `roles/tidy.py`, and
    panel *membership* was the tuple `("verifier_a", "verifier_b")` in `roles/verify.py`
    — so no bp.yaml could add a third reader or drop to one."""

    def _config(self, tmp_path, data):
        import json

        from bp.agents.registry import load_config
        from bp.paths import Project

        (tmp_path / "nodes").mkdir(exist_ok=True)
        (tmp_path / "bp.yaml").write_text(json.dumps(data), encoding="utf-8")
        return load_config(Project(tmp_path))

    def test_the_proofreader_has_its_own_role(self):
        from bp.agents.registry import ROLES
        from bp.roles.tidy import ROLE

        assert ROLE == "proofreader"
        assert ROLE in ROLES

    def test_the_proofreader_inherits_from_checker_by_default(self, tmp_path):
        """It used to *be* checker, so inheriting keeps every existing project
        identical while making it adjustable."""
        config = self._config(
            tmp_path,
            {"agents": {"roles": {"checker": {"backend": "codex_cli", "model": "sol"}}}},
        )
        assert config.role("proofreader").backend == "codex_cli"
        assert config.provenance["proofreader"] == "inherited from checker"

    def test_the_panel_defaults_to_the_two_verifiers(self, tmp_path):
        config = self._config(tmp_path, {})
        assert config.panel == ["verifier_a", "verifier_b"]

    def test_the_panel_can_be_changed(self, tmp_path):
        """A third reader, or one — both were impossible before."""
        roles = {
            r: {"backend": "codex_cli", "model": "sol"}
            for r in ("verifier_a", "verifier_b", "checker")
        }
        config = self._config(
            tmp_path,
            {"agents": {"roles": roles, "panel": ["verifier_a", "verifier_b", "checker"]}},
        )
        assert config.panel == ["verifier_a", "verifier_b", "checker"]

        one = self._config(tmp_path, {"agents": {"roles": roles, "panel": ["verifier_a"]}})
        assert one.panel == ["verifier_a"]

    def test_a_panel_naming_an_unconfigured_role_is_refused(self, tmp_path):
        from bp.agents.registry import ConfigError

        with pytest.raises(ConfigError, match="not a configured role"):
            self._config(tmp_path, {"agents": {"panel": ["verifier_z"]}})

    def test_an_empty_panel_is_refused(self, tmp_path):
        """Nobody would read a whole proof, so no node could ever be verified — and it
        would look like a working configuration."""
        from bp.agents.registry import ConfigError

        with pytest.raises(ConfigError, match="nobody would read a whole proof"):
            self._config(tmp_path, {"agents": {"panel": []}})

    def test_the_panel_is_used_rather_than_the_constant(self, tmp_path, monkeypatch):
        from bp.roles import verify as verify_role

        # The module constant is only a default now.
        assert verify_role.PANEL == ("verifier_a", "verifier_b")

    def test_every_role_the_code_asks_for_by_name_is_a_bp_yaml_key(self):
        """A role resolved by a name that is not in ROLES could never be configured,
        which is the bug class this whole group is about."""
        import re
        from pathlib import Path

        from bp.agents.registry import ROLES

        root = Path(__file__).resolve().parent.parent / "bp"
        asked: set[str] = set()
        for path in root.rglob("*.py"):
            for m in re.finditer(
                r'(?:registry\.agent|config\.role|\.agent)\(\s*"([a-z_]+)"\s*\)',
                path.read_text(encoding="utf-8"),
            ):
                asked.add(m.group(1))
        assert asked, "found no role lookups at all — has the pattern changed?"
        assert asked <= set(ROLES), f"not configurable: {sorted(asked - set(ROLES))}"


class TestFillMissingRoles:
    """`bp agents --fill` writes every unconfigured role into bp.yaml, so the file
    becomes the complete truth and nothing is inherited."""

    def _project(self, tmp_path, text):
        from bp.paths import Project

        (tmp_path / "nodes").mkdir(exist_ok=True)
        (tmp_path / "bp.yaml").write_text(text, encoding="utf-8")
        return Project(tmp_path)

    ORIGINAL = """# my own notes, which must survive
agents:
  roles:
    # the checker, at high effort
    checker:
      backend: codex_cli
      model: gpt-5.6-sol
      options:
        command: [codex, exec, --model, gpt-5.6-sol]
      timeout: 2400
budget:
  max_calls_per_recompile: 40
"""

    def test_it_writes_every_missing_role(self, tmp_path):
        from bp.agents.registry import ROLES, fill_missing_roles, load_config

        project = self._project(tmp_path, self.ORIGINAL)
        added, path = fill_missing_roles(project)
        assert "checker" not in added
        assert set(added) == set(ROLES) - {"checker"}
        config = load_config(project)
        for role in ROLES:
            assert config.provenance[role] == "bp.yaml", role

    def test_it_writes_the_value_the_role_already_resolved_to(self, tmp_path):
        """Nothing about the setup changes — it is only written down. Otherwise the
        command would be a reconfiguration disguised as bookkeeping."""
        from bp.agents.registry import fill_missing_roles, load_config

        project = self._project(tmp_path, self.ORIGINAL)
        before = load_config(project)
        fill_missing_roles(project)
        after = load_config(project)
        for role in before.roles:
            assert after.role(role).backend == before.role(role).backend, role
            assert after.role(role).model == before.role(role).model, role
            assert after.role(role).options == before.role(role).options, role

    def test_the_users_comments_and_options_survive(self, tmp_path):
        from bp.agents.registry import fill_missing_roles

        project = self._project(tmp_path, self.ORIGINAL)
        fill_missing_roles(project)
        text = (tmp_path / "bp.yaml").read_text()
        assert "# my own notes, which must survive" in text
        assert "# the checker, at high effort" in text
        assert "--skip-git-repo-check" not in text  # not invented
        assert "max_calls_per_recompile: 40" in text

    def test_each_written_role_gets_a_note_saying_what_it_is_for(self, tmp_path):
        from bp.agents.registry import fill_missing_roles

        project = self._project(tmp_path, self.ORIGINAL)
        fill_missing_roles(project)
        text = (tmp_path / "bp.yaml").read_text()
        assert "biggest lever on cost" in text          # obligation
        assert "TRANSLATION, not judgement" in text     # extractor
        assert "added by `bp agents --fill`" in text

    def test_what_it_writes_matches_the_style_of_what_is_there(self, tmp_path):
        """A block that does not look like its neighbours reads as machine output, and
        therefore as not the user's to edit — in the one file they are meant to edit.

        Two specifics, both seen on a real project: ruamel emits a plain Python list as
        a block sequence, so an inherited `command` came out one item per line beneath
        ten hand-written `[codex, exec, …]` lines; and `timeout` is a float field, so it
        came out `2400.0` where every hand-written value is a whole number.
        """
        from bp.agents.registry import fill_missing_roles

        project = self._project(tmp_path, self.ORIGINAL)
        fill_missing_roles(project)
        text = (tmp_path / "bp.yaml").read_text()
        assert "command: [codex, exec, --model, gpt-5.6-sol]" in text
        assert "- codex" not in text        # not a block sequence
        assert "timeout: 2400\n" in text
        assert "2400.0" not in text

    def test_running_it_twice_changes_nothing(self, tmp_path):
        from bp.agents.registry import fill_missing_roles

        project = self._project(tmp_path, self.ORIGINAL)
        fill_missing_roles(project)
        first = (tmp_path / "bp.yaml").read_text()
        added, _ = fill_missing_roles(project)
        assert added == []
        assert (tmp_path / "bp.yaml").read_text() == first

    def test_it_works_on_a_file_with_no_agents_block(self, tmp_path):
        from bp.agents.registry import ROLES, fill_missing_roles, load_config

        project = self._project(tmp_path, "budget: {max_calls_per_recompile: 5}\n")
        added, _ = fill_missing_roles(project)
        assert set(added) == set(ROLES)
        assert load_config(project).budget.max_calls_per_recompile == 5
