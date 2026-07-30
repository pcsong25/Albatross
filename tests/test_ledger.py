"""LED001-LED006, LED100, and claim-obligation emission.

The ledger is the other half of the anti-gap device: ``DIS011`` covers the
children's hypotheses, ``LED001`` covers what the reduction claims on its own
account. Every code gets a test that fires it, and the clean case gets one that
does not, because a check that fires on a clean node trains the user to ignore it.

Written against a **hand-written** ledger throughout. The extractor that normally
produces one is an agent and is tested separately: the audit must be
demonstrable without a model in the loop.
"""

from __future__ import annotations

import pytest

from bp import ops
from bp.graph import Graph
from bp.hash import proof_hash
from bp.ledger import (
    claim_obligations_for,
    check_ledger,
    ledger_is_stale,
    summarise,
)
from bp.load import load_nodes

from .conftest import write_node


def graph_of(project) -> Graph:
    nodes, errors = load_nodes(project)
    assert not errors, errors
    return Graph(nodes)


def codes(diagnostics):
    return sorted(d.code for d in diagnostics)


def claim(cid, text="a claim", kind="none", ref=""):
    return {"id": cid, "text": text, "source": {"kind": kind, "ref": ref}}


def node_with(project, claims, *, proof="By `c` we are done.", **extra):
    """A parent with one child, one hypothesis, and the given hand-written ledger.

    ``claims_of`` is set to the proof's hash so the ledger counts as current;
    staleness has its own test.
    """
    frontmatter = {
        "target": True,
        "children": ["c"],
        "proof": proof,
        "hypotheses": [{"id": "H1", "tex": "a > 0"}],
        "uses": {"c": {"applied_to": "x", "discharges": {}}},
        "claims": claims,
        **extra,
    }
    write_node(project, "t", **frontmatter)
    write_node(project, "c", statement="The lemma.")
    graph = graph_of(project)
    node = graph["t"]
    if "claims_of" not in extra:
        node.claims_of = proof_hash(node)
    return graph, node


