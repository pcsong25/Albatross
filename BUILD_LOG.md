# BUILD_LOG.md

Append-only. One entry per milestone.

---

## L0 — Deterministic core, no agents

**Date** 2026-07-29

### What was built

The whole deterministic layer: a proof graph that loads from hand-editable
markdown files, checks its own integrity, derives every node's global status
from the local opinions written into it, explains that derivation in English,
and renders the lot to a compilable LaTeX document.

Nothing here calls a model, and there is no UI, per the milestone's *do not
build* list.

### Files added

```
pyproject.toml  .gitignore
CLAUDE.md  ARCHITECTURE.md  DECISIONS.md  UPGRADE.md  BUILD_LOG.md
bp/__init__.py       package docstring stating the four non-negotiables
bp/model.py          Node, Hypothesis, Use, Flag; body sections; the citation matcher
bp/paths.py          project discovery, .bp/ layout
bp/diagnostics.py    Diagnostic; err/warn/info; stable sorting
bp/load.py           comment-preserving frontmatter read/write; atomic writes
bp/hash.py           statement_hash, is_stale, certificate
bp/graph.py          the DAG, ordering, integrity REF001-REF008
bp/discharge.py      DIS010-DIS017, DIS100, obligation emission
bp/checks.py         USE001, SCH001-SCH003, SYS001, the check runner
bp/propagate.py      the sweep and its invariants
bp/why.py            plain-English explanation
bp/events.py         append-only JSONL, UUID per event, fsync per append
bp/ops.py            every mutation
bp/render.py + bp/templates/document.tex.j2
bp/cli.py            the `bp` command
nodes/*.md           a six-node development, described below
tests/               142 tests
```

### The acceptance fixture

`nodes/` holds a real six-node development: finite-time blowup for the
generalised Constantin–Lax–Majda equation with small odd data, reduced to a
scalar Riccati inequality at the stagnation point. It was written as
mathematics rather than as filler, because the renderer's output is the real
gate for this milestone and filler would not have exposed anything.

It contains, deliberately: a proved leaf (`gclm.elb-a`), an admitted node
(`gclm.elb-b`), a node that is `verified` but carries an `ADMITTED` discharge
(`gclm.energy-lower-bound`), a stale node whose statement was edited after
verification (`gclm.blowup-criterion`), an unverified node with a proof
(`gclm.local-existence`), and a target whose `uses` table omits one hypothesis
of one child (`gclm.blowup`). Five of the eight global statuses appear.

### What the acceptance run showed

```
bp check        1 error, 0 warnings, 1 note over 6 active nodes; exit 1
                the error is DIS011 on gclm.blowup — the deliberately omitted
                discharge — and nothing else. Integrity is clean.
                The note is DIS100, the admitted discharge, with its reason.
bp obligations  10 records, one per discharge, 9 entailment and 1 admitted,
                each with a stable content hash
bp status       every global status correct by hand-inspection
bp why          "gclm.blowup has a verified reduction, but 2 of the lemmas it
                 uses are not finished: gclm.local-existence has a proof, but
                 nobody has verified it yet. gclm.blowup-criterion was
                 verified, but its own statement has been edited since…"
bp render       .bp/build/document.tex compiles under pdflatex to a 4-page
                document with a support certificate, coloured marks on every
                unproved node, and the admitted lemma in a labelled box
bp render --clean   compiles to 3 pages; no status apparatus at all
pytest -q       142 passed
```

The propagation invariants are asserted inside `sweep` itself, in production —
not only in tests — so the 25 random-DAG cases in `tests/test_propagate.py` are
genuine property tests: any generated graph that could make the derived layer
lie raises immediately.

### What surprised me

**A hex hash is a valid YAML float.** `896e63762324` — one of the fixture's real
statement hashes — parses as `8.96e+63762324`, which is `inf`. Written
unquoted, every hash of that shape would compare equal to every other, and
`is_stale` would start returning `False` for nodes whose statements had changed.
That is a failure in the *open* direction, in the one mechanism whose whole
purpose is to fail closed. Hashes are now always written quoted, and a hash that
comes back from YAML as a float is refused with an explanation rather than
coerced. Writing a realistic fixture found this on the first run; a fixture of
`hash: aaa` would not have.

**`python-frontmatter` discards a custom handler's parse.** `frontmatter.loads()`
rebuilds the metadata as a plain dict through `**kwargs`, so the `ruamel`
round-trip handler's `CommentedMap` — comments, key order, quote style and all —
was thrown away, and every write reformatted the user's file. Using
`handler.split()` and `handler.load()` directly fixes it. Node files are meant to
be hand-edited, so this was not cosmetic.

**The children-used check, specified as a substring search, is wrong for short
ids.** A node called `a` was reported as cited by the word *never*. Matching by
whole token instead.

**How much of the renderer's difficulty is escaping policy.** Everything in this
system is LaTeX — statements, proofs, notes, admission reasons, hypothesis
fragments — so escaping any of it destroys it, while escaping none of it lets a
stray `%` silently swallow a line. The rule that worked: escape ids and generated
labels, pass authored text through untouched except for a bare `%`, and treat
`hypotheses[].tex` and `applied_to` as math-mode fragments to be wrapped in
dollars. Getting that wrong is what produced the only two failures to compile.

### What was deferred, and why

Everything on the brief's deliberately-absent list, all recorded in
`UPGRADE.md` with its `DESIGN.md` section: binders and substitution maps,
numbered proof steps with typed justifications, constant tables, vacuity
witnesses, numeric falsification sweeps, LaTeX normalization, the strategy slot
library, Lean, and the rest of the check catalog.

Two smaller things were deferred within L0's own scope:

- **`unsound` is unreachable.** Nothing refutes a node in v0, so no leaf can
  produce it. The branch that propagates it is written anyway, so that
  refutation lands additively rather than into a hole.
- **`bp.yaml` does not exist.** Nothing in L0 needs configuration, and an empty
  config file invites people to put things in it. L1 introduces it for agent
  roles. See `DECISIONS.md` D015.

Sixteen decisions the brief did not settle are recorded in `DECISIONS.md`
(D001–D016). The two worth flagging to a reader: the target node is designated
by a `target: true` frontmatter field (D001), and an `ADMITTED` discharge clamps
the parent's status in the *derived* layer rather than by rewriting the author's
`local_status` (D004).

