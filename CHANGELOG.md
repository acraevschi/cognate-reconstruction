# Changelog

## Unreleased

Reliability work driven by live `google/gemma-4-e4b` runs in which every
reconstruction was linguistically correct but 43–71% of tool calls were
rejected commit-schema errors.

- Described every `CommittedSoundRule`, `CascadeRuleSpec`, and
  `CommitReconstructionArgs` field, including `validation_call_id`, which
  previously had no description at all.
- Added `remediation` to `ToolError`. A rejected `commit_reconstruction` now
  returns every recorded `(validation_call_id, dsl, source_child_ids)` triple,
  including when the rejection came from schema validation before the handler
  ran.
- Made the per-rule `validation_call_id` optional: an omitted ID is resolved
  from the unique same-session `test_sound_law` validation whose DSL, child
  scope, and segmentation overlay match exactly, and the resolved ID is stored
  in the commit request. Zero or multiple matches are rejected. The
  exact-same-session-validation invariant is unchanged.
- Made `supporting_form_ids` default to the resolved validation's forms, and
  `rationale` optional. A supplied form list must still be a subset, and a rule
  supported by no form is still rejected. `confidence` remains required.
- Added `failed_tool_call_count`, `tool_failures_by_type`, and
  `truncated_response_count` to `AgentNodeMetrics`, all defaulted so existing
  trajectories stay loadable, and surfaced them in `summarize-trajectories` and
  the run-triage skill.
- Gated `high_quality` on a protocol-failure rate of at most 0.25. This is a
  workflow heuristic, not a linguistic judgement; it previously returned true
  for a session that failed 10 of 14 tool calls.
- Added `ProtocolStallError`. Three identical rejections of one tool within a
  node — counted per error signature across the node, not only back to back,
  since a live session alternated between two commit errors — now trigger one
  targeted correction carrying that tool's remediation, and one further
  recurrence ends the node instead of exhausting the turn budget.
- Handled `finish_reason="length"` explicitly with a `response_truncated` event
  and a specific instruction to reply with a smaller tool call, stalling after
  three truncated no-tool responses.
- Added `max_repeated_tool_failures` and `max_truncated_responses` as
  orchestrator parameters, included in the orchestrator's own
  `public_configuration`. `infer` computes and supplies its own configuration
  hash (`cli._provider_and_configuration`), which overrides the orchestrator's;
  it now contains both thresholds, and both are CLI flags. See the checkpoint
  entry below — this is the change that invalidates existing checkpoints.
- Changed `rule_coverage` to `successful_applications /
  applicable_rule_results`, excluding results whose form never contained the
  rule's target, and added `applicable_rule_results` to the diagnostics. A
  correct rule scoped to a whole polytomy no longer scores 0.33 where the same
  rule scoped to one child scores 1.0. Historical diagnostics keep their
  recorded values.
- Kept `schema_version` at `2.0`: the new fields are additive and defaulted,
  and `trajectory_schema_sha256` already records the exact schema per record.
- Added a structural `code` to every tool rejection, drawn from a closed
  vocabulary documented in the new `agent/error_codes.py`. Schema rejections
  derive theirs from the sorted set of `(field location, error type)` pairs with
  list indices normalized, so `rules.0.confidence` and `rules.1.confidence`
  collapse to `schema:rules[].confidence=missing`. `message` is unchanged and
  still carries the full explanation; the code exists only for counting and
  matching.
- Changed the stall signature from `(tool, error type, error message)` to
  `(tool, code)`. Pydantic embeds input values in its messages, so a model whose
  malformed arguments kept changing produced a fresh signature for one
  unchanging mistake and looped until the turn limit. It now stalls.
- Keyed `tool_failures_by_type` on the code rather than the exception class
  name: a real run reported `{"ValidationError": 4}`. The field name is
  deliberately unchanged, since `extra="forbid"` would make existing records
  carrying it unloadable.
- Bounded the stall detector's memory with a trailing window of
  `stall_window_calls` tool calls, default `3 * max_repeated_tool_failures`, with
  successful calls occupying slots. A long, mostly-productive session is no
  longer killed by three well-separated repeats it recovered from each time,
  while the interleave that defeats reset-on-success — bad commit, good test, bad
  commit — still trips. Added to the orchestrator's `public_configuration` and
  exposed as `--stall-window-calls`.
- Added a second stall condition on the same window: when
  `max_window_protocol_failures` of the last `stall_window_calls` calls were
  protocol rejections, whatever their codes, the node draws one correction
  naming them and then raises `ProtocolStallError`. The per-signature rule needs
  the *same* code N times, so a model producing a differently-shaped protocol
  error every turn spent its whole budget and ended in `AgentLoopLimitError`
  with no diagnosis. Defaults to `min(2 * max_repeated_tool_failures,
  stall_window_calls)`; exploratory rejections are excluded from the count.
