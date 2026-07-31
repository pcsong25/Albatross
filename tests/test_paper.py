"""The optional exposition: the writer role and the artifact it produces.

Two things are actually under test, and neither is "did the model write nice prose"
— nothing here can check that. What can be checked, and is:

*Nothing is silently dropped.* An outline that leaves a node out, a section that
says nothing about a node it was given, a `stated` claim with no `\\label` — each is
a deterministic rejection with a repair round behind it. Those checks are the only
guarantee this document offers, so they get the most tests.

*The document compiles, with its apparatus in it.* A render path that has never
been through pdflatex does not work; that lesson is written down in CLAUDE.md and
was paid for by `bp render --audit`. So the paper is compiled here for real,
including the failure cases (a section that was never written, an admitted node),
whenever there is a pdflatex to run it with.
"""

from __future__ import annotations

import json

import pytest

from bp import compile as compile_mod, ops, paper as paper_mod
from bp.agents.base import AgentError
from bp.checks import load_graph
from bp.roles import paper as paper_role

from .conftest import json_reply, scripted_registry, write_node

pdflatex = pytest.mark.skipif(
    compile_mod.engine() is None, reason="no pdflatex on PATH"
)


# --- a small development ------------------------------------------------------


def development(project):
    """Three nodes, one of them admitted, so the honesty apparatus has work to do."""
    write_node(
        project,
        "x.main",
        target=True,
        difficulty="hard",
        statement="For every $s>3/2$ the solution blows up in finite time.",
        proof="By `x.elb` and `x.riccati` the claim follows.",
        children=["x.elb", "x.riccati"],
        hypotheses=[{"id": "H1", "tex": "s > 3/2"}],
        uses={
            "x.elb": {"applied_to": "\\omega", "discharges": {"H1": "hypothesis:H1"}},
            "x.riccati": {"applied_to": "E(t)", "discharges": {"H1": "child:x.elb"}},
        },
    )
    write_node(
        project,
        "x.elb",
        statement="The energy satisfies $E(t) \\ge c t^{-1}$.",
        proof="Integrate by parts.",
        hypotheses=[{"id": "H1", "tex": "s > 3/2"}],
        local_status="verified",
    )
    write_node(
        project,
        "x.riccati",
        statement="A Riccati inequality blows up.",
        proof="Standard ODE comparison.",
        hypotheses=[{"id": "H1", "tex": "E(0) > 0"}],
        local_status="admitted",
        status_reason="taken from the literature, not reproved here",
    )
    return project


def graph_of(project):
    g, _, ok = load_graph(project)
    assert ok
    return g


OUTLINE = {
    "title": "Blow-up for a model equation",
    "abstract": "We prove finite-time blow-up under a Riccati assumption.",
    "sections": [
        {"heading": "Introduction", "purpose": "state the theorem", "nodes": ["x.main"]},
        {"heading": "The energy lower bound", "purpose": "the estimate", "nodes": ["x.elb"]},
        {"heading": "The ODE step", "purpose": "conclude", "nodes": ["x.riccati"]},
    ],
    "notes": "x.riccati is admitted, so the theorem here is conditional.",
}


def section(node_id, *, extra="", stated=True, merged_where="", departures=(), lost=()):
    tex = (
        f"\\begin{{lemma}}\\label{{paper:{node_id}}}\nA statement.\n\\end{{lemma}}\n{extra}"
        if stated
        else f"The content of it is folded in here.\n{extra}"
    )
    return {
        "tex": tex,
        "stated": [node_id] if stated else [],
        "merged": [] if stated else [{"id": node_id, "where": merged_where or "in the proof"}],
        "departures": list(departures),
        "lost": list(lost),
    }


def scripted(project, outline=OUTLINE, sections=None, **extra):
    replies = [json_reply(outline)]
    replies += [json_reply(s) for s in (sections or [])]
    return scripted_registry(project, writer=replies, **extra)


def full_run(project, **kw):
    sections = [
        section("x.main", extra="See Lemma~\\ref{paper:x.elb}.",
                departures=["the hypotheses are written as a sentence"]),
        section("x.elb"),
        section("x.riccati", lost=["the literature reference for the comparison"]),
    ]
    registry = scripted(project, sections=sections)
    return paper_role.write(project, registry=registry, **kw)


# --- the completeness checks --------------------------------------------------