### Known limitation to state plainly to users

The discharge check verifies that a source is **named** for every hypothesis of
every cited child. It does **not** verify that the named source entails the
hypothesis. It catches omission, not misattribution. Misattribution is handed to
the verifier in L1 as a narrow per-obligation question — a far better position
than having it buried in prose — but until L1 exists, nothing checks it at all.
A user who believes the check is stronger than it is will over-trust green
nodes. This is stated in `ARCHITECTURE.md` §6 as well.

---

## L1 — Agents

**Date** 2026-07-29

### What was built

The agent layer, and the four roles on top of it. Every model call in the system
now goes through `bp/agents/`; nothing else imports an SDK or shells out to a
model, which is what makes the call log complete, the budget enforceable and
`--replay` able to reproduce a session offline.

No UI, per the milestone's *do not build* list.

### Files added

```
bp.yaml                          which model plays which role
bp/agents/
  base.py        Backend.complete: JSON, validated, retried once, logged, budgeted
  registry.py    role -> backend from bp.yaml; the price table
  log.py         the call log, which is also the --replay cache
  claude_api.py  openai_api.py  claude_cli.py  codex_cli.py  scripted.py
bp/roles/
  context.py     deterministic context assembly
  decompose.py check.py verify.py prove.py
  prompts/       decompose, check_reduction, check_triviality,
                 verify_obligation, verify_proof, verify_confirm, prove
bp/jobs.py       job records
bp/recompile.py  selection, the previewable bill, run and resume
bp/cli_agents.py the L1 commands
tests/test_agents.py test_roles.py test_recompile.py   (+88 tests, 230 total)
```

### What the acceptance run showed

This machine has the `claude` and `codex` CLIs and no API key, so the run used
the subscription backends — the case the whole role-indirection layer exists for.
The target was the shipped gCLM development rather than one the user supplied;
that substitution is flagged in the report.

**`bp expand gclm.elb-b`** — the one genuinely hard node — produced three
children with difficulty labels (`standard`, `hard`, `standard`), a reduction
proof, and a complete `uses` table exercising all four source kinds. Clean on the
first attempt after a bug fix (below); `bp render` compiles the result to 5
pages, model-written LaTeX and all.

The mathematics was substantive rather than filler. The decomposer isolated the
missing comparison as its own node and then, unprompted, proposed a third child
asserting that a high-frequency family *contradicts* it — which is the
"constraint emission" behaviour `DESIGN.md` §12.8 describes, arrived at on its own.

**`bp check-decomp gclm.elb-b`** returned nine located problems across its two
calls, every one specific and quoted. The strongest: the decomposition is
internally contradictory — one child's conclusion is the negation of another's —
and no structural check can see that, because the graph only records that both
are cited. It supplied the counterexample family $f_n = -n^{-1}\sin(nx)$ and
named the child that should have existed and does not. This is precisely the
class of failure the checker is for, and it found it on the first real
decomposition it was ever shown.

**Kill and resume.** `bp recompile` selected two nodes and reported its bill
before spending it. The run was killed with `pkill` after the first node's
verdict landed. The job record showed `completed: [verify:gclm.blowup-criterion]`,
`pending: [verify:gclm.local-existence]`. `bp resume` then made **six calls, all
six about `gclm.local-existence` and none about the completed node** — verified by
diffing `.bp/agent/` before and after, which is the acceptance criterion.

**`--replay` with no network.** `bp expand --replay` reproduced the whole
decomposition from the log, instantly and offline.

```
pytest -q       230 passed
bp check        1 error, 1 note over 9 active nodes (the planted DIS011, unchanged)
bp render       compiles; 5 pages, 4 with --clean
```

### The verifier found a real error in my own fixture

The single most valuable output of the run. `gclm.blowup-criterion` — a lemma I
wrote by hand in L0 and believed — says that $z' \ge \kappa z^2$ with $z(0) > 0$
forces $T \le 1/(\kappa z(0))$ **and** $z(t) \to \infty$ as $t \to T^-$.

The second clause is false as written. $T$ is an arbitrary interval endpoint, not
the maximal existence time. Take $\kappa = 1$, $T = 1/2$, $z(t) = 1/(1-t)$: both
hypotheses hold, the bound on $T$ holds, and $z \to 2$.

Both panel members found it independently — Claude via `claude -p`, Codex via
`codex exec` — and all four objections survived the confirmation pass. The node
is now `flagged`.

It has been left flagged rather than quietly corrected. It is the honest state of
the graph, it is the acceptance evidence, and how to restate the lemma is the
user's call: either assume $T$ maximal, or drop the blow-up clause and keep the
bound on $T$, which is all `gclm.blowup` actually uses.

### What surprised me

**The single highest-value bug came from running it for real, not from tests.**
The prompt asks the decomposer to reference siblings by slug (`child:elb-a`),
because it cannot know the project's id namespace. `candidate_graph` translated
slugs to ids in the *keys* of `uses` and left the *values* alone — so every
`child:` discharge came back `DIS014`, and the repair round was spent on a problem
the system had invented for itself. Eighty-eight tests passed through this,
because every one of them used `hypothesis:` sources. The first real
decomposition hit it immediately. There is now a test for it.

**`BudgetExceeded` subclasses `AgentError`, and the panel was swallowing it.** The
verifier tolerates one panel member failing — the other still reads the proof.
That handler was also catching the budget cap, so a recompile ran straight past
its limit. Worse: a node whose verifiers had *all* failed was recorded as
`verified`, because no objections had been collected. A network outage would have
turned into a green graph. Both halves are fixed: `BudgetExceeded` and
`ReplayMiss` are re-raised, and `verify` refuses to record a verdict when no panel
member answered. Silence is not agreement.

**`rich` ate the mathematics.** `console.print` applies markup to strings, so a
statement containing `\[` displayed as `[` and `[0,T)` was read as a style tag.
The files were correct throughout — it was purely `bp show`. Everything authored
now prints as `Text`, never as markup. Worth remembering for L2: the same class
of bug, in a browser, is an XSS hole rather than a cosmetic one.

