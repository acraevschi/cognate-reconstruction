# Shared session handoff

Use this file to carry implementation context between chats, agents, and resumed
sessions. Historical Task01–Task08 and active post-review R01–R07 identify work
packages, not individual chats. Always include the R prefix for new work. Keep
the live summary short; link detailed evidence in each task's result document.

The [current state](current_state.md) describes accepted findings and implemented
behavior; the [research plan](research_plan.md) defines scope and dependencies;
the [experiment policy](experiment_policy.md) sets testing and resource limits.
This file records progress and concrete amendments to the local task briefs.
Latest direct user instructions take precedence. Evidence-backed amendments can
refine a brief within the accepted plan; proposals to expand scope or resources
remain proposals until the user authorizes them. Code and artifacts establish
what actually exists, even when a status entry is out of date.

## Numbering — updated 2026-10-04

The owner requested consecutive numbering after the repair brief was added.
Historical instructions and Task01–08 rows retain that sequence; the 2026-10-08
post-review amendment below introduces the separately named R01–R07 sequence.
Dated research reports, saved runs, conversation references and the historical
session entries retain the numbers used when they were written. Artifact/schema
labels such as task02-v1, units-v1 and task03-* have not changed.

| Previous number | Current number | Work |
| --- | --- | --- |
| 01–03 | 01–03 | Delivered audit, evaluation and evidence/assembly |
| 03.5 | 04 | Evidence-contract repair |
| 04 | 05 | Model instructions and protocol |
| 05 | 06 | Provider interruption and resume |
| 06 | 07 | Controlled local comparisons |
| 07 | 08 | Deferred forward prediction |

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
   revision and existing changes. Post-review work (R02 onward) continues on the
   pushed branch `r01-contract-repairs`; its name is historical and it carries
   the whole post-review sequence. Commit, push or rename only when the owner asks. Verify that prerequisite artifacts and interfaces
   are present; a previous agent's completion claim is not sufficient by itself.
   Within the ignored `prompts/` folder, read only your own brief, the
   post-review common contract and files your brief or its amendments explicitly
   name, unless the owner asks. Do not browse older or other briefs to save effort.
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

Updated 2026-10-23: R01 is complete offline (see its handoff below) and R02 is
ready; the 2026-10-08 summary that follows is retained as history.
Updated 2026-10-08. Tasks01–04 remain delivered with newly identified residual
reporting/export gaps. Task05 has an offline conditioned-JSON defect and unproven
substantive live usability. Task06 has an abrupt-history gap beyond its delivered
graceful-recovery work. No new fixes or inference have run. The completed independent
review and subsequent owner discussion are translated into R01–R07 below; R01–R03
are the immediate sequence. Original Task07 is superseded as the next experiment;
Task08's optional successor is R06. The older task03/05 smokes remain qualified
historical interface evidence, not controlled comparisons.

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
| 03 — Evidence/assembly | complete | Historical delivery retained; R01 repaired analysis loss in best-lexicon export | Task03 completion; R01 completion |
| 04 — Evidence repair | complete | Documented counterexamples repaired; R01 repaired the same-set ambiguity-reporting gap | Task04 completion; R01 completion |
| 05 — Instructions/protocol | partial | R01 repaired token-conditioned native serialization offline; R03 tests substantive final usability | R01 completion |
| 06 — Provider recovery | complete | Graceful recovery retained; R01 added journaled abrupt-loss accounting (legacy/journal-loss limits remain) | R01 completion |
| 07 — Original local comparisons | deferred | Unstarted historical experiment superseded as immediate work by R02/R03; package comparison can be selected in R04 | Post-review amendment |
| 08 — Original forward prediction | deferred | Optional successor is R06, activated by owner choice | Post-review amendment |

| Post-review ID | Status | Prerequisite / next action | Intended result |
| --- | --- | --- | --- |
| R01 — Contract repairs | complete | Four findings reproduced and repaired offline (branch `r01-contract-repairs`); independent review's three journal defects fixed 2026-10-25; live usability not tested | `docs/research/post_review_contract_repairs.md` |
| R02 — Diagnostic panel and manifests | ready | On branch `r01-contract-repairs`; verify R01 interfaces per the R01 completion amendment; build Stage A/B instruments and ledger | `docs/research/model_diagnostic_design.md` |
| R03 — Stronger-model diagnostic | not started | R01/R02, concrete reviewed manifest; models selected 2026-10-25 (Gemma 4 26B local, Gemini 3.8 Flash medium); paid ceiling US$5 aggregate / 60 minutes confirmed 2026-10-25; local success not required | `docs/research/model_capability_diagnostic.md` |
| R04 — Interface and evidence study | deferred | R03/owner selects a specific question; no automatic redesign | `docs/research/focused_interface_study.md` |
| R05 — Propagation and robustness | deferred | Useful local judgments or a demonstrated propagation uncertainty | `docs/research/propagation_robustness_study.md` |
| R06 — Forward prediction | deferred | Owner-selected alternative, not a completion gate | `docs/research/forward_prediction_feasibility.md` |
| R07 — Hypothesis criticism | deferred | Owner-selected alternative; no R06 prerequisite | `docs/research/hypothesis_criticism_feasibility.md` |

## Amendments for downstream tasks

### Prompt voice, delegation and workflow clarification — 2026-10-13

The user requested a wording correction, not implementation of the R-series.
All seven `prompts/post-review/` briefs now speak as the user's direct first-person
instructions. The user selects the main agent and thinking level when starting
the session; no main-agent model is prescribed. Delegated agents should use
Claude Opus 5.5 with medium thinking. This supersedes the Sol xhigh/high settings
in older preparation entries and does not select a reconstruction provider or
authorize model operations. Use supported delegation controls rather than inventing
a provider identifier. If the requested setting is unavailable, continue separable
implementation yourself and record the limit; a required independent review stays
pending unless explicitly scoped out, rather than becoming self-review.

Copy-paste one individual brief at a time: R01, then its amended R02, then its
amended R03 after each result/handoff. The agent reads the common README and tracked
handoff; do not paste the entire folder as one task. Choose subsequent work from
R03's findings: R04/R05 remain conditional, R06/R07 optional alternatives. Pasting
one of these briefs selects that direction within its stated scope, so do not ask
the user to select it again; verify its evidence and live-resource prerequisites.
Do not return to root-level historical 07/08 afterward as a second required phase.
Old Task07 is superseded by R02/R03 and possibly R04; old Task08's optional
successor is R06. Preserve historical briefs as background. Downstream amendments,
their tracked mirrors, scientific gates and aggregate resource limits are unchanged.

### Owner model selection for R02/R03 — 2026-10-25

The owner selected the R03 arms in chat, which removes the "ask for the
model/provider" step:

- **Local baseline:** `google/gemma-4-26b-a4b`, already loaded in LM Studio.
  Verify availability, context length and competing jobs only at R03 launch;
  R02 does no discovery or loading.
- **Stronger candidate:** Gemini 3.8 Flash (`gemini-3.8-flash`, harness form
  `gemini/gemini-3.8-flash`) through the hosted Gemini API with
  `--reasoning-effort medium`.
- **Available credit:** the owner reports 7.36 CHF on the AI Studio project.
  That is the prepaid balance, not a spending authorization.

**Pricing.** The official pricing page, read 2026-10-25, gives per 1M tokens on
the paid standard tier through 2026-12-31:

- input US$0.75;
- output, including thinking tokens, US$3.75;
- cached input US$0.075.

Prices double from 2027-01-01. Re-read the page when freezing the manifest.

**Calibration from banked runs.** Each banked Gemini 3.7 Flash run was a full
three-node Burmish tree. It used 6.1–11.0M cumulative input tokens and 134–188k
output tokens. The largest single request was 248–336k tokens, and the runs cost
US$1.79–2.83. The same token use would cost roughly US$5–9 at 3.8 Flash prices,
before any extra medium-reasoning output. Full-tree runs therefore do not fit
the credit and are not R03's design.

**Budget (confirmed by the owner, 2026-10-25).** The small
Stage A/B fixtures should cost far less. The cap arithmetic is: worst-case input
≤ total turns × maximum request, and output ≤ turns × maximum response.

- **Ceiling:** at most **US$5 aggregate** for all R03 Gemini 3.8 Flash
  requests, including Stage A, Stage B, failures, retries and interruptions,
  with **60 minutes** of paid wall time. Choose per-trial `--max-total-cost-usd`,
  turn caps and a maximum output allowance so that the worst-case sum plus one
  maximum-response headroom fits inside the ceiling. Keep the remaining credit
  as margin against unknown or lost cost.
- **Local arm:** keeps the existing two-hour serial ceiling.
- **Superseded allowance:** the historical US$2/30-minute Flash allowance
  referred to the earlier Flash model. The owner confirmed the ceiling above on
  2026-10-25, so it supersedes that allowance for this arm only. It is not
  re-requested in later prompts and does not grow.

