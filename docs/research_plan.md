# Research and implementation plan

## Active post-review plan — 2026-10-08

The owner requested implementing the independent review's actionable repairs and
research directions, then clarified that the same repaired harness should be
tested with a stronger model before substantial redesign or pivot. The active
briefs are `prompts/post-review/01-contract-repairs.md` through
`07-assisted-hypothesis-criticism.md`, identified as **R01–R07**. As clarified
2026-10-13, the user selects the main agent and thinking level outside the prompt;
useful delegated subagents use Claude Opus 5.5 with medium thinking.
Experimental reconstruction models are a separate choice. Preparation changes
documentation only and does not launch agents, implement repairs or run inference.

| ID | Work | Dependencies and decision |
| --- | --- | --- |
| R01 | Four bounded contract/reporting fixes: token-conditioned native JSON/readback; abrupt-history accounting; same-set ambiguity reporting; annotated best-lexicon export | Reproduce review counterexamples; offline only |
| R02 | Small supplied-hypothesis usability and evidence-sensitive judgment tasks, source validity, baselines, normal evaluator controls, batch ledger, candidate manifests | R01 for final validation; independent design can start earlier; no provider calls |
| R03 | One local baseline and one stronger candidate on the same repaired harness; distinguish interaction success from linguistic utility | R01/R02 verified, reviewed manifest and explicit model/resource authorization; local success/availability does not gate stronger arm |
| R04 | Conditional current-versus-simpler evidence/response package study, or a justified narrower follow-up | R03 selects unresolved question; do not assume redesign is necessary |
| R05 | Conditional value of intermediate hypotheses and robustness to equivalent presentations | Useful local capability or a specific demonstrated propagation uncertainty |
| R06 | Optional explicit forward prediction with genuine withholding; minimal offline prototype | Owner selects this direction; not all conditional tasks must precede it |
| R07 | Optional source-linked hypothesis critic and balanced/blinded evaluation prototype | Alternative contribution selected by owner; R06 not required |

Immediate sequence: R01 → R02 → R03. Do not interpret the later briefs as a
requirement to implement every idea. R04/R05 are evidence-dependent and R06/R07
are alternatives, not completion gates. Give an agent one individual brief at a
time and use the amended next brief after its handoff. Pasting a conditional or
optional brief selects that direction within its scope; verify evidence and any
live-resource prerequisites without asking the user to select it again. Do not
return to historical root-level 07/08 as a second phase. Preserve both execution
backends while
allowing a small study to expose one appropriate representation. Defer broad model
rankings, training, large new corpora, global optimization, automatic subgrouping
and feature/backend expansion until a bounded study demonstrates the need.

The first live comparison separates two stages. A supplies a nonempty conditioned
hypothesis and tests preview/revision/commit; B asks the model to choose a linguistic
analysis from appropriate evidence. A is not quality evidence. Freeze B's outcomes,
counterevidence/ambiguity cases and non-oracle baselines; exact copying can be
legitimate and can also make an alleged conditioning test non-discriminating.
Keep raw and versioned diagnostics, all planned denominators and exposure labels.

Model changes are the intended intervention in R03, while harness/evidence/scoring
stay common. Necessary provider/reasoning differences are recorded. Later interface
comparisons hold model choice common or explicitly propose a small factorial study.
Do not pool changed models, prompts or budgets as an isolated assembly repair.
The updated experiment policy retains aggregate budget limits and excludes any
unspecified paid authorization. Frozen manifests are reviewed before live use;
previous owner approval carries forward without repeated requests.

Each implementing session updates its result and shared handoff, then makes small
concrete amendments to affected downstream prompts: delivered versions/interfaces,
input paths, commands, interpretation and remaining gates. Mirror the actionable
text in the tracked handoff because prompts are ignored. The user chooses the next
task; no handoff dispatches it. Use the latest amendment over an older instruction.

## Historical Task01–08 plan

The material below preserves the earlier task formulation and numbered history.
Its original Task07 local-first experiment is superseded as the immediate next
study by R02/R03; historical Task08's optional successor is R06. Earlier local-
success gates and Task07-only spending references are read under the dated current
policy above. Historical artifact/contract names are not renumbered.

