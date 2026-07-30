# ADDENDUM A to LIGHT.md

Read this alongside `LIGHT.md`. Where the two conflict, this document wins. It is
self-contained: you do not need to re-read `LIGHT.md` to act on it, though you should keep
following its working agreements, non-negotiables, and milestone gates.

**If your copy of `LIGHT.md` already contains a "Discharge check" section with codes
`DIS010`–`DIS016`, skip Part 1.** Everything from Part 2 onward is new regardless.

---

## Intent

Two changes, one small and one structural.

The small one: statements now list their hypotheses, and any proof citing a child must name
where each of that child's hypotheses comes from. That single addition converts "the children
do not actually cover the parent" from an invisible failure into a hard error, which is the
highest-value check available at this scale.

The structural one: every mathematical judgement in this system is made by an agent, and agent
judgement is unsound. The response is **not** more verifiers. It is to make each question as
narrow as possible and to enumerate the questions deterministically, so that a clean verdict
means "all N enumerated checks passed" rather than "nothing caught my eye."

The governing principle for the whole system:

> **Agents supply judgement. Code supplies the guarantee that the judgement was complete.**

Whether a claim is true cannot be checked deterministically. That every claim was enumerated,
assigned a source, and dispatched to a verifier *can* be, and must be.

| Question | Answered by |
|---|---|
| Do the children exist, is the graph acyclic | code |
| Is every child mentioned in the proof | code |
| Does every child hypothesis have a named source | code (`DIS011`) |
| Does the named source actually give that hypothesis | **agent** — obligation check |
| Is every load-bearing claim in the proof sourced at all | code (`LED001`), over an agent-produced ledger |
| Is each sourced claim justified by its source | **agent** — claim check |
| Does the parent follow from the children's conclusions | **agent** — whole-proof pass |
| Is the statement well-posed, non-vacuous, correctly quantified | **agent** — statement audit |
| Which nodes are proved, given all of the above | code — propagation sweep |

No agent role is ever asked an open question like "is this proof correct." Every role consumes
a deterministically generated worklist and returns a structured verdict against it.

---

## Part 1 — Discharge checking

### Node format additions

```yaml
# hypotheses of THIS node's statement, referenced by parents that cite it
hypotheses:
  - {id: H1, tex: "s > 3/2"}
  - {id: H2, tex: "\\|\\omega_0\\|_{H^s} \\le \\varepsilon_0"}

# for each child cited in the proof, where each of ITS hypotheses comes from
uses:
  mff.elb-a:
    applied_to: "\\omega(t) \\text{ for } t \\in [0,T)"   # free text, not checked
    discharges:
      H1: "hypothesis:H1"          # a hypothesis of THIS node
      H2: "child:mff.elb-b"        # the conclusion of a sibling
  mff.elb-b:
    applied_to: "\\omega_0"
    discharges:
      H1: "hypothesis:H1"
      H2: "ADMITTED: needs a continuation argument not yet written"
```

Statement bodies and proofs remain **free LaTeX prose**. This is the only structure borrowed
back from the full design in `DESIGN.md`.

### `bp/discharge.py`

Implement exactly this. Do not improvise it.

```python
SOURCE_RE = re.compile(r"^(hypothesis|child|proof|literature|ADMITTED)(:(.*))?$")

def check_discharge(node, graph) -> list[Diagnostic]:
    d = []
    own_hyps = {h.id for h in node.hypotheses}

    for cid in node.children:
        entry = node.uses.get(cid)
        if entry is None:
            d.append(err("DIS010", node,
                f"child {cid} is cited but has no `uses` entry",
                hint=f"add uses.{cid}.discharges naming a source for each of its hypotheses"))
            continue

        child = graph[cid]
        for h in child.hypotheses:
            src = entry.discharges.get(h.id)
            if not src:
                d.append(err("DIS011", node,
                    f"{cid} hypothesis {h.id} ({h.tex}) is not discharged",
                    hint="name where this hypothesis comes from, or mark it ADMITTED"))
                continue

            m = SOURCE_RE.match(src.strip())
            if not m:
                d.append(err("DIS012", node,
                    f"{cid}.{h.id}: source {src!r} is not a recognised form",
                    hint="use hypothesis:<id> | child:<id> | proof:<free text> | "
                         "literature:<ref> | ADMITTED: <reason>"))
                continue

            kind, _, arg = m.groups()
            if kind == "hypothesis" and arg not in own_hyps:
                d.append(err("DIS013", node,
                    f"{cid}.{h.id}: {node.id} has no hypothesis {arg!r}"))
            elif kind == "child" and arg not in node.children:
                d.append(err("DIS014", node,
                    f"{cid}.{h.id}: {arg!r} is not a declared child of {node.id}",
                    hint="add it to `children`, or discharge from something in scope"))
            elif kind == "ADMITTED" and not (arg or "").strip():
                d.append(err("DIS015", node, f"{cid}.{h.id}: ADMITTED needs a reason"))

    for cid in node.uses:
        if cid not in node.children:
            d.append(warn("DIS016", node, f"`uses` mentions {cid}, which is not a child"))
    return d
```

