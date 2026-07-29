"""Albatross / Blueprint v0.

An interactive proof-decomposition assistant. This package is the deterministic
core: it loads a DAG of proof nodes from markdown files, checks its integrity,
derives every node's global status from the statuses its author actually wrote,
and renders the whole thing to LaTeX.

Four things in here are load-bearing and must not be worked around:

1. ``global_status`` is computed by :mod:`bp.propagate`, never written by hand
   and never written by an agent.
2. The LaTeX document is rendered from the node files by :mod:`bp.render`, never
   maintained by an agent.
3. Nothing is destroyed. ``.bp/events.jsonl`` is append-only; archiving replaces
   deletion.
4. Node ids are stable, statements are hashed, and ``local_status`` (an opinion)
   is a different field from ``global_status`` (a derivation).
"""

__version__ = "0.1.0"
