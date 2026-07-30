"""The check runner, the explainer, and the renderer."""

from __future__ import annotations

import re

from bp import checks, ops, render, why
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


class TestRenderScrutiny:
    """The verification record goes into the document.

    Reading the LaTeX has to tell you how much scrutiny each lemma received. A
    green colour with no provenance is the thing most likely to be over-trusted,
    and the document is what the user actually reads.
    """

    def _record(self, level="standard", **overrides):
        data = {
            "checked_at": "2026-08-03T14:22:00+00:00",
            "level": level,
            "deterministic": {"integrity": "pass", "discharge": "pass"},
            "ledger": {"claims": 3, "unsourced": 0, "checked": 3},
            "obligations": {"total": 2, "verified": 2, "flagged": 0, "cached": 1},
            "whole_proof": {"verifier_a": "no_objection", "verifier_b": "no_objection"},
            "statement_audit": "pass",
        }
        data.update(overrides)
        return data

    def test_the_level_and_the_counts_are_printed(self, project):
        write_node(project, "t", target=True, local_status="verified", proof="p")
        ops.record_verification(project, "t", "verified", record=self._record("deep"))
        tex = render.document(graph(project), today="2026-01-01")
        assert "Checked. level deep" in tex
        assert "3 claim(s), 0 unsourced, 3 checked" in tex

    def test_role_names_are_escaped_not_passed_through(self, project):
        """`verifier_a` in LaTeX text mode is "Missing $ inserted" and no PDF. The
        record is entirely generated text, so it is escaped — unlike anything a
        person wrote, which is LaTeX already."""
        write_node(project, "t", target=True, local_status="verified", proof="p")
        ops.record_verification(project, "t", "verified", record=self._record())
        tex = render.document(graph(project), today="2026-01-01")
        assert "verifier\\_a=no\\_objection" in tex
        assert "verifier_a" not in tex

    def test_a_verified_node_with_no_record_says_so_rather_than_implying_one(self, project):
        write_node(project, "t", target=True, local_status="verified", proof="p")
        ops.record_verification(project, "t", "verified")
        tex = render.document(graph(project), today="2026-01-01")
        assert "No verification record" in tex

    def test_clean_omits_the_record_with_the_rest_of_the_apparatus(self, project):
        write_node(project, "t", target=True, local_status="verified", proof="p")
        ops.record_verification(project, "t", "verified", record=self._record())
        tex = render.document(graph(project), clean=True, today="2026-01-01")
        assert "Checked." not in tex

    def test_an_unverified_node_gets_no_record_line(self, project):
        write_node(project, "t", target=True, proof="p")
        tex = render.document(graph(project), today="2026-01-01")
        assert "Checked." not in tex

    def test_the_audit_view_names_the_unsourced_claims(self, project):
        from bp.hash import proof_hash

        write_node(project, "t", target=True, proof="An argument.")
        g = graph(project)
        ops.record_ledger(
            project,
            "t",
            [
                {"id": "c1", "text": "a > 0", "source": {"kind": "literature", "ref": "Smith"}},
                {"id": "c2", "text": "\\omega \\in C^1", "source": {"kind": "none"}},
            ],
            proof_hash(g["t"]),
        )
        tex = render.document(graph(project), audit=True, today="2026-01-01")
        assert "2 load-bearing claim(s), of which 1 unsourced" in tex
        # Claim text is a math-mode fragment, like a hypothesis `tex`: the renderer
        # supplies the dollars, or it is "Missing $ inserted" and no PDF.
        assert "$\\omega \\in C^1$" in tex

    def test_a_fully_sourced_ledger_is_counted_not_listed(self, project):
        from bp.hash import proof_hash

        write_node(project, "t", target=True, proof="An argument.")
        g = graph(project)
        ops.record_ledger(
            project,
            "t",
            [{"id": "c1", "text": "a > 0", "source": {"kind": "literature", "ref": "Smith"}}],
            proof_hash(g["t"]),
        )
        tex = render.document(graph(project), audit=True, today="2026-01-01")
        assert "1 load-bearing claim(s), each with a named source." in tex


def test_the_shipped_fixture_fires_the_ledger_check_on_exactly_one_claim(fixture_project):
    """Part of the L0 acceptance: the fixture carries a hand-written ledger with a
    deliberately unsourced claim, and LED001 fires on that claim and nothing else."""
    report = checks.run(fixture_project)
    led = [d for d in report.diagnostics if d.code.startswith("LED")]
    assert [d.code for d in led] == ["LED001"]
    assert led[0].node == "gclm.blowup"
    assert "c4" in led[0].message


