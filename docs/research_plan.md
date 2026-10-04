# Research and implementation plan

Accepted work direction, 2026-09-15. These are planned tasks, not implemented
features. Read [current state](current_state.md) and
[experiment policy](experiment_policy.md) first. Local executable briefs live in
`prompts/`; this tracked document preserves their scope for other checkouts.

## Objective

Develop a harness in which a local-capable LLM can infer defensible ancestral
phonology and words, explain daughter reflexes, and preserve uncertainty and
provenance. Improvement means better linguistic results under a valid evaluation,
not just more accepted commits, more tools, or more tests.

Keep the LLM responsible for linguistic judgments. Deterministic code can carry
and verify a model-approved analysis without inventing it. Both rule cascades and
inventories remain available. Training is outside this plan.

## Work packages

| Prompt | Work and output | Dependencies | Live testing |
| --- | --- | --- | --- |
| 01 | Offline failure audit; reproducible concept traces and ranked diagnoses | None | None |
| 02 | Evaluation contracts, proxy labels, outcome denominators, small diagnostic synthetic suite | Start after 01's panel is fixed; use its findings | None required |
| 03 | Consistent evidence and assembly units; typed provenance through intermediate candidates | 01; use 02 for interpretation | One bounded local smoke after deterministic checks |
| 04 | Correct and simplify model instructions; verify tool descriptions and commit requirements | 01; coordinate schema changes with 03 | Local pilot only if needed |
| 05 | Provider-failure accounting, retry/resume semantics, bounded recovery | Independent of 01–04 | Mock providers; no paid calls |
| 06 | Frozen, local-first comparisons; isolate effects and decide next work | 01–05 complete or explicitly scoped out with reasons | Small local pilots; limited replication; optional capped Gemini |
| 07 | Forward-prediction feasibility and a small held-out prototype | After 06, only if still useful | Offline first; optional local smoke |

Do not run multiple agents mutating the same schemas or serving live inference
concurrently. 05 can be developed independently, but coordinate shared reporting
and checkpoint files with 02/03. Freeze both arms before any live comparison.

## 01 — Diagnose before choosing a repair

Select 10–15 concepts from the four valid 36-turn Burmish runs using a recorded
selection rule. Include NEEDLE, near misses, compounds/partial cognates, lost
material and a control. Trace evidence, commitments, residue and parent outputs.
Do not claim the chosen panel estimates population error frequencies. Summarize
whole-benchmark counts separately. Output `docs/research/failure_audit.md` and a
small offline instrument/fixtures if needed. If saved data cannot establish a
cause, say what observation is missing. No new full sweep is a prerequisite.

## 02 — Make evaluation answer the right questions

Preserve old exact/NED measurements and version new readings. Expose historical
binding validity, selection-overlap sets, tone/segment/morphology diagnostics,
missing outputs and failures. Preserve proxy scores without presenting them as
historically validated. Keep gold out of model-facing data, including derived
metadata. Label per-word B-Cubed appropriately; do not call it a cross-lexicon
consistency measure. Add compact, identifiable synthetic cases for targeted
mechanisms and a null/ambiguous control; avoid building a second broad benchmark
framework. Output a metric contract and migration notes.

## 03 — Unify the evidence contract

Determine which surveyed units were actually used by assembly, including at the
next node. Choose the smallest typed design that preserves cognacy/morpheme
analysis and alignment provenance without assigning it silently. Explicitly
represent unknown analyses, multiple candidates, and overlays. Whole-form cases
must remain supported. Prove the correspondence tested is the correspondence
committed and applied. Version changed artifacts and retain old readers; do not
reuse stale validation IDs across incompatible views. If diagnosis does not
support this intervention, deliver the evidence and a smaller alternative instead.

## 04 — Repair model-facing claims and friction

Correct the false cascade impossibility claim in the runtime prompt and all
mirrored commit notes. Treat singleton support and absent outgroup evidence as
qualified evidence situations, not universal linguistic verdicts. Keep real
mechanical constraints explicit. Remove stale run anecdotes from instructions;
put detailed operator history in docs. Measure prompt/schema size and rejection
patterns. Any budget reminder is a separately toggleable experiment, not a reason
to relax validation or force a claim the model cannot defend. Refresh operator
recipes with the current local model policy; keep historical sampling provenance.

## 05 — Distinguish unavailable infrastructure from unsolved linguistics

Classify structured provider errors conservatively, bound retry time, honor useful
retry hints, and preserve checkpoint progress on infrastructure interruption.
Propagate reasons to sweep summaries. Audit compatibility hash semantics before
relaxing operational retry controls. Do not unhash model-visible budgets or changes
that affect reconstructions. Recover from completed nodes without claiming
mid-node resume. Use deterministic fake providers for the full lifecycle.

## 06 — Measure one change at a time

Write a small experiment manifest before running: question, frozen inputs/configs,
primary outcome, controls, resource caps, stopping rule and interpretation.
Prioritize 03's evidence change and 04's instruction correction separately. Do
not bundle them with a model switch or budget increase. Existing sibling-evidence
exposure and copy warnings are secondary ablations only if diagnosis makes them
worthwhile. Replication is not a fishing expedition. Publish nulls and failures;
small samples can be inconclusive. Output `docs/research/local_comparison.md`.

## 07 — Ask whether the ancestor explains its descendants

Explore an explicit parent-to-child account evaluated on held-out observations.
The current child-to-parent rules are not generally invertible: mergers, losses,
conditioning and chronology require explicit treatment. Start on a tiny synthetic
family. Include a trivial/overfit baseline and an ambiguous case so round-trip
agreement is not mistaken for a unique historical answer. Do not build a new
training backend or global inference engine unless a later task authorizes it.
Relevant background: [Lu et al. (2024)](https://aclanthology.org/2024.acl-long.788/).

## Decision points

- If 01 finds mostly proxy/notation error, prioritize 02 before changing assembly.
- If 01 identifies an evidence-view defect, 03 owns the repair and regression.
- If a local model cannot complete the diagnostic task, isolate protocol and
  prompt cost before buying a hosted sweep.
- If 06 improves completion without improving linguistic outcomes, report both;
  do not declare the reconstruction problem solved.
- Defer 07 until its question is not already answered by existing diagnostics.

## Deliberately outside the immediate scope

Deleting a commit path, fine-tuning, large new real-language corpora, automatic
subgrouping/tree revision, a sound-change typology database, unrestricted tools,
and broad model leaderboards. These are not forbidden future research; they do
not resolve the current uncertainty cheaply enough to lead this plan.
