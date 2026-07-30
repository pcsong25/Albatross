# UI.md — the interface, every control and every colour

A complete reference for the browser interface (`bp ui`). If you want the workflow
rather than the reference, read [GUIDE.md](GUIDE.md); if you want to know how much
a green node is worth, read [ARCHITECTURE.md](ARCHITECTURE.md) §0.

Two facts to hold on to while reading:

- **The interface contains no logic of its own.** Every status, support set,
  frontier rank and diagnostic you see is computed by the core and serialised. The
  browser and the terminal cannot tell you two different stories about the same
  graph, by construction.
- **Reads are instant, model calls are not.** Anything that calls a model becomes
  a background job and the page stays live. Nothing ever blocks.

Buttons that spend money or time on a model are marked **⚡** below.

---

## 1. The page

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ Albatross   gclm.blowup is not proved yet…  3 proved, 2 open, …    [job strip] │
│             Frontier  Recompile…  Render LaTeX  Preamble  Check  Archive  …    │
├──────────────────────────────────────┬────────────────────────────────────────┤
│                                      │  gclm.energy-lower-bound  ★            │
│           the proof graph            │  [proved modulo] [proposition] [hard]  │
│                                      │  ─────────────────────────────────     │
│         ┌──────────────┐             │  Hypotheses                            │
│         │ ▾ gclm.main  │             │  Statement            [edit]           │
│         └──────┬───────┘             │  Proof                [edit]           │
│           ┌────┴────┐                │  Discharges           [edit]           │
│           ▼         ▼                │  Claim ledger         [re-extract]     │
│      ┌───────┐ ┌───────┐             │  Verification record                   │
│      │ elb-a │ │ elb-b │             │  Objections                            │
│      └───────┘ └───────┘             │  Notes                                 │
│                       ┌────────────┐ │  Actions                               │
│                       │ Status ▾   │ │  [Expand] [Verify] [Why?] …            │
│                       │ ■ proved   │ │                                        │
│                       └────────────┘ │                                        │
└──────────────────────────────────────┴────────────────────────────────────────┘
```

Three regions: the **top bar** (whole-project actions, always available), the
**graph** (orientation), and the **detail panel** (one node, everything about it).
Everything modal — every sheet in section 5 — opens over the top of all three, and
**Escape** closes it. That is the only keyboard shortcut; there is no `j`/`k`
navigation yet.

The job strip and the graph refresh on a **2-second poll**. Fine for one person on
localhost, which is the whole design.

---

## 2. The top bar

The line under the word *Albatross* is the **support certificate** for the target
theorem, at a glance — the single most important sentence in the interface:

| It reads | It means |
|---|---|
| `<target> is proved.` | Nothing outstanding. No admitted step, no assumption, no unfinished lemma. |
| `<target> holds relative to N item(s).` | Everything else is proved outright; these N are the debt. They are listed on the target's own panel under **rests on**. |
| `<target> is not proved yet. <reason>` | The plain-English reason, same text as **Why?**. |
| `no node is marked target: true` | Set `target: true` on your theorem, or the certificate and `bp why` have nothing to be about. |

Then the counts — `3 proved, 2 open, 1 blocked:children` — a tally of
`global_status` **over active nodes only**. Archived nodes are excluded from the
graph, the counts, the certificate and the document.

| Button | Does | Calls a model |
|---|---|---|
| **Frontier** | The ranked list of nodes where work is *possible right now*: unfinished, with everything beneath them finished. Columns: node / needs / difficulty / gates / depth. Click a row to select that node. | no |
| **Recompile…** | Bulk re-verification, with the bill previewed first. See §5.2. | only after you confirm |
| **Render LaTeX** | The unified `.tex` for the whole graph, plus `.tex` download and PDF. See §5.3. | no |
| **Preamble** | Edit `preamble.tex`, and see how many macros the browser managed to parse out of it. See §5.4. | no |
| **Check** | Every deterministic check over the whole project, as a diagnostic list. No model is involved in any of it. See §5.5. | no |
| **Archive** | What is out of the active graph, with a **Bring back** button each. Nothing is ever deleted. | no |
| **History** | The last 200 entries of the append-only event log, newest first: when / what / node / who. | no |
| **Agents** | Which model plays which role and whether it can run here — the only place that tells you a backend is unusable *before* you spend a click. Also the budget caps, the call-log size, and whether the server is in `--replay`. | no |

### Why the Frontier is the right place to start

A theorem blocked by three unproved lemmas is not a place to work; its lemmas are.
The Frontier applies exactly that rule, so a `blocked:children` node never appears
on it. Ranking is shallow-first (a decomposition near the target may reshape
everything under it, so deep work risks being thrown away), then by how many nodes
each item **gates**.

The **needs** column translates a status into an instruction: *decompose it, or
write a proof* / *verify the proof* / *re-verify: the statement moved* / *resolve
the objection*.

---

## 3. The graph

Nodes are the active graph; arrows point **parent → child**, i.e. in the direction
of dependency. Layout is breadth-first rooted at the target, and the page opens on
the target.

- **Click** a node to select it into the detail panel.
- **`▸` / `▾`** at the start of a node's label folds and unfolds its subtree. `▸`
  means folded, and `(+N)` after the id counts how many nodes are hidden — counted
  transitively and de-duplicated, so a node reachable by another unfolded path
  stays visible even though it is counted. **Folding is view-only**: it makes no
  request, changes nothing, and is forgotten on reload.
- **`★`** marks the target. It is also drawn bold and slightly larger.

### The legend (top right of the graph, `–` collapses it)

Fill colour is the node's `global_status`. Border is an **orthogonal channel** —
two extra bits that ride on top of the colour:

| Swatch | Status | Fill |
|---|---|---|
| ■ green | `proved` | `#dff0e4` / border `#2e7d4f` |
| ■ teal | `proved_modulo` — *proved modulo* | `#d7eded` / `#2a7d7d` |
| ■ orange | `blocked` — **four different statuses share this colour** | `#fbead0` / `#b26a00` |
| ■ grey | `open` | `#eceae6` / `#7a7a7a` |
| ■ red | `unsound` | `#f9dedc` / `#b3261e` |
| ⌐ dashed border | **stale** | a verification expired |
| ▯ thick border | **flagged** | a verification failed |

