# Evidence and execution contract — task03 units-v1

The bounded repair addresses two audited failures. In r2/01 CRAWL, the survey
places Achang/Xiandao's core against Rangoon's first cognate morpheme, whereas
whole-word execution places it against the second `tθ` morpheme at column 5.
FLOWER's core set 7 occurs before the boundary in Achang/Xiandao and after it in
Rangoon; whole-word execution couples the wrong onsets and leaves an orphan `w`.
See audit (`docs/research/failure_audit.md`, local only) and traces (`docs/research/failure_audit_traces.md`, local only). NEEDLE's
witness-gap loss is a separate sparse-material judgment: expose its exact column
and permit an explicit disposition; never insert the reference onset automatically.

Two practical designs were considered. A saved per-concept assembly plan alone
can freeze the inspected columns, but loses their meaning at the next node and
cannot distinguish identical surfaces with different analyses. Typed candidate
analysis alone preserves pieces, but matching commitments by reflex tuple still
allows one unit's decision to fire in another. The chosen small combination is
typed piece analysis plus exact column bindings built by a shared unit aligner.
The model approves these bindings by previewing and committing the hypothesis.
No new inference model or widened beam is proposed.

Source pieces carry source form, membership, cognate set, and exact zero-based
segment positions. Reconstructed pieces carry emitted positions and source/column
provenance, with cognacy inherited only from an explicit source unit. Unknown
pieces stay unknown. Whole-form and unannotated forms have a conservative whole
unit path. Alternative whole-form memberships become separate candidate analyses.
Uncovered segments and structural boundaries remain explicit, never discarded.

An evidence column names the concept, ordered child semantic inputs, piece,
alignment reading, overlays and column position. Equal reflex tuples are only
aggregated within compatible unit scopes. An inventory binds its set IDs to the
exact columns it surveyed; execution cannot apply a set outside that binding.
Survey, preview and commit use every retained candidate analysis, not a hidden
first/last reading. Paginated tools return compact sample pointers; full previews
return the source unit and column IDs needed to inspect a miss.

Piece order follows the union of source orders when those agree. Conflicting
orders require an explicit model claim specifying the unit order; no lexical
sorting or convenient splitting chooses ancestral morphology. That claim changes
the evidence reading and requires a new survey and preview. Realignment preserves
tokens and source positions; ambiguous whole-word edits on partial units are
refused with remediation to specify the unit. Segmentation remaps indices through
boundary-only edits and changes the evidence revision.

Candidates merge by surface plus compatible unit claims (unit ID, cognate ID,
kind, emitted positions and order status). Different source histories merge into
the candidate's source/column unions and remain separately recorded in derivations;
they do not split branch-support mass. Incompatible analyses with equal surfaces
remain separate. Distributions record pre-prune/pruned counts; rule diagnostics
also count pruned partial states. Cartesian work is counted before alignment:
4,096 tuples per concept, 65,536 per node and a conservative 250,000 projected
column limit. Exceeding a limit rejects the operation with required/allowed counts
rather than dropping an analysis. Rule combinations also refuse a product above
4,096. Caches include concept, child order, segments, full provenance and overlays.

Mixed, overlapping or discontinuous source annotations take an explicitly noted
unknown whole-form fallback, retaining every supplied membership as provenance.
The model can replace that unresolved partition through `analysis_claim`. This
does not import reference memberships or equate units from their spelling.

A validation is exact to hypothesis, evidence revision and overlays. Changing a
proto value, confidence, conditioning, residue disposition, restoration, piece
order or overlay requires previewing that hypothesis again. Re-surveying identical
evidence is idempotent. New trajectories identify changed semantics; 2.0/3.0
remain readable. Old inventories replay on their legacy execution path; old
checkpoints cannot resume into units-v1 without an explicit incompatibility error.

The model chooses proto values, deletions, residue witness, restorations,
conditioning and any unresolved ancestral order. The harness carries those
claims, aligns identified pieces, checks exact provenance and reports uncertainty.
It neither assigns cognacy from resemblance nor imports reference analysis.
Task02-v1 and task01-v1 diagnostics retain their definitions. Offline probes are
answer-key-assisted controls, not live quality estimates; real tone and OLD MAN
scope remain unresolved. Results, measured costs and migration details will be
recorded in the companion task 03 result document.

