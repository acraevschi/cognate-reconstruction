# Current state

## Post-review qualification — 2026-10-08

The independent assessment completed on 2026-10-07 and is local-only at
`prompts/review-after-tasks01-06-report.md`. Its fresh verification reproduced
364 historical score records and eleven committed beams/reports; 167 focused
tests passed. Those are review observations, not tests rerun during this prompt
preparation. The review also reproduced four gaps: token-conditioned JSON/handle
commit failure, abrupt first-node resource-history reset, missing same-set
condition-overlap diagnostics, and dropped analysis in `best_lexicon` export.
Current traversal/normal evaluation use the analysis-preserving beam path; the
export defect does not negate those propagation controls.

No fixes or new inference have been performed by the follow-up prompt preparation.
Task05 therefore has an additional offline contract gap as well as unproven live
usability; Task06's delivered graceful recovery does not establish safe cumulative
caps over every hard-interruption window. Preserve their historical test results.

The owner requested an early stronger-model comparison on the repaired harness
before substantial redesign/pivot. R01 repairs, R02 prepares instruments/manifests,
and R03 separates supplied-hypothesis usability from linguistic judgment for a
local baseline and one stronger candidate. Local success is not a prerequisite to
the stronger arm. Most software tests are deterministic; older hosted Gemini
commit success and recent local Gemma failures are not a controlled model comparison.
See the shared handoff and research plan for the current R01–R07 sequence. Sections
below retain their dated historical task numbering/status and implemented evidence.

Updated 2026-10-05 with task 06 offline provider recovery and interruption accounting.
Task05's single local smoke failed; substantive live usability remains unresolved.
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

## R01 contract repairs — verified 2026-10-23

[R01](research/post_review_contract_repairs.md) reproduced and repaired all four
review findings offline at starting HEAD `63af18d`, committed on branch `r01-contract-repairs`. There was no
inference, model operation, paid call or dependency change.

1. **Token-conditioned claims.** These now preview, commit, persist to JSONL and
   checkpoints, re-preview immutably and reach parent nodes in both native
   profiles. Strict validation is retained.
2. **Abrupt loss.** New checkpointed runs journal each counted turn, request and
   tool call before it happens. Turn and tool caps count lost effort. Cost and
   elapsed time stay unknown and conservatively refuse their caps.
   `history_complete` stays false. A legacy checkpoint without a summary is not
   certified complete.
3. **Overlapping conditioned choices.** Overlapping choices on one set are
   reported by choice identity, with additive fields, and the emitted values are
   unchanged.
4. **`best_lexicon`.** It carries the top candidate's analysis.

Model-visible instruction, schema and node-note digests are unchanged; the
assembly preview's result carries the new ambiguity fields. An independent
review on 2026-10-25 found three journal defects (a graceful failure read as
abrupt loss, a torn tail breaking a later resume, an unwritable journal
producing fallbacks); all three are fixed, see section 6 of the R01 report.
Portable suite: 750 passed, 41 deselected. JSON dumps of boundary-token sets are now
sorted, so stored-handle digests no longer depend on the hash seed. The banked replay still agrees on 364/364
scores and 11/11 beams and reports. These fixes establish interface and
accounting behaviour only, not live usability or reconstruction quality.
Task05's offline protocol claim now includes token-conditioned JSON. Task06's
cumulative caps hold for journaled abrupt loss, not for effort lost with its
journal. R02 is ready to start.

## R02 diagnostic instruments — prepared 2026-10-25

[R02](research/model_diagnostic_design.md) prepared offline, on branch
`r01-contract-repairs`, everything R03 needs; no model was called.

