"""The verification record, and the derivation of ``local_status`` from it.

The derivation is the one place where "is this node green" is decided, so it gets
one test per way of being not-green plus one for the clean case. It is pure: no
project, no model, no I/O.

The last group is the one that matters most. ``ops.record_verification`` re-derives
the status from the record it is handed and refuses a verdict that disagrees —
that is what makes "no role may set ``local_status``" a property of the code rather
than a convention.
"""

from __future__ import annotations

import pytest

from bp import ops, verification
from bp.checks import load_graph
from bp.diagnostics import err, warn
from bp.model import VerificationRecord

from .conftest import write_node


def clean(**overrides) -> VerificationRecord:
    """A record that implies `verified`, so each test can spoil one thing."""
    data = {
        "level": verification.STANDARD,
        "deterministic": {
            "integrity": "pass",
            "children_used": "pass",
            "discharge": "pass",
            "ledger": "pass",
        },
        "ledger": {"claims": 4, "unsourced": 0, "checked": 4, "flagged": 0},
        "obligations": {"total": 3, "verified": 3, "flagged": 0, "cached": 1},
        "whole_proof": {"verifier_a": "no_objection", "verifier_b": "no_objection"},
        "statement_audit": "pass",
    }
    data.update(overrides)
    return VerificationRecord(**data)


class TestDerivation:
    def test_a_clean_record_implies_verified(self):
        assert verification.implied_status(clean()) == "verified"
        assert verification.reasons(clean()) == []

    def test_a_deterministic_error_flags_it(self):
        record = clean(deterministic={"integrity": "pass", "discharge": "fail"})
        assert verification.implied_status(record) == "flagged"
        assert "discharge check" in " ".join(verification.reasons(record))

    def test_an_unsourced_claim_flags_it(self):
        record = clean(ledger={"claims": 4, "unsourced": 1, "checked": 0})
        assert verification.implied_status(record) == "flagged"
        assert "no source" in " ".join(verification.reasons(record))

    def test_a_flagged_obligation_flags_it(self):
        record = clean(obligations={"total": 3, "verified": 2, "flagged": 1})
        assert verification.implied_status(record) == "flagged"

    def test_a_flagged_claim_flags_it(self):
        record = clean(ledger={"claims": 4, "unsourced": 0, "checked": 4, "flagged": 1})
        assert verification.implied_status(record) == "flagged"

    def test_a_confirmed_objection_flags_it(self):
        record = clean(
            whole_proof={"verifier_a": "objection_confirmed", "verifier_b": "no_objection"}
        )
        assert verification.implied_status(record) == "flagged"
        assert "upheld on confirmation" in " ".join(verification.reasons(record))

    def test_a_withdrawn_objection_does_not_flag_it(self):
        """An objection that dissolved on confirmation is not an objection. If it
        kept the node flagged, the confirmation pass would be pointless."""
        record = clean(
            whole_proof={"verifier_a": "objection_withdrawn", "verifier_b": "no_objection"}
        )
        assert verification.implied_status(record) == "verified"

    def test_silence_from_every_verifier_is_not_agreement(self):
        record = clean(
            whole_proof={"verifier_a": "did_not_answer", "verifier_b": "did_not_answer"}
        )
        assert verification.implied_status(record) == "flagged"
        assert "no verifier answered" in " ".join(verification.reasons(record))

    def test_no_whole_proof_pass_at_all_is_not_a_verification(self):
        record = clean(whole_proof={})
        assert verification.implied_status(record) == "flagged"
        assert "no whole-proof pass ran" in " ".join(verification.reasons(record))

    def test_one_member_answering_is_enough(self):
        record = clean(
            whole_proof={"verifier_a": "no_objection", "verifier_b": "did_not_answer"}
        )
        assert verification.implied_status(record) == "verified"

    def test_a_quick_record_can_be_verified_without_a_ledger(self):
        """`quick` never runs the extractor, so it reports `ledger: not_run` and no
        counts. That is a weaker claim than a `deep` verification, which is exactly
        why the level is on the record."""
        record = clean(
            level=verification.QUICK,
            deterministic={
                "integrity": "pass",
                "children_used": "pass",
                "discharge": "pass",
                "ledger": "not_run",
            },
            ledger={},
            obligations={},
            statement_audit="not_run",
        )
        assert verification.implied_status(record) == "verified"
        assert record.deterministic_failures == []