**Offline gate for R02: cost reporting for 3.8 Flash.** The harness's cost
comes from LiteLLM `response_cost`. The installed LiteLLM 1.81.16 bundled price
map lists no `gemini-3.7-flash` or `gemini-3.8-flash` entry, so banked costs
came from LiteLLM's runtime-fetched map. If `gemini/gemini-3.8-flash` gets no
price, every response is unpriced, `--max-total-cost-usd` refuses after the
first response, and the ledger records unknown cost.

R02 must establish, offline and using public documentation, how a priced
response will be obtained or recorded. Do not change dependencies; an explicit,
versioned price registration in the harness would be a code change to test.
R02 must also record that the cost cap is checked after each response, so one
response of headroom is always needed.

Mirrored in both the R02 and R03 briefs under their upstream amendments.

### R01 completion amendments — 2026-10-23

Mirrors the amendments applied to the ignored `prompts/post-review/` briefs.

**For R02 / `02-diagnostic-panel-and-manifests.md`** (replaces its "R01 must supply…" placeholder):

R01 is complete offline. See `docs/research/post_review_contract_repairs.md`,
the `_results.json` and the `_manifest.json` beside it. Starting HEAD was
`63af18d`; the work is uncommitted. Use these delivered facts instead of
preliminary assumptions:

- **Native conditioning.** Choices, full commitments and shared claims accept
  `conditioning` with `left`/`right` `{"tokens": [...]}` (optionally
  `morphological_boundary_tokens` ⊆ `["+","-"]`) and `word_initial`/`word_final`
  booleans. This works through `ToolRegistry.execute` in both `stored-hypothesis`
  and `full-payload` profiles: preview → commit (handle or payload) → trajectory
  JSONL → checkpoint → parent use → resume. Model-visible digests are unchanged
  from Task05 final:
  - instructions `0b9d91cf…`;
  - default tool schemas `dd58d427…`;
  - probe tool definitions: full `d3421479…`, stored `f4bf9ab5…`;
  - node commit notes `1ddfc0fc…`;
  - evidence contract `b1f459e7…`.
- **Executable conditioned fixture.** Start from
  `tests/workbench/test_conditioned_native_roundtrip.py`:
  - `one_word(("p","i"),("f","i"))` with the `p:f` set → `p` under
    `{"right":{"tokens":["i"]}}` and residue witness A (exact review case), or
    witness B (discriminating: `p i` only if the condition applies);
  - `test_conditioned_shared_claim_commits_through_handle`, three concepts, a
    recurrent shared claim;
  - `ConditionedProvider` for a two-level scripted `((A,B)x,C)r` run.

  Stage A still needs its own small recurrent fixture, a specified revision and
  a source-unit decision. These are tested building blocks, not a Stage A
  manifest.
- **Ambiguity fields.** These are additive.
  - `ColumnResolution.competing_choices`: each entry is `set_id, proto_segment,
    confidence, conditioning`.
  - `ColumnResolution.decided_by_equal_confidence`: an equal-confidence rival
    had another value, so the documented order picked the value.
  - Preview `ambiguous_columns` now includes same-set conditioned overlaps.
  - `ReconstructionDiagnostics.columns_with_competing_choices` and
    `columns_decided_by_equal_confidence` are new.
  - `columns_decided_by_tie_break` keeps its historical competing-set meaning.
    Under units-v2 it is normally 0, so read the two new counts.
  - Emitted values and resolution order are unchanged.
- **Export format.** `FamilyReconstructionResult.internal_nodes[].best_lexicon`
  is the top candidate per concept with its analysis copied as-is: unknown
  pieces stay unknown, order status is preserved, nothing is re-derived from
  spelling. The beam remains the full candidate record.
- **Resume and accounting policy.** Run with `--checkpoint` to get
  `<checkpoint>.requests.jsonl` (`request-journal-v1`, fsynced before each
  counted turn, request and tool call). `run_summary.json` `usage` adds
  `effort_counts_known`, `unrecorded_requests` and
  `usage_accounting_version="abrupt-loss-v1"`.
  - Turn and tool caps count lost effort.
  - Lost or unpriced cost stays unknown in `responses_without_cost`; a cost cap
    refuses resume.
  - Elapsed time is a lower bound; a time cap refuses.
  - `history_complete` stays false.
  - A `usage_recorded` marker follows each run summary, and a resume reconciles
    only the journal after the last marker, so a graceful failure is not lost
    effort.
  - A journal write failure stops the run (`RequestJournalError`). A Ctrl-C
    mid-request counts as unknown cost. A fresh run refuses an existing journal.

  The whole-batch ledger must read these per-seed fields, and the journal for
  attempts without trajectories. It must carry unknowns as unknown and never
  sum them as zero. Per-seed caps are not batch caps. A legacy checkpoint
  without a summary is uncertified.
- **Test commands.** The focused command in the R01 report (14 modules, 246
  passed), and `python -m pytest -q -k 'not local_run_artifacts'` (750 passed,
  41 deselected, 2026-10-25).
- **Outstanding limits.**
  - `inspect_run` and the sweep aggregate do not display the new usage keys, and
    no batch resource sum exists yet; that is R02 ledger work.
  - Effort lost together with its journal is undetectable; there is no bounded
    cost estimate.
  - macOS fsync is not `F_FULLFSYNC`.
  - A rival with an equal value but a different condition still counts as a
    competing choice.
  - No live usability has been shown.

**For R03 / `03-stronger-model-diagnostic.md`:**

Only these launch, serialization and budget facts changed. The serialization
fact also covers report readers.

- **Launch.** Launch every live trial with `--checkpoint` (and a unique
  `--run-id`) so the request journal exists. Without a checkpoint there is no
  abrupt-loss accounting.
- **After an abrupt interruption.** Do not reset spend under a new name.
  - A resume enforces turn and tool caps, counting journaled lost effort.
  - A cost-capped or time-capped resume refuses. Record the lost requests as
    unknown cost in the ledger, plus any provider-console spend as external
    accounting. Only then start a fresh trial with an identity, and a cap
    reduced, inside the same aggregate envelope as the frozen manifest permits.
- **Serialization.** Token-conditioned claims are JSON-safe in both profiles.
  Report readers must accept the additive `competing_choices`,
  `decided_by_equal_confidence`, `columns_with_competing_choices` and
  `columns_decided_by_equal_confidence` fields.
- **Model-visible digests.** These are unchanged from Task05 final. The
  `test_proto_assembly` result gains the two column fields above.

### Active post-review amendment — 2026-10-08

This amendment supersedes older forward-looking local-first/Task07 sequencing
instructions below. Historical observations, task identifiers, raw artifacts and
original task deliverables are not rewritten. The owner requested detailed prompts
for the agreed repairs/studies, including early testing of a stronger model on the
same repaired harness before substantial redesign/pivot. The prompts are in
`prompts/post-review/`, with consecutive files identified as R01–R07. The root
prompt index routes to them; original Task01–08 briefs remain for provenance.

Delegation clarified 2026-10-13: the user selects the main implementation agent
and thinking level outside the prompt. Useful delegated subagents: Claude Opus 5.5
with medium thinking. Delegate separable offline work with named file ownership;
main owns shared semantic interfaces and integration. Only main launches authorized
reconstruction inference, serially. These coding-agent choices do not specify
the reconstruction model/provider. No task or inference was launched during
prompt preparation; no commit/push/merge is authorized by a brief alone.

**Review evidence to preserve.** The independent report is local-only at
`prompts/review-after-tasks01-06-report.md`, completed 2026-10-07 at HEAD `63af18d`.
It ran 167 focused tests, reproduced 364 saved scores and eleven committed
beams/reports, and remeasured current frozen-input coverage: Burmic 543 local
sets/210 patterns, 437/567 alternative occurrences under the default filter;
Maruic 738/320, 1033/1340 occurrences. Both represent all 54 concepts; concept
coverage is not material coverage. These are prior review observations, not
verification newly run by prompt preparation or the next agent.

**R01 / `01-contract-repairs.md`: reproduce and repair four boundaries.**

1. Token conditioning: a valid `CorrespondenceCommitment` with reflexes `p:f`,
   proto `p`, confidence .8, and `conditioning.right.tokens=("i",)` fails JSON
   round-trip in review Pydantic 2.13.4. A=`p i`, B=`f i`, one supplied root unit,
   other columns retained from A, reproduces through the native registry. Full
   preview rejects nested arrays; compact choices preview commit-ready then fail
   when the stored spec is read at commit. Word-edge-only controls succeed.
   Inspect gap normalization in `schemas/inventory.py`, native registry and stored
   hypothesis readback. Preserve strict values; cover both profiles, token contexts,
   shared claims where relevant, exact re-preview, JSONL and downstream readback.
