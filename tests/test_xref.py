"""Cross-references between nodes: XRF001-XRF005, and resolved numbers.

Every node renders into one LaTeX document, so a `\\label` in one node and an
`\\eqref` in another already resolve. What this module adds is that the two ways
such a reference goes *silently* wrong — dangling, and duplicated — become hard
errors instead of LaTeX warnings nobody reads.

The severity split is the thing to keep straight, and it follows this codebase's
rule everywhere else: **errors are for silently wrong, warnings for legal but
almost always a mistake.**

* `XRF001` dangling → error. The PDF prints `??`.
* `XRF002` duplicate → error. One definition silently wins.
* `XRF003` out of scope → warn. Resolves correctly; the structure is wrong.
* `XRF004` into another node's proof → warn. Same.
* `XRF005` never referenced → warn. Harmless.
"""

from __future__ import annotations

import pytest

from bp import xref
from bp.checks import load_graph
from bp.graph import Graph
from bp.load import load_nodes

from .conftest import write_node


def graph_of(project) -> Graph:
    nodes, errors = load_nodes(project)
    assert not errors, errors
    return Graph(nodes)


def codes(diagnostics):
    return sorted(d.code for d in diagnostics)


def by_code(diagnostics, code):
    return [d for d in diagnostics if d.code == code]


class TestScanning:
    def test_labels_and_refs_are_found_in_both_sections(self, project):
        write_node(
            project,
            "t",
            target=True,
            statement="A display \\begin{equation}\\label{eq:one} a=b \\end{equation}",
            proof="By \\eqref{eq:one} and \\label{step:two} we go on.",
        )
        node = graph_of(project)["t"]
        assert {(l.name, l.section) for l in xref.labels_in(node)} == {
            ("eq:one", "Statement"),
            ("step:two", "Proof"),
        }
        assert [(r.name, r.command) for r in xref.refs_in(node)] == [("eq:one", "eqref")]

    def test_commented_out_text_defines_and_references_nothing(self, project):
        """A label inside a LaTeX comment defines nothing. Firing on text the author
        has already commented out is how a check earns being ignored."""
        write_node(
            project,
            "t",
            target=True,
            statement="Live.\n% \\label{eq:dead} and \\ref{eq:ghost}\n",
        )
        node = graph_of(project)["t"]
        assert xref.labels_in(node) == []
        assert xref.refs_in(node) == []

    def test_an_escaped_percent_is_not_a_comment(self, project):
        write_node(project, "t", target=True, statement="50\\% then \\label{eq:live}")
        assert [l.name for l in xref.labels_in(graph_of(project)["t"])] == ["eq:live"]

    @pytest.mark.parametrize(
        "command", ["ref", "eqref", "cref", "Cref", "autoref", "nameref", "pageref", "vref"]
    )
    def test_every_referencing_command_is_understood(self, project, command):
        write_node(project, "t", target=True, statement=f"See \\{command}{{eq:one}}.")
        refs = xref.refs_in(graph_of(project)["t"])
        assert [(r.name, r.command) for r in refs] == [("eq:one", command)]

    def test_a_multi_target_cref_yields_one_ref_each(self, project):
        """`\\cref{a,b}` is two dependencies, and a check that saw one would miss
        half of them."""
        write_node(project, "t", target=True, statement="See \\cref{eq:one, eq:two}.")
        refs = xref.refs_in(graph_of(project)["t"])
        assert sorted(r.name for r in refs) == ["eq:one", "eq:two"]

    def test_whitespace_around_the_brace_is_tolerated(self, project):
        write_node(project, "t", target=True, statement="\\label {eq:one} \\ref {eq:one}")
        node = graph_of(project)["t"]
        assert [l.name for l in xref.labels_in(node)] == ["eq:one"]
        assert [r.name for r in xref.refs_in(node)] == ["eq:one"]


