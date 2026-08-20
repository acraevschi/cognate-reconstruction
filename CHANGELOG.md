# Changelog

## Unreleased

Loop resilience, driven by a 7-node Polynesian benchmark that failed three ways
in three attempts and never reached the root.

- Let a `test_rule_cascade` preview satisfy the per-rule validation
  requirement. The cascade applied the rule to real forms *and* in its
  committed order, which is strictly more evidence than a standalone test. The
  workflow `SKILL.md` prescribes — test, cascade, refine, commit — previously
  had no legal path through the commit contract. The bound record and its
  `validation_kind` are stored in the commit.
- Derived the validation match key from the parsed rule instead of the DSL
  source string, so `t > k` and `t > k / _` — identical to the engine — no
  longer reject each other. `rule_id` stays lexical; it is persisted.
- Narrowed `validation-ambiguous` to matches that disagree about which forms
  the rule applied to. Matches that agree are one experiment run twice and now
  resolve deterministically, preferring a cascade record and then the most
  recent.
- Made a rule-specific rejection answer the question it raised: the remediation
  names that rule's own DSL, the near matches that differ only in environment
  (the refinement case), and the call that would unblock the commit, before the
  session catalogue.
- Made a node failure non-fatal. The failure is recorded in
  `result.json:node_failures`, an identity fallback is committed so the walk
  continues, and the step is marked `diagnostics.failure_fallback` — distinct
  from `identity_reconstruction`, which it does not overload. Fallback nodes are
  excluded from the reconstructed-node counts, from `high_quality`, and from
  trajectory export, and are surfaced by `inspect-run` at the top of its report.
  Added `--fail-fast` and `--max-failed-nodes` (default 3). A run-budget failure
  is never absorbed into a fallback.
- Kept a fallback node, and every node above it, out of the checkpoint, so
  `--resume` re-runs exactly the nodes whose reconstruction a failure cost.
- Removed the give-up thresholds from `configuration_sha256`. They cannot change
  a committed rule or a beam, and hashing them meant the one change a stall
  invites — loosen and resume — was the change that invalidated the checkpoint.
  They stay recorded, and a resume reports that they moved. **This and the added
  `validation_kind` field invalidate existing checkpoints.**
- Forced a tool call after *every* truncated no-tool response rather than once
  per node, stopping only if the backend refuses `tool_choice="required"`, and
  named the observed output token counts in the truncation stall so a new
  `max_tokens` is not a guess.

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
- Added `inspect-run --run-dir`, the supported artifact-facing report over
  `result.json` and `trajectories.jsonl` (`events.jsonl` when present). Plain
  text on stdout; `--html PATH` writes one self-contained file with no external
  CSS, JS, fonts, or images, readable in light and dark, with rule tables
  scrolling inside their own container; `--all-forms` lifts the 40-form cap. Per
  node it reports the session shape, the committed hypothesis, the deterministic
  diagnostics, the best lexicon, and `high_quality` **with the condition it
  failed**. A missing `events.jsonl` drops only the event counts; a missing
  `result.json` falls back to the trajectories' own beams.
- Added a report-only cross-node consistency section: one DSL committed at
  several nodes with materially different confidence, adjacent nodes mapping the
  same target in the same environment to different things, and a correspondence
  established below a node that the node never mentions. Worded as observations,
  headed by a line saying the harness does not judge historical correctness, and
  scored by nothing — a test asserts a contradictory family and a consistent one
  get identical `high_quality` verdicts. Penalising any of it changes what counts
  as a valid reconstruction and stays a research-owner decision.
- Made `driver.py triage` shell out to `inspect-run` for the artifact sections
  instead of keeping its own copy of them. Triage keeps what only `events.jsonl`
  knows: the turn-by-turn timeline and the failure taxonomy, which is still the
  only source of rejection counts for runs written before failure accounting.
- Added `AgentTrajectory.high_quality_failure_reasons`, and defined
  `high_quality` as that tuple being empty. The report states why the gate
  failed rather than describing the gate, so the two cannot drift.
- Required a per-rule `rationale` on commits carrying more than one rule, with a
  new `missing-rule-rationale` code and a remediation naming the exact
  `rule_id`s. The schema keeps the field optional, so existing records stay
  loadable, and single-rule commits are unaffected — the measured transcription
  friction that made `rationale` optional was entirely on those. One `summary`
  cannot attribute reasoning to one of several rules, and a corpus filter that
  discards every multi-rule commit for missing reasoning is the worse outcome.
- Added `schema_variants` and `current_trajectory_schema_sha256` to
  `summarize-trajectories`: record counts grouped by `trajectory_schema_sha256`
  with the current digest marked. `schema_version` stays `2.0` — the rule, now
  written down in the README, is to bump it when a reader must behave
  differently, never merely because fields were added. A regression test widens
  the literal to `Literal["2.0", "2.1"]` and asserts a real 2.0 file still loads
  and still says 2.0.
- Committed `tests/workbench/fixtures/trajectory_real_pre_change.jsonl`, a
  genuine pre-change live run copied verbatim out of `runs/`, and asserted
  against it that the record loads and keeps its exact `high_quality` verdict.
  The claim previously rested only on globbing gitignored `runs/`: clearing that
  directory reduced the parametrization to zero cases and left the suite green
  with the guarantee gone. The glob stays as opportunistic extra coverage, so
  `pytest -q -k "not local_run_artifacts"` is now the authoritative count.
