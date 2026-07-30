"""The command line.

In v0 this is a testing scaffold: the intended daily interface is the web UI in
L2. It exists so that every operation can be driven and inspected without a
browser, and so that the deterministic core can be exercised on its own.

Every command loads the project, derives statuses in memory, and reports. Only
``sweep`` and the mutation commands write anything.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from . import checks, events as events_mod, frontier as frontier_mod, ops
from . import render as render_mod, verification as verification_mod, why as why_mod
from .discharge import all_obligations, obligations_for
from .ledger import all_claim_obligations, claim_obligations_for
from .xref import all_reference_obligations, reference_obligations_for
from .graph import GraphError
from .paths import ProjectNotFound, find_project
from .propagate import (
    BLOCKED_CHILDREN,
    BLOCKED_OBJECTION,
    BLOCKED_STALE,
    BLOCKED_UNVERIFIED,
    OPEN,
    PROVED,
    PROVED_MODULO,
    UNSOUND,
)

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Albatross / Blueprint v0 — proof decomposition bookkeeping.",
)
console = Console()
err_console = Console(stderr=True)

STATUS_STYLE = {
    PROVED: "bold green",
    PROVED_MODULO: "cyan",
    OPEN: "dim white",
    BLOCKED_UNVERIFIED: "yellow",
    BLOCKED_STALE: "yellow",
    BLOCKED_CHILDREN: "yellow",
    BLOCKED_OBJECTION: "red",
    UNSOUND: "bold red",
    "archived": "dim",
}

SEVERITY_STYLE = {"error": "bold red", "warn": "yellow", "info": "dim cyan"}


def _project(root: Optional[Path] = None):
    try:
        return find_project(root)
    except ProjectNotFound as exc:
        err_console.print(f"[bold red]error[/] {exc}")
        raise typer.Exit(code=2)


def _graph(root: Optional[Path] = None):
    """Load the project, or refuse.

    A node file that will not parse is **fatal here**, not a warning. It used to be
    printed to stderr and then ignored, which is much worse than it sounds: the
    unparseable node is simply absent from the graph, so its parent has one fewer
    child, the sweep finds nothing unfinished beneath it, and `bp render` produces a
    document headed *"top is proved. It rests on no admitted step, no assumption and
    no unfinished lemma."* — with the missing lemma nowhere in it and exit code 0.

    A document derived from a partial graph is worse than no document. This is the
    same call the loader already made for a cycle, applied to the other way the
    graph can be incomplete.
    """
    project = _project(root)
    graph, diagnostics, swept = checks.load_graph(project)
    fatal = [d for d in diagnostics if d.severity == "error"]
    for d in fatal:
        err_console.print(f"[bold red]error[/] {d.message}")
    if fatal:
        err_console.print(
            f"[bold red]error[/] {len(fatal)} node file(s) could not be read, so the "
            "graph is incomplete and anything derived from it would be a claim about "
            "a project you do not have. Fix the file(s) above and try again."
        )
        raise typer.Exit(code=1)
    if not swept:
        err_console.print(
            "[bold red]error[/] the children relation has a cycle, so no status "
            "could be derived. Run `bp check` for the cycle."
        )
        raise typer.Exit(code=1)
    return project, graph


def _status_text(status: str | None) -> Text:
    return Text(status or "?", style=STATUS_STYLE.get(status or "", "white"))


# --- read-only ----------------------------------------------------------------


@app.command()
def status(
    root: Optional[Path] = typer.Option(None, "--root", help="project directory"),
    show_archived: bool = typer.Option(False, "--archived", help="include archived nodes"),
) -> None:
    """One line per node: what it claims, and what it actually rests on."""
    project, graph = _graph(root)
    table = Table(box=None, pad_edge=False, header_style="bold")
    table.add_column("node", overflow="fold")
    table.add_column("role", overflow="fold")
    table.add_column("local", overflow="fold")
    table.add_column("global", overflow="fold")
    table.add_column("rests on", overflow="fold")

    nodes = graph.nodes.values() if show_archived else graph.active.values()
    order = [n for n in graph.reverse_topo_order()]
    ranked = sorted(
        nodes, key=lambda n: (order.index(n.id) if n.id in order else 10**6, n.id)
    )
    for node in ranked:
        rests = ", ".join(node.support) if node.support else ""
        if node.blocked_by:
            rests = "blocked by " + ", ".join(node.blocked_by)
        name = Text(node.id + (" *" if node.target else ""))
        table.add_row(
            name,
            node.role,
            node.local_status + (" (stale)" if node.stale else ""),
            _status_text(node.global_status),
            rests,
        )
    console.print(table)

    target = graph.target
    if target is not None:
        console.print()
        console.print(why_mod.text(graph, target.id).splitlines()[0])


@app.command()
def show(
    node_id: str = typer.Argument(..., help="node id"),
    root: Optional[Path] = typer.Option(None, "--root"),
) -> None:
    """Everything about one node."""
    project, graph = _graph(root)
    node = graph.get(node_id)
    if node is None:
        err_console.print(f"[bold red]error[/] no node {node_id!r}")
        raise typer.Exit(code=2)

    console.print(Text(node.id, style="bold"), _status_text(node.global_status))
    console.print(
        f"  role={node.role}  difficulty={node.difficulty}  local={node.local_status}"
        f"  lifecycle={node.lifecycle}"
    )
    console.print(f"  statement_hash={node.statement_hash}  stale={node.stale}")
    if node.status_reason:
        console.print(Text(f"  reason: {node.status_reason}"))
    if node.support:
        console.print(f"  rests on: {', '.join(node.support)}")
    if node.blocked_by:
        console.print(f"  blocked by: {', '.join(node.blocked_by)}")
    parents = graph.parents(node.id)
    if parents:
        console.print(f"  cited by: {', '.join(parents)}")
    if node.children:
        console.print(f"  children: {', '.join(node.children)}")
    if node.hypotheses:
        console.print("  hypotheses:")
        for h in node.hypotheses:
            console.print(Text(f"    {h.id}: {h.tex}"))
    if node.uses:
        console.print("  uses:")
        for cid, use in node.uses.items():
            console.print(Text(f"    {cid} applied to {use.applied_to or '-'}"))
            for hid, src in sorted(use.discharges.items()):
                console.print(Text(f"      {hid} <- {src}"))
    if node.claims:
        console.print("  claim ledger:")
        for claim in node.claims:
            src = claim.source
            where = "UNSOURCED" if src.kind == "none" else f"{src.kind}:{src.ref}"
            console.print(Text(f"    {claim.id} [{where}] {claim.text}"))
        from .ledger import ledger_is_stale

        if ledger_is_stale(node):
            console.print(
                "    [yellow]extracted from an earlier version of this proof[/]"
            )

    # The verification record, so that `verified` is never an opaque flag: what was
    # checked, at what level, by which model.
    console.print()
    console.print(Text("verification", style="bold"))
    console.print(Text(f"  {verification_mod.compact(node.verification)}"))
    if node.verification is not None:
        reasons = verification_mod.reasons(node.verification)
        for reason in reasons:
            console.print(Text(f"  flagged because: {reason}"))
        if node.verification.models:
            console.print(
                "  models: "
                + ", ".join(
                    f"{k}={v}" for k, v in sorted(node.verification.models.items())
                )
            )
    for section in ("Statement", "Proof", "Notes"):
        text = node.section(section)
        if text.strip():
            console.print()
            console.print(Text(section, style="bold"))
            console.print(Text(text))


@app.command("graph")
def graph_cmd(
    root: Optional[Path] = typer.Option(None, "--root"),
) -> None:
    """The DAG as a tree, rooted at the target."""
    project, graph = _graph(root)
    target = graph.target
    roots = [target.id] if target else sorted(
        n.id for n in graph.active.values() if not graph.parents(n.id)
    )
    if not roots:
        roots = sorted(graph.active)

    printed: set[str] = set()

    def walk(node_id: str, prefix: str, connector: str, last: bool) -> None:
        node = graph.get(node_id)
        if node is None:
            console.print(f"{prefix}{connector}[red]{node_id} (missing)[/]")
            return
        line = Text(prefix + connector)
        line.append(node.id, style="bold" if node.target else "")
        line.append("  ")
        line.append(_status_text(node.global_status))
        seen_before = node_id in printed
        if seen_before and node.children:
            line.append("  (expanded above)", style="dim")
        console.print(line)
        if seen_before:
            return
        printed.add(node_id)
        child_prefix = prefix + ("" if not connector else ("   " if last else "│  "))
        for i, cid in enumerate(node.children):
            is_last = i == len(node.children) - 1
            walk(cid, child_prefix, "└─ " if is_last else "├─ ", is_last)

    for r in roots:
        walk(r, "", "", True)


@app.command()
def why(
    node_id: Optional[str] = typer.Argument(None, help="node id (default: the target)"),
    root: Optional[Path] = typer.Option(None, "--root"),
) -> None:
    """Explain a node's status in plain English. No model involved."""
    project, graph = _graph(root)
    if node_id is None:
        target = graph.target
        if target is None:
            err_console.print("[bold red]error[/] no target node; name one explicitly")
            raise typer.Exit(code=2)
        node_id = target.id
    console.print(Text(why_mod.text(graph, node_id)))


