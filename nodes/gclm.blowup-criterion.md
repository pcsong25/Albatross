---
id: gclm.blowup-criterion
role: lemma
children: []
strategy: null
difficulty: routine
lifecycle: active
local_status: flagged
flags:
  - kind: counterexample
    section: statement
    quote: and $z(t) \to \infty$ as $t \to T^-$.
    why: 'The final step is a genuine non-sequitur: the inequality $1/z(t) \le 1/z(0) - \kappa t$ only forces $1/z(t) \to 0$ when $T = 1/(\kappa z(0))$, and since $T \in (0,\infty]$ is an arbitrary interval endpoint rather than the maximal existence time, the blowup conclusion fails outright for $\kappa = 1$, $T = 1/2$, $z(t) = 1/(1-t)$, where $z(t) \to 2$.'
    raised_by: verifier_a:opus
  - kind: non-sequitur
    section: proof
    quote: Letting $t \to T^-$ in the displayed inequality gives $1/z(t) \to 0$, so $z(t) \to \infty$.
    why: 'The final step needs $T$ to be maximal, which is nowhere assumed: with $\kappa = 1$, $z(t) = 1/(1-t)$ on $[0, T)$ with $T = 1/2$ all hypotheses hold and $T \le 1/(\kappa z(0)) = 1$, yet $z(t) \to 2$, so the asserted $z(t) \to \infty$ as $t \to T^-$ is false as stated and the inequality $1/z(t) \le 1/z(0) - \kappa t$ only forces $1/z(t) \to 0$ when $T = 1/(\kappa z(0))$.'
    raised_by: verifier_a:opus
  - kind: counterexample
    section: statement
    quote: and $z(t) \to \infty$ as $t \to T^-.$
    why: 'The conclusion $z(t) \to \infty$ as $t \to T^-$ does not follow, because $T$ is not assumed maximal: the integrated inequality only gives $1/z(t) \le 1/z(0) - \kappa t$, whose right-hand side tends to $1/z(0) - \kappa T > 0$ unless $T = 1/(\kappa z(0))$, and the admissible datum $\kappa = 1$, $T = 1/2$, $z(t) = 1/(1-t)$ satisfies every hypothesis while $z$ stays bounded by $2$.'
    raised_by: verifier_b:default
  - kind: unjustified-limit
    section: proof
    quote: Letting $t \to T^-$ in the displayed inequality gives $1/z(t) \to 0$, so $z(t) \to \infty$.
    why: 'The blow-up conclusion needs $T$ to be the maximal existence time, equivalently $T = 1/(\kappa z(0))$, and nothing in the hypotheses forces that: $\kappa = 1$, $z(t) = 1/(1-t)$ on $[0, T)$ with $T = 1/2$ satisfies H1 and H2 yet $z(t) \to 2$, so the final step of the proof — and the corresponding clause of the statement — is false as written.'
    raised_by: verifier_b:default

hypotheses:
  - {id: H1, tex: "z \\in C^1([0,T)) \\text{ and } z(0) > 0"}
  - {id: H2, tex: "z'(t) \\ge \\kappa\\, z(t)^2 \\text{ on } [0,T), \\ \\kappa > 0"}

uses: {}
# --- computed fields: written by `bp sweep`. Never edit them, and never let an agent write them. ---
global_status: blocked:stale
support: []
blocked_by: []
statement_hash: '896e63762324'
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
  T \ \le \ \frac{1}{\kappa\, z(0)},
\]
and $z(t) \to \infty$ as $t \to T^-$.

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
