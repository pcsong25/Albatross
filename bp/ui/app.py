"""The HTTP surface.

Every endpoint here is a thin wrapper around a function that already exists in
:mod:`bp.ops`, :mod:`bp.roles`, or the derived layer. Nothing in this file
decides a status, computes a support set, ranks a frontier or interprets a
diagnostic — if the interface needs a derived fact, the derivation belongs in the
core and this returns it. That is what keeps the browser and the terminal from
telling the user two different stories about the same graph.

The split that matters: **reads are synchronous, role calls are not.** A read
loads the graph and derives in memory, which takes milliseconds. A role call can
take minutes, so it goes to :mod:`bp.ui.jobs` and the request returns a job id.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import checks, events as events_mod, frontier, ops, recompile as recompile_mod
from .. import render as render_mod
from .. import why as why_mod
from ..agents.log import CallLog
from ..agents.registry import ConfigError, Registry
from ..discharge import obligations_for
from ..graph import Graph
from ..model import Node
from ..paths import Project
from ..roles import check as check_role
from ..roles import decompose as decompose_role
from ..roles import prove as prove_role
from ..roles import tidy as tidy_role
from ..roles import verify as verify_role
from . import jobs as jobs_mod

STATIC = Path(__file__).parent / "static"


# --- request bodies -----------------------------------------------------------


class TextBody(BaseModel):
    text: str = ""


class ReasonBody(BaseModel):
    reason: str


class HintBody(BaseModel):
    hint: str | None = None
    #: Decompose even if the decomposer judges the node not worth splitting.
    force: bool = False


class DifficultyBody(BaseModel):
    difficulty: str


class ChildBody(BaseModel):
    id: str
    statement: str = ""
    role: str = "lemma"
    difficulty: str = "unknown"
    hypotheses: list[dict[str, str]] = Field(default_factory=list)


class AttachBody(BaseModel):
    children: list[str]


class TidyBody(BaseModel):
    text: str
    kind: str = "statement"


class UsesBody(BaseModel):
    uses: dict[str, dict[str, Any]]


class ArchiveBody(BaseModel):
    cascade: bool = True


class RecompileBody(BaseModel):
    nodes: list[str] = Field(default_factory=list)


# --- serialisation ------------------------------------------------------------


def node_summary(graph: Graph, node: Node) -> dict[str, Any]:
    return {
        "id": node.id,
        "role": node.role,
        "difficulty": node.difficulty,
        "target": node.target,
        "local_status": node.local_status,
        "global_status": node.global_status,
        "stale": node.stale,
        "flagged": node.local_status == "flagged",
        "support": list(node.support),
        "blocked_by": list(node.blocked_by),
        "children": list(node.children),
        "has_proof": node.has_proof,
        "headline": " ".join(node.statement_section.split())[:140],
    }


def node_detail(graph: Graph, node: Node) -> dict[str, Any]:
    return {
        **node_summary(graph, node),
        "lifecycle": node.lifecycle,
        "strategy": node.strategy,
        "status_reason": node.status_reason,
        "statement": node.statement_section,
        "proof": node.proof_section,
        "notes": node.notes_section,
        "statement_hash": node.statement_hash,
        "verified_against": dict(node.verified_against),
        "parents": graph.parents(node.id),
        "hypotheses": [h.model_dump() for h in node.hypotheses],
        "uses": {
            cid: {"applied_to": u.applied_to, "discharges": dict(u.discharges)}
            for cid, u in node.uses.items()
        },
        "flags": [f.model_dump() for f in node.flags],
        "support_detail": [
            {
                "id": s,
                "local_status": graph[s].local_status if s in graph else "?",
                "reason": (graph[s].status_reason if s in graph else None),
            }
            for s in node.support
        ],
        "obligations": obligations_for(node, graph),
        "why": why_lines(graph, node.id),
    }


def why_lines(graph: Graph, node_id: str) -> list[dict[str, Any]]:
    def walk(exp, depth: int) -> list[dict[str, Any]]:
        out = [{"depth": depth, "node": exp.node, "text": exp.sentence}]
        for child in exp.children:
            out.extend(walk(child, depth + 1))
        return out

    return walk(why_mod.explain(graph, node_id), 0)


def create_app(project: Project, replay: bool = False) -> FastAPI:
    app = FastAPI(title="Albatross", docs_url=None, redoc_url=None)
    runner = jobs_mod.JobRunner()
    app.state.project = project
    app.state.runner = runner
    app.state.replay = replay

    # --- helpers -------------------------------------------------------------

    def load() -> Graph:
        graph, diagnostics, swept = checks.load_graph(project)
        if not swept:
            raise HTTPException(
                status_code=409,
                detail="the children relation has a cycle, so no status can be "
                "derived. Run `bp check` for the cycle.",
            )
        broken = [d.message for d in diagnostics if d.severity == "error"]
        if broken:
            raise HTTPException(
                status_code=409, detail="unreadable node files: " + "; ".join(broken)
            )
        return graph

    def node_or_404(graph: Graph, node_id: str) -> Node:
        node = graph.get(node_id)
        if node is None:
            raise HTTPException(status_code=404, detail=f"no node {node_id!r}")
        return node

    def refuse_if_busy(node_id: str | None) -> None:
        """An agent is mid-write on this node; do not race it.

        Refusing beats blocking: the request returns at once with something the
        user can act on, and the page has already disabled the buttons that
        would land here.
        """
        if node_id and node_id in runner.busy_nodes():
            raise HTTPException(
                status_code=409,
                detail=f"an agent is working on {node_id}. Wait for it to finish, "
                "or act on a different node — the rest of the graph is live.",
            )

    def mutate(fn, *args, **kwargs):
        """Every write goes through here: one error shape.

        Ordering is `bp.ops.serialised`'s job, per mutation. Nothing is held
        across a role call.
        """
        try:
            return fn(*args, **kwargs)
        except ops.ComputedFieldError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ops.OpError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def registry_for(job: jobs_mod.Job) -> Registry:
        try:
            return Registry(
                project, replay=app.state.replay, observer=jobs_mod.progress(job)
            )
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # --- reads ---------------------------------------------------------------

    @app.get("/api/graph")
    def api_graph() -> dict[str, Any]:
        graph = load()
        nodes = [node_summary(graph, n) for n in graph.active.values()]
        edges = [
            {"source": n.id, "target": c}
            for n in graph.active.values()
            for c in n.children
            if c in graph.active
        ]
        target = graph.target
        return {
            "nodes": nodes,
            "edges": edges,
            "target": target.id if target else None,
            "counts": _counts(graph),
            "certificate": _certificate(graph),
        }

    @app.get("/api/node/{node_id}")
    def api_node(node_id: str) -> dict[str, Any]:
        graph = load()
        return node_detail(graph, node_or_404(graph, node_id))

    @app.get("/api/why/{node_id}")
    def api_why(node_id: str) -> dict[str, Any]:
        graph = load()
        node_or_404(graph, node_id)
        return {"node": node_id, "lines": why_lines(graph, node_id)}

    @app.get("/api/check")
    def api_check() -> dict[str, Any]:
        report = checks.run(project)
        return {
            "diagnostics": [d.model_dump() for d in report.diagnostics],
            "errors": len(report.errors),
            "warnings": len(report.warnings),
            "notes": len(report.notes),
        }

    @app.get("/api/frontier")
    def api_frontier() -> dict[str, Any]:
        graph = load()
        return {"items": [i.as_dict() for i in frontier.rank(graph)]}

    @app.get("/api/events")
    def api_events(limit: int = 200) -> dict[str, Any]:
        log = events_mod.read(project)
        return {
            "events": [
                {**e, "line": events_mod.describe(e)} for e in log[-limit:]
            ][::-1]
        }

    @app.get("/api/agents")
    def api_agents() -> dict[str, Any]:
        try:
            registry = Registry(project, replay=app.state.replay)
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "roles": [
                {"role": r, "backend": b, "model": m, "usable": ok, "note": note}
                for r, b, m, ok, note in registry.describe()
            ],
            "budget": registry.config.budget.model_dump(),
            "calls_logged": len(CallLog.for_project(project)),
            "replay": app.state.replay,
        }

    @app.get("/api/node/{node_id}/stale-radius")
    def api_stale_radius(node_id: str) -> dict[str, Any]:
        graph = load()
        node_or_404(graph, node_id)
        radius = ops.stale_radius(graph, node_id)
        return {
            "node": node_id,
            "radius": [
                {
                    "id": rid,
                    "local_status": graph[rid].local_status,
                    "global_status": graph[rid].global_status,
                }
                for rid in radius
            ],
        }

    # --- render --------------------------------------------------------------

    @app.get("/api/preamble", response_class=PlainTextResponse)
    def api_get_preamble() -> str:
        """The project's own LaTeX preamble. The browser parses the macro
        definitions out of it so KaTeX renders statements in your notation."""
        return ops.read_preamble(project)

    @app.post("/api/preamble")
    def api_set_preamble(body: TextBody) -> dict[str, Any]:
        mutate(ops.set_preamble, project, body.text)
        return {"ok": True}

    @app.get("/api/render", response_class=PlainTextResponse)
    def api_render(clean: bool = False, audit: bool = False) -> str:
        return render_mod.document(
            load(), clean=clean, audit=audit, preamble=ops.read_preamble(project)
        )

    @app.get("/api/render.tex")
    def api_render_download(clean: bool = False, audit: bool = False) -> FileResponse:
        tex = render_mod.document(
            load(), clean=clean, audit=audit, preamble=ops.read_preamble(project)
        )
        path = project.build_dir / ("document-clean.tex" if clean else "document.tex")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(tex, encoding="utf-8")
        return FileResponse(path, media_type="application/x-tex", filename=path.name)

    @app.get("/api/render.pdf")
    def api_render_pdf(clean: bool = False, audit: bool = False) -> FileResponse:
        engine = shutil.which("pdflatex")
        if engine is None:
            raise HTTPException(
                status_code=501,
                detail="no pdflatex on PATH. The LaTeX source is still available "
                "from the download button.",
            )
        tex = render_mod.document(
            load(), clean=clean, audit=audit, preamble=ops.read_preamble(project)
        )
        build = project.build_dir
        build.mkdir(parents=True, exist_ok=True)
        name = "document-clean" if clean else "document"
        (build / f"{name}.tex").write_text(tex, encoding="utf-8")
        for _ in range(2):  # twice, so \ref and the hyperlinks resolve
            result = subprocess.run(
                [engine, "-interaction=nonstopmode", "-halt-on-error", f"{name}.tex"],
                cwd=build,
                capture_output=True,
                text=True,
                timeout=180,
            )
        pdf = build / f"{name}.pdf"
        if not pdf.exists():
            raise HTTPException(
                status_code=500,
                detail="pdflatex did not produce a PDF:\n"
                + _tex_error(result.stdout or ""),
            )
        return FileResponse(pdf, media_type="application/pdf", filename=pdf.name)

    # --- mutations -----------------------------------------------------------

    @app.post("/api/node/{node_id}/statement")
    def api_edit_statement(node_id: str, body: TextBody) -> dict[str, Any]:
        refuse_if_busy(node_id)
        result = mutate(ops.edit_statement, project, node_id, body.text)
        return {"ok": True, "staled": result.event["payload"].get("stale_radius", [])}

    @app.post("/api/node/{node_id}/proof")
    def api_edit_proof(node_id: str, body: TextBody) -> dict[str, Any]:
        refuse_if_busy(node_id)
        mutate(ops.edit_proof, project, node_id, body.text)
        return {"ok": True}

    @app.post("/api/node/{node_id}/note")
    def api_add_note(node_id: str, body: TextBody) -> dict[str, Any]:
        refuse_if_busy(node_id)
        if not body.text.strip():
            raise HTTPException(status_code=400, detail="a note needs some text")
        mutate(ops.add_note, project, node_id, body.text)
        return {"ok": True}

    @app.post("/api/node/{node_id}/admit")
    def api_admit(node_id: str, body: ReasonBody) -> dict[str, Any]:
        refuse_if_busy(node_id)
        mutate(ops.admit, project, node_id, body.reason)
        return {"ok": True}

    @app.post("/api/node/{node_id}/assume")
    def api_assume(node_id: str, body: ReasonBody) -> dict[str, Any]:
        refuse_if_busy(node_id)
        mutate(ops.set_assumption, project, node_id, body.reason)
        return {"ok": True}

    @app.post("/api/node/{node_id}/relabel")
    def api_relabel(node_id: str, body: DifficultyBody) -> dict[str, Any]:
        refuse_if_busy(node_id)
        mutate(ops.relabel, project, node_id, body.difficulty)
        return {"ok": True}

    @app.post("/api/node/{node_id}/archive")
    def api_archive(node_id: str, body: ArchiveBody) -> dict[str, Any]:
        refuse_if_busy(node_id)
        result = mutate(ops.archive, project, node_id, body.cascade)
        return {"ok": True, "archived": result.event["payload"].get("nodes", [])}

    @app.post("/api/node/{node_id}/child")
    def api_add_child(node_id: str, body: ChildBody) -> dict[str, Any]:
        refuse_if_busy(node_id)
        mutate(
            ops.add_node,
            project,
            body.id,
            role=body.role,
            statement=body.statement,
            difficulty=body.difficulty,
            hypotheses=body.hypotheses,
            parent=node_id,
        )
        return {"ok": True, "id": body.id}

    @app.post("/api/node/{node_id}/children")
    def api_set_children(node_id: str, body: AttachBody) -> dict[str, Any]:
        refuse_if_busy(node_id)
        mutate(ops.set_children, project, node_id, body.children)
        return {"ok": True}

    @app.post("/api/node/{node_id}/uses")
    def api_set_uses(node_id: str, body: UsesBody) -> dict[str, Any]:
        """Replace the discharge table.

        Shape is validated here; whether it is *complete* is the discharge
        check's job, and whether each named source actually entails the
        hypothesis is the verifier's.
        """
        refuse_if_busy(node_id)
        mutate(ops.set_uses, project, node_id, body.uses)
        return {"ok": True}

    @app.post("/api/tidy")
    def api_tidy(body: TidyBody) -> dict[str, Any]:
        """Propose a syntax-only correction to a passage of LaTeX.

        Writes nothing. The browser shows the rewrite beside the original and the
        author accepts or rejects it — an agent must not edit a mathematician's
        theorem behind their back.
        """
        try:
            registry = Registry(project, replay=app.state.replay)
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            report = tidy_role.tidy(project, body.text, kind=body.kind, registry=registry)
        except Exception as exc:  # a failed tidy must never block a save
            raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}")
        return {
            "changed": report.changed,
            "text": report.result.text if report.result else body.text,
            "changes": report.result.changes if report.result else [],
            "concerns": report.result.concerns if report.result else [],
        }

    @app.post("/api/sweep")
    def api_sweep() -> dict[str, Any]:
        graph, rewritten = mutate(ops.sweep_only, project)
        return {"ok": True, "rewritten": rewritten}

    # --- role jobs -----------------------------------------------------------

    @app.post("/api/jobs/expand/{node_id}")
    def api_expand(node_id: str, body: HintBody) -> dict[str, Any]:
        def work(job: jobs_mod.Job) -> dict[str, Any]:
            result = decompose_role.expand(
                project, node_id, hint=body.hint, registry=registry_for(job),
                force=body.force,
            )
            return {
                "children": result.children,
                "rounds": result.rounds,
                "clean": result.clean,
                "declined": result.declined,
                "verdict": result.verdict,
                "assessment": result.assessment,
                "assessed_difficulty": (
                    result.decomposition.assessed_difficulty if result.decomposition else ""
                ),
                "diagnostics": [d.model_dump() for d in result.diagnostics],
                "notes": result.decomposition.notes if result.decomposition else "",
                "strategy": result.decomposition.strategy if result.decomposition else "",
            }

        return runner.submit("expand", node_id, work).as_dict()

    @app.post("/api/jobs/redo/{node_id}")
    def api_redo(node_id: str, body: HintBody) -> dict[str, Any]:
        def work(job: jobs_mod.Job) -> dict[str, Any]:
            result = decompose_role.redo(
                project, node_id, hint=body.hint, registry=registry_for(job)
            )
            return {
                "children": result.children,
                "rounds": result.rounds,
                "clean": result.clean,
                "archived_to": str(result.archived_to) if result.archived_to else None,
                "diagnostics": [d.model_dump() for d in result.diagnostics],
                "notes": result.decomposition.notes if result.decomposition else "",
            }

        return runner.submit("redo", node_id, work).as_dict()

    @app.post("/api/jobs/check-decomp/{node_id}")
    def api_check_decomp(node_id: str) -> dict[str, Any]:
        def work(job: jobs_mod.Job) -> dict[str, Any]:
            report = check_role.check_decomposition(
                project, node_id, registry=registry_for(job)
            )
            return {
                "clean": report.clean,
                "answers": [
                    {
                        "question": label,
                        "checked": answer.checked,
                        "problems": [p.model_dump() for p in answer.problems],
                    }
                    for label, answer in (
                        ("Does the reduction establish the parent?", report.reduction),
                        ("Is any child a restatement, or as hard?", report.triviality),
                    )
                    if answer is not None
                ],
            }

        return runner.submit("check-decomp", node_id, work).as_dict()

    @app.post("/api/jobs/verify/{node_id}")
    def api_verify(node_id: str) -> dict[str, Any]:
        def work(job: jobs_mod.Job) -> dict[str, Any]:
            report = verify_role.verify(project, node_id, registry=registry_for(job))
            return {
                "verdict": report.verdict,
                "obligations_checked": report.obligations_checked,
                "obligations_cached": report.obligations_cached,
                "panel_ran": report.panel_ran,
                "flags": [f.to_record() for f in report.flags],
                "withdrawn": [
                    {"kind": f.kind, "why": f.why, "resolved": why} for f, why in report.withdrawn
                ],
                "checked": report.checked,
            }

        return runner.submit("verify", node_id, work).as_dict()

    @app.post("/api/jobs/prove/{node_id}")
    def api_prove(node_id: str) -> dict[str, Any]:
        def work(job: jobs_mod.Job) -> dict[str, Any]:
            result = prove_role.prove(project, node_id, registry=registry_for(job))
            draft = result.draft
            return {
                "written": result.written,
                "attempted": draft.attempted if draft else False,
                "reason": draft.reason if draft else "",
                "gaps": draft.gaps if draft else [],
            }

        return runner.submit("prove", node_id, work).as_dict()

    @app.get("/api/recompile/plan")
    def api_recompile_plan() -> dict[str, Any]:
        """The dry run. Makes no model calls, so it can answer synchronously."""
        try:
            registry = Registry(project, replay=app.state.replay)
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        plan = recompile_mod.plan(project, registry=registry)
        return {
            "tasks": [
                {
                    "node": t.node,
                    "reason": t.reason,
                    "calls": t.calls,
                    "obligations": t.obligations,
                    "cached": t.cached,
                }
                for t in plan.tasks
            ],
            "calls": plan.calls,
            "estimated_usd": plan.estimated_usd,
            "unpriced_calls": plan.unpriced_calls,
            "text": plan.describe(),
        }

    @app.post("/api/jobs/recompile")
    def api_recompile(body: RecompileBody) -> dict[str, Any]:
        def work(job: jobs_mod.Job) -> dict[str, Any]:
            result = recompile_mod.run(
                project, registry=registry_for(job), only=list(body.nodes) or None
            )
            return {
                "job": result.job.id,
                "verified": result.verified,
                "flagged": result.flagged,
                "skipped": result.skipped,
                "stopped": result.stopped,
            }

        # Claim the nodes the plan names, so the interface disables their
        # buttons for the duration and leaves every other node live. Not wrapped
        # in a try: if planning fails the job would fail the same way, and
        # swallowing it here once cost an afternoon by hiding a TypeError.
        planned = [
            t.node
            for t in recompile_mod.plan(project, only=list(body.nodes) or None).tasks
        ]
        return runner.submit("recompile", None, work, nodes=planned).as_dict()

    @app.post("/api/jobs/resume")
    def api_resume() -> dict[str, Any]:
        def work(job: jobs_mod.Job) -> dict[str, Any]:
            result = recompile_mod.resume(project, registry=registry_for(job))
            return {
                "job": result.job.id,
                "verified": result.verified,
                "flagged": result.flagged,
                "skipped": result.skipped,
                "stopped": result.stopped,
            }

        return runner.submit("resume", None, work).as_dict()

    @app.get("/api/jobs")
    def api_jobs() -> dict[str, Any]:
        return {
            "jobs": [j.as_dict() for j in reversed(runner.all())],
            "busy": sorted(runner.busy_nodes()),
            "active": len(runner.active),
        }

    @app.get("/api/jobs/{job_id}")
    def api_job(job_id: str) -> dict[str, Any]:
        job = runner.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"no job {job_id!r}")
        return job.as_dict()

    # --- the page ------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (STATIC / "index.html").read_text(encoding="utf-8")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def _counts(graph: Graph) -> dict[str, int]:
    out: dict[str, int] = {}
    for node in graph.active.values():
        key = node.global_status or "?"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def _certificate(graph: Graph) -> dict[str, Any]:
    target = graph.target
    if target is None:
        return {"target": None}
    return {
        "target": target.id,
        "status": target.global_status,
        "support": [
            {
                "id": s,
                "local_status": graph[s].local_status if s in graph else "?",
                "reason": graph[s].status_reason if s in graph else None,
            }
            for s in target.support
        ],
    }


def _tex_error(log: str) -> str:
    lines = log.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("!"):
            return "\n".join(lines[i : i + 8])
    return "\n".join(lines[-15:])
