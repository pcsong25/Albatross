"""Editing a parent: the history, the decomposition certificate, and the amender.

The scenario all three exist for: a mathematician tightens a hypothesis on a node
that already has four children with proofs. Before this, the system's answer was
`bp redo` — archive the subtree and decompose again — and the previous wording of the
statement was gone, because the event log recorded a character count.

What is under test is not "did the model write a good amendment", which nothing can
check. It is the three mechanisms around it:

* the previous text survives every edit (:mod:`bp.history`);
* the decomposition check leaves a certificate, so *checked against different
  wording* is a fact the system can state (``DEC010``);
* every existing child comes back with exactly one verdict, the discharge table is
  re-gated before anything is written, and **nothing is applied that the user did not
  tick**.
"""

from __future__ import annotations

import json

import pytest

from bp import checks, history, ops
from bp.checks import load_graph
from bp.roles import amend as amend_role
from bp.roles import check as check_role

from .conftest import json_reply, scripted_registry, write_node


def graph_of(project):
    g, _, ok = load_graph(project)
    assert ok
    return g


def codes(project, prefix=""):
    return [
        d.code
        for d in checks.run(project).diagnostics
        if d.code.startswith(prefix)
    ]


# --- the history --------------------------------------------------------------


class TestHistory:
    """"Nothing is destroyed" was true of nodes and false of the two fields the user
    actually writes."""

    def test_an_edit_keeps_the_text_it_replaced(self, project):
        write_node(project, "t", target=True, statement="Version one.")
        result = ops.edit_statement(project, "t", "Version two.")
        assert history.previous(project, "t", "Statement").strip() == "Version one."
        # And the event says where it went, rather than only how long it was.
        assert result.event["payload"]["previous"].endswith("0001-statement.tex")

    def test_proofs_are_kept_too(self, project):
        write_node(project, "t", target=True, proof="A first argument.")
        ops.edit_proof(project, "t", "A better argument.")
        assert history.previous(project, "t", "Proof").strip() == "A first argument."

    def test_versions_accumulate_and_stay_in_order(self, project):
        write_node(project, "t", target=True, statement="One.")
        for text in ("Two.", "Three.", "Four."):
            ops.edit_statement(project, "t", text)
        revs = history.revisions(project, "t", "Statement")
        assert [r.seq for r in revs] == [1, 2, 3]
        assert [r.text.strip() for r in revs] == ["One.", "Two.", "Three."]

    def test_the_two_sections_are_numbered_independently(self, project):
        write_node(project, "t", target=True, statement="S1.", proof="P1.")
        ops.edit_statement(project, "t", "S2.")
        ops.edit_proof(project, "t", "P2.")
        assert [(r.section, r.seq) for r in history.revisions(project, "t")] == [
            ("Proof", 1),
            ("Statement", 1),
        ]

    def test_an_edit_that_changes_nothing_keeps_nothing(self, project):
        write_node(project, "t", target=True, statement="Unchanged.")
        ops.edit_statement(project, "t", "Unchanged.")
        assert history.revisions(project, "t") == []

    def test_writing_into_an_empty_section_keeps_nothing(self, project):
        """The prover writing a first proof is not a loss, and a directory full of
        empty files would make the real revisions harder to find."""
        write_node(project, "t", target=True, proof="")
        ops.edit_proof(project, "t", "The first proof.")
        assert history.revisions(project, "t", "Proof") == []

    def test_a_hypothesis_edit_records_the_wording_not_just_the_ids(self, project):
        write_node(project, "t", target=True, hypotheses=[{"id": "H1", "tex": "s > 1"}])
        result = ops.set_hypotheses(project, "t", [{"id": "H1", "tex": "s > 3/2"}])
        assert result.event["payload"]["before"] == [{"id": "H1", "tex": "s > 1"}]
        assert result.event["payload"]["after"] == [{"id": "H1", "tex": "s > 3/2"}]

    def test_a_node_id_is_not_a_path(self, project):
        with pytest.raises(ValueError):
            history.node_dir(project, "../escape")


# --- the decomposition certificate --------------------------------------------


