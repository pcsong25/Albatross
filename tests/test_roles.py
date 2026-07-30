"""The six roles, driven by scripted backends.

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
from bp.roles import audit as audit_role
from bp.roles import decompose as decompose_role
from bp.roles import extract as extract_role
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
            obligation=[
                json_reply({"entails": True, "why": "identical", "confidence": "high"}),
            ],
            verifier_a=[json_reply({"checked": ["step 1", "step 2"], "objections": []})],
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
            obligation=[json_reply({"entails": True, "why": "yes", "confidence": "high"})],
            verifier_a=[
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
            ],
            confirmer=[json_reply({"upheld": True, "why": "c really does give less"})],
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
            obligation=[json_reply({"entails": True, "why": "yes", "confidence": "high"})],
            verifier_a=[
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
            ],
            confirmer=[
                json_reply({"upheld": False, "why": "the justification is the cited lemma"})
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
            obligation=[
                json_reply(
                    {"entails": False, "why": "H1 of t is weaker", "confidence": "high"}
                ),
            ],
            verifier_a=[json_reply({"checked": ["step 1"], "objections": []})],
            confirmer=[json_reply({"upheld": True, "why": "H1 of t really is weaker"})],
            verifier_b=[json_reply({"checked": ["everything"], "objections": []})],
        )
        report = verify_role.verify(project, "t", registry=registry)
        assert report.verdict == "flagged"
        assert report.flags[0].kind == "hypothesis-unsatisfied"

    def test_obligation_results_are_cached_on_the_hash(self, project):
        self._prepare(project)
        first = scripted_registry(
            project,
            obligation=[json_reply({"entails": True, "why": "yes", "confidence": "high"})],
            verifier_a=[json_reply({"checked": ["step 1"], "objections": []})],
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
            obligation=[json_reply({"entails": True, "why": "yes", "confidence": "high"})],
            verifier_a=[],
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
            obligation=[json_reply({"entails": True, "why": "yes", "confidence": "high"})],
            verifier_a=[json_reply({"checked": ["step 1"], "objections": []})],
            verifier_b=[],  # unavailable
        )
        report = verify_role.verify(project, "t", registry=registry)
        assert report.panel_ran == 1
        assert report.verdict == "verified"

    def test_no_record_leaves_the_node_alone(self, project):
        self._prepare(project)
        registry = scripted_registry(
            project,
            obligation=[json_reply({"entails": True, "why": "yes", "confidence": "high"})],
            verifier_a=[json_reply({"checked": ["step 1"], "objections": []})],
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
            "extract",
            "verify_obligation",
            "verify_claim",
            "verify_proof",
            "verify_confirm",
            "audit",
            "prove",
        ):
            assert len(context_mod.load_prompt(name)) > 400


# --- the extractor -----------------------------------------------------------


LEDGER = json_reply(
    {
        "claims": [
            {"id": "c1", "text": "a > 0", "source": {"kind": "hypothesis", "ref": "H1"}},
            {"id": "c2", "text": "the lemma holds", "source": {"kind": "child", "ref": "c"}},
            {"id": "c3", "text": "\\omega \\in C^1", "source": {"kind": "none", "ref": ""}},
        ],
        "omitted": "the closing sentence, which restates the conclusion",
    }
)


class TestExtractor:
    def _prepare(self, project):
        write_node(
            project,
            "t",
            target=True,
            children=["c"],
            proof="By `c`, and by standard regularity, we are done.",
            hypotheses=[{"id": "H1", "tex": "a > 0"}],
            uses={"c": {"applied_to": "x", "discharges": {}}},
        )
        write_node(project, "c", statement="The lemma.")

    def test_the_ledger_is_written_and_audited(self, project):
        self._prepare(project)
        registry = scripted_registry(project, extractor=[LEDGER])
        result = extract_role.extract(project, "t", registry=registry)
        assert result.written
        assert result.claims == 3
        assert result.unsourced == ["c3"]
        node = graph_of(project)["t"]
        assert [c.id for c in node.claims] == ["c1", "c2", "c3"]
        assert node.claims_of  # the proof hash it was extracted from

    def test_LED001_fires_on_exactly_the_unsourced_claim(self, project):
        self._prepare(project)
        registry = scripted_registry(project, extractor=[LEDGER])
        result = extract_role.extract(project, "t", registry=registry)
        assert [d.code for d in result.diagnostics] == ["LED001"]
        assert "c3" in result.diagnostics[0].message
        assert not result.clean

    def test_what_the_extractor_left_out_becomes_a_note(self, project):
        """A suspiciously short ledger should be legible rather than mysterious."""
        self._prepare(project)
        registry = scripted_registry(project, extractor=[LEDGER])
        extract_role.extract(project, "t", registry=registry)
        assert "restates the conclusion" in graph_of(project)["t"].notes_section

    def test_a_missing_source_defaults_to_unsourced_not_absent(self, project):
        """The one failure mode worth engineering against is a model inventing a
        source. The structural defence is that `none` is the default, so an
        omitted source is unsourced rather than silently dropped."""
        self._prepare(project)
        registry = scripted_registry(
            project, extractor=[json_reply({"claims": [{"id": "c1", "text": "x"}]})]
        )
        result = extract_role.extract(project, "t", registry=registry)
        assert result.unsourced == ["c1"]

    def test_duplicate_claim_ids_are_rejected_by_the_schema(self, project):
        self._prepare(project)
        duplicate = json_reply(
            {"claims": [{"id": "c1", "text": "x"}, {"id": "c1", "text": "y"}]}
        )
        registry = scripted_registry(project, extractor=[duplicate, duplicate])
        with pytest.raises(AgentError):
            extract_role.extract(project, "t", registry=registry)

    def test_an_unknown_source_kind_is_rejected(self, project):
        self._prepare(project)
        bad = json_reply(
            {"claims": [{"id": "c1", "text": "x", "source": {"kind": "vibes"}}]}
        )
        registry = scripted_registry(project, extractor=[bad, bad])
        with pytest.raises(AgentError):
            extract_role.extract(project, "t", registry=registry)

    def test_a_node_with_no_proof_has_no_claims_to_extract(self, project):
        write_node(project, "t", target=True, statement="A claim.")
        registry = scripted_registry(project)
        with pytest.raises(ops.OpError):
            extract_role.extract(project, "t", registry=registry)

    def test_no_record_leaves_the_node_alone(self, project):
        self._prepare(project)
        registry = scripted_registry(project, extractor=[LEDGER])
        result = extract_role.extract(project, "t", registry=registry, apply=False)
        assert not result.written
        assert graph_of(project)["t"].claims == []


# --- the statement auditor ----------------------------------------------------


def audit_reply(**overrides):
    payload = {
        "well_posed": {"ok": True, "checked": "s, omega_0 and T_max all bound", "findings": []},
        "non_vacuous": {
            "verdict": "exhibited",
            "witness": "\\omega_0(x) = -\\sin x, \\ s = 2",
            "conflict": "",
        },
        "quantifiers": {"ok": True, "checked": "for all s > 3/2 there is T_max", "findings": []},
        "constants": {
            "ok": True,
            "constants": ["kappa: depends only on a"],
            "findings": [],
        },
    }
    payload.update(overrides)
    return json_reply(payload)


class TestStatementAuditor:
    def _prepare(self, project):
        write_node(project, "t", target=True, statement="A claim.", proof="An argument.")

    def test_a_clean_audit_changes_nothing(self, project):
        self._prepare(project)
        registry = scripted_registry(project, auditor=[audit_reply()])
        report = audit_role.audit(project, "t", registry=registry)
        assert report.clean
        assert report.verdict == "pass"
        node = graph_of(project)["t"]
        # It never touches a status: its answers are prompts for attention, not
        # checks, because it stands in for VAC/CST and is weaker than both.
        assert node.local_status == "unverified"
        assert not report.noted

    def test_a_constant_dependence_finding_becomes_a_note(self, project):
        self._prepare(project)
        registry = scripted_registry(
            project,
            auditor=[
                audit_reply(
                    constants={
                        "ok": False,
                        "constants": ["kappa: declared uniform in t"],
                        "findings": [
                            {
                                "quote": "there is $\\kappa > 0$, independent of $t$",
                                "why": "kappa is built from a bound that deteriorates in t",
                                "confidence": "high",
                            }
                        ],
                    }
                )
            ],
        )
        report = audit_role.audit(project, "t", registry=registry)
        assert not report.clean
        assert report.verdict == "flagged"
        node = graph_of(project)["t"]
        assert "deteriorates in t" in node.notes_section
        assert node.local_status == "unverified"  # still not a status change

    def test_a_missing_witness_is_a_finding_in_its_own_right(self, project):
        """`not_found` is the interesting answer: hypotheses that cannot hold
        together make a statement true and useless."""
        self._prepare(project)
        registry = scripted_registry(
            project,
            auditor=[
                audit_reply(
                    non_vacuous={
                        "verdict": "not_found",
                        "witness": "",
                        "conflict": "H1 needs s > 3/2 and H3 forces s < 1",
                    }
                )
            ],
        )
        report = audit_role.audit(project, "t", registry=registry)
        assert not report.clean
        assert "H1 needs s > 3/2" in graph_of(project)["t"].notes_section

    def test_out_of_reach_does_not_read_as_a_pass(self, project):
        self._prepare(project)
        registry = scripted_registry(
            project,
            auditor=[
                audit_reply(
                    non_vacuous={"verdict": "out_of_reach", "witness": "", "conflict": ""}
                )
            ],
        )
        report = audit_role.audit(project, "t", registry=registry)
        assert report.verdict == "flagged"
        assert "out of reach" in audit_role.summarise(report)

    def test_the_summary_says_what_the_role_is_worth(self, project):
        self._prepare(project)
        registry = scripted_registry(project, auditor=[audit_reply()])
        text = audit_role.summarise(audit_role.audit(project, "t", registry=registry))
        assert "prompts for your attention, not checks" in text


# --- the verifier's three jobs, levels, batching -------------------------------


ENTAILS = json_reply({"entails": True, "why": "yes", "confidence": "high"})
NO_OBJECTION = json_reply({"checked": ["the whole argument"], "objections": []})


class TestLevels:
    def _prepare(self, project, claims=None):
        write_node(
            project,
            "t",
            target=True,
            children=["c"],
            proof="By `c` we are done.",
            hypotheses=[{"id": "H1", "tex": "a > 0"}],
            uses={"c": {"applied_to": "x", "discharges": {"H1": "hypothesis:H1"}}},
        )
        write_node(
            project, "c", statement="The lemma.", hypotheses=[{"id": "H1", "tex": "a > 0"}]
        )
        if claims:
            from bp.hash import proof_hash

            graph = ops.open_graph(project)
            ops.record_ledger(project, "t", claims, proof_hash(graph["t"]))

    def test_quick_runs_the_proof_pass_only(self, project):
        """No extractor, no obligation checks — and the record says `ledger:
        not_run` rather than reporting zero unsourced claims from a ledger nobody
        extracted."""
        self._prepare(project)
        registry = scripted_registry(
            project, verifier_a=[NO_OBJECTION], verifier_b=[NO_OBJECTION]
        )
        report = verify_role.verify(project, "t", registry=registry, level="quick")
        assert report.verdict == "verified"
        assert report.obligations_checked == 0
        assert not report.ledger_ran
        assert report.record.deterministic["ledger"] == "not_run"
        assert report.record.level == "quick"

    def test_standard_adds_extraction_and_the_obligation_checks(self, project):
        self._prepare(project)
        registry = scripted_registry(
            project,
            extractor=[
                json_reply(
                    {
                        "claims": [
                            {
                                "id": "c1",
                                "text": "a > 0",
                                "source": {"kind": "hypothesis", "ref": "H1"},
                            }
                        ]
                    }
                )
            ],
            obligation=[ENTAILS],
            verifier_a=[NO_OBJECTION],
            verifier_b=[NO_OBJECTION],
        )
        report = verify_role.verify(project, "t", registry=registry, level="standard")
        assert report.verdict == "verified"
        assert report.ledger_ran and report.ledger_claims == 1
        assert report.obligations_checked == 1
        # No claim checks at `standard`: the record says so honestly.
        assert report.claims_checked == 0
        assert report.record.ledger["checked"] == 0
        assert report.record.deterministic["ledger"] == "pass"

    def test_deep_checks_every_claim_and_audits_the_statement(self, project):
        self._prepare(
            project,
            claims=[
                {"id": "c1", "text": "a > 0", "source": {"kind": "hypothesis", "ref": "H1"}},
                {"id": "c2", "text": "the lemma", "source": {"kind": "child", "ref": "c"}},
            ],
        )
        registry = scripted_registry(
            project,
            obligation=[ENTAILS, ENTAILS, ENTAILS],
            verifier_a=[NO_OBJECTION],
            verifier_b=[NO_OBJECTION],
            auditor=[audit_reply()],
        )
        report = verify_role.verify(project, "t", registry=registry, level="deep")
        assert report.verdict == "verified"
        assert report.claims_checked == 2
        assert report.record.ledger["checked"] == 2
        assert report.statement_audit == "pass"
        assert report.record.statement_audit == "pass"

    def test_a_failed_claim_check_flags_the_node(self, project):
        """Premise smuggling: the prose attributes a claim to a lemma that does not
        give it. Indistinguishable from a good citation until somebody asks about
        that one claim on its own."""
        self._prepare(
            project,
            claims=[{"id": "c1", "text": "a > 5", "source": {"kind": "child", "ref": "c"}}],
        )
        registry = scripted_registry(
            project,
            obligation=[
                ENTAILS,
                json_reply(
                    {"entails": False, "why": "the lemma gives a > 0, not a > 5",
                     "confidence": "high"}
                ),
            ],
            verifier_a=[NO_OBJECTION],
            verifier_b=[NO_OBJECTION],
            auditor=[audit_reply()],
            confirmer=[json_reply({"upheld": True, "why": "a > 0 does not give a > 5"})],
        )
        report = verify_role.verify(project, "t", registry=registry, level="deep")
        assert report.verdict == "flagged"
        assert report.claims_flagged == 1
        assert report.record.ledger["flagged"] == 1
        assert any(f.kind == "claim-unjustified" for f in report.flags)

    def test_an_unsourced_claim_alone_flags_the_node(self, project):
        """No agent has to object: LED001 is a deterministic error, and the derived
        status refuses `verified` while it stands."""
        self._prepare(
            project,
            claims=[{"id": "c1", "text": "\\omega \\in C^1", "source": {"kind": "none"}}],
        )
        registry = scripted_registry(
            project,
            obligation=[ENTAILS],
            verifier_a=[NO_OBJECTION],
            verifier_b=[NO_OBJECTION],
        )
        report = verify_role.verify(project, "t", registry=registry, level="standard")
        assert report.verdict == "flagged"
        assert report.ledger_unsourced == 1
        assert "no source" in " ".join(report.reasons)

    def test_an_unknown_level_is_refused_before_anything_is_spent(self, project):
        self._prepare(project)
        registry = scripted_registry(project)
        with pytest.raises(ops.OpError) as exc:
            verify_role.verify(project, "t", registry=registry, level="thorough")
        assert "quick" in str(exc.value)

    def test_extraction_is_skipped_when_the_ledger_is_current(self, project):
        """The ledger is a function of the proof text, so an unchanged proof means
        an unchanged ledger and there is nothing to buy. No extractor response is
        scripted here, so a call would fail the test."""
        self._prepare(
            project,
            claims=[{"id": "c1", "text": "a > 0", "source": {"kind": "hypothesis", "ref": "H1"}}],
        )
        registry = scripted_registry(
            project, obligation=[ENTAILS], verifier_a=[NO_OBJECTION], verifier_b=[NO_OBJECTION]
        )
        report = verify_role.verify(project, "t", registry=registry, level="standard")
        assert report.ledger_ran and report.ledger_claims == 1
        assert report.verdict == "verified"

    def test_a_run_that_does_not_read_the_proof_cannot_record(self, project):
        self._prepare(project)
        registry = scripted_registry(project, obligation=[ENTAILS])
        with pytest.raises(ops.OpError) as exc:
            verify_role.verify(project, "t", registry=registry, proof=False)
        assert "whole-proof pass" in str(exc.value)
        assert graph_of(project)["t"].local_status == "unverified"

    def test_the_verdict_and_the_record_always_agree(self, project):
        self._prepare(project)
        registry = scripted_registry(
            project, obligation=[ENTAILS], verifier_a=[NO_OBJECTION], verifier_b=[NO_OBJECTION]
        )
        verify_role.verify(project, "t", registry=registry, level="standard")
        node = graph_of(project)["t"]
        from bp import verification as verification_mod

        assert verification_mod.implied_status(node.verification) == node.local_status


class TestBatching:
    def _prepare(self, project):
        hyps = [{"id": f"H{i}", "tex": f"x_{i} > 0"} for i in (1, 2, 3)]
        write_node(
            project,
            "t",
            target=True,
            children=["c"],
            proof="By `c` we are done.",
            hypotheses=hyps,
            uses={
                "c": {
                    "applied_to": "x",
                    "discharges": {f"H{i}": f"hypothesis:H{i}" for i in (1, 2, 3)},
                }
            },
        )
        write_node(project, "c", statement="The lemma.", hypotheses=hyps)

    def test_batch_one_is_one_call_per_record(self, project):
        self._prepare(project)
        registry = scripted_registry(
            project,
            obligation=[ENTAILS, ENTAILS, ENTAILS],
            verifier_a=[NO_OBJECTION],
            verifier_b=[NO_OBJECTION],
        )
        report = verify_role.verify(project, "t", registry=registry, batch=1)
        assert report.obligations_checked == 3
        assert len([c for c in report.calls if c.role == "obligation"]) == 3

    def test_batching_sends_several_records_in_one_call(self, project):
        self._prepare(project)
        batched = json_reply(
            {
                "verdicts": [
                    {"id": f"ob:t:c:H{i}", "entails": True, "why": "yes", "confidence": "high"}
                    for i in (1, 2, 3)
                ]
            }
        )
        registry = scripted_registry(
            project,
            obligation=[batched],
            verifier_a=[NO_OBJECTION],
            verifier_b=[NO_OBJECTION],
        )
        report = verify_role.verify(project, "t", registry=registry, batch=3)
        assert report.obligations_checked == 3
        assert len([c for c in report.calls if c.role == "obligation"]) == 1
        assert report.verdict == "verified"

    def test_a_batched_reply_that_skips_a_question_fails_it_closed(self, project):
        """An unanswered question is not a pass. This is the reliability that
        batching trades away, which is why --batch defaults to 1."""
        self._prepare(project)
        partial = json_reply(
            {
                "verdicts": [
                    {"id": "ob:t:c:H1", "entails": True, "why": "yes", "confidence": "high"}
                ]
            }
        )
        registry = scripted_registry(
            project,
            obligation=[partial],
            verifier_a=[NO_OBJECTION],
            verifier_b=[NO_OBJECTION],
            confirmer=[
                json_reply({"upheld": True, "why": "still unanswered"}),
                json_reply({"upheld": True, "why": "still unanswered"}),
            ],
        )
        report = verify_role.verify(project, "t", registry=registry, batch=3)
        assert report.verdict == "flagged"
        assert report.obligations_flagged == 2

    def test_the_unanswered_flag_says_to_re_run_unbatched(self, project):
        """Checked before confirmation, which rewrites `why` with its own sharper
        restatement of an upheld objection."""
        self._prepare(project)
        partial = json_reply(
            {
                "verdicts": [
                    {"id": "ob:t:c:H1", "entails": True, "why": "yes", "confidence": "high"}
                ]
            }
        )
        registry = scripted_registry(project, obligation=[partial])
        report = verify_role.verify_obligations(project, "t", registry=registry, batch=3)
        assert len(report.flags) == 2
        assert all("--batch 1" in f.why for f in report.flags)
