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

---

## D017 — Prompt files are the *system* prompt; the user message is assembled by code

**Date** 2026-07-29 · **Milestone** L1

The brief requires each role's prompt to live in a separate `prompts/*.md` file
"so the user can edit prompts without touching code", without saying what the
file contains.

**Decision.** Each file is the **system** prompt: the instructions, the standards
of a good decomposition, what counts as a finding. The **user** message is built
from the graph by `bp/roles/context.py`.

**Why.** The instruction wording is where most of the quality lives and is what a
mathematician will want to iterate on — that belongs in a file they can open.
Which node's statement, hypotheses and ancestors get sent is data assembly, not
prose; putting it in a file to be hand-edited would invite the two to drift and
make a prompt file unable to say what it was actually asked about.

---

## D018 — The JSON schema instruction is appended by the agent layer, not written in the prompt files

**Date** 2026-07-29 · **Milestone** L1

**Decision.** `Backend.complete` appends the pydantic model's JSON Schema and the
"double every LaTeX backslash" warning to every user prompt. The prompt files
never mention JSON.

**Why.** The prompt files are meant to be edited by someone thinking about
mathematics. The JSON contract is machinery, and an accidental edit to it breaks
every call from that role in a way that looks like a model failure. Keeping it
out of reach is the point.

**To reverse.** Move `schema_instruction` into each prompt file and stop
appending; every prompt then has to be kept in sync with its schema by hand.

---

## D019 — A JSON parse failure gets one mechanical repair before the retry

**Date** 2026-07-29 · **Milestone** L1

**Decision.** If a reply will not parse, backslashes that JSON does not recognise
as escapes are doubled and the parse is retried once. Whether that happened is
recorded on the call as `repaired_json`.

**Why.** Every string this system moves through a model is LaTeX, and a model
asked for JSON containing `\omega` very often writes a single backslash, which is
not legal JSON. Throwing the whole answer away and paying for a retry when the
content is fine and only the escaping is wrong is waste.

**The known limitation, stated in the code.** `\nabla` *is* legal JSON — `\n`
followed by `abla` — so a strict parse succeeds and silently yields a newline.
The repair cannot help there. That is why the schema instruction asks for doubled
backslashes: the repair is the safety net, not the plan.

---

## D020 — A decomposition that still fails after two repairs is written anyway

**Date** 2026-07-29 · **Milestone** L1

The brief says to allow two repair rounds "before surfacing to the user" without
saying whether the failing decomposition is written.

**Decision.** Write it, and report the remaining diagnostics. `bp expand` exits
non-zero when it does.

**Why.** It matches what the rest of the system does with debt: the shipped
fixture has a `DIS011` committed to it on purpose. `bp check` says exactly what
is wrong, `bp why` explains what it blocks, the renderer marks it, and nothing is
destroyed if the user archives it. Discarding a decomposition that is 90% right
because one hypothesis has no source would throw away the useful part and leave
the user nothing to edit.

**Alternative.** Refuse and return only the diagnostics. Reasonable, and one line
to change (`apply=False` in `expand`) if the user finds the graph accumulating
junk.

---

## D021 — Child ids are `<project prefix>.<slug>`, de-duplicated with a numeric suffix

**Date** 2026-07-29 · **Milestone** L1

**Decision.** The model proposes a short kebab-case slug with no prefix. The
prefix is the first dotted component of the parent's id, so a child of
`gclm.blowup` becomes `gclm.riccati-bound`. A collision with an existing id gets
`-2`, `-3`, …

**Why.** Ids are the system's stable keys and appear in citations, hashes, the
event log and every discharge table; letting a model choose them freely would
produce collisions and ever-lengthening paths (`gclm.blowup.energy.lower.bound`).
Deriving the prefix keeps a project's ids in one namespace without asking the
model to know what the namespace is.

---

## D022 — Silence from the whole verifier panel is not agreement

**Date** 2026-07-29 · **Milestone** L1

