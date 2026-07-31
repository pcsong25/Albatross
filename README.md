# Albatross

**An interactive proof-decomposition assistant for research mathematics.**

You are trying to prove a theorem. You break it into lemmas, break those into
smaller lemmas, and at any moment some are proved, some are sketched, some are
believed but unargued, and some you have not started. The bookkeeping of *which is
which, and what your theorem currently depends on* is tedious, error-prone, and
exactly the thing that quietly goes wrong over months.

Albatross holds that bookkeeping. Each lemma is one markdown file with LaTeX in
it; the files form a graph. Agents propose decompositions, argue with them, check
proofs and write the easy ones. A deterministic core keeps the accounting honest
and renders the whole thing to a LaTeX document that cannot drift from the graph.

```
┌─ what it guarantees ──────────────────────────────────────────────────────┐
│  Complete bookkeeping. Every hypothesis a cited lemma needs, and every    │
│  load-bearing claim a proof makes, has a named source — or there is a     │
│  hard error. Statuses are derived, never asserted. A verification dies    │
│  the moment anything it depended on changes.                              │
├─ what it does not ────────────────────────────────────────────────────────┤
│  Any mathematical claim whatsoever. A green node means "no agent found a  │
│  problem in N enumerated checks at level L". It never means proved.       │
└───────────────────────────────────────────────────────────────────────────┘
```

That distinction is the whole design, and it has a name:

> **Agents supply judgement. Code supplies the guarantee that the judgement was
> complete.**

Whether a claim is true cannot be checked deterministically. That every claim was
*enumerated*, *assigned a source*, and *dispatched to a verifier* can be — and is.
Read [ARCHITECTURE.md §0](ARCHITECTURE.md) before you trust anything this tool
tells you; it is one page and it is the most important page.

---

## Install

Requires **Python 3.12+**. A LaTeX installation is optional but wanted — without
one you get the `.tex` source and no PDF.

```bash
git clone <this repo> albatross && cd albatross
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q        # 598 tests, no network, no API key
```

`bp` is then on the venv's path. Either activate the venv or use
`.venv/bin/bp` — the examples below assume `bp`.

### LaTeX

For a PDF you need `pdflatex`. A **minimal** TeX install is not enough for most
real documents: BasicTeX and `texlive-latex-base` both lack `enumitem`,
`cleveref` and much else, and the failure is a hard "File `enumitem.sty' not
found".

