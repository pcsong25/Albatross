You are writing one section of a paper, from a machine-checked proof development.

You are given the outline the whole paper follows, the section you are responsible
for, and the full text of every node assigned to it — statement, hypotheses, proof,
and how each cited lemma is applied. Write that section the way it would appear in
a journal paper or a careful set of notes.

# What you may do — this is the point of the exercise

- **Turn hypothesis lists into sentences.** The development stores conditions as
  `(H1) s > 3/2`, `(H2) u_0 \in H^s`, because a checker reads them. A paper says
  *"Let $s > 3/2$ and let $u_0 \in H^s(\mathbb{R}^2)$ be divergence-free."* Do that.
- **Merge what should be merged.** A lemma whose proof is three lines and which is
  used once belongs inside the proof that uses it, not as a numbered statement of
  its own. Declare every node you merge in `merged`, with a note saying where it
  went.
- **Name results by what they say.** Write *"by the energy estimate
  (Lemma~\ref{paper:...})"*, never *"by `proj.energy-lower-bound`"*. Machine
  identifiers must not appear in the prose at all.
- **Add the connective tissue a paper has and a graph does not**: a sentence saying
  where the argument is going, a remark on why a hypothesis is needed, a note that
  the next lemma is where the difficulty sits.
- **Reorganise inside your section.** Statement before proof, definitions before
  the statements that use them, the calculation displayed rather than inline.

# What you may not do

- **Do not change the mathematics.** Not a constant, an index, a quantifier, an
  inequality direction, or the order of quantifiers. If a hypothesis is needed, it
  appears in your section; if a step is claimed, it is still claimed.
- **Do not prove anything the development does not prove.** If a node is admitted,
  assumed, or has no proof, you may not supply one, and you may not write prose
  that reads as though one exists. Present it as an assumption and say what it is
  used for. Each node's status is given to you.
- **Do not upgrade a conditional result.** If the development's target holds
  relative to admitted items, your section must not claim it holds outright.
- **Do not invent references to the literature.** Cite something only where the
  development already does, and keep its wording.
- **Do not write anything you cannot source in the material you were given.**

# Labels and cross-references

Every node you state as a numbered result must carry the label
`\label{paper:<node id>}` on its environment, exactly as written, and its id must
appear in `stated`:

```latex
\begin{lemma}[Energy lower bound]\label{paper:gclm.energy-lower-bound}
Let $s > 3/2$ ... then $E(t) \ge c t^{-1}$.
\end{lemma}
```

Refer to another result of the paper — including one in a different section — by
that label: `Lemma~\ref{paper:gclm.energy-lower-bound}`. Those are the only labels
you may reference, because they are the only ones anything can check. Do not invent
`\ref` or `\cite` targets, and do not use `\label` names of your own; a reference
to something that does not exist prints as `??`.

# What to return

`tex`: the body of your section only. **No `\section` heading** — that is added for
you from the outline — and no preamble, no `\documentclass`, no `\begin{document}`.
`\subsection` is yours to use if the section needs it. Use the project's own macros
where the preamble defines them.

`stated`: the ids you gave their own labelled, numbered statement.

`merged`: the ids you folded into prose, each with `where` saying what it became
("absorbed into the proof of Lemma~\ref{paper:...} as Step 2").

**Every node assigned to you must appear in `stated` or in `merged`.** A
deterministic checker compares the two lists against the assignment and rejects
the section otherwise. That check is the only guarantee anyone has that this
document did not quietly lose a lemma.

`departures`: places where your exposition differs from the development in a way a
careful reader should know about — a hypothesis restated in words rather than
symbols, two lemmas combined, a step's justification compressed.

`lost`: anything in the material you could not carry over faithfully. An empty list
is the good answer; a wrong empty list is the worst thing you can return, because
the whole document is trusted on the strength of it.
