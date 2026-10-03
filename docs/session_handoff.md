# Shared session handoff

Use this file to carry implementation context between chats, agents, and resumed
sessions. Task numbers refer to work packages 01–07, not individual chats. Keep
the live summary short; link detailed evidence in each task's result document.

The [current state](current_state.md) describes accepted findings and implemented
behavior; the [research plan](research_plan.md) defines scope and dependencies;
the [experiment policy](experiment_policy.md) sets testing and resource limits.
This file records progress and concrete amendments to the local task briefs.
Latest direct user instructions take precedence. Evidence-backed amendments can
refine a brief within the accepted plan; proposals to expand scope or resources
remain proposals until the user authorizes them. Code and artifacts establish
what actually exists, even when a status entry is out of date.

## Availability of task 01 material

The user chose on 2026-10-03 to keep the task 01 audit reports, CLI, extraction
tests and fixtures local and uncommitted. References to that audit below record
the original sessions and require the original checkout. Portable evaluation and
unit regressions use their own checked-in fixtures; use the task 02/03 contracts,
results and amendments for their supported interfaces. A fresh clone cannot run
`tools/failure_audit.py` or inspect its full traces without a separate transfer.

## Start or resume a session

1. Read your task's row, applicable amendments, and the latest relevant handoff
   below, then the documents listed in your brief. Confirm the checkout, branch,
   revision and existing changes. Verify that prerequisite artifacts and interfaces
   are present; a previous agent's completion claim is not sufficient by itself.
2. Briefly state the inherited decisions, your effective task and any remaining
   prerequisite. Mark the row `in progress` and identify the active session below
   by task and chat link/ID if available. Preserve existing work; continue from
   the first unfinished step rather than repeat completed diagnosis or experiments.
3. If a prerequisite is missing, record exactly what is needed and finish useful
   independent work. Do not guess its findings. On resumption, recheck the changed
   interfaces and relevant validation; repeat checks when changes or unresolved
   failures warrant it. After an important interface decision, update this file
   before dependent work continues, even if the task is not finished.

Default to sequential implementation. If another session is already editing
overlapping files, record the conflict and coordinate before changing those files.
Separate worktrees need the relevant code and tracked handoff changes transferred
before downstream work can rely on them; a chat summary alone does not transfer
an implementation. Local inference remains serial under the experiment policy.

## Before finishing, pausing, or handing off

1. Update your result document and `docs/current_state.md` where accepted findings
   or behavior changed. Update the task row and append one concise handoff below.
   Record actual validation and remaining uncertainty, including work that is
   implemented but untested or waiting for a local model.
2. Translate downstream consequences into concrete amendments under the affected
   task number: what to read, which interface/version/command to use, what existing
   work to reuse, and which requirement to replace or narrow, with a reason and
   evidence link. Do not leave only "coordinate with the next agent."
3. Apply those small edits to the affected `prompts/` briefs when available,
   preserving their objectives and the user's additions. Record the full actionable
   amendment here too: `prompts/` is ignored and will not travel to another checkout.
   Routine adaptations within scope need no new approval. If a prompt is absent,
   this tracked amendment still supplies the next session's instructions.
4. In the final response, link the handoff and result, summarize downstream changes,
   and identify the next ready task or exact blocker. The user reviews the outcome
   and chooses when to start the next session; updating this file does not dispatch
   it. Clear your active-session entry when stopping.

## Live task state

Updated 2026-10-03 after tasks 01–03. Other statuses carry forward the September
prompt index; amendments do not complete downstream implementation tasks.

Active session: none.

Task 03 delivered [units-v1](research/evidence_contract.md),
[migration](research/evidence_migration.md) and [results](research/evidence_results.md).
Its single local smoke had two valid previews but no valid commit; preserve that
qualification. No comparative quality claim or second smoke is authorized here.

Use `not started`, `in progress`, `partial`, `waiting`, `complete`, `scoped out`,
or `deferred`. `Complete` means the effective deliverables and required checks
are satisfied; explain any scoped-out work rather than silently dropping it.

