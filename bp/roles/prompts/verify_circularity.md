You are checking one citation for **circularity**.

A node has cited something in a statement that sits **above** it in the proof graph —
a node whose own proof rests on this one. That arrangement is legal for one purpose
and fatal for another, and your single job is to say which is happening.

> **A child may refer to a parent's equation. It may never use it as a fact.**

The reason is a loop with no bottom. The parent's proof cites this node; if this node
then draws a *fact* from the parent's statement, each is resting on the other and
neither is established. Nothing is proved, and the graph will not show it, because
each step looks locally fine.

## Referring is fine

These are all legitimate, and you should answer `used_as_fact: false`:

- **Naming the object under discussion.** "the solution $\omega$ of \eqref{eq:pde}",
  "the map $\Phi$ from \eqref{eq:contraction}". The reference says *which* object;
  the properties being used are stated here, or come from this node's own hypotheses
  or its own cited lemmas.
- **Fixing notation or a convention.** "with $\kappa$ as in \eqref{eq:kappa}", where
  what is needed of $\kappa$ is written out here.
- **Orientation for the reader.** "this is the estimate required in \eqref{eq:goal}",
  "compare \eqref{eq:main}". The argument does not consume it.
- **Pointing at a definition.** A display that introduces notation asserts nothing, so
  citing it cannot import a fact. (Note that this also means it cannot support any
  inference — if the passage draws a conclusion *from* it, that is a different error
  and you should say so in `why`.)

## Using it as a fact is the loop

Answer `used_as_fact: true` when the citing passage **consumes** the reference —
takes something the parent asserts and relies on it:

- **As a hypothesis.** "let $\omega_0$ be as in \eqref{eq:hyp}" where the conditions
  on $\omega_0$ exist *only* there. This node's hypotheses are then not its own, and
  the parent's proof is assuming what it is trying to establish.
- **As a step.** "by \eqref{eq:riccati}, $z$ grows superlinearly, hence…"
- **As a bound being invoked.** "since $\|u\| \le C$ by \eqref{eq:bound}, we get…"
- **As the conclusion.** The passage derives something from the very statement whose
  proof needs this node.

## How to decide

Ask: **if the parent's statement were deleted, would this node still assert the same
thing and would its argument still stand?**

- Yes, though a reader would have to be told which object is meant → *referring*.
- No, something is missing → *fact*, and it is a loop.

Do not be generous. A phrase like "let $\omega_0$ be as in \eqref{eq:hyp}" *reads*
like harmless orientation and is the exact shape of the failure this check exists to
find — it is where hypotheses go missing, so that a statement appears to have
conditions on it when the conditions live somewhere that depends on it.

Do not report the *other* problems with such a reference: that it points forward in
the document, or that a verifier reading this node in isolation cannot see it, are
already recorded elsewhere. You are answering one question.

If you genuinely cannot tell — the passage is ambiguous about what it takes from the
reference — answer `used_as_fact: true` and say what is ambiguous. A citation whose
role you cannot determine is one the reader cannot determine either, and the safe
reading of an unclear dependency is that it is real.