class TestAudit:
    def test_a_fully_sourced_ledger_is_clean(self, project):
        _, node = node_with(
            project,
            [
                claim("c1", "a > 0", "hypothesis", "H1"),
                claim("c2", "the lemma holds", "child", "c"),
                claim("c3", "b > 0", "claim", "c1"),
                claim("c4", "\\omega \\in C^1", "literature", "Gilbarg-Trudinger Thm 8.8"),
                claim("c5", "the integral is 2.401", "computation", "notes/quad.ipynb"),
            ],
        )
        assert check_ledger(node) == []

    def test_no_ledger_at_all_says_nothing(self, project):
        """At `--level quick` the extractor never runs. A check that complained
        about every unextracted node would be noise on exactly the nodes the user
        has not asked about yet; the verification record says `ledger: not_run`
        instead."""
        _, node = node_with(project, [])
        assert check_ledger(node) == []

    def test_LED001_an_unsourced_claim_is_an_error(self, project):
        _, node = node_with(
            project,
            [claim("c1", "a > 0", "hypothesis", "H1"), claim("c2", "\\omega \\in C^1")],
        )
        diagnostics = check_ledger(node)
        assert codes(diagnostics) == ["LED001"]
        assert diagnostics[0].severity == "error"
        assert "c2" in diagnostics[0].message
        # It fires on exactly the unsourced claim, not on the sourced one.
        assert "c1" not in diagnostics[0].message

    def test_LED002_a_child_source_must_name_a_child(self, project):
        _, node = node_with(project, [claim("c1", "x", "child", "not-a-child")])
        assert codes(check_ledger(node)) == ["LED002"]

    def test_LED003_a_hypothesis_source_must_name_a_hypothesis(self, project):
        _, node = node_with(project, [claim("c1", "x", "hypothesis", "H9")])
        diagnostics = check_ledger(node)
        assert codes(diagnostics) == ["LED003"]
        assert "H1" in (diagnostics[0].hint or "")

    def test_LED004_a_claim_may_not_rest_on_a_later_claim(self, project):
        _, node = node_with(
            project,
            [claim("c1", "x", "claim", "c2"), claim("c2", "y", "hypothesis", "H1")],
        )
        diagnostics = check_ledger(node)
        assert codes(diagnostics) == ["LED004"]
        assert "later" in diagnostics[0].message

    def test_LED004_a_claim_may_not_rest_on_itself(self, project):
        _, node = node_with(project, [claim("c1", "x", "claim", "c1")])
        diagnostics = check_ledger(node)
        assert codes(diagnostics) == ["LED004"]
        assert "itself" in diagnostics[0].message

    def test_LED004_a_claim_source_naming_nothing_is_an_error(self, project):
        _, node = node_with(project, [claim("c1", "x", "claim", "c7")])
        assert codes(check_ledger(node)) == ["LED004"]

    def test_LED004_duplicate_claim_ids(self, project):
        _, node = node_with(
            project,
            [
                claim("c1", "x", "hypothesis", "H1"),
                claim("c1", "y", "hypothesis", "H1"),
            ],
        )
        assert codes(check_ledger(node)) == ["LED004"]

    def test_a_backwards_claim_reference_is_fine(self, project):
        _, node = node_with(
            project,
            [claim("c1", "x", "hypothesis", "H1"), claim("c2", "y", "claim", "c1")],
        )
        assert check_ledger(node) == []

    @pytest.mark.parametrize("ref", ["standard", "well known", "classical", ""])
    def test_LED005_a_vague_literature_reference_is_a_warning(self, project, ref):
        """"standard" is how an unsourced claim looks when it wants to pass as a
        sourced one. A warning, not an error: a real result vaguely cited is still
        a real result, and the claim check can judge it."""
        _, node = node_with(project, [claim("c1", "x", "literature", ref)])
        diagnostics = check_ledger(node)
        assert codes(diagnostics) == ["LED005"]
        assert diagnostics[0].severity == "warn"

    def test_a_named_literature_reference_is_clean(self, project):
        _, node = node_with(
            project, [claim("c1", "x", "literature", "Constantin-Lax-Majda 1985")]
        )
        assert check_ledger(node) == []

    def test_LED006_a_computation_with_no_artifact_is_a_warning(self, project):
        _, node = node_with(
            project, [claim("c1", "x", "computation", "a short calculation")]
        )
        diagnostics = check_ledger(node)
        assert codes(diagnostics) == ["LED006"]
        assert diagnostics[0].severity == "warn"

    def test_a_computation_naming_an_artifact_is_clean(self, project):
        _, node = node_with(
            project, [claim("c1", "x", "computation", "see scripts/kappa.py")]
        )
        assert check_ledger(node) == []

    def test_LED100_a_ledger_extracted_from_an_older_proof(self, project):
        _, node = node_with(
            project,
            [claim("c1", "x", "hypothesis", "H1")],
            claims_of="0" * 12,
        )
        diagnostics = check_ledger(node)
        assert codes(diagnostics) == ["LED100"]
        assert diagnostics[0].severity == "warn"
        assert ledger_is_stale(node)

    def test_a_current_ledger_is_not_stale(self, project):
        _, node = node_with(project, [claim("c1", "x", "hypothesis", "H1")])
        assert not ledger_is_stale(node)

    def test_summarise_counts_what_the_record_needs(self, project):
        _, node = node_with(
            project,
            [claim("c1", "x", "hypothesis", "H1"), claim("c2", "y"), claim("c3", "z")],
        )
        assert summarise(node) == {"claims": 3, "unsourced": 2}


