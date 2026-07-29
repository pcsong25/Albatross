---
id: gclm.energy-lower-bound
role: proposition
children: [gclm.elb-a, gclm.elb-b]
strategy: bootstrap on the sign of the gradient at the origin
difficulty: hard
lifecycle: active
local_status: verified
flags: []

hypotheses:
  - {id: H1, tex: "0 < a < 1/2"}
  - {id: H2, tex: "\\omega_0 \\text{ is odd and } \\omega_0'(0) < 0"}
  - {id: H3, tex: "\\omega_0 \\in H^s(\\mathbb{S}^1), \\ s > 3/2"}

uses:
  gclm.elb-a:
    applied_to: "\\omega(t,\\cdot) \\text{ for } t \\in [0, T_{\\max})"
    discharges:
      H1: "hypothesis:H3"
      H2: "hypothesis:H2"
  gclm.elb-b:
    applied_to: "\\omega(t,\\cdot) \\text{ for } t \\in [0, T_{\\max})"
    discharges:
      H1: "hypothesis:H1"
      H2: "child:gclm.elb-a"
      H3: "ADMITTED: the a priori bound $\\|\\omega(t)\\|_{L^\\infty} \\le 2\\|\\omega_0\\|_{L^\\infty}$ is not established anywhere in this development"

# --- computed fields: written by `bp sweep`. Never edit them, and never let an agent write them. ---
global_status: proved_modulo
support:
  - gclm.energy-lower-bound
blocked_by: []
statement_hash: '5a07832c405d'
verified_against:
  self: '5a07832c405d'
  gclm.elb-a: '27260e7d162d'
  gclm.elb-b: '76d0a85e9f5d'
stale: false
---

## Statement

Let $0 < a < 1/2$, let $\omega_0 \in H^s(\mathbb{S}^1)$ with $s > 3/2$ be odd with
$\omega_0'(0) < 0$, and let $\omega$ be the corresponding solution on
$[0,T_{\max})$. Write $z(t) := -\partial_x\omega(t,0)$. Then there is
$\kappa = \kappa(a) > 0$, independent of $\omega_0$ and of $t$, with
\[
  z'(t) \ \ge \ \kappa\, z(t)^2 \qquad \text{for all } t \in [0, T_{\max}) .
\]

## Proof

Differentiating the equation in $x$ and evaluating at the origin, where
$\omega(t,0) = 0$ and $u(t,0) = 0$ by oddness, gives
\[
  \partial_t \partial_x\omega(t,0)
  \ = \ -a\, u_x(t,0)\, \partial_x \omega(t,0) + u_{xx}(t,0)\, \omega(t,0)
        + u_x(t,0)\, \partial_x\omega(t,0)
  \ = \ (1 - a)\, u_x(t,0)\, \partial_x\omega(t,0),
\]
so that $z'(t) = -(1-a)\, u_x(t,0)\, z(t)$ with $z(t) = -\partial_x\omega(t,0)$.

By `gclm.elb-a` the sign of the gradient at the origin is preserved:
$\partial_x\omega(t,0) < 0$, hence $z(t) > 0$, throughout $[0,T_{\max})$.

By `gclm.elb-b` the Biot--Savart law converts that sign information into the
quantitative bound $-u_x(t,0) \ge c_a\, z(t)$ with $c_a > 0$ depending only on
$a$. Substituting,
\[
  z'(t) \ = \ -(1-a)\, u_x(t,0)\, z(t) \ \ge \ (1-a)\, c_a\, z(t)^2,
\]
which is the claim with $\kappa := (1-a)\,c_a$, positive because $a < 1/2 < 1$.

## Notes

The constant $\kappa$ must be uniform in $t$; that is what makes the Riccati
comparison in `gclm.blowup` legitimate rather than circular. The $L^\infty$ bound
that `gclm.elb-b` wants is currently admitted and is the main outstanding debt in
this branch.
