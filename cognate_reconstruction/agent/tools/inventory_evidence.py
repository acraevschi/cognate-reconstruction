"""Re-derive a node's correspondence sets, and check what a commit claims of them.

`test_proto_assembly` and `commit_reconstruction` both need the same four
things, so they live here rather than in whichever tool happened to need them
first:

- the node's own alignment under the committed segmentation and alignment
  overlays, which is what every set ID is derived from;
- the check that each commitment cites a set the data actually contains, and
  carries the support the harness itself counted;
- the check that a claimed conditioned split really is complementary over those
  columns;
- the check that a restoration's cited out-group genuinely attests the segment.

The validation invariant these implement is *stronger* than the per-rule one it
replaces, not weaker: a committed rule had to have been *tested*, while a
committed set has to be *re-derived* from the node's forms. A commitment citing
a set the data does not contain is refused; one whose support the model altered
is refused. Neither is a judgement about the linguistics.
"""

from __future__ import annotations

from collections.abc import Sequence

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.tools.errors import ToolInputError
from cognate_reconstruction.alignment.correspondence_sets import (
    build_correspondence_sets,
    one_reading_per_node,
)
from cognate_reconstruction.alignment.environments import (
    environment_matches,
    readings_from,
)
from cognate_reconstruction.schemas.alignment import (
    AlignmentMember,
    AlignmentResult,
    CorrespondenceDetail,
    CorrespondenceInventory,
    MultipleAlignmentMap,
)
from cognate_reconstruction.schemas.inventory import (
    AlignmentOverride,
    CorrespondenceCommitment,
    ResiduePolicy,
    SegmentRestoration,
)
from cognate_reconstruction.schemas.traversal import EvidenceRelation
from cognate_reconstruction.traversal.assembler import build_plan, resolve_columns

MAX_REPORTED_UNKNOWN_SETS = 8
"""Near-miss sets listed in an `unknown-correspondence-set` remediation."""


def node_alignments(
    context: AgentContext,
    *,
    segmentation_overlay_id: str | None,
    alignment_overlay_id: str | None,
    concept_ids: Sequence[str] = (),
) -> MultipleAlignmentMap:
    """The node's own n-way alignment, with any committed overrides applied.

    Overrides replace the aligner's columns for the concepts they name and
    nothing else, so a session that repaired one compound is reasoning about
    SCA's output everywhere else.
    """
    selected = set(concept_ids)
    lexicons = []
    for child_id in context.child_ids:
        lexicon = context.lexicon(child_id, segmentation_overlay_id)
        if selected:
            lexicon = lexicon.model_copy(
                update={
                    "forms": tuple(
                        form
                        for form in lexicon.forms
                        if form.concept_id in selected
                    )
                }
            )
        lexicons.append(lexicon)
    try:
        alignment_map = context.aligner.align_multiple(
            # The same reduction `summarize_correspondences` applies, and for
            # the same reason: the IDs derived here have to be the IDs a model
            # was handed there, and both have to be columns the assembler can
            # reproduce from one candidate per child.
            one_reading_per_node(lexicons),
            correspondence_detail=CorrespondenceDetail.SUMMARY,
        )
    except ToolInputError:
        raise
    except ValueError as error:
        raise ToolInputError(str(error), code="alignment-failed") from error
    return apply_alignment_overrides(
        alignment_map,
        context.alignment_overrides(alignment_overlay_id),
        context.child_ids,
    )


