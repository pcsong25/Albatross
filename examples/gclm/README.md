# The gCLM example — illustrative, and **not verified mathematics**

> ⚠️ **Read this before reading the nodes.** This is a **test fixture**. It is not a
> research result, it is not anybody's paper, and its mathematics has never been checked
> by a mathematician. Several statements are probably wrong. Some are *deliberately*
> wrong.

It exists so that the deterministic core has something realistic to be tested against,
and so that a new reader can see what a project looks like without having to build one.

## What it is

A ten-node development of a finite-time blowup claim for the generalised
Constantin–Lax–Majda equation

$$\partial_t \omega + a\,u\,\partial_x \omega = u_x\,\omega, \qquad u_x = H\omega,$$

on the circle, for $0 < a < 1/2$. The shape of the argument — reduce to a scalar Riccati
inequality at a stagnation point — is a real strategy from the literature. The details
here are illustrative.

## Where it came from, exactly

| Nodes | Origin |
|---|---|
| `gclm.blowup`, `gclm.energy-lower-bound`, `gclm.elb-a`, `gclm.elb-b`, `gclm.local-existence`, `gclm.blowup-criterion` | Written by Claude as the **L0 acceptance fixture** (`47587f3`). Real-looking mathematics rather than filler, because the renderer's output was the acceptance gate and filler would not have exposed anything. It did in fact expose the YAML-float hash bug on the first run. |
| `gclm.critical-scale-domination`, `gclm.high-frequency-obstruction`, `gclm.one-scale-hilbert-coercivity` | Produced by the **decomposer agent** during the L1 acceptance run (`9a32f8f`). |
| `gclm.hilbert-kernel-split` | Produced during the **L2 acceptance session** (`bc27583`). |

So: about half of it was written by a language model asked to write plausible
mathematics, and the other half by a language model asked to decompose it. Treat every
statement in here accordingly.

## The errors are the point

`bp check` reports **two errors** on this fixture, and both are deliberate:

| | |
|---|---|
| `DIS011` on `gclm.blowup` | one hypothesis of `gclm.blowup-criterion` is left undischarged. The node file says so in a comment. |
| `LED001` on `gclm.blowup` | claim `c4` — that $z$ is well defined and $C^1$ — has no source. It is the exact step both verifiers objected to in prose, found deterministically. |

It also contains, by design: a proved leaf, an admitted node, a verified node carrying an
`ADMITTED` discharge, a node left stale by an edit made after it was verified, an
unverified node with a proof, and both shapes of verification record — one at `quick`
and one at `deep`, so the difference is visible in the rendered document.

If you "fix" these, several tests fail. They are asserted.

## Using it

```bash
cd examples/gclm
bp status          # one line per node
bp check           # the two deliberate errors
bp why             # why the target is not proved, in English
bp labels          # every \label and every reference to one
bp render --pdf    # the document, with every gap marked
bp show gclm.elb-a # a node in full, including its verification record
```

All of the above are deterministic: no API key, no network, no model calls.

`.bp/agent/` holds the 38 calls the L1 and L2 acceptance runs actually made, which is
worth reading — it is the exact prompt and the exact reply for every model call that
produced part of this fixture:

```bash
bp calls                     # a summary by role
bp calls --show <hash>       # one call in full: what was asked, what came back
bp events                    # every mutation, with its actor
```

**`--replay` will mostly miss on these now.** The log is keyed on a hash of the prompt,
and the prompts have since changed — the verifier is given cross-reference context, the
decomposer is told about the circularity rule, and so on. A miss is a loud
`ReplayMiss` rather than a silent fall-through to the network, which is the intended
behaviour: a replay run that quietly reached a provider would stop being either free or
reproducible.

`bp.yaml` here is the configuration those runs actually used — every role on GPT-5.6 Sol
through the Codex CLI. It is a worked example of pointing the whole system at one
subscription CLI; it is not a recommendation, and in particular it puts both verifiers on
the same model family, which the file itself warns against.

## Why it is not in the repository root

It used to be, and that was a mistake: `bp ui` from the root opened this fixture as
though it were a live project, and a fresh clone looked like it shipped somebody's
half-finished paper. The root is no longer a project, so `bp` run there reports that it
cannot find one — which is correct.
