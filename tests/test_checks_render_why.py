"""The check runner, the explainer, and the renderer."""

from __future__ import annotations

import re

from bp import checks, render, why
from bp.checks import load_graph

from .conftest import write_node


def graph(project):
    g, _, ok = load_graph(project)
    assert ok
    return g


def codes(report):
    return sorted(d.code for d in report.diagnostics)


class TestChecks:
    def test_use001_declared_child_never_cited(self, project):
        write_node(project, "t", target=True, children=["c"],
                   proof="An argument that forgets to use its lemma.")
        write_node(project, "c")
        assert "USE001" in codes(checks.run(project))

    def test_use001_silent_when_the_child_is_cited(self, project):
        write_node(project, "t", target=True, children=["c"], proof="by c we are done")
        write_node(project, "c")
        assert "USE001" not in codes(checks.run(project))

    def test_use001_does_not_match_an_id_inside_a_longer_word(self, project):
        write_node(project, "t", target=True, children=["a"],
                   proof="never mention the actual lemma")
        write_node(project, "a")
        assert "USE001" in codes(checks.run(project))

    def test_sch002_flags_a_misspelled_key(self, project):
        write_node(project, "t", target=True, childern=["c"])
        write_node(project, "c")
        report = checks.run(project)
        assert "SCH002" in codes(report)
        assert any("childern" in d.message for d in report.diagnostics)

    def test_sch003_verified_with_nothing_behind_it(self, project):
        write_node(project, "t", target=True, local_status="verified")
        assert "SCH003" in codes(checks.run(project))

    def test_sys001_reports_stale_computed_fields(self, project):
        write_node(project, "t", target=True, local_status="verified", proof="p")
        assert "SYS001" in codes(checks.run(project))

    def test_unparseable_file_becomes_a_diagnostic_not_a_crash(self, project):
        write_node(project, "t", target=True)
        (project.nodes_dir / "broken.md").write_text("no frontmatter\n", encoding="utf-8")
        report = checks.run(project)
        assert "SCH001" in codes(report)
        assert report.errors

    def test_exit_status_is_driven_by_errors_only(self, project):
        write_node(project, "t", target=True, proof="p")
        report = checks.run(project)
        assert report.warnings
        assert report.ok is True


class TestWhy:
    def test_chain_reads_as_english(self, project):
        write_node(project, "t", target=True, children=["a", "b"],
                   local_status="verified", proof="cites a and b")
        write_node(project, "a", proof="an unverified argument")
        write_node(project, "b", local_status="verified", proof="p")
        text = why.text(graph(project), "t")
        assert "not finished" in text
        assert "nobody has verified it yet" in text
        assert "`b`" not in text  # b is fine, so it is not part of the answer

    def test_stale_says_which_statement_moved(self, project):
        write_node(project, "t", target=True, children=["c"], local_status="verified",
                   proof="cites c", verified_against={"self": "aaa", "c": "old"})
        write_node(project, "c", local_status="verified", proof="p")
        g = graph(project)
        g["t"].verified_against["self"] = g["t"].statement_hash
        text = why.text(g, "t")
        assert "`c`" in text and "changed since" in text

    def test_proved_says_so_plainly(self, project):
        write_node(project, "t", target=True, local_status="verified", proof="p")
        assert "rests on nothing outstanding" in why.text(graph(project), "t")

    def test_support_is_spelled_out_with_reasons(self, project):
        write_node(project, "t", target=True, children=["c"], local_status="verified",
                   proof="cites c")
        write_node(project, "c", local_status="admitted",
                   status_reason="no argument for this yet")
        text = why.text(graph(project), "t")
        assert "holds relative to 1 item" in text
        assert "no argument for this yet" in text

    def test_shared_child_is_not_re_explained(self, project):
        write_node(project, "t", target=True, children=["a", "b"],
                   local_status="verified", proof="cites a and b")
        write_node(project, "a", children=["shared"], local_status="verified",
                   proof="cites shared")
        write_node(project, "b", children=["shared"], local_status="verified",
                   proof="cites shared")
        write_node(project, "shared")
        text = why.text(graph(project), "t")
        assert text.count("has no proof yet") == 1
        assert "as above" in text