| Task | Status | Prerequisite / next action | Latest handoff |
| --- | --- | --- | --- |
| 01 — Failure audit | complete | Fixed 12-concept panel, fresh counts, traces and deterministic replay delivered | Task 01 completion below |
| 02 — Evaluation | complete | task02-v1 contract, evaluator, six small cases, migration and offline results delivered | Task 02 completion below |
| 03 — Evidence/assembly | complete | units-v1 repair and offline checks delivered; single smoke stalled on malformed commits | Task 03 completion below |
| 04 — Instructions/protocol | not started | Ready from 01/02; sparse decisions, null/tuple friction and licensed tone reading; coordinate 03 | Task 02 amendment |
| 05 — Provider recovery | not started | Ready independently; reuse 02's operational-node/fallback view and preserve unknown legacy causes | Task 02 amendment |
| 06 — Local comparisons | not started | 02 complete; await 03–05 or explicit scope-out; freeze task02-v1 and separate arms | Task 02 amendment |
| 07 — Forward prediction | deferred | 06's recommendation and the user's decision to take up the study | — |

## Amendments for downstream tasks

Task 01 amendments below are applied to the local briefs. They are tracked here
because `prompts/` is ignored and does not travel to another checkout. Receiving
sessions must verify the interfaces and mark these entries applied/verified; no
entry claims downstream implementation is complete.

### For task 02 — fixed panel and measurement limits

Status: applied and verified by task 02; four valid artifacts and fixed panel replayed.
From: task 01, 2026-10-02, chat `01a0fda6-d530-7c61-9d8c-57a7ceb5b257`.
Evidence: failure audit (`docs/research/failure_audit.md`, local only),
trace appendix (`docs/research/failure_audit_traces.md`, local only).

Instruction (also in `prompts/02-evaluation-and-diagnostic-benchmarks.md`):

Read `docs/research/failure_audit.md` and its trace appendix. Reuse the fixed IDs
`1382,81,1350,749,156,1209,96,239,272,406,208,254`; these are development cases,
not a prevalence sample. Reproduce with `tools/failure_audit.py --select-panel
--replay --json` and supplied valid result paths. Preserve official scores; its
superscript-only token diagnostic is explicitly versioned `task01-v1` and is not
a category-to-contour mapping. All root top tone sequences disagree, but stripping
fixes only 16/216. Validate any additional tone/phonation mapping from source
notation before applying it. Saved Old Burmese gold already splits grapheme/phoneme
slash tokens. Retain proxy labels, all alternatives and ancestor-fallback flags:
r2/00 root is committed but consumes a failed Maruic node. Start fixtures with
NEEDLE's alternate gold/child-hit/root-miss, FATHOM/MONKEY tone controls, CRAWL's
morpheme switch and OLD MAN's unresolved lexical scope. New metrics must keep gold
out of model evidence. Task 01's CLI is a read-only audit, not the new evaluator.

Requires: task01-v1 audit CLI and banked artifact paths for reproduction;
02's versioned contract before interpreting later intervention quality. Full-run
artifacts are local only; portable extraction fixtures are checked in. No
reconstruction interface changed in 01. Receiving session records its resolution.

### For task 03 — observed unit failures

Status: applied and verified by task 03; frozen CRAWL/FLOWER/NEEDLE units reused.
From: task 01, 2026-10-02, chat `01a0fda6-d530-7c61-9d8c-57a7ceb5b257`.
Evidence: failure audit (`docs/research/failure_audit.md`, local only),
trace appendix (`docs/research/failure_audit_traces.md`, local only).

Instruction (also in `prompts/03-evidence-and-assembly-contract.md`):

Start from `docs/research/failure_audit.md` and `failure_audit_traces.md`, especially
r2/01 CRAWL burmic column 5 (wrong Rangoon morpheme), FLOWER burmic columns 0/5
and root orphan w, and NEEDLE Maruic column 0 (support-1 initial lost to witness
absence). Reuse `tools/failure_audit.py --replay --json`; all 11 old committed
beams/reports replay exactly. Actual builder: `alignment/correspondence_sets.py`;
`one_reading_per_node` is the survey reading, while saved get_alignments can show
all beam candidates. Preserve the model-approved morpheme/column identity through
preview, commit and parent input. Equal reflex tuples can address different
morphemes; token equality alone is not adequate provenance. Preserve unknown
analyses, notably OLD MAN's set 93; do not assign cognacy by output resemblance.
No exact root gold exists before final pruning, and all retained input tuples are
enumerated: widening the beam is not a supported first repair. Broad success is
not promised; tone and inferred onset-class decisions remain independent. Apply
02's interpretation contract, and use the audit's falsifiers to narrow or
reconsider 03 if its approved-unit repair gives no segment/morphology benefit.