Two things about this table are worth knowing:

**One orange, four meanings.** `blocked:stale`, `blocked:objection`,
`blocked:unverified` and `blocked:children` are all orange. Orange asserts only
*there is still work here*; the status pill in the detail panel says which, and the
status box says what to do about it.

**`unsound` cannot happen.** Nothing in this version refutes a node. The colour and
the sweep branch exist so refutation has somewhere to land. If you ever see a red
node it is a bug in the sweep, not a fact about your mathematics.

---

## 4. The detail panel

Sections appear in a fixed order, and each is omitted when it has nothing to say.

### 4.1 The id line and the pill row

`gclm.energy-lower-bound ★` in monospace, then four or five pills:

| Pill | Is | Means |
|---|---|---|
| coloured, e.g. `proved modulo` | **computed** | `global_status`, from one reverse-topological sweep over the whole graph. No agent can write it — `ops.set_authored` raises on any attempt. This is the only status that accounts for the whole subtree. |
| `proposition` | authored | The **role**, which is purely how the node is typeset in the document. Note `role: assumption` and `local_status: assumption` are different fields. |
| `hard` | authored | The **difficulty**, a guess. One mechanical consequence: the prover runs on `routine` and `standard` leaves only, so **Generate proof** is refused on a `hard` node until you **Relabel** it. It affects nothing else — not status, not colour. |
| `local: verified` | authored *or* derived | The opinion about **this one node**, asserting nothing about anything beneath it. See §6.2. |
| `stale` (orange) | computed | Shown only when stale. Because `blocked:stale` wins over every other case in the sweep, this pill appearing means the coloured pill definitely reads `blocked:stale`. |

