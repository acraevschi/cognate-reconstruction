"""Normalized lexical input schemas."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from cognate_reconstruction.schemas.common import (
    MORPHOLOGICAL_BOUNDARY_TOKENS,
    NonEmptyStr,
    WorkbenchModel,
)


class ConceptMetadata(WorkbenchModel):
    """Optional human-readable semantics for a stable concept identifier."""

    concept_id: NonEmptyStr
    gloss: NonEmptyStr | None = None
    concepticon_id: NonEmptyStr | None = None
    aliases: tuple[NonEmptyStr, ...] = ()
    semantic_field: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_aliases(self) -> ConceptMetadata:
        if len(set(self.aliases)) != len(self.aliases):
            raise ValueError("concept aliases must be unique")
        return self


class FormProvenance(WorkbenchModel):
    dataset_id: NonEmptyStr | None = None
    source_form_id: NonEmptyStr | None = None
    source_language_id: NonEmptyStr | None = None
    source_glottocode: NonEmptyStr | None = None
    tree_glottocode: NonEmptyStr | None = None
    source_row: int | None = Field(default=None, ge=1)
    segment_source: NonEmptyStr | None = None
    source_reference: NonEmptyStr | None = None
    compatibility_rule_ids: tuple[NonEmptyStr, ...] = ()


class CognateMembershipScope(StrEnum):
    """How much of the form a source cognacy judgement covers."""

    WHOLE_FORM = "whole_form"
    SEGMENT_SLICE = "segment_slice"


class CognateMembershipInterpretation(StrEnum):
    """A transparent interpretation of source membership structure."""

    ASSERTED = "asserted"
    ALTERNATIVE_ANALYSIS = "alternative_analysis"
    PARTIAL_COGNATE = "partial_cognate"


class CognateMembershipProvenance(WorkbenchModel):
    """Lossless source-row provenance for one cognacy judgement."""

    dataset_id: NonEmptyStr | None = None
    source_table: Literal["FormTable", "CognateTable"]
    source_row: int = Field(ge=1)
    source_membership_id: NonEmptyStr | None = None
    source_cognateset_id: NonEmptyStr
    source_segment_slice: tuple[NonEmptyStr, ...] = ()
    source_slice_unit: Literal["segment", "morpheme"] | None = None
    alignment: tuple[NonEmptyStr, ...] = ()
    sources: tuple[NonEmptyStr, ...] = ()
    cognate_detection_method: NonEmptyStr | None = None
    alignment_method: NonEmptyStr | None = None
    alignment_source: NonEmptyStr | None = None
    doubt: bool | None = None
    comment: NonEmptyStr | None = None
    source_reference: NonEmptyStr | None = None
    compatibility_rule_ids: tuple[NonEmptyStr, ...] = ()


class CognateMembership(WorkbenchModel):
    """One source cognacy judgement, without an inferred weight."""

    membership_id: NonEmptyStr
    cognate_set_id: NonEmptyStr
    scope: CognateMembershipScope
    interpretation: CognateMembershipInterpretation
    # Normalized zero-based positions into ``LexicalForm.segments``. The
    # original one-based inclusive CLDF slice remains in provenance.
    segment_indices: tuple[int, ...] = ()
    slice_unit: Literal["segment", "morpheme"] | None = None
    provenance: CognateMembershipProvenance

    @model_validator(mode="after")
    def validate_scope(self) -> CognateMembership:
        if len(set(self.segment_indices)) != len(self.segment_indices):
            raise ValueError("cognate membership segment indices must be unique")
        if any(index < 0 for index in self.segment_indices):
            raise ValueError("cognate membership segment indices must be non-negative")
        if self.scope is CognateMembershipScope.SEGMENT_SLICE:
            if not self.segment_indices:
                raise ValueError("segment-slice memberships require segment indices")
            if (
                self.interpretation
                is not CognateMembershipInterpretation.PARTIAL_COGNATE
            ):
                raise ValueError(
                    "segment-slice memberships must be partial-cognate judgements"
                )
            if self.slice_unit is None:
                raise ValueError("segment-slice memberships require a slice unit")
        elif self.segment_indices:
            raise ValueError("whole-form memberships cannot have segment indices")
        elif self.slice_unit is not None:
            raise ValueError("whole-form memberships cannot have a slice unit")
        if (
            self.interpretation
            is CognateMembershipInterpretation.ALTERNATIVE_ANALYSIS
            and self.scope is not CognateMembershipScope.WHOLE_FORM
        ):
            raise ValueError("alternative analyses must be whole-form judgements")
        return self


class LexicalForm(WorkbenchModel):
    """A tokenized form; ``+`` and ``-`` are structural, not IPA segments."""

    form_id: NonEmptyStr
    variety_id: NonEmptyStr
    concept_id: NonEmptyStr
    segments: tuple[NonEmptyStr, ...] = Field(min_length=1)
    # Backward-compatible shorthand for a single unambiguous whole-form
    # membership. It is deliberately null for partial or alternative analyses.
    cognate_set_id: NonEmptyStr | None = None
    cognate_memberships: tuple[CognateMembership, ...] = ()
    morphological_boundary_tokens: frozenset[str] = MORPHOLOGICAL_BOUNDARY_TOKENS
    provenance: FormProvenance = Field(default_factory=FormProvenance)

    @model_validator(mode="after")
    def validate_boundaries(self) -> LexicalForm:
        if not self.morphological_boundary_tokens:
            raise ValueError("morphological_boundary_tokens must not be empty")
        if self.morphological_boundary_tokens - MORPHOLOGICAL_BOUNDARY_TOKENS:
            raise ValueError("only '+' and '-' are supported as morphological boundaries")
        membership_ids = [
            membership.membership_id for membership in self.cognate_memberships
        ]
        if len(membership_ids) != len(set(membership_ids)):
            raise ValueError("cognate membership IDs must be unique within a form")
        for membership in self.cognate_memberships:
            if any(index >= len(self.segments) for index in membership.segment_indices):
                raise ValueError(
                    f"cognate membership {membership.membership_id!r} references "
                    "a segment outside the form"
                )
            if (
                membership.scope is CognateMembershipScope.SEGMENT_SLICE
                and not any(
                    self.segments[index]
                    not in self.morphological_boundary_tokens
                    for index in membership.segment_indices
                )
            ):
                raise ValueError(
                    f"cognate membership {membership.membership_id!r} selects "
                    "only morphological boundaries"
                )
        if self.cognate_set_id is not None:
            matching = tuple(
                membership
                for membership in self.cognate_memberships
                if membership.cognate_set_id == self.cognate_set_id
            )
            if self.cognate_memberships and (
                not matching
                or
                len({item.cognate_set_id for item in self.cognate_memberships}) != 1
                or any(
                    item.scope is not CognateMembershipScope.WHOLE_FORM
                    or item.interpretation
                    is CognateMembershipInterpretation.ALTERNATIVE_ANALYSIS
                    for item in matching
                )
            ):
                raise ValueError(
                    "cognate_set_id shorthand is only valid for one unambiguous "
                    "whole-form cognate set"
                )
        return self

    @property
    def phonetic_segments(self) -> tuple[str, ...]:
        """Return segments with structural morphological boundaries removed."""
        return tuple(s for s in self.segments if s not in self.morphological_boundary_tokens)

    @property
    def cognate_set_ids(self) -> tuple[str, ...]:
        """Return every source cognate set without selecting a primary one."""
        values = (
            tuple(item.cognate_set_id for item in self.cognate_memberships)
            if self.cognate_memberships
            else ((self.cognate_set_id,) if self.cognate_set_id else ())
        )
        return tuple(dict.fromkeys(values))

    def segments_for_membership(
        self,
        membership: CognateMembership,
        *,
        include_boundaries: bool = False,
    ) -> tuple[str, ...]:
        """Return the exact form subsequence covered by one judgement."""
        if membership.membership_id not in {
            item.membership_id for item in self.cognate_memberships
        }:
            raise ValueError(
                f"membership {membership.membership_id!r} does not belong to "
                f"form {self.form_id!r}"
            )
        selected = (
            tuple(self.segments[index] for index in membership.segment_indices)
            if membership.scope is CognateMembershipScope.SEGMENT_SLICE
            else self.segments
        )
        if include_boundaries:
            return selected
        return tuple(
            segment
            for segment in selected
            if segment not in self.morphological_boundary_tokens
        )


class LanguageLexicon(WorkbenchModel):
    variety_id: NonEmptyStr
    name: NonEmptyStr
    forms: tuple[LexicalForm, ...]
    dataset_id: NonEmptyStr | None = None
    source_language_id: NonEmptyStr | None = None
    source_glottocode: NonEmptyStr | None = None
    tree_glottocode: NonEmptyStr | None = None
    compatibility_rule_ids: tuple[NonEmptyStr, ...] = ()
    family: NonEmptyStr | None = None
    is_historical: bool = False

    @model_validator(mode="after")
    def validate_form_ownership(self) -> LanguageLexicon:
        ids: set[str] = set()
        for form in self.forms:
            if form.variety_id != self.variety_id:
                raise ValueError(f"form {form.form_id!r} belongs to another variety")
            if form.form_id in ids:
                raise ValueError(f"duplicate form_id {form.form_id!r}")
            ids.add(form.form_id)
        return self
