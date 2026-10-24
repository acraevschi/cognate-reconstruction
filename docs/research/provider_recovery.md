# Task 06 — provider recovery and trustworthy interruption accounting

2026-10-05, `/Users/acraev/Work/cognate-reconstruction`, branch
`burmish-session-evaluation-units`, starting HEAD `7356f66`. Task05's uncommitted
implementation and the owner's local task01 audit were preserved. Work was offline:
no hosted requests, local inference, model discovery/switch, download, push or PR.
This changes recovery and reporting, not linguistic hypotheses or accuracy.
Machine-readable validation and hashes: [provider_recovery_results.json](provider_recovery_results.json).

## Inherited evidence and contracts

The failure audit separates four valid r2/r3 runs from void t36/t36b experiments.
Their void status excludes **all** linguistic quality, including t36/01's root
beam hit. The incident notebook's initial attribution was corrected to TPM, then
a separate 503 outage. The banked retry events themselves lack structured quota/
TPM detail; this implementation does not derive a more specific cause from their
prose. r2 retries recovered historically. r2/00 Maruic is a protocol failure;
its committed root consumes that failed descendant. Neither task03 nor task05's
failed local smoke is provider-exhaustion evidence.

`tests/fixtures/provider_recovery/banked_events.json` contains four redacted saved
retry examples with source SHA-256 and line pointers. It retains only event kind,
node, retry counters and exception class; provider prose/identifiers are omitted.
Fixtures use scripted requests and injectable time. Nothing replays hosted traffic.

The runtime preserves units-v2/count independent-etyma-v1, pieces units-v1,
trajectory 5.0, checkpoint 3.0, raw evaluator task02-v1 and piece evaluator
task04-units-v1. The task05 system/native schemas/node checklist and expanded
commit requests are unchanged. Handles remain same-session state, never checkpoints.
The machine result verifies the task05 manifest differences against this task's
actual edits; linguistic/protocol source files remain at task05's saved hashes.

## Structured taxonomy

Adapter normalization reads explicit status/error code fields and Retry-After /
Google RetryInfo. It never classifies provider prose or error-message substrings.
Only recognized codes, status, exception class, evidence source, response certainty
and delay are retained. Bodies, URLs, header sets, request IDs and credentials
are not persisted. Unrecognized codes are omitted, leaving an explicit unknown.

| `failure_kind` | Evidence | Decision |
| --- | --- | --- |
| `recoverable_rate_limit` | Explicit `rate_limit_exceeded` / `too_many_requests` code | Bounded retry of a rejected request |
| `exhausted_quota_billing` | Explicit insufficient-quota or billing-hard-limit/inactive code | Stop the run immediately |
| `capacity_unavailability` | 500/502/503/504 or explicit unavailable/overloaded code | Bounded retry; no tier/model-availability inference |
| `authentication_configuration` | 400/401/403/404/422 or explicit auth/configuration code | Stop the run immediately |
| `unknown_provider_failure` | Generic 429, RESOURCE_EXHAUSTED/QUOTA_EXHAUSTED without distinguishing detail, or insufficient metadata | Rejected 408/409/425/429 can retry; an uncertain/lost response cannot |

Generic quota exhaustion can describe a rate window; it is not a billing diagnosis.
Raw exception classes alone do not establish quota versus rate or a 503's specific
cause. Existing trajectories without new metadata retain null/unknown or their
existing task02-v1 unspecified infrastructure reading; no legacy file is restamped.
`ProviderTransientError` remains an import-compatible adapter assertion of retryability,
with unknown cause when no metadata is supplied.

## Lifecycle and limits

A successful response continues the same model turn. A rejected request may be
retried without advancing model-visible turn/tool budgets. Defaults are six retries
(seven adapter calls at most), initial backoff 10 seconds, exponential-delay ceiling
60 seconds and a 300-second request/retry elapsed envelope. There is no distributed
limiter. Delay is the larger of capped backoff plus injectable nonnegative jitter
(default zero) and a valid Retry-After. HTTP dates and numeric/structured durations
are supported. A hint that leaves no remaining budget ends the attempt without
sleeping or calling early. Attempts, failed-request time and backoff share the bound.

The LiteLLM adapter disables SDK/LiteLLM retries. Configured nested retries,
retry policies and model fallback dictionaries are refused; nonzero global LiteLLM
retry state is refused before dispatch. A response-lost timeout/connection failure
without an explicit rejection is unknown and is **not** automatically replayed.
An explicit owner-invoked resume restarts the unfinished node; there is no promise
of idempotent provider generation or mid-node recovery.

