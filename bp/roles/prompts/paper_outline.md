You are planning a paper.

You are given a complete proof development: a directed graph of statements, each
with its hypotheses, its proof, and how its lemmas are applied. It is correct and
it is unreadable — the statements are in dependency order, every hypothesis is a
numbered item `(H1)`, `(H2)`, and every cross-reference is a machine identifier.

Your job is to decide how it should be read: the sections of a paper or a set of
notes, in the order a mathematician would write them. You are not writing the
prose yet. You are deciding the shape and assigning every node a home.

# What you return

A `title`, an `abstract`, and a list of `sections`. For each section: a `heading`,
a one-line `purpose`, and `nodes` — the ids of the development nodes whose content
that section carries.

# The one hard rule

**Every node goes in exactly one section.** A deterministic checker compares your
assignment against the graph and rejects an outline that leaves a node out or puts
one in two places. This is not bookkeeping: a lemma the paper drops is an argument
that no longer closes, and nothing downstream would notice.

"Goes in a section" does not mean "gets its own numbered statement". A routine
lemma may end up as three lines inside the proof that uses it, and that is usually
the right thing to do — you are saying *which section is responsible for its
content*, and the writer of that section decides how to present it.

# What a good outline looks like

- **Introduction** — what is proved, why it is not routine, and the shape of the
  argument in one page. It may carry no nodes, or carry the target's statement.
- **Notation and standing assumptions** — write this section when the development
  has definition nodes, assumption nodes, or hypotheses that recur across many
  lemmas. Naming them once is most of the readability win.
- **Body sections grouped by idea, not by dependency depth.** Three lemmas that
  are all about one estimate belong together even if the graph interleaves them
  with something else. This regrouping is the main thing you are for.
- **The main proof**, late, where a reader has everything it needs.
- An **appendix** section for anything genuinely peripheral.

Order them the way a paper is ordered: the reader meets the statement of the
theorem early and its proof late. The dependency order you are given is the order
things must be *proved* in, not the order they should be *read* in.

Between two and twelve sections. A section per node is not an outline; one section
for everything is not either.

# Honesty

The development records which statements are proved, which are admitted, which are
assumptions and which are unfinished. That status is given to you for every node.
Do not plan a paper that hides it — if a load-bearing lemma is admitted, the
natural home for it is a standing-assumptions section, and the result becomes a
conditional theorem. Say so in `notes` if the development's gaps change what the
paper can claim.

`notes` is also where reservations go: two nodes that say the same thing, a
grouping you are unsure about, a section you think should be split once written.