@app.command()
def check(
    root: Optional[Path] = typer.Option(None, "--root"),
    fmt: str = typer.Option("text", "--format", help="text | json"),
    quiet: bool = typer.Option(False, "--quiet", help="errors only"),
) -> None:
    """Run every deterministic check. Exits 1 if anything is an error."""
    project = _project(root)
    report = checks.run(project)

    if fmt == "json":
        console.print_json(
            json.dumps([d.model_dump() for d in report.diagnostics], ensure_ascii=False)
        )
    else:
        shown = report.errors if quiet else report.diagnostics
        for d in shown:
            where = d.node or (Path(d.file).name if d.file else "-")
            console.print(
                Text(where, style="bold"),
                Text(f"{d.severity}[{d.code}]", style=SEVERITY_STYLE[d.severity]),
                Text(d.message),
            )
            if d.hint and not quiet:
                console.print(Text(f"    hint: {d.hint}", style="dim"))
                # Everything a user or an agent writes is LaTeX. `rich` would read
                # `\[` as an escaped bracket and `[dim]` as a style tag, so node
                # text and diagnostic messages are printed as Text, never as markup.
        console.print()
        console.print(
            f"{len(report.errors)} error(s), {len(report.warnings)} warning(s), "
            f"{len(report.notes)} note(s) over {len(report.graph.active)} active nodes"
        )
    raise typer.Exit(code=1 if report.errors else 0)


