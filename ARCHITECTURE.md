# ARCHITECTURE.md — what Albatross currently is

Written for someone who has never seen the code. Current as of **L2**: the
deterministic core, the agent layer, and the web interface.

Sections 1–11 are the deterministic core. Nothing in them calls a model, and all
of it runs with no key, no network and no configuration. Sections 12–14 are the
agent layer. Everything there is built *on top of* the core and never around it:
an agent proposes, the core checks, and the core decides what the graph says.

**Read section 0 first.** It is what the system guarantees and what it does not,
and it is the only section that matters if you are deciding how much to trust a
green node.

---

## 0. What this guarantees, and what it does not

The governing principle, and everything below is a consequence of it:

> **Agents supply judgement. Code supplies the guarantee that the judgement was
> complete.**

Whether a claim is true cannot be checked deterministically. That every claim was
enumerated, assigned a source, and dispatched to a verifier *can* be, and is.

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

### What the deterministic layer guarantees

These hold absolutely. They are properties of the code, they are asserted after
every sweep, and no agent can affect them:

- **The graph is acyclic**, and every citation resolves to a node that exists and
  is active (`REF001`–`REF008`).
- **Status propagation is correct.** `global_status` is derived, in one pass, from
  the `local_status` opinions beneath it. A node marked `proved` has no
  descendant that is not `proved` or `proved_modulo`, an empty support set, and
  carries every admitted step its children carry. `bp/propagate.py` asserts all
  of that in production, not just in tests.
- **A verification is invalidated when anything it depended on changes.** Each
  verification records the statement hash of the node and of every child. Move
  any of them and the node is `blocked:stale`. Hashing is over raw text, so it
  over-invalidates rather than under-invalidates; that is the safe direction.
- **Every child hypothesis has a named source or there is a hard error.** No
  exceptions, no defaults, no silence. A hypothesis you cannot source has to be
  written `ADMITTED: <reason>`, which is visible debt that propagates into the
  support certificate (`DIS010`–`DIS017`).
- **Every extracted claim has a named source or there is a hard error.** Same
  rule, applied to what the proof asserts on its own account (`LED001`–`LED006`).
- **Every source produced an obligation record, and every record was
  dispatched.** The worklists come from `bp/discharge.py` and `bp/ledger.py`, not
  from a model deciding what is worth checking. Nothing is skipped because a
  model failed to notice it needed checking, and the record on the node says how
  many questions there were and how many were answered.
- **No agent writes a status.** `local_status` is set only by an explicit human
  decision (`bp admit`, `bp assume`) or *derived* from the verification record by
  `bp/verification.py`. `ops.record_verification` re-derives it and refuses a
  verdict that disagrees with its own record.
- **The document is regenerated from the node files, every time.** It holds no
  state and cannot drift from the graph.

That is complete bookkeeping, and it contains **no mathematical content
whatsoever**. Not one of those guarantees says anything is true.

### What the agent layer contributes, and its ceiling

Every mathematical judgement in the system. All of it.

The design does what can be done about that: it makes each question as narrow as
possible, and it enumerates the questions deterministically. A model asked "does
`H1` give `H2` for this object" with nothing else in view is in a much better
position than a model asked "is this proof correct", and a clean verdict over a
generated worklist means *all N enumerated checks passed* rather than *nothing
caught my eye*. Narrow questions with a complete worklist is the best available
configuration for LLM verification.

**It remains unsound.** Reported false-positive rates for LLM verification sit in
the same band across cross-model and conjunction-of-verifier setups, which is why
the response to disappointing verification is to narrow the questions further or
add a deterministic check — never to add a fourth model.

So:

> **A green node means "no agent found a problem in N enumerated checks at level
> L". It never means proved.**

The verification record exists so that this is legible rather than hidden. It
names the level, the counts, and the models, and `bp show`, the browser and the
rendered LaTeX all print it. A node verified at `quick` and one verified at
`deep` are not making the same claim, and collapsing them to one colour would be
dishonest in exactly the place this system must not be.

### Where the agent substitutes are weakest

The **statement auditor** (§13, `bp/roles/audit.py`) stands in for the
deterministic `VAC` and `CST` checks in `DESIGN.md` §8, which v0 defers. It is
weaker than both, in specific ways worth knowing:

- A constant-scope check walks a declared dependency table and finds a circular
  constant dependency *mechanically*. The auditor finds one by reading, so it will
  miss some. Question 4 catches the classic bootstrap error often enough to pay
  for the call, but "it found nothing" is not "there is nothing".
- A vacuity check exhibits a witness or reports the constraint system
  unsatisfiable. The auditor's answer is an **assertion**, and an assertion that a
  witness exists is not a witness. This is why its schema forces it to write the
  witness down and to distinguish `exhibited` from `not_found` from
  `out_of_reach`.

Its verdicts are therefore **prompts for the user's attention, not checks**.
Nothing in the system blocks on them: they become a note on the node and a line
on the record.

The other soft spot is the **extractor**. The ledger's guarantee is that every
claim *in the ledger* is sourced or errors — not that the ledger is complete. A
load-bearing claim the extractor did not list is invisible to `LED001`. That is
why the prompt is written the way it is, why the role reports what it
deliberately omitted, and why extraction is a translation task on a cheap model
rather than a judgement task.

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
    ├── bp/checks.py     integrity + discharge + ledger + hygiene → Diagnostics
    ├── bp/discharge.py  the `uses` table → one obligation record per discharge
    ├── bp/ledger.py     the `claims` ledger → one record per sourced claim
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

Verification is the same shape, with the worklist generated in the middle:

```
bp/discharge.py + bp/ledger.py    enumerate the questions — deterministically
    ▼
bp/roles/verify.py                three jobs, one narrow question at a time,
                                  each answer cached on the record's content hash
    ▼
bp/verification.py                assemble the record; DERIVE local_status from it
    ▼
bp/ops.py                         write it, re-deriving and refusing a mismatch
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

# The claim ledger (§6a). Written by `bp extract`, audited by LED001-LED006.
claims:
  - id: c1
    text: "\\partial_x\\omega(t,0) < 0 \\text{ on } [0,T_{\\max})"
    source: {kind: child, ref: gclm.elb-a}
  - id: c2
    text: "-u_x(t,0) \\ge c_a z(t)"
    source: {kind: child, ref: gclm.elb-b}
claims_of: '9f31c0aa72be'

# What was actually checked (§13a). `local_status` is DERIVED from this.
verification:
  checked_at: '2026-08-03T14:22:00+00:00'
  level: standard
  deterministic: {integrity: pass, children_used: pass, discharge: pass, ledger: pass}
  ledger: {claims: 2, unsourced: 0, checked: 0, flagged: 0, cached: 0}
  obligations: {total: 5, verified: 5, flagged: 0, cached: 3}
  whole_proof: {verifier_a: no_objection, verifier_b: no_objection}
  statement_audit: not_run
  models: {extractor: haiku-4.5, obligation: sonnet-5, verifier_a: opus-5}
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
| `verification` | `ops.record_verification` **only** | §13a. What was actually checked, at what level, by which model — and what `local_status` is derived *from*. |
| `claims` | `ops.record_ledger` **only** | §6a. The claim ledger: every load-bearing claim the proof makes, with its source. |
| `claims_of` | `ops.record_ledger` **only** | The hash of the proof text the ledger was extracted from. When it stops matching, `LED100`. |

`ops.set_authored` raises `ComputedFieldError` if anything tries to author one of
these. That is enforcement, not convention: the one thing an agent must never be
able to do is write its own global status — or its own ledger, or its own
verification record.

`local_status` is authored, but only in two ways: an explicit human decision
(`bp admit`, `bp assume`, each requiring a reason) or *derivation* from
`verification`. No role writes it. §13a.

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

## 6a. The claim ledger — the other half of the same device

The `uses` table covers the **children's** hypotheses. It says nothing about what
a reduction asserts on its own account. A proof that says

> by standard elliptic regularity, $\omega \in C^1$, hence…

has a load-bearing claim with no child, no hypothesis, and no entry anywhere.
That is premise smuggling in its purest form, and at research level it is the
dominant failure mode. The ledger closes it.

`claims` is a list on the node, keyed by id, in the order the proof makes them:

```yaml
claims:
  - id: c1
    text: "\\omega \\in C^1([0,T))"
    source: {kind: literature, ref: standard elliptic regularity}
  - id: c2
    text: "\\|\\omega(t)\\|_{H^s} \\le \\varepsilon_0 \\text{ for } t < T"
    source: {kind: child, ref: mff.elb-b}
  - id: c3
    text: "the map \\Phi is a contraction on B_R"
    source: {kind: none, ref: ""}