def decomposed(project):
    """A parent with two children, a reduction and a complete discharge table."""
    write_node(
        project,
        "t",
        target=True,
        statement="Let $s>1$. Then it blows up.",
        proof="By `t.elb` and `t.ode` we are done.",
        children=["t.elb", "t.ode"],
        hypotheses=[{"id": "H1", "tex": "s > 1"}],
        uses={
            "t.elb": {"applied_to": "w", "discharges": {"H1": "hypothesis:H1"}},
            "t.ode": {"applied_to": "E", "discharges": {"H1": "child:t.elb"}},
        },
    )
    write_node(
        project,
        "t.elb",
        statement="For $s>1$, $E(t) \\ge c t^{-1}$.",
        proof="Integrate by parts.",
        hypotheses=[{"id": "H1", "tex": "s > 1"}],
    )
    write_node(
        project,
        "t.ode",
        statement="A Riccati inequality blows up.",
        proof="ODE comparison.",
        hypotheses=[{"id": "H1", "tex": "E(0) > 0"}],
    )
    return project


CLEAN_CHECK = {"checked": ["the reduction, step by step"], "problems": []}


def run_check(project):
    registry = scripted_registry(
        project, checker=[json_reply(CLEAN_CHECK), json_reply(CLEAN_CHECK)]
    )
    return check_role.check_decomposition(project, "t", registry=registry)


class TestDecompositionCertificate:
    def test_a_node_with_children_and_no_check_says_so(self, project):
        decomposed(project)
        assert "DEC011" in codes(project, "DEC")

    def test_the_check_records_what_it_checked_against(self, project):
        decomposed(project)
        run_check(project)
        node = graph_of(project)["t"]
        assert node.checked_against["self"] == node.statement_hash
        assert set(node.checked_against) == {"self", "t.elb", "t.ode"}
        assert codes(project, "DEC") == []

    def test_editing_the_parent_makes_it_stale(self, project):
        decomposed(project)
        run_check(project)
        ops.edit_statement(project, "t", "Let $s>3/2$. Then it blows up.")
        assert "DEC010" in codes(project, "DEC")

    def test_editing_a_child_makes_it_stale_too(self, project):
        """The checker's questions are about the parent *and* the children, so the
        certificate covers both — the same set a verification's does."""
        decomposed(project)
        run_check(project)
        ops.edit_statement(project, "t.elb", "For $s>1$, $E(t) \\ge 1$.")
        assert "DEC010" in codes(project, "DEC")

    def test_it_is_recorded_even_when_problems_were_found(self, project):
        """A check that ran and found three problems is not an unchecked node."""
        decomposed(project)
        dirty = {
            "checked": ["the reduction"],
            "problems": [
                {"where": "t.ode", "why": "it assumes what it proves", "confidence": "high"}
            ],
        }
        registry = scripted_registry(
            project, checker=[json_reply(dirty), json_reply(CLEAN_CHECK)]
        )
        report = check_role.check_decomposition(project, "t", registry=registry)
        assert not report.clean
        node = graph_of(project)["t"]
        assert node.checked_against
        # And the findings are on the node, not only in the terminal.
        assert "it assumes what it proves" in node.notes_section

    def test_it_never_moves_a_status(self, project):
        decomposed(project)
        before = graph_of(project)["t"].global_status
        run_check(project)
        ops.edit_statement(project, "t", "Something else entirely.")
        after = graph_of(project)["t"]
        assert after.global_status == before
        assert "DEC010" in codes(project, "DEC")

    def test_a_node_with_no_children_is_never_asked_about(self, project):
        write_node(project, "leaf", target=True, statement="A lemma.")
        assert codes(project, "DEC") == []
        with pytest.raises(ops.OpError):
            ops.record_decomposition_check(project, "leaf")


# --- the amender ---------------------------------------------------------------


def amendment(
    *,
    verdict="amend",
    elb="edit",
    ode="keep",
    new=None,
    reduction=None,
    uses=None,
    include_ode=True,
):
    children = [
        {
            "id": "t.elb",
            "action": elb,
            "why": "the parent now assumes $s>3/2$, so H1 tightens" if elb != "keep" else "",
            **(
                {
                    "statement": "For $s>3/2$, $E(t) \\ge c t^{-1}$.",
                    "hypotheses": [{"id": "H1", "tex": "s > 3/2"}],
                }
                if elb == "edit"
                else {}
            ),
        }
    ]
    if include_ode:
        children.append({"id": "t.ode", "action": ode, "why": "no longer needed"
                         if ode != "keep" else ""})
    table = uses if uses is not None else {
        "t.elb": {"applied_to": "w", "discharges": {"H1": "hypothesis:H1"}},
        "t.ode": {"applied_to": "E", "discharges": {"H1": "child:t.elb"}},
    }
    return {
        "verdict": verdict,
        "assessment": "H1 tightens; the ODE step is unaffected.",
        "children": children,
        "new_children": new or [],
        "reduction_proof": reduction or "",
        "reduction_changed": bool(reduction),
        "uses": table,
        "notes": "",
    }


