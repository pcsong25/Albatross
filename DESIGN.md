# Blueprint — an interactive proof decomposition and verification system

Design specification, v1. This document is the reference for implementation. It is
normative: where an implementation choice is not stated here, prefer the simplest
option consistent with the invariants in §1 and record the decision in `DECISIONS.md`.

---

## 0. Purpose and scope

A research assistant for mathematics, in the spirit of Lean's `blueprint` tooling but
operating on natural-language mathematics with LLM verifiers in place of a kernel.

The system does three things:

1. **Decompose** a target theorem into a DAG of subproblems, under human steering.
2. **Check** the decomposition and any supplied proofs with deterministic structural
   analysis.
3. **Verify** the residual semantic obligations with adversarial LLM verifiers.

The human is the regulator. Every control decision — expand, redo, fold, abandon, edit,
recompile — is a user action, not an agent decision. There is no autonomous control loop.

**Not in scope for v1:** automated proof generation for hard leaves; corpus ingestion and
research-problem proposal; rigorous validated numerics beyond a falsification sweep;
automated iteration control.

**Design bet.** A sound compiler is unavailable, so the strategy is to factor the
compiler's job into (a) a large deterministic fragment with zero false accepts, (b) an
optional Lean skeleton for logical form, and (c) a small residue of genuinely semantic
questions handed to LLMs one at a time. The value of the system is mostly in (a) and in
the completeness of the worklist handed to (c).

---

## 1. Invariants

These are load-bearing. Resolve any later design question by checking against them.

1. **Structured form is primary.** Human-readable statements are *rendered* from the
   structured form. There is no second representation that can drift. Free prose lives
   only in `remark` and `note`, which carry no obligations and are never parsed.
2. **The graph is the only durable state.** Agents are pure functions: read node → emit
   artifact → write node. No agent-to-agent conversation. No hidden memory.
3. **Three verification layers, never conflated.** Deterministic checks (sound, narrow);
   Lean skeleton (sound, structural, optional); LLM panel (unsound, calibrated). Every
   node records which layers certified it.
4. **Intrinsic vs derived status.** Only agents and humans write intrinsic status. Only
   the engine writes derived status. Separate tables. Never merge them.
5. **Only statements have signatures.** Only a statement edit invalidates a verification.
   Proving, refuting, objecting and admitting are handled entirely in the derived layer.
6. **Support sets, not booleans.** The output is "T holds relative to these six items."
7. **`ADMITTED` is legal and loud.** The system makes debt visible; it does not forbid it.
8. **The deterministic layer enumerates the semantic worklist.** Code decides which
   questions exist; LLMs only answer them.
9. **Mutation testing is the acceptance gate** for every component.
10. **No user operation destroys information.** Retire and archive, never delete. The
    event log is append-only; node files are in git.
11. **Derived state is disposable.** `index.sqlite` is rebuildable from `events.jsonl`
    plus the YAML node files at any time. It is never a source of truth.

---

## 2. Node model

### 2.1 Kinds

Four kinds, deliberately few. `lemma`/`proposition`/`theorem`/`corollary` are a cosmetic
`role` attribute, not kinds — making them kinds invites kind-specific logic that will be
wrong.

| Kind | Carries obligation | Notes |
|---|---|---|
| `def` | sometimes | Definitions in analysis spawn well-definedness obligations ("let `T*` be the first time the bound fails" needs nonemptiness and positivity). Model these as auto-generated `stmt` nodes owned by the `def`. |
| `stmt` | yes | `role: lemma \| prop \| thm \| cor` is display only. |
| `assume` | no, by design | A deliberate standing hypothesis: an unproved conjecture, a numerically observed spectral gap being conditioned on. Distinct from admitted — "Theorem, assuming C" is a legitimate paper; admitted is debt. |
| `proof` | — | Targets exactly one `stmt`. `kind: prose \| computation \| formal`. Several may compete for one target. |

Plus `note`: strategy commentary, excluded from all propagation, usable as agent context.

**A reduction is not a node kind.** A reduction is a proof of the parent that cites the
children. There is no structural difference between "the reduction argument" and
"Lemma 4's proof". Leaf vs internal is derived: a statement is a leaf iff its chosen proof
cites no other statements.

**Competing proof nodes give AND-OR structure for free.** A statement with three proof
nodes is an OR; each proof's cite list is an AND. Two proofs of the target citing disjoint
children *are* two competing decompositions. Strategy-level parallelism needs no
additional data structure.

### 2.2 Intrinsic status — written by agents or humans

```
stmt.form      : draft | well_formed | ill_formed(errors)
stmt.truth     : unknown | refuted(counterexample_artifact)
stmt.lifecycle : active | archived

proof.local    : draft          # written, not yet structured
               | structured     # schema-valid
               | linted         # deterministic checks pass
               | verified       # verifier panel found no located objection
               | flagged(objections)
               | rejected(reason)
               | stale(changed_deps)
               | retired
proof.preference : normal | deprefer
```

`proof.local` means exactly one thing: *this proof correctly derives its target from its
cited statements, taken as hypotheses.* It says nothing about whether those statements are
true or proved. That separation is the core of the design.

### 2.3 Derived status — written only by the engine

