# task02-v1 migration and commands

The [contract](evaluation_contract.md) defines the readings;
[implementation/results](evaluation_results.md) record validation and limits.

## Compatibility

`HistoricalFormBinding`, preparation requests and benchmark targets gain nullable
`target_validity` and `target_validity_note`. Default null means unknown, not
validated. Old Burmese at `burmic` has an explicit `provisional_proxy` annotation
in `benchmarks/burmish.json`. Legacy reports without that field recognize only
that exact `(node_id, source_variety_id)` pair. No reference prose is parsed.
Other unannotated old bindings remain unknown and need curation before entering
the validated-target summary. Evidence kind is unchanged.

Historical evaluations gain `evaluator_version`, `model_committed`, descendant
fallback IDs, selection counts/IDs and per-concept `token_diagnostics`. Missing
new fields read as unmeasured. Raw exact, distances, nearest-alternative rules,
all target alternatives and graded distributions retain their old definitions.
`agent.service._evaluate_target` remains an import-compatible alias of the
evaluator in `evaluation/targets.py`. Trajectory versions 2.0/3.0 and both commit
shapes remain supported.

New family results include `evaluation_report` (nullable on old artifacts).
It describes every planned target and every operational internal node. Sweep
summaries retain the legacy `gold_targets` block as raw historical measurements
and add `evaluation_views`: raw planned-set, explicitly validated-target and
per-node counts. Those counts pool nested concept evaluations; they are not
independent sampling units or uncertainty estimates. Existing distributions
remain distributions across node/seed evaluations, with SD not a confidence interval.

An older code checkout using strict `extra=forbid` cannot load newly added
fields; use this checkout for new reports. The current reader loads old artifacts.
No old file is rewritten to claim the new version. Version labels live on the
new interpretation, not on the old saved score. Banked aggregates stay intact.

Result JSON historically includes three computed `RuleApplicationReport`
properties (`words_applied`, `anchors_matched`, `exceptions`). The evaluator
ignores only those properties while validating actual fields strictly. JSONL
and checkpoint readers retain their canonical format. Conflicting result and
completed-trajectory steps are refused rather than silently chosen.

## Offline interpretation of saved or abandoned runs

```sh
conda run -n llm_reconstruction python tools/evaluate_run.py \
  runs/sweeps/burmish-gemini-t36-r2/seed-00 \
  runs/sweeps/burmish-gemini-t36-r2/seed-01 \
  runs/sweeps/burmish-gemini-t36-r3/seed-00 \
  runs/sweeps/burmish-gemini-t36-r3/seed-01 \
  --payload runs/benchmarks/burmish.json --definition benchmarks/burmish.json --json \
  > /tmp/task02-burmish-evaluation.json
```

Omit `--json` for text. `--payload` supplies the intended target set and tree;
`--definition` adds explicit binding and declared selection metadata without
rebuilding/reselecting the payload. JSON keeps saved evaluations beside the
versioned report. A result file path is accepted as well as a directory.

Completed JSONL trajectories are read even when no result exists. Salvage uses
only their saved deterministic steps. Failed trajectories and prose cannot
supply an output. A completed commit with no saved step has missing coverage,
not an invented beam. Without trajectory commitment evidence, an available
result step is `unknown_commitment`, not a model commitment. Unknown legacy
provider causes remain unknown/unspecified. Task 05 will improve causes later.

`read_seed(..., payload=...)` supports this same plan and salvage behavior;
`run-benchmark` supplies its frozen payload automatically. Without a supplied
plan or persisted `evaluation_report`, `seeds_without_plan` is explicit and the
new end-to-end view is unavailable. Legacy aggregate quality is retained; it
does not acquire invented missing-run scores. `inspect-run` text/HTML display
proxy labels and descendant fallback dependencies on legacy artifacts too;
new result reports additionally display the planned-set views.

## Small mechanism suite

```sh
conda run -n llm_reconstruction python tools/diagnostic_suite.py \
  --output-dir /tmp/task02-diagnostics --json > /tmp/task02-synthetic-evaluation.json
```

Definitions: `benchmarks/diagnostic/task02-v1.json`. Each `<case>.json` is a
runnable payload with observed evidence and separate hidden target bindings;
`<case>.answer-key.json` holds generated truth and operator-only identifiability
notes. Supply only the runnable payload to inference. Initial node payloads and
tool results contain neither reference annotations nor key-derived hints.
Observed morphology IDs are independently declared cognacy metadata.

The command performs no live inference: identity uses a scripted provider;
perfect/wrong are labelled score fixtures made after that run. Their counts
test the evaluator, not model skill. Lost contrast and ancestral morphology
order are excluded from validated unique-answer summaries. The piece comparator
`evaluation.diagnostics.compare_cognate_units` takes independently supplied IDs
and complete token pieces, reports extra/missing/reordered units, and refuses
missing/duplicate analyses. Task 03 supplies faithful output memberships before
this can grade real morpheme reconstructions.

Do not tune against these development cases and call them held-out results.
Fit/freeze any later learned normalization on separate development material.
No category-to-contour, phonation or corpus mapping score is licensed here.

## Task04 diagnostic update — 2026-10-04

`build_case` now attaches scorer-only supplied target layouts to binding forms;
observed payloads, target tokens and task02-v1 raw score definitions are unchanged.
`TokenEvaluationDiagnostics.unit_evaluator_version` defaults to null for historical
records and is `task04-units-v1` for explicit output comparisons. `diagnostic_suite`
adds `normal_unit_controls`, using scripted assembly/serialization/normal evaluation
for correct, wrong, extra, missing and reordered pieces. Standalone piece controls
remain available but are no longer the only verification. See
[evidence repair](evidence_repair.md) for measured results and compatibility.
