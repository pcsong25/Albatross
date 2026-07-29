# LIGHT.md — Blueprint v0, build brief for Claude Code

A deliberately light version of the system described in `DESIGN.md`. Build **this**, not
that. `DESIGN.md` is retained as the reference for deferred features; `UPGRADE.md` (which
you will write) maps each deferral back to it.

Target: usable on live research in about three weeks.

---

## What v0 is

An interactive proof-decomposition assistant. Agents propose decompositions, check them,
verify proofs, and generate proofs for easy nodes. The user drives everything through a web
UI. A deterministic core keeps the graph's bookkeeping honest and renders the whole thing to
LaTeX.

**What is deliberately absent** (all in `DESIGN.md`, all recoverable later): binders and
substitution maps, numbered proof steps with typed justifications, constant tables, vacuity
witnesses, numeric falsification sweeps, LaTeX normalization, the strategy slot library, Lean
integration, the rest of the check catalog.

Statement bodies and proofs stay **free LaTeX prose**. The one exception is that statements
list their hypotheses and reductions carry a discharge table — see non-negotiable 5.

**What is not negotiable**, because it costs almost nothing and the system is worthless
without it:

1. **Global status is computed, never written by an agent.** `local_status` is an agent's or
   the user's opinion about one node. `global_status` is derived by a deterministic sweep. If
   an agent could write global status, the graph's colours would be opinions and the whole
   value proposition — glance at it, know where you are — evaporates.
2. **The LaTeX document is rendered from the node files, never maintained by an agent.** An
   agent-maintained document *will* drift from the graph, and since the document is what the
   user reads, they would be reading a plausible fiction of their own proof. Deterministic
   template, regenerated on demand.
3. **Nothing is destroyed.** Redo archives, delete archives. `events.jsonl` is append-only.
4. **Stable node ids, statement hashing, and separate local/global status fields**, because
   these are the things that are painful to retrofit.
5. **Every cited child's hypotheses are discharged explicitly.** A decomposition is not
   complete until each hypothesis of each child names where it comes from. This is the only
   substantive structure v0 retains from the full schema, and it is retained because it is the
   single highest-value check: it turns "the children do not actually cover the parent" from an
   invisible failure into a hard error. See the discharge check below.

---

## Living documentation — a standing requirement

The user needs to be able to extend this later without re-deriving it. Maintain four files
at the repo root. **Updating them is part of every milestone's acceptance criteria** — a
milestone with working code and stale docs is not complete.

| File | Content | Update cadence |
|---|---|---|
| `ARCHITECTURE.md` | Current state of the system: every module and what it does, the data flow, the node format with every field explained, the status semantics with the exact propagation algorithm, the agent roles with their prompts' purposes, the API surface. Written for someone who has never seen the code. | Rewrite the affected sections at the end of each milestone |
| `BUILD_LOG.md` | Append-only. One entry per milestone: date, what was built, files added, what the acceptance run showed, what surprised you, what you deferred and why. | Append at each milestone |
| `DECISIONS.md` | Append-only, ADR-style. One entry per non-obvious choice: the decision, the alternatives, why this one, and what would have to change to reverse it. | Append whenever you decide something the brief did not specify |
| `UPGRADE.md` | The bridge back to `DESIGN.md`. One row per deferred feature: what it is, which `DESIGN.md` section specifies it, which v0 modules it would touch, rough effort, and what signal indicates it is now needed. | Write in L0, extend as you go |

Also write `CLAUDE.md` in L0 for your own context: the four non-negotiables above, the repo
layout, the stack, and a "mistakes I have made in this repo" section you extend as you go.

Write these in prose a mathematician can read. Avoid generated-looking API dumps.

---

## Working agreements

- One milestone at a time. Run the acceptance checks, update the docs, commit, **stop and
  report**. Do not start the next milestone unprompted.
- Respect each milestone's *do not build* list.
- If a design question is not answered here, pick the simplest option consistent with the
  four non-negotiables, record it in `DECISIONS.md`, and flag it in your report. Do not
  silently invent behaviour.
- Every model call goes through `bp/agents/`. No SDK or `subprocess` model calls anywhere
  else.
- Never write a computed field into a node file by hand or from an agent response.
- Small commits with real messages.