Accepted work direction, 2026-09-15; sequence amended 2026-10-04 after independent
review; numbered consecutively 01–08. These are planned tasks, not implemented
features. Read [current state](current_state.md) and
[experiment policy](experiment_policy.md) first. Local executable briefs live in
`prompts/`; this tracked document preserves their scope for other checkouts.

The session handoff (`docs/session_handoff.md`, local and untracked) carries
progress, decisions and concrete amendments between sessions. Follow its start/resume and completion
steps for every work package. Keep live status there, accepted findings in
`current_state.md`, and detailed evidence in each task's result document.

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
| 04 | Repair recurrence/count semantics, false contrast detection, scoped witnesses and normal morphology evaluation | Delivered 02/03; independent-review counterexamples | Offline only |
| 05 | Correct model instructions and simplify preview-to-commit workflow | 04; keep protocol and linguistic interventions identifiable | One bounded local interface smoke if needed |
| 06 | Provider-failure accounting, retry/resume semantics, bounded recovery | Independent of 01–05 | Mock providers; no paid calls |
| 07 | Frozen, local-first comparisons with verified outcome instruments and usable arms | 04/05; 06 complete or bounded explicit scope-out; focused manifest review or owner scope-out | Small local pilots; limited replication; optional capped Gemini |
| 08 | Forward-prediction feasibility and a small held-out prototype | After 07, only if still useful | Offline first; optional local smoke |

Do not run multiple agents mutating the same schemas or serving live inference
concurrently. 06 can be developed independently, but coordinate shared reporting
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

Implemented 2026-10-02: [contract](research/evaluation_contract.md),
[result](research/evaluation_results.md), [migration](research/evaluation_migration.md).
Evaluator task02-v1; no live model runs. Source-backed tone mapping and real output
morpheme identity remain unresolved for downstream work, as the contract states.

Preserve old exact/NED measurements and version new readings. Expose historical
binding validity, selection-overlap sets, tone/segment/morphology diagnostics,
missing outputs and failures. Preserve proxy scores without presenting them as
historically validated. Keep gold out of model-facing data, including derived
metadata. Label per-word B-Cubed appropriately; do not call it a cross-lexicon
consistency measure. Add compact, identifiable synthetic cases for targeted
mechanisms and a null/ambiguous control; avoid building a second broad benchmark
framework. Output a metric contract and migration notes.

## 03 — Unify the evidence contract

Implemented 2026-10-03: [contract](research/evidence_contract.md),
[migration](research/evidence_migration.md), [results](research/evidence_results.md).
One bounded smoke produced two previews but no commit. Protocol usability remains
for 05; quality/cost comparison remains for 07. The scope below is preserved.

Determine which surveyed units were actually used by assembly, including at the
next node. Choose the smallest typed design that preserves cognacy/morpheme
analysis and alignment provenance without assigning it silently. Explicitly
represent unknown analyses, multiple candidates, and overlays. Whole-form cases
must remain supported. Prove the correspondence tested is the correspondence
committed and applied. Version changed artifacts and retain old readers; do not
reuse stale validation IDs across incompatible views. If diagnosis does not
support this intervention, deliver the evidence and a smaller alternative instead.

## 04 — Repair the delivered evidence semantics

The 2026-10-04 review supports retaining task 03's provenance repair, while
reproducing and repairing four boundaries: etymon-specific scopes obscure
cross-word recurrence; alternative tuples can inflate apparent support; repeated
identity mappings are flagged as mergers; scoped outgroup profiles match unscoped
tuples. Also connect the existing scorer-only morphology layouts to normal run
evaluation. See the shared handoff for self-contained counterexamples and code
pointers; the executable local brief is `prompts/04-evidence-contract-repair.md`.

Separate occurrence identity from descriptive correspondence grouping. Allow
explicit model-approved shared claims and local exceptions without automatic
cognacy/phonological inference. Declare independent-etymon and alternative-dependent
counts. Preserve exact bindings, unknown/competing analyses and parent propagation.
Repair actual contrast/witness checks, add focused regressions, preserve legacy
readers/replays, and document count/artifact/resume changes. Work offline; 05 owns
the next live interface smoke. Output `docs/research/evidence_repair.md`.

Task 04 delivered on 2026-10-04: [evidence repair](research/evidence_repair.md).
Current units-v2 uses exact local bindings plus default descriptive recurrence and
explicit shared member selections. Counts, scoped witnesses and normal serialized
piece evaluation are repaired; 607 portable tests pass. Task 05 consumes those
interfaces and the minimal runtime wording changes as an evidence-mechanics package;
07 cannot assume those instructions remained byte-identical to task03.