class TestCompleteness:
    """The one thing code can guarantee about an exposition: nothing vanished."""

    def test_an_outline_that_drops_a_node_is_repaired(self, project):
        development(project)
        short = json.loads(json.dumps(OUTLINE))
        short["sections"] = short["sections"][:2]  # x.riccati has no home
        registry = scripted_registry(
            project,
            writer=[
                json_reply(short),
                json_reply(OUTLINE),  # the repair round
                json_reply(section("x.main")),
                json_reply(section("x.elb")),
                json_reply(section("x.riccati")),
            ],
        )
        report = paper_role.write(project, registry=registry)
        assert report.clean
        assert report.draft.unplaced == []
        # Five calls: two outlines and three sections. The repair happened.
        assert len(report.calls) == 5

    def test_a_node_the_outline_never_places_is_named_not_hidden(self, project):
        development(project)
        short = json.loads(json.dumps(OUTLINE))
        short["sections"] = short["sections"][:2]
        registry = scripted_registry(
            project,
            writer=[
                json_reply(short),
                json_reply(short),  # declines to repair
                json_reply(section("x.main")),
                json_reply(section("x.elb")),
            ],
        )
        report = paper_role.write(project, registry=registry)
        assert not report.clean
        assert [d.code for d in report.diagnostics if d.severity == "error"] == ["PAP001"]
        assert report.draft.unplaced == ["x.riccati"]

        graph = graph_of(project)
        tex = paper_mod.document(report.draft, graph)
        assert "x.riccati" in tex
        assert "Never placed by the outline" in tex

    def test_a_section_silent_about_a_node_is_repaired(self, project):
        development(project)
        silent = {"tex": "Some prose.", "stated": [], "merged": [], "departures": [], "lost": []}
        registry = scripted_registry(
            project,
            writer=[
                json_reply(OUTLINE),
                json_reply(silent),            # says nothing about x.main
                json_reply(section("x.main")),  # the repair
                json_reply(section("x.elb")),
                json_reply(section("x.riccati")),
            ],
        )
        report = paper_role.write(project, registry=registry)
        assert report.clean
        assert report.draft.sections[0].stated == ["x.main"]

    def test_a_stated_node_without_its_label_is_rejected(self, project):
        development(project)
        unlabelled = {
            "tex": "\\begin{theorem}\nA statement.\n\\end{theorem}",
            "stated": ["x.main"], "merged": [], "departures": [], "lost": [],
        }
        registry = scripted_registry(
            project,
            writer=[json_reply(OUTLINE), json_reply(unlabelled), json_reply(unlabelled),
                    json_reply(section("x.elb")), json_reply(section("x.riccati"))],
        )
        report = paper_role.write(project, registry=registry)
        codes = [d.code for d in report.diagnostics if d.severity == "error"]
        assert codes == ["PAP004"]

    def test_a_merged_node_is_accounted_for_and_traceable(self, project):
        development(project)
        registry = scripted(project, sections=[
            section("x.main"),
            section("x.elb", stated=False, merged_where="Step 1 of the main proof"),
            section("x.riccati"),
        ])
        report = paper_role.write(project, registry=registry)
        assert report.clean
        assert paper_mod.check(report.draft, graph_of(project)) == []
        placement = report.draft.placement()
        assert placement["x.elb"][1] == "merged"
        tex = paper_mod.document(report.draft, graph_of(project))
        assert "Step 1 of the main proof" in tex

    def test_a_reference_to_nothing_is_reported(self, project):
        development(project)
        stray = section("x.main", extra="As in Lemma~\\ref{paper:x.nonexistent}.")
        registry = scripted(project, sections=[stray, section("x.elb"), section("x.riccati")])
        report = paper_role.write(project, registry=registry)
        # A warning, not an error: LaTeX prints `??` rather than failing, and the
        # rest of the paper is worth having.
        assert [d.code for d in report.diagnostics if d.code.startswith("PAP")] == ["PAP005"]
        assert report.clean

    def test_unbalanced_maths_in_a_section_is_caught_before_pdflatex(self, project):
        development(project)
        broken = section("x.main", extra="An unclosed $x + 1 dollar.")
        registry = scripted(project, sections=[
            broken, broken, section("x.elb"), section("x.riccati")
        ])
        report = paper_role.write(project, registry=registry)
        assert "TEX002" in [d.code for d in report.diagnostics]


# --- failure, and what the document says about it ------------------------------


