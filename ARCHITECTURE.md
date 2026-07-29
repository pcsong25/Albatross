# ARCHITECTURE.md — what Albatross currently is

Written for someone who has never seen the code. Current as of **L1**: the
deterministic core plus the agent layer. There is no web interface yet; that is
L2.

Sections 1–11 are the deterministic core. Nothing in them calls a model, and all
of it runs with no key, no network and no configuration. Sections 12–14 are the
agent layer. Everything there is built *on top of* the core and never around it:
an agent proposes, the core checks, and the core decides what the graph says.

---

## 1. The idea in one page

You are trying to prove a theorem. You break it into lemmas, break those into
smaller lemmas, and at any moment some of them are proved, some are sketched,
some are believed but unargued, and some you have not started. The bookkeeping
of *which is which, and what the theorem currently depends on* is tedious,
error-prone, and exactly the thing that quietly goes wrong in a long project.

Albatross holds that bookkeeping. Each lemma is one markdown file with LaTeX in
it. The files form a directed acyclic graph. Two kinds of status live on each
node and they must not be confused:

- **`local_status`** is an *opinion about one node*: somebody — you, or later an
  agent — looked at this node's proof and formed a view. It is authored.
- **`global_status`** is a *derivation over the whole graph*: given every
  opinion beneath it, what does this node actually rest on? It is computed by a
  single deterministic sweep and never written by hand.

Everything else in the system exists to keep that derivation honest and to
render it back to you: as a status table, as a plain-English explanation, and as
a LaTeX document that marks every gap.

---

## 2. Data flow

```
nodes/*.md
    │  bp/load.py        parse frontmatter (ruamel, comments preserved) + body
    ▼
  Node objects           bp/model.py — validated, typed, still carrying their file
    │  bp/graph.py       index by id, compute the children relation
    ▼
   Graph
    │  bp/propagate.py   one reverse-topological sweep
    ▼
 derived fields          global_status, support, blocked_by, stale, statement_hash
    │
    ├── bp/checks.py     integrity + discharge + hygiene → Diagnostics
    ├── bp/why.py        the derived fields, as English
    ├── bp/render.py     the derived fields, as a LaTeX document
    └── bp/load.py       persist_computed writes them back into the files
```

The agent layer sits on top and only ever writes through `ops`:

```
bp/roles/context.py   assemble context from the graph, deterministically
    ▼
bp/agents/            one model call: JSON, validated, retried once, logged
    ▼
bp/roles/*.py         run the deterministic checks on what came back
    ▼
bp/ops.py             write it — and the sweep decides what the graph now says
```

Reading commands (`check`, `status`, `why`, `graph`, `show`, `render`,
`obligations`) derive in memory and write nothing. `bp sweep` and every mutation
in `bp/ops.py` persist. When the files' derived fields disagree with a fresh
sweep — which happens as soon as you hand-edit a statement — `bp check` says so
as `SYS001` rather than silently correcting it.

---

## 3. The node format

One markdown file per node under `nodes/`, YAML frontmatter and a LaTeX body.
Hand-editable by design; the writer preserves comments, quote style and key
order, so a file you edit and the system rewrites comes back looking like yours.

```markdown
---
id: gclm.energy-lower-bound
role: proposition
children: [gclm.elb-a, gclm.elb-b]
strategy: bootstrap on the sign of the gradient at the origin
difficulty: hard
lifecycle: active
local_status: verified
flags: []

hypotheses:
  - {id: H1, tex: "0 < a < 1/2"}
  - {id: H2, tex: "\\omega_0 \\text{ is odd and } \\omega_0'(0) < 0"}

uses:
  gclm.elb-a:
    applied_to: "\\omega(t,\\cdot) \\text{ for } t \\in [0, T_{\\max})"
    discharges:
      H1: "hypothesis:H2"
  gclm.elb-b:
    applied_to: "\\omega(t,\\cdot)"
    discharges:
      H1: "hypothesis:H1"
      H2: "child:gclm.elb-a"
      H3: "ADMITTED: the a priori $L^\\infty$ bound is not established here"

# --- computed fields: written by `bp sweep`. Never edit these. ---
global_status: proved_modulo
support: [gclm.energy-lower-bound]
blocked_by: []
statement_hash: '5a07832c405d'
verified_against: {self: '5a07832c405d', gclm.elb-a: '27260e7d162d'}
stale: false
---

## Statement

Let $0 < a < 1/2$ …

## Proof

By `gclm.elb-a` the sign is preserved …

## Notes

Free prose. Strategy hints, dead ends, references. Fed to agents as context.
```

### Authored fields