**Stack.** Python 3.12. `pydantic>=2`, `python-frontmatter`, `ruamel.yaml`, `networkx`,
`jinja2`, `typer`, `rich`, `fastapi`, `uvicorn`, `watchfiles`, `pytest`, `anthropic`,
`openai`. Front end: **vanilla JS, no build step, no npm** — Cytoscape.js and KaTeX from a
CDN or vendored. The user is a mathematician who will need to maintain this; a webpack
config is a liability.

---

## Node format

One markdown file per node under `nodes/`, YAML frontmatter plus LaTeX body. Prose-heavy and
hand-editable by design.

```markdown
---
id: mff.energy-lower-bound
role: lemma                # lemma | proposition | theorem | definition | assumption
children: [mff.elb-a, mff.elb-b]
strategy: null             # free-text hint, e.g. "bootstrap on the L-infinity norm"
difficulty: hard           # standard | routine | hard | unknown
lifecycle: active          # active | archived
local_status: unverified   # unverified | verified | flagged | admitted | assumption
flags: []                  # objection records, written by the verifier

# hypotheses of THIS node's statement, referenced by parents that cite it
hypotheses:
  - {id: H1, tex: "s > 3/2"}
  - {id: H2, tex: "\\|\\omega_0\\|_{H^s} \\le \\varepsilon_0"}

# for each child cited in the proof, where each of ITS hypotheses comes from
uses:
  mff.elb-a:
    applied_to: "\\omega(t) \\text{ for } t \\in [0,T)"   # free text, not checked
    discharges:
      H1: "hypothesis:H1"          # a hypothesis of THIS node
      H2: "child:mff.elb-b"        # the conclusion of a sibling
  mff.elb-b:
    applied_to: "\\omega_0"
    discharges:
      H1: "hypothesis:H1"
      H2: "ADMITTED: needs a continuation argument not yet written"

# --- computed fields: never edit, never let an agent write these ---
global_status: blocked
support: [mff.elb-b]
statement_hash: 3f2a9c…
verified_against: {self: 3f2a9c…, mff.elb-a: 9c1b…, mff.elb-b: 77de…}
stale: false
---

## Statement

Let $\omega_0 \in H^s(\mathbb{S}^1)$ with $s > 3/2$ be odd…

## Proof

Assuming `mff.elb-a` and `mff.elb-b`, we argue as follows…

## Notes

Free prose. Strategy hints, dead ends, references. Fed to agents as context.
```

**The graph is a DAG, not a tree.** Edges come from `children` only; there is no `parent`
field, because a node may be cited by several parents and a stored parent would go
inconsistent. Compute parents when needed.

Proofs cite children by id in the prose. That is how the children-used check works.

---

## The deterministic core — exact specifications

Do not improvise these. They are short and they must be right.

### Integrity (`bp/graph.py`)

- every id in `children` resolves to an existing active node
- the `children` relation is acyclic; on failure report the **full cycle**
- no node lists one of its own ancestors as a child
- warn on: active node with no parent and not the target; node with `children` but
  `local_status: verified` and no child mentioned in the proof

### Children-used check (`bp/checks.py`)

For each id in `children`, the id string must appear in the Proof section. Warn if not.
Catches "declared a lemma, never used it", which is a real and common decomposition failure.

### Discharge check (`bp/discharge.py`) — the most valuable check in v0

When a proof invokes a child lemma, that lemma has hypotheses, and they must hold where it is
invoked. This check verifies that a **source is named** for each one. It does *not* verify
that the named source entails the hypothesis — that question is handed to the verifier agent
(see obligation emission below). Catching omission is what matters, and omission is the
common failure.

```python
SOURCE_RE = re.compile(r"^(hypothesis|child|proof|literature|ADMITTED)(:(.*))?$")

def check_discharge(node, graph) -> list[Diagnostic]:
    d = []
    own_hyps = {h.id for h in node.hypotheses}

    for cid in node.children:
        entry = node.uses.get(cid)
        if entry is None:
            d.append(err("DIS010", node,
                f"child {cid} is cited but has no `uses` entry",
                hint="add uses.%s.discharges naming a source for each of its hypotheses" % cid))
            continue

        child = graph[cid]
        for h in child.hypotheses:
            src = entry.discharges.get(h.id)
            if not src:
                d.append(err("DIS011", node,
                    f"{cid} hypothesis {h.id} ({h.tex}) is not discharged",
                    hint="name where this hypothesis comes from, or mark it ADMITTED"))
                continue

            m = SOURCE_RE.match(src.strip())
            if not m:
                d.append(err("DIS012", node,
                    f"{cid}.{h.id}: source {src!r} is not a recognised form",
                    hint="use hypothesis:<id> | child:<id> | proof:<free text> | "
                         "literature:<ref> | ADMITTED: <reason>"))
                continue

            kind, _, arg = m.groups()
            if kind == "hypothesis" and arg not in own_hyps:
                d.append(err("DIS013", node,
                    f"{cid}.{h.id}: {node.id} has no hypothesis {arg!r}"))
            elif kind == "child" and arg not in node.children:
                d.append(err("DIS014", node,
                    f"{cid}.{h.id}: {arg!r} is not a declared child of {node.id}",
                    hint="add it to `children`, or discharge from something in scope"))
            elif kind == "ADMITTED" and not (arg or "").strip():
                d.append(err("DIS015", node, f"{cid}.{h.id}: ADMITTED needs a reason"))

    for cid in node.uses:
        if cid not in node.children:
            d.append(warn("DIS016", node, f"`uses` mentions {cid}, which is not a child"))
    return d
```

