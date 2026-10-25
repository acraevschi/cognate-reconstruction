# R01 — post-review contract repairs

2026-10-23, branch `burmish-session-evaluation-units`, starting HEAD `63af18d`
(the review's HEAD). Committed on branch `r01-contract-repairs`; offline only: no model requests, model
discovery/loading, paid calls, dependency changes or downloads. Environment:
`llm_reconstruction`, Python 3.11.0, Pydantic 2.13.4, pytest 9.1.1, LingPy 2.6.14.
[Compact results](post_review_contract_repairs_results.json) and the
[source manifest](post_review_contract_repairs_manifest.json) (183 SHA-256
entries over tracked `cognate_reconstruction/`, `tools/`, `tests/`, `skills/`
plus the four new test modules) accompany this report.

All four review findings reproduced on a pristine `git archive HEAD` snapshot.
The review's `/tmp/review-0106-20261006/` probe scripts were absent (only a
pytest basetemp remained), so portable regressions were built from the review's
descriptions. These are interface/accounting repairs. **No performance or
linguistic-quality improvement follows from them.**

Work split: the main agent fixed finding 1 and integrated everything. Two Claude
Opus 5.5 subagents (medium thinking) implemented finding 2 (`cli.py`,
`agent/orchestrator.py`) and findings 3–4 (assembler, inventory/traversal
schemas, preview, `inspect_run`, `service.py`) under disjoint file ownership.
Every change was reviewed here. One subagent choice was revised: it had
redefined the historical `columns_decided_by_tie_break` count, which is now
restored (see finding 3).

## 1. Token-conditioned claims at the native JSON boundary

**Before.** A=`p i`, B=`f i`, one supplied root unit. The claim was the local
`p:f` set → `p`, confidence .8, `conditioning={"right":{"tokens":["i"]}}`, with
residue retained from A. It was sent through `ToolRegistry.execute`:

| Profile | Preview | Commit |
| --- | --- | --- |
| stored-hypothesis (compact choices) | `ok`, `commit_ready=true` | refused: `ProtoInventorySpec commitments.0.conditioning.right.tokens tuple_type` (and `morphological_boundary_tokens frozen_set_type`) when the snapshot JSON was read |
| full-payload | refused: `TestProtoAssemblyArgs ... right.tokens tuple_type` | — |
| either, `{"word_initial":true}` | ok | ok |

`CorrespondenceCommitment.model_validate_json(c.model_dump_json())` failed as
the review showed.

**Cause.** `CorrespondenceCommitment.accept_gap_spellings` was a model-level
`mode="before"` validator. It returned a modified dict, and Pydantic then
validated the rest of the model in strict *python* mode. JSON arrays in the
nested `conditioning` therefore met strict `tuple`/`frozenset` fields. The
gap-spelling docstring already described this hazard for `reflexes`, but not
for nested fields. Shared claims were unaffected: they carry no such validator,
and they expand into typed objects after readback.

**Repair.** The validator is now `@field_validator("reflexes", mode="before")`,
the same scoping `PolarizeArgs.correspondence` already used. Only `reflexes` is
normalized; every other field keeps JSON-mode strict validation at the tool
boundary and python-mode strictness elsewhere. No validation was loosened.
Integer tokens, empty tokens, a string instead of an array, `#` as a boundary
token, extra keys, `"true"` for a bool, string support/confidence and short
reflex tuples all stay refused. Serialized bytes, `hypothesis_digest`, hypothesis
IDs and all behavioural digests are unchanged. Old stored hashes need no
migration. The other model-level `before` validators (`CascadeRuleSpec`,
`CommittedSoundRule`, `AlignmentOverride`) convert every container field they
hand on, and a populated JSON round-trip test now guards them.

**After.** Both profiles preview, commit, persist and reuse left- and right-token
contexts, including a context whose boundary vocabulary is restricted to `+`.
`tests/workbench/test_conditioned_native_roundtrip.py` (34 cases; 15 fail on
HEAD, namely every token-context case) covers:

- left/right token contexts plus boundary and word-edge controls, both profiles,
  native JSON arguments only;
- a discriminating variant with residue witness B, where only an *applied*
  condition yields `p i` and an unmet `_u` yields `f i`;
- malformed values staying rejected without storing a handle;
- exact JSON round-trips of commitment, shared claim, spec and preview args;
- a conditioned shared claim committed through a handle;
- immutable re-preview: editing the condition yields a new handle, re-previewing
  the same choice reuses the old handle, and the old handle commits the original
  condition;
- a two-level scripted run in both profiles: native preview → handle or full
  commit → trajectory JSONL (`trajectory_from_artifact` and the CLI's
  `TrajectoryDatasetBuilder.read_jsonl`) → `FamilyCheckpoint` save/load → parent
  node assembling from the conditioned child's `p i` → `FamilyReconstructionResult`
  JSON → completed-node resume with a provider that fails if called.

## 2. Abrupt interruption and cumulative resource history

**Before.** CLI fixture X → ROOT, `--max-total-turns 2`. The fake provider
returns one uncommitted response, then raises a custom `BaseException` on its
second call, which bypasses normal finalization. That left 2 calls, an empty
checkpoint and `input.json`, with no trajectory or summary. Resume with the same
cap then made **2 more calls** and completed both nodes. Its final usage was
`turns=2, responses_without_cost=2, history_complete=true`. The completeness
test (`set(checkpoint.steps_by_node) <= recorded_completed`) is vacuously true
for an empty checkpoint.

**Design: an append-only request journal.** The journal is
`<checkpoint>.requests.jsonl` (`request-journal-v1`), written only when a
checkpoint is used. Each record is flushed and `os.fsync`ed *before* the effort
it describes: a counted model turn (`turn`), each provider attempt
(`request_start`) and each counted tool call (`tool_call`). A `request_end`
record follows each response or provider error, with duration, reported cost
and tokens, `response_state` and `retryable`.

- **Linking to trajectories.** A node session's `trajectory_id` is now fixed
  when the session starts, so journal records name the trajectory that will
  eventually record that effort.
- **Journal markers.** A fresh run writes `journal_opened` before its checkpoint
  and marks the checkpoint `operational_settings["request_journal"]`. The
  `FamilyCheckpoint` schema is unchanged.
- **Summary markers.** After each run summary is written and fsynced, the CLI
  appends a `usage_recorded` record. The summary covers every record before it.
- **Reconciliation on resume.** Only the journal after the last marker is
  examined. There, a session with a JSONL trajectory is recorded effort and a
  session without one is unrecorded effort. Restored totals are the saved
  summary plus both, so repeated resumes are idempotent. A run without a
  journal keeps the earlier rule: the per-key maximum of summary and JSONL.
- **Graceful exits are not lost effort.** A session that commits and then fails
  in deterministic post-processing has no trajectory, but the run summary
  records it (see section 6, D1).
- **Write failures and torn records.** A failed journal write stops the run
  with `RequestJournalError`, a run-level interruption like a budget. No request
  is sent unjournaled and no node becomes a fallback. The reader ignores a torn
  final line with a warning and refuses corruption anywhere else. The next
  writer removes the torn line before it appends.
- **Interrupted requests.** A request interrupted by Ctrl-C, or by an ordinary
  exception from the provider adapter, is journaled with `outcome="abandoned"`
  and counted in `responses_without_cost`: it may have been billed.
- **Stale journals.** A fresh run refuses a journal already at its checkpoint
  path, so an earlier run's sessions cannot be read as its own.

**Accounting policy per quantity.**

| Quantity | Policy after unrecorded effort |
| --- | --- |
| Model turns, tool calls | **Restores known consumption.** Each was journaled before it happened, so caps stay enforceable (`effort_counts_known=true`) |
| Reported cost | **Restores known consumption** for lost requests whose priced response was journaled. In-flight or unpriced requests stay **unknown** (`responses_without_cost`). With `--max-total-cost-usd` the run **conservatively stops** and names the lost requests |
| Active elapsed time | **Lower bound only** (recorded request durations). With `--max-run-seconds` the run **conservatively stops** |
| Tokens | No cap exists. Provider-reported counts remain in journal records; otherwise unknown |
| Bounded maximum estimate | **Not made**: configuration has no real per-request cost/time bound |