Requires: task01-v1 audit CLI and banked artifact paths for reproduction;
02's versioned contract before interpreting later intervention quality. Full-run
artifacts are local only; portable extraction fixtures are checked in. No
reconstruction interface changed in 01. Receiving session records its resolution.

### For task 04 — sparse decisions and protocol evidence

Status: applied to local brief; pending verification by receiving session.
From: task 01, 2026-10-02, chat `01a0fda6-d530-7c61-9d8c-57a7ceb5b257`.
Evidence: failure audit (`docs/research/failure_audit.md`, local only),
trace appendix (`docs/research/failure_audit_traces.md`, local only).

Instruction (also in `prompts/04-model-instructions-and-protocol.md`):

Read the audit/trace appendix before editing. r2/00 Maruic has the only valid-run
node failure (ProtocolStallError); 35 rejected tool results across the four runs
are distinct from accepted linguistic decisions. The three fully committed runs
still have zero root exact hits. Keep null positions explicit and preserve strict
validation; the malformed tuple/anomalies cases support narrow remediation.
Prioritize qualified sparse/material choices: NEEDLE's support-1 Maruic initial
is lost through witness absence, STICKING's singleton onset is never represented,
and I/SNOT have traceable wrong values relative to gold. Correct the existing
false cascade claim as scoped. Tone-category claims need 02's source-backed
contract; do not automatically equate category digits with daughter contours.
Do not add a countdown based on these runs: none hits the 36-turn limit (max 29).
Keep prompt changes separately selectable from 03's unit/provenance mechanics.

Requires: task01-v1 audit CLI and banked artifact paths for reproduction;
02's versioned contract before interpreting later intervention quality. Full-run
artifacts are local only; portable extraction fixtures are checked in. No
reconstruction interface changed in 01. Receiving session records its resolution.

### For task 05 — node versus ancestor failures

Status: applied to local brief; pending verification by receiving session.
From: task 01, 2026-10-02, chat `01a0fda6-d530-7c61-9d8c-57a7ceb5b257`.
Evidence: failure audit (`docs/research/failure_audit.md`, local only),
trace appendix (`docs/research/failure_audit_traces.md`, local only).

Instruction (also in `prompts/05-provider-interruption-and-resume.md`):

Read the fresh run table in `docs/research/failure_audit.md`. Keep t36/t36b void
provider examples excluded from linguistic quality, even t36/01's root beam hit.
Valid r2 retries recover; r2/00 Maruic fails on protocol, not provider exhaustion.
Its root says failure_fallback=false while consuming that failed descendant.
Coordinate with 02 so committed-node, direct fallback and ancestor-fallback
provenance remain distinguishable. Do not classify the legacy 429 incident more
specifically than its saved structured evidence permits. Reuse banked event
examples to design redacted fake-provider tests; do not replay hosted requests.

Requires: task01-v1 audit CLI and banked artifact paths for reproduction;
02's versioned contract before interpreting later intervention quality. Full-run
artifacts are local only; portable extraction fixtures are checked in. No
reconstruction interface changed in 01. Receiving session records its resolution.

### For task 06 — frozen development cases and falsifiers

Status: applied to local brief; pending verification by receiving session.
From: task 01, 2026-10-02, chat `01a0fda6-d530-7c61-9d8c-57a7ceb5b257`.
Evidence: failure audit (`docs/research/failure_audit.md`, local only),
trace appendix (`docs/research/failure_audit_traces.md`, local only).

Instruction (also in `prompts/06-controlled-local-experiments.md`):