class TestClaimObligations:
    def test_one_record_per_sourced_claim(self, project):
        graph, node = node_with(
            project,
            [
                claim("c1", "a > 0", "hypothesis", "H1"),
                claim("c2", "the lemma", "child", "c"),
                claim("c3", "unsourced", "none"),
            ],
        )
        records = claim_obligations_for(node, graph)
        # The unsourced claim produces no record: LED001 has already decided it,
        # deterministically, and asking a model would invite it to unsettle that.
        assert [r["claim"] for r in records] == ["c1", "c2"]
        assert all(r["kind"] == "claim" for r in records)
        assert all(r["parent"] == "t" for r in records)

    def test_the_source_text_travels_with_the_record(self, project):
        """The verifier is asked a self-contained question, so the source comes
        with it rather than being something a model has to go and look up."""
        graph, node = node_with(
            project,
            [
                claim("c1", "a > 0", "hypothesis", "H1"),
                claim("c2", "the lemma", "child", "c"),
                claim("c3", "still a > 0", "claim", "c1"),
                claim("c4", "known", "literature", "Smith 1990"),
            ],
        )
        by_id = {r["claim"]: r for r in claim_obligations_for(node, graph)}
        assert by_id["c1"]["source_text"] == "a > 0"
        assert by_id["c2"]["source_text"] == "The lemma."
        assert by_id["c3"]["source_text"] == "a > 0"
        assert by_id["c4"]["source_text"] == "Smith 1990"

    def test_hashes_are_stable_and_distinct(self, project):
        graph, node = node_with(
            project,
            [
                claim("c1", "a > 0", "hypothesis", "H1"),
                claim("c2", "b > 0", "hypothesis", "H1"),
            ],
        )
        first = claim_obligations_for(node, graph)
        second = claim_obligations_for(node, graph)
        assert [r["hash"] for r in first] == [r["hash"] for r in second]
        assert len({r["hash"] for r in first}) == 2

    def test_the_hash_moves_when_the_question_changes(self, project):
        graph, node = node_with(project, [claim("c1", "a > 0", "hypothesis", "H1")])
        before = claim_obligations_for(node, graph)[0]["hash"]
        node.claims[0].text = "a > 1"
        after = claim_obligations_for(node, graph)[0]["hash"]
        assert before != after

    def test_the_hash_does_not_move_on_reformatting(self, project):
        """Whitespace is not a change of question. If it were, editing one
        paragraph would re-bill every check in the node."""
        graph, node = node_with(project, [claim("c1", "a  >  0", "hypothesis", "H1")])
        before = claim_obligations_for(node, graph)[0]["hash"]
        node.claims[0].text = "a > 0"
        assert claim_obligations_for(node, graph)[0]["hash"] == before


class TestOps:
    def test_the_ledger_is_computed_and_refuses_to_be_authored(self, project):
        """A ledger any role could edit would let the model that makes a claim
        decide the claim is sourced, and LED001 would stop meaning anything."""
        node_with(project, [])
        graph = ops.open_graph(project)
        for field in ("claims", "claims_of", "verification"):
            with pytest.raises(ops.ComputedFieldError):
                ops.set_authored(graph["t"], field, [])

    def test_record_ledger_writes_the_claims_and_the_proof_hash(self, project):
        node_with(project, [])
        graph = ops.open_graph(project)
        digest = proof_hash(graph["t"])
        ops.record_ledger(
            project,
            "t",
            [claim("c1", "a > 0", "hypothesis", "H1"), claim("c2", "unsourced")],
            digest,
        )
        node = graph_of(project)["t"]
        assert [c.id for c in node.claims] == ["c1", "c2"]
        assert node.claims[0].source.ref == "H1"
        assert node.claims_of == digest
        assert not ledger_is_stale(node)
        assert codes(check_ledger(node)) == ["LED001"]

    def test_a_duplicate_claim_id_is_refused_rather_than_written(self, project):
        node_with(project, [])
        with pytest.raises(ops.OpError):
            ops.record_ledger(project, "t", [claim("c1"), claim("c1")], "abc")

    def test_editing_the_proof_makes_the_ledger_stale(self, project):
        node_with(project, [])
        graph = ops.open_graph(project)
        ops.record_ledger(
            project, "t", [claim("c1", "a > 0", "hypothesis", "H1")], proof_hash(graph["t"])
        )
        assert not ledger_is_stale(graph_of(project)["t"])
        ops.edit_proof(project, "t", "By `c`, and also by a new step, we are done.")
        node = graph_of(project)["t"]
        assert ledger_is_stale(node)
        assert "LED100" in codes(check_ledger(node))

    def test_the_ledger_survives_a_round_trip(self, project):
        """Claim text is LaTeX and goes into YAML. It has to come back unchanged."""
        node_with(project, [])
        graph = ops.open_graph(project)
        text = "\\|\\omega(t)\\|_{H^s} \\le \\varepsilon_0 \\text{ for } t < T"
        ops.record_ledger(
            project, "t", [claim("c1", text, "hypothesis", "H1")], proof_hash(graph["t"])
        )
        assert graph_of(project)["t"].claims[0].text == text


class TestCheckRunner:
    def test_bp_check_runs_the_ledger_audit(self, project):
        from bp import checks

        node_with(project, [claim("c1", "\\omega \\in C^1")])
        graph = ops.open_graph(project)
        ops.record_ledger(
            project, "t", [claim("c1", "\\omega \\in C^1")], proof_hash(graph["t"])
        )
        report = checks.run(project)
        assert "LED001" in codes(report.diagnostics)
        assert not report.ok

    def test_for_node_groups_diagnostics_by_family(self, project):
        from bp import checks

        graph, _ = node_with(project, [])
        families = checks.for_node(graph, graph["t"])
        assert set(families) == set(checks.FAMILIES)
