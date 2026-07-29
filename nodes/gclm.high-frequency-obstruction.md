---
id: gclm.high-frequency-obstruction
role: proposition
children: []
strategy: null
difficulty: standard
lifecycle: active
local_status: unverified
flags: []
hypotheses:
  - id: H1
    tex: 0<\theta<1
uses: {}
# --- computed fields: written by `bp sweep`. Never edit them, and never let an agent write them. ---
global_status: open
support: []
blocked_by: []
statement_hash: '7011192f03de'
stale: false
---

## Statement

Fix \(0<\theta<1\). For \(n\ge1\), let
\[
f_n(x)=-\frac1n\sin(nx),\qquad z_n=-f_n'(0)=1,\qquad M_n=2\|f_n\|_{L^\infty}=\frac2n.
\]
These profiles are real analytic and odd, and the kernel convention in the parent gives
\[
Hf_n(0)=-\frac1n,
\qquad
\frac{-Hf_n(0)}{|f_n'(0)|}=\frac1n\longrightarrow0.
\]
Moreover, if \(f_n(y)\le-\theta z_n y\) on \([0,\delta]\), then \(\delta\le r_\theta/n\), where \(r_\theta\in(0,\pi)\) is determined by \(\sin r_\theta=\theta r_\theta\). Consequently,
\[
\inf_{0<\delta\le r_\theta/n}
\frac{2M_n\log\!\csc(\delta/2)}{\theta\delta z_n}
\longrightarrow\infty.
\]
Hence neither the uniform critical-scale comparison nor a positive coercivity constant depending only on \(a\) holds on the profile class specified by the parent.

## Proof



## Notes

This is a direct obstruction, not merely a failure of the proposed proof technique.
