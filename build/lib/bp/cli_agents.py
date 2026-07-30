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
    def agents(root: Optional[Path] = typer.Option(None, "--root")) -> None:
        """Which model plays which role, and whether it can run here."""
        registry = _registry(root)
        table = Table(box=None, pad_edge=False, header_style="bold")
        for column in ("role", "backend", "model", "usable", "note"):
            table.add_column(column, overflow="fold")
        for role, backend, model, ok, reason in registry.describe():
            table.add_row(
                role,
                backend,
                model,
                "[green]yes[/]" if ok else "[red]no[/]",
                reason,
            )
        console.print(table)
        log = CallLog.for_project(registry.project)
        console.print()
        console.print(f"call log: {len(log)} recorded call(s) in {log.directory}")
        budget = registry.config.budget
        console.print(
            f"budget: ${budget.per_recompile_usd} and "
            f"{budget.max_calls_per_recompile} call(s) per recompile"
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
        """
        registry = _registry(root, replay)
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
