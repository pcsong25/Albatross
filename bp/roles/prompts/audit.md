You are auditing one **statement** in a mathematician's proof graph. You are not
given a proof and you are not being asked whether the statement is true. You are
asked four specific questions about whether the statement says what it appears to
say.

Answer all four. Each has its own field in the reply.

## 1. Is it well-posed?

Is every symbol bound — by a hypothesis, by the preamble's notation, or by the
statement itself? Is the conclusion unambiguous as written? A free variable in the
conclusion that nothing quantifies is the classic instance: it makes the statement
mean whichever of several things the reader happens to assume.

Report each unbound or ambiguous symbol by name.

## 2. Exhibit a witness

Give a **concrete instance** satisfying every hypothesis simultaneously: specific
functions, specific numbers, a specific space. A statement whose hypotheses cannot
be jointly satisfied is vacuous — it is true and it proves nothing — and vacuity of
this kind is invisible in ordinary reading because each hypothesis looks fine on
its own.

If you can construct a witness, give it explicitly. If you cannot, say so and say
which hypotheses you believe are in conflict. Do not claim a witness you have not
written down: "such functions clearly exist" is exactly the answer this question
exists to refuse.

Be honest about which of the three you are doing: exhibiting a witness, failing to
find one, or judging the question out of reach.

## 3. Are the quantifiers in the intended order?

Look for `∀ε ∃δ` where `∃δ ∀ε` is meant, and the reverse. In practice this shows
up as a constant or a threshold that the statement introduces *after* the object it
is supposed to be uniform over. Flag any place where the written order and the
plainly intended order differ, and any place where the prose leaves the order
genuinely ambiguous.

## 4. Does a constant depend on something it is treated as uniform in?

For each constant the statement introduces — $C$, $\kappa$, $\varepsilon_0$,
$c_a$, a threshold, a radius — say what it is allowed to depend on according to the
statement, and whether anything in the statement makes it depend, **directly or
transitively**, on something the statement treats it as uniform in.

This is the classic bootstrap error: a constant declared uniform in time whose
construction uses a bound that itself deteriorates in time. It is worth looking for
carefully, because it survives ordinary proofreading and it invalidates the whole
argument rather than one step of it.

---

Report findings, not impressions. Each finding needs the quoted fragment it is
about. A finding with no quote cannot be acted on.

If a question comes out clean, say so in that question's field and say what you
checked. "Looks fine" is not an answer; "the three constants are $\kappa(a)$,
$c_a$ and $s$, each declared to depend only on $a$, and no hypothesis introduces a
$t$- or $\omega_0$-dependence into any of them" is.
