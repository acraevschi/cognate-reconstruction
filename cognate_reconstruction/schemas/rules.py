"""Sound-law AST, application diff, and anomaly schemas."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, computed_field, model_validator

from cognate_reconstruction.schemas.common import (
    MORPHOLOGICAL_BOUNDARY_TOKENS,
    NonEmptyStr,
    WorkbenchModel,
)


class SegmentExpression(WorkbenchModel):
    """Literal token expression with explicit structural-boundary vocabulary."""

    tokens: tuple[NonEmptyStr, ...]
    morphological_boundary_tokens: frozenset[str] = MORPHOLOGICAL_BOUNDARY_TOKENS

    @model_validator(mode="after")
    def validate_boundary_vocabulary(self) -> SegmentExpression:
        if self.morphological_boundary_tokens - MORPHOLOGICAL_BOUNDARY_TOKENS:
            raise ValueError("only '+' and '-' are supported as morphological boundaries")
        return self


class RuleEnvironment(WorkbenchModel):
    left: SegmentExpression | None = None
    right: SegmentExpression | None = None
    word_initial: bool = False
    word_final: bool = False


class ParsedSoundRule(WorkbenchModel):
    rule_id: NonEmptyStr
    source: NonEmptyStr
    target: SegmentExpression
    replacement: SegmentExpression
    environment: RuleEnvironment

    @model_validator(mode="after")
    def validate_target(self) -> ParsedSoundRule:
        if not self.target.tokens:
            raise ValueError("sound-rule target must not be empty")
        if any(t in self.target.morphological_boundary_tokens for t in self.target.tokens):
            raise ValueError("morphological boundaries may constrain context but not be targets")
        if any(t in self.replacement.morphological_boundary_tokens for t in self.replacement.tokens):
            raise ValueError("rules may not insert morphological boundaries")
        return self


class ReconstructionRule(WorkbenchModel):
    """A confidence-weighted rule scoped to one or more active children."""

    rule: ParsedSoundRule
    source_child_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)
    confidence: float = Field(gt=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_child_scope(self) -> ReconstructionRule:
        if len(set(self.source_child_ids)) != len(self.source_child_ids):
            raise ValueError("source_child_ids must be unique")
        return self


class AnchorPolicy(StrEnum):
    """How optional ancestor anchors influence reconstruction."""

    IGNORE = "ignore"
    ADVISORY = "advisory"
    SCORED = "scored"


class ApplicationStatus(StrEnum):
    APPLIED = "applied"
    TARGET_ABSENT = "target_absent"
    CONTEXT_MISMATCH = "context_mismatch"
    ANCHOR_MISMATCH = "anchor_mismatch"
    WOULD_EMPTY_FORM = "would_empty_form"
    """The rule matched, and applying it would leave the form with no segments.

    Refused rather than applied, because an empty form is not a form: every
    other layer already says so -- `LexicalForm.segments` requires at least one
    token and `normalize_and_prune` drops an empty candidate -- and until this
    existed `RuleEngine.apply_rules` discovered it by handing pydantic an empty
    tuple, raising a `ValidationError` from inside the reconstructor with no
    rule, form, or node named. Reachable from both commit shapes: a cascade of
    deletions under `rules`, and under `inventory` any derived view where enough
    sets reconstruct nothing, which is how it was found.

    Counted as *applicable and not applied*, so `rule_coverage` sees a rule that
    could have fired and did not. Nothing gates on it.
    """


class MatchLocation(WorkbenchModel):
    start_token: int = Field(ge=0)
    end_token: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_span(self) -> MatchLocation:
        if self.end_token <= self.start_token:
            raise ValueError("match location must be a non-empty half-open span")
        return self


class FormRuleResult(WorkbenchModel):
    form_id: NonEmptyStr
    source_candidate_id: NonEmptyStr | None = None
    input_segments: tuple[str, ...]
    output_segments: tuple[str, ...]
    status: ApplicationStatus
    locations: tuple[MatchLocation, ...] = ()
    target_occurrences: int = Field(default=0, ge=0)
    anchor_ids: tuple[NonEmptyStr, ...] = ()
    matched_anchor_ids: tuple[NonEmptyStr, ...] = ()
    explanation: NonEmptyStr


class RuleApplicationReport(WorkbenchModel):
    rule: ParsedSoundRule
    results: tuple[FormRuleResult, ...]

    @computed_field
    @property
    def words_applied(self) -> int:
        return sum(bool(result.locations) for result in self.results)

    @computed_field
    @property
    def anchors_matched(self) -> int:
        return sum(len(result.matched_anchor_ids) for result in self.results)

    @computed_field
    @property
    def exceptions(self) -> tuple[FormRuleResult, ...]:
        return tuple(
            result for result in self.results if result.status is not ApplicationStatus.APPLIED
        )


class AnomalyType(StrEnum):
    """Why a form resists the regular correspondences, in four kinds."""

    LOANWORD = "loanword"
    """Borrowed, so it never underwent the changes the cognates did.

    Needs positive evidence — a donor, or a shape belonging to another
    stratum. "Irregular, therefore borrowed" is the claim this label is most
    often used to hide, and `system_prompt.md` forbids it.
    """

    MORPHOLOGICAL_LEVELING = "morphological_leveling"
    """Regular sound change ran and was undone by analogy with a paradigm."""

    TABOO_DEFORMATION = "taboo_deformation"
    """Deliberately altered to avoid a proscribed form."""

    UNKNOWN_IRREGULARITY = "unknown_irregularity"
    """The cause is unresolved, and saying so is the honest report.

    The correct label whenever the other three would be a guess. Say in
    `explanation` what you tested and what it ruled out; an unexplained
    correspondence recorded as unexplained costs nothing, and one filed as a
    loanword without a donor is a fabricated fact in the audit record.
    """


class AnomalyReport(WorkbenchModel):
    """One irregularity a session could not resolve, and what it is about."""

    anomaly_type: AnomalyType = Field(
        description=(
            'Required field anomaly_type, not \'type\': loanword, morphological_leveling, taboo_deformation or unknown_irregularity. Use unknown_irregularity when cause is unresolved.'
        ),
    )
    explanation: NonEmptyStr = Field(
        description=(
            'Required field explanation, not \'issue\': what is irregular and what you inspected. This records reasoning, not a historical grade.'
        ),
    )
    form_id: NonEmptyStr | None = Field(
        default=None,
        description=(
            'Give form_id or concept_id (or both) from this node; naming neither is refused.'
        ),
    )
    concept_id: NonEmptyStr | None = Field(
        default=None,
        description=(
            'Give concept_id or form_id (or both) from this node; naming neither is refused.'
        ),
    )

    @model_validator(mode="after")
    def require_subject(self) -> AnomalyReport:
        if self.form_id is None and self.concept_id is None:
            raise ValueError("an anomaly must identify a form_id or concept_id")
        return self
