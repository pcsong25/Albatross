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
