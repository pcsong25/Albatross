"""Statement hashing and staleness.

The hash answers one question: *has the claim this node makes changed since the
last time somebody verified it?* It is taken over the raw Statement section with
LaTeX comments removed and whitespace collapsed — no normalization at all in v0.

That is deliberate. Raw-text hashing errs toward saying "changed" when nothing
substantive did, so renaming a variable forces re-verification you did not
strictly need. The opposite error — saying "unchanged" when the claim moved —
would let a verification certificate outlive the statement it certified, which is
exactly the failure the whole mechanism exists to prevent. Over-invalidation is
the safe direction. Normalization is the deferred upgrade (see ``UPGRADE.md``);
it replaces this function and nothing else.
"""

from __future__ import annotations

import hashlib
import re

from .model import Node

_COMMENT_RE = re.compile(r"%.*$", re.M)
_WS_RE = re.compile(r"\s+")

HASH_LENGTH = 12


def canonical_statement(text: str) -> str:
    s = _COMMENT_RE.sub("", text)
    return _WS_RE.sub(" ", s).strip()


def statement_hash(node: Node) -> str:
    """A short, stable digest of what this node claims."""
    return hashlib.sha256(canonical_statement(node.statement_section).encode()).hexdigest()[
        :HASH_LENGTH
    ]


def is_stale(node: Node, graph) -> bool:
    """True when the node's verification certificate no longer matches reality.

    ``verified_against`` records, at the moment verification succeeded, this
    node's own statement hash under the key ``self`` plus each child's hash under
    its id. If any of those moved, the verification was about a different claim
    than the one now written down.

    A node that has never been verified is not stale — it is merely unverified,
    which the sweep reports differently and which reads very differently to a
    user.
    """
    va = node.verified_against
    if not va:
        return False
    if va.get("self") != node.statement_hash:
        return True
    for c in node.children:
        child = graph.get(c)
        if child is None:
            # A dangling child is an integrity error reported elsewhere. Treat
            # the certificate as void rather than silently honouring it.
            return True
        if va.get(c) != child.statement_hash:
            return True
    return False


def certificate(node: Node, graph) -> dict[str, str]:
    """The ``verified_against`` map to write when a verification succeeds."""
    out = {"self": node.statement_hash or statement_hash(node)}
    for c in node.children:
        child = graph.get(c)
        if child is not None:
            out[c] = child.statement_hash or statement_hash(child)
    return out