`proof:` and `literature:` sources take free text and are not structurally checked — they
exist so that a hypothesis established inline in the prose, or cited from the literature, has
an honest label rather than being silently omitted.

An `ADMITTED` discharge makes the parent's `local_status` at best `admitted`, and its id
enters the support set. A hypothesis you cannot source is visible debt, not a hidden gap.

### Obligation emission (`bp/discharge.py`)

The `uses` table is an obligation list. `bp obligations <node>` emits one record per
discharge:

```json
{ "id": "ob:mff.energy-lower-bound:mff.elb-a:H2",
  "parent": "mff.energy-lower-bound",
  "child": "mff.elb-a",
  "applied_to": "\\omega(t) \\text{ for } t \\in [0,T)",
  "needed": "\\|\\omega_0\\|_{H^s} \\le \\varepsilon_0",
  "claimed_source": "child:mff.elb-b",
  "source_text": "<statement of mff.elb-b>",
  "hash": "…" }
```

The verifier consumes these **one at a time** instead of judging a whole proof. This is a
quality improvement in verification, not merely an extra check: the questions are narrow, and
the list is generated deterministically so nothing is skipped because a model failed to
notice it needed checking.

Cache verifier results on `hash`, so editing one part of a proof does not re-bill the rest.

### Statement hashing (`bp/hash.py`)

```python
def statement_hash(node) -> str:
    s = node.statement_section
    s = re.sub(r"%.*$", "", s, flags=re.M)      # strip LaTeX comments
    s = re.sub(r"\s+", " ", s).strip()          # collapse whitespace
    return hashlib.sha256(s.encode()).hexdigest()[:12]
```

Raw text, whitespace-collapsed only. No normalization in v0 — that is a deferred upgrade,
and hashing raw text errs toward over-invalidation, which is the safe direction.

### Staleness

```python
def is_stale(node, graph) -> bool:
    va = node.verified_against
    if not va: return False                      # never verified, not stale
    if va.get("self") != node.statement_hash: return True
    return any(va.get(c) != graph[c].statement_hash for c in node.children)
```

`verified_against` is written **only** when a verification succeeds, and records `self` plus
every child's hash at that moment.

### Status propagation (`bp/propagate.py`)

One topological sweep after every mutation. `global_status` and `support` are outputs.

```
for N in reverse_topological_order(active nodes):

    if is_stale(N):                    N.global = "blocked:stale";      N.support = []
    elif N.local == "flagged":         N.global = "blocked:objection";  N.support = []
    elif N.local == "admitted":        N.global = "proved_modulo";      N.support = [N.id]
    elif N.local == "assumption":      N.global = "proved_modulo";      N.support = [N.id]
    elif N.local == "unverified":
        N.global = "blocked:unverified" if N.has_proof else "open"
        N.support = []
    elif N.local == "verified":
        kids = [graph[c] for c in N.children]
        if any(k.global == "unsound" for k in kids):
            N.global = "unsound"; N.support = []
        elif any(k.global.startswith(("open", "blocked")) for k in kids):
            N.global = "blocked:children"; N.support = []
            N.blocked_by = [k.id for k in kids if k.global.startswith(("open","blocked"))]
        else:
            N.support = sorted(set().union(*[set(k.support) for k in kids] or [set()]))
            N.global = "proved" if not N.support else "proved_modulo"
```

Assert after every sweep: `global == "proved"` implies `support == []`; no node is `proved`
while any descendant is not `proved` or `proved_modulo`. These assertions are the test suite.

