"""A backend that returns canned responses.

It is registered like any other backend so that a test project's ``bp.yaml``
can point a role at it without the role code special-casing anything. Real runs
never reach it: it has to be named explicitly in configuration, and it is not
the default for any role.

Its purpose is to let the role logic — the decompose/repair loop, the checker's
two calls, the verifier's obligation pass and confirmation pass — be tested
against known model output, deterministically and for free. ``--replay`` covers
the same ground for *recorded* calls; this covers the ones that have not
happened yet, including the failure cases nobody wants to pay to reproduce.
"""

from __future__ import annotations

from .base import AgentError, Backend, Completion


class ScriptedBackend(Backend):
    name = "scripted"
    reports_cost = False

    def available(self) -> tuple[bool, str]:
        return True, ""

    def invoke(self, system: str, user: str, timeout: float) -> Completion:
        script = self.options.get("responses") or []
        index = int(self.options.get("_cursor", 0))
        if index >= len(script):
            raise AgentError(
                f"the scripted backend for role {self.role!r} ran out of responses "
                f"after {index}; the role asked for more calls than the test scripted"
            )
        self.options["_cursor"] = index + 1
        entry = script[index]
        if isinstance(entry, dict):
            return Completion(**entry)
        return Completion(text=str(entry), cost_usd=self.options.get("cost_usd"))