**Real models produce LaTeX in JSON with single backslashes, constantly.** The
repair path built on suspicion fired on the very first live call and on most
since. It is not an edge case; it is the normal case.

**Subscription CLIs are slow.** A decomposition prompt runs 5–15 minutes through
`codex exec`, against seconds for the same call on the API. Role timeouts are set
to 900s and anything driving these backends needs to expect minutes, which is
also why L2's async job design is not optional.

### What was deferred, and why

Within L1's own scope: the recompile is the model tier only — the cheap
deterministic tiers exist but are not wired in *below* the agents as a gate; there
is no watch mode; and there is no lock, so two concurrent `bp` processes would
both write the obligation cache and the last one would win. All three are new
rows in `UPGRADE.md` with the signal that says they are needed. The third gets
sharper in L2, where running the UI and a CLI at once is easy.

Thirteen decisions the brief did not settle are recorded in `DECISIONS.md`
(D017–D029). The two worth flagging: a decomposition that still fails after two
repair rounds is **written anyway** with its diagnostics reported (D020), matching
how the rest of the system treats debt; and the shipped `bp.yaml` points at the
subscription CLIs because that is what runs on this machine (D026) — with the
consequence, stated in the file, that the dollar cap can never fire and the call
cap is the only real limit.

---

## L2 — Web UI

**Date** 2026-07-29

### What was built

The interface the system was always for. `bp ui` serves a FastAPI app and a
vanilla-JavaScript page — no build step, no npm, Cytoscape and KaTeX either from
a CDN or vendored locally by `bp ui --vendor`.

Two rules shaped it, and both were tested rather than asserted:

**The interface contains no logic of its own.** Every endpoint is a thin wrapper
around something in `ops.py`, `roles/`, or the derived layer. When the interface
needed a derived fact it did not have — the ranked frontier — the ranking went
into `bp/frontier.py`, where the CLI can reach it too. `tests/test_ui.py` asserts
the endpoint's answer equals the core's, node by node.

**Nothing blocks.** Role calls run on a worker thread and the page polls. The
agent layer grew an `observer` hook so the action bar can say which agent is
working rather than showing an anonymous spinner.

### Files added

```
bp/frontier.py          the ranked queue — core, not interface
bp/ui/app.py            FastAPI; 32 endpoints, each one ops.py or roles/ call
bp/ui/jobs.py           background role calls
bp/ui/assets.py         `bp ui --vendor`
bp/ui/static/index.html app.js style.css   (+ vendor/, 23 files, ~1 MB)
bp/cli_ui.py            `bp ui`
tests/test_ui.py        33 tests (+34 total, 261)
```

### What the acceptance session showed

Driven through the same HTTP endpoints the page calls, against the live server,
with Chrome rendering the page for the visual checks.

The graph draws with status fills, a dashed border on the stale node and chevrons
on nodes with children. The detail panel typesets the statement and proof with
KaTeX — display maths, inline maths, and node ids as live cross-references — and
the status line spells out `blocked_by` rather than leaving an id to chase.

The session, in order:

- **Check** — the planted `DIS011` and the `DIS100` admission, unchanged.
- **Edit a statement, with the warning first.** The preview named both
  verifications the edit would invalidate (`gclm.blowup` and the node itself);
  the commit reported staling exactly those two.
- **Promote a child manually** — `gclm.hilbert-kernel-split`, typed as LaTeX.
- **Mark a node admitted** — with the empty-reason case correctly refused: *"admit
  requires a reason — it is what the support certificate prints."*
- **Recompile** — the dry-run bill first: two stale nodes, nine calls, and the
  note that confirmation calls cannot be predicted. The run then made **thirteen**,
  which is the preview's caveat being right rather than wrong.
- **Why** on a blocked node, and **the document**: LaTeX in a panel, a `.tex`
  download, and a 246 KB PDF from the Open PDF button.
- **Reload** — every change persisted: the new node, the admission, and the two
  nodes the statement edit staled.

A real decomposition was also started from the browser to photograph the async
path: the action bar showed *"● Decomposing gclm.critical-scale-domination —
decomposer (default) — call 1"* while the graph and the rest of the interface
stayed live.

```
pytest -q       261 passed
```

### The statement edit was a real fix — and the recompile showed it was only half of one

The L1 verifier found that `gclm.blowup-criterion` claimed $z \to \infty$ as
$t \to T^-$ when $T$ is an arbitrary interval endpoint rather than the maximal
existence time. The acceptance session used the edit-statement flow to correct
it: the bound $T \le 1/(\kappa z(0))$ always holds, and the blow-up clause now
says "if moreover $[0,T)$ is maximal". The warning named both affected
verifications before committing; the recompile then re-checked it.

**It came back flagged, correctly.** I changed the statement and not the proof,
and the proof still ends by letting $t \to T^-$ in $1/z(t) \le 1/z(0) - \kappa t$
— which never invokes maximality and does not give the conclusion. The verifier
said exactly that, and produced a second counterexample showing the repair is not
even a matter of bookkeeping: with $\kappa = 1$, $T = 1/100$, $z(0) = 1$ and
$z' = 3 + \sin(1/(T-t))$, the hypotheses hold and $z$ admits no $C^1$ extension,
yet $z$ stays bounded. Non-extendability can come from an oscillating derivative
rather than from blow-up, so "maximal as a $C^1$ function" is the wrong
maximality.

It also found a separate, unrelated gap on `gclm.blowup`: `gclm.local-existence`
gives continuation from $\int_0^T \|\partial_x\omega\|_{L^\infty}\,dt < \infty$,
and the proof restates it as boundedness of $\|\omega\|_{H^s}$, then uses that
misstatement to pass from $\|\partial_x\omega(t)\|_{L^\infty} \to \infty$ to the
theorem's $\|\omega(t)\|_{L^\infty} \to \infty$. That step is not justified by
anything cited.

Both are left flagged. `bp check` and `bp why` explain them, the render marks
them, and how to restate the lemma is the user's mathematics, not mine.

The loop is what matters here: found by an agent, edited by a human through the
interface with the blast radius shown before committing, re-checked by an agent,
and found still wanting — with the graph tracking exactly what each step
invalidated. It ran end to end in a browser, and it caught me being sloppy.

### What surprised me

