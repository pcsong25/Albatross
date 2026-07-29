"""The frontier: nodes awaiting a decision, ranked.

The graph is for orientation. The daily working surface is a *list* — the nodes
where work is possible right now — because a graph of forty nodes does not tell
you which one to open next.

A node is on the frontier when it is unfinished **and everything beneath it is
finished**. That second half is what makes the list actionable: a theorem blocked
by three unproved lemmas is not a place to work, it is a place to wait. Its
lemmas are.

Ranking is shallow-first, then by how many nodes the item gates. Shallow first
because a decomposition near the target may reshape everything under it, and
work done deep inside a branch that later gets replaced is work thrown away.
Gating-many first because a lemma four nodes depend on buys more than one nothing
depends on yet.

This is derived-layer logic, not interface logic, which is why it lives here and
not in ``bp/ui``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .graph import Graph
from .model import Node
from .propagate import (
    BLOCKED_CHILDREN,
    BLOCKED_OBJECTION,
    BLOCKED_STALE,
    BLOCKED_UNVERIFIED,
    OPEN,
    PROVED,
    PROVED_MODULO,
    unfinished,
)

FINISHED = {PROVED, PROVED_MODULO}

#: What each kind of unfinished node is actually waiting for. This is the column
#: the user reads; "blocked:unverified" is a status, "needs verifying" is an
#: instruction.
NEEDS = {
    OPEN: "decompose it, or write a proof",
    BLOCKED_UNVERIFIED: "verify the proof",
    BLOCKED_STALE: "re-verify: the statement moved",
    BLOCKED_OBJECTION: "resolve the objection",
    BLOCKED_CHILDREN: "waiting on its lemmas",
}


@dataclass
class Item:
    node: str
    status: str
    needs: str
    difficulty: str
    depth: int
    gates: int
    #: True when the node has no proof and no children — the case where the
    #: decision is "how should this be broken up", not "is this argument right".
    unattempted: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "node": self.node,
            "status": self.status,
            "needs": self.needs,
            "difficulty": self.difficulty,
            "depth": self.depth,
            "gates": self.gates,
            "unattempted": self.unattempted,
        }


def depths(graph: Graph) -> dict[str, int]:
    """Distance from the target, by shortest path along the children relation."""
    out: dict[str, int] = {}
    target = graph.target
    if target is None:
        return out
    frontier = [(target.id, 0)]
    while frontier:
        current, d = frontier.pop(0)
        if current in out and out[current] <= d:
            continue
        out[current] = d
        node = graph.active.get(current)
        if node is None:
            continue
        frontier.extend((c, d + 1) for c in node.children if c in graph.active)
    return out


def is_frontier(graph: Graph, node: Node) -> bool:
    if not unfinished(node.global_status):
        return False
    return all(
        child.global_status in FINISHED for child in graph.active_children(node)
    )


def rank(graph: Graph) -> list[Item]:
    """Everything awaiting a decision, best first."""
    depth = depths(graph)
    items: list[Item] = []
    for node in graph.active.values():
        if not is_frontier(graph, node):
            continue
        items.append(
            Item(
                node=node.id,
                status=node.global_status or "?",
                needs=NEEDS.get(node.global_status or "", "look at it"),
                difficulty=node.difficulty,
                depth=depth.get(node.id, 10**6),
                gates=len(graph.ancestors(node.id)),
                unattempted=not node.has_proof and not node.children,
            )
        )
    items.sort(key=lambda i: (i.depth, -i.gates, i.node))
    return items


def summarise(items: list[Item]) -> str:
    if not items:
        return "the frontier is empty: nothing is waiting on a decision"
    lines = [f"{len(items)} node(s) awaiting a decision:", ""]
    for item in items:
        lines.append(
            f"  {item.node:<34} {item.difficulty:<9} gates {item.gates:<3} {item.needs}"
        )
    return "\n".join(lines)
