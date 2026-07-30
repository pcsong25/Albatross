"""The agent layer.

Every model call in the system goes through here. Nothing else in the codebase
may import an SDK or shell out to a model — that rule is what makes the call
log complete, the budget enforceable, and ``--replay`` able to reproduce a whole
session offline.

Two kinds of backend are supported deliberately: metered APIs, which report
tokens and cost, and subscription CLI tools, which report neither. Budget logic
therefore must not assume a price is available; it falls back to a call-count
cap. See :mod:`bp.agents.base`.

Which model plays which role is configuration, not code. ``bp.yaml`` maps role
names — ``decomposer``, ``checker``, ``verifier_a``, ``verifier_b``, ``prover``
— onto backends, so swapping a model is an edit to one file.
"""

from .base import Backend, CallMeta, Completion, AgentError, BudgetExceeded
from .registry import Registry, load_config

__all__ = [
    "AgentError",
    "Backend",
    "BudgetExceeded",
    "CallMeta",
    "Completion",
    "Registry",
    "load_config",
]
