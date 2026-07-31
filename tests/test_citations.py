"""The layered defence against a citation to something that does not exist.

This file exists because of one reported failure, and the failure is worth writing
down because every layer of the system missed it at once.

A target theorem's statement said *"let $\\omega_0$ be as in Section
\\ref{sec-space}"*. That section was never written. Then:

1. **Nothing examined the target when it was provided.** There was no check on the
   root statement at all.
2. **The decomposer split it into seven children**, every one of which inherited the
   phrase, without noticing.
3. **The verifier passed their proofs.**
4. **LaTeX only warned** and printed `??`.

Four layers, each of which could have caught it, and they failed for one reason:
**nobody enumerated the references.** That is this codebase's recurring lesson —
a thing nobody enumerates is a thing nobody checks — applied to citations, having
already been applied to hypotheses (`DIS011`) and claims (`LED001`).

So there are now four answers, one per layer, and this file tests each of them
against the original scenario.
"""

from __future__ import annotations

import pytest

from bp import checks, ops, verification, xref
from bp.checks import load_graph
from bp.roles import audit as audit_role
from bp.roles import decompose as decompose_role
from bp.roles import verify as verify_role

from .conftest import json_reply, scripted_registry, write_node

#: The statement as reported: a citation to a section that was never provided.
REPORTED = "Let $\\omega_0$ be as in Section \\ref{sec-space}. Then it blows up."


def graph_of(project):
    g, _, ok = load_graph(project)
    assert ok
    return g


def by_code(diagnostics, code):
    return [d for d in diagnostics if d.code == code]


def audit_reply(clean=True):
    return json_reply(
        {
            "well_posed": {
                "ok": clean,
                "checked": "every symbol resolved",
                "findings": []
                if clean
                else [
                    {
                        "quote": "as in Section \\ref{sec-space}",
                        "why": "the hypotheses on omega_0 are nowhere stated",
                        "confidence": "high",
                    }
                ],
            },
            "non_vacuous": {"verdict": "exhibited", "witness": "\\omega_0 = -\\sin x", "conflict": ""},
            "quantifiers": {"ok": True, "checked": "as intended", "findings": []},
            "constants": {"ok": True, "constants": [], "findings": []},
        }
    )


class TestLayerOneTheTargetIsExamined:
    """The layer that was entirely missing. Nothing looked at the root statement."""

    def test_TGT001_says_the_target_has_never_been_audited(self, project):
        write_node(project, "gclm.main", target=True, statement=REPORTED)
        d = [x for x in checks.run(project).diagnostics if x.code == "TGT001"]
        assert len(d) == 1
        assert d[0].node == "gclm.main"
        assert "bp audit gclm.main" in (d[0].hint or "")

    def test_a_non_target_node_is_not_nagged(self, project):
        """Most nodes are never audited — the auditor runs at `deep` only. Firing on
        all of them would make the check noise, and noise is how a check earns being
        ignored."""
        write_node(project, "gclm.main", target=True, statement="A theorem.")
        write_node(project, "child", statement="A lemma.")
        d = [x for x in checks.run(project).diagnostics if x.code.startswith("TGT")]
        assert [x.node for x in d] == ["gclm.main"]

    def test_auditing_it_clears_the_check(self, project):
        write_node(project, "gclm.main", target=True, statement=REPORTED)
        registry = scripted_registry(project, auditor=[audit_reply()])
        audit_role.audit(project, "gclm.main", registry=registry)
        node = graph_of(project)["gclm.main"]
        assert node.audited_against == node.statement_hash
        assert [x for x in checks.run(project).diagnostics if x.code == "TGT001"] == []

    def test_TGT002_the_audit_expires_when_the_statement_is_edited(self, project):
        """A certificate, not a boolean: an audit of different words is not an audit
        of these words."""
        write_node(project, "gclm.main", target=True, statement=REPORTED)
        registry = scripted_registry(project, auditor=[audit_reply()])
        audit_role.audit(project, "gclm.main", registry=registry)
        ops.edit_statement(project, "gclm.main", "A completely different theorem.")
        d = [x for x in checks.run(project).diagnostics if x.code == "TGT002"]
        assert len(d) == 1
        assert "edited since it was audited" in d[0].message

    def test_the_audit_still_never_touches_a_status(self, project):
        """D049 stands: its findings are prompts for attention. Recording *that* it
        ran is a different thing from letting it decide anything."""
        write_node(project, "gclm.main", target=True, statement=REPORTED, proof="p")
        registry = scripted_registry(project, auditor=[audit_reply(clean=False)])
        report = audit_role.audit(project, "gclm.main", registry=registry)
        assert not report.clean
        node = graph_of(project)["gclm.main"]
        assert node.local_status == "unverified"
        assert node.audited_against is not None
        assert "nowhere stated" in node.notes_section

    def test_audited_against_cannot_be_authored(self, project):
        write_node(project, "gclm.main", target=True, statement="S.")
        graph = ops.open_graph(project)
        with pytest.raises(ops.ComputedFieldError):
            ops.set_authored(graph["gclm.main"], "audited_against", "x")