- **Stage A** (`r02-stage-a-v1`, `r02-usability-v1`): one node with a supplied
  nonempty token-conditioned shared claim, a source-unit decision (a pooled
  `[m, m]` pattern versus the suffix unit's own sets), one specified revision
  and a handle commit. The scripted operator succeeds in both profiles through
  `cli infer` and the real LiteLLM adapter; scripted deviations are classified.
- **Stage B** (`r02-stage-b-v1`, `r02-decisions-v1`): 16 synthetic etyma at node
  `x` of `((a,b)x,c)r`, 18 identified retain/absent opportunities in the correct
  cognate unit, 2 unresolved items and 6 matched counterevidence pairs. Copying,
  uniform and no-outgroup cue policies score 8–12/18 and 0–3/6 pairs; the
  deployable outgroup-witness rule is the identification rule and scores 18/18.
  (Corrected 2026-10-25 from an earlier draft's 14/16/5 counts.)
- **Harness changes:** `--price-table` (versioned explicit prices; upper-bound
  cost; digest-joined only when used); Gemini 3+ thinking level sent explicitly,
  because LiteLLM 1.81.16 turned `medium` into `high` (or refused it) for
  `gemini-3.8-flash`; whole-batch ledger and serial launcher; `inspect_run`
  shows the abrupt-loss usage keys.
- **Candidate manifests** under `runs/experiments/r02-model-diagnostic-20261025/`
  bound Gemini 3.8 Flash at a worst case of US$4.70 within the owner's US$5 /
  60-minute ceiling, and the local arm within two hours. The required read-only
  manifest review, launch preflight and the launch itself belong to R03.

## R03 stronger-model diagnostic — measured 2026-10-25

[R03](research/model_capability_diagnostic.md) ran R02's Stage A/B once per
model, serially, on the same code, evidence, profile, instructions and tools.

- **Pre-launch repair.** The required read-only review found that LiteLLM
  1.81.16's Gemini schema mapping keeps only a top-level `anyOf`, so
  `test_proto_assembly` reached Gemini with none of its 12 arguments. The
  published `anyOf` is removed. The validator still refuses an omitted claim
  collection, and a wire test now covers every tool in both profiles. The
  stored-hypothesis tool-schema digest is `628f0f32…` (was `dd58d427…`).
- **Gemini 3.8 Flash** (medium thinking, temperature 1.0):
  - Stage A `success`: supplied conditioned hypothesis, revision, handle commit, readback.
  - Stage B node `x`: 18/18 model-committed correct and 6/6 matched pairs, all by explicit claims, in the correct units; both unresolved items committed at confidence 0.5. That equals the panel's deployable identification rule: necessary-condition evidence use on synthetic development material, not discovery.
- **Gemma 4 26B A4B** (LM Studio, MLX 6-bit, temperature 0.1): Stage A
  `no_commit`. Seven of eleven calls were invalid submissions (invented fields
  or IDs, stale IDs after a re-survey), ending in `ProtocolStallError`. There is
  no local judgment outcome.
- **Resources.** Gemini US$2.4754 upper bound (no unknown-cost or retried
  request; about US$0.81 using the cached-token counts Gemini reported) and
  690.5 s, within US$5 and 3,600 s; local 283.9 s. The external console check is
  pending.
- One trial per arm: feasibility, not reliability or a model ranking. The
  current harness is usable by this Gemini configuration and was not usable by
  this local one. Interface redesign is deferred; R04 is narrowed to a judgment
  panel that the outgroup-witness rule does not solve.
- **R03b follow-up** (separate experiment): the same local Stage A, with
  Gemma's published sampler sent explicitly (temperature 1.0, top_k 64, top_p
  0.95, repeat_penalty 1.0, min_p 0), again ended `no_commit` with the same
  error classes. A harness gap was found: `unit_orders` naming an unknown
  concept was accepted as a no-op that renamed every set ID.
- **R03c follow-up** (separate experiment, same code as R03b): Qwen3.6
  35B-A3B (MLX 4-bit) at its card's precise thinking sampler (temperature 0.6,
  top_k 20, top_p 0.95, min_p 0, presence 0) passed Stage A with 0 rejected
  calls. On Stage B it committed `retain` everywhere: 10/18, 0/6 pairs,
  baseline-level; it read outgroup witnesses correctly but treated outgroup
  absence as a tie. So Gemma's Stage A failure is not general to local models
  with this interface; the local judgment gap remains.
- **`unit_orders` fix** (after R03c; no run uses it yet): `evidence_map` now
  refuses a `unit_orders` entry whose concept has no form at the node, with
  the valid concept IDs (`alignment-failed`). Supersets of a concept's units
  stay accepted; a concept present in only one child is still not refused.
