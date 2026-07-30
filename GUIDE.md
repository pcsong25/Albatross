# GUIDE.md — using Albatross

For the mathematician using this on a real problem. `ARCHITECTURE.md` says how it
works inside; this says how to work with it.

---

## 1. What it is, and what it is not

Albatross holds the **bookkeeping** of a proof you are building: which lemmas
exist, which cite which, which are proved, which are believed, and — at any
moment — exactly what your theorem currently rests on. Agents propose
decompositions, argue with them, verify proofs, and write the easy ones. A
deterministic core keeps the accounting honest and renders the whole thing to
LaTeX.

**It does not know whether your mathematics is right.** Nothing in it does. What
it guarantees is narrower and more useful: that the *colours never lie about the
opinions underneath them*. If a node is green, then somebody — a human or a model
— claimed to have checked it, and everything beneath it is green too. If it is
blue-green, the certificate lists exactly what it rests on. You are still the
mathematician. This is the filing system, and the point of a good filing system
is that you can stop holding forty things in your head.

Read a green node as exactly this:

> **No agent found a problem in N enumerated checks at level L.**

Never as *proved*. Each node carries a record of what was actually checked — the
level, the counts, which model answered — and `bp show`, the browser and the
rendered document all print it, so you never have to guess how much scrutiny a
lemma received. A node verified at `quick` and one verified at `deep` are not
making the same claim. `ARCHITECTURE.md` §0 is the full account, in one page,
and it is worth reading once.

What *is* guaranteed absolutely is the accounting: the graph is acyclic, status
propagates correctly, a verification dies when anything it depended on moves, and
**every hypothesis and every load-bearing claim has a named source or there is a
hard error.** That last one is the check that earns its keep.

Two things it is deliberately not: it is not a theorem prover, and it is not a
document you edit. The LaTeX is regenerated from the graph every time, so it
cannot drift into a plausible fiction of your own proof.

---

## 2. Install

```bash
cd /path/to/Albatross
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q          # 266 passed
```

That gives you a `bp` command inside the virtualenv. Either use
`.venv/bin/bp`, or activate the environment (`source .venv/bin/activate`) and
just type `bp`. This guide writes `bp`.

Optional but recommended:

```bash
bp ui --vendor --no-open    # download Cytoscape and KaTeX so the UI works offline
```

You also need at least one model backend. `bp agents` tells you what will run
here — see §9.

---

## 3. Five minutes: your first project

```bash
bp init ~/proj-riemann --id rh.main
cd ~/proj-riemann
```

That makes `nodes/`, writes `nodes/rh.main.md` as your target theorem, and copies
a `bp.yaml`. Now write the theorem. Either open `nodes/rh.main.md` in your editor
and replace the `## Statement` section, or do it in the browser:

```bash
bp ui
```

which opens `http://127.0.0.1:8000/`. Click the node, click **edit** under
Statement, type LaTeX, Save.

Then **fill in the hypotheses** in the frontmatter (or leave them until you first
cite this node from somewhere). They matter: a node's `hypotheses` list is what
its *parents* have to discharge, and it is the single highest-value thing the
system checks.

```yaml
hypotheses:
  - {id: H1, tex: "s \\in \\mathbb{C}, \\ \\Re s > 1"}
  - {id: H2, tex: "\\zeta(s) \\ne 0"}
```

Note `tex` is a **math-mode fragment** — `s > 3/2`, not `$s > 3/2$`. The renderer
wraps it.

Now press **Expand**.

---

## 4. The one idea to hold on to

There are two status fields and they are not the same thing.

**`local_status` is an opinion about one node.** Somebody looked at *this* node's
proof and formed a view. It is authored — by you, or by the verifier.

| value | means |
|---|---|
| `unverified` | nobody has checked this proof. The default. |
| `verified` | somebody checked it and believes it, **given its children** |
| `flagged` | a verifier raised an objection that stands |
| `admitted` | believed but not argued. Deliberate, visible debt. |
| `assumption` | taken as given for this project, by choice, not omission |