### `bp why <node>`

Walk `blocked_by` transitively and print the chain in plain language: *"`mff.main` is
blocked by `mff.elb-a` (unverified) and `mff.elb-b` (stale: its statement changed after
verification)."* No model involved, always correct. Build it in L0 — this is what makes the
user trust the colours.

### LaTeX renderer (`bp/render.py`)

Jinja2 template, topological order, deterministic. Emits a compilable document:
preamble, then for each node a `\begin{lemma}[id]…\end{lemma}` with the proof beneath, then
the target theorem last. Requirements:

- unproved nodes get a visible marker (a margin note or a coloured box), never silent
- admitted nodes and assumptions render as a boxed statement labelled as an assumption
- the support certificate goes at the top: *"Theorem X holds relative to the following N
  items"*, listing them
- `bp render --clean` omits markers, for when everything is proved and this becomes the
  paper

---

## Agent layer (`bp/agents/`)

Role-based indirection. Both subscription CLI tools and metered APIs, configured, not
hardcoded.

```yaml
# bp.yaml
agents:
  roles:
    decomposer: {backend: codex_cli,     model: gpt-5.6-sol}
    checker:    {backend: claude_api,    model: claude-opus-5}
    verifier_a: {backend: claude_cli,    model: opus}
    verifier_b: {backend: openai_api,    model: gpt-5.6}
    prover:     {backend: claude_cli,    model: sonnet}
budget:
  per_recompile_usd: 3.0
  max_calls_per_recompile: 40
```

- `base.py` — one method: `complete(system, user, schema, timeout) -> (model, CallMeta)`.
  Every prompt requests JSON; validate with pydantic; on failure retry **once** with the
  validation error appended; then fail the task. Never guess.
- `claude_cli.py`, `codex_cli.py` — subprocess in headless/print mode. Write the prompt to a
  temp file (prompts exceed argv limits); capture stdout; **extract the JSON block**, since
  CLI tools emit preamble; enforce timeout and kill the process group on expiry.
  `cost_usd = None`, record wall time instead.
- Budget logic must tolerate `cost_usd is None` and fall back to the call-count cap. Test
  this explicitly.
- `log.py` — every call logged to `.bp/agent/<prompt_hash>.json`. `--replay` resolves from
  the log instead of the network, erroring loudly on a miss. This makes tests free and lets
  the user work offline.

### The four roles

**Decomposer.** One level only. 3–7 children, each "a section or a major lemma". Tell it
explicitly that leaves at this stage are *expected* to be hard and unproved and that it must
not attempt provable granularity — without this it goes four levels deep in one call and the
user spends their time pruning. Requires a difficulty label per child, so difficulty
concentration is visible. Accepts an optional free-text strategy hint from the user and any
`Notes` on the node.

Returns, per child: statement prose, difficulty, **and an explicit `hypotheses` list**. Plus
a reduction proof for the parent **and a complete `uses` table** naming a source for every
hypothesis of every child. This is the most demanding part of the schema and where most of
your prompt iteration will go; budget for it. If the model cannot source a hypothesis it must
write `ADMITTED: <reason>` rather than omitting the entry — say so explicitly in the prompt,
with an example.

Expect the discharge check to reject a substantial fraction of first attempts. That is the
mechanism working: a decomposition that cannot fill its own `uses` table is a decomposition
whose children do not cover the parent. Feed the diagnostics back and allow two repair rounds
before surfacing to the user.

**Checker.** Two **separate** calls, not one. Each must return a specific located problem or
an explicit "none found, having checked the following":

1. *Assuming every child is true, does the reduction establish the parent?* Name the missing
   child or the step that does not follow.
2. *Is any child a restatement of the parent, or as hard as the parent?*

The third question from the earlier draft — are the needed hypotheses available — is now
handled by the discharge check plus obligation verification, deterministically for
completeness and per-obligation for entailment. Do not also ask it here.

**Verifier.** Two jobs, kept separate.

*Obligation checking.* Consume `bp obligations <node>` one record at a time: does
`source_text` give you `needed`, for the object in `applied_to`? No proof search, no strategy,
no whole-proof context. Narrow questions are where model judgement is most reliable, and the
list is complete by construction.

*Whole-proof pass.* Given the statement, the proof, and the children's statements **as
assumptions**, either produce a located objection `{section, quote, class, why}` or
`no_objection` naming what was checked. Two backends from different families, no shared
context.

