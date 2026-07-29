"""Anthropic API backend.

Streams every call. The decomposer's replies routinely run to thousands of
tokens of LaTeX, and a non-streaming request with a large ``max_tokens`` risks
an HTTP timeout — the SDK will refuse one outright above roughly ten minutes of
estimated generation. Streaming costs nothing here because the result is
consumed as a whole anyway.

Two model-family details are worth knowing before editing this file. Adaptive
thinking (``thinking={"type": "adaptive"}``) is the only supported form on the
Claude 5 family; the old fixed ``budget_tokens`` is rejected outright, as are
``temperature``, ``top_p`` and ``top_k``. And a call can come back with
``stop_reason == "refusal"`` and *no content*, which is a successful HTTP
response — code that reads ``content[0]`` without checking would raise an
IndexError and blame the wrong thing.
"""

from __future__ import annotations

from typing import Any

from .base import AgentError, Backend, BackendUnavailable, Completion


class ClaudeAPIBackend(Backend):
    """Metered Anthropic API. Reports tokens, so its calls have a price."""

    name = "claude_api"
    reports_cost = True

    def available(self) -> tuple[bool, str]:
        try:
            import anthropic  # noqa: F401
        except ImportError:  # pragma: no cover - the dependency is declared
            return False, "the `anthropic` package is not installed"
        return True, ""

    def invoke(self, system: str, user: str, timeout: float) -> Completion:
        import anthropic

        try:
            client = anthropic.Anthropic(timeout=timeout)
        except Exception as exc:  # pragma: no cover - construction rarely fails
            raise BackendUnavailable(f"could not build an Anthropic client: {exc}") from exc

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": int(self.options.get("max_tokens", 32000)),
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        # Both of these are model-gated, so they are configuration rather than
        # constants: the Claude 5 family takes them, older models reject them.
        thinking = self.options.get("thinking", "adaptive")
        if thinking and thinking != "none":
            kwargs["thinking"] = {"type": str(thinking)}
        effort = self.options.get("effort", "high")
        if effort and effort != "none":
            kwargs["output_config"] = {"effort": str(effort)}

        try:
            with client.messages.stream(**kwargs) as stream:
                message = stream.get_final_message()
        except anthropic.AuthenticationError as exc:
            raise BackendUnavailable(
                "the Anthropic API rejected the credentials. Set ANTHROPIC_API_KEY, "
                "or run `ant auth login`, or point this role at a CLI backend in "
                f"bp.yaml ({exc})"
            ) from exc
        except anthropic.APIStatusError as exc:
            raise AgentError(f"anthropic {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise AgentError(f"could not reach the Anthropic API: {exc}") from exc

        if message.stop_reason == "refusal":
            category = getattr(getattr(message, "stop_details", None), "category", None)
            raise AgentError(
                "the model declined this request"
                + (f" (category: {category})" if category else "")
                + ". This is a policy decline, not a mathematical judgement."
            )

        text = "".join(
            block.text for block in message.content if getattr(block, "type", "") == "text"
        )
        usage = message.usage
        return Completion(
            text=text,
            cost_usd=self._price(usage),
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )

    def _price(self, usage: Any) -> float | None:
        price = self.pricing.get(self.model)
        if not price:
            return None
        # Cached reads are cheaper than this assumes. Nothing here caches yet,
        # and erring high is the right direction for a budget cap.
        billed_in = (getattr(usage, "input_tokens", 0) or 0) + (
            getattr(usage, "cache_creation_input_tokens", 0) or 0
        ) + (getattr(usage, "cache_read_input_tokens", 0) or 0)
        out = getattr(usage, "output_tokens", 0) or 0
        return (
            billed_in * price.get("input_usd_per_mtok", 0.0)
            + out * price.get("output_usd_per_mtok", 0.0)
        ) / 1_000_000