The conservative scope is an explicit tradeoff: partial-piece sets are scoped
to their supplied unit ID. Their support is counted within that scope, rather
than automatically pooling similar tuples across different etyma. Whole-form
patterns retain their ordinary recurrence reading. This can increase set/tool
size and lower reported support, and must be included in later cost/quality
comparisons. It does not license interpreting support-1 material as innovation.
`derived_rules_scope=unscoped_view` marks the inventory's DSL view: the DSL cannot
express exact column/unit restrictions, so it is an approximation rather than
an executable substitute for the approved assembly. Rule commits remain executable.

Runtime and migration details: [evidence migration](evidence_migration.md).

## Current amendment — task04 units-v2, 2026-10-04

The task03 design above is historical. Current implementation/result:
[evidence repair](evidence_repair.md), [machine results](evidence_repair_results.json).
Exact local scopes and column bindings remain; whole-form/full-span simplex units
now have equivalent geometry/local scoping. Default surveys return descriptive
`reading="recurrence"` rows with `csp-*` IDs and explicit local `member_set_ids`.
Use `reading="local", min_support=1` for individual `csu-*` commitments. Recurrence
rows do not declare cognacy or automatically authorize execution.

`shared_claims` explicitly selects a pattern's local members and one proto
value/null, confidence, rationale and optional conditioning/directionality. Only
those members expand into ordinary local commitments. Stored expanded requests
and `approved_shared_claims` retain both execution and approval provenance.
Different member collections/choices require exact re-preview; exceptions are
excluded and committed locally, and competing conditioned values remain supported.

Count semantics `independent-etyma-v1`: support is distinct supplied etyma plus
separately reported unresolved concept/unit opportunities. `etymon_count`,
`unresolved_unit_count`, `concept_count`, distinct positioned source combinations
(`source_column_count`) and alternative execution columns (`occurrence_count`)
are separate. A supplied etymon ID is not source attestation or proof of historical
independence. Repeated columns/alternatives do not add independent support. Sparse
values can be explicitly committed; the filter is not a linguistic prohibition.
Realignment joins verify source-column gain, reporting that and independent-support
gain separately. Contrast checks require actual reflex-tuple distinctions.

Local outgroup profiles/scoped polarize retain concept/unit/column/source pointers;
recurrence evidence is labelled separately. Counts are complete, witness examples
bounded with explicit truncation; absence remains diagnostic, not a positive witness.
Partial restorations require the named unit in the cited outgroup. Targets stay
scorer-only. Normal diagnostic target layouts and reconstructed parent pieces reach
ordinary serialized run evaluation, preserving task02-v1 raw scores and the
underdetermined order/lost-contrast readings. Piece diagnostics record
`task04-units-v1` where measured.

Trajectories/checkpoints now write 5.0/3.0. Earlier records remain audit-readable;
old checkpoints and units-v1 execution require their original semantics/checkout.
The piece representation stays units-v1. Legacy whole-string replay is unchanged.


## Task05 exact-reference amendment — 2026-10-05

[Protocol revision](protocol_revision.md) adds compact local decisions resolved
through exact IDs, executable versus commit-ready explanation reporting and an
immutable same-session inventory handle. It changes instruction/native-schema/
node-checklist hashes, not the units-v2 denominator or piece execution. Proto
values/nulls, confidence and scientific reasoning are never inferred. Edited
choices, collections, explanations, overlays or evidence require a new preview.
Supplementary witness/anchor digests now join active-column revision checks for
both inventory paths. Full payloads/rules and historical readers remain supported;
handles are not checkpoint state. Live usability is qualified in the result, not
inferred from scripted controls or a shorter prompt.

## R01 amendment — choice identity and annotated export, 2026-10-23

Units-v2 allows several conditioned values on one local set; only an identical
`(set_id, conditioning)` pair is refused. Column resolution keeps the documented
order `(-confidence, proto_segment, set_id)`. Reporting now identifies competing
applicable claims by `(set_id, conditioning, proto_segment)`. Additive fields:

- `ColumnResolution.competing_choices` and `decided_by_tie_break`;
- `ReconstructionDiagnostics.columns_with_competing_choices` and
  `columns_decided_by_equal_confidence`.

`columns_decided_by_tie_break` keeps its historical competing-set meaning.
`FamilyReconstructionResult.internal_nodes[].best_lexicon` now carries the top
candidate's analysis as-is; no membership is inferred from spelling. See
[R01 repairs](post_review_contract_repairs.md).
