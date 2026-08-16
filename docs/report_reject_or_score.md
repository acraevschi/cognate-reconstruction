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