## 05 — Repair model-facing claims and friction

Offline implementation on 2026-10-05: [protocol revision](research/protocol_revision.md).
Compact choices and immutable preview handles are independently selectable from
system text; full-payload/rule compatibility and strict validation remain.
633 portable checks and the ordinary two-level instrument controls pass. The single
local smoke failed without a substantive preview/commit; final clarifications are
offline-tested only. Task05 is partial at live usability, so 07 is not ready.
Review the final interface/manifest and decide the next bounded probe before
comparative inference; no second smoke or downstream work is dispatched here.

Start after 04 establishes the repaired contract. Make preview distinguish
executable from commit-ready and reduce transcription of harness-owned data.
Prefer commitment of an immutable stored validated hypothesis after explanations
are present, preserving explicit linguistic values and exact revalidation. Keep
protocol ergonomics and linguistic guidance separately identifiable.

Correct the false cascade impossibility claim in the runtime prompt and all
mirrored commit notes. Treat singleton support and absent outgroup evidence as
qualified evidence situations, not universal linguistic verdicts. Keep real
mechanical constraints explicit. Remove stale run anecdotes from instructions;
put detailed operator history in docs. Measure prompt/schema size and rejection
patterns. Any budget reminder is a separately toggleable experiment, not a reason
to relax validation or force a claim the model cannot defend. Refresh operator
recipes with the current local model policy; keep historical sampling provenance.

## 06 — Distinguish unavailable infrastructure from unsolved linguistics

Delivered offline 2026-10-05: [provider recovery](research/provider_recovery.md).
Structured conservative causes, bounded retry/Retry-After, completed-node-only
recovery, operational-retry-v1 compatibility and incomplete/sweep accounting pass
206 focused and 680 portable checks. No live requests or accuracy claim. Old
checkpoints retain their strict checks; task05 semantic boundaries stay unchanged.
Task07 remains gated on substantive task05 usability and final interface/manifest
review. The retained scope below describes the delivered work.

Classify structured provider errors conservatively, bound retry time, honor useful
retry hints, and preserve checkpoint progress on infrastructure interruption.
Propagate reasons to sweep summaries. Audit compatibility hash semantics before
relaxing operational retry controls. Do not unhash model-visible budgets or changes
that affect reconstructions. Recover from completed nodes without claiming
mid-node resume. Use deterministic fake providers for the full lifecycle.

## 07 — Measure one change at a time

Write a small experiment manifest before running: question, frozen inputs/configs,
primary outcome, controls, resource caps, stopping rule and interpretation.
Verify the normal evaluator measures the primary outcome, including independent
morphology target pieces. Test the final survey/preview/commit/serialization/
parent/evaluation path and both arms' actual input/work limits before inference.
Compare 03/04 evidence, 05 protocol ergonomics and linguistic wording separately
where usable arms allow it; otherwise name the necessary package and limit
attribution. Do not bundle it with a model switch or budget increase. The visible
internal concept split is a diagnostic partition, not unseen-word evidence.
Arrange a focused independent interface/manifest review before comparative runs
unless the owner scopes it out. Task 06 can be scoped out for a bounded single-node
pilot with demonstrated interruption/missing-outcome accounting. Existing sibling-evidence
exposure and copy warnings are secondary ablations only if diagnosis makes them
worthwhile. Replication is not a fishing expedition. Publish nulls and failures;
small samples can be inconclusive. Output `docs/research/local_comparison.md`.

## 08 — Ask whether the ancestor explains its descendants

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
- Proceed with 04, then 05; keep 06 independent and 08 deferred.
- If a local model cannot complete the diagnostic task, isolate protocol and
  prompt cost before buying a hosted sweep.
- If 07 improves completion without improving linguistic outcomes, report both;
  do not declare the reconstruction problem solved.
- Defer 08 until its question is not already answered by existing diagnostics.

## Deliberately outside the immediate scope

Deleting a commit path, fine-tuning, large new real-language corpora, automatic
subgrouping/tree revision, a sound-change typology database, unrestricted tools,
and broad model leaderboards. These are not forbidden future research; they do
not resolve the current uncertainty cheaply enough to lead this plan.
