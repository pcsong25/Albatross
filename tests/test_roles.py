"""The four roles, driven by scripted backends.

No network, no key, no cost — but the full path each role really takes: prompt
assembly, schema validation, the deterministic checks in the middle of the
decompose loop, and the writes through ``ops``.
"""

from __future__ import annotations

import copy

import pytest

from bp import ops
from bp.agents.base import AgentError
from bp.checks import load_graph
from bp.roles import check as check_role
from bp.roles import context as context_mod
from bp.roles import decompose as decompose_role
from bp.roles import prove as prove_role
from bp.roles import verify as verify_role

from .conftest import json_reply, scripted_registry, write_node


def child(slug, tex="a > 0", difficulty="routine"):
    return {
        "slug": slug,
        "role": "lemma",
        "statement": f"The statement of {slug}.",
        "difficulty": difficulty,
        "hypotheses": [{"id": "H1", "tex": tex}],
        "notes": "",
    }


def decomposition(*, discharges_complete=True, slugs=("step-one", "step-two", "step-three")):
    uses = {
        slug: {"applied_to": "x", "discharges": {"H1": "hypothesis:H1"}} for slug in slugs
    }
    if not discharges_complete:
        uses[slugs[1]]["discharges"] = {}
    return {
        "verdict": "decompose",
        "assessed_difficulty": "hard",
        "assessment": "Three genuinely separate steps.",
        "strategy": "reduce to an ODE inequality at the origin",
        "children": [child(s) for s in slugs],
        "reduction_proof": "By "
        + ", ".join(f"`{s}`" for s in slugs)
        + " the claim follows.",
        "uses": uses,
        "notes": "",
    }


def target_project(project):
    write_node(
        project,
        "gclm.main",
        target=True,
        difficulty="hard",
        statement="The theorem.",
        hypotheses=[{"id": "H1", "tex": "a > 0"}],
    )
    return project


def graph_of(project):
    g, _, ok = load_graph(project)
    assert ok
    return g