| Field | Meaning |
|---|---|
| `id` | The node's stable key. Letters, digits, dot, hyphen, underscore. Never reuse one, never rename one casually: hashes, citations, the event log and the discharge tables all refer to it. |
| `role` | `lemma`, `proposition`, `theorem`, `definition` or `assumption`. Cosmetic — it picks the LaTeX environment — with no effect on status. |
| `target` | `true` on exactly one node: the theorem you are trying to prove. `bp why`, the render's reading order and the support certificate are all written about it. |
| `children` | The nodes this node's proof cites. **This is the only source of edges.** There is deliberately no `parent` field: a lemma may be cited by several parents, and a stored parent list would be a second copy of the truth that eventually disagrees with the first. Parents are computed (`graph.parents`). |
| `strategy` | Free-text hint, e.g. "bootstrap on the $L^\infty$ norm". Passed to the decomposer in L1; prefilled into the Expand dialog in L2. |
| `difficulty` | `standard`, `routine`, `hard` or `unknown`. Makes difficulty concentration visible, and gates which nodes the prover role will attempt in L1. |
| `lifecycle` | `active` or `archived`. Archived nodes keep their files and their text and leave the active graph. Nothing is ever deleted. |
| `local_status` | One of `unverified`, `verified`, `flagged`, `admitted`, `assumption`. An opinion; see §5. |
| `status_reason` | Why the node is admitted or assumed. Required by `bp admit` / `bp assume`. This text is what the support certificate prints — an admission nobody can act on is not much better than a silent gap. |
| `flags` | Objection records written by the verifier in L1. A node with `local_status: flagged` is blocked by the sweep; the flag text explains why. |
| `hypotheses` | This node's own hypotheses, each `{id, tex}`. `tex` is a **math-mode fragment** — `s > 3/2`, not `$s > 3/2$`. Parents refer to these ids when they discharge. |
| `uses` | For each cited child, `applied_to` (free text naming the object the child is applied to, never parsed) and `discharges`, mapping the *child's* hypothesis ids to a source. See §6. |

Any frontmatter key the system does not recognise is reported as `SCH002`. A
misspelled `childern:` is accepted in silence by YAML and would drop a whole
decomposition out of the graph.

### Computed fields — never edit, never let an agent write them

| Field | Written by | Meaning |
|---|---|---|
| `global_status` | `propagate.sweep` | §5. |
| `support` | `propagate.sweep` | The set of items this node currently rests on: admitted nodes and assumptions, transitively. Empty means proved outright. |
| `blocked_by` | `propagate.sweep` | For a node blocked by its children, which ones. |
| `statement_hash` | `propagate.sweep` | §4. |
| `stale` | `propagate.sweep` | §4. |
| `verified_against` | `ops.record_verification` **only** | The hashes this node's verification was performed against: `self`, plus each child at that moment. |

`ops.set_authored` raises `ComputedFieldError` if anything tries to author one of
these. That is enforcement, not convention: the one thing an agent must never be
able to do is write its own global status.

### The body

Three level-two sections: `## Statement`, `## Proof`, `## Notes`. All three are
free LaTeX prose — v0 deliberately has no step structure. Anything else in the
body is preserved but ignored.

A node "has a proof" when its Proof section holds anything but whitespace and
LaTeX comments. That distinction is what separates `open` (nothing attempted)
from `blocked:unverified` (something written, nobody checked it).

Proofs cite children by writing the id in the prose. Backticks around it are
optional and are the convention here; the renderer turns `` `gclm.elb-a` `` into
a cross-reference, since a literal backtick in LaTeX is a quotation mark.

---

## 4. Hashing and staleness

```python
def statement_hash(node):
    s = strip_latex_comments(node.statement_section)
    s = collapse_whitespace(s)
    return sha256(s).hexdigest()[:12]
```

Raw text, whitespace-collapsed. **No normalization in v0.** That means renaming
$\varepsilon$ to $\delta$ changes the hash and forces re-verification you did
not strictly need. That is the intended direction of error: over-invalidation
costs a re-verification, under-invalidation lets a verification certificate
outlive the claim it certified, which is the exact failure the mechanism exists
to prevent.

A node is **stale** when its `verified_against` map no longer matches: either its
own statement moved, or one of its children's did. A node that was never
verified has no map and is not stale — it is *unverified*, which the sweep
reports differently and which reads very differently to a user.

Hashes are always written to YAML **quoted**. A hex digest like `896e63762324`
is a valid YAML float; unquoted it comes back as `inf`, and every hash of that
shape would compare equal to every other.

---

## 5. Status semantics

### `local_status` — authored

| Value | Means |
|---|---|
| `unverified` | Nobody has checked this node's proof. The default. |
| `verified` | Somebody checked it and believes it, *given its children*. |
| `flagged` | A verifier raised an objection that has not been resolved. |
| `admitted` | Believed but not argued. Deliberate, visible debt. |
| `assumption` | Taken as given for this project, by choice, not by omission. |

