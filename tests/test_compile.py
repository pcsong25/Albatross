"""Compiling the document, and saying something useful when it does not compile.

Two groups. :class:`TestClassify` is pure text-in/diagnosis-out over real pdflatex
log fragments, so it runs everywhere. :class:`TestCompile` actually shells out to
pdflatex and is skipped when there is none — but when there is one it covers the
bug that motivated this module: **a failing compile used to serve the previous
run's PDF**, because the code checked only whether the file existed.
"""

from __future__ import annotations

import pytest

from bp import compile as compile_mod

pdflatex = pytest.mark.skipif(
    compile_mod.engine() is None, reason="no pdflatex on PATH"
)


MISSING_PACKAGE_LOG = r"""
This is pdfTeX, Version 3.141592653-2.6-1.40.29 (TeX Live 2026)
(./document.tex
LaTeX2e <2025-06-01>
(/usr/local/texlive/2026basic/texmf-dist/tex/latex/base/article.cls
Document Class: article 2025/01/22 v1.4n Standard LaTeX document class
)
! LaTeX Error: File `enumitem.sty' not found.

Type X to quit or <RETURN> to proceed,
or enter new name. (Default extension: sty)

Enter file name:
! Emergency stop.
<read *>
l.44 \newcommand
"""

MISSING_DOLLAR_LOG = r"""
! Missing $ inserted.
<inserted text>
                $
l.183 ...w$ child:gclm.critical-scale-domination.}
"""

UNDEFINED_CS_LOG = r"""
! Undefined control sequence.
l.92 \ip
        {u}{v}
"""

WARNINGS_LOG = r"""
LaTeX Warning: Reference `sec-space' on page 1 undefined on input line 66.
LaTeX Warning: Reference `sec-space' on page 1 undefined on input line 85.
LaTeX Warning: Label `eq:main' multiply defined.
LaTeX Warning: There were undefined references.
"""


class TestClassify:
    def test_a_missing_package_is_named_with_the_command_that_installs_it(self):
        """The failure the user actually hit. "Internal server error" was one
        `tlmgr install` away from being a fixed problem."""
        problem = compile_mod.classify(MISSING_PACKAGE_LOG)
        assert problem is not None
        assert problem.kind == "missing_package"
        assert "enumitem" in problem.message
        assert "tlmgr install enumitem" in problem.hint
        # And the escape hatch, for someone who would rather not install it.
        assert "IfFileExists" in problem.hint

    def test_a_missing_non_package_file_says_where_the_document_lives(self):
        problem = compile_mod.classify("! LaTeX Error: File `figure.pdf' not found.")
        assert problem.kind == "missing_file"
        assert ".bp/build" in problem.hint

    def test_missing_dollars_points_at_free_text_sources(self):
        problem = compile_mod.classify(MISSING_DOLLAR_LOG)
        assert problem.kind == "missing_dollar"
        # This repo's actual recurring cause, so the hint names it.
        assert "proof:" in problem.hint
        assert "183" in problem.hint

    def test_an_undefined_command_is_named(self):
        problem = compile_mod.classify(UNDEFINED_CS_LOG)
        assert problem.kind == "undefined_command"
        assert "\\ip" in problem.message
        assert "preamble.tex" in problem.hint

    def test_an_undefined_environment_is_distinguished_from_a_command(self):
        problem = compile_mod.classify("! LaTeX Error: Environment align undefined.")
        assert problem.kind == "undefined_environment"
        assert "align" in problem.message

    def test_an_unbalanced_brace_is_recognised(self):
        problem = compile_mod.classify(
            "Runaway argument?\n{the statement\n! Paragraph ended before \\bpmark was complete."
        )
        assert problem.kind == "unbalanced"

    def test_an_unrecognised_error_still_reports_the_first_one(self):
        problem = compile_mod.classify("! Dimension too large.\nl.7 \\hbox")
        assert problem.kind == "latex_error"
        assert "Dimension too large" in problem.message

    def test_an_empty_log_is_reported_rather_than_read_as_success(self):
        problem = compile_mod.classify("")
        assert problem is not None
        assert problem.kind == "no_output"

    def test_a_clean_log_classifies_as_no_problem(self):
        assert compile_mod.classify("Output written on document.pdf (3 pages).") is None

    def test_the_first_error_wins_over_its_consequences(self):
        """A missing package causes a cascade. Reporting the cascade instead of the
        cause sends the user after the wrong thing."""
        problem = compile_mod.classify(
            MISSING_PACKAGE_LOG + "\n! Undefined control sequence.\nl.99 \\item"
        )
        assert problem.kind == "missing_package"