2. Abrupt history: a fake first-node run returns one uncommitted response, then
   exits outside ordinary finalization on its second call under a two-turn cap.
   Empty initial checkpoint survives; no final trajectory/summary exists. Resume
   currently permits two further calls and says history complete because the set
   of completed nodes is empty. Inspect `cli.py` usage completeness and durable
   lifecycle state. Fix first/later-node windows with a minimal marker/journal or
   conservative refusal; do not claim known-zero missing spend or mid-node resume.
3. Overlapping choices: one-token A=`p`, B=`f`, same local set reconstructs `p`
   at word start (.7) and `t` at word end (.9). Both apply; current code commits
   `t` while ambiguity/competitor lists are empty. Distinguish claim identity from
   set identity in `traversal/assembler.py` and reports; test equal/unequal confidence.
4. `_best_lexicon` in `agent/service.py` drops beam analysis from the public
   `internal_nodes[].best_lexicon` projection. Preserve compatible analysis or an
   explicit annotated-export contract. Actual traversal `beam_to_lexicon` and
   normal evaluator already retain analysis; do not conflate their behavior.

Use review temporary probes only if available; make portable minimal regressions
without requiring `/tmp` transfer. Result: `post_review_contract_repairs.md`.
Update contracts/current state and amend R02/R03 with actual versions, APIs,
fixtures, commands, compatibility and unresolved limits. No provider/model work.

**R02 / `02-diagnostic-panel-and-manifests.md`: prepare instruments, not inference.**
Stage A supplies a nonempty token-conditioned hypothesis, a small revision and
exact preview/commit/readback; it is usability, not linguistic discovery. Stage B
uses a very small recurrent multi-etymon decision panel with counterevidence and
ambiguity controls; models propose the choices. Keep A's answers, targets and
evaluator hints out of B. Verify identity/fixed-daughter and a justified simple
deployable baseline. Daughter c copies 6/6 in the old conditioned case, so raw exact
alone does not demonstrate conditioning skill. Preserve raw/versioned readings,
all planned denominators, scorable coverage, proxies and missing/fallback distinctions.
Audit source/unit/notation validity before a real-language primary outcome; no
invented tone mapping or OLD MAN resolution. Use normal evaluator and fake-run
controls, not comparator-only tests. Measure actual fixture caps/sparse coverage.

Prepare one local baseline and one stronger candidate, not a model leaderboard.
Choose for native tools/reasoning and auditable resources, not size alone. Consult
official public metadata/pricing; no model-server discovery/loading or provider
requests in R02. Carry existing owner choices; if provider/model or ceiling remains
unspecified, prepare a concrete recommendation and ask only for that missing
decision while continuing offline work. Coding-model settings are not experimental
API authorization. Existing Flash policy applies only within its named envelope.

Implement/reuse a minimal whole-batch ledger/launcher with fake tests for all
attempts, missing costs, interruptions and distinct outcomes. Candidate manifests
freeze inputs, code/dirty/source identities, model-visible instruction/schema/node
notes, versions, output/reasoning settings, caps, primary outcome and stop rules.
Initial proposal: at most one A and one conditional B trial per model, smaller if
budget requires; prespecified replication only within the same total envelope.
Result: `model_diagnostic_design.md`. Amend R03 with actual commands/artifacts,
model/resource decision, ledger and outstanding review/launch gates.

**R03 / `03-stronger-model-diagnostic.md`: early same-harness model diagnosis.**
Verify R01/R02 and use a read-only Claude Opus 5.5 subagent with medium thinking
to review the final concrete manifest unless owner explicitly scopes that review out.
Reviewer cannot edit,
run/discover/load models or spend. Main resolves findings and freezes before launch.
Use one local baseline and one stronger candidate on the same repaired harness.
The stronger model may run first; local failure or unavailability is not its gate.
Run A then conditional B separately for each model; missing local B limits the
paired conclusion but does not automatically block stronger B. Old hosted Gemini
commit success and local Gemma smoke failure are different snapshots, not a
controlled comparison. Preserve model/provider/configuration attribution limits.

Live scope must name the model/provider and total authorized envelope. Existing
Flash ceiling is US$2 total/30 minutes, not per stage/seed/arm (for R03's Gemini
3.8 Flash arm, superseded by the owner-confirmed US$5 aggregate / 60 minutes of
2026-10-25); local initial batch ceiling is two hours, serially. An explicitly approved alternative supersedes the
specified fields, and prior permission is not requested again. No fresh paid
allowance arises in later prompts. Include usability and failures/retries, maximum
in-flight headroom and unknown costs in one ledger. Actual loaded-model/context
preflight happens only when ready; no unauthorized model replacement/download.

Separate software-invalid acceptance/rejection, malformed submissions, navigation,
truncation, infrastructure/resource stops, successful commitments and useful
linguistic judgments. Stronger success/local failure identifies a practical
capability/interface interaction, not an optimal harness. Both completing poorly
points toward task/evidence/judgment; both failing motivates a smaller-interface
diagnostic, not an immediate verdict of impossibility. No extra seeds/model swaps
or mid-batch patches to obtain success. Result: `model_capability_diagnostic.md`.
Amend R04 with one evidence-backed next question or explicit deferral; R05 only
when a propagation question is supported.

**Conditional follow-ups, not a compulsory roadmap.** R04
`04-interface-and-evidence-study.md` builds/tests only the minimal reduced
evidence/response package warranted by R03, holding model common or proposing a
small explicitly funded 2×2 comparison if interaction is the issue. Do not leak
answers through dossier/candidate curation or mistake membership lists for laws
over unseen units. R05 `05-propagation-and-robustness.md` tests a specifically
implicated intermediate/alternative or representation sensitivity before any joint
optimizer; correct synthetic intermediates are privileged controls, not model
discoveries. Both start offline and need selected live scope for inference.

R06 `06-forward-prediction.md` is the optional successor to historical Task08:
explicit forward branch rules, one known- or inferred-ancestor regime, real
withholding from every evidence channel, ambiguous and overfit controls, smallest
offline prototype; no automatic inversion or training/backend expansion. R07
`07-assisted-hypothesis-criticism.md` is an optional alternative: read-only
source-linked critic, balanced legitimate/error cases, actionable precision and
false-objection measurement, human utility pending actual blinded expert evaluation.
No automatic fixes or external messaging. Neither optional task is needed to
complete R01–R03, and they need not follow each other. PBEBench/CFR remains
auxiliary background for a concrete question, not a required import.

**Mandatory downstream continuity.** Every implementing main agent records actual
changes/tests/hashes/artifact paths/limits, updates its R-row and result, then
patches affected downstream brief paragraphs with concrete delivered interfaces,
commands, interpretation and remaining gate. Mirror the full actionable amendment
here because ignored prompts do not travel. Do not append contradictions, copy
historical allowances as fresh permission, dispatch another chat or claim a pending
live result is complete. Preserve unrelated changes and all historical experiment
artifacts. Use existing conda environment, focused meaningful tests and one portable
suite after substantive changes; documentation-only preparation needs no runtime
suite. No new dependency/model/data operations by default.

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

### For task 05 — sparse decisions and protocol evidence

Status: applied and verified by task05; malformed fixtures and qualified guidance delivered.
From: task 01, 2026-10-02, chat `01a0fda6-d530-7c61-9d8c-57a7ceb5b257`.
Evidence: failure audit (`docs/research/failure_audit.md`, local only),
trace appendix (`docs/research/failure_audit_traces.md`, local only).

Instruction (also in `prompts/05-model-instructions-and-protocol.md`):

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

### For task 06 — node versus ancestor failures

Status: applied and verified by task06; redacted banked retries/void exclusions and fallback provenance retained.
From: task 01, 2026-10-02, chat `01a0fda6-d530-7c61-9d8c-57a7ceb5b257`.
Evidence: failure audit (`docs/research/failure_audit.md`, local only),
trace appendix (`docs/research/failure_audit_traces.md`, local only).

Instruction (also in `prompts/06-provider-interruption-and-resume.md`):

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

### For task 07 — frozen development cases and falsifiers

Status: applied to local brief; pending verification by receiving session.
From: task 01, 2026-10-02, chat `01a0fda6-d530-7c61-9d8c-57a7ceb5b257`.
Evidence: failure audit (`docs/research/failure_audit.md`, local only),
trace appendix (`docs/research/failure_audit_traces.md`, local only).

Instruction (also in `prompts/07-controlled-local-experiments.md`):

Read `docs/research/failure_audit.md` and its appendix. Freeze task 02's official
and licensed diagnostic readings, then compare 03 and 05 separately where usable
arms permit isolation. Use CRAWL,
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

### For task 05 — retain the licensed tone reading