```
stmt.chosen_proof : proof_id | none
stmt.support      : set of support items
stmt.global       : open | blocked(reason) | proved | proved_modulo(support) | unsound
stmt.frontier     : bool
stmt.depth, stmt.fan_in, stmt.fan_out
```

---

## 3. Schemas

YAML, one file per node, under `nodes/`. Git is the source of truth.

### 3.1 Statement

```yaml
id: gclm.energy-lower-bound
kind: stmt                    # def | stmt | assume
role: lemma                   # cosmetic
lifecycle: active
binders:
  - {sym: a,      type: real,        constraints: "0 < a < 1/2", uniform_in: []}
  - {sym: omega0, type: "H^s(S^1)",  constraints: "odd, s > 3/2", uniform_in: [a]}
hypotheses:
  - {id: H1, tex: "\\omega_0'(0) < 0", check: null}
  - {id: H2, tex: "\\|\\omega_0\\|_{H^s} \\le \\epsilon_0(a)", check: null}
conclusion: "\\exists T_* < \\infty : \\lim_{t \\to T_*} \\|\\omega(t)\\|_{L^\\infty} = \\infty"
constants:
  - {sym: epsilon_0, depends_on: [a], uniform_in: [omega0]}
defs_used: [gclm.def-solution]
params_used: [rate]           # named holes in the target template this node depends on
witness: {a: "0.25", omega0: "-sin(x)"}
numeric_form: null
difficulty: hard              # standard | routine | hard | computational
anchor: null                  # required when difficulty == standard
remark: "free prose, never parsed"
```

`check` is an optional sympy-evaluable predicate used by the vacuity checker.
`numeric_form` is `{expr, vars: {name: [lo, hi]}, sense: ">=" | "<=" | "=="}`.
`anchor` is `{id: "arXiv:1234.5678", locator: "Thm 2.3", quoted: "..."}`.

### 3.2 Proof

```yaml
id: gclm.energy-lower-bound.pf2
target: gclm.energy-lower-bound
kind: prose                   # prose | computation | formal
strategy: bootstrap           # id from strategies/, or "custom"
provenance: agent:codex       # human | human_revised | agent:<backend>
preference: normal
steps:
  - id: S1
    claim: "..."
    justification:
      kind: cite
      node: gclm.wick-bound
      substitution: {x: "\\omega(t)", delta: "\\epsilon_0/2"}
      discharges: {A1: "hypothesis:H2", A2: "step:S0"}
  - id: S2
    claim: "..."
    justification:
      kind: literature
      anchor: {id: "arXiv:1234.5678", locator: "Thm 2.3", quoted: "..."}
  - id: S3
    claim: "..."
    justification:
      kind: ADMITTED
      reason: "needs coercivity of the linearised operator"
```

Justification kinds, as a **discriminated union on `kind`** — pydantic rejects anything
else at parse time. There is no free-text escape:

| kind | Fields |
|---|---|
| `cite` | `node`, `substitution`, `discharges` |
| `hypothesis` | `ref` |
| `step` | `ref` |
| `literature` | `anchor` (must include `quoted`) |
| `computation` | `artifact` (path), `tool`, `version`, `seed` |
| `ADMITTED` | `reason` (required) |

`discharges` is the load-bearing field. It is what makes premise smuggling mechanically
detectable.

### 3.3 Config

```yaml
# blueprint.yaml
agents:
  default_backend: claude_cli
  roles:
    decomposer: {backend: codex_cli,  model: gpt-5.6-sol}
    encoder:    {backend: claude_cli, model: sonnet}
    verifier_a: {backend: claude_cli, model: opus}
    verifier_b: {backend: openai_api, model: gpt-5.6}
    reviewer:   {backend: claude_cli, model: opus}
budget:
  per_recompile_usd: 5.0
  per_node_attempts: 3
  objection_rounds: 2
numerics:
  sweep_samples: 2000
  precision_dps: 40
  tolerance: 1.0e-9
hygiene:
  max_steps: 12
  max_citations: 6
  max_depth: 6
  max_hard_leaves: 3
paths: {nodes: nodes/, strategies: strategies/, state: .blueprint/}
```

---

## 4. Normalization and signatures

Bias hard toward **over-sensitivity**: unnecessary re-verification is safe, silent
staleness is not.

```python
def normalize(tex, macros, binders) -> str:
    s = strip_comments(tex)
    s = expand_macros(s, macros)             # project macros.yaml, with arguments
    s = canonicalize_synonyms(s)             # \tfrac|\dfrac→\frac, \leq→\le, \rightarrow→\to,
                                             # \lvert→|, \left(→(, drop \, \; \! \quad
    s = strip_single_token_braces(s)         # x_{i} → x_i
    s = collapse_whitespace(s)
    s = alpha_normalize(s, binders)          # each binder → #0, #1, … by position
    return s
```

`alpha_normalize` is what makes renaming `ε` to `δ` a no-op downstream. Replace the
longest symbol first; match backslash-commands with a trailing non-letter lookahead so
`a` does not match inside `\alpha`.

Signatures hash *what is claimed*, not labels:

