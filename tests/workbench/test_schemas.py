from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from cognate_reconstruction.agent.schemas import GetAlignmentsArgs
from cognate_reconstruction.schemas.beam import (
    CandidateDerivation,
    ConceptCandidateDistribution,
    ReconstructionCandidate,
)
from cognate_reconstruction.schemas.lexicon import LexicalForm
from cognate_reconstruction.schemas.rules import AnomalyReport, AnomalyType


def test_morphological_boundaries_are_structural() -> None:
    form = LexicalForm(
        form_id="f1",
        variety_id="lang-a",
        concept_id="water",
        segments=("k", "-", "a"),
    )
    assert form.phonetic_segments == ("k", "a")


def test_anomaly_requires_form_or_concept() -> None:
    with pytest.raises(ValidationError):
        AnomalyReport(
            anomaly_type=AnomalyType.LOANWORD,
            explanation="external etymology",
        )


def test_alignment_request_requires_a_bounded_evidence_selection() -> None:
    with pytest.raises(ValidationError, match="explicit bounded"):
        GetAlignmentsArgs(node_ids=("A", "B"))
    with pytest.raises(ValidationError, match="at most 24"):
        GetAlignmentsArgs(
            node_ids=("A", "B"),
            concept_ids=tuple(f"concept-{index}" for index in range(25)),
        )


def test_candidate_distribution_must_be_normalized_and_sorted() -> None:
    derivation = CandidateDerivation(derivation_id="d", child_candidate_ids=())
    candidates = (
        ReconstructionCandidate(
            candidate_id="a", segments=("p",), probability=0.8, log_score=math.log(0.8), derivations=(derivation,)
        ),
        ReconstructionCandidate(
            candidate_id="b", segments=("b",), probability=0.2, log_score=math.log(0.2), derivations=(derivation,)
        ),
    )
    distribution = ConceptCandidateDistribution(concept_id="water", candidates=candidates)
    assert distribution.candidates[0].candidate_id == "a"
