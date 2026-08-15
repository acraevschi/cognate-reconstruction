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