class TestFailureIsVisible:
    def test_a_section_that_could_not_be_written_says_so_in_the_paper(self, project):
        development(project)
        # Two replies short: the third section's call and its repair both fail.
        registry = scripted(project, sections=[section("x.main"), section("x.elb")])
        report = paper_role.write(project, registry=registry)
        assert report.failed == ["The ODE step"]
        assert not report.clean
        assert [d.code for d in report.diagnostics if d.severity == "error"] == ["PAP006"]

        draft = report.draft
        assert draft.sections[2].failed
        tex = paper_mod.document(draft, graph_of(project))
        assert "This section was not written" in tex
        # And the node it would have covered is still named.
        assert "x.riccati" in tex

    def test_the_budget_cap_stops_the_run_and_the_paper_says_where(self, project):
        development(project)
        from bp.agents.base import Budget

        registry = scripted(project, sections=[section("x.main"), section("x.elb"),
                                               section("x.riccati")])
        registry.budget = Budget(max_calls=2)  # the outline and one section
        report = paper_role.write(project, registry=registry)
        assert report.stopped
        assert [s.heading for s in report.draft.failed_sections] == [
            "The energy lower bound", "The ODE step"
        ]
        # Two skipped sections, two PAP006s. A cap that fired must not be the one
        # path that reports a clean paper.
        assert [d.code for d in report.diagnostics if d.severity == "error"] == [
            "PAP006", "PAP006"
        ]
        assert not report.clean

    def test_a_cycle_is_refused_before_any_call(self, project):
        write_node(project, "a", children=["b"], target=True)
        write_node(project, "b", children=["a"])
        registry = scripted_registry(project)  # no replies at all
        with pytest.raises(ops.OpError):
            paper_role.write(project, registry=registry)

    def test_an_unparseable_node_is_refused_rather_than_written_around(self, project):
        development(project)
        (project.nodes_dir / "x.broken.md").write_text(
            "---\nid: [not, a, string\n---\n\n## Statement\n\nBroken.\n", encoding="utf-8"
        )
        registry = scripted_registry(project)
        with pytest.raises(ops.OpError) as exc:
            paper_role.write(project, registry=registry)
        assert "part of a graph" in str(exc.value)


# --- the artifact -------------------------------------------------------------


class TestArtifact:
    def test_the_draft_round_trips_through_disk(self, project):
        development(project)
        report = full_run(project)
        assert report.path == paper_mod.draft_path(project)
        again = paper_mod.load(project)
        assert again == report.draft

    def test_nothing_in_the_graph_is_touched(self, project):
        development(project)
        before = {p.name: p.read_text() for p in project.nodes_dir.glob("*.md")}
        events_before = project.events_path.read_text() if project.events_path.exists() else ""
        full_run(project)
        after = {p.name: p.read_text() for p in project.nodes_dir.glob("*.md")}
        assert after == before
        events_after = project.events_path.read_text() if project.events_path.exists() else ""
        assert events_after == events_before

    def test_a_draft_from_another_version_is_refused_not_guessed_at(self, project):
        development(project)
        full_run(project)
        path = paper_mod.draft_path(project)
        data = json.loads(path.read_text())
        data["version"] = 999
        path.write_text(json.dumps(data))
        with pytest.raises(paper_mod.DraftUnreadable):
            paper_mod.load(project)

    def test_editing_a_node_makes_the_paper_stale(self, project):
        development(project)
        report = full_run(project)
        graph = graph_of(project)
        assert not paper_mod.changes(report.draft, graph).stale

        ops.edit_statement(project, "x.elb", "The energy satisfies $E(t) \\ge 1$.")
        delta = paper_mod.changes(report.draft, graph_of(project))
        assert delta.stale and delta.changed == ["x.elb"]
        assert "edited" in delta.sentence()

    def test_editing_a_proof_makes_it_stale_too(self, project):
        """The exposition reproduces proofs, so a proof edit invalidates it exactly
        as a statement edit does."""
        development(project)
        report = full_run(project)
        ops.edit_proof(project, "x.elb", "A different argument entirely.")
        assert paper_mod.changes(report.draft, graph_of(project)).changed == ["x.elb"]

    def test_a_new_node_and_an_archived_one_both_register(self, project):
        development(project)
        report = full_run(project)
        ops.add_node(project, "x.extra", statement="Another lemma.")
        ops.archive(project, "x.riccati")
        delta = paper_mod.changes(report.draft, graph_of(project))
        assert delta.added == ["x.extra"]
        assert delta.removed == ["x.riccati"]

    def test_the_title_can_be_overridden(self, project):
        development(project)
        report = full_run(project, title="Notes on blow-up")
        assert report.draft.title == "Notes on blow-up"