def apply_alignment_overrides(
    alignment_map: MultipleAlignmentMap,
    overrides: Sequence[AlignmentOverride],
    child_ids: Sequence[str],
) -> MultipleAlignmentMap:
    """Substitute the model's columns for the aligner's, concept by concept.

    The pairwise correspondence views are dropped rather than recomputed: they
    are the quadratic term, nothing in this path reads them, and leaving stale
    ones behind would be worse than returning none.
    """
    if not overrides:
        return alignment_map
    by_concept = {override.concept_id: override for override in overrides}
    order = {child_id: index for index, child_id in enumerate(child_ids)}
    rebuilt = []
    for alignment in alignment_map.alignments:
        override = by_concept.get(alignment.concept_id)
        if override is None:
            rebuilt.append(alignment)
            continue
        members = []
        for member in alignment.members:
            index = order.get(member.variety_id)
            if member.is_anchor or index is None or index >= len(override.rows):
                continue
            members.append(
                member.model_copy(
                    update={"aligned_segments": override.rows[index]}
                )
            )
        if len(members) < 2:
            rebuilt.append(alignment)
            continue
        rebuilt.append(alignment.model_copy(update={"members": tuple(members)}))
    return alignment_map.model_copy(
        update={
            "alignments": tuple(rebuilt),
            "pairwise_correspondences": (),
        }
    )


def node_inventory(
    context: AgentContext,
    *,
    segmentation_overlay_id: str | None,
    alignment_overlay_id: str | None,
    concept_ids: Sequence[str] = (),
) -> tuple[CorrespondenceInventory, MultipleAlignmentMap]:
    """The node's correspondence sets, with the alignment they came from."""
    alignment_map = node_alignments(
        context,
        segmentation_overlay_id=segmentation_overlay_id,
        alignment_overlay_id=alignment_overlay_id,
        concept_ids=concept_ids,
    )
    inventory = build_correspondence_sets(
        alignment_map,
        node_ids=context.child_ids,
        segmentation_overlay_id=segmentation_overlay_id,
        alignment_overlay_id=alignment_overlay_id,
    )
    return inventory, alignment_map


def verify_commitments(
    context: AgentContext,
    commitments: Sequence[CorrespondenceCommitment],
    inventory: CorrespondenceInventory,
) -> None:
    """Re-derive every cited set from the node's own forms, and refuse a miss.

    Two refusals, both arithmetic. `unknown-correspondence-set` means the cited
    ID is not in this node's data at all — most often stale, because a realign
    invalidates every ID derived under the previous overlay.
    `correspondence-support-mismatch` means the reflexes are right and the count
    is not, which is a transcription error: support is copied from the harness's
    own inventory and is the one number that separates a correspondence from
    residue, so it must never be a model claim.
    """
    by_id = {item.set_id: item for item in inventory.sets}
    for commitment in commitments:
        known = by_id.get(commitment.set_id)
        if known is None:
            raise ToolInputError(
                f"commitment cites correspondence set {commitment.set_id!r}, "
                "which this node's forms do not produce under the committed "
                "overlays",
                code="unknown-correspondence-set",
                remediation=_describe_unknown_set(commitment, inventory),
            )
        if tuple(commitment.reflexes) != tuple(known.segments):
            raise ToolInputError(
                f"commitment {commitment.set_id!r} carries reflexes "
                f"{list(commitment.reflexes)} but that set is "
                f"{list(known.segments)}",
                code="correspondence-support-mismatch",
                remediation=(
                    "The set_id is derived from the reflex tuple, so the two "
                    "cannot disagree. Copy the row back from "
                    "summarize_correspondences rather than retyping it."
                ),
            )
        if commitment.support != known.support:
            raise ToolInputError(
                f"commitment {commitment.set_id!r} claims support "
                f"{commitment.support}; this node's forms show "
                f"{known.support}",
                code="correspondence-support-mismatch",
                remediation=(
                    f"Set 'support' to {known.support}. It is the harness's own "
                    "count of aligned columns showing this set and is re-derived "
                    "on every commit, so it is never worth estimating."
                ),
            )


