# Current state

Updated 2026-10-05 with task 05 offline protocol/instruction repair; its single
local smoke failed and substantive live usability remains unresolved.
Task 04 units-v2 and task 03 final smoke accounting
is in [evidence results](research/evidence_results.md).
Prompt numbering was updated on 2026-10-04; this entry document uses the current
01–08 sequence. Dated research reports and conversations retain their original
numbering; the shared handoff contains the translation.
The September baseline was
read from the checkout, Claude conversation ending 2026-09-02, and saved experiments.
The audit changes no reconstruction behavior. Task 02 adds report-only binding
annotations and evaluation views; it changes no target forms, selection or traversal.
Last pre-reset commit: `50c4db0` (2026-09-02). The last session reported 535
passing tests; that count was not rerun for the reset. Fresh task 02 checks are below.

## Authority and reading order

This file summarizes implemented behavior and accepted decisions.
[Shared session handoff](session_handoff.md) carries live task status, unfinished
steps and amendments for later sessions; read it when starting or resuming work.
[Research plan](research_plan.md) defines the work packages and dependencies;
[experiment policy](experiment_policy.md) governs testing and expenditure.
The local `prompts/` files implement that plan. CLI/schema behavior is ultimately
verified in code. `proto_inventory_design.md` is a historical notebook: its
original approvals, stop conditions, and “not implemented” labels are dated
claims, not fresh instructions. Do not read its 6,000+ lines before every task.

The September plan supersedes old prompt numbers 01–14, instructions to delete
rule cascades, mandatory five-seed sweeps after every change, demands that the
test count always increase, and “non-overlapping spread” as a universal verdict.

## Project contract and implemented capabilities

Every internal node gets a model session using its direct child lexicons/beams.
Typed tools expose alignments, correspondence patterns, outgroup witnesses,
previous hypotheses, segmentation/realignment overlays, and hypothesis previews.
The model commits either child-to-parent rules or a proto-inventory; deterministic
execution creates parent beams. Both paths are supported, with strict validation,
versioned trajectories (new 5.0, with 2.0/3.0/4.0 readable), reports, and completed-node resume.
No mid-node resume or training backend exists.

Ingestion supports supplied Newick trees, native polytomies, historical targets
versus anchors, and partial cognacy. Benchmarks include Polynesian, Romance,
Burmish, and three synthetic definitions. Offline probes and graded scoring exist.
Sibling evidence is now included by default for disagreeing surveyed sets; its
causal benefit has not been isolated in a controlled comparison.

## The last experiment

Gemini Flash's Burmish sessions often exhausted the default 24 turns. Raising the
cap to 36 produced 11 commitments out of 12 node attempts over four valid runs;
the final two runs committed all nodes. One earlier node stalled on the protocol.
The turn cap was a real limitation but removing it did not establish quality.

| Target node | Four valid 36-turn runs | Interpretation |
| --- | --- | --- |
| `burmic` | 1 exact match / 148 repeated concept evaluations | One NEEDLE hit in one run, scored against a provisional Old Burmese target |
| `proto_burmish` | 0 / 216 repeated concept evaluations; beam exact also zero | No exact root target occurred in the saved beams |

These are 37 and 54 concepts repeated four times, not independent samples of
148 and 216 words. The run-level cost ceilings differed between the two pairs
and neither was reached; do not claim identical configuration hashes.

Artifacts (local only):

- `runs/sweeps/burmish-gemini-t36-r2/seed-{00,01}/result.json`
- `runs/sweeps/burmish-gemini-t36-r3/seed-{00,01}/result.json`
- `runs/sweeps/burmish-gemini-t36/` and `burmish-gemini-t36b/` are **void**
  provider-failure experiments. Do not count their aggregates as linguistic results.

NEEDLE at `burmic` combined `a p` from Achang/Xiandao with Rangoon's `⁴`, yielding
`a p ⁴`. No daughter attests that whole form. At the root in that same run the
output was `a p ⁵⁵`, against targets `ˀŋ a p ⁴` or `ʔ a p ⁴`.
The success demonstrates a useful combination, not the historical validity of the
intermediate binding or a capability exclusive to inventories.