### `global_status` — derived

| Value | Means |
|---|---|
| `proved` | Rests on nothing outstanding. `support` is empty. |
| `proved_modulo` | True relative to the items in `support`. |
| `open` | No proof written. |
| `blocked:unverified` | A proof exists; nobody has verified it. |
| `blocked:stale` | Verified once, but the statement — its own or a child's — has changed since. |
| `blocked:objection` | A verifier's objection stands. |
| `blocked:children` | The reduction is verified, but the lemmas it uses are not finished. `blocked_by` names them. |
| `unsound` | Rests on something refuted. **Cannot arise in v0** — nothing refutes a node yet — but the branch is written so that refutation lands additively. |
| `archived` | Not part of the active graph. |

### The propagation algorithm

One pass in reverse topological order — children before parents, because a
parent's status is a function of its children's. `bp/propagate.py`:

```
for every node: statement_hash := hash(statement section)

for N in reverse_topological_order(active nodes):

    N.blocked_by := []
    N.stale      := is_stale(N)
    local        := effective_local(N)          # see below

    if N.stale:                 N.global = "blocked:stale";      N.support = []
    elif local == "flagged":    N.global = "blocked:objection";  N.support = []
    elif local == "admitted":   N.global = "proved_modulo";      N.support = [N.id]
    elif local == "assumption": N.global = "proved_modulo";      N.support = [N.id]
    elif local == "unverified":
        N.global = "blocked:unverified" if N.has_proof else "open"
        N.support = []
    elif local == "verified":
        kids = active children of N
        if any kid is "unsound":
            N.global = "unsound"; N.support = []
        elif any kid is open or blocked:
            N.global = "blocked:children"; N.support = []
            N.blocked_by = [those kids]
        else:
            N.support = sorted(union of kids' supports)
            N.global  = "proved" if N.support is empty else "proved_modulo"
```

`effective_local(N)` is `admitted` when `N.local_status` is `verified` **and**
the node's `uses` table admits any hypothesis; otherwise it is `local_status`
unchanged. A node whose author called it verified but which admits a hypothesis
has not verified everything it claims. Rather than silently honouring the label
or rewriting the author's field, the sweep treats it as admitted, so the debt
reaches the support certificate instead of disappearing. The file's
`local_status` is left exactly as written — the clamp is a derivation, not an
edit.

Note that an admitted node's support is `[itself]` and does **not** include its
children's. That is the v0 simplification: an admitted node is itself the item
the theorem rests on, and what sits under it is not what you are being asked to
trust.

### The invariants — these are the test suite

Asserted after every sweep, in production, not only in tests. A violation means
the derived layer is lying, which is worse than crashing.

- `global == "proved"` implies `support == []`
- no node is `proved` while any descendant is not `proved` or `proved_modulo`
- a stale node is never `proved`; a flagged node is never `proved`
- a verified node's `support` contains the union of its children's

`tests/test_propagate.py` generates random DAGs with random statuses,
hypotheses and discharge tables and sweeps them; because `sweep` asserts, every
generated graph is a property test.

---

## 6. The discharge check — the most valuable check in v0

When a proof invokes a child lemma, that lemma has hypotheses, and they must
hold where it is invoked. The `uses` table records, for each hypothesis of each
cited child, where it comes from:

```
hypothesis:<id>     a hypothesis of THIS node
child:<id>          the conclusion of a sibling this node also cites
proof:<free text>   established inline in the prose
literature:<ref>    cited from the literature
ADMITTED: <reason>  not available; carried as visible debt
```

`proof:` and `literature:` take free text and are not structurally checked. They
exist so that a hypothesis established in the prose, or taken from a paper, has
an honest label rather than being silently absent.

| Code | Sev | Catches |
|---|---|---|
| `DIS010` | error | A cited child has no `uses` entry at all |
| `DIS011` | error | A hypothesis of a cited child is not discharged |
| `DIS012` | error | The source string is not one of the recognised forms |
| `DIS013` | error | `hypothesis:X` where this node has no hypothesis `X` |
| `DIS014` | error | `child:X` where `X` is not a declared child |
| `DIS015` | error | `ADMITTED` with no reason |
| `DIS016` | warn | `uses` mentions something that is not a child |
| `DIS017` | warn | `discharges` names a hypothesis the child does not have — a typo here hides a real undischarged hypothesis behind a `DIS011` for a different id |
| `DIS100` | info | An admitted discharge, with its reason. Tracked, never an error |

### What this check does not do — say this plainly to users

It verifies that a source is **named** for every hypothesis. It does **not**
verify that the named source entails the hypothesis. An agent can write
`H2: "hypothesis:H1"` when `H1` does not in fact give `H2`; the check passes and
the claim is false.