@app.command()
def obligations(
    node_id: Optional[str] = typer.Argument(None, help="node id (default: all)"),
    root: Optional[Path] = typer.Option(None, "--root"),
    kind: str = typer.Option(
        "all",
        "--kind",
        help="all | discharge | claim | reference — which worklist to emit",
    ),
) -> None:
    """Emit the worklists: one record per discharge, sourced claim, and citation.

    This is what the verifier consumes, and it is generated here — deterministically
    — so that a clean verdict means *all N enumerated checks passed* rather than
    *nothing caught my eye*. Each record carries a content hash, which is what the
    verifier's cache is keyed on.
    """
    project, graph = _graph(root)
    if kind not in {"all", "discharge", "claim", "reference"}:
        err_console.print(
            f"[bold red]error[/] unknown kind {kind!r}; use all, discharge, claim "
            "or reference"
        )
        raise typer.Exit(code=2)
    if node_id is None:
        discharge_records = all_obligations(graph)
        claim_records = all_claim_obligations(graph)
        reference_records = all_reference_obligations(graph)
    else:
        node = graph.get(node_id)
        if node is None:
            err_console.print(f"[bold red]error[/] no node {node_id!r}")
            raise typer.Exit(code=2)
        discharge_records = obligations_for(node, graph)
        claim_records = claim_obligations_for(node, graph)
        reference_records = reference_obligations_for(node, graph)
    records = []
    if kind in {"all", "discharge"}:
        records.extend(discharge_records)
    if kind in {"all", "claim"}:
        records.extend(claim_records)
    if kind in {"all", "reference"}:
        records.extend(reference_records)
    sys.stdout.write(json.dumps(records, indent=2, ensure_ascii=False) + "\n")