def pair(project, *, parent_statement="Parent.", parent_proof="By `c`.",
         child_statement="Child.", child_proof=""):
    write_node(
        project, "t", target=True, children=["c"],
        statement=parent_statement, proof=parent_proof,
        uses={"c": {"applied_to": "x", "discharges": {}}},
    )
    write_node(project, "c", statement=child_statement, proof=child_proof)
    return graph_of(project)


class TestChecks:
    def test_a_self_contained_reference_is_clean(self, project):
        g = pair(
            project,
            parent_statement="\\begin{equation}\\label{eq:one} a=b \\end{equation}",
            parent_proof="By `c` and \\eqref{eq:one} we are done.",
        )
        assert xref.check_xref(g) == []

    def test_XRF001_a_dangling_reference_is_an_error(self, project):
        """The reported case: a model wrote "Section \\ref{sec-space}" for a section
        that does not exist. LaTeX only warns and prints ??."""
        g = pair(project, child_statement="In the setting of Section \\ref{sec-space}.")
        d = by_code(xref.check_xref(g), "XRF001")
        assert len(d) == 1
        assert d[0].severity == "error"
        assert d[0].node == "c"
        assert "sec-space" in d[0].message
        assert "??" in (d[0].hint or "")

    def test_XRF002_a_duplicate_label_is_an_error(self, project):
        """LaTeX lets one win silently, so a reference can resolve to the wrong
        equation with nothing said at all."""
        g = pair(
            project,
            parent_statement="\\begin{equation}\\label{eq:one} a=b \\end{equation}",
            parent_proof="By `c` and \\eqref{eq:one}.",
            child_statement="\\begin{equation}\\label{eq:one} x=y \\end{equation}",
        )
        d = by_code(xref.check_xref(g), "XRF002")
        assert len(d) == 1
        assert d[0].severity == "error"
        assert "t" in d[0].message and "c" in d[0].message
        assert "prefix them with the node id" in (d[0].hint or "")

    def test_XRF003_a_child_referencing_its_parent_warns(self, project):
        """What the user asked for. It works — so it warns rather than erroring —
        but it makes the child unreadable on its own, which is what the verifier
        actually does with it."""
        g = pair(
            project,
            parent_statement="\\begin{equation}\\label{eq:main} a=b \\end{equation}",
            child_statement="With \\eqref{eq:main} in mind, this holds.",
        )
        d = by_code(xref.check_xref(g), "XRF003")
        assert len(d) == 1
        assert d[0].severity == "warn"
        assert d[0].node == "c"
        assert "cites this one" in d[0].message
        # And the hint names the fix, rather than only the problem.
        assert "its own node" in (d[0].hint or "")

    def test_a_parent_referencing_its_child_is_clean(self, project):
        """The legitimate direction: a proof may lean on the statements it cites,
        and the verifier is handed exactly those."""
        g = pair(
            project,
            parent_proof="By `c` and \\eqref{eq:child} we are done.",
            child_statement="\\begin{equation}\\label{eq:child} x=y \\end{equation}",
        )
        assert by_code(xref.check_xref(g), "XRF003") == []

    def test_a_reference_to_a_transitive_descendant_is_clean(self, project):
        write_node(project, "t", target=True, children=["mid"],
                   proof="By `mid` and \\eqref{eq:deep}.")
        write_node(project, "mid", children=["deep"], proof="By `deep`.")
        write_node(project, "deep",
                   statement="\\begin{equation}\\label{eq:deep} q=r \\end{equation}")
        assert by_code(xref.check_xref(graph_of(project)), "XRF003") == []

    def test_XRF003_an_unrelated_node_warns_about_the_undeclared_dependency(self, project):
        write_node(project, "t", target=True, children=["c"], proof="By `c`.",
                   uses={"c": {"applied_to": "x", "discharges": {}}})
        write_node(project, "c", statement="See \\eqref{eq:elsewhere}.")
        write_node(project, "other",
                   statement="\\begin{equation}\\label{eq:elsewhere} u=v \\end{equation}")
        d = by_code(xref.check_xref(graph_of(project)), "XRF003")
        assert len(d) == 1
        assert d[0].severity == "warn"
        assert "does not cite" in d[0].message

    def test_XRF004_referencing_into_another_nodes_proof_warns(self, project):
        """A proof is private: the verifier is only ever handed statements, so
        depending on another node's proof text is a coupling nothing reports when it
        breaks."""
        g = pair(
            project,
            parent_proof="By `c` and \\eqref{step:inner} we are done.",
            child_proof="\\begin{equation}\\label{step:inner} p=q \\end{equation}",
        )
        d = by_code(xref.check_xref(g), "XRF004")
        assert len(d) == 1
        assert d[0].severity == "warn"
        assert "*proof*" in d[0].message

    def test_referencing_a_label_in_ones_own_proof_is_fine(self, project):
        g = pair(
            project,
            parent_proof="By `c`. \\begin{equation}\\label{s:1} a=b \\end{equation} "
            "Then \\eqref{s:1}.",
        )
        assert by_code(xref.check_xref(g), "XRF004") == []

    def test_XRF005_an_unreferenced_label_is_only_a_warning(self, project):
        g = pair(
            project,
            parent_statement="\\begin{equation}\\label{eq:unused} a=b \\end{equation}",
        )
        d = by_code(xref.check_xref(g), "XRF005")
        assert len(d) == 1
        assert d[0].severity == "warn"

    def test_the_severity_split_is_exactly_as_documented(self, project):
        g = pair(project, child_statement="\\ref{nope}")
        errors = {d.code for d in xref.check_xref(g) if d.severity == "error"}
        assert errors <= {"XRF001", "XRF002"}