So the check catches **omission**, not **misattribution**. Omission is the
common failure and the invisible one, which is why catching it
deterministically is worth so much. Misattribution is handed to the verifier as
a narrow, explicit, per-obligation question — which is a far better position
than having it buried in prose where nobody enumerates it at all.

**A user who believes the check is stronger than it is will over-trust green
nodes.**

### Obligation emission

`bp obligations [node]` turns the `uses` table into a list of questions, one per
discharge:

```json
{ "id": "ob:gclm.blowup:gclm.energy-lower-bound:H1",
  "kind": "entailment",
  "parent": "gclm.blowup",
  "child": "gclm.energy-lower-bound",
  "hypothesis": "H1",
  "applied_to": "\\omega(t,\\cdot) \\text{ for } t \\in [0, T_{\\max})",
  "needed": "0 < a < 1/2",
  "claimed_source": "hypothesis:H1",
  "source_kind": "hypothesis",
  "source_text": "0 < a < 1/2",
  "hash": "58d0568f3b601a23" }
```

The verifier (L1) consumes these one at a time — *does this source give me this
hypothesis, for this object?* — instead of judging a whole proof. Two things
make that better than a whole-proof pass: the questions are narrow, which is
where model judgement is most reliable; and the list is generated
deterministically, so nothing is skipped because a model failed to notice it
needed checking.

`hash` is over what the obligation *asks*, normalised for whitespace, not over
where it sits. Verifier results cache on it, so editing one paragraph of a proof
does not re-bill every obligation in the node.

---

## 7. The other checks

**Integrity** (`bp/graph.py`) — the graph is not a graph without these.

| Code | Sev | Catches |
|---|---|---|
| `REF001` | error | A child id that resolves to nothing |
| `REF002` | error | A node listing itself as a child |
| `REF003` | error | A cycle in the children relation; the message names the full cycle. (A node listing one of its own ancestors as a child *is* a cycle, so this covers that too.) |
| `REF004` | error | A child that exists but is archived |
| `REF005` | warn | An active node nothing cites, which is not the target |
| `REF006` | warn | A node marked verified, with children, whose proof mentions none of them |
| `REF007` | error | Two files claiming the same id |
| `REF008` | warn | No target node, or more than one |

**Children-used** (`bp/checks.py`) — `USE001`, one warning per declared child
whose id does not appear in the proof. Catches "declared a lemma, never used
it", which is a real and common decomposition failure: the graph claims a
dependency that carries no weight. The match is by whole token, so a node called
`a` is not "cited" by the word *never*.

**Schema hygiene** — `SCH001` (a file that could not be parsed at all, reported
as a diagnostic rather than a traceback, so one bad file does not hide the state
of the other forty), `SCH002` (unknown frontmatter key), `SCH003` (marked
verified with no proof and no children — probably meant `assumption`).

**Drift** — `SYS001`, the computed fields in a file disagree with a fresh sweep.

`bp check` exits 1 if any diagnostic is an error, 0 otherwise. `--format json`
emits the diagnostics as JSON.

---

## 8. Explaining status: `bp why`

No model is involved, so it is always correct. That matters more than it sounds:
the colours are only useful if you trust them, and trust comes from being able
to ask any node "why are you that colour?" and get an answer that is plainly
true rather than plausible.

```
$ bp why
`gclm.blowup` has a verified reduction, but 2 of the lemmas it uses are not finished:
  `gclm.local-existence` has a proof, but nobody has verified it yet.
  `gclm.blowup-criterion` was verified, but its own statement has been edited
  since; the verification was about a different claim, so it needs re-verifying.
```

`bp/why.py` walks `blocked_by` transitively and stops at the first honest reason
on each branch. A node reached twice is not explained twice.

---

## 9. Rendering

`bp render` produces a compilable LaTeX document from the node files. It is
regenerated from scratch every time and holds no state, because an
agent-maintained document drifts from the graph and the document is what the
user reads.

Reading order is a depth-first post-order from the target: every lemma appears
before the argument that uses it, and the target theorem is last, which is how a
paper reads. Nodes the target does not reach go to an appendix rather than being
silently dropped.

- The document opens with a **support certificate**: *"`gclm.blowup` holds
  relative to the following 2 items"*, listing them with their reasons — or,
  when the target is not proved at all, the `bp why` chain as a nested list.
- **Unproved nodes carry a visible coloured mark** saying exactly what is wrong
  with them. Proved nodes carry no apparatus; the absence of marks is what
  "proved" looks like.
- **Admitted nodes and assumptions render as a boxed statement labelled as an
  assumption.** If such a node has text in its Proof section it is set as
  *"Sketch — this is not a proof"*, not in a `proof` environment: a QED box on
  an argument nobody has made would be a lie in the one place the document must
  not tell one.
