"""Mutations: they are logged, they re-derive, and they refuse to lie."""

from __future__ import annotations

import json

import pytest

from bp import events, ops
from bp.checks import load_graph
from bp.load import read_node
from bp.propagate import BLOCKED_STALE, PROVED, PROVED_MODULO

from .conftest import write_node


def graph(project):
    g, diagnostics, ok = load_graph(project)
    assert ok, diagnostics
    return g


def base(project):
    write_node(project, "t", target=True, children=["c"], local_status="verified",
               proof="cites c", hypotheses=[{"id": "H1", "tex": "x"}],
               uses={"c": {"applied_to": "y", "discharges": {"H1": "hypothesis:H1"}}})
    write_node(project, "c", local_status="verified", proof="p",
               hypotheses=[{"id": "H1", "tex": "x"}])


class TestGuard:
    @pytest.mark.parametrize(
        "field", ["global_status", "support", "blocked_by", "statement_hash", "stale"]
    )
    def test_computed_fields_cannot_be_authored(self, project, field):
        base(project)
        node = graph(project)["t"]
        with pytest.raises(ops.ComputedFieldError):
            ops.set_authored(node, field, "nonsense")

    def test_verified_against_needs_a_verification(self, project):
        base(project)
        node = graph(project)["t"]
        with pytest.raises(ops.ComputedFieldError):
            ops.set_authored(node, "verified_against", {"self": "x"})


class TestEditing:
    def test_edit_statement_reports_its_blast_radius(self, project):
        base(project)
        ops.record_verification(project, "c", "verified")
        ops.record_verification(project, "t", "verified")
        result = ops.edit_statement(project, "c", "A different claim entirely.")
        assert set(result.event["payload"]["stale_radius"]) == {"c", "t"}
        assert graph(project)["t"].global_status == BLOCKED_STALE

    def test_edit_proof_does_not_stale_anything(self, project):
        base(project)
        ops.record_verification(project, "c", "verified")
        result = ops.edit_proof(project, "c", "A tidier argument.")
        assert result.event["payload"]["stale_radius"] == []
        assert graph(project)["c"].stale is False

    def test_add_note_appends_and_keeps_the_old_ones(self, project):
        base(project)
        ops.add_note(project, "c", "first thought")
        ops.add_note(project, "c", "second thought")
        notes = graph(project)["c"].notes_section
        assert "first thought" in notes and "second thought" in notes


class TestStructure:
    def test_add_node_attaches_to_a_parent(self, project):
        base(project)
        ops.add_node(project, "new", statement="Something.", parent="t")
        assert graph(project)["t"].children == ["c", "new"]

    def test_add_node_refuses_a_duplicate_id(self, project):
        base(project)
        with pytest.raises(ops.OpError):
            ops.add_node(project, "c")

    def test_set_children_refuses_a_cycle(self, project):
        base(project)
        with pytest.raises(ops.OpError) as exc:
            ops.set_children(project, "c", ["t"])
        assert "cycle" in str(exc.value)

    def test_set_children_refuses_a_missing_child(self, project):
        base(project)
        with pytest.raises(ops.OpError):
            ops.set_children(project, "t", ["ghost"])

    def test_set_uses_validates_shape(self, project):
        base(project)
        with pytest.raises(ops.OpError):
            ops.set_uses(project, "t", {"c": {"discharges": "not a mapping"}})

    def test_set_uses_round_trips(self, project):
        base(project)
        ops.set_uses(
            project, "t", {"c": {"applied_to": "z", "discharges": {"H1": "proof:inline"}}}
        )
        node = graph(project)["t"]
        assert node.uses["c"].discharges == {"H1": "proof:inline"}
        assert node.uses["c"].applied_to == "z"