def test_the_shipped_fixture_has_both_shapes_of_verification_record(fixture_project):
    g, _, ok = load_graph(fixture_project)
    assert ok
    assert g["gclm.elb-a"].verification.level == "deep"
    assert g["gclm.blowup"].verification.level == "standard"
    # And the record on each agrees with the status the node actually carries.
    from bp import verification as verification_mod

    for node_id in ("gclm.elb-a", "gclm.blowup"):
        node = g[node_id]
        assert verification_mod.implied_status(node.verification) == node.local_status


class TestLatexTextChecks:
    """TEX001 and TEX002: the two ways authored LaTeX goes wrong in silence."""

    def test_TEX001_a_midline_percent_is_reported(self, project):
        """It deletes the rest of the line from the PDF, in a document that compiles
        cleanly. `render.prose` was documented as defusing this for bodies and does
        not — and it must not, because the prover writes `% GAP:` comments."""
        write_node(project, "t", target=True,
                   statement="The bound improves by 5% in the interior, hence $x>0$.")
        report = checks.run(project)
        d = [x for x in report.diagnostics if x.code == "TEX001"]
        assert len(d) == 1
        assert d[0].severity == "warn"
        assert "\\%" in (d[0].hint or "")

    def test_a_line_initial_percent_is_a_deliberate_comment(self, project):
        write_node(project, "t", target=True,
                   statement="Real text.\n% a comment, and the prover's % GAP: lines\n")
        assert [d for d in checks.run(project).diagnostics if d.code == "TEX001"] == []

    def test_an_escaped_percent_is_not_reported(self, project):
        write_node(project, "t", target=True, statement="50\\% of the mass.")
        assert [d for d in checks.run(project).diagnostics if d.code == "TEX001"] == []

    def test_TEX002_an_odd_number_of_dollars_is_an_error(self, project):
        write_node(project, "t", target=True, proof="We have $a = b and then we go on.")
        d = [x for x in checks.run(project).diagnostics if x.code == "TEX002"]
        assert len(d) == 1
        assert d[0].severity == "error"
        assert "proof" in d[0].message

    def test_balanced_dollars_are_clean(self, project):
        write_node(project, "t", target=True, proof="We have $a = b$ and $c = d$.")
        assert [d for d in checks.run(project).diagnostics if d.code == "TEX002"] == []

    def test_an_escaped_dollar_does_not_count(self, project):
        write_node(project, "t", target=True, statement="It costs \\$5 and $x>0$.")
        assert [d for d in checks.run(project).diagnostics if d.code == "TEX002"] == []

    def test_a_dollar_inside_a_comment_does_not_count(self, project):
        write_node(project, "t", target=True, statement="$x>0$\n% note about $y$\n")
        assert [d for d in checks.run(project).diagnostics if d.code == "TEX002"] == []


class TestRenderCorruption:
    def test_a_fragment_with_interior_dollars_is_still_wrapped(self):
        """The old rule was "leave it alone if it contains any $", which emitted this
        bare into text mode where `>` is the wrong glyph — the reader saw `s¿3/2`,
        in a document that compiled."""
        out = render.math("s>3/2 \\text{ where $s$ is the regularity}")
        assert out.startswith("$") and out.endswith("$")

    def test_an_already_wrapped_fragment_is_not_double_wrapped(self):
        assert render.math("$s > 3/2$") == "$s > 3/2$"

    def test_an_empty_fragment_stays_empty(self):
        assert render.math("") == ""
        assert render.math("$$") == ""

    def test_latex_open_quotes_survive_reference_resolution(self):
        """`_BACKTICK_RE` knew nothing about the ``quote'' idiom, so the phrase
        between two quotations was set in typewriter — in a document that compiled."""
        text = "the ``good'' case and the ``bad'' case"
        assert render.resolve_refs(text, set()) == text

    def test_a_backticked_node_id_still_becomes_a_link(self):
        out = render.resolve_refs("by `a.b` we are done", {"a.b"})
        assert "\\hyperref[node:a.b]" in out

    def test_a_backticked_non_id_is_left_alone(self):
        text = "the `not an id, this` case"
        assert render.resolve_refs(text, set()) == text