class TestDecompose:
    def test_a_clean_decomposition_is_written(self, project):
        target_project(project)
        registry = scripted_registry(project, decomposer=[json_reply(decomposition())])
        result = decompose_role.expand(project, "gclm.main", registry=registry)

        assert result.clean
        assert result.rounds == 1
        assert result.children == [
            "gclm.step-one",
            "gclm.step-two",
            "gclm.step-three",
        ]
        graph = graph_of(project)
        parent = graph["gclm.main"]
        assert parent.children == result.children
        assert set(parent.uses) == set(result.children)
        assert parent.strategy == "reduce to an ODE inequality at the origin"
        for child_id in result.children:
            assert graph[child_id].hypotheses[0].id == "H1"

    def test_child_discharges_are_resolved_from_slug_to_node_id(self, project):
        """The prompt asks for sibling references by slug, so `child:step-one`
        has to become `child:gclm.step-one` — otherwise every such discharge
        comes back as DIS014 and a repair round is spent on a problem the system
        invented for itself."""
        target_project(project)
        payload = decomposition()
        payload["uses"]["step-two"]["discharges"]["H1"] = "child:step-one"
        registry = scripted_registry(project, decomposer=[json_reply(payload)])
        result = decompose_role.expand(project, "gclm.main", registry=registry)

        assert result.clean, [d.message for d in result.diagnostics]
        assert result.rounds == 1
        uses = graph_of(project)["gclm.main"].uses
        assert uses["gclm.step-two"].discharges["H1"] == "child:gclm.step-one"

    def test_slugs_are_resolved_to_project_ids_in_the_proof(self, project):
        target_project(project)
        registry = scripted_registry(project, decomposer=[json_reply(decomposition())])
        decompose_role.expand(project, "gclm.main", registry=registry)
        proof = graph_of(project)["gclm.main"].proof_section
        assert "`gclm.step-one`" in proof
        assert "`step-one`" not in proof

    def test_an_incomplete_discharge_table_is_repaired(self, project):
        target_project(project)
        registry = scripted_registry(
            project,
            decomposer=[
                json_reply(decomposition(discharges_complete=False)),
                json_reply(decomposition()),
            ],
        )
        result = decompose_role.expand(project, "gclm.main", registry=registry)
        assert result.rounds == 2
        assert result.clean

    def test_the_repair_prompt_carries_the_diagnostics(self, project):
        """The model is told exactly which hypothesis it failed to discharge —
        a bare 'try again' produces the same answer twice."""
        target_project(project)
        seen: list[str] = []

        class Recorder(dict):
            pass

        registry = scripted_registry(
            project,
            decomposer=[
                json_reply(decomposition(discharges_complete=False)),
                json_reply(decomposition()),
            ],
        )
        agent = registry.agent("decomposer")
        original = agent.invoke

        def spy(system, user, timeout):
            seen.append(user)
            return original(system, user, timeout)

        agent.invoke = spy  # type: ignore[method-assign]
        decompose_role.expand(project, "gclm.main", registry=registry)
        assert len(seen) == 2
        assert "DIS011" in seen[1]
        assert "ADMITTED" in seen[1]

    def test_two_failed_repairs_still_write_but_report_the_errors(self, project):
        target_project(project)
        broken = json_reply(decomposition(discharges_complete=False))
        registry = scripted_registry(project, decomposer=[broken, broken, broken])
        result = decompose_role.expand(project, "gclm.main", registry=registry)
        assert result.rounds == 3
        assert not result.clean
        assert any(d.code == "DIS011" for d in result.diagnostics)
        # Written anyway: debt is visible, and `bp check` says exactly what is wrong.
        assert graph_of(project)["gclm.main"].children

    def test_nothing_is_written_when_apply_is_false(self, project):
        target_project(project)
        registry = scripted_registry(project, decomposer=[json_reply(decomposition())])
        decompose_role.expand(project, "gclm.main", registry=registry, apply=False)
        assert graph_of(project)["gclm.main"].children == []

    def test_expanding_an_already_expanded_node_is_refused(self, project):
        target_project(project)
        registry = scripted_registry(
            project, decomposer=[json_reply(decomposition()), json_reply(decomposition())]
        )
        decompose_role.expand(project, "gclm.main", registry=registry)
        with pytest.raises(ops.OpError) as exc:
            decompose_role.expand(project, "gclm.main", registry=registry)
        assert "bp redo" in str(exc.value)

    def test_id_collisions_get_a_suffix(self, project):
        target_project(project)
        write_node(project, "gclm.step-one", statement="Already taken.")
        registry = scripted_registry(project, decomposer=[json_reply(decomposition())])
        result = decompose_role.expand(project, "gclm.main", registry=registry)
        assert "gclm.step-one-2" in result.children

    def test_the_hint_reaches_the_prompt(self, project):
        target_project(project)
        registry = scripted_registry(project, decomposer=[json_reply(decomposition())])
        graph = graph_of(project)
        prompt = decompose_role.build_prompt(
            graph, graph["gclm.main"], "bootstrap on the $L^\\infty$ norm"
        )
        assert "bootstrap on the $L^\\infty$ norm" in prompt
        assert "user's guidance" in prompt

    def test_schema_bounds_the_child_count(self):
        from pydantic import ValidationError

        too_few = decomposition(slugs=("a", "b"))
        with pytest.raises(ValidationError):
            decompose_role.Decomposition(**too_few)