class TestStatus:
    def test_admit_requires_a_reason(self, project):
        base(project)
        with pytest.raises(ops.OpError):
            ops.admit(project, "c", "   ")

    def test_admit_makes_the_node_its_own_support(self, project):
        base(project)
        ops.admit(project, "c", "believed, not proved")
        g = graph(project)
        assert g["c"].global_status == PROVED_MODULO
        assert g["t"].support == ["c"]

    def test_record_verification_writes_the_certificate(self, project):
        base(project)
        ops.record_verification(project, "t", "verified")
        node = graph(project)["t"]
        assert node.verified_against["self"] == node.statement_hash
        assert node.verified_against["c"] == graph(project)["c"].statement_hash

    def test_flagging_blocks_the_node(self, project):
        base(project)
        ops.record_verification(project, "c", "flagged",
                                [{"why": "step three does not follow"}])
        assert graph(project)["c"].local_status == "flagged"
        assert graph(project)["c"].global_status == "blocked:objection"


class TestArchive:
    def test_archive_detaches_parents_and_keeps_the_file(self, project):
        base(project)
        ops.archive(project, "c")
        assert (project.nodes_dir / "c.md").exists()
        assert read_node(project.nodes_dir / "c.md").lifecycle == "archived"
        assert graph(project)["t"].children == []
        assert graph(project)["t"].uses == {}

    def test_archive_cascades_to_orphans_only(self, project):
        write_node(project, "t", target=True, children=["mid"], proof="cites mid")
        write_node(project, "mid", children=["orphan", "shared"],
                   proof="cites orphan and shared")
        write_node(project, "orphan")
        write_node(project, "shared")
        write_node(project, "other", children=["shared"], proof="cites shared")
        ops.set_children(project, "t", ["mid", "other"])

        ops.archive(project, "mid")
        g = graph(project)
        assert g["mid"].lifecycle == "archived"
        assert g["orphan"].lifecycle == "archived"
        assert g["shared"].lifecycle == "active"  # still cited by `other`

    def test_target_is_not_archivable(self, project):
        base(project)
        with pytest.raises(ops.OpError):
            ops.archive(project, "t")


class TestEvents:
    def test_every_mutation_appends_exactly_one_event(self, project):
        base(project)
        ops.add_note(project, "c", "hello")
        ops.relabel(project, "c", "hard")
        ops.admit(project, "c", "reason")
        log = events.read(project)
        assert [e["kind"] for e in log] == ["add_note", "relabel", "admit"]
        assert all(e["uuid"] for e in log)
        assert len({e["uuid"] for e in log}) == 3

    def test_it_is_stored_in_utc_and_shown_in_local_time(self, project):
        """Storage and display are different jobs. A log read on another machine a
        year later needs the offset; a mathematician reading "22:57" for something they
        did over lunch should not have to convert in their head."""
        from datetime import datetime

        base(project)
        ops.add_note(project, "c", "hello")
        stored = events.read(project)[-1]["ts"]
        assert stored.endswith("+00:00")

        shown = events.local(stored)
        assert "+00:00" not in shown and "T" not in shown
        expect = datetime.fromisoformat(stored).astimezone()
        assert shown == expect.strftime("%Y-%m-%d %H:%M:%S")
        # And the line a person reads uses it.
        assert shown in events.describe(events.read(project)[-1])

    def test_a_timestamp_it_cannot_parse_is_shown_as_stored(self, project):
        """Display code must not raise on an odd log line — the line is still worth
        reading, and this is the one place a hand-edited log would surface."""
        assert events.local("who knows") == "who knows"
        assert events.local(None) == ""
        # Written before the system stored offsets: UTC is the only honest guess and
        # is what `now()` has always produced.
        assert events.local("2026-07-31T22:57:40") == events.local(
            "2026-07-31T22:57:40+00:00"
        )

    def test_the_log_is_append_only_jsonl(self, project):
        base(project)
        ops.add_note(project, "c", "one")
        first = project.events_path.read_text()
        ops.add_note(project, "c", "two")
        second = project.events_path.read_text()
        assert second.startswith(first)
        assert all(json.loads(line) for line in second.strip().splitlines())


def test_sweep_persists_and_is_then_a_no_op(project):
    base(project)
    _, rewritten = ops.sweep_only(project)
    assert set(rewritten) == {"t", "c"}
    _, again = ops.sweep_only(project)
    assert again == []
    assert read_node(project.nodes_dir / "t.md").global_status == PROVED