```python
def sig(stmt):
    payload = {
      "binders":   [(b.type, N(b.constraints), sorted(b.uniform_in)) for b in stmt.binders],
      "hyps":      sorted(N(h.tex) for h in stmt.hypotheses),      # set, not list
      "concl":     N(stmt.conclusion),
      "constants": sorted((c.sym, sorted(c.depends_on), sorted(c.uniform_in))
                          for c in stmt.constants),
      "defs":      [sig(ctx.stmt(d)) for d in stmt.defs_used],
      "params":    {p: ctx.param_value(p) for p in stmt.params_used},
    }
    return sha256(canonical_json(payload)).hexdigest()
```

Hypotheses hash as a set, so reordering does not invalidate. Hypothesis **ids** are
excluded — renaming `H1` to `H2` does not change the claim, and broken references are the
dangling-reference checker's job. Do not fold these concerns together.

Proofs have no signature. Instead, on reaching `verified`:

```
proof.witnessed = { (cited_id, sig(cited_id)) at verification time }
proof.local := stale  ⟺  ∃ (id, s) ∈ witnessed : sig(id) ≠ s
```

`params_used` and the `params` term in the payload exist so that later, when target
statements become templates with typed holes, changing a hole's value invalidates only the
nodes referencing it rather than the whole tree. Provision it now; the hole mechanism
itself is out of scope for v1.

---

## 5. Support sets and derived status

Do not compute "is it proved". Compute what it rests on.

```
support(N) =
  let P = chosen_proof(N)
  if P is none or P.local ≠ verified : ⊥
  else  { ADMITTED steps of P }
      ∪ { literature anchors of P below trust tier }
      ∪ { computation artifacts of P below trust tier }
      ∪ ⋃ { {c} if kind(c) = assume else support(c) | c ∈ cites(P) }
```

Classification:

| Condition | `global` |
|---|---|
| `support = ⊥`, no proof at all | `open` |
| `support = ⊥`, proof exists but not verified | `blocked(reason)` |
| `support = ∅` | `proved` |
| `support ≠ ∅` | `proved_modulo(support)` |
| any element of `support` refuted | `unsound` |

This is the semantics of Lean's `#print axioms`, which is why the Lean-lite layer drops in
cleanly. The final report states the theorem plus its support certificate.

---

## 6. Events and propagation

Append-only event log; state is a fold over it. This yields time travel, blame, branching
for competing decompositions, and reproducible debugging.

Every event carries a UUID and is idempotent under replay.

| Event | Intrinsic effect | Cascade |
|---|---|---|
| `edit_stmt(intent)` | recompute `sig`; `form := draft` unless cosmetic | see §7 |
| `edit_def` | re-sign dependent statements, then stale their proofs | two-stage |
| `lint(node)` | `form :=`, `proof.local := linted \| structured` | none |
| `verify(P, verdict)` | `P.local := verified \| flagged` | none |
| `objection(open/upheld/withdrawn)` | `P.local := flagged \| rejected \| linted` | none |
| `refute(N, artifact)` | `N.truth := refuted` | none |
| `admit_step` / `discharge_step` | rewrite step; `P.local := structured` | none |
| `promote_step(P, s)` | new `stmt`; step becomes `cite(new)`; `P.local := structured` | none |
| `add_proof` | — | none |
| `retire_proof` | `P.local := retired` | children may orphan (warn) |
| `deprefer_proof` | `P.preference := deprefer` | none |
| `archive(N…)` | `lifecycle := archived` | none |
| `add_stmt` | — | orphan warning until cited |
| `relabel(N, difficulty)` | — | may change frontier rank |
| `assert_equivalent(old_sig, new_sig)` | rewrite `witnessed` sigs | logged trust event |

**Note what does not cascade.** Proving a lemma invalidates nothing. Refuting a lemma
invalidates nothing either — "T follows from Q" stays true when Q is false; refutation is
handled entirely in the derived layer via `support` and `unsound`. Only *restating* a
lemma invalidates: proofs of it (goal changed) and proofs citing it (tool changed).

### Recompute

```
recompute(graph):
  assert acyclic(proof_edges)                  # hard invariant, fail loudly
  for N in topological_order(active statements):
      cands = [P for P in proofs(N) if P.local ≠ retired]
      N.chosen_proof = argmax(cands, key=(status_rank, preference_rank,
                                          -len(support), recency))
      N.support  = support_formula(N)
      N.global   = classify(N)
      N.frontier = N.global in {open, blocked} and \
                   all(c.global in {proved, proved_modulo} for c in cites(chosen))
```

`status_rank` is a fixed total order, so proof selection is deterministic, not heuristic.

### Invariants asserted after every pass — these are the test suite

- proof edges acyclic; no proof of `N` cites a descendant of `N`
- `global = proved` ⟹ `support = ∅`
- any support element refuted ⟹ `global = unsound`
- `local ∈ {stale, flagged, rejected}` ⟹ `global ≠ proved`
- `support(N) ⊇ ⋃ support(c)` over the chosen proof's citations

This is a build system. Steal vocabulary and testing approach from `make` / Bazel / Salsa:
content-addressed inputs, recorded dependencies, incremental invalidation.

---

## 7. User operations

All non-destructive. Every operation is a CLI command first; the UI is a wrapper.

