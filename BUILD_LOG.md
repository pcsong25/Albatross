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
