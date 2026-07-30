"""Role → backend resolution, read from ``bp.yaml``.

The system talks about *roles* — decomposer, checker, extractor, obligation,
verifier_a, verifier_b, confirmer, auditor, prover — and never about models. Which
model plays which role is one edit to one file. That indirection is worth keeping
even though it costs a layer: it is what lets a user move the expensive verifier
onto a subscription CLI when the bill gets uncomfortable, or put the two verifiers
on different families so the panel is worth having, without touching a line of
Python.

It is also how **model tiering** happens, which is the difference between a
recompile you can afford and one you cannot. Extraction is translation and belongs
on the cheap model; the narrow entailment checks — obligations and claims, the bulk
of the calls — belong on a mid model; the whole-proof pass and the confirmation
pass belong on the strongest one available. The defaults below say that, and
``bp.yaml`` overrides any of it.

Prices are configuration too. They are needed for ``--dry-run`` estimates and
for the budget cap, they change, and hardcoding them would make the estimate
quietly wrong six months from now.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from ruamel.yaml import YAML

from ..paths import Project
from .base import Backend, Budget
from .claude_api import ClaudeAPIBackend
from .claude_cli import ClaudeCLIBackend
from .codex_cli import CodexCLIBackend
from .log import CallLog
from .openai_api import OpenAIAPIBackend
from .scripted import ScriptedBackend

CONFIG_NAME = "bp.yaml"

BACKENDS: dict[str, type[Backend]] = {
    ClaudeAPIBackend.name: ClaudeAPIBackend,
    OpenAIAPIBackend.name: OpenAIAPIBackend,
    ClaudeCLIBackend.name: ClaudeCLIBackend,
    CodexCLIBackend.name: CodexCLIBackend,
    ScriptedBackend.name: ScriptedBackend,
}

#: Every role the system asks for by name. ``obligation`` answers both narrow
#: entailment jobs — a discharge obligation and a ledger claim are the same shape
#: of question and want the same tier of model — so there is one role rather than
#: two knobs that would always be set alike.
ROLES = (
    "decomposer",
    "checker",
    "extractor",
    "obligation",
    "verifier_a",
    "verifier_b",
    "confirmer",
    "auditor",
    "prover",
)

#: Published list prices, US dollars per million tokens. Overridable in
#: ``bp.yaml`` under ``pricing:``. Used for the ``--dry-run`` estimate and the
#: budget cap; subscription backends report no cost at all and are counted
#: rather than priced.
DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-5": {"input_usd_per_mtok": 5.0, "output_usd_per_mtok": 25.0},
    "claude-opus-4-8": {"input_usd_per_mtok": 5.0, "output_usd_per_mtok": 25.0},
    "claude-fable-5": {"input_usd_per_mtok": 10.0, "output_usd_per_mtok": 50.0},
    "claude-sonnet-5": {"input_usd_per_mtok": 3.0, "output_usd_per_mtok": 15.0},
    "claude-haiku-4-5": {"input_usd_per_mtok": 1.0, "output_usd_per_mtok": 5.0},
}

#: The tiering, as defaults. Cheap model for translation, mid model for the narrow
#: entailment checks that make up most of the calls, strongest model for the two
#: jobs that need a whole argument in view.
DEFAULT_ROLES: dict[str, dict[str, Any]] = {
    "decomposer": {"backend": "claude_api", "model": "claude-opus-5"},
    "checker": {"backend": "claude_api", "model": "claude-opus-5"},
    "extractor": {"backend": "claude_api", "model": "claude-haiku-4-5"},
    "obligation": {"backend": "claude_api", "model": "claude-sonnet-5"},
    "verifier_a": {"backend": "claude_api", "model": "claude-opus-5"},
    "verifier_b": {"backend": "claude_api", "model": "claude-opus-5"},
    "confirmer": {"backend": "claude_api", "model": "claude-opus-5"},
    "auditor": {"backend": "claude_api", "model": "claude-opus-5"},
    "prover": {"backend": "claude_api", "model": "claude-sonnet-5"},
}


#: When ``bp.yaml`` does not configure a role, which *configured* role it should copy
#: rather than falling back to a built-in default.
#:
#: This exists because of a real failure. Four roles were added — `extractor`,
#: `obligation`, `confirmer`, `auditor` — and every existing project's `bp.yaml`
#: predated them, so all four silently resolved to the built-in `claude_api` default.
#: A user who had configured every role for `codex_cli` found half their system
#: pointed at Anthropic, with no key, and discovered it from a raw SDK TypeError.
#:
#: Silently changing *provider* is the worst possible default: it is invisible, it
#: costs money on an account the user may not have meant to use, and it contradicts the
#: one thing `bp.yaml` is for. Inheriting from the nearest configured role of the same
#: tier gives the answer they would obviously have written themselves.
ROLE_INHERITS: dict[str, tuple[str, ...]] = {
    # Translation: the cheapest thing configured. `prover` is mid-tier and the closest
    # pre-existing role to "cheap"; `checker` is the safe last resort.
    "extractor": ("prover", "checker", "decomposer"),
    # The narrow entailment checks. Mid-tier, most like the checker.
    "obligation": ("checker", "verifier_a", "prover"),
    # Both of these read a whole argument, like the panel does.
    "confirmer": ("verifier_a", "verifier_b", "checker"),
    "auditor": ("checker", "verifier_a", "decomposer"),
}


class ConfigError(Exception):
    pass


class RoleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: str
    model: str
    #: Backend-specific knobs: ``max_tokens``, ``effort``, ``thinking``,
    #: ``command``, ``timeout``. Kept loose on purpose — they are exactly the
    #: things that differ between models and CLI releases.
    options: dict[str, Any] = Field(default_factory=dict)
    timeout: float = 600.0


class BudgetConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    per_recompile_usd: float | None = 3.0
    max_calls_per_recompile: int | None = 40


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roles: dict[str, RoleConfig] = Field(default_factory=dict)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    pricing: dict[str, dict[str, float]] = Field(default_factory=dict)
    #: role -> where its configuration came from: ``"bp.yaml"``, ``"inherited from
    #: <role>"``, or ``"built-in default"``. Reported by ``bp agents`` and by the
    #: browser, because a role the user did not configure is a role they should be
    #: told about rather than left to discover from a provider error.
    provenance: dict[str, str] = Field(default_factory=dict)

    def price_table(self) -> dict[str, dict[str, float]]:
        merged = {k: dict(v) for k, v in DEFAULT_PRICING.items()}
        merged.update({k: dict(v) for k, v in self.pricing.items()})
        return merged

    def role(self, name: str) -> RoleConfig:
        try:
            return self.roles[name]
        except KeyError:
            raise ConfigError(
                f"no role {name!r} in {CONFIG_NAME}; configured roles are "
                + (", ".join(sorted(self.roles)) or "none")
            ) from None


def config_path(project: Project) -> Path:
    return project.root / CONFIG_NAME


def load_config(project: Project) -> Config:
    """Read ``bp.yaml``, falling back to defaults for anything absent."""
    path = config_path(project)
    data: dict[str, Any] = {}
    if path.exists():
        yaml = YAML(typ="safe")
        try:
            loaded = yaml.load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ConfigError(f"{path} must be a YAML mapping")
        data = loaded

    agents = data.get("agents") or {}
    authored = dict((agents.get("roles") or {}))

    roles: dict[str, Any] = {}
    provenance: dict[str, str] = {}
    for name in set(ROLES) | set(DEFAULT_ROLES) | set(authored):
        if name in authored:
            roles[name] = authored[name]
            provenance[name] = "bp.yaml"
            continue
        # Not configured. Copy the nearest configured role of the same tier before
        # reaching for a built-in default, so adding a role to this system never
        # silently moves a project to a different provider.
        source = next((s for s in ROLE_INHERITS.get(name, ()) if s in authored), None)
        if source is not None:
            roles[name] = dict(authored[source])
            provenance[name] = f"inherited from {source}"
        else:
            roles[name] = DEFAULT_ROLES[name]
            provenance[name] = "built-in default"

    try:
        return Config(
            roles=roles,
            budget=data.get("budget") or {},
            pricing=data.get("pricing") or {},
            provenance=provenance,
        )
    except Exception as exc:
        raise ConfigError(f"{path}: {exc}") from exc


class Registry:
    """Hands out configured, logged, budgeted agents by role name."""

    def __init__(
        self,
        project: Project,
        config: Config | None = None,
        *,
        replay: bool = False,
        budget: Budget | None = None,
        log: CallLog | None = None,
        observer: Any = None,
    ):
        self.project = project
        self.config = config or load_config(project)
        self.replay = replay
        self.log = log if log is not None else CallLog.for_project(project)
        self.budget = budget if budget is not None else self.default_budget()
        #: Passed to every backend; see :attr:`bp.agents.base.Backend.observer`.
        self.observer = observer
        self._cache: dict[str, Backend] = {}

    def default_budget(self) -> Budget:
        return Budget(
            max_usd=self.config.budget.per_recompile_usd,
            max_calls=self.config.budget.max_calls_per_recompile,
        )

    def agent(self, role: str) -> Backend:
        if role in self._cache:
            return self._cache[role]
        spec = self.config.role(role)
        cls = BACKENDS.get(spec.backend)
        if cls is None:
            raise ConfigError(
                f"role {role!r} names backend {spec.backend!r}, which does not exist; "
                f"known backends are {', '.join(sorted(BACKENDS))}"
            )
        backend = cls(
            spec.model,
            role=role,
            options=dict(spec.options),
            log=self.log,
            budget=self.budget,
            replay=self.replay,
            pricing=self.config.price_table(),
            observer=self.observer,
        )
        self._cache[role] = backend
        return backend

    def describe(self) -> list[tuple[str, str, str, bool, str, str]]:
        """``(role, backend, model, available, reason, provenance)`` for ``bp agents``.

        ``provenance`` is the column that would have saved a real afternoon: it says
        whether a role's backend came from the user's ``bp.yaml``, was inherited from
        another role, or is a built-in default they have never seen.
        """
        rows = []
        for role in sorted(self.config.roles):
            source = self.config.provenance.get(role, "bp.yaml")
            try:
                backend = self.agent(role)
            except ConfigError as exc:
                rows.append((role, "?", "?", False, str(exc), source))
                continue
            ok, reason = backend.available()
            rows.append((role, backend.name, backend.model, ok, reason, source))
        return rows
