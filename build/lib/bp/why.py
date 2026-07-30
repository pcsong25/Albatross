"""``bp why`` — the status explainer.

No model is involved, so it is always correct. That matters more than it sounds:
the graph's colours are only useful if the user trusts them, and trust comes from
being able to ask any node "why are you that colour?" and get an answer that is
plainly true rather than plausible.

The explanation walks ``blocked_by`` transitively and stops at the first honest
reason on each branch.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import Node
from .propagate import (
    ARCHIVED,
    BLOCKED_CHILDREN,
    BLOCKED_OBJECTION,
    BLOCKED_STALE,
    BLOCKED_UNVERIFIED,
    OPEN,
    PROVED,
    PROVED_MODULO,
    UNSOUND,
)


@dataclass
class Explanation:
    node: str
    status: str
    sentence: str
    children: list["Explanation"] = field(default_factory=list)
    repeated: bool = False


def _stale_reason(node: Node, graph) -> str:
    va = node.verified_against
    if va.get("self") != node.statement_hash:
        return (
            f"`{node.id}` was verified, but its own statement has been edited since; "
            "the verification was about a different claim"
        )
    moved = [
        c
        for c in node.children
        if graph.get(c) is None or va.get(c) != graph[c].statement_hash
    ]
    if moved:
        names = ", ".join(f"`{m}`" for m in moved)
        return (
            f"`{node.id}` was verified against an earlier version of {names}, whose "
            "statement has changed since"
        )

    # A cross-reference is a dependency too, so it is also something that can move
    # underneath a verification. Naming it matters: "it is stale" leaves the user
    # hunting, and the cause here is not a child but a `\ref` into another node.
    from .hash import XREF_PREFIX

    referenced = [
        key[len(XREF_PREFIX) :]
        for key, recorded in va.items()
        if key.startswith(XREF_PREFIX)
        and (
            graph.get(key[len(XREF_PREFIX) :]) is None
            or recorded != graph[key[len(XREF_PREFIX) :]].statement_hash
        )
    ]
    if referenced:
        names = ", ".join(f"`{m}`" for m in sorted(referenced))
        return (
            f"`{node.id}` cross-references {names} with `\\ref` or `\\eqref`, and that "
            "statement has changed since it was verified"
        )
    return f"`{node.id}` is stale"


def _support_line(item_id: str, graph) -> str:
    node = graph.get(item_id)
    if node is None:
        return f"`{item_id}` (missing)"
    reason = (node.status_reason or "").strip()
    if node.local_status == "assumption":
        label = "assumed"
    elif node.local_status == "admitted":
        label = "admitted"
    elif node.admitted_discharges:
        admitted = node.admitted_discharges[0]
        label = "admitted"
        reason = reason or f"{admitted[0]}.{admitted[1]}: {admitted[2]}"
    else:
        label = "carried"
    return f"`{item_id}` ({label}" + (f": {reason}" if reason else "") + ")"


def sentence(node: Node, graph) -> str:
    status = node.global_status
    if status == PROVED:
        return f"`{node.id}` is proved, and rests on nothing outstanding."
    if status == PROVED_MODULO:
        items = ", ".join(_support_line(s, graph) for s in node.support)
        n = len(node.support)
        return (
            f"`{node.id}` holds relative to {n} item{'s' if n != 1 else ''}: {items}."
        )
    if status == OPEN:
        return f"`{node.id}` has no proof yet."
    if status == BLOCKED_UNVERIFIED:
        return f"`{node.id}` has a proof, but nobody has verified it yet."
    if status == BLOCKED_STALE:
        return _stale_reason(node, graph) + ", so it needs re-verifying."
    if status == BLOCKED_OBJECTION:
        why = ""
        for flag in node.flags:
            if flag.why:
                why = f": {flag.why}"
                break
        return f"`{node.id}` is flagged by a verifier{why}."
    if status == BLOCKED_CHILDREN:
        n = len(node.blocked_by)
        return (
            f"`{node.id}` has a verified reduction, but {n} of the lemmas it uses "
            f"{'is' if n == 1 else 'are'} not finished:"
        )
    if status == UNSOUND:
        return f"`{node.id}` rests on something that has been refuted."
    if status == ARCHIVED:
        return f"`{node.id}` is archived and no longer part of the graph."
    return f"`{node.id}` has status {status}."


def explain(graph, node_id: str, _seen: set[str] | None = None) -> Explanation:
    node = graph.get(node_id)
    if node is None:
        return Explanation(node=node_id, status="missing", sentence=f"There is no node `{node_id}`.")
    seen = _seen if _seen is not None else set()
    if node_id in seen:
        return Explanation(
            node=node_id,
            status=node.global_status or "?",
            sentence=f"`{node_id}` — as above.",
            repeated=True,
        )
    seen.add(node_id)
    exp = Explanation(
        node=node_id, status=node.global_status or "?", sentence=sentence(node, graph)
    )
    if node.global_status == BLOCKED_CHILDREN:
        for cid in node.blocked_by:
            exp.children.append(explain(graph, cid, seen))
    return exp


def to_lines(exp: Explanation, depth: int = 0) -> list[str]:
    pad = "  " * depth
    lines = [f"{pad}{exp.sentence}"]
    for child in exp.children:
        lines.extend(to_lines(child, depth + 1))
    return lines


def text(graph, node_id: str) -> str:
    return "\n".join(to_lines(explain(graph, node_id)))
