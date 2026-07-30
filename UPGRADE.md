# UPGRADE.md — the bridge from v0 back to `DESIGN.md`

v0 is a deliberate subset. This file is the map: one row per deferred feature,
what it is, where `DESIGN.md` specifies it, which v0 modules it would touch,
roughly what it costs, and — most importantly — **the signal that tells you it is
now needed**. Do not build any of these speculatively. Wait for the signal.

The ordering within each table is roughly by expected value, highest first.

Current as of L2 plus Addendum A: the claim ledger, the three-job verifier, the
statement auditor, recompile levels and the verification record are **in**. Two of
the rows below changed character as a result, and both changes are in the
dangerous direction if you misread them:

- **`CST001`–`CST002` and `VAC001`–`VAC003` now have an agent stand-in**, the
  statement auditor. It is strictly weaker than the checks it replaces — see the
  rows, and `ARCHITECTURE.md` §0. Having a weak substitute makes the strong
  version *easier to forget*, not less necessary.
- **Recompile tiering exists, but as levels over the agent jobs**, not as the cheap
  deterministic gate `DESIGN.md` §9 specifies. The row is updated.

---

## Why the deferrals are safe

The full design lands **additively** on top of v0, because six things were kept
even though almost everything else was cut:

1. **Stable node ids.** Every citation, hash, event and discharge refers to one.
   Retrofitting stability onto ids people have already renamed is miserable.
2. **`statement_hash`, even as a raw-text SHA-256.** Normalization replaces the
   *hash function* and nothing else — `bp/hash.py:statement_hash` is a single
   function with a single caller in the sweep.
3. **`events.jsonl`.** Append-only from the first commit, so the event-fold
   architecture of `DESIGN.md` §6 has a real history to fold when it arrives.
4. **`local_status` and `global_status` as separate fields, with global
   computed.** This is the one thing that cannot be retrofitted at all: if
   agents have been writing a single `status` field for six months, there is no
   way to recover which values were opinions.
5. **Role-based agent config rather than hardcoded models** (L1).
6. **`hypotheses` and `uses`.** The full design's `substitution` map and step ids
   are *additive refinements* of `uses`, not replacements for it
   (`DESIGN.md` §3.2). A `uses` entry becomes a `cite` justification by gaining
   a `substitution` field and moving under a step id; the `discharges` map it
   already carries is the load-bearing part and does not change shape.

With those in place: normalization replaces the hash function; the deterministic
checks slot into `recompile` as a tier that runs *below* the agents; and the
structured proof schema becomes optional frontmatter that the new checks require
and v0's code ignores.

---

## Deterministic checks