Then a **confirmation pass** over every objection from either job: re-present it with
surrounding context; if the flaw dissolves, downgrade it to a note. Skipping confirmation
produces so much pedantic noise that the user stops reading the output.

**Prover.** For `routine` and `standard` leaves only. Writes a proof into the node. Never
sets `local_status` — the verifier does that.

### Recompile

`bp recompile` verifies only stale and unverified nodes, then sweeps. `--dry-run` lists the
calls it would make and the estimated cost. Results write as they land, so an interrupted
run keeps its progress. Job record in `.bp/jobs/` with completed task ids; `bp resume`
skips them.

---

## Milestones

### L0 — Deterministic core, no agents

**Build.** Node model and frontmatter loader; `bp/graph.py` (integrity, topo order, cycle
reporting); `bp/hash.py`; `bp/propagate.py` with its assertions; `bp/checks.py`
(children-used); **`bp/discharge.py` (`DIS010`–`DIS016` plus obligation emission)**;
`bp/render.py` plus the Jinja template; `bp/events.py` (append-only JSONL,
UUID per event, fsync per append); `bp/ops.py` (every mutation goes through here:
`add_node`, `edit_statement`, `edit_proof`, `set_children`, `set_uses`, `archive`, `admit`,
`set_assumption`, `relabel`, `add_note`); atomic writes via tmp + `os.replace`; `bp/cli.py`
with `show`, `graph`, `render`, `status`, `why`, `check`, `obligations`.

Write `CLAUDE.md`, `ARCHITECTURE.md`, `UPGRADE.md`, `DECISIONS.md`, `BUILD_LOG.md`.

**Do not build.** Anything that calls a model. Any UI.

**Acceptance.** Hand-write a 6-node DAG in `nodes/` with a mix of statuses including one
admitted node, one deliberately stale node, one node with a **missing discharge**, and one
with an `ADMITTED` discharge. Then:

```
bp check          # integrity clean; children-used and DIS010-016 fire exactly as intended
bp obligations    # one record per discharge, stable hashes
bp status         # global statuses correct by hand-inspection
bp why <target>   # chain reads as plain, correct English
bp render         # produces LaTeX that compiles and that a mathematician would read
pytest -q         # propagation assertions hold on random graphs
```

The renderer output is the real gate. If it does not read like a paper, fix it now — the
user will spend more time in that document than anywhere else.

### L1 — Agents

**Build.** `bp/agents/` per the spec above: `base.py`, `registry.py`, `log.py`,
`claude_api.py`, `openai_api.py`, `claude_cli.py`, `codex_cli.py`. Then
`bp/roles/decompose.py`, `check.py`, `verify.py`, `prove.py`, each with its prompt in a
separate `prompts/*.md` file so the user can edit prompts without touching code. Then
`bp/recompile.py` with `--dry-run`, budget caps, job records and `bp resume`.

CLI: `bp expand <node> [--hint "..."]`, `bp redo <node>`, `bp check-decomp <node>`,
`bp verify <node>`, `bp prove <node>`, `bp recompile [--dry-run]`, `bp resume`.

`bp redo` writes the current subtree to `attempts/<node>-<n>/` before regenerating.

**Do not build.** UI.

**Acceptance.** On a real target supplied by the user: `bp expand` produces 3–7 children with
difficulty labels; `bp check-decomp` returns located problems or explicit none-found;
`bp render` shows the result. Kill a recompile mid-run and confirm `bp resume` re-queries
nothing already done, verified from the agent log. Confirm `--replay` works with no network.

### L2 — Web UI

This is the intended daily interface. The L0 CLI is a testing scaffold, not the product.

**Build.** `bp/ui/app.py` (FastAPI) plus `bp/ui/static/`. Every endpoint calls an existing
`ops.py` or role function; the UI contains no logic of its own.

Layout: graph panel left, detail panel right, action bar on top.

**Graph panel.** Cytoscape.js, hierarchical layout. Node fill encodes `global_status`:
green `proved`, blue-green `proved_modulo`, amber `blocked`, grey `open`, red `unsound`.
Dashed border for `stale`, thicker border for `flagged`. Click selects; the chevron on a node
collapses its subtree in the **view only**, with zero graph mutation. Legend always visible.

**Detail panel** for the selected node. Statement and proof rendered with KaTeX — rendered
mathematics, never raw source, though an "edit" toggle swaps in a textarea of the LaTeX.
Status line with `support` and `blocked_by` spelled out. Notes. Then buttons:

