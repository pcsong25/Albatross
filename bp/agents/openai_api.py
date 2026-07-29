"""OpenAI API backend, for the second verifier in the panel.

The verifier panel exists so that two models from *different families* read the
same proof with no shared context. That is the entire reason this backend is
here: if both verifiers are Anthropic models, the second one costs as much and
adds much less, because two models trained by the same lab miss the same things.

Uses the Chat Completions interface, which is the most stable surface across
SDK versions. Anything model-specific goes through ``options.extra`` in
``bp.yaml`` rather than being hardcoded here.
"""

from __future__ import annotations

import os
from typing import Any

from .base import AgentError, Backend, BackendUnavailable, Completion


class OpenAIAPIBackend(Backend):
    name = "openai_api"
    reports_cost = True

    def available(self) -> tuple[bool, str]:
        try:
            import openai  # noqa: F401
        except ImportError:  # pragma: no cover - the dependency is declared
            return False, "the `openai` package is not installed"
        if not os.environ.get("OPENAI_API_KEY"):
            return False, "OPENAI_API_KEY is not set"
        return True, ""

    def invoke(self, system: str, user: str, timeout: float) -> Completion:
        import openai

        client = openai.OpenAI(timeout=timeout)
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                **self.options.get("extra", {}),
            )
        except openai.AuthenticationError as exc:
            raise BackendUnavailable(f"OpenAI rejected the credentials: {exc}") from exc
        except openai.APIStatusError as exc:
            raise AgentError(f"openai {exc.status_code}: {exc}") from exc
        except openai.APIConnectionError as exc:
            raise AgentError(f"could not reach the OpenAI API: {exc}") from exc

        text = response.choices[0].message.content or ""
        usage = response.usage
        return Completion(
            text=text,
            cost_usd=self._price(usage),
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
        )

    def _price(self, usage: Any) -> float | None:
        price = self.pricing.get(self.model)
        if not price or usage is None:
            return None
        return (
            (getattr(usage, "prompt_tokens", 0) or 0) * price.get("input_usd_per_mtok", 0.0)
            + (getattr(usage, "completion_tokens", 0) or 0)
            * price.get("output_usd_per_mtok", 0.0)
        ) / 1_000_000
