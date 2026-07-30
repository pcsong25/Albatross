"""Deterministic context assembly.

What a model is told about a node is decided here, by code, not by another
model. That matters for two reasons: the same node produces the same context
every time, which is what makes the call log a usable cache; and when a role
misbehaves, the context is a thing you can read rather than infer.

Every role gets the same shape of context, so a prompt written for one reads
against the same material as the others.
"""

from __future__ import annotations

from pathlib import Path

from ..graph import Graph
from ..model import Node

PROMPT_DIR = Path(__file__).parent / "prompts"


def load_prompt(name: str) -> str:
    """Read a system prompt. These are meant to be edited by the user."""
    path = PROMPT_DIR / f"{name}.md"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise FileNotFoundError(f"missing prompt file {path}: {exc}") from exc


def _hyp_block(node: Node) -> str:
    if not node.hypotheses:
        return "(none)"
    return "\n".join(f"- {h.id}: {h.tex}" for h in node.hypotheses)


def preamble_block(project) -> str:
    """The project's LaTeX preamble, for the agents.

    Without it a statement written in the user's own macros is unreadable — a
    model shown ``\\ip{u}{v} \\in \\HH`` and nothing else is guessing. This is
    cheap context and it prevents a whole class of confident nonsense.
    """
    from .. import ops

    text = ops.read_preamble(project).strip()
    if not text:
        return ""
    return (
        "## The project's LaTeX preamble\n\n"
        "Every statement below is written against these definitions. Use the same "
        "macros when you write mathematics back.\n\n"
        f"```latex\n{text}\n```"
    )


def node_block(node: Node, *, heading: str = "Node", proof: bool = True) -> str:
    """One node, rendered for a prompt."""
    parts = [
        f"## {heading}: `{node.id}`",
        "",
        f"Role: {node.role}. Difficulty: {node.difficulty}. "
        f"Status: {node.local_status} (derived: {node.global_status}).",
        "",
        "### Hypotheses",
        "",
        _hyp_block(node),
        "",
        "### Statement",
        "",
        node.statement_section.strip() or "(not written)",
    ]
    if proof:
        parts += ["", "### Proof", "", node.proof_section.strip() or "(none written)"]
    if node.notes_section.strip():
        parts += ["", "### Notes", "", node.notes_section.strip()]
    if node.strategy:
        parts += ["", f"### Strategy hint\n\n{node.strategy}"]
    return "\n".join(parts)


def ancestry(graph: Graph, node_id: str) -> list[Node]:
    """The chain from the target down to this node, if there is one.

    A lemma read without the theorem it serves invites decompositions that are
    locally sensible and globally useless, so the setting is always supplied.
    """
    target = graph.target
    if target is None or target.id == node_id:
        return []
    path = _path_to(graph, target.id, node_id, set())
    if path is None:
        return []
    return [graph[i] for i in path[:-1]]


def _path_to(graph: Graph, start: str, goal: str, dead: set[str]) -> list[str] | None:
    """One path from ``start`` down to ``goal``, or None.

    ``dead`` memoises nodes already known not to reach the goal. The graph is
    acyclic, so a node cannot be on the stack and revisited beneath itself.
    """
    if start == goal:
        return [start]
    if start in dead:
        return None
    node = graph.active.get(start)
    if node is None:
        dead.add(start)
        return None
    for child in node.children:
        sub = _path_to(graph, child, goal, dead)
        if sub is not None:
            return [start] + sub
    dead.add(start)
    return None


def setting(graph: Graph, node: Node) -> str:
    """The theorem this node serves, and the chain of lemmas down to it."""
    chain = ancestry(graph, node.id)
    if not chain:
        return ""
    lines = ["## The setting", ""]
    for ancestor in chain:
        label = "Target theorem" if ancestor.target else "Then, via"
        lines.append(f"**{label} `{ancestor.id}`.** {_one_line(ancestor.statement_section)}")
        lines.append("")
    return "\n".join(lines).strip()


def siblings_available(graph: Graph, node: Node) -> str:
    """Statements this node's proof may legitimately cite.

    Only nodes that already exist and are not descendants of this one; citing a
    descendant would be circular and the integrity check would reject it.
    """
    forbidden = graph.descendants(node.id) | {node.id}
    usable = [
        n
        for n in graph.active.values()
        if n.id not in forbidden and node.id not in graph.descendants(n.id)
    ]
    if not usable:
        return ""
    lines = ["## Statements already in the project", "",
             "You may cite any of these instead of proposing a new lemma:", ""]
    for n in sorted(usable, key=lambda n: n.id)[:40]:
        lines.append(f"- `{n.id}` ({n.difficulty}, {n.global_status}): "
                     f"{_one_line(n.statement_section)}")
    return "\n".join(lines)


def children_block(graph: Graph, node: Node) -> str:
    if not node.children:
        return ""
    lines = ["## The lemmas this proof cites", ""]
    for cid in node.children:
        child = graph.get(cid)
        if child is None:
            lines.append(f"### `{cid}` — MISSING FROM THE PROJECT\n")
            continue
        lines.append(f"### `{cid}`")
        lines.append("")
        lines.append("Hypotheses:")
        lines.append(_hyp_block(child))
        lines.append("")
        lines.append("Statement:")
        lines.append("")
        lines.append(child.statement_section.strip() or "(not written)")
        lines.append("")
    return "\n".join(lines).strip()


def xref_block(graph: Graph, node: Node) -> str:
    """What this node's ``\\ref`` and ``\\eqref`` commands point at.

    A proof containing ``\\eqref{eq:coercivity}`` is not readable without being told
    what that is, and a model that is not told will invent something and then reason
    confidently from the invention. Where the reference points is a *deterministic*
    fact, so it is supplied rather than guessed — and a reference that points at
    nothing is named as a gap, which is exactly what ``XRF001`` says about it.
    """
    from .. import xref

    return xref.obligations_note(xref.build(graph), node.id)


def uses_block(node: Node) -> str:
    if not node.uses:
        return ""
    lines = ["## The discharge table as it stands", ""]
    for cid, use in node.uses.items():
        lines.append(f"- `{cid}` applied to {use.applied_to or '(unstated)'}:")
        for hid, src in sorted(use.discharges.items()):
            lines.append(f"    - {hid} ← {src}")
    return "\n".join(lines)


def diagnostics_block(diagnostics, heading: str = "Problems with your last attempt") -> str:
    if not diagnostics:
        return ""
    lines = [f"## {heading}", "",
             "These are from a deterministic checker, not a judgement call. "
             "Every one of them is a fact about the structure you returned.", ""]
    for d in diagnostics:
        lines.append(f"- **{d.code}** ({d.severity}): {d.message}")
        if d.hint:
            lines.append(f"  - {d.hint}")
    return "\n".join(lines)


def _one_line(text: str, limit: int = 400) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def join(*blocks: str) -> str:
    return "\n\n".join(b.strip() for b in blocks if b and b.strip())
