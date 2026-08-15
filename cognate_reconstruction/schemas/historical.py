"""Explicit historical-form roles and held-out target evaluation."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from cognate_reconstruction.schemas.common import NonEmptyStr, WorkbenchModel
from cognate_reconstruction.schemas.lexicon import LexicalForm


class HistoricalFormRole(StrEnum):
    ANCHOR = "anchor"
    TARGET = "target"


class HistoricalLineageRelation(WorkbenchModel):
    branch_id: NonEmptyStr
    descendant_variety_id: NonEmptyStr
    evidence: NonEmptyStr | None = None
    source_reference: NonEmptyStr | None = None
    source_row: int | None = Field(default=None, ge=1)


class HistoricalFormBinding(WorkbenchModel):
    """Attested forms bound explicitly to one runtime internal tree node."""

    node_id: NonEmptyStr
    role: HistoricalFormRole
    source_variety_id: NonEmptyStr
    source_declared_historical: bool = False
    forms: tuple[LexicalForm, ...] = Field(min_length=1)
    lineage_relations: tuple[HistoricalLineageRelation, ...] = ()
    source_reference: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_forms(self) -> HistoricalFormBinding:
        form_ids: set[str] = set()
        for form in self.forms:
            if form.variety_id != self.node_id:
                raise ValueError(
                    f"historical form {form.form_id!r} must use target node "
                    f"variety_id {self.node_id!r}"
                )
            if form.form_id in form_ids:
                raise ValueError(
                    f"duplicate historical form ID {form.form_id!r}"
                )
            form_ids.add(form.form_id)
        return self


class HistoricalBindingRequest(WorkbenchModel):
    source_variety_id: NonEmptyStr
    node_id: NonEmptyStr
    role: HistoricalFormRole
    lineage_relations: tuple[HistoricalLineageRelation, ...] = ()
    source_reference: NonEmptyStr | None = None


class HistoricalBindingFile(WorkbenchModel):
    """Strict preparation-time mapping from source varieties to tree nodes."""

    schema_version: Literal["1.0"] = "1.0"
    bindings: tuple[HistoricalBindingRequest, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bindings(self) -> HistoricalBindingFile:
        sources = [binding.source_variety_id for binding in self.bindings]
        if len(sources) != len(set(sources)):
            raise ValueError(
                "a historical source variety may have only one role per payload"
            )
        node_roles = [
            (binding.node_id, binding.role) for binding in self.bindings
        ]
        if len(node_roles) != len(set(node_roles)):
            raise ValueError("historical node/role bindings must be unique")
        return self


class TargetConceptEvaluation(WorkbenchModel):
    concept_id: NonEmptyStr
    target_form_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)
    target_segment_alternatives: tuple[tuple[NonEmptyStr, ...], ...] = Field(
        min_length=1
    )
    top_candidate_id: NonEmptyStr | None = None
    top_candidate_segments: tuple[NonEmptyStr, ...] | None = None
    top_exact_match: bool
    beam_exact_match: bool


class HistoricalTargetEvaluation(WorkbenchModel):
    """Mechanical comparison against forms withheld from the model prompt."""

    node_id: NonEmptyStr
    source_variety_id: NonEmptyStr
    source_reference: NonEmptyStr | None = None
    target_form_count: int = Field(ge=1)
    evaluated_concepts: int = Field(ge=0)
    missing_reconstruction_concepts: int = Field(ge=0)
    top_exact_matches: int = Field(ge=0)
    beam_exact_matches: int = Field(ge=0)
    top_exact_rate: float = Field(ge=0.0, le=1.0)
    beam_exact_rate: float = Field(ge=0.0, le=1.0)
    concepts: tuple[TargetConceptEvaluation, ...]

