"""Explicit historical-form roles and held-out target evaluation."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from cognate_reconstruction.schemas.common import NonEmptyStr, WorkbenchModel
from cognate_reconstruction.schemas.lexicon import LexicalForm
from cognate_reconstruction.schemas.metrics import MetricDistribution


class HistoricalFormRole(StrEnum):
    ANCHOR = "anchor"
    TARGET = "target"


class GoldEvidenceKind(StrEnum):
    """What a gold historical form actually is, which is not always an observation.

    A published proto-form is somebody's reconstruction. Scoring against
    Proto-Polynesian measures agreement with Walworth's analysis, not with the
    sixth century; scoring against Latin measures agreement with an attested
    language. Both are useful and they are not the same claim, so the
    distinction travels with the binding and is printed wherever the score is.

    `None` means the binding predates the field or its builder did not say. It
    is deliberately not defaulted to `ATTESTED`: silence must not read as the
    stronger claim.
    """

    ATTESTED = "attested"
    RECONSTRUCTED = "reconstructed"
    SYNTHETIC = "synthetic"
    """Gold known by construction: a proto-lexicon somebody wrote down first.

    A third thing, not a flattering synonym for `ATTESTED`. A synthetic gold is
    exact and unmemorizable, and it is also not a language — its regularity is
    whatever the generator was told to produce. Calling it attested would claim
    evidence about a real speech community that does not exist.
    """


class HistoricalLineageRelation(WorkbenchModel):
    branch_id: NonEmptyStr
    descendant_variety_id: NonEmptyStr
    evidence: NonEmptyStr | None = None
    source_reference: NonEmptyStr | None = None
    source_row: int | None = Field(default=None, ge=1)


class HistoricalFormBinding(WorkbenchModel):
    """Historical forms bound explicitly to one runtime internal tree node."""

    node_id: NonEmptyStr
    role: HistoricalFormRole
    source_variety_id: NonEmptyStr
    source_declared_historical: bool = False
    forms: tuple[LexicalForm, ...] = Field(min_length=1)
    lineage_relations: tuple[HistoricalLineageRelation, ...] = ()
    source_reference: NonEmptyStr | None = None
    gold_evidence_kind: GoldEvidenceKind | None = None
    """Whether these forms are attested or are a published reconstruction.

    Defaulted `None` so payloads written before the field existed still load.
    See `GoldEvidenceKind`; it is carried through to every evaluation so a
    reported accuracy always says what it is an accuracy against.
    """

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
    gold_evidence_kind: GoldEvidenceKind | None = None


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
    """One concept's reconstruction against the gold form withheld from the model.

    Everything below `beam_exact_match` was added later and is defaulted, so a
    `result.json` written before graded metrics existed still loads and reads as
    "not measured" rather than as a perfect or a failed reconstruction.
    """

    concept_id: NonEmptyStr
    target_form_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)
    target_segment_alternatives: tuple[tuple[NonEmptyStr, ...], ...] = Field(
        min_length=1
    )
    top_candidate_id: NonEmptyStr | None = None
    top_candidate_segments: tuple[NonEmptyStr, ...] | None = None
    top_exact_match: bool
    beam_exact_match: bool
    nearest_target_segments: tuple[NonEmptyStr, ...] | None = None
    """The gold alternative the top candidate was actually graded against.

    A concept may list several gold proto-forms; exact matching accepts any of
    them, so the graded scores are computed against the nearest one and it is
    named here rather than left to be guessed.
    """
    top_edit_distance: int | None = Field(default=None, ge=0)
    top_normalized_edit_distance: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    top_bcubed_precision: float | None = Field(default=None, ge=0.0, le=1.0)
    top_bcubed_recall: float | None = Field(default=None, ge=0.0, le=1.0)
    top_bcubed_f1: float | None = Field(default=None, ge=0.0, le=1.0)
    beam_best_candidate_id: NonEmptyStr | None = None
    beam_best_candidate_segments: tuple[NonEmptyStr, ...] | None = None
    beam_best_edit_distance: int | None = Field(default=None, ge=0)
    beam_best_normalized_edit_distance: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    """The lowest normalized edit distance any retained candidate reached.

    Its distance from `top_normalized_edit_distance` is the graded form of the
    selection gap: how much better the node could have done by choosing
    differently among the candidates it already computed.
    """


class GradedTargetMetrics(WorkbenchModel):
    """Distributions of the graded scores over one node's evaluated concepts.

    Distributions rather than means alone: a node that is nearly right
    everywhere and a node that is exact on half its concepts and unrelated on
    the other half can share a mean, and they are not the same reconstruction.

    Polarity is not uniform here and cannot be made so. Edit distances are
    better when *lower*; B-Cubed F1 is better when higher. Every printed line
    that carries one of these says which.
    """

    top_edit_distance: MetricDistribution | None = None
    top_normalized_edit_distance: MetricDistribution | None = None
    beam_best_normalized_edit_distance: MetricDistribution | None = None
    top_bcubed_f1: MetricDistribution | None = None
    normalized_edit_distance_selection_gap: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    """Mean top NED minus mean beam-best NED: distance recoverable by selection.

    The graded counterpart of the exact-match selection gap. It is never
    negative — the top candidate is in the beam — and it separates a generation
    problem from a selection problem: a large gap means the node computed better
    reconstructions than it reported.
    """


class HistoricalTargetEvaluation(WorkbenchModel):
    """Mechanical comparison against forms withheld from the model prompt.

    A report and never a gate. Nothing here filters a trajectory, weights a
    candidate, or decides whether a run was valid; see
    `docs/report_reject_or_score.md` for why that boundary is where it is.

    Note what "held out" means in this class and what it does not. These are
    gold proto-forms — the answer key, removed from the lexicons before the run
    and compared against afterwards. They are unrelated to
    `AgentNodeMetrics.held_out_convergence_rate`, which measures agreement among
    a node's children on concepts the *session* did not select and never leaves
    the node.
    """

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
    gold_evidence_kind: GoldEvidenceKind | None = None
    """Carried from the binding: is the answer key attested or reconstructed?"""
    failure_fallback: bool = False
    """This node's session failed and its beam is the harness's identity fallback.

    Defaulted false so evaluations written before node-failure fallback existed
    read as what they were. A score computed over a fallback node measures the
    fallback, not a reconstruction, and must be excluded from any aggregate or
    reported separately — a run that scores seven nodes when two of them are
    fallbacks is exactly the false number this harness exists to avoid.
    """
    graded: GradedTargetMetrics | None = None
    """Distributions of the graded scores; `None` on records that predate them."""

