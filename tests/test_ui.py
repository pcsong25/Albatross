"""The web interface, driven through the HTTP surface.

These run the real app against a real project directory. What they are actually
checking is the property the whole package is built around: **the UI contains no
logic of its own**, so every answer it gives must be the one the core gives.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from bp import frontier, ops
from bp.checks import load_graph
from bp.ui.app import create_app
from bp.ui.jobs import JobRunner

from .conftest import json_reply, scripted_registry, write_node


@pytest.fixture
def client(project):
    app = create_app(project)
    with TestClient(app) as c:
        c.project = project
        yield c


def small(project):
    write_node(
        project,
        "t",
        target=True,
        children=["a", "b"],
        local_status="verified",
        proof="By `a` and `b` we are done.",
        statement="The theorem: for $s > 3/2$ the solution blows up.",
        hypotheses=[{"id": "H1", "tex": "s > 3/2"}],
        uses={"a": {"applied_to": "x", "discharges": {"H1": "hypothesis:H1"}}},
    )
    write_node(project, "a", statement="Lemma A.", proof="An argument.",
               hypotheses=[{"id": "H1", "tex": "s > 3/2"}])
    write_node(project, "b", statement="Lemma B.", difficulty="routine")
    return project


def graph_of(project):
    g, _, ok = load_graph(project)
    assert ok
    return g


class TestReads:
    def test_graph_matches_the_core(self, client, project):
        small(project)
        data = client.get("/api/graph").json()
        assert data["target"] == "t"
        by_id = {n["id"]: n for n in data["nodes"]}
        core = graph_of(project)
        for node_id, payload in by_id.items():
            assert payload["global_status"] == core[node_id].global_status
        assert {"source": "t", "target": "a"} in data["edges"]

    def test_node_detail_carries_everything_the_panel_shows(self, client, project):
        small(project)
        node = client.get("/api/node/t").json()
        assert node["statement"].startswith("The theorem")
        assert node["hypotheses"][0]["tex"] == "s > 3/2"
        assert node["uses"]["a"]["discharges"]["H1"] == "hypothesis:H1"
        assert node["parents"] == []
        assert node["why"][0]["text"].startswith("`t`")
        assert node["obligations"][0]["hypothesis"] == "H1"

    def test_missing_node_is_a_404(self, client, project):
        small(project)
        assert client.get("/api/node/nope").status_code == 404

    def test_why_is_the_same_chain_the_cli_prints(self, client, project):
        small(project)
        lines = client.get("/api/why/t").json()["lines"]
        assert any("not finished" in line["text"] for line in lines)
        assert any(line["depth"] == 1 for line in lines)

    def test_check_returns_the_diagnostics_verbatim(self, client, project):
        small(project)
        data = client.get("/api/check").json()
        codes = {d["code"] for d in data["diagnostics"]}
        assert "DIS010" in codes  # `b` is cited with no uses entry
        assert data["errors"] >= 1

    def test_frontier_matches_the_core_ranking(self, client, project):
        small(project)
        api_items = [i["node"] for i in client.get("/api/frontier").json()["items"]]
        core_items = [i.node for i in frontier.rank(graph_of(project))]
        assert api_items == core_items

    def test_events_are_newest_first_and_human_readable(self, client, project):
        small(project)
        ops.add_note(project, "a", "a thought")
        events = client.get("/api/events").json()["events"]
        assert events[0]["kind"] == "add_note"
        assert "add_note" in events[0]["line"]

    def test_a_cycle_is_reported_rather_than_crashing(self, client, project):
        write_node(project, "a", target=True, children=["b"], proof="cites b")
        write_node(project, "b", children=["a"], proof="cites a")
        response = client.get("/api/graph")
        assert response.status_code == 409
        assert "cycle" in response.json()["detail"]

    def test_agents_reports_what_can_run(self, client, project):
        small(project)
        data = client.get("/api/agents").json()
        assert {r["role"] for r in data["roles"]} >= {"decomposer", "verifier_a"}
        assert "max_calls_per_recompile" in data["budget"]


class TestRender:
    def test_latex_is_served_and_compiles_in_shape(self, client, project):
        small(project)
        tex = client.get("/api/render").text
        assert "\\begin{document}" in tex and "\\end{document}" in tex
        assert "The theorem" in tex

    def test_clean_mode_drops_the_apparatus(self, client, project):
        small(project)
        clean = client.get("/api/render?clean=true").text
        assert "\\section*{Status}" not in clean

    def test_download_sets_a_filename(self, client, project):
        small(project)
        response = client.get("/api/render.tex")
        assert response.status_code == 200
        assert "document.tex" in response.headers["content-disposition"]


class TestMutations:
    def test_edit_statement_reports_what_went_stale(self, client, project):
        small(project)
        ops.record_verification(project, "a", "verified")
        ops.record_verification(project, "t", "verified")

        preview = client.get("/api/node/a/stale-radius").json()
        assert {r["id"] for r in preview["radius"]} == {"a", "t"}

        result = client.post("/api/node/a/statement", json={"text": "A different claim."})
        assert result.status_code == 200
        assert set(result.json()["staled"]) == {"a", "t"}
        assert graph_of(project)["t"].global_status == "blocked:stale"

    def test_admit_requires_a_reason(self, client, project):
        small(project)
        bad = client.post("/api/node/b/admit", json={"reason": "   "})
        assert bad.status_code == 400
        assert "reason" in bad.json()["detail"]

        ok = client.post("/api/node/b/admit", json={"reason": "believed, not proved"})
        assert ok.status_code == 200
        assert graph_of(project)["b"].local_status == "admitted"

    def test_add_child_creates_attaches_and_opens_its_discharge_row(self, client, project):
        """Attaching a lemma must not hand the user a DIS010 they did not cause."""
        small(project)
        response = client.post(
            "/api/node/b/child",
            json={"id": "b.helper", "statement": "A helper.", "difficulty": "routine"},
        )
        assert response.status_code == 200
        parent = graph_of(project)["b"]
        assert parent.children == ["b.helper"]
        assert "b.helper" in parent.uses
        # `t` cites `b` with no row — that is the fixture's own DIS010. The point
        # is that attaching `b.helper` did not add a second one.
        offending = {
            d["code"]
            for d in client.get("/api/check").json()["diagnostics"]
            if "b.helper" in d["message"]
        }
        assert "DIS010" not in offending

    def test_the_discharge_table_is_editable_from_the_browser(self, client, project):
        """Without this the browser can create a DIS011 it cannot then fix."""
        small(project)
        response = client.post(
            "/api/node/t/uses",
            json={"uses": {"a": {"applied_to": "y", "discharges": {"H1": "proof:inline"}}}},
        )
        assert response.status_code == 200
        assert graph_of(project)["t"].uses["a"].discharges["H1"] == "proof:inline"

    def test_a_malformed_discharge_table_is_refused(self, client, project):
        small(project)
        response = client.post(
            "/api/node/t/uses", json={"uses": {"a": {"discharges": "not a mapping"}}}
        )
        assert response.status_code == 400

    def test_a_bad_mutation_is_a_400_with_the_reason(self, client, project):
        small(project)
        response = client.post("/api/node/t/children", json={"children": ["ghost"]})
        assert response.status_code == 400
        assert "does not exist" in response.json()["detail"]

    def test_archive_never_deletes(self, client, project):
        small(project)
        response = client.post("/api/node/b/archive", json={"cascade": True})
        assert response.status_code == 200
        assert (project.nodes_dir / "b.md").exists()
        assert graph_of(project)["b"].lifecycle == "archived"

    def test_the_target_cannot_be_archived(self, client, project):
        small(project)
        assert client.post("/api/node/t/archive", json={"cascade": True}).status_code == 400

    def test_notes_need_text(self, client, project):
        small(project)
        assert client.post("/api/node/a/note", json={"text": "  "}).status_code == 400


class TestJobs:
    """Role calls must never block a request, and must report which agent runs."""

    def _patch_registry(self, monkeypatch, project, **responses):
        import bp.ui.app as app_mod

        def fake(project_arg, replay=False, observer=None):
            registry = scripted_registry(project, **responses)
            registry.observer = observer
            return registry

        monkeypatch.setattr(app_mod, "Registry", fake)

    def test_a_role_call_returns_a_job_id_immediately(self, client, project, monkeypatch):
        small(project)
        self._patch_registry(
            monkeypatch, project,
            obligation=[json_reply({"entails": True, "why": "yes", "confidence": "high"})],
            verifier_a=[json_reply({"checked": ["step 1"], "objections": []})],
            verifier_b=[json_reply({"checked": ["all"], "objections": []})],
        )
        started = client.post("/api/jobs/verify/a", json={"level": "quick"}).json()
        assert started["status"] in ("queued", "running")
        assert started["id"]

        job = _wait(client, started["id"])
        assert job["status"] == "done"
        assert job["result"]["verdict"] == "verified"
        assert graph_of(project)["a"].local_status == "verified"

    def test_the_job_names_the_agent_that_ran(self, client, project, monkeypatch):
        small(project)
        self._patch_registry(
            monkeypatch, project,
            verifier_a=[json_reply({"checked": ["step 1"], "objections": []})],
            verifier_b=[json_reply({"checked": ["all"], "objections": []})],
        )
        started = client.post("/api/jobs/verify/a", json={}).json()
        job = _wait(client, started["id"])
        assert job["calls"] >= 1
        assert "verifier" in job["step"] or job["step"] == "finished"

    def test_a_failing_job_reports_the_error_rather_than_a_500(self, client, project, monkeypatch):
        small(project)
        self._patch_registry(monkeypatch, project)  # no scripted responses at all
        started = client.post("/api/jobs/verify/a", json={}).json()
        job = _wait(client, started["id"])
        assert job["status"] == "failed"
        assert job["error"]

    def test_expand_writes_the_children(self, client, project, monkeypatch):
        small(project)
        payload = {
            "verdict": "decompose",
            "assessed_difficulty": "hard",
            "assessment": "Three separate steps.",
            "strategy": "split it",
            "children": [
                {"slug": f"part-{i}", "role": "lemma", "statement": f"Part {i}.",
                 "difficulty": "routine", "hypotheses": [{"id": "H1", "tex": "x > 0"}],
                 "notes": ""}
                for i in (1, 2, 3)
            ],
            "reduction_proof": "By `part-1`, `part-2` and `part-3`.",
            "uses": {
                f"part-{i}": {"applied_to": "x", "discharges": {"H1": "proof:inline"}}
                for i in (1, 2, 3)
            },
            "notes": "",
        }
        self._patch_registry(monkeypatch, project, decomposer=[json_reply(payload)])
        started = client.post("/api/jobs/expand/b", json={"hint": "split it"}).json()
        job = _wait(client, started["id"])
        assert job["status"] == "done"
        assert len(job["result"]["children"]) == 3
        assert graph_of(project)["b"].children == job["result"]["children"]

    def test_a_node_with_a_running_job_is_reported_busy(self, project):
        runner = JobRunner()
        import threading

        release = threading.Event()
        runner.submit("verify", "a", lambda job: release.wait(5))
        for _ in range(100):
            if runner.busy_nodes():
                break
        assert "a" in runner.busy_nodes()
        release.set()

    def test_a_long_job_does_not_freeze_edits_elsewhere(self, client, project, monkeypatch):
        """The brief: a running job disables the buttons that would conflict with
        it and leaves the rest live. Holding a write lock across a job body froze
        every edit in the interface for the minutes a decomposition takes."""
        import threading

        small(project)
        release = threading.Event()
        runner = client.app.state.runner
        runner.submit("expand", "b", lambda job: release.wait(10))
        for _ in range(200):
            if runner.busy_nodes():
                break
        assert "b" in runner.busy_nodes()

        # A different node is still fully editable while that runs.
        response = client.post("/api/node/a/note", json={"text": "still live"})
        assert response.status_code == 200
        release.set()

    def test_a_mutation_on_a_busy_node_is_refused_with_its_name(self, client, project):
        import threading

        small(project)
        release = threading.Event()
        runner = client.app.state.runner
        runner.submit("expand", "b", lambda job: release.wait(10))
        for _ in range(200):
            if runner.busy_nodes():
                break

        response = client.post("/api/node/b/note", json={"text": "racing"})
        assert response.status_code == 409
        assert "an agent is working on b" in response.json()["detail"]
        release.set()

    def test_recompile_plan_is_synchronous_because_it_costs_nothing(self, client, project):
        small(project)
        data = client.get("/api/recompile/plan").json()
        assert [t["node"] for t in data["tasks"]] == ["a"]
        assert "confirmation calls are not included" in data["text"]

    def test_a_recompile_claims_the_nodes_its_plan_names(self, client, project, monkeypatch):
        """A recompile writes to many nodes but is named after none. Without the
        claim, its buttons stay live and a user can queue a second verification
        of a node it is already verifying."""
        import threading

        small(project)
        release = threading.Event()
        self._patch_registry(monkeypatch, project)
        monkeypatch.setattr(
            "bp.recompile.run", lambda *a, **k: release.wait(10)
        )
        started = client.post("/api/jobs/recompile", json={}).json()
        assert started["nodes"] == ["a"]
        for _ in range(200):
            if client.app.state.runner.busy_nodes():
                break
        assert client.post("/api/node/a/note", json={"text": "x"}).status_code == 409
        # …and everything else is still live.
        assert client.post("/api/node/b/note", json={"text": "x"}).status_code == 200
        release.set()


class TestStaticSurface:
    def test_the_page_is_served(self, client, project):
        small(project)
        html = client.get("/").text
        assert "cytoscape" in html and "katex" in html
        assert 'id="cy"' in html

    def test_the_script_and_stylesheet_are_served(self, client, project):
        small(project)
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/static/style.css").status_code == 200

    def test_the_script_never_assigns_untrusted_text_to_innerhtml(self):
        """Statements are LaTeX written by models. In the terminal, mishandling
        that was cosmetic; in a browser it is script execution."""
        from pathlib import Path

        source = (Path(__file__).parent.parent / "bp/ui/static/app.js").read_text()
        assert "innerHTML" in source  # the KaTeX path
        # The only assignment is inside el(), guarded by the 'html' key, and the
        # only caller passes katex.renderToString output.
        assignments = [
            line for line in source.splitlines()
            if "innerHTML" in line and "=" in line and not line.strip().startswith("*")
        ]
        assert len(assignments) == 1
        assert "KaTeX output only" in assignments[0]
        assert "html: html" in source  # renderMath result, nothing else


def _wait(client, job_id, tries=200):
    import time

    for _ in range(tries):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished: {json.dumps(job)}")


class TestFrontier:
    def test_only_nodes_whose_children_are_finished(self, project):
        write_node(project, "t", target=True, children=["mid"], local_status="verified",
                   proof="cites mid")
        write_node(project, "mid", children=["leaf"], local_status="verified", proof="cites leaf")
        write_node(project, "leaf", proof="an argument")
        items = {i.node for i in frontier.rank(graph_of(project))}
        # `leaf` is where work is possible; `t` and `mid` are merely waiting.
        assert items == {"leaf"}

    def test_ranking_is_shallow_then_gating_many(self, project):
        write_node(project, "t", target=True, children=["a", "deep"], local_status="verified",
                   proof="cites a and deep")
        write_node(project, "a")
        write_node(project, "deep", children=["shared"], local_status="verified",
                   proof="cites shared")
        write_node(project, "other", children=["shared"], local_status="verified",
                   proof="cites shared")
        write_node(project, "shared")
        ops.set_children(project, "t", ["a", "deep", "other"])
        ranked = frontier.rank(graph_of(project))
        assert ranked[0].node == "a"          # depth 1
        assert ranked[-1].node == "shared"    # depth 2, though it gates more
        assert ranked[-1].gates == 3

    def test_each_item_says_what_it_needs(self, project):
        write_node(project, "t", target=True, proof="an argument")
        item = frontier.rank(graph_of(project))[0]
        assert item.needs == "verify the proof"
        assert item.unattempted is False


class TestPreamble:
    """A project's own macros have to reach three places or the notation is
    only correct in the author's head: the document, the agents, the browser."""

    def test_round_trips_through_the_api(self, client, project):
        small(project)
        assert client.get("/api/preamble").text == ""
        text = "\\newcommand{\\RR}{\\mathbb{R}}\n"
        assert client.post("/api/preamble", json={"text": text}).status_code == 200
        assert client.get("/api/preamble").text.strip() == text.strip()
        assert (project.root / "preamble.tex").exists()

    def test_it_reaches_the_rendered_document(self, client, project):
        small(project)
        client.post("/api/preamble", json={"text": "\\newcommand{\\RR}{\\mathbb{R}}"})
        tex = client.get("/api/render").text
        assert "\\newcommand{\\RR}{\\mathbb{R}}" in tex
        assert tex.index("\\newcommand{\\RR}") < tex.index("\\begin{document}")

    def test_it_reaches_the_agents(self, client, project):
        from bp.roles import context as context_mod

        small(project)
        client.post("/api/preamble", json={"text": "\\newcommand{\\RR}{\\mathbb{R}}"})
        block = context_mod.preamble_block(project)
        assert "\\newcommand{\\RR}" in block
        assert "Use the same" in block

    def test_no_preamble_means_no_block(self, project):
        from bp.roles import context as context_mod

        small(project)
        assert context_mod.preamble_block(project) == ""

    def test_the_document_loads_the_standard_packages(self, client, project):
        small(project)
        tex = client.get("/api/render").text
        for package in ("amsmath", "amssymb", "amsthm", "mathtools", "mathrsfs"):
            assert f"\\usepackage{{{package}}}" in tex or f"{{{package}}}" in tex
        # Optional ones are guarded, so a machine without them still builds.
        assert "\\IfFileExists{bbm.sty}" in tex