Read `docs/research/failure_audit.md` and its appendix. Freeze task 02's official
and licensed diagnostic readings, then compare 03 and 04 separately. Use CRAWL,
FLOWER and NEEDLE to test unit/provenance/material retention, with FATHOM/MONKEY
controls and I/SNOT/STICKING for independent phonological decisions. Preserve
recurrent lexicon evidence; extracting one word alone need not identify its
correspondences. The twelve audit concepts are development cases, not held-out
prevalence evidence. No exact root gold was generated pre-prune, so widening the
beam is not the first arm. Reject a claim of linguistic improvement based only
on more commits or fewer rejections. Use the audit's explicit deprioritization
conditions for 03; retain ambiguous OLD MAN/source-notation cases as unresolved
until 02 can justify their unit/mapping. Gemma was loaded on 2026-10-02 as
`google/gemma-4-26b-a4b`, 6-bit/262144 context; recheck current availability rather
than treating this observation as a future guarantee. No local inference ran in 01.

Requires: task01-v1 audit CLI and banked artifact paths for reproduction;
02's versioned contract before interpreting later intervention quality. Full-run
artifacts are local only; portable extraction fixtures are checked in. No
reconstruction interface changed in 01. Receiving session records its resolution.

### For task 03 — task02-v1 evidence units and regression commands

Status: applied and verified by task 03; task02-v1 scores and controls preserved.
From: task 02, 2026-10-02, chat `01a0fde2-c71f-7550-a4d4-050b6cde7838`.
Evidence: [contract](research/evaluation_contract.md),
[results](research/evaluation_results.md), [migration](research/evaluation_migration.md).

Read those three documents before interpreting a repair. Preserve official exact,
NED and every target alternative. Evaluate with
`conda run -n llm_reconstruction python tools/evaluate_run.py RUN_DIR --payload FROZEN_PAYLOAD --definition benchmarks/burmish.json --json`.
The evaluator version is task02-v1; banked scores are saved beside the new report.
Old Burmese remains a provisional proxy; root output can be a commitment while
naming `descendant_fallback_node_ids`. Superscript-token diagnostics are task01-v1,
not a historical tone/category map. Do not resolve OLD MAN from resemblance.

`evaluation.diagnostics.compare_cognate_units` scores complete independently named
pieces and reports extra/missing/reordered IDs. It does not recover IDs from tokens.
Current real outputs have no memberships; `cognate_unit_exact` remains unknown.
Carry approved source morpheme/column identities through preview, commit, assembly
and parent evidence before wiring real comparisons into that field. Keep unknown
and alternative analyses explicit. Task 02 adds no reconstruction schema/mechanism
for those units and makes no claim that the repair will improve historical quality.
Reuse the six small definitions with
`conda run -n llm_reconstruction python tools/diagnostic_suite.py --output-dir /tmp/task02-diagnostics --json`.
Their keys/identifiability notes are scorer-only; morphology order and lost contrast
are not uniquely identified. Regressions: `test_evaluation_contract.py`,
`test_diagnostic_suite.py`, existing partial-cognacy/assembly/serialization tests.

### For task 04 — retain the licensed tone reading

Status: applied to local brief; receiving session verifies.
From: task 02, same session/date. Evidence: [contract](research/evaluation_contract.md).
No category-to-contour or phonation mapping was established. Keep raw tone-token
agreement beside task01-v1 partition diagnostics; notation disagreement does not
by itself prove an incorrect historical category. Reuse FATHOM/MONKEY controls and
NEEDLE alternate-gold/child-hit/root-miss fixtures in `test_evaluation_contract.py`.
Prompt changes remain a separate arm from task 03; target annotations/diagnostics
must stay outside initial contexts and tool evidence. Sentinel tests cover this.

### For task 05 — preserve task02-v1 outcome semantics

Status: applied to local brief; receiving session verifies.
From: task 02, same session/date. Evidence: [migration](research/evaluation_migration.md).
Reuse `evaluation/run.py::evaluate_run`, `schemas/evaluation.py` and
`read_seed(..., payload=...)`. Direct identity fallback is not a commitment;
committed ancestors name failed descendants. Completed trajectories without a
saved deterministic step have missing outputs; abandoned runs retain all planned
target concepts. Prospective structured causes may improve `failure_kind`, but
do not parse legacy provider prose or rewrite unknown/unspecified causes. Keep
provider recovery separate from exact/NED, validated-target and selection readings.