Status: applied and verified by task05; evaluator regressions and final reference-word isolation pass.
From: task 02, same session/date. Evidence: [contract](research/evaluation_contract.md).
No category-to-contour or phonation mapping was established. Keep raw tone-token
agreement beside task01-v1 partition diagnostics; notation disagreement does not
by itself prove an incorrect historical category. Reuse FATHOM/MONKEY controls and
NEEDLE alternate-gold/child-hit/root-miss fixtures in `test_evaluation_contract.py`.
Prompt changes remain a separate arm from task 03; target annotations/diagnostics
must stay outside initial contexts and tool evidence. Sentinel tests cover this.

### For task 06 — preserve task02-v1 outcome semantics

Status: applied and verified by task06; prospective causes/current outcomes added without legacy prose inference.
From: task 02, same session/date. Evidence: [migration](research/evaluation_migration.md).
Reuse `evaluation/run.py::evaluate_run`, `schemas/evaluation.py` and
`read_seed(..., payload=...)`. Direct identity fallback is not a commitment;
committed ancestors name failed descendants. Completed trajectories without a
saved deterministic step have missing outputs; abandoned runs retain all planned
target concepts. Prospective structured causes may improve `failure_kind`, but
do not parse legacy provider prose or rewrite unknown/unspecified causes. Keep
provider recovery separate from exact/NED, validated-target and selection readings.

### For task 07 — preserve historical readings and compare valid units

Status: applied to local brief; receiving session verifies.
From: task 02, same session/date. Evidence: [results](research/evaluation_results.md),
[compact counts](research/evaluation_offline_results.json).
Freeze the final evaluator version delivered by 04/05 plus definition/input hashes
in the manifest, preserving historical task02-v1 readings separately. Use the
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
Compare 03 and 05 separately where usable arms permit isolation after their required
checks. Require 04/05; only 06 may be scoped out under the documented bounded
exception. Commit counts alone are no gain.

### For tasks 05–07 — task 03 units-v1 implementation

Status: mirrored in local briefs; receiving sessions verify the delivered checkout.
From: task 03, 2026-10-03, current chat. Evidence:
[contract](research/evidence_contract.md), [migration](research/evidence_migration.md),
[results](research/evidence_results.md), [compact result](research/evidence_offline_results.json).

**05:** Read those documents and changed runtime/tool schemas before revising
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

**06:** New trajectories write 4.0 (2.0/3.0 readable); checkpoints write 2.0.
Checkpoint 1.0 reads for audit but `infer --resume` explicitly refuses missing
unit provenance. The evidence contract and LingPy backend/version are behavioral
hash inputs. Do not relax them as retry settings. Retain unknown legacy causes,
completed-node boundaries and task02-v1 outcomes. This smoke is a structured
protocol failure, not provider exhaustion; never relabel it from prose.

**07:** Freeze the final evidence/evaluator versions delivered by 04/05 and their
hashes, preserving historical readings separately. Include all input/instruction/
schema hashes.
Task 03's compact controls use explicit operator hypotheses on three development
concepts, not actual banked-model approvals. They remove CRAWL's duplicate glide
and correct FLOWER's piece pairing, but proxy exact remains 1/3 and tone/glide
choices remain independent. All eleven old beams/reports replay exactly and
old raw scores stay intact. `oracle_ceiling.py` retains labelled legacy whole-string
oracles; source-unit controls are a separate reading. Partial scopes separate
etyma and the tuple cap can refuse wide inputs; record costs/coverage and do not
silently reduce an arm. Use the migration's commands and existing fixtures/tests.
The smoke supplies incomplete interface evidence only. Require 04/05 before a
frozen comparative run; only 06 may be scoped out under the documented bounded
exception. No broad improvement is established.

### Independent-review amendments — 2026-10-04

Status: owner requested prompt updates and new task 04; mirrored in local briefs.
Implementation is not started. These amendments supersede conflicting earlier
next-task/dependency instructions; dated delivery entries remain historical.
Reviewed snapshot: `burmish-session-evaluation-units` at
`cb16374461e4a3e5be38e5ca32e90b9d08e8ad4d`, plus local untracked task 01
material and ignored prompts/runs. Recheck the actual checkout when starting.
The review ran 126 focused passing checks, reproduced 364 score records and
all eleven old beams/reports, and confirmed the four result/event hash pairs.
No runtime changes or inference occurred. The full review is in the conversation;
former local review brief/launcher files are unavailable in this checkout.

**04 — scope and evidence:** Reproduce these offline counterexamples:
(a) full-span simplex slices become etymon-scoped sets; on the frozen 54-concept
Burmish payload the review counted Burmic legacy/units sets 130/543 (519 singleton,
4 multi-concept), Maruic 150/738 (576 singleton, 0 multi-concept); counts include
alternatives/additional material and are not a pure pooling ablation;
(b) A=`p k`, B=`p t`, with identified core/extra pieces: adding B's `p s`
alternative doubles unchanged core `p:p` support from 1 to 2;
(c) two independent A=`p`, B=`p` units reconstructing `p` preview successfully
but commit demands a merger directionality rationale despite no daughter contrast;
(d) two scoped etyma with A=`p`, B=`f`, O=`p` in one and O=`t` in the other
receive both O tokens in each local profile;
(e) the four generated morphology targets have no usable annotated units even
though `target_unit_layouts` exists and standalone piece controls pass.

Entry points: `alignment/units.py::source_analyses/align_tuple/evidence_map`,
`alignment/correspondence_sets.py::_unit_sets`,
`traversal/assembler.py::inventory_contrast_reductions`,
`agent/tools/correspondences.py::_outgroup_profiles`, `polarize.py`, restoration
checks in `inventory_evidence.py`, `synthesis/diagnostics.py::build_case`,
`evaluation/diagnostics.py::annotated_units/with_unit_diagnostics` and
`tools/diagnostic_suite.py` (package paths are under `cognate_reconstruction/`).
Reproduce before choosing the smallest repair. Separate exact occurrence identity
from recurrence/grouping, expose independent-etymon and alternative-dependent
counts, and permit explicit model-approved shared claims with local exceptions.
Repair false contrast detection and local witnesses; audit polarize/restorations
for the same assumption. Wire scorer-only morphology pieces into ordinary run
evaluation without leaking them to model evidence. Keep source/unknown/competing
analysis, exact bindings and parent propagation; retain CRAWL/FLOWER controls.

Deliver `docs/research/evidence_repair.md`, regressions, measured counts/payload/work,
and contract/migration updates. Test true contrast/deletion, scoped witnesses,
equivalent whole/full-span annotation, unrelated alternatives, and scripted parent
propagation/serialization/normal evaluation. Run focused then one portable suite;
check available historical replay and version altered semantics. Offline only:
no inference/provider calls/model operations. Broad reconstruction-quality gain
is not a completion requirement. The local prompt is
`prompts/04-evidence-contract-repair.md`; these instructions survive its absence.

**05:** Start from 04's verified result. Reduce retranscription of reflex/support
and validated hypothesis data. Prefer immutable stored-hypothesis commitment or a
smaller justified equivalent, with executable versus commit-ready previews and
missing explanations visible before commit. Require explicit proto values/nulls,
confidence and linguistic choices; changed claims/evidence need exact revalidation.
Preserve practical full-payload compatibility and strict checks. Keep protocol
changes separate from linguistic guidance; correct cascade/singleton/outgroup
claims using actual counts. Reproduce the saved malformed-call classes offline,
then use at most one bounded local smoke to test commitment on final code.
Check model availability when ready for that smoke. If unavailable, complete the
offline work and report the smoke as pending; availability does not block offline
implementation. No countdown absent new evidence. Report cumulative tokens separately from
maximum request/context size. Output remains `research/protocol_revision.md`.

**06:** Remains independent with shared-file/version/hash coordination. For a
bounded single-node 07 pilot it may be explicitly scoped out if interruption and
missing-outcome handling are demonstrated and recorded. This does not complete 06.

**07:** Require repaired invariants, scripted normal-evaluator measurement of the
primary outcome, final local commit usability and actual input/work-cap coverage.
Freeze usable arms with a declared question: evidence mechanics, protocol ergonomics,
linguistic wording or a necessary package. If interface/semantic adaptations make
an assembly-only arm unusable, label the package and limit attribution. No silent
input/beam narrowing. The visible internal concept split is a diagnostic partition;
claim generalization only from an explicitly withheld observation/tuning design.
Keep development cases, proxy/notation/scope limits, synthetic retention assumptions
and missing outcomes explicit. Arrange a focused independent review of the final
interface/manifest before comparative inference unless the owner scopes it out.
Task 08 remains deferred. No implementation or inference is dispatched by this entry.

### Task 04 interface decision — 2026-10-04, now verified