`proof:` and `literature:` sources take free text and are not structurally checked — they exist
so a hypothesis established inline, or cited from the literature, carries an honest label rather
than being silently omitted.

An `ADMITTED` discharge caps the parent's `local_status` at `admitted` and puts its id into the
support set. A hypothesis you cannot source becomes visible debt, not a hidden gap.

### Obligation emission

`bp obligations <node>` emits one record per discharge:

```json
{ "id": "ob:mff.energy-lower-bound:mff.elb-a:H2",
  "kind": "discharge",
  "parent": "mff.energy-lower-bound",
  "child": "mff.elb-a",
  "applied_to": "\\omega(t) \\text{ for } t \\in [0,T)",
  "needed": "\\|\\omega_0\\|_{H^s} \\le \\varepsilon_0",
  "claimed_source": "child:mff.elb-b",
  "source_text": "<statement of mff.elb-b>",
  "hash": "…" }
```

Cache verifier results on `hash`, so editing one part of a proof does not re-bill the rest.

### Decomposer prompt changes

The decomposer must now return, per child: statement prose, difficulty, **and an explicit
`hypotheses` list**. Plus the parent's reduction proof **and a complete `uses` table** naming a
source for every hypothesis of every child.

This is the most demanding part of the schema and where most of your prompt iteration will go.
State explicitly in the prompt, with an example, that a hypothesis it cannot source must be
written as `ADMITTED: <reason>` and never omitted.

Expect the discharge check to reject a substantial fraction of first attempts. That is the
mechanism working. Feed diagnostics back and allow two repair rounds before surfacing to the
user.

### Checker: three calls become two

Keep questions 1 and 2 (does the reduction establish the parent; is any child a restatement of
or as hard as the parent). **Delete question 3** — "are the hypotheses each child needs
available" — which is now handled by the discharge check for completeness and by obligation
verification for entailment. Do not ask it twice.

---

## Part 2 — Claim ledger

The `uses` table covers the *children's* hypotheses. It says nothing about claims the reduction
makes on its own account. A proof that says "by standard elliptic regularity, $\omega \in C^1$,
hence…" has a load-bearing claim with no child, no hypothesis, and no entry anywhere. That is
premise smuggling in its purest form and it is the dominant failure mode in research-level
output. The ledger closes it.

### New role: extractor

Cheap model. Given a proof, return every load-bearing claim with the source the prose offers:

```json
{"claims": [
  {"id": "c1", "text": "\\omega \\in C^1([0,T))",
   "source": {"kind": "literature", "ref": "standard elliptic regularity"}},
  {"id": "c2", "text": "\\|\\omega(t)\\|_{H^s} \\le \\varepsilon_0 \\text{ for } t < T",
   "source": {"kind": "child", "ref": "mff.elb-b"}},
  {"id": "c3", "text": "the map \\Phi is a contraction on B_R",
   "source": {"kind": "none"}}
]}
```

`kind ∈ {hypothesis, child, claim, literature, computation, none}`.

This is a **translation** task, not a judgement task, which is why a cheap model suffices and
why the output is reliable. Instruct it explicitly that `none` is the correct answer for an
unjustified claim, and that inventing a plausible source is the one unacceptable outcome.

The ledger is stored under `claims:` in the node and is a **computed field** — regenerated when
the proof text changes, never hand-edited, never written by any other role.

### `bp/ledger.py` — deterministic audit

| Code | Sev | Catches |
|---|---|---|
| `LED001` | error | claim with `source.kind: none` — an unsourced load-bearing claim |
| `LED002` | error | `child` source naming an id not in `children` |
| `LED003` | error | `hypothesis` source naming an id not in this node's `hypotheses` |
| `LED004` | error | `claim` source naming a later claim, or itself |
| `LED005` | warn | `literature` source with no identifiable reference |
| `LED006` | warn | `computation` source with no artifact path |

Together with `DIS011`, this means no load-bearing claim anywhere in a proof can go unsourced
without producing a hard error.

It also gives the verifier's verdict a completeness guarantee. "No objection" now means "all 11
enumerated claims were checked," not "nothing caught my eye."

Emit one obligation record per ledger claim whose source is not `none`, with
`kind: "claim"` and the same shape as the discharge records.

---

## Part 3 — Verifier: three jobs, separately cached

Replace the existing verifier role with three jobs. Keep them separate; do not merge the
prompts.

