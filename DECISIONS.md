# DECISIONS.md

Append-only. One entry per non-obvious choice the brief did not settle: the
decision, what else was considered, why this one, and what would have to change
to reverse it.

---

## D001 — The target node is marked with `target: true` in its frontmatter

**Date** 2026-07-29 · **Milestone** L0

The brief refers to "the target" in the orphan warning, in `bp why` and in the
render's support certificate, but never says how a node becomes the target.

**Decision.** A boolean `target` frontmatter field, false by default. Exactly one
active node should carry it; `REF008` warns when none or several do.

**Alternatives.** (a) The unique node with no parents. Rejected: the brief's own
orphan warning distinguishes "no parent" from "is the target", so they cannot be
the same condition, and a graph mid-edit often has several parentless nodes.
(b) A project config file. Rejected: v0 has no config file, and one more file to
keep in sync with the node ids is one more thing to go stale.

**To reverse.** Delete the field, treat the unique parentless node as the target,
and drop `REF008`. Nothing else reads it.

---

## D002 — Admission and assumption reasons live in a `status_reason` field

**Date** 2026-07-29 · **Milestone** L0

The brief requires a reason when marking a node admitted or an assumption ("*Mark
admitted | prompts for a reason, which is required*") but does not say where it
is stored.

**Decision.** An authored `status_reason` frontmatter field. `ops.admit` and
`ops.set_assumption` refuse an empty one. The renderer prints it in the support
certificate and in the node's box; `bp why` prints it beside the support item.

**Alternatives.** (a) Append it to the Notes section. Rejected: Notes is a
scratchpad fed to agents as context, and the reason needs to be retrievable as a
field to appear in the certificate. (b) A structured record with author and
date. Rejected as more than v0 needs; the event log already carries both.

**To reverse.** Move the text into Notes and read it from there; the only
consumers are `render.certificate`, `render._admitted_note` and `why._support_line`.

---

## D003 — Read-only commands never write; `bp sweep` persists; `SYS001` reports drift

**Date** 2026-07-29 · **Milestone** L0

The computed fields live in the node files, but the brief does not say when they
are written.

**Decision.** Every command derives statuses in memory. `bp sweep` and every
mutation in `ops.py` write them back. `bp check` compares what is in the files
with a fresh sweep and reports `SYS001` when they differ.

**Alternatives.** (a) Every command persists. Rejected: `bp status` silently
modifying six files, and showing up in `git status`, is a surprise, and a
read-only command that writes is a read-only command you cannot run on a shared
checkout. (b) Never store them in the files. Rejected: the brief's node format
shows them in the frontmatter, and a node file that says what it rests on is
worth a lot when reading one on its own.

**To reverse.** Call `persist_computed` from `checks.load_graph` and delete the
drift check.

---

## D004 — An `ADMITTED` discharge clamps the parent's effective local status

**Date** 2026-07-29 · **Milestone** L0

The brief says "*An `ADMITTED` discharge makes the parent's `local_status` at
best `admitted`, and its id enters the support set*" without saying where that
happens.

**Decision.** In the derived layer. `propagate.effective_local(N)` returns
`admitted` when `N.local_status` is `verified` and the node's `uses` table admits
any hypothesis. The file's `local_status` is left exactly as the author wrote it.

**Alternatives.** Rewrite `local_status` in the file when an admission is added.
Rejected: `local_status` is an *opinion*, and the system silently editing the
user's opinion is precisely the confusion the local/global split exists to
prevent. Deriving keeps the file honest about who said what.

**To reverse.** Nothing depends on the file being unmodified; but see the
argument above before doing it.

---

## D005 — `SOURCE_RE` is compiled with `re.DOTALL`

**Date** 2026-07-29 · **Milestone** L0

**Decision.** The regex is exactly as the brief specifies, with `re.DOTALL`
added, so a `proof:` source may span several lines.

**Why.** Without it, a discharge like `proof:` followed by two lines of
justification fails to match and is reported as `DIS012` — an unrecognised
form — which is a false positive for the one source kind that is explicitly free
text. A false `DIS012` teaches the user to distrust the check.

**To reverse.** Drop the flag. No other behaviour depends on it.

---

## D006 — Diagnostic codes beyond those the brief names

**Date** 2026-07-29 · **Milestone** L0

The brief names `DIS010`–`DIS016` and describes the integrity and children-used
checks without giving them codes.

**Decision.** Integrity is `REF001`–`REF008` (following `DESIGN.md` §8's `REF`
prefix, renumbered because v0's graph has no separate proof objects);
children-used is `USE001`; drift is `SYS001`. Four codes are genuinely new:

- `SCH002` (unknown frontmatter key) — YAML accepts a misspelled `childern:` in
  silence, and a whole decomposition would drop out of the graph with no
  diagnostic at all. Node files are hand-edited; this is not hypothetical.
- `SCH003` (marked verified with no proof and no children) — otherwise the sweep
  reports `proved` for a node with nothing behind it. The author probably meant
  `assumption`.
- `DIS017` (`discharges` names a hypothesis the child does not have) — a typo
  here also produces a `DIS011` for the *correct* id, so the user sees "H2 is not
  discharged" while looking at a line that appears to discharge it. This makes
  the actual mistake visible.
- `DIS100` (an admitted discharge, with its reason) — informational, matching
  `DESIGN.md` §8's `DIS100`. It makes debt visible in `bp check` output rather
  than only in the rendered document.

None of the four is an error, so none affects the exit code.

**To reverse.** Delete the check functions; the codes are not referenced
elsewhere.

---

## D007 — Backticked node ids in bodies become LaTeX cross-references

**Date** 2026-07-29 · **Milestone** L0

The brief's own example proof writes ``Assuming `mff.elb-a` and `mff.elb-b```,
in markdown backticks, inside what is otherwise free LaTeX.

**Decision.** `render.resolve_refs` turns `` `x` `` into `\hyperref[node:x]{\texttt{x}}`
when `x` is an active node id, and into `\texttt{x}` otherwise.

**Why.** A literal backtick in LaTeX is an opening quotation mark, so the
brief's own convention would render as ``mff.elb-a'` — wrong and ugly. Treating
it as a citation is both what the author meant and useful: the document gets
working internal links.

**Risk.** A body that uses double backticks for genuine LaTeX quotation marks is
untouched (the regex requires single backticks with no newline inside), but a
single backtick used as a quote mark and followed by another one would be
rewritten. This has not occurred; if it does, require the content to match a
known node id rather than merely the id syntax.

---

## D008 — Authored text is passed through to LaTeX; only ids are escaped

**Date** 2026-07-29 · **Milestone** L0

**Decision.** `render.escape` is used for node ids and generated labels only.
Everything a human or an agent wrote — statements, proofs, notes, admission
reasons, discharge sources, hypothesis fragments — goes through `render.prose`,
which escapes a bare `%` and nothing else. Hypothesis `tex` and `applied_to` are
treated as **math-mode fragments** and wrapped in `$…$` by `render.math`.

**Why.** Everything in this system is LaTeX; the brief says so twice ("free
LaTeX prose", "edits are LaTeX textareas"). Escaping an admission reason that
reads `needs $\varepsilon_0$ small` renders it as literal backslash-v-a-r. The
one exception is worth making: an unescaped `%` silently swallows the rest of a
line, and silence is the failure mode to avoid.

**To reverse.** Escape everything and require authors to write `$…$` themselves;
expect complaints.

---

## D009 — Hashes are always written quoted, and a float-shaped hash is refused

**Date** 2026-07-29 · **Milestone** L0

**Decision.** `load.quoted` forces every hash written to YAML into a quoted
scalar. A `statement_hash` or `verified_against` value that comes back from YAML
as a float raises a `LoadError` explaining that it must be quoted; an integer is
accepted and stringified, because integers round-trip exactly.

**Why.** `896e63762324` is a valid YAML float and becomes `inf`. Every hash of
that shape would then compare equal to every other, and `is_stale` would return
`False` for a node whose statement had changed — failing *open*, in the one place
the system must fail closed. This was found by the acceptance fixture, which is
the argument for having written a realistic fixture.

**To reverse.** Nothing; do not.

---

## D010 — Citation matching is by whole token, not substring

**Date** 2026-07-29 · **Milestone** L0

The brief specifies the children-used check as "the id string must appear in the
Proof section".

**Decision.** `model.cites` requires the id to stand as a whole token: not
preceded or followed by an id character, while still permitting a trailing full
stop.

**Why.** A plain substring test reports that a node called `a` is cited by the
word *never*, and that `gclm.elb-a` is cited by a mention of `gclm.elb-ab`. Both
directions are wrong, and the first makes the check useless for short ids.

**To reverse.** Replace with `cid in proof`; two call sites.

---

## D011 — Archiving detaches citations from parents and records them

**Date** 2026-07-29 · **Milestone** L0

Archiving a cited node would leave every parent with a `REF004` error forever.

**Decision.** `ops.archive` removes the archived ids from parents' `children` and
`uses`, and records each removal in the event payload under `detached`.

**Alternatives.** (a) Leave the citations and let the errors stand. Rejected: a
permanently broken graph that cannot be swept is worse than a recorded edit.
(b) Refuse to archive a cited node. Rejected: the brief's Archive button archives
"the node and its orphaned descendants" without such a condition.

**Note.** This is the closest thing in v0 to a destructive operation. It destroys
nothing — the archived node keeps its file and text, and the removed citations
are in the log — but it is the one place where an operation on node A edits node
B. Cascade is limited to descendants that this actually orphans; a node still
cited from elsewhere stays active.

---

## D012 — `ops.record_verification` exists in L0

**Date** 2026-07-29 · **Milestone** L0

The brief's L0 operation list does not include it, and the L0 *do not build*
list forbids anything that calls a model.

**Decision.** Build it. It calls no model: it takes a verdict as an argument,
writes `local_status` and `verified_against`, and appends an event.

**Why.** `verified_against` is required to be written "only when a verification
succeeds". Without this function, no code path writes it at all, so the field
could only ever be filled by hand — which the same brief forbids — and staleness
would be untestable. The L1 verifier will call it rather than writing frontmatter
itself.

---

## D013 — Reading order in the rendered document is a post-order walk from the target

**Date** 2026-07-29 · **Milestone** L0

The brief says "topological order […] then the target theorem last", and
topological order is not unique.

**Decision.** Depth-first post-order from the target, visiting children in
declared order. Nodes the target does not reach go to an appendix titled "Nodes
not cited by the target". With no target, lexicographic reverse-topological
order.

**Why.** Post-order from the target reads the way a paper does: each lemma
appears immediately before the argument that uses it, related lemmas stay
together, and the theorem is last. A bare topological sort satisfies the brief
but interleaves unrelated branches. The appendix exists because silently
dropping a node from the document would make the document a lie about the
project.

---

## D014 — Admitted nodes' proof text renders as a sketch, not a `proof` environment

**Date** 2026-07-29 · **Milestone** L0

**Decision.** A node with `local_status` `admitted` or `assumption` renders as a
boxed `assumption`, as the brief requires; if its Proof section has text, that
text is set as *"Sketch — this is not a proof"* rather than inside `\begin{proof}`.

**Why.** `amsthm`'s proof environment ends with a QED box. Putting one at the end
of an argument nobody has made is a false claim in exactly the place the document
must not make one, and the reader's eye reads the box before the words.

---

## D015 — Project discovery walks up for `nodes/`; no config file in L0

**Date** 2026-07-29 · **Milestone** L0

**Decision.** A project is a directory containing `nodes/`. Commands walk up from
the working directory to find it, the way `git` finds its repository. `$BP_ROOT`
overrides, and `--root` overrides that. State goes in `.bp/`.

**Why.** The brief introduces `bp.yaml` only for agent configuration, which is
L1. Nothing in L0 needs configuration, and an empty config file invites people to
put things in it.

**To reverse.** L1 adds `bp.yaml`; make its presence an additional project
marker.

---

## D016 — Developed on Python 3.14 although the brief says 3.12

**Date** 2026-07-29 · **Milestone** L0

**Decision.** `pyproject.toml` requires `>=3.12`; the development virtualenv is
the Python 3.14 that was installed. Every dependency installs and imports
cleanly, and nothing in the code uses a feature newer than 3.12.

**To reverse.** Create the virtualenv from a 3.12 interpreter; no code changes.