| Platform | Enough | Comfortable |
|---|---|---|
| macOS | [BasicTeX](https://tug.org/mactex/morepackages.html) + `sudo tlmgr install enumitem cleveref` | [MacTeX](https://tug.org/mactex/) (~5 GB, everything) |
| Debian/Ubuntu | `texlive-latex-recommended` | `texlive-latex-extra texlive-science` |
| Anywhere | — | `tlmgr install <package>` as needed |

Albatross tells you which package is missing and the command that installs it, so
you can also just start and fix it when it complains.

### Models

Every model call goes through one layer and is configured in `bp.yaml` by *role*,
never by model name. Nothing needs a key until you use an agent command — the
whole deterministic core runs offline.

```bash
export ANTHROPIC_API_KEY=...     # or OPENAI_API_KEY, or a Claude/Codex CLI login
bp agents                        # which model plays which role, and what can run here
```

---

## An example to look at first

```bash
cd examples/gclm
bp status          # one line per node
bp check           # two deliberate errors — see the README there
bp why             # why the target is not proved, in English
bp render --pdf    # the document, with every gap marked
```

All deterministic: no key, no network, no model calls. **Read
[examples/gclm/README.md](examples/gclm/README.md) first** — the mathematics in it is
illustrative and has never been checked, and some of it is wrong on purpose.

The repository root is not a project, so `bp` run there will tell you it cannot find
one. That is correct.

## Five minutes

```bash
mkdir ~/proj && cd ~/proj
bp init . --id gclm.main --statement 'Fix $a \in (0,1/2)$. Then the solution blows up.'
bp ui                            # http://127.0.0.1:8000
```

The browser is the intended surface. From there:

1. **Expand** the target — the decomposer proposes 3–7 lemmas, a reduction proof,
   and a complete table saying where every hypothesis of every cited lemma comes
   from. That table is the point: a model cannot fill it in without confronting
   whether its lemmas actually cover the parent, and most insufficient
   decompositions die there, deterministically, before any verifier runs.
2. **Check decomposition** — two fixed questions about what came back.
3. **Generate proof** on the cheap leaves. A refusal here is the most valuable
   thing the tool produces: it is usually a fact about your *decomposition*.
4. **Verify** — at `quick`, `standard` or `deep`. What ran is recorded on the node
   and printed into the document.
5. **Render LaTeX** — the paper, with every gap marked.

Everything is also a CLI command; `bp --help` lists them. See
**[GUIDE.md](GUIDE.md)** for the full manual, including a reference for every
button, label and colour in the interface.

---

## What it looks like on disk

Plain files. No database, no lock-in, and hand-editing is expected — the writer
preserves your comments, key order and quote style.

Your project is its own directory, separate from this repository.

```
myproject/
  nodes/*.md        one file per lemma: YAML frontmatter + LaTeX body
  preamble.tex      your own macros; read by the renderer, the agents AND the browser
  bp.yaml           which model plays which role
  attempts/         what `bp redo` archived before regenerating
  .bp/              events.jsonl (append-only), the call log, the answer cache, build/
```

A node:

```markdown
---
id: gclm.energy-lower-bound
role: proposition
children: [gclm.elb-a, gclm.elb-b]
difficulty: hard
local_status: verified

hypotheses:                  # what a PARENT must discharge to cite this node
  - {id: H1, tex: "0 < a < 1/2"}

uses:                        # for each child, where each of ITS hypotheses comes from
  gclm.elb-b:
    applied_to: "\\omega(t,\\cdot)"
    discharges:
      H1: "hypothesis:H1"
      H2: "child:gclm.elb-a"
      H3: "ADMITTED: the a priori $L^\\infty$ bound is not established here"
---

## Statement
Let $0 < a < 1/2$ …

## Proof
By `gclm.elb-a` the sign of the gradient is preserved …

## Notes
Free prose. Fed to agents as context.
```

The `ADMITTED` line is visible debt: that node now enters its own support set, and
it appears in the theorem's certificate until somebody discharges it. A hypothesis
you cannot source has to be written down, and that single rule is where most of
the value comes from.

---

## Documentation

| | |
|---|---|
| **[GUIDE.md](GUIDE.md)** | The user's manual. Install, daily workflow, every button and colour, every command, costs, and what the system does not check. Start here. |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | How it works, and — §0 — exactly what it guarantees and what it does not. |
| **[DECISIONS.md](DECISIONS.md)** | Every non-obvious design choice, what else was considered, and what would reverse it. |
| **[UPGRADE.md](UPGRADE.md)** | What is deliberately not built, what it would cost, and the signal that says you now need it. |
| **[BUILD_LOG.md](BUILD_LOG.md)** | What was built when, and what surprised us. |
| `LIGHT.md`, `ADDENDUM-A.md`, `DESIGN.md` | The build brief, its amendment, and the larger design v0 is a subset of. |

---

## Design commitments

Five things this codebase will not trade away, because each is either impossible
to retrofit or the reason the tool is worth using:

1. **Global status is computed, never written by an agent.** If an agent could
   write it, the colours would be opinions rather than derivations, and glancing
   at the graph would tell you what the models believe instead of where you are.
2. **The document is rendered from the node files and holds no state.** An
   agent-maintained document drifts, and the document is what you read — you would
   be reading a plausible fiction of your own proof.
3. **Nothing is destroyed.** Archiving replaces deletion; the event log is
   append-only and fsynced per append.
4. **Every cited lemma's hypotheses are discharged explicitly**, and **every
   load-bearing claim in a proof is sourced explicitly.** Between them, no gap in
   a proof can be silent.
5. **No role sets a status.** `local_status` is derived from a record of what was
   actually checked, and the writer re-derives it and refuses a verdict that
   disagrees with its own evidence.

## Limits worth knowing before you rely on it

- **Verification is unsound.** It narrows each question as far as it can and
  enumerates the questions deterministically, which is the best available
  configuration for LLM verification — and still not a proof.
- **The claim ledger is not guaranteed complete.** Every claim *in* it is sourced
  or errors; a load-bearing claim the extractor never listed is invisible.
- **No constant-dependency or vacuity checking.** An agent stands in for both and
  is much weaker than the real checks (`UPGRADE.md`).
- **One process at a time.** Running `bp ui` and a `bp` command simultaneously is
  unguarded; they can overwrite each other's answer cache.
- **Single user, localhost.** There is no authentication, and there is not meant
  to be.

## Status

v0, in active use on a real problem. The deterministic core is well covered by
tests; the agent layer is exercised against scripted backends and, less
systematically, against live models.

## License

TODO — pick one before publishing. Until then, all rights reserved.