| Action | Event(s) | Notes |
|---|---|---|
| Expand node | `add_proof(decomposition)` | derived recompute only |
| Redo decomposition | `add_proof(new strategy)` + optional `deprefer(old)` | **additive**; prior attempt's diagnostics become negative context |
| Fold (view) | none | pure UI state, zero graph mutation — this is what the chevron does |
| Prove in one shot | `add_proof(direct, no citations)` | decomposition survives as a competing proof; switch back by preference |
| Abandon route | `retire_proof` | children may orphan; warn, do not delete |
| Sweep orphans | `archive(N…)` | nodes with no path to target; still searchable and memo-matchable |
| Edit statement | `edit_stmt(intent)` | see intents below |
| Create node | `add_stmt` | orphan warning until cited |
| Promote step → node | `promote_step` | prominent in UI; more common than creating from scratch |
| Admit step | `admit_step` | support grows, node greys |
| Supply proof | `add_proof(provenance: human)` | |
| Relabel difficulty | `relabel` | |
| Recompile | tiered run, §9 | |
| Explain status | read-only | `blueprint why <node>` |

**Expand and redo are one primitive:** `propose_decomposition(node, strategy?, mode)`,
differing only in whether a prior proof exists. One code path, one prompt template.

### Edit intents

| Intent | Engine behaviour |
|---|---|
| `cosmetic` | Assert the *normalized* signature is unchanged. If it moved, **reject the edit** and show the normalized diff. Nothing stales. |
| `refine` | Semantic change. Full cascade: proofs of it and proofs citing it → `stale`. |
| `equivalent` | Signature moved but the user asserts the claims are equivalent. Verification preserved; logged as a trust event; surfaced in the support certificate as "N nodes carry human equivalence assertions". |

The `cosmetic` check catches the real error class where you thought you were tidying
notation and actually changed the statement.

**Dry-run blast radius is mandatory** before any edit commits: which proofs go stale, how
many are currently verified, estimated recompile cost. Editing a `def` shows the two-stage
radius separately.

---

## 8. Deterministic check catalog

Run before any verifier sees a node. Compiler-style diagnostics: code, severity, node,
path, file, line, hint. `--format json`. Exit 1 on any error. A proof advances
`structured → linted` iff zero errors; warnings require a human acknowledgment recorded as
an event, so the graph does not become permanently yellow and ignored.

| Code | Sev | Catches |
|---|---|---|
| `SCH0xx` | error | Schema violation; unknown justification kind; `standard` without anchor; `ADMITTED` without reason |
| `REF001` | error | Reference to nonexistent node |
| `REF002` | error | Proof of `N` cites a descendant of `N` |
| `REF003` | error | Cycle in proof edges (report the full cycle) |
| `REF004` | error | Cycle in definition edges |
| `REF005` | warn | Statement cited by nothing and not the target |
| `REF006` | warn | Non-target statement with no proof and kind ≠ `assume` |
| `DIS001` | error | Citation does not instantiate every binder of the cited node |
| `DIS002` | error | Substitution supplies a symbol that is not a binder of the cited node |
| `DIS003` | error | Substituted term mentions a symbol not in the parent's scope |
| `DIS004` | error | A hypothesis of the cited node is not discharged |
| `DIS005` | error | Named discharge source does not exist or is out of scope |
| `DIS006` | error | Forward reference — step cites a later step |
| `DIS007` | error | `hypothesis:` ref not among the target's hypotheses |
| `DIS008` | error | `literature` justification missing anchor or quote |
| `DIS100` | info | Admitted step, with reason — tracked, never an error |
| `CST001` | error | Cycle in constant `depends_on` |
| `CST002` | error | Constant claims uniformity in something it transitively depends on |
| `CST003` | error | Symbol in a hypothesis or conclusion is neither binder, constant, nor declared global |
| `CST004` | warn | Constants declared out of dependency order |
| `CST005` | info | Uniformity contract manifest, per citation, for human review |
| `VAC001` | error | Statement has no witness |
| `VAC002` | error | Witness violates a machine-checkable hypothesis or binder constraint |
| `VAC003` | warn | Witness coverage below 50% — report which hypotheses were unchecked |
| `NUM001` | error | Falsification sweep violation beyond tolerance, with the parameters |
| `NUM002` | warn | Violations only within tolerance — likely numerical |
| `NUM003` | info | Slack exceeds 100× everywhere — constant probably very lossy |
| `NUM004` | warn | Conclusion is an inequality with explicit constants but no `numeric_form` |
| `SLT001` | error | Declared `strategy` has an unfilled mandatory slot |
| `SLT002` | error | `case_split` without an exhaustiveness node |
| `SLT003` | error | `contradiction` negation node's hypotheses ≠ parent's + ¬conclusion |
| `SLT004` | warn | Slot filled with unexpected difficulty (e.g. `hard` in a bookkeeping slot) |
| `STR001` | warn | Child signature equals an ancestor's |
| `STR002` | warn | Child is a syntactic weakening of an ancestor |
| `STR003` | warn | Decomposition of a non-`standard` target with zero `hard` leaves |
| `STR004` | warn | More than `max_hard_leaves` hard leaves — difficulty not concentrated |
| `HYG001` | warn | Proof exceeds `max_steps` |
| `HYG002` | warn | Proof cites more than `max_citations` |
| `HYG003` | warn | Chain depth beyond `max_depth` |
| `EDT001` | error | `cosmetic` edit changed the normalized signature |

### What the checker cannot do — state plainly in the docs