class TestTidy:
    def _patch(self, monkeypatch, project, **responses):
        import bp.ui.app as app_mod

        def fake(project_arg, replay=False, observer=None):
            return scripted_registry(project, **responses)

        monkeypatch.setattr(app_mod, "Registry", fake)

    def test_a_correction_is_proposed_not_applied(self, client, project, monkeypatch):
        small(project)
        self._patch(monkeypatch, project, checker=[json_reply({
            "changed": True,
            "text": "\\begin{align} a &= b \\end{align}",
            "changes": ["closed the align environment"],
            "concerns": [],
        })])
        response = client.post(
            "/api/tidy",
            json={"text": "\\begin{align} a &= b \\end{aligned}", "kind": "statement"},
        )
        assert response.status_code == 200
        assert response.json()["changed"] is True
        assert "end{align}" in response.json()["text"]
        # Nothing was written: the author has not seen it yet.
        assert graph_of(project)["t"].statement.startswith("The theorem") if hasattr(
            graph_of(project)["t"], "statement"
        ) else True

    def test_clean_latex_comes_back_unchanged(self, client, project, monkeypatch):
        small(project)
        self._patch(monkeypatch, project, checker=[json_reply({
            "changed": False, "text": "$a = b$", "changes": [], "concerns": [],
        })])
        data = client.post("/api/tidy", json={"text": "$a = b$"}).json()
        assert data["changed"] is False
        assert data["changes"] == []

    def test_mathematical_concerns_are_reported_not_fixed(self, client, project, monkeypatch):
        small(project)
        self._patch(monkeypatch, project, checker=[json_reply({
            "changed": False,
            "text": "$p \\in [1, \\infty]$",
            "changes": [],
            "concerns": ["the case p = infinity may need separate treatment"],
        })])
        data = client.post("/api/tidy", json={"text": "$p \\in [1, \\infty]$"}).json()
        assert data["concerns"]
        assert data["text"] == "$p \\in [1, \\infty]$"

    def test_a_failed_proofreader_is_a_502_so_the_page_can_save_anyway(
        self, client, project, monkeypatch
    ):
        small(project)
        self._patch(monkeypatch, project)  # no scripted response
        assert client.post("/api/tidy", json={"text": "$a$"}).status_code == 502