| Feature | `DESIGN.md` | Touches | Effort | Signal that you need it |
|---|---|---|---|---|
| **Constant tables and `CST001`–`CST002`** — declared constant dependencies, cycle detection, uniformity violations | §3.1 `constants`, §8 | new `bp/checks/constants.py`; `constants` field on `Node`; `bp/checks.py:FAMILIES` and `for_node`; `bp/verification.py` (a new `deterministic` key) | 2–3 days | **Still the next check to add.** The statement auditor's question 4 now asks whether a constant depends transitively on something it is treated as uniform in, so the error is no longer completely invisible — but it is found *by reading*, which means it is found sometimes. A scope check walks a declared table and is complete. The signal: the auditor flags a real circular dependency (good — but you now know they are in there), or you find one by hand that it missed. |
| **Numeric falsification sweeps, `NUM001`–`NUM004`** — sample the parameter space and look for violations of explicit inequalities | §8, §8 "Sampling strategy" | new `bp/checks/numeric.py`; `numeric_form` field; `mpmath` dependency; `bp/checks.py:FAMILIES` | 3–4 days | A verifier passes a lemma whose explicit constant is wrong, or you find a sign error by hand that a sweep would have caught in a second. Boundary approach is where real errors surface — interior sampling alone is nearly worthless. The claim ledger makes this cheaper to wire in than it was: a claim with `kind: computation` is already an enumerated, hashed record with its own cache slot, so a numeric sweep is a *deterministic* answerer for exactly those records rather than a new pipeline. |
| **Vacuity witnesses, `VAC001`–`VAC003`** — every statement carries a *checked* witness satisfying its hypotheses | §3.1 `witness`, §8 | `witness` field; new `bp/checks/vacuity.py`; `sympy`; `bp/roles/audit.py` would feed it rather than replace it | 2 days | A lemma with unsatisfiable hypotheses survives verification: it looks fine because it *is* fine, vacuously, and the theorem below it rests on nothing. The auditor's question 2 now asks for a witness and distinguishes `exhibited` / `not_found` / `out_of_reach` — but an asserted witness is not a checked one. The natural upgrade is small: persist the auditor's `exhibited` witness into a `witness` field and have `VAC` check it mechanically. That turns an assertion into a constructed object, which is the whole difference. |
| **Binders and substitution maps, `DIS001`–`DIS003`** — every citation must instantiate every binder of the cited node | §3.1 `binders`, §3.2, §8 | `binders` field; `Use` gains `substitution`; `bp/discharge.py` | 3–5 days | Your `applied_to` free text starts carrying real information that nobody checks — "applied to $\omega(t)$ with $\delta = \varepsilon_0/2$" — and a mis-instantiated citation gets through. |
| **Structural checks `STR001`–`STR004`** — a child that restates or weakens an ancestor; difficulty not concentrated | §8 | `bp/checks.py`, needs signatures for `STR001` | 1 day (after normalization) | Decompositions that go in circles: a "lemma" that is the parent again. The checker's second question asks this in prose; making it deterministic is cheaper and complete, and would let that call be dropped rather than merely double-checked. |
| **Hygiene `HYG001`–`HYG003`** — proof length, citation count, chain depth | §3.3 `hygiene`, §8 | `bp/checks.py`, `bp.yaml` | half a day | Proofs get long enough that you stop reading them. |
| **Ledger completeness — a check that the ledger covers the proof** | not in `DESIGN.md`; this is v0's own gap | `bp/ledger.py`; needs numbered steps, or a second extractor pass with a different prompt | 2–3 days | **The ledger's soft spot, and worth understanding before trusting it.** `LED001` guarantees every claim *in the ledger* is sourced. Nothing guarantees the ledger is complete: a load-bearing claim the extractor did not list is invisible. Today's mitigations are a prompt and a self-reported `omitted` field, which are not guarantees. Numbered proof steps would make it structural — one ledger entry per step, checked by count. The signal: an objection from the whole-proof pass about a step that is not in the ledger. Watch for it; it is the failure this design is least protected against. |
| **Per-claim `applied_to`** — the object a ledger claim is asserted about | §3.2 (the `substitution` map does this for citations) | `Claim` gains `applied_to`; `bp/ledger.py`; `prompts/extract.md` | 1 day | A claim check comes back `entails: true` for a claim that is true of a *different* object than the proof uses it on. Discharge records carry `applied_to`; claim records do not, because the extractor has nowhere to put it. The signal is a claim check you disagree with where the disagreement is about which object. |
| **Forward-reference and scope checks `DIS005`–`DIS007`** | §8 | requires numbered steps first | — | Only meaningful once proofs have steps. |

---

## Proof and statement structure

| Feature | `DESIGN.md` | Touches | Effort | Signal |
|---|---|---|---|---|
| **Numbered proof steps with typed justifications** — the `cite` / `hypothesis` / `step` / `literature` / `computation` / `ADMITTED` discriminated union | §3.2 | `Node` gains an optional `steps` field; `bp/discharge.py` emits per-step obligations; `bp/render.py` | 1 week | Whole-proof verification produces objections you cannot locate, or `proof:` discharges start carrying multi-sentence arguments that deserve to be nodes. This is the single largest structural upgrade and everything else in this section depends on it. |
| **LaTeX normalization and $\alpha$-normalization** | §4 | replaces `bp/hash.py:statement_hash`; needs `macros.yaml` | 3–4 days | You spend real time re-verifying nodes after cosmetic edits. Measure it before building it: the current behaviour is annoying, not wrong. |
| **Signatures over claims rather than text** — hypotheses hashed as a set, ids excluded | §4 `sig` | `bp/hash.py`; requires structured statements | 2 days (after the above) | Reordering hypotheses invalidates a verification and you notice it is absurd. |
| **Multiple competing proofs per node, with preference ordering** | §5, §6, §7 | `Node` splits into statement and proof files; `propagate.py` gains proof selection | 1 week+ | You want to keep a decomposition *and* a direct proof of the same lemma and switch between them. v0 forces you to archive one. |
| **Edit intents (`cosmetic` / `refine` / `equivalent`)** with the cosmetic assertion | §7 "Edit intents" | `ops.edit_statement`; requires normalization | 1 day (after normalization) | You tidy notation, everything downstream goes stale, and you know for a fact the claim did not move. `equivalent` also gives the support certificate an honest line for human equivalence assertions. |
| **`promote_step` — turn a proof step into its own node** | §7 | `ops.py`, UI | 2 days | You keep writing `proof:` discharges that are really lemmas. `DESIGN.md` notes this is more common than creating a node from scratch. |
| **Refutation (`refute`, `truth: refuted`, the `unsound` status)** | §6 | `ops.py`; the `unsound` branch already exists in `propagate.py` | 1 day | You discover a lemma is false and need the graph to say so rather than quietly deleting it. The sweep branch is already written and currently unreachable. |
| **Constants, `defs_used`, `params_used`, target templates with typed holes** | §3.1, §4 | `Node`, `bp/hash.py` | 1 week | You want to change one constant in the target and see only the affected nodes invalidate, rather than the whole tree. |

