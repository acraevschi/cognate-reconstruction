# Task 02 — interpretable evaluation and small mechanism tests

2026-10-02, evaluator `task02-v1`, same checkout/branch at HEAD `25f8c93` plus
uncommitted work. [Contract](evaluation_contract.md) was written before code;
[migration/commands](evaluation_migration.md) describe the additive interfaces.
[Compact offline results](evaluation_offline_results.json) retain source hashes
and numerator/denominator counts. Task 01's fixed panel and read-only audit were
reproduced before selecting fixtures. No live model or paid API call occurred.

## Implemented

Reports now separate protocol completion, raw reference agreement, literal
selection overlap, and binding validity. Existing exact/NED/all-alternative
readings remain. New result/sweep views report quality at committed nodes and
end-to-end over the planned target set, with fallback, unknown commitment and
missing coverage separate. Completed steps can be salvaged from abandoned runs;
missing steps cannot. Direct fallbacks are never model commitments; a committed
ancestor remains committed and names failed dependencies. Structured legacy
provider errors have conservative unspecified causes; prose is not parsed.

Old Burmese at `burmic` is explicitly `provisional_proxy` in the definition,
prepared binding, evaluation, JSON and text/HTML reports. Its raw score stays
visible, and its concepts are excluded only from the validated-target summary.
Regression tests prove that removing this target binding leaves the selected
IDs, observed lexicons, tree and `maruic/burmic/proto_burmish` traversal unchanged.
The implementation retains the binding and changes no traversal or target forms.

Outside-selection top/beam hit IDs and counts sit beside eligible concepts and
the gold-assisted best-daughter oracle. Copying commits remain scoreable.
Superscript-only token diagnostics reuse `task01-v1`, preserve boundaries and
phonation, and label attached digits/slash notation ambiguous. Tone-token
agreement does not equate categories with contours. Boundary pieces/counts are
descriptive; cognate units require explicit independent IDs and complete pieces.
OLD MAN's unresolved scope stays explicit. No substring scorer is introduced.

Per-word B-Cubed is labelled repetition structure. A test scores both `p a` vs
`b e` and `p u` vs `t o` as 1.0 despite contradictory cross-word mappings.
Corpus-level scoring is deferred because conditioning, aligned units and a
sampling denominator need independent justification. High B-Cubed is not
linguistic accuracy.

## Banked Burmish findings

The four valid runs retain all 364 concept evaluations, with raw root 0/216 and
proxy 1/148. The proxy hit is NEEDLE in r2/01, outside observed-daughter whole-form
selection; it remains a proxy hit, not validated intermediate historical accuracy.
Raw root tone sequences disagree on 216/216 comparisons. The partition diagnostic
recovers 16/216 segment-only hits, exactly task 01's count; it licenses no further
tone/phonation mapping. r2/00 root names failed `maruic` as a dependency while
remaining a model commitment. All twelve audit IDs stay development cases.

The validated summary contains only the explicitly accepted root reference:
216 planned repeated comparisons, 216 committed outputs, zero exact hits.
All 148 proxy comparisons remain in the separate raw view. Missing proxy gold on
17 selected concepts per run is target ineligibility, not missing model output.
The sample uses target cognacy (`fully_cognate_with_target`, Proto-Burmish
selection source), disclosed in the report and inherited recipe.

## Diagnostic definitions and controls

Six compact cases in `benchmarks/diagnostic/task02-v1.json` use the existing
forward generator; only the morphology case adds explicit observed whole-form
overlays because the DSL cannot insert boundaries. Old synthetic definitions
and published measurements are untouched. Restricted conservative-retention
assumptions are stated; alternative histories/symbol relabelings remain possible.
Generated truth alone is not a proof of identifiability.

| Case | Planned comparisons | Perfect score fixture | Scripted identity | Wrong fixture | Identified distinction |
| --- | --- | --- | --- | --- | --- |
| Complementary retention | 6 | 6 | 0 | 0 | Six independent etyma, two witnesses for each retained position; both branches needed |
| Conditioned change | 6 | 6 | 4 | 0 | Two changed contexts plus unaffected p/t controls; conservative branch fixes the restricted comparison |
| Unequal/reordered morphology | 4 | 4 raw | 0 | 0 | Complete identified pieces recoverable; ancestral order/polarity underdetermined, whole-word validated denominator 0 |
| Two-level propagation | 18 at three nodes | 18 | 3 | 0 | Recurring intermediate/root transformations; root p-initial forms absent from every leaf |
| Identity | 4 | 4 | 4 | 0 | Matching conservative daughters are legitimate copying commitments |
| Lost contrast | 4 | 4 raw | 2 raw | 0 | Alternative all-t ancestor produces exactly the same observations; validated denominator 0 |

The independent morpheme comparator scores the correct pieces as 1.0 even when
reordered, while reporting reordered IDs, extra pieces and nonexact whole
analysis. Wrong pieces score zero. Missing or duplicate IDs are unscorable.
This is a separate unit, not relaxed whole-word accuracy. Real output memberships
remain unavailable until task 03; the evaluator visibly records that limitation.

## Verification and limits

Scripted/fake tests cover successful copying commitments, genuine turn-limit
failure, timeout interruption, unknown cause, direct/descendant fallback,
abandoned salvage, commit without a saved output, missing concept, multiple
alternatives, proxy annotation and conflicting saved steps. Sentinel target tokens
and annotations cannot enter initial contexts, tool definitions or alignment
results; changing only targets leaves initial payloads identical. Checked-in
source-extracted fixtures cover NEEDLE, FATHOM, MONKEY, CRAWL and OLD MAN.

Focused evaluator/metrics/sweep/Burmish/identity/synthetic/inspect/historical/failure
group: 106 passed. One portable suite run:
`conda run -n llm_reconstruction python -m pytest -q -k 'not local_run_artifacts' --tb=short`:
571 passed, 41 deselected in 49.37 seconds. Whitespace and local-document links
also checked. A nonrequired system-Python compile check hit the macOS cache sandbox;
the required conda tests imported and executed all changed modules successfully.
After the portable run, compact text/HTML diagnostic readings, partial-result
status and piece-container equality received focused reporting/lifecycle checks:
38 passed. These changes do not alter old scores or model evidence. The compact
result records the HEAD plus dirty code/fixture manifest hash for the tested state.
Original result/event hashes and all saved score fields are verified independently;
full exports stay under `/tmp`. No historical source notation mapping was learned
or asserted, and no inference capability improvement is claimed.

Task 03 can now preserve approved morpheme/column identity under this contract.
Task 04 should keep tone-category decisions qualified. Task 05 supplies better
prospective failure causes without rewriting unknown legacy causes. Task 06 uses
this frozen evaluator with separate 03/04 arms and the development/held-out boundary.
