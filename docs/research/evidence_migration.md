# units-v1 migration and operator contract

Read the [design](evidence_contract.md) and [results](evidence_results.md). This
changes reconstruction evidence/execution semantics, not the task02-v1 exact/NED
definitions or task01-v1 superscript partition.

## Artifacts and resume

New trajectories are 4.0 for both commit shapes. Readers accept 2.0, 3.0 and 4.0
without restamping old records. New inventory commitments carry
`evidence_contract_version=units-v1`, `evidence_revision` and exact column bindings.
An inventory missing those fields reads as `legacy` and executes with the old
whole-string/reflex-tuple mechanism. Do not translate old set IDs by token matching.
New inventory `derived_rules_scope=unscoped_view` warns that its derived DSL view
omits unit/column restrictions; do not use it as an equivalent global cascade or
claim global rule precision from that view. Exact assembly is the execution.

Checkpoints now write schema 2.0. Schema 1.0 remains readable for offline audit,
but `infer --resume` refuses it explicitly because it lacks inherited unit
provenance. Start a new run/checkpoint or use the original checkout to resume it.
The evidence contract is also a named behavioral configuration hash component.
Instruction/schema hashes remain strict; no mid-node resume was added.

Candidates and lexical forms gain `analysis`. Old missing/null analyses mean
unknown, not recovered cognacy. New source beams carry complete pieces, original
source references and positional spans. Reconstructed pieces retain approved
column IDs and immediate child-form positions; stored input beams/derivations
link those positions to original source forms. Compatible claims merge their
provenance; incompatible claims retain separate candidate IDs despite equal
surfaces. Ordinary beam pruning counts are recorded. Rules retain exact analysis
on identity; applied rules preserve derivation and mark the resulting whole-form
analysis unresolved. An explicit later model claim can analyze it.

Runtime tools identify retained candidate analyses with candidate form IDs.
Original source form IDs remain in piece provenance. A raw lexicon has no beam
scores; standalone previews normalize its explicitly supplied readings. During a
family run previews use the actual retained child beams and their scores.

## Typed model tools

1. Survey with `summarize_correspondences`. `scope_id`, bounded
   `example_column_ids`, `evidence_revision` and work counters supplement reflexes
   and support. Every retained analysis is represented; a page/filter does not
   change IDs. An explicit `respect_cognate_sets=false` diagnostic is a legacy
   unscoped reading and is not a source of units-v1 commitments.
2. `get_alignments` over bounded concepts/forms returns shared unit columns,
   source positions and `analysis_id`; pairwise summary/full detail remains
   available. Anchor-inclusive alignments remain supplementary evidence.
3. Conflicting source orders require `unit_orders=[{concept_id, unit_ids,
   rationale}]` in survey, preview and inventory. A claim may order the union of
   alternative analyses; execution projects it onto each tuple's present units.
   Unknown inter-unit order is marked unresolved. The harness does not supply
   historical order or silently reorder tokens within a piece.
4. `segment_morphemes` preserves known units through boundary edits. Optional
   `analysis_claim` on each segmentation explicitly declares complete ordered
   pieces (`unit_id`, nullable `cognate_set_id`, `segment_indices`). Every segment
   must be covered exactly once; repeated occurrences need distinct unit IDs.
   `rationale` records the model's judgment. Unknown/omitted analysis is preserved.
5. `realign` on partial evidence needs `unit_id`. Its rows contain only that
   unit, one per child. When source/candidate selection is ambiguous, supply
   `analysis_ids` in child order, from `get_alignments`; the overlay freezes those
   IDs. Multiple units of one concept can be edited independently.
6. A full `test_proto_assembly` names each `evidence_column_id`, `unit_id` and
   source position. Summary returns counts plus up to eight unmatched columns
   per concept, with reasons. A `ResidueDisposition.evidence_column_id` or
   `SegmentRestoration.before_evidence_column_id` selects an exact alternative
   column; an index alone is accepted only when unambiguous. Restoration's
   optional `unit_id` is an explicit association; omitted association stays unknown.
7. Preview the exact hypothesis before commit: values, confidence, conditioning,
   residue policy/witness/dispositions, restorations, unit order and overlays.
   Re-surveying identical evidence is safe. Changing any of those requires a new
   preview. The harness rejects stale sets/validations with a re-survey/re-preview
   instruction. Empty identity commits remain usable without a preview.

Caps refuse work explicitly; they do not prune a survey to a hidden first reading.
Use a narrower frozen input/beam in a new run when necessary. A failed cap is a
resource/coverage limitation, not evidence for a phonological claim. The flat
46-concept Polynesian fixture requests 32,768 tuples on one concept; its full
survey is explicitly refused. A separately declared one-form-per-concept control
still tests the matching invariant. Do not quote its cost as the full fixture's.

