"""DIS010-DIS017 and obligation emission.

The discharge check is the highest-value check in v0, so every code gets a test
that fires it and the clean case gets one that does not.
"""

from __future__ import annotations

from bp.discharge import check_discharge, obligations_for
from bp.graph import Graph
from bp.load import load_nodes

from .conftest import write_node


def graph_of(project) -> Graph:
    nodes, errors = load_nodes(project)
    assert not errors, errors
    return Graph(nodes)


def run(project, node_id="t"):
    graph = graph_of(project)
    return graph, check_discharge(graph[node_id], graph)


def codes(diagnostics):
    return sorted(d.code for d in diagnostics)


CHILD_HYPS = [{"id": "H1", "tex": "a > 0"}, {"id": "H2", "tex": "b > 0"}]


def parent(project, discharges, *, own=("H1",), children=("c",), uses_key="c"):
    write_node(
        project,
        "t",
        target=True,
        children=list(children),
        proof="cites c",
        hypotheses=[{"id": h, "tex": f"{h} holds"} for h in own],
        uses={uses_key: {"applied_to": "x", "discharges": discharges}},
    )
    write_node(project, "c", hypotheses=CHILD_HYPS)


def test_complete_table_is_clean(project):
    parent(project, {"H1": "hypothesis:H1", "H2": "literature:Smith 1990, Thm 2"})
    _, diagnostics = run(project)
    assert diagnostics == []


def test_dis010_child_with_no_uses_entry(project):
    write_node(project, "t", target=True, children=["c"], proof="cites c")
    write_node(project, "c", hypotheses=CHILD_HYPS)
    _, diagnostics = run(project)
    assert codes(diagnostics) == ["DIS010"]


def test_dis011_hypothesis_not_discharged(project):
    parent(project, {"H1": "hypothesis:H1"})
    _, diagnostics = run(project)
    assert codes(diagnostics) == ["DIS011"]
    assert "H2" in diagnostics[0].message and "b > 0" in diagnostics[0].message


def test_dis012_unrecognised_source_form(project):
    parent(project, {"H1": "hypothesis:H1", "H2": "because I say so"})
    _, diagnostics = run(project)
    assert codes(diagnostics) == ["DIS012"]


def test_dis013_hypothesis_source_names_nothing_real(project):
    parent(project, {"H1": "hypothesis:H9", "H2": "proof:inline"})
    _, diagnostics = run(project)
    assert codes(diagnostics) == ["DIS013"]


def test_dis014_child_source_is_not_a_child(project):
    parent(project, {"H1": "child:elsewhere", "H2": "proof:inline"})
    _, diagnostics = run(project)
    assert codes(diagnostics) == ["DIS014"]


def test_dis015_admitted_needs_a_reason(project):
    parent(project, {"H1": "ADMITTED", "H2": "proof:inline"})
    _, diagnostics = run(project)
    assert codes(diagnostics) == ["DIS015"]


def test_dis016_uses_mentions_a_non_child(project):
    write_node(
        project,
        "t",
        target=True,
        children=["c"],
        proof="cites c",
        hypotheses=[{"id": "H1", "tex": "x"}],
        uses={
            "c": {"applied_to": "", "discharges": {"H1": "hypothesis:H1", "H2": "proof:p"}},
            "gone": {"applied_to": "", "discharges": {}},
        },
    )
    write_node(project, "c", hypotheses=CHILD_HYPS)
    _, diagnostics = run(project)
    assert codes(diagnostics) == ["DIS016"]


def test_dis017_discharge_names_a_hypothesis_the_child_does_not_have(project):
    parent(project, {"H1": "hypothesis:H1", "H2": "proof:p", "H7": "proof:p"})
    _, diagnostics = run(project)
    assert codes(diagnostics) == ["DIS017"]


def test_dis100_records_admitted_debt_as_information(project):
    parent(project, {"H1": "ADMITTED: no argument yet", "H2": "proof:p"})
    _, diagnostics = run(project)
    assert codes(diagnostics) == ["DIS100"]
    assert diagnostics[0].severity == "info"


def test_multiline_proof_source_is_accepted(project):
    parent(project, {"H1": "proof:first line\nsecond line", "H2": "proof:p"})
    _, diagnostics = run(project)
    assert diagnostics == []


class TestObligations:
    def test_one_record_per_discharge(self, project):
        parent(project, {"H1": "hypothesis:H1", "H2": "child:sibling"},
               children=("c", "sibling"))
        write_node(project, "sibling", statement="b is positive.")
        graph = graph_of(project)
        records = obligations_for(graph["t"], graph)
        assert [r["hypothesis"] for r in records] == ["H1", "H2"]
        assert records[0]["needed"] == "a > 0"
        assert records[0]["source_text"] == "H1 holds"
        assert records[1]["source_text"] == "b is positive."

    def test_hash_is_stable_under_irrelevant_edits(self, project):
        parent(project, {"H1": "hypothesis:H1", "H2": "proof:p"})
        graph = graph_of(project)
        before = {r["id"]: r["hash"] for r in obligations_for(graph["t"], graph)}

        # Reformat the source text without changing what it says.
        write_node(
            project,
            "t",
            target=True,
            children=["c"],
            proof="cites c",
            hypotheses=[{"id": "H1", "tex": "H1   holds"}],
            uses={"c": {"applied_to": "x", "discharges": {"H1": "hypothesis:H1", "H2": "proof:p"}}},
        )
        graph = graph_of(project)
        after = {r["id"]: r["hash"] for r in obligations_for(graph["t"], graph)}
        assert before == after

    def test_hash_moves_when_the_question_changes(self, project):
        parent(project, {"H1": "hypothesis:H1", "H2": "proof:p"})
        graph = graph_of(project)
        before = {r["id"]: r["hash"] for r in obligations_for(graph["t"], graph)}

        write_node(project, "c", hypotheses=[{"id": "H1", "tex": "a > 1"},
                                             {"id": "H2", "tex": "b > 0"}])
        graph = graph_of(project)
        after = {r["id"]: r["hash"] for r in obligations_for(graph["t"], graph)}
        assert before["ob:t:c:H1"] != after["ob:t:c:H1"]
        assert before["ob:t:c:H2"] == after["ob:t:c:H2"]

    def test_admitted_obligations_are_marked_as_such(self, project):
        parent(project, {"H1": "ADMITTED: later", "H2": "proof:p"})
        graph = graph_of(project)
        records = obligations_for(graph["t"], graph)
        assert records[0]["kind"] == "admitted"
        assert records[1]["kind"] == "entailment"