- `--clean` omits every marker and the whole status section. That is the paper.
- `--audit` adds each node's discharge table beneath it, for reading the
  bookkeeping alongside the mathematics.
- `--title`, `-o`, `--stdout` do what they say. The default output is
  `.bp/build/document.tex`.

Statements, proofs and reasons are inserted as LaTeX, unescaped, because that is
what they are. Only ids and generated labels are escaped. Hypothesis `tex`
fragments are wrapped in `$…$`. The preamble uses only `amsmath`, `amssymb`,
`amsthm`, `xcolor` and `hyperref`, so it compiles anywhere.

---

## 10. Mutations and the event log

Every change goes through `bp/ops.py`: `add_node`, `edit_statement`,
`edit_proof`, `add_note`, `set_children`, `set_uses`, `set_hypotheses`,
`relabel`, `admit`, `set_assumption`, `record_verification`, `archive`,
`unarchive`. Each one writes the file, sweeps the graph, persists the derived
fields, and appends one event.

- Writes are atomic: temp file in the same directory, `fsync`, `os.replace`. A
  crash mid-write leaves the old file, never half a new one.
- `edit_statement` reports its **blast radius** in the event payload
  (`stale_radius`): this node, plus every node that cites it transitively and
  holds a verification certificate. Show it to the user *before* committing;
  that is what the L2 warning dialog is for.
- `archive` never deletes. It marks the node archived, cascades to descendants
  that this orphans (and only those — a node still cited from elsewhere stays),
  removes the now-dangling citations from parents, and records the removals in
  the event so the change is reversible by reading the log.
- `record_verification` is the only writer of `verified_against`.

`.bp/events.jsonl` is append-only, one JSON object per line, UUID per event,
fsynced on every append. v0 does not fold state from events — the node files are
the state and the log is the history. `DESIGN.md` §6 describes the fold;
rebuilding it later needs only this log to have been honest all along, which is
why it is written from the first milestone.

---

## 11. The command line

In v0 this is a testing scaffold. The intended daily interface is the L2 web UI.

| Command | Does |
|---|---|
**The deterministic core** — no key, no network, no configuration:

| Command | Does |
|---|---|
| `bp status` | One line per node: role, local status, global status, what it rests on |
| `bp show <id>` | Everything about one node, including its discharge table |
| `bp graph` | The DAG as a tree, rooted at the target |
| `bp why [id]` | The status chain in plain English |
| `bp check [--format json] [--quiet]` | Every deterministic check. Exit 1 on error |
| `bp obligations [id]` | The obligation list as JSON |
| `bp render [--clean] [--audit] [--title T] [-o F] [--stdout]` | The LaTeX document |
| `bp events [--limit N]` | The event log, human-readable |
| `bp sweep` | Re-derive and write the computed fields |
| `bp admit <id> -r "…"` / `bp assume <id> -r "…"` | Mark, with a required reason |
| `bp note <id> "…"` / `bp relabel <id> <difficulty>` / `bp archive <id>` | |

**The agent layer** — these call models, and can fail for reasons the ones above
cannot: a missing credential, a budget cap, a model that would not answer.

| Command | Does |
|---|---|
| `bp agents` | Which model plays which role, and whether it can run here |
| `bp expand <id> [--hint "…"]` | Decompose one level, repairing against the discharge check |
| `bp redo <id> [--hint "…"]` | Archive the subtree to `attempts/`, decompose again |
| `bp check-decomp <id>` | The two checker calls |
| `bp verify <id> [--no-record]` | Obligations, whole proof, confirmation |
| `bp prove <id> [--force]` | Write a proof for a routine or standard leaf |
| `bp recompile [--dry-run] [--node id]` | Verify every stale and unverified node |
| `bp resume [job_id]` | Continue an interrupted recompile |
| `bp jobs` / `bp calls [--show hash]` | Job records; the model call log |

Every one of them takes `--replay`, which resolves calls from the log instead of
the network.

`--root` overrides project discovery, which otherwise walks up from the working
directory looking for `nodes/`, the way `git` finds its repository.
`$BP_ROOT` also works.

---

## 12. The agent layer

Every model call in the system goes through `bp/agents/`. Nothing else may
import an SDK or shell out to a model, and that rule is what makes the call log
complete, the budget enforceable, and `--replay` able to reproduce a session
offline.

### Roles, not models

The system talks about *roles* — `decomposer`, `checker`, `verifier_a`,
`verifier_b`, `prover` — and never about models. Which model plays which role is
one edit to `bp.yaml`:

