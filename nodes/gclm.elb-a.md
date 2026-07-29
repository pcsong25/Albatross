---
id: gclm.elb-a
role: lemma
children: []
strategy: null
difficulty: standard
lifecycle: active
local_status: verified
flags: []

hypotheses:
  - {id: H1, tex: "\\omega_0 \\in H^s(\\mathbb{S}^1), \\ s > 3/2"}
  - {id: H2, tex: "\\omega_0 \\text{ is odd and } \\omega_0'(0) < 0"}

uses: {}
# --- computed fields: written by `bp sweep`. Never edit them, and never let an agent write them. ---
global_status: proved
support: []
blocked_by: []
statement_hash: '27260e7d162d'
verified_against: {self: '27260e7d162d'}
stale: false
---

## Statement

Let $\omega$ be the solution on $[0,T_{\max})$ with odd datum
$\omega_0 \in H^s(\mathbb{S}^1)$, $s > 3/2$, satisfying $\omega_0'(0) < 0$. Then
\[
  \partial_x \omega(t,0) \ < \ 0 \qquad \text{for every } t \in [0, T_{\max}) .
\]

## Proof

Set $y(t) := \partial_x\omega(t,0)$. Oddness gives $\omega(t,0) = 0$ and
$u(t,0) = 0$ for all $t$, so differentiating the equation at the origin leaves
\[
  y'(t) \ = \ (1-a)\, u_x(t,0)\, y(t),
\]
a linear ODE in $y$ with continuous coefficient
$t \mapsto (1-a)u_x(t,0)$, which is continuous because
$\omega \in C([0,T_{\max}); H^s)$ and $H^{s}(\mathbb{S}^1) \hookrightarrow
C^1(\mathbb{S}^1)$ for $s > 3/2$. Hence
\[
  y(t) \ = \ y(0) \exp\Big( (1-a)\int_0^t u_x(\tau,0)\, d\tau \Big),
\]
and the exponential factor is strictly positive. Since $y(0) = \omega_0'(0) < 0$
we get $y(t) < 0$ throughout.

## Notes

This is the sign-preservation step; it is where oddness is used essentially. It
says nothing quantitative, which is why `gclm.elb-b` is needed.