def _describe_unknown_set(
    commitment: CorrespondenceCommitment,
    inventory: CorrespondenceInventory,
) -> str:
    """Point at the set the model probably meant, when there is one."""
    lines = [
        "Correspondence sets are named by their content, so a set_id is only "
        "valid for the exact reflex tuple, child order, and overlays it was "
        "derived under. A realign call invalidates every earlier set_id.",
    ]
    exact = [
        item
        for item in inventory.sets
        if tuple(item.segments) == tuple(commitment.reflexes)
    ]
    if exact:
        lines.append(
            "This node does contain a set with exactly these reflexes, under a "
            f"different ID: {exact[0].set_id!r} at support {exact[0].support}. "
            "Cite that one."
        )
    else:
        near = [
            item
            for item in inventory.sets
            if sum(
                left != right
                for left, right in zip(
                    item.segments, commitment.reflexes, strict=False
                )
            )
            == 1
        ][:MAX_REPORTED_UNKNOWN_SETS]
        if near:
            lines.append(
                "Sets differing from the cited reflexes in one node: "
                + ", ".join(
                    f"{item.set_id!r} {list(item.segments)} (support "
                    f"{item.support})"
                    for item in near
                )
            )
        else:
            lines.append(
                "No set in this node's data is within one node of these "
                "reflexes. Re-run summarize_correspondences and cite a row it "
                "returned."
            )
    return "\n".join(lines)


def check_complementary_splits(
    context: AgentContext,
    commitments: Sequence[CorrespondenceCommitment],
    alignment_map: MultipleAlignmentMap,
    *,
    residue_policy: ResiduePolicy,
    residue_witness_child_id: str | None,
) -> None:
    """Check every `merges_with_set_id` claim against the node's own columns.

    Four conditions, all arithmetic over the forms: both commitments name the
    same non-null `proto_segment`; every occurrence of each set's reflex tuple
    satisfies that set's own conditioning; and no occurrence satisfies both. The
    harness is not deciding whether the collapse is *correct*, only whether the
    distributional claim the model made is true of the data in front of it — the
    same asymmetry that governs `polarize`.

    Environments are read through `alignment/environments.py`, the one
    definition the `complementary_candidates` report and the assembler also use.
    Columns are resolved under this very inventory first, so "the neighbouring
    proto-phoneme" means the same thing here as it does during assembly.
    """
    claims = [
        item for item in commitments if item.merges_with_set_id is not None
    ]
    if not claims:
        return
    by_id: dict[str, list[CorrespondenceCommitment]] = {}
    for item in commitments:
        by_id.setdefault(item.set_id, []).append(item)
    plan = build_plan(
        context.child_ids,
        commitments,
        residue_policy=residue_policy,
        residue_witness_child_id=residue_witness_child_id,
    )
    for claim in claims:
        partners = by_id.get(claim.merges_with_set_id or "")
        if not partners:
            raise ToolInputError(
                f"commitment {claim.set_id!r} claims a conditioned split with "
                f"{claim.merges_with_set_id!r}, which this inventory does not "
                "commit",
                code="non-complementary-split",
                remediation=(
                    "Both halves of a split have to be committed together: the "
                    "claim is about two sets being one phoneme, so the harness "
                    "needs both values and both conditionings to check it."
                ),
            )
        partner = partners[0]
        if (
            claim.proto_segment is None
            or partner.proto_segment is None
            or claim.proto_segment != partner.proto_segment
        ):
            raise ToolInputError(
                f"commitment {claim.set_id!r} claims a conditioned split with "
                f"{partner.set_id!r} but they reconstruct "
                f"{claim.proto_segment!r} and {partner.proto_segment!r}",
                code="non-complementary-split",
                remediation=(
                    "Two sets in complementary distribution are one phoneme, so "
                    "both commitments must name the same non-null "
                    "proto_segment. If they reconstruct different phonemes they "
                    "are not a split; drop merges_with_set_id."
                ),
            )
        if partner.conditioning is None:
            raise ToolInputError(
                f"the partner set {partner.set_id!r} of a claimed conditioned "
                "split carries no 'conditioning'",
                code="non-complementary-split",
                remediation=(
                    "A split says each set occurs where the other does not, so "
                    "each half needs the environment it is confined to."
                ),
            )
        _check_one_split(claim, partner, alignment_map, plan, context)


