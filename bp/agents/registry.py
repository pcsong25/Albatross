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

import io
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from ..load import atomic_write
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
    "proofreader",
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
    "proofreader": {"backend": "claude_api", "model": "claude-sonnet-5"},
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
    # It used to *be* `checker`, hardcoded in `roles/tidy.py`. Inheriting from it keeps
    # every existing project's behaviour identical while making it adjustable.
    "proofreader": ("checker", "decomposer", "verifier_a"),
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


#: Who reads the whole proof. Two by default, and they should be different model
#: families — but the *membership* was hardcoded, so a bp.yaml could not add a third
#: reader or drop to one. Configurable under `agents.panel`.
DEFAULT_PANEL = ("verifier_a", "verifier_b")


class BudgetConfig(BaseModel):
    """The caps. They apply to *any* run, not only to a recompile.

    Both keys were originally named ``*_per_recompile``, which was accurate when a
    recompile was the only thing that made many calls and is misleading now: a
    single ``bp verify --level deep`` on a node with thirty obligations makes forty.
    A user read "40 calls per recompile", reasonably concluded it did not constrain
    one node, and lost the whole cap to a run that needed forty-one.

    So the names are ``per_run``, the old ones are accepted as aliases forever — a
    config file that stops working is a worse cost than two spellings — and
    ``bp agents`` prints the cap with the words "per run" next to it.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    per_run_usd: float | None = Field(default=3.0, alias="per_recompile_usd")
    max_calls_per_run: int | None = Field(default=80, alias="max_calls_per_recompile")

    @property
    def per_recompile_usd(self) -> float | None:
        return self.per_run_usd

    @property
    def max_calls_per_recompile(self) -> int | None:
        return self.max_calls_per_run


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roles: dict[str, RoleConfig] = Field(default_factory=dict)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    pricing: dict[str, dict[str, float]] = Field(default_factory=dict)
    #: Which roles read the whole proof. Every name here must be a configured role.
    panel: list[str] = Field(default_factory=lambda: list(DEFAULT_PANEL))
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


#: Notes written beside a role when `bp agents --fill` materialises it, so a file that
#: gains a role six months from now still explains what the role is for.
ROLE_NOTES: dict[str, str] = {
    "decomposer": "Proposes children, a reduction, and a complete discharge table.",
    "checker": "Two fixed questions about a decomposition. Also the proof-reader, unless `proofreader` is set.",
    "extractor": "Lists every load-bearing claim a proof makes. TRANSLATION, not judgement: use your cheapest setting.",
    "obligation": "The narrow checks: discharges, ledger claims, citations. Most of the calls at --level deep, so the biggest lever on cost.",
    "verifier_a": "The whole-proof panel. These two should be DIFFERENT model families -- that is the entire reason there are two.",
    "verifier_b": "See verifier_a.",
    "confirmer": "Re-reads each objection in context and drops the ones that dissolve. Do not economise: without it the list is mostly pedantry.",
    "auditor": "Four questions about a statement, no proof in view. --level deep only.",
    "proofreader": "Syntax-only corrections when you save a statement. Small and frequent.",
    "prover": "Writes proofs for routine and standard leaves. Never sets a status.",
}


def fill_missing_roles(project: Project) -> tuple[list[str], Path]:
    """Write every unconfigured role into ``bp.yaml``, and return which ones.

    The point is that the file becomes the complete truth. Inheritance
    (:data:`ROLE_INHERITS`) exists so that adding a role to Albatross never silently
    repoints an existing project — but inheritance is still a layer the user cannot see
    in their own file, and "I want every backend adjustable from bp.yaml" is a
    reasonable thing to want. After this there is nothing left to infer.

    Round-trip YAML, so comments, key order and quote style survive: this file is
    hand-maintained and full of the user's own notes about why each role is set the way
    it is.
    """
    path = config_path(project)
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)

    data = yaml.load(path.read_text(encoding="utf-8")) if path.exists() else None
    if data is None:
        data = CommentedMap()
    agents = data.setdefault("agents", CommentedMap())
    roles = agents.setdefault("roles", CommentedMap())

    resolved = load_config(project)
    added: list[str] = []
    for name in ROLES:
        if name in roles:
            continue
        spec = resolved.role(name)
        entry = CommentedMap()
        entry["backend"] = spec.backend
        entry["model"] = spec.model
        if spec.options:
            entry["options"] = spec.options
        entry["timeout"] = spec.timeout
        roles[name] = entry
        note = ROLE_NOTES.get(name)
        source = resolved.provenance.get(name, "")
        comment = f"{note} [added by `bp agents --fill`; {source}]" if note else None
        if comment:
            try:
                roles.yaml_set_comment_before_after_key(name, before=comment, indent=4)
            except AttributeError:  # pragma: no cover - a plain dict
                pass
        added.append(name)

    if added:
        buf = io.StringIO()
        yaml.dump(data, buf)
        atomic_write(path, buf.getvalue())
    return added, path


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
        # `or DEFAULT_PANEL` would be wrong: an empty list is falsy, so an explicitly
        # empty panel would silently become the default instead of being refused.
        panel = (
            list(agents["panel"] or [])
            if "panel" in agents and agents["panel"] is not None
            else list(DEFAULT_PANEL)
        )
        unknown = [p for p in panel if p not in roles]
        if unknown:
            raise ConfigError(
                f"{path}: agents.panel names {', '.join(unknown)}, which "
                + ("is not a configured role" if len(unknown) == 1 else "are not configured roles")
                + ". Add them under agents.roles, or remove them from the panel."
            )
        if not panel:
            raise ConfigError(
                f"{path}: agents.panel is empty, so nobody would read a whole proof "
                "and no node could ever be verified. Name at least one role."
            )
        return Config(
            roles=roles,
            budget=data.get("budget") or {},
            pricing=data.get("pricing") or {},
            panel=panel,
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
