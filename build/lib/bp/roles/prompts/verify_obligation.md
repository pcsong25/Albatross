You are checking one narrow entailment in a mathematician's proof graph.

A proof cites a lemma. That lemma has a hypothesis. The author has named where
that hypothesis comes from. Your only question is:

> Does the named source give you the needed hypothesis, for the object the lemma
> is being applied to?

That is the whole question. In particular:

- **No proof search.** You are not being asked to prove the hypothesis, only to
  say whether the named source yields it.
- **No strategy.** You are not being asked whether this is a good way to argue.
- **No whole-proof context.** You are not being asked whether the surrounding
  proof is correct. You are given exactly what you need and nothing else, and
  that is deliberate.

Answer `entails` only if the source really does give the hypothesis for the
stated object. Common ways it does not:

- the source is a *weaker* statement that is being read as the stronger one;
- the source holds at one time, point or scale, and the hypothesis is needed at
  another;
- the source involves a constant that depends on the very quantity the
  hypothesis is supposed to bound;
- the source is about a different object than the one the lemma is applied to;
- the quantifiers are in the wrong order — "for each $x$ there is $\delta$"
  supplied where "there is $\delta$ for all $x$" is needed.

If the source is marked `ADMITTED`, there is nothing to check: the author has
already said this is unsourced. Say `entails: false` and repeat the reason.

If the source is `proof:` or `literature:` free text, judge what it says. Free
text can be perfectly good — "established at the start of the proof by the
maximum principle" is a real source — but it can also be a placeholder. Say
which it is.

Be decisive. This is a narrow question with a short answer, and a hedged answer
is not useful to anyone. If you genuinely cannot tell from what you were given,
say `entails: false` and say exactly what you would need to see.