Found while testing: `BudgetExceeded` subclasses `AgentError`, and the panel's
"one verifier failing is survivable" `except AgentError: continue` was catching
it. A recompile sailed straight past its call cap, and — worse — a node whose
verifiers had *all* failed was being recorded as `verified`, because no
objections had been collected.

**Decision.** Two changes. `BudgetExceeded` and `ReplayMiss` are re-raised rather
than caught. And `verify` counts how many panel members actually answered; if
none did, it refuses to record a verdict and raises.

**Why.** A network outage, an expired subscription or an exhausted budget would
otherwise turn into a green graph — the exact failure the whole system exists to
prevent, arriving through the back door. One panel member failing is survivable
and shows up as its absence from `checked`; both failing is not.

---

## D023 — Verifier results are cached on the obligation hash, in `.bp/verify/obligations.json`

**Date** 2026-07-29 · **Milestone** L1

**Decision.** One JSON file mapping obligation hash to verdict. Written after
each node's obligations are checked.

**Why.** The brief requires caching on the hash. A single file is enough at this
scale, is readable, and diffs sensibly; one file per hash (as the call log does)
would be tidier at ten thousand obligations and is a trivial change if it ever
matters.

**Note.** The cache is keyed on what the obligation *asks*, normalised for
whitespace — not on where it sits. That is what makes editing one paragraph of a
proof leave the other obligations as cache hits.

---

## D024 — `ADMITTED` discharges are not sent to the verifier

**Date** 2026-07-29 · **Milestone** L1

**Decision.** Obligation records for `ADMITTED` sources carry `kind: "admitted"`
and are skipped by the verifier and by the recompile estimate.

**Why.** There is nothing to ask. The author has already said this hypothesis has
no source, the sweep's admitted clamp has already put the node into its own
support set, and the certificate already prints it. Paying a model to confirm a
stated absence is pure cost.

---

## D025 — A backend's command vector is configuration, not a constant

**Date** 2026-07-29 · **Milestone** L1

**Decision.** `claude_cli` and `codex_cli` ship a default argv, overridable per
role in `bp.yaml` under `options.command`.

**Why.** This was not hypothetical. `codex exec` refuses to run outside a trusted
directory without `--skip-git-repo-check`, and a Codex CLI signed in with a
ChatGPT account rejects an explicit `--model` outright. CLI flags drift between
releases, and the user should be able to follow that drift by editing one line of
YAML rather than opening a `.py` file.

---

## D026 — The shipped `bp.yaml` uses the subscription CLI backends

**Date** 2026-07-29 · **Milestone** L1

**Decision.** The committed configuration points every role at `claude_cli` or
`codex_cli`. The code's built-in defaults (used when `bp.yaml` is absent) point
at `claude_api` with `claude-opus-5`.

**Why.** This machine has the `claude` and `codex` CLIs and no API key, so the
CLI backends are what actually runs here, and a shipped configuration that cannot
run is worse than none. The comments in the file say exactly what to change to
move to the metered API. Note the consequence, which the file also states: with
subscription backends the dollar cap can never fire, so the **call cap** is the
only thing limiting a run.

---

## D027 — L1's commands live in `bp/cli_agents.py`, not in `bp/cli.py`

**Date** 2026-07-29 · **Milestone** L1

**Decision.** A separate module, registered onto the same `typer` app.

**Why.** Everything in `bp/cli.py` runs with no key, no network and no
configuration, and that property is worth being able to see at a glance. The
agent commands fail for a whole additional class of reasons and report in those
terms. The split is also what lets the L0 acceptance still be run in isolation.

---

## D028 — Recompile selects stale and unverified-with-proof nodes only

**Date** 2026-07-29 · **Milestone** L1

**Decision.** Exactly what the brief says: `blocked:stale` and
`blocked:unverified`. Not `open` nodes (nothing to verify), not `blocked:children`
(the reduction is already verified; the problem is underneath), not
`proved_modulo`.

Ordering is by distance from the target, shallow first, then everything else
alphabetically — so a partial run leaves the user closer to knowing about their
theorem rather than about an unrelated branch.