```yaml
agents:
  roles:
    decomposer: {backend: codex_cli,  model: default}
    checker:    {backend: claude_cli, model: opus}
    verifier_a: {backend: claude_cli, model: opus}
    verifier_b: {backend: openai_api, model: gpt-5.6}
    prover:     {backend: claude_cli, model: sonnet}
budget:
  per_recompile_usd: 3.0
  max_calls_per_recompile: 40
```

That indirection costs a layer and earns two things. It lets the expensive
verifier move onto a subscription CLI when the bill gets uncomfortable. And it
lets the two panel verifiers be put on **different model families**, which is the
whole reason there are two of them — two verifiers from the same lab miss the
same things.

### Backends

| Backend | What it is | Reports cost |
|---|---|---|
| `claude_api` | Metered Anthropic API. Streams; adaptive thinking; `output_config.effort`. | yes |
| `openai_api` | Metered OpenAI API, Chat Completions. | yes |
| `claude_cli` | `claude -p`, a flat-fee subscription | **no** |
| `codex_cli` | `codex exec`, a flat-fee subscription | **no** |
| `scripted` | Canned replies. Tests only; never a default. | no |

CLI backends write the prompt to a temp file and feed it on stdin (a
decomposition prompt exceeds the argv limit, and a prompt truncated by the shell
fails in a way that looks like a model error), run in their own process group,
and kill the **group** on timeout — a CLI tool spawns children, and killing only
the parent leaves them holding the terminal. Their command vector is
configurable per role in `bp.yaml`, because CLI flags drift between releases and
the user should not have to edit Python to keep up.

### One method

```python
Backend.complete(system, user, schema, timeout) -> (model, CallMeta)
```

Everything above `invoke` is shared, so all backends behave identically:

- The JSON schema is appended to the user prompt automatically, along with an
  instruction to double backslashes. It is deliberately **not** in the prompt
  files — those are about mathematics and the user is expected to edit them; the
  JSON contract is machinery they should not be able to break by accident.
- The reply is dug out of whatever preamble wrapped it: fenced block, whole text,
  then an outermost balanced `{…}` scan that understands string literals.
- A reply that will not parse as JSON gets one repair attempt: backslashes that
  JSON rejects are doubled. Every string this system moves is LaTeX, and a model
  asked for JSON containing `\omega` very often emits a single backslash. The
  repair is a safety net, recorded on the call; the schema instruction is the plan.
- The result is validated against the pydantic schema. On failure it is sent back
  **once**, with the validation error appended. On a second failure the task
  **fails**. It never guesses — silently patching up a malformed decomposition
  would put unchecked structure into the graph.

### Cost, and the fact that it is sometimes unknown

API backends report tokens and are priced from a table in `bp.yaml` (`bp` ships
current list prices). Subscription backends report **nothing**, and say so:
`cost_usd is None`, wall time recorded instead.

So budget logic never assumes a price exists. `Budget` holds a dollar cap *and* a
call cap; the dollar cap only constrains priced calls, which makes the **call cap
the one that always works** — with a CLI backend it is the only thing between a
repair loop and an afternoon of unattended work. `Budget.check()` runs *before*
each call, so a run stops before the call that would cross the cap rather than
after.

### The call log, and `--replay`

Every call is written to `.bp/agent/<prompt_hash>.json` with its full prompt and
full response. `--replay` resolves calls from there instead of the network. A
replay miss is a **loud error**, never a quiet fallback: a replay run that
silently went online would stop being either reproducible or free, and would do
so without saying so.

The hash covers backend, model, system and user, so two models asked the same
question do not collide.

---

## 13. The four roles

Each role assembles context deterministically (`bp/roles/context.py` — no model
decides what a model gets to see), asks for JSON, runs the deterministic checks
on what came back, and writes through `ops`. The prompts live in
`bp/roles/prompts/*.md` and are meant to be edited.

### Decomposer

One level. 3–7 children, each a section or a major lemma. The prompt says
explicitly that the leaves are *expected* to be hard and unproved and that it
must not attempt provable granularity — without that it goes four levels deep in
one call and the user spends the afternoon pruning.

Returns, per child: statement, difficulty, and an explicit `hypotheses` list.
Plus a reduction proof for the parent **and a complete `uses` table**.

That table is the load-bearing part, and it is not a judgement. A model cannot
fill in `discharges` for every hypothesis of every lemma it cites without
confronting whether those lemmas actually cover the parent. So the decomposition
is assembled into a **candidate graph in memory**, the discharge check and the
children-used check are run on it, and only then is anything written. Expect a
substantial fraction of first attempts to be rejected: that is the mechanism
working. The diagnostics are fed back verbatim — `DIS011`, the hypothesis id, the
hint — and two repair rounds are allowed.

After two failed repairs it is written anyway, with the remaining diagnostics
reported. That is deliberate: this system's posture is that debt is visible
rather than hidden, `bp check` says exactly what is wrong, and nothing is
destroyed if the user archives it.