class TestLayerTwoExpansionRefuses:
    """The decomposer split an incoherent statement into seven children."""

    def test_expand_refuses_a_statement_that_cites_nothing(self, project):
        write_node(project, "gclm.main", target=True, difficulty="hard", statement=REPORTED)
        with pytest.raises(ops.OpError) as exc:
            decompose_role.expand(project, "gclm.main", registry=scripted_registry(project))
        message = str(exc.value)
        assert "XRF001" in message
        assert "Every child inherits whatever is wrong here" in message

    def test_it_refuses_before_spending_a_call(self, project):
        """The registry has no scripted decomposer response, so a call would fail the
        test rather than pass it."""
        write_node(project, "gclm.main", target=True, difficulty="hard", statement=REPORTED)
        registry = scripted_registry(project)
        with pytest.raises(ops.OpError):
            decompose_role.expand(project, "gclm.main", registry=registry)
        assert registry.budget.calls == 0

    def test_force_overrides_it(self, project):
        """The user may be mid-edit and know better. It is an override, not a
        default."""
        write_node(project, "gclm.main", target=True, difficulty="hard", statement=REPORTED)
        problems = decompose_role.statement_errors(
            graph_of(project), graph_of(project)["gclm.main"]
        )
        assert problems  # would refuse
        # With force the guard is skipped; the call then fails for want of a script,
        # which is a different error and proves the guard was passed.
        with pytest.raises(Exception) as exc:
            decompose_role.expand(
                project, "gclm.main", registry=scripted_registry(project), force=True
            )
        assert "XRF001" not in str(exc.value)

    def test_an_unclosed_dollar_also_refuses(self, project):
        write_node(project, "gclm.main", target=True, difficulty="hard",
                   statement="Let $\\omega_0 be odd. Then it blows up.")
        with pytest.raises(ops.OpError) as exc:
            decompose_role.expand(project, "gclm.main", registry=scripted_registry(project))
        assert "TEX002" in str(exc.value)

    def test_a_clean_statement_is_not_blocked(self, project):
        write_node(project, "gclm.main", target=True, difficulty="hard",
                   statement="Let $\\omega_0$ be odd. Then it blows up.")
        assert decompose_role.statement_errors(
            graph_of(project), graph_of(project)["gclm.main"]
        ) == []

    def test_the_decomposer_is_told_what_the_statement_cites(self, project):
        """It had no cross-reference context at all, which is why it propagated the
        phrase without noticing."""
        from bp.roles import context as context_mod

        write_node(project, "gclm.main", target=True, difficulty="hard", statement=REPORTED)
        graph = graph_of(project)
        prompt = decompose_role.build_prompt(graph, graph["gclm.main"], None, project)
        assert "sec-space" in prompt
        assert "refers to nothing that exists" in prompt
        assert context_mod.xref_block(graph, graph["gclm.main"])


class TestLayerThreeTheVerifierCannotPass:
    """The verifier passed the local proof. It can no longer."""

    def test_a_dangling_citation_flags_the_node_even_at_quick(self, project):
        write_node(project, "gclm.main", target=True, statement=REPORTED, proof="An argument.")
        registry = scripted_registry(
            project,
            verifier_a=[json_reply({"checked": ["the whole argument"], "objections": []})],
            verifier_b=[json_reply({"checked": ["all of it"], "objections": []})],
        )
        report = verify_role.verify(project, "gclm.main", registry=registry, level="quick")
        assert report.verdict == "flagged"
        assert report.record.deterministic["xref"] == "fail"
        assert any("xref" in r for r in report.reasons)
        assert graph_of(project)["gclm.main"].local_status == "flagged"


def citing_pair(project, *, cited_statement, citing_statement):
    write_node(
        project, "t", target=True, children=["c"], proof="By `c`.",
        statement=citing_statement,
        uses={"c": {"applied_to": "x", "discharges": {}}},
    )
    write_node(project, "c", statement=cited_statement, proof="An argument.")
    return graph_of(project)


