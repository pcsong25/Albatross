"""The claim ledger: the deterministic audit, and claim-obligation emission.

:mod:`bp.discharge` covers the *children's* hypotheses. It says nothing about
what a reduction asserts on its own account. A proof that says "by standard
elliptic regularity, $\\omega \\in C^1$, hence…" has a load-bearing claim with no
child, no hypothesis and no entry anywhere. That is premise smuggling in its
purest form, and at research level it is the dominant failure mode. The ledger
closes it.

The division of labour is the same as everywhere else in this system. An agent —
the extractor, a cheap one, because this is *translation* and not judgement —
reads the proof and lists every load-bearing claim with the source the prose
offers. This module then answers, in code and without a model:

* is any claim unsourced (``LED001``);
* does every named source exist and point somewhere legal (``LED002``–``LED004``);
* is a ``literature`` or ``computation`` source actually identifiable
  (``LED005``–``LED006``).

Together with ``DIS011``, the effect is that **no load-bearing claim anywhere in
a proof can go unsourced without producing a hard error**. And because the list
is enumerated deterministically, a verifier's "no objection" can mean *all
eleven claims were checked* instead of *nothing caught my eye*.

What this module does **not** do is judge whether a named source actually
justifies its claim. That is one narrow question per claim, handed to the
verifier by :func:`claim_obligations_for`.
"""

from __future__ import annotations

import re
from typing import Any

from .diagnostics import Diagnostic, err, warn
from .hash import canonical_statement, content_hash, proof_hash
from .model import Claim, Node

#: A ``literature`` source has to name something a reader could go and find.
#: One word ("standard", "classical", "well-known") is the shape a model reaches
#: for when it wants to sound sourced without being sourced, so it is a warning
#: rather than a pass.
_VAGUE_LITERATURE = {
    "",
    "standard",
    "classical",
    "well-known",
    "well known",
    "known",
    "folklore",
    "textbook",
    "obvious",
    "standard theory",
    "the literature",
    "literature",
}

#: A ``computation`` source has to name an artifact — a file, a notebook, a
#: script — because the point of the label is that somebody can re-run it.
_ARTIFACT_RE = re.compile(r"[\w./-]+\.[A-Za-z0-9]{1,8}\b")


def ledger_is_stale(node: Node) -> bool:
    """Was this ledger extracted from a different proof than the one on file?"""
    if not node.claims and node.claims_of is None:
        return False
    return node.claims_of != proof_hash(node)


def check_ledger(node: Node) -> list[Diagnostic]:
    """``LED001``–``LED006``, plus ``LED100`` for a ledger that is out of date.

    A node with no ledger at all produces nothing. That is deliberate: at
    ``--level quick`` the extractor never runs, and a check that fired on every
    unextracted node would be noise on exactly the nodes the user has not asked
    about yet. What the ledger's absence costs is recorded honestly in the
    verification record instead, as ``ledger: not_run``.
    """
    d: list[Diagnostic] = []
    if not node.claims:
        if ledger_is_stale(node):
            d.append(_stale_diagnostic(node))
        return d

    own_hyps = node.hypothesis_ids
    seen: set[str] = set()

    for position, claim in enumerate(node.claims):
        if claim.id in seen:
            d.append(
                err(
                    "LED004",
                    node,
                    f"claim id {claim.id!r} is used twice",
                    hint="claim ids must be unique within a node; a duplicate makes "
                    "`claim:` sources ambiguous and hides one of the two claims",
                )
            )
        seen.add(claim.id)

        kind = claim.source.kind
        ref = claim.source.ref.strip()

        if kind == "none":
            d.append(
                err(
                    "LED001",
                    node,
                    f"claim {claim.id} is load-bearing and unsourced: {claim.text}",
                    hint="justify it from a hypothesis, a child, an earlier claim, the "
                    "literature or a computation — or decompose it out into its own "
                    "node. An unsourced claim is a premise the proof is smuggling in.",
                )
            )
        elif kind == "child" and ref not in node.children:
            d.append(
                err(
                    "LED002",
                    node,
                    f"claim {claim.id} cites {ref!r}, which is not a child of {node.id}",
                    hint="add it to `children` (and give it a `uses` row), or source the "
                    "claim from something in scope",
                )
            )
        elif kind == "hypothesis" and ref not in own_hyps:
            d.append(
                err(
                    "LED003",
                    node,
                    f"claim {claim.id} cites hypothesis {ref!r}, which {node.id} "
                    "does not have",
                    hint="its hypotheses are "
                    + (", ".join(sorted(own_hyps)) or "— it has none"),
                )
            )
        elif kind == "claim":
            earlier = {c.id for c in node.claims[:position]}
            if ref == claim.id:
                d.append(
                    err(
                        "LED004",
                        node,
                        f"claim {claim.id} cites itself",
                        hint="a claim cannot be its own justification",
                    )
                )
            elif ref not in earlier:
                later = ref in node.claim_ids
                d.append(
                    err(
                        "LED004",
                        node,
                        f"claim {claim.id} cites {ref!r}, which is "
                        + ("established later" if later else "not a claim of this node"),
                        hint="a claim may only rest on a claim that comes before it; "
                        "otherwise the ledger admits a cycle and proves nothing",
                    )
                )
        elif kind == "literature" and ref.strip().lower() in _VAGUE_LITERATURE:
            d.append(
                warn(
                    "LED005",
                    node,
                    f"claim {claim.id} cites the literature as {ref!r}, which names "
                    "nothing a reader could look up",
                    hint="give an author, a result name or a reference — "
                    "\"standard\" is how an unsourced claim looks when it wants to "
                    "pass as a sourced one",
                )
            )
        elif kind == "computation" and not _ARTIFACT_RE.search(ref):
            d.append(
                warn(
                    "LED006",
                    node,
                    f"claim {claim.id} rests on a computation with no artifact: {ref!r}",
                    hint="name the file, notebook or script, so the computation can be "
                    "re-run rather than believed",
                )
            )

    if ledger_is_stale(node):
        d.append(_stale_diagnostic(node))
    return d