claims_of: 'f2c1a9b40e77'      # hash of the proof text it was extracted from
```

`kind` is one of `hypothesis`, `child`, `claim`, `literature`, `computation`,
`none`. A claim's `text` is a **math-mode fragment**, like a hypothesis's `tex`.

Two things about this field matter more than its contents:

**It is computed.** The extractor role (§13) produces it and
`ops.record_ledger` is its only writer. A ledger any other role could edit would
let the model that makes a claim decide the claim is sourced, and `LED001` would
stop meaning anything.

**It is a function of the proof text.** `claims_of` records the hash of the proof
it came from. When the proof moves they disagree, and `LED100` says the ledger is
describing an earlier proof rather than letting a stale audit pass for a current
one. `bp verify` at `standard` or above re-extracts when that happens, and skips
extraction entirely when it has not — an unchanged proof means an unchanged
ledger and there is nothing to buy.

### The audit (`bp/ledger.py`)

| Code | Sev | Catches |
|---|---|---|
| `LED001` | error | A claim with `source.kind: none` — an unsourced load-bearing claim |
| `LED002` | error | A `child` source naming an id that is not in `children` |
| `LED003` | error | A `hypothesis` source naming an id this node does not have |
| `LED004` | error | A `claim` source naming a later claim, or itself; or a duplicate claim id |
| `LED005` | warn | A `literature` source with no identifiable reference — "standard", "well known" |
| `LED006` | warn | A `computation` source with no artifact path |
| `LED100` | warn | The ledger was extracted from an earlier version of the proof |

Together with `DIS011`, this means **no load-bearing claim anywhere in a proof
can go unsourced without producing a hard error.**

A node with no ledger at all produces nothing. That is deliberate: at
`--level quick` the extractor never runs, and a check that fired on every
unextracted node would be noise on exactly the nodes the user has not asked about
yet. What the absence costs is recorded honestly on the node instead, as
`ledger: not_run`.

`LED005` and `LED006` are warnings rather than errors because a real result
vaguely cited is still a real result, and the claim check can judge it. Blocking
on them would train the user to ignore the ones that matter.

### Claim obligations

`bp obligations` emits one record per **sourced** ledger claim, `kind: "claim"`,
in the same shape as a discharge record and cached in the same namespace:

```json
{ "id": "ob:mff.energy-lower-bound:claim:c2",
  "kind": "claim",
  "parent": "mff.energy-lower-bound",
  "claim": "c2",
  "applied_to": "",
  "needed": "\\|\\omega(t)\\|_{H^s} \\le \\varepsilon_0 \\text{ for } t < T",
  "claimed_source": "child:mff.elb-b",
  "source_kind": "child",
  "source_text": "<statement of mff.elb-b>",
  "hash": "6b1f0c2ad4e9f715" }