Read [evidence repair](research/evidence_repair.md). The implementation uses
units-v2: separate local scopes and default descriptive recurrence rows, with explicit
`shared_claims` selections over `member_set_ids`. Counts distinguish supplied etyma,
unresolved concept/unit opportunities, concepts, source columns and alternative
occurrences. New trajectories/checkpoints write 5.0/3.0; old records remain readable,
but old checkpoints and units-v1 execution require the original checkout.
Task 05 must use the delivered interfaces/counts; keep
broader guidance and live smoke deferred until then. Task 06 must preserve the
new semantic resume refusal; task 07 must freeze final count/evidence versions.
Final verification and measured costs are in the completion amendment/result below.


### Task 04 completion amendment — 2026-10-04

Read `docs/research/evidence_repair.md`, `evidence_repair_results.json`, and the
current amendments in evidence/evaluation contracts and migration. Delivered
units-v2 / count semantics independent-etyma-v1; trajectory 5.0, checkpoint 3.0,
unchanged piece representation units-v1 and raw evaluator task02-v1; explicit
piece diagnostics task04-units-v1. Verify the actual checkout/schema hashes.

05: default `summarize_correspondences` is descriptive `reading="recurrence"`.
`csp-*` rows list complete local `member_set_ids`; they cannot be committed as
local IDs. Use `shared_claims` with explicit pattern/member selection and required
value/null, confidence/rationale, optional conditioning/directionality, alongside
`commitments` (supply [] when all choices are shared). `reading="local",
min_support=1` gives individual `csu-*` values. Expanded persisted requests retain
`approved_shared_claims`. Changing a collection or choices requires exact preview.
The default filter is inspection, not a support-1 prohibition. Distinguish supplied
etyma/unresolved units/concepts/source columns/alternative occurrences. Scoped
polarize must preserve set_id, unit_orders and overlays; outgroup pointers are
bounded with explicit full counts/truncation. Realignment joins verify source-column
gain and report independent-support gain separately. Partial restorations need a
named unit. Reuse the saved task03 malformed-call classes; broader guidance,
stored-preview ergonomics and next bounded live commit smoke remain yours.

06: retain trajectory 2.0/3.0/4.0 readers and checkpoint 1.0/2.0 audit reading;
refuse unsafe old resumes under units-v2. Old units-v1 inventory execution requires
its original checkout. Do not relax evidence/instruction/schema hashes as retry
settings. The post-commit unit_orders propagation is repaired. Unknown legacy
provider causes and task02-v1 outcome/fallback readings are unchanged.

07: run the normal instrument control with
`conda run -n llm_reconstruction python tools/evidence_repair_controls.py --output-dir /tmp/task04-controls-new`.
It executes correct/wrong/extra/missing/reordered hypotheses through two levels,
JSONL and evaluate_run; it is operator-controlled, not live quality. Freeze
units-v2/count/task02-v1/task04-units-v1 and both submitted and expanded choices.
The minimum runtime wording needed for counts/shared IDs/scoping changed in 04;
an assembly-only arm cannot assume unchanged instruction hashes. Label any
necessary evidence/instruction package and limit attribution.

The full 54-concept frozen leaf input fits caps: Burmic 57 tuples/926 projected
columns, Maruic 91/2460. Default recurrence filters cover 437/567 and 1033/1340
alternative occurrences. The preserved three-concept input has 3 tuples,
33 local sets/28 patterns; default filter covers 9/33 occurrences. Declare sparse
inspection explicitly; never silently narrow input/beams. Retained historical
r2/01 root inputs fit at 65 tuples; future candidate root beams are not measured
by that legacy reading and must be preflighted. Flat all-leaf Polynesian still
refuses 32,768 tuples for concept 1212 against 4,096. Cost command:
`conda run -n llm_reconstruction python tools/evidence_repair_probe.py --payload FROZEN_PAYLOAD`.

Require final 05 local commit usability and normal-evaluator/cap/manifest checks,
plus relevant 06 completion or bounded explicit scope-out. Recommend another
independent review after 04/05 and relevant 06 work before comparative inference.
No downstream task or inference is dispatched; the owner chooses when to start.

### Task05 interface decision — 2026-10-05

Read [protocol revision](research/protocol_revision.md) and
[compact results](research/protocol_revision_results.json). Task04 hashes verified
with zero runtime/test mismatches; final interface has 633 portable passes. Current evidence/counts,
piece representation, trajectory/checkpoint and raw/unit evaluators remain
units-v2 / independent-etyma-v1 / units-v1 / 5.0 / 3.0 / task02-v1 / task04-units-v1.
The single authorized smoke failed: 15 turns/13 calls, seven rejections, two output
truncations, one empty preview and no commit. Final explicit-list/flat-shape/isolation
clarifications are offline-tested only; no second smoke was authorized or run.

**06:** Preserve the new strict node-checklist component (`the node commit
requirements`) alongside instruction/native-schema/evidence hashes. Selected
system text comes from `--agent-instructions PATH`; selected native inventory
schema comes from `--inventory-protocol full-payload|stored-hypothesis`. Neither
is a retry setting. Inventory handles are immutable, same-session aliases, never
checkpoint/mid-node state. Completed commitments still persist the full expanded
request and exact validation ID. Historical null readiness means unknown; keep old
readers and the 1.0/2.0 checkpoint resume refusal. Supplementary witness/anchor
digests now guard both inventory paths. Preserve task02-v1 failure/fallback readings.

**07:** Use the final runtime and both protocol profiles in offline preflight.
The stored profile adds explicit local choices (values/nulls, confidence and
reasoning) while deriving only reflexes/support; shared member selections remain
explicit. Executable previews expose commit_ready/missing_commit_requirements;
Final previews require an explicit collection, including [] for deliberate identity.
Choices are flat token-correspondence rows, never whole-form/per-concept groups.
ready hypothesis_id commits exactly that immutable inventory with final reporting.
Changed decisions, explanations, collections, evidence or overlays require preview.
Freeze submitted preview calls as well as full expanded requests/shared approvals.
The ergonomic arm is compact choices plus handle commitment, including its schema
descriptions; the full profile shares readiness and supplementary-validation guards.
`--agent-instructions` can isolate system text while notes/descriptions stay common,
not all linguistic guidance. Freeze a compatible control text and review its actual
schemas before launching. An older evidence arm necessarily includes task04's
count/shared-ID/scoping instruction package; do not label it pure assembly-only.
No countdown exists: the audit gave no cap-failure reason. Keep evaluator/cap/normal
parent-propagation checks, relevant 06 completion or bounded explicit exception,
and independent final interface/manifest review as prerequisites. One smoke does
not identify causes or establish reconstruction quality. No inference is dispatched.
The live gate remains unresolved. Freeze the final clarified hashes, not the smoke's
earlier snapshot. Review the failed calls and final interface before deciding a new
bounded usability probe; do not launch comparative inference from offline success.

Use the tracked `skills/run-cognate-reconstruction/driver.py` and SKILL.md; both
installed `.claude` copies are stale and read-only in this session. preflight now
reports installation divergence; catalogue IDs require separate loaded-state
verification. CLI/driver expose time/timeout/retry/sampler controls without fixed
test-count claims. Record actual model-specific sampling and hidden settings limits.

### Task06 completion amendments — 2026-10-05

Read [provider recovery](research/provider_recovery.md),
[validation/hashes](research/provider_recovery_results.json) and the updated retry/
checkpoint section of running_inference.md. Provider-recovery-v1 is delivered offline:
206 focused passes and one portable run, 680 passed/41 deselected. No provider
requests, model operations, downloads or downstream dispatch. Versions stay
units-v2 / independent-etyma-v1 / units-v1 / 5.0 / 3.0 / task02-v1 / task04-units-v1.

**02/shared readers:** Prospective trajectories have nullable failure_kind,
failure_error_type, provider_failure and interruption_reason. Keep old null/unknown/
unspecified causes; never classify saved provider prose. run_summary.json explicitly
retains interrupted status and the full planned evaluation set. active_trajectory_ids
identify current realized outcomes; do not salvage an earlier fallback-dependent
ancestor after a resumed attempt stops earlier. JSONL keeps all effort/attempts;
node totals and completed output use distinct current nodes. VOID.txt exclusions
remove all t36/t36b linguistic quality, even root hits, while retaining raw audit
records and all-run operational coverage. Conditional, end-to-end, direct fallback
and committed-ancestor dependency readings remain task02-v1.

**05/usability follow-up:** Model-facing system/native schemas/node checklist and
stored/expanded commitment contracts remain at task05's final hashes. The four retry
controls are operational only on new checkpoints; changing system instructions,
inventory protocol, model/sampler, evidence/backend or model-visible budgets still
requires a new run. Same-session inventory handles do not survive recovery. Your
failed smoke remains protocol evidence with no substantive preview/commit; task06
does not license a second smoke or establish a usable arm. Use the tracked driver/
skill, which now forwards all retry controls and displays run interruption summaries.
Installed .claude copies remain stale/read-only.