class TestLayerFourCitationsAreObligations:
    """Existence is deterministic. Whether the cited text *supports the use made of
    it* is a judgement, so it becomes one narrow question per citation — the third
    worklist, alongside discharges and ledger claims."""

    def test_one_record_per_cross_node_citation(self, project):
        g = citing_pair(
            project,
            cited_statement="\\begin{equation}\\label{eq:bound} \\|u\\| \\le C \\end{equation}",
            citing_statement="By \\eqref{eq:bound} the norm is finite, so we may proceed.",
        )
        records = xref.reference_obligations_for(g["t"], g)
        assert len(records) == 1
        r = records[0]
        assert r["kind"] == "reference"
        assert r["reference"] == "eq:bound"
        assert r["target"] == "c"
        # The passage doing the citing, not just the reference: the question is what
        # is drawn from it, and that is in the surrounding prose.
        assert "the norm is finite" in r["needed"]
        # And what the cited text actually says, so the question is self-contained.
        assert "\\le C" in r["source_text"]

    def test_a_dangling_citation_produces_no_record(self, project):
        """XRF001 has already decided it, deterministically. Sending it to a model
        would invite the model to imagine what it might have pointed at."""
        write_node(project, "t", target=True, statement=REPORTED)
        g = graph_of(project)
        assert xref.reference_obligations_for(g["t"], g) == []

    def test_a_reference_inside_one_node_produces_no_record(self, project):
        write_node(project, "t", target=True,
                   statement="\\begin{equation}\\label{eq:a} x=y \\end{equation}",
                   proof="By \\eqref{eq:a} we are done.")
        g = graph_of(project)
        assert xref.reference_obligations_for(g["t"], g) == []

    def test_hashes_are_stable_and_move_with_the_question(self, project):
        g = citing_pair(
            project,
            cited_statement="\\begin{equation}\\label{eq:b} a=b \\end{equation}",
            citing_statement="By \\eqref{eq:b}, done.",
        )
        first = xref.reference_obligations_for(g["t"], g)[0]["hash"]
        assert xref.reference_obligations_for(g["t"], g)[0]["hash"] == first
        ops.edit_statement(project, "c", "\\begin{equation}\\label{eq:b} a=2b \\end{equation}")
        g2 = graph_of(project)
        assert xref.reference_obligations_for(g2["t"], g2)[0]["hash"] != first

    def test_bp_obligations_emits_them(self, project):
        citing_pair(
            project,
            cited_statement="\\begin{equation}\\label{eq:c} a=b \\end{equation}",
            citing_statement="By \\eqref{eq:c}, done.",
        )
        g = graph_of(project)
        kinds = {r["kind"] for r in xref.all_reference_obligations(g)}
        assert kinds == {"reference"}

    def test_a_misused_citation_flags_the_node(self, project):
        """The failure the prompt is written around: a definition cited as a theorem,
        or a bound cited as a strict inequality."""
        citing_pair(
            project,
            cited_statement="\\begin{equation}\\label{eq:defn} z(t) := -\\partial_x\\omega(t,0) \\end{equation}",
            citing_statement="By \\eqref{eq:defn}, $z(t) > 0$ for all $t$.",
        )
        registry = scripted_registry(
            project,
            extractor=[json_reply({"claims": []})],
            obligation=[
                json_reply(
                    {
                        "entails": False,
                        "why": "that display defines z; a definition asserts nothing, "
                        "so positivity does not follow from it",
                        "confidence": "high",
                    }
                )
            ],
            verifier_a=[json_reply({"checked": ["x"], "objections": []})],
            verifier_b=[json_reply({"checked": ["y"], "objections": []})],
            confirmer=[json_reply({"upheld": True, "why": "a definition asserts nothing"})],
        )
        report = verify_role.verify(project, "t", registry=registry, level="standard")
        assert report.verdict == "flagged"
        assert report.references_flagged == 1
        assert any(f.kind == "citation-misuse" for f in report.flags)
        assert report.record.references["flagged"] == 1
        assert any("citation" in r for r in report.reasons)

    def test_a_sound_citation_passes_and_is_listed_as_checked(self, project):
        citing_pair(
            project,
            cited_statement="\\begin{equation}\\label{eq:ok} \\|u\\| \\le C \\end{equation}",
            citing_statement="By \\eqref{eq:ok} the norm is finite.",
        )
        registry = scripted_registry(
            project,
            extractor=[json_reply({"claims": []})],
            obligation=[json_reply({"entails": True, "why": "it gives exactly that", "confidence": "high"})],
            verifier_a=[json_reply({"checked": ["x"], "objections": []})],
            verifier_b=[json_reply({"checked": ["y"], "objections": []})],
        )
        report = verify_role.verify(project, "t", registry=registry, level="standard")
        assert report.verdict == "verified"
        assert report.references_checked == 1
        assert any("citation" in c for c in report.checked)
        assert report.record.references == {
            "total": 1, "verified": 1, "flagged": 0, "circular": 0, "cached": 0
        }

    def test_citations_are_checked_at_standard_not_only_at_deep(self, project):
        """A citation is as load-bearing as a hypothesis, so it belongs with the
        discharge obligations rather than with the optional extras."""
        assert "references" in verify_role.jobs_for(verification.STANDARD)
        assert "references" in verify_role.jobs_for(verification.DEEP)
        assert "references" not in verify_role.jobs_for(verification.QUICK)

    def test_the_answer_is_cached_on_the_content_hash(self, project):
        citing_pair(
            project,
            cited_statement="\\begin{equation}\\label{eq:d} a=b \\end{equation}",
            citing_statement="By \\eqref{eq:d}, done.",
        )
        common = dict(
            extractor=[json_reply({"claims": []})],
            verifier_a=[json_reply({"checked": ["x"], "objections": []})],
            verifier_b=[json_reply({"checked": ["y"], "objections": []})],
        )
        first = scripted_registry(
            project,
            obligation=[json_reply({"entails": True, "why": "yes", "confidence": "high"})],
            **common,
        )
        verify_role.verify(project, "t", registry=first, level="standard")
        # No obligation response scripted: it must come from cache.
        second = scripted_registry(project, **common)
        report = verify_role.verify(project, "t", registry=second, level="standard")
        assert report.references_cached == 1
        assert report.verdict == "verified"