class TestTriage:
    """The decomposer judges difficulty first and may decline to split."""

    def _declined(self, verdict="already-atomic", difficulty="routine"):
        return json_reply({
            "verdict": verdict,
            "assessed_difficulty": difficulty,
            "assessment": "One integration by parts; splitting it would add bookkeeping.",
        })

    def test_a_declined_node_is_not_decomposed(self, project):
        target_project(project)
        registry = scripted_registry(project, decomposer=[self._declined()])
        result = decompose_role.expand(project, "gclm.main", registry=registry)

        assert result.declined
        assert result.children == []
        assert result.verdict == "already-atomic"
        assert graph_of(project)["gclm.main"].children == []

    def test_the_assessment_is_kept_as_a_note(self, project):
        target_project(project)
        registry = scripted_registry(project, decomposer=[self._declined()])
        decompose_role.expand(project, "gclm.main", registry=registry)
        notes = graph_of(project)["gclm.main"].notes_section
        assert "Decomposer declined" in notes
        assert "integration by parts" in notes

    def test_force_overrides_the_decline(self, project):
        target_project(project)
        registry = scripted_registry(
            project, decomposer=[self._declined(), json_reply(decomposition())]
        )
        # The first reply declines; with force it is ignored and the schema then
        # requires a real decomposition, which the second reply supplies.
        result = decompose_role.expand(project, "gclm.main", registry=registry, force=True)
        assert not result.declined
        assert len(result.children) == 3

    def test_a_decline_costs_exactly_one_call(self, project):
        target_project(project)
        registry = scripted_registry(project, decomposer=[self._declined()])
        result = decompose_role.expand(project, "gclm.main", registry=registry)
        assert len(result.calls) == 1

    def test_summarise_tells_the_user_what_to_do_next(self, project):
        target_project(project)
        registry = scripted_registry(project, decomposer=[self._declined("prove-directly")])
        result = decompose_role.expand(project, "gclm.main", registry=registry)
        text = decompose_role.summarise(result)
        assert "not decomposed" in text
        assert "Generate a proof" in text


class TestRedo:
    def test_the_previous_subtree_is_archived_to_attempts_first(self, project):
        target_project(project)
        registry = scripted_registry(
            project,
            decomposer=[
                json_reply(decomposition()),
                json_reply(decomposition(slugs=("alt-one", "alt-two", "alt-three"))),
            ],
        )
        decompose_role.expand(project, "gclm.main", registry=registry)
        result = decompose_role.redo(project, "gclm.main", registry=registry)

        assert result.archived_to is not None and result.archived_to.exists()
        saved = {p.name for p in result.archived_to.iterdir()}
        assert "gclm.step-one.md" in saved
        assert "gclm.main.md" in saved

        graph = graph_of(project)
        assert graph["gclm.step-one"].lifecycle == "archived"
        assert graph["gclm.main"].children == [
            "gclm.alt-one",
            "gclm.alt-two",
            "gclm.alt-three",
        ]
        # Nothing was deleted.
        assert (project.nodes_dir / "gclm.step-one.md").exists()

    def test_the_previous_problems_become_negative_context(self, project):
        target_project(project)
        broken = json_reply(decomposition(discharges_complete=False))
        registry = scripted_registry(
            project,
            decomposer=[
                broken,
                broken,
                broken,
                json_reply(decomposition(slugs=("alt-one", "alt-two", "alt-three"))),
            ],
        )
        decompose_role.expand(project, "gclm.main", registry=registry)
        seen: list[str] = []
        agent = registry.agent("decomposer")
        original = agent.invoke
        agent.invoke = lambda s, u, t: (seen.append(u), original(s, u, t))[1]  # type: ignore
        decompose_role.redo(project, "gclm.main", registry=registry)
        assert "Do not reproduce it" in seen[0]


