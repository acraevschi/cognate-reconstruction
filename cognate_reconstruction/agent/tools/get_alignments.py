"""Adapter exposing pairwise LingPy alignments to the agent."""

from __future__ import annotations
from itertools import combinations

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.schemas import GetAlignmentsArgs, GetAlignmentsResult
from cognate_reconstruction.agent.tools.errors import ToolInputError
from cognate_reconstruction.schemas.common import WorkbenchModel
from cognate_reconstruction.alignment.units import evidence_map
from cognate_reconstruction.alignment.lingpy_adapter import _pairwise_map
from cognate_reconstruction.schemas.alignment import CorrespondenceDetail


def get_alignments(
    raw_arguments: WorkbenchModel,
    context: AgentContext,
    call_id: str,  # noqa: ARG001 - uniform tool signature
) -> GetAlignmentsResult:
    arguments = GetAlignmentsArgs.model_validate(raw_arguments)
    selected = set(arguments.concept_ids)
    selected_forms = set(arguments.form_ids)
    lexicons = []
    for node_id in arguments.node_ids:
        lexicon = context.evidence_lexicon(
            node_id, arguments.segmentation_overlay_id
        )
        if selected or selected_forms:
            lexicon = lexicon.model_copy(
                update={
                    "forms": tuple(
                        form
                        for form in lexicon.forms
                        if (not selected or form.concept_id in selected)
                        and (not selected_forms or form.form_id in selected_forms)
                    )
                }
            )
        lexicons.append(lexicon)
    anchors = (
        tuple(
            anchor
            for anchor in context.active_anchors
            if (not selected or anchor.concept_id in selected)
            and (not selected_forms or anchor.form_id in selected_forms)
        )
        if arguments.include_anchors
        else ()
    )
    # The aligner is deterministic core and knows nothing about tool codes, so
    # the code is attached here at the boundary, as with rule parsing. Without
    # it a refused selection would be the one remaining `unclassified` path a
    # model can reach.
    try:
        if arguments.respect_cognate_sets and not anchors:
            alignment_map, _ = evidence_map(lexicons, context.aligner,
                unit_orders=arguments.unit_orders,
                overlay_ids=(arguments.segmentation_overlay_id, None),
                cache=context.unit_alignment_cache)
            alignment_map = alignment_map.model_copy(update={"detail": arguments.detail,
                "pairwise_correspondences": tuple(_pairwise_map(left, right, alignment_map.alignments, arguments.detail)
                                                 for left, right in combinations(alignment_map.variety_ids, 2))
                if arguments.detail is CorrespondenceDetail.FULL else ()})
        else:
            alignment_map = context.aligner.align_multiple(
                lexicons, anchors, respect_cognate_sets=arguments.respect_cognate_sets,
                correspondence_detail=arguments.detail)
    except ToolInputError:
        raise
    except ValueError as error:
        raise ToolInputError(str(error), code="alignment-failed") from error
    # Under `summary` the pairwise views are dropped and the n-way alignments
    # kept. One view per node pair grows quadratically with the nodes compared,
    # and across 844 recorded calls they were 62% of this tool's characters;
    # the counts they carry are what `summarize_correspondences` reports over
    # the whole evidence set. `full` still returns them.
    if arguments.detail is CorrespondenceDetail.SUMMARY:
        alignment_map = alignment_map.model_copy(
            update={"pairwise_correspondences": ()}
        )
    return GetAlignmentsResult(
        alignment_map=alignment_map,
        segmentation_overlay_id=arguments.segmentation_overlay_id,
    )