- **R03d follow-up** (Gemma on the fixed code, R03b's sampler): Stage A
  `no_commit` again, 7/9 rejected, all claim-structure errors (invented fields,
  pattern IDs as choices, missing `support`, a set both in `choices` and a shared
  claim). Gemma sent no `unit_orders`, so the fix was not exercised. Its
  reasoning fell to 1 token per turn from the first preview, as in R03/R03b.
  Offline diagnosis (report §17a): the harness does not send `reasoning_content`
  back, and Gemma's template renders the tool loop as one model turn with no
  thinking cue. So Gemma imitates its own visible thoughtless calls; thinking
  returns whenever a new model turn starts. Gemma's failures are therefore
  "as deployed by this harness"; carrying reasoning back is tested in R03e.
  Qwen's template forces `<think>` each step, so it was unaffected.
- **R03e follow-up** (Gemma, reasoning resent within the tool loop, new
  `--reasoning-history keep`, 16k budget + 200-token heads; default stays
  `drop`): thinking was sustained on every step and Stage A **succeeded** (6
  calls, 1 rejected), Gemma's first. Stage B did not commit: three
  16,384-token thinking-only responses at node x (non-converging analysis, no
  outgroup use); peak prompt 39k. Report §18 also records per-node context
  measurements (real-data Gemma median peaks 54k–90k, tool results up to 129k)
  and context-budget design options; none of those are implemented.
- **`--reasoning-history auto`** (2026-10-28): decides `keep`/`drop` per model
  from its chat template (keep only when resent reasoning is rendered and the
  template continues one model turn through tool results), with a live server
  probe. Resolves Gemma 4 → keep, Qwen3.6/3.8 → drop, Gemini → drop. `auto`
  is the default; only `keep` enters the digest (dropping runs hash as
  before), and every decision is written to `run_summary.json`. When nothing
  can be inferred the default falls back to drop with a warning (report §20).
- **Creation-time tool-result slimming (Option 1a, R03f).** Implemented:
  `exceptions` no longer list `target_absent` forms; `get_alignments`
  `detail="summary"` omits pairwise views; `search_forms` hits and cascade
  `final_forms` show forms without provenance (memberships only when the
  `cognate_set_id` shorthand does not cover them). Tool schemas stay `628f0f32…`.
  Offline replay of 327 recorded sessions: 14.4 MB less tool output; Qwen
  Polynesian peaks p90 110k → 93k (none over 100k), Gemma Polynesian median 54k
  → 46k, Burmish Gemma 90k → 64k. Live Qwen (R03f): Stage A identical to R03c;
  Stage B `x` no commit after three 16k thinking-only responses, with no slimmed
  content in its prompt (so not attributable to 1a). Report §19 has the
  next-option analysis (supersession with a repeat guard, watermark trigger,
  versioned schema diet). Committed in `7e6d637`.

## Authority and reading order

This file summarizes implemented behavior and accepted decisions.
The session handoff (`docs/session_handoff.md`, a local, untracked file) carries
live task status, unfinished steps and amendments for later sessions; where it
exists, read it when starting or resuming work.
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

## Task 06 recovery, verified 2026-10-05

[Provider recovery](research/provider_recovery.md) and
[results/hashes](research/provider_recovery_results.json) deliver structured conservative
causes, bounded attempts/elapsed time, Retry-After, cancellation during backoff and
no automatic replay of uncertain transport responses. SDK retries are disabled.
Exhaustion/auth/quota stop the tree; protocol identity fallback remains labelled.
No linguistic hypotheses or score definitions changed, and no inference ran.

Completed nodes survive interruption. Exact matching finalized JSONL receipts can
close the checkpoint-write crash window; ancestor receipt chronology prevents
laundering earlier fallback use. Resume does not repeat completed node calls/output
or completion events. New 3.0 checkpoints declare operational-retry-v1 and log changed
retry controls; unmarked 3.0 keeps strict retry hashes, and 1.0/2.0 remains unsafe.
Instructions, schemas, node notes, evidence/backend/version, inputs, sampler/model
and model-visible budgets remain strict. Truncation token overrides are semantic.

Atomic run_summary.json reports incomplete status, structured reason, attempted/
completed/unattempted nodes, cost coverage and full planned-set missing evaluations.
Current trajectory IDs prevent stale fallback-dependent ancestor salvage after a
resumed interruption. Sweeps separate interruption, direct fallback, ancestor
provenance and conditional versus end-to-end task02-v1 views. VOID-marked t36/t36b
quality is excluded even with a root commit; raw audit data remains readable.
Caps are cumulative per seed across recorded resumes, not experiment-wide; missing
cost/history cannot silently restart a capped seed's spend at zero. One synchronous
request still needs timeout support and one-response cost headroom.

Validation: 206 focused passes; one portable run, 680 passed/41 deselected.
No provider/API calls, model operations or downloads. Task05's final interface
hashes remain unchanged; its live usability gate and task07's final review remain.

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
6. **Provider interruption is separate from model protocol failure.** Task06 stops
   provider exhaustion/auth/quota/cancellation without walking identity fallbacks.
   Completed-node-only resume preserves semantic hashes; new checkpoints permit
   recorded retry-only changes. Old cause metadata stays unknown/unspecified.
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
Task 06 is delivered offline with 680 portable passes. Task 07 requires an instrument/interface gate, usable
frozen arms and a focused manifest review unless the owner scopes that review out;
06 can be explicitly scoped out for a bounded single-node pilot with demonstrated
interruption/missing-outcome handling. Forward prediction remains deferred.
No broad reconstruction gain has been established by the controls or smoke.