**Also decided:** the `--dry-run` estimate excludes confirmation calls and *says
so* in the output. They happen only for objections, and how many there will be is
not knowable in advance. Inventing a number would make the estimate look more
precise than it is; omitting it silently would make it look cheaper.

---

## D029 — The scripted backend ships in the package, not in the tests

**Date** 2026-07-29 · **Milestone** L1

**Decision.** `bp/agents/scripted.py` is a registered backend named `scripted`.

**Why.** It lets a test project's configuration point a role at canned replies
without the role code special-casing anything, which means the tests exercise the
real path — registry resolution, schema validation, retry, budget — rather than a
parallel one. It is never a default and has to be named explicitly, so a real run
cannot reach it by accident.

**Alternative.** A test-only fixture that monkey-patches `Backend.invoke`.
Rejected: it would bypass the registry, which is exactly the layer worth testing.

---

## D030 — The frontier ranking lives in the core, not in the interface

**Date** 2026-07-29 · **Milestone** L2

The brief puts the frontier queue in the action bar and specifies its ranking:
"nodes awaiting a decision, ranked shallow-first then by how many nodes they
gate".

**Decision.** `bp/frontier.py`, with `bp frontier` on the CLI and
`GET /api/frontier` in the UI, both returning the same list.

**Why.** It is a derivation over the graph, and the rule "the UI contains no
logic of its own" is only meaningful if it is followed when it costs something.
A ranking computed in JavaScript would be a second opinion about the graph, and
the moment the CLI grew a frontier command the two would disagree.

**The definition, which the brief left open.** A node is on the frontier when it
is unfinished **and every active child is finished**. That second clause is what
makes the list actionable: a theorem blocked by three unproved lemmas is not a
place to work, it is a place to wait — its lemmas are. It matches
`DESIGN.md` §6's `frontier` predicate.

---

## D031 — Cytoscape and KaTeX load from a CDN, with `bp ui --vendor` for offline

**Date** 2026-07-29 · **Milestone** L2

The brief says "from a CDN or vendored".

**Decision.** Both. The page prefers `static/vendor/` when it exists and falls
back to jsDelivr; `bp ui --vendor` downloads 23 files (~1 MB) into that
directory.

**Why not CDN alone.** The deterministic half of this system works with no
network — `bp check`, `bp why`, `bp render`, and every agent call under
`--replay`. It would be a poor joke if the interface to it did not.

**Why not vendored alone.** A megabyte of minified JavaScript and twenty font
files in the repository, for a user who may never work offline, and which then
have to be updated by hand.

Only `.woff2` fonts are fetched. Every browser of the last decade takes them and
the `.woff`/`.ttf` fallbacks would triple the download for no living user.

---

## D032 — A running job refuses conflicting work; it does not block it

**Date** 2026-07-29 · **Milestone** L2

The first implementation held a write lock for the whole body of a job. It was
found by driving the acceptance session: with a decomposition running, *every*
edit in the interface hung, including edits to unrelated nodes.

**Decision.** Two changes. Ordering moved to `bp.ops.serialised`, a process-wide
re-entrant lock taken by each mutation individually — a mutation is *read, edit,
sweep, write derived fields*, and two of those interleaving would let one sweep
persist values computed before the other's edit. And an operation on a node an
agent is working on is refused with a 409 naming the node, rather than queued
behind it.

**Why refuse rather than queue.** The request returns at once with something the
user can act on, and it matches the brief: "a running job disables the buttons
that would conflict with it and leaves the rest live." A queued edit that lands
four minutes later, on top of whatever the agent wrote, is worse than being told
no.

**Still unguarded.** Two *processes*. `UPGRADE.md` has the row, and it is sharper
now: running the UI and a CLI at once is easy.

---

## D033 — The whole-graph read is one endpoint, not one per node

**Date** 2026-07-29 · **Milestone** L2

**Decision.** `GET /api/graph` returns every active node's summary plus the
edges, counts and certificate in one response; `GET /api/node/{id}` returns the
full detail for the selected one only.

