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
