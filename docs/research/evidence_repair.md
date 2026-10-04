# Task 04 — evidence semantics repair

2026-10-04. Offline implementation on `burmish-session-evaluation-units`, HEAD
`cb16374461e4a3e5be38e5ca32e90b9d08e8ad4d`. The checkout matched the independent
review's reference snapshot. Inherited task 01 local/uncommitted files and entry
document changes were preserved. No inference, provider requests, discovery,
model switches, downloads, push or PR creation occurred.

## Evidence reproduced before changing behavior

The four small behavioral regressions failed on the starting runtime, then passed
after repair. Their initial output was retained in `/tmp/task04-before-counterexamples.txt`.
The complete frozen payload has 54 concepts and SHA-256
`2febdd6da0ca44fe37dbc72af8627d92677807d05c3c84fadb6594cf9e51ace2`.

| Observation | Starting behavior | Repaired behavior |
| --- | --- | --- |
| Unrelated B alternative `p s`, with unchanged identified core `p:p` | Local core support 1→2 | Support remains 1; positioned source columns and alternative occurrences report 2 |
| Independent units each `p:p→p` | Preview accepted; commit rejected with `missing-directionality-rationale` | Commit accepted without an invented merger explanation |
| Local etyma `p:f`, with O=`p` / O=`t` respectively | Both profiles show both tokens | Each local profile and scoped `polarize` shows its own token and occurrence pointers; recurrence aggregate is explicitly labelled |
| Four generated morphology targets | `annotated_units()` is null for all four | All four have complete scorer-only memberships; actual assembled output is graded through the ordinary run evaluator |
| Whole membership versus full-span simplex slice | Whole path pools globally; full-span slice gets an etymon-local scope | Both use the same whole-unit geometry and local scope; original source membership/provenance survives |

The frozen counts also reproduced exactly: Burmic legacy/units-v1 130/543 sets,
519 support-1 and four multi-concept sets; Maruic 150/738, 576 support-1 and none
multi-concept. FATHOM, MONKEY and I remain locally scoped; phonological recurrence
is now separately retrievable. The initial counts include different reading,
alternatives, unidentified/additional material and unit alignment. They are not
a pure pooling ablation.

Local task 01 audit/traces and task03's input, events, instructions, manifest and
outcome exist. The smoke retains two accepted previews of the same hypothesis,
no valid commit, and `ProtocolStallError`. The full independent review conversation
and former review launcher/brief are not repository-local evidence; its tracked
amendment supplies the counterexamples. No finding needed an invented trace.

## Smallest coherent repair

`units-v2` keeps exact local execution sets and adds descriptive recurrence rows
over compatible reflex patterns. It reuses the existing local commitments,
conditioning, column bindings, preview validation and assembler. A tuple aggregate
makes no historical-equivalence claim and never changes inherited cognacy.

`summarize_correspondences` defaults to `reading="recurrence"`. Its rows have
`csp-*` IDs and complete explicit `member_set_ids`. `reading="local"` returns
`csu-*` execution sets. Both share the evidence revision and work counters. The
same reflex pattern can have local exceptions; observed context unions are shown
for inspection, and proto conditioning is still evaluated on the actual columns.
Structural boundary patterns are kept separate from material patterns. Source
and model analyses, unknown/unresolved material and incompatible equal surfaces
remain distinct. Unknown whole forms retain their conservative shared whole-unit
fallback, with unresolved concept/unit counts and no inferred cognate ID. A model
can supply distinct occurrence analyses through `analysis_claim` where that whole
reading needs local exceptions. No sound-change database or automatic cognacy inference was added.

A `ProtoInventorySpec` / `test_proto_assembly` may contain `shared_claims` alongside
ordinary `commitments`. Each shared claim explicitly names `pattern_id`, selected
`member_set_ids`, required `proto_segment` (including explicit null), confidence,
rationale, and optional conditioning/directionality rationale. The harness expands
only those members, deriving their reflexes and counts. A pattern ID alone is not
an executable commitment. The ordinary uniqueness check rejects a local/shared
overlap in the same environment; competing conditioned values remain expressible.
Exclude a local exception from a collection and give it a separate commitment.
Exact column dispositions, explicit unit analyses and conditioning remain available
for more local distinctions; there is no new arbitrary occurrence grouping engine.