- Coded the alignment backend's refusals at the tool boundary
  (`alignment-failed`), closing the last path by which a model-reachable
  rejection arrived as `unclassified`.
- Documented in `CascadeRuleSpec` and the `test_rule_cascade` description that a
  cascade rule carries no `validation_call_id`. A live `google/gemma-4-26b-a4b`
  run sent one and was rejected; the schema is unchanged, since accepting the
  field would weaken validation to paper over a documentation gap.
- Added a `tool_failures_by_code` read-only view of `tool_failures_by_type`, so
  new code reads the name that describes the key while the persisted field stays
  where append-only auditability needs it.
- Reported the number of distinct messages behind each code in triage. Two
  unrelated mistakes sharing a code cannot be prevented in general; this makes
  the over-collapse visible so a code can be split on evidence.
- Guarded the triage driver's hand-copied exploratory code set against the real
  classification, and the two checked-in skill copies against each other, with
  tests rather than by removing the duplication — the driver is stdlib-only by
  design so it runs without the harness installed.
- Split rejections into `exploratory` (`dsl-parse-error`, `no-op-rule`,
  `empty-scope`) and `protocol` (everything else, including all `schema:*`
  codes), with anything unclassified failing closed as protocol, and gated
  `high_quality` on the protocol rate alone. A `test_sound_law` rejection for a
  malformed DSL is the hypothesis loop working; counting it like a commit
  reference error scored a model that explores below one that never explores.
- Added `protocol_failure_count` to `AgentNodeMetrics`, defaulting to `None`
  rather than `0` so records written before the split fall back to
  `failed_tool_call_count / tool_call_count` and keep the exact `high_quality`
  verdict they already had. `failed_tool_call_count` remains the total.
- Added a floor of one protocol failure to the `high_quality` gate: a three-call
  identity commit was disqualified at 0.33 by a single slip it recovered from.
  The 0.25 threshold is unchanged and still uncalibrated.
- Surfaced the code in `tool_result` events, in `summarize-trajectories` (which
  now reports `total_protocol_failures` and `total_exploratory_failures`), and in
  the run-triage skill's failure taxonomy.
- Added `NoOpRuleError` to the rule parser so a rule that does nothing can be
  told from one that does not parse without matching on prose.
- Recovered from truncation instead of only naming it. `LLMProvider.complete`
  gained keyword-only `tool_choice` and `max_tokens_override`; the turn after a
  truncated response that carried no tool call is now requested with
  `tool_choice="required"`. This crosses no configuration boundary — the
  request shape is the harness's own responsibility — and is attempted once per
  node, falling back to the ordinary request if the provider raises or still
  returns no tool call. Every scripted provider in `tests/workbench/` accepts
  and ignores both keywords.
- Added `--allow-truncation-backoff` and `--truncation-max-tokens-ceiling`,
  **off by default**, letting the harness double the effective `max_tokens` for
  the rest of a node after a truncated no-tool response, never above the
  ceiling. `max_tokens` is a user-supplied `--provider-config` option, which is
  why this is opt-in and why the adapter merges the override into a copy rather
  than mutating stored options. The base for doubling is the truncated
  response's reported output length; a provider that reports no usage gets no
  backoff, since there would be no way to guarantee the raised value stays
  above what the user configured.
- Added `forced_tool_choice_count` and `truncation_backoff_applied` to
  `AgentNodeMetrics` and a `truncation_recovery` event, both defaulted, so a
  session that only reached a tool call because the harness intervened is not
  silently identical to a clean one. The `ProtocolStallError` message now says
  which recoveries were already tried.
- Made `trajectories.jsonl` a readable input on `--resume`. Committed
  hypotheses lived only in `AgenticNodeReconstructor.prior_reconstructions` for
  one process, so after a resume `get_node_reconstruction` returned nothing for
  checkpoint-restored nodes even though their lexicons were fully available —
  two kinds of cross-node information with different durability and no way to
  tell from outside. `seed_prior_reconstructions` replays completed
  trajectories through the same `summarize_commit` the live path uses.
  `infer --resume` seeds only records that are completed with a commit, name a
  node in the checkpoint, and carry both the current `configuration_sha256` and
  the checkpoint's `run_id`, and prints how many. A missing or unreadable file
  warns and continues; a file that fails schema validation stops the run.