class TestLedgerAndRecord:
    """The browser must tell the same story the terminal does.

    Nothing here computes anything: every field is the core's answer, serialised.
    """

    def _patch(self, monkeypatch, project, **responses):
        from bp.ui import app as app_mod

        def fake(proj, *a, **kw):
            registry = scripted_registry(project, **responses)
            registry.observer = kw.get("observer")
            return registry

        monkeypatch.setattr(app_mod, "Registry", fake)

    def test_a_node_with_no_ledger_says_so(self, client, project):
        small(project)
        data = client.get("/api/node/a").json()
        assert data["claims"] == []
        assert data["ledger_stale"] is False
        assert data["verification"] is None
        assert data["verification_summary"] == "never verified"

    def test_the_ledger_and_its_diagnostics_are_served(self, client, project):
        from bp.hash import proof_hash

        small(project)
        graph = ops.open_graph(project)
        ops.record_ledger(
            project,
            "a",
            [
                {"id": "c1", "text": "s > 3/2", "source": {"kind": "hypothesis", "ref": "H1"}},
                {"id": "c2", "text": "\\omega \\in C^1", "source": {"kind": "none", "ref": ""}},
            ],
            proof_hash(graph["a"]),
        )
        data = client.get("/api/node/a").json()
        assert [c["id"] for c in data["claims"]] == ["c1", "c2"]
        assert data["claims"][1]["source"]["kind"] == "none"
        assert [d["code"] for d in data["ledger_diagnostics"]] == ["LED001"]
        # One claim obligation: the unsourced one is already decided by LED001.
        assert [r["claim"] for r in data["claim_obligations"]] == ["c1"]

    def test_a_stale_ledger_is_reported(self, client, project):
        small(project)
        # A hash that is not this proof's, so the ledger reads as out of date.
        ops.record_ledger(project, "a", [{"id": "c1", "text": "x"}], "0" * 12)
        data = client.get("/api/node/a").json()
        assert data["ledger_stale"] is True
        assert "LED100" in [d["code"] for d in data["ledger_diagnostics"]]

    def test_extract_writes_the_ledger_through_ops(self, client, project, monkeypatch):
        small(project)
        self._patch(
            monkeypatch,
            project,
            extractor=[
                json_reply(
                    {
                        "claims": [
                            {"id": "c1", "text": "s > 3/2",
                             "source": {"kind": "hypothesis", "ref": "H1"}},
                            {"id": "c2", "text": "\\omega \\in C^1",
                             "source": {"kind": "none", "ref": ""}},
                        ]
                    }
                )
            ],
        )
        started = client.post("/api/jobs/extract/a").json()
        job = _wait(client, started["id"])
        assert job["status"] == "done"
        assert job["result"]["claims"] == 2
        assert job["result"]["unsourced"] == ["c2"]
        assert [c.id for c in graph_of(project)["a"].claims] == ["c1", "c2"]

    def test_audit_writes_a_note_and_never_a_status(self, client, project, monkeypatch):
        small(project)
        self._patch(
            monkeypatch,
            project,
            auditor=[
                json_reply(
                    {
                        "well_posed": {"ok": True, "checked": "all bound", "findings": []},
                        "non_vacuous": {"verdict": "not_found", "witness": "",
                                        "conflict": "H1 and H2 cannot both hold"},
                        "quantifiers": {"ok": True, "checked": "as intended", "findings": []},
                        "constants": {"ok": True, "constants": [], "findings": []},
                    }
                )
            ],
        )
        started = client.post("/api/jobs/audit/a").json()
        job = _wait(client, started["id"])
        assert job["status"] == "done"
        assert job["result"]["verdict"] == "flagged"
        node = graph_of(project)["a"]
        assert "cannot both hold" in node.notes_section
        assert node.local_status == "unverified"

    def test_verify_serves_the_record_it_wrote(self, client, project, monkeypatch):
        small(project)
        self._patch(
            monkeypatch,
            project,
            verifier_a=[json_reply({"checked": ["step 1"], "objections": []})],
            verifier_b=[json_reply({"checked": ["all"], "objections": []})],
        )
        started = client.post("/api/jobs/verify/a", json={"level": "quick"}).json()
        job = _wait(client, started["id"])
        assert job["result"]["level"] == "quick"
        assert job["result"]["record"]["level"] == "quick"
        data = client.get("/api/node/a").json()
        assert data["verification"]["level"] == "quick"
        assert "level quick" in data["verification_summary"]

    def test_an_unknown_verify_level_is_a_400_not_a_failed_job(self, client, project):
        small(project)
        response = client.post("/api/jobs/verify/a", json={"level": "thorough"})
        assert response.status_code == 400
        assert "quick" in response.json()["detail"]

    def test_the_recompile_plan_takes_a_level(self, client, project):
        small(project)
        quick = client.get("/api/recompile/plan?level=quick").json()
        deep = client.get("/api/recompile/plan?level=deep").json()
        assert quick["level"] == "quick" and deep["level"] == "deep"
        assert deep["calls"] >= quick["calls"]
        assert client.get("/api/recompile/plan?level=thorough").status_code == 400

    def test_a_recompile_at_a_level_reports_it_back(self, client, project, monkeypatch):
        small(project)
        self._patch(
            monkeypatch,
            project,
            verifier_a=[json_reply({"checked": ["x"], "objections": []})] * 3,
            verifier_b=[json_reply({"checked": ["y"], "objections": []})] * 3,
        )
        started = client.post(
            "/api/jobs/recompile", json={"nodes": [], "level": "quick"}
        ).json()
        job = _wait(client, started["id"])
        assert job["status"] == "done"
        assert job["result"]["level"] == "quick"