The adapter shortens request timeout to remaining request/run patience. Requests
remain synchronous: cancellation is observed at request boundaries or on keyboard
interrupt; an SDK/server must honor its timeout to finish an in-flight call. Backoff
polls cancellation and run caps every 0.25 seconds. Sleep, monotonic clock, jitter
and cancellation are injectable; tests advance fake time without minute-long waits.

| Control | Scope |
| --- | --- |
| `--max-retries`, `--retry-backoff-seconds`, `--max-retry-seconds`, `--retry-max-delay-seconds` | One provider request and its retry sequence |
| `--timeout` | One adapter call; shortened by remaining patience/time |
| `--max-turns`, `--max-tool-calls` | One node session |
| `--max-total-turns`, `--max-total-tool-calls`, `--max-run-seconds`, `--max-total-cost-usd` | One family/seed, including recorded effort across resumes |
| `run-benchmark --infer-arg=...` | Forwarded to each seed; **no experiment-wide cap** |

A resume restores cumulative recorded turns, calls, active elapsed time and reported
cost from both JSONL and the latest summary, taking the larger recorded totals.
Paused time between processes is excluded. Missing effort history refuses further
requests when cumulative caps are configured. Missing cost metadata remains
unknown; with a cost cap it stops after the first unpriced response. A lost response
also makes cost accounting incomplete. Reported cost checks act after receipt;
reserve one maximum-size response of headroom using an explicit worst-case estimate
before any paid experiment. This is not a pre-charge billing guarantee. The owner
must bound total experiment time/cost separately across seeds and retry attempts.

Protocol stalls/loop failures still support labelled identity fallback under the
existing give-up policy. Provider errors, exhausted recovery, authentication, hard
quota, cancellation and run budgets bypass that handler: the remaining tree is
unattempted/missing, with no fabricated model failures or identity outputs.

## Completed-node recovery and compatibility

Checkpoints remain atomic completed-node steps. Successful steps and hypotheses
are reused without new provider calls, trajectory appends, node-commit events or
node-complete events. Repeated interruption attempts remain separately auditable;
outcome/node counts use current distinct nodes and effort sums distinct attempts.
Resume verifies full child beams, not only their node IDs, and refuses dangling
internal-child/fallback steps.

The finalized JSONL-before-checkpoint crash window is recoverable under the new
policy only. A complete 5.0 receipt must match run/configuration, saved child beams
and a completed internal subtree. Child receipts must precede the ancestor receipt:
a later identity child cannot launder an earlier fallback-dependent ancestor merely
because their beams are equal. A receipt with missing step is never synthesized.
Unsafe or partial receipts are not recovered. Resume seeding also verifies step
agreement with the checkpoint. The interrupted node's conversation, preview handles,
thought signatures and uncommitted tools are restarted, never migrated.

New 3.0 checkpoints declare `compatibility_policy="operational-retry-v1"`.
Only the four retry controls are removed from the semantic configuration digest;
their digest and original values remain recorded, and changed values are printed
and emitted as `resume_settings_changed`. Operational give-up thresholds retain
advisory handling. Instructions, native/tool schemas, node commit notes, inputs,
tree, anchors, evidence/backend/version, model, sampler, timeout, beam settings and
model-visible turn/tool budgets remain strict. Truncation token-override permission/
ceiling are now explicitly strict rather than bundled into advisory thresholds.
The new hash includes all named behavioral components, closing the prior evidence-
component-only gap. No schema/instruction hash is weakened to force recovery.

Old 3.0 checkpoints default to `strict-v1`: recompute their original digest with
original retry settings and retain strict checks. There is no automatic migration
or deletion of an old digest. Changed legacy advisory controls are conservatively
refused because their saved composite cannot distinguish token overrides from
patience. Missing component digests retain the exact configuration check. Existing
1.0/2.0 checkpoints remain audit-readable and explicitly unsafe to resume under
units-v2. Historical 2.0/3.0/4.0 trajectories remain readable. Old inventory
execution requiring units-v1 still needs its original checkout.

## Artifacts and interpretation

New trajectories add nullable `failure_kind`, `failure_error_type`,
`provider_failure` and `interruption_reason`. Events include structured retry,
`node_interrupted`, `run_interrupted` and changed-resume-settings records. Model
protocol failures retain `node_failed`; direct/ancestor fallback semantics remain.

`infer` writes atomic `run_summary.json` beside its requested result even when no
result can be produced. `complete=false` / `status=interrupted`, cause/stop reason,
planned/attempted/completed/restored/unattempted/fallback node IDs, cost coverage,
usage, retry controls, completed-node-only recovery and task02-v1 missing evaluations
are explicit. Partial realized steps are retained without inventing a full result.
Successful results include the lifecycle summary and restored hypotheses.