class TestChecker:
    def _prepare(self, project):
        target_project(project)
        registry = scripted_registry(project, decomposer=[json_reply(decomposition())])
        decompose_role.expand(project, "gclm.main", registry=registry)

    def test_two_separate_calls(self, project):
        self._prepare(project)
        registry = scripted_registry(
            project,
            checker=[
                json_reply({"checked": ["the reduction, step by step"], "problems": []}),
                json_reply({"checked": ["each child against the parent"], "problems": []}),
            ],
        )
        report = check_role.check_decomposition(project, "gclm.main", registry=registry)
        assert len(report.calls) == 2
        assert report.clean
        assert "none found" in check_role.summarise(report)

    def test_located_problems_are_reported(self, project):
        self._prepare(project)
        registry = scripted_registry(
            project,
            checker=[
                json_reply(
                    {
                        "checked": ["the reduction"],
                        "problems": [
                            {
                                "where": "the final step",
                                "quote": "the claim follows",
                                "why": "step-three is never used",
                                "confidence": "high",
                            }
                        ],
                    }
                ),
                json_reply({"checked": ["each child"], "problems": []}),
            ],
        )
        report = check_role.check_decomposition(project, "gclm.main", registry=registry)
        assert not report.clean
        assert report.problems[0][0] == "reduction"
        assert "step-three is never used" in check_role.summarise(report)

    def test_a_node_with_no_children_has_no_decomposition_to_check(self, project):
        target_project(project)
        registry = scripted_registry(project)
        with pytest.raises(ops.OpError):
            check_role.check_decomposition(project, "gclm.main", registry=registry)


