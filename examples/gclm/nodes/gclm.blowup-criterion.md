---
id: gclm.blowup-criterion
role: lemma
children: []
strategy: null
difficulty: routine
lifecycle: active
local_status: flagged
flags:
  - kind: non-sequitur
    section: proof
    quote: Letting $t \to T^-$ in the displayed inequality gives $1/z(t) \to 0$, so $z(t) \to \infty$.
    why: The displayed inequality yields only $\limsup_{t \to T^-} 1/z(t) \le 1/z(0) - \kappa T$, which vanishes only if $T$ attains the bound the proof merely established as an inequality, and no continuation argument is supplied to rule out a bounded $z$ on a maximal finite interval — indeed for a general $C^1$ function no such argument exists, since $z(t) = 1 + t + \eta (1/2 - t)^2 \sin\!\big(1/(1/2 - t)\big)$ with $\eta$ and $\kappa$ small satisfies $z' \ge \kappa z^2$ on $[0, 1/2)$, is maximal there because $z'$ has no limit at $1/2^-$, and stays bounded.
    raised_by: verifier_a:opus
  - kind: counterexample
    section: statement
    quote: If moreover $[0,T)$ is the maximal interval on which $z$ is defined and $C^1$, then $z(t) \to \infty$ as $t \to T^-$.
    why: "The second conclusion does not follow: the proof's last step, letting $t \\to T^-$ in $1/z(t) \\le 1/z(0) - \\kappa t$, forces $1/z(t) \\to 0$ only when $T = 1/(\\kappa z(0))$, and maximality in the stated sense ($z$ admits no $C^1$ extension) does not force that, since non-extendability can come from an oscillating $z'$ instead — e.g. $\\kappa = 1$, $T = 1/100$, $z(0) = 1$, $z' = 3 + \\sin(1/(T-t))$ satisfies H1-H2, has no $C^1$ extension past $T$, yet stays below $1.04$."
    raised_by: verifier_a:opus
  - kind: unjustified-limit
    section: proof
    quote: Letting $t \to T^-$ in the displayed inequality gives $1/z(t) \to 0$, so $z(t) \to \infty$.
    why: "The final limit is a non-sequitur: the displayed inequality's right-hand side tends to $1/z(0) - \\kappa T$, which is strictly positive whenever $T < 1/(\\kappa z(0))$, so it cannot force $1/z(t) \\to 0$ — the conclusion can only come from the maximality hypothesis, which the proof never invokes (and would need an extension argument to use)."
    raised_by: verifier_b:default
  - kind: counterexample
    section: statement
    quote: If moreover $[0,T)$ is the maximal interval on which $z$ is defined and $C^1$, then $z(t) \to \infty$ as $t \to T^-.$
    why: "The blow-up clause is false as stated: maximality of the $C^1$ interval only prevents $C^1$ continuation, which can fail because $z'$ diverges while $z$ stays bounded (e.g. $\\kappa = 1/8$, $T = 1$, $z(t) = 2 - \\sqrt{1-t}$, where $z' \\ge 1/2 \\ge \\kappa z^2$ and $z \\to 2$), and the proof's last step is the same gap — $1/z(t) \\le 1/z(0) - \\kappa t$ forces $1/z(t) \\to 0$ only when $T = 1/(\\kappa z(0))$, so the conclusion needs maximality with respect to continuation of the underlying ODE rather than mere $C^1$ extendability."
    raised_by: verifier_b:default
hypotheses:
  - {id: H1, tex: "z \\in C^1([0,T)) \\text{ and } z(0) > 0"}
  - {id: H2, tex: "z'(t) \\ge \\kappa\\, z(t)^2 \\text{ on } [0,T), \\ \\kappa > 0"}

uses: {}
# --- computed fields: written by `bp sweep`. Never edit them, and never let an agent write them. ---
global_status: blocked:stale
support: []
blocked_by: []
statement_hash: '50d363cce6d9'
verified_against: {self: '0000deadbeef'}
stale: true
---

## Statement

Let $\kappa > 0$, let $T \in (0, \infty]$, and let $z \in C^1([0,T))$ satisfy
$z(0) > 0$ and
\[
  z'(t) \ \ge \ \kappa\, z(t)^2 \qquad \text{for all } t \in [0,T) .
\]
Then
\[
  T \ \le \ \frac{1}{\kappa\, z(0)} .
\]
If moreover $[0,T)$ is the maximal interval on which $z$ is defined and $C^1$,
then $z(t) \to \infty$ as $t \to T^-$.

## Proof

Since $z(0) > 0$ and $z' \ge \kappa z^2 \ge 0$, the function $z$ is
non-decreasing and therefore stays positive on $[0,T)$. Hence $w := 1/z$ is well
defined and $C^1$ there, with
\[
  w'(t) \ = \ -\frac{z'(t)}{z(t)^2} \ \le \ -\kappa .
\]
Integrating from $0$ to $t$ gives $w(t) \le w(0) - \kappa t$, that is
\[
  \frac{1}{z(t)} \ \le \ \frac{1}{z(0)} - \kappa t .
\]
The left-hand side is strictly positive for every $t \in [0,T)$, so the
right-hand side must be too, which forces $t < 1/(\kappa z(0))$ for every such
$t$ and hence $T \le 1/(\kappa z(0))$. Letting $t \to T^-$ in the displayed
inequality gives $1/z(t) \to 0$, so $z(t) \to \infty$.

## Notes

The explicit bound $T \le 1/(\kappa z(0))$ was added to the statement after this
node was verified; before that the statement only asserted $T < \infty$. The
proof already covers it, but the verification certificate is against the older
statement, so the node is stale until it is re-verified. This is exactly the
situation staleness exists to make visible.