def edited(project):
    """The scenario: a decomposed, verified node whose hypothesis is tightened."""
    decomposed(project)
    for node_id in ("t.elb", "t.ode", "t"):
        ops.record_verification(project, node_id, "verified")
    ops.edit_statement(project, "t", "Let $s>3/2$. Then it blows up.")
    ops.set_hypotheses(project, "t", [{"id": "H1", "tex": "s > 3/2"}])
    return project


def propose(project, *replies):
    registry = scripted_registry(project, amender=[json_reply(r) for r in replies])
    return amend_role.amend(project, "t", registry=registry)


class TestAmendProposes:
    def test_the_edit_leaves_the_children_alone_and_the_parent_stale(self, project):
        """The state the amender exists for, asserted so the premise cannot rot."""
        edited(project)
        graph = graph_of(project)
        assert graph["t"].global_status == "blocked:stale"
        assert graph["t.elb"].global_status == "proved"
        assert graph["t.ode"].global_status == "proved"

    def test_it_writes_nothing(self, project):
        edited(project)
        before = {p.name: p.read_text() for p in project.nodes_dir.glob("*.md")}
        report = propose(project, amendment())
        assert report.clean
        assert {p.name: p.read_text() for p in project.nodes_dir.glob("*.md")} == before
        assert amend_role.load_proposal(project, "t") is not None

    def test_the_diff_of_the_last_edit_reaches_the_prompt(self, project):
        """The whole reason `bp/history.py` exists: without it the amender has to
        infer what moved from the children."""
        edited(project)
        graph = graph_of(project)
        prompt = amend_role.build_prompt(project, graph, graph["t"])
        assert "-Let $s>1$. Then it blows up." in prompt
        assert "+Let $s>3/2$. Then it blows up." in prompt

    def test_with_no_history_it_says_so_rather_than_pretending(self, project):
        decomposed(project)
        graph = graph_of(project)
        prompt = amend_role.build_prompt(project, graph, graph["t"])
        assert "No earlier version of this statement was recorded" in prompt

    def test_items_carry_the_before_and_after(self, project):
        edited(project)
        report = propose(project, amendment())
        item = report.items[0]
        assert item.key == "child:t.elb"
        assert item.kind == "edit"
        assert "s>1" in item.before
        assert "s>3/2" in item.after
        assert item.hypotheses_before == [{"id": "H1", "tex": "s > 1"}]
        assert item.hypotheses_after == [{"id": "H1", "tex": "s > 3/2"}]
        assert item.why

    def test_a_child_it_says_nothing_about_is_rejected_and_repaired(self, project):
        edited(project)
        report = propose(
            project, amendment(include_ode=False), amendment()
        )
        assert report.clean
        assert report.rounds == 2

    def test_after_the_repair_round_the_omission_is_reported(self, project):
        edited(project)
        report = propose(
            project, amendment(include_ode=False), amendment(include_ode=False)
        )
        assert not report.clean
        assert "AMD001" in [d.code for d in report.diagnostics]

    def test_an_edit_with_no_reason_is_rejected(self, project):
        edited(project)
        bad = amendment()
        bad["children"][0]["why"] = ""
        report = propose(project, bad, bad)
        assert "AMD004" in [d.code for d in report.diagnostics]

    def test_an_amendment_that_changes_nothing_is_rejected(self, project):
        edited(project)
        empty = amendment(elb="keep")
        report = propose(project, empty, empty)
        assert "AMD005" in [d.code for d in report.diagnostics]

    def test_the_discharge_table_is_re_gated_before_anything_is_written(self, project):
        """The point of the exercise. What a parent's edit changes *is* what its
        children can be given, so an amendment that leaves a hypothesis unsourced is
        rejected by the same check a decomposition faces."""
        edited(project)
        unsourced = amendment(
            uses={"t.elb": {"applied_to": "w", "discharges": {}},
                  "t.ode": {"applied_to": "E", "discharges": {"H1": "child:t.elb"}}}
        )
        report = propose(project, unsourced, unsourced)
        assert "DIS011" in [d.code for d in report.diagnostics]
        assert not report.clean

    def test_no_change_is_an_answer_with_no_items(self, project):
        edited(project)
        report = propose(project, amendment(verdict="no-change", elb="keep"))
        assert report.verdict == "no-change"
        assert report.items == []
        assert report.clean

    def test_redecompose_is_an_answer_too(self, project):
        edited(project)
        report = propose(project, amendment(verdict="redecompose", elb="keep"))
        assert report.verdict == "redecompose"
        assert report.items == []
        with pytest.raises(ops.OpError):
            amend_role.apply_amendment(project, "t")

    def test_a_node_with_no_children_is_refused(self, project):
        write_node(project, "leaf", target=True, statement="A lemma.")
        registry = scripted_registry(project)
        with pytest.raises(ops.OpError) as exc:
            amend_role.amend(project, "leaf", registry=registry)
        assert "bp expand" in str(exc.value)