**`global_status` is a derivation over the whole graph.** Given every opinion
beneath it, what does this node actually rest on? You never write it; a
deterministic sweep computes it after every change.

| value | colour | means |
|---|---|---|
| `proved` | green | rests on nothing outstanding |
| `proved_modulo` | blue-green | true relative to the items in `support` |
| `open` | grey | no proof written |
| `blocked:unverified` | amber | a proof exists, nobody checked it |
| `blocked:stale` | amber, dashed | verified once, but a statement moved since |
| `blocked:objection` | red border | a verifier's objection stands |
| `blocked:children` | amber | the reduction is verified, the lemmas beneath are not |

When you cannot see why something is the colour it is, press **Why?** — or run
`bp why <node>`. No model is involved in that answer, so it is always correct.
It is the feature that makes the colours worth trusting.

---

## 5. The daily loop

Most sessions look like this.

**1. Open the frontier.** The **Frontier** button lists nodes where work is
*possible now* — unfinished, with everything beneath them finished. A theorem
blocked by three unproved lemmas is not a place to work; its lemmas are. It is
ranked shallow-first, then by how many nodes each one gates.

**2. Pick one and expand it.** **Expand** first asks *is this worth decomposing
at all?* If the decomposer judges the node a single step, or an argument it could
just write out, it says so and stops — nothing is written, the assessment becomes
a note, and you are offered **Write the proof** or **Decompose anyway**. A lemma
that is one integration by parts should be proved, not split into three
sub-lemmas and a reduction.