`bp redo` copies the current subtree to `attempts/<node>-<n>/` **before**
archiving anything, then archives the children and decomposes again with the
previous attempt's problems as negative context.

### Checker

Two **separate** calls, with no shared context, so a problem in the reduction
cannot colour the judgement about triviality:

1. *Assuming every child is true, does the reduction establish the parent?*
2. *Is any child a restatement of the parent, or as hard as the parent?*

Each returns located problems or an explicit "none found, having checked the
following" — the `checked` list is required either way, because a reviewer that
can pass anything by saying nothing will pass bad proofs.

The third question an earlier design asked — *are the needed hypotheses
available?* — is deliberately **not** asked here. It already has a better answer:
completeness from `bp/discharge.py`, deterministically; entailment from the
verifier, one narrow obligation at a time.

### Verifier

Two jobs, kept apart.

*Obligation checking.* Consume the obligation list one record at a time: does
this source give this hypothesis, for this object? No proof search, no strategy,
no whole-proof context. Narrow questions are where model judgement is most
reliable, and the list is complete by construction. Results are cached on the
obligation hash in `.bp/verify/obligations.json`, so editing one paragraph of a
proof does not re-bill the rest. `ADMITTED` discharges are not sent at all —
they are already visible debt.

*Whole-proof pass.* Statement, proof, and the children's statements **as
assumptions**. Two backends, different families, no shared context.

Then a **confirmation pass** over every objection from either job: it is
re-presented with surrounding context and dropped if the flaw dissolves. This is
not optional. Without it the output is mostly pedantry, the user stops reading
it, and the real objection goes with the rest. Withdrawn objections become notes
on the node rather than disappearing.

Two failure modes are handled explicitly, because both would be silent:

- Running out of budget is **not** a verifier declining to object, so
  `BudgetExceeded` is re-raised rather than caught by the panel's fault
  tolerance.
- If **no** panel member answered, `verify` refuses to record a verdict at all.
  Silence from every verifier is not agreement, and recording `verified` there
  would turn a network outage into a green graph.

### Prover

`routine` and `standard` leaves only. Not because a model could not attempt a
hard lemma, but because proving the cheap leaves first is a *falsification test
on the strategy*: if a bookkeeping lemma the decomposition requires turns out to
be false or to need a hypothesis nobody has, the strategy is wrong and it cost a
few cheap attempts instead of three weeks.

It **never sets `local_status`.** It writes prose into the Proof section and
stops; whether that prose is a proof is the verifier's judgement, made
separately, and the verifier is not told who wrote it.

A refusal is a result. `attempted: false` with a reason — needs an idea, missing
a hypothesis, the statement looks false — is often the most valuable thing this
role produces, because it is usually a fact about the *decomposition* rather than
about the lemma. Steps it could not justify go into `gaps`, which become `% GAP:`
comments in the proof and a note on the node.

---

## 14. Recompile, jobs and resume

`bp recompile` verifies only what needs it — nodes that are **stale** or
**unverified with a proof** — and then sweeps. Within that set it works in an
order that makes a partial run useful: the path to the target first, shallow
before deep. A partial run should leave the user closer to knowing about their
theorem, not about an unrelated branch.

**The bill is previewable.** `--dry-run` prints the nodes, the call count and an
estimated cost, computed from the prompts that would actually be sent, before any
of them happen. Confirmation calls are excluded and the preview says so — they
happen only for objections, and how many there will be is not knowable in
advance. With subscription backends there is no dollar figure and it reports call
counts instead of printing a reassuring `$0.00`.

**Results write as they land**, through `ops`, so an interrupted run keeps
everything it paid for.

**Resuming performs no duplicate paid work.** A job record is written to
`.bp/jobs/<id>.json` *before* any work happens and updated after **each** task,
so the file on disk is always at least as current as the paid work done. Task
granularity is one node's verification — fine enough that losing one is cheap.
`bp resume [job_id]` re-reads the record and skips completed tasks; the
obligation cache means even a re-entered task mostly hits cache rather than the
network.

---

## 15. The web interface

`bp ui` serves it; this is the intended daily surface and the CLI is the testing
scaffold. FastAPI, vanilla JavaScript, no build step and no npm — Cytoscape for
the graph and KaTeX for the mathematics, either from a CDN or vendored locally by
`bp ui --vendor`. A webpack config would be a liability for the person
maintaining this.

Two rules shape the whole package.

**The interface contains no logic of its own.** Every endpoint is a thin wrapper
around a function that already exists in `ops.py`, `roles/`, or the derived
layer. Nothing in `bp/ui/` decides a status, computes a support set, ranks a
frontier or interprets a diagnostic. When the interface needed a derived fact it
did not have — the ranked frontier — the ranking went into `bp/frontier.py` and
the endpoint returns it. That is what keeps the browser and the terminal from
telling the user two different stories about the same graph, and the UI tests
assert it directly by comparing the endpoint's answer to the core's.