- Noted, without changing it, that `result.json` is written with computed fields
  included and therefore does not round-trip through its own `extra="forbid"`
  model. `inspect-run` reads it as JSON and validates the fragments it uses.
- Added `docs/report_reject_or_score.md`, recording the reasoning the
  mechanical/workflow/linguistic invariant compresses into one line: the three
  questions a run can be asked, why a report is reversible and a gate is not,
  and the rule for deciding which a new signal belongs to. The worked example is
  the cross-node observation that fires on a perfectly correct run — report it
  and a human reads a line; score it and a correct reconstruction is excluded
  from the corpus.

### Making linguistic evidence affordable to look at

Driven by a 10-language, 46-concept Polynesian benchmark that could not be
completed in three attempts. One `get_alignments` call for six concepts across
two languages returned 31 KB and moved a session from 5,003 to 34,286 tokens; the
same call across ten languages returned 2,885 KB. Inspecting evidence cost more
context than reasoning about it, so the model committed on 5, 12, 12 and 8 of 46
concepts.

- Stopped re-embedding the alignments in every pairwise view.
  `CorrespondenceMap.alignments` became `alignment_ids`, with the alignments held
  once on `MultipleAlignmentMap` and a validator that keeps every reference —
  pairwise IDs and example columns alike — resolvable against them. With N nodes
  the alignments were previously serialized `1 + N·(N−1)/2` times.
- Added `detail` to `GetAlignmentsArgs`, defaulting to `"summary"`: correspondence
  records carry a true occurrence `count` plus at most three
  `(alignment_id, column_index)` references into alignments that are in the
  payload anyway. `"full"` still returns every column occurrence with its
  contexts.
- Renamed `CorrespondenceSummary.observations` to `example_observations`, added
  `example_columns`, and relaxed `validate_counts` from `count == len(...)` to
  bounding the samples by the count. The old field name and the old validator
  together were what *forced* the full trace to be present; `count` is the true
  count under both renderings, and no sample is ever passed off as complete.
- Shortened `alignment_id` from every participating variety spelled out to
  `msa-<selection digest>:<concept>:<cognate set>`. The selection stays in the ID
  because the same cognate set aligned against different daughters is different
  aligned material, but 308 characters repeated once per reference was 700 KB of a
  single ten-node call.
- Raised the `get_alignments` concept cap from 12 to 24 on measurement, not
  preference: 24 concepts cost 41 KB across two nodes and 82 KB across three. The
  docstring states what the cap does not do — it bounds concepts, not bytes, since
  the pairwise term is quadratic in the node count.
- Added `summarize_correspondences`, the tenth tool: correspondence sets over the
  whole evidence set at once — the n-tuple of aligned segments across the selected
  nodes with its support count — ordered by support, with `min_support` defaulting
  to 2, an optional `segment`/`segment_node_id` filter (`Ø` for a gap, as in the
  DSL), and `list_concepts`-style pagination. It deliberately takes no batching
  bound on its input, because recurrence is invisible in a batch; the output is
  bounded instead. `total_set_count`, `matched_set_count`, and
  `suppressed_below_min_support` are reported so a page of thirty rows says
  whether there is a tail. 216 sets over ten Polynesian daughters and all 46
  concepts, 28 KB, matching `tools/correspondence_inventory.py` set for set.
- Populated `ReconstructionStep.correspondence_maps`, which had been declared,
  serialized as `[]` into every artifact by every run, and populated by nothing.
  It uses the compact rendering and is recorded only when the traverser supplies
  an evidence context, so the analysis scripts in `tools/` still pay nothing.
  448 KB of a 10,017 KB `result.json` on the seven-node Polynesian benchmark
  (+4.5%), which is twice the 232 KB the snapshot alone shows: a step is
  serialized both in `snapshot.steps` and as the trajectory's
  `reconstruction_step`. Nothing in it reaches a rule, a candidate, or the beam.
- Dropped superseded evidence results from the live prompt. When a read-only
  evidence call re-requests a selection an earlier call covered in full, the
  earlier tool message content is replaced by a `{"compacted": true, ...}`
  placeholder naming the tool, its call ID, and the call that superseded it;
  `compacted_tool_results` counts it per node and a `context_compaction` event
  records it. Supersession requires full coverage, not overlap, and every
  non-selection argument must match exactly. The most recent result for a tool,
  rejections, validations, cascade previews, overlays, and commits are never
  eligible. **The trajectory keeps the full content**: only the live prompt
  shrinks, and the two are allowed to diverge because a record edited to fit is
  worthless as a record.
- Rewrote the required workflow in `SKILL.md`: survey the correspondence
  inventory, read it by support, narrow it by segment, and only then pull
  alignments for the concepts a set names — and said plainly that a correspondence
  with support 1 is residue rather than evidence. The instruction text and the
  tool schemas are both hashed into checkpoint compatibility, so **every existing
  checkpoint refuses to resume**. That is correct: a resumed run would otherwise
  finish its remaining nodes under a different workflow from the ones already in
  the checkpoint.

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
