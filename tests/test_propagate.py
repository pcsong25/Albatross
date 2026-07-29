"""Propagation. The invariants asserted here are the point of the whole system.

``sweep`` asserts its own invariants in production, so the random-graph test
below is a genuine property test: if any generated graph could make the derived
layer lie, the sweep raises.
"""

from __future__ import annotations

import random

import pytest

from bp.checks import load_graph
from bp.graph import Graph
from bp.load import load_nodes
from bp.propagate import (
    BLOCKED_CHILDREN,
    BLOCKED_OBJECTION,
    BLOCKED_STALE,
    BLOCKED_UNVERIFIED,
    GLOBAL_STATUSES,
    OPEN,
    PROVED,
    PROVED_MODULO,
    PropagationError,
    assert_invariants,
    effective_local,
    sweep,
)

from .conftest import write_node


def swept(project) -> Graph:
    nodes, errors = load_nodes(project)
    assert not errors, errors
    graph = Graph(nodes)
    sweep(graph)
    return graph


class TestStatusTable:
    def test_unverified_leaf_with_no_proof_is_open(self, project):
        write_node(project, "a", target=True)
        assert swept(project)["a"].global_status == OPEN

    def test_unverified_leaf_with_a_proof_is_blocked(self, project):
        write_node(project, "a", target=True, proof="An argument.")
        assert swept(project)["a"].global_status == BLOCKED_UNVERIFIED

    def test_verified_leaf_is_proved(self, project):
        write_node(project, "a", target=True, local_status="verified", proof="p")
        node = swept(project)["a"]
        assert node.global_status == PROVED
        assert node.support == []

    def test_flagged_is_blocked_by_objection(self, project):
        write_node(project, "a", target=True, local_status="flagged", proof="p")
        assert swept(project)["a"].global_status == BLOCKED_OBJECTION

    def test_admitted_supports_itself(self, project):
        write_node(project, "a", target=True, local_status="admitted",
                   status_reason="believed")
        node = swept(project)["a"]
        assert node.global_status == PROVED_MODULO
        assert node.support == ["a"]

    def test_assumption_supports_itself(self, project):
        write_node(project, "a", target=True, local_status="assumption",
                   status_reason="taken as given")
        assert swept(project)["a"].support == ["a"]

    def test_stale_beats_every_other_reason(self, project):
        write_node(project, "a", target=True, local_status="verified", proof="p",
                   verified_against={"self": "0" * 12})
        node = swept(project)["a"]
        assert node.stale is True
        assert node.global_status == BLOCKED_STALE

    def test_never_verified_is_not_stale(self, project):
        write_node(project, "a", target=True, proof="p")
        assert swept(project)["a"].stale is False

    def test_child_statement_change_stales_the_parent(self, project):
        write_node(project, "t", target=True, children=["c"], local_status="verified",
                   proof="cites c", verified_against={"self": "x", "c": "stale-hash"})
        write_node(project, "c", local_status="verified", proof="p")
        assert swept(project)["t"].global_status == BLOCKED_STALE

    def test_support_unions_over_children(self, project):
        write_node(project, "t", target=True, children=["a", "b"],
                   local_status="verified", proof="cites a and b")
        write_node(project, "a", local_status="admitted", status_reason="r")
        write_node(project, "b", local_status="assumption", status_reason="r")
        node = swept(project)["t"]
        assert node.support == ["a", "b"]
        assert node.global_status == PROVED_MODULO

    def test_blocked_children_names_only_the_unfinished_ones(self, project):
        write_node(project, "t", target=True, children=["ok", "bad"],
                   local_status="verified", proof="cites ok and bad")
        write_node(project, "ok", local_status="verified", proof="p")
        write_node(project, "bad")
        node = swept(project)["t"]
        assert node.global_status == BLOCKED_CHILDREN
        assert node.blocked_by == ["bad"]

    def test_archived_nodes_leave_the_derived_layer(self, project):
        write_node(project, "t", target=True, local_status="verified", proof="p")
        write_node(project, "old", lifecycle="archived", local_status="verified")
        assert swept(project)["old"].global_status == "archived"


class TestAdmittedDischargeClamp:
    """An ADMITTED discharge caps the parent at ``admitted`` however its author
    labelled it, so the debt reaches the certificate instead of vanishing."""

    def setup_parent(self, project, source):
        write_node(
            project,
            "t",
            target=True,
            children=["c"],
            local_status="verified",
            proof="cites c",
            hypotheses=[{"id": "H1", "tex": "x"}],
            uses={"c": {"applied_to": "y", "discharges": {"H1": source}}},
        )
        write_node(project, "c", local_status="verified", proof="p",
                   hypotheses=[{"id": "H1", "tex": "x"}])

    def test_clamped(self, project):
        self.setup_parent(project, "ADMITTED: no argument for this yet")
        graph = swept(project)
        assert effective_local(graph["t"]) == "admitted"
        assert graph["t"].global_status == PROVED_MODULO
        assert graph["t"].support == ["t"]

    def test_not_clamped_without_an_admission(self, project):
        self.setup_parent(project, "hypothesis:H1")
        graph = swept(project)
        assert graph["t"].global_status == PROVED
        assert graph["t"].support == []

    def test_local_status_on_disk_is_left_alone(self, project):
        """The clamp is a derivation, not an edit. The author's opinion stays
        exactly as they wrote it."""
        self.setup_parent(project, "ADMITTED: reason")
        assert swept(project)["t"].local_status == "verified"