It checks that a discharge source exists, is in scope and is not a forward reference. It
does **not** check that the source entails the obligation. It catches *declared* constant
circularity, not undeclared. It catches parameter-constraint vacuity, not function-space
vacuity. Each gap is a line item on the obligation list.

### Obligation emission

`blueprint lint --emit-obligations` writes, for every discharge:

```json
{ "id": "ob:gclm.elb.pf2:S1:A2",
  "question": "entailment",
  "given":  "\\|\\omega_0\\|_{H^s} \\le \\epsilon_0(a)",
  "target": "\\|\\omega(0)\\|_{H^s} \\le \\epsilon_0/2",
  "substitution": {"x": "\\omega(t)", "delta": "\\epsilon_0/2"},
  "context_hypotheses": ["H1", "H2"],
  "hash": "…" }
```

Each is a one-line question with no proof search, no strategy, no global context — the
regime where LLM judgment is most reliable. The point is that deterministic code
enumerates the *complete* list, so nothing is skipped because a verifier failed to notice
it needed checking.

### Sampling strategy for `NUM`

Sampling strategy matters more than sample count. Combine: uniform (½), log-uniform (¼)
for ranges spanning orders of magnitude, all `2^k` corners inset by 1e-9,
boundary approach at `endpoint ± range·10^-k` for `k = 1..8`, and asymptotic `10^k` for
unbounded ranges. Evaluate at 40 dps via mpmath. **Boundary approach is where real errors
surface** — a wrong constant usually holds comfortably in the interior and fails near an
endpoint.

---

## 9. Recompile

Naive recompile re-runs the LLM tier on everything and becomes too expensive to press.

| Tier | What | Cost | Scope |
|---|---|---|---|
| T0 | parse, schema, union validation | ms | dirty nodes |
| T1 | deterministic checks | seconds | dirty nodes |
| T2 | propagation sweep, support sets, derived status | ms | always full, it is O(V+E) |
| T3 | obligation checks and gap hunts | minutes, dollars | only where obligations changed |

**Cache at the obligation level, not the node level.** Key on `hash(obligation_record)`.
Editing step 5 leaves step 3's obligation record byte-identical, so step 3 is a cache hit.
This is what makes recompile feel like `make`. About forty lines of code.

**Preview the bill.** `blueprint recompile --dry-run` → "34 obligation checks, 3 gap
hunts, ~$2, ~4 min". `--budget` caps it. Value-order so partial runs are useful:
obligations on the chosen proof path and the frontier first; archived and depreferred
branches last. Results write to the log as they land, so runs are interruptible and
resumable.

**Watch mode.** `blueprint watch` runs T0–T2 on file save. Instant structural feedback
while typing LaTeX; T3 only on explicit request. This is the Lean-in-an-editor model and
it is the right interaction shape for a flexible system.

**Race safety.** Write every T3 result with the signature it was computed against;
discard results whose signature has since moved.

---

## 10. Agent layer

Support **both** subscription-based CLI tools and metered APIs. Role-based indirection so
swapping is config-only.

```
agents/
  base.py            # Agent protocol
  anthropic_api.py   # anthropic SDK, ANTHROPIC_API_KEY
  openai_api.py      # openai SDK, OPENAI_API_KEY
  claude_cli.py      # subprocess: claude -p  (subscription)
  codex_cli.py       # subprocess: codex exec (subscription)
  registry.py        # role -> backend resolution from blueprint.yaml
  log.py             # call log + replay cache
```

**Protocol.** One method:

```python
class Agent(Protocol):
    def complete(self, *, system: str, user: str, schema: type[BaseModel],
                 timeout: int) -> tuple[BaseModel, CallMeta]: ...
```

Every prompt requests JSON. Validate with pydantic; on failure, retry once with the
validation error appended to the prompt; then fail the task rather than guessing.

**CLI backends.** Write the prompt to a temp file (prompts exceed argv limits), invoke in
headless/print mode, capture stdout, extract the JSON block (CLI tools may emit preamble),
enforce a timeout, and kill the process group on timeout.

**Cost accounting.** API backends report tokens. CLI backends may not — record wall time
and mark cost `unknown`. Budget logic must not assume cost is always available; fall back
to a per-call count cap.

**Call log and replay.** Log every call to `.blueprint/cache/agent/<prompt_hash>.json`
with backend, model, prompt, response, timestamp, meta. `--replay` resolves calls from
this cache instead of the network. This gives reproducible tests and lets work continue on
deterministic layers while offline.

---

## 11. Durability and checkpointing

Requirements: an interrupted run (token exhaustion, network loss, `Ctrl-C`, crash) loses at
most one task, and resuming performs no duplicate paid work.

```
.blueprint/
  events.jsonl              # append-only, fsync per append
  index.sqlite              # derived, rebuildable, disposable
  cache/
    obligations/<hash>.json
    agent/<hash>.json
  jobs/<job_id>.json
  logs/
```

- **Atomic writes.** Write `path.tmp`, `fsync`, `os.replace(path.tmp, path)`. Never
  partially write a node file, the index, or a job record.
- **Job records.** Any multi-step operation (recompile, k-strategy decompose, batch
  verify) creates a job before doing work:
  `{job_id, kind, params, task_list, completed_task_ids, status, started_at}`. Update
  after each task completes.