**07/comparison manifest:** Relevant 06 work is complete on this checkout; freeze
its actual code/schema and operational-retry-v1 policy alongside final 04/05 hashes.
New defaults: max-retries=6, retry-backoff-seconds=10, max-retry-seconds=300,
retry-max-delay-seconds=60; the tracked smoke driver intentionally defaults to zero
retries. Set matched controls explicitly. Through run-benchmark use repeated
--infer-arg=--FLAG=VALUE; caps are cumulative per seed across recorded resumes,
not experiment-wide. Bound the whole batch separately. Missing cost/history cannot
be treated as free spend; preserve one-response cost headroom. Provider/auth/quota/
cancellation stop the tree without identity fallbacks. Resume only completed nodes;
an interrupted node restarts its conversation/handles. Preserve incomplete summaries,
missing evaluations, unknown legacy causes, void exclusions and ancestor flags.
An unmarked old 3.0 checkpoint retains strict retry checks; 1.0/2.0 remains unsafe.
Do not migrate hashes or mix arms merely to resume. Task05 substantive usability
and the final independent interface/manifest/cap review still gate comparative
inference; the owner chooses the next bounded follow-up. No inference is dispatched.

### Review preparation amendment — 2026-10-06

The owner requested a brief for an open-ended GPT-6 Astra review of Tasks01–06
before Task07.
The local brief is `prompts/review-after-tasks01-06.md`, prepared against
`burmish-session-evaluation-units` at `63af18d`; it is not a completed review or
a dispatch. Task01 has no dedicated implementation commit and remains local by
owner choice. Tasks02/03 share `eebc8f6`, with Task03 review fixes in `217e25e`;
Task04 is `7356f66`, Task05 `3ea4402`, Task06 `63af18d`. The review may challenge
the diagnoses, final integrated implementation and research direction, and propose
new studies, substantial changes or pivots beyond the numbered plan. Task07 readiness
is one part of the assessment, not its organizing objective. The current plan and
old implementation-scope restrictions are context, not limits on recommendations;
operational limits still govern what the reviewer may execute.
Read-only inspection and focused deterministic offline probes are appropriate;
write only the local review report and temporary
probe outputs. No implementation/status edits or new reconstruction inference,
provider/model operations, downloads, commits, pushes or task dispatch are part
of the review. The report is `prompts/review-after-tasks01-06-report.md` when
produced; it is absent at preparation.

**05/07 next session under the current plan:** Read that report when available, verify accepted findings
against actual source/artifacts, and carry material consequences into the bounded
usability follow-up, frozen arms and final comparison manifest. A review of the
prospective plan is not certification of a manifest that does not yet exist.
Task05 substantive usability, ordinary evaluator/caps and owner-chosen launch
remain gates; this brief neither completes them nor licenses a second smoke.

**Research-direction clarification:** The owner explicitly wants the reviewer to
develop its own future directions, changes and pivots, rather than merely inspect
past work and readiness for the next prompt. A different sequence or research
roadmap is an acceptable recommendation. Task07 may be revised, replaced or deferred
in that recommendation; the owner decides which proposals to adopt before any
implementation/inference. Targeted primary-source literature reading may inform
the assessment; new data collection, models, dependencies and provider runs remain
proposals, not authorized review actions.

**08 scope clarification:** The owner explicitly treats Task08 as an optional
future idea outside the current Tasks01–07 plan's completion criteria. Do not
require its implementation for Task07 or the Tasks01–06 assessment. The reviewer
may discuss it alongside other future ideas, without treating it as the required
destination or the limit of recommendations. A later owner decision is needed to
activate it. These instructions are mirrored in the
local 07/08 briefs and index. `prompts/` remains ignored; transfer the brief/report
separately to another checkout or use this tracked context and verify missing
evidence rather than inventing it.

## Session handoffs

Entries below through the prompt-revision handoff use the numbering in effect
at that time. Use the translation above for current tasks; quoted historical
filenames may have been renamed. The renumbering entry at the end uses current
numbers and records the change without rewriting earlier history.


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

### 2026-10-04 — independent review and prompt revision

The owner requested the review's proposed prompt changes and new task 03.5.
Prepared `prompts/03.5-evidence-contract-repair.md`; amended 04–06, the original
03's follow-up pointer, prompt index, tracked plan and current-state next action.
The actionable scope and self-contained counterexamples are mirrored above.
Task 03.5 precedes 04; 05 stays independent; 06 needs verified instruments,
usable frozen arms and focused interface/manifest review or owner scope-out.
No reconstruction code, tests, Git history, models or runs were changed. Validation
for this revision is document links, whitespace, sequence and cross-file consistency.
The user chooses when to start implementation; no task was dispatched.

### 2026-10-04 — consecutive prompt numbering

At the owner's request, renamed the pending repair from 03.5 to 04 and shifted
instructions/protocol to 05, provider recovery to 06, local comparisons to 07,
and deferred forward prediction to 08. Tasks 01–03 retain their numbers.
Updated every active brief, prompt-index link, tracked plan/current-state reference,
experiment-policy task number and live handoff amendment/dependency. The translation
above preserves interpretation of dated reports and earlier conversation/history.
The next implementation is 04, followed by 05; 06 remains independent and 07 is
subject to its instrument/interface and manifest-review prerequisites. Task 08
remains deferred. Content scope, implementation status, resource limits, artifact
versions and run names are unchanged. Document links, whitespace, filename/title
sequence and old-name references were checked. No implementation or inference ran.

### 2026-10-04 — wording cleanup after renumbering

Applied the owner's two corrections: task 07 freezes the final evidence/evaluator
versions delivered by 04/05 while preserving historical readings, requires 04/05,
and permits only the documented bounded 06 exception. Intervention isolation is
qualified by usable arms. Task 05 checks model availability when ready for its
live smoke; unavailable models leave that smoke pending while offline work proceeds.
Matching live handoff instructions were updated; dated history remains intact.
Document checks pass. No implementation or inference ran.

### 2026-10-04 — optional PBEBench/CFR extension parked

After the [literature assessment](research/pbebench_cfr_assessment.md), the owner
requested a note in `prompts/` marking this as a possible future improvement.
Added `prompts/future-pbebench-cfr-extension.md` and linked it from the prompt index
and optional 08 brief. Finish and review 04–07 before revisiting these ideas;
the existing bounded 06 exception is unchanged. Task 08 remains deferred and
requires a later owner decision. No active deliverables or task states changed.

Because `prompts/` is ignored, preserve this scope in other checkouts: potential
reuse is a small PBEBench sequencing/induction diagnostic, DiaSim-inspired offline
residual/context and rule-edit comparisons, and later explicit forward hypotheses
tested on withheld daughter observations. These are proposals, not immediate
features. Reuse existing machinery and the assessment's limitations; neither
known-input PBE success nor forward fit establishes unique ancestral recovery.
This update changed documentation only; no implementation or inference ran.

### 2026-10-04 — task 04 — complete

Session: chat `01a10868-6d4a-7732-b08c-cca58dddc59b`, task 04.
Checkout: `/Users/acraev/Work/cognate-reconstruction`, branch
`burmish-session-evaluation-units`, HEAD
`cb16374461e4a3e5be38e5ca32e90b9d08e8ad4d`; implementation is uncommitted.
Inherited local task 01 reports/CLI/tests/fixtures and prior entry-document work
are preserved. Ignored prompts/runs stay local. Result:
`docs/research/evidence_repair.md`, `evidence_repair_results.json`,
`evidence_repair_manifest.json`; new offline measurement/control tools and sixteen
behavioral repair regressions. Tested code manifest SHA-256:
`0271e055a434dc5256aacda0fea563429d2bbd978d69d1bc4e5c21dbcd66df59`.

Decisions/interfaces: units-v2, independent-etyma-v1, trajectories/checkpoints
5.0/3.0; exact local bindings plus explicit shared collections over descriptive
recurrence; actual-reflex contrast checks; scoped outgroup/restoration evidence;
hidden target layouts and actual serialized parent pieces through normal scoring.
Only necessary runtime count/shared-ID/scoping wording changed; broad instructions
and preview-to-commit usability remain 05's work.

Validation/resources: four original counterexample failures reproduced before
repair. 162 focused checks passed; first portable 605 passed/two failures/41
excluded, then diagnostic-gap/vocabulary repairs received 78 focused passes.
Final portable: 607 passed/41 excluded, 56.03 s. Two full runs were made because
the first failed; no further repetition. All 364 saved score records, eleven
beams/reports and four result/event hash pairs reproduce. Source-unit CRAWL/FLOWER
controls and NEEDLE/proxy 1/3 interpretation persist. Five scripted normal-evaluator
controls commit at both levels, preserving underdetermined readings and raw scores.
Frozen full/panel costs and the flat Polynesian refusal are recorded; no narrowing.
Zero inference/provider/model operations or downloads.

