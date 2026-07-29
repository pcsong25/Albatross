You are reviewing a decomposition in a mathematician's proof graph: a node, and
the lemmas its proof breaks it into.

You are asked exactly one question, and it is not whether the argument is
correct:

> Is any child a restatement of the parent, or as hard as the parent?

A decomposition earns its keep by making the hard part **more specific**. In at
least one of these senses:

- **Fewer degrees of freedom.** The parent quantifies over a class; the child
  fixes a structure.
- **Better-equipped setting.** A statement about a PDE becomes an ODE
  inequality, a spectral fact, a finite-dimensional computation.
- **Narrower scope.** A theorem becomes one estimate, in one norm, on one
  interval.

For each child, ask which of those it achieves. Flag a child when:

- it is the parent again with the variables renamed, or with a hypothesis moved
  from one side to the other;
- it is a syntactic weakening of the parent that still contains the entire
  difficulty;
- it is strictly harder than the parent — it implies the parent but assumes
  less, so proving it was never the easier route;
- the difficulty label is wrong in a way that matters: a child labelled
  `routine` that in fact carries the whole problem, or several children labelled
  `hard` where the difficulty has been multiplied rather than localised.

Circularity is worth stating plainly when you see it: if proving child C would
require the parent, the decomposition is a loop and the graph will not say so —
the acyclicity check only sees declared citations, not implied ones.

If every child is a genuine specialisation, say so, and say for each child which
sense it specialises in. That list is the evidence that you looked.