class TestRenderErrors:
    """A document that does not compile is a fact about the LaTeX, not a server bug.

    Before this, `/api/render.pdf` raised 500 and the browser reached it by
    `window.open`, so the useful detail landed in a new tab as raw JSON and the
    user read "internal server error" — when the actual answer was usually one
    `tlmgr install` away.
    """

    def test_the_source_endpoints_do_not_need_latex(self, client, project):
        small(project)
        assert client.get("/api/render").status_code == 200
        assert client.get("/api/render.tex").status_code == 200

    def test_a_document_that_will_not_compile_is_422_not_500(self, client, project):
        small(project)
        # An unguarded \usepackage of something that cannot exist: exactly the
        # shape of the user's `\usepackage{enumitem}` on a BasicTeX install.
        ops.set_preamble(project, "\\usepackage{a-package-that-does-not-exist}\n")
        response = client.get("/api/render.pdf")
        if response.status_code == 501:
            pytest.skip("no pdflatex on PATH")
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["kind"] == "missing_package"
        assert "a-package-that-does-not-exist" in detail["message"]
        assert "tlmgr install" in detail["hint"]

    def test_the_compile_probe_answers_without_returning_a_file(self, client, project):
        """The browser asks this first so it can show a problem in the sheet the
        user is looking at, rather than in a new tab."""
        small(project)
        ops.set_preamble(project, "\\usepackage{a-package-that-does-not-exist}\n")
        report = client.get("/api/render/compile").json()
        if (report.get("problem") or {}).get("kind") == "no_engine":
            pytest.skip("no pdflatex on PATH")
        assert report["ok"] is False
        assert report["problem"]["kind"] == "missing_package"

    def test_a_dangling_ref_compiles_but_is_reported_as_a_warning(self, client, project):
        small(project)
        ops.edit_statement(project, "a", "See Section \\ref{nowhere} for the setting.")
        report = client.get("/api/render/compile").json()
        if (report.get("problem") or {}).get("kind") == "no_engine":
            pytest.skip("no pdflatex on PATH")
        assert report["ok"] is True
        assert report["undefined_refs"] == ["nowhere"]
        assert any("??" in w for w in report["warnings"])

    def test_a_failing_compile_does_not_serve_the_previous_pdf(self, client, project):
        small(project)
        first = client.get("/api/render.pdf")
        if first.status_code == 501:
            pytest.skip("no pdflatex on PATH")
        assert first.status_code == 200
        ops.set_preamble(project, "\\usepackage{a-package-that-does-not-exist}\n")
        assert client.get("/api/render.pdf").status_code == 422