**When the coloured pill and `local:` disagree, the coloured one is the truth about
your proof.** `local: verified` with a teal `proved modulo` pill means: this node's
own reduction is fine, and something underneath it is not paid for.

### 4.2 The status box

First row: the derived, model-free explanation of the current colour. Then, when
non-empty:

| Row | Is |
|---|---|
| **rests on:** | The **support set** — everything this node's proof still depends on that has not been argued: admitted nodes, assumptions, and nodes carrying `ADMITTED` discharges. Each with its `local_status` and its reason. This is *not* the child list; it is the debt. |
| **blocked by:** | Only for `blocked:children`: the specific children still `open` or blocked. Finished children are omitted, so this names where the work actually is. |
| **cited by:** | The node's parents. A node can have several — that is why the graph is a DAG and why archiving something may leave it active, still cited elsewhere. |
| `hash <12 hex>` | The statement hash. Verifications record it; any change invalidates them. It is bookkeeping, not identity — the **node id** is the stable identifier. |
| `has a verification certificate` | `verified_against` is non-empty: some verification recorded which text it checked. It is **not** a proof certificate, and it does not imply the current status is verified. |

### 4.3 Hypotheses

This node's own hypotheses: a monospaced id and a maths fragment. **These are what
a parent must discharge when it cites this node** — so a node with no hypotheses
listed is a node whose parents will never be asked to discharge anything, which is
usually an omission rather than a fact.

`tex` is a *fragment*: write `s > 3/2`, not `$s > 3/2$`. The renderer adds the
dollars.

### 4.4 Statement and Proof

Typeset, with an **edit** button that swaps in a raw-LaTeX textarea. There is no
rich-text editor and there is not meant to be: you write LaTeX source and read it
typeset.

**Save ⚡** does three things, in order:

1. Sends the text to the **proof-reader** — one model call, syntax only. If it
   proposes a change you get the rewrite beside your original with a one-line
   reason per change and a typeset preview, and you pick: *Use the correction*,
   *Keep mine*, or *Skip and save*. The prompt forbids touching the mathematics —
   not an index, not a quantifier, not the direction of an inequality — and
   anything it believes is mathematically wrong goes into *concerns*, unchanged.
   A proof-reader that cannot run never blocks your save.
2. For a **statement** only: fetches the **stale radius** — every verification
   this edit will invalidate — and asks you to confirm. Editing a statement
   invalidates the verification *of* it and of every node that cites it, because
   the tool those proofs used changed underneath them.
3. Writes.

Editing a **proof** skips step 2: a proof edit does not move the statement hash, so
it invalidates nothing downstream.

### 4.5 Discharges

The mechanism that makes the whole tool worth using. One block per cited child: the
child id (clickable), `applied to <tex>` if given, then one row per hypothesis of
that child:

```
gclm.elb-b   applied to ω(t,·)
   H1 ← hypothesis:H1
   H2 ← child:gclm.elb-a
   H3 ← ADMITTED: the a priori L∞ bound is not established here
```

`ADMITTED` rows are drawn **orange**. An admitted discharge silently caps the
node's *effective* local status at `admitted` during the sweep — so a node whose
`local:` pill reads `verified` still shows teal `proved modulo` if any row here is
admitted, and the debt propagates all the way to the target's certificate.

**edit** opens a dialog that fetches each child's actual hypotheses and generates
one input per hypothesis. The rows you have to fill are exactly the rows the
discharge check will ask about — which is the whole idea. Sources:

| Source | Means |
|---|---|
| `hypothesis:H2` | a hypothesis of *this* node, by id |
| `child:some.id` | the conclusion of another lemma this node cites |
| `proof:<free text>` | established inline in this node's prose |
| `literature:<ref>` | from the literature — name it |
| `ADMITTED: <reason>` | not available, and you are proceeding anyway |