1. **Obligation checks.** Consume discharge records one at a time: does `source_text` give you
   `needed`, for the object in `applied_to`? This is the misattribution check — the answer to
   "the table says `H2` comes from `H_init`, but does it?" No proof search, no strategy, no
   whole-proof context.
2. **Claim checks.** One record per ledger claim with a non-`none` source: does the named source
   justify this claim, as applied here? Same narrow shape.
3. **Whole-proof pass.** Given the statement, the proof, and the children's statements **as
   assumptions**, return a located objection `{section, quote, class, why}` or `no_objection`.
   This catches what per-claim checking cannot: gaps *between* individually correct claims, and
   whether the claims collectively reach the conclusion. Two backends from different families,
   no shared context.

Then one **confirmation pass** over every objection from any of the three: re-present it with
surrounding context; if the flaw dissolves, downgrade it to a note. Do not skip this — without
it, pedantic over-rejection produces enough noise that the user stops reading the output.

---

## Part 4 — New role: statement auditor

One call per statement, independent of any proof. Four questions, returned as a structured
verdict rather than prose:

1. Is the statement well-posed — is every symbol bound, is the conclusion unambiguous?
2. Exhibit a concrete instance satisfying every hypothesis, or report that you cannot. A
   statement whose hypotheses cannot be jointly satisfied is vacuous.
3. Are the quantifiers in the intended order? Flag any `∀ε ∃δ` versus `∃δ ∀ε` ambiguity.
4. Does any constant depend, directly or transitively, on something the statement treats it as
   uniform in?

This is the agent stand-in for the deterministic `VAC` and `CST` checks specified in
`DESIGN.md` §8, which v0 defers. It is weaker than those — it cannot be relied on the way a
scope check can — but question 4 catches the classic bootstrap error often enough to justify the
call.

---

## Part 5 — Tiered recompile and cost control

Agent-checking every claim is expensive: a node with a ten-claim proof runs roughly fifteen
calls at full depth, so a thirty-node graph is several hundred. Recompile must be tiered.

| `--level` | Runs | Use for |
|---|---|---|
| `quick` | deterministic checks, whole-proof pass | fast sanity check while iterating |
| `standard` (default) | + extraction, ledger audit, obligation checks | routine work |
| `deep` | + per-claim checks, statement audits, confirmation on everything | before trusting a subtree, or before writing it up |

All of the following are required, not optional:

- **Cache on content hash.** Every obligation and claim record carries a hash; an unchanged
  record is never re-billed. Editing one paragraph must not re-verify the rest of the proof.
- **Batching.** `--batch N` sends N obligation or claim checks per call. **Default 1.** Batching
  trades reliability for cost; make it opt-in.
- **Model tiering.** Extraction on the cheap model; obligation and claim checks on a mid model;
  whole-proof pass and confirmation on the strong model. Configurable per role in `bp.yaml`,
  which the role registry already supports.
- **`--dry-run`** lists the calls it would make, by role, with estimated cost and time.
- **Value ordering.** Nodes on the path to the target first, then the frontier, then the rest. A
  run stopped by `--budget` should have spent its money where it mattered.

---

## Part 6 — The verification record

`local_status: verified` must not be an opaque flag. Each node carries a computed record of what
was actually checked:

```yaml
verification:
  checked_at: 2026-08-03T14:22:00Z
  level: standard
  deterministic: {integrity: pass, children_used: pass, discharge: pass, ledger: pass}
  ledger:       {claims: 11, unsourced: 0, checked: 0}      # checked: 0 at `standard`
  obligations:  {total: 7, verified: 6, flagged: 1, cached: 4}
  whole_proof:  {verifier_a: no_objection, verifier_b: objection_confirmed}
  statement_audit: not_run
  models: {extractor: haiku-4.5, obligation: sonnet-5, whole_proof: opus-5}
```

Add `bp/verification.py`, which assembles this record and **derives** `local_status` from it:
`verified` requires zero deterministic errors, zero unsourced claims, no confirmed objections,
and no flagged obligations. Anything else is `flagged`.

**No role may set `local_status` directly.** This is a hard rule.

The renderer prints a compact form of the record per node, so reading the LaTeX tells you how
much scrutiny each lemma actually received. A node verified at `quick` and one verified at
`deep` are not the same claim, and collapsing them to one colour would be dishonest.

---

## Part 7 — Do not do these

- **Do not add more verifiers.** Reported false-positive rates for LLM verification stay in the
  same band across cross-model and conjunction-of-verifier setups. The returns come from
  narrowing questions and guaranteeing coverage, not from ensembling. If verification
  disappoints, narrow the questions further or add a deterministic check — do not add a fourth
  model.
- **Do not ask any agent an open-ended validity question.** Every role gets a worklist and a
  structured output schema.
- **Do not let any agent write `global_status`, `support`, `statement_hash`,
  `verified_against`, `claims`, or `local_status`.** All computed.
