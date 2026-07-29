"""Compiler-style diagnostics.

Every check in the system returns a list of these. They carry a stable code so
that a user can look one up, a severity so that ``bp check`` knows whether to
exit non-zero, and a hint saying what to actually do about it — a diagnostic
without a hint is a diagnostic the user has to guess at.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

Severity = Literal["error", "warn", "info"]

_RANK: dict[str, int] = {"error": 0, "warn": 1, "info": 2}


class Diagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: Severity
    node: str | None = None
    message: str
    hint: str | None = None
    file: str | None = None

    def line(self) -> str:
        """One-line rendering, in the shape editors and humans both expect."""
        where = self.file or self.node or "-"
        out = f"{where}: {self.severity}[{self.code}] {self.message}"
        if self.hint:
            out += f"\n    hint: {self.hint}"
        return out


def _node_id(node: Any) -> str | None:
    if node is None:
        return None
    if isinstance(node, str):
        return node
    return getattr(node, "id", None)


def _node_file(node: Any) -> str | None:
    path = getattr(node, "path", None)
    return str(path) if path else None


def diag(
    severity: Severity, code: str, node: Any, message: str, hint: str | None = None
) -> Diagnostic:
    return Diagnostic(
        code=code,
        severity=severity,
        node=_node_id(node),
        message=message,
        hint=hint,
        file=_node_file(node),
    )


def err(code: str, node: Any, message: str, hint: str | None = None) -> Diagnostic:
    return diag("error", code, node, message, hint)


def warn(code: str, node: Any, message: str, hint: str | None = None) -> Diagnostic:
    return diag("warn", code, node, message, hint)


def info(code: str, node: Any, message: str, hint: str | None = None) -> Diagnostic:
    return diag("info", code, node, message, hint)


def sort_diagnostics(ds: list[Diagnostic]) -> list[Diagnostic]:
    """Errors first, then warnings, then info; stable within a severity by node
    and code so that two runs on an unchanged graph print identically."""
    return sorted(ds, key=lambda d: (_RANK[d.severity], d.node or "", d.code))


def has_errors(ds: list[Diagnostic]) -> bool:
    return any(d.severity == "error" for d in ds)
