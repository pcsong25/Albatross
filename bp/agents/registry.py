"""Role → backend resolution, read from ``bp.yaml``.

The system talks about *roles* — decomposer, checker, verifier_a, verifier_b,
prover — and never about models. Which model plays which role is one edit to one
file. That indirection is worth keeping even though it costs a layer: it is what
lets a user move the expensive verifier onto a subscription CLI when the bill
gets uncomfortable, or put the two verifiers on different families so the panel
is worth having, without touching a line of Python.

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

ROLES = ("decomposer", "checker", "verifier_a", "verifier_b", "prover")

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

DEFAULT_ROLES: dict[str, dict[str, Any]] = {
    "decomposer": {"backend": "claude_api", "model": "claude-opus-5"},
    "checker": {"backend": "claude_api", "model": "claude-opus-5"},
    "verifier_a": {"backend": "claude_api", "model": "claude-opus-5"},
    "verifier_b": {"backend": "claude_api", "model": "claude-opus-5"},
    "prover": {"backend": "claude_api", "model": "claude-sonnet-5"},
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
    roles = dict(DEFAULT_ROLES)
    for name, entry in (agents.get("roles") or {}).items():
        roles[name] = entry

    try:
        return Config(
            roles=roles,
            budget=data.get("budget") or {},
            pricing=data.get("pricing") or {},
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

    def describe(self) -> list[tuple[str, str, str, bool, str]]:
        """``(role, backend, model, available, reason)`` for ``bp agents``."""
        rows = []
        for role in sorted(self.config.roles):
            try:
                backend = self.agent(role)
            except ConfigError as exc:
                rows.append((role, "?", "?", False, str(exc)))
                continue
            ok, reason = backend.available()
            rows.append((role, backend.name, backend.model, ok, reason))
        return rows
