"""Create immutable, session-local morphological segmentation overlays."""

from __future__ import annotations

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.schemas import (
    SegmentMorphemesArgs,
    SegmentMorphemesResult,
)
from cognate_reconstruction.schemas.common import MORPHOLOGICAL_BOUNDARY_TOKENS, WorkbenchModel
from cognate_reconstruction.schemas.lexicon import LexicalForm


def _remap_memberships(
    original: LexicalForm,
    new_segments: tuple[str, ...],
) -> tuple:
    """Project source slice positions through boundary-only edits."""
    original_phonetic_ordinal = {}
    ordinal = 0
    for index, segment in enumerate(original.segments):
        if segment in MORPHOLOGICAL_BOUNDARY_TOKENS:
            continue
        original_phonetic_ordinal[index] = ordinal
        ordinal += 1
    new_index_by_ordinal = {}
    ordinal = 0
    for index, segment in enumerate(new_segments):
        if segment in MORPHOLOGICAL_BOUNDARY_TOKENS:
            continue
        new_index_by_ordinal[ordinal] = index
        ordinal += 1
    return tuple(
        membership.model_copy(
            update={
                "segment_indices": tuple(
                    new_index_by_ordinal[original_phonetic_ordinal[index]]
                    for index in membership.segment_indices
                    if index in original_phonetic_ordinal
                )
            }
        )
        for membership in original.cognate_memberships
    )


def segment_morphemes(
    raw_arguments: WorkbenchModel,
    context: AgentContext,
    call_id: str,  # noqa: ARG001 - uniform tool signature
) -> SegmentMorphemesResult:
    arguments = SegmentMorphemesArgs.model_validate(raw_arguments)
    ids = [item.form_id for item in arguments.segmentations]
    if len(ids) != len(set(ids)):
        raise ValueError("a segmentation request may edit each form only once")
    base_forms = context.forms_for_overlay(arguments.base_overlay_id)
    edited = []
    for segmentation in arguments.segmentations:
        try:
            original = base_forms[segmentation.form_id]
        except KeyError as error:
            raise ValueError(f"unknown form {segmentation.form_id!r}") from error
        phonetic = tuple(
            segment
            for segment in segmentation.segments
            if segment not in MORPHOLOGICAL_BOUNDARY_TOKENS
        )
        if phonetic != original.phonetic_segments:
            raise ValueError(
                f"segmentation for {segmentation.form_id!r} changes phonetic tokens"
            )
        updated = original.model_dump(mode="python")
        updated["segments"] = segmentation.segments
        updated["cognate_memberships"] = _remap_memberships(
            original,
            segmentation.segments,
        )
        edited.append(LexicalForm.model_validate(updated))
    forms = tuple(edited)
    overlay_id = context.store_overlay(
        forms,
        base_overlay_id=arguments.base_overlay_id,
    )
    return SegmentMorphemesResult(
        segmentation_overlay_id=overlay_id,
        forms=forms,
        rationale=arguments.rationale,
    )