- **Task granularity = one agent call or one check.** Fine enough that losing one is cheap.
- **Resume.** `blueprint resume <job_id>` or `blueprint resume --all` re-reads the job and
  skips completed tasks. The obligation cache means resumption is often free even without
  the job record.
- **Idempotency.** Every event has a UUID; replaying the log is a no-op for events already
  applied.
- **`blueprint doctor`.** Verify log integrity, rebuild the index from log + YAML, report
  orphaned jobs and stale locks.
- **Single-writer lock** on `.blueprint/` with a PID file, so two sessions cannot interleave
  appends.

---

## 12. Decomposer

### 12.1 Depth is not a parameter

Never request a full tree. **Decompose one level at a time, lazily**, with a stopping
predicate per node. Difficulty is not observable before an attempt; any depth chosen in
advance is a guess about an unobservable quantity. One-level expansion also limits damage
when a strategy is wrong, which at level 1 on a research problem it usually is.

### 12.2 Stopping predicate

A node is **terminal** if it is `standard` (with a resolvable anchor), `routine` (closable
in ≤ `max_steps` with ≤ 3 hypotheses), `computational`, `assume`, or `admitted`.

A node **must be decomposed** if an attempt failed, or it is `hard` and unattempted, or a
submitted proof tripped `HYG001`/`HYG002`.

`routine` is *confirmed by attempting*, not asserted in advance. A failed attempt on a
`routine` node is a **relabel event**, not a failure. This is what makes the system
self-correcting without requiring the difficulty labels to be right up front.

### 12.3 Concentrate difficulty, do not divide it

A good decomposition yields mostly `standard`/`routine` children plus one or two `hard`
ones, with a reduction that is itself routine. The purpose is *localizing* difficulty.
Five equally hard children means nothing was learned and the verification surface was
multiplied by five.

The test a decomposition must pass: **did the hard part get more specific**, in at least
one sense — fewer degrees of freedom (parent quantifies over a range, child fixes a
structure); better-equipped domain (PDE statement → ODE inequality or finite-dimensional
spectral fact); narrower scope (theorem → one estimate in one norm on one interval). If
none holds, the problem was restated, not decomposed.

### 12.4 Transaction contract

One decomposition attempt produces **one atomic transaction**:

- N new statement nodes, each schema-complete (binders, hypotheses, conclusion, constant
  table with dependency and uniformity fields, witness, difficulty label, anchor if
  `standard`, optional `numeric_form`)
- exactly one proof node targeting the parent, with `strategy` declared, whose steps cite
  those children
- a `note` node with strategy commentary, carrying no obligations

It passes the linter and commits whole, or is rejected whole. No partial decompositions
enter the graph.

**Why this works:** requiring the reduction in-schema is the anti-gap device, and it is
not a judgment. An LLM cannot fill `discharges` for every cited lemma without confronting
whether the children actually cover the obligations. Most insufficient decompositions die
at `DIS004`, deterministically, before any verifier runs. This is the highest-leverage
single decision in the system.

### 12.5 Pipeline

1. **Context assembly** (deterministic): rendered target; ancestor statements; the library
   of already-proved statements available for citation; `note` hints on this node; prior
   failed attempts on this node with their diagnostics.
2. **Decompose** (strong model): emit the transaction.
3. **Lint** (free): reject on error, return diagnostics, allow ≤ 2 repair rounds.
4. **Reduction review**: does the reduction derive the parent from the children, and is
   any child as hard as the parent *in substance*? Human in M3; verifier panel from M5.
5. **Human gate**: surviving candidates presented; pick, edit or reject.

### 12.6 Expansion order

Fully decompose level 1. Review. Then — before touching hard children — attempt the
`routine` and `standard` leaves. **The cheap leaves are a falsification test on the
strategy.** If a bookkeeping lemma the strategy requires is false or needs a hypothesis
nobody has, the strategy is wrong and it cost a few cheap attempts instead of three weeks.
Only then descend, and descend into one hard child, not all — a resolved hard child often
reshapes its siblings.

Calibration anchors: a paper-scale theorem lands at roughly 20–60 statement nodes over
3–5 levels. Past 6 levels, restructure. Past 100 nodes, algebra was probably node-ified
that should have stayed as steps.

### 12.7 Human modes

| Mode | Human provides | Agent provides | Use for |
|---|---|---|---|
| A — steer | the strategy schema | the instantiation | `hard` nodes, **default** |
| B — propose | a choice among k | k schemas with rationale, then instantiation | `hard`, undecided |
| C — auto | nothing | schema selection and instantiation | `routine`, mechanical splits |
| D — dictate | the children | the reduction, plus linting | structure known, schemas tedious |

Mode A is the default for `hard`. Naming the schema costs ten seconds and removes the
largest source of bad decompositions. Mode D will be the most used in practice.

