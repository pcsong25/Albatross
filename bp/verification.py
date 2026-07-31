"""The verification record, and the derivation of ``local_status`` from it.

``local_status: verified`` must not be an opaque flag. A node checked at
``quick`` — deterministic checks and a whole-proof read — and one checked at
``deep`` — every discharge obligation, every ledger claim, a statement audit, and
a confirmation pass over every objection — are not making the same claim. One
colour for both would be dishonest in the direction that matters, because a user
who over-trusts a green node is the worst outcome this system can produce.

So each verification writes down what it actually ran, and this module *derives*
the status from that:

    verified  ⟺  no deterministic errors
                 ∧ no unsourced ledger claims
                 ∧ no flagged obligations
                 ∧ no flagged claims
                 ∧ no flagged or circular citations
                 ∧ no confirmed objections
                 ∧ at least one whole-proof verifier answered

Anything else is ``flagged``. The last conjunct is the one that is easy to forget
and expensive to get wrong: silence from every verifier is not agreement, and a
network outage must not read as a green graph.

Nothing here is a judgement. Every input is either a deterministic diagnostic or
a count of agent answers, which is the whole point — agents supply judgement, and
code supplies the guarantee that the judgement was complete.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from .diagnostics import Diagnostic
from .model import VerificationRecord

#: Recompile levels, cheapest first. See :mod:`bp.recompile` for what each runs.
QUICK = "quick"
STANDARD = "standard"
DEEP = "deep"
LEVELS = (QUICK, STANDARD, DEEP)

PASS = "pass"
FAIL = "fail"
NOT_RUN = "not_run"

NO_OBJECTION = "no_objection"
OBJECTION_CONFIRMED = "objection_confirmed"
OBJECTION_WITHDRAWN = "objection_withdrawn"
DID_NOT_ANSWER = "did_not_answer"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def deterministic_block(
    families: dict[str, list[Diagnostic]], ran: Iterable[str] | None = None
) -> dict[str, str]:
    """``{family: pass | fail | not_run}`` from grouped diagnostics.

    ``fail`` means *this family produced an error*. Warnings do not fail a node:
    ``USE001`` and ``LED005`` are worth reading and are not grounds for calling a
    proof broken, and a check that blocked on them would train the user to ignore
    the ones that matter.
    """
    ran_set = set(families) if ran is None else set(ran)
    out: dict[str, str] = {}
    for family, diagnostics in families.items():
        if family not in ran_set:
            out[family] = NOT_RUN
            continue
        out[family] = (
            FAIL if any(d.severity == "error" for d in diagnostics) else PASS
        )
    return out


def implied_status(record: VerificationRecord) -> str:
    """``verified`` or ``flagged``, derived from the record. The only rule.

    No role calls this on its own behalf and then writes the answer: the writer
    (:func:`bp.ops.record_verification`) re-derives it from the record it is
    handed and refuses a verdict that disagrees.
    """
    if record.deterministic_failures:
        return "flagged"
    if record.unsourced_claims:
        return "flagged"
    if record.flagged_obligations or record.flagged_claims:
        return "flagged"
    if record.flagged_references or record.circular_citations:
        return "flagged"
    if record.confirmed_objections:
        return "flagged"
    if not any(
        v in (NO_OBJECTION, OBJECTION_WITHDRAWN) for v in record.whole_proof.values()
    ):
        # Nobody read the proof — either no pass ran, or every member of the panel
        # failed. That is not a clean verification; it is the absence of one, and
        # recording it as `verified` would turn an outage into a green graph.
        return "flagged"
    return "verified"


def reasons(record: VerificationRecord) -> list[str]:
    """Why the record implies what it implies, in plain English.

    Shown by ``bp verify`` and by the browser, so that a ``flagged`` node says
    which of the five conditions failed rather than leaving the user to compare
    counts by eye.
    """
    out: list[str] = []
    for family in record.deterministic_failures:
        out.append(f"the {family.replace('_', ' ')} check reports an error")
    if record.unsourced_claims:
        n = record.unsourced_claims
        out.append(f"{n} load-bearing claim{'s' if n != 1 else ''} with no source")
    if record.flagged_obligations:
        n = record.flagged_obligations
        out.append(f"{n} discharge obligation{'s' if n != 1 else ''} flagged")
    if record.flagged_claims:
        n = record.flagged_claims
        out.append(f"{n} ledger claim{'s' if n != 1 else ''} flagged")
    if record.circular_citations:
        n = record.circular_citations
        out.append(
            f"{n} circular citation{'s' if n != 1 else ''} — a statement above this "
            "node in the graph is being used as a fact, so each rests on the other "
            "and neither is established"
        )
    plain = record.flagged_references - record.circular_citations
    if plain > 0:
        out.append(
            f"{plain} citation{'s' if plain != 1 else ''} flagged — the cited text "
            "does not give what the citing passage uses it for"
        )
    if record.confirmed_objections:
        n = record.confirmed_objections
        out.append(f"{n} objection{'s' if n != 1 else ''} upheld on confirmation")
    if not record.whole_proof:
        out.append("no whole-proof pass ran")
    elif all(v == DID_NOT_ANSWER for v in record.whole_proof.values()):
        # Distinct from "every verifier objected", which is already reported above.
        # Conflating them would tell the user a network outage was a mathematical
        # finding, or the reverse.
        out.append("no verifier answered on the whole proof")
    return out


def build(
    *,
    level: str,
    families: dict[str, list[Diagnostic]],
    families_ran: Iterable[str] | None = None,
    ledger: dict[str, int] | None = None,
    obligations: dict[str, int] | None = None,
    references: dict[str, int] | None = None,
    whole_proof: dict[str, str] | None = None,
    statement_audit: str = NOT_RUN,
    models: dict[str, str] | None = None,
    checked_at: str | None = None,
) -> VerificationRecord:
    """Assemble a record. Every caller of this is in :mod:`bp.roles.verify`."""
    return VerificationRecord(
        checked_at=checked_at or now(),
        level=level,
        deterministic=deterministic_block(families, families_ran),
        ledger=dict(ledger or {}),
        obligations=dict(obligations or {}),
        references=dict(references or {}),
        whole_proof=dict(whole_proof or {}),
        statement_audit=statement_audit,
        models=dict(models or {}),
    )


def compact(record: VerificationRecord | None) -> str:
    """One line naming the scrutiny a node received.

    Printed by ``bp show``, by the browser and — this is the point — into the
    rendered LaTeX, so that reading the document tells you how much checking each
    lemma actually got.
    """
    if record is None:
        return "never verified"
    bits = [f"level {record.level}"]
    det = record.deterministic
    if det:
        failed = record.deterministic_failures
        skipped = sorted(k for k, v in det.items() if v == NOT_RUN)
        if failed:
            bits.append("deterministic: " + ", ".join(failed) + " failing")
        elif skipped:
            bits.append(f"deterministic: {len(det) - len(skipped)} of {len(det)} run")
        else:
            bits.append("deterministic: all pass")
    if record.ledger:
        led = record.ledger
        bits.append(
            "ledger: {n} claim(s), {u} unsourced, {c} checked".format(
                n=led.get("claims", 0),
                u=led.get("unsourced", 0),
                c=led.get("checked", 0),
            )
        )
    if record.references:
        rf = record.references
        piece = "citations: {v}/{t} verified, {f} flagged".format(
            v=rf.get("verified", 0), t=rf.get("total", 0), f=rf.get("flagged", 0)
        )
        if rf.get("circular"):
            piece += f", {rf['circular']} circular"
        bits.append(piece)
    if record.obligations:
        ob = record.obligations
        bits.append(
            "obligations: {v}/{t} verified, {f} flagged, {c} cached".format(
                v=ob.get("verified", 0),
                t=ob.get("total", 0),
                f=ob.get("flagged", 0),
                c=ob.get("cached", 0),
            )
        )
    if record.whole_proof:
        bits.append(
            "whole proof: "
            + ", ".join(f"{k}={v}" for k, v in sorted(record.whole_proof.items()))
        )
    if record.statement_audit != NOT_RUN:
        bits.append(f"statement audit: {record.statement_audit}")
    if record.checked_at:
        # Local, like every other timestamp a person reads. Note this string also
        # goes into the rendered LaTeX, so the document says when *you* checked it.
        from .events import local

        bits.append(f"at {local(record.checked_at)}")
    return "; ".join(bits)


def as_dict(record: VerificationRecord | None) -> dict[str, Any] | None:
    return record.model_dump() if record is not None else None


__all__ = [
    "DEEP",
    "DID_NOT_ANSWER",
    "FAIL",
    "LEVELS",
    "NOT_RUN",
    "NO_OBJECTION",
    "OBJECTION_CONFIRMED",
    "OBJECTION_WITHDRAWN",
    "PASS",
    "QUICK",
    "STANDARD",
    "as_dict",
    "build",
    "compact",
    "deterministic_block",
    "implied_status",
    "now",
    "reasons",
]
