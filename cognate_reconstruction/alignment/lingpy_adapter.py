"""Typed wrapper around LingPy pairwise and multiple sequence alignment."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations, product
from typing import Literal

from cognate_reconstruction.schemas.alignment import (
    AlignmentMember,
    AlignmentResult,
    CorrespondenceMap,
    CorrespondenceObservation,
    CorrespondenceSummary,
    MultipleAlignmentMap,
)
from cognate_reconstruction.schemas.lexicon import (
    CognateMembershipInterpretation,
    CognateMembershipScope,
    LanguageLexicon,
    LexicalForm,
)


@dataclass(frozen=True)
class _AlignmentInput:
    form: LexicalForm
    segments: tuple[str, ...]
    cognate_set_id: str | None
    membership_id: str | None
    membership_scope: CognateMembershipScope | None
    membership_interpretation: CognateMembershipInterpretation | None
    source_segment_indices: tuple[int, ...]
    source_slice_unit: Literal["segment", "morpheme"] | None
    is_anchor: bool


def _alignment_inputs(
    form: LexicalForm,
    *,
    is_anchor: bool,
    respect_cognate_sets: bool,
) -> tuple[_AlignmentInput, ...]:
    if respect_cognate_sets and form.cognate_memberships:
        return tuple(
            _AlignmentInput(
                form=form,
                segments=form.segments_for_membership(membership),
                cognate_set_id=membership.cognate_set_id,
                membership_id=membership.membership_id,
                membership_scope=membership.scope,
                membership_interpretation=membership.interpretation,
                source_segment_indices=membership.segment_indices,
                source_slice_unit=membership.slice_unit,
                is_anchor=is_anchor,
            )
            for membership in form.cognate_memberships
        )
    return (
        _AlignmentInput(
            form=form,
            segments=form.phonetic_segments,
            cognate_set_id=(
                form.cognate_set_id if respect_cognate_sets else None
            ),
            membership_id=None,
            membership_scope=None,
            membership_interpretation=None,
            source_segment_indices=(),
            source_slice_unit=None,
            is_anchor=is_anchor,
        ),
    )


def _context(sequence: tuple[str | None, ...], index: int) -> tuple[str | None, str | None]:
    before = sequence[index - 1] if index > 0 else None
    after = sequence[index + 1] if index + 1 < len(sequence) else None
    return before, after


def _pairwise_map(
    left_id: str,
    right_id: str,
    alignments: Sequence[AlignmentResult],
) -> CorrespondenceMap:
    relevant = tuple(
        alignment
        for alignment in alignments
        if {left_id, right_id}
        <= {member.variety_id for member in alignment.members if not member.is_anchor}
    )
    observations: dict[
        tuple[str | None, str | None], list[CorrespondenceObservation]
    ] = defaultdict(list)
    for alignment in relevant:
        left_members = [m for m in alignment.members if m.variety_id == left_id]
        right_members = [m for m in alignment.members if m.variety_id == right_id]
        anchor_present = any(m.is_anchor for m in alignment.members)
        for left_member, right_member in product(left_members, right_members):
            for index, (left_segment, right_segment) in enumerate(
                zip(left_member.aligned_segments, right_member.aligned_segments, strict=True)
            ):
                observations[(left_segment, right_segment)].append(
                    CorrespondenceObservation(
                        alignment_id=alignment.alignment_id,
                        column_index=index,
                        left_segment=left_segment,
                        right_segment=right_segment,
                        left_context=_context(left_member.aligned_segments, index),
                        right_context=_context(right_member.aligned_segments, index),
                        anchor_supported=anchor_present,
                    )
                )
    summaries = tuple(
        CorrespondenceSummary(
            left_segment=pair[0],
            right_segment=pair[1],
            count=len(items),
            anchor_count=sum(item.anchor_supported for item in items),
            observations=tuple(items),
        )
        for pair, items in sorted(
            observations.items(), key=lambda item: (str(item[0][0]), str(item[0][1]))
        )
    )
    return CorrespondenceMap(
        left_variety_id=left_id,
        right_variety_id=right_id,
        alignments=relevant,
        correspondences=summaries,
    )


class LingPyAligner:
    """Align cognate-aware concept groups across two or more lexicons."""

    def __init__(
        self,
        *,
        method: Literal["sca"] = "sca",
        mode: Literal["global", "local", "overlap", "dialign"] = "global",
    ) -> None:
        if method != "sca":
            raise ValueError("LingPyAligner currently supports only the SCA model")
        if mode not in {"global", "local", "overlap", "dialign"}:
            raise ValueError(f"unsupported LingPy alignment mode {mode!r}")
        self.method = method
        self.mode = mode

    def align(
        self,
        left: LanguageLexicon,
        right: LanguageLexicon,
        anchors: tuple[LexicalForm, ...] = (),
    ) -> CorrespondenceMap:
        """Compatibility pairwise view derived from the same n-way engine."""
        result = self.align_multiple((left, right), anchors)
        return result.pairwise_correspondences[0]

    def align_multiple(
        self,
        lexicons: Sequence[LanguageLexicon],
        anchors: tuple[LexicalForm, ...] = (),
        *,
        respect_cognate_sets: bool = True,
    ) -> MultipleAlignmentMap:
        from lingpy import Multiple  # type: ignore[import-untyped]

        selected = tuple(lexicons)
        variety_ids = tuple(lexicon.variety_id for lexicon in selected)
        if len(variety_ids) < 2 or len(set(variety_ids)) != len(variety_ids):
            raise ValueError("alignment requires at least two distinct lexicons")

        grouped: dict[tuple[str, str | None], list[_AlignmentInput]] = defaultdict(list)
        for lexicon in selected:
            for form in lexicon.forms:
                for item in _alignment_inputs(
                    form,
                    is_anchor=False,
                    respect_cognate_sets=respect_cognate_sets,
                ):
                    grouped[(form.concept_id, item.cognate_set_id)].append(item)
        anchor_inputs = tuple(
            item
            for anchor in anchors
            for item in _alignment_inputs(
                anchor,
                is_anchor=True,
                respect_cognate_sets=respect_cognate_sets,
            )
        )

        alignments: list[AlignmentResult] = []
        for (concept_id, cognate_set_id), form_inputs in sorted(
            grouped.items(), key=lambda item: (item[0][0], item[0][1] or "")
        ):
            present = {item.form.variety_id for item in form_inputs}
            if len(present) < 2:
                continue
            compatible_anchors = [
                item
                for item in anchor_inputs
                if item.form.concept_id == concept_id
                and (
                    not respect_cognate_sets
                    or item.cognate_set_id is None
                    or cognate_set_id is None
                    or item.cognate_set_id == cognate_set_id
                )
            ]
            material = form_inputs + compatible_anchors
            multiple = Multiple(
                [list(item.segments) for item in material]
            )
            multiple.prog_align(model="sca", mode=self.mode)
            members = tuple(
                AlignmentMember(
                    form_id=item.form.form_id,
                    variety_id=item.form.variety_id,
                    concept_id=concept_id,
                    cognate_set_id=item.cognate_set_id,
                    membership_id=item.membership_id,
                    membership_scope=item.membership_scope,
                    membership_interpretation=item.membership_interpretation,
                    source_segment_indices=item.source_segment_indices,
                    source_slice_unit=item.source_slice_unit,
                    aligned_segments=tuple(
                        None if token == "-" else str(token) for token in aligned
                    ),
                    is_anchor=item.is_anchor,
                )
                for item, aligned in zip(
                    material, multiple.alm_matrix, strict=True
                )
            )
            group_suffix = cognate_set_id or "unassigned"
            alignments.append(
                AlignmentResult(
                    alignment_id=(
                        f"{':'.join(variety_ids)}:{concept_id}:{group_suffix}"
                    ),
                    concept_id=concept_id,
                    cognate_set_id=cognate_set_id,
                    members=members,
                    method=self.method,
                    mode=self.mode,
                )
            )

        pairwise = tuple(
            _pairwise_map(left_id, right_id, alignments)
            for left_id, right_id in combinations(variety_ids, 2)
        )
        return MultipleAlignmentMap(
            variety_ids=variety_ids,
            alignments=tuple(alignments),
            pairwise_correspondences=pairwise,
        )