One shared value can therefore name dozens of occurrences with one transcription
of its linguistic choices. The stored request contains the expanded local
commitments; `approved_shared_claims` retains the original approved collections.
Serialization checks their consistency. The submitted collection and every value,
confidence, conditioning, policy, restoration, order and overlay are in the exact
hypothesis digest. Changed member selections require a new preview. Parent pieces
retain their original unit identity, source positions and approved column IDs.

Alternatives considered: retaining only local sets would leave repetitive approval
work; automatic global tuple pooling would silently authorize historical
equivalence assumptions; a separate sound-law/grouping framework would duplicate
working machinery. The default was tested with the new denominator: local
`min_support=2` returns no frozen Burmish sets, so a default recurrence reading is
necessary to make the first survey usable. Individual per-set scripts now request
`reading="local", min_support=1` explicitly.

## Count contract: `independent-etyma-v1`

| Field | Meaning in units-v2 |
| --- | --- |
| `etymon_count` | Distinct supplied `cognate_set_id` values, across concepts/columns; a supplied identifier is not proof of historical independence |
| `unresolved_unit_count` | Distinct `(concept_id, unit_id)` opportunities without a supplied etymon; expressly unresolved, not inferred independent etyma |
| `support` | Sum of those two counts; copied/re-derived locally, never a model estimate |
| `concept_count` | Distinct concepts; may exceed support when one supplied etymon appears in several concepts |
| `source_column_count` | Distinct unit and positioned child-source combinations; repeated tuple executions of one combination are deduplicated, alternatives can add combinations |
| `occurrence_count` | Distinct exact execution column IDs, including candidate/alternative-dependent possibilities |

Repeated positions or unrelated alternatives do not increase independent support.
Source-column counts can increase and must not be read as independent recurrence.
`min_support` is an inspection filter, not a ban on sparse reconstruction.
Unknown, boundary and restored material do not acquire supplied etymon IDs from
similarity. Repeated occurrences still require distinct unit IDs; a shared cognate
ID across occurrences is counted once, and incomplete/duplicate scorer analyses
remain unknown/ambiguous.

`realign.joins_set_id` now verifies increased **source columns**, since a genuine
alignment edit inside one etymon can leave independent support unchanged. It
accepts a local set or descriptive pattern handle. `joined_source_column_delta`
reports that gain; `joined_set_support_delta` keeps the independent-support delta
separate. Overlays invalidate local/pattern IDs and exact previews as before.

## Contrast and witness repairs

Contrast detection now requires differing actual reflex tuples among the
unconditioned sets sharing a proto value. Different scope IDs alone are not a
contrast. Deletions and actual differing-reflex reductions retain directionality
requirements. Conditioning requirements/claims are unchanged. The harness records
explanations and does not judge their historical truth.

Local outgroup retrieval uses the supplied concept and unit, compares each
outgroup alternative separately, and verifies the active children's exact token
positions against the approved column. A combined alignment that moves those
positions cannot provide a local witness. Witness records carry concept, unit,
active evidence-column ID, node, token and positioned sources. A known/partial unit
requires a supplied matching outgroup unit/cognacy; missing outgroup annotation
is not filled from surface similarity. Unknown whole forms retain an explicitly
unresolved whole-form comparison path. Outgroup alternatives are not multiplied
into a joint product. Work preflight has the same 65,536 pair / 250,000 projected
column envelope; refusal is explicit in the survey's outgroup note. `outgroup_work`
records pair/column/alignment costs.

