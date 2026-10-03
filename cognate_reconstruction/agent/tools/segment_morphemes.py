"""Create immutable, session-local morphological segmentation overlays."""

from __future__ import annotations

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.schemas import (
    SegmentMorphemesArgs,
    SegmentMorphemesResult,
)
from cognate_reconstruction.agent.tools.errors import ToolInputError
from cognate_reconstruction.schemas.common import MORPHOLOGICAL_BOUNDARY_TOKENS, WorkbenchModel
from cognate_reconstruction.schemas.lexicon import LexicalForm
from cognate_reconstruction.schemas.evidence import EvidencePiece, FormAnalysis, PieceSource
from cognate_reconstruction.alignment.units import source_analyses


def remap_analysis(original, segments):
    if original.analysis is None:
        return None
    old_phonetic = [i for i, t in enumerate(original.segments) if t not in MORPHOLOGICAL_BOUNDARY_TOKENS]
    new_phonetic = [i for i, t in enumerate(segments) if t not in MORPHOLOGICAL_BOUNDARY_TOKENS]
    mapping = dict(zip(old_phonetic, new_phonetic, strict=True))
    # Existing boundaries survive only at the same phonetic offset and spelling.
    for index, token in enumerate(original.segments):
        if token not in MORPHOLOGICAL_BOUNDARY_TOKENS:
            continue
        offset = sum(i < index for i in old_phonetic)
        match = next((i for i, t in enumerate(segments) if t == token
                      and sum(j < i for j in new_phonetic) == offset), None)
        if match is not None:
            mapping[index] = match
    labels = {mapping[index]: piece for piece in original.analysis.pieces
              for index in piece.segment_indices if index in mapping}
    for index in range(len(segments)):
        if index in labels:
            continue
        left, right = labels.get(index - 1), labels.get(index + 1)
        if left is not None and right is not None and left.unit_id == right.unit_id:
            # A boundary-only edit does not silently split one claimed unit.
            labels[index] = left
    pieces = []
    for index in range(len(segments)):
        piece = labels.get(index)
        if piece is None:
            piece = EvidencePiece(unit_id=f"boundary:{original.form_id}:{index}", kind="boundary", segment_indices=(index,))
        if pieces and pieces[-1].unit_id == piece.unit_id:
            previous = pieces.pop()
            pieces.append(previous.model_copy(update={"segment_indices": (*previous.segment_indices, index)}))
        else:
            pieces.append(piece.model_copy(update={"segment_indices": (index,)}))
    return FormAnalysis(pieces=tuple(pieces), claim=original.analysis.claim)


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
        raise ToolInputError(
            "a segmentation request may edit each form only once",
            code="overlay-invalid-edit",
        )
    base_forms = context.forms_for_overlay(arguments.base_overlay_id)
    edited = []
    for segmentation in arguments.segmentations:
        try:
            original = base_forms[segmentation.form_id]
        except KeyError as error:
            raise ToolInputError(
                f"unknown form {segmentation.form_id!r}",
                code="unknown-form",
            ) from error
        phonetic = tuple(
            segment
            for segment in segmentation.segments
            if segment not in MORPHOLOGICAL_BOUNDARY_TOKENS
        )
        if phonetic != original.phonetic_segments:
            raise ToolInputError(
                f"segmentation for {segmentation.form_id!r} changes phonetic tokens",
                code="overlay-invalid-edit",
            )
        updated = original.model_dump(mode="python")
        updated["segments"] = segmentation.segments
        updated["analysis"] = remap_analysis(original, segmentation.segments)
        if segmentation.analysis_claim is not None:
            sources = tuple(source for analysis in source_analyses(original)
                for piece in analysis.pieces for source in piece.sources)
            analysis = FormAnalysis(claim="model", pieces=tuple(EvidencePiece(
                unit_id=claim.unit_id, cognate_set_id=claim.cognate_set_id,
                kind="cognate" if claim.cognate_set_id else "unknown",
                segment_indices=claim.segment_indices, sources=sources,
            ) for claim in segmentation.analysis_claim))
            try:
                analysis.validate_segments(len(segmentation.segments))
            except ValueError as error:
                raise ToolInputError(str(error), code="overlay-invalid-edit",
                    remediation="Cover each segment once in surface order; keep unknown pieces explicit.") from error
            updated["analysis"] = analysis
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