During the September review, stripping tokens composed solely of superscript
digits from both prediction and target raised root exact matches to 5, 4, 3, 4
of 54 in r2/00, r2/01, r3/00, r3/01 respectively. This is an exploratory diagnostic,
not the official metric. Tone alone does not explain the zero.

Historical detail: [§7.29](proto_inventory_design.md#729-the-turn-budget-was-binding-and-the-first-form-no-daughter-attests).

## Task 01 findings, verified 2026-10-02

Failure audit (`docs/research/failure_audit.md`, local only) fixes a 12-concept panel and provides
source/column traces (`docs/research/failure_audit_traces.md`, local only). The new read-only
`tools/failure_audit.py` accepts supplied result paths, checks scores with the
existing all-alternative metric and optionally replays deterministic assembly.
All four saved inputs match their checkpoints; all 364 scored-concept flags and
top edit distances/NED agree. Eleven committed beams and reports replay exactly.
Original run artifacts are unchanged; no inference, downloads or paid calls ran.

The root zero has several causes. All 216 root top predictions disagree with
gold's tone-token sequences, but superscript-only token removal fixes just 16
top comparisons (seven distinct concepts). Source-backed category/contour mapping
is still needed; token disagreement does not prove historical tone error.
CRAWL and FLOWER demonstrate changed morpheme pairing between survey and assembly,
and every intermediate lexicon lacks inherited memberships. Simple controls and
SNOT also expose independent tone/phonological choices. NEEDLE's support-1 Maruic
initial is actually discarded by an Atsi-witness gap, while its exact Burmic
candidate reaches root unchanged and the root explicitly reassigns its tone.

No exact root gold was generated before final beam pruning; all retained input
tuples were enumerated at every committed node. Final pruning is not a demonstrated
cause here. r2/00's Maruic protocol fallback must be disclosed in root provenance;
three fully committed runs still give zero root hits. Old Burmese remains a
provisional proxy. Saved proxy gold already normalizes grapheme/phoneme slash
tokens, so the older unnormalized-source warning does not explain these scores.

Next priorities are 02's evaluation/notation contract, a bounded 03 repair for
traced unit/provenance defects, and 05's explicit sparse/polarity instructions.
These are proposals, not implemented improvements. No largest whole-benchmark
causal effect is established. Read the handoff amendments before downstream work.

## Task 02 evaluation, verified 2026-10-02

Evaluator `task02-v1` is implemented. Read the
[contract](research/evaluation_contract.md), [results](research/evaluation_results.md)
and [migration/commands](research/evaluation_migration.md). Raw exact/NED,
all alternatives and per-word B-Cubed retain their definitions. All 364 saved
Burmish concept score records reproduce unchanged; root remains 0/216, proxy
1/148, with 16/216 segment-only diagnostic hits. Original result/event hashes
are unchanged. Outside-selection IDs/counts and eligible concepts are visible;
the best-daughter selector is labelled gold-assisted oracle. Copying commits
remain commitments. No historical source mapping or model improvement is claimed.

Old Burmese at `burmic` has an explicit provisional-proxy annotation; its raw
score remains while validated-target summaries exclude it. Missing legacy
annotations remain unknown except the documented exact-identity proxy migration.
New family results and sweep views distinguish quality at committed nodes from
end-to-end planned-set coverage, direct fallback, unknown commitment and missing
outputs. Ancestors consuming fallbacks name those descendants; r2/00 root now
reports `maruic`. Abandoned runs can salvage completed stored steps faithfully.
Legacy provider causes stay unknown/unspecified. `inspect-run` text/HTML also
surface proxy and dependency labels for banked artifacts.

Superscript-token diagnostics retain task01-v1 and make ambiguous notation,
unmarked tones, unknown output memberships and OLD MAN scope visible. No tone
category/contour or phonation equivalence is licensed. Morphemes use a separate
complete-piece comparator with independently supplied IDs; real output analysis
awaits task 03. Corpus mapping consistency is deferred; per-word B-Cubed tests
repetition only and can be perfect despite contradictions across words.

Six new diagnostic cases cover complementary retention, conditioning, unequal/
reordered morphology, two-level propagation, identity and unrecoverable contrast.
They state restricted identifiability assumptions, preserve separate keys, and
exclude unrecoverable contrast and morphology order from unique-answer summaries.
Identity scores 0/6 on complementary retention and 3/18 across propagation nodes;
perfect/wrong controls are score fixtures, not live-model performance.
Old synthetic definitions are untouched. Focused checks: 106 passed; portable
suite: 571 passed, 41 deselected, one run. Zero live/paid calls or downloads.

Task 03 is ready under this contract; 05/06 have independent work, and 07 awaits
those interventions before a frozen comparison. See tracked handoff amendments.

## Task 03 evidence, verified 2026-10-03

Task 03 is delivered: [results](research/evidence_results.md) and
[migration](research/evidence_migration.md). units-v1 shares typed pieces and exact
column bindings through parent evidence, with unknown analyses explicit. Final
portable checks: 588 passed/41 deselected; a final provenance guard received 41
focused checks. All eleven old beams/reports replay exactly. Source-unit controls
repair CRAWL/FLOWER pairing but do not increase three-concept proxy exact (1/3).
Exactly one local Gemma smoke had two accepted previews and no valid commit,
ending on ProtocolStallError after 597.3 s. No broad quality improvement is claimed.
Partial scopes can lower support/pooling and increase tool costs; compare these
readings explicitly in 07. Task 05 has concrete malformed-call examples to repair.

## Task 04 evidence repair, verified 2026-10-04

[Evidence repair](research/evidence_repair.md) and
[machine results](research/evidence_repair_results.json) reproduce all review
counterexamples and repair independent-support counts, false mergers, local witnesses
and normal morphology scoring. Exact local scopes remain; default descriptive
recurrence rows support explicit `shared_claims` collections, with local exceptions
and competing conditioned values. No tuple silently assigns cognacy.

Count semantics are `independent-etyma-v1`: supplied etyma, unresolved concept/unit
opportunities, concepts, positioned source combinations and alternative execution
occurrences are distinct. Whole/full-span simplex annotation geometry is equivalent.
Burmic/Maruic retain 543/738 local sets and expose 210/320 patterns. Default filters
cover all 54 concepts but only 437/567 and 1033/1340 alternative occurrences. Sparse
material remains inspectable/committable; these counts are not a quality estimate.

The normal scorer receives hidden target layouts and actual approved parent pieces
through JSONL; correct/wrong/extra/missing/reordered scripted controls pass. Raw
scores and underdetermined order/lost contrast are retained. Trajectories/checkpoints
write 5.0/3.0; old records remain readable, but old checkpoints and units-v1
execution are explicitly refused under current semantics. Both commit shapes and
legacy replay remain. Final portable suite: 607 passed/41 deselected. All 364 banked
scores, eleven beams/reports and four result/event hash pairs reproduce unchanged.
No live inference/provider/model operations occurred. Task 05 owns the next live
smoke and broader protocol/guidance. 07 needs final usability, instrument/cap/manifest
checks and another independent review after 04/05 and relevant 06 work.

## How to interpret earlier Polynesian results

Copying the best single daughter scored 27/46 (58.7%). An oracle selecting the
closest attested form per concept scored 38/46 (82.6%). The latter uses the
answer key and is a diagnostic, not a deployable baseline.

Gemini's three recorded runs scored 0.630 ± 0.022 (sample SD), exceeding the
single-daughter baseline. Their exact hits were all already daughter-attested.
This measures agreement with gold, but does not establish performance beyond
literal selection. It also does not prove that the model merely copied.

The named oracle probes are answer-key-assisted constructions, not live model
scores or universal proofs of representational limits. State the oracle mode,
node, input, width and alignment reading whenever quoting them.

## Accepted decisions and remaining limitations

1. **Keep both commit shapes.** Stage 4 was cancelled on 2026-08-30. The historical
   approval in §11 is superseded. No new deletion decision is pending.
2. **Keep the selection-overlap diagnostic, narrow its claim.** A correct form
   absent from every daughter exceeds literal selection. Matching a conservative
   daughter can be correct reconstruction; an unattested exact hit can still
   reflect memorization. Neither outcome alone proves the model's reasoning.
3. **Old Burmese at `burmic` is a provisional proxy.** The benchmark explicitly
   says it is not the ancestor of all that node's descendants. Preserve old
   scores for provenance, but do not treat this as validated intermediate gold.
4. **New inventories share units-v2 evidence and execution.** Source/model-approved
   pieces and exact column bindings survive into parent beams. Unknown analysis
   stays unknown; compatible claims merge provenance and incompatible claims stay
   separate. Legacy artifacts keep their whole-string interpretation. See the
   [contract](research/evidence_contract.md) and [migration](research/evidence_migration.md).
5. **The runtime prompt now corrects the representational claim.** Rules can emit
   new literal tokens/sequences; empty targets remain forbidden. Task05 qualifies
   sparse/outgroup/morphology judgments and changes instruction/schema/checklist
   hashes separately from task04's evidence repair. Scientific benefit is untested.
6. **Provider failures can contaminate interpretation.** Retry settings remain in
   the compatibility hash; provider outages can become node fallbacks. Planned
   recovery work must distinguish these from a model failing to solve a node.
7. **Statistics are exploratory.** Small, nested samples and multiple changed
   settings do not establish causal effects of model or commit shape. Failure
   exclusions can bias comparisons. Task02-v1 reports conditional quality and
   end-to-end outcomes with explicit denominators; sampling/causal limits remain.
8. **B-Cubed is currently per word.** It measures aligned repetition structure;
   high scores are not evidence of consistent phoneme mappings across a lexicon.
9. **Shared-innovation reports remain deferred.** The specific proposal in
   `shared_innovation_note.md` is not implemented; existing cross-node reports
   are not equivalent to it. A derived inverse rule is not by itself proof of
   a historically shared innovation.

## What is next

Tasks 01–03 provide offline diagnosis, task02-v1 interpretation and units-v1
mechanics. The 2026-10-04 independent review reproduced false merger requirements
on identical scoped retention mappings, cross-etymon mixing in scoped outgroup
profiles, alternative-dependent support, and missing target-piece integration in
normal morphology evaluation. Full-span simplex annotations also receive local
scopes, obscuring cross-word recurrence. Existing focused tests and legacy replay
pass; they do not cover those counterexamples. See the shared handoff for evidence.

Task 04 has delivered the bounded offline repair and verified instruments
described above. Task 05's [protocol revision](research/protocol_revision.md)
provides compact local choices, executable versus commit-ready previews and
immutable same-session inventory handles; full inventory/rule paths remain.
Missing decisions/explanations and stale evidence remain strictly validated.
Both paths freeze supplementary witness/anchor evidence too. System text and
inventory protocol are independently selectable; node notes are now hashed.
Five two-level scripted controls and 633 portable checks pass. The single Gemma
smoke stalled after 15 turns/13 calls, seven rejections and two output truncations;
only an empty preview succeeded, with no commit. Final explicit-list/flat-shape
remediation and reference-word isolation clarifications are offline-tested only.
Task05 is partial at the live usability gate; no second smoke ran. Cumulative
input tokens were 631,609 versus a maximum request of 56,233; configured context
was 262,144. A shorter static prompt did not establish lower cost or better science.
Task 06 remains independent. Task 07 requires an instrument/interface gate, usable
frozen arms and a focused manifest review unless the owner scopes that review out;
06 can be explicitly scoped out for a bounded single-node pilot with demonstrated
interruption/missing-outcome handling. Forward prediction remains deferred.
No broad reconstruction gain has been established by the controls or smoke.