`proof:`, `literature:` and `ADMITTED:` take **free text, which is prose** — any
maths inside them needs its own `$…$`. (`applied_to` and a hypothesis `tex` are the
opposite: fragments, wrapped for you. Getting this backwards produces a document
that will not compile.)

**What the check does and does not do.** It verifies a source is *named*. It does
**not** verify the named source entails the hypothesis — you can write
`H2: hypothesis:H1` when `H1` does not give `H2` and the check passes. It catches
**omission**, not **misattribution**. Misattribution goes to the verifier as one
narrow question per row, at `standard` and above.

### 4.6 Claim ledger

The same idea, pointed at what the proof asserts *on its own account*. "By standard
elliptic regularity, $\omega \in C^1$, hence…" has no child, no hypothesis and no
entry anywhere — and at research level that is the commonest way a gap hides.

| You see | Means |
|---|---|
| *Not extracted.* | No ledger, so `LED001` cannot fire and a verifier's "no objection" cannot mean "all N claims were checked". One cheap call fixes it. |
| `c1  ω ∈ C¹([0,T))  ← literature: standard elliptic regularity` | A claim with a named source. |
| `c3  Φ is a contraction on B_R  ← UNSOURCED` (orange) | `LED001`, a hard error: a premise the proof is smuggling in. It does not mean the claim is false — it means nothing here justifies it. |
| *This ledger was extracted from an earlier version of the proof.* | `LED100`. The audit is describing text that is no longer in the file. Re-extract. |

`extract` / `re-extract` on the heading runs it. Do not hand-edit `claims`: it is a
computed field, regenerated from the proof text, and the writer refuses an
authored write. A ledger you could edit would let the thing making a claim decide
the claim is sourced.

**What this does not guarantee:** that the ledger is *complete*. Every claim in it
is sourced or errors; a load-bearing claim the extractor never listed is invisible.

### 4.7 Verification record

One line saying what this node's status is actually worth:

```
level standard; deterministic: all pass; ledger: 7 claim(s), 0 unsourced, 0 checked;
obligations: 6/6 verified, 0 flagged, 4 cached;
whole proof: verifier_a=no_objection, verifier_b=no_objection; at 2026-07-30T…
```

| Field | Read it as |
|---|---|
| `level quick\|standard\|deep` | The scrutiny received. **This is part of what the green means.** |
| `deterministic: all pass` | Per check family, from the last verification. `fail` means that family produced an **error**; warnings deliberately do not fail a node. `not_run` means the level did not include it. |
| `ledger: N claim(s), U unsourced, C checked` | `checked` is 0 below `deep` — the claims were enumerated and audited for having sources, not judged. |
| `obligations: v/t verified, f flagged, c cached` | `t` is what the code *generated*, so a clean run means all `t` enumerated questions were answered — not "nothing caught my eye". `cached` was reused from an identical earlier question. |
| `whole proof: verifier_a=…` | `no_objection` / `objection_confirmed` / `objection_withdrawn` / `did_not_answer`. **Silence is not agreement:** if every member reads `did_not_answer` the node is flagged for absence of evidence, not presence of a problem — check the Agents sheet. |
| `statement audit: pass` | Only at `deep`. Weaker than it sounds; see §5.7. |
| `never verified` | No record at all. Distinct from a record that implies flagged. |
| `flagged because: …` | Which of the derivation conditions failed, in English. |

### 4.8 Objections

One box per recorded flag: the kind in small red capitals, the reason, the quoted
passage, and which role raised it. Every objection here **survived a confirmation
pass** — it was re-read with surrounding context and not withdrawn. It still
asserts a model's judgement, not a fact.

### 4.9 Notes

Timestamped, attributed prose. **Notes are fed to every agent as context on every
later attempt at this node**, which makes *Add note* the main way to tell the tool
something it keeps getting wrong. Withdrawn objections, declined decompositions and
audit findings all land here.

### 4.10 Actions

The button row changes with the node.

