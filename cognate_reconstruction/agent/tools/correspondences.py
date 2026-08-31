"""Adapter exposing the correspondence-set inventory to the agent.

`get_alignments` answers "how do these few words line up?". This answers "which
segment correspondences recur across the whole evidence set, and how often?",
which is the question the comparative method actually starts from and the one no
batch of alignments can answer.
"""

from __future__ import annotations

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.schemas import (
    ColumnPosition,
    OutgroupReflex,
    SetOutgroupProfile,
    SummarizeCorrespondencesArgs,
    SummarizeCorrespondencesResult,
)
from cognate_reconstruction.agent.tools.errors import ToolInputError
# The same definitions polarize uses, imported rather than reimplemented: a
# survey that disagreed with polarize about which columns show a correspondence
# would put two different answers to one question in front of the model.
from cognate_reconstruction.agent.tools.polarize import (
    matching_column,
    outside_nodes,
    restrict,
)
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
from cognate_reconstruction.schemas.traversal import EvidenceRelation


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


def _outgroup_profiles(
    context,
    page,
    node_ids,
    *,
    segmentation_overlay_id,
    respect_cognate_sets,
    selected_concepts,
):
    """What every node outside the active children shows in each set's columns.

    This is `polarize`'s answer, computed once for the survey rather than once
    per call. The reason it is worth computing that way is measured:
    `tools/outgroup_coverage.py` reports that across the banked sweeps a node
    calls `polarize` and commits many times more sets than it polarizes — 11%
    coverage on Gemma's Polynesian sweep, 24.8% on Qwen's. Every node reached
    for out-group evidence; almost no committed set had any.

    One alignment over the children *and* the outside nodes, then one scan per
    returned set. Cost is bounded by the page rather than by the inventory, the
    same way `complementary_candidates` is bounded.

    Returns `(profiles, note)`. The note is not decoration: at the root nothing
    lies outside the node, so every available node is a descendant and none can
    polarize anything, and a reader who does not know that will read an empty
    profile as missing data.
    """
    outside = outside_nodes(context, ())
    if not outside:
        return (), (
            "No node outside the active children is available, so nothing here "
            "can polarize these correspondences."
        )
    lexicons = [
        restrict(
            context.evidence_lexicon(node_id, segmentation_overlay_id),
            selected_concepts,
        )
        for node_id in node_ids
    ]
    lexicons.extend(
        restrict(
            context.evidence_lexicon(item.node_id, segmentation_overlay_id),
            selected_concepts,
        )
        for item in outside
    )
    try:
        alignment_map = context.aligner.align_multiple(
            one_reading_per_node(lexicons),
            respect_cognate_sets=respect_cognate_sets,
            correspondence_detail=CorrespondenceDetail.SUMMARY,
        )
    except ValueError:
        # A survey that could align the children can still fail to align them
        # against the outside nodes. That costs the extra evidence and must not
        # cost the survey, which is the thing the caller asked for.
        return (), (
            "The nodes outside the active children could not be aligned with "
            "them, so no out-group reading is available for these sets."
        )

    outside_ids = tuple(item.node_id for item in outside)
    # Only sets whose children *disagree*. A set where every active child shows
    # the same segment has nothing to polarize: there is no competing value to
    # choose between, so an out-group reading of it is evidence about a question
    # nobody asked. This is the whole cost control — measured on Polynesian's
    # `tongic`, it takes the addition from 3.9x the result to a fraction of it —
    # and it is a property of the question rather than a truncation, so nothing
    # informative is dropped to hit a size.
    wanted = {
        item.set_id: item.segments
        for item in page
        if item.set_id and len(set(item.segments)) > 1
    }
    # {set_id: {segment: {node_id: columns}}}
    tally: dict[str, dict[str | None, dict[str, int]]] = {
        set_id: {} for set_id in wanted
    }
    if not wanted:
        return (), _outgroup_note(outside)

    for alignment in alignment_map.alignments:
        members_by_node: dict[str, tuple] = {}
        for member in alignment.members:
            members_by_node[member.variety_id] = (
                *members_by_node.get(member.variety_id, ()),
                member,
            )
        width = len(alignment.members[0].aligned_segments)
        for column in range(width):
            for set_id, segments in wanted.items():
                if not matching_column(
                    members_by_node,
                    column,
                    tuple(node_ids),
                    segments,
                    ColumnPosition.ANY,
                ):
                    continue
                for node_id in outside_ids:
                    for member in members_by_node.get(node_id, ()):
                        segment = member.aligned_segments[column]
                        if segment is None:
                            # A gap outside the group is the node showing
                            # nothing, and absence is not evidence: it is
                            # equally consistent with independent loss. Only
                            # presence is reported, exactly as `polarize`
                            # summarises only presence in its candidates, and
                            # `tools/outgroup_probe.py` measured that scoring
                            # absence lands *below* alphabetical tie-breaking.
                            # It is also the single widest row when it is kept,
                            # since a gap is usually shown by every node at once.
                            continue
                        by_node = tally[set_id].setdefault(segment, {})
                        by_node[node_id] = by_node.get(node_id, 0) + 1

    # Grouped by segment rather than by node. The question is "which values
    # exist outside this group, and who attests each", and a row per (node,
    # segment) pair repeats the node IDs — the widest single cost here, since a
    # Polynesian variety ID is over thirty characters.
    profiles = tuple(
        SetOutgroupProfile(
            set_id=set_id,
            reflexes=tuple(
                OutgroupReflex(
                    segment=segment,
                    node_ids=tuple(
                        node_id
                        for node_id, _ in sorted(
                            by_node.items(), key=lambda item: (-item[1], item[0])
                        )
                    ),
                    columns=sum(by_node.values()),
                )
                for segment, by_node in sorted(
                    tally[set_id].items(),
                    # A gap sorts as "" rather than None: None is not orderable
                    # against a string.
                    key=lambda item: (-sum(item[1].values()), item[0] or ""),
                )
            ),
        )
        for set_id in tally
        if tally[set_id]
    )
    return profiles, _outgroup_note(outside)