**Nothing blocks.** Reads derive in memory and answer in milliseconds. Role calls
go to a worker thread; the request returns a job id and the page polls every two
seconds. The agent layer's `observer` hook reports each call as it starts, so the
strip in the action bar says *"Decomposing gclm.critical-scale-domination —
decomposer (default) — call 1"* rather than showing an anonymous spinner for four
minutes.

### Layout

Graph left, detail right, action bar on top.

The **graph panel** is Cytoscape with a hierarchical (`breadthfirst`) layout.
Fill encodes `global_status` — green proved, blue-green proved-modulo, amber
blocked, grey open, red unsound — with a dashed border for stale and a thicker
one for flagged. The chevron at a node's left edge folds its subtree **in the
view only**: no request is made, nothing is written, and the fold is a property
of that browser tab. The legend is always visible and can be collapsed when a
wide graph reaches it.

The **detail panel** renders the statement and proof with KaTeX — typeset
mathematics, never raw source — with an *edit* toggle that swaps in a textarea of
the LaTeX. The user writes source and reads it typeset; there is no rich-text
editor. Node ids in backticks become links. The status line spells out `support`
and `blocked_by` rather than leaving ids for the reader to chase, and the
buttons beneath cover every operation: Expand, Redo, Generate proof, Verify,
Check decomposition, Add child, Add note, Mark admitted, Mark assumption,
Relabel, Archive, Why.

The **action bar** carries the support certificate, then Frontier, Recompile
(which shows the dry-run bill and requires confirmation before spending),
Render LaTeX (source, `.tex` download, and a compiled PDF when a TeX toolchain
is present), Check, History and Agents.

### Two things the interface must get right

*Editing a statement warns before it commits.* The Save button first asks
`/api/node/{id}/stale-radius` and shows exactly which verifications the edit will
invalidate — this node, and every node whose verification cited it. Only then
does it write. Discovering the blast radius afterwards is how a user learns to
distrust the tool.

*No untrusted HTML, ever.* Statements and proofs are LaTeX written by models.
Prose enters the DOM through `textContent`; mathematics goes through
`katex.renderToString`, whose output is the only HTML the script inserts. In the
terminal, mishandling this was cosmetic — `\[` displayed as `[`. In a browser it
is script execution, and a test asserts there is exactly one `innerHTML`
assignment in the file.

### Concurrency

One worker thread, so one role call at a time. Individual mutations are ordered
by `bp.ops.serialised`, a process-wide re-entrant lock: a mutation is *read the
graph, change it, sweep, write the derived fields*, and two of those interleaving
would let one sweep persist values computed before the other's edit.

A job does **not** hold that lock across its whole body. It did at first, and
that froze every edit in the interface for the minutes a decomposition takes,
including edits to nodes the job would never touch. Instead, an operation on a
node an agent is currently working on is **refused** with a 409 naming the node —
and the page has already disabled those buttons. The rest of the graph stays
live, which is what the brief asks for.

Two *processes* — a UI and a CLI at once — are still unguarded. That is the
locking row in `UPGRADE.md`, and L2 is what makes it easy to hit.

### The API surface

| Read | |
|---|---|
| `GET /api/graph` | nodes, edges, counts, the support certificate |
| `GET /api/node/{id}` | everything the detail panel shows, including obligations |
| `GET /api/why/{id}` | the explanation chain, as depth-tagged lines |
| `GET /api/check` | every diagnostic |
| `GET /api/frontier` | the ranked queue |
| `GET /api/events` | the log, newest first |
| `GET /api/agents` | roles, backends, budget, calls logged |
| `GET /api/node/{id}/stale-radius` | what an edit would invalidate |
| `GET /api/render[.tex|.pdf]` | the document |
| `GET /api/recompile/plan` | the dry run — synchronous, because it costs nothing |

| Write | |
|---|---|
| `POST /api/node/{id}/{statement,proof,note,admit,assume,relabel,archive,child,children}` | one `ops` call each |
| `POST /api/sweep` | re-derive and persist |

| Jobs | |
|---|---|
| `POST /api/jobs/{expand,redo,check-decomp,verify,prove}/{id}` | returns a job id |
| `POST /api/jobs/{recompile,resume}` | returns a job id |
| `GET /api/jobs[/{id}]` | status, step, call count, result |

---

## 16. Not built yet

**L3** is driven by the friction log from using L2, not planned in advance. Ask
the user for theirs.

See `UPGRADE.md` for what is deferred from the full design, and why each
deferral is safe.