---

## Agents and decomposition

L1 exists, so everything in this section is now an increment on working code
rather than a prerequisite.

| Feature | `DESIGN.md` | Touches | Effort | Signal |
|---|---|---|---|---|
| **Strategy library as prompt scaffolding** — named schemas with expected child roles and mandatory slots, plus `SLT001`–`SLT004` | §13, §8 | `strategies/*.yaml`; `bp/roles/decompose.py`; `bp/checks.py` | 3–4 days | The decomposer produces structurally sloppy decompositions: a case split with no exhaustiveness node, a contradiction argument whose negation node has the wrong hypotheses. `LIGHT.md` L3 rates this the highest-value L3 item and notes it is nearly free. |
| **k-parallel decomposition under different strategies, as competing subtrees** | §12.5, §12.8 | `bp/roles/decompose.py`; requires multiple proofs per node | 1 week | Your first decomposition is usually not your best and you want to compare rather than iterate. |
| **Memoisation of decompositions by signature** | §12.5 `memo.py` | `bp/decompose/memo.py` | 2 days | You re-expand the same lemma in two branches and pay twice. |
| **Failure taxonomy measurement** — record *why* each decomposition attempt failed | §12.9 | `bp/roles/`, event log | 1 day | You are iterating on prompts and guessing at what is going wrong. Cheap, and it turns prompt engineering into measurement. |
| **Expansion order / frontier ranking beyond shallow-first** | §12.6 | `bp/frontier.py` (does not exist) | 2 days | The frontier queue stops matching what you actually want to work on next. |
| **Encoder role** — turn prose statements into the structured schema | §14 "Encoder" | requires structured statements | 1 week | Only once the structured schema exists. |
| **Trust tiers for literature anchors and computation artifacts** | §5 `support` | `bp/propagate.py` support formula | 2 days | Your support certificate lists a citation of a textbook alongside a hand-waved admission and treats them the same. |

---

## Infrastructure

| Feature | `DESIGN.md` | Touches | Effort | Signal |
|---|---|---|---|---|
| **State as a fold over the event log** — time travel, blame, branching | §6 | `bp/events.py` gains a reducer; `ops.py` writes events first and derives files from them | 1–2 weeks | You want to branch a decomposition, or to answer "what did this node look like last Tuesday". The log is already append-only and honest, so this is additive. |
| **Recompile tiers T0–T3 as a cheap *gate*** | §9 | `bp/recompile.py:plan`, `bp/roles/verify.py` | 1 day | **Half done, and the remaining half is the cheap half.** `--level quick/standard/deep` now tiers the *agent* jobs, which is what cost control needed. What `DESIGN.md` §9 also specifies is the deterministic tiers running *below* the agents as a gate: a node with a `DIS011` or a `LED001` gets no model calls at all, because the answer is already known. Today it gets the full level and is then flagged by the derivation anyway. The signal is watching a `deep` recompile spend fifteen calls on a node `bp check` had already rejected for free. |
| **Deterministic answerers for obligation and claim records** | §8, §9 | `bp/roles/verify.py:_check_records` | 2 days | The narrow-question worklist is now a clean interface: a record in, a yes/no with a reason out, cached on a content hash. Nothing says the answerer has to be a model. `hypothesis:H1` where `H1` is literally the needed text is a string comparison; a `computation` claim with an artifact could be re-run; a numeric claim could be swept. Every record answered deterministically is one that is both free and *sound*. The signal is noticing how many obligation checks are trivially true by inspection. |
| **Watch mode** — run the deterministic tiers on file save | §9 "Watch mode" | new `bp/watch.py`; `watchfiles` is already a dependency | 1 day | You are editing LaTeX and running `bp check` by hand after every save. This is the Lean-in-an-editor interaction shape and it is cheap; it was left out of L1 only because L2's UI may subsume it. |
| **Cross-process locking** | §11 | `bp/locking.py` (does not exist) | 2 days | **Now the most likely thing to bite.** Within one process, `ops.serialised` orders every mutation, so the UI's worker thread and its request handlers are safe. Two *processes* are not: `bp ui` in one terminal and `bp verify` in another will both write the obligation cache and the last one wins, silently discarding the other's paid results. L2 makes this arrangement natural — the signal is you doing it. A PID lockfile on `.bp/` is most of the fix. |
| **Race safety on verification results** — write each result with the signature it was computed against, discard results whose signature has moved | §9 "Race safety" | `bp/roles/verify.py` | half a day | A long verification finishes after the user has edited the statement. Today the certificate is written against the *current* hashes, so a verification of the old text can be recorded as current. Staleness catches the common case, but not this one. |
| **Lean-lite** — one Lean file per node, unproved leaves as axioms, the reduction as a theorem | §17 | separate `lean/` directory, `formalized` flag | 2+ weeks | You want machine-checked reductions. Fully parallel to everything else; abandoning it costs nothing. |