### For task 06 — freeze task02-v1 and compare valid units

Status: applied to local brief; receiving session verifies.
From: task 02, same session/date. Evidence: [results](research/evaluation_results.md),
[compact counts](research/evaluation_offline_results.json).
Freeze evaluator task02-v1 plus definition/input hashes in the manifest. Use the
evaluate-run and diagnostic-suite commands in the task 03 amendment. Preserve the
old raw score next to new interpretations, and publish committed-node quality,
end-to-end planned outcomes, fallback/dependency counts and outside-selection IDs.
Exclude Old Burmese only from the validated-target view; keep its raw score and
the frozen concept set/tree. Fully-cognate-with-target sample selection is a
gold-assisted design choice and must be disclosed. The 12 Burmish panel IDs and
six synthetic cases are development material, not held-out prevalence evidence.

No source-backed tone/phonation map or corpus consistency score is licensed.
Report raw tone and task01-v1 partition separately. Morphology needs independent
unit IDs; do not use substrings. Lost contrast and morphology order are explicitly
underdetermined. Perfect/wrong offline fixtures test scores, not model ability.
Compare 03 and 04 separately after their required checks; 05 remains a prerequisite
or explicitly scoped-out operational limitation. Commit counts alone are no gain.

### For tasks 04–06 — task 03 units-v1 implementation

Status: mirrored in local briefs; receiving sessions verify the delivered checkout.
From: task 03, 2026-10-03, current chat. Evidence:
[contract](research/evidence_contract.md), [migration](research/evidence_migration.md),
[results](research/evidence_results.md), [compact result](research/evidence_offline_results.json).

**04:** Read those documents and changed runtime/tool schemas before revising
instructions. New correspondence sets bind exact scoped columns over every retained
analysis. Source histories merge only for compatible unit claims; unknown pieces
stay unknown. Preview validation is exact to values/confidence/conditioning,
residue choices, restorations, unit order and overlays. Re-surveying identical
evidence is safe; changed claims need re-preview. Use `unit_orders`,
`segment_morphemes.analysis_claim`, partial `realign.unit_id`/`analysis_ids` and
exact disposition/restoration column IDs as documented. Partial-unit scopes may
lower support and increase tool size; do not treat support-1/witness absence as
proof of innovation. Derived DSL is an unscoped view, not an equivalent cascade.
Task 03 changed only prose necessary for this contract; the broader false-cascade
claim and sparse/polarity instruction work remain yours.

Reuse the one local run `runs/experiments/task03-interface-smoke-20261003/`:
13 calls, seven failures, two accepted assembly previews, ProtocolStallError at
597.3 s, no commit. Concrete failures: duplicate set claims, reflex mismatch,
missing rationale, omitted `proto_segment`, invented `proto_segment_is_null`,
shortened tuples. Do not relax validation or call this a quality result. The
inventory-only smoke instruction is recorded; preserve its distinct hash.
No second task 03 smoke ran. Your own pilot remains subject to the shared policy.

**05:** New trajectories write 4.0 (2.0/3.0 readable); checkpoints write 2.0.
Checkpoint 1.0 reads for audit but `infer --resume` explicitly refuses missing
unit provenance. The evidence contract and LingPy backend/version are behavioral
hash inputs. Do not relax them as retry settings. Retain unknown legacy causes,
completed-node boundaries and task02-v1 outcomes. This smoke is a structured
protocol failure, not provider exhaustion; never relabel it from prose.

**06:** Freeze units-v1 plus task02-v1 and all input/instruction/schema hashes.
Task 03's compact controls use explicit operator hypotheses on three development
concepts, not actual banked-model approvals. They remove CRAWL's duplicate glide
and correct FLOWER's piece pairing, but proxy exact remains 1/3 and tone/glide
choices remain independent. All eleven old beams/reports replay exactly and
old raw scores stay intact. `oracle_ceiling.py` retains labelled legacy whole-string
oracles; source-unit controls are a separate reading. Partial scopes separate
etyma and the tuple cap can refuse wide inputs; record costs/coverage and do not
silently reduce an arm. Use the migration's commands and existing fixtures/tests.
The smoke supplies incomplete interface evidence only. Await 04/05 or explicitly
scope them out before a frozen comparative run; no broad improvement is established.

