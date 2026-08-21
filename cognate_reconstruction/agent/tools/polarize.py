"""Retrieve the evidence that settles which branch innovated.

Rules in this interface are child-to-parent, so "make the children agree" is
satisfiable by rewriting either child toward the other. Nothing in the tool
surface ever asked which one changed, and live runs answered it backwards:
`ʔ > Ø / #_` scoped to the one Tongic branch that *keeps* the glottal stop,
`f > h` and `t > k` scoped to North Marquesan when Hawaiian is the innovator.

The evidence that decides it was already in the harness. `list_available_nodes`
and `search_forms(scope="available_tree")` expose every observed node outside
the active children and every node already reconstructed in this run, tagged
`OUTGROUP` or `DESCENDANT`, and across a whole ten-language benchmark run the
model reached for that scope once. Advice in a document is not a mechanism.

This is data retrieval, not a prior. Given one correspondence over the active
children, it aligns those children with each node outside them and reports what
each of those nodes shows in the same columns. It deliberately does not say
which value is original — see `PolarizeResult` — because that judgement is the
model's and its record is the committed rule's `directionality_rationale`.

Three properties of the technique, each measured by `tools/outgroup_probe.py`
against the withheld gold on the Polynesian benchmark:

- **Support is a property of clades, not of daughters.** Averaging over
  daughters scores exactly what alphabetical tie-breaking scores, because most
  Polynesian daughters lost `*ʔ` and similarity to the out-group degenerates
  into a majority vote over shared innovations. Every node report carries its
  `descendant_leaf_ids` so nodes belonging to one clade can be read as one
  witness.
- **Presence is evidence; absence is not.** A node showing a segment puts that
  segment outside the group under study. A node lacking it has no distinctive
  segment to attest, and scoring the empty set as trivially supported drops the
  measured result *below* alphabetical order. Only presence is summarised in
  `candidates`.
- **Morphology comes first.** Material added at a morph boundary is innovation
  however well its segments are attested elsewhere — `m a n u` against
  `m a n u + l e l e` — so a boundary in a form outranks any count here.
"""

from __future__ import annotations

from collections import defaultdict

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.schemas import (
    MAX_POLARIZE_EXAMPLE_CONCEPTS,
    ColumnPosition,
    PolarizeArgs,
    PolarizeCandidateSummary,
    PolarizeNodeReport,
    PolarizeResult,
    PolarizeSegmentObservation,
)
from cognate_reconstruction.agent.tools.errors import ToolInputError
from cognate_reconstruction.schemas.alignment import (
    GAP_SEGMENT_TOKENS,
    MAX_CORRESPONDENCE_EXAMPLES,
    AlignmentMember,
    CorrespondenceDetail,
)
from cognate_reconstruction.schemas.common import WorkbenchModel
from cognate_reconstruction.schemas.lexicon import LanguageLexicon
from cognate_reconstruction.schemas.traversal import (
    EvidenceKind,
    EvidenceRelation,
    NodeEvidence,
)


def _wanted(segment: str) -> str | None:
    return None if segment in GAP_SEGMENT_TOKENS else segment


def _edge_ok(
    member: AlignmentMember,
    column: int,
    position: ColumnPosition,
) -> bool:
    """Is this column at the word edge the caller asked for, for this member?

    An alignment pads with gaps, so "word-initial" is "no non-gap segment in an
    earlier column of this member" rather than "column zero".
    """
    if position is ColumnPosition.ANY:
        return True
    segments = member.aligned_segments
    if position is ColumnPosition.INITIAL:
        return all(segment is None for segment in segments[:column])
    return all(segment is None for segment in segments[column + 1 :])


def _matching_column(
    members_by_node: dict[str, tuple[AlignmentMember, ...]],
    column: int,
    child_ids: tuple[str, ...],
    wanted: tuple[str | None, ...],
    position: ColumnPosition,
) -> bool:
    for child_id, value in zip(child_ids, wanted, strict=True):
        members = members_by_node.get(child_id, ())
        if not any(
            member.aligned_segments[column] == value
            and _edge_ok(member, column, position)
            for member in members
        ):
            return False
    return True


