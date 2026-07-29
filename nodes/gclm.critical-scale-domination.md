---
id: gclm.critical-scale-domination
role: assumption
children: []
strategy: null
difficulty: hard
lifecycle: active
local_status: unverified
flags: []
hypotheses:
  - id: H1
    tex: 0<a<1/2
  - id: H2
    tex: f\in C^1(\mathbb S^1)\text{ is odd}
  - id: H3
    tex: z=-f'(0)>0
  - id: H4
    tex: M>0
  - id: H5
    tex: \|f\|_{L^\infty}\le M
uses: {}
# --- computed fields: written by `bp sweep`. Never edit them, and never let an agent write them. ---
global_status: open
support: []
blocked_by: []
statement_hash: 'f06889ed20f5'
stale: false
---

## Statement

There exist constants \(\theta_a,\eta_a\in(0,1)\) and \(\delta_a\in(0,\pi/2]\), depending only on \(a\), such that every profile satisfying the hypotheses below admits a scale \(\delta\in[\delta_a,\pi/2]\) for which
\[
f(y)\le-\theta_a z y\quad(0\le y\le\delta)
\]
and
\[
2M\log\!\csc\!\left(\frac{\delta}{2}\right)
\le (1-\eta_a)\theta_a\delta z.
\]
Thus the interval on which the negative tangent controls the profile has uniformly positive length, and on that same interval the inner quantity \(\delta z\) dominates the logarithmic \(L^\infty\)-tail.

## Proof



## Notes

This is exactly the missing comparison. It is not a consequence of the stated hypotheses and is contradicted by the high-frequency family in `high-frequency-obstruction`; it can only serve as an additional profile assumption unless the admissible class is narrowed.
