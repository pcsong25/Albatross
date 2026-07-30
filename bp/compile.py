"""Running pdflatex, and saying something useful when it fails.

The renderer's job is to produce correct LaTeX. This module's job is the next
question a user actually asks — *why did it not compile?* — and it exists because
the honest answer is almost never "internal server error".

Three things here are deliberate.

**A failure is classified, not dumped.** A 4000-line pdflatex log is not a
diagnostic. `File `enumitem.sty' not found` is a missing package the user can
install in one command, and saying so is the difference between a fixable problem
and a broken tool. Everything this module cannot classify falls back to the first
error block, which is still better than the last fifteen lines of a log.

**A stale PDF is never served.** The build directory persists between runs, so a
previous successful `document.pdf` sits there while the current one fails. The
first version of this code checked only whether the file existed, which meant a
failing compile happily returned last week's document and the user read it
believing it was their current graph. Silently serving stale output is the worst
failure mode available to a tool whose entire purpose is that the document never
drifts from the graph. So the target is deleted before the run, and existence
afterwards means *this* run produced it.

**Warnings are surfaced, not swallowed.** An undefined `\\ref` and a duplicated
`\\label` are only warnings to LaTeX: the build succeeds and the PDF says `??`.
This module reports them alongside a successful compile so they can be shown.
They are also checked deterministically before compilation ever happens — see
:mod:`bp.xref` — and this is the belt to that braces, catching anything written in
raw LaTeX that the check does not model.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

#: pdflatex names a missing package as ``File `enumitem.sty' not found.``
_MISSING_FILE_RE = re.compile(r"File [`'\"]([^'\"]+?)['\"] not found")
_UNDEFINED_CS_RE = re.compile(r"Undefined control sequence.*?\n.*?(\\[A-Za-z@]+)", re.S)
_UNDEFINED_ENV_RE = re.compile(r"Environment ([A-Za-z@*]+) undefined")
_UNDEFINED_REF_RE = re.compile(r"Reference [`'\"]([^'\"]+?)['\"] on page \d+ undefined")
_MULTIPLY_DEFINED_RE = re.compile(r"Label [`'\"]([^'\"]+?)['\"] multiply defined")
#: Content that fell off the page. `\output is active` distinguishes "a line is a
#: bit long" (routine, ignorable) from "a block did not fit and is gone".
_LOST_CONTENT_RE = re.compile(r"Overfull \\vbox \(([\d.]+)pt too high\)[^\n]*output is active")
#: LaTeX asking for another pass. Two is normally enough, but a changed label set
#: can need a third, and stopping early leaves ?? in a document that "succeeded".
_RERUN_RE = re.compile(r"Rerun to get|Label\(s\) may have changed")
_ERROR_BLOCK_RE = re.compile(r"^! (.*)$", re.M)
_LINE_RE = re.compile(r"^l\.(\d+)(.*)$", re.M)

#: Macro definitions in a user's `preamble.tex`, so an "undefined control sequence"
#: can say whether the macro is *absent from their own preamble* — which is almost
#: always the answer — and offer the near-misses.
_DEFINITION_RE = re.compile(
    r"\\(?:def|newcommand|renewcommand|providecommand|DeclareMathOperator\*?|let)\s*"
    r"\{?(\\[A-Za-z@]+)"
)


def defined_macros(preamble: str) -> set[str]:
    return {m.group(1) for m in _DEFINITION_RE.finditer(preamble)}


def _near_misses(name: str, known: set[str], limit: int = 6) -> list[str]:
    """Defined macros that look like the undefined one.

    Not fuzzy string distance — a shared prefix. The real case was `\cV` in a project
    defining `\cX`, `\cY`, `\cA`…: the user has a naming scheme and has missed one
    member of it, and showing the siblings makes that obvious at a glance.
    """
    stem = name.rstrip("0123456789")
    candidates = [
        k
        for k in known
        if k != name
        and len(k) > 1
        and (k.startswith(stem[: max(2, len(stem) - 1)]) or stem.startswith(k[:2]))
    ]
    return sorted(candidates)[:limit]


#: Packages a small TeX installation (BasicTeX, `texlive-latex-base`) does not
#: ship, mapped to the collection that provides them. This is here so the message
#: can name the *one* command that fixes it rather than leaving the user to search.
_TLMGR_HINT = "install it with `tlmgr install {pkg}` (you may need sudo)"
_APT_HINT = "on Debian/Ubuntu, `texlive-latex-extra` covers most of these"


@dataclass
class LatexProblem:
    """One classified reason a document did not compile."""

    kind: str
    message: str
    hint: str = ""
    #: The excerpt of the log this was read from, for the user who wants it.
    excerpt: str = ""

    def describe(self) -> str:
        out = self.message
        if self.hint:
            out += f"\n\n{self.hint}"
        if self.excerpt:
            out += f"\n\n--- from the LaTeX log ---\n{self.excerpt}"
        return out

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "message": self.message,
            "hint": self.hint,
            "excerpt": self.excerpt,
        }


@dataclass
class CompileResult:
    ok: bool
    pdf: Path | None = None
    problem: LatexProblem | None = None
    #: ``\ref`` targets LaTeX could not resolve. A successful compile with these
    #: is a PDF containing ``??``, which is not a success worth being quiet about.
    undefined_refs: list[str] = field(default_factory=list)
    #: Labels defined more than once. One silently wins, so any ``\ref`` to them
    #: may point at the wrong thing.
    duplicate_labels: list[str] = field(default_factory=list)
    #: Overflow amounts, in points, for blocks that fell off a page. A successful
    #: compile with one of these is a PDF missing some of the user's mathematics.
    lost_content: list[str] = field(default_factory=list)
    #: LaTeX still wanted another pass when we stopped. Means numbers may be wrong.
    needs_rerun: bool = False
    log: str = ""

    @property
    def warnings(self) -> list[str]:
        out = []
        for ref in self.undefined_refs:
            out.append(
                f"`\\ref{{{ref}}}` does not resolve to anything, so the document "
                "prints ?? there"
            )
        for label in self.duplicate_labels:
            out.append(
                f"`\\label{{{label}}}` is defined more than once; one silently wins, "
                "so a reference to it may point at the wrong place"
            )
        for amount in self.lost_content:
            out.append(
                f"a block overflowed its page by {amount}pt and part of it is not in "
                "the PDF at all — usually a very long admitted or assumed statement"
            )
        if self.needs_rerun:
            out.append(
                "LaTeX still wanted another pass, so some numbers or references in "
                "this PDF may be one build out of date"
            )
        return out


def _excerpt(log: str, around: int) -> str:
    """A few lines of log either side of an offset, for context."""
    lines = log.splitlines()
    start = max(0, around - 1)
    return "\n".join(lines[start : start + 8]).strip()


def _offset_of(log: str, needle: str) -> int:
    for i, line in enumerate(log.splitlines()):
        if needle in line:
            return i
    return 0


def classify(log: str, preamble: str = "") -> LatexProblem | None:
    """Turn a pdflatex log into one actionable problem, or None if it looks fine.

    Order matters: the most specific and most fixable causes are tested first, so
    a missing package is reported as a missing package rather than as whatever
    knock-on error it caused twenty lines later.
    """
    if not log.strip():
        return LatexProblem(
            kind="no_output",
            message="pdflatex produced no output at all.",
            hint="that usually means the engine could not start. Check that "
            "`pdflatex` runs in a terminal.",
        )

    missing = _MISSING_FILE_RE.search(log)
    if missing:
        name = missing.group(1)
        if name.endswith(".sty"):
            pkg = name[: -len(".sty")]
            return LatexProblem(
                kind="missing_package",
                message=f"The LaTeX package `{pkg}` is not installed, and something "
                f"in this document loads it — most likely a `\\usepackage{{{pkg}}}` "
                "in your preamble.tex.",
                hint=_TLMGR_HINT.format(pkg=pkg)
                + f".\n{_APT_HINT}.\n\nOr, if you would rather not install it, guard "
                f"the line in preamble.tex so the document still builds without it:\n"
                f"    \\IfFileExists{{{name}}}{{\\usepackage{{{pkg}}}}}{{}}\n"
                "though anything that needs the package will then typeset wrongly.",
                excerpt=_excerpt(log, _offset_of(log, missing.group(0))),
            )
        return LatexProblem(
            kind="missing_file",
            message=f"LaTeX could not find the file `{name}`.",
            hint="if it is one of your own files, it has to sit next to the "
            "generated document — which lives in `.bp/build/`, not in the project "
            "root. Inlining the content into preamble.tex is usually simpler.",
            excerpt=_excerpt(log, _offset_of(log, missing.group(0))),
        )

    if "font expansion" in log and "scalable" in log:
        return LatexProblem(
            kind="font_expansion",
            message="`microtype` cannot expand the fonts this document is using, and "
            "pdfTeX treats that as fatal.",
            hint="it happens when a T1-encoded Computer Modern is present as *bitmap* "
            "fonts, which a minimal TeX installation ships. Either install scalable T1 "
            "faces — `tlmgr install lm cm-super` — or drop `\\usepackage{microtype}` "
            "from your preamble.tex; it only affects typographic polish. Albatross "
            "itself only enables T1 when `lmodern` is present, precisely to avoid this.",
            excerpt=_excerpt(log, _offset_of(log, "font expansion")),
        )

    env = _UNDEFINED_ENV_RE.search(log)
    if env:
        return LatexProblem(
            kind="undefined_environment",
            message=f"`\\begin{{{env.group(1)}}}` is not an environment this document "
            "knows about.",
            hint="either the package that defines it is missing from your "
            "preamble.tex, or the name is misspelled. The renderer defines only "
            "theorem, proposition, lemma, definition and assumption itself.",
            excerpt=_excerpt(log, _offset_of(log, env.group(0))),
        )

    errors = _ERROR_BLOCK_RE.findall(log)
    if not errors:
        return None

    first = errors[0].strip()
    offset = _offset_of(log, errors[0])
    line = _LINE_RE.search(log)
    where = ""
    if line:
        where = (
            f"\n\nIt gave up at line {line.group(1)} of the generated document. "
            "Download the .tex to see that line — the line numbers are the "
            "generated file's, not your node file's."
        )

    if first.startswith("Undefined control sequence"):
        cs = _UNDEFINED_CS_RE.search(log)
        name = cs.group(1) if cs else "a command"
        known = defined_macros(preamble or "")
        hint = ""
        if preamble and name != "a command" and name not in known:
            hint = (
                f"`{name}` is **not defined in your preamble.tex**, which defines "
                f"{len(known)} macro(s)."
            )
            near = _near_misses(name, known)
            if near:
                hint += " You do define " + ", ".join(f"`{n}`" for n in near) + "."
            hint += (
                f"\n\nEither add `\\newcommand{{{name}}}{{…}}` to preamble.tex, or "
                "correct the node that uses it. Note that the browser shows an "
                "undefined macro as red literal text rather than refusing — easy to "
                "read past."
            )
        else:
            hint = (
                "if it is your own macro, define it in preamble.tex — that file is "
                "injected into the document, shown to every agent, and parsed by the "
                "browser. If it comes from a package, add the `\\usepackage` there too."
            )
        return LatexProblem(
            kind="undefined_command",
            message=f"`{name}` is not defined.",
            hint=hint + where,
            excerpt=_excerpt(log, offset),
        )

    if "Missing $ inserted" in first:
        return LatexProblem(
            kind="missing_dollar",
            message="Mathematics appears outside math mode.",
            hint="something wrote maths without delimiters. The usual causes are a "
            "`_` or `^` in prose, and a `proof:` or `literature:` discharge source "
            "containing bare maths — those are free text, so maths inside them needs "
            "its own `$...$`. (A hypothesis `tex` and an `applied_to` are the "
            "opposite: fragments, which the renderer wraps for you.)" + where,
            excerpt=_excerpt(log, offset),
        )

    if "Paragraph ended before" in first or "Paragraph ended before" in log:
        return LatexProblem(
            kind="paragraph_in_argument",
            message="A blank line appears in a field that has to be a single "
            "paragraph.",
            hint="the status apparatus, a hypothesis fragment, an admission reason, a "
            "discharge source and an objection are all single-paragraph fields. "
            "Remove the blank line — or, if the text really needs two paragraphs, it "
            "probably wants to be a note on the node instead." + where,
            excerpt=_excerpt(log, offset),
        )

    if "Runaway argument" in log or "File ended while scanning" in log:
        return LatexProblem(
            kind="unbalanced",
            message="A brace or an environment is left open.",
            hint="look for a `{` with no `}`, or a `\\begin{...}` with no matching "
            "`\\end{...}`, in the statement or proof of the node named near the end "
            "of the excerpt below." + where,
            excerpt=_excerpt(log, offset),
        )

    return LatexProblem(
        kind="latex_error",
        message=first,
        hint="the excerpt below is the first thing pdflatex objected to; later "
        "errors are usually consequences of it." + where,
        excerpt=_excerpt(log, offset),
    )


def warnings_in(log: str) -> tuple[list[str], list[str]]:
    """``(undefined refs, duplicate labels)`` from a log, de-duplicated in order."""
    refs: list[str] = []
    for m in _UNDEFINED_REF_RE.finditer(log):
        if m.group(1) not in refs:
            refs.append(m.group(1))
    labels: list[str] = []
    for m in _MULTIPLY_DEFINED_RE.finditer(log):
        if m.group(1) not in labels:
            labels.append(m.group(1))
    return refs, labels


def lost_content_in(log: str) -> list[str]:
    """Blocks that overflowed the page and are therefore not in the PDF.

    A successful compile can still have dropped content: an unbreakable box longer
    than a page runs off the bottom, and the only trace is an ``Overfull \vbox``
    while the output routine is active. That is a silent loss of the user's
    mathematics, so it is reported next to the success.
    """
    return sorted({m.group(1) for m in _LOST_CONTENT_RE.finditer(log)})


def wants_another_pass(log: str) -> bool:
    return bool(_RERUN_RE.search(log))


def engine() -> str | None:
    return shutil.which("pdflatex")


def compile_pdf(
    tex: str,
    workdir: Path,
    name: str = "document",
    *,
    passes: int = 2,
    timeout: float = 180.0,
    preamble: str = "",
) -> CompileResult:
    """Write ``tex`` into ``workdir`` and compile it. Never serves a stale PDF.

    Two passes by default, because ``\\ref``, ``\\eqref`` and hyperref's anchors
    all need the ``.aux`` from a previous run to resolve. ``-halt-on-error`` means
    a failing first pass stops there rather than producing a second, identical
    wall of log.
    """
    binary = engine()
    if binary is None:
        return CompileResult(
            ok=False,
            problem=LatexProblem(
                kind="no_engine",
                message="There is no `pdflatex` on PATH, so no PDF can be built here.",
                hint="the LaTeX source is still available from the download button, "
                "and it compiles anywhere you do have TeX. To install: MacTeX or "
                "BasicTeX on macOS, `texlive-latex-recommended` on Debian/Ubuntu.",
            ),
        )

    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / f"{name}.tex").write_text(tex, encoding="utf-8")

    pdf = workdir / f"{name}.pdf"
    # Delete first. Existence afterwards is then evidence that *this* run
    # succeeded, rather than evidence that some earlier run did.
    pdf.unlink(missing_ok=True)
    # The .aux carries the label table. A stale one from a document with different
    # labels resolves references to numbers that are no longer right, and the
    # second pass would then "confirm" them.
    for suffix in (".aux", ".out", ".toc", ".log"):
        (workdir / f"{name}{suffix}").unlink(missing_ok=True)

    # pdflatex wraps its log at 79 columns *mid-token* by default, which silently
    # breaks every regex below: a document with nine undefined references yielded
    # four, because the wrap fell inside "on page 1 undefined" and the pattern could
    # no longer match locally. `max_print_line` is the documented knob.
    #
    # `-no-shell-escape` because every statement and proof in this document is at
    # least partly model-written, and a `\write18` in one of them executes on a
    # machine configured with `shell_escape=t` — which people who use minted or
    # gnuplot often are. Behaviour should not depend on local TeX configuration.
    env = {**os.environ, "max_print_line": "10000", "error_line": "254",
           "half_error_line": "238"}
    log = ""
    for _ in range(max(1, passes)):
        try:
            result = subprocess.run(
                [
                    binary,
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    "-no-shell-escape",
                    f"{name}.tex",
                ],
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return CompileResult(
                ok=False,
                problem=LatexProblem(
                    kind="timeout",
                    message=f"pdflatex did not finish within {timeout:.0f} seconds.",
                    hint="that is usually an infinite loop in a macro, or a `\\input` "
                    "of something that includes itself. Download the .tex and run "
                    "pdflatex on it by hand to see where it hangs.",
                ),
                log=log,
            )
        log = result.stdout or ""
        if result.returncode != 0:
            break

    # Prefer the log file: pdflatex writes more into it than it puts on stdout.
    log_file = workdir / f"{name}.log"
    if log_file.exists():
        try:
            log = log_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass

    # LaTeX occasionally needs a third pass when the label set has changed. Two is
    # the normal answer; stopping at two anyway would leave ?? in a "successful" PDF.
    if pdf.exists() and wants_another_pass(log) and passes >= 2:
        try:
            subprocess.run(
                [
                    binary,
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    "-no-shell-escape",
                    f"{name}.tex",
                ],
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            if log_file.exists():
                log = log_file.read_text(encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired:
            pass

    refs, labels = warnings_in(log)
    if not pdf.exists():
        return CompileResult(
            ok=False,
            problem=classify(log, preamble)
            or LatexProblem(
                kind="no_pdf",
                message="pdflatex reported no error but produced no PDF.",
                hint="download the .tex and compile it by hand; the log excerpt "
                "below is all there is.",
                excerpt="\n".join(log.splitlines()[-15:]),
            ),
            undefined_refs=refs,
            duplicate_labels=labels,
            lost_content=lost_content_in(log),
            log=log,
        )

    return CompileResult(
        ok=True,
        pdf=pdf,
        undefined_refs=refs,
        duplicate_labels=labels,
        lost_content=lost_content_in(log),
        needs_rerun=wants_another_pass(log),
        log=log,
    )


__all__ = [
    "CompileResult",
    "defined_macros",
    "LatexProblem",
    "classify",
    "compile_pdf",
    "engine",
    "warnings_in",
]
