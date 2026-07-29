"""Integrity: the conditions everything above the graph assumes."""

from __future__ import annotations

import pytest

from bp.checks import load_graph
from bp.graph import Graph, GraphError
from bp.load import load_nodes

from .conftest import write_node


def codes(diagnostics):
    return sorted(d.code for d in diagnostics)


def build(project) -> Graph:
    nodes, errors = load_nodes(project)
    assert not errors, errors
    return Graph(nodes)


def test_clean_graph_has_no_integrity_errors(project):
    write_node(project, "t", children=["a"], target=True, proof="uses a")
    write_node(project, "a")
    assert [d for d in build(project).integrity() if d.severity == "error"] == []


def test_dangling_child(project):
    write_node(project, "t", children=["ghost"], target=True)
    assert "REF001" in codes(build(project).integrity())


def test_self_citation(project):
    write_node(project, "t", children=["t"], target=True)
    assert "REF002" in codes(build(project).integrity())


def test_cycle_reports_the_full_cycle(project):
    write_node(project, "a", children=["b"], target=True)
    write_node(project, "b", children=["c"])
    write_node(project, "c", children=["a"])
    graph = build(project)
    cycle_diags = [d for d in graph.integrity() if d.code == "REF003"]
    assert cycle_diags
    message = cycle_diags[0].message
    for node_id in ("a", "b", "c"):
        assert node_id in message
    with pytest.raises(GraphError):
        graph.topo_order()


def test_archived_child_is_an_error(project):
    write_node(project, "t", children=["a"], target=True)
    write_node(project, "a", lifecycle="archived")
    assert "REF004" in codes(build(project).integrity())


def test_orphan_warning(project):
    write_node(project, "t", target=True)
    write_node(project, "loose")
    assert "REF005" in codes(build(project).integrity())


def test_verified_with_children_that_the_proof_ignores(project):
    write_node(project, "t", children=["a"], target=True, local_status="verified",
               proof="A proof that never mentions its lemma.")
    write_node(project, "a")
    assert "REF006" in codes(build(project).integrity())


def test_duplicate_ids(project):
    write_node(project, "t", target=True)
    (project.nodes_dir / "copy.md").write_text(
        (project.nodes_dir / "t.md").read_text(), encoding="utf-8"
    )
    assert "REF007" in codes(build(project).integrity())


def test_missing_and_multiple_targets(project):
    write_node(project, "a")
    assert "REF008" in codes(build(project).integrity())
    write_node(project, "a", target=True)
    write_node(project, "b", target=True)
    assert "REF008" in codes(build(project).integrity())


def test_parents_are_computed_not_stored(project):
    write_node(project, "t", children=["shared"], target=True, proof="shared")
    write_node(project, "other", children=["shared"], proof="shared")
    write_node(project, "shared")
    graph = build(project)
    assert graph.parents("shared") == ["other", "t"]


def test_reverse_topo_puts_children_first(project):
    write_node(project, "t", children=["a"], target=True)
    write_node(project, "a", children=["b"])
    write_node(project, "b")
    order = build(project).reverse_topo_order()
    assert order.index("b") < order.index("a") < order.index("t")


def test_cycle_makes_the_sweep_bail_rather_than_guess(project):
    write_node(project, "a", children=["b"], target=True)
    write_node(project, "b", children=["a"])
    _, _, swept = load_graph(project)
    assert swept is False