class TestInvariants:
    def test_violation_is_caught(self, project):
        write_node(project, "t", target=True, local_status="verified", proof="p")
        graph = swept(project)
        graph["t"].support = ["something"]
        graph["t"].global_status = PROVED
        with pytest.raises(PropagationError):
            assert_invariants(graph)

    def test_proved_requires_proved_descendants(self, project):
        write_node(project, "t", target=True, children=["c"],
                   local_status="verified", proof="cites c")
        write_node(project, "c", local_status="verified", proof="p")
        graph = swept(project)
        graph["c"].global_status = OPEN
        with pytest.raises(PropagationError):
            assert_invariants(graph)


LOCALS = ["unverified", "verified", "flagged", "admitted", "assumption"]


def random_project(project, rng: random.Random, n: int = 12) -> None:
    ids = [f"n{i}" for i in range(n)]
    for i, node_id in enumerate(ids):
        # Edges only from later to earlier indices, so the graph is acyclic by
        # construction; cycles are the integrity checker's problem, not the
        # sweep's.
        pool = ids[:i]
        children = rng.sample(pool, k=min(len(pool), rng.randint(0, 3)))
        local = rng.choice(LOCALS)
        hyps = [{"id": "H1", "tex": "h"}] if rng.random() < 0.5 else []
        uses = {}
        for c in children:
            source = rng.choice(
                ["hypothesis:H1", "proof:inline", "ADMITTED: unfinished", "literature:ref"]
            )
            uses[c] = {"applied_to": "obj", "discharges": {"H1": source}}
        verified_against = {}
        if local == "verified" and rng.random() < 0.4:
            verified_against = {"self": "deadbeef0000"}
        write_node(
            project,
            node_id,
            target=(i == n - 1),
            children=children,
            local_status=local,
            status_reason="because" if local in {"admitted", "assumption"} else None,
            proof=("cites " + ", ".join(children)) if rng.random() < 0.8 else "",
            hypotheses=hyps,
            uses=uses,
            verified_against=verified_against,
        )


@pytest.mark.parametrize("seed", range(25))
def test_random_graphs_satisfy_the_invariants(project, seed):
    rng = random.Random(seed)
    random_project(project, rng, n=rng.randint(4, 14))
    graph = swept(project)  # sweep() asserts the invariants itself
    assert_invariants(graph)

    for node in graph.active.values():
        assert node.global_status in GLOBAL_STATUSES
        if node.global_status == PROVED:
            assert node.support == []
        if node.global_status != BLOCKED_CHILDREN:
            assert node.blocked_by == []


@pytest.mark.parametrize("seed", range(10))
def test_sweep_is_idempotent(project, seed):
    rng = random.Random(1000 + seed)
    random_project(project, rng, n=10)
    graph = swept(project)
    first = {n.id: (n.global_status, tuple(n.support), n.stale) for n in graph}
    sweep(graph)
    second = {n.id: (n.global_status, tuple(n.support), n.stale) for n in graph}
    assert first == second


def test_the_shipped_development_sweeps_and_holds_its_invariants(fixture_project):
    """The real project in ``nodes/``.

    This asserts what must be true of it however the mathematics is going, not a
    snapshot of the statuses. That directory is a *live* project — agents expand
    it, the acceptance sessions edit it — and a test pinning exact statuses there
    fails every time the system is actually used, which trains you to ignore it.
    Exact status behaviour is covered above, on synthetic graphs that hold still.
    """
    graph, diagnostics, ok = load_graph(fixture_project)
    assert ok
    assert not [d for d in diagnostics if d.severity == "error"]
    assert_invariants(graph)  # would already have raised inside the sweep

    target = graph.target
    assert target is not None and target.id == "gclm.blowup"

    for node in graph.active.values():
        assert node.global_status in GLOBAL_STATUSES
        assert node.statement_hash
        if node.global_status == PROVED:
            assert node.support == []

    # An admission is a statement about the node, not about what sits under it:
    # `gclm.elb-b` supports itself even though the decomposer has since given it
    # children of its own.
    elb_b = graph["gclm.elb-b"]
    assert elb_b.local_status == "admitted"
    assert elb_b.global_status == PROVED_MODULO
    assert elb_b.support == ["gclm.elb-b"]
    assert elb_b.children