Downstream: current contracts/migration/current state and 05–07 briefs amended.
The full actionable amendment is tracked above because prompts are ignored.
Remaining limits: no live commit/quality claim, source notation/OLD MAN remain open,
real target piece analysis may be unavailable, future generated root beams need
preflight, old semantic resumes/execution require original code. Another independent
review is recommended after 04/05 and relevant 06 work, before comparisons.
Next: 05 is ready; read the repair/contracts and verify actual schemas, then reproduce
malformed calls offline before the next bounded live interface smoke. The owner
chooses when to start; no task was dispatched.

### 2026-10-05 — task 04 saved as a separate commit

At the owner's request, record task 04 in a new commit on
`burmish-session-evaluation-units`, preserving the earlier task 02/03 commits.
Include the repair, its contracts/results/tests and the reviewed 01–08 workflow
numbering and prerequisites needed to interpret it. The tested code manifest is
unchanged since the final 607-pass suite; the earlier delivery HEAD/dirty-state
records remain historical provenance. The standalone task 01 audit and optional
PBEBench/CFR assessment/note remain local and uncommitted. Prompts remain ignored;
the task 05–07 interface amendments are present in this tracked handoff.
No push, PR or downstream task is part of this follow-up.


### 2026-10-05 — task05 — partial at live usability

Session: task05 chat `01a10b2c-434f-7ea1-ad62-aea808c4602f`.
Checkout: /Users/acraev/Work/cognate-reconstruction, branch
`burmish-session-evaluation-units`, HEAD `7356f6601b67aaaaf6e4d991d54927ab3cf315aa`.
Task05 work remains uncommitted, separate from saved task04. Inherited local task01
audit/fixtures and optional PBEBench assessment are preserved. Active session cleared.

Result: docs/research/protocol_revision.md, protocol_revision_results.json and
protocol_revision_manifest.json; stored-hypothesis adapter, explicit flat decisions,
commit readiness, immutable aliases, exact active/supplementary evidence checks,
corrected/shorter instructions, independent system/protocol switches, strict node-
checklist hashes and current tracked operator skill/driver. Both full inventory and
rules remain supported. No countdown, sound-change database or assembly/evaluator
execution changes. Final code manifest SHA-256:
`c4e3ad6fc0825382ba2cdc5a3ee30211a88b8d56d25abc2eb34a66aec41654c2`.

Validation: task04 runtime/test hashes matched its manifest; 35 prerequisite passes.
Saved task03 seven rejection classes replay with only explicitly rebound harness IDs;
new task05 malformed calls remain rejected. Five stored-hypothesis controls commit
at both levels and score through normal JSONL/evaluate_run, retaining underdetermined
order. Pre-smoke portable 630/41 excluded after three description/install integration
failures; final post-smoke interface 162 focused passes and portable 633/41 excluded
(60.96 s). Operator catalogue/loaded/busy controls and classifier group: 52 passed.
Only justified suite repetitions occurred; no fourth full run for operator-only work.
Final local links, whitespace and manifest checks pass.

Resource/outcome: one serial Gemma 4 26B A4B, 6-bit/262144 local run on the unchanged
three-concept observed input. Manifest/sampling/settings/raw artifacts are in
runs/experiments/task05-interface-smoke-20261005. It ended ProtocolStallError after
1171.75 node seconds, 15 turns, 13 calls, seven rejections and two output truncations/
forced-tool recoveries; one empty preview, no substantive preview or commit. Input
631609/output37966 cumulative tokens; max request input56233/total57589 versus context
262144. No provider retries, paid calls, switch, download, sweep or second smoke.
No result.json; failed trajectory/checkpoint/events preserved.

Final explicit-list/flat-shape rejection remediation and reference-word isolation
were added after that failure, so they are offline-tested only. The frozen mechanical
example coincided with the provisional NEEDLE reference; final runtime text uses
abstract symbols. Do not call the frozen run target-isolated quality evidence.
The snapshot-to-final distinction and hashes are recorded, not hidden. Both installed
.claude copies remain stale/read-only; preflight reports this and verifies actual
local loaded/idle status separately from the six-entry server catalogue.

Downstream: actionable 06/07 interface/hash/profile/package amendments are above
and mirrored in their ignored briefs; 05's own handoff also records the exhausted
one-smoke allowance. Freeze final clarified hashes/explicit collections, retain both
submitted and expanded choices, and keep normal evaluator/cap/manifest safeguards.
No pure assembly-only attribution is licensed where task04 requires instruction/
evidence/schema adaptations. Recommend a focused independent final interface and
comparison-manifest review before 07. No downstream work was dispatched.

Open work: substantive local survey/valid nonempty preview/immutable commit remains
unverified. The sole smoke did not reach that path, and final clarifications have
not had live confirmation. Further inference needs a later owner instruction, not
an automatic retry. Scientific benefit, source-backed tone mapping and OLD MAN
scope remain unresolved.
Next: 06 is independently ready; a focused read-only final interface/manifest review
can prepare an owner-chosen bounded usability follow-up. 07 remains gated.

### 2026-10-05 — task 06 — complete offline

Session: current Codex chat. Checkout: /Users/acraev/Work/cognate-reconstruction,
burmish-session-evaluation-units at 7356f6601b67aaaaf6e4d991d54927ab3cf315aa;
task05's existing dirty work and local task01 audit preserved; task06 is uncommitted.
Result: docs/research/provider_recovery.md and provider_recovery_results.json.
Implemented structured conservative taxonomy/redacted metadata, bounded retry hints/
cancellation, no lost-response replay, run suspension without provider fallbacks,
completed-step recovery/idempotence, operational-retry-v1 versus strict old hashes,
cumulative seed caps and atomic incomplete/current-outcome/sweep/void accounting.
Linguistic hypotheses, task02-v1 scores and task05 model-facing hashes are unchanged.

Validation/resources: final 206 focused passes (15.08 s); one portable run,
680 passed/41 deselected (67.35 s). CLI/driver help, manifest and whitespace checks
pass. Four banked retry examples were redacted with SHA/line provenance; raw artifacts
are untouched. All lifecycle providers/time are fake; no live/paid provider calls,
model discovery/switch/download, push or PR. The result ledger distinguishes retained
semantic source hashes from changed operational/reporting code.

Compatibility: trajectory 5.0/checkpoint 3.0 remain; old readers and 1.0/2.0 unsafe-
resume refusal remain. New retry patience changes log differences; unmarked 3.0
keeps its original checks without migration. Token overrides/model-visible budgets
remain strict. Mid-node restart, synchronous timeout and one-response billing
headroom limitations are explicit. Unrecorded history cannot silently reset caps.

Downstream: concrete 02/shared-reader, 05 follow-up and 07 manifest amendments above
are mirrored in their local ignored briefs. Current state, inference guide, research
plan and migration docs updated. No task dispatched. Open uncertainty: no live
recovery or model usability/accuracy demonstration is claimed or required by 06.
Next: the owner may start the focused final interface/manifest review and choose
Task05's bounded usability follow-up; Task07 remains gated on that work.

### 2026-10-05 — tasks 05/06 — local commit packaging

The owner requested committing both sessions and delegated the grouping decision.
Task05 is commit `3ea4402` (Clarify reconstruction guidance and add immutable
hypothesis commits); all 100 runtime/operator hashes match its saved delivery
manifest. Shared files were staged at the verified Task05 boundary before the
Task06 changes. The accompanying provider-recovery commit contains Task06's final
implementation, tests/results and current status documentation. Its runtime stays
at the previously tested 206 focused/680 portable-pass snapshot; no inference or
new runtime change was introduced for packaging. The README now reflects delivery.
Task01 audit/CLI/tests/fixtures, PBEBench assessment, raw runs and ignored prompts
remain local. No push or PR was requested or performed. Task05 stays partial at
substantive live usability; the task07 review/usability gate remains unchanged.

### 2026-10-06 — independent review brief for Tasks01–06 prepared

At the owner's request, wrote `prompts/review-after-tasks01-06.md` for GPT-6 Astra,
against `burmish-session-evaluation-units` at `63af18d`. It supplies project context,
the actual six briefs, verified task-to-commit mapping, local and checked-in evidence,
frozen-smoke versus final-source distinctions, and open-ended review questions.
The reviewer may challenge diagnoses, implementation and the prospective Task07
design; the output is an evidence-backed readiness judgment and prioritized next
sequence, without implementation edits or new inference. No review was dispatched.

Task01 remains local/uncommitted; Tasks02/03 share a commit rather than fictitious
separate histories. Task05 stays partial at live usability, Task06 delivered offline,
and Task07 unstarted. Recorded the owner's clarification that Task08 is an optional
future idea outside the current plan's completion criteria. The actionable amendment
is above and mirrored in the local 07/08 briefs; refreshed the local prompt index.
No implemented behavior or accepted research finding changed, so current-state and
runtime files are unchanged. Prompts/report remain ignored and need separate transfer.

