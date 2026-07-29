"""Recompile: selection, the previewable bill, and interruption-resume."""

from __future__ import annotations

import pytest

from bp import jobs, ops, recompile
from bp.agents.base import Budget
from bp.checks import load_graph
from bp.roles import verify as verify_role

from .conftest import json_reply, scripted_registry, write_node


NO_OBJECTION = json_reply({"checked": ["the whole argument"], "objections": []})
ENTAILS = json_reply({"entails": True, "why": "identical", "confidence": "high"})


def two_leaves(project):
    """A target whose reduction is verified, over two unverified leaves."""
    write_node(
        project,
        "t",
        target=True,
        children=["a", "b"],
        local_status="verified",
        proof="By `a` and `b` we are done.",
    )
    write_node(project, "a", proof="An argument.", statement="Lemma A.")
    write_node(project, "b", proof="Another argument.", statement="Lemma B.")
    ops.record_verification(project, "t", "verified")
    return project


def graph_of(project):
    g, _, ok = load_graph(project)
    assert ok
    return g


class TestPlan:
    def test_selects_only_stale_and_unverified(self, project):
        two_leaves(project)
        registry = scripted_registry(project)
        prepared = recompile.plan(project, registry=registry)
        assert [t.node for t in prepared.tasks] == ["a", "b"]
        assert all(t.reason == "unverified" for t in prepared.tasks)

    def test_a_stale_node_is_selected_and_says_why(self, project):
        write_node(
            project,
            "t",
            target=True,
            local_status="verified",
            proof="p",
            verified_against={"self": "0" * 12},
        )
        registry = scripted_registry(project)
        prepared = recompile.plan(project, registry=registry)
        assert [(t.node, t.reason) for t in prepared.tasks] == [("t", "stale")]

    def test_a_verified_current_node_is_left_alone(self, project):
        two_leaves(project)
        registry = scripted_registry(project)
        prepared = recompile.plan(project, registry=registry)
        assert "t" not in [t.node for t in prepared.tasks]

    def test_nothing_to_do_says_so(self, project):
        write_node(project, "t", target=True, local_status="verified", proof="p")
        ops.record_verification(project, "t", "verified")
        registry = scripted_registry(project)
        assert "nothing to recompile" in recompile.plan(project, registry=registry).describe()

    def test_order_is_shallow_first_along_the_path_to_the_target(self, project):
        write_node(project, "t", target=True, children=["mid"], proof="cites mid")
        write_node(project, "mid", children=["deep"], proof="cites deep")
        write_node(project, "deep", proof="an argument")
        write_node(project, "loose", proof="an argument")
        graph = graph_of(project)
        assert recompile.order(graph, {"deep", "mid", "t", "loose"}) == [
            "t",
            "mid",
            "deep",
            "loose",
        ]

    def test_the_bill_is_previewable_before_anything_runs(self, project):
        two_leaves(project)
        registry = scripted_registry(project)
        prepared = recompile.plan(project, registry=registry)
        text = prepared.describe()
        assert "2 node(s) to verify" in text
        assert "model call(s)" in text
        # Confirmation calls cannot be predicted, and the preview says so rather
        # than quietly under-reporting.
        assert "confirmation calls are not included" in text

    def test_a_priced_backend_produces_a_dollar_estimate(self, project):
        two_leaves(project)
        from bp.agents.registry import Config, Registry, RoleConfig

        config = Config(
            roles={
                role: RoleConfig(backend="claude_api", model="claude-opus-5")
                for role in ("decomposer", "checker", "verifier_a", "verifier_b", "prover")
            }
        )
        prepared = recompile.plan(project, registry=Registry(project, config))
        assert prepared.estimated_usd is not None and prepared.estimated_usd > 0
        assert "estimated cost" in prepared.describe()

    def test_a_subscription_backend_reports_calls_not_dollars(self, project):
        two_leaves(project)
        from bp.agents.registry import Config, Registry, RoleConfig

        config = Config(
            roles={
                role: RoleConfig(backend="claude_cli", model="opus")
                for role in ("decomposer", "checker", "verifier_a", "verifier_b", "prover")
            }
        )
        prepared = recompile.plan(project, registry=Registry(project, config))
        assert prepared.estimated_usd is None
        assert "reports no price" in prepared.describe()

    def test_cached_obligations_are_subtracted_from_the_estimate(self, project):
        write_node(
            project,
            "t",
            target=True,
            children=["c"],
            proof="By `c`.",
            hypotheses=[{"id": "H1", "tex": "a > 0"}],
            uses={"c": {"applied_to": "x", "discharges": {"H1": "hypothesis:H1"}}},
        )
        write_node(project, "c", statement="Lemma.", hypotheses=[{"id": "H1", "tex": "a > 0"}])
        registry = scripted_registry(project)
        before = recompile.plan(project, registry=registry).tasks[0]
        assert before.obligations == 1 and before.cached == 0

        verify_role.verify(
            project,
            "t",
            registry=scripted_registry(
                project,
                verifier_a=[ENTAILS, NO_OBJECTION],
                verifier_b=[NO_OBJECTION],
            ),
        )
        ops.record_verification(project, "t", "flagged", [{"why": "reset for the test"}])
        after = recompile.plan(project, registry=registry).tasks
        assert after == [] or after[0].cached == 1