class TestDeterministicBlock:
    def test_errors_fail_and_warnings_do_not(self):
        """USE001 and LED005 are worth reading and are not grounds for calling a
        proof broken. A check that blocked on them would train the user to ignore
        the ones that matter."""
        block = verification.deterministic_block(
            {
                "integrity": [],
                "children_used": [warn("USE001", None, "unused child")],
                "discharge": [err("DIS011", None, "undischarged")],
                "ledger": [],
            }
        )
        assert block == {
            "integrity": "pass",
            "children_used": "pass",
            "discharge": "fail",
            "ledger": "pass",
        }

    def test_a_family_that_did_not_run_says_so(self):
        block = verification.deterministic_block(
            {"integrity": [], "ledger": []}, ran=["integrity"]
        )
        assert block == {"integrity": "pass", "ledger": "not_run"}


class TestCompact:
    def test_never_verified_says_so(self):
        assert verification.compact(None) == "never verified"

    def test_the_line_names_the_level_and_the_counts(self):
        text = verification.compact(clean())
        assert "level standard" in text
        assert "4 claim(s), 0 unsourced, 4 checked" in text
        assert "3/3 verified" in text
        assert "verifier_a=no_objection" in text
        assert "statement audit: pass" in text

    def test_a_partly_run_deterministic_block_is_reported_honestly(self):
        record = clean(
            deterministic={"integrity": "pass", "ledger": "not_run"}, ledger={}
        )
        assert "1 of 2 run" in verification.compact(record)


class TestTheWriter:
    def _node(self, project):
        write_node(project, "t", target=True, proof="An argument.", statement="A claim.")

    def test_the_record_is_written_to_the_node(self, project):
        self._node(project)
        ops.record_verification(project, "t", "verified", record=clean().model_dump())
        graph, _, _ = load_graph(project)
        node = graph["t"]
        assert node.local_status == "verified"
        assert node.verification is not None
        assert node.verification.level == "standard"
        assert node.verification.ledger["claims"] == 4

    def test_a_verdict_that_disagrees_with_its_record_is_refused(self, project):
        """This is what makes "no role may set local_status" structural. A role that
        could hand in `verified` alongside a record full of confirmed objections
        would be setting the status by the back door."""
        self._node(project)
        spoiled = clean(ledger={"claims": 4, "unsourced": 2, "checked": 0})
        with pytest.raises(ops.OpError) as exc:
            ops.record_verification(project, "t", "verified", record=spoiled.model_dump())
        assert "implies 'flagged'" in str(exc.value)
        assert load_graph(project)[0]["t"].local_status == "unverified"

    def test_a_flagged_verdict_needs_a_record_that_implies_flagged(self, project):
        self._node(project)
        with pytest.raises(ops.OpError):
            ops.record_verification(
                project, "t", "flagged", [{"why": "x"}], record=clean().model_dump()
            )

    def test_the_record_survives_a_round_trip(self, project):
        self._node(project)
        stamp = "2026-08-03T14:22:00+00:00"
        record = clean(
            checked_at=stamp, models={"extractor": "haiku-4.5", "verifier_a": "opus-5"}
        )
        ops.record_verification(project, "t", "verified", record=record.model_dump())
        graph, _, _ = load_graph(project)
        stored = graph["t"].verification
        assert stored.models == {"extractor": "haiku-4.5", "verifier_a": "opus-5"}
        # A timestamp read back as a datetime is the same class of bug as an
        # unquoted hex hash read back as a float, so it is written quoted.
        assert stored.checked_at == stamp
        assert isinstance(stored.checked_at, str)

    def test_verification_without_a_record_still_works(self, project):
        """L0 and the tests write verdicts with no record; those nodes report
        "never verified" in the record line rather than claiming a level."""
        self._node(project)
        ops.record_verification(project, "t", "verified")
        graph, _, _ = load_graph(project)
        assert graph["t"].local_status == "verified"
        assert graph["t"].verification is None


class TestReasonsDistinguishSilenceFromObjection:
    def test_a_panel_that_objected_did_answer(self):
        """Conflating "every verifier objected" with "no verifier answered" would
        tell the user a network outage was a mathematical finding, or the reverse."""
        record = clean(
            whole_proof={
                "verifier_a": "objection_confirmed",
                "verifier_b": "objection_confirmed",
            }
        )
        text = " ".join(verification.reasons(record))
        assert "upheld on confirmation" in text
        assert "no verifier answered" not in text

    def test_a_silent_panel_says_it_was_silent(self):
        record = clean(
            whole_proof={"verifier_a": "did_not_answer", "verifier_b": "did_not_answer"}
        )
        text = " ".join(verification.reasons(record))
        assert "no verifier answered" in text
        assert "upheld on confirmation" not in text