class TestVerifier:
    def _prepare(self, project):
        write_node(
            project,
            "t",
            target=True,
            children=["c"],
            proof="By `c` we are done.",
            hypotheses=[{"id": "H1", "tex": "a > 0"}],
            uses={"c": {"applied_to": "x", "discharges": {"H1": "hypothesis:H1"}}},
        )
        write_node(project, "c", statement="The lemma.", hypotheses=[{"id": "H1", "tex": "a > 0"}])

    def test_clean_verification_records_a_certificate(self, project):
        self._prepare(project)
        registry = scripted_registry(
            project,
            verifier_a=[
                json_reply({"entails": True, "why": "identical", "confidence": "high"}),
                json_reply({"checked": ["step 1", "step 2"], "objections": []}),
            ],
            verifier_b=[json_reply({"checked": ["the whole argument"], "objections": []})],
        )
        report = verify_role.verify(project, "t", registry=registry)
        assert report.verdict == "verified"
        assert report.obligations_checked == 1
        node = graph_of(project)["t"]
        assert node.local_status == "verified"
        assert node.verified_against["self"] == node.statement_hash
        assert node.verified_against["c"] == graph_of(project)["c"].statement_hash

    def test_an_upheld_objection_flags_the_node(self, project):
        self._prepare(project)
        registry = scripted_registry(
            project,
            verifier_a=[
                json_reply({"entails": True, "why": "yes", "confidence": "high"}),
                json_reply(
                    {
                        "checked": ["step 1"],
                        "objections": [
                            {
                                "section": "proof",
                                "quote": "By `c` we are done.",
                                "kind": "non-sequitur",
                                "why": "c gives less than the conclusion",
                                "confidence": "high",
                            }
                        ],
                    }
                ),
                json_reply({"upheld": True, "why": "c really does give less"}),
            ],
            verifier_b=[json_reply({"checked": ["everything"], "objections": []})],
        )
        report = verify_role.verify(project, "t", registry=registry)
        assert report.verdict == "flagged"
        node = graph_of(project)["t"]
        assert node.local_status == "flagged"
        assert node.global_status == "blocked:objection"
        assert node.flags[0].why

    def test_a_dissolved_objection_is_withdrawn_and_noted(self, project):
        self._prepare(project)
        registry = scripted_registry(
            project,
            verifier_a=[
                json_reply({"entails": True, "why": "yes", "confidence": "high"}),
                json_reply(
                    {
                        "checked": ["step 1"],
                        "objections": [
                            {
                                "section": "proof",
                                "quote": "By `c` we are done.",
                                "kind": "non-sequitur",
                                "why": "no justification given",
                                "confidence": "low",
                            }
                        ],
                    }
                ),
                json_reply({"upheld": False, "why": "the justification is the cited lemma"}),
            ],
            verifier_b=[json_reply({"checked": ["everything"], "objections": []})],
        )
        report = verify_role.verify(project, "t", registry=registry)
        assert report.verdict == "verified"
        assert len(report.withdrawn) == 1
        assert "withdrawn on confirmation" in graph_of(project)["t"].notes_section

    def test_a_failed_obligation_becomes_an_objection(self, project):
        self._prepare(project)
        registry = scripted_registry(
            project,
            verifier_a=[
                json_reply(
                    {"entails": False, "why": "H1 of t is weaker", "confidence": "high"}
                ),
                json_reply({"checked": ["step 1"], "objections": []}),
                json_reply({"upheld": True, "why": "H1 of t really is weaker"}),
            ],
            verifier_b=[json_reply({"checked": ["everything"], "objections": []})],
        )
        report = verify_role.verify(project, "t", registry=registry)
        assert report.verdict == "flagged"
        assert report.flags[0].kind == "hypothesis-unsatisfied"

    def test_obligation_results_are_cached_on_the_hash(self, project):
        self._prepare(project)
        first = scripted_registry(
            project,
            verifier_a=[
                json_reply({"entails": True, "why": "yes", "confidence": "high"}),
                json_reply({"checked": ["step 1"], "objections": []}),
            ],
            verifier_b=[json_reply({"checked": ["all"], "objections": []})],
        )
        verify_role.verify(project, "t", registry=first)

        # No obligation response scripted this time: it must come from cache.
        second = scripted_registry(
            project,
            verifier_a=[json_reply({"checked": ["step 1"], "objections": []})],
            verifier_b=[json_reply({"checked": ["all"], "objections": []})],
        )
        report = verify_role.verify(project, "t", registry=second)
        assert report.obligations_cached == 1
        assert report.verdict == "verified"

    def test_an_admitted_discharge_is_not_sent_to_the_verifier(self, project):
        self._prepare(project)
        ops.set_uses(
            project,
            "t",
            {"c": {"applied_to": "x", "discharges": {"H1": "ADMITTED: no argument yet"}}},
        )
        registry = scripted_registry(
            project,
            verifier_a=[json_reply({"checked": ["step 1"], "objections": []})],
            verifier_b=[json_reply({"checked": ["all"], "objections": []})],
        )
        report = verify_role.verify(project, "t", registry=registry)
        assert report.obligations_checked == 0  # already visible debt; nothing to ask

    def test_silence_from_the_whole_panel_is_not_agreement(self, project):
        """A network outage must not turn into a green graph. If no verifier
        answered, refuse to record a verdict rather than recording `verified`."""
        self._prepare(project)
        registry = scripted_registry(
            project,
            verifier_a=[json_reply({"entails": True, "why": "yes", "confidence": "high"})],
            verifier_b=[],
        )
        with pytest.raises(AgentError) as exc:
            verify_role.verify(project, "t", registry=registry)
        assert "no verifier answered" in str(exc.value)
        assert graph_of(project)["t"].local_status == "unverified"

    def test_one_panel_member_failing_is_survivable(self, project):
        self._prepare(project)
        registry = scripted_registry(
            project,
            verifier_a=[
                json_reply({"entails": True, "why": "yes", "confidence": "high"}),
                json_reply({"checked": ["step 1"], "objections": []}),
            ],
            verifier_b=[],  # unavailable
        )
        report = verify_role.verify(project, "t", registry=registry)
        assert report.panel_ran == 1
        assert report.verdict == "verified"

    def test_no_record_leaves_the_node_alone(self, project):
        self._prepare(project)
        registry = scripted_registry(
            project,
            verifier_a=[
                json_reply({"entails": True, "why": "yes", "confidence": "high"}),
                json_reply({"checked": ["step 1"], "objections": []}),
            ],
            verifier_b=[json_reply({"checked": ["all"], "objections": []})],
        )
        verify_role.verify(project, "t", registry=registry, record=False)
        assert graph_of(project)["t"].local_status == "unverified"


