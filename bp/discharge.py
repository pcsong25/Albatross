"""The discharge check and obligation emission — the most valuable check in v0.

When a proof invokes a child lemma, that lemma has hypotheses, and they have to
hold at the point of invocation. This module checks that a **source is named**
for each one. It does *not* check that the named source entails the hypothesis.

Say that plainly, because a user who believes otherwise will over-trust green
nodes: the check catches **omission**, not **misattribution**. An agent can write
``H2: "hypothesis:H1"`` when ``H1`` does not in fact give ``H2``; the check
passes and the claim is false. Omission is the common failure and the invisible
one, so catching it deterministically is worth a great deal. Misattribution is
handed to the verifier as a narrow, explicit, per-obligation question — see
:func:`obligations` — which is a far better position than having it buried in
prose where nobody enumerates it at all.

The second thing this module does is turn the ``uses`` table into an obligation
list. That list is generated deterministically, so nothing is skipped because a
model failed to notice it needed checking.
"""

from __future__ import annotations

import re
from typing import Any

from .diagnostics import Diagnostic, err, info, warn
from .hash import canonical_statement, content_hash
from .model import Node

#: The recognised discharge source forms. ``DOTALL`` so that a ``proof:`` source
#: may span lines — a hypothesis established inline in the prose sometimes needs
#: a sentence, and forcing it onto one line would push authors toward omitting it.
SOURCE_RE = re.compile(
    r"^(hypothesis|child|proof|literature|ADMITTED)(:(.*))?$", re.DOTALL
)

SOURCE_FORMS = (
    "hypothesis:<id> | child:<id> | proof:<free text> | "
    "literature:<ref> | ADMITTED: <reason>"
)


def check_discharge(node: Node, graph) -> list[Diagnostic]:
    """``DIS010``–``DIS017`` for one node."""
    d: list[Diagnostic] = []
    own_hyps = node.hypothesis_ids

    for cid in node.children:
        entry = node.uses.get(cid)
        if entry is None:
            d.append(
                err(
                    "DIS010",
                    node,
                    f"child {cid} is cited but has no `uses` entry",
                    hint=f"add uses.{cid}.discharges naming a source for each of its "
                    "hypotheses",
                )
            )
            continue

        child = graph.get(cid)
        if child is None:
            # Dangling child: REF001 already said so. Nothing to check against.
            continue

        for h in child.hypotheses:
            src = entry.discharges.get(h.id)
            if not src or not src.strip():
                d.append(
                    err(
                        "DIS011",
                        node,
                        f"{cid} hypothesis {h.id} ({h.tex}) is not discharged",
                        hint="name where this hypothesis comes from, or mark it ADMITTED",
                    )
                )
                continue

            m = SOURCE_RE.match(src.strip())
            if not m:
                d.append(
                    err(
                        "DIS012",
                        node,
                        f"{cid}.{h.id}: source {src!r} is not a recognised form",
                        hint=f"use {SOURCE_FORMS}",
                    )
                )
                continue

            kind, _, arg = m.groups()
            arg = (arg or "").strip()
            if kind == "hypothesis" and arg not in own_hyps:
                if not arg:
                    d.append(
                        err(
                            "DIS013",
                            node,
                            f"{cid}.{h.id}: `hypothesis` source names no hypothesis",
                            hint="write hypothesis:<id> of "
                            + (", ".join(sorted(own_hyps)) or "— this node has none"),
                        )
                    )
                else:
                    d.append(
                        err(
                            "DIS013",
                            node,
                            f"{cid}.{h.id}: {node.id} has no hypothesis {arg!r}",
                            hint="its hypotheses are "
                            + (", ".join(sorted(own_hyps)) or "— it has none"),
                        )
                    )
            elif kind == "child" and arg not in node.children:
                d.append(
                    err(
                        "DIS014",
                        node,
                        f"{cid}.{h.id}: {arg!r} is not a declared child of {node.id}",
                        hint="add it to `children`, or discharge from something in scope",
                    )
                )
            elif kind == "ADMITTED" and not arg:
                d.append(
                    err(
                        "DIS015",
                        node,
                        f"{cid}.{h.id}: ADMITTED needs a reason",
                        hint="ADMITTED: <what is missing and why you are proceeding "
                        "anyway> — this text is what the support certificate prints",
                    )
                )
            elif kind == "ADMITTED":
                d.append(
                    info(
                        "DIS100",
                        node,
                        f"{cid}.{h.id} is admitted: {arg}",
                        hint="visible debt: this node enters its own support set",
                    )
                )

        child_hyps = {h.id for h in child.hypotheses}
        for hid in entry.discharges:
            if hid not in child_hyps:
                d.append(
                    warn(
                        "DIS017",
                        node,
                        f"uses.{cid}.discharges names {hid!r}, which is not a "
                        f"hypothesis of {cid}",
                        hint="its hypotheses are "
                        + (", ".join(sorted(child_hyps)) or "— it has none")
                        + "; a typo here hides a real undischarged hypothesis",
                    )
                )

    for cid in node.uses:
        if cid not in node.children:
            d.append(
                warn(
                    "DIS016",
                    node,
                    f"`uses` mentions {cid}, which is not a child",
                    hint="add it to `children`, or delete the stale `uses` entry",
                )
            )
    return d


