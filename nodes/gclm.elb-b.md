---
id: gclm.elb-b
role: lemma
children: []
strategy: null
difficulty: hard
lifecycle: active
local_status: admitted
status_reason: the Biot--Savart lower bound at the stagnation point is believed but not proved here; it is the one genuinely hard analytic input of the development
flags: []

hypotheses:
  - {id: H1, tex: "0 < a < 1/2"}
  - {id: H2, tex: "\\partial_x\\omega(t,0) < 0 \\text{ on } [0,T_{\\max})"}
  - {id: H3, tex: "\\|\\omega(t)\\|_{L^\\infty} \\le 2\\|\\omega_0\\|_{L^\\infty} \\text{ on } [0,T_{\\max})"}

uses: {}
# --- computed fields: written by `bp sweep`. Never edit them, and never let an agent write them. ---
global_status: proved_modulo
support:
  - gclm.elb-b
blocked_by: []
statement_hash: '76d0a85e9f5d'
stale: false
---

## Statement

Let $0 < a < 1/2$ and let $\omega(t,\cdot)$ be odd with
$\partial_x\omega(t,0) < 0$ and
$\|\omega(t)\|_{L^\infty} \le 2\|\omega_0\|_{L^\infty}$. Write $u_x = H\omega$.
Then there is $c_a > 0$, depending only on $a$, with
\[
  -u_x(t,0) \ \ge \ c_a \, \big| \partial_x \omega(t,0) \big| .
\]

## Proof

Not written. The intended route is to expand the Hilbert transform at the origin,
\[
  u_x(t,0) \ = \ \mathrm{p.v.}\, \frac{1}{2\pi}\int_{-\pi}^{\pi}
  \omega(t,y) \cot\!\Big(\frac{y}{2}\Big)\, dy,
\]
split the integral at $|y| \le \delta$, and use oddness together with the sign of
$\partial_x\omega(t,0)$ on the inner region while controlling the outer region by
the $L^\infty$ bound. The obstruction is that the inner contribution is
proportional to $\delta \, \partial_x\omega(t,0)$ while the outer error is
$O(\|\omega\|_{L^\infty} \log(1/\delta))$, and closing the two requires a lower
bound on $|\partial_x\omega(t,0)|$ relative to $\|\omega\|_{L^\infty}$ that is
not available a priori.

## Notes

Admitted deliberately. This is the node to attack next: everything else in the
development is either routine or already verified, and this is the only item in
the support certificate for the theorem's branch through
`gclm.energy-lower-bound`.