class TestIndex:
    def test_edges_expose_the_dependency_the_children_relation_misses(self, project):
        g = pair(
            project,
            parent_proof="By `c` and \\eqref{eq:child}.",
            child_statement="\\begin{equation}\\label{eq:child} x=y \\end{equation}",
        )
        assert xref.build(g).edges() == {("t", "c")}

    def test_define_refuses_to_pick_between_duplicates(self, project):
        g = pair(
            project,
            parent_statement="\\label{eq:one}",
            child_statement="\\label{eq:one}",
        )
        # Ambiguous is not the same as absent, and guessing would be the very bug
        # XRF002 exists to report.
        assert xref.build(g).define("eq:one") is None

    def test_in_scope_is_self_plus_descendants(self, project):
        write_node(project, "t", target=True, children=["mid"], proof="cites mid")
        write_node(project, "mid", children=["deep"], proof="cites deep")
        write_node(project, "deep")
        g = graph_of(project)
        assert xref.in_scope(g, "mid") == {"mid", "deep"}
        assert "t" not in xref.in_scope(g, "mid")

    def test_summarise_reads_as_english_on_an_empty_project(self, project):
        write_node(project, "t", target=True)
        g = graph_of(project)
        text = xref.summarise(xref.build(g), g)
        assert "no \\label or \\ref" in text

    def test_summarise_names_the_dangling_ones(self, project):
        g = pair(project, child_statement="\\ref{sec-space}")
        text = xref.summarise(xref.build(g), g)
        assert "sec-space" in text
        assert "print ?? in the PDF" in text


AUX = r"""
\newlabel{node:c}{{1}{1}{\texttt {c}}{theorem.1}{}}
\newlabel{node:t}{{2}{1}{\texttt {t}}{theorem.2}{}}
\newlabel{eq:main}{{1}{1}{\texttt {t}}{equation.1}{}}
\newlabel{eq:second}{{2}{2}{\texttt {t}}{equation.2}{}}
"""


