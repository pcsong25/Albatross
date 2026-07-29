---
id: gclm.elb-b
role: lemma
children:
  - gclm.one-scale-hilbert-coercivity
  - gclm.critical-scale-domination
  - gclm.high-frequency-obstruction
strategy: A conditional one-scale Hilbert-kernel coercivity argument, with the unresolved content isolated as a uniform coherent-scale versus logarithmic-tail comparison and checked against a high-frequency obstruction.
difficulty: hard
lifecycle: active
local_status: admitted
status_reason: the Biot--Savart lower bound at the stagnation point is believed but not proved here; it is the one genuinely hard analytic input of the development
flags: []

hypotheses:
  - {id: H1, tex: "0 < a < 1/2"}
  - {id: H2, tex: "\\partial_x\\omega(t,0) < 0 \\text{ on } [0,T_{\\max})"}
  - {id: H3, tex: "\\|\\omega(t)\\|_{L^\\infty} \\le 2\\|\\omega_0\\|_{L^\\infty} \\text{ on } [0,T_{\\max})"}

uses:
  gclm.one-scale-hilbert-coercivity:
    applied_to: f=\omega(t,\cdot),\quad z=-\partial_x\omega(t,0),\quad M=2\|\omega_0\|_{L^\infty},\quad \theta=\theta_a
    discharges:
      H1: proof:oddness is part of the parent statement, while the standing solution regularity with s>3/2 gives f\in C^1(\mathbb S^1) by Sobolev embedding
      H2: hypothesis:H2
      H3: proof:M:=2\|\omega_0\|_{L^\infty}>0 because \omega_0'(0)<0 in the standing setting
      H4: hypothesis:H3
      H5: child:gclm.critical-scale-domination
      H6: child:gclm.critical-scale-domination
      H7: child:gclm.critical-scale-domination
  gclm.critical-scale-domination:
    applied_to: f=\omega(t,\cdot),\quad z=-\partial_x\omega(t,0),\quad M=2\|\omega_0\|_{L^\infty}
    discharges:
      H1: hypothesis:H1
      H2: proof:oddness is part of the parent statement, while the standing solution regularity with s>3/2 gives f\in C^1(\mathbb S^1)
      H3: hypothesis:H2
      H4: proof:M:=2\|\omega_0\|_{L^\infty}>0 because \omega_0'(0)<0
      H5: hypothesis:H3
  gclm.high-frequency-obstruction:
    applied_to: f_n(x)=-n^{-1}\sin(nx)\text{ and }\theta=\theta_a
    discharges:
      H1: child:gclm.critical-scale-domination
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

Fix \(t\in[0,T_{\max})\) and set
\[
f=\omega(t,\cdot),\qquad z=-\partial_x\omega(t,0)>0,\qquad M=2\|\omega_0\|_{L^\infty}.
\]
If `gclm.critical-scale-domination` were available, it would provide \(\theta_a,\eta_a,\delta_a\) and \(\delta\in[\delta_a,\pi/2]\) satisfying its cone and tail inequalities. Applying `gclm.one-scale-hilbert-coercivity` at this scale yields
\[
-u_x(t,0)=-Hf(0)
\ge \frac{\theta_a\delta}{\pi}z
 -\frac{2M}{\pi}\log\!\csc\!\left(\frac{\delta}{2}\right)
\ge \frac{\eta_a\theta_a\delta}{\pi}z
\ge \frac{\eta_a\theta_a\delta_a}{\pi}z.
\]
Thus the claimed conclusion would follow with \(c_a=\eta_a\theta_a\delta_a/\pi\). This conditional reduction is routine. It is not an unconditional proof: `gclm.high-frequency-obstruction`, applied with \(\theta=\theta_a\), shows that the required scale cannot exist uniformly and also gives \(-Hf_n(0)/|f_n'(0)|=1/n\to0\), directly contradicting the asserted coercivity on the formally stated profile class.

## Notes

Admitted deliberately. This is the node to attack next: everything else in the
development is either routine or already verified, and this is the only item in
the support certificate for the theorem's branch through
`gclm.energy-lower-bound`.

*2026-07-29T20:42:22+00:00 — decomposer.* Decomposer's reservations: The node is false under its displayed hypotheses. The family \(f_n=-n^{-1}\sin(nx)\) has unit negative derivative at the origin but \(-Hf_n(0)=n^{-1}\). It also shows that a lower bound for the gradient relative to \(\|f\|_{L^\infty}\) is insufficient: here \(z_n/M_n=n/2\to\infty\), while the coherent tangent scale shrinks like \(n^{-1}\) and the logarithmic tail comparison fails. If \(\omega\) is intended to range only over genuine gCLM solutions satisfying the global bootstrap bound, that materially stronger domain restriction is absent from H1--H3 and must be formalized; proving that it enforces `critical-scale-domination` would then be the substantive missing result. Any viable repair must add quantitative profile or frequency control, allow \(c_a\) to depend on such control, or replace the claimed coercivity estimate.

*2026-07-29T20:42:22+00:00 — human.* Expanded with hint: Expand the Hilbert-transform lower bound at the stagnation point. The obstruction noted in the Notes is that the inner contribution is proportional to delta times the gradient while the outer error is O(||omega||_Linf log(1/delta)); a decomposition should isolate exactly that comparison.