class TestTheCircularityRule:
    """*A child may refer to a parent's equation; it may never use it as a fact.*

    The reason is a loop with no bottom: the parent's proof cites the child, so if the
    child draws a fact from the parent, each rests on the other and neither is
    established — and nothing in the graph shows it, because each step looks locally
    fine.

    The split cannot be made deterministically: whether a reference *identifies* or
    *asserts* is a fact about the prose. So code enumerates the loop candidates and an
    agent judges each one, which is the usual division of labour here.
    """

    def _upward(self, project):
        """A child whose statement points at its parent's display."""
        write_node(
            project, "parent", target=True, children=["child"], proof="By `child`.",
            statement="\\begin{equation}\\label{eq:riccati} z' \\ge \\kappa z^2 \\end{equation}",
            uses={"child": {"applied_to": "x", "discharges": {}}},
        )
        write_node(
            project, "child",
            statement="Let $z$ be as in \\eqref{eq:riccati}. Then $z$ blows up.",
            proof="An argument.",
        )
        return graph_of(project)

    def test_the_relation_is_computed_deterministically(self, project):
        g = self._upward(project)
        assert xref.relation(g, "child", "parent") == xref.ANCESTOR
        assert xref.relation(g, "parent", "child") == xref.DESCENDANT
        assert xref.relation(g, "child", "child") == xref.SELF

    def test_an_upward_citation_is_marked_as_such_on_the_record(self, project):
        g = self._upward(project)
        record = xref.reference_obligations_for(g["child"], g)[0]
        assert record["relation"] == xref.ANCESTOR

    def test_the_hash_moves_when_the_relation_moves(self, project):
        """Re-parenting changes the question from "does it support this" to "is this a
        loop", so the cached answer to the old question must not be reused."""
        g = self._upward(project)
        before = xref.reference_obligations_for(g["child"], g)[0]["hash"]
        ops.set_children(project, "parent", [])
        g2 = graph_of(project)
        after = xref.reference_obligations_for(g2["child"], g2)[0]["hash"]
        assert after != before

    def _run(self, project, used_as_fact, why):
        registry = scripted_registry(
            project,
            extractor=[json_reply({"claims": []})],
            obligation=[json_reply({"used_as_fact": used_as_fact, "why": why,
                                    "confidence": "high"})],
            verifier_a=[json_reply({"checked": ["x"], "objections": []})],
            verifier_b=[json_reply({"checked": ["y"], "objections": []})],
            confirmer=[json_reply({"upheld": True, "why": why})],
        )
        return verify_role.verify(project, "child", registry=registry, level="standard")

    def test_referring_only_is_allowed(self, project):
        """Naming the object under discussion is not assuming anything about it."""
        self._upward(project)
        report = self._run(project, False, "it only says which z is meant")
        assert report.verdict == "verified"
        assert report.circular_citations == 0
        assert any("names it, does not assume it" in c for c in report.checked)

    def test_using_it_as_a_fact_is_a_loop_and_flags_the_node(self, project):
        self._upward(project)
        report = self._run(
            project, True, "the growth bound is taken from the parent as a premise"
        )
        assert report.verdict == "flagged"
        assert report.circular_citations == 1
        flag = next(f for f in report.flags if f.kind == "circular-citation")
        # The graph fact lives in `context`, which confirmation does not rewrite — for
        # a loop it is the part the reader most needs and the part a model restating
        # the objection is least likely to reproduce.
        assert "rests on this node" in flag.context
        assert "loop with no bottom" in flag.context
        assert flag.to_record()["context"] == flag.context
        assert report.record.references["circular"] == 1

    def test_the_reason_says_it_is_a_loop_not_a_weak_step(self, project):
        """A circular citation and a citation that merely fails to support its use are
        different failures, and conflating them would send the user to fix the wrong
        thing."""
        self._upward(project)
        report = self._run(project, True, "it is consumed as a hypothesis")
        text = " ".join(report.reasons)
        assert "circular citation" in text
        assert "neither is established" in text

    def test_an_upward_citation_is_asked_the_circularity_question(self, project):
        """Asking a loop candidate "does the cited text support this use" gets "yes,
        the parent asserts it" — true, and exactly the wrong answer."""
        self._upward(project)
        seen: list[str] = []
        registry = scripted_registry(
            project,
            extractor=[json_reply({"claims": []})],
            obligation=[json_reply({"used_as_fact": False, "why": "names only",
                                    "confidence": "high"})],
            verifier_a=[json_reply({"checked": ["x"], "objections": []})],
            verifier_b=[json_reply({"checked": ["y"], "objections": []})],
        )
        agent = registry.agent("obligation")
        original = agent.invoke
        agent.invoke = (  # type: ignore[method-assign]
            lambda s, u, t, _o=original: (seen.append(s + "\n" + u), _o(s, u, t))[1]
        )
        verify_role.verify(project, "child", registry=registry, level="standard")
        assert seen
        assert "checking one citation for **circularity**" in seen[0]
        # The graph fact has to be in the prompt: the model cannot see the graph.
        assert "own proof cites" in seen[0]

    def test_a_downward_citation_still_gets_the_support_question(self, project):
        write_node(
            project, "parent", target=True, children=["child"],
            proof="By `child` and \\eqref{eq:kid} we are done.",
            statement="A theorem.",
            uses={"child": {"applied_to": "x", "discharges": {}}},
        )
        write_node(project, "child",
                   statement="\\begin{equation}\\label{eq:kid} \\|u\\| \\le C \\end{equation}")
        seen: list[str] = []
        registry = scripted_registry(
            project,
            extractor=[json_reply({"claims": []})],
            obligation=[json_reply({"entails": True, "why": "yes", "confidence": "high"})],
            verifier_a=[json_reply({"checked": ["x"], "objections": []})],
            verifier_b=[json_reply({"checked": ["y"], "objections": []})],
        )
        agent = registry.agent("obligation")
        original = agent.invoke
        agent.invoke = (  # type: ignore[method-assign]
            lambda s, u, t, _o=original: (seen.append(s), _o(s, u, t))[1]
        )
        report = verify_role.verify(project, "parent", registry=registry, level="standard")
        assert report.verdict == "verified"
        # The circularity prompt has a distinctive opening; the support prompt does not
        # (it does mention circularity among its failure modes, which is fine).
        assert seen and "checking one citation for **circularity**" not in seen[0]

    def test_the_rule_reaches_the_roles_that_write_and_read_the_text(self, project):
        from bp.roles import context as context_mod

        g = self._upward(project)
        block = context_mod.xref_block(g, g["child"])
        assert "above" in block
        assert "never be used as a fact" in block

    def test_XRF003_states_the_rule_rather_than_only_the_consequence(self, project):
        g = self._upward(project)
        d = by_code(xref.check_xref(g), "XRF003")
        assert len(d) == 1
        assert "must not be used as a fact" in d[0].message
        assert "never" in (d[0].hint or "")

    def test_hoisting_the_display_removes_the_problem(self, project):
        """The documented fix, tested — otherwise the advice is untested advice."""
        write_node(project, "parent", target=True, children=["setting", "child"],
                   proof="By `setting` and `child`.", statement="A theorem.",
                   uses={"setting": {"applied_to": "x", "discharges": {}},
                         "child": {"applied_to": "x", "discharges": {}}})
        write_node(project, "setting", role="definition",
                   statement="\\begin{equation}\\label{eq:riccati} z' \\ge \\kappa z^2 \\end{equation}")
        write_node(project, "child", children=["setting"],
                   statement="Let $z$ be as in \\eqref{eq:riccati}. Then $z$ blows up.",
                   proof="An argument.",
                   uses={"setting": {"applied_to": "x", "discharges": {}}})
        g = graph_of(project)
        assert by_code(xref.check_xref(g), "XRF003") == []
        assert xref.relation(g, "child", "setting") == xref.DESCENDANT