class TestRun:
    def test_results_are_written_as_they_land(self, project):
        two_leaves(project)
        registry = scripted_registry(
            project,
            verifier_a=[NO_OBJECTION, NO_OBJECTION],
            verifier_b=[NO_OBJECTION, NO_OBJECTION],
        )
        result = recompile.run(project, registry=registry)
        assert result.verified == ["a", "b"]
        graph = graph_of(project)
        assert graph["a"].local_status == "verified"
        assert graph["b"].local_status == "verified"
        assert result.job.status == jobs.DONE

    def test_a_flagged_node_is_reported_separately(self, project):
        two_leaves(project)
        objection = json_reply(
            {
                "checked": ["step 1"],
                "objections": [
                    {
                        "section": "proof",
                        "quote": "An argument.",
                        "kind": "non-sequitur",
                        "why": "it does not follow",
                        "confidence": "high",
                    }
                ],
            }
        )
        registry = scripted_registry(
            project,
            verifier_a=[
                objection,
                json_reply({"upheld": True, "why": "it really does not follow"}),
                NO_OBJECTION,
            ],
            verifier_b=[NO_OBJECTION, NO_OBJECTION],
        )
        result = recompile.run(project, registry=registry)
        assert result.flagged == ["a"]
        assert result.verified == ["b"]


class TestResume:
    def _interrupt(self, project):
        """Run with a budget that runs out after the first node."""
        registry = scripted_registry(
            project, verifier_a=[NO_OBJECTION], verifier_b=[NO_OBJECTION]
        )
        registry.budget = Budget(max_calls=2)  # exactly what node `a` needs
        return recompile.run(project, registry=registry)

    def test_the_run_stops_and_records_where_it_got_to(self, project):
        two_leaves(project)
        result = self._interrupt(project)
        assert result.verified == ["a"]
        assert result.stopped and "call cap" in result.stopped
        assert result.job.status == jobs.INTERRUPTED
        assert result.job.completed == ["verify:a"]
        assert result.job.pending == ["verify:b"]
        assert graph_of(project)["b"].local_status == "unverified"

    def test_resume_re_queries_nothing_already_done(self, project):
        two_leaves(project)
        interrupted = self._interrupt(project)

        asked: list[str] = []
        registry = scripted_registry(
            project, verifier_a=[NO_OBJECTION], verifier_b=[NO_OBJECTION]
        )
        for role in ("verifier_a", "verifier_b"):
            agent = registry.agent(role)
            original = agent.invoke
            agent.invoke = (  # type: ignore[method-assign]
                lambda s, u, t, _o=original: (asked.append(u), _o(s, u, t))[1]
            )

        result = recompile.resume(project, interrupted.job.id, registry=registry)
        assert result.skipped == ["a"]
        assert result.verified == ["b"]
        assert result.job.status == jobs.DONE
        # Every call the resume made was about `b`; `a` was not re-read at all.
        assert asked and all("Lemma B." in prompt for prompt in asked)
        assert not any("Lemma A." in prompt for prompt in asked)

    def test_resume_with_no_job_id_takes_the_latest_interrupted_one(self, project):
        two_leaves(project)
        self._interrupt(project)
        registry = scripted_registry(
            project, verifier_a=[NO_OBJECTION], verifier_b=[NO_OBJECTION]
        )
        result = recompile.resume(project, registry=registry)
        assert result.verified == ["b"]

    def test_nothing_to_resume_is_an_error_not_a_silent_no_op(self, project):
        two_leaves(project)
        with pytest.raises(ops.OpError):
            recompile.resume(project)


class TestJobRecords:
    def test_a_job_is_written_before_any_work_happens(self, project):
        two_leaves(project)
        job = jobs.Job.create(project, "recompile", ["verify:a", "verify:b"])
        assert job.path(project).exists()
        assert job.pending == ["verify:a", "verify:b"]

    def test_each_completion_is_persisted_immediately(self, project):
        job = jobs.Job.create(project, "recompile", ["one", "two"])
        job.complete(project, "one", "one: verified")
        reloaded = jobs.Job.load(project, job.id)
        assert reloaded.completed == ["one"]
        assert reloaded.notes == ["one: verified"]

    def test_completing_twice_is_idempotent(self, project):
        job = jobs.Job.create(project, "recompile", ["one"])
        job.complete(project, "one")
        job.complete(project, "one")
        assert jobs.Job.load(project, job.id).completed == ["one"]

    def test_listing_and_describing(self, project):
        jobs.Job.create(project, "recompile", ["one"])
        records = jobs.Job.all(project)
        assert len(records) == 1
        assert "recompile" in records[0].describe()