@app.command()
def labels(
    root: Optional[Path] = typer.Option(None, "--root"),
) -> None:
    """Every `\\label` and every reference to it, across the whole graph.

    Cross-references work because the renderer puts every node into one document.
    What this adds is that a dangling or duplicated one is a hard error here
    (`XRF001`, `XRF002`) rather than a LaTeX warning nobody reads.
    """
    project, graph = _graph(root)
    from . import xref as xref_mod

    index = xref_mod.build(graph)
    console.print(Text(xref_mod.summarise(index, graph)))
    diagnostics = xref_mod.check_xref(graph, index)
    if diagnostics:
        console.print()
        for d in diagnostics:
            console.print(
                Text(d.node or "-", style="bold"),
                Text(f"{d.severity}[{d.code}]", style=SEVERITY_STYLE[d.severity]),
                Text(d.message),
            )
    numbers = xref_mod.resolved_numbers(project)
    console.print()
    if numbers:
        console.print(
            f"[dim]{len(numbers)} number(s) read back from the last compile in "
            f"{project.build_dir}[/]"
        )
    else:
        console.print(
            "[dim]no numbers yet: run `bp render --pdf` once and they are read back "
            "from LaTeX's own .aux[/]"
        )
    raise typer.Exit(code=1 if any(d.severity == "error" for d in diagnostics) else 0)


