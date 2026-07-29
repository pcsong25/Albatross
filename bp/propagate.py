"""Status propagation — the one sweep that decides every colour in the system.

``local_status`` is an opinion about one node: an agent's or a human's claim to
have checked it. ``global_status`` is a derivation over the whole graph: what
this node actually rests on, given every opinion beneath it. Only this module
writes ``global_status``, ``support``, ``blocked_by`` and ``stale``.

That separation is the entire value proposition. If an agent could write global
status, the graph's colours would be opinions, and glancing at the picture would
tell you what the agents believe rather than where you are.

The sweep is one pass in reverse topological order — children before parents,
because a parent's status is a function of its children's — and it is followed by
assertions that would catch the sweep being wrong. Those assertions are the test
suite.
"""

from __future__ import annotations

from .hash import is_stale, statement_hash
from .model import Node

PROVED = "proved"
PROVED_MODULO = "proved_modulo"
OPEN = "open"
UNSOUND = "unsound"
BLOCKED_STALE = "blocked:stale"
BLOCKED_OBJECTION = "blocked:objection"
BLOCKED_UNVERIFIED = "blocked:unverified"
BLOCKED_CHILDREN = "blocked:children"

#: Everything the user might see. ``unsound`` cannot arise in v0 — nothing
#: refutes a node yet — but the branch that produces it is written, because
#: leaving a hole where refutation lands would be worse than an unused case.
GLOBAL_STATUSES = (
    PROVED,
    PROVED_MODULO,
    OPEN,
    UNSOUND,
    BLOCKED_STALE,
    BLOCKED_OBJECTION,
    BLOCKED_UNVERIFIED,
    BLOCKED_CHILDREN,
)

ARCHIVED = "archived"


class PropagationError(AssertionError):
    """A sweep produced a graph that violates its own invariants. This is a bug
    in this module, never a bug in the user's mathematics."""


def unfinished(status: str | None) -> bool:
    """True for statuses that mean 'there is still work here'."""
    return bool(status) and status.startswith(("open", "blocked"))


def effective_local(node: Node) -> str:
    """The node's local status after accounting for admitted discharges.

    A node whose author marked it ``verified`` but whose ``uses`` table admits a
    hypothesis has not verified everything it claims to. Rather than silently
    honouring the ``verified`` label or rewriting the author's field, the sweep
    treats it as ``admitted``: the node becomes ``proved_modulo`` and enters its
    own support set, so the debt shows up in the certificate instead of
    disappearing.
    """
    if node.local_status == "verified" and node.admitted_discharges:
        return "admitted"
    return node.local_status


def sweep(graph) -> None:
    """Recompute every derived field. Run after every mutation."""
    for node in graph:
        node.statement_hash = statement_hash(node)

    for node in graph.nodes.values():
        if node.lifecycle != "active":
            node.global_status = ARCHIVED
            node.support = []
            node.blocked_by = []
            node.stale = False

    for node_id in graph.reverse_topo_order():
        N = graph[node_id]
        N.blocked_by = []
        N.stale = is_stale(N, graph)
        local = effective_local(N)

        if N.stale:
            N.global_status = BLOCKED_STALE
            N.support = []
        elif local == "flagged":
            N.global_status = BLOCKED_OBJECTION
            N.support = []
        elif local == "admitted":
            N.global_status = PROVED_MODULO
            N.support = [N.id]
        elif local == "assumption":
            N.global_status = PROVED_MODULO
            N.support = [N.id]
        elif local == "unverified":
            N.global_status = BLOCKED_UNVERIFIED if N.has_proof else OPEN
            N.support = []
        elif local == "verified":
            kids = graph.active_children(N)
            if any(k.global_status == UNSOUND for k in kids):
                N.global_status = UNSOUND
                N.support = []
            elif any(unfinished(k.global_status) for k in kids):
                N.global_status = BLOCKED_CHILDREN
                N.support = []
                N.blocked_by = [k.id for k in kids if unfinished(k.global_status)]
            else:
                acc: set[str] = set()
                for k in kids:
                    acc.update(k.support)
                N.support = sorted(acc)
                N.global_status = PROVED if not N.support else PROVED_MODULO
        else:  # pragma: no cover - the Literal type makes this unreachable
            raise PropagationError(f"unknown local_status {N.local_status!r} on {N.id}")

    assert_invariants(graph)


def assert_invariants(graph) -> None:
    """The propagation test suite, run in production after every sweep.

    These are cheap, they are exactly the properties the colours promise, and a
    violation means the derived layer is lying — which is worse than crashing.
    """
    active = graph.active

    for node in active.values():
        if node.global_status == PROVED and node.support:
            raise PropagationError(
                f"{node.id} is {PROVED} but its support is {node.support}"
            )
        if node.stale and node.global_status == PROVED:
            raise PropagationError(f"{node.id} is stale but {PROVED}")
        if node.local_status == "flagged" and node.global_status == PROVED:
            raise PropagationError(f"{node.id} is flagged but {PROVED}")

    for node in active.values():
        if node.global_status != PROVED:
            continue
        for did in graph.descendants(node.id):
            desc = active[did]
            if desc.global_status not in (PROVED, PROVED_MODULO):
                raise PropagationError(
                    f"{node.id} is {PROVED} but its descendant {did} is "
                    f"{desc.global_status}"
                )

    for node in active.values():
        if effective_local(node) != "verified":
            continue
        if node.global_status not in (PROVED, PROVED_MODULO):
            continue
        need: set[str] = set()
        for kid in graph.active_children(node):
            need.update(kid.support)
        missing = need - set(node.support)
        if missing:
            raise PropagationError(
                f"{node.id} support {node.support} drops {sorted(missing)} "
                "carried by its children"
            )


def summary(graph) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in graph.active.values():
        counts[node.global_status or "?"] = counts.get(node.global_status or "?", 0) + 1
    return dict(sorted(counts.items()))