## Session handoffs

Append the following at a meaningful handoff, keeping detailed logs in the result
document. For partial work, make the next action specific enough to execute.

```text
### YYYY-MM-DD — task NN — complete / partial / waiting
Session: chat link/ID if available
Checkout: path, branch, HEAD; uncommitted changes and tested-state/diff reference
Result: document/artifact paths; implemented changes versus findings/proposals
Decisions/interfaces: accepted choices, versions, commands and compatibility effects
Validation/resources: commands and outcomes; live runs/time/cost or none
Downstream: affected task numbers and amendments/briefs updated
Open work: exact unfinished step, uncertainty or required user decision
Next: ready task and concrete starting action
```

### 2026-10-02 — coordination setup

- Basis: reviewed chat `01a0a483-b105-70f3-b174-645cdd5835e7`, local briefs and
  entry-point documents at HEAD `25f8c93`, branch `partial-cognacy-and-tool-use`.
- Change: added this shared protocol and linked it from all seven briefs and
  project entry points. Existing task scope and local-model instructions remain.
- Validation/resources: documentation links, handoff coverage and whitespace
  checked; no runtime tests, inference or API calls. This is not task 01's audit.
- Next: task 01 fixes its panel, records findings, and writes specific amendments
  for 02–04 and 06 where those findings affect their work.

### 2026-10-02 — task 01 — complete

Session: chat `01a0fda6-d530-7c61-9d8c-57a7ceb5b257`.
Checkout: `/Users/acraev/Work/cognate-reconstruction`, branch
`partial-cognacy-and-tool-use`, HEAD `25f8c9363755806722f6f951ee118ddb99094882`.
Inherited README/current-state/research-plan edits and the untracked handoff were
preserved. New audit documents, tool and fixtures/tests remain uncommitted;
local `prompts/` remains ignored. No runtime reconstruction code changed.

Result: `docs/research/failure_audit.md`, `failure_audit_traces.md`, read-only
`tools/failure_audit.py` (diagnostic version task01-v1), real redacted fixtures
under `tests/fixtures/failure_audit/`, and four extraction tests. Twelve concepts
were fixed before rationale/assembly inspection. Fresh inventory confirms 11/12
commitments, 0/216 root top/beam exact, 1/148 provisional proxy exact. Tone removal
recovers 16 root top hits, not the remaining 200. All 364 score records and eleven
committed beams/reports were cross-checked against existing code.

Decisions/interfaces: no target binding or reconstruction behavior changed.
CRAWL/FLOWER demonstrate changed morpheme pairing; NEEDLE loses a support-1 initial
through witness absence, while its exact Burmic child candidate reaches root
unchanged and gets a new tone. Independent accepted phonological/tone choices
remain visible in controls/I/SNOT/STICKING. No exact root target is generated
pre-prune, and every retained child tuple is enumerated. Final beam widening is
not a supported first intervention. Root failure_fallback=false hides r2/00's
failed Maruic ancestor. Saved Old Burmese gold already normalizes slash tokens.
Do not repeat unnormalized historical warnings as the current cause.

Validation/resources: focused extraction check 4 passed; relevant audit/metrics/
partial-cognacy/assembly group 47 passed; portable suite
`conda run -n llm_reconstruction python -m pytest -q -k 'not local_run_artifacts'`
539 passed, 41 deselected (47.70 s). One full portable-suite run. Whitespace and
local document links pass. Four original result/event hash pairs remain unchanged.
Zero inference, paid API calls, downloads or switches. Read-only availability
checks confirmed idle loaded `google/gemma-4-26b-a4b`, 6-bit, context 262144.
Recheck availability before any later smoke; it is not a future guarantee.

Downstream: full actionable amendments for 02–06 are tracked above and mirrored
in their local briefs. 02 preserves raw scores and establishes notation/proxy/
ancestor-failure interpretation; 03 is bounded to traced unit/provenance/material
failures; 04 isolates sparse/polarity choices and protocol correction; 05 separates
provider and ancestor failure; 06 uses frozen development cases and explicit
falsifiers, never commit-count-only quality claims.