def _outgroup_note(outside) -> str:
    """Say how many of the inspected nodes can actually polarize anything.

    Deliberately the same distinction `polarize._witnesses` draws, in the same
    words, because it is the one a reader gets wrong: only an out-group lies
    outside this node's subtree, so only an out-group can show that a segment
    predates the split. A descendant shows what these children became.
    """
    outgroups = sum(
        item.relation is EvidenceRelation.OUTGROUP for item in outside
    )
    descendants = len(outside) - outgroups
    if not outgroups:
        return (
            f"{descendants} node(s) outside the active children were read and "
            "every one is a descendant of this node, so none can polarize "
            "these correspondences: a descendant lies inside the subtree and "
            "shows what these children became. This node has no out-group, "
            "which at the root is not a gap in the data - nothing lies outside "
            "it."
        )
    if not descendants:
        return (
            f"{outgroups} out-group node(s) were read. A segment one of them "
            "shows was present before this node split; a node showing nothing "
            "is absent above, because absence is not evidence."
        )
    return (
        f"{outgroups} out-group node(s) were read, plus {descendants} "
        "descendant(s), which lie inside this node's subtree and polarize "
        "nothing."
    )


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
    profiles: tuple = ()
    note = ""
    if arguments.include_outgroup:
        profiles, note = _outgroup_profiles(
            context,
            page,
            node_ids,
            segmentation_overlay_id=arguments.segmentation_overlay_id,
            respect_cognate_sets=arguments.respect_cognate_sets,
            selected_concepts=selected_concepts,
        )
    return SummarizeCorrespondencesResult(
        node_ids=node_ids,
        outgroup_reflexes=profiles,
        outgroup_note=note,
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