- Filtered seeding on `run_id` as well as the configuration hash. The hash
  cannot separate two invocations — the same model over the same input with the
  same settings hashes identically — and `--trajectories` defaults to one file
  in the working directory, so two runs append to it. Reproduced before fixing:
  a checkpoint from `run-A` seeded node X's hypothesis from `run-B`, pairing one
  run's checkpointed lexicon with another run's rules, decided by which line was
  written last. `--run-id` cannot change during `--resume`, so the filter
  excludes nothing legitimate.
- Documented, without changing behaviour: that `--max-truncated-responses`
  bounds how far `--allow-truncation-backoff` can escalate (two doublings at the
  defaults); that `--stall-window-calls 9` and omitting the flag hash
  differently despite identical behaviour; and that `high_quality` does not
  currently penalise a node that needed truncation recovery. The last is left
  open as part of the threshold-calibration item rather than settled in code.
- Recorded `TrajectoryDatasetBuilder.read_jsonl`'s whole-file materialization
  under "Trajectory and training boundary", now that seeding makes it four
  callers rather than three. Measured rather than estimated: a 434 KB record
  costs 1.5 MB resident and 2.8 MB peak, of which seeding uses 2.4 KB. Left
  unoptimised deliberately — a 30-node family peaks around 85 MB beside a local
  model holding gigabytes — with the fix specified as a streaming variant of the
  reader serving all four callers, and the conditions that should trigger it
  written down. Seeding would need no API change for that: the reconstructor
  already accepts an `Iterable` and retains only the summary.
- Passed the seeds through `ReconstructionService.reconstruct_family` rather
  than setting them beforehand: `clear_run_results` at the top of that method
  also clears prior hypotheses, so anything seeded earlier was silently wiped.
  A test pre-seeds, clears, and fails if that ordering is ever inverted.
- **Existing CLI checkpoints do not resume after this release.** Verified, not
  assumed: a checkpoint written by `infer` before this change was replayed
  against the new code and refused with `checkpoint cannot be resumed because
  these changed: the configuration`. The earlier note in this section claiming
  such checkpoints remain resumable described the state before this change and
  has been corrected. `cli._provider_and_configuration` now hashes
  `instruction_sha256`, the tool-schema hash, and a digest of the `--anchors`
  file, using the same derivations as `AgentOrchestrator._trajectory` so the two
  artifacts report identical values.
- Exposed `--max-repeated-tool-failures`, `--stall-window-calls`, and
  `--max-truncated-responses` as CLI flags and included them, with the two
  truncation-backoff flags, in the configuration hash. `max_window_protocol_failures`
  remains orchestrator-only; the CLI never sets it and its default derives from
  two hashed values, so it cannot change independently from the command line.
- Added `configuration_components` to `FamilyCheckpoint`, defaulted, holding
  named digests of the parts of the configuration hash. A refused resume now
  reads "these changed: the agent instructions" instead of "these hashes
  changed: configuration". `configuration_sha256` is still the decision; a
  checkpoint written without components refuses correctly and keeps the generic
  wording rather than guessing.
- Added a ninth tool, `get_node_reconstruction`, returning the rules, child
  scopes, confidences, anomalies, and summary committed at one node already
  reconstructed in this run, and flagged those nodes with
  `has_committed_hypothesis` in `list_available_nodes`. Each node still gets a
  fresh conversation; a prior rule is exposed as a hypothesis, is never
  citable as support, and has no effect on scoring. Visibility follows the
  traverser's post-order reconstructed-evidence set, so nothing leaks from a
  node that has not been reconstructed yet. Hypotheses from nodes restored by
  `--resume` are not retrievable, since those nodes never ran in the process.

## 0.2.0

- Refocused the installed project on `cognate_reconstruction`.
- Migrated CLDF ingestion and Newick traversal out of the legacy generator.
- Added strict historical-anchor files and CLI policies.
- Added provider-neutral LiteLLM configuration, safe secret handling, request
  normalization tests, retry controls, run budgets, and LM Studio as an
  optional preset.
- Added structured event JSONL, provider/usage metadata, per-node metrics,
  failed trajectories, and atomic checkpoint/resume.
- Added ordered cascade preview, mechanical quality diagnostics, and visible
  identity-without-inspection/testing flags.
- Rejected mechanically empty sound laws such as `p > p`; historical
  trajectories containing them remain auditable but are excluded from
  high-quality exports.
- Versioned trajectories at 2.0 and added validation, summary, filtering, and
  generic training-example export commands.
- Archived the former Stage-1/Stage-2 generator, commands, tests, and metadata
  in the [predecessor repository](https://github.com/acraevschi/llm_cognate_reflexes);
  only the curated lineage CSV is carried forward, as
  `data/historical_lineages.csv`.

## 0.1.0

- Initial Lexibank corpus-generation and reconstruction workbench experiments.