Survey profiles show presence only. Scoped `polarize(set_id=...)` uses the same
retrieval; pattern or tuple queries are labelled recurrence. `polarize` still
reports observed gaps diagnostically, but never turns them into positive witnesses
or evidence against a value. Survey witness pointers are sampled to eight per
profile, polarize to 24, with full `witness_count` and explicit truncation. Counts
use the complete reading. Narrow with local set/concept IDs to inspect a source.
One-child or deliberately unscoped legacy queries keep their labelled legacy path.

Restoration checks preserve concept and named unit. Partial evidence requires
`unit_id`; a token in a different piece of the same outgroup word does not license
it. Named alternative positions no longer select the last alignment for a concept.
Selected segmentation/analysis overlays also reach witness verification. A wholly
lost position still has no matching active column: position/polarity are model
claims, while cited presence in the named unit is mechanically checked. Targets
and answer keys never enter witness retrieval.

## Ordinary morphology evaluation, including parent propagation

`build_case` attaches the supplied `target_unit_layouts` only to hidden target
bindings, with scorer-only provenance. It does not change target tokens or observed
lexicons. `task02-v1` exact/NED/all-alternative definitions are retained. Explicit
piece diagnostics identify `unit_evaluator_version="task04-units-v1"`; unannotated
real targets and OLD MAN's unresolved lexical scope remain unknown.

`tools/evidence_repair_controls.py` runs five operator-selected hypotheses through
survey, preview, commit, two-level traversal `((a,b)x,c)p`, JSONL serialization and
`evaluate_run`. The provider uses observed units only. The test changes target
layout IDs to a scorer sentinel and proves all model-visible requests/tool schemas
and results remain identical. A newly exposed defect in post-commit recomputation
was repaired: `_held_out_unaccounted_rate` now retains approved `unit_orders`.

| Scripted control | Raw root exact / 4 | Unit reading for each target | Validated whole-word denominator |
| --- | --- | --- | --- |
| Correct | 4 | 2/2 complete pieces, no extras/missing | 0 |
| Wrong core | 0 | 1/2; wrong piece kept visible | 0 |
| Extra piece | 0 | 2/2 target pieces, extra `u4`; overall unit exact false | 0 |
| Missing piece | 0 | 1/2, missing piece named | 0 |
| Reordered | 0 | 2/2; order difference and nonexact whole analysis reported | 0 |

All ten node sessions commit, and parent evidence carries the intermediate pieces.
These are scripted/operator controls, not model ability or quality gains. Ancestral
order and lost contrast retain their underdetermined readings and raw scores.
`diagnostic_suite.py` now also exposes the normal run controls, alongside its
historical standalone piece comparator and perfect/wrong score fixtures.

CRAWL/FLOWER/NEEDLE source controls still replay the legacy beam/report first.
CRAWL loses the duplicated glide, FLOWER keeps the correct core pairing, NEEDLE is
unchanged; raw three-concept proxy exact remains 1/3. The interpretation remains
labelled operator control. Tone, lexical scope and historical polarity are separate.

## Frozen costs, coverage and caps

The complete input was retained; no hidden beam/source narrowing was used.
Numbers below compare the frozen leaf-node input, not unknown future model beams.
Full machine measurements and SHA-256 provenance are in
[evidence_repair_results.json](evidence_repair_results.json).

| Quantity | Burmic | Maruic |
| --- | ---: | ---: |
| Legacy / v1 local / v2 local sets | 130 / 543 / 543 | 150 / 738 / 738 |
| v1 support-1 / v2 local support-1 | 519 / 543 | 576 / 738 |
| v2 recurrence patterns | 210 | 320 |
| Default recurrence support≥2 patterns | 90 | 113 |
| Local sets covered by that filter | 423/543 | 531/738 |
| Alternative occurrences covered | 437/567 | 1033/1340 |
| Concepts with any default-filter coverage | 54/54 | 54/54 |
| Candidate tuples / aligner calls | 57 / 62 | 91 / 106 |
| Projected column upper bound | 926 | 2460 |
| Default 30-row page, without outgroups, bytes | 36,135 | 36,785 |
| Individual / shared full claim serialization, bytes | 138,622 / 60,272 | 192,859 / 89,009 |