class TestPreambleDefaults:
    """What the renderer adds around your preamble, extracted from the template.

    You cannot avoid a collision you cannot see, and "your preamble wins" is only
    reassuring once you can see what it is winning against. Extracted rather than
    listed by hand, because a hand-written list is a list that goes stale — and the
    whole value here is that the user can trust it.
    """

    def test_the_defaults_are_the_real_generated_preamble(self):
        from bp import render

        text = render.default_preamble()
        assert text.startswith("\\documentclass")
        assert "\\begin{document}" not in text
        # And it is genuinely a prefix of what a document gets.
        from bp.graph import Graph

        assert render.document(Graph([]), today="2026-01-01").startswith(text[:200])

    def test_every_package_is_listed_with_its_options(self):
        from bp import render

        packages = {p["name"]: p for p in render.preamble_facts()["packages"]}
        assert "amsmath" in packages
        assert packages["hyperref"]["options"].startswith("colorlinks")
        assert packages["geometry"]["options"] == "margin=1.15in"

    def test_optional_packages_are_marked_as_such(self):
        """An `\\IfFileExists` guard degrades; an unguarded `\\usepackage` in the
        user's own file is a hard error. The difference matters enough to show."""
        from bp import render

        packages = {p["name"]: p for p in render.preamble_facts()["packages"]}
        assert packages["enumitem"]["optional"] is True
        assert packages["amsmath"]["optional"] is False

    def test_theorem_environments_are_listed_with_their_printed_names(self):
        from bp import render

        envs = {e["name"]: e["printed_as"] for e in render.preamble_facts()["environments"]}
        assert envs == {
            "theorem": "Theorem",
            "proposition": "Proposition",
            "lemma": "Lemma",
            "definition": "Definition",
            "assumption": "Assumption",
            # Not emitted by the node document; the exposition uses them, and both
            # are behind `\@ifundefined` so a project defining its own keeps it.
            "corollary": "Corollary",
            "remark": "Remark",
        }

    def test_latex_comments_are_not_read_as_definitions(self):
        """The template *documents* the collisions it avoids, and those comments quote
        `\\newtheorem{lemma}{Lemma}`. An unfiltered scan reported it as a real
        definition, listing `lemma` twice."""
        from bp import render

        names = [e["name"] for e in render.preamble_facts()["environments"]]
        assert len(names) == len(set(names))

    def test_the_renderers_own_macros_are_named_so_they_are_not_redefined(self):
        from bp import render

        macros = render.preamble_facts()["macros"]
        assert "\\bpmark" in macros
        assert "\\bphyp" in macros

    def test_the_user_preamble_is_injected_before_the_options(self, project):
        """The ordering guarantee, tested rather than asserted in a comment: a user's
        `\\newtheorem{lemma}` and `\\usepackage[hidelinks]{hyperref}` must come first,
        or they collide and nothing compiles."""
        from bp import ops, render

        write_node(project, "t", target=True, statement="A theorem.")
        ops.set_preamble(project, "% MINE\n\\newtheorem{lemma}{Lemma}\n")
        text = render.document(
            graph_of(project), preamble=ops.read_preamble(project), today="2026-01-01"
        )
        # The real directives, not the header comment that explains them — the
        # comment mentions `\PassOptionsToPackage` and would match first.
        assert text.index("% MINE") < text.index(
            "\\PassOptionsToPackage{margin=1.15in}{geometry}"
        )
        assert text.index("% MINE") < text.index("\\@ifundefined{lemma}{\\newtheorem")
        # And amsmath is before it, so a user's \DeclareMathOperator works.
        assert text.index("\\usepackage{amsmath}") < text.index("% MINE")