| Button | Shown when | Does | ⚡ |
|---|---|---|---|
| **Expand** | no children | The decomposer: one level, 3–7 children, written as new files with the parent's `children` and discharge table updated. It first judges whether the node is *worth* decomposing and may decline. | ⚡ |
| **Redo** | has children | Copies the subtree to `attempts/`, archives it, decomposes again — sending the previous attempt's problems as negative context. | ⚡ |
| **Check decomposition** | has children | Two fixed questions: does the reduction establish the parent, and is any child a restatement or as hard as the parent. Writes nothing. | ⚡ |
| **Generate proof** | no children | The prover, on this leaf. Writes into the Proof section and **never sets a status**. Refused on a `hard`/`unknown` node. | ⚡ |
| **Verify** | a proof exists | Opens the level picker, then verifies. The verdict is **derived** from a record of what was checked. | ⚡ |
| **Extract claims** | a proof exists | Builds the claim ledger. One cheap call. | ⚡ |
| **Audit statement** | always | Four fixed questions about the statement. Writes a note, **never a status**. | ⚡ |
| **Add child** | always | A lemma you state yourself, attached as a child. The discharge table will then report its hypotheses as undischarged until you fill them in. | no |
| **Add note** | always | Appends to Notes. | no |
| **Mark admitted** | always | `local_status: admitted`, **reason required**. Believed but not argued. The node enters its own support set and the reason is printed in the certificate and the PDF. | no |
| **Mark assumption** | always | Same propagation; the difference is *intent* — given by choice rather than by omission. | no |
| **Relabel** | always | Changes difficulty. This is the gate on the prover. | no |
| **Why?** | always | The derived status in indented plain English, walking the `blocked_by` chain to the first honest reason on each branch. **The only button that stays enabled while an agent is working on the node.** | no |
| **Archive** | not the target | Red. The file and its text stay; `lifecycle` becomes `archived`, the node leaves the active graph, orphaned descendants go too, and citations to it are stripped from parents and recorded in the event log. Recoverable from the **Archive** sheet. | no |

**Why a button is greyed out.** Either an agent is working on this node — you get
an orange banner saying so, and the server independently refuses the write with a
409 — or the button does not apply (Expand on a node with children, Generate proof
on a node with children). The rest of the graph stays fully live either way:
ordering is per mutation, so a four-minute decomposition never freezes the
interface.

---

## 5. The sheets

One modal for everything. Escape or clicking outside closes it.

### 5.1 Frontier
Read-only. Clicking a row selects that node and closes the sheet.

### 5.2 Recompile…
Opens on a **dry run**: which nodes, why (`stale` or `unverified` — the only two
reasons anything is ever selected), how many calls, how many are cache hits, and an
estimated cost. Changing the **Level** re-prices immediately, so the bill for
`deep` is something you see *before* agreeing to it.

- **Run N call(s)** — starts it. Results write as they land, so an interrupted run
  keeps everything it paid for.
- **Resume interrupted** — continues the last interrupted run at **the level it
  started at**, re-querying nothing already done.

Recompile never touches an `open` node. A graph whose frontier is all `open`
reports "nothing to recompile" no matter how often you press it — those nodes need
**Expand** or **Generate proof** first.

Subscription backends report no price, so you get call counts instead of a
reassuring `$0.00`. With those, the **call cap** is the only thing limiting a run.

### 5.3 Render LaTeX
The unified `.tex` for the whole graph as plain text, regenerated on every request
— it holds no state and cannot drift from the graph.

- **clean** — omit every marker and all apparatus. This version is the paper.
- **audit** — add the discharge tables and the claim ledger.
- **Download .tex** — the source.
- **Open PDF** — compiles (two `pdflatex` passes, so `\ref` and `\eqref` resolve)
  and opens it. **If it does not compile, the reason appears in this sheet**, named
  and with the fix — a missing package gives you the exact `tlmgr install` command.
  A document that will not compile is a fact about the LaTeX, not a failure of the
  graph, and everything else in the interface is unaffected.