**Persistent strategy hints.** Any node may carry `note` children ("bootstrap on the
vorticity `L^∞` norm"; "the `a → 1/2` limit is where this gets tight"). These become
context for every future attempt on that node, including retries. Make writing one a
single click.

**Frontier queue, not a graph to browse.** The graph is for orientation; the daily
interface is a ranked list of nodes awaiting a decision — `hard` and unattempted, or
attempted-and-failed, or proposed-and-awaiting-review. Rank shallow before deep, and
gating-many before gating-few.

### 12.8 Two derived mechanisms

**Constraint emission instead of children.** A decomposer may find that a strategy works
only under a sharpening of the target ("closes if the blowup rate is exactly
`(T−t)^{-1}`"). Return `{constraint, source_node, hard|soft}` to a constraint ledger
rather than an empty result. A decomposition that pins down a parameter is a real result.

**Memoization.** Before creating a proposed child, normalize, hash and search the graph
including archived nodes. On match, cite the existing node instead of duplicating.

### 12.9 Failure taxonomy — measure these

| | Failure | Caught by |
|---|---|---|
| D1 | Structurally invalid | linter, free |
| D2 | Insufficient — children plausible individually, jointly inadequate | mostly `DIS004`; residue to review |
| D3 | Circular or restated child | `STR001/002`, then reviewer |
| D4 | Misallocated difficulty — one child is the parent in disguise | `STR003/004`, then reviewer |
| D5 | Wrong strategy — valid, non-trivial, will not work | human |

D5 is not automatable and will not become automatable. The human gate is permanent, not
scaffolding.

---

## 13. Strategy library

`strategies/*.yaml`. Each schema declares mandatory slots; declaring `strategy: X` on a
proof licenses `SLT001` to require them. Adding a schema is a config change. `custom` is
an escape hatch with no slot checks — **track how often it is used**, since heavy use
means a missing schema.

### Domain-general

| id | Mandatory slots |
|---|---|
| `sequential` | ordered chain; each child's hypotheses discharged by predecessors |
| `case_split` | the cases, plus an explicit exhaustiveness node |
| `contradiction` | negated-conclusion node (hypotheses = parent's + ¬conclusion, derived mechanically), plus the contradiction |
| `induction` | base, step, well-foundedness |
| `reduce_to_known` | anchor node, plus a hypothesis-alignment node |
| `strengthen_then_specialize` | the stronger statement, plus the specialization |

### Analysis and PDE

| id | Mandatory slots | Expected difficulty by slot |
|---|---|---|
| `apriori_continuation` | local well-posedness, a priori bound, continuation criterion | standard, **hard**, routine |
| `bootstrap` | good set nonempty at `t=0`, open, closed, strict improvement | routine, routine, routine, **hard** |
| `contraction` | the map, ball invariance, contraction estimate, conclusion | routine, **hard**, **hard**, routine |
| `energy_functional` | functional well-defined, differential inequality, ODE comparison lemma | routine, **hard**, standard |
| `self_similar_stability` | profile existence, spectral gap of linearisation, nonlinear closing | computational, computational, **hard** |
| `modulation` | adapted coordinates, modulation equations, remainder control, closing | routine, routine, **hard**, routine |
| `barrier` | sub/supersolution construction, comparison principle, conclusion | **hard**, standard, routine |
| `spectral_split` | finite-dim unstable part, stable part, coupling control | computational, **hard**, **hard** |
| `compactness_limit` | approximate problems, uniform bounds, limit extraction, limit identification | routine, **hard**, standard, routine |
| `degree_shooting` | the map, degree or index computation, conclusion | routine, **hard**, routine |
| `rescaling_classification` | rescaling, classification of limits, exclusion of bad limits | routine, **hard**, **hard** |
| `variational` | minimiser existence, Euler–Lagrange, regularity, conclusion | routine, routine, **hard**, routine |

Schema file format:

```yaml
id: bootstrap
name: Bootstrap / continuity argument
applies_to: "a bound claimed to hold on a maximal time interval"
slots:
  - {role: nonempty,    expect: routine, desc: "the good set contains t=0"}
  - {role: open,        expect: routine, desc: "good set is open in [0,T)"}
  - {role: closed,      expect: routine, desc: "good set is closed in [0,T)"}
  - {role: improvement, expect: hard,    desc: "the bound strictly improves on the good set"}
reduction_template: |
  S1  define S = {t in [0,T) : bound holds}      justification: hypothesis
  S2  S is nonempty                              justification: cite(slot:nonempty)
  S3  S is open                                  justification: cite(slot:open)
  S4  S is closed                                justification: cite(slot:closed)
  S5  bound improves strictly on S               justification: cite(slot:improvement)
  S6  S = [0,T) by connectedness                 justification: step:S2,S3,S4
  S7  conclude                                   justification: step:S5,S6
```

The `SLT` payoff is concrete: a bootstrap decomposition missing the closedness node is a
hard error found for free, and forgetting closedness is a real, common oversight.

Beyond slot checking, declared schemas make the k-strategy request meaningful ("this
target under `bootstrap`, `apriori_continuation` and `self_similar_stability`" returns
three genuinely different attacks, each a competing proof node) and give the human a
steering vocabulary ("redo node 7 as a modulation argument").

---

## 14. Encoder and verifier v0

### Encoder

Converts prose (a paper's proof, a draft, an LLM's output) into the step schema. This is
*translation*, not judgment — the task class models handle well. Any step it cannot assign
a typed justification to must become `ADMITTED` with a reason, which is how invisible gaps
become named grey nodes.

Gate: round-trip fidelity on the good corpus (encode → render → judged equivalent), and on
the known-flawed proofs, does the `ADMITTED` set contain the actual flaw?

### Verifier v0 — two distinct jobs, do not merge

**Obligation checking.** Narrow scoped questions from `--emit-obligations`: does `X` entail
`Y` under substitution σ given this context? No proof search, no strategy, no global
context. Worklist complete by construction.

**Gap hunting.** One pass over the whole atomized proof with a **forced-ranking** prompt:
which step carries the largest unjustified leap? Forced choice rather than yes/no, because
a verifier that can pass a proof by saying nothing will pass bad proofs.

**Panel.** Two models from different families, no shared context. Each returns either a
located objection `{step_id, class, witness, severity}` or `no_objection` naming what it
checked. Objection classes: citation fabrication; premise smuggling; silent reformulation;
local-to-global gap; hypothesis unsatisfied at invocation; quantifier order; uniformity
violation; counterexample; non-sequitur.

**Confirmation phase — do not skip this.** Any objection is re-presented to the same
verifier with surrounding context; if the perceived flaw dissolves, it drops to `info`.
Without it, pedantic over-rejection drowns the signal and the output stops being read.

**Adjudication** is the human in v0. Cap at `objection_rounds`, then hard escalate.

Explicitly **not** in v0: debate protocols, prover-verifier games, self-consistency
ensembles, trained process reward models. Published evidence indicates stacking mechanisms
does not buy soundness — false-positive rates stay in the same band across cross-model and
conjunction-of-verifier setups. Treat the panel as a recall device and spend the effort on
the deterministic layer.

Gate: per-mutation-class catch rate; false-accept rate on the good corpus; and
**false-objection rate on correct steps**, which is the metric that decides whether the
tool gets used.

---

## 15. Explain status

With a deterministic derived layer, "why is this node not green" is answerable
mechanically. `blueprint why <node>` returns the `blocked_by` chain: "T is
`proved_modulo` three items: Lemma 4 step 7 admitted; Lemma 9's anchor unresolved; Prop 2's
proof has an open objection at step 3." No LLM involved, always correct. This is the
feature that makes the graph trustworthy; build it with the propagation engine, not with
the UI.

---

## 16. Repository layout

```
blueprint/
  pyproject.toml
  blueprint.yaml
  CLAUDE.md
  DESIGN.md
  DECISIONS.md
  blueprint/
    model.py  load.py  latex.py  sig.py  graph.py  diagnostics.py  render.py
    events.py  propagate.py  support.py  ops.py  obligations.py  jobs.py  locking.py
    checks/  __init__.py schema.py refs.py discharge.py constants.py
             vacuity.py numeric.py slots.py structure.py hygiene.py
    agents/  base.py registry.py log.py
             anthropic_api.py openai_api.py claude_cli.py codex_cli.py
    decompose/  strategies.py context.py propose.py repair.py memo.py
    verify/     encode.py obligation.py gaphunt.py panel.py confirm.py
    recompile/  driver.py tiers.py cache.py estimate.py watch.py
    report/     certificate.py latex.py
    ui/         app.py static/
    cli.py
  strategies/*.yaml
  nodes/**/*.{stmt,proof,def,note}.yaml
  macros.yaml
  lean/                      # optional, independent
  tests/
    fixtures/good/  fixtures/mutated/  fixtures/normalize/
    corpus/                  # real hand-encoded theorems (human-supplied)
```

---

## 17. Lean-lite (optional, independent)

Fully parallel to everything above. Separate `lean/` directory, one file per node with
imports matching declared citations, and a `formalized: bool` flag on each node. Nothing in
M0–M7 depends on it; abandoning it costs nothing.

Encoding: mathematical vocabulary in a `structure` (no axioms, so it stays out of the
support set); unproved leaf obligations as named axioms parameterised by it; the reduction
as a theorem.

```lean
structure Sig where
  Sol : Type
  N   : Sol → ℝ → ℝ
  dN  : Sol → ℝ → ℝ
  T   : Sol → ℝ
  c α : ℝ

axiom energy_ineq (S : Sig) (s : S.Sol) :
    ∀ t, 0 ≤ t → t < S.T s → S.dN s t ≥ S.c * (S.N s t) ^ (1 + S.α)

theorem blowup (S : Sig) (s : S.Sol) (hα : 0 < S.α) (hc : 0 < S.c) : S.T s < ⊤ := by
  sorry
```

What `lake build` alone provides per node: discharge completeness as a kernel guarantee;
constant-dependency circularity as a scope error (the binder structure *is* the constant
table); quantifier order enforced by the type; the support set from `#print axioms`,
filtering the standard `propext` / `Classical.choice` / `Quot.sound`; alpha-normalization
for free by hashing the elaborated pretty-printed type instead of LaTeX; sound definitional
statement equivalence; and, with one file per node, native acyclicity plus citation
restriction plus incremental rebuild.

Naming convention `..._prose` / `..._assume` on axioms makes the trust tiering read
straight off the axiom list.

Costs: two representations, so drift is a new failure mode — mitigate by generating the
prose skeleton from the Lean file, or by mechanically checking node names and cite lists
match. Some PDE reductions have real analysis in the glue; those need extra opaque axioms,
which degrades gracefully into a larger support set. A false axiom proves anything, which
is why `VAC` stays mandatory at the prose layer — the kernel checks form, not truth.

Suggested scope: statement forms for every node; reductions for the top two or three
levels; skip leaves. Keep the Python linter regardless — where the two disagree about a
discharge, that is a bug report on the linter.