Usage records add `effort_counts_known`, `unrecorded_requests` and
`usage_accounting_version="abrupt-loss-v1"`. These are additive; older summaries
parse with the old one-flag meaning. `history_complete` is false whenever any
effort is unrecorded, and stays false on later resumes. Refusal messages direct
the operator to a fresh run (new checkpoint/run ID) with a reduced cap. Caps
remain strict resume configuration. Unknowable spend is never claimed as
recovered.

**Legacy and missing-journal runs.** A legacy checkpoint *with* a run summary
is trusted as before, so complete historical runs stay resumable and complete.
A legacy checkpoint *without* a summary is no longer certified complete. Every
normal exit writes a summary, so its absence is consistent with an abrupt exit.
Resume refuses under any cumulative cap ("usage history unavailable") and
continues flagged without caps. A marked checkpoint whose journal is missing is
treated the same way.

**After.** The same probe gives `['X','X']` before the crash and a surviving
journal. Resume under the 2-turn cap makes **0 calls**, exits 2 with "run
exceeded its total model-turn limit", and reports `turns=2, tool_calls=0,
responses_without_cost=2, history_complete=false, effort_counts_known=true,
unrecorded_requests=2`. Under a 4-turn cap resume makes exactly 2 calls (total
4); a further resume makes 0 calls and leaves totals unchanged.

`tests/workbench/test_abrupt_interruption.py` (24 cases, fake providers):
- first-node loss counted against the cap;
- larger-cap conservative, idempotent resume;
- later-node loss with completed nodes and trajectories intact;
- in-flight request with and without a cost cap;
- priced response restored, but not its time;
- time cap refusal;
- journal durability before each request, and one fsync per record;
- graceful `KeyboardInterrupt` mid-request: resumable, with its cost unknown,
  so a cost-capped resume stops;
- a post-commit failure, then a time-capped resume that proceeds;
- effort after a summary added to it, not compared with it;
- an unwritable journal stopping the run;
- a torn tail followed by two resumes;
- unknown history reported before an exhausted turn count;
- a fresh run refusing a stale journal;
- retry-only setting change after abrupt loss;
- legacy run with a summary, legacy run without a summary (with and without
  caps), and a missing journal;
- torn versus corrupt records;
- an isolated subprocess calling `os._exit(17)` mid-node.

At `63af18d` the module cannot import the journal API, so its failure there
says nothing about behaviour. The behavioural before-state is the probe above.
The review fixes were checked by reverting each one (section 6). No real
service was killed.

**Limits.** Effort lost together with its journal, or effort from pre-journal
processes behind an older summary, cannot be detected; the first is handled by
refusal, the second is undetectable. A process that dies between writing a
summary and its marker leaves sessions that both count, which over-counts. macOS `os.fsync` is not `F_FULLFSYNC`, so
device-level power-loss durability is not guaranteed. Concurrent resumes are
not coordinated. Mid-node conversation recovery was deliberately not built.
`run_summary.json` exposes the new usage keys. `inspect_run`/sweep aggregates do
not yet display them, and the whole-batch ledger remains R02 work.

## 3. Overlapping conditioned choices and ambiguity diagnostics

**Before.** One-token A=`p`, B=`f`, one root unit. On the same local set: `p`
under `word_initial` and `t` under `word_final`, both with rationales. At .7/.9
the preview was commit-ready and the commit emitted `t`. At .9/.9 it emitted
`p`. In both cases `competing_set_ids=[]`, `ambiguous_columns=[]`, and the
aggregate count was 0. `resolve_columns` listed competitors as
`item.set_id != best.set_id`. Units-v2 binds an evidence column to one set, and
the spec refuses only duplicates of `(set_id, conditioning)`. The one overlap
that can actually occur, several conditioned values on one set, was always
discarded.

**Repair.**
- **Resolution policy unchanged.** The documented policy
  `(-confidence, proto_segment, set_id)` is now one shared key function, so
  emitted values are identical.
- **Choice identity.** Competing choices are identified by
  `(set_id, conditioning, proto_segment)`, not correspondence identity.
  Duplicates of the winner or of a listed rival are not double-counted.
  Confidence and rationale grade a choice; they do not create a new one.
- **Additive `ColumnResolution` fields.** `competing_choices` lists
  `CompetingChoice(set_id, proto_segment, confidence, conditioning)`, runner-up
  first. `decided_by_equal_confidence` marks a column where a rival had the
  winner's confidence and another value, so the order picked the value.
  `competing_set_ids` keeps its meaning (distinct other sets, now
  deduplicated).
- **Preview.** `ambiguous_columns` now includes columns with competing choices.
- **New additive diagnostics.** `ReconstructionDiagnostics.columns_with_competing_choices`
  and `columns_decided_by_equal_confidence`. Both are `None` on older steps.
- **Historical measurement preserved.** `columns_decided_by_tie_break` keeps its
  historical computation: a column with another matching *set*. The subagent's
  redefinition of it was reverted here. `inspect_run` now labels that count
  "with a competing set", and adds the competing-choice and equal-confidence
  counts when present.

**After.** At .7/.9 the column emits `t`, `ambiguous_columns` has one entry and
`competing_choices=[p/.7/word_initial]`, `decided_by_equal_confidence=false`.
At .9/.9 it emits `p` with rival `t/.9/word_final` and
`decided_by_equal_confidence=true`. No historical rationale is required to
silence the diagnostic.

`tests/workbench/test_choice_ambiguity.py` (10 cases):
- both profiles × unequal/equal confidence, through preview, actual commit, the
  step rebuilt from the committed inventory, diagnostics and `ReconstructionStep`
  JSON readback;
- single-claim non-ambiguity;
- de-duplication without a winner change (defensive: a validated spec cannot
  repeat a claim);
- an equal-confidence rival with the same value, which is listed but does not
  count as decided by equal confidence;
- the legacy distinct-set path and its historical count;
- old reports without the new fields still load.

**Compatibility.** Tool-argument schemas and hypothesis digests are unchanged.
New report JSON carries the two column fields, so trajectory/report bytes and
the trajectory JSON-schema digest change additively. Saved reports load with
defaults. The model-visible `test_proto_assembly` *result* also changes: every
`detail=full` column carries both fields (about 50 bytes per column), and
`ambiguous_columns` is broader. **Limit:** a rival with the same value but
another condition still counts as a competing choice, which is accurate but can
flag a column whose emitted value would not change.

## 4. Annotated `best_lexicon` export

**Before.** `agent/service.py::_best_lexicon` rebuilt each top form from its ID,
variety, concept and segments. A scripted run's beam candidate had units-v1
analysis, but `internal_nodes[].best_lexicon` had `analysis=None`.
`traversal/beam.py::beam_to_lexicon` and step-based evaluation already
preserved analysis and were not changed.

**Repair (smallest compatible).** `analysis=distribution.candidates[0].analysis`
is copied as-is, never re-derived from spelling. No digest changes, and the
public projection is now the annotated top-candidate lexicon.

`tests/workbench/test_best_lexicon_export.py` (2 cases, both fail on HEAD) runs
an actual `FamilyReconstructionResult` through JSON. It covers two concepts with
equal surfaces `p a` but distinct analyses, an `unknown:tail` piece that stays
`kind="unknown"` with no cognate set, source order status, and model order
claims (`order_status="model_claim"`) from the morphology control.

## 5. Found while verifying the commit: hash-order serialization of boundary sets

**Before.** A clean `git archive` export of the first R01 commit failed six
stored-hypothesis conditioned tests in one full run, then passed in the next.
Looping the conditioned modules reproduced a `hypothesis-stale` refusal at
commit about once in twelve runs. `SegmentExpression.morphological_boundary_tokens`
and `LexicalForm.morphological_boundary_tokens` are `frozenset`s. Their JSON
dump follows hash-table order, which depends on the process's string-hash seed
and on insertion order. With `PYTHONHASHSEED=7`, the default `{"+","-"}` dumped
as `["+","-"]` but its JSON readback dumped as `["-","+"]`. A stored handle is
re-digested from its JSON snapshot at commit, so the digests could disagree.
Cross-process dumps of every form and condition also varied with the seed. The
defect was latent at HEAD, where conditioned handles could not commit at all.

**Repair.** JSON-mode field serializers (`when_used="json"`) emit both sets
sorted, via `schemas.common.sorted_token_set`. Python-mode dumps keep the
`frozenset`, so strict python revalidation is unchanged. The default dumps as
`["+","-"]` in every process. Saved artifacts in either order still load,
because the sets compare equal. The behavioural and tool-schema digests hash
texts and schemas, not boundary-token data, so they are unchanged under seeds
1 and 7, and the banked replay still agrees 364/364 and 11/11. A digest over
*data* that holds a boundary set (a hypothesis digest, a handle) can differ
from one computed before this repair in a process that dumped `["-","+"]`.
Such a digest was never reproducible across processes, and none is re-verified
across processes, so nothing is migrated.
`test_boundary_sets_serialize_canonically_and_handles_commit_under_any_hash_seed`
runs seeds 1, 2 and 7 in fresh interpreters, through a conditioned handle
commit. It fails on the first R01 commit. Twenty-five consecutive loops of the
conditioned, protocol and ambiguity modules then passed.

**Clean-export note.** A clean export also fails ten tests that read ignored
local corpora (`data/lexibank/hillburmish`, Burmish benchmark material) or
local-only audit files. The same ten fail on a clean export of `63af18d`; they
are not R01 regressions. The working-tree portable suite includes those local
inputs.

## 6. Independent review of R01 — 2026-10-25

A separate Claude Opus 5.5 reviewer (medium thinking) read the R01 commits
without pointers to suspected faults. It changed nothing in the repository.
It reported three defects, all in finding 2's journal. Each was reproduced here
before it was fixed.

- **D1: a graceful failure read as an abrupt one.** A committed trajectory
  reaches the JSONL only in `finalize`, after the overlay and the assembler run.
  When either raised an ordinary error (an ambiguous overlay, a changed bound
  column), the summary said `history_complete=true`, but the journal showed a
  session with no trajectory. Every later resume reported "1 provider request(s)
  … journaled by a process that exited" and, under `--max-run-seconds`, refused
  for good. At `63af18d` the same run resumed. **Fix:** the `usage_recorded`
  marker (section 2). The resume reads only the journal after the last marker,
  and adds that tail to the summary instead of comparing the two.
- **D2: a torn tail broke the second resume.** A torn record has no newline, so
  the next process's first record joined it. The next resume then refused
  "corrupt request journal … line 2". **Fix:** the writer truncates an
  unterminated last record before its first append; the reader already ignored
  it.
- **D3: an unwritable journal became silent fallbacks.** The `OSError` reached
  the node's ordinary-failure path, so every node became an identity fallback,
  no request was sent and the run "completed". **Fix:** `_journal` raises
  `RequestJournalError`, which the node wrapper re-raises like a budget.

The review also raised risks. These were fixed:
- **Ctrl-C mid-request recorded no cost.** The request now counts in
  `responses_without_cost`, so a cost-capped resume stops.
- **Equal confidence overstated.** `decided_by_equal_confidence` is set only
  when the equal-confidence rival has another value; the field was renamed from
  `decided_by_tie_break` (introduced by R01 and never banked).
- **A reused checkpoint path inherited a stale journal.** A fresh run now
  refuses it.

These were not changed and are recorded here:
- A deferred column skips a conditioned claim whose environment is undecidable,
  and its unconditioned fallback is not reported as competition. This predates
  R01.
- `with_suffix` maps `a.json` and `a.ckpt` to one journal path. Records are
  filtered by run ID and configuration, and a fresh run now refuses an existing
  journal.

**Test gaps closed.** Deleting the per-turn history check, the fsync, the torn
tail repair, the error wrapping, the summary marker, the abandoned-request
count or the stale-journal refusal each fails at least one named test in
`test_abrupt_interruption.py`. The equal-confidence and distinct-set paths in
`test_choice_ambiguity.py` have direct tests.

**Readability.** The journal writer, reader and resume reconciliation are one
module, `agent/request_journal.py`, with typed `UnrecordedEffort`,
`JournalTail` and `ResumeUsage` records. The CLI's resume accounting is two
short functions. `restore_usage` states its legacy rule directly. The
assembler and the spec share `claim_key`, and an unread ambiguity list was
removed. Orchestrator messages no longer name CLI flags.

## Verification

```sh
PYTHONDONTWRITEBYTECODE=1 /opt/anaconda3/envs/llm_reconstruction/bin/python -m pytest -q -p no:cacheprovider \
  tests/workbench/test_protocol_revision.py tests/workbench/test_evidence_contract.py \
  tests/workbench/test_evidence_repair.py tests/workbench/test_provider_recovery.py \
  tests/workbench/test_resume_integrity.py tests/workbench/test_evaluation_contract.py \
  tests/workbench/test_diagnostic_suite.py tests/workbench/test_high_quality_across_commit_shapes.py \
  tests/workbench/test_schema_versioning.py tests/workbench/test_schemas.py \
  tests/workbench/test_conditioned_native_roundtrip.py tests/workbench/test_abrupt_interruption.py \
  tests/workbench/test_choice_ambiguity.py tests/workbench/test_best_lexicon_export.py