class TestNumbers:
    def test_numbers_come_from_latex_rather_than_being_predicted(self):
        """Predicting them would mean reimplementing LaTeX's counters — \\notag,
        multi-line align, \\tag, shared theorem counters — and being subtly wrong
        about a number is worse than showing none."""
        assert xref.numbers_from_aux(AUX) == {"eq:main": "1", "eq:second": "2"}

    def test_the_renderers_own_node_anchors_are_not_offered_as_labels(self):
        """`node:t` is generated by the renderer for hyperlinking, not written by
        anybody, so it is not something a user can reference by that name."""
        assert "node:t" not in xref.numbers_from_aux(AUX)

    def test_no_compile_yet_is_an_empty_answer_not_a_failure(self, project):
        write_node(project, "t", target=True)
        assert xref.resolved_numbers(project) == {}

    def test_display_map_carries_the_node_even_without_a_number(self, project):
        """"defined in `gclm.blowup`" is more use to a reader of the graph than
        "(1)" is, so the node is always there and the number is a bonus."""
        g = pair(
            project,
            parent_statement="\\begin{equation}\\label{eq:main} a=b \\end{equation}",
            parent_proof="By `c` and \\eqref{eq:main}.",
        )
        info = xref.display_map(g, project)["eq:main"]
        assert info == {"node": "t", "section": "statement", "number": "", "duplicate": ""}

    def test_display_map_marks_duplicates_so_the_browser_can_show_them_broken(self, project):
        g = pair(project, parent_statement="\\label{eq:one}", child_statement="\\label{eq:one}")
        assert xref.display_map(g, project)["eq:one"]["duplicate"] == "yes"

    def test_numbers_are_picked_up_once_a_compile_has_run(self, project):
        write_node(project, "t", target=True,
                   statement="\\begin{equation}\\label{eq:main} a=b \\end{equation}")
        project.build_dir.mkdir(parents=True, exist_ok=True)
        (project.build_dir / "document.aux").write_text(AUX, encoding="utf-8")
        g = graph_of(project)
        assert xref.display_map(g, project)["eq:main"]["number"] == "1"


class TestRoleContext:
    def test_a_role_is_told_what_a_reference_points_at(self, project):
        """A proof containing `\\eqref{eq:coercivity}` is unreadable without being
        told what that is, and a model that is not told will invent something."""
        g = pair(
            project,
            parent_proof="By `c` and \\eqref{eq:child} we are done.",
            child_statement="\\begin{equation}\\label{eq:child} x=y \\end{equation}",
        )
        note = xref.obligations_note(xref.build(g), "t")
        assert "eq:child" in note
        assert "`c`" in note

    def test_a_dangling_reference_is_flagged_to_the_role_as_a_gap(self, project):
        g = pair(project, child_statement="See \\ref{sec-space}.")
        note = xref.obligations_note(xref.build(g), "c")
        assert "refers to nothing that exists" in note
        assert "Treat it as a gap" in note

    def test_no_references_means_no_block(self, project):
        g = pair(project)
        assert xref.obligations_note(xref.build(g), "t") == ""


class TestIntegration:
    def test_bp_check_runs_the_xref_checks(self, project):
        from bp import checks

        pair(project, child_statement="See \\ref{sec-space}.")
        report = checks.run(project)
        assert "XRF001" in codes(report.diagnostics)
        assert not report.ok

    def test_xref_is_its_own_family_in_the_verification_record(self, project):
        from bp import checks

        pair(project, child_statement="See \\ref{sec-space}.")
        g, _, _ = load_graph(project)
        families = checks.for_node(g, g["c"])
        assert "xref" in families
        assert codes(families["xref"]) == ["XRF001"]
        # And the parent is not blamed for the child's dangling reference.
        assert checks.for_node(g, g["t"])["xref"] == []


