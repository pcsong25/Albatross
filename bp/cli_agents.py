"""The agent-facing half of the command line: L1's commands.

Kept in its own module so that :mod:`bp.cli` stays what it was in L0 — the
deterministic core, runnable with no key, no network and no configuration. Every
command here can fail for reasons the L0 commands cannot (a missing credential,
a budget cap, a model that would not answer), and they say so in those terms.
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

from . import jobs as jobs_mod
from . import ops, recompile as recompile_mod, verification as verification_mod
from .agents.base import AgentError, Budget, BudgetExceeded
from .agents.log import CallLog
from .agents.registry import ConfigError, Registry
from .paths import ProjectNotFound, find_project
from .roles import audit as audit_role
from .roles import check as check_role
from .roles import decompose as decompose_role
from .roles import extract as extract_role
from .roles import prove as prove_role
from .roles import verify as verify_role

console = Console()
err_console = Console(stderr=True)


def _project(root: Optional[Path]):
    try:
        return find_project(root)
    except ProjectNotFound as exc:
        err_console.print(f"[bold red]error[/] {exc}")
        raise typer.Exit(code=2)


def _registry(root: Optional[Path], replay: bool = False) -> Registry:
    project = _project(root)
    try:
        return Registry(project, replay=replay)
    except ConfigError as exc:
        err_console.print(f"[bold red]error[/] {exc}")
        raise typer.Exit(code=2)


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (ops.OpError, ConfigError) as exc:
        err_console.print(f"[bold red]error[/] {exc}")
        raise typer.Exit(code=1)
    except BudgetExceeded as exc:
        err_console.print(f"[bold yellow]stopped[/] {exc}")
        raise typer.Exit(code=1)
    except AgentError as exc:
        err_console.print(f"[bold red]agent error[/] {exc}")
        raise typer.Exit(code=1)


def register(app: typer.Typer) -> None:
    """Attach the L1 commands to the main app."""

    @app.command()
    def agents(
        root: Optional[Path] = typer.Option(None, "--root"),
        fill: bool = typer.Option(
            False,
            "--fill",
            help="write every unconfigured role into bp.yaml, so the file is the "
            "complete truth and nothing is inherited",
        ),
    ) -> None:
        """Which model plays which role, whether it can run here, and where it came from.

        With `--fill`, every role missing from `bp.yaml` is written into it using the
        value it currently resolves to — inherited from a role you did configure where
        possible. Your comments and key order survive. After that there is nothing left
        for the system to infer.
        """
        registry = _registry(root)
        if fill:
            from .agents.registry import fill_missing_roles

            added, path = fill_missing_roles(registry.project)
            if added:
                console.print(
                    f"wrote {len(added)} role(s) into {path}: " + ", ".join(added)
                )
                console.print(
                    "[dim]each with the value it already resolved to, so nothing about "
                    "your setup changed — it is just written down now.[/]"
                )
            else:
                console.print(f"{path} already configures every role")
            console.print()
            registry = _registry(root)
        table = Table(box=None, pad_edge=False, header_style="bold")
        for column in ("role", "backend", "model", "from", "usable", "note"):
            table.add_column(column, overflow="fold")
        rows = registry.describe()
        for role, backend, model, ok, reason, source in rows:
            table.add_row(
                role,
                backend,
                model,
                source if source == "bp.yaml" else f"[yellow]{source}[/]",
                "[green]yes[/]" if ok else "[red]no[/]",
                reason,
            )
        console.print(table)
        # A role nobody configured is a role the user should hear about, not discover
        # from a provider error three commands later.
        unconfigured = [r for r, *_rest, source in rows if source != "bp.yaml"]
        if unconfigured:
            console.print()
            console.print(
                f"[yellow]note[/] {len(unconfigured)} role(s) are not in your "
                "bp.yaml: " + ", ".join(unconfigured) + ". They were filled in as "
                "shown in the `from` column. Add them explicitly to choose."
            )
        broken = [r for r, _b, _m, ok, *_rest in rows if not ok]
        if broken:
            console.print(
                f"[red]warning[/] {len(broken)} role(s) cannot run here: "
                + ", ".join(broken)
                + ". Any job that needs one will fail."
            )
        log = CallLog.for_project(registry.project)
        console.print()
        console.print(f"call log: {len(log)} recorded call(s) in {log.directory}")
        budget = registry.config.budget
        console.print(
            f"budget: ${budget.per_run_usd} and {budget.max_calls_per_run} call(s) "
            "per run — a single `bp verify --level deep` on a large node can reach "
            "this. `bp verify <node> --level deep --dry-run` prices one node."
        )

    @app.command()
    def expand(
        node_id: str,
        hint: Optional[str] = typer.Option(None, "--hint", "-h"),
        root: Optional[Path] = typer.Option(None, "--root"),
        replay: bool = typer.Option(False, "--replay", help="resolve calls from the log"),
        rounds: int = typer.Option(2, "--repair-rounds"),
        force: bool = typer.Option(
            False, "--force", help="decompose even if it judges the node too easy"
        ),
    ) -> None:
        """Decompose a node one level, repairing against the discharge check."""
        registry = _registry(root, replay)
        result = _run(
            decompose_role.expand,
            registry.project,
            node_id,
            hint=hint,
            registry=registry,
            repair_rounds=rounds,
            force=force,
        )
        console.print(Text(decompose_role.summarise(result)))
        _print_spend(registry)
        raise typer.Exit(code=0 if result.clean and not result.declined else 1)

    @app.command()
    def redo(
        node_id: str,
        hint: Optional[str] = typer.Option(None, "--hint", "-h"),
        root: Optional[Path] = typer.Option(None, "--root"),
        replay: bool = typer.Option(False, "--replay"),
        rounds: int = typer.Option(2, "--repair-rounds"),
    ) -> None:
        """Archive this node's subtree and decompose again."""
        registry = _registry(root, replay)
        result = _run(
            decompose_role.redo,
            registry.project,
            node_id,
            hint=hint,
            registry=registry,
            repair_rounds=rounds,
        )
        if result.archived_to:
            console.print(f"previous attempt archived to {result.archived_to}")
        console.print(Text(decompose_role.summarise(result)))
        _print_spend(registry)
        raise typer.Exit(code=0 if result.clean else 1)

    @app.command("check-decomp")
    def check_decomp(
        node_id: str,
        root: Optional[Path] = typer.Option(None, "--root"),
        replay: bool = typer.Option(False, "--replay"),
    ) -> None:
        """Two checker calls: does the reduction hold, and is any child trivial."""
        registry = _registry(root, replay)
        report = _run(
            check_role.check_decomposition, registry.project, node_id, registry=registry
        )
        console.print(Text(check_role.summarise(report)))
        _print_spend(registry)
        raise typer.Exit(code=0 if report.clean else 1)

    @app.command()
    def extract(
        node_id: str,
        root: Optional[Path] = typer.Option(None, "--root"),
        replay: bool = typer.Option(False, "--replay"),
        dry: bool = typer.Option(
            False, "--no-record", help="report without writing the ledger to the node"
        ),
    ) -> None:
        """Build the claim ledger for a proof, then audit it (LED001-LED006).

        One cheap call. Every load-bearing claim the proof makes, with the source
        the prose offers — and a hard error on every claim that has none.
        """
        registry = _registry(root, replay)
        result = _run(
            extract_role.extract,
            registry.project,
            node_id,
            registry=registry,
            apply=not dry,
        )
        console.print(Text(extract_role.summarise(result)))
        _print_spend(registry)
        raise typer.Exit(code=0 if result.clean else 1)

    @app.command()
    def audit(
        node_id: str,
        root: Optional[Path] = typer.Option(None, "--root"),
        replay: bool = typer.Option(False, "--replay"),
        dry: bool = typer.Option(
            False, "--no-record", help="do not write the findings as a note"
        ),
    ) -> None:
        """Audit a statement: well-posedness, vacuity, quantifiers, constants.

        Never touches a status. This role stands in for the deterministic vacuity
        and constant-scope checks that v0 defers, and is weaker than both — its
        answers are prompts for your attention, not checks.
        """
        registry = _registry(root, replay)
        report = _run(
            audit_role.audit,
            registry.project,
            node_id,
            registry=registry,
            apply=not dry,
        )
        console.print(Text(audit_role.summarise(report)))
        _print_spend(registry)
        raise typer.Exit(code=0 if report.clean else 1)

    @app.command()
    def verify(
        node_id: str,
        root: Optional[Path] = typer.Option(None, "--root"),
        replay: bool = typer.Option(False, "--replay"),
        level: str = typer.Option(
            verification_mod.STANDARD, "--level", "-l", help="quick | standard | deep"
        ),
        batch: int = typer.Option(
            1, "--batch", help="obligation/claim checks per call; 1 is the reliable one"
        ),
        obligations_only: bool = typer.Option(False, "--obligations-only"),
        proof_only: bool = typer.Option(False, "--proof-only"),
        dry_run: bool = typer.Option(
            False, "--dry-run", help="print the bill and make no calls"
        ),
        dry: bool = typer.Option(
            False, "--no-record", help="report without writing a verdict to the node"
        ),
    ) -> None:
        """Verify a node at the given level, then confirm every objection.

        `quick` reads the proof; `standard` adds extraction, the ledger audit and
        the discharge obligations; `deep` adds per-claim checks and a statement
        audit. Which level produced a verdict is recorded on the node, because a
        node verified at `quick` and one verified at `deep` are not making the same
        claim.

        `--dry-run` prints what it would cost. Worth doing on a big node: every
        worklist is computed from the files, so the count is exact.
        """
        registry = _registry(root, replay)
        if dry_run:
            bill = _run(
                verify_role.plan,
                registry.project,
                node_id,
                level=level,
                batch=batch,
            )
            cap = registry.config.budget.max_calls_per_run
            console.print(Text(f"{node_id} at --level {level}\n"))
            for line in bill.lines():
                console.print(Text("  " + line))
            console.print(
                Text(
                    f"\n  at least {bill.floor} call(s), plus one per objection"
                    + (f"; the cap allows {cap} per run" if cap else "; no call cap set")
                    + (f"\n  {bill.cached} answer(s) already cached" if bill.cached else "")
                )
            )
            return
        report = _run(
            verify_role.verify,
            registry.project,
            node_id,
            registry=registry,
            level=level,
            batch=batch,
            obligations=not proof_only,
            proof=not obligations_only,
            record=not dry,
        )
        console.print(Text(verify_role.summarise(report)))
        _print_spend(registry)
        raise typer.Exit(code=0 if report.verdict == "verified" else 1)

    @app.command()
    def prove(
        node_id: str,
        root: Optional[Path] = typer.Option(None, "--root"),
        replay: bool = typer.Option(False, "--replay"),
        force: bool = typer.Option(False, "--force"),
    ) -> None:
        """Write a proof for a routine or standard leaf. Never sets a status."""
        registry = _registry(root, replay)
        result = _run(
            prove_role.prove, registry.project, node_id, registry=registry, force=force
        )
        console.print(Text(prove_role.summarise(result)))
        _print_spend(registry)

    @app.command()
    def recompile(
        root: Optional[Path] = typer.Option(None, "--root"),
        dry_run: bool = typer.Option(False, "--dry-run", help="preview the bill"),
        replay: bool = typer.Option(False, "--replay"),
        node: Optional[list[str]] = typer.Option(None, "--node", help="limit to these"),
        level: str = typer.Option(
            verification_mod.STANDARD, "--level", "-l", help="quick | standard | deep"
        ),
        batch: int = typer.Option(
            1, "--batch", help="obligation/claim checks per call; 1 is the reliable one"
        ),
        budget: Optional[int] = typer.Option(
            None, "--budget", help="stop after this many model calls"
        ),
    ) -> None:
        """Verify every stale and unverified node at the given level, then sweep.

        Ordering is by value: nodes on the path to the target first, then the
        frontier, then the rest — so a run stopped by `--budget` has spent its
        money where it mattered.
        """
        registry = _registry(root, replay)
        prepared = _run(
            recompile_mod.plan,
            registry.project,
            registry=registry,
            only=list(node or []),
            level=level,
            batch=batch,
        )
        console.print(Text(prepared.describe()))
        if dry_run or not prepared.tasks:
            return
        console.print()
        cap = None
        if budget is not None:
            # An explicit `--budget` replaces the configured caps rather than
            # tightening them: the user is saying how many calls this run may make.
            cap = Budget(max_usd=None, max_calls=budget)
        result = _run(
            recompile_mod.run,
            registry.project,
            registry=registry,
            only=list(node or []),
            level=level,
            batch=batch,
            budget=cap,
        )
        console.print(Text(result.describe()))
        _print_spend(registry)

    @app.command()
    def resume(
        job_id: Optional[str] = typer.Argument(None),
        root: Optional[Path] = typer.Option(None, "--root"),
        replay: bool = typer.Option(False, "--replay"),
    ) -> None:
        """Continue an interrupted recompile. Completed tasks are not re-queried."""
        registry = _registry(root, replay)
        result = _run(recompile_mod.resume, registry.project, job_id, registry=registry)
        console.print(Text(result.describe()))
        _print_spend(registry)

    @app.command("paper")
    def paper_cmd(
        root: Optional[Path] = typer.Option(None, "--root"),
        replay: bool = typer.Option(False, "--replay"),
        title: Optional[str] = typer.Option(None, "--title", help="override the writer's title"),
        guidance: Optional[str] = typer.Option(
            None, "--guidance", "-g", help="how you want the paper shaped"
        ),
        plan: bool = typer.Option(
            False, "--plan", help="what it would cost, without making a call"
        ),
        status: bool = typer.Option(
            False, "--status", help="describe the paper already built, if any"
        ),
        rebuild: bool = typer.Option(
            False,
            "--rebuild",
            help="re-render the stored draft to LaTeX without calling any model",
        ),
        bare: bool = typer.Option(
            False,
            "--bare",
            help="omit the provenance note and the appendix — for a file going to a "
            "journal rather than to you",
        ),
        out: Optional[Path] = typer.Option(None, "-o", "--out"),
        to_stdout: bool = typer.Option(False, "--stdout"),
        pdf: bool = typer.Option(False, "--pdf", help="compile it too"),
    ) -> None:
        """Write the development up as a readable paper. Optional, and never automatic.

        `bp render` is the document this system guarantees: generated from the node
        files every time, with every gap marked. This is the other one — an agent
        reorganises the same mathematics into something a person would want to read,
        merging routine lemmas into the proofs that use them and turning `(H1)`,
        `(H2)` into sentences. It is a build artifact under `.bp/paper/`, it is never
        rebuilt behind your back, and it goes out of date the moment you edit a node:
        `--status` says whether it has.

        The exposition may lose detail. Every built paper therefore carries a
        provenance note and an appendix saying which section covers each node, both
        written by code rather than by the agent.
        """
        from . import compile as compile_mod
        from . import paper as paper_mod
        from .checks import load_graph
        from .roles import paper as paper_role

        project = _project(root)

        if plan:
            registry = _registry(root, replay)
            console.print(Text(paper_role.estimate(project, registry=registry).describe()))
            return

        graph, load_diagnostics, swept = load_graph(project)
        if not swept:
            err_console.print("[bold red]error[/] the graph has a cycle; run `bp check`")
            raise typer.Exit(code=1)
        # Same refusal as `cli._graph`: a document assembled from a graph that only
        # partly loaded describes a project the user does not have.
        broken = [d for d in load_diagnostics if d.severity == "error"]
        if broken:
            err_console.print(
                "[bold red]error[/] some node files could not be loaded, so the "
                "development is incomplete. Run `bp check` and fix those first."
            )
            for d in broken:
                err_console.print(Text(f"  {d.code}: {d.message}"))
            raise typer.Exit(code=2)

        draft = None
        clean = True
        if status or rebuild:
            try:
                draft = paper_mod.load(project)
            except paper_mod.DraftUnreadable as exc:
                err_console.print(f"[bold red]error[/] {exc}")
                raise typer.Exit(code=1)
            if draft is None:
                err_console.print(
                    "[bold red]error[/] no paper has been built for this project yet; "
                    "run `bp paper` without --status/--rebuild"
                )
                raise typer.Exit(code=1)
            if status:
                console.print(Text(paper_mod.describe(draft, graph)))
                problems = paper_mod.check(draft, graph)
                for d in problems:
                    console.print(
                        Text(d.line(), style="red" if d.severity == "error" else "yellow")
                    )
                raise typer.Exit(
                    code=1 if any(d.severity == "error" for d in problems) else 0
                )
        else:
            registry = _registry(root, replay)
            report = _run(
                paper_role.write,
                project,
                registry=registry,
                title=title,
                guidance=guidance or "",
            )
            console.print(Text(paper_role.summarise(report)))
            _print_spend(registry)
            draft = report.draft
            if draft is None:
                raise typer.Exit(code=1)
            clean = report.clean
            console.print(f"[dim]draft written to {report.path}[/]")

        if title:
            draft = draft.model_copy(update={"title": title})
        tex = paper_mod.document(
            draft, graph, preamble=ops.read_preamble(project), apparatus=not bare
        )
        if to_stdout:
            sys.stdout.write(tex)
            raise typer.Exit(code=0 if clean else 1)
        path = out or (project.build_dir / "paper.tex")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(tex, encoding="utf-8")
        console.print(f"wrote {path}")
        if not pdf:
            raise typer.Exit(code=0 if clean else 1)

        result = compile_mod.compile_pdf(
            tex, path.parent, name=path.stem, preamble=ops.read_preamble(project)
        )
        for warning in result.warnings:
            console.print(Text(f"warning: {warning}", style="yellow"))
        if result.ok:
            console.print(f"wrote {result.pdf}")
            raise typer.Exit(code=0 if clean else 1)
        problem = result.problem
        err_console.print(
            Text(f"the paper did not compile: {problem.kind}", style="bold red")
        )
        if problem.message:
            err_console.print(Text(problem.message))
        if problem.hint:
            err_console.print(Text(problem.hint, style="dim"))
        if problem.excerpt:
            err_console.print(Text(problem.excerpt, style="dim"))
        raise typer.Exit(code=1)

    @app.command("jobs")
    def jobs_cmd(root: Optional[Path] = typer.Option(None, "--root")) -> None:
        """Job records, most recent last."""
        project = _project(root)
        records = jobs_mod.Job.all(project)
        if not records:
            console.print("[dim]no jobs yet[/]")
            return
        for job in records:
            console.print(job.describe())

    @app.command("calls")
    def calls_cmd(
        root: Optional[Path] = typer.Option(None, "--root"),
        show: Optional[str] = typer.Option(None, "--show", help="print one call by hash"),
    ) -> None:
        """The model call log: what was asked, and what came back."""
        project = _project(root)
        log = CallLog.for_project(project)
        if show:
            record = log.get(show)
            if record is None:
                err_console.print(f"[bold red]error[/] no logged call {show!r}")
                raise typer.Exit(code=2)
            sys.stdout.write(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
            return
        summary = log.summary()
        if not summary:
            console.print("[dim]no calls logged yet[/]")
            return
        for key, count in summary.items():
            console.print(f"{count:>4}  {key}")
        console.print(f"\n{len(log)} call(s) in {log.directory}")


def _print_spend(registry: Registry) -> None:
    budget = registry.budget
    if budget.calls:
        console.print(f"[dim]{budget.summary()}[/]")