def _outside_nodes(
    context: AgentContext,
    selected: tuple[str, ...],
) -> tuple[NodeEvidence, ...]:
    active = set(context.child_ids)
    available = tuple(
        item for item in context.evidence if item.node_id not in active
    )
    if not selected:
        return available
    known = {item.node_id for item in available}
    unknown = sorted(set(selected) - known)
    if unknown:
        raise ToolInputError(
            "polarize compares nodes outside the active children; these are "
            f"not available for that: {unknown}",
            code="unknown-node",
        )
    return tuple(item for item in available if item.node_id in selected)


def _restrict(
    lexicon: LanguageLexicon,
    concept_ids: set[str],
) -> LanguageLexicon:
    if not concept_ids:
        return lexicon
    return lexicon.model_copy(
        update={
            "forms": tuple(
                form for form in lexicon.forms if form.concept_id in concept_ids
            )
        }
    )


def _witnesses(outside: tuple[NodeEvidence, ...]) -> str:
    """Say how many of the inspected nodes can actually polarize anything.

    Only an out-group can: it lies outside this node's subtree, so a segment it
    shows was present before the node split. A descendant lies *inside* the
    subtree and shows what this node's own children became, which is the
    proposition under test rather than evidence about it.

    Counting them together would be the cladistic error the tool exists to
    prevent, and it is not hypothetical: at the root every available node is a
    descendant, so a note reading "14 nodes outside the active children were
    inspected" is true and reads exactly like out-group support.
    """
    outgroups = sum(
        item.relation is EvidenceRelation.OUTGROUP for item in outside
    )
    descendants = len(outside) - outgroups
    if not outgroups:
        return (
            f"{descendants} node(s) were inspected and every one of them is a "
            "descendant of this node, so none can polarize this correspondence: "
            "a descendant lies inside the subtree and shows what these children "
            "became. This node has no out-group, which at the root is not a gap "
            "in the data — nothing lies outside it"
        )
    if not descendants:
        return f"{outgroups} out-group node(s) were inspected"
    return (
        f"{outgroups} out-group node(s) were inspected, plus {descendants} "
        "descendant(s), which lie inside this node's subtree and polarize nothing"
    )


def _note(
    columns: int,
    child_ids: tuple[str, ...],
    outside: tuple[NodeEvidence, ...],
) -> str:
    scope = ", ".join(child_ids)
    if not outside:
        return (
            "No node outside the active children is available at all, so "
            "nothing here can polarize this correspondence."
        )
    if not columns:
        return (
            f"No aligned column shows this correspondence across [{scope}]; "
            f"{_witnesses(outside)}."
        )
    return (
        f"{columns} aligned column(s) show this correspondence across [{scope}]; "
        f"{_witnesses(outside)}. Counts only — which value is original is your "
        "judgement."
    )