class TestAmendApplies:
    def test_applying_everything_edits_the_child_and_keeps_its_proof(self, project):
        edited(project)
        propose(project, amendment())
        result = amend_role.apply_amendment(project, "t")
        assert result.edited == ["t.elb"]
        child = graph_of(project)["t.elb"]
        assert "s>3/2" in child.statement_section
        assert [h.tex for h in child.hypotheses] == ["s > 3/2"]
        assert child.proof_section.strip() == "Integrate by parts."

    def test_an_edited_child_loses_its_verification_and_a_kept_one_does_not(self, project):
        edited(project)
        propose(project, amendment())
        amend_role.apply_amendment(project, "t")
        graph = graph_of(project)
        assert graph["t.elb"].global_status == "blocked:stale"
        assert graph["t.ode"].global_status == "proved"

    def test_the_subtree_is_copied_before_anything_is_written(self, project):
        edited(project)
        propose(project, amendment())
        result = amend_role.apply_amendment(project, "t")
        assert result.archived_to is not None
        kept = sorted(p.name for p in result.archived_to.glob("*.md"))
        assert kept == ["t.elb.md", "t.md", "t.ode.md"]
        # The copy predates the edit.
        assert "s>1" in (result.archived_to / "t.elb.md").read_text()

    def test_the_previous_statement_is_also_in_the_history(self, project):
        edited(project)
        propose(project, amendment())
        amend_role.apply_amendment(project, "t")
        assert "s>1" in history.previous(project, "t.elb", "Statement")

    def test_rejecting_an_item_applies_nothing(self, project):
        edited(project)
        propose(project, amendment())
        result = amend_role.apply_amendment(project, "t", [])
        assert result.applied == []
        assert result.rejected == ["child:t.elb"]
        assert result.archived_to is None
        assert "s>1" in graph_of(project)["t.elb"].statement_section

    def test_one_item_can_be_taken_and_another_left(self, project):
        edited(project)
        propose(
            project,
            amendment(
                reduction="By `t.elb` alone we are done, citing `t.ode` as well.",
            ),
        )
        result = amend_role.apply_amendment(project, "t", ["reduction"])
        assert result.reduction is True
        assert result.edited == []
        graph = graph_of(project)
        assert "alone" in graph["t"].proof_section
        assert "s>1" in graph["t.elb"].statement_section

    def test_a_dropped_child_is_archived_not_deleted(self, project):
        edited(project)
        propose(
            project,
            amendment(
                ode="drop",
                reduction="By `t.elb` we are done.",
                uses={"t.elb": {"applied_to": "w", "discharges": {"H1": "hypothesis:H1"}}},
            ),
        )
        result = amend_role.apply_amendment(project, "t")
        assert result.dropped == ["t.ode"]
        graph = graph_of(project)
        assert "t.ode" not in graph.active
        assert graph["t.ode"].lifecycle == "archived"
        assert (project.nodes_dir / "t.ode.md").exists()
        assert graph["t"].children == ["t.elb"]

    def test_rejecting_a_drop_keeps_the_child_and_its_discharge_row(self, project):
        """Taking two of four changes must not manufacture a `DIS010` the user did
        not cause."""
        edited(project)
        propose(
            project,
            amendment(
                ode="drop",
                reduction="By `t.elb` we are done.",
                uses={"t.elb": {"applied_to": "w", "discharges": {"H1": "hypothesis:H1"}}},
            ),
        )
        amend_role.apply_amendment(project, "t", ["child:t.elb"])
        graph = graph_of(project)
        assert "t.ode" in graph.active
        assert "t.ode" in graph["t"].uses
        assert graph["t"].uses["t.ode"].discharges == {"H1": "child:t.elb"}
        assert "DIS010" not in codes(project, "DIS")

    def test_a_new_child_is_created_and_cited(self, project):
        edited(project)
        propose(
            project,
            amendment(
                new=[
                    {
                        "slug": "oddness",
                        "role": "lemma",
                        "statement": "An odd datum stays odd.",
                        "difficulty": "routine",
                        "hypotheses": [{"id": "H1", "tex": "\\omega_0 \\text{ odd}"}],
                        "notes": "the new hypothesis needs its own lemma",
                    }
                ],
                reduction="By `t.elb`, `t.ode` and `oddness` we are done.",
                uses={
                    "t.elb": {"applied_to": "w", "discharges": {"H1": "hypothesis:H1"}},
                    "t.ode": {"applied_to": "E", "discharges": {"H1": "child:t.elb"}},
                    "oddness": {"applied_to": "w_0", "discharges": {"H1": "proof:given"}},
                },
            ),
        )
        result = amend_role.apply_amendment(project, "t")
        assert result.added == ["t.oddness"]
        graph = graph_of(project)
        assert graph["t"].children == ["t.elb", "t.ode", "t.oddness"]
        assert "`t.oddness`" in graph["t"].proof_section
        assert "t.oddness" in graph["t"].uses

    def test_a_proposal_made_against_older_text_is_refused(self, project):
        edited(project)
        propose(project, amendment())
        ops.edit_statement(project, "t", "Let $s>2$. Then it blows up.")
        with pytest.raises(ops.OpError) as exc:
            amend_role.apply_amendment(project, "t")
        assert "changed since" in str(exc.value)

    def test_applying_twice_is_refused_for_the_same_reason(self, project):
        edited(project)
        propose(project, amendment())
        amend_role.apply_amendment(project, "t")
        with pytest.raises(ops.OpError):
            amend_role.apply_amendment(project, "t")

    def test_an_unknown_item_key_is_refused(self, project):
        edited(project)
        propose(project, amendment())
        with pytest.raises(ops.OpError) as exc:
            amend_role.apply_amendment(project, "t", ["child:nope"])
        assert "child:nope" in str(exc.value)

    def test_applying_with_no_proposal_is_refused(self, project):
        edited(project)
        with pytest.raises(ops.OpError):
            amend_role.apply_amendment(project, "t")

    def test_a_draft_from_another_version_is_refused(self, project):
        edited(project)
        propose(project, amendment())
        path = amend_role.proposal_path(project, "t")
        data = json.loads(path.read_text())
        data["version"] = 999
        path.write_text(json.dumps(data))
        with pytest.raises(amend_role.ProposalUnreadable):
            amend_role.load_proposal(project, "t")

    def test_the_result_says_the_decomposition_check_is_now_out_of_date(self, project):
        """Applying an amendment moves a child, which invalidates the check that
        approved the decomposition. The user is told at the moment it happens rather
        than at the next `bp check`."""
        decomposed(project)
        run_check(project)
        assert codes(project, "DEC") == []

        ops.edit_statement(project, "t", "Let $s>3/2$. Then it blows up.")
        ops.set_hypotheses(project, "t", [{"id": "H1", "tex": "s > 3/2"}])
        propose(project, amendment())
        result = amend_role.apply_amendment(project, "t")
        assert result.clean
        assert "DEC010" in [d.code for d in result.diagnostics]

    def test_the_apply_summary_names_what_moved(self, project):
        edited(project)
        propose(project, amendment())
        result = amend_role.apply_amendment(project, "t")
        text = amend_role.summarise_apply(result)
        assert "edited: t.elb" in text
        assert "attempts" in text
        assert "re-verify" in text