Open evidence: source-backed tone category/contour and preglottalization mappings;
OLD MAN set 93 and gold lexical scope; historical polarity/conditioning of wrong
accepted values. The artifacts do not settle their historical correctness or the
largest causal intervention benefit. Proposed repairs remain unimplemented.
Next: task 02 is ready. Start by reading its amendment and the audit, reproduce
`tools/failure_audit.py` with the four valid paths/--payload/--select-panel/--replay,
then write `docs/research/evaluation_contract.md`. The user chooses the next chat;
no downstream task was dispatched.

### 2026-10-02 — task 02 — complete

Session: chat `01a0fde2-c71f-7550-a4d4-050b6cde7838`.
Checkout: `/Users/acraev/Work/cognate-reconstruction`, branch
`partial-cognacy-and-tool-use`, HEAD `25f8c9363755806722f6f951ee118ddb99094882`.
Inherited README/current-state/plan/handoff and task 01 code/fixtures are preserved.
All work remains uncommitted. The tested dirty code/fixture manifest hash is
`41ea5a8fc461fd32b2a94b062b7b1a4ca3e06d5b73ae126e03887e49fcf5131b`, also
recorded in the compact result; local detailed manifest `/tmp/task02-code-manifest.json`.

Result: `docs/research/evaluation_contract.md` (written before implementation),
`evaluation_results.md`, `evaluation_migration.md`, `evaluation_offline_results.json`;
report-only `evaluation/targets.py`, `diagnostics.py`, `run.py` and additive schemas;
integrated family/sweep/inspect reports; read-only `tools/evaluate_run.py`;
six definitions at `benchmarks/diagnostic/task02-v1.json` and offline
`tools/diagnostic_suite.py`. Compact real top-score extraction and scripted tests
cover NEEDLE alternatives/child-hit/root-miss, tone controls, CRAWL and OLD MAN.

Decisions/interfaces: evaluator task02-v1 preserves all raw score definitions and
alternatives. Superscript partition stays task01-v1, no source mapping invented.
Old Burmese is explicitly a provisional proxy, retaining raw scores outside
validated summaries. Direct fallbacks, committed ancestors using failed nodes,
unknown commitments, missing outputs and abandoned coverage are distinct.
Scorer-only complete-piece IDs permit separate morpheme comparison; real output
memberships are unknown pending 03. B-Cubed remains per word; no corpus metric is
licensed. Morphology order and lost contrast are underdetermined in the new suite.
Old synthetic definitions, target forms, selected IDs and traversal are unchanged.

Validation/resources: task01-v1 panel/replay reproduced on all four valid paths.
All 364 concept score records, graded aggregates and four result/event hash pairs
remain identical. Raw root 0/216, proxy 1/148; token partition 16/216; r2/01 NEEDLE
is the one outside-selection proxy hit. r2/00 root names failed `maruic`.
Focused evaluator/sweep/benchmark/legacy-reader/failure group: 106 passed. One
portable suite: 571 passed, 41 deselected (49.37 s). Final compact text/HTML and
report-status/piece-container refinements: 38 focused checks passed. Local document
links and whitespace pass. Zero live model/paid API calls, downloads or switches.

Downstream: full actionable amendments for 03–06 above are mirrored in local
ignored briefs. 03 consumes explicit units under task02-v1; 04 retains qualified
tone readings and isolated prompts; 05 improves prospective causes while retaining
unknown legacy causes; 06 freezes this evaluator and compares 03/04 separately.

Open evidence: source-backed tone/phonation mapping, OLD MAN lexical scope, real
output memberships, prospective provider cause detail, and live intervention
effects. These are explicit evidence limits, not unfinished evaluator work.
Next: task 03 is ready; start from its amendment and CRAWL/FLOWER/NEEDLE traces,
write the bounded evidence design, then implement the supported provenance repair.
04/05 have independent ready work; 06 still awaits those tasks or explicit scope-out.
The user chooses the next chat; no downstream task was dispatched.