| Button | Action |
|---|---|
| Expand | decompose one level; opens a hint textarea first, prefilled with the node's `strategy` |
| Redo | archive current subtree, decompose again; hint textarea prefilled with the previous attempt's problems |
| Generate proof | prover role |
| Verify | verifier panel on this node |
| Check decomposition | the three checker calls |
| Edit statement | inline LaTeX textarea; on save, warn which descendants will go stale **before** committing |
| Edit proof | inline LaTeX textarea |
| Add child | manual node creation, statement typed by the user |
| Add note | free prose, becomes agent context |
| Mark admitted | prompts for a reason, which is required |
| Mark assumption | same |
| Archive | archives the node and its orphaned descendants; never deletes |
| Why? | the `bp why` chain, in a panel |

**Action bar.** Recompile (with a dry-run preview dialog showing calls and cost before
confirming), Render LaTeX (opens the document; a download button), Frontier queue (nodes
awaiting a decision, ranked shallow-first then by how many nodes they gate), History (the
event log, human-readable).

**Async is mandatory.** An expand call takes 30–90 seconds. Run role calls as background
jobs, return a job id, poll for status, and show a live progress indicator naming which
agent is running. The UI must never block or appear frozen. A running job disables the
buttons that would conflict with it and leaves the rest live.

**Edits are LaTeX textareas.** The user writes mathematics as LaTeX and reads it rendered.
No rich-text editor, no WYSIWYG.

**Acceptance.** Run a full session from the browser alone, touching no CLI: expand a target,
read the check output, reject and redo with a different hint, edit a statement and observe
the staleness warning before committing, promote a child manually, mark one node admitted,
recompile, read `why` on a blocked node, open the rendered LaTeX. Then reload the page and
confirm all state persisted.

### L3 — Driven by the friction log

Do not plan this in advance. At the end of L2, ask the user for their friction list and
build against it. Likely candidates, in rough order of expected value:

- strategy library as prompt scaffolding (named schemas with expected child roles — nearly
  free, and improves decomposition quality more than anything else here)
- k-parallel decomposition under different strategies, as competing subtrees
- constant tables plus `CST001`–`CST002` (`DESIGN.md` §8) — circular constant dependency and
  uniformity violations, the next most valuable deterministic check after discharge
- numeric falsification sweeps, `NUM001`–`NUM004` (`DESIGN.md` §8)
- per-node agent-call history visible in the detail panel
- keyboard navigation

---

## Expectations to set with the user

**What the discharge check does not do.** It verifies that a source is *named* for every
hypothesis, not that the named source entails it. An agent can write
`H2: "hypothesis:H_init"` when `H_init` does not in fact give `H2`. The check passes and the
claim is false. So the check catches **omission**, not **misattribution** — and misattribution
is left as a narrow, explicit, per-obligation question for the verifier, which is a far better
position than having it buried in prose. Say this plainly in `ARCHITECTURE.md`; a user who
believes the check is stronger than it is will over-trust green nodes.

**What is still missing relative to the full design.** Without normalization, cosmetic edits
invalidate downstream verification, so expect more re-verification than necessary. Without
constant tables, circular constant dependencies and uniformity violations — the classic
bootstrap error — are invisible; that is the next check to add, `DESIGN.md` §8
`CST001`–`CST002`. Without vacuity witnesses, a lemma with unsatisfiable hypotheses looks
fine. Without numeric sweeps, sign errors and wrong constants in explicit inequalities pass.

Record each of these in `UPGRADE.md` with its `DESIGN.md` section, which v0 modules it would
touch, and the signal that indicates it is now needed.

---

## Upgrade path — preserve these five things

Everything else can be deferred safely. These are cheap now and painful later:

1. stable node ids
2. `statement_hash`, even as raw-text SHA-256 — normalization can replace the hash function
   later without touching anything else
3. `events.jsonl`
4. `local_status` and `global_status` as separate fields, with global computed
5. role-based agent config rather than hardcoded models
6. `hypotheses` and `uses` — already in v0. The full design's `substitution` map and step ids
   are additive refinements of `uses`, not replacements for it (`DESIGN.md` §3.2)

With those in place, the full design lands additively: normalization replaces the hash
function; deterministic checks slot into `recompile` as a tier that runs *below* the agents;
the structured schema becomes optional frontmatter that the checks require and v0 ignores.
State this explicitly in `UPGRADE.md`, with the `DESIGN.md` section number for each row.