class TestArchiveAndBack:
    """"Nothing is destroyed" needs a way back, or it is a promise about the
    filesystem and nothing more. `ops.unarchive` existed from L0 but was reachable
    from neither the CLI nor the browser, so archiving was one-way in practice.
    """

    def test_archived_nodes_are_listed_separately_from_the_graph(self, client, project):
        small(project)
        client.post("/api/node/b/archive", json={"cascade": True})
        graph_ids = {n["id"] for n in client.get("/api/graph").json()["nodes"]}
        assert "b" not in graph_ids          # not part of the argument any more
        archived = client.get("/api/archived").json()["nodes"]
        assert [n["id"] for n in archived] == ["b"]
        assert archived[0]["headline"]        # its text is still there

    def test_bringing_one_back_puts_it_in_the_active_graph(self, client, project):
        small(project)
        client.post("/api/node/b/archive", json={"cascade": True})
        response = client.post("/api/node/b/unarchive")
        assert response.status_code == 200
        assert "b" in {n["id"] for n in client.get("/api/graph").json()["nodes"]}
        assert graph_of(project)["b"].lifecycle == "active"

    def test_it_says_when_the_node_comes_back_uncited(self, client, project):
        """Archiving strips the citation from the parent to keep the graph
        consistent. Restoring does not put it back, because re-citing is a
        decision — so the response says so rather than leaving an orphan silently."""
        small(project)
        client.post("/api/node/b/archive", json={"cascade": True})
        assert client.post("/api/node/b/unarchive").json()["orphan"] is True
        assert "b" not in graph_of(project)["t"].children

    def test_nothing_archived_is_an_empty_list_not_an_error(self, client, project):
        small(project)
        assert client.get("/api/archived").json()["nodes"] == []
