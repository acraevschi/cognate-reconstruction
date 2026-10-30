"""Probability distributions retained by the deterministic beam search."""

from __future__ import annotations

import math

from pydantic import Field, model_validator

from cognate_reconstruction.schemas.common import NonEmptyStr, WorkbenchModel
from cognate_reconstruction.schemas.evidence import FormAnalysis


class BranchCandidateAnalysis(WorkbenchModel):
    child_id: NonEmptyStr
    candidate_id: NonEmptyStr
    segments: tuple[NonEmptyStr, ...]
    analysis: FormAnalysis | None = None


class CandidateDerivation(WorkbenchModel):
    branch_analyses: tuple[BranchCandidateAnalysis, ...] = ()
    analysis: FormAnalysis | None = None
    derivation_id: NonEmptyStr
    child_candidate_ids: tuple[NonEmptyStr, ...]
    rule_ids: tuple[NonEmptyStr, ...] = ()
    alignment_ids: tuple[NonEmptyStr, ...] = ()
    # Defaulted for append-only readability: derivations written before branch
    # support was retained name no supporters, which reads as "not recorded".
    supporting_child_ids: tuple[NonEmptyStr, ...] = ()
    """Active children whose scoped cascade produced this exact parent form.

    Branch agreement is evidence in the comparative method, so the count behind
    a candidate is part of its derivation, not a summary statistic derived from
    it. `traversal/reconstructor.py` scores a candidate by how many of these
    there are; naming them lets a reader check the claim against the input
    beams.
    """
    note: NonEmptyStr | None = None


class ReconstructionCandidate(WorkbenchModel):
    analysis: FormAnalysis | None = None
    candidate_id: NonEmptyStr
    segments: tuple[NonEmptyStr, ...] = Field(min_length=1)
    probability: float = Field(ge=0.0, le=1.0)
    log_score: float
    derivations: tuple[CandidateDerivation, ...]

    @model_validator(mode="after")
    def validate_finite_scores(self) -> ReconstructionCandidate:
        if self.analysis is not None:
            self.analysis.validate_segments(len(self.segments))
        if not math.isfinite(self.probability) or not math.isfinite(self.log_score):
            raise ValueError("candidate probability and log_score must be finite")
        return self


class ConceptCandidateDistribution(WorkbenchModel):
    pre_prune_candidate_count: int | None = Field(default=None, ge=0)
    pruned_candidate_count: int | None = Field(default=None, ge=0)
    concept_id: NonEmptyStr
    candidates: tuple[ReconstructionCandidate, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_distribution(self) -> ConceptCandidateDistribution:
        candidate_ids = [c.candidate_id for c in self.candidates]
        segment_sequences = [(c.segments, c.analysis.compatibility_key() if c.analysis else None)
                             for c in self.candidates]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("candidate IDs must be unique within a distribution")
        if len(set(segment_sequences)) != len(segment_sequences):
            raise ValueError("candidate segment sequences must be unique within a distribution")
        if abs(sum(c.probability for c in self.candidates) - 1.0) > 1e-8:
            raise ValueError("candidate probabilities must sum to one")
        if any(
            left.probability < right.probability
            for left, right in zip(self.candidates, self.candidates[1:])
        ):
            raise ValueError("candidates must be sorted by descending probability")
        return self


class NodeBeamState(WorkbenchModel):
    node_id: NonEmptyStr
    distributions: tuple[ConceptCandidateDistribution, ...]
    beam_width: int = Field(ge=1)
    source_child_ids: tuple[NonEmptyStr, ...] | None = None

    @model_validator(mode="after")
    def validate_beam(self) -> NodeBeamState:
        concepts = [distribution.concept_id for distribution in self.distributions]
        if len(concepts) != len(set(concepts)):
            raise ValueError("a node beam may contain each concept only once")
        if any(len(d.candidates) > self.beam_width for d in self.distributions):
            raise ValueError("distribution exceeds beam_width")
        if self.source_child_ids is not None and len(self.source_child_ids) < 2:
            raise ValueError("a reconstructed node must identify at least two children")
        return self
