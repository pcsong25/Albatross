"""The node model.

A node is one markdown file: YAML frontmatter describing the node's place in the
graph, then a LaTeX body split into ``## Statement``, ``## Proof`` and ``## Notes``.

The frontmatter has two halves, and the difference between them is the single
most important convention in the system:

*Authored fields* are opinions. A human or an agent writes them. ``local_status``
is one node's author saying "I have checked this and I believe it".

*Computed fields* are derivations. Only :func:`bp.propagate.sweep` and
:func:`bp.load.persist_computed` ever write them. ``global_status`` is the system
saying "given every opinion in the graph, here is what this node actually rests
on". :data:`COMPUTED_FIELDS` names them, and :mod:`bp.ops` refuses to touch them.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator

Role = Literal["lemma", "proposition", "theorem", "definition", "assumption"]
Difficulty = Literal["standard", "routine", "hard", "unknown"]
Lifecycle = Literal["active", "archived"]
LocalStatus = Literal["unverified", "verified", "flagged", "admitted", "assumption"]

#: Frontmatter keys that are derived, not authored. Never write these by hand and
#: never let an agent response write them; :mod:`bp.ops` raises if you try.
COMPUTED_FIELDS = frozenset(
    {"global_status", "support", "blocked_by", "statement_hash", "stale"}
)

#: Also computed, but by a *verification* rather than by the sweep. Written once
#: per verification by :func:`bp.ops.record_verification` and read thereafter.
#: Keeping them out of :data:`COMPUTED_FIELDS` lets the sweep leave them alone;
#: keeping them here documents that they are still not hand-edited fields — and
#: in particular that no role may set ``local_status``, which is *derived* from
#: ``verification`` by :mod:`bp.verification`.
VERIFICATION_FIELDS = frozenset(
    {"verified_against", "verification", "audited_against"}
)

#: The claim ledger. Produced by the extractor role, audited deterministically by
#: :mod:`bp.ledger`, and written only by :func:`bp.ops.record_ledger`. It is a
#: computed field for the same reason ``global_status`` is: a ledger any role
#: could edit would let the role that makes a claim also decide the claim is
#: sourced, and ``LED001`` would stop meaning anything.
EXTRACTED_FIELDS = frozenset({"claims", "claims_of"})

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]*$")

def cites(text: str, node_id: str) -> bool:
    """Does ``text`` cite ``node_id``?

    Proofs cite children by writing the id in the prose, so this is a text
    search — but a plain substring test would report that a node called ``a`` is
    cited by the word "never", and that ``gclm.elb-a`` is cited by a mention of
    ``gclm.elb-ab``. The lookarounds require the id to stand as a whole token
    while still allowing it to be followed by sentence punctuation.
    """
    pattern = (
        r"(?<![A-Za-z0-9_\-])(?<![A-Za-z0-9_\-]\.)"
        + re.escape(node_id)
        + r"(?![A-Za-z0-9_\-])(?!\.[A-Za-z0-9_\-])"
    )
    return re.search(pattern, text) is not None


#: The three body sections we understand. Anything else in the body is preserved
#: verbatim but is not fed to the checks or the renderer.
STATEMENT = "Statement"
PROOF = "Proof"
NOTES = "Notes"

_SECTION_RE = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.MULTILINE)


def split_sections(body: str) -> dict[str, str]:
    """Split a node body into ``{heading: text}`` on level-two headings.

    Headings are matched case-insensitively at lookup time (see
    :meth:`Node.section`), but stored with their authored capitalisation so a
    round-trip does not rewrite the user's file.
    """
    out: dict[str, str] = {}
    matches = list(_SECTION_RE.finditer(body))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        out[m.group(1).strip()] = body[m.end() : end].strip("\n")
    return out


#: The order sections are written in when one has to be created.
CANONICAL_SECTIONS = [STATEMENT, PROOF, NOTES]


def parse_body(body: str) -> tuple[str, list[tuple[str, str]]]:
    """Split a body into the text before the first heading and the sections."""
    matches = list(_SECTION_RE.finditer(body))
    if not matches:
        return body.strip("\n"), []
    preamble = body[: matches[0].start()].strip("\n")
    sections: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections.append((m.group(1).strip(), body[m.end() : end].strip("\n")))
    return preamble, sections


def render_body(preamble: str, sections: list[tuple[str, str]]) -> str:
    parts = [preamble.strip("\n")] if preamble.strip() else []
    for name, text in sections:
        parts.append(f"## {name}\n\n{text.strip(chr(10))}".rstrip())
    return "\n\n".join(parts).strip("\n") + "\n"


def set_section(body: str, name: str, text: str) -> str:
    """Replace one section's text, creating the section if it is absent.

    Sections that already exist keep their position; a new one is inserted at the
    place :data:`CANONICAL_SECTIONS` says it belongs, so a node that gains a proof
    does not end up with the proof after the notes.
    """
    preamble, sections = parse_body(body)
    want = name.strip().lower()
    for i, (heading, _) in enumerate(sections):
        if heading.strip().lower() == want:
            sections[i] = (heading, text)
            return render_body(preamble, sections)

    order = {s.lower(): i for i, s in enumerate(CANONICAL_SECTIONS)}
    new_rank = order.get(want, len(CANONICAL_SECTIONS))
    insert_at = len(sections)
    for i, (heading, _) in enumerate(sections):
        rank = order.get(heading.strip().lower(), len(CANONICAL_SECTIONS))
        if rank > new_rank:
            insert_at = i
            break
    sections.insert(insert_at, (name, text))
    return render_body(preamble, sections)


class Hypothesis(BaseModel):
    """One hypothesis of *this* node's statement, as cited by its parents."""

    model_config = ConfigDict(extra="forbid")

    id: str
    tex: str = ""

    @field_validator("id")
    @classmethod
    def _id_shape(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("hypothesis id must be non-empty")
        return v.strip()


class Use(BaseModel):
    """How a parent applies one child, and where each of the child's
    hypotheses is claimed to come from.

    ``discharges`` maps the *child's* hypothesis ids to a source string in one of
    the forms recognised by :data:`bp.discharge.SOURCE_RE`. ``applied_to`` is free
    text naming the object the child is applied to; it is never parsed.
    """

    model_config = ConfigDict(extra="forbid")

    applied_to: str = ""
    discharges: dict[str, str] = Field(default_factory=dict)


#: The source kinds a ledger claim may name. ``none`` is the honest answer for a
#: claim the prose does not justify, and it is the one the audit turns into a hard
#: error (``LED001``). An extractor that invents a plausible source instead of
#: writing ``none`` defeats the entire mechanism.
CLAIM_SOURCE_KINDS = (
    "hypothesis",
    "child",
    "claim",
    "literature",
    "computation",
    "none",
)

ClaimSourceKind = Literal[
    "hypothesis", "child", "claim", "literature", "computation", "none"
]


class ClaimSource(BaseModel):
    """Where a ledger claim says it comes from.

    ``ref`` names the thing: a hypothesis id, a child id, an earlier claim id, a
    bibliographic reference, or a path to a computation. It is empty exactly when
    ``kind`` is ``none``.
    """

    model_config = ConfigDict(extra="forbid")

    kind: ClaimSourceKind = "none"
    ref: str = ""


class Claim(BaseModel):
    """One load-bearing claim a proof makes, with the source the prose offers.

    The ``uses`` table covers the *children's* hypotheses. It says nothing about
    what the reduction asserts on its own account — "by standard elliptic
    regularity, $\\omega \\in C^1$, hence…" has no child, no hypothesis and no
    entry anywhere. The ledger is what makes those claims enumerable, and
    enumerable is what lets a verifier's "no objection" mean *all eleven claims
    were checked* rather than *nothing caught my eye*.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    text: str = ""
    source: ClaimSource = Field(default_factory=ClaimSource)

    @field_validator("id")
    @classmethod
    def _id_shape(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("claim id must be non-empty")
        return v.strip()

    @property
    def sourced(self) -> bool:
        return self.source.kind != "none"


class VerificationRecord(BaseModel):
    """What was actually checked, the last time this node was verified.

    ``local_status: verified`` must not be an opaque flag. A node verified at
    ``quick`` and one verified at ``deep`` are not making the same claim, and
    collapsing them to one colour would be dishonest — so the record says which
    checks ran, how many questions each enumerated, and which model answered
    them. :mod:`bp.verification` assembles it and derives ``local_status`` from
    it; nothing else may write either.

    ``extra="allow"`` on purpose: a later level or a new job should be readable
    by an older build rather than making the file refuse to load.
    """

    model_config = ConfigDict(extra="allow")

    checked_at: str | None = None
    level: str = "quick"
    #: check name -> ``pass`` | ``fail`` | ``not_run``
    deterministic: dict[str, str] = Field(default_factory=dict)
    #: ``{claims, unsourced, checked, flagged, cached}``. Empty when no ledger was
    #: available, which is the honest answer at ``quick`` — reporting
    #: ``unsourced: 0`` from a ledger nobody extracted would be a claim about
    #: claims nobody enumerated.
    ledger: dict[str, int] = Field(default_factory=dict)
    #: ``{total, verified, flagged, cached}``
    obligations: dict[str, int] = Field(default_factory=dict)
    #: ``{total, verified, flagged, circular, cached}`` over cross-node citations. A
    #: citation is as load-bearing as a hypothesis: the failure that motivated this
    #: block was a statement citing a section nobody had written. ``circular`` counts
    #: the worse case — a citation of an ancestor used as a *fact*, which is a loop
    #: with no bottom rather than merely a weak step.
    references: dict[str, int] = Field(default_factory=dict)
    #: panel role -> ``no_objection`` | ``objection_confirmed`` |
    #: ``objection_withdrawn`` | ``did_not_answer``
    whole_proof: dict[str, str] = Field(default_factory=dict)
    statement_audit: str = "not_run"
    #: job name -> the model that answered it, so the record names its own
    #: provenance rather than making the user guess from ``bp.yaml``.
    models: dict[str, str] = Field(default_factory=dict)

    @property
    def deterministic_failures(self) -> list[str]:
        return sorted(k for k, v in self.deterministic.items() if v == "fail")

    @property
    def unsourced_claims(self) -> int:
        return int(self.ledger.get("unsourced", 0))

    @property
    def flagged_obligations(self) -> int:
        return int(self.obligations.get("flagged", 0))

    @property
    def flagged_claims(self) -> int:
        return int(self.ledger.get("flagged", 0))

    @property
    def flagged_references(self) -> int:
        return int(self.references.get("flagged", 0))

    @property
    def circular_citations(self) -> int:
        return int(self.references.get("circular", 0))

    @property
    def confirmed_objections(self) -> int:
        return sum(1 for v in self.whole_proof.values() if v == "objection_confirmed")


class Flag(BaseModel):
    """An objection record. Written by the verifier in L1; carried, not
    interpreted, in L0 — except that a node whose ``local_status`` is ``flagged``
    is blocked by the sweep."""

    model_config = ConfigDict(extra="allow")

    kind: str | None = None
    section: str | None = None
    quote: str | None = None
    why: str | None = None
    raised_by: str | None = None
    at: str | None = None


class Node(BaseModel):
    """One proof node.

    Instances are validated projections of a file. They carry ``path`` and
    ``body`` so that everything downstream — checks, renderer, ops — works from
    the node rather than re-reading the file.
    """

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    # --- authored: graph shape and opinion -----------------------------------
    id: str
    role: Role = "lemma"
    target: bool = False
    children: list[str] = Field(default_factory=list)
    strategy: str | None = None
    difficulty: Difficulty = "unknown"
    lifecycle: Lifecycle = "active"
    local_status: LocalStatus = "unverified"
    #: Why this node is admitted or assumed. Required by ``bp admit`` and
    #: ``bp assume`` — an admission without a reason is debt nobody can act on,
    #: and this text is what the support certificate prints.
    status_reason: str | None = None
    flags: list[Flag] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    uses: dict[str, Use] = Field(default_factory=dict)

    # --- computed: never edit ------------------------------------------------
    global_status: str | None = None
    support: list[str] = Field(default_factory=list)
    blocked_by: list[str] = Field(default_factory=list)
    statement_hash: str | None = None
    verified_against: dict[str, str] = Field(default_factory=dict)
    #: The statement hash at the last statement audit, written by
    #: :func:`bp.ops.record_audit`. Its *absence* is the point: a statement nobody
    #: has examined is the hole this closes, and the target theorem was the node it
    #: mattered for most — nothing ever looked at it.
    audited_against: str | None = None
    #: The claim ledger, and the hash of the proof text it was extracted from.
    #: When they disagree the ledger describes an earlier proof, which is
    #: ``LED100``.
    claims: list[Claim] = Field(default_factory=list)
    claims_of: str | None = None
    verification: VerificationRecord | None = None
    stale: bool = False

    # --- file backing --------------------------------------------------------
    body: str = ""
    path: Path | None = Field(default=None, exclude=True)

    #: The frontmatter exactly as ``ruamel.yaml`` parsed it, comments and all.
    #: :mod:`bp.load` writes through this so hand-authored files survive a
    #: round-trip unchanged.
    _raw: Any = PrivateAttr(default=None)

    @field_validator("id")
    @classmethod
    def _id_shape(cls, v: str) -> str:
        if not ID_RE.match(v):
            raise ValueError(
                f"node id {v!r} must match {ID_RE.pattern} "
                "(letters, digits, dot, hyphen, underscore)"
            )
        return v

    @field_validator(
        "statement_hash", "verified_against", "claims_of", "audited_against",
        mode="before",
    )
    @classmethod
    def _hashes_are_strings(cls, v: Any) -> Any:
        """Keep hashes textual.

        A hex digest like ``896e63762324`` is a perfectly good YAML float, and an
        unquoted one silently becomes ``inf`` — a hash that compares equal to
        every other unquoted hash of that shape, which would make staleness
        detection quietly wrong. Integers round-trip exactly and are accepted;
        floats are refused with an explanation rather than coerced.
        """

        def one(x: Any) -> Any:
            if isinstance(x, bool) or x is None:
                return x
            if isinstance(x, int):
                return str(x)
            if isinstance(x, float):
                raise ValueError(
                    "hash values must be quoted in YAML — this one was read as the "
                    f"number {x!r} and its digits are gone"
                )
            return x

        if isinstance(v, dict):
            return {k: one(x) for k, x in v.items()}
        return one(v)

    @field_validator("children")
    @classmethod
    def _children_unique(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        for c in v:
            if c in seen:
                raise ValueError(f"child {c!r} listed twice")
            seen.add(c)
        return v

    # --- body access ---------------------------------------------------------

    @property
    def sections(self) -> dict[str, str]:
        return split_sections(self.body)

    def section(self, name: str) -> str:
        """Return a named section's text, matched case-insensitively, or ``""``."""
        want = name.strip().lower()
        for k, v in self.sections.items():
            if k.strip().lower() == want:
                return v
        return ""

    @property
    def statement_section(self) -> str:
        return self.section(STATEMENT)

    @property
    def proof_section(self) -> str:
        return self.section(PROOF)

    @property
    def notes_section(self) -> str:
        return self.section(NOTES)

    @property
    def has_proof(self) -> bool:
        """True when the Proof section contains anything but whitespace and
        LaTeX comments. This distinguishes ``open`` (no attempt yet) from
        ``blocked:unverified`` (an attempt exists, nobody has checked it)."""
        text = re.sub(r"%.*$", "", self.proof_section, flags=re.M)
        return bool(text.strip())

    @property
    def hypothesis_ids(self) -> set[str]:
        return {h.id for h in self.hypotheses}

    @property
    def admitted_discharges(self) -> list[tuple[str, str, str]]:
        """``(child_id, hypothesis_id, reason_text)`` for every ADMITTED source.

        An ADMITTED discharge is visible debt: it caps the node's effective
        local status at ``admitted`` during the sweep, which puts the node into
        its own support set.
        """
        out: list[tuple[str, str, str]] = []
        for cid, use in self.uses.items():
            for hid, src in use.discharges.items():
                if src.strip().startswith("ADMITTED"):
                    out.append((cid, hid, src.strip()[len("ADMITTED") :].lstrip(": ")))
        return out

    def hypothesis(self, hid: str) -> Hypothesis | None:
        for h in self.hypotheses:
            if h.id == hid:
                return h
        return None

    def claim(self, cid: str) -> "Claim | None":
        for c in self.claims:
            if c.id == cid:
                return c
        return None

    @property
    def claim_ids(self) -> set[str]:
        return {c.id for c in self.claims}

    @property
    def unsourced_claims(self) -> list["Claim"]:
        return [c for c in self.claims if not c.sourced]

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Node {self.id} {self.local_status}/{self.global_status}>"


def authored_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Strip computed keys out of a frontmatter dict."""
    return {k: v for k, v in data.items() if k not in COMPUTED_FIELDS}


def known_frontmatter_keys() -> set[str]:
    """Every frontmatter key the system understands.

    Node files are hand-edited, so a misspelled key — ``childern:`` — would
    otherwise be accepted in silence and a whole decomposition would vanish from
    the graph. ``SCH002`` reports anything not in here.
    """
    return set(Node.model_fields) - {"body", "path"}