- **Do not have an agent maintain the LaTeX document.** It is rendered from the node files by a
  Jinja template. An agent-maintained document will drift from the graph, and since the document
  is what the user reads, they would be reading a plausible fiction of their own proof.
- **Do not merge the three verifier jobs** into one prompt to save calls. Use `--level` for cost
  control instead.

---

## Part 8 — Revised milestone assignments

**Into L0** (deterministic, no agents):

- `bp/discharge.py` — `DIS010`–`DIS016` plus discharge-obligation emission
- `bp/ledger.py` — `LED001`–`LED006` plus claim-obligation emission. The *audit* only; the
  extractor that produces the ledger is an agent and arrives in L1, so write the audit against a
  hand-written ledger fixture.
- `bp/ops.py` gains `set_uses`
- `bp/cli.py` gains `obligations`

**Into L1** (agents): six roles, not four — `decompose`, `check`, `extract`, `verify`, `audit`,
`prove`. Each prompt in its own `prompts/<role>.md` so the user can tune prompts without
touching code; prompt iteration is where most of the quality comes from.

Also in L1: `bp/recompile.py` with the three levels, per-record caching, `--batch`, `--budget`,
`--dry-run`, value ordering, job records, `bp resume`. And `bp/verification.py`.

CLI after L1: `bp expand <node> [--hint "..."]`, `bp redo <node>`, `bp check-decomp <node>`,
`bp extract <node>`, `bp verify <node> [--level L]`, `bp audit <node>`, `bp prove <node>`,
`bp recompile [--level L] [--dry-run] [--budget N] [--batch N]`, `bp resume`.

---

## Part 9 — Revised acceptance criteria

**L0.** Hand-write a 6-node DAG including one admitted node, one deliberately stale node, one
node with a **missing discharge**, one with an `ADMITTED` discharge, and one hand-written ledger
fixture containing an unsourced claim. Then:

```
bp check          # DIS010-016 and LED001-006 fire exactly as intended, nothing spurious
bp obligations    # one record per discharge and per sourced claim, stable hashes
bp status         # global statuses correct by hand-inspection
bp why <target>   # chain reads as plain, correct English
bp render         # LaTeX that compiles and that a mathematician would read
pytest -q         # propagation assertions hold on random graphs
```

**L1.** On a real target supplied by the user:

- `bp expand` produces 3–7 children with difficulty labels, hypotheses, and a complete `uses`
  table. **Report how many first attempts the discharge check rejected** — this number tells the
  user how much the check is earning.
- `bp extract` on a proof containing one deliberately unsourced claim: `LED001` fires on exactly
  that claim and nothing else.
- `bp verify --level deep` on a proof with a deliberate misattribution, where the `uses` table
  names a source that does not give the hypothesis: that obligation is flagged.
- `bp recompile --dry-run` at each of the three levels shows plausibly different call counts and
  costs.
- Edit one paragraph of a proof, recompile, and confirm from the agent log that unchanged
  obligations and claims were **cache hits**.
- Kill a recompile mid-run; `bp resume` re-queries nothing already done, verified from the log.
- `--replay` works with no network.
- `bp show <node>` displays the verification record, and `local_status` matches what the record
  implies.

---

## Part 10 — Documentation requirement

`ARCHITECTURE.md` must contain a section, in your own words, on what the system guarantees and
what it does not. A user who misjudges what a green node means will over-trust it, and that is
the worst outcome this system can produce. Cover:

**What the deterministic layer guarantees.** The graph is acyclic; status propagation is
correct; a verification is invalidated when a statement it depended on changes; every child
hypothesis and every extracted claim has a named source or a hard error; every source produced
an obligation record and every record was dispatched. Complete bookkeeping, no mathematical
content.

**What the agent layer contributes, and its ceiling.** Every mathematical judgement in the
system. The design narrows each question and enumerates the questions deterministically, because
narrow questions with a complete worklist is the best available configuration for LLM
verification — but it remains unsound. A green node means *"no agent found a problem in N
enumerated checks at level L"*, never *proved*. The verification record exists so this is
legible rather than hidden.

**Where agent substitutes are weakest.** The statement auditor stands in for `VAC` and `CST`.
It will miss circular constant dependencies a scope check would catch mechanically, and its
vacuity answer is an assertion rather than a construction. Its verdicts are prompts for the
user's attention, not checks.

Then update `UPGRADE.md` with a row for each still-deferred piece — LaTeX normalization,
constant tables (`DESIGN.md` §8 `CST001`–`CST002`), vacuity witnesses, numeric sweeps
(`NUM001`–`NUM004`), typed step justifications, the strategy slot library, Lean — giving for
each: the `DESIGN.md` section, which v0 modules it would touch, rough effort, and the signal
indicating it is now needed.