class TestAuxStaleness:
    """A number served from an old build is a wrong number presented confidently,
    which is worse than no number: adding a display to a node typeset earlier in
    reading order shifts every later one."""

    def _labelled(self, project):
        write_node(project, "t", target=True,
                   statement="\\begin{equation}\\label{eq:main} a=b \\end{equation}",
                   proof="By \\eqref{eq:main}.")
        project.build_dir.mkdir(parents=True, exist_ok=True)
        (project.build_dir / "document.aux").write_text(AUX, encoding="utf-8")

    def test_a_current_aux_is_used(self, project):
        self._labelled(project)
        import os, time
        # Make the aux unambiguously newer than the node file.
        future = time.time() + 10
        os.utime(project.build_dir / "document.aux", (future, future))
        assert xref.resolved_numbers(project) == {"eq:main": "1", "eq:second": "2"}

    def test_an_aux_older_than_a_node_file_is_refused(self, project):
        self._labelled(project)
        import os, time
        past = time.time() - 3600
        os.utime(project.build_dir / "document.aux", (past, past))
        assert xref.resolved_numbers(project) == {}

    def test_an_aux_older_than_the_preamble_is_refused(self, project):
        self._labelled(project)
        import os, time
        now = time.time()
        os.utime(project.build_dir / "document.aux", (now, now))
        project.preamble_path.write_text("\\newcommand{\\Hs}{H^s}\n", encoding="utf-8")
        os.utime(project.preamble_path, (now + 10, now + 10))
        assert xref.resolved_numbers(project) == {}


class TestStalenessThroughReferences:
    """A cross-reference is a dependency, and staleness has to know about it.

    Without this, a child whose statement says `\\eqref{eq:riccati}` — with the
    equation in another node — keeps its verification when that equation is edited:
    `verified_against` holds `self` and the child hashes, the referenced node is not
    in it, and the node stays green while the text it leans on moves underneath.

    That is *under*-invalidation, which bp/hash.py exists to avoid; it deliberately
    over-invalidates everywhere else because the opposite error lets a certificate
    outlive the claim it certified.
    """

    def _referencing_pair(self, project):
        from bp import ops

        write_node(
            project, "t", target=True, children=["c"], proof="By `c`.",
            statement="\\begin{equation}\\label{eq:riccati} z' \\ge \\kappa z^2 \\end{equation}",
            uses={"c": {"applied_to": "x", "discharges": {}}},
        )
        write_node(
            project, "c",
            statement="With \\eqref{eq:riccati} in mind, this holds.",
            proof="An argument.",
        )
        ops.record_verification(project, "c", "verified")

    def test_the_certificate_records_the_referenced_node(self, project):
        from bp.hash import XREF_PREFIX

        self._referencing_pair(project)
        g, _, _ = load_graph(project)
        assert f"{XREF_PREFIX}t" in g["c"].verified_against
        assert not g["c"].stale

    def test_editing_the_referenced_statement_makes_the_referrer_stale(self, project):
        from bp import ops

        self._referencing_pair(project)
        ops.edit_statement(
            project, "t",
            "\\begin{equation}\\label{eq:riccati} z' \\ge 2\\kappa z^2 \\end{equation}",
        )
        g, _, _ = load_graph(project)
        assert g["c"].stale
        assert g["c"].global_status == "blocked:stale"

    def test_why_names_the_cross_reference_rather_than_only_saying_stale(self, project):
        from bp import ops, why

        self._referencing_pair(project)
        ops.edit_statement(project, "t", "\\begin{equation}\\label{eq:riccati} q=r \\end{equation}")
        g, _, _ = load_graph(project)
        text = why.text(g, "c")
        assert "cross-references" in text
        assert "`t`" in text

    def test_a_node_with_no_references_gets_no_extra_keys(self, project):
        from bp import ops

        write_node(project, "t", target=True, statement="Plain.", proof="An argument.")
        ops.record_verification(project, "t", "verified")
        g, _, _ = load_graph(project)
        assert set(g["t"].verified_against) == {"self"}

    def test_an_older_certificate_without_xref_keys_still_reads_correctly(self, project):
        """The prefix is namespaced so a certificate written before this existed is
        not misread as stale."""
        write_node(
            project, "t", target=True, local_status="verified",
            statement="S.", proof="p", verified_against={"self": "placeholder"},
        )
        g, _, _ = load_graph(project)
        node = g["t"]
        node.verified_against["self"] = node.statement_hash
        from bp.hash import is_stale

        assert not is_stale(node, g)