**A lock held across a job froze the entire interface.** The job runner
originally took a write lock for the duration of a role call. With a
decomposition running, *every* edit anywhere hung — including on nodes the job
would never touch. The tests did not catch it because none of them ran a slow job
alongside an edit; driving the acceptance session did, immediately, when a `curl`
sat for two minutes and timed out.

The fix moved ordering to where it belongs: `bp.ops.serialised`, a process-wide
lock taken per mutation, because a mutation is *read the graph, edit, sweep,
write the derived fields* and two of those interleaving would let one sweep
persist values computed before the other's edit. Conflicting *operations* are now
refused with a 409 naming the node, which is what the brief asked for all along —
"a running job disables the buttons that would conflict with it and leaves the
rest live". Two tests now cover it.

**The dry-run's honesty was vindicated within the hour.** The preview said nine
calls and printed the caveat that confirmation calls happen only for objections
and cannot be counted in advance. The run made thirteen. A preview that had
quietly rounded to a confident number would have been wrong; the one that named
its own blind spot was right.

**`rich` and `innerHTML` are the same bug at different stakes.** In L1,
mishandling model-written LaTeX made `\[` display as `[`. In a browser the same
mistake executes it. The page therefore puts prose in through `textContent` and
mathematics through `katex.renderToString`, and a test counts the `innerHTML`
assignments in `app.js` — there is exactly one, and it takes KaTeX output.

**The legend collided with the graph, twice.** Bottom-left is where a deep tree
puts its leaves; top-right is where a wide one puts its. It is now top-right and
collapsible, which is the only answer that survives both.

### One deviation from the brief, flagged

The L2 button table says *"Check decomposition | the three checker calls"*. The
agent-layer specification in the same document says two, explicitly, and says not
to ask the third — hypothesis availability is answered better by the discharge
check (completeness, deterministically) and the verifier (entailment, one narrow
obligation at a time). L1 built two and L2 shows two. This is the earlier
discrepancy, unchanged; say so if you want the third.

### What was deferred, and why

Everything still on `UPGRADE.md`, plus the interface rows L2 made concrete:
per-node agent-call history, keyboard navigation, live updates instead of the
two-second poll, durable job state, and watch mode wired to the browser. None of
them is needed until the friction log says so.

Six decisions the brief did not settle are recorded in `DECISIONS.md`
(D030–D035). The one worth flagging: the frontier ranking went into the core
rather than into JavaScript (D030), because "the UI contains no logic of its own"
only means anything when it costs something.

### Ready for L3

`LIGHT.md` says not to plan L3 in advance, and to ask for the friction list at
the end of L2. That is the next thing I need from you.

---

## L3, first round — driven by the friction log

**Date** 2026-07-29

`LIGHT.md` says not to plan L3 in advance and to build against the user's
friction list. This is the first of it: they set every role to GPT-5.6 Sol at
`max`/`xhigh` effort, entered a real theorem — uniqueness for the fractional heat
equation — pressed Expand, and reported it running a long time on a simple
problem, plus two LaTeX complaints.

### The reported hang was not one

Diagnosis from the machine, not from theory: `bp ui` had been up ten seconds, no
`codex` process was running, `.bp/agent/` was empty, and the event log showed
only `add_node` and two `edit_statement`. The server had been restarted, and job
state lives in its memory with the model subprocess as its child — so the run was
gone, not stuck.

Timed the real thing to be sure: their exact decomposer prompt, at `max` effort,
returned in **3 minutes 24 seconds** with a complete decomposition, seven
hypotheses on its hardest child, and a note pointing out that the theorem does
not say what "solution" means. The pipeline was working the whole time.

`GUIDE.md` gained §5a — how to watch a run, what looks like a symptom and is not
(an empty call log during a call; an unchanged `nodes/`), and the one thing that
really does kill a run.

### Built

**Bare display environments render.** `\begin{align}…\end{align}` without
surrounding dollars is ordinary LaTeX and the splitter did not know it, so it
printed as source. Eleven math segments now detected in their statement where ten
were before, and the align block typesets.

**The document loads the packages people expect** — `mathtools`, `mathrsfs` added
unconditionally; `bbm`, `enumitem`, `float` behind `\IfFileExists` so a machine
without them still builds.

**`preamble.tex`.** The user asked for somewhere to put their own macros. It goes
three places, and the third is the one that matters: injected into the rendered
document, parsed by the browser into KaTeX macros, and **included in every
agent's context** — a model shown `\ip{u}{v} \in \Hs` and no definitions will
invent a meaning and answer confidently about it.

**The decomposer triages first.** It returns `decompose`, `prove-directly` or
`already-atomic` with an assessed difficulty and two sentences of reasoning. On a
decline nothing is written and the user is offered *Write the proof* or
*Decompose anyway*.

**Saving LaTeX runs a proof-reader.** Syntax only, diff shown, nothing written
until accepted. Tested live on deliberately broken input: it closed
`\begin{align}` that had been closed with `\end{aligned}`, added a missing
parenthesis, and replaced an obsolete `\bf` — three fixes, one line of
justification each, no mathematics touched.

```
pytest -q       280 passed
```

### What surprised me

**KaTeX does not learn a `\newcommand` it has rendered.** The documented-looking
trick of passing a shared `macros` object and letting definitions accumulate does
not work in 0.16.11 — I checked rather than assumed, and the second render failed
with "Undefined control sequence". So the preamble has to be parsed. An explicit
macro map works fine, arguments and all.

**`--force` that skips a check is not a force.** The first version of "decompose
anyway" ignored the verdict rather than overruling it, so a model that declined
twice produced an empty decomposition which was then written. Overruling belongs
in the prompt: tell the model the user has decided otherwise, and treat a second
decline as a repair round.

**The user's own file was the best test input available.** Every one of the three
LaTeX problems was visible in it, and none of them was visible in the fixture I
had written — because I write `\[…\]` and they write `align`.

---

## Addendum A — the claim ledger, three verifier jobs, and the verification record

**Date** 2026-07-29

### What was built

The addendum's Part 1 was already in (`DIS010`–`DIS017`, obligation emission, the
decomposer's `uses` table, the checker's third question deleted). Everything from
Part 2 onward is new.

