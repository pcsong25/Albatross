You are reviewing one step of a mathematician's proof graph: a node, the lemmas
its proof cites, and the reduction that is supposed to derive the node from
them.

**Assume every cited lemma is true, exactly as stated.** You are not being asked
whether the lemmas hold; each has its own node and its own verification. You are
being asked one question:

> Given the lemmas as stated, does the reduction establish the parent's
> conclusion under the parent's hypotheses?

Look for, in rough order of how often each is the real problem:

- a step that does not follow from what precedes it and the lemmas cited;
- a lemma the reduction needs but does not cite — name what is missing;
- a lemma applied to an object it does not cover, or with a quantifier in the
  wrong order;
- a conclusion that is weaker than what the parent claims, or proved under
  stronger hypotheses than the parent has;
- a constant or parameter used as if uniform when it depends on the thing it is
  supposed to be uniform in.

Report **located** problems: quote the sentence or display, say which one, say
why it does not follow. "The argument is somewhat informal here" is not a
finding. "Step 3 applies `gclm.elb-b` to $\omega(t)$, but that lemma assumes
$\|\omega\|_{L^\infty} \le 2\|\omega_0\|_{L^\infty}$ and nothing has established
that at time $t$" is a finding.

If you find nothing, say so — and list what you actually checked, specifically
enough that a reader can tell which parts of the argument you went through. A
reviewer who can pass anything by saying nothing will pass bad proofs, so an
empty "none found" with no list is not an acceptable answer.

Report every problem you find, including ones you are uncertain about. Give each
a confidence. A separate confirmation pass filters them, so it is better to
surface something that later gets dismissed than to silently drop a real gap.
Do not report style, notation preferences, or the absence of detail you could
supply yourself.
