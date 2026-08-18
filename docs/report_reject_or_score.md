# Report, reject, or score

Where a new signal belongs. This is the reasoning behind the invariant
"distinguish mechanical correctness, workflow quality, and linguistic truth",
written down because the three collapse into each other whenever nobody is
watching.

## Three questions, not one

"Was this run good?" is three separate questions with three different answerers:

| Question | Who can answer it | Where it lives |
| --- | --- | --- |
| Did the machinery do exactly what it was told? | Deterministic code, with certainty | `rules/`, `traversal/`, tool rejections in `agent/tools/` |
| Was this a good example of an agent using these tools? | A heuristic, guessing | `high_quality` in `agent/trajectory.py` |
| Is this reconstruction historically correct? | A comparative linguist, not this repo | nothing |

The first is provable. The third is a research question the harness is not
equipped to answer. The second is the awkward middle: a judgement the repo makes
anyway, because something has to decide which trajectories enter a future
fine-tuning corpus.

## The failure mode: answering one with another's evidence

`runs/google-gemma-4-e4b-20260815-101423`, the pre-change baseline, is one run
with three true and different verdicts:

- **linguistically** correct — `p a`, `p u r`;
- **mechanically** correct — the committed rule was validated and applied
  exactly as written;
- **as a tool-use example** poor — three of seven calls were rejected
  commit-schema errors, so training on it teaches fumbling the commit protocol
  three times before getting it right.

It reported `high_quality: 1`, because the flag was answering "is it correct?"
when its job was "is it a good example?"

The `rule_coverage` defect was the same mistake pointing the other way. A
correct `f > p / #_` scoped to three children scored 0.33 while the identical
reconstruction scoped to the one child showing `f` scored 1.0 — a *mechanical*
counter measuring a *scoping convention* and being read as quality, which
pressured the model to narrow a linguistic claim to satisfy a number. The
coupling was the defect, not the scope.

## Why "gate" is a special word

A report is read by a human who then decides. A gate decides without one:
`export-trajectories --high-quality-only` uses `high_quality` to choose what
enters the corpus.

- **Adding a number to a report is reversible.** Print a line, decide it was
  noise, delete the line. Nothing downstream remembers.
- **Adding a number to a gate is not.** Once it filters, corpora exist that were
  selected by it — already written, already exported, possibly already trained
  on. You cannot un-select them.

Same asymmetry that keeps `schema_version` at `2.0`: bumping later is trivial,
un-bumping after files exist in the wild is impossible. When the cost of being
wrong is lopsided, the cheap direction is the default and the expensive one
needs evidence.

## The worked example: cross-node consistency

A live two-node run: `INNER` committed `f > p / #_`, then `PROTO` committed an
identity reconstruction. `inspect-run` observes that `PROTO` never mentions a
correspondence established below it.

The observation is correct **and the run is perfect** — the change was already
complete below, so the parent has nothing to say about it. Wire the same signal
into the gate and this run is disqualified: a correct reconstruction excluded
from the corpus by a rule that sounded reasonable when it was written.

Hence the question to keep in your pocket: **what happens when this fires on a
correct run?**

- "A human reads a line and moves on" — report it.
- "The run is disqualified" — you now need evidence about how often it fires on
  correct runs, and that evidence is a corpus of graded trajectories, which does
  not exist yet.

Adjacent nodes mapping `f` to `p` and to `b` in the same environment genuinely
deserves attention. Whether it means one rule is wrong, the tree is wrong, the
cognate set is wrong, or it is ordinary chronological layering is exactly the
linguistic-truth question this harness cannot answer. Printing it is honest;
scoring it would be the harness claiming expertise it does not have.

## The second worked example: child convergence

`child_convergence_rate` measures the share of concepts on which every active
child, after its own scoped cascade, produced the identical parent form. It is
the first diagnostic that measures the reconstruction rather than the rules, and
it was classified as a **score and a report**, not a rejection. That decision is
recorded here because it is the sort of thing a later reader will want to
re-litigate.

The case for rejecting looks strong at first. A live node committed
`f > p / _eː` scoped to Tongan **and** `p > f / _e` scoped to Niuean —
contradictory claims about one correspondence, guaranteeing that the branches
could not agree. Both rules were validated, both were accepted at confidence 1.0,
no protocol failure was recorded, and the session passed `high_quality`. Every
rule diagnostic reported a flawless node.

Run that through the question in the pocket: **what happens when this fires on a
correct run?**

It fires constantly, and correctly. A comparative argument routinely leaves a
residue — forms the regular correspondences do not yet explain — and the honest
hypothesis is the one that says so, in `anomalies`, rather than the one that
invents a rule per exception until everything lines up. Rejecting divergence at
the tool boundary would reward exactly the padding the anomaly channel exists to
avoid. And an identity commit at a node whose children genuinely differ is a
legitimate, conservative claim: nothing yet explains this, so nothing is
asserted. Deterministic code cannot tell that apart from the Tongan/Niuean case,
because the difference is whether the rules are *true*, which is question three.

So it lands on rule 2 of the decision rule below: a fact about the session that a
human wants, where "bad" needs judgement. It is reported to the model in the
`test_rule_cascade` and `commit_reconstruction` results, recorded in
`ReconstructionDiagnostics`, and printed by `inspect-run` and
`summarize-trajectories`. It is deliberately **not** a condition of
`high_quality`: that flag is documented as protocol hygiene making no linguistic
claim, and convergence is much closer to linguistic than to protocol. Adding it
would quietly change what `--high-quality-only` selects for, in the direction of
over-fitted rule sets, and — per the asymmetry above — corpora selected by it
cannot be un-selected.

Note what *is* a rejection in the same area, and why. A rule that cannot change
any token sequence is refused by the parser: that is question one, provable by
deterministic code, no judgement involved. "These children still disagree" is
not.

There is one place convergence does change what a machine does, and it is worth
naming rather than eliding: branch support now weights the beam, so how many
children back a form affects which form wins the node. That is scoring, it is
the subject of a separate entry in "Decisions that require research-owner
input", and it is bounded — it orders candidates the harness already computed.
It does not decide whether a run is valid, and no trajectory is filtered by it.

## The decision rule

For anything new, in order:

1. **Can deterministic code be certain this is a defect?** A DSL that does not
   parse, a commit referencing a validation that does not exist, a rule that
   changed nothing. Reject it at the tool boundary — that is a fact, not a
   judgement.
2. **Is it a fact about the session a human would want, where "bad" needs
   judgement?** Confidence spread across nodes, a wide scope, an anomaly rate.
   Report it and let the reader decide.
3. **Would it change which trajectories are exported, or which candidate wins
   the beam?** Stop. That is the definition of "what counts as a valid
   reconstruction" and belongs to the research owner, alongside the branch
   penalty, the anchor boost, and whether parsimony should affect scoring. See
   README, "Decisions that require research-owner input".

If you are unsure which layer you are editing, ask whether the number you are
adding can change something a machine does. If it can, it is a gate.