**`bp/ledger.py` — the claim ledger.** The `uses` table covers the children's
hypotheses. It says nothing about what a reduction asserts on its own account, and
"by standard elliptic regularity, $\omega \in C^1$, hence…" is a load-bearing
claim with no child, no hypothesis and no entry anywhere. `claims` is now a list on
the node, one entry per load-bearing claim with the source the prose offers, and
`LED001`–`LED006` audit it. Together with `DIS011` the result is the sentence worth
remembering: **no load-bearing claim anywhere in a proof can go unsourced without a
hard error.**

Written against a hand-written fixture, as the addendum asks — the audit is
demonstrable with no model in the loop, and `tests/test_ledger.py` never calls one.

**Two computed fields, with their own writer.** `claims` and `claims_of` join
`verified_against` in the category of "derived, but not by the sweep".
`ops.record_ledger` is the only writer. `claims_of` holds the hash of the proof the
ledger came from, which is what makes staleness detectable at all (`LED100`).

**`bp/roles/extract.py` — the extractor.** Cheap model, because listing what a
proof asserts is *translation*, not judgement. The prompt spends a paragraph on the
one unacceptable outcome: inventing a plausible source converts a visible gap into
an invisible one, which is worse than not running the role. `none` is both the
correct answer and the schema default.

**The verifier is three jobs, separately cached.** Obligation checks
(misattribution), claim checks (premise smuggling), whole-proof pass (gaps
*between* correct claims). Both worklists come from code. `--batch N` batches the
narrow ones, default 1, and a batched reply that skips a question fails it closed.
Confirmation runs at every level.

**`bp/roles/audit.py` — the statement auditor.** Four fixed questions about a
statement with no proof in view. It writes a note and never a status, because it
stands in for `VAC`/`CST` and is weaker than both.

**`bp/verification.py` — the record, and the derivation.** `local_status` is now
*derived* from a record of what was actually checked. `ops.record_verification`
re-derives it from the record it is handed and refuses a verdict that disagrees —
so "no role may set `local_status`" is a property of the code rather than a
convention. `bp show`, the browser and the rendered LaTeX all print the record.

**Recompile is tiered.** `--level quick|standard|deep`, `--batch`, `--budget`,
`--dry-run` at each level, value ordering that puts the path to the target first
and then the frontier. Nine roles in `bp.yaml` so extraction, the narrow checks,
and the whole-proof pass can sit on three different model tiers.

```
bp check        2 errors — the deliberate DIS011 and the deliberate LED001,
                on exactly the claim the verifiers had also objected to
bp obligations  33 records (22 discharge, 10 claim, 1 admitted), hashes stable
bp render       compiles; --audit compiles too, which it did not before
pytest -q       388 passed
```

`bp recompile --dry-run` at the three levels: 4, 5 and 13 calls on the fixture,
with the cache credited and the per-node jobs named.

### What surprised me

**`verifier_a` does not typeset.** The verification record goes into the LaTeX, and
role names contain underscores — "Missing $ inserted", no PDF. The record is
*generated* text throughout (level names, role names, counts, a timestamp), so it
goes through `render.escape`. This is the fourth time the escape/prose distinction
has cost something in this repo, and the rule keeps holding: authored text is
LaTeX and passes through, generated text is not and must be escaped.

**A claim's `text` is a math-mode fragment, and I wrote it as prose first.**
Exactly the mistake already in `CLAUDE.md` about `Hypothesis.tex`, made again on
the new field one hour after reading the note about it. Both the renderer and the
browser now wrap it.

**`--audit` had never compiled.** Fixing my own bug exposed a pre-existing one: two
`proof:` discharge sources in the fixture contained bare math — `f\in C^1(\mathbb
S^1)` with no dollars — written by the decomposer months of tokens ago and never
typeset because nobody had run `bp render --audit` through `pdflatex`. Fixed in the
fixture, and the decomposer's prompt now says free-text sources are prose and need
their own dollars. A render path with no compile test is a render path that does
not work.

**A timestamp is the hex-hash bug wearing a different hat.** `checked_at:
2026-08-03T14:22:00+00:00` unquoted comes back from YAML as a `TimeStamp`, and
pydantic refuses it for a `str` field — so the node file would fail to load
entirely. Same fix as the hashes (`load.quoted`), same lesson: anything
scalar-shaped going into YAML needs to be asked what it parses back as.

**Two parts of the addendum disagreed about confirmation, and the resolution was
the cheap one.** Part 3 says never skip it; Part 5's table lists it only under
`deep`. Running it at every level satisfies both, because at `deep` there is
strictly more to confirm — and it costs nothing on a clean proof, since zero
objections is zero calls. `DECISIONS.md` D046.

**`--obligations-only` became incoherent the moment the status was derived.** It
produces a record with an empty `whole_proof` block, which correctly reads as
"nobody looked at this proof". The old code computed the verdict from flags alone
and would happily have written `verified` for a node no verifier had read. Now it
refuses up front. Deriving the status did not create that bug; it revealed it.

---

## L3 round two — the LaTeX round

**Date** 2026-07-30

Four things reported: "Render LaTeX" gave an internal server error; `enumitem` did
not work although it was in `preamble.tex`; `\label`/`\ref` did not work; and
cross-references between nodes were wanted, "maintaining a live and unified latex
file" being the suggested mechanism. Plus a user's guide, for open-sourcing.

### What was actually wrong

The reported bug took twenty minutes: `/api/render.pdf` raised **500** when pdflatex
failed, and the browser reached it by `window.open`, so the useful detail landed in a
new tab as raw JSON. And `enumitem.sty` is simply **not installed** here — this is
BasicTeX — so the user's unguarded `\usepackage` was a hard failure the tool declined
to explain.

Then I went looking for the rest, and the rest was worse. Every item below was
reproduced before being fixed.

**A document that says "is proved" because a node file would not parse.** One YAML
typo in a child; `load_nodes` skips it; the parent has one fewer child; the sweep
finds nothing unfinished; `bp render` emits *"top is proved. It rests on no admitted
step, no assumption and no unfinished lemma"* with the missing lemma nowhere in it,
and exits 0. Of everything in this log, that is the one that most directly violates
the point of the system.

**A pasted-in preamble could not compile.** `\newtheorem{lemma}` → "Command \lemma
already defined"; `\usepackage[hidelinks]{hyperref}` → "Option clash". Both certain
to appear in a real mathematician's preamble, both fatal on the first try.

