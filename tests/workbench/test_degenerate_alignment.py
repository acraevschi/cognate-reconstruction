"""A degenerate beam candidate must not end the run.

Found live on 2026-08-29. A sweep seed had committed five of seven nodes when
LingPy raised `ZeroDivisionError` from `_calign.py:1879`, inside the identity
fallback the harness was building for a node that had already failed. The
exception left a C module, crossed the fallback, and ended the process. The
trajectories survived on disk; `result.json` was never written.

The arithmetic is LingPy's:

    dist = 1 - ( 2 * sim / ( simA + simB ) )

`simA` and `simB` are the self-similarity of the two rows, and the sum is zero
on material that carries no phonological content. In the crashed seed one
node's output beam held 16 candidates whose only segment was the morphological
boundary `+`.
"""

from __future__ import annotations

import pytest

from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.alignment.protocol import AlignmentFailure
from cognate_reconstruction.schemas.alignment import CorrespondenceDetail
from cognate_reconstruction.schemas.beam import NodeBeamState
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm
from cognate_reconstruction.schemas.traversal import (
    EvidenceKind,
    EvidenceRelation,
    NodeEvidence,
    NodeReconstructionContext,
)
from cognate_reconstruction.traversal.beam import make_leaf_beam
from cognate_reconstruction.traversal.reconstructor import RuleBasedReconstructor

BOUNDARY_ONLY: dict[str, tuple[str, ...]] = {
    "A": ("+",),
    "B": ("+", "+"),
}
"""The measured trigger: two boundary-only rows of unequal length.

Equal-length boundary-only rows align without complaint, and an empty sequence
raises `ValueError` rather than `ZeroDivisionError`, so neither is the case
this guards. The exact input of the live crash was never reproduced; this is a
reproduction of the same arithmetic, which is what the guard is written
against.
"""


def _lexicon(variety_id: str) -> LanguageLexicon:
    return LanguageLexicon(
        variety_id=variety_id,
        name=variety_id,
        forms=(
            LexicalForm(
                form_id=f"{variety_id}:water",
                variety_id=variety_id,
                concept_id="water",
                segments=BOUNDARY_ONLY[variety_id],
                cognate_set_id="cog-water",
            ),
        ),
    )


def _beam(variety_id: str) -> NodeBeamState:
    return make_leaf_beam(_lexicon(variety_id), beam_width=3)


def _context() -> NodeReconstructionContext:
    return NodeReconstructionContext(
        parent_node_id="PROTO",
        active_child_ids=("A", "B"),
        available_nodes=tuple(
            NodeEvidence(
                node_id=variety_id,
                kind=EvidenceKind.OBSERVED,
                relation=EvidenceRelation.ACTIVE_CHILD,
                lexicon=_lexicon(variety_id),
            )
            for variety_id in ("A", "B")
        ),
    )


def test_the_aligner_reports_a_refused_group_instead_of_dividing_by_zero() -> None:
    with pytest.raises(AlignmentFailure) as caught:
        LingPyAligner().align_multiple(
            (_lexicon("A"), _lexicon("B")),
            correspondence_detail=CorrespondenceDetail.SUMMARY,
        )
    message = str(caught.value)
    assert "water" in message
    assert "cog-water" in message
    assert "ZeroDivisionError" in message


def test_a_refused_alignment_is_a_value_error_for_every_tool_boundary() -> None:
    """`registry.execute` and `polarize` catch `ValueError` and nothing wider.

    A bare `ZeroDivisionError` is neither `ValidationError` nor `ValueError`, so
    it escaped the tool boundary as well as the traversal one.
    """
    assert issubclass(AlignmentFailure, ValueError)


def test_a_refused_alignment_leaves_the_step_without_its_report() -> None:
    step = RuleBasedReconstructor().reconstruct(
        "PROTO",
        (_beam("A"), _beam("B")),
        evidence_context=_context(),
    )
    assert step.correspondence_maps == ()
    assert step.diagnostics.correspondence_map_failure is not None
    assert "water" in step.diagnostics.correspondence_map_failure
    assert step.output_beam.distributions, "the node still produced a beam"


def test_a_clean_step_says_nothing_about_a_refusal() -> None:
    """An empty report is not evidence of degradation on its own."""
    step = RuleBasedReconstructor().reconstruct(
        "PROTO",
        (_beam("A"), _beam("B")),
    )
    assert step.correspondence_maps == ()
    assert step.diagnostics.correspondence_map_failure is None
