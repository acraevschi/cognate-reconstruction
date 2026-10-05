"""Planned-set coverage, faithful completed-step salvage and labelled provenance."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from typing import Any
from pathlib import Path

from cognate_reconstruction.evaluation.targets import _evaluate_target
from cognate_reconstruction.evaluation.diagnostics import diagnostic_text
from cognate_reconstruction.schemas.evaluation import (
    EvaluationSummary, NodeEvaluationOutcome, RunEvaluationReport, OperationalNodeOutcome,
)
from cognate_reconstruction.schemas.historical import HistoricalFormRole, TargetValidity
from cognate_reconstruction.schemas.traversal import ReconstructionStep
from cognate_reconstruction.tree import assign_node_ids, parse_newick


def load_result_or_summary(run_dir: Path):
    """The latest interruption summary overrides a stale pre-resume result."""
    summary_path = run_dir / "run_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else None
    if summary and summary.get("status") == "interrupted":
        return summary
    result_path = run_dir / "result.json"
    return json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else summary


def step_from_artifact(raw) -> ReconstructionStep:
    if isinstance(raw, ReconstructionStep):
        return raw
    # result.json includes these three read-only computed RuleApplicationReport
    # properties; canonical checkpoints/JSONL omit them. Ignore only known
    # computed properties, retaining strict validation for all actual fields.
    cleaned = dict(raw)
    cleaned["rule_reports"] = [
        {k: v for k, v in report.items() if k not in {"words_applied", "anchors_matched", "exceptions"}}
        for report in raw.get("rule_reports", ())
    ]
    return ReconstructionStep.model_validate_json(json.dumps(cleaned))


def trajectory_from_artifact(raw):
    from cognate_reconstruction.agent.trajectory import AgentTrajectory
    cleaned = dict(raw)
    if raw.get("reconstruction_step"):
        cleaned["reconstruction_step"] = step_from_artifact(raw["reconstruction_step"]).model_dump(
            mode="json", exclude_computed_fields=True,
        )
    return AgentTrajectory.model_validate_json(json.dumps(cleaned))


def failure_kind(error_type: str | None) -> str | None:
    if error_type is None:
        return None
    if error_type in {"AgentLoopLimitError", "ProtocolStallError"}:
        return "model_protocol_failure"
    if error_type in {"Timeout", "TimeoutError", "APIConnectionError", "RateLimitError",
                       "ServiceUnavailableError", "InternalServerError", "ProviderError"}:
        return "infrastructure_interruption_cause_unspecified"
    if error_type in {"RunBudgetExceeded", "RunBudgetExceededError"}:
        return "resource_interruption"
    return "unknown"


def summarize(targets: Sequence[NodeEvaluationOutcome]) -> EvaluationSummary:
    planned = available = committed_plan = committed_out = fallback = unknown = 0
    committed_hits = all_hits = fallback_hits = 0
    neds: list[float] = []
    for target in targets:
        e = target.evaluation
        planned += e.evaluated_concepts
        outputs = e.evaluated_concepts - e.missing_reconstruction_concepts
        available += outputs
        all_hits += e.top_exact_matches
        if target.output_kind == "committed":
            committed_plan += e.evaluated_concepts
            committed_out += outputs
            committed_hits += e.top_exact_matches
            neds.extend(c.top_normalized_edit_distance for c in e.concepts
                        if c.top_normalized_edit_distance is not None)
        elif target.output_kind == "identity_fallback":
            fallback += outputs
            fallback_hits += e.top_exact_matches
        elif target.output_kind == "unknown_commitment":
            unknown += outputs
    return EvaluationSummary(
        planned_concepts=planned, available_outputs=available,
        missing_outputs=planned - available, committed_node_concepts=committed_plan,
        committed_outputs=committed_out, fallback_outputs=fallback,
        unknown_commitment_outputs=unknown, committed_top_hits=committed_hits,
        output_top_hits=all_hits, fallback_top_hits=fallback_hits,
        conditional_committed_top_exact_rate=committed_hits / committed_plan if committed_plan else None,
        conditional_committed_mean_ned=sum(neds) / len(neds) if neds else None,
        conditional_committed_ned_count=len(neds),
        end_to_end_model_top_exact_rate=committed_hits / planned if planned else None,
        end_to_end_output_top_exact_rate=all_hits / planned if planned else None,
    )


def evaluate_run(
    payload,
    result: Mapping[str, Any] | None,
    trajectories: Sequence = (),
    *,
    exit_code: int | None = None,
    selection_provenance: dict[str, str | bool] | None = None,
) -> RunEvaluationReport:
    """Payload supplies the planned set; result and trajectories supply outputs.

    No calls, step synthesis or artifact mutation. Completed trajectories may
    salvage absent results; failed trajectories never supply outputs.
    """
    # Attempts remain in append-only JSONL; outcomes use the latest node record.
    # A resumed ancestor can legitimately replace an earlier fallback-tainted one.
    artifact_run_id = (result or {}).get("run_id") or ((result or {}).get("lifecycle_summary") or {}).get("run_id")
    lifecycle = (result or {}).get("lifecycle_summary") or result or {}
    active_ids = lifecycle.get("active_trajectory_ids")
    trajectories = tuple({t.node_id: t for t in trajectories
                          if (artifact_run_id is None or t.run_id == artifact_run_id)
                          and (active_ids is None or t.trajectory_id in active_ids)}.values())
    steps = {}
    for raw in ((result or {}).get("snapshot") or {}).get("steps", ()):
        step = step_from_artifact(raw)
        steps[step.parent_node_id] = step
    completed = {t.node_id for t in trajectories if t.completed}
    notes = []
    for trajectory in trajectories:
        if trajectory.completed and trajectory.reconstruction_step is not None:
            step = trajectory.reconstruction_step
            if trajectory.node_id in steps and steps[trajectory.node_id] != step:
                raise ValueError(f"conflicting saved steps for {trajectory.node_id}")
            if trajectory.node_id not in steps:
                steps[trajectory.node_id] = step
                notes.append(f"salvaged completed deterministic step: {trajectory.node_id}")
    failures = {f["node_id"]: f for f in (result or {}).get("node_failures", ())}
    direct_fallbacks = {
        node for node, step in steps.items() if step.diagnostics.failure_fallback
    } | set(failures)
    # Exact tree ancestry, not trajectory order or target-list order.
    root = parse_newick(payload.newick)
    ids = assign_node_ids(root)
    descendants = {}
    leaves = {}

    def visit(node):
        node_id = ids[id(node)]
        below = set()
        leaf_set = {node_id} if node.is_leaf else set()
        for child in node.children:
            child_id = ids[id(child)]
            visit(child)
            below |= {child_id} | descendants[child_id]
            leaf_set |= leaves[child_id]
        descendants[node_id] = below
        leaves[node_id] = leaf_set

    visit(root)
    latest = {t.node_id: t for t in trajectories}
    def cause_for(node):
        record = failures.get(node, {})
        trajectory = latest.get(node)
        error_type = record.get("error_type") or (trajectory.failure_error_type if trajectory and not trajectory.completed else None)
        cause = record.get("failure_kind") or (trajectory.failure_kind if trajectory and not trajectory.completed else None)
        return error_type, cause or failure_kind(error_type)
    operational = []
    for node in sorted(n for n in descendants if descendants[n]):
        failed = any(t.node_id == node and not t.completed for t in trajectories)
        error_type, cause = cause_for(node)
        status = ("identity_fallback" if node in direct_fallbacks else
                  "committed" if node in completed and node in steps else
                  "committed_without_saved_output" if node in completed else
                  "unknown_commitment" if node in steps else
                  "failed_no_output" if failed else "unvisited_or_missing")
        operational.append(OperationalNodeOutcome(
            node_id=node, status=status, failure_error_type=error_type,
            failure_kind=cause or ("unknown" if failed or node in direct_fallbacks else None),
        ))
    targets = []
    for binding in payload.historical_form_bindings:
        if binding.role is not HistoricalFormRole.TARGET:
            continue
        node = binding.node_id
        if node not in descendants:
            raise ValueError(f"target {node} is absent from the planned tree")
        step = steps.get(node)
        committed = node in completed and node not in direct_fallbacks
        kind = ("identity_fallback" if node in direct_fallbacks else
                "committed" if committed else "missing" if step is None else "unknown_commitment")
        e = _evaluate_target(
            binding, step,
            observed_lexicons=[l for l in payload.lexicons if l.variety_id in leaves[node]],
            model_committed=committed if kind != "unknown_commitment" else None,
            descendant_fallback_node_ids=tuple(sorted(descendants[node] & direct_fallbacks)),
        )
        if node in direct_fallbacks and not e.failure_fallback:
            e = e.model_copy(update={"failure_fallback": True})
        error_type, cause = cause_for(node)
        failed_trajectory = any(t.node_id == node and not t.completed for t in trajectories)
        if cause is None and (failed_trajectory or node in direct_fallbacks):
            cause = "unknown"
        targets.append(NodeEvaluationOutcome(
            node_id=node, output_kind=kind, failure_kind=cause,
            failure_error_type=error_type,
            missing_concept_ids=tuple(c.concept_id for c in e.concepts if c.top_candidate_id is None),
            evaluation=e,
        ))
    validated = [t for t in targets if t.evaluation.target_validity is TargetValidity.VALIDATED]
    status = ("abandoned_no_result" if result is None else "result_written_incomplete_or_unknown"
              if any(n.status not in {"committed", "identity_fallback"} for n in operational)
              else "finished_with_fallbacks" if direct_fallbacks else "finished")
    if (result or {}).get("status") == "interrupted":
        status = "interrupted"
    if result is not None and (result or {}).get("status") != "interrupted" and exit_code not in (None, 0):
        status = "result_written_nonzero_exit"
    return RunEvaluationReport(
        attempted_node_ids=tuple(sorted(set(latest))),
        completed_node_ids=tuple(sorted(completed & set(steps) - direct_fallbacks)),
        interruption_reason=(result or {}).get("interruption_reason"),
        run_status=status, planned_node_ids=tuple(t.node_id for t in targets),
        targets=tuple(targets), raw_target_summary=summarize(targets),
        validated_target_summary=summarize(validated),
        excluded_from_validated_node_ids=tuple(t.node_id for t in targets if t not in validated),
        notes=tuple(notes),
        operational_nodes=tuple(operational),
        selection_provenance=selection_provenance,
    )


def render_text(report: RunEvaluationReport) -> str:
    lines = [f"Evaluation {report.evaluator_version}: {report.run_status}"]
    if report.linguistic_exclusion_reason:
        lines.append(f"Excluded from linguistic quality: {report.linguistic_exclusion_reason}; raw outcomes retained for audit")
    lines.append(f"Sample selection: {report.selection_provenance or 'not recorded; consult the frozen definition'}")
    for node in report.operational_nodes:
        lines.append(f"node {node.node_id}: {node.status}; cause {node.failure_kind or 'none recorded'}; "
                     f"error type {node.failure_error_type or 'unknown/unrecorded'}")
    for label, summary in (("raw targets", report.raw_target_summary),
                           ("validated targets", report.validated_target_summary)):
        lines.append(
            f"{label}: {summary.planned_concepts} planned; {summary.available_outputs} outputs; "
            f"{summary.missing_outputs} missing; {summary.fallback_outputs} fallback; "
            f"{summary.unknown_commitment_outputs} unknown commitment"
        )
        lines.append(
            f"  committed exact {summary.committed_top_hits}/{summary.committed_node_concepts}; "
            f"end-to-end model {summary.committed_top_hits}/{summary.planned_concepts}; "
            f"end-to-end all outputs {summary.output_top_hits}/{summary.planned_concepts}; "
            f"committed NED {summary.conditional_committed_mean_ned} "
            f"(available outputs n={summary.conditional_committed_ned_count})"
        )
    for target in report.targets:
        e = target.evaluation
        validity = e.target_validity.value if e.target_validity else "unknown validity"
        lines.append(f"{target.node_id}: {validity}; {target.output_kind}; "
                     f"raw exact {e.top_exact_matches}/{e.evaluated_concepts}; "
                     f"descendant fallbacks {list(e.descendant_fallback_node_ids or ())}; "
                     f"failure {target.failure_kind or 'none recorded'}")
        if e.target_validity_note:
            lines.append(f"  {e.target_validity_note}")
        s = e.selection
        if s is not None:
            lines.append(f"  selection eligible {s.eligible_concepts}; gold-assisted daughter oracle "
                         f"{s.oracle_reachable_concepts}; outside-selection top "
                         f"{s.outside_selection_top_hits} {list(s.outside_selection_top_hit_ids)}; "
                         f"beam {s.outside_selection_beam_hits} {list(s.outside_selection_beam_hit_ids)}")
        lines.append(f"  missing IDs {list(target.missing_concept_ids)}")
        lines.append(f"  {diagnostic_text(e)}")
    lines.append("NED: lower is better. Per-word B-Cubed measures repetition, not across-word mappings.")
    return "\n".join(lines) + "\n"