**A blank line in a verifier objection killed the build.** `\bpmark` was a short
`\newcommand` taking model-written free text. `\long\def` was necessary and not
sufficient: `\textcolor{...}{#3}` is another short argument.

**A blocked chain five deep made the document uncompilable** — one nested `itemize`
per level, and `article` permits four.

**Open PDF downloaded rather than displayed** (Starlette defaults the disposition to
`attachment` once a filename is given), **compiled four times per click**, and
**corrupted under concurrency**: ten of thirty-six parallel requests returned 200
with a body that was not a PDF, including a zero-byte one.

**A failing compile served the previous run's PDF**, because the code checked only
`pdf.exists()`.

**pdflatex wraps its log at 79 columns mid-token**, so nine undefined references were
reported as four.

**The appendix was a divergent copy of the entry template** and gave an ADMITTED node
a QED box — a claim of proof in the one place the document must not make one.

### Cross-references

They already worked. Every node renders into one document and pdflatex runs twice; a
`\label` in one node resolves from another, verified by reading the `.aux`. What was
missing was every guarantee, and all of it silent: a dangling reference is a LaTeX
*warning* that prints `??`, a duplicated label resolves to one at random, the browser
rendered `\eqref` as literal garbage with **no error node**, and a reference was a
dependency the graph did not record.

`bp/xref.py` is a derived index — recomputed on every load like `Graph`, stored
nowhere. Which is also the answer to the stateful `.tex` file: forbidden by
non-negotiable 2, and unnecessary, because the renderer already produces the unified
document the user wanted. `XRF001`–`XRF005`; browser references become clickable
chips carrying the number LaTeX assigned, via `\tag`, which KaTeX does support.

```
bp check        2 errors on the fixture — both deliberate
pytest -q       518 passed (was 390)
render          default, --audit and --clean all compile
```

### What surprised me

**The user's premise was wrong and their goal was right.** "Maintain a live unified
`.tex`" is exactly the thing this codebase forbids, and the reason they wanted it —
working cross-references with real numbers — needed no state at all. Worth
separating those two before answering.

**An adversarial review found the hole in what I had just built, and it was the
silent kind.** `verified_against` records `self` plus each child's hash; a node
referencing another node's equation had no key for it, so editing that equation left
the referrer green. That is *under*-invalidation, which `bp/hash.py` exists to rule
out — it over-invalidates on purpose everywhere else. Two of three reviewers wanted
child→parent references to be a hard error, and this was their strongest argument;
closing it properly is what lets the check stay a warning and lets the user have what
they asked for.

**`\long\def` is not enough.** I fixed the short-argument bug and it still failed,
because `\textcolor{...}{#3}` puts the same free text into another short argument. A
fix that addresses the mechanism I noticed rather than the mechanism that failed is
not a fix; testing it was the only reason I found out.

**A pip install of this had never worked.** `pyproject.toml` shipped only
`templates/*.j2`, so an installed copy had no prompts and no web interface at all.
Invisible from a source checkout, fatal for every other user — and the whole point of
this round was preparing to open-source it. There is now a test that builds a real
wheel.

**`ops.unarchive` had existed since L0 and was reachable from nothing.** "Nothing is
destroyed" was a promise about the filesystem; the only way back was hand-editing
`lifecycle`.

### The citation layer (same round, after the user traced the reference)

The user found where `Section \ref{sec-space}` came from: **the statement of the
target theorem**, citing a section that was never provided. Their diagnosis was
right and sharper than mine had been:

> the self-containedness, consistency and completeness of the target theorem is never
> examined … at later expansion none of the children nodes has found out this issue …
> the verifier even passed the local proof. It means that there is a logic hole under
> the whole system.

Four layers had the information and none acted. They failed for one reason, and it is
this project's recurring lesson arriving a third time: **nobody enumerated the
references.** `DIS011` works because code iterates another node's `hypotheses`.
`LED001` works because code iterates an extracted ledger. Citations had no list, so
no layer could be asked a complete question about them, and each layer's silence
looked like assent.

Four answers, one per layer:

1. **`TGT001`/`TGT002`** — the target's statement has never been audited, or was
   audited against different words. Backed by `audited_against`, a statement-hash
   certificate written only by `ops.record_audit`. This is the layer that did not
   exist at all: nothing had ever looked at the root statement.
2. **`bp expand` refuses** a node whose own statement carries `xref` or `latex`
   errors, naming them, before spending a call. And the decomposer now gets
   `context.xref_block`, so it is told what its node cites — it had nothing.
3. **The verifier cannot pass it.** `xref` is a family in the verification record,
   so a dangling citation derives `flagged` at `quick`, with both panel members
   saying "no objection".
4. **Citations are obligations.** `reference_obligations_for` emits one record per
   resolving cross-node citation, checked at `--level standard` — a citation is as
   load-bearing as a hypothesis — carrying the *citing passage* as well as the cited
   text, because the question was never "does equation (3) exist" but "does equation
   (3) give what this sentence draws from it".

```
pytest -q       540 passed
bp check        the reported statement now fires XRF001 + TGT001
bp expand       refuses it, naming the code, before spending a call
bp verify       flagged at quick even with both verifiers clean
```

**What surprised me.** The prompt for the citation check had to name a failure I had
not thought of and which is probably the commonest: **a display that *defines*
something being cited as though it *asserted* something.** `\eqref{eq:defn}` where
the display is `z(t) := -\partial_x\omega(t,0)` gives nothing at all, because a
definition asserts nothing — and it reads exactly like a citation that works.

**What I got wrong first.** I had already built `XRF001` before the user wrote, and I
thought that closed it. It closed one layer of four. The user's framing — *a logic
hole under the whole system* — was the correct unit of analysis, and mine (*a missing
check*) was not.

### Refer, never assume

The user refined the rule, and the refinement is the mathematics:

> A child could refer its parent's equation, but it can never use it as a fact.
> Otherwise a logic loop occurs.

I had `XRF003` warning generically about upward citations, reasoning that they resolve
correctly so the cost is structural. Right about *naming*, wrong about *consuming*. A
child that takes a fact from its parent is in a loop with no bottom — the parent's
proof rests on the child — and the `children` relation stays acyclic throughout, so
nothing in the graph shows it.

