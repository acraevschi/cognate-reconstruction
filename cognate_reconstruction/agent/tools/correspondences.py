"""Adapter exposing the correspondence-set inventory to the agent.

`get_alignments` answers "how do these few words line up?". This answers "which
segment correspondences recur across the whole evidence set, and how often?",
which is the question the comparative method actually starts from and the one no
batch of alignments can answer.
"""

from __future__ import annotations

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.schemas import (
    SummarizeCorrespondencesArgs,
    SummarizeCorrespondencesResult,
)
from cognate_reconstruction.agent.tools.errors import ToolInputError
from cognate_reconstruction.agent.tools.evidence import selected_evidence
from cognate_reconstruction.agent.tools.inventory_evidence import (
    apply_alignment_overrides,
)
from cognate_reconstruction.alignment.correspondence_sets import (
    build_correspondence_sets,
    complementary_candidates,
    one_reading_per_node,
)
from cognate_reconstruction.schemas.alignment import (
    GAP_SEGMENT_TOKENS,
    CorrespondenceDetail,
    CorrespondenceSet,
)
from cognate_reconstruction.schemas.common import WorkbenchModel


def _matches_segment(
    item: CorrespondenceSet,
    node_ids: tuple[str, ...],
    segment: str | None,
    segment_node_id: str | None,
) -> bool:
    if segment is None:
        return True
    wanted = None if segment in GAP_SEGMENT_TOKENS else segment
    if segment_node_id is not None:
        return item.segments[node_ids.index(segment_node_id)] == wanted
    return any(candidate == wanted for candidate in item.segments)


def summarize_correspondences(
    raw_arguments: WorkbenchModel,
    context: AgentContext,
    call_id: str,  # noqa: ARG001 - uniform tool signature
) -> SummarizeCorrespondencesResult:
    arguments = SummarizeCorrespondencesArgs.model_validate(raw_arguments)
    evidence = selected_evidence(context, arguments.scope, arguments.node_ids)
    # The requested order is the column order of every returned set, so an
    # explicit selection keeps its own order rather than the tree's.
    node_ids = arguments.node_ids or tuple(item.node_id for item in evidence)
    if arguments.segment_node_id is not None and (
        arguments.segment_node_id not in node_ids
    ):
        raise ToolInputError(
            f"segment_node_id {arguments.segment_node_id!r} is not one of the "
            f"compared nodes: {sorted(node_ids)}",
            code="unknown-node",
        )

    selected_concepts = set(arguments.concept_ids)
    lexicons = []
    for node_id in node_ids:
        lexicon = context.evidence_lexicon(node_id, arguments.segmentation_overlay_id)
        if selected_concepts:
            lexicon = lexicon.model_copy(
                update={
                    "forms": tuple(
                        form
                        for form in lexicon.forms
                        if form.concept_id in selected_concepts
                    )
                }
            )
        lexicons.append(lexicon)
    # As in get_alignments, the aligner is deterministic core and knows nothing
    # about tool codes, so a refused selection is coded at this boundary. No
    # anchors are passed: they are not columns of a correspondence set, and an
    # anchor that changed the support counts would make recurrence depend on
    # whether one happened to be supplied.
    try:
        alignment_map = context.aligner.align_multiple(
            # One reading per node, so a correspondence is between the nodes'
            # reported forms and so the set IDs below are ones the assembler can
            # reproduce from a candidate tuple. See `one_reading_per_node`.
            one_reading_per_node(lexicons),
            respect_cognate_sets=arguments.respect_cognate_sets,
            correspondence_detail=CorrespondenceDetail.SUMMARY,
        )
        alignment_map = apply_alignment_overrides(
            alignment_map,
            context.alignment_overrides(arguments.alignment_overlay_id),
            node_ids,
        )
        inventory = build_correspondence_sets(
            alignment_map,
            node_ids=node_ids,
            segmentation_overlay_id=arguments.segmentation_overlay_id,
            alignment_overlay_id=arguments.alignment_overlay_id,
        )
    except ToolInputError:
        raise
    except ValueError as error:
        raise ToolInputError(str(error), code="alignment-failed") from error

    filtered = tuple(
        item
        for item in inventory.sets
        if _matches_segment(
            item, node_ids, arguments.segment, arguments.segment_node_id
        )
    )
    matched = tuple(item for item in filtered if item.support >= arguments.min_support)
    page = matched[arguments.offset : arguments.offset + arguments.limit]
    next_offset = arguments.offset + len(page)
    # Computed over the page, not over the whole inventory: the pairs a reader
    # can act on are the ones whose set IDs are in front of them.
    candidates, candidate_count = complementary_candidates(
        alignment_map, page, node_ids=node_ids
    )
    return SummarizeCorrespondencesResult(
        node_ids=node_ids,
        alignment_count=inventory.alignment_count,
        total_set_count=len(inventory.sets),
        suppressed_below_min_support=len(filtered) - len(matched),
        matched_set_count=len(matched),
        min_support=arguments.min_support,
        sets=page,
        next_offset=next_offset if next_offset < len(matched) else None,
        segmentation_overlay_id=arguments.segmentation_overlay_id,
        alignment_overlay_id=arguments.alignment_overlay_id,
        complementary_candidates=candidates,
        complementary_candidate_count=candidate_count,
    )