def _check_one_split(
    left: CorrespondenceCommitment,
    right: CorrespondenceCommitment,
    alignment_map: MultipleAlignmentMap,
    plan,
    context: AgentContext,
) -> None:
    order = {child_id: index for index, child_id in enumerate(context.child_ids)}
    for alignment in alignment_map.alignments:
        rows = _rows_for(alignment, order, len(context.child_ids))
        if rows is None:
            continue
        outcomes, _stats = resolve_columns(rows, alignment.concept_id, plan)
        decided = {
            outcome.resolution.column_index: outcome.reading
            for outcome in outcomes
        }
        readings = readings_from(rows, decided)
        for column in range(len(rows[0])):
            reflexes = tuple(row[column] for row in rows)
            for item, other in ((left, right), (right, left)):
                if reflexes != tuple(item.reflexes):
                    continue
                if item.conditioning is None:
                    continue
                own = environment_matches(item.conditioning, readings, column)
                if own is not True:
                    raise ToolInputError(
                        f"set {item.set_id!r} occurs in concept "
                        f"{alignment.concept_id!r} at column {column}, where its "
                        "own conditioning does not hold, so it is not confined "
                        "to the environment the split claims",
                        code="non-complementary-split",
                        remediation=(
                            "A conditioned split says every occurrence of this "
                            "set is in that environment. Widen or drop the "
                            "conditioning, or drop merges_with_set_id and "
                            "commit the two sets as two phonemes."
                        ),
                    )
                if other.conditioning is None:
                    continue
                theirs = environment_matches(
                    other.conditioning, readings, column
                )
                if theirs is True:
                    raise ToolInputError(
                        f"sets {left.set_id!r} and {right.set_id!r} both match "
                        f"the environment of concept {alignment.concept_id!r} "
                        f"column {column}, so they are not in complementary "
                        "distribution",
                        code="non-complementary-split",
                        remediation=(
                            "Complementary distribution means no environment "
                            "admits both. Narrow one of the two conditionings, "
                            "or drop merges_with_set_id."
                        ),
                    )


def _rows_for(
    alignment: AlignmentResult,
    order: dict[str, int],
    width: int,
) -> tuple[tuple[str | None, ...], ...] | None:
    """One row per child, positional, or `None` when fewer than two are present."""
    by_node: dict[int, tuple[str | None, ...]] = {}
    for member in alignment.members:
        if member.is_anchor or member.variety_id not in order:
            continue
        by_node[order[member.variety_id]] = member.aligned_segments
    if len(by_node) < 2:
        return None
    columns = len(next(iter(by_node.values())))
    return tuple(
        by_node.get(index, (None,) * columns) for index in range(width)
    )