class TestApparatus:
    """The parts of the document no agent can write, and no agent can remove."""

    def test_the_provenance_note_and_the_appendix_are_always_there(self, project):
        development(project)
        report = full_run(project)
        tex = paper_mod.document(report.draft, graph_of(project))
        assert "Provenance" in tex
        assert "sec:bp-provenance" in tex
        for node_id in ("x.main", "x.elb", "x.riccati"):
            assert node_id in tex

    def test_an_admitted_node_is_named_as_admitted_whatever_the_prose_says(self, project):
        development(project)
        report = full_run(project)
        tex = paper_mod.document(report.draft, graph_of(project))
        assert "stated here without proof (admitted)" in tex
        assert "taken from the literature, not reproved here" in tex
        # And it is named whether or not the target happens to rest on it — every
        # admitted node in the graph is one the reader meets.
        assert "no verified proof" in tex

    def test_a_conditional_target_says_what_it_is_conditional_on(self, project):
        development(project)
        ops.record_verification(project, "x.main", "verified")
        report = full_run(project)
        tex = paper_mod.document(report.draft, graph_of(project))
        assert "relative to" in tex
        assert "x.riccati" in tex

    def test_the_declared_losses_reach_the_document(self, project):
        development(project)
        report = full_run(project)
        tex = paper_mod.document(report.draft, graph_of(project))
        assert "the literature reference for the comparison" in tex
        assert "the hypotheses are written as a sentence" in tex

    def test_bare_drops_the_apparatus_and_only_the_apparatus(self, project):
        development(project)
        report = full_run(project)
        graph = graph_of(project)
        bare = paper_mod.document(report.draft, graph, apparatus=False)
        assert "Provenance" not in bare
        assert "sec:bp-provenance" not in bare
        # The mathematics is untouched.
        assert "\\label{paper:x.elb}" in bare
        assert "Blow-up for a model equation" in bare

    def test_the_preamble_is_the_same_one_the_development_gets(self, project):
        """One preamble file, so `preamble_facts` cannot be describing a document
        nobody renders."""
        from bp import render

        development(project)
        report = full_run(project)
        tex = paper_mod.document(report.draft, graph_of(project))
        for package in ("amsmath", "hyperref", "geometry"):
            assert f"{{{package}}}" in tex
        assert render.default_preamble(clean=True).split("\n")[0] in tex

    def test_the_project_preamble_is_injected(self, project):
        development(project)
        project.preamble_path.write_text("\\newcommand{\\HH}{\\mathcal H}\n", encoding="utf-8")
        report = full_run(project)
        tex = paper_mod.document(
            report.draft, graph_of(project), preamble=ops.read_preamble(project)
        )
        assert "\\newcommand{\\HH}{\\mathcal H}" in tex


# --- the estimate -------------------------------------------------------------


class TestEstimate:
    def test_it_makes_no_call_and_names_a_floor(self, project):
        development(project)
        registry = scripted_registry(project)  # no replies: a call would fail
        est = paper_role.estimate(project, registry=registry)
        assert est.nodes == 3
        assert est.calls == 1 + est.sections
        assert "floor" in est.describe()

    def test_a_subscription_backend_is_counted_rather_than_priced(self, project):
        development(project)
        registry = scripted_registry(project)  # `scripted` has no price table entry
        est = paper_role.estimate(project, registry=registry)
        assert est.estimated_usd is None
        assert est.unpriced_calls == est.calls


# --- compiling it -------------------------------------------------------------


@pdflatex
class TestCompiles:
    """Every render mode needs a real compile. This one is a render mode."""

    def _compile(self, project, tex, name="paper"):
        result = compile_mod.compile_pdf(tex, project.build_dir, name=name, preamble="")
        assert result.ok, (
            result.problem.kind if result.problem else "?",
            result.problem.message if result.problem else "",
            result.problem.excerpt if result.problem else "",
        )
        assert not result.undefined_refs
        return result

    def test_the_paper_compiles(self, project):
        development(project)
        report = full_run(project)
        self._compile(project, paper_mod.document(report.draft, graph_of(project)))

    def test_it_compiles_bare(self, project):
        development(project)
        report = full_run(project)
        self._compile(
            project,
            paper_mod.document(report.draft, graph_of(project), apparatus=False),
            name="paper-bare",
        )

    def test_it_compiles_with_a_section_that_failed(self, project):
        development(project)
        registry = scripted(project, sections=[section("x.main"), section("x.elb")])
        report = paper_role.write(project, registry=registry)
        self._compile(project, paper_mod.document(report.draft, graph_of(project)))

    def test_it_compiles_with_a_two_paragraph_reason_in_the_apparatus(self, project):
        """The `\\bp*` macros take model-written free text and a blank line in a short
        argument is "Paragraph ended before \\bpmark was complete" and no PDF. The
        paper's apparatus takes the same text from the same places."""
        development(project)
        ops.admit(project, "x.riccati", "First paragraph of the reason.\n\nSecond one.")
        report = full_run(project)
        self._compile(project, paper_mod.document(report.draft, graph_of(project)))

    def test_a_percent_in_the_prose_does_not_swallow_the_page(self, project):
        development(project)
        registry = scripted(project, sections=[
            section("x.main", extra="It improves by 5% in the interior."),
            section("x.elb"),
            section("x.riccati"),
        ])
        report = paper_role.write(project, registry=registry)
        tex = paper_mod.document(report.draft, graph_of(project))
        assert "5\\%" in tex
        self._compile(project, tex)