**Why.** The graph panel needs status for every node at once and the detail panel
needs everything about exactly one. Splitting it that way means a redraw after a
mutation is two requests rather than forty, and the detail payload can afford to
carry the obligations and the `why` chain without paying for them per node.

---

## D034 — The interface renders a PDF when a TeX toolchain is present

**Date** 2026-07-29 · **Milestone** L2

The brief says the Render LaTeX button "opens the document; a download button".

**Decision.** Three things: the source in a panel, a `.tex` download, and an
*Open PDF* button that runs `pdflatex` twice and serves the result. Without
`pdflatex` on `PATH` the PDF endpoint returns 501 with a message pointing at the
download, and the other two still work.

**Why.** For a mathematician "the document" means the typeset one, and the
toolchain is already assumed by the milestone's own acceptance criterion that
the LaTeX compiles. Failing softly when it is absent keeps the interface usable
on a machine without TeX.

---

## D035 — The chevron is the node's left edge, and folding is view-only

**Date** 2026-07-29 · **Milestone** L2

The brief: "the chevron on a node collapses its subtree in the **view only**,
with zero graph mutation."

**Decision.** Each node with children carries `▾`/`▸` at the start of its label.
A tap inside the leftmost 22 pixels of the node's bounding box folds; a tap
anywhere else selects. Folded state is a `Set` in the page — no request is made
and nothing is written, so it is a property of that browser tab and vanishes on
reload.

**Alternatives.** Double-click to fold (invisible, undiscoverable) or a fold
button in the detail panel (works, but then it is not on the node, and the point
is to prune the picture while looking at the picture).

---

## D036 — `bp init` and `bp new`, because a guide should not begin "hand-write this YAML"

**Date** 2026-07-29 · **Milestone** L2 (follow-up)

Writing the usage guide surfaced it: there was no way to *start* a project. Every
command needs a `nodes/` directory with something in it, and the only way to get
the first node was to hand-author frontmatter with exact field names. The web
interface could not help either — "Add child" needs a node to hang the child on.

**Decision.** `bp init <dir> --id <node-id>` makes `nodes/`, writes the target
node and copies `bp.yaml`; `bp new <id> [--parent P]` creates one by hand. Both
are thin wrappers over `ops.add_node`, so nothing new can be written to a node
file by a path that does not go through `ops`.

**Also added, for the same reason:** `bp frontier`, so the ranked queue is
reachable from the terminal and not only from the browser.

---

## D037 — Attaching a child creates its row in the discharge table

**Date** 2026-07-29 · **Milestone** L2 (follow-up)

Adding a child by hand — from the CLI or the interface's Add child — produced a
`DIS010` immediately: *"child X is cited but has no `uses` entry"*. The user had
not made a mistake; the system had.

**Decision.** `ops.add_node(parent=…)` gives the new child an empty `uses` row.
For a fresh child with no hypotheses that row is complete and no diagnostic
fires. As soon as the child gains hypotheses, `DIS011` names them one at a time,
which is the useful message.

---

## D038 — The discharge table is editable from the browser

**Date** 2026-07-29 · **Milestone** L2 (follow-up)

The L2 acceptance session added a child through the interface and produced a
`DIS010` that **could not be fixed from the interface** — the discharge table was
read-only, so the only repair was a text editor. That contradicts the milestone's
own criterion of running a full session from the browser alone.

**Decision.** `POST /api/node/{id}/uses` (wrapping `ops.set_uses`, which already
existed) and an edit dialog that generates one input per hypothesis of each cited
lemma.

**Why generated from the children's hypotheses rather than a free-form editor.**
The rows you are asked to fill in are then exactly the rows the discharge check
will ask about, and there is no way to leave one out by forgetting it exists.
That is the same argument as requiring the decomposer to return a complete
table — the form is the anti-gap device, not the diligence of whoever fills it in.

---

## D039 — Bare display environments count as mathematics

**Date** 2026-07-29 · **Milestone** L3 (friction log)