Whether a particular reference names or assumes is a fact about the prose, so the split
is the division of labour this system already runs on: `xref.relation` enumerates the
loop candidates deterministically, and `prompts/verify_circularity.md` judges each one
with a single question. `CircularityVerdict.used_as_fact` rather than `entails`, because
the healthy answer is a **no** — and because asking a loop candidate the *support*
question gets "yes, the parent asserts it", which is true and exactly the wrong answer.

The rule is now stated in four places, one per actor that needs it: `XRF003`'s hint, the
shared role context, the decomposer's prompt (so it does not write such a child), and
the whole-proof taxonomy as `circular`.

Also, as asked: the Preamble sheet now shows what the renderer adds — every package
with its options, which are optional, the theorem environments, the `\bp*` macros, and
the generated preamble in full. `bp preamble --defaults` prints the same.

```
pytest -q       558 passed
```

**What surprised me.** Two things, both about where text ends up.

`Flag.why` is rewritten by the confirmation pass, which is correct — it sharpens the
objection. But for a circular citation the load-bearing half is *which node rests on
which*, a graph fact a model restating the objection will not reproduce. So that half
moved to `Flag.context`, which confirmation does not touch and which reaches the
browser and the document.

And the defaults list nearly shipped wrong in a way that would have been funny: the
template documents the collisions it avoids, and those comments quote
`\newtheorem{lemma}{Lemma}` — so the first version of the extractor reported `lemma`
twice. A tool for avoiding collisions that invents one.

### Every backend adjustable, and the file made complete

The user checked and said the four roles *were* in their `bp.yaml`. They were — in
`/Users/peicong/Albatross/bp.yaml`, the repo's own config, which their IDE had open.
The file `bp` reads for their project is `/Users/peicong/my-theorem/bp.yaml`, and that
one had five roles. Two files with the same name, and the wrong one is the more
plausible thing to be looking at. Worth a line in the docs.

Then, against their actual request — *every backend adjustable from bp.yaml* — an audit
found two things that were not:

- `roles/tidy.py` had `ROLE = "checker"` hardcoded, so the proof-reader could not be
  pointed at anything of its own. It is now `proofreader`, inheriting from `checker`, and
  it is the one role that is a small frequent call and therefore wants a cheap fast model.
- `PANEL = ("verifier_a", "verifier_b")` was a tuple in `roles/verify.py`, so no config
  could add a third reader or drop to one. Now `agents.panel`.

Plus `bp agents --fill`, which writes every unconfigured role into the file using the
value it already resolves to. Their file went from five roles to ten, comments intact,
every row now reading `from: bp.yaml`.

```
pytest -q       598 passed
```

**What surprised me.** Two things.

`agents.get("panel") or DEFAULT_PANEL` silently turns an explicitly empty panel into the
default, because `[]` is falsy — so `panel: []` would have looked like a working
configuration in which nothing could ever be verified. Presence and emptiness are
different questions.

And `--fill` had to write the *resolved* value, not the shipped default. Writing the
default would be a reconfiguration disguised as bookkeeping: the user runs a command
they think is cosmetic and their whole system moves to another provider. There is now a
test asserting backend, model and options are all unchanged across a fill.

### The example moves out of the root

The user asked where `nodes/` had come from, having not written it. Fair question, and
the honest answer is: I did, in an earlier session, as the L0 acceptance fixture — plus
four nodes the decomposer produced during the L1 and L2 acceptance runs. The commit
message at the time said why real-looking mathematics rather than filler, and that
reasoning still holds. What it did not do was say so anywhere a *reader* would see it.

So it is now `examples/gclm/` with a README that opens by saying it is a test fixture and
not verified mathematics, that about half of it was written by a language model asked to
write plausible mathematics and the other half by one asked to decompose it, and that two
of its diagnostics are deliberate and asserted by tests.

The repository root now has no `nodes/`, which means `find_project` refuses there — so
`bp ui` from the root does nothing, which is correct. Before this it opened the fixture as
though it were live work, and a fresh clone looked like it shipped somebody's
half-finished paper.

Guarded in `tests/test_packaging.py`: the root has no `nodes/`, discovery refuses there,
the example is a project, and its README contains the words that make its status
unmissable.

Also removed a tracked `build/` directory that `pip wheel` had left during the packaging
work and that I committed by accident.

```
pytest -q       598 passed
bp status       (from the root) error: no nodes/ directory — correct
bp check        (in examples/gclm) 2 deliberate errors
```

### Forty calls for an error message

The user verified their target at `--level deep` and got "budget exceeded (40 calls)".
They asked why one node was so expensive.

Because that node had 15 discharge obligations and 21 ledger claims, so `deep` needed
39 calls before confirmation, against a cap of 40. It could not have finished. Three
things made that worse than it had to be:

The cap was enforced per call and never compared against the worklist — even though
every worklist is computed by code from the files, so the number was free. Failing
closed was right (a truncated verification is not recorded) but happened at the last
possible moment. And `_check_records` saved its answer cache only on a clean exit, so
a cap firing mid-worklist threw away every answer already bought — meaning the retry
re-billed from zero and died in the same place. A worklist longer than the budget
could never be got past, however many times you paid for it.

Now: `verify.plan()` prices a node deterministically, and `verify` refuses **before
the first call** if the budget cannot finish, with the arithmetic and the remedies in
the message. `bp verify <node> --level deep --dry-run` prints the bill, and so does
the browser's Verify dialog, per level, before the button is live. The cache is banked
in a `finally`. And confirmation degrades rather than throwing — by the time it runs
the two whole-proof passes are already paid for, so the verification is recorded and
the objections nobody could re-read are marked `NOT CONFIRMED` in the node file and in
the document.

The caps are also renamed `*_per_run` (old spellings still accepted) because
"per_recompile" is what made 40 sound generous for one node, and the default rises to
80.

```
pytest                                             613 passed
bp verify thm.main --level deep --dry-run          3 calls; 21 of 21 claims cached
bp verify thm.main --level deep   (cap 2)          refused, 0 calls spent
```