- Warnings appear here too: an unresolved `\ref` (the PDF prints `??`) or a
  duplicated `\label` (one silently wins, so a reference may point at the wrong
  place).

### 5.4 Preamble
Edits `preamble.tex`, which goes to **three** places: injected into the rendered
document, parsed into KaTeX macros so the browser typesets your notation, and
**included in every agent's context** — a model shown `\ip{u}{v} \in \Hs` with no
definitions will invent a meaning and answer confidently about it.

The sheet reports how many macros the browser parsed. If a macro of yours is
missing from that count it will still reach the document and the agents; only the
browser's display is affected. `\newcommand` with an optional-argument default is
the known gap.

### 5.5 Check
Every deterministic check, as a list of code / severity / node / message / hint. No
model is involved in any of it. See §7 for the code families.

### 5.6 Archive
Everything out of the active graph, with **Bring back** on each. Restoring does
**not** re-create the citations archiving removed from parents — re-citing is a
decision, not a mechanical undo — so a restored node usually comes back as an
orphan (`REF005`) until you add it to a parent's `children`. History records which
citations were stripped and from where.

### 5.7 Job-result sheets
When a job you started finishes, its result opens automatically. If a *different*
tab started it you get a toast instead.

The **statement audit** sheet is worth reading carefully. It reports four answers,
and its own limits:

- **witness** — `exhibited` means the auditor *wrote a witness down*. An assertion
  that one exists is not a witness, which is why `not_found` and `out_of_reach` are
  reported separately.
- **well-posed / quantifiers / constants** — `clean` or `SUSPECT`. `clean` means
  the auditor found nothing *by reading*. This role stands in for two deterministic
  checks that are not built yet and is weaker than both, so "it found nothing" is
  not "there is nothing". Nothing in the system blocks on its verdict.

### 5.8 Agents
Role → backend → model → usable. **The only place that tells you a backend cannot
run before you spend a click on it.** Also the budget caps, the number of logged
calls, and `Running with --replay` when the server resolves every call from the log
and can neither reach a provider nor cost money.

### 5.9 History
The append-only event log, newest first. Every mutation is here with its actor
(`human`, `decomposer`, `verifier`, `extractor`, `auditor`, `prover`), so "who
changed this and when" always has an answer.

---

## 6. Statuses in full

### 6.1 `global_status` — computed, never authored

| Status | Holds when | To move it |
|---|---|---|
| `proved` | Locally verified, every active child `proved`/`proved_modulo`, and the union of their support sets **empty**. | Nothing. This is the finished state — and it still does not mean the mathematics is right. |
| `proved_modulo` | Verified with all children finished, but resting on a non-empty support set; **or** admitted; **or** an assumption. | Read **rests on**. For each item: prove and verify it, or replace its `ADMITTED` discharge with a real source. Clears only when the support set empties. |
| `open` | `local_status: unverified` **and** no proof (whitespace and LaTeX comments do not count). | Expand, Generate proof, write it yourself, or Mark admitted/assumption. |
| `blocked:unverified` | `unverified`, but a proof exists. | Verify. This is why an unread attempt is a different state from no attempt. |
| `blocked:stale` | `verified_against` no longer matches this statement's hash or a child's. **Checked first in the sweep, so it overrides everything else.** | Verify again. **Why?** says which hash moved. Hashing is over raw text, so a whitespace change is enough — it over-invalidates, which is the safe direction. |
| `blocked:objection` | Effective local status is `flagged`. | Read **Objections** and the `flagged because:` lines. If the reason is "no verifier answered", that is an outage — check Agents. |
| `blocked:children` | This node's reduction is verified and clean, but a child is still open or blocked. Support is emptied. | Nothing here. Follow **blocked by**, or open the Frontier. |
| `unsound` | A verified node with an `unsound` child. | Unreachable in this version. |
| `archived` | `lifecycle: archived`. Excluded from the graph, counts, certificate and document. | The **Archive** sheet, or `bp unarchive`. |