```

Unsourced claims produce no record. `LED001` has already decided them,
deterministically; sending one to a model would be asking for an opinion on a
settled question, and inviting it to unsettle it.

`bp obligations --kind discharge|claim|all` picks the worklist.

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
fragments are wrapped in `$…$`.

The document loads `amsmath`, `amssymb`, `amsthm`, `mathtools`, `mathrsfs`,
`xcolor` and `hyperref` unconditionally, and `bbm`, `enumitem` and `float`
behind `\IfFileExists`, so a machine without them still builds. Then, if the
project has a `preamble.tex`, it is injected verbatim before `\title` — see §9a.

---

## 9a. The project preamble

`preamble.tex` at the project root, optional, edited from `bp preamble` or the
**Preamble** button. Everything in this system is written in the author's own
notation, so three separate things need to know what that notation means:

1. **The rendered document** includes it verbatim, before `\title`.
2. **Every agent** gets it in context (`roles/context.preamble_block`). This is
   the one that matters. A model shown `\ip{u}{v} \in \Hs` and no definitions
   does not say it cannot read the statement; it invents a meaning and answers
   confidently about it.
3. **The browser** parses it into a KaTeX macro map (`parsePreamble` in
   `app.js`), because KaTeX takes a macro map but does not learn from a
   `\newcommand` it has rendered. `\newcommand`, `\renewcommand`,
   `\providecommand`, `\DeclareMathOperator` (starred or not) and `\def` are
   handled, with arguments and nested braces. KaTeX has no optional-argument
   default, so `\newcommand{\f}[2][x]{…}` loses the default; `GUIDE.md` §6a says
   so.

The parse in (3) decides only how notation is *drawn*. Nothing about the graph
depends on it, which is the line `bp/ui` is not allowed to cross.

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
| `bp show <id>` | Everything about one node: discharge table, claim ledger, verification record |
| `bp graph` | The DAG as a tree, rooted at the target |
| `bp why [id]` | The status chain in plain English |
| `bp check [--format json] [--quiet]` | Every deterministic check. Exit 1 on error |
| `bp obligations [id] [--kind discharge\|claim\|all]` | The worklists as JSON: one record per discharge and per sourced claim |
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
| `bp extract <id> [--no-record]` | Build the claim ledger, then audit it (`LED001`–`LED006`) |
| `bp verify <id> [--level L] [--batch N] [--no-record]` | The three jobs the level calls for, then confirmation |
| `bp audit <id> [--no-record]` | The four statement questions. Never touches a status |
| `bp prove <id> [--force]` | Write a proof for a routine or standard leaf |
| `bp recompile [--level L] [--dry-run] [--budget N] [--batch N] [--node id]` | Verify every stale and unverified node |
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

The system talks about *roles* and never about models. Which model plays which
role is one edit to `bp.yaml`:

```yaml
agents:
  roles:
    decomposer: {backend: codex_cli,  model: default}
    checker:    {backend: claude_cli, model: opus}
    extractor:  {backend: claude_api, model: claude-haiku-4-5}
    obligation: {backend: claude_api, model: claude-sonnet-5}
    verifier_a: {backend: claude_cli, model: opus}
    verifier_b: {backend: openai_api, model: gpt-5.6}
    confirmer:  {backend: claude_cli, model: opus}
    auditor:    {backend: claude_cli, model: opus}
    prover:     {backend: claude_cli, model: sonnet}
budget:
  per_recompile_usd: 3.0
  max_calls_per_recompile: 40