Validation: all Markdown links in the new brief resolve, eight full commit hashes
exist in current ancestry, and 38 document/tool/fixture pointers exist. Changed
documentation passes whitespace checks. No runtime tests, model operations, provider
calls, downloads, commits or pushes were performed for this documentation task.
Next: the owner can start Astra with this brief in the current checkout. Its review
may inform a bounded Task05 follow-up and the final Task07 manifest; neither is
authorized or completed by preparing the prompt. Active session cleared.

### 2026-10-06 — review remit broadened at the owner's clarification

The owner clarified that open-ended means independently proposing future research
directions, changes and pivots, not only auditing delivered work and Task07 readiness.
Revised `prompts/review-after-tasks01-06.md` around both retrospective assessment
and research strategy. Astra may propose a different roadmap, revise/replace/defer
Task07, or recommend changes beyond the numbered prompts. Existing brief restrictions
are context for past work, not limits on recommendations. Execution remains read-only
with no reconstruction inference/model operations; targeted primary-source literature
reading may inform ideas. Task08 may be assessed alongside other future ideas without
being required or setting the boundary of future directions.

Updated the actionable amendment above and mirrored it in the local index and 07/08
briefs. Commit/evidence pointers are preserved. Changed-document links, commit ancestry
and whitespace checks pass. No runtime changes/tests or review dispatch occurred;
task statuses and current-state findings are unchanged. Next: the owner may start
Astra with the revised brief and choose which recommendations to adopt afterward.
Active session cleared.

### 2026-10-08 — post-review follow-up prompts prepared

At the owner's request, translated the completed independent assessment and the
subsequent stronger-model discussion into seven session-sized briefs in
`prompts/post-review/`, IDs R01–R07. Immediate work is R01 offline contract repairs,
R02 offline diagnostic/instrument preparation, and R03 a bounded same-harness
local/stronger comparison with distinct supplied-hypothesis and judgment stages.
R04/R05 are conditional interface/propagation studies; R06/R07 are optional forward
prediction and hypothesis-criticism alternatives, not required milestones.

Every brief introduces the project, identifies scope/prerequisites/artifacts,
defines meaningful completion and limits, suggests separable Sol-high subagent work
under a Sol-xhigh main agent, and requires concrete amendments to affected downstream
briefs plus the tracked handoff. The coding-agent model does not select a reconstruction
provider. Local-model success/availability no longer gates an otherwise authorized
stronger arm. Existing aggregate caps remain; a different unspecified paid model
or larger envelope still needs a concrete applicable owner decision.

Preserved historical Task01–08 numbering and briefs, adding supersession pointers
to the old 07/08. Updated the prompt index, optional PBEBench/CFR note, tracked
research plan/policy/current state and live handoff. The completed review report,
review brief and historical Tasks01–06 prompt contents are unchanged. All prior
user changes were retained. No implementation, tests of runtime behavior, model
operations, inference, dependency changes, commits, pushes or task dispatch occurred.

Documentation checks: seven consecutively named R-briefs have matching IDs and
upstream-amendment sections; local links in 16 new/edited Markdown documents
resolve; whitespace and `git diff --check` pass. A pre-edit hash inventory confirms
no protected file changed outside the intended eight existing documentation/prompt
paths. Eight new files comprise the seven briefs and their common index. Next:
the owner may give R01 to a main implementation agent; no session is active here.

### 2026-10-13 — first-person prompts and workflow clarified

At the user's request, rewrote the seven post-review briefs as direct instructions
in the user's voice. Removed prescribed main-agent model/thinking settings;
the user selects those when starting a session. Delegated work now requests
Claude Opus 5.5 with medium thinking. Updated the common contract, root index and
active tracked plan/policy/handoff references; retained older dated preparation
logs as history under the new amendment above.

Made the copy-paste order explicit: one brief at a time, R01 → R02 → R03, using
each upstream session's amended next brief and handoff. R04/R05 remain conditional,
R06/R07 optional alternatives; pasting one selects that direction within scope.
Old root-level 07/08 are background, not another phase after the R-series.
Scientific prerequisites, downstream amendments, provider choices and resource
limits remain unchanged. No implementation task was started.

Documentation checks: all seven briefs have first-person openings and the requested
subagent setting; no GPT/Sol/main-thinking prescription remains in the post-review
folder. All 103 local Markdown links in the 14 changed files resolve; trailing
whitespace and `git diff --check` checks pass. Compared a pre-edit hash inventory
of 262 tracked files and local prompts: changes are confined to the intended
documentation/prompt paths. No runtime tests, inference, model operations,
dependency changes, commits, pushes or task dispatch occurred. Task statuses and
the independent report are unchanged.

### 2026-10-23 — R01 — complete

Session: Claude Code desktop session (main agent), with two Claude Opus 5.5
medium-thinking subagents under disjoint file ownership. One handled recovery
(`cli.py`, `agent/orchestrator.py`); the other handled ambiguity and export
(assembler, inventory/traversal schemas, preview, `inspect_run`, `service.py`).
Checkout: `/Users/acraev/Work/cognate-reconstruction`, branch
`burmish-session-evaluation-units`, HEAD `63af18d`. Committed 2026-10-25 on branch
`r01-contract-repairs`, after a separate commit of the owner's earlier post-review
planning edits; local audit/PBEBench files remain untracked.

Result: [R01 repairs](research/post_review_contract_repairs.md), with compact
results and a 182-entry source manifest beside it. All four review findings
reproduced on a pristine `git archive HEAD` snapshot. The review's `/tmp`
probes were absent, so portable regressions were written.

1. **Token-conditioned claims.** The `CorrespondenceCommitment` gap-spelling
   validator is now a field validator, and token-conditioned claims preview,
   commit and read back in both profiles.
2. **Abrupt loss.** An fsynced `request-journal-v1` with `abrupt-loss-v1` usage
   semantics: turn and tool caps count lost effort, cost and time stay unknown
   and refuse their caps, and a legacy run without a summary is uncertified.
3. **Choice identity.** Ambiguity is reported by choice identity
   (`competing_choices`, `decided_by_tie_break`, two new diagnostics), and the
   historical tie-break count is preserved.
4. **Export.** `best_lexicon` keeps the analysis.

Validation/resources:
- Focused tests: 235 passed. The four new modules hold 59 cases.
- Portable suite: 736 passed after integration; 739 passed, 41 deselected after
  the boundary-set serialization repair found during commit verification
  (see the R01 report, section 5).
- Local-artifact readers: 41 passed. `git diff --check` is clean.
- Banked replay: 364/364 scores and 11/11 beams/reports agree.
- Model-visible digests are unchanged.
- No inference, model operations, paid calls, dependency changes or Git
  publication.

Downstream: R02/R03 briefs amended under their upstream sections and mirrored
above. Contracts amended: protocol revision, provider recovery, evidence
contract and current state.

Open work: no live usability evidence yet. The ledger, plus `inspect_run`/sweep
display of the new usage keys, belong to R02. Effort lost together with its
journal remains undetectable.

Next: R02 is ready. Start from the R01 completion amendment and the conditioned
fixture.

### 2026-10-25 — R01 — independent review fixes

Session: the same Claude Code desktop session. A separate Claude Opus 5.5
subagent (medium thinking) reviewed the R01 commits without pointers to
suspected faults and changed nothing. Checkout and branch as above; the R01
commits were amended rather than followed by a new one.

Result: [R01 repairs, section 6](research/post_review_contract_repairs.md). The
three defects the review found were reproduced, then fixed:
1. **D1.** A graceful failure after a commit was read as abrupt loss, and a
   time-capped resume then refused for good. A `usage_recorded` marker now
   follows each run summary, and a resume reconciles only the journal after it.
2. **D2.** A torn journal tail broke the second resume. The writer now removes
   it before appending.
3. **D3.** An unwritable journal turned every node into an identity fallback.
   It now stops the run with `RequestJournalError`.

Also fixed: a Ctrl-C mid-request counts as unknown cost; a fresh run refuses a
journal left at its checkpoint path; `ColumnResolution.decided_by_tie_break`
is renamed `decided_by_equal_confidence` and is set only when the rival's value
differs. The journal code is one module, `agent/request_journal.py`, and the
CLI's resume accounting is two short functions.

Validation/resources:
- Focused tests: 246 passed. Portable suite: 750 passed, 41 deselected.
  Local-artifact readers: 41 passed.
- Reverting each of seven fixes fails at least one named test.
- Banked replay: 364/364 scores and 11/11 beams/reports agree.
- Model-visible digests are unchanged; the `test_proto_assembly` result has the
  two column fields R01 added, and the docs now say so.
- No inference, model operations, paid calls or dependency changes.

Downstream: the R02/R03 completion amendments above and in both briefs now
name the renamed field and the new journal behaviour.

Next: R02 is ready.