### 2026-10-03 — task 03 — complete

Session: current chat `01a0fe22-5767-7801-90f1-37588ff8af31`.
Checkout: `/Users/acraev/Work/cognate-reconstruction`, branch
`partial-cognacy-and-tool-use`, HEAD `25f8c9363755806722f6f951ee118ddb99094882`.
Inherited uncommitted 01/02 changes preserved; all 03 changes remain uncommitted.
Result: `docs/research/evidence_contract.md`, `evidence_migration.md`,
`evidence_results.md`, `evidence_offline_results.json`; shared unit aligner,
analysis/provenance schemas and bindings, typed tools, version/resume guards,
redacted fixture and `tools/evidence_contract_probe.py`.

Decisions/interfaces: units-v1, trajectory 4.0, checkpoint 2.0; exact hypothesis/
evidence validation, compatible-claim provenance merging, unknown whole-form
fallbacks, explicit model analysis/order claims and bounded work. Legacy inventory
execution remains; checkpoint 1.0 resume is explicitly incompatible. Derived
DSL view omits column/unit scope. No new inference model or widened beam.

Validation/resources: portable 588 passed/41 deselected (52.94 s); final
contradictory-claim guard 41 focused checks (2.09 s). Eleven committed old beams
and reports replay exactly, four original result/event hash pairs unchanged;
task02-v1 six controls and legacy oracle width curves preserved. Frozen source
controls improve CRAWL/FLOWER segment/piece reading without increasing proxy
exact. The compact result records the delivery code manifest hash.
One serial local Gemma 4 26B/6-bit/262144 smoke: 597.3 s, 13 turns/calls, seven
protocol failures, two accepted previews, no commit. No paid calls, model switch,
download, full-family sweep or second smoke. Its frozen code manifest precedes
final compatibility/view/order guards; no further live validation is claimed.

Downstream: full 04–06 amendments above, mirrored in ignored local briefs; CLI/tool
and current-state documentation updated. No downstream chat was dispatched.
Open evidence: historical tone/phonation map, OLD MAN scope, automatic cross-etymon
pooling cost, full local commit usability and intervention quality. These remain
explicit research/protocol limitations, not a claim of broad reconstruction success.
Next: task 04 is ready from the contract and actual smoke errors; 05 is independent.
Task 06 still awaits 04/05 or an explicit scope-out. User chooses the next session.

### 2026-10-03 — independent review brief prepared

At the owner's request, prepared the independent review brief
(now `prompts/independent_review_brief.md`, local only), with a local
launcher `prompts/review-after-task03.md` and prompt-index link. It supplies
01–03 evidence, code/artifact and conversation pointers while leaving the reviewer
free to challenge the diagnosis, implementation and remaining plan. The review
itself has not been dispatched or completed; numbered task statuses are unchanged.
Local links and whitespace checks pass. No runtime changes or inference were
performed for this documentation follow-up. The owner chooses the review session.

### 2026-10-03 — session work reviewed and committed

Reviewed tasks 01–03 and verified the original branch's 16 post-PR-12 commits
are unmerged. Preserved that branch at `25f8c93`; session implementation is on
`burmish-audit-evaluation-units` (`b342cf0`, review repairs `43e6cf6`). The owner
chose to leave the standalone task 01 audit local and uncommitted. Its eight
files are unchanged; tasks 02/03 have independent fixtures. The owner moved
the independent review brief to ignored `prompts/`; it is not committed.

Two demonstrated edge defects were fixed: boundary edits retain analysis order
status/notes; realignment analysis IDs must match child-row count. The separate
source export passes 583 tests with local CLDF data supplied, 4 skipped and
1 deselected; 57 focused checks pass. All eleven legacy beams/reports and 364
raw score records reproduce unchanged. No inference ran. The original smoke's
no-commit result remains a usability limit. The original delivery also passed
588 portable checks, and the three added regression cases failed before repair.
The source-export suite requires separately installed local CLDF datasets.

The existing branch's PR decision remains with the owner; no PR was created
and no unmerged branch was deleted. This review does not dispatch tasks 04–06
or substitute for the independent scientific/architectural assessment.
