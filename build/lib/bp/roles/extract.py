"""The extractor: turn a proof into a claim ledger.

This is the cheapest role in the system and the only one whose output is a
*computed* field. Both facts follow from the same observation: listing what a
proof asserts, and what the prose says each assertion rests on, is translation
rather than mathematics. A cheap model does it reliably, and because the answer is
mechanical, no other role is allowed to touch it — a ledger that the verifier
could edit would let the model being audited decide what it is audited on.

The value is not in the extraction. It is in what :mod:`bp.ledger` can then say
deterministically: that ``LED001`` fires on every claim the prose does not source,
and that a verifier's "no objection" covers an enumerated list rather than
whatever happened to catch its eye.

The one failure mode worth engineering against is a model that invents a source to
look helpful, since that converts a visible gap into an invisible one. The prompt
says so at length; here, the only structural defence is that ``none`` is the
schema default, so an omitted source is unsourced rather than absent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .. import ops
from ..agents.base import CallMeta
from ..agents.registry import Registry
from ..checks import load_graph
from ..diagnostics import Diagnostic
from ..hash import proof_hash
from ..ledger import check_ledger
from ..model import CLAIM_SOURCE_KINDS
from ..paths import Project
from . import context


class SourceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(
        default="none",
        description="hypothesis | child | claim | literature | computation | none. "
        "`none` is correct and expected for a claim the prose does not justify.",
    )
    ref: str = Field(
        default="",
        description="the hypothesis id, child node id, earlier claim id, reference or "
        "artifact path. Empty when kind is `none`.",
    )

    @model_validator(mode="after")
    def _known_kind(self) -> "SourceSpec":
        if self.kind not in CLAIM_SOURCE_KINDS:
            raise ValueError(
                f"source kind {self.kind!r} is not one of "
                + ", ".join(CLAIM_SOURCE_KINDS)
            )
        return self


class ClaimSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="c1, c2, … in the order the proof makes them")
    text: str = Field(description="the claim as LaTeX, one line, precise enough to check")
    source: SourceSpec = Field(default_factory=SourceSpec)


class Ledger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims: list[ClaimSpec] = Field(default_factory=list)
    #: What the model deliberately left out, so a suspiciously short ledger is
    #: legible rather than mysterious.
    omitted: str = Field(
        default="",
        description="anything you judged not load-bearing and left out, if it might "
        "look like an omission",
    )

    @model_validator(mode="after")
    def _ids_unique(self) -> "Ledger":
        seen: set[str] = set()
        for claim in self.claims:
            key = claim.id.strip()
            if not key:
                raise ValueError("every claim needs a non-empty id")
            if key in seen:
                raise ValueError(f"claim id {key!r} is used twice")
            seen.add(key)
        return self


@dataclass
class ExtractResult:
    node: str
    ledger: Ledger | None = None
    written: bool = False
    diagnostics: list[Diagnostic] = field(default_factory=list)
    calls: list[CallMeta] = field(default_factory=list)

    @property
    def claims(self) -> int:
        return len(self.ledger.claims) if self.ledger else 0

    @property
    def unsourced(self) -> list[str]:
        if self.ledger is None:
            return []
        return [c.id for c in self.ledger.claims if c.source.kind == "none"]

    @property
    def clean(self) -> bool:
        return not any(d.severity == "error" for d in self.diagnostics)


def extract(
    project: Project,
    node_id: str,
    *,
    registry: Registry | None = None,
    apply: bool = True,
) -> ExtractResult:
    """Extract the ledger for one node and record it.

    Returns the ledger together with the diagnostics :mod:`bp.ledger` reports
    against it, because those diagnostics — not the ledger — are what the user
    acts on.
    """
    registry = registry or Registry(project)
    graph, _, swept = load_graph(project)
    if not swept:
        raise ops.OpError("the graph has a cycle; run `bp check` first")
    node = graph.get(node_id)
    if node is None:
        raise ops.OpError(f"no node {node_id!r}")
    if not node.has_proof:
        raise ops.OpError(
            f"{node_id} has no proof, so there are no claims to extract. A node with "
            "no proof is `open`, which the sweep already reports."
        )

    agent = registry.agent("extractor")
    user = context.join(
        context.preamble_block(project),
        context.node_block(node, heading="The claim and its proof"),
        context.children_block(graph, node)
        or "## The lemmas this proof cites\n\nNone — this is a leaf.",
        _id_block(node),
    )
    ledger, meta = agent.complete(
        context.load_prompt("extract"),
        user,
        Ledger,
        registry.config.role("extractor").timeout,
    )
    result = ExtractResult(node=node_id, ledger=ledger, calls=[meta])

    if not apply:
        return result

    ops.record_ledger(
        project,
        node_id,
        [
            {
                "id": c.id.strip(),
                "text": c.text,
                "source": {"kind": c.source.kind, "ref": c.source.ref.strip()},
            }
            for c in ledger.claims
        ],
        proof_hash(node),
        actor="extractor",
    )
    result.written = True

    fresh, _, _ = load_graph(project)
    result.diagnostics = check_ledger(fresh[node_id])
    if ledger.omitted.strip():
        ops.add_note(
            project,
            node_id,
            f"Extractor left out of the ledger: {ledger.omitted.strip()}",
            actor="extractor",
        )
    return result


def _id_block(node) -> str:
    """The ids a source may legally name.

    Given to the model because a source naming something that does not exist is
    ``LED002``/``LED003``, and a repair round spent on a namespace the model was
    never shown is a round the system wasted rather than earned.
    """
    hyps = ", ".join(f"`{h.id}`" for h in node.hypotheses) or "— this node has none"
    kids = ", ".join(f"`{c}`" for c in node.children) or "— this proof cites none"
    return (
        "## The ids you may name\n\n"
        f"- `hypothesis` sources may name: {hyps}\n"
        f"- `child` sources may name: {kids}\n"
        "- `claim` sources may name any claim earlier in your own list\n"
    )


def summarise(result: ExtractResult) -> str:
    lines = [f"{result.node}: {result.claims} claim(s) extracted"]
    for claim in result.ledger.claims if result.ledger else []:
        src = claim.source
        where = "UNSOURCED" if src.kind == "none" else f"{src.kind}:{src.ref}"
        lines.append(f"  {claim.id}  [{where}]  {claim.text}")
    errors = [d for d in result.diagnostics if d.severity == "error"]
    warnings = [d for d in result.diagnostics if d.severity == "warn"]
    if errors:
        lines.append(f"  {len(errors)} error(s) from the ledger audit:")
        for d in errors:
            lines.append(f"    {d.code}: {d.message}")
    for d in warnings:
        lines.append(f"  {d.code}: {d.message}")
    if result.ledger and result.ledger.omitted.strip():
        lines.append(f"  deliberately omitted: {result.ledger.omitted.strip()}")
    return "\n".join(lines)


__all__ = ["ClaimSpec", "ExtractResult", "Ledger", "SourceSpec", "extract", "summarise"]
