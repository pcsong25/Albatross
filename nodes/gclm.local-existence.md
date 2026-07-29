---
id: gclm.local-existence
role: lemma
children: []
strategy: null
difficulty: routine
lifecycle: active
local_status: verified
flags: []

hypotheses:
  - {id: H1, tex: "\\omega_0 \\in H^s(\\mathbb{S}^1), \\ s > 3/2"}

uses: {}
# --- computed fields: written by `bp sweep`. Never edit them, and never let an agent write them. ---
global_status: proved
support: []
blocked_by: []
statement_hash: '200cb418dc84'
verified_against:
  self: '200cb418dc84'
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

*2026-07-29T20:58:24+00:00 — verifier.* Objection withdrawn on confirmation (non-sequitur): The proof does not claim a contraction argument driven by the $H^s \times H^s \to H^{s-1}$ bound — it explicitly invokes "mollification and energy estimates", which is the quasilinear method the objection itself says is required, and the Kato--Ponce commutator estimate $|\langle \Lambda^s(u\,\partial_x\omega), \Lambda^s\omega\rangle| \lesssim \|\partial_x u\|_{L^\infty}\|\omega\|_{H^s}^2$ is the standard internal content of that named argument (its Gr\"onwall output being precisely the stated $\int_0^T\|\partial_x\omega\|_{L^\infty}\,dt$ continuation criterion), while the bilinear bound does the separate job of placing $\partial_t\omega$ in $H^{s-1}$; so the complaint is about how much of a routine argument was written out, not a hole.

*2026-07-29T20:58:24+00:00 — verifier.* Objection withdrawn on confirmation (non-sequitur): The criterion is stated in the Lipschitz quantity rather than $\|\omega\|_{L^\infty}$, so the $L^\infty$-endpoint failure of $H$ never arises: boundedness of $H$ on $C^{0,\alpha}$ (Privalov) gives $\|H\omega\|_{L^\infty} \lesssim \|\omega - \bar\omega\|_{C^{0,\alpha}} \lesssim \|\partial_x\omega\|_{L^\infty}$ on $\mathbb{S}^1$, and conservation of $\int\omega$ is one line from $\frac{d}{dt}\int\omega = (a+1)\int (H\omega)\omega = 0$ (skew-adjointness of $H$), whence $\|\omega\|_{L^\infty} \le |\bar\omega_0| + \pi\|\partial_x\omega\|_{L^\infty}$ — both are exactly the routine bookkeeping that 'a standard mollification and energy-estimate argument' is entitled to absorb in a lemma of this difficulty.

*2026-07-29T20:58:24+00:00 — verifier.* Objection withdrawn on confirmation (premise-smuggling): The normalisation is the standard convention for the gCLM equation — $u = \partial_x^{-1}H\omega$ with zero mean is what "$u_x = H\omega$" denotes on the circle, since $H\omega$ has zero mean and $\partial_x^{-1}$ is understood as its mean-zero primitive, so no unstated hypothesis is smuggled in and the oddness argument stands as written.

*2026-07-29T20:58:24+00:00 — verifier.* Objection withdrawn on confirmation (premise-smuggling): The parameter $a$ is a fixed constant of the gCLM equation family being studied throughout the development, so its declaration belongs to the development's setup rather than to this lemma's hypothesis list, and the proof is uniform in $a$ — as the objection itself concedes — so no step depends on an unstated restriction.