class TestProver:
    def test_a_routine_leaf_gets_a_proof_and_keeps_its_status(self, project):
        write_node(project, "t", target=True, children=["c"], proof="cites c")
        write_node(project, "c", difficulty="routine", statement="An easy lemma.")
        registry = scripted_registry(
            project,
            prover=[json_reply({"attempted": True, "proof": "Integrate by parts.", "gaps": []})],
        )
        result = prove_role.prove(project, "c", registry=registry)
        assert result.written
        node = graph_of(project)["c"]
        assert "Integrate by parts." in node.proof_section
        # The prover never decides whether its own proof is correct.
        assert node.local_status == "unverified"

    def test_a_declined_lemma_becomes_a_note_not_a_proof(self, project):
        write_node(project, "t", target=True, children=["c"], proof="cites c")
        write_node(project, "c", difficulty="routine", statement="Not so easy after all.")
        registry = scripted_registry(
            project,
            prover=[
                json_reply(
                    {
                        "attempted": False,
                        "reason": "this needs a hypothesis the statement does not have",
                    }
                )
            ],
        )
        result = prove_role.prove(project, "c", registry=registry)
        assert not result.written
        node = graph_of(project)["c"]
        assert not node.has_proof
        assert "needs a hypothesis" in node.notes_section

    def test_gaps_are_recorded_rather_than_papered_over(self, project):
        write_node(project, "t", target=True, children=["c"], proof="cites c")
        write_node(project, "c", difficulty="standard", statement="A lemma.")
        registry = scripted_registry(
            project,
            prover=[
                json_reply(
                    {
                        "attempted": True,
                        "proof": "The argument.",
                        "gaps": ["the interchange of limits is not justified"],
                    }
                )
            ],
        )
        prove_role.prove(project, "c", registry=registry)
        node = graph_of(project)["c"]
        assert "GAP: the interchange of limits" in node.proof_section
        assert "unjustified step" in node.notes_section

    def test_hard_leaves_are_refused(self, project):
        write_node(project, "t", target=True, children=["c"], proof="cites c")
        write_node(project, "c", difficulty="hard")
        registry = scripted_registry(project, prover=[json_reply({"attempted": True})])
        with pytest.raises(ops.OpError) as exc:
            prove_role.prove(project, "c", registry=registry)
        assert "routine and standard leaves only" in str(exc.value)

    def test_a_node_with_children_is_refused(self, project):
        write_node(project, "t", target=True, children=["c"], difficulty="routine", proof="cites c")
        write_node(project, "c", difficulty="routine")
        registry = scripted_registry(project, prover=[json_reply({"attempted": True})])
        with pytest.raises(ops.OpError) as exc:
            prove_role.prove(project, "t", registry=registry)
        assert "reduction" in str(exc.value)


class TestContext:
    def test_the_setting_names_the_target_and_the_chain(self, project):
        write_node(project, "t", target=True, children=["mid"], statement="The theorem.",
                   proof="cites mid")
        write_node(project, "mid", children=["leaf"], statement="The middle.", proof="cites leaf")
        write_node(project, "leaf", statement="The leaf.")
        graph = graph_of(project)
        setting = context_mod.setting(graph, graph["leaf"])
        assert "The theorem." in setting
        assert "The middle." in setting
        assert "The leaf." not in setting  # the node itself is given separately

    def test_descendants_are_not_offered_as_citable(self, project):
        write_node(project, "t", target=True, children=["mid"], proof="cites mid")
        write_node(project, "mid", children=["leaf"], proof="cites leaf")
        write_node(project, "leaf")
        graph = graph_of(project)
        available = context_mod.siblings_available(graph, graph["mid"])
        assert "`leaf`" not in available  # citing a descendant would be circular
        assert "`t`" not in available  # so would citing an ancestor

    def test_prompts_load_from_files_the_user_can_edit(self):
        for name in (
            "decompose",
            "check_reduction",
            "check_triviality",
            "verify_obligation",
            "verify_proof",
            "verify_confirm",
            "prove",
        ):
            assert len(context_mod.load_prompt(name)) > 400
