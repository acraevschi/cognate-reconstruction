"""Additive report schemas; no model-facing schema imports these objects."""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from cognate_reconstruction.schemas.common import WorkbenchModel
from cognate_reconstruction.schemas.historical import HistoricalTargetEvaluation


class EvaluationSummary(WorkbenchModel):
    planned_concepts: int = Field(ge=0)
    available_outputs: int = Field(ge=0)
    missing_outputs: int = Field(ge=0)
    committed_node_concepts: int = Field(ge=0)
    committed_outputs: int = Field(ge=0)
    fallback_outputs: int = Field(ge=0)
    unknown_commitment_outputs: int = Field(ge=0)
    committed_top_hits: int = Field(ge=0)
    output_top_hits: int = Field(ge=0)
    fallback_top_hits: int = Field(ge=0)
    conditional_committed_top_exact_rate: float | None = None
    conditional_committed_mean_ned: float | None = None
    conditional_committed_ned_count: int = Field(ge=0)
    end_to_end_model_top_exact_rate: float | None = None
    end_to_end_output_top_exact_rate: float | None = None
    denominator_note: str = (
        "Exact conditional: planned concepts at committed nodes, missing is a miss. "
        "NED conditional: available committed outputs only. End-to-end: all planned "
        "target concepts. Model hits exclude direct fallbacks and unknown commitments."
    )


class NodeEvaluationOutcome(WorkbenchModel):
    node_id: str
    output_kind: Literal["committed", "identity_fallback", "unknown_commitment", "missing"]
    failure_kind: str | None = None
    failure_error_type: str | None = None
    missing_concept_ids: tuple[str, ...]
    evaluation: HistoricalTargetEvaluation


class OperationalNodeOutcome(WorkbenchModel):
    node_id: str
    status: str
    failure_kind: str | None = None
    failure_error_type: str | None = None


class RunEvaluationReport(WorkbenchModel):
    evaluator_version: Literal["task02-v1"] = "task02-v1"
    run_status: str
    planned_node_ids: tuple[str, ...]
    targets: tuple[NodeEvaluationOutcome, ...]
    raw_target_summary: EvaluationSummary
    validated_target_summary: EvaluationSummary
    excluded_from_validated_node_ids: tuple[str, ...]
    operational_nodes: tuple[OperationalNodeOutcome, ...] = ()
    selection_provenance: dict[str, str | bool] | None = None
    notes: tuple[str, ...] = ()
    attempted_node_ids: tuple[str, ...] = ()
    completed_node_ids: tuple[str, ...] = ()
    interruption_reason: str | None = None
    linguistic_exclusion_reason: str | None = None
