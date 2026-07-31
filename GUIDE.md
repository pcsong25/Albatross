# GUIDE.md — using Albatross

For the mathematician using this on a real problem. This is the manual.

- **[UI.md](UI.md)** — the interface reference: every button, label, colour, status
  and diagnostic code. Reach for it when you want to know what something *is*.
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — how it works inside. Its §0 is what the
  system guarantees and what it does not, and it is worth reading once before you
  trust anything here.
- **[README.md](README.md)** — the short version, for someone deciding whether to
  try it.

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
git clone <repo> albatross && cd albatross
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q          # no network, no key needed
```

`bp` is then on the venv's path. Activate the venv, or use `.venv/bin/bp`.

**LaTeX.** Optional, but without it you get the `.tex` source and no PDF. A
*minimal* install is not enough for real documents — BasicTeX and
`texlive-latex-base` both lack `enumitem` and much else, and that is a hard failure
rather than a degradation:

| Platform | Enough | Comfortable |
|---|---|---|
| macOS | BasicTeX + `sudo tlmgr install enumitem cleveref` | MacTeX |
| Debian/Ubuntu | `texlive-latex-recommended` | `texlive-latex-extra texlive-science` |

Albatross names the missing package and the command that installs it whenever one
is missing, so you can also just start and fix it when it complains. §6a has the
detail.

**Models.** Nothing needs a key until you use an agent command; the whole
deterministic core runs offline. Then:

```bash
export ANTHROPIC_API_KEY=...   # or OPENAI_API_KEY, or a Claude/Codex CLI login
bp agents                      # who plays what, and what can actually run here
```

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

When it does decompose, it produces one level: between one and ten children,
usually three to seven, each a section or a major lemma. One child is what you get
when the node's whole content is a reduction to a single lemma; ten when the
argument really has that many independent estimates in it. The hint box is prefilled with the node's
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

**4a. If you edit the statement afterwards, Amend rather than Redo.** Tightening a
hypothesis on a node that already has children does not oblige you to start over —
see §8c. **Redo** is for when the *strategy* was wrong.

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
`--audit` adds the discharge tables and the ledger. `--clean` strips all of it.

**10. When you want something readable, build the paper.** `--clean` removes the
apparatus but not the shape: it is still one numbered node after another in
dependency order, with `(H1)`, `(H2)` above each statement and every reference an
identifier. **Paper…** (or `bp paper`) is the other document — see §9c. It is
optional, you build it when you ask for it, and it never replaces the one above.

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

*Every control in the interface, exhaustively, is in [UI.md](UI.md). This is the
short tour.*

| Button | What it does | When |
|---|---|---|
| **Expand** | Decompose one level. Hint box prefilled with `strategy`. | A node with no children that you cannot prove directly |
| **Amend…** | One call: what minimally has to change now the parent has been edited. Proposes; you accept per item (§8c) | You edited a statement that already has children |
| **Redo** | Archive the subtree to `attempts/`, decompose again with the last attempt's problems as context | The *strategy* was wrong |
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
| **Amend…** | One call: what minimally has to change now the parent has been edited. Proposes; you accept per item | After editing a statement that already has children (§8c) |
| **Why?** | The status chain in plain English. No model involved | Whenever a colour surprises you |

Two buttons in the top bar produce documents: **Render LaTeX** (exact, generated from
your files every time) and **Paper…** (readable, agent-written, built on request —
§9c).

The chevron on a node in the graph (`▾`/`▸`, at its left edge) folds the subtree
**in the view only** — nothing is written and the fold is gone on reload.

---

## 6a. LaTeX: your macros, your packages, and what breaks

This is the chapter to read before you paste in your paper's preamble.

### Your macros go in `preamble.tex`

At the project root. The **Preamble** button edits it, or `bp preamble --from
myfile.tex`. It is used in **three** places, which is the whole point:

- injected verbatim into the rendered document;
- shown to **every agent** as context, so a statement in your notation is read
  rather than guessed at — a model shown `\ip{u}{v} \in \Hs` and no definitions
  will invent a meaning and answer confidently about it;
- parsed by the browser into KaTeX macros, so it typesets on screen.

`\newcommand`, `\renewcommand`, `\providecommand`, `\DeclareMathOperator` (with or
without `*`) and `\def` are all understood, including arguments:

```latex
\newcommand{\RR}{\mathbb{R}}
\newcommand{\ip}[2]{\langle #1, #2 \rangle}
\DeclareMathOperator{\supp}{supp}
```

**Your preamble wins.** It is injected *before* the renderer's own options and
theorem environments, so if you define `lemma` your own way, or load `hyperref`
with `hidelinks`, or set your own `geometry` margins, yours is what the document
uses. (This was not always true, and a pasted-in preamble used to fail on the
first try with "Command \lemma already defined".)

**See exactly what the renderer adds.** The **Preamble** sheet lists it under *What
the renderer adds* — every package with its options, which ones are loaded only if
your TeX has them, the five theorem environments with their printed names, and the
macros it defines — plus the whole generated preamble in full, so nothing is hidden.
`bp preamble --defaults` prints the same thing.

It is read from the template rather than written down, so it cannot go out of date.
Use it to see what you are overriding: you cannot avoid a collision you cannot see.

Currently that is `amsmath`, `amssymb`, `amsthm`, `mathtools`, `mathrsfs`, `fontenc`,
`geometry`, `xcolor` and `hyperref` always, plus `bbm`, `enumitem` and `float` when
installed. Loading any of them again yourself is harmless — and your options win.
**Do not redefine `\bpmark`, `\bphyp`, `\bpaudit` or `\bpboxreg`**: those draw the
status apparatus.

### Missing packages, which is the commonest first failure

Your `\usepackage{enumitem}` is **not** guarded. If the package is not installed
the document does not compile at all, with

```
! LaTeX Error: File `enumitem.sty' not found.
```

A minimal TeX install — BasicTeX, `texlive-latex-base` — is missing a lot:
`enumitem`, `cleveref`, `mdframed`, `tikz`, `braket`, and more. Two ways out:

```bash
sudo tlmgr install enumitem cleveref        # macOS / TeX Live
sudo apt install texlive-latex-extra        # Debian / Ubuntu
```

or, if you would rather not install anything, guard it and accept worse
typesetting:

```latex
\IfFileExists{enumitem.sty}{\usepackage{enumitem}}{}
```

**Open PDF names the package and the command.** You do not have to read a log. The
same diagnosis is on the terminal from `bp render --pdf`, which is the better place
to debug from.

### Cross-references between nodes

**They work.** Every node is rendered into one document and `pdflatex` runs twice,
so a `\label` written in one node resolves from another and the numbers are the
document's own:

```latex
% in the parent's statement
\begin{equation}\label{eq:riccati}
  z'(t) \ \ge \ \kappa\, z(t)^2
\end{equation}

% in another node
By \eqref{eq:riccati} the growth is superlinear.
```

What Albatross adds is that the two ways a reference goes **silently** wrong are
hard errors instead of LaTeX warnings nobody reads:

| Code | | |
|---|---|---|
| `XRF001` | **error** | A reference to a label nothing defines. LaTeX only warns and prints `??` in the PDF. This is what catches an agent writing `Section \ref{sec-space}` for a section that does not exist. |
| `XRF002` | **error** | The same label defined in two nodes. LaTeX lets one win *silently*, so a reference can resolve to the wrong equation with nothing said. |
| `XRF003` | warn | A reference to a node not in scope — see below. |
| `XRF004` | warn | A reference into another node's **proof**. A proof is private: what a citer may rely on is a statement, and the verifier is only ever handed statements. Rewriting that proof silently breaks this reference. |
| `XRF005` | warn | A label nothing references. Usually a leftover, sometimes a reference you meant to write. |

`bp labels` lists every label, everything that references it, and everything
referenced that does not exist.

**Labels are global to the whole document.** Two nodes that both write
`\label{eq:main}` collide, so prefix them: `\label{gclm.blowup:main}`.

**In the browser** you see the resolved number as a clickable chip — click it to
jump to the node that defines it — because KaTeX cannot do `\ref` at all. The
number comes from LaTeX's own `.aux`, so **build the PDF once** and the numbers
appear; before that, and whenever a node file is newer than the last build, you see
the label name instead. Showing a number that might be one build out of date would
be worse than showing none.

### Can a child reference its parent's equation?

Yes — **to name something, never to use as a fact.** That distinction is the whole
rule, and it is not stylistic:

> The parent's proof cites the child. If the child then takes a *fact* from the
> parent's statement, each rests on the other and **neither is established** — and
> nothing in the graph will show it, because every step looks locally fine.

**Referring is fine.** "the solution $\omega$ of that equation", "with $\kappa$ as in
\eqref{eq:kappa}", "compare \eqref{eq:main}". You are saying *which* object is meant.

**Assuming is a loop.** "let $\omega_0$ be as in \eqref{eq:hyp}" where the conditions
on $\omega_0$ exist only there. "by \eqref{eq:riccati}, $z$ grows superlinearly."
"since $\|u\| \le C$ by \eqref{eq:bound}." You are consuming what the parent
asserts.

The test: **if the parent's statement were deleted, would this node still say the same
thing and would its argument still stand?** If not, it is a fact, and it is a loop.

Whether a particular reference names or assumes is a fact about your prose, so it is
judged per citation at `--level standard` and reported as `circular-citation` — with
the graph fact spelled out, so you can see which node rests on which. A `\ref`
pointing upward also gets `XRF003`, which warns and states the rule.

Two further costs even when it only names:

1. **The document reads dependencies-first**, so a child prints *before* its
   parent. A child referencing the parent's equation points forward, to something
   the reader has not met yet.
2. **The verifier reads that child with its own children as assumptions and no
   parent context at all.** It will not know what the reference means, and a model
   that does not know invents something.

The fix that removes all three, and the one to reach for whenever you find yourself
writing "in the setting of Section …": **put the shared thing in its own node and cite
it from both.** A `definition` node holding the function space, the equation, or the
standing notation, listed in the `children` of everyone who needs it. Then the
graph records the dependency, the verifier is handed it automatically, and it prints
before everything that uses it.

That is what `Section \ref{sec-space}` in a child's hypotheses actually wanted to
be.

### Citations are checked, in four places

This is worth a paragraph because it is the one thing in the system that was
comprehensively broken, and the fix is layered.

A statement that says "let $\omega_0$ be as in Section \ref{sec-space}" for a
section that does not exist used to survive **everything**: no check looked at the
target when it was written, the decomposer split it into seven children that all
inherited the phrase, and the verifier passed their proofs. Now:

1. **`bp check` errors** on the reference itself (`XRF001`).
2. **`bp expand` refuses** to decompose a statement carrying errors of its own,
   naming them, before spending a call. Everything downstream would inherit them.
   `--force` overrides if you are mid-edit.
3. **`bp verify` cannot pass it**, at any level, however sure the models are: the
   `xref` family is part of the verification record, so a dangling citation derives
   `flagged`.
4. **Each citation that *does* resolve becomes a question for the verifier** at
   `--level standard`: does the cited text say what this passage uses it for? That
   catches the case a compiler never could — a display that *defines* something being
   cited as though it *asserted* something, a bound cited as a strict inequality, a
   statement about $\omega_0$ applied to $\omega(t)$.

And separately, **the target theorem itself is now checked.** `TGT001` says when
nobody has audited it and `TGT002` when the audit predates the current wording. Run
`bp audit <target>` — or the button on the target's panel — before you decompose.
Everything in the project is built on that statement, so an ambiguity or a citation
to nothing in it is inherited by every child and much more expensive to find later.

*What this does not cover:* a citation written as prose — "by standard elliptic
regularity" — is not a `\ref`, so it is not enumerated. It reaches the system only if
claim extraction lists it, which is §8a's known soft spot.

### Things that break, and what they look like

The renderer passes your LaTeX through — it does not escape it, because escaping
would destroy it. The cost is that a mistake is yours to fix. These are the ones
worth recognising:

| Symptom | Cause |
|---|---|
| Text missing from the PDF, which compiled fine | A mid-line `%`. LaTeX comments out the rest of the line. Write `\%`. **`bp check` reports this as `TEX001`.** |
| "Missing $ inserted" | Maths outside maths mode. Most often a `proof:` or `literature:` discharge source containing bare maths — those are **free text**, so maths inside them needs its own `$…$`. A hypothesis `tex` and an `applied_to` are the opposite: fragments, which the renderer wraps for you. |
| "Paragraph ended before … was complete" | A blank line in a field that has to be one paragraph: an objection, an admission reason, a hypothesis fragment, a discharge source. |
| Prose typeset as italic mathematics in the browser | An unclosed `$`. **`bp check` reports this as `TEX002`.** |
| "Command \lemma already defined" | You are on an old build; update. Your preamble is now injected first and yours wins. |
| A page of an admitted statement missing | It overflowed its frame. Reported as a warning next to the successful compile. |
| `\begin{enumerate}` shown as raw source in the browser | KaTeX only typesets *maths*. Lists, `\newenvironment`s and `\\` line breaks appear as source on screen and typeset correctly in the PDF. Use **Open PDF** to see them properly. |

### The proof-reader

**Saving a statement or proof runs a proof-reader first.** It may fix syntax — an
unbalanced brace, `\end{aligned}` closing a `\begin{align}`, an obsolete `\bf` —
and it is forbidden from touching the mathematics. You see the rewrite beside your
original with a one-line reason for each change, and nothing is saved until you
pick. If it ever changes a symbol, an index or the direction of an inequality, that
is a bug worth reporting.

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

## 8c. You edited a statement. Now what?

Say you tighten the target: $s>1$ becomes $s>3/2$, and you add an oddness assumption.
It already has four children, three of them with proofs.

**What happens by itself.** The node's statement hash moves, so its verification is
void and it goes `blocked:stale`; so does every node above it that cited it. Its
**children are untouched**, which is right — a child does not depend on its parent.
The structural checks re-run immediately: if a child's discharge cited a hypothesis you
deleted, that is `DIS013` now; if a child needs one nobody sources, `DIS011`.

**What you are told.** The node panel gains a line under **The decomposition**:
*checked against an earlier version of this statement, or of a child* (`DEC010`). Every
`bp check-decomp` now leaves a certificate, so the system can say this instead of
leaving you to remember it. Note that the *colour* does not move for it — `DEC010` is a
warning about a judgement being out of date, not a claim that anything is false — so
after an edit, read `bp check` as well as the graph.

**What you should do.** Not `bp redo`. That archives the whole subtree — copied to
`attempts/` first, nothing is deleted — and decomposes from scratch, which throws away
proofs that were probably still fine. Instead:

    bp amend thm.main --hint "tightened s>1 to s>3/2 and added oddness"

or **Amend…** on the node. One call. It sees the statement as it now reads, the children
as they stand, and **the diff of your edit** — every edit keeps the text it replaced, so
the amender is told what changed rather than guessing. It comes back with one of three
answers:

- **`no-change`** — the edit does not affect the decomposition. Worth having: it costs
  one call and saves you reviewing changes nobody needs.
- **`amend`** — a verdict for every child (`keep`, `edit`, `drop`), any new lemma the
  statement now needs, a rewritten reduction, and a complete discharge table. That table
  goes through the same deterministic gate a decomposition does, so an amendment that
  leaves a hypothesis unsourced never reaches you.
- **`redecompose`** — the statement has moved far enough that patching would be
  dishonest. Then `bp redo` is the right answer, and you have paid one call to find out.

**Nothing is applied until you say so, item by item.** Each proposed change is shown
against the current text with a tick box — the statement diff, the hypotheses that
move, the reduction. Take three and leave one if that is your judgement; the discharge
check re-runs afterwards and tells you what your selection left open. Accepting an
edit invalidates that child's verification (correctly — re-verify it) and keeps its
proof. A dropped child is archived, never deleted. The subtree is copied to
`attempts/<node>-amend-<n>/` before the first write.

    bp amend thm.main --apply                          # take all of it
    bp amend thm.main --apply --only child:thm.elb      # take one item
    bp amend thm.main --show                            # re-read it, no call

**And you can always see what you changed.** Every edit to a Statement or a Proof keeps
the text it replaced:

    bp revisions thm.main                               # what versions exist
    bp revisions thm.main --show 2 --section statement  # print one
    bp revisions thm.main --show 2 --diff               # against what is there now

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
    writer:     {backend: claude_cli, model: opus}
    amender:    {backend: codex_cli,  model: default}
budget:
  per_run_usd: 3.0
  max_calls_per_run: 80
```

**The tiering is deliberate and it is where the bill is decided.** `extractor` is
doing translation, so it goes on the cheapest thing you have. `obligation` answers
the narrow one-question-at-a-time checks — both hypothesis discharges and ledger
claims — and at `--level deep` it is most of the calls, so a mid model there is the
single biggest lever on cost. The four that need a whole argument in view
(`verifier_a`, `verifier_b`, `confirmer`, `auditor`) want the strongest model you
have; do not economise on `confirmer` in particular, because without confirmation
the objection list is mostly pedantry and you will stop reading it. `writer` runs
only when you press **Paper…**, so it can afford your best setting — and since
nothing waits on it, it is the role least harmed by a slow subscription CLI.

Backends:

| backend | what | credential | reports cost |
|---|---|---|---|
| `claude_api` | metered Anthropic API | `ANTHROPIC_API_KEY`, or `ant auth login` | yes |
| `openai_api` | metered OpenAI API | `OPENAI_API_KEY` | yes |
| `claude_cli` | `claude -p` | a Claude subscription | **no** |
| `codex_cli` | `codex exec` | a Codex subscription | **no** |

**Every backend is adjustable from `bp.yaml`, and `bp agents --fill` makes that
literal:** it writes every role the file does not mention into it, using the value the
role already resolves to, keeping your comments and key order. Nothing about your setup
changes — it is just written down, so there is no layer left to infer. Run it once after
upgrading.

Beyond the twelve roles, one more knob:

```yaml
agents:
  panel: [verifier_a, verifier_b]   # who reads a whole proof
```

Two from different families is the design, but you can add a third reader or drop to
one. Every name must be a configured role, and an empty list is refused — nobody would
read a proof and nothing could ever be verified.

`bp agents` prints the table and says which can actually run here — and where each
role's backend came from:

| `from` | Means |
|---|---|
| `bp.yaml` | you configured it |
| `inherited from <role>` | Albatross added this role after your `bp.yaml` was written, so it copied the nearest role you *did* configure. Your project never moves to a different provider behind your back. |
| `built-in default` | nothing to inherit from. **Check this one** — the built-in defaults are Anthropic, and if you have no key the role cannot run. |

Add the inherited ones to your `bp.yaml` explicitly whenever you want to choose for
yourself. `usable: no` means any job needing that role will fail, and `bp agents` is
the only place that tells you before you spend a click.

**Put the two verifiers on different families.** That is the entire reason there
are two of them; two models from the same lab miss the same things, and the
second one costs the same either way.

**Two caps, and which one bites.** The dollar cap only constrains calls whose
price is known. A subscription CLI reports no price at all, so with CLI backends
the **call cap** is the only thing limiting a run. Keep it set.

**Both caps apply to any run, including one `bp verify`.** They were originally
spelled `*_per_recompile`, which read as though a single node could not reach them.
It can, easily: a `deep` verify of a node citing fifteen lemmas, whose proof has
twenty-one ledger claims, is *thirty-nine calls* — one per obligation, one per claim,
two panel members, a statement audit — plus one per objection. The old spellings are
still accepted.

**Price a node before you verify it:**

```
$ bp verify thm.main --level deep --dry-run
thm.main at --level deep

  extract        0 call(s)
  obligations   15 call(s)
  claims        21 call(s)
  whole proof    2 call(s)
  audit          1 call(s)
  confirm        ? one per objection raised above

  at least 39 call(s), plus one per objection; the cap allows 80 per run
```

Exact, not an estimate: every worklist is computed from your files. The Verify
dialog in the browser shows the same numbers, per level, before the button is live.

**A cap that is too low costs a message, not money.** A verification that stops
part-way is never recorded — "no objection in all 36 checks" and "no objection in
the 30 we could afford" are different claims, and only the first is worth anything —
so `verify` prices its worklist first and refuses before spending if the remaining
budget cannot finish. Raise `max_calls_per_run`, drop to `--level standard`, or use
`--batch 5`, and re-run: **the answers you already bought are cached**, so a second
attempt only pays for what is left. If the cap is reached during the final
confirmation pass, the verification *is* recorded — the expensive whole-proof passes
are already paid for by then — and the objections nobody could re-read are marked
`NOT CONFIRMED` in the node file and in the document.

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

**The single biggest waste is putting `extractor` and `obligation` on a top model at
maximum reasoning.** Between them they make most of the calls at `deep`, and neither
is doing mathematics: the extractor lists what a proof claims, and the obligation
role answers one narrow yes/no at a time. A maximum-effort setting there buys almost
nothing and multiplies the slowest part of every run by a large factor.

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

## 9c. The paper

Two documents come out of a project, and they are not interchangeable.

**`bp render`** is the one this system stands behind. It is generated from your node
files every time, it holds no state, and every gap in it is marked. It also reads
like a graph: statements in dependency order, `(H1)`, `(H2)` above each one,
`gclm.energy-lower-bound` where a paper would write "the energy estimate". `--clean`
removes the markers, not the shape.

**`bp paper`**, or the **Paper…** button, is the other one. An agent reads the whole
development and rewrites it the way a paper is written:

- hypothesis lists become sentences — *"Let $s > 3/2$ and let $u_0 \in H^s$ be
  divergence-free"*;
- routine lemmas move inside the proofs that use them, instead of being Lemma 7;
- sections are grouped by idea rather than by dependency depth, and the theorem is
  stated early and proved late, the way you would write it;
- results are named — *"by the energy estimate (Lemma 3)"* — and never referred to by
  node id.

It works in two passes: one call plans the sections and assigns every node a home,
then one call writes each section. `bp paper --plan` prices that before you spend it.

**What it is not.** It is not maintained, and it is not exact. It is built when you
ask and never touched again, so it goes out of date the moment you edit a node —
`bp paper --status` and the sheet lead with what has moved. And an exposition can
lose detail: a hypothesis restated in words, two lemmas combined, a justification
compressed.

**What stops that being dangerous.** Nothing can check that prose is faithful, so
instead nothing is allowed to go missing quietly:

- Every node of your development is assigned to exactly one section, and the
  assignment is checked against the graph. A node the outline drops is a `PAP001`
  error and, if the writer will not fix it, the paper's own appendix says the node is
  **not included**.
- Every section says which nodes it stated outright and which it folded into prose,
  with a note saying where each went. A section silent about a node it was given is
  rejected and rewritten.
- The writer's own declared departures and losses are printed in the paper.
- Under the title, written by code and not by the agent: what the development says
  the target rests on, every admitted or assumed statement with its reason, and how
  many statements have no verified proof. An exposition cannot make a conditional
  theorem unconditional by sounding more confident.
- An appendix maps every node to the section covering it. When a passage looks wrong,
  that is how you find the node it came from — and the node is the authority.

`--bare` drops the provenance note and the appendix, for a file going to a journal
rather than to you. Everything else is unchanged.

Downloading, re-rendering and compiling a paper you have already built cost nothing
and make no model call: `bp paper --rebuild`, or the buttons in the sheet.

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
| `bp obligations [id] [--kind discharge\|claim\|reference\|all]` | the worklists as JSON: one record per discharge, per sourced claim, and per citation |
| `bp render [--clean] [--audit] [--pdf] [-o F]` | the LaTeX document; `--pdf` compiles it and explains any failure |
| `bp labels` | every `\label`, everything referencing it, and everything referenced that does not exist |
| `bp revisions <id> [--section S] [--show N] [--diff]` | superseded versions of a statement or proof: every edit keeps the text it replaced |
| `bp events` / `bp jobs` / `bp calls` | history |
| `bp sweep` | re-derive and persist the computed fields |
| `bp admit <id> -r "…"` / `bp assume <id> -r "…"` | with a required reason |
| `bp note <id> "…"` / `bp relabel <id> <difficulty>` | |
| `bp archive <id>` / `bp unarchive <id>` | never deletes; `lifecycle` changes |

Agents — these call models and cost time or money:

| Command | |
|---|---|
| `bp agents` | which model plays which role, and whether it can run |
| `bp expand <id> [--hint "…"]` | decompose one level |
| `bp redo <id> [--hint "…"]` | archive the subtree and decompose again |
| `bp check-decomp <id>` | the two checker calls |
| `bp extract <id>` | build the claim ledger, then audit it |
| `bp verify <id> [--level L] [--batch N] [--no-record]` | the three jobs the level calls for, then confirmation |
| `bp audit <id>` | the four statement questions. Never changes a status, but does record that it ran — `TGT001` |
| `bp prove <id> [--force]` | write a proof for an easy leaf |
| `bp amend <id> [--hint "…"] [--show] [--apply] [--only k1,k2]` | adapt an existing decomposition to an edited parent (§8c). Proposing is one call; `--show` and `--apply` make none |
| `bp paper [--plan] [--status] [--rebuild] [--bare] [--guidance "…"] [--pdf]` | the readable write-up (§9c). `--plan` and `--status` and `--rebuild` make no model call |
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
- **Whether the claim ledger is complete** — see §8a.
- **Citations written as prose.** `\ref`-family citations are enumerated and checked
  (§6a); "by standard elliptic regularity" is not, unless claim extraction happens to
  list it.
- **Whether a `literature:` reference is real.** `LED005` warns when one names
  nothing findable, and that is all it can do — there is no bibliography to check
  against. Every claim *in* it is
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
  process everything is ordered — including PDF builds, which are serialised. Use
  one at a time.
- **Whether your LaTeX is valid**, beyond the two silent cases `TEX001` and
  `TEX002` catch. An unclosed `\begin{align}` or `\textbf{` is found by
  `pdflatex`, not by `bp check` — so **Open PDF** is part of checking your work,
  not just of reading it.
- **Whether the claim ledger is complete** — see §8a.
- **Citations written as prose.** `\ref`-family citations are enumerated and checked
  (§6a); "by standard elliptic regularity" is not, unless claim extraction happens to
  list it.
- **Whether a `literature:` reference is real.** `LED005` warns when one names
  nothing findable, and that is all it can do — there is no bibliography to check
  against.

---

## 12. Recipes

**"After updating, the panel shows an error and the buttons are gone."** The running
`bp ui` is older than the page. Stop it, start it again, and hard-reload
(Cmd-Shift-R / Ctrl-Shift-R). An orange strip under the top bar tells you this and
which way round it is; the action buttons render regardless, so you are never stuck.

**"Render LaTeX says internal server error."** That was a bug and it is fixed — a
document that will not compile now says which package is missing, in the sheet. If you
still see it, you are on a stale server (restart `bp ui`). If it survives a restart,
`bp render --pdf` in a terminal prints the real reason with a full traceback.

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
