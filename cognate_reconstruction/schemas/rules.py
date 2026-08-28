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
    """Why a form resists the regular correspondences, in four kinds.

    A closed vocabulary rather than free text, because an anomaly is counted:
    `committed_anomaly_count` is a diagnostic, and a category a reviewer can
    tally is worth more than a phrase only its author can read. The categories
    are about *provenance*, not about how confident the session is.
    """

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
    """One irregularity a session could not resolve, and what it is about.

    Reported, never a gate: nothing here filters a trajectory, weights a
    candidate, or decides whether a run was valid. `commit_reconstruction`
    accepts an empty list and the harness never judges what an explanation
    says — it checks only that the object identifies its subject.

    Every field is described because the model writes these objects and reads
    nothing but this schema. On the sweeps of 2026-08-24 they were not, and 20
    rejections followed: `anomalies[].anomaly_type=missing`,
    `anomalies[].explanation=missing`, and — the shape the model reached for
    when the schema told it nothing — `anomalies[].type=extra_forbidden` and
    `anomalies[].issue=extra_forbidden`. This is the largest schema rejection
    class that is not specific to the inventory protocol; 13 of the 20 are on
    the pre-stage-3 instructions.
    """

    anomaly_type: AnomalyType = Field(
        description=(
            "Required. One of exactly four values: 'loanword', "
            "'morphological_leveling', 'taboo_deformation', "
            "'unknown_irregularity'. The field is named 'anomaly_type', not "
            "'type'. Use 'unknown_irregularity' whenever the other three would "
            "be a guess — an unresolved cause recorded as unresolved is a "
            "correct report."
        ),
    )
    explanation: NonEmptyStr = Field(
        description=(
            "Required. What is irregular, and what you tested before calling "
            "it irregular. The field is named 'explanation', not 'issue' or "
            "'description'. Nothing checks what it says; it is the audit "
            "record a reviewer reads instead of re-deriving your reasoning."
        ),
    )
    form_id: NonEmptyStr | None = Field(
        default=None,
        description=(
            "The single form this is about, when one form is. Give this or "
            "'concept_id' — an anomaly naming neither is refused, because an "
            "irregularity nothing can be traced to is not a report. Both is "
            "legal."
        ),
    )
    concept_id: NonEmptyStr | None = Field(
        default=None,
        description=(
            "The concept this is about, when the irregularity spans the "
            "children's forms rather than sitting in one of them. Give this or "
            "'form_id'; an anomaly naming neither is refused."
        ),
    )

    @model_validator(mode="after")
    def require_subject(self) -> AnomalyReport:
        if self.form_id is None and self.concept_id is None:
            raise ValueError("an anomaly must identify a form_id or concept_id")
        return self
