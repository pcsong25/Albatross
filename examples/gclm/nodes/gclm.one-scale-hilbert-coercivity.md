---
id: gclm.one-scale-hilbert-coercivity
role: lemma
children:
  - gclm.hilbert-kernel-split
strategy: null
difficulty: standard
lifecycle: active
local_status: unverified
flags: []
hypotheses:
  - id: H1
    tex: f\in C^1(\mathbb S^1)\text{ is odd}
  - id: H2
    tex: z>0
  - id: H3
    tex: M>0
  - id: H4
    tex: \|f\|_{L^\infty}\le M
  - id: H5
    tex: 0<\delta\le \pi/2
  - id: H6
    tex: 0<\theta\le 1
  - id: H7
    tex: f(y)\le-\theta z y\quad\text{for }0\le y\le\delta
uses:
  gclm.hilbert-kernel-split:
    applied_to: ''
    discharges: {}
# --- computed fields: written by `bp sweep`. Never edit them, and never let an agent write them. ---
global_status: open
support: []
blocked_by: []
statement_hash: '7151b9bdd731'
stale: false
---

## Statement

Let \(f\in C^1(\mathbb S^1)\) be odd. Under the hypotheses below, the periodic Hilbert transform satisfies
\[
-Hf(0)\ge \frac{\theta\delta}{\pi}z-\frac{2M}{\pi}\log\!\csc\!\left(\frac{\delta}{2}\right).
\]
Indeed, oddness gives
\[
-Hf(0)=-\frac1\pi\int_0^\pi f(y)\cot\!\left(\frac y2\right)\,dy,
\]
and the first term in the lower bound is the contribution of \((0,\delta)\), whereas the second is the sharp \(L^\infty\)-control of the remaining kernel mass.

## Proof



## Notes

This packages the inner coercive contribution and the logarithmic outer loss in the precise form needed by the reduction.
