"""The six agent roles: decompose, check, extract, verify, audit, prove.

Every mathematical judgement in this system is made in one of these six modules,
and every one of them consumes a **deterministically generated worklist** and
returns a **structured verdict against it**. No role is ever asked an open question
like "is this proof correct":

* ``decompose`` proposes children, a reduction and a complete discharge table,
  which :mod:`bp.discharge` then checks for completeness before anything is written;
* ``check`` asks two fixed questions about a decomposition;
* ``extract`` translates a proof into an enumerated claim ledger, which
  :mod:`bp.ledger` audits;
* ``verify`` runs three separately-cached jobs over the lists that discharge and
  ledger emit, then a confirmation pass;
* ``audit`` asks four fixed questions about a statement;
* ``prove`` writes a proof for an easy leaf and never sets a status.

That is the whole design in one sentence: **agents supply judgement, code supplies
the guarantee that the judgement was complete.** Whether a claim is true cannot be
checked deterministically. That every claim was enumerated, assigned a source and
dispatched to a verifier can be, and is.

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