class TestWarnings:
    def test_undefined_refs_and_duplicate_labels_are_collected(self):
        refs, labels = compile_mod.warnings_in(WARNINGS_LOG)
        assert refs == ["sec-space"]        # de-duplicated
        assert labels == ["eq:main"]

    def test_the_warnings_read_as_english(self):
        result = compile_mod.CompileResult(
            ok=True, undefined_refs=["sec-space"], duplicate_labels=["eq:main"]
        )
        text = " ".join(result.warnings)
        assert "prints ??" in text
        assert "may point at the wrong place" in text

    def test_a_clean_log_has_no_warnings(self):
        assert compile_mod.warnings_in("Output written on document.pdf") == ([], [])


DOC = r"""\documentclass{article}
\usepackage{amsmath}
\begin{document}
Hello. \begin{equation}\label{eq:one} a = b \end{equation}
And \eqref{eq:one}.
\end{document}
"""

BROKEN = r"""\documentclass{article}
\usepackage{a-package-that-does-not-exist}
\begin{document}
Hello.
\end{document}
"""

DANGLING = r"""\documentclass{article}
\begin{document}
See Section \ref{nowhere}.
\end{document}
"""


@pdflatex
class TestCompile:
    def test_a_good_document_compiles(self, tmp_path):
        result = compile_mod.compile_pdf(DOC, tmp_path)
        assert result.ok
        assert result.pdf is not None and result.pdf.exists()
        assert result.problem is None

    def test_a_cross_reference_resolves_in_two_passes(self, tmp_path):
        """`\\eqref` needs the .aux from a previous run, which is why the default is
        two passes. One pass leaves an undefined reference."""
        one = compile_mod.compile_pdf(DOC, tmp_path, name="one", passes=1)
        assert one.ok
        assert one.undefined_refs == ["eq:one"]

        two = compile_mod.compile_pdf(DOC, tmp_path, name="two", passes=2)
        assert two.ok
        assert two.undefined_refs == []

    def test_a_missing_package_is_diagnosed_end_to_end(self, tmp_path):
        result = compile_mod.compile_pdf(BROKEN, tmp_path)
        assert not result.ok
        assert result.problem.kind == "missing_package"
        assert "a-package-that-does-not-exist" in result.problem.message

    def test_a_dangling_ref_compiles_but_is_reported(self, tmp_path):
        """LaTeX only warns and prints ??. Reporting it is the whole point: a
        successful compile is not the same as a correct document."""
        result = compile_mod.compile_pdf(DANGLING, tmp_path)
        assert result.ok
        assert result.undefined_refs == ["nowhere"]
        assert result.warnings

    def test_a_failing_compile_never_serves_the_previous_pdf(self, tmp_path):
        """The bug this module was written for.

        The build directory persists, so a previous `document.pdf` is sitting there
        while the current one fails. Checking only `pdf.exists()` returned last
        week's document and the user read it as their current graph — the worst
        available failure for a tool whose promise is that the document never
        drifts from the graph.
        """
        good = compile_mod.compile_pdf(DOC, tmp_path)
        assert good.ok and good.pdf.exists()

        bad = compile_mod.compile_pdf(BROKEN, tmp_path)
        assert not bad.ok
        assert bad.pdf is None
        # And the stale file is gone, so nothing downstream can serve it either.
        assert not (tmp_path / "document.pdf").exists()

    def test_a_stale_aux_does_not_survive_into_the_next_run(self, tmp_path):
        """A .aux from a document with different labels resolves references to
        numbers that are no longer right, and the second pass confirms them."""
        compile_mod.compile_pdf(DOC, tmp_path)
        assert (tmp_path / "document.aux").exists()
        result = compile_mod.compile_pdf(DANGLING, tmp_path)
        assert result.ok
        aux = (tmp_path / "document.aux").read_text()
        assert "eq:one" not in aux


class TestNoEngine:
    def test_no_pdflatex_is_a_501_shaped_answer_not_a_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr(compile_mod, "engine", lambda: None)
        result = compile_mod.compile_pdf(DOC, tmp_path)
        assert not result.ok
        assert result.problem.kind == "no_engine"
        assert "download button" in result.problem.hint