class TestRender:
    def test_target_is_last_and_children_come_first(self, project):
        write_node(project, "t", target=True, children=["c"], proof="cites c",
                   statement="The theorem.")
        write_node(project, "c", statement="The lemma.")
        tex = render.document(graph(project), today="2026-01-01")
        assert tex.index("The lemma.") < tex.index("The theorem.")

    def test_unproved_nodes_are_marked_and_proved_ones_are_not(self, project):
        write_node(project, "t", target=True, children=["c"], local_status="verified",
                   proof="cites c")
        write_node(project, "c", local_status="verified", proof="p")
        write_node(project, "loose", proof="")
        tex = render.document(graph(project), today="2026-01-01")
        assert "\\bpmark{Orange}{open}" in tex  # the loose, unproved node
        # the proved lemma carries no apparatus at all: nothing between the
        # preceding node's end and this one's declaration.
        body = tex.split("\\begin{document}", 1)[1]
        before = body[: body.index("\\begin{lemma}[\\texttt{c}]")]
        assert "\\bpmark{" not in before[-200:]

    def test_admitted_nodes_are_boxed_and_labelled_as_assumptions(self, project):
        write_node(project, "t", target=True, children=["c"], local_status="verified",
                   proof="cites c")
        write_node(project, "c", local_status="admitted", status_reason="believed",
                   proof="a sketch")
        tex = render.document(graph(project), today="2026-01-01")
        assert "\\begin{bpbox}" in tex
        assert "\\begin{assumption}[\\texttt{c}]" in tex
        assert "Sketch --- this is not a proof." in tex
        assert "\\begin{proof}\na sketch" not in tex

    def test_clean_mode_omits_every_marker(self, project):
        write_node(project, "t", target=True, children=["c"], proof="cites c")
        write_node(project, "c")
        tex = render.document(graph(project), clean=True, today="2026-01-01")
        assert "\\section*{Status}" not in tex
        assert "\\bpmark{" not in tex.split("\\begin{document}")[1]

    def test_certificate_lists_what_the_theorem_rests_on(self, project):
        write_node(project, "t", target=True, children=["c"], local_status="verified",
                   proof="cites c")
        write_node(project, "c", local_status="admitted", status_reason="believed")
        tex = render.document(graph(project), today="2026-01-01")
        assert "holds relative to the following 1 item" in tex
        assert "believed" in tex

    def test_backticked_ids_become_cross_references(self, project):
        write_node(project, "t", target=True, children=["c"], proof="by `c` we finish")
        write_node(project, "c")
        tex = render.document(graph(project), today="2026-01-01")
        assert "\\hyperref[node:c]{\\texttt{c}}" in tex
        assert "by `c`" not in tex

    def test_hypothesis_fragments_are_put_into_math_mode(self, project):
        write_node(project, "t", target=True, hypotheses=[{"id": "H1", "tex": "s > 3/2"}])
        tex = render.document(graph(project), today="2026-01-01")
        assert "$s > 3/2$" in tex

    def test_authored_latex_is_not_escaped(self, project):
        write_node(project, "t", target=True, local_status="admitted",
                   status_reason="needs $\\varepsilon_0$ small")
        tex = render.document(graph(project), today="2026-01-01")
        assert "$\\varepsilon_0$" in tex
        assert "textbackslash" not in tex

    def test_a_stray_percent_is_defused_rather_than_swallowing_a_line(self):
        assert render.prose("50% of the mass") == "50\\% of the mass"
        assert render.prose("already \\% escaped") == "already \\% escaped"

    def test_unreachable_nodes_go_to_an_appendix_not_the_bin(self, project):
        write_node(project, "t", target=True, statement="Target.")
        write_node(project, "stray", statement="Stray lemma.")
        tex = render.document(graph(project), today="2026-01-01")
        assert "\\appendix" in tex
        assert "Stray lemma." in tex

    def test_render_is_deterministic(self, project):
        write_node(project, "t", target=True, children=["c"], proof="cites c")
        write_node(project, "c")
        g = graph(project)
        assert render.document(g, today="2026-01-01") == render.document(
            g, today="2026-01-01"
        )


def test_shipped_fixture_renders_without_placeholders(fixture_project):
    g, _, ok = load_graph(fixture_project)
    assert ok
    tex = render.document(g, today="2026-01-01")
    assert "\\begin{document}" in tex and "\\end{document}" in tex
    assert re.search(r"\(\(\(|\(\(\*", tex) is None  # no unrendered template markers
    assert "gclm.blowup" in tex
