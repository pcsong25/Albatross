"""The LaTeX renderer.

The document is **generated from the node files, every time**. No agent and no
human maintains it. An agent-maintained document drifts from the graph, and since
the document is what the user actually reads, they would end up reading a
plausible fiction of their own proof. So: deterministic template, regenerated on
demand, no state of its own.

Two modes. The default marks everything that is not proved — a coloured tag above
each statement saying exactly what is wrong with it — and opens with a support
certificate. ``--clean`` strips all of that apparatus and emits the paper.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .model import ID_RE, Node
from .propagate import (
    BLOCKED_CHILDREN,
    BLOCKED_OBJECTION,
    BLOCKED_STALE,
    BLOCKED_UNVERIFIED,
    OPEN,
    PROVED,
    PROVED_MODULO,
    UNSOUND,
)
from .why import explain

TEMPLATE_DIR = Path(__file__).parent / "templates"

ROLE_ENV = {
    "lemma": "lemma",
    "proposition": "proposition",
    "theorem": "theorem",
    "definition": "definition",
    "assumption": "assumption",
}

#: status → (xcolor name, short label). Proved nodes get no mark at all; the
#: absence of apparatus is what "proved" looks like.
MARKS = {
    OPEN: ("Orange", "open"),
    BLOCKED_UNVERIFIED: ("Orange", "unverified"),
    BLOCKED_STALE: ("Orange", "stale"),
    BLOCKED_OBJECTION: ("BrickRed", "objection"),
    BLOCKED_CHILDREN: ("Orange", "blocked"),
    UNSOUND: ("BrickRed", "unsound"),
    PROVED_MODULO: ("MidnightBlue", "conditional"),
}

_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}

_BACKTICK_RE = re.compile(r"`([^`\n]+)`")


_BARE_PERCENT_RE = re.compile(r"(?<!\\)%")


def escape(text: str) -> str:
    """Escape a literal string for LaTeX. Used for **ids and status codes only**
    — never for anything a person wrote, which is LaTeX already."""
    return "".join(_ESCAPES.get(ch, ch) for ch in text)


def prose(text: str) -> str:
    """Pass authored prose through to LaTeX, defusing only stray comment marks.

    Everything a user or an agent writes in this system is LaTeX: statements,
    proofs, notes, admission reasons, hypothesis fragments. Escaping those would
    render ``$\\varepsilon_0$`` as literal backslash-v-a-r. The one thing worth
    fixing is an unescaped ``%``, which would silently swallow the rest of a
    line rather than failing loudly.
    """
    return _BARE_PERCENT_RE.sub(r"\\%", text)


def math(tex: str) -> str:
    """Wrap a math-mode fragment in dollars.

    Hypothesis ``tex`` and ``applied_to`` are fragments — ``s > 3/2``, not
    ``$s > 3/2$``. If the author already supplied dollars, leave them be rather
    than producing display math by accident.
    """
    tex = prose(tex.strip())
    if not tex:
        return ""
    return tex if "$" in tex else f"${tex}$"


def _link(node_id: str, known: set[str]) -> str:
    tt = f"\\texttt{{{escape(node_id)}}}"
    if node_id in known:
        return f"\\hyperref[node:{node_id}]{{{tt}}}"
    return tt


def resolve_refs(text: str, known: set[str]) -> str:
    """Turn `` `node.id` `` in a body into a cross-reference.

    Proofs cite children by id in the prose, and the brief's own examples write
    those ids in markdown backticks. Backticks in LaTeX render as quotation
    marks, which would be wrong and ugly, so they become hyperlinks to the
    cited node instead. Anything backticked that is not a node id is left as
    typewriter text.
    """

    def sub(m: re.Match[str]) -> str:
        inner = m.group(1).strip()
        if ID_RE.match(inner):
            return _link(inner, known)
        return f"\\texttt{{{escape(inner)}}}"

    return _BACKTICK_RE.sub(sub, text)


def _hypotheses_line(node: Node) -> str:
    if not node.hypotheses:
        return ""
    parts = [
        f"\\textup{{({escape(h.id)})}}~{math(h.tex)}".rstrip("~")
        for h in node.hypotheses
    ]
    return "; ".join(parts) + "."


def _admitted_note(node: Node) -> str:
    bits = []
    if node.status_reason:
        bits.append(prose(node.status_reason))
    for cid, hid, reason in node.admitted_discharges:
        bits.append(
            f"hypothesis {escape(hid)} of {_link(cid, set())} is admitted"
            + (f" ({prose(reason)})" if reason else "")
        )
    return "; ".join(bits)


def _mark_for(node: Node, graph) -> dict[str, str] | None:
    status = node.global_status or ""
    if status == PROVED:
        return None
    spec = MARKS.get(status)
    if spec is None:
        return None
    colour, label = spec
    known = set(graph.active)
    if status == PROVED_MODULO:
        note = _admitted_note(node)
        if node.local_status == "assumption":
            text = "taken as an assumption" + (f" --- {note}" if note else "")
        elif node.support == [node.id]:
            text = "admitted" + (f" --- {note}" if note else "")
        else:
            items = ", ".join(_link(s, known) for s in node.support)
            text = f"holds relative to {items}"
    elif status == BLOCKED_CHILDREN:
        items = ", ".join(_link(b, known) for b in node.blocked_by)
        text = f"the reduction is verified, but {items} " + (
            "is not finished" if len(node.blocked_by) == 1 else "are not finished"
        )
    elif status == BLOCKED_STALE:
        text = (
            "verified against an earlier version of this statement or of a lemma it "
            "uses; needs re-verifying"
        )
    elif status == BLOCKED_UNVERIFIED:
        text = "a proof is written but nobody has verified it"
    elif status == OPEN:
        text = "no proof yet"
    elif status == BLOCKED_OBJECTION:
        why = next((f.why for f in node.flags if f.why), "")
        text = "a verifier raised an objection" + (f" --- {prose(why)}" if why else "")
    else:
        text = escape(status)
    return {"colour": colour, "label": label, "text": text}


def _audit_line(node: Node, graph) -> str:
    if not node.uses:
        return ""
    known = set(graph.active)
    chunks = []
    for cid in node.children:
        use = node.uses.get(cid)
        if use is None:
            continue
        applied = f" applied to {math(use.applied_to)}" if use.applied_to else ""
        dis = ", ".join(
            f"{escape(hid)} $\\leftarrow$ {prose(src)}"
            for hid, src in sorted(use.discharges.items())
        )
        chunks.append(f"{_link(cid, known)}{applied}: {dis or 'nothing discharged'}")
    if not chunks:
        return ""
    return "Discharges. " + "; ".join(chunks) + "."


def _entry(node: Node, graph, clean: bool, audit: bool) -> dict[str, object]:
    known = set(graph.active)
    boxed = node.local_status in {"admitted", "assumption"}
    env = ROLE_ENV.get(node.role, "lemma")
    if boxed and env not in {"assumption", "definition"}:
        env = "assumption"
    statement = resolve_refs(node.statement_section.strip(), known)
    proof = resolve_refs(node.proof_section.strip(), known)
    entry: dict[str, object] = {
        "id": node.id,
        "env": env,
        "caption": f"\\texttt{{{escape(node.id)}}}",
        "statement": statement or "% no statement written yet",
        "hypotheses": _hypotheses_line(node),
        "proof": proof,
        "boxed": boxed,
        "mark": None if clean else _mark_for(node, graph),
        "audit": _audit_line(node, graph) if (audit and not clean) else "",
        "no_proof_note": None,
        # An admitted node's Proof section is a sketch of an argument nobody has
        # made. Setting it in a `proof` environment would end it with a QED box,
        # which is a lie in exactly the place the document must not tell one.
        "sketch": boxed,
    }
    if not proof and not boxed and not clean:
        entry["no_proof_note"] = {
            "colour": "Gray",
            "label": "no proof",
            "text": "this statement has no proof in the project",
        }
    return entry


def order_entries(graph) -> tuple[list[str], list[str]]:
    """Reading order: dependencies first, target last.

    A depth-first post-order from the target reads the way a paper does — every
    lemma appears before the argument that uses it. Nodes the target does not
    reach are not part of that argument, so they go to an appendix rather than
    being silently dropped.
    """
    active = graph.active
    target = graph.target
    order: list[str] = []
    seen: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in seen or node_id not in active:
            return
        seen.add(node_id)
        for cid in active[node_id].children:
            visit(cid)
        order.append(node_id)

    if target is not None:
        visit(target.id)
    else:
        for node_id in graph.reverse_topo_order():
            visit(node_id)

    rest = [n for n in graph.reverse_topo_order() if n not in seen]
    return order, rest


def certificate(graph) -> dict[str, object]:
    """The support certificate: what the theorem currently rests on."""
    target = graph.target
    known = set(graph.active)
    counts: dict[str, int] = {}
    for node in graph.active.values():
        counts[node.global_status or "?"] = counts.get(node.global_status or "?", 0) + 1
    counts_line = ", ".join(f"{v} {escape(k)}" for k, v in sorted(counts.items()))

    if target is None:
        return {
            "headline": "\\noindent No node is marked as the target, so there is no "
            "certificate to state.",
            "support_items": [],
            "why": [],
            "counts": f"Nodes: {counts_line}.",
        }

    items: list[str] = []
    why: list[str] = []
    status = target.global_status
    name = _link(target.id, known)
    if status == PROVED:
        headline = (
            f"\\noindent\\textbf{{{name} is proved.}} It rests on no admitted step, "
            "no assumption and no unfinished lemma."
        )
    elif status == PROVED_MODULO:
        n = len(target.support)
        headline = (
            f"\\noindent\\textbf{{{name} holds relative to the following "
            f"{n} item{'s' if n != 1 else ''}.}} "
            "Everything else in this document is proved outright."
        )
        for sid in target.support:
            node = graph.get(sid)
            reason = ""
            if node is not None:
                bits = []
                if node.status_reason:
                    bits.append(prose(node.status_reason))
                for cid, hid, text in node.admitted_discharges:
                    bits.append(
                        f"hypothesis {escape(hid)} of {_link(cid, known)} admitted"
                        + (f": {prose(text)}" if text else "")
                    )
                reason = "; ".join(bits)
            label = "assumption" if node and node.local_status == "assumption" else "admitted"
            items.append(f"{_link(sid, known)} --- {label}" + (f": {reason}" if reason else ""))
    else:
        exp = explain(graph, target.id)
        headline = (
            f"\\noindent\\textbf{{{name} is not proved yet.}} "
            + resolve_refs(exp.sentence, known)
        )
        why = _why_items(exp.children, known)

    return {
        "headline": headline,
        "support_items": items,
        "why": why,
        "counts": f"Nodes: {counts_line}.",
    }


def _why_items(children, known: set[str], depth: int = 0) -> str:
    """The ``bp why`` chain as a nested itemize.

    Nesting matters: a flat list of reasons loses which node is blocked by
    which, and that structure is the whole content of the answer.
    """
    if not children:
        return ""
    pad = "  " * depth
    out = [f"{pad}\\begin{{itemize}}\\itemsep2pt"]
    for child in children:
        out.append(f"{pad}  \\item {resolve_refs(child.sentence, known)}")
        nested = _why_items(child.children, known, depth + 1)
        if nested:
            out.append(nested)
    out.append(f"{pad}\\end{{itemize}}")
    return "\n".join(out)


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        block_start_string="((*",
        block_end_string="*))",
        variable_start_string="(((",
        variable_end_string=")))",
        comment_start_string="((=",
        comment_end_string="=))",
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )


def document(
    graph,
    clean: bool = False,
    audit: bool = False,
    title: str | None = None,
    today: str | None = None,
    preamble: str = "",
) -> str:
    main_ids, rest_ids = order_entries(graph)
    entries = [_entry(graph[i], graph, clean, audit) for i in main_ids]
    appendix = [_entry(graph[i], graph, clean, audit) for i in rest_ids]

    target = graph.target
    if title is None:
        if target is not None:
            title = f"Proof development for \\texttt{{{escape(target.id)}}}"
        else:
            title = "Proof development"

    template = _environment().get_template("document.tex.j2")
    return template.render(
        title=title,
        preamble=preamble.strip(),
        date=today or date.today().isoformat(),
        clean=clean,
        certificate=certificate(graph),
        entries=entries,
        appendix=appendix if not clean else [],
    )