def verify_restorations(
    context: AgentContext,
    restorations: Sequence[SegmentRestoration],
    alignment_map: MultipleAlignmentMap,
) -> None:
    """Check that every cited out-group really attests the restored segment.

    Three refusals, all arithmetic. The second is the same cladistic error
    `polarize` was built to prevent: a descendant lies *inside* the subtree and
    shows what these children became, which is the proposition under test rather
    than evidence about it. The third is a limit rather than a check, and it
    bites exactly where restoration is most tempting — the root has no
    out-group, so nothing licenses a restoration there.

    What is checked is that the evidence cited exists. Whether the restoration
    is *right* — whether the segment was lost independently in both branches, or
    the position is correct, or the out-group is the relevant one — is a
    linguistic judgement, and `restored_segment_count` is reported and gated on
    nothing.
    """
    if not restorations:
        return
    relations = {item.node_id: item.relation for item in context.evidence}
    outgroups = {
        node_id
        for node_id, relation in relations.items()
        if relation is EvidenceRelation.OUTGROUP
    }
    if not outgroups:
        raise ToolInputError(
            f"{len(restorations)} restoration(s) were requested at a node with "
            "no out-group, so nothing can license one",
            code="restoration-without-outgroup",
            remediation=(
                "A restoration is the claim that every active branch lost a "
                "segment some branch outside them still shows. At the root "
                "nothing lies outside, which is a property of the tree rather "
                "than a gap in the data — the same limit polarize carries. "
                "Reconstruct the segment at a node that does have an out-group, "
                "or drop the restoration."
            ),
        )
    by_concept = {
        alignment.concept_id: alignment for alignment in alignment_map.alignments
    }
    order = {child_id: index for index, child_id in enumerate(context.child_ids)}
    for restoration in restorations:
        descendants = [
            node_id
            for node_id in restoration.restored_from_node_ids
            if relations.get(node_id) is EvidenceRelation.DESCENDANT
        ]
        if descendants:
            raise ToolInputError(
                f"restoration of {restoration.proto_segment!r} in concept "
                f"{restoration.concept_id!r} cites {descendants}, which lie "
                "inside this node's subtree",
                code="restoration-cites-descendant",
                remediation=(
                    "A descendant shows what these children became, which is "
                    "the proposition under test rather than evidence about it. "
                    "Cite a node polarize reports with relation 'outgroup'."
                ),
            )
        unknown = [
            node_id
            for node_id in restoration.restored_from_node_ids
            if node_id not in relations
        ]
        if unknown:
            raise ToolInputError(
                f"restoration in concept {restoration.concept_id!r} cites "
                f"unavailable nodes: {unknown}",
                code="unknown-node",
                remediation=(
                    "list_available_nodes reports every node this session may "
                    "cite, with its relation to this one."
                ),
            )
        alignment = by_concept.get(restoration.concept_id)
        if alignment is None:
            raise ToolInputError(
                f"restoration cites concept {restoration.concept_id!r}, which "
                "no alignment at this node covers",
                code="restoration-unattested",
                remediation=(
                    "A restoration names a position in this node's own "
                    "alignment. Only concepts at least two active children "
                    "attest have one."
                ),
            )
        rows = _rows_for(alignment, order, len(context.child_ids))
        width = len(rows[0]) if rows else 0
        if restoration.before_column_index > width:
            raise ToolInputError(
                f"restoration in concept {restoration.concept_id!r} names "
                f"column {restoration.before_column_index}, past the "
                f"{width}-column alignment it would insert into",
                code="restoration-unattested",
                remediation=(
                    "before_column_index is an index into this concept's "
                    f"alignment, so it must be between 0 and {width}. "
                    "test_proto_assembly with detail='full' prints the columns."
                ),
            )
        attested = _restoration_is_attested(context, restoration)
        if not attested:
            raise ToolInputError(
                f"none of {list(restoration.restored_from_node_ids)} shows "
                f"{restoration.proto_segment!r} in concept "
                f"{restoration.concept_id!r}",
                code="restoration-unattested",
                remediation=(
                    "A restoration needs a real out-group node showing the real "
                    "segment. polarize reports what each node outside the "
                    "active children shows in the columns of a correspondence; "
                    "cite one that shows this segment in this concept."
                ),
            )


def _restoration_is_attested(
    context: AgentContext,
    restoration: SegmentRestoration,
) -> bool:
    """Does some cited node show the segment anywhere in this concept's form?

    Position is checked as membership in the cited node's form rather than as an
    aligned column index, and that is deliberate: the whole situation is that
    the active children have *no* column there, so there is no column to align
    the out-group against. Requiring the segment to be in the cited node's form
    for this concept is what the evidence can actually support, and it is a
    narrower power than `proto_segment` already has for an ordinary set.
    """
    for node_id in restoration.restored_from_node_ids:
        lexicon = context.evidence_lexicon(node_id)
        for form in lexicon.forms:
            if form.concept_id != restoration.concept_id:
                continue
            if restoration.proto_segment in form.phonetic_segments:
                return True
    return False


__all__ = [
    "apply_alignment_overrides",
    "check_complementary_splits",
    "node_alignments",
    "node_inventory",
    "verify_commitments",
    "verify_restorations",
]