# 235 passed at R01; 246 passed after the review fixes (section 6)
/opt/anaconda3/envs/llm_reconstruction/bin/python -m pytest -q -p no:cacheprovider -k 'not local_run_artifacts'
# after integration 736 passed; after the boundary-set repair: 739 passed;
# after the review fixes: 750 passed, 41 deselected
/opt/anaconda3/envs/llm_reconstruction/bin/python -m pytest -q -p no:cacheprovider -k 'local_run_artifacts'   # relevant readers: 41 passed
```

**Banked replay.** `tools/failure_audit.py` is local-only. It ran over the four
valid Burmish runs with `--payload runs/benchmarks/burmish.json --select-panel
--replay --json`, after finding 1 and again with findings 1, 3 and 4
integrated, and again after the review fixes. Each time all 364 saved score
checks, 11/11 committed beams and 11/11 assembly reports agreed. Finding 2 does
not touch the replay boundary.

**Behavioural digests.** These are identical at `63af18d`, after R01 and after
the review fixes:
- evidence contract `b1f459e7…`
- instructions `0b9d91cf…`
- node commit requirements `1ddfc0fc…`
- default tool schemas `dd58d427…`
- probe tool-definition hashes: full-payload `d3421479…`, stored-hypothesis
  `f4bf9ab5…`

Existing checkpoints therefore keep their configuration digests. The local
Task06 manifest's 11 differing entries are the nine changed runtime modules,
plus two local-only audit files that did not change and are simply absent from
this tracked-file manifest.

## Remaining limits

- Finding 2's guarantee covers journaled effort only (limits above). Per-seed
  caps are still not batch caps; R02 must sum all attempts across seeds,
  including `unrecorded_requests` and unknown costs.
- Instructions, tool-argument schemas and commit notes are unchanged. Two
  `test_proto_assembly` result fields are new (section 3). These repairs make
  the intended conditioned case executable; they do not show that any model
  will use it. Substantive live usability remains untested (R03).
- Task05/06 historical results stand as recorded. Task05's "complete offline"
  claim now holds for token-conditioned native JSON. Task06's cumulative caps
  now cover journaled abrupt loss in new runs; pre-journal checkpoints keep the
  conservative legacy rule.