## Offline commands

```sh
conda run -n llm_reconstruction python tools/evidence_contract_probe.py --json
conda run -n llm_reconstruction python tools/diagnostic_suite.py \
  --output-dir /tmp/task03-diagnostics --json
conda run -n llm_reconstruction python tools/evaluate_run.py RUN_DIR \
  --payload FROZEN_PAYLOAD --definition benchmarks/burmish.json --json
```

The probe replays frozen r2/01 Burmic outputs exactly, then runs explicitly named
source-unit controls using transferred legacy values and a stated core/deletion
hypothesis. Those new hypotheses are operator controls, not banked model decisions.
`tools/oracle_ceiling.py` preserves its original whole-string oracle reading and
labels it `legacy_whole_string`; its historical width curves are unchanged.
Source-unit controls and future units-v1 model runs have a different reading and
need separate reports. Keys/targets are scorer-only. Independent complete target
pieces permit `compare_cognate_units`; without them the result stays unknown.
OLD MAN's lexical scope and source-backed tone/phonation equivalences remain open.

## Current migration — units-v2 (task04, 2026-10-04)

The preceding units-v1 migration is retained as history. Read
[evidence repair](evidence_repair.md) before using the current runtime.

- New trajectories: 5.0 (2.0/3.0/4.0 readable). New checkpoints: 3.0; 1.0/2.0
  read for audit but `infer --resume` refuses them explicitly. Behavioral evidence
  hashes include units-v2. Do not weaken these checks as retry policy.
- New inventory artifacts: `evidence_contract_version=units-v2`. FormAnalysis
  representation remains units-v1. Legacy inventories retain old replay; units-v1
  inventories remain readable but cannot execute under changed scope/count IDs.
- `summarize_correspondences()` now returns descriptive recurrence by default.
  `total_set_count`/pagination/filter counts refer to the selected reading;
  `local_set_count` and `recurrence_pattern_count` disclose both totals.
  `reading="local", min_support=1` retains individual per-set workflows.
- A `csp-*` pattern is not a local `csu-*` commitment. Use `shared_claims`:
  `{pattern_id, member_set_ids, proto_segment, confidence, rationale,
  conditioning?, directionality_rationale?}` with an explicitly chosen member
  collection. Supply `commitments=[]` when all choices are shared. Use the identical
  submitted spec for preview and commit. The persisted request expands local
  commitments and stores the original collections in `approved_shared_claims`.
- Changed count semantics are identified by `independent-etyma-v1`; do not copy
  units-v1 support values into current commitments. Source columns, alternative
  occurrences, concepts, supplied etyma and unresolved opportunities are distinct.
  `min_support=1` inspection and justified sparse commitments are allowed.
- `polarize` accepts `set_id`, `unit_orders`, and both overlay IDs. Local queries
  stay local; pattern/tuple queries are labelled recurrence. Witness samples have
  explicit full counts/truncation. Source/unknown witness absence stays visible.
- `realign` accepts local or pattern join handles, verifies positioned source-column
  gain, and reports `joined_source_column_delta` separately from
  `joined_set_support_delta`. This is not new independent recurrence.
- Partial restorations need `unit_id`; a segment in another piece of the same
  outgroup word cannot serve as witness. Named alternative positions and selected
  overlays are preserved. Lost-position historical interpretation stays a claim.
- Diagnostic target layouts are now carried by hidden binding forms, not contexts.
  Explicit unit scores identify `task04-units-v1`; raw evaluator remains task02-v1.
  Underidentified order/lost contrast remain excluded from validated summaries.

Reproduce current offline work in a fresh output directory:

```sh
conda run -n llm_reconstruction python tools/evidence_repair_probe.py \
  --payload runs/benchmarks/burmish.json \
  --banked-inputs runs/sweeps/burmish-gemini-t36-r2/seed-01/trajectories.jsonl
conda run -n llm_reconstruction python tools/evidence_repair_probe.py \
  --payload runs/experiments/task03-interface-smoke-20261003/input.json
conda run -n llm_reconstruction python tools/evidence_repair_probe.py \
  --payload runs/benchmarks/polynesian.json --flat-control
conda run -n llm_reconstruction python tools/evidence_repair_controls.py \
  --output-dir /tmp/task04-morphology-new
conda run -n llm_reconstruction python tools/evidence_contract_probe.py --json
```

The last command now labels new source-unit controls `task04-source-controls-v1`;
the frozen legacy beam/report and operator-control interpretation remain. Old
compact task03 artifacts are not rewritten. The three-concept default filter
covers 9/33 occurrences; full sparse inspection is a declared choice, not hidden
input narrowing. Future generated root beams still require dynamic cap preflight.