def check_all(graph) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    for node in graph.active.values():
        out.extend(check_discharge(node, graph))
    return out


# --- obligation emission -----------------------------------------------------


def _source_text(node: Node, kind: str, arg: str, graph) -> str:
    """What the claimed source actually says, so the verifier can be asked a
    self-contained question rather than being sent to look it up."""
    if kind == "hypothesis":
        h = node.hypothesis(arg)
        return h.tex if h else ""
    if kind == "child":
        child = graph.get(arg)
        return child.statement_section.strip() if child else ""
    return arg


def obligation_hash(record: dict[str, Any]) -> str:
    """Content hash of a discharge obligation, over what it *asks*.

    Verifier results are cached on this, so the hash must move when the question
    changes and stay put when it does not — otherwise editing one paragraph of a
    proof re-bills every obligation in the node.
    """
    return content_hash(
        {
            "parent": record["parent"],
            "child": record["child"],
            "hypothesis": record["hypothesis"],
            "applied_to": canonical_statement(record["applied_to"]),
            "needed": canonical_statement(record["needed"]),
            "claimed_source": canonical_statement(record["claimed_source"]),
            "source_text": canonical_statement(record["source_text"]),
        }
    )


def obligations_for(node: Node, graph) -> list[dict[str, Any]]:
    """One record per discharge in this node's ``uses`` table.

    The verifier consumes these one at a time — *does this source give me this
    hypothesis, for this object?* — instead of judging a whole proof. Narrow
    questions are where model judgement is most reliable.
    """
    out: list[dict[str, Any]] = []
    for cid in node.children:
        entry = node.uses.get(cid)
        child = graph.get(cid)
        if entry is None or child is None:
            continue
        for h in child.hypotheses:
            src = (entry.discharges.get(h.id) or "").strip()
            if not src:
                continue
            m = SOURCE_RE.match(src)
            kind, _, arg = m.groups() if m else ("malformed", None, src)
            arg = (arg or "").strip()
            record: dict[str, Any] = {
                "id": f"ob:{node.id}:{cid}:{h.id}",
                "kind": "admitted" if kind == "ADMITTED" else "entailment",
                "parent": node.id,
                "child": cid,
                "hypothesis": h.id,
                "applied_to": entry.applied_to or "",
                "needed": h.tex,
                "claimed_source": src,
                "source_kind": kind,
                "source_text": _source_text(node, kind, arg, graph),
            }
            record["hash"] = obligation_hash(record)
            out.append(record)
    return out


def all_obligations(graph) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for node_id in sorted(graph.active):
        out.extend(obligations_for(graph[node_id], graph))
    return out