```

That indirection costs a layer and earns three things.

It lets the expensive verifier move onto a subscription CLI when the bill gets
uncomfortable. It lets the two panel verifiers be put on **different model
families**, which is the whole reason there are two of them — two verifiers from
the same lab miss the same things.

And it is where **model tiering** lives, which is the difference between a
recompile you can afford and one you cannot. `extractor` is doing translation and
belongs on the cheap model. `obligation` answers the narrow entailment
questions — both discharge obligations and ledger claims, since they are the same
shape of question — and is the bulk of the calls at `--level deep`, so it belongs
on a mid model. `verifier_a`, `verifier_b`, `confirmer` and `auditor` need a whole
argument in view and belong on the strongest thing available. There is one
`obligation` role rather than two because two knobs that would always be set
alike are not two knobs.

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

## 13. The roles

Six of them: `decompose`, `check`, `extract`, `verify`, `audit`, `prove`.

Each assembles context deterministically (`bp/roles/context.py` — no model decides
what a model gets to see), asks for JSON against a pydantic schema, runs the
deterministic checks on what came back, and writes through `ops`. The prompts live
in `bp/roles/prompts/*.md` and are meant to be edited: prompt wording is where
most of the quality lives, and a mathematician should never have to open a `.py`
file to change what an agent is told.

**No role is ever asked an open-ended validity question.** Every one of them
consumes a deterministically generated worklist or a fixed list of questions, and
returns a structured verdict against it. That is not a style preference; it is the
only reason a clean verdict carries information (§0).

### Decomposer

**It decides whether to decompose at all, first.** The response carries a
`verdict` — `decompose`, `prove-directly` or `already-atomic` — with an
`assessed_difficulty` and two sentences of `assessment`. A pydantic validator
ties the shape to the verdict: `decompose` requires 3–7 children and a reduction
proof, the other two require neither, so a decline cannot arrive carrying
half a decomposition.

On a decline **nothing is written**. The assessment is kept as a note and the
user is offered *Write the proof* (the prover, on this node) or *Decompose
anyway*. Reporting rather than auto-proving is deliberate: auto-proving would let
one call decide both that a node needs no structure and what its proof is, and
would bypass the prover's own difficulty guard. `DECISIONS.md` D041.

*Decompose anyway* (`force=True`, `?force=1`) changes the **prompt** — the model
is told the user has overruled its judgement and asked for the best available
split — rather than skipping the check. Skipping it was the first
implementation, and a model that declined a second time returned an empty
decomposition which was then applied. A forced call that still declines is now a
`DEC001` warning fed into the ordinary repair round.

When it does decompose: one level. 3–7 children, each a section or a major lemma. The prompt says
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

### Extractor

Given a proof, return every load-bearing claim with the source the prose offers.
That is a **translation** task, not a judgement task, which is why it is the cheap
model and why its output is reliable enough to be a computed field. The value is
not in the extraction; it is in what `bp/ledger.py` can then say
deterministically (§6a).

The one failure mode worth engineering against is a model that invents a plausible
source to look helpful, because that converts a visible gap into an invisible one
— strictly worse than not running the role. The prompt says so at length: `none`
is the *correct* answer for a claim the proof simply asserts, and it is the single
most valuable thing the role produces. Structurally, `none` is also the schema
default, so an omitted source is unsourced rather than absent.

The role also reports what it deliberately left out, as a note, so a
suspiciously short ledger is legible rather than mysterious.

### Verifier

**Three** jobs, kept apart and separately cached. They exist separately because
they fail differently; merging them to save calls would give up the only thing
that makes agent verification worth running. Use `--level` for cost control
instead.

*1. Obligation checks.* Consume the discharge worklist one record at a time: does
this source give this hypothesis, for this object? No proof search, no strategy,
no whole-proof context. This is the **misattribution** check — the answer to "the
table says `H2` comes from `H1`, but does it?" `ADMITTED` discharges are not sent
at all; they are already visible debt.

*2. Claim checks.* One record per sourced ledger claim, in the same narrow shape:
does the named source justify this claim, as applied here? This is where premise
smuggling dies. A claim the prose attributes to a lemma that does not give it
looks exactly like a claim attributed to a lemma that does — until somebody asks
about that one claim on its own.

*3. Whole-proof pass.* Statement, proof, and the children's statements **as
assumptions**. Two backends, different families, no shared context. This catches
what per-claim checking cannot: gaps *between* individually correct claims, and
whether the claims collectively reach the conclusion.

Both worklists come from code, and that is the point: "no objection" then means
*all N enumerated checks passed*. Results are cached on each record's content hash
in `.bp/verify/obligations.json`, so editing one paragraph of a proof does not
re-bill the rest.

`--batch N` sends N obligation or claim checks per call. **It defaults to 1.**
Batching trades reliability for cost — a model asked ten questions at once answers
each less carefully — so it is opt-in everywhere. A batched reply that skips a
question fails that question closed, with a reason naming the batching: an
unanswered question is not a pass.

Then a **confirmation pass** over every objection from any of the three: it is
re-presented with surrounding context, the discharge table and the ledger, and
dropped if the flaw dissolves. This is not optional at any level. Without it the
output is mostly pedantry, the user stops reading it, and the real objection goes
with the rest. Withdrawn objections become notes on the node rather than
disappearing, and the record downgrades that panel member to
`objection_withdrawn` — otherwise a dissolved finding would keep the node flagged
forever.

Three failure modes are handled explicitly, because all three would be silent:

- Running out of budget is **not** a verifier declining to object, so
  `BudgetExceeded` is re-raised rather than caught by the panel's fault
  tolerance.
- If **no** panel member answered, `verify` refuses to record a verdict at all.
  Silence from every verifier is not agreement, and recording `verified` there
  would turn a network outage into a green graph.
- A run that does not read the proof — `--obligations-only` — cannot record
  either. It has not verified anything, whatever the obligations said, so it
  refuses up front and tells you to pass `--no-record`.

### Statement auditor

One call per statement, with **no proof in view** — a proof in the context would
let the model read the intended meaning off the argument instead of off the words.
Four fixed questions, each with its own field in the reply:

1. Is the statement well-posed — is every symbol bound, is the conclusion
   unambiguous?
2. Exhibit a concrete instance satisfying every hypothesis, or report that you
   cannot. A statement whose hypotheses cannot be jointly satisfied is vacuous.
3. Are the quantifiers in the intended order? Flag any `∀ε ∃δ` versus `∃δ ∀ε`
   ambiguity.
4. Does any constant depend, directly or transitively, on something the statement
   treats it as uniform in?

It **never touches a status.** Findings become a note on the node and one line
(`statement_audit: pass | flagged | not_run`) on the verification record. See §0
for why it is weaker than the `VAC`/`CST` checks it stands in for, and what that
means for how much its clean verdicts are worth. Runs at `--level deep`.

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

### Proof-reader

`bp/roles/tidy.py`, run when a statement is saved from the browser. It is the
narrowest thing in the system, and the two constraints are what make an agent
touching authored text acceptable at all:

*It may fix syntax; it may not touch the mathematics.* Not an index, not a
quantifier, not the direction of an inequality. Braces, `$`, `\left`/`\right`, an
environment closed with the wrong name, an obsolete `\bf`, an unambiguous
misspelled control sequence. Anything it believes is mathematically wrong goes
into `concerns`, **unchanged** — it is the author's theorem and it may be right
in a way the model has not seen. Commands defined in `preamble.tex` are correct
by definition.

*The author sees the rewrite before it is written.* `POST /api/tidy` writes
nothing; the browser shows the proposal beside the original with one line of
justification per change and a typeset preview, and the save happens only on
accept. A proof-reader that fails returns 502 and the page saves as typed — this
must never block an edit.

It runs on the `checker` role rather than a sixth entry in `bp.yaml`: that is
already a strong model everywhere, and pointing it somewhere cheaper is a
one-line change (`tidy.ROLE`).

---

## 13a. The verification record

`local_status: verified` must not be an opaque flag. Each node carries a computed
record of what was actually checked:

```yaml
verification:
  checked_at: '2026-08-03T14:22:00+00:00'
  level: standard
  deterministic: {integrity: pass, children_used: pass, discharge: pass, ledger: pass}
  ledger:       {claims: 11, unsourced: 0, checked: 0, flagged: 0, cached: 0}
  obligations:  {total: 7, verified: 6, flagged: 1, cached: 4}
  whole_proof:  {verifier_a: no_objection, verifier_b: objection_confirmed}
  statement_audit: not_run
  models: {extractor: haiku-4.5, obligation: sonnet-5, verifier_a: opus-5}
```

`bp/verification.py` assembles it and **derives** `local_status` from it:

```
verified  ⟺  no deterministic errors
           ∧ no unsourced ledger claims
           ∧ no flagged obligations
           ∧ no flagged claims
           ∧ no confirmed objections
           ∧ at least one whole-proof verifier answered
```

Anything else is `flagged`. Every input is either a deterministic diagnostic or a
count of agent answers; nothing here is a judgement. `deterministic` values are
`pass`/`fail`/`not_run`, and `fail` means *this family produced an error* —
warnings do not fail a node, because a check that blocked on `USE001` would train
the user to ignore the ones that matter.

**No role may set `local_status` directly.** That is enforced, not trusted:
`ops.record_verification` re-derives the status from the record it is handed and
refuses a verdict that disagrees with it. A role that could pass `verified`
alongside a record full of confirmed objections would be setting the status by the
back door.

The record's absence is also honest. A node verified before the record existed, or
by hand, reports "never verified" in the record line rather than claiming a level.
An empty `ledger` block means no ledger was available — reporting `unsourced: 0`
from a ledger nobody extracted would be a claim about claims nobody enumerated.

`bp show`, the browser, and the rendered LaTeX all print a compact form. The
renderer's line is generated text throughout — level names, role names, counts —
so it goes through `render.escape`, not `render.prose`: `verifier_a` in LaTeX text
mode is "Missing $ inserted" and no PDF.

---

## 14. Recompile, jobs and resume

`bp recompile` verifies only what needs it — nodes that are **stale** or
**unverified with a proof** — and then sweeps.

### Levels

Agent-checking every claim is expensive: a node with a ten-claim proof runs
roughly fifteen calls at full depth, so a thirty-node graph is several hundred.
So recompile is tiered rather than being one thing you either can or cannot
afford.

| `--level` | Runs | Use for |
|---|---|---|
| `quick` | deterministic checks, whole-proof pass | fast sanity check while iterating |
| `standard` (default) | + extraction, ledger audit, obligation checks | routine work |
| `deep` | + per-claim checks, statement audits | before trusting a subtree, or writing it up |

Confirmation is in **every** level; see §13. `--level` is also the honest name for
what the levels are: three different claims about a node, which is why the level
is written onto the record and printed everywhere the status is.

`bp verify --level L` applies the same tiering to one node. Resuming an
interrupted run keeps the level the run *started* at — it is stored on the job
record — because finishing a `deep` run at `quick` would leave half the graph
claiming a scrutiny it did not get.

### Cost control

**Nothing is re-billed.** Every obligation and claim record carries a content
hash, and an unchanged record is answered from cache. Extraction is skipped
outright when `claims_of` already matches the proof on file.

**Model tiering.** Extraction on the cheap model, obligation and claim checks on a
mid model, whole-proof and confirmation on the strong one. All nine roles are
configurable in `bp.yaml`; the registry's defaults say the same thing.

**`--batch N`** sends N narrow checks per call, default 1. See §13.

**`--budget N`** caps the run at N model calls, replacing the configured caps.

**Value ordering.** The path to the target first (shallow before deep, since a
decomposition near the target may reshape everything under it), then the frontier
— the nodes where work is actually possible right now — then everything else. A
run stopped by `--budget` should have spent its money where it mattered.

**The bill is previewable.** `--dry-run` prints the nodes, the per-node jobs, the
call count and an estimated cost, computed from the prompts that would actually be
sent, before any of them happen. Confirmation calls are excluded and the preview
says so — they happen only for objections, and how many there will be is not
knowable in advance. With subscription backends there is no dollar figure and it
reports call counts instead of printing a reassuring `$0.00`.

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
is present), Check, History, Agents and Preamble.

What counts as mathematics for KaTeX is `$…$`, `$$…$$`, `\[…\]`, `\(…\)` **and a
bare display environment** — `align`, `equation`, `gather`, `multline`,
`alignat`, `flalign`, `eqnarray`, `displaymath`, `CD`, starred or not, with no
delimiters around them, which is how people actually write. `aligned`, `cases`,
`split` and the matrix environments are deliberately not matched standalone: they
only occur inside mathematics, so the enclosing delimiter already covers them.

### Two things the interface must get right

*Editing a statement warns before it commits.* The Save button first asks
`/api/node/{id}/stale-radius` and shows exactly which verifications the edit will
invalidate — this node, and every node whose verification cited it. Only then
does it write. Discovering the blast radius afterwards is how a user learns to
distrust the tool. Before both, the proof-reader has offered its rewrite — see
§13 — and the author has accepted or rejected it.

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
| `GET /api/preamble` | `preamble.tex`, for the editor and the macro map |

| Write | |
|---|---|
| `POST /api/node/{id}/{statement,proof,note,admit,assume,relabel,archive,child,children,uses}` | one `ops` call each |
| `POST /api/sweep` | re-derive and persist |
| `POST /api/preamble` | replace `preamble.tex` |
| `POST /api/tidy` | propose a syntax-only rewrite; writes nothing; 502 if the role fails, so the page can still save |

| Jobs | |
|---|---|
| `POST /api/jobs/{expand,redo,check-decomp,extract,audit,verify,prove}/{id}` | returns a job id; `expand` takes `force` to overrule a decline, `verify` takes `level` and `batch` |
| `GET /api/recompile/plan?level=L` | the dry run, priced; synchronous, since it makes no calls |
| `POST /api/jobs/{recompile,resume}` | returns a job id; `recompile` takes `level` and `batch` |
| `GET /api/jobs[/{id}]` | status, step, call count, result |

---

## 16. Not built yet

**L3** is driven by the friction log from using L2, not planned in advance. Ask
the user for theirs. The first round of it is already in — bare display
environments, the project preamble, the decomposer's verdict, and the
proof-reader on save (`BUILD_LOG.md`, `DECISIONS.md` D039–D042) — and the list is
open.

See `UPGRADE.md` for what is deferred from the full design, and why each
deferral is safe.