The user's own re-run is now three calls rather than thirty-nine: the 21 claim answers
they had already paid for survived, because the jobs that completed had saved their
caches. That was luck — the cap fired between jobs. The `finally` makes it a guarantee.

### 1–10 children, and a second document

Two requests from the first real tuning session, one small and one not.

**The decomposer's bound was wrong at both ends.** 3–7 came from the brief. A node
whose whole content is a *reduction* — the theorem follows from one substantial lemma
plus a limiting argument — has one child, and the bound forced the model either to
invent two siblings it did not believe in or to return `already-atomic` for a node
that was nothing of the kind. Ten at the other end, because an argument with several
independent estimates is an ordinary shape. The validator now only excludes the two
degenerate answers, and the judgement moved into the prompt, which says what each end
of the range is *for* and what makes each end wrong.

**The clean document reads like a graph, because it is one.** The user's complaint was
precise: content runs off the page, the mathematics is arranged by following the DAG
with `(H1)`, `(H2)` above every statement, and references name nodes rather than
results. All three are true, and none is a bug — that is what a faithful rendering of a
dependency graph looks like. The tempting fix, making `render.py` cleverer, is the one
thing forbidden: its guarantee is that it holds no state and is regenerated from the
node files, and prose judgement cannot be regenerated.

So there is a second artifact and a seventh role. `bp paper` / **Paper…** asks a
`writer` to reorganise the same mathematics — hypothesis lists into sentences, routine
lemmas into the proofs that use them, sections by idea, results named — in two passes:
one call plans the sections, then one call writes each. `bp render` is untouched.

The interesting part was where to put the guarantee, since nothing can check that
prose is faithful. Answer: check that nothing *vanished*, and make the losses print.
The outline must place every active node (`PAP001`); each section must declare every
node it was given as stated — with a checkable `\label{paper:<id>}` — or merged, with
a note saying where it went (`PAP003`, `PAP004`); a `\ref` to a node that does not
exist is reported (`PAP005`); and a section whose call failed prints "This section was
not written" rather than being quietly omitted (`PAP006`). Then the assembled document
carries, from code and not from the agent, the target's status, every admitted node
with its reason, and an appendix mapping each node to its section, followed by every
departure and loss the writer itself declared. `--bare` drops that for a journal
submission.

Staleness rather than regeneration: the draft stores each node's statement *and* proof
hash, and `bp paper --status` leads with what has moved. Nothing rebuilds
automatically, and rendering, downloading and compiling a built draft make no model
call at all.

Two things went wrong on the way. `\noindent(((counts)))` in the new template expands
to `\noindentDevelopment status: …` — a fatal undefined control sequence that the line
above it escaped only because *its* variable happened to start with `\textit`. And the
first version of the paper template copied the fifty-line preamble, which would have
made the Preamble sheet describe a document the user was not compiling; it is now one
included file.

```
pytest                                             651 passed
bp paper --plan --root examples/gclm               10 nodes, 5 calls (unpriced)
bp paper --pdf   (scripted writer, 2 nodes)        wrote .bp/build/paper.pdf
bp paper --status   (after one edit)               written before 1 node(s) edited
```

### The edit nobody could act on

The user asked two things: what the claim ledger is, and what happens when they edit a
statement — *"should I redecompose it, hence I will lose all the current children?"*
They described the case that actually happens: a hypothesis tightened, most of the
children still right, small associated fixes needed.

Answering the second honestly meant admitting three gaps.

**The previous text was gone.** `_edit_section` recorded `chars_before` — a count. So
"nothing is destroyed" was true of nodes and false of the two fields the user writes,
and the most ordinary question after an edit had no answer anywhere.

**The decomposition check left no certificate.** A verification records
`verified_against`; a statement audit records `audited_against`; `bp check-decomp`
recorded nothing at all. So after editing a parent, *these children were approved
against different wording* was not something the system could say. It was the one
certificate missing, and this is exactly the case it was missing for.

**And the only tool was `bp redo`** — archive the subtree, decompose again, lose every
proof underneath. For "I tightened a hypothesis" that is the wrong instrument by an
order of magnitude.

All three are closed. `bp/history.py` snapshots superseded Statement and Proof text
under `.bp/history/`, and `bp revisions` lists, prints and diffs it.
`ops.record_decomposition_check` writes `checked_against` over the same set a
verification covers, with `DEC010`/`DEC011` reporting it and neither moving a status.
And `bp amend` / **Amend…** is one call that reads the parent as it now stands, the
children as they stand, and the diff of the edit, and returns `no-change`, `amend`
(keep/edit/drop per child, new children, a rewritten reduction, a complete `uses`
table) or `redecompose`.

The guarantee sits where it always does. Every existing child must come back with
exactly one verdict — silence is `AMD001` and a repair round — and the proposed
discharge table is assembled into a candidate graph and run through the *existing*
discharge check before anything is written. That last part is the whole mechanism
rather than a formality: what a parent's edit changes **is** what its children can be
given, so an inadequate amendment dies at `DIS011` for free, exactly as an inadequate
decomposition does.

Nothing is applied that was not ticked. The proposal goes to `.bp/amend/<node>.json`
with a per-item diff; applying takes the keys the user accepted. Partial acceptance is
honest rather than clever — rejecting a `drop` keeps the child and its existing `uses`
row so declining one item cannot manufacture a `DIS010` nobody caused, while keeping a
reduction that cites a lemma you unticked genuinely does dangle, and the sheet warns
before you apply as well as after.

Two things found by driving the browser rather than by the tests: the conflict warning
was originally appended below the notes, the diagnostics and the hint box — a warning
below the fold, in response to a click two screens up — and the proposal cards used
`.flag`, which is objection styling, so every proposed change looked like a problem.

```
pytest                                             703 passed
bp revisions t --show 2 --diff                     the two versions, coloured
bp amend t   (scripted, 2 children)                1 item, nothing written
bp amend t --apply                                 edited t.elb, subtree copied
bp check                                           DEC010 on t, as it should be
```

The claim-ledger half of the question needed no code: `bp/ledger.py` and
`roles/prompts/extract.md` were already the answer, and `GUIDE.md` §8a already
explained it. Worth noting anyway that the user's own project had a live `LED006` —
a claim resting on a computation with no named artifact — which is the check doing
precisely what it is for.
