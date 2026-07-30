"""The statement auditor: four questions about a statement, no proof involved.

This role is the agent stand-in for the deterministic ``VAC`` and ``CST`` checks
in ``DESIGN.md`` §8, which v0 defers. Being clear about that matters, because it is
*weaker* than what it replaces and must not be read as equivalent:

* a scope check finds a circular constant dependency mechanically, by walking a
  declared dependency table. This role finds one by reading, which means it will
  miss some;
* a vacuity check exhibits a witness or reports the constraint system unsatisfiable.
  This role's vacuity answer is an assertion, and an assertion that a witness exists
  is not a witness.

So its verdicts are prompts for the user's attention, not checks. Nothing in the
system blocks on them, and the only status it can influence is the
``statement_audit`` line of the verification record — which says *audited*, never
*sound*.

It is worth the call anyway. Question 4 — does a constant depend, transitively, on
something the statement treats it as uniform in — catches the classic bootstrap
error often enough to pay for itself, and that error invalidates a whole argument
rather than one step of it.

One call per statement, and it is independent of any proof, so the answer is
cacheable against the statement hash and survives every edit to the proof.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

from .. import ops
from ..agents.base import CallMeta
from ..agents.registry import Registry
from ..checks import load_graph
from ..paths import Project
from . import context


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote: str = Field(description="the exact fragment of the statement this is about")
    why: str = Field(description="what is wrong with it, in one or two sentences")
    confidence: str = Field(default="medium", description="low | medium | high")


class WellPosed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    checked: str = Field(description="which symbols you resolved, and to what")
    findings: list[Finding] = Field(default_factory=list)


class Witness(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: str = Field(
        description="`exhibited` if you wrote one down, `not_found` if you could not, "
        "`out_of_reach` if the question needs work beyond reading the statement"
    )
    witness: str = Field(
        default="",
        description="the concrete instance, in LaTeX. Required when verdict is "
        "`exhibited`; a claim that one exists is not a witness.",
    )
    conflict: str = Field(
        default="",
        description="when not_found: which hypotheses you believe cannot hold together",
    )


class Quantifiers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    checked: str = Field(description="the quantifier order you read, spelled out")
    findings: list[Finding] = Field(default_factory=list)


class ConstantDependence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    constants: list[str] = Field(
        default_factory=list,
        description="one entry per constant: its name, and what the statement allows "
        "it to depend on",
    )
    findings: list[Finding] = Field(default_factory=list)


class StatementAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    well_posed: WellPosed
    non_vacuous: Witness
    quantifiers: Quantifiers
    constants: ConstantDependence

    @property
    def findings(self) -> list[tuple[str, Finding]]:
        out: list[tuple[str, Finding]] = []
        for label, block in (
            ("well-posed", self.well_posed),
            ("quantifiers", self.quantifiers),
            ("constants", self.constants),
        ):
            out.extend((label, f) for f in block.findings)
        return out

    @property
    def vacuity_unresolved(self) -> bool:
        """A missing witness is a finding in its own right.

        ``not_found`` is the interesting answer — hypotheses that cannot hold
        together make a statement true and useless — and ``out_of_reach`` is an
        honest admission that must not read as a pass.
        """
        return self.non_vacuous.verdict != "exhibited"

    @property
    def clean(self) -> bool:
        return not self.findings and not self.vacuity_unresolved


@dataclass
class AuditReport:
    node: str
    audit: StatementAudit | None = None
    calls: list[CallMeta] = field(default_factory=list)
    noted: bool = False

    @property
    def clean(self) -> bool:
        return self.audit is not None and self.audit.clean

    @property
    def verdict(self) -> str:
        """The ``statement_audit`` line of the verification record."""
        if self.audit is None:
            return "not_run"
        return "pass" if self.audit.clean else "flagged"


def audit(
    project: Project,
    node_id: str,
    *,
    registry: Registry | None = None,
    apply: bool = True,
) -> AuditReport:
    """One call, four questions. Never touches a status."""
    registry = registry or Registry(project)
    graph, _, swept = load_graph(project)
    if not swept:
        raise ops.OpError("the graph has a cycle; run `bp check` first")
    node = graph.get(node_id)
    if node is None:
        raise ops.OpError(f"no node {node_id!r}")
    if not node.statement_section.strip():
        raise ops.OpError(f"{node_id} has no statement to audit")

    agent = registry.agent("auditor")
    user = context.join(
        context.preamble_block(project),
        # No proof: the statement has to stand on its own, and a proof in the
        # context would let the model read the intended meaning off the argument
        # instead of off the words.
        context.node_block(node, heading="The statement to audit", proof=False),
        context.setting(graph, node),
    )
    result, meta = agent.complete(
        context.load_prompt("audit"),
        user,
        StatementAudit,
        registry.config.role("auditor").timeout,
    )
    report = AuditReport(node=node_id, audit=result, calls=[meta])

    if apply and not result.clean:
        ops.add_note(project, node_id, note_text(result), actor="auditor")
        report.noted = True
    return report


def note_text(result: StatementAudit) -> str:
    """The audit as a note on the node.

    A note rather than a flag, and that is the whole design: this role's answers
    are weaker than the deterministic checks they stand in for, so they belong
    where the user reads them and where every later role sees them as context —
    not where they can block a status.
    """
    bits = ["Statement audit:"]
    for label, finding in result.findings:
        bits.append(f"[{label}, {finding.confidence}] {finding.why} — “{finding.quote}”")
    if result.vacuity_unresolved:
        w = result.non_vacuous
        if w.verdict == "not_found":
            bits.append(
                "[vacuity] no instance satisfying every hypothesis at once was found"
                + (f"; suspected conflict: {w.conflict}" if w.conflict else "")
            )
        else:
            bits.append(
                "[vacuity] whether the hypotheses can hold together was judged out of "
                "reach from the statement alone"
            )
    return " ".join(bits) if len(bits) > 1 else "Statement audit: nothing found."


def summarise(report: AuditReport) -> str:
    result = report.audit
    if result is None:
        return f"{report.node}: not audited"
    lines = [f"{report.node}: statement audit {report.verdict}"]
    lines.append(f"  well-posed: {'yes' if result.well_posed.ok else 'no'} — "
                 f"{result.well_posed.checked}")
    w = result.non_vacuous
    if w.verdict == "exhibited":
        lines.append(f"  non-vacuous: witness — {w.witness}")
    elif w.verdict == "not_found":
        lines.append(f"  non-vacuous: NO WITNESS FOUND — {w.conflict or 'no conflict named'}")
    else:
        lines.append("  non-vacuous: out of reach from the statement alone")
    lines.append(f"  quantifiers: {'as intended' if result.quantifiers.ok else 'SUSPECT'} — "
                 f"{result.quantifiers.checked}")
    lines.append(f"  constants: {'uniform as stated' if result.constants.ok else 'SUSPECT'}")
    for entry in result.constants.constants:
        lines.append(f"    - {entry}")
    for label, finding in result.findings:
        lines.append(f"  [{label}, {finding.confidence}] {finding.why}")
        if finding.quote:
            lines.append(f"      quoting: {finding.quote[:160]}")
    lines.append(
        "  These are prompts for your attention, not checks: this role stands in for "
        "the deterministic vacuity and constant-scope checks and is weaker than both."
    )
    return "\n".join(lines)


__all__ = [
    "AuditReport",
    "ConstantDependence",
    "Finding",
    "Quantifiers",
    "StatementAudit",
    "WellPosed",
    "Witness",
    "audit",
    "note_text",
    "summarise",
]
