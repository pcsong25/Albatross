"""The graph: containment, ordering, and integrity.

The graph is a **DAG, not a tree**. Edges come from ``children`` only. There is
deliberately no ``parent`` field on a node: a lemma may be cited by several
parents, and a stored parent list would be a second copy of the truth that
eventually disagrees with the first. Parents are computed.

Integrity is the cheapest and least negotiable layer of checking. If the graph
does not satisfy these conditions then nothing above them — propagation,
rendering, verification — means anything, so they run first and their failures
are errors.
"""

from __future__ import annotations

from typing import Iterable, Iterator

import networkx as nx

from .diagnostics import Diagnostic, err, warn
from .model import Node, cites


class GraphError(Exception):
    pass


class Graph:
    """An indexed collection of nodes with the children relation on top.

    Holds archived nodes too — nothing is destroyed, and archived nodes stay
    readable — but every structural operation works on the active subgraph.
    """

    def __init__(self, nodes: Iterable[Node]):
        self.nodes: dict[str, Node] = {}
        self.duplicates: list[tuple[str, Node]] = []
        for node in nodes:
            if node.id in self.nodes:
                self.duplicates.append((node.id, node))
                continue
            self.nodes[node.id] = node

    # --- container protocol --------------------------------------------------

    def __getitem__(self, node_id: str) -> Node:
        try:
            return self.nodes[node_id]
        except KeyError:
            raise KeyError(f"no node with id {node_id!r}") from None

    def get(self, node_id: str) -> Node | None:
        return self.nodes.get(node_id)

    def __contains__(self, node_id: object) -> bool:
        return node_id in self.nodes

    def __iter__(self) -> Iterator[Node]:
        return iter(self.nodes.values())

    def __len__(self) -> int:
        return len(self.nodes)

    # --- views ---------------------------------------------------------------

    @property
    def active(self) -> dict[str, Node]:
        return {i: n for i, n in self.nodes.items() if n.lifecycle == "active"}

    @property
    def target(self) -> Node | None:
        for node in self.active.values():
            if node.target:
                return node
        return None

    def active_children(self, node: Node) -> list[Node]:
        """Children that exist and are active. Dangling or archived children are
        skipped here and reported by :meth:`integrity`."""
        out = []
        for cid in node.children:
            child = self.nodes.get(cid)
            if child is not None and child.lifecycle == "active":
                out.append(child)
        return out

    def parents(self, node_id: str) -> list[str]:
        return sorted(
            n.id for n in self.active.values() if node_id in n.children
        )

    def digraph(self) -> nx.DiGraph:
        """Active subgraph, edges pointing parent → child."""
        g = nx.DiGraph()
        active = self.active
        g.add_nodes_from(active)
        for node in active.values():
            for cid in node.children:
                if cid in active:
                    g.add_edge(node.id, cid)
        return g

    # --- ordering ------------------------------------------------------------

    def topo_order(self) -> list[str]:
        """Parents before children. Raises :class:`GraphError` on a cycle."""
        g = self.digraph()
        try:
            return list(nx.topological_sort(g))
        except nx.NetworkXUnfeasible as exc:
            cycles = self.cycles()
            detail = "; ".join(" -> ".join(c + [c[0]]) for c in cycles) or str(exc)
            raise GraphError(f"children relation has a cycle: {detail}") from exc

    def reverse_topo_order(self) -> list[str]:
        """Children before parents — the order the propagation sweep needs, since
        a parent's status is a function of its children's."""
        return list(reversed(self.topo_order()))

    def cycles(self) -> list[list[str]]:
        return [list(c) for c in nx.simple_cycles(self.digraph())]

    def descendants(self, node_id: str) -> set[str]:
        g = self.digraph()
        if node_id not in g:
            return set()
        return set(nx.descendants(g, node_id))

    def ancestors(self, node_id: str) -> set[str]:
        g = self.digraph()
        if node_id not in g:
            return set()
        return set(nx.ancestors(g, node_id))

    # --- integrity -----------------------------------------------------------

    def integrity(self) -> list[Diagnostic]:
        """Structural conditions the rest of the system assumes.

        ``REF001``–``REF004`` and ``REF007`` are errors: the graph is not a graph
        without them. ``REF005``, ``REF006`` and ``REF008`` are warnings about
        shapes that are legal but almost always a mistake.
        """
        d: list[Diagnostic] = []
        active = self.active

        for node_id, node in self.duplicates:
            d.append(
                err(
                    "REF007",
                    node,
                    f"duplicate node id {node_id!r}; this file was ignored in favour of "
                    f"{self.nodes[node_id].path}",
                    hint="node ids are the system's stable keys — give one of them a new id",
                )
            )

        for node in active.values():
            for cid in node.children:
                if cid == node.id:
                    d.append(
                        err("REF002", node, "node lists itself as a child")
                    )
                    continue
                child = self.nodes.get(cid)
                if child is None:
                    d.append(
                        err(
                            "REF001",
                            node,
                            f"child {cid!r} does not exist",
                            hint="create the node, or remove it from `children`",
                        )
                    )
                elif child.lifecycle != "active":
                    d.append(
                        err(
                            "REF004",
                            node,
                            f"child {cid!r} is archived",
                            hint="un-archive it, or remove it from `children` and "
                            "re-state the step it was providing",
                        )
                    )

        for cycle in self.cycles():
            if len(cycle) == 1:
                continue  # already reported as REF002
            path = " -> ".join(cycle + [cycle[0]])
            d.append(
                err(
                    "REF003",
                    self.nodes.get(cycle[0]),
                    f"cycle in the children relation: {path}",
                    hint="one of these nodes cites an ancestor of itself; break the "
                    "loop by promoting the shared content to a new lemma",
                )
            )

        targets = [n for n in active.values() if n.target]
        if not targets:
            d.append(
                warn(
                    "REF008",
                    None,
                    "no node is marked `target: true`",
                    hint="mark the theorem you are trying to prove; `bp why` and the "
                    "render's support certificate are written about it",
                )
            )
        elif len(targets) > 1:
            d.append(
                warn(
                    "REF008",
                    None,
                    "several nodes are marked `target: true`: "
                    + ", ".join(sorted(n.id for n in targets)),
                )
            )

        cited: set[str] = set()
        for node in active.values():
            cited.update(c for c in node.children if c in active)
        for node in active.values():
            if node.id not in cited and not node.target:
                d.append(
                    warn(
                        "REF005",
                        node,
                        "nothing cites this node and it is not the target",
                        hint="cite it from a parent's `children`, or archive it",
                    )
                )

        for node in active.values():
            if node.local_status == "verified" and node.children:
                if not any(cites(node.proof_section, cid) for cid in node.children):
                    d.append(
                        warn(
                            "REF006",
                            node,
                            "marked verified and has children, but the proof mentions "
                            "none of them",
                            hint="either the proof does not actually use the "
                            "decomposition, or the citations are missing from the prose",
                        )
                    )
        return d


def build(nodes: Iterable[Node]) -> Graph:
    return Graph(nodes)
