"""LingPy-independent alignment and correspondence schemas."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from cognate_reconstruction.schemas.common import NonEmptyStr, WorkbenchModel
from cognate_reconstruction.schemas.lexicon import (
    CognateMembershipInterpretation,
    CognateMembershipScope,
)

MAX_CORRESPONDENCE_EXAMPLES = 3
"""Example references one compact correspondence record carries.

Small on purpose. An example is a pointer for a follow-up call, not the
evidence: the count says how often the correspondence recurs, and the aligned
material it points into is already present once at the top of the payload.
"""

GAP_SEGMENT_TOKENS: frozenset[str] = frozenset({"Ø", "∅"})
"""Spellings a caller may use to mean "the gap" when filtering segments.

An alignment gap is `None` in these models, which no tool argument can express.
These are the same two characters the sound-law DSL accepts for deletion, so a
model that knows the DSL already knows how to ask for a gap.
"""


class CorrespondenceDetail(StrEnum):
    """How much of the aligner's working trace a correspondence view carries.

    `SUMMARY` keeps the answer — which segments correspond and how often — and
    reduces the trace to bounded references into the alignments that are
    serialized once anyway. `FULL` keeps every column occurrence with its
    contexts, which is the aligner's working trace and costs one record per
    aligned column per node pair.
    """

    SUMMARY = "summary"
    FULL = "full"


class AlignmentMember(WorkbenchModel):
    form_id: NonEmptyStr
    variety_id: NonEmptyStr
    concept_id: NonEmptyStr
    cognate_set_id: NonEmptyStr | None = None
    membership_id: NonEmptyStr | None = None
    membership_scope: CognateMembershipScope | None = None
    membership_interpretation: CognateMembershipInterpretation | None = None
    source_segment_indices: tuple[int, ...] = ()
    source_slice_unit: Literal["segment", "morpheme"] | None = None
    aligned_segments: tuple[str | None, ...]
    is_anchor: bool = False

    @model_validator(mode="after")
    def validate_membership_metadata(self) -> AlignmentMember:
        details_present = (
            self.membership_scope is not None
            or self.membership_interpretation is not None
            or bool(self.source_segment_indices)
            or self.source_slice_unit is not None
        )
        if details_present != (self.membership_id is not None):
            raise ValueError(
                "alignment membership metadata requires a membership ID"
            )
        return self


class AlignmentResult(WorkbenchModel):
    alignment_id: NonEmptyStr
    concept_id: NonEmptyStr
    members: tuple[AlignmentMember, ...] = Field(min_length=2)
    cognate_set_id: NonEmptyStr | None = None
    alignment_score: float | None = None
    method: Literal["sca"] = "sca"
    mode: Literal["global", "local", "overlap", "dialign"] = "global"

    @model_validator(mode="after")
    def validate_width(self) -> AlignmentResult:
        widths = {len(member.aligned_segments) for member in self.members}
        if len(widths) != 1:
            raise ValueError("all alignment members must have equal width")
        return self


class CorrespondenceObservation(WorkbenchModel):
    alignment_id: NonEmptyStr
    column_index: int = Field(ge=0)
    left_segment: str | None
    right_segment: str | None
    left_context: tuple[str | None, str | None]
    right_context: tuple[str | None, str | None]
    anchor_supported: bool = False


class CorrespondenceExample(WorkbenchModel):
    """A resolvable pointer to one aligned column.

    `alignment_id` names an entry of the `MultipleAlignmentMap.alignments` that
    carries this record and `column_index` a column inside it, so a compact
    summary can cite its evidence without copying it. The full
    `CorrespondenceObservation` is derivable from the pair.
    """

    alignment_id: NonEmptyStr
    column_index: int = Field(ge=0)


class CorrespondenceSummary(WorkbenchModel):
    """How often one segment pair corresponds, with an optional trace.

    `count` is always the true number of aligned column occurrences.
    The two example fields are *samples* and may be shorter than `count` or
    empty; neither is named `observations` precisely because neither is
    required to be complete:

    - `example_observations` carries whole occurrences with their contexts, and
      is populated only for `CorrespondenceDetail.FULL`;
    - `example_columns` carries bounded references into the enclosing map's
      alignments, and is the compact rendering.
    """

    left_segment: str | None
    right_segment: str | None
    count: int = Field(ge=1)
    anchor_count: int = Field(ge=0)
    example_observations: tuple[CorrespondenceObservation, ...] = ()
    example_columns: tuple[CorrespondenceExample, ...] = ()

    @model_validator(mode="after")
    def validate_counts(self) -> CorrespondenceSummary:
        if self.anchor_count > self.count:
            raise ValueError(
                "anchor-supported occurrences cannot exceed the total count"
            )
        if len(self.example_observations) > self.count:
            raise ValueError(
                "sampled observations cannot exceed the occurrence count"
            )
        if len(self.example_columns) > self.count:
            raise ValueError("sampled columns cannot exceed the occurrence count")
        return self


class CorrespondenceMap(WorkbenchModel):
    """One pairwise view over alignments held elsewhere.

    The n-way alignments belong to the enclosing `MultipleAlignmentMap` and are
    serialized once there. This map references the ones it covers by ID: with N
    nodes there are N·(N−1)/2 of these, and embedding a copy of the alignments
    in each is what made a ten-language alignment call larger than most context
    windows.
    """

    left_variety_id: NonEmptyStr
    right_variety_id: NonEmptyStr
    alignment_ids: tuple[NonEmptyStr, ...] = ()
    correspondences: tuple[CorrespondenceSummary, ...]


class MultipleAlignmentMap(WorkbenchModel):
    """N-way alignment plus derived pairwise correspondence views."""

    variety_ids: tuple[NonEmptyStr, ...] = Field(min_length=2)
    alignments: tuple[AlignmentResult, ...]
    pairwise_correspondences: tuple[CorrespondenceMap, ...]
    detail: CorrespondenceDetail = CorrespondenceDetail.FULL

    @model_validator(mode="after")
    def validate_varieties(self) -> MultipleAlignmentMap:
        if len(set(self.variety_ids)) != len(self.variety_ids):
            raise ValueError("multiple-alignment variety IDs must be unique")
        return self

    @model_validator(mode="after")
    def validate_references(self) -> MultipleAlignmentMap:
        """Keep every ID in a pairwise view resolvable against `alignments`.

        Pairwise maps stopped carrying their own copy of the alignments, so a
        dangling ID would leave a reader with a reference and nothing to resolve
        it against. Checking it here is what makes the reference honest.
        """
        known = {alignment.alignment_id for alignment in self.alignments}
        for correspondence_map in self.pairwise_correspondences:
            referenced = set(correspondence_map.alignment_ids)
            for summary in correspondence_map.correspondences:
                referenced.update(
                    example.alignment_id for example in summary.example_columns
                )
                referenced.update(
                    observation.alignment_id
                    for observation in summary.example_observations
                )
            if unknown := sorted(referenced - known):
                raise ValueError(
                    "pairwise correspondences reference unknown alignment IDs: "
                    f"{unknown}"
                )
        return self


class CorrespondenceSet(WorkbenchModel):
    """One correspondence set: aligned segments across every selected node.

    This is the object the comparative method operates on. `segments` is
    positional against the `node_ids` of the inventory carrying it, with `None`
    for a gap, and `support` counts the aligned columns showing exactly this
    n-tuple.

    Examples are concept IDs rather than form IDs because a concept ID is the
    handle every other evidence tool accepts: the follow-up call from a row of
    this inventory is `get_alignments` or `search_forms` over those concepts.
    """

    segments: tuple[str | None, ...] = Field(min_length=2)
    support: int = Field(ge=1)
    concept_count: int = Field(ge=1)
    example_concept_ids: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def validate_support(self) -> CorrespondenceSet:
        if self.concept_count > self.support:
            raise ValueError(
                "a correspondence set cannot occur in more concepts than columns"
            )
        if len(self.example_concept_ids) > self.concept_count:
            raise ValueError(
                "sampled concept IDs cannot exceed the concept count"
            )
        return self


class CorrespondenceInventory(WorkbenchModel):
    """Every correspondence set over one evidence selection, by support.

    The complete deterministic aggregate, ordered by descending support. It is
    the whole inventory rather than a page: callers that answer a model bound
    their own output, and the counts here are what tell a reader that a page has
    a tail behind it.
    """

    node_ids: tuple[NonEmptyStr, ...] = Field(min_length=2)
    alignment_count: int = Field(ge=0)
    sets: tuple[CorrespondenceSet, ...] = ()

    @model_validator(mode="after")
    def validate_inventory(self) -> CorrespondenceInventory:
        if len(set(self.node_ids)) != len(self.node_ids):
            raise ValueError("inventory node IDs must be unique")
        width = len(self.node_ids)
        for item in self.sets:
            if len(item.segments) != width:
                raise ValueError(
                    "every correspondence set must have one segment per node"
                )
        return self
