---
id: gclm.blowup-criterion
role: lemma
children: []
strategy: null
difficulty: routine
lifecycle: active
local_status: verified
flags: []

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