### 6.2 `local_status` — an opinion about one node

| Status | Is | Notes |
|---|---|---|
| `unverified` | the default | Nobody has claimed anything. |
| `verified` | **derived** | Set only when the record shows: no deterministic errors, no unsourced claims, no flagged obligations, no flagged claims, no confirmed objections, **and at least one whole-proof verifier that actually answered**. The writer re-derives it and refuses a verdict that disagrees with the record. It says *"no agent found a problem in N enumerated checks at level L"* — nothing more. |
| `flagged` | **derived** | The complement. Also never chosen by a role. |
| `admitted` | human decision | Believed, not argued. Reason **mandatory** — the write is refused without one, because that text is what the certificate prints. |
| `assumption` | human decision | Mechanically identical to admitted; the difference is intent, recorded in the reason and in the PDF's wording. |

---

## 7. Diagnostic codes

From the **Check** sheet and `bp check`. Red chip = error (exit 1), orange =
warning, blue = note.

| Family | Covers |
|---|---|
| `REF001`–`REF008` | Graph integrity: a child that does not exist, a self-citation, a cycle (named in full), an archived child, an uncited node, no target or several. |
| `USE001` | A declared child the proof never mentions — a dependency that carries no weight. |
| `DIS010`–`DIS017` | The discharge table: a cited child with no entry, an undischarged hypothesis, an unrecognised source form, a source naming something that does not exist, `ADMITTED` with no reason. |
| `DIS100` | An admitted discharge, with its reason. Tracked, never an error. |
| `LED001`–`LED006` | The claim ledger: an unsourced claim, a source naming a non-existent child/hypothesis/claim, a forward or self-reference, a vague literature citation, a computation with no artifact. |
| `LED100` | The ledger was extracted from an earlier version of the proof. |
| `SCH001`–`SCH003` | A file that would not parse at all (reported rather than crashing), an unknown frontmatter key, `verified` with no proof and no children. |
| `SYS001` | The computed fields in a file are out of date. Harmless; run `bp sweep`. |

`LED005`, `LED006` and `USE001` are warnings on purpose. A real result vaguely
cited is still a real result, and a check that blocked on those would train you to
ignore the ones that matter.

---

## 8. Jobs, and what happens when things go wrong

The **job strip** names the first active job — what it is, on which node, and the
step it is in — then `(+N queued)`. There is exactly **one worker thread**, so
"queued" means literally waiting.

| You see | Means |
|---|---|
| pulsing orange dot | something is running |
| red toast, 7 seconds | any failed request or failed job, showing the API's own message verbatim |
| dark toast, 3.2 seconds | success. **This is the only confirmation you get** for a save, note, relabel or archive |
| *An agent is working on this node* | every action button but **Why?** is disabled, and the server will refuse a write with a 409 |

**Job state lives in memory.** Restarting `bp ui` mid-decomposition does not merely
lose the spinner — it kills the run, because the model subprocess is the server's
child. Work that has *landed* is safe: results write through to the node files as
they arrive, and `.bp/jobs/` plus the call log survive. But do not restart the
server during a long call.

---

## 9. Not in the interface

Deliberate omissions, so you do not go looking:

- **No authentication.** Single user, localhost, by design.
- **No keyboard navigation** beyond Escape.
- **No live updates** — a 2-second poll. Fine for one user; not fine if two people
  ever watch the same project.
- **No per-node agent-call history.** `bp calls --show <hash>` in a terminal prints
  the exact prompt and reply.
- **No editing of computed fields**, and no way to ask for one. `global_status`,
  `support`, `claims` and `verification` are derived; the writer refuses.
- **No partial expansion.** `Expand` refuses a node that already has children;
  `Redo` archives them first.
- **No un-`Redo`.** The previous subtree is in `attempts/<node>-<n>/`, by hand.
