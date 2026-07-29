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
            verifier_a=[json_reply({"entails": True, "why": "yes", "confidence": "high"}),
                        json_reply({"checked": ["step 1"], "objections": []})],
            verifier_b=[json_reply({"checked": ["all"], "objections": []})],
        )
        started = client.post("/api/jobs/verify/a", json={}).json()
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