`active_trajectory_ids` identifies current realized outcomes. Prior fallback-dependent
ancestor receipts stay in JSONL for audit but cannot supply output after a resumed
attempt interrupts earlier in the tree. An interruption summary takes precedence
over a stale result.json. The evaluator, inspect-run and sweep use that view.
Committed-node conditional scores, full planned-set outcomes, direct fallback and
ancestor dependencies remain distinct. Unvisited nodes receive no provider-specific
cause. Missing completed-step output remains missing; score definitions, target/proxy
validity, selection and linguistic hypotheses are unchanged.

Sweep reports add interruption causes/reasons, completed/unattempted counts and
per-seed plans. VOID.txt at seed/sweep level explicitly excludes that seed from
linguistic quality aggregates, including committed root hits, while retaining its
raw audit outcome and all-run operational coverage. No cause is parsed from VOID
text. Ordinary interrupted runs retain their full planned set and completed outputs;
a provider interruption alone does not retroactively mark every completed node void.

## Commands and validation

Focused final command:

```sh
conda run -n llm_reconstruction python -m pytest -q tests/workbench/test_provider_recovery.py tests/workbench/test_recovery_and_provider.py tests/workbench/test_gemini_provider.py tests/workbench/test_node_failure_fallback.py tests/workbench/test_resume_integrity.py tests/workbench/test_multi_node_targets_and_sweep.py tests/workbench/test_evaluation_contract.py tests/workbench/test_truncation_recovery.py tests/workbench/test_protocol_revision.py tests/workbench/test_inspect_run.py
```

Result: **206 passed, 15.08 seconds**. Earlier focused runs exposed a legacy timeout-
to-fallback expectation, fixture node-name errors, a run-ID display-label mismatch
and corruption-message regression. They were corrected without rewriting old scores.
Final focused tests cover recovery/Retry-After, persistent 503, quota/auth, ambiguous
429, absent cost, reported cap, cancellation/keyboard interrupt, transport uncertainty,
nested SDK retry refusal, CLI/driver forwarding, post-node interruption, retry-only
resume, semantic refusal, old strict checkpoints, orphan receipt recovery, event/
output idempotence, cumulative caps, stale ancestors, void exclusion and mixed seeds.
All provider calls are fake; no API keys or external network are needed.

Portable command (one final run):

```sh
conda run -n llm_reconstruction python -m pytest -q -k 'not local_run_artifacts'
```

Result: **680 passed, 41 deselected, 67.35 seconds**; one portable run. CLI and
tracked driver help and whitespace checks pass. No live usability or accuracy
improvement is claimed.

Example forwarding (documentation only):

```sh
cognate-reconstruct run-benchmark --benchmark FROZEN_PAYLOAD --model MODEL --seeds 2 --out-dir NEW_RUN_DIR --no-oracle --infer-arg=--max-retries=6 --infer-arg=--retry-backoff-seconds=10 --infer-arg=--max-retry-seconds=300 --infer-arg=--retry-max-delay-seconds=60 --infer-arg=--max-run-seconds=1800
conda run -n llm_reconstruction python tools/evaluate_run.py RUN_DIR --payload FROZEN_PAYLOAD --json
```

Task06 is independently delivered after the required checks. Task07 still needs
task05's substantive usability follow-up, final frozen interface/manifest/cap review
and the owner's choice to start. Recovery does not establish a usable linguistic arm.

## R01 amendment — abrupt-loss accounting, 2026-10-23

The guarantee above covered recorded or gracefully finalized effort. After an
abrupt exit, an empty or partial checkpoint made missing history look
complete. New checkpointed runs now keep an fsynced `request-journal-v1`
(`<checkpoint>.requests.jsonl`). It is written before each counted turn,
provider request and tool call. Usage records add `effort_counts_known`,
`unrecorded_requests` and `usage_accounting_version="abrupt-loss-v1"`.

- **Turn and tool-call caps.** These count journaled lost effort exactly.
- **Cost.** Known priced responses are restored. In-flight and unpriced requests
  stay unknown, and a cost cap refuses.
- **Elapsed time.** This is a lower bound, and a time cap refuses.
- **History flag.** `history_complete` stays false.
- **Legacy checkpoints.** One without a run summary is no longer certified
  complete: it refuses cumulative caps and continues flagged without them.

The sentence "missing cost/history cannot silently restart a capped seed's spend
at zero" now holds for journaled abrupt loss. It is not a guarantee for effort
lost together with its journal. See [R01 repairs](post_review_contract_repairs.md).