The user's first real theorem contained `\begin{align} … \end{align}` with no
dollar signs around it — which is ordinary LaTeX — and the browser printed it as
literal source. The splitter only knew `$…$`, `$$…$$`, `\[…\]` and `\(…\)`.

**Decision.** `align`, `equation`, `gather`, `multline`, `alignat`, `flalign`,
`eqnarray`, `displaymath` and `CD`, starred or not, are recognised standalone and
handed to KaTeX whole (it renders them directly, in display mode).

**Not** included: `aligned`, `cases`, `split`, the matrix environments. Those only
ever occur *inside* mathematics, so they are already covered by the surrounding
delimiter, and matching them standalone would risk capturing an inner environment
when the outer one was malformed.

---

## D040 — The project keeps its own LaTeX preamble, and three things read it

**Date** 2026-07-29 · **Milestone** L3 (friction log)

A statement written in the author's own macros is unreadable to KaTeX, missing
from the rendered document, and — worst — **guessed at by every agent**. A model
shown `\ip{u}{v} \in \Hs` and nothing else will invent a meaning and answer
confidently.

**Decision.** `preamble.tex` at the project root, optional. Injected verbatim
into the rendered document; included in the context of every role; parsed by the
browser into a KaTeX macro map.

**Why the browser parses it rather than the server.** KaTeX takes a macro map but
does not learn from a `\newcommand` it renders — verified, not assumed. So
something must parse it, and the parse decides only how notation is *drawn*: it
touches nothing about the graph, which is the line `bp/ui` is not allowed to
cross. `\newcommand`, `\renewcommand`, `\providecommand`, `\DeclareMathOperator`
(starred or not) and `\def` are handled, with arguments and nested braces.

**Known gap.** KaTeX has no optional-argument default, so
`\newcommand{\f}[2][x]{…}` loses the default. Documented in `GUIDE.md`.

---

## D041 — The decomposer judges difficulty before decomposing, and may decline

**Date** 2026-07-29 · **Milestone** L3 (friction log)

Reported: a simple problem cost a long `max`-effort decomposition. The decomposer
was never asked whether the node deserved splitting — only to split it.

**Decision.** `Decomposition` gains a `verdict`: `decompose`,
`prove-directly`, or `already-atomic`, with an `assessed_difficulty` and a short
`assessment`. On a decline nothing is written, the assessment is kept as a note,
and the user is offered *Write the proof* or *Decompose anyway*. A pydantic
validator ties the shape to the verdict: `decompose` requires 3–7 children and a
reduction; the others require neither.

**Why report rather than auto-prove** (the user's choice, offered as an
alternative): auto-proving bypasses the prover's `routine`/`standard` guard and
lets one model call decide both that a node needs no structure *and* what its
proof is. Reporting costs one cheap round trip and keeps the structural decision
with the mathematician.

**Note on `--force`.** Overruling the verdict changes the *prompt* — the model is
told the user has overruled it — rather than skipping the check. The first
implementation skipped the check, and a model that declined anyway produced an
empty decomposition that was silently applied.

---

## D042 — Saving a statement runs a proof-reader, and shows the rewrite first

**Date** 2026-07-29 · **Milestone** L3 (friction log)

**Decision.** `POST /api/tidy` proposes a syntax-only correction. It writes
nothing. The browser shows the rewrite beside the original with a one-line reason
per change, plus a typeset preview, and the author picks. A proof-reader that
cannot run never blocks the save.

**The constraint that makes it acceptable.** The prompt forbids touching the
mathematics — not an index, not a quantifier, not the direction of an inequality
— and requires that anything it thinks is mathematically wrong go into
`concerns`, unchanged. Combined with showing the diff before writing, an agent
never silently edits a mathematician's theorem, which is the same rule that keeps
it away from `global_status`.

**Why the `checker` role rather than a sixth role.** It is already a strong model
in every configuration, and this is a small frequent call. Splitting it out is a
one-line change in `bp/roles/tidy.py` when someone wants it cheaper.
