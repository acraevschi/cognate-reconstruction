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
  `public_configuration`. Note that `infer` computes and supplies its own
  configuration hash (`cli._provider_and_configuration`), which overrides the
  orchestrator's and does not contain these two values, so **CLI checkpoints
  written before this release remain resumable** and a change to either
  threshold is not detected on `--resume`. Neither threshold is exposed as a
  CLI flag yet. `agent/SKILL.md` and the tool schemas also changed, and the
  checkpoint hash covers neither.
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
  commit — still trips. Added to the orchestrator's `public_configuration`; still
  no CLI flag, so a change to it is not detected on `--resume`.
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