def polarize(
    raw_arguments: WorkbenchModel,
    context: AgentContext,
    call_id: str,  # noqa: ARG001 - uniform tool signature
) -> PolarizeResult:
    arguments = PolarizeArgs.model_validate(raw_arguments)
    # Raises unknown-node for anything that is not an active child.
    child_lexicons = tuple(
        context.lexicon(child_id, arguments.segmentation_overlay_id)
        for child_id in arguments.child_ids
    )
    outside = _outside_nodes(context, arguments.node_ids)
    wanted = tuple(_wanted(segment) for segment in arguments.correspondence)
    if not outside:
        return PolarizeResult(
            child_ids=arguments.child_ids,
            correspondence=arguments.correspondence,
            columns_matched=0,
            matched_concept_count=0,
            segmentation_overlay_id=arguments.segmentation_overlay_id,
            note=_note(0, arguments.child_ids, outside),
        )

    selected_concepts = set(arguments.concept_ids)
    lexicons = [
        _restrict(lexicon, selected_concepts) for lexicon in child_lexicons
    ]
    lexicons.extend(
        _restrict(
            context.evidence_lexicon(
                item.node_id, arguments.segmentation_overlay_id
            ),
            selected_concepts,
        )
        for item in outside
    )
    if not any(lexicon.forms for lexicon in lexicons):
        raise ToolInputError(
            "no forms matched the requested node and concept scope",
            code="empty-scope",
        )
    # As in the other alignment adapters, the aligner is deterministic core and
    # knows nothing about tool codes, so a refused selection is coded here.
    try:
        alignment_map = context.aligner.align_multiple(
            lexicons,
            respect_cognate_sets=arguments.respect_cognate_sets,
            correspondence_detail=CorrespondenceDetail.SUMMARY,
        )
    except ToolInputError:
        raise
    except ValueError as error:
        raise ToolInputError(str(error), code="alignment-failed") from error

    columns_matched = 0
    matched_concepts: list[str] = []
    counts: dict[str, dict[str | None, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    examples: dict[tuple[str, str | None], list[str]] = defaultdict(list)
    covered: dict[str, int] = defaultdict(int)
    outside_ids = tuple(item.node_id for item in outside)
    for alignment in alignment_map.alignments:
        members_by_node: dict[str, tuple[AlignmentMember, ...]] = {}
        for member in alignment.members:
            members_by_node[member.variety_id] = (
                *members_by_node.get(member.variety_id, ()),
                member,
            )
        width = len(alignment.members[0].aligned_segments)
        for column in range(width):
            if not _matching_column(
                members_by_node,
                column,
                arguments.child_ids,
                wanted,
                arguments.position,
            ):
                continue
            columns_matched += 1
            if alignment.concept_id not in matched_concepts:
                matched_concepts.append(alignment.concept_id)
            for node_id in outside_ids:
                members = members_by_node.get(node_id, ())
                if not members:
                    continue
                covered[node_id] += 1
                for segment in dict.fromkeys(
                    member.aligned_segments[column] for member in members
                ):
                    counts[node_id][segment] += 1
                    seen = examples[(node_id, segment)]
                    if (
                        alignment.concept_id not in seen
                        and len(seen) < MAX_CORRESPONDENCE_EXAMPLES
                    ):
                        seen.append(alignment.concept_id)

    nodes = tuple(
        PolarizeNodeReport(
            node_id=item.node_id,
            relation=item.relation,
            kind=item.kind,
            is_attestation=item.kind is EvidenceKind.OBSERVED,
            descendant_leaf_ids=item.descendant_leaf_ids,
            columns_covered=covered.get(item.node_id, 0),
            observations=tuple(
                PolarizeSegmentObservation(
                    segment=segment,
                    count=count,
                    example_concept_ids=tuple(examples[(item.node_id, segment)]),
                )
                for segment, count in sorted(
                    counts.get(item.node_id, {}).items(),
                    key=lambda entry: (-entry[1], entry[0] or ""),
                )
            ),
        )
        for item in outside
    )
    # Presence only, and one entry per distinct competing value. A node that
    # lacks a segment is never listed as evidence against it.
    candidates = tuple(
        PolarizeCandidateSummary(
            segment=segment,
            observed_node_ids=tuple(
                report.node_id
                for report in nodes
                if report.kind is EvidenceKind.OBSERVED
                and any(item.segment == segment for item in report.observations)
            ),
            reconstructed_node_ids=tuple(
                report.node_id
                for report in nodes
                if report.kind is EvidenceKind.RECONSTRUCTED
                and any(item.segment == segment for item in report.observations)
            ),
        )
        for segment in dict.fromkeys(
            value for value in wanted if value is not None
        )
    )
    return PolarizeResult(
        child_ids=arguments.child_ids,
        correspondence=arguments.correspondence,
        columns_matched=columns_matched,
        matched_concept_count=len(matched_concepts),
        matched_concept_ids=tuple(
            matched_concepts[:MAX_POLARIZE_EXAMPLE_CONCEPTS]
        ),
        nodes=nodes,
        candidates=candidates,
        segmentation_overlay_id=arguments.segmentation_overlay_id,
        note=_note(columns_matched, arguments.child_ids, outside),
    )


__all__ = ["polarize"]
