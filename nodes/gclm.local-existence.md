---
id: gclm.local-existence
role: lemma
children: []
strategy: null
difficulty: routine
lifecycle: active
local_status: unverified
flags: []

hypotheses:
  - {id: H1, tex: "\\omega_0 \\in H^s(\\mathbb{S}^1), \\ s > 3/2"}

uses: {}
# --- computed fields: written by `bp sweep`. Never edit them, and never let an agent write them. ---
global_status: blocked:unverified
support: []
blocked_by: []
statement_hash: '200cb418dc84'
stale: false
---

## Statement

Let $s > 3/2$ and $\omega_0 \in H^s(\mathbb{S}^1)$. Then there exist
$T_{\max} \in (0,\infty]$ and a unique solution
$\omega \in C([0,T_{\max}); H^s) \cap C^1([0,T_{\max}); H^{s-1})$ of the
generalised Constantin--Lax--Majda equation with datum $\omega_0$. If
$\omega_0$ is odd then $\omega(t,\cdot)$ is odd for every $t \in [0,T_{\max})$.
Moreover the solution continues past $T$ whenever
$\int_0^{T} \|\partial_x \omega(t)\|_{L^\infty}\, dt < \infty$.

## Proof

The nonlinearity $\omega \mapsto -a\,u\,\partial_x\omega + u_x \omega$ with
$u_x = H\omega$ is a bounded bilinear map $H^s \times H^s \to H^{s-1}$ for
$s > 3/2$, since $H$ is bounded on every $H^\sigma$ and $H^{s-1}$ is an algebra in
this range. A standard mollification and energy-estimate argument then gives
local well-posedness in $H^s$ together with the stated continuation criterion.

Oddness is preserved because the Hilbert transform maps odd functions to even
functions, so $u$ is odd, $u_x$ is even, and the vector field on the right-hand
side maps odd data to odd data.

## Notes

Standard; this is the only node in the development that a referee would accept
without an argument. Written out because the continuation criterion is used in
`gclm.blowup` and ought to be stated somewhere.