When it does decompose, it produces one level: 3–7 children,
each a section or a major lemma. The hint box is prefilled with the node's
`strategy` — use it. Naming the shape of the argument you have in mind ("bootstrap
on the $L^\infty$ norm"; "case split on whether $a < 1/2$") is ten seconds of
typing and removes the largest single source of bad decompositions.

Expect it to take minutes. The interface stays live; the action bar says which
agent is working.

**3. Read what came back.** The result panel lists the children and — importantly
— the decomposer's own reservations. Then press **Check decomposition**. That
runs two independent questions:

- assuming every child is true, does the reduction establish the parent?
- is any child a restatement of the parent, or as hard as the parent?

Read the located problems. In our own test run this caught a decomposition whose
two children *contradicted each other* — one child's conclusion was the negation
of the other's — which no structural check can see.

**4. Accept, or Redo.** If the decomposition is wrong, press **Redo**. It copies
the current subtree to `attempts/<node>-<n>/` before archiving anything, and
sends the previous attempt's problems to the decomposer as negative context. Give
it a different hint. A redo that does not know why the last one was rejected
tends to produce the same thing again.

**5. Attack the cheap leaves first.** For each `routine` or `standard` leaf,
press **Generate proof**. This is not about saving yourself typing — it is a
*falsification test on the strategy*. If a bookkeeping lemma your decomposition
requires turns out to be false, or to need a hypothesis nobody has, you want to
find that out now for the price of a few cheap calls rather than after three
weeks in the hard branch. A prover that declines, with a reason, is the most
valuable output it produces.

**6. Extract the claims.** **Extract claims** lists every load-bearing claim the
proof makes with the source your prose offers, and `LED001` fires on every one it
has no source for. This is the same device as the discharge table, pointed at what
the proof asserts on its own account — see §8a. It is one cheap call and it is
where premise smuggling shows up.

**7. Verify.** **Verify** asks you for a level first, because the level is part of
what the verdict *means*:

- `quick` — the deterministic checks and the whole proof read by two models from
  different families. Fast; use it while you are still moving.
- `standard` — adds claim extraction, the ledger audit, and every discharge
  obligation asked one at a time. This is the routine setting.
- `deep` — adds a check on every sourced claim and a statement audit. Roughly
  fifteen calls on a ten-claim proof. Run it before you trust a subtree.

Whatever the level, every objection then goes through a confirmation pass that
drops the ones which dissolve in context. Withdrawn objections become notes rather
than vanishing, so you can see what was considered.

The node then shows a **verification record**: the level, how many questions there
were, how many were answered, how many came from cache, and which model answered
each job. Read it. It is the difference between "green" and "green, and here is
what that cost you".

**8. Recompile periodically.** **Recompile** re-verifies everything stale or
unverified, at a level you pick. It prices each level before you commit and will
not spend without confirmation. Unchanged questions come from cache, so a
recompile after a small edit is much cheaper than the first one.

**9. Read the document.** **Render LaTeX** gives you the source, a `.tex`
download, and a compiled PDF. Unproved nodes carry a visible marker; admitted
ones are boxed and labelled as assumptions; the support certificate is at the
top. Each checked node also carries one line saying what was verified and at what
level, so reading the document tells you how much scrutiny each lemma got.
`--audit` adds the discharge tables and the ledger. `--clean` strips all of it —
that version is the paper.

---

## 5a. Watching a run, and telling slow from stuck

Role calls take minutes. `max` effort through the Codex CLI runs a decomposition
in roughly 3–10 minutes on a typical statement; a recompile makes twenty or more
calls. Nothing is wrong until it is much longer than that.

**In the browser**, the action bar shows `● Decomposing thm.main — decomposer
(gpt-5.6-sol) — call 3`. The call counter is the signal: if it advances, work is
happening; if it sits at 1 for half an hour, the model is thinking hard, not
looping.

**From a second terminal**, while it runs:

```bash
pgrep -af "codex exec"                       # is the subprocess alive?  ← trust this one
curl -s localhost:8000/api/jobs | python3 -m json.tool
tail -f ~/my-theorem/.bp/events.jsonl        # writes as they land
ls -l ~/my-theorem/.bp/agent/                # calls that have RETURNED
```

Two things that look like symptoms and are not:

- **`.bp/agent/` is empty during a long call.** A call is logged only *after* it
  returns. An empty log during a run is expected.
- **Nothing in `nodes/` yet.** A decomposition is checked in memory and written
  only when it passes, so the graph does not change until the call is done.

And one that *is*: **restarting `bp ui` kills the run.** Job state lives in the
server's memory and the model subprocess is its child, so a restart loses both.
The graph is safe — results are written as they land — but an in-flight call is
gone and `bp calls` will show nothing for it. Durable job state is on the list in
`UPGRADE.md`.

If you want a run you can watch die, use the CLI instead: `bp expand <node>`
blocks in your terminal and prints what happened.

---

## 6. The detail panel, button by button

| Button | What it does | When |
|---|---|---|
| **Expand** | Decompose one level. Hint box prefilled with `strategy`. | A node with no children that you cannot prove directly |
| **Redo** | Archive the subtree to `attempts/`, decompose again with the last attempt's problems as context | The decomposition was wrong |
| **Generate proof** | Prover role. Writes into the Proof section; **never** sets a status | `routine` and `standard` leaves |
| **Verify** | Obligations, then the panel, then confirmation. Sets `verified` or `flagged` | Any node with a proof |
| **Check decomposition** | The two checker calls | Any node with children |
| **edit** (Statement) | LaTeX textarea. On save, the LaTeX is proof-read and any correction shown beside your original; then it **warns which verifications it invalidates before committing** | |
| **edit** (Proof) | LaTeX textarea. Editing a proof stales nothing | |
| **edit** (Discharges) | One input per hypothesis of each cited lemma | After adding a child by hand |
| **Add child** | A lemma you state yourself, attached here | You know the lemma you want |
| **Add note** | Free prose. Fed to agents as context on every later attempt | Dead ends, hints, "the $a \to 1/2$ limit is where this gets tight" |
| **Mark admitted** | Believed, not argued. Reason required | You want to move on and carry the debt visibly |
| **Mark assumption** | Taken as given for this project. Reason required | A standing hypothesis of the whole project |
| **Relabel** | Change the difficulty label | The prover declined a "routine" lemma |
| **Archive** | Leaves the active graph. **Never deletes** | A branch you have abandoned |
| **Why?** | The status chain in plain English. No model involved | Whenever a colour surprises you |

The chevron on a node in the graph (`▾`/`▸`, at its left edge) folds the subtree
**in the view only** — nothing is written and the fold is gone on reload.

---

## 6a. Your own LaTeX

**Standard LaTeX works.** `$…$`, `$$…$$`, `\[…\]`, `\(…\)`, and bare display
environments — `align`, `equation`, `gather`, `multline`, `alignat`, `flalign`,
starred or not — all typeset in the browser. The rendered document loads
`amsmath`, `amssymb`, `amsthm`, `mathtools` and `mathrsfs` always, and `bbm`,
`enumitem` and `float` when your TeX installation has them.

**Your macros go in `preamble.tex`**, at the project root — the **Preamble**
button in the action bar edits it, or `bp preamble --from myfile.tex`. It is
used in three places, which is the point:

- injected verbatim into the rendered document;
- shown to **every agent** as context, so a statement written in your notation is
  read correctly rather than guessed at;
- parsed by the browser into KaTeX macros, so it typesets on screen.

`\newcommand`, `\renewcommand`, `\providecommand`, `\DeclareMathOperator`
(with or without `*`) and `\def` are all understood, including arguments:

```latex
\newcommand{\RR}{\mathbb{R}}
\newcommand{\ip}[2]{\langle #1, #2 \rangle}
\DeclareMathOperator{\supp}{supp}
```

One limitation: KaTeX has no equivalent of an optional-argument default, so
`\newcommand{\f}[2][x]{…}` loses the default. Everything else carries over.

**Saving a statement or proof runs a proof-reader first.** It may fix syntax — an
unbalanced brace, `\end{aligned}` closing a `\begin{align}`, an obsolete `\bf`
— and it is forbidden from touching the mathematics. You see the rewrite beside
your original with a one-line reason for each change, and nothing is saved until
you pick one. If it ever changes a symbol, an index or the direction of an
inequality, that is a bug: tell me.

If the proof-reader cannot run, the save goes through as you typed it. It never
blocks you.

---

## 7. Node files

One markdown file per node under `nodes/`. They are meant to be hand-edited; the
writer preserves your comments, key order and quote style.

```markdown
---
id: gclm.energy-lower-bound
role: proposition            # lemma | proposition | theorem | definition | assumption
target: false                # true on exactly one node: the theorem you are proving
children: [gclm.elb-a, gclm.elb-b]
strategy: bootstrap on the sign of the gradient at the origin
difficulty: hard             # routine | standard | hard | unknown
lifecycle: active            # active | archived
local_status: verified
status_reason: null          # required when admitted or an assumption
flags: []                    # objection records, written by the verifier

hypotheses:                  # what a PARENT must discharge to cite this node
  - {id: H1, tex: "0 < a < 1/2"}
  - {id: H2, tex: "\\omega_0 \\text{ is odd and } \\omega_0'(0) < 0"}

uses:                        # for each child, where each of ITS hypotheses comes from
  gclm.elb-a:
    applied_to: "\\omega(t,\\cdot)"
    discharges:
      H1: "hypothesis:H2"
  gclm.elb-b:
    applied_to: "\\omega(t,\\cdot)"
    discharges:
      H1: "hypothesis:H1"
      H2: "child:gclm.elb-a"
      H3: "ADMITTED: the a priori $L^\\infty$ bound is not established here"

# --- computed fields: written by `bp sweep`. Never edit them. ---
global_status: proved_modulo
support: [gclm.energy-lower-bound]
blocked_by: []
statement_hash: '5a07832c405d'
verified_against: {self: '5a07832c405d', gclm.elb-a: '27260e7d162d'}

# The claim ledger (§8a). Written by `bp extract`; never by hand.
claims:
  - id: c1
    text: "\\partial_x\\omega(t,0) < 0 \\text{ on } [0,T_{\\max})"
    source: {kind: child, ref: gclm.elb-a}
claims_of: '9f31c0aa72be'    # the proof this ledger describes

# What was actually checked. `local_status` is DERIVED from this, not written.
verification:
  checked_at: '2026-08-03T14:22:00+00:00'
  level: standard
  deterministic: {integrity: pass, children_used: pass, discharge: pass, ledger: pass}
  ledger: {claims: 1, unsourced: 0, checked: 0, flagged: 0, cached: 0}
  obligations: {total: 5, verified: 5, flagged: 0, cached: 3}
  whole_proof: {verifier_a: no_objection, verifier_b: no_objection}
  statement_audit: not_run
  models: {extractor: haiku-4.5, obligation: sonnet-5, verifier_a: opus-5}
stale: false
---

## Statement

Let $0 < a < 1/2$ …

## Proof

By `gclm.elb-a` the sign of the gradient is preserved …

## Notes

Free prose. Strategy hints, dead ends, references. Fed to agents as context.
```

Things worth knowing:

- **Edges come from `children` only.** There is no `parent` field, because a
  lemma may be cited by several parents and a stored parent would go
  inconsistent. Parents are computed.
- **Cite children by writing the id in the proof prose**, in backticks by
  convention. That is how the children-used check works, and the renderer turns
  it into a cross-reference.
- **Hash values must be quoted.** `896e63762324` is a valid YAML float. The
  system always writes them quoted and refuses to load one that came back as a
  number. Timestamps too: `2026-08-03T14:22:00+00:00` unquoted comes back as a
  date object and the file will not load.
- **`local_status` is the one status you may set by hand**, and only two ways:
  `bp admit` and `bp assume`, each of which requires a reason. Otherwise it is
  derived from `verification`, and a role that tried to write it directly would be
  refused. `global_status` is never yours to write.
- **`claims` and `verification` are computed too.** `bp extract` writes the first,
  `bp verify` the second. Editing them by hand is refused, because a ledger you
  could edit would let the thing making a claim decide the claim is sourced.
- If you hand-edit, run `bp sweep` afterwards (or just open the UI, which shows
  current values; `bp check` reports `SYS001` when the file is out of date).

---

## 8. The discharge table — get this one right

This is the mechanism that makes the whole thing worth using, so it deserves a
section.

When a proof cites a lemma, that lemma has hypotheses, and they have to hold
where it is invoked. The `uses` table records, for each hypothesis of each cited
child, **where it comes from**:

| Source | Means |
|---|---|
| `hypothesis:H2` | a hypothesis of *this* node, by id |
| `child:some.id` | the conclusion of another lemma this node also cites |
| `proof:<free text>` | established inline, in this node's prose |
| `literature:<reference>` | taken from the literature — name it |
| `ADMITTED: <reason>` | not available, and you are proceeding anyway |

Fill it in honestly. If a hypothesis has no source, write
`ADMITTED: <why it is missing>` rather than leaving it out. An omitted entry is a
hidden gap; an `ADMITTED` entry is debt you can see, and it propagates: the node
enters its own support set and appears in the theorem's certificate.

**What the check does and does not do.** It verifies that a source is *named*.
It does **not** verify that the named source entails the hypothesis. You can
write `H2: "hypothesis:H1"` when `H1` does not in fact give `H2`, and the check
will pass. So it catches **omission**, not **misattribution** — and omission is
the common failure and the invisible one. Misattribution goes to the verifier as
a narrow, explicit, one-at-a-time question (`bp obligations` shows you the list).

**If you believe the check is stronger than it is, you will over-trust green
nodes.** That is the single most important sentence in this guide.

---

## 8a. The claim ledger — the same idea, for what the proof asserts itself

The discharge table covers the hypotheses of the lemmas you *cite*. It says
nothing about what a proof claims on its own account. This:

> By standard elliptic regularity, $\omega \in C^1$, hence…

is a load-bearing claim with no child, no hypothesis, and no entry anywhere. At
research level that is the most common way a gap hides, and it hides *well*,
because the sentence reads like an argument.

`bp extract <node>` — the *Extract claims* button — reads the proof with a cheap
model and lists every load-bearing claim with the source your prose offers:

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
    source: {kind: none, ref: ""}       # <- LED001 fires on this one
```

That last entry is the point. `kind: none` is the **correct** answer for a claim
your prose simply asserts, and `LED001` turns every one of them into a hard error
you will see in `bp check`. The extractor is told at length that inventing a
plausible source is the one thing it must never do, because that converts a visible
gap into an invisible one.

Do not hand-edit `claims`. It is computed: it is regenerated when the proof text
changes, and `LED100` tells you when it has gone out of date. `bp verify` at
`standard` or above re-extracts for you.

**What the audit does and does not do.** Same shape as §8. It guarantees every
claim *in the ledger* has a named source. It does not guarantee the ledger is
**complete** — a claim the extractor did not notice is invisible to `LED001`. If
the whole-proof pass ever objects to a step that is not in the ledger, that is
the one gap this design is least protected against; say so in your friction log.

Whether each named source actually *gives* its claim is a separate question, asked
one claim at a time at `bp verify --level deep`.

---

## 8b. Auditing a statement

`bp audit <node>` — the *Audit statement* button — asks four fixed questions about
a statement, with no proof in view:

1. Is every symbol bound, and is the conclusion unambiguous?
2. Can you write down one concrete instance satisfying **every** hypothesis? (If
   not, the statement may be vacuous — true, and proving nothing.)
3. Are the quantifiers in the order you meant?
4. Does any constant depend, directly or transitively, on something the statement
   treats it as uniform in?

Question 4 is the reason to run it. That is the classic bootstrap error, and it
invalidates a whole argument rather than one step of it.

**Its answers are prompts for your attention, not checks.** They become a note on
the node and one line on the verification record; nothing blocks on them. This role
is standing in for two deterministic checks that are not built yet, and it is
weaker than both: it finds a circular constant by *reading*, so it finds some, and
its "a witness exists" is an assertion rather than a witness. A clean audit is
mildly reassuring and nothing more.

---

## 9. Models, and what it costs

`bp.yaml` says which model plays which role. The system never names a model in
its code, only a role, so changing one is a one-line edit.

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

**The tiering is deliberate and it is where the bill is decided.** `extractor` is
doing translation, so it goes on the cheapest thing you have. `obligation` answers
the narrow one-question-at-a-time checks — both hypothesis discharges and ledger
claims — and at `--level deep` it is most of the calls, so a mid model there is the
single biggest lever on cost. The four that need a whole argument in view
(`verifier_a`, `verifier_b`, `confirmer`, `auditor`) want the strongest model you
have; do not economise on `confirmer` in particular, because without confirmation
the objection list is mostly pedantry and you will stop reading it.

Backends:

| backend | what | credential | reports cost |
|---|---|---|---|
| `claude_api` | metered Anthropic API | `ANTHROPIC_API_KEY`, or `ant auth login` | yes |
| `openai_api` | metered OpenAI API | `OPENAI_API_KEY` | yes |
| `claude_cli` | `claude -p` | a Claude subscription | **no** |
| `codex_cli` | `codex exec` | a Codex subscription | **no** |

`bp agents` prints the table and says which can actually run here.

**Put the two verifiers on different families.** That is the entire reason there
are two of them; two models from the same lab miss the same things, and the
second one costs the same either way.

**Two caps, and which one bites.** The dollar cap only constrains calls whose
price is known. A subscription CLI reports no price at all, so with CLI backends
the **call cap** is the only thing limiting a run. Keep it set.

**API is much faster than a subscription CLI** — seconds against minutes on a
decomposition prompt. If you have a key, use it for the decomposer at least.

**`--level` is the cost control, not the budget cap.** A budget cap stops a run;
a level decides how much the run costs in the first place.

| `--level` | Runs | Use for |
|---|---|---|
| `quick` | the deterministic checks and the whole-proof pass | while you are iterating |
| `standard` (default) | + claim extraction, the ledger audit, every hypothesis discharge | routine work |
| `deep` | + a check on every sourced claim, + the statement audit | before you trust a subtree, or write it up |

A ten-claim proof is roughly fifteen calls at `deep`, so a thirty-node graph is
several hundred. Always look at `bp recompile --dry-run --level deep` before
running it; it prints the nodes, the jobs per node, the call count and a cost.

Two things make repeated runs cheap. **Nothing is re-billed**: every question
carries a content hash and an unchanged question is answered from cache, so editing
one paragraph does not re-verify the rest of a proof. And **the order is by value**
— the path to your target first, then the frontier — so a run you stop early has
bought the useful half.

`--batch N` puts N narrow checks in one call. It defaults to 1 and should stay
there unless cost is genuinely hurting: a model asked ten questions at once answers
each less carefully, and that is the reliability the whole design is built to buy.

**Every call is logged** to `.bp/agent/`. `bp calls` summarises it;
`bp calls --show <hash>` prints one in full — the exact prompt and the exact
reply. Any command with `--replay` resolves from that log instead of the network,
which makes re-runs free and lets you work offline.

---

## 10. Every command

Deterministic — no key, no network, no configuration:

| Command | |
|---|---|
| `bp init <dir> --id <node-id>` | start a project |
| `bp new <id> [--parent P] [--statement ...]` | create a node by hand |
| `bp status` | one line per node |
| `bp show <id>` | everything about one node |
| `bp graph` | the DAG as a tree |
| `bp frontier` | what to work on next |
| `bp why [id]` | the status chain, in English |
| `bp check [--format json]` | every check. Exit 1 on error |
| `bp obligations [id] [--kind discharge\|claim\|all]` | the worklists as JSON: one record per discharge, one per sourced claim |
| `bp render [--clean] [--audit] [-o F]` | the LaTeX document |
| `bp events` / `bp jobs` / `bp calls` | history |
| `bp sweep` | re-derive and persist the computed fields |
| `bp admit <id> -r "…"` / `bp assume <id> -r "…"` | with a required reason |
| `bp note <id> "…"` / `bp relabel <id> <difficulty>` / `bp archive <id>` | |

Agents — these call models and cost time or money:

| Command | |
|---|---|
| `bp agents` | which model plays which role, and whether it can run |
| `bp expand <id> [--hint "…"]` | decompose one level |
| `bp redo <id> [--hint "…"]` | archive the subtree and decompose again |
| `bp check-decomp <id>` | the two checker calls |
| `bp extract <id>` | build the claim ledger, then audit it |
| `bp verify <id> [--level L] [--batch N] [--no-record]` | the three jobs the level calls for, then confirmation |
| `bp audit <id>` | the four statement questions. Never changes a status |
| `bp prove <id> [--force]` | write a proof for an easy leaf |
| `bp recompile [--level L] [--dry-run] [--budget N] [--batch N]` | verify everything stale or unverified |
| `bp resume [job_id]` | continue an interrupted recompile |
| `bp ui [--port N] [--vendor] [--replay]` | the web interface |

Every command takes `--root <dir>` to point at a project other than the working
directory (or set `$BP_ROOT`). The **agent** commands and `bp ui` additionally
take `--replay`, which resolves calls from the log instead of the network — free,
offline, and reproducible. The deterministic commands never touch the network, so
they have no such flag.

---

## 11. What the system does not check

Be clear-eyed about the gaps. Each is a known deferral with a row in
`UPGRADE.md`.

- **Misattributed discharges** — see §8. The verifier is asked; the check is not.
- **Whether the claim ledger is complete** — see §8a. Every claim *in* it is
  sourced or errors; a claim the extractor never listed is invisible. This is the
  gap the design is least protected against, and the tell is a whole-proof
  objection about a step that is not in the ledger.
- **Constant circularity and uniformity.** If $\varepsilon_0$ depends on
  something that depends on $\varepsilon_0$, nothing *checks* it. `bp audit`
  question 4 now asks, which means the error is no longer completely invisible —
  but it is found by reading, so it is found sometimes. A real scope check walks a
  declared table and is complete; it is still the next check worth adding.
- **Vacuous hypotheses.** A lemma whose hypotheses cannot all hold looks fine —
  it *is* fine, vacuously — and the theorem below rests on nothing. `bp audit`
  question 2 asks for a witness, but an asserted witness is not a checked one.
- **Wrong constants and sign errors** in explicit inequalities. There is no
  numeric sweep.
- **Cosmetic edits invalidate verification.** There is no LaTeX normalisation, so
  renaming $\varepsilon$ to $\delta$ moves the hash and makes things stale.
  Annoying, but it errs in the safe direction.
- **Two `bp` processes at once are unguarded.** Running the UI and a CLI command
  simultaneously can have one overwrite the other's obligation cache. Within one
  process everything is ordered. Use one at a time.

---

## 12. Recipes

**"I hand-edited a file and the statuses look wrong."** `bp sweep`. `bp check`
reports `SYS001` when a file's computed fields are out of date.

**"An expand produced errors."** That is the discharge check working. `bp check`
names the hypothesis with no source. Fix it in the **Discharges** editor, or
press **Redo** with a hint saying what was wrong.

**"The prover says a routine lemma is not routine."** Believe it. That is usually
a fact about your *decomposition* — a missing hypothesis, or a step that needs an
idea. `bp relabel <id> hard`, and read what it said in the node's Notes.

**"Verification says flagged and I disagree."** Read the objection: it quotes the
sentence it applies to. If it is wrong, edit the proof to close the gap it
thinks it sees, and verify again. Confirmation already dropped the objections
that dissolved in context, so what remains has survived a second look.

**"Expand has disappeared from a node."** Expand only offers itself on a node
with *no* children — the decomposer proposes a whole level at once, so it has
nothing sensible to do alongside children you added yourself. Once a node has
any child you get **Redo** instead, which archives what is there (to
`attempts/`) and decomposes afresh. If you want to keep your hand-written lemma
*and* have the agent propose the rest, add the rest by hand for now; expanding a
partially-decomposed node is a known gap with a row in `UPGRADE.md`.

**"I want to try a different decomposition without losing this one."** `bp redo`
copies the subtree to `attempts/<node>-<n>/` first. Nothing is destroyed. (Two
*live* competing decompositions are not supported yet — that is a row in
`UPGRADE.md`.)

**"A run stopped partway."** `bp resume`. Completed nodes are not re-queried, and
the obligation cache means even a re-entered node mostly hits cache.

**"How much have I spent?"** `bp agents` shows the call count; `bp calls` breaks
it down by role and model. With subscription backends there is no dollar figure
to show, which the interface says rather than printing a reassuring `$0.00`.

**"Start again from scratch."** Every node file is just a file. Delete `nodes/`
and `bp init` again; or archive branches, which keeps them.

---

## 13. What to send back

`LIGHT.md` says L3 is driven by your friction log, not planned in advance. So use
it on something real and write down:

- every point where you had to drop out of the browser to a terminal or an editor
- every time a colour surprised you, and whether `Why?` explained it
- decompositions that were bad, with the hint you gave — prompt wording is where
  most of the quality lives and it is meant to be edited (`bp/roles/prompts/*.md`)
- anything that felt slow, and whether it was the model or the interface
- checks that fired when they should not have, and gaps you wish had been caught

That list is the L3 plan.