def _stale_diagnostic(node: Node) -> Diagnostic:
    return warn(
        "LED100",
        node,
        "the claim ledger was extracted from an earlier version of this proof",
        hint="run `bp extract` again — until then LED001-LED006 are describing text "
        "that is no longer in the file",
    )


def check_all(graph) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    for node in graph.active.values():
        out.extend(check_ledger(node))
    return out


# --- obligation emission -----------------------------------------------------


def _source_text(node: Node, claim: Claim, graph) -> str:
    """What the claimed source actually says.

    The verifier is asked a self-contained question, so the source travels with
    the record rather than being something a model has to go and look up.
    """
    kind, ref = claim.source.kind, claim.source.ref.strip()
    if kind == "hypothesis":
        h = node.hypothesis(ref)
        return h.tex if h else ""
    if kind == "child":
        child = graph.get(ref)
        return child.statement_section.strip() if child else ""
    if kind == "claim":
        other = node.claim(ref)
        return other.text if other else ""
    return ref


def claim_hash(record: dict[str, Any]) -> str:
    return content_hash(
        {
            "parent": record["parent"],
            "claim": record["claim"],
            "needed": canonical_statement(record["needed"]),
            "claimed_source": canonical_statement(record["claimed_source"]),
            "source_text": canonical_statement(record["source_text"]),
        }
    )


def claim_obligations_for(node: Node, graph) -> list[dict[str, Any]]:
    """One record per sourced ledger claim, in the same shape as a discharge.

    Unsourced claims produce no record, because there is nothing to ask a model
    about: ``LED001`` has already said, deterministically, that the claim has no
    source. Sending it to a verifier would be asking for an opinion on a settled
    question.
    """
    out: list[dict[str, Any]] = []
    for claim in node.claims:
        if not claim.sourced:
            continue
        record: dict[str, Any] = {
            "id": f"ob:{node.id}:claim:{claim.id}",
            "kind": "claim",
            "parent": node.id,
            "claim": claim.id,
            "applied_to": "",
            "needed": claim.text,
            "claimed_source": f"{claim.source.kind}:{claim.source.ref}".rstrip(":"),
            "source_kind": claim.source.kind,
            "source_text": _source_text(node, claim, graph),
        }
        record["hash"] = claim_hash(record)
        out.append(record)
    return out


def all_claim_obligations(graph) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for node_id in sorted(graph.active):
        out.extend(claim_obligations_for(graph[node_id], graph))
    return out


def summarise(node: Node) -> dict[str, int]:
    """Counts for the verification record."""
    return {
        "claims": len(node.claims),
        "unsourced": len(node.unsourced_claims),
    }


__all__ = [
    "all_claim_obligations",
    "check_all",
    "check_ledger",
    "claim_hash",
    "claim_obligations_for",
    "ledger_is_stale",
    "summarise",
]
