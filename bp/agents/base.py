"""The agent protocol, and everything that is the same for every backend.

A backend implements exactly one thing: :meth:`Backend.invoke`, which turns a
system prompt and a user prompt into text. Everything above that — asking for
JSON, extracting it from whatever preamble the model wrapped it in, validating
it against a pydantic schema, retrying once with the validation error, logging
the call, charging it to the budget, and resolving it from the log instead of
the network under ``--replay`` — happens once, here, so that all four backends
behave identically and the call log has one format.

Two policies are worth stating explicitly because they are easy to get wrong:

*Never guess.* If the model's output does not validate, it is sent back once
with the error appended. If it fails again the task fails. Silently patching up
a malformed decomposition would put unchecked structure into the graph.

*Cost may be unknown.* Subscription CLI backends report no tokens and no price.
Budget logic must therefore never assume a number is available; the call-count
cap is the backstop that always works. See :class:`Budget`.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, ClassVar, Type, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError

T = TypeVar("T", bound=BaseModel)


class AgentError(Exception):
    """A model call that could not be turned into a validated result."""


class BackendUnavailable(AgentError):
    """The backend cannot run here: no API key, or the CLI is not installed."""


class ReplayMiss(AgentError):
    """``--replay`` was asked for a call that is not in the log.

    Loud on purpose. A replay run that silently fell back to the network would
    make an "offline, reproducible" test quietly cost money and quietly stop
    being reproducible.
    """


class BudgetExceeded(AgentError):
    """The run hit its dollar or call-count cap. Raised *before* the call."""


class Completion(BaseModel):
    """What a backend returns: text, plus whatever accounting it can offer."""

    model_config = ConfigDict(extra="forbid")

    text: str
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class CallMeta(BaseModel):
    """The record of one completed call, for the log and for reporting."""

    model_config = ConfigDict(extra="forbid")

    role: str
    backend: str
    model: str
    prompt_hash: str
    started_at: str
    wall_seconds: float
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    attempts: int = 1
    replayed: bool = False
    repaired_json: bool = False


class Budget:
    """A dollar cap and a call cap for one run.

    The dollar cap only constrains calls whose price is known. The call cap
    constrains everything, which is why it is the one that must always be set:
    with a subscription CLI backend it is the *only* thing standing between a
    repair loop and an afternoon of unattended work.
    """

    def __init__(self, max_usd: float | None = None, max_calls: int | None = None):
        self.max_usd = max_usd
        self.max_calls = max_calls
        self.spent_usd = 0.0
        self.calls = 0
        self.unpriced_calls = 0

    def check(self) -> None:
        if self.max_calls is not None and self.calls >= self.max_calls:
            raise BudgetExceeded(
                f"call cap reached: {self.calls} of {self.max_calls} calls used"
            )
        if self.max_usd is not None and self.spent_usd >= self.max_usd:
            raise BudgetExceeded(
                f"budget reached: ${self.spent_usd:.2f} of ${self.max_usd:.2f} spent"
            )

    def record(self, cost_usd: float | None) -> None:
        self.calls += 1
        if cost_usd is None:
            self.unpriced_calls += 1
        else:
            self.spent_usd += cost_usd

    @property
    def priced(self) -> bool:
        """False once any call has come back without a price, which is when the
        dollar figure stops being the whole story."""
        return self.unpriced_calls == 0

    def summary(self) -> str:
        money = f"${self.spent_usd:.2f}" if self.priced else f"${self.spent_usd:.2f}+"
        note = (
            ""
            if self.priced
            else f" ({self.unpriced_calls} call(s) on a subscription backend, price unknown)"
        )
        return f"{self.calls} call(s), {money}{note}"


# --- JSON extraction ---------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_VALID_ESCAPES = set('"\\/bfnrtu')


def extract_json(text: str) -> str:
    """Pull the JSON value out of a model response.

    CLI backends in particular wrap their answer in commentary, and even API
    backends sometimes preface it. Tried in order: a fenced block, the whole
    text, then the outermost balanced ``{...}`` or ``[...]``.
    """
    candidates: list[str] = []
    fences = _FENCE_RE.findall(text)
    candidates.extend(f.strip() for f in fences if f.strip())
    stripped = text.strip()
    if stripped:
        candidates.append(stripped)
    balanced = _outermost_balanced(text)
    if balanced:
        candidates.append(balanced)

    for candidate in candidates:
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            continue
    for candidate in candidates:
        try:
            json.loads(repair_backslashes(candidate))
            return candidate
        except json.JSONDecodeError:
            continue
    if candidates:
        return candidates[0]
    raise AgentError("the response contained nothing that looked like JSON")


def _outermost_balanced(text: str) -> str | None:
    starts = [i for i, ch in enumerate(text) if ch in "{["]
    if not starts:
        return None
    start = starts[0]
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def repair_backslashes(blob: str) -> str:
    """Escape backslashes that JSON would reject.

    Every string this system moves through a model is LaTeX, and a model asked
    for JSON containing ``\\omega`` very often emits it with a single backslash,
    which is not a legal JSON escape. Doubling those recovers the value.

    This is a repair of last resort, attempted only after a strict parse has
    failed, and the fact that it happened is recorded on the call. It is not
    perfect: ``\\nabla`` *is* a legal JSON escape (``\\n`` followed by "abla"),
    so a strict parse succeeds and silently produces a newline. That is why the
    schema instruction sent with every prompt asks for doubled backslashes —
    this function is the safety net, not the plan.
    """
    out: list[str] = []
    i = 0
    while i < len(blob):
        ch = blob[i]
        if ch == "\\":
            nxt = blob[i + 1] if i + 1 < len(blob) else ""
            if nxt in _VALID_ESCAPES:
                out.append(ch)
                out.append(nxt)
                i += 2
                continue
            out.append("\\\\")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def schema_instruction(schema: Type[BaseModel]) -> str:
    """The block appended to every user prompt.

    Kept out of the prompt files on purpose: prompt files are about
    mathematics, and the user is expected to edit them. The JSON contract is
    machinery and should not be something they can accidentally break.
    """
    body = json.dumps(schema.model_json_schema(), indent=2, ensure_ascii=False)
    return (
        "\n\n---\n\n"
        "## Response format\n\n"
        "Reply with a single JSON object and nothing else — no preamble, no "
        "commentary, no explanation before or after it. It must validate "
        "against this JSON Schema:\n\n"
        f"```json\n{body}\n```\n\n"
        "Every field of mathematics you write is LaTeX. Inside JSON strings, "
        "write each LaTeX backslash **doubled**: `\\\\omega`, `\\\\le`, "
        "`\\\\|x\\\\|_{H^s}`. A single backslash makes the JSON invalid and the "
        "whole answer is thrown away."
    )


def prompt_hash(backend: str, model: str, system: str, user: str) -> str:
    payload = json.dumps(
        {"backend": backend, "model": model, "system": system, "user": user},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Backend(ABC):
    """One configured model, bound to one role.

    Subclasses implement :meth:`invoke`. Everything else is shared.
    """

    name: ClassVar[str] = "abstract"
    #: Whether this backend can report what a call cost.
    reports_cost: ClassVar[bool] = False

    def __init__(
        self,
        model: str,
        *,
        role: str = "",
        options: dict[str, Any] | None = None,
        log: Any = None,
        budget: Budget | None = None,
        replay: bool = False,
        pricing: dict[str, Any] | None = None,
    ):
        self.model = model
        self.role = role
        self.options = options or {}
        self.log = log
        self.budget = budget
        self.replay = replay
        self.pricing = pricing or {}
        self._last_error = ""

    # --- what subclasses provide --------------------------------------------

    @abstractmethod
    def invoke(self, system: str, user: str, timeout: float) -> Completion:
        """Send one prompt, return the text. No retries, no parsing."""

    def available(self) -> tuple[bool, str]:
        """Can this backend run here? Returns ``(ok, reason)``."""
        return True, ""

    # --- the one method everything else calls --------------------------------

    def complete(
        self,
        system: str,
        user: str,
        schema: Type[T],
        timeout: float = 300.0,
    ) -> tuple[T, CallMeta]:
        """Ask for JSON matching ``schema``; validate it; retry once; then fail."""
        full_user = user + schema_instruction(schema)
        result, meta = self._attempt(system, full_user, schema, timeout, attempt=1)
        if result is not None:
            return result, meta

        retry_user = (
            full_user
            + "\n\n---\n\n## Your previous reply was rejected\n\n"
            + f"```\n{self._last_error}\n```\n\n"
            + "Return only the corrected JSON object."
        )
        result, meta2 = self._attempt(system, retry_user, schema, timeout, attempt=2)
        if result is not None:
            meta2.attempts = 2
            return result, meta2
        raise AgentError(
            f"{self.role or self.name} returned unusable output twice; "
            f"last error: {self._last_error}"
        )

    def _attempt(
        self,
        system: str,
        user: str,
        schema: Type[T],
        timeout: float,
        attempt: int,
    ) -> tuple[T | None, CallMeta]:
        digest = prompt_hash(self.name, self.model, system, user)
        started = time.monotonic()

        cached = self.log.get(digest) if self.log is not None else None
        if cached is not None:
            completion = Completion(**cached["completion"])
            replayed = True
        elif self.replay:
            raise ReplayMiss(
                f"--replay: no logged call for {self.role or self.name} "
                f"(prompt {digest}). Run once without --replay to record it."
            )
        else:
            if self.budget is not None:
                self.budget.check()
            ok, reason = self.available()
            if not ok:
                raise BackendUnavailable(f"{self.name}: {reason}")
            completion = self.invoke(system, user, timeout)
            if self.budget is not None:
                self.budget.record(completion.cost_usd)
            replayed = False
            if self.log is not None:
                self.log.put(
                    digest,
                    role=self.role,
                    backend=self.name,
                    model=self.model,
                    system=system,
                    user=user,
                    completion=completion,
                )

        meta = CallMeta(
            role=self.role,
            backend=self.name,
            model=self.model,
            prompt_hash=digest,
            started_at=_now(),
            wall_seconds=round(time.monotonic() - started, 3),
            cost_usd=completion.cost_usd,
            input_tokens=completion.input_tokens,
            output_tokens=completion.output_tokens,
            attempts=attempt,
            replayed=replayed,
        )

        try:
            blob = extract_json(completion.text)
        except AgentError as exc:
            self._last_error = str(exc)
            return None, meta

        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            try:
                data = json.loads(repair_backslashes(blob))
                meta.repaired_json = True
            except json.JSONDecodeError as exc:
                self._last_error = f"the reply is not valid JSON: {exc}"
                return None, meta

        try:
            return schema.model_validate(data), meta
        except ValidationError as exc:
            self._last_error = _format_validation_error(exc)
            return None, meta

    def estimate_usd(self, input_tokens: int, output_tokens: int) -> float | None:
        """What a call of this size would cost, for ``--dry-run``.

        ``None`` for subscription backends, which is not a failure — it is the
        honest answer, and the caller reports call counts instead.
        """
        price = self.pricing.get(self.model)
        if not price:
            return None
        return (
            input_tokens * price.get("input_usd_per_mtok", 0.0)
            + output_tokens * price.get("output_usd_per_mtok", 0.0)
        ) / 1_000_000


def _format_validation_error(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err["loc"]) or "<root>"
        lines.append(f"- {loc}: {err['msg']}")
    return "\n".join(lines)
