"""The LaTeX proof-reader.

Human input has typos. A missing brace or an `\\end{aligned}` closing a
`\\begin{align}` means the statement will not typeset, and — worse — that every
agent downstream reads mangled mathematics and answers confidently about it.

So a statement is passed through this on its way in. It is deliberately the
narrowest role in the system:

*It may fix syntax. It may not touch the mathematics.* Not an index, not a
quantifier, not the direction of an inequality. If it thinks the statement is
wrong it says so in ``concerns`` and changes nothing.

*The user sees the rewrite before it is written.* The endpoint returns the
proposed text; the browser shows it beside the original with the list of changes,
and nothing is saved until the author accepts. An agent silently editing a
mathematician's theorem is precisely what the rest of this system refuses to do,
and it would not stop being wrong just because it is usually right.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from ..agents.base import CallMeta
from ..agents.registry import Registry
from ..paths import Project
from . import context

#: Which role does this. The checker is a strong model already configured, and
#: this is a small, frequent call — not worth a sixth role in ``bp.yaml`` until
#: someone wants to point it somewhere cheaper.
ROLE = "checker"


class TidyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changed: bool = Field(
        description="false if the input was already fine — the expected answer"
    )
    text: str = Field(description="the corrected passage, complete")
    changes: list[str] = Field(
        default_factory=list,
        description="one line per change: what you altered and why",
    )
    concerns: list[str] = Field(
        default_factory=list,
        description="things that look mathematically wrong. You did NOT change "
        "these; you are telling the author about them.",
    )


@dataclass
class TidyReport:
    original: str
    result: TidyResult | None = None
    calls: list[CallMeta] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.result and self.result.changed and self.result.text != self.original)


def tidy(
    project: Project,
    text: str,
    *,
    kind: str = "statement",
    registry: Registry | None = None,
) -> TidyReport:
    """Propose a syntax-only correction. Writes nothing."""
    registry = registry or Registry(project)
    report = TidyReport(original=text)
    if not text.strip():
        return report

    agent = registry.agent(ROLE)
    user = context.join(
        context.preamble_block(project),
        f"## The {kind}, as typed\n\n```latex\n{text}\n```",
    )
    result, meta = agent.complete(
        context.load_prompt("tidy_latex"),
        user,
        TidyResult,
        registry.config.role(ROLE).timeout,
    )
    report.result = result
    report.calls.append(meta)
    return report


def summarise(report: TidyReport) -> str:
    if report.result is None:
        return "nothing to tidy"
    if not report.changed:
        return "LaTeX is fine as written" + (
            "; concerns: " + "; ".join(report.result.concerns)
            if report.result.concerns
            else ""
        )
    lines = [f"{len(report.result.changes)} change(s) proposed:"]
    lines += [f"  - {c}" for c in report.result.changes]
    if report.result.concerns:
        lines.append("  concerns (not changed):")
        lines += [f"    - {c}" for c in report.result.concerns]
    return "\n".join(lines)


__all__ = ["ROLE", "TidyReport", "TidyResult", "summarise", "tidy"]
