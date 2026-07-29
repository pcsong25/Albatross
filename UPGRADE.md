# UPGRADE.md — the bridge from v0 back to `DESIGN.md`

v0 is a deliberate subset. This file is the map: one row per deferred feature,
what it is, where `DESIGN.md` specifies it, which v0 modules it would touch,
roughly what it costs, and — most importantly — **the signal that tells you it is
now needed**. Do not build any of these speculatively. Wait for the signal.

The ordering within each table is roughly by expected value, highest first.

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
| **Constant tables and `CST001`–`CST002`** — declared constant dependencies, cycle detection, uniformity violations | §3.1 `constants`, §8 | new `bp/checks/constants.py`; `constants` field on `Node`; `checks.run` | 2–3 days | You write a bootstrap argument and find yourself checking by hand whether $\varepsilon_0$ depends on something that depends on $\varepsilon_0$. This is the classic error the system currently cannot see at all, and it is the **next check to add**. |
| **Numeric falsification sweeps, `NUM001`–`NUM004`** — sample the parameter space and look for violations of explicit inequalities | §8, §8 "Sampling strategy" | new `bp/checks/numeric.py`; `numeric_form` field; `mpmath` dependency | 3–4 days | A verifier passes a lemma whose explicit constant is wrong, or you find a sign error by hand that a sweep would have caught in a second. Boundary approach is where real errors surface — interior sampling alone is nearly worthless. |
| **Vacuity witnesses, `VAC001`–`VAC003`** — every statement carries a witness satisfying its hypotheses | §3.1 `witness`, §8 | `witness` field; new `bp/checks/vacuity.py`; `sympy` | 2 days | A lemma with unsatisfiable hypotheses survives verification. It looks fine because it *is* fine — vacuously — and the theorem below it rests on nothing. |
| **Binders and substitution maps, `DIS001`–`DIS003`** — every citation must instantiate every binder of the cited node | §3.1 `binders`, §3.2, §8 | `binders` field; `Use` gains `substitution`; `bp/discharge.py` | 3–5 days | Your `applied_to` free text starts carrying real information that nobody checks — "applied to $\omega(t)$ with $\delta = \varepsilon_0/2$" — and a mis-instantiated citation gets through. |
| **Structural checks `STR001`–`STR004`** — a child that restates or weakens an ancestor; difficulty not concentrated | §8 | `bp/checks.py`, needs signatures for `STR001` | 1 day (after normalization) | Decompositions that go in circles: a "lemma" that is the parent again. The L1 checker asks this in prose; making it deterministic is cheaper and complete. |
| **Hygiene `HYG001`–`HYG003`** — proof length, citation count, chain depth | §3.3 `hygiene`, §8 | `bp/checks.py`, `bp.yaml` | half a day | Proofs get long enough that you stop reading them. |
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
| **Recompile tiers T0–T3** | §9 | `bp/recompile.py` | 2 days | v0's recompile is the model tier only: it selects nodes and verifies them. The cheap tiers (parse, deterministic checks, sweep) exist but are not wired into it as a gate that runs *below* the agents. The signal is paying for a verification of a node that `bp check` would have rejected for free. |
| **Watch mode** — run the deterministic tiers on file save | §9 "Watch mode" | new `bp/watch.py`; `watchfiles` is already a dependency | 1 day | You are editing LaTeX and running `bp check` by hand after every save. This is the Lean-in-an-editor interaction shape and it is cheap; it was left out of L1 only because L2's UI may subsume it. |
| **Locking and checkpointing for concurrent runs** | §11 | `bp/locking.py` (does not exist) | 2 days | **Sharpened by L1.** Two `bp` processes, or the L2 UI and a CLI, write at once. Atomic writes make a corrupt *file* unlikely, but two concurrent recompiles will both write the obligation cache and the last one wins, silently discarding the other's paid results. The signal is running the UI and the CLI at the same time — which L2 makes easy. |
| **Race safety on verification results** — write each result with the signature it was computed against, discard results whose signature has moved | §9 "Race safety" | `bp/roles/verify.py` | half a day | A long verification finishes after the user has edited the statement. Today the certificate is written against the *current* hashes, so a verification of the old text can be recorded as current. Staleness catches the common case, but not this one. |
| **Lean-lite** — one Lean file per node, unproved leaves as axioms, the reduction as a theorem | §17 | separate `lean/` directory, `formalized` flag | 2+ weeks | You want machine-checked reductions. Fully parallel to everything else; abandoning it costs nothing. |

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
