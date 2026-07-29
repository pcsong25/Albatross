"""The four agent roles: decompose, check, verify, prove.

Each role is a thin function around one or more model calls. The pattern is the
same every time and is worth stating once:

1. **Assemble context deterministically.** :mod:`bp.roles.context` builds it from
   the graph — the node, its hypotheses, its notes, the chain of ancestors down
   from the target. No model decides what context a model gets.
2. **Ask for JSON against a pydantic schema.** :meth:`bp.agents.base.Backend.complete`
   validates, retries once, then fails. Never guesses.
3. **Run the deterministic checks on the result** before anything reaches the
   graph, and feed the diagnostics back for repair.
4. **Write through** :mod:`bp.ops`, so the event log and the sweep see it.

The prompts live in ``bp/roles/prompts/*.md`` and are the *system* prompts. They
are meant to be edited: the user is a mathematician, prompt wording is where
most of the quality lives, and they should never have to open a ``.py`` file to
change what an agent is told. The *user* message is assembled from the graph by
code, because that is data rather than instruction.
"""

from . import context

__all__ = ["context"]