The byte ledger supplies the measured serialized sizes; page bytes use JSON with
spaces and UTF-8. Local sets plus recurrence rows increase full stored inventory
size (about 348 KB / 502 KB before added work metadata), despite reducing repeated
choice transcription. Default outgroup pages cost about 98 KB / 73 KB with bounded
witness samples, at 189/116 unit-form pairs and 177/63 aligner calls. Performance
is not inferred from bytes, and cumulative tokens are not maximum request/context
size. Task 05 owns further preview/transcription ergonomics.

A same-reading local→recurrence comparison changes only descriptive aggregation.
Legacy→v2 comparisons also change source-unit alignment, alternatives and extra
material, so the increase over legacy is not attributed to a single cause.

The preserved three-concept smoke input hash is
`44c08e488d907ad9ec5e9cedef89ebd282606f220d47f410c3f75c517e7ed97e`.
It has three tuples, 33 local sets, 28 patterns; the default filter shows four
patterns covering 9/33 occurrences, with some coverage of all three concepts.
That is measurable but weak sparse coverage: 05/07 must inspect `min_support=1`
and freeze their chosen filter, rather than treat a small default page as complete.

A separately labelled retained r2/01 historical root input covers all 54 concepts
in 65 tuples (legacy analyses stay unknown); it fits current caps. This is an
operational cost reading, not a prospective repaired root reconstruction. Future
model beams must be preflighted again. An explicit all-leaf flat Polynesian control
still refuses concept 1212's 32,768 tuples against 4,096. The native Polynesian leaf
nodes were measured separately; no flat-input narrowing was substituted.

## Compatibility, validation and next tasks

New inventories are units-v2; piece representation remains units-v1. New trajectories
write 5.0 and checkpoints 3.0. This checkout reads historical 2.0/3.0/4.0 trajectories
and 1.0/2.0 checkpoints without restamping them. Checkpoint 1.0/2.0 resumes are
explicitly refused under current semantics. units-v1 inventories remain audit
readable but require their original checkout for execution. No safe automatic
set-ID/cognacy migration is claimed. Legacy inventories still replay through their
original whole-string path. Both commit shapes remain supported.

Focused checks: 162 passed (9.40 s). The first portable run found two integration
issues (605 passed, two failed, 41 deselected, 56.32 s): polarize had dropped
its diagnostic gap observation, and the new rejection code was absent from the
closed vocabulary. Those were repaired; 78 focused integration checks passed.
Final portable suite: 607 passed, 41 deselected, 56.03 s. The second full run
was justified by those failures; no further full-suite repetitions were made.
The compact result records both attempts.
Historical audit freshly reproduces all 364 saved score records and eleven
beams/reports; all four result/event hash pairs remain unchanged. No old artifacts
or task 02/03 result documents were rewritten.

The unavoidable runtime wording changes are confined to the new count denominator,
sparse commitments, local versus recurrence IDs/shared selections, scoped polarize
arguments and actual-reflex contrast requirements in tool/schema/commit notes.
The broader linguistic guidance (including the old cascade assertion), protocol
handles and preview commit-readiness belong to 05. These minimal wording changes
are part of the evidence-mechanics package and must not be described in 07 as an
unchanged-instructions assembly-only intervention.

05 is the next ready task: read this result and the updated contracts/migration,
verify actual tool schemas, reproduce malformed calls offline, then own the next
bounded live smoke. 06 preserves the 3.0/5.0 semantic resume boundary. 07 requires
normal-evaluator instrument checks, final 05 commit usability, actual arm/input
caps and a manifest that identifies package versus isolated changes. Relevant 06
work must be complete or explicitly bounded/scope-out. Arrange another independent
review after 04/05 and relevant 06 work, before comparative inference. Updating
these prerequisites dispatches no task; the owner chooses when to start.