---

## The interface

L2 exists, so these are increments on a working UI.

| Feature | `DESIGN.md` | Touches | Effort | Signal |
|---|---|---|---|---|
| **Per-node agent-call history in the detail panel** | §10 log | `bp/ui/app.py`, `app.js`; the call log already has everything | 1 day | You want to know what the decomposer was actually told about this node, and find yourself running `bp calls --show` in a terminal beside the browser. `LIGHT.md` L3 lists it. |
| **Expanding a partially-decomposed node** | §12.5 | `bp/roles/decompose.py`, `prompts/decompose.md` | 1 day | You add one lemma by hand and want the decomposer to propose the rest. Today `expand` refuses a node that already has children and `Redo` archives them, because the prompt asks for a whole level at once. The fix is to send the existing children as context and ask for the remainder — the signal is finding yourself hand-writing siblings you would rather have proposed. |
| **Keyboard navigation** | — | `app.js` | 1 day | You are clicking through a forty-node graph and want `j`/`k`/`enter`. `LIGHT.md` L3 lists it. |
| **Live updates instead of a 2s poll** | — | `bp/ui/app.py` (SSE), `app.js` | 1 day | The poll is fine for one user on localhost, which is the whole design. It stops being fine if two people ever watch the same project. |
| **Durable job state** | §11 | `bp/ui/jobs.py` | half a day | **This has already bitten once.** The UI's job table is in memory and the model subprocess is the server's child, so restarting `bp ui` mid-decomposition does not merely lose the spinner — it kills the run, minutes into a `max`-effort call, with nothing in `.bp/agent/` to show for it. (Work that has *landed* is safe: results write through `ops` as they arrive.) `GUIDE.md` §5a warns about it; that warning is the workaround, not the fix. |
| **KaTeX preamble parsing: optional-argument defaults, `\newenvironment`, `\let`** | — | `parsePreamble` in `app.js` | half a day | Your `preamble.tex` uses `\newcommand{\f}[2][x]{…}` and the browser drops the default, or defines an environment and the browser does not see it. Only display is affected — the rendered document and the agents get the file verbatim. The signal is notation that typesets in your paper but not in the detail panel. |
| **Watch mode wired to the browser** | §9 "Watch mode" | `bp/watch.py`, SSE | 1 day | You edit a node file in your own editor and want the page to notice. `watchfiles` is already a dependency. |

---

## Things v0 does that the full design does differently

Not deferrals — places where v0 made a *different* choice that would need
revisiting, listed so nobody mistakes them for oversights.

- **An admitted node's support is `[itself]`, not its children's union.** In
  `DESIGN.md` §5 support is computed through the proof; in v0 an admitted node
  is itself the item you are being asked to trust and what sits under it is not
  part of that. If admitted nodes start acquiring substantial subtrees, revisit.
- **`ADMITTED` discharges clamp the parent to `admitted` rather than producing a
  separate support element per admission.** The full design tracks each admitted
  *step* as its own support item (§5). v0 has no steps, so the node is the
  granularity available.
- **v0 has one proof per node, inline in the file.** The full design has proof
  objects with `preference` ordering and a deterministic `chosen_proof`
  (§6 "Recompute"). Splitting statements from proofs is the prerequisite for
  several rows above.
- **Warnings do not require acknowledgment.** `DESIGN.md` §8 records a human
  acknowledgment as an event so the graph does not become permanently yellow and
  ignored. v0 has too few warnings for this to matter yet; if `bp check` output
  starts getting skimmed, add it.
