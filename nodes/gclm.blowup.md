---
id: gclm.blowup
role: theorem
target: true
children: [gclm.local-existence, gclm.energy-lower-bound, gclm.blowup-criterion]
strategy: reduce to a scalar Riccati inequality at the origin
difficulty: hard
lifecycle: active
local_status: verified
flags: []

# hypotheses of THIS node's statement, referenced by parents that cite it
hypotheses:
  - {id: H1, tex: "0 < a < 1/2"}
  - {id: H2, tex: "\\omega_0 \\in H^s(\\mathbb{S}^1) \\text{ is odd}, \\ s > 3/2, \\ \\omega_0'(0) < 0"}

# for each child cited in the proof, where each of ITS hypotheses comes from
uses:
  gclm.local-existence:
    applied_to: "\\omega_0"
    discharges:
      H1: "hypothesis:H2"
  gclm.energy-lower-bound:
    applied_to: "\\omega(t,\\cdot) \\text{ for } t \\in [0, T_{\\max})"
    discharges:
      H1: "hypothesis:H1"
      H2: "hypothesis:H2"
      H3: "hypothesis:H2"
  gclm.blowup-criterion:
    applied_to: "z(t) = -\\partial_x \\omega(t,0)"
    discharges:
      H1: "proof:$z(0) = -\\omega_0'(0) > 0$ by H2, and $z \\in C^1([0,T_{\\max}))$ because the local solution is classical"
      # H2 is deliberately absent: DIS011 fires here, and it should.

# --- computed fields: written by `bp sweep`. Never edit them, and never let an agent write them. ---
global_status: blocked:children
support: []
blocked_by:
  - gclm.blowup-criterion
statement_hash: '97d9825d910a'
verified_against:
  self: '97d9825d910a'
  gclm.local-existence: '200cb418dc84'
  gclm.energy-lower-bound: '5a07832c405d'
  gclm.blowup-criterion: '896e63762324'
stale: false
---

## Statement

Fix $a \in (0, 1/2)$ and let $\omega_0 \in H^s(\mathbb{S}^1)$ with $s > 3/2$ be odd
and satisfy $\omega_0'(0) < 0$. Let $\omega$ be the solution of the generalised
Constantin--Lax--Majda equation
\[
  \partial_t \omega + a\, u\, \partial_x \omega = u_x\, \omega,
  \qquad u_x = H\omega,
\]
with initial datum $\omega_0$, where $H$ denotes the Hilbert transform on
$\mathbb{S}^1$. Then the maximal time of existence $T_{\max}$ is finite, and
\[
  \lim_{t \to T_{\max}^-} \| \omega(t) \|_{L^\infty} = \infty .
\]

## Proof

By `gclm.local-existence` there is a unique classical solution on a maximal
interval $[0, T_{\max})$, odd in $x$ for every $t$, and $T_{\max} < \infty$ unless
$\|\omega(t)\|_{H^s}$ stays bounded. Oddness forces $\omega(t,0) = 0$ for all $t$,
so the origin is a stagnation point and the quantity
\[
  z(t) := -\partial_x \omega(t,0)
\]
is well defined and $C^1$ on $[0, T_{\max})$, with $z(0) = -\omega_0'(0) > 0$.

By `gclm.energy-lower-bound`, applied to $\omega(t,\cdot)$ on $[0,T_{\max})$, this
quantity satisfies the differential inequality
\[
  z'(t) \ \ge \ \kappa\, z(t)^2, \qquad \kappa = \kappa(a) > 0 .
\]

By `gclm.blowup-criterion` applied to $z$, no such function can exist on an
interval longer than $1/(\kappa z(0))$. Hence
$T_{\max} \le 1/(\kappa\, |\omega_0'(0)|) < \infty$, and since
$\|\partial_x \omega(t)\|_{L^\infty} \ge z(t) \to \infty$ the solution leaves
$H^s$; by the continuation criterion in `gclm.local-existence` this forces
$\|\omega(t)\|_{L^\infty} \to \infty$ as $t \to T_{\max}^-$.

## Notes

The interesting parameter range is $0 < a < 1/2$; for $a = 1$ this is the De
Gregorio equation and the argument below is known to fail, because the advection
term is then strong enough to move the negative gradient away from the origin.

Strategy: the whole development is a reduction to a scalar ODE inequality at the
stagnation point. Everything hard is concentrated in `gclm.energy-lower-bound`.

The reduction itself was verified on 2026-07-24 and every hash in
`verified_against` still matches, so this node is not stale; it is blocked
because two of the lemmas it uses are not finished.