@app.command()
def render(
    root: Optional[Path] = typer.Option(None, "--root"),
    clean: bool = typer.Option(False, "--clean", help="omit all status apparatus"),
    audit: bool = typer.Option(False, "--audit", help="include the discharge tables"),
    title: Optional[str] = typer.Option(None, "--title"),
    out: Optional[Path] = typer.Option(None, "-o", "--out"),
    to_stdout: bool = typer.Option(False, "--stdout"),
    pdf: bool = typer.Option(
        False, "--pdf", help="compile it too, and explain any failure"
    ),
) -> None:
    """Render the whole graph to a compilable LaTeX document.

    With ``--pdf`` it also runs pdflatex twice and reports what went wrong in
    terms you can act on — a missing package is named, with the command that
    installs it. Worth reaching for when the browser says a document will not
    compile and you want to see it outside the browser.
    """
    project, graph = _graph(root)
    tex = render_mod.document(
        graph, clean=clean, audit=audit, title=title,
        preamble=ops.read_preamble(project),
    )
    if to_stdout:
        sys.stdout.write(tex)
        return
    path = out or (project.build_dir / ("document-clean.tex" if clean else "document.tex"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tex, encoding="utf-8")
    console.print(f"wrote {path}")
    if not pdf:
        return

    from . import compile as compile_mod

    result = compile_mod.compile_pdf(
        tex, path.parent, name=path.stem, preamble=ops.read_preamble(project)
    )
    for warning in result.warnings:
        console.print(Text(f"warning: {warning}", style="yellow"))
    if result.ok:
        console.print(f"wrote {result.pdf}")
        return
    problem = result.problem
    err_console.print(Text(f"the document did not compile: {problem.kind}", style="bold red"))
    if problem.message:
        err_console.print(Text(problem.message))
    if problem.hint:
        err_console.print(Text(problem.hint, style="dim"))
    if problem.excerpt:
        err_console.print()
        err_console.print(Text(problem.excerpt, style="dim"))
    raise typer.Exit(code=1)


@app.command("events")
def events_cmd(
    root: Optional[Path] = typer.Option(None, "--root"),
    limit: int = typer.Option(40, "--limit"),
) -> None:
    """The event log, most recent last."""
    project = _project(root)
    log = events_mod.read(project)
    for event in log[-limit:]:
        console.print(events_mod.describe(event))
    if not log:
        console.print("[dim]no events yet[/]")


# --- writes -------------------------------------------------------------------


STARTER_STATEMENT = """% Replace this with the theorem you are trying to prove.
% It is LaTeX prose: write it the way you would write it in a paper.
%
% State the hypotheses in the `hypotheses` list in the frontmatter as well —
% those are what a parent cites when it uses this node, and what the discharge
% check reads. Their `tex` is a math-mode fragment: `s > 3/2`, not `$s > 3/2$`.
"""


@app.command()
def init(
    directory: Path = typer.Argument(
        Path("."), help="where to create the project (default: here)"
    ),
    node_id: str = typer.Option(..., "--id", help="id of the target node, e.g. gclm.main"),
    statement: Optional[str] = typer.Option(None, "--statement"),
    statement_file: Optional[Path] = typer.Option(None, "--statement-file"),
    role: str = typer.Option("theorem", "--role"),
) -> None:
    """Start a project: make `nodes/`, write the target node, copy `bp.yaml`.

    Everything else in the system is reachable once one node exists.
    """
    root = directory.expanduser().resolve()
    nodes_dir = root / "nodes"
    if nodes_dir.exists() and any(nodes_dir.glob("*.md")):
        err_console.print(
            f"[bold red]error[/] {nodes_dir} already has nodes. "
            "Use `bp new` to add one."
        )
        raise typer.Exit(code=1)
    nodes_dir.mkdir(parents=True, exist_ok=True)

    text = STARTER_STATEMENT
    if statement_file is not None:
        text = statement_file.expanduser().read_text(encoding="utf-8")
    elif statement is not None:
        text = statement

    project = _project(root)
    try:
        ops.add_node(
            project, node_id, role=role, statement=text, target=True, difficulty="hard"
        )
    except ops.OpError as exc:
        err_console.print(f"[bold red]error[/] {exc}")
        raise typer.Exit(code=1)

    # The shipped default lives *inside* the package. It used to be read from
    # `Path(__file__).parent.parent / "bp.yaml"`, which is the repo root in a
    # source checkout and `site-packages/` in an installed one — so `bp init`
    # silently produced a project with no config for anyone who pip-installed.
    config = root / "bp.yaml"
    if not config.exists():
        shipped = Path(__file__).parent / "templates" / "bp.yaml"
        if shipped.exists():
            config.write_text(shipped.read_text(encoding="utf-8"), encoding="utf-8")
        else:  # pragma: no cover - only if package data is missing
            err_console.print(
                "[yellow]warning[/] no bp.yaml was written: the installed package "
                "is missing its default config. `bp agents` will fall back to "
                "built-in defaults."
            )

    console.print(f"created {nodes_dir / (node_id + '.md')}")
    console.print()
    console.print("Next:")
    console.print(f"  1. write the theorem into that file, or edit it in the browser")
    console.print(f"  2. check which models will run:   [bold]bp agents[/]")
    console.print(f"  3. open it:                       [bold]bp ui[/]")


@app.command()
def new(
    node_id: str = typer.Argument(..., help="id of the new node"),
    parent: Optional[str] = typer.Option(None, "--parent", help="attach as its child"),
    role: str = typer.Option("lemma", "--role"),
    difficulty: str = typer.Option("unknown", "--difficulty"),
    statement: Optional[str] = typer.Option(None, "--statement"),
    statement_file: Optional[Path] = typer.Option(None, "--statement-file"),
    target: bool = typer.Option(False, "--target"),
    root: Optional[Path] = typer.Option(None, "--root"),
) -> None:
    """Create a node by hand. The statement is yours; nothing is generated."""
    text = ""
    if statement_file is not None:
        text = statement_file.expanduser().read_text(encoding="utf-8")
    elif statement is not None:
        text = statement
    _run_op(
        ops.add_node,
        _project(root),
        node_id,
        role=role,
        statement=text,
        difficulty=difficulty,
        target=target,
        parent=parent,
    )


@app.command()
def preamble(
    file: Optional[Path] = typer.Option(None, "--from", help="replace it with this file"),
    defaults: bool = typer.Option(
        False,
        "--defaults",
        help="show what the renderer loads and defines, so you can avoid collisions",
    ),
    root: Optional[Path] = typer.Option(None, "--root"),
) -> None:
    """Show, or replace, the project's LaTeX preamble (preamble.tex).

    Macros defined here are injected into the rendered document, shown to every
    agent as context, and used by the browser to typeset your notation.
    """
    project = _project(root)
    if defaults:
        facts = render_mod.preamble_facts()
        console.print(Text("packages the renderer loads", style="bold"))
        for pkg in facts["packages"]:
            opts = f"[{pkg['options']}]" if pkg["options"] else ""
            tail = "  (only if installed)" if pkg["optional"] else ""
            console.print(Text(f"  {pkg['name']}{opts}{tail}"))
        console.print()
        console.print(Text("theorem environments", style="bold"))
        for env in facts["environments"]:
            console.print(
                Text(f"  {env['name']} — prints as \u201c{env['printed_as']}\u201d, "
                     "defined only if you have not")
            )
        console.print()
        console.print(Text("macros it defines (do not redefine)", style="bold"))
        console.print(Text("  " + "  ".join(facts["macros"])))
        console.print()
        console.print(
            "[dim]Your preamble.tex is injected BEFORE the options and the theorem "
            "environments, so anything you load or define yourself wins.[/]"
        )
        return
    if file is None:
        text = ops.read_preamble(project)
        console.print(Text(text) if text else "[dim]no preamble.tex in this project[/]")
        return
    _run_op(ops.set_preamble, project, file.expanduser().read_text(encoding="utf-8"))


@app.command()
def frontier(
    root: Optional[Path] = typer.Option(None, "--root"),
) -> None:
    """Nodes awaiting a decision, best first. What to work on next."""
    project, graph = _graph(root)
    console.print(Text(frontier_mod.summarise(frontier_mod.rank(graph))))


@app.command()
def sweep(root: Optional[Path] = typer.Option(None, "--root")) -> None:
    """Re-derive the computed fields and write them into the node files."""
    project = _project(root)
    try:
        graph, rewritten = ops.sweep_only(project)
    except (ops.OpError, GraphError) as exc:
        err_console.print(f"[bold red]error[/] {exc}")
        raise typer.Exit(code=1)
    if rewritten:
        console.print(f"updated {len(rewritten)} node(s): {', '.join(sorted(rewritten))}")
    else:
        console.print("already up to date")


def _run_op(fn, *args, **kwargs) -> None:
    try:
        result = fn(*args, **kwargs)
    except ops.OpError as exc:
        err_console.print(f"[bold red]error[/] {exc}")
        raise typer.Exit(code=1)
    console.print(f"{result.event['kind']}: {result.event['node']}")
    if result.rewritten:
        console.print(f"[dim]re-derived {len(result.rewritten)} node(s)[/]")


@app.command()
def admit(
    node_id: str,
    reason: str = typer.Option(..., "--reason", "-r"),
    root: Optional[Path] = typer.Option(None, "--root"),
) -> None:
    """Mark a node admitted, with a required reason. It becomes visible debt."""
    _run_op(ops.admit, _project(root), node_id, reason)


@app.command()
def assume(
    node_id: str,
    reason: str = typer.Option(..., "--reason", "-r"),
    root: Optional[Path] = typer.Option(None, "--root"),
) -> None:
    """Mark a node an assumption, with a required reason."""
    _run_op(ops.set_assumption, _project(root), node_id, reason)


@app.command()
def note(
    node_id: str,
    text: str = typer.Argument(...),
    root: Optional[Path] = typer.Option(None, "--root"),
) -> None:
    """Append a note. Notes are fed to agents as context."""
    _run_op(ops.add_note, _project(root), node_id, text)


@app.command()
def relabel(
    node_id: str,
    difficulty: str = typer.Argument(..., help="standard | routine | hard | unknown"),
    root: Optional[Path] = typer.Option(None, "--root"),
) -> None:
    """Change a node's difficulty label."""
    _run_op(ops.relabel, _project(root), node_id, difficulty)


@app.command()
def archive(
    node_id: str,
    keep_descendants: bool = typer.Option(
        False, "--keep-descendants", help="do not archive newly orphaned descendants"
    ),
    root: Optional[Path] = typer.Option(None, "--root"),
) -> None:
    """Archive a node. Never deletes: the file stays, `lifecycle` changes."""
    _run_op(ops.archive, _project(root), node_id, not keep_descendants)


@app.command()
def unarchive(
    node_id: str,
    root: Optional[Path] = typer.Option(None, "--root"),
) -> None:
    """Bring an archived node back into the active graph.

    "Nothing is destroyed" is only worth something if there is a way back.
    Archiving strips the node's citations from its parents so the graph stays
    consistent, and those are *not* restored here — the event log records which
    ones were removed (`bp events`), and re-citing is a decision rather than a
    mechanical undo. So expect to add it to a parent's `children` again.
    """
    project = _project(root)
    _run_op(ops.unarchive, project, node_id)
    graph, _, _ = checks.load_graph(project)
    node = graph.get(node_id)
    if node is not None and not graph.parents(node_id) and not node.target:
        console.print(
            "[yellow]note[/] nothing cites it yet, so it is an orphan (`REF005`). "
            "Add it back to a parent's children — `bp events` shows which "
            "citations archiving removed."
        )


# --- L1 and L2 commands -------------------------------------------------------
# Registered from separate modules so that everything above stays runnable with
# no key, no network and no configuration.
from . import cli_agents, cli_ui  # noqa: E402

cli_agents.register(app)
cli_ui.register(app)


def main() -> None:  # pragma: no cover - console-script entry point
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
