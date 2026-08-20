"""Strict provider-neutral schemas for the hypothesis-manager layer."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from cognate_reconstruction.schemas.alignment import (
    CorrespondenceDetail,
    CorrespondenceSet,
    MultipleAlignmentMap,
)
from cognate_reconstruction.schemas.common import NonEmptyStr, WorkbenchModel
from cognate_reconstruction.schemas.lexicon import LexicalForm
from cognate_reconstruction.schemas.lexicon import ConceptMetadata
from cognate_reconstruction.schemas.rules import (
    AnomalyReport,
    AnchorPolicy,
    ParsedSoundRule,
    ReconstructionRule,
    RuleApplicationReport,
)
from cognate_reconstruction.schemas.traversal import (
    EvidenceKind,
    EvidenceRelation,
)


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class LLMToolCall(WorkbenchModel):
    call_id: NonEmptyStr
    name: NonEmptyStr
    arguments: dict[str, Any]


class LLMMessage(WorkbenchModel):
    role: MessageRole
    content: str | None = None
    tool_calls: tuple[LLMToolCall, ...] = ()
    tool_call_id: NonEmptyStr | None = None
    name: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_role_fields(self) -> LLMMessage:
        if self.role is MessageRole.ASSISTANT:
            if self.content is None and not self.tool_calls:
                raise ValueError("assistant messages need content or tool calls")
        elif self.tool_calls:
            raise ValueError("only assistant messages may contain tool calls")
        if self.role is MessageRole.TOOL:
            if self.tool_call_id is None or self.name is None or self.content is None:
                raise ValueError("tool messages require call ID, name, and content")
        elif self.tool_call_id is not None or self.name is not None:
            raise ValueError("tool_call_id and name are only valid on tool messages")
        if self.role in {MessageRole.SYSTEM, MessageRole.USER} and self.content is None:
            raise ValueError("system and user messages require content")
        return self


class ProviderUsage(WorkbenchModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0.0)


class ProviderResponseMetadata(WorkbenchModel):
    provider_id: NonEmptyStr | None = None
    model_id: NonEmptyStr | None = None
    response_id: NonEmptyStr | None = None
    finish_reason: NonEmptyStr | None = None
    usage: ProviderUsage | None = None


class ProviderResponse(WorkbenchModel):
    message: LLMMessage
    metadata: ProviderResponseMetadata = Field(
        default_factory=ProviderResponseMetadata
    )

    # Convenience accessors retain a compact adapter experience while the
    # orchestrator consumes explicit response metadata.
    @property
    def role(self) -> MessageRole:
        return self.message.role

    @property
    def content(self) -> str | None:
        return self.message.content

    @property
    def tool_calls(self) -> tuple[LLMToolCall, ...]:
        return self.message.tool_calls


class LLMToolDefinition(WorkbenchModel):
    name: NonEmptyStr
    description: NonEmptyStr
    parameters: dict[str, Any]


class ToolError(WorkbenchModel):
    error_type: NonEmptyStr
    message: NonEmptyStr
    code: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Stable structural identifier for this rejection, used for counting "
            "and matching only. The full explanation stays in 'message'."
        ),
    )
    remediation: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Deterministic guidance derived from recorded session state, "
            "explaining how to construct an accepted call."
        ),
    )


class ToolExecutionResult(WorkbenchModel):
    ok: bool
    result: dict[str, Any] | None = None
    error: ToolError | None = None

    @model_validator(mode="after")
    def validate_result_shape(self) -> ToolExecutionResult:
        if self.ok == (self.error is not None):
            raise ValueError("successful results cannot contain errors and failures must")
        if self.ok != (self.result is not None):
            raise ValueError("successful tool calls must contain a result")
        return self


MAX_ALIGNMENT_CONCEPTS = 24
"""Concept IDs one `get_alignments` call may request.

Raised from 12 once the default payload stopped carrying the aligner's working
trace, and measured rather than guessed. On the ten-daughter Polynesian
benchmark, `detail="summary"` costs 41 KB for 24 concepts across two nodes and
82 KB across three — the widths a node session actually aligns, since a rule is
committed against active children.

What the cap does *not* bound is bytes. The payload also carries one pairwise
view per node pair, so cost grows quadratically in the node count: the same
24-concept request across ten nodes is 782 KB. Doubling the cap costs 42% there
(551 KB at 12 concepts) because the pairwise segment inventory saturates long
before the concept list does, which is exactly why the concept count is the
wrong lever for that call — `summarize_correspondences` covers all 46 concepts
across all ten nodes in 22 KB and is what a wide survey should use.
"""

MAX_ALIGNMENT_FORMS = 48
"""Exact form IDs one `get_alignments` call may request."""


class GetAlignmentsArgs(WorkbenchModel):
    """One bounded alignment request over two or more evidence nodes.

    `detail` decides how much of the aligner's trace comes back and defaults to
    the compact rendering; see `CorrespondenceDetail`.
    """

    node_ids: tuple[NonEmptyStr, ...] = Field(min_length=2)
    concept_ids: tuple[NonEmptyStr, ...] = Field(
        default=(),
        max_length=MAX_ALIGNMENT_CONCEPTS,
        description=(
            "Concept IDs to align, at most 24. Prefer far smaller batches: this "
            "is a ceiling on one call, not a target. Use "
            "summarize_correspondences to decide which concepts are worth "
            "aligning."
        ),
    )
    form_ids: tuple[NonEmptyStr, ...] = Field(
        default=(),
        max_length=MAX_ALIGNMENT_FORMS,
        description="Exact form IDs to align, at most 48.",
    )
    detail: CorrespondenceDetail = Field(
        default=CorrespondenceDetail.SUMMARY,
        description=(
            "'summary' returns each correspondence with its true occurrence "
            "count and a few example column references into the alignments "
            "already in the payload. 'full' additionally returns every column "
            "occurrence with its contexts, which is the aligner's working trace "
            "and is orders of magnitude larger; ask for it only for a "
            "correspondence you are actively conditioning."
        ),
    )
    segmentation_overlay_id: NonEmptyStr | None = None
    respect_cognate_sets: bool = True
    include_anchors: bool = False

    @model_validator(mode="after")
    def validate_nodes(self) -> GetAlignmentsArgs:
        if len(set(self.node_ids)) != len(self.node_ids):
            raise ValueError("get_alignments requires distinct node IDs")
        if not self.concept_ids and not self.form_ids:
            raise ValueError(
                "get_alignments requires an explicit bounded concept_ids or "
                "form_ids selection; inspect evidence in small batches"
            )
        if len(set(self.concept_ids)) != len(self.concept_ids):
            raise ValueError("get_alignments concept IDs must be unique")
        if len(set(self.form_ids)) != len(self.form_ids):
            raise ValueError("get_alignments form IDs must be unique")
        return self


class GetAlignmentsResult(WorkbenchModel):
    alignment_map: MultipleAlignmentMap
    segmentation_overlay_id: NonEmptyStr | None = None


class EvidenceScope(StrEnum):
    ACTIVE_CHILDREN = "active_children"
    AVAILABLE_TREE = "available_tree"


class SegmentPosition(StrEnum):
    INITIAL = "initial"
    FINAL = "final"
    CONTAINS = "contains"
    EXACT = "exact"


class ListConceptsArgs(WorkbenchModel):
    query: str | None = None
    scope: EvidenceScope = EvidenceScope.ACTIVE_CHILDREN
    node_ids: tuple[NonEmptyStr, ...] = ()
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)


class ConceptListing(WorkbenchModel):
    concept: ConceptMetadata
    form_count: int = Field(ge=1)
    node_ids: tuple[NonEmptyStr, ...]


class ListConceptsResult(WorkbenchModel):
    concepts: tuple[ConceptListing, ...]
    next_offset: int | None = Field(default=None, ge=0)


class SearchFormsArgs(WorkbenchModel):
    scope: EvidenceScope = EvidenceScope.ACTIVE_CHILDREN
    node_ids: tuple[NonEmptyStr, ...] = ()
    concept_ids: tuple[NonEmptyStr, ...] = ()
    concept_query: str | None = None
    segment_pattern: tuple[NonEmptyStr, ...] = ()
    position: SegmentPosition = SegmentPosition.CONTAINS
    cognate_set_ids: tuple[NonEmptyStr, ...] = ()
    include_boundaries: bool = False
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=200)


class FormSearchHit(WorkbenchModel):
    node_id: NonEmptyStr
    evidence_kind: EvidenceKind
    relation: EvidenceRelation
    concept: ConceptMetadata
    form: LexicalForm


class SearchFormsResult(WorkbenchModel):
    hits: tuple[FormSearchHit, ...]
    next_offset: int | None = Field(default=None, ge=0)


DEFAULT_MIN_CORRESPONDENCE_SUPPORT = 2
"""Occurrences a correspondence set needs before it is shown by default.

A correspondence attested once is residue: a compound boundary, a loan, a
segmentation artefact. Recurrence is what the comparative method reasons from,
so the tail is suppressed by default and counted rather than hidden.
"""


class SummarizeCorrespondencesArgs(WorkbenchModel):
    """Request the correspondence-set inventory over the whole evidence set.

    Unlike `get_alignments` this deliberately has no batching bound on its
    input: recurrence is only visible across every cognate set at once, and the
    inventory over all of them is smaller than a handful of alignments. The
    *output* is bounded by pagination instead.
    """

    node_ids: tuple[NonEmptyStr, ...] = Field(
        default=(),
        description=(
            "Nodes to compare, in the order their segments appear in every "
            "returned set. Defaults to every node in scope, which for the "
            "default scope is the active children."
        ),
    )
    scope: EvidenceScope = EvidenceScope.ACTIVE_CHILDREN
    concept_ids: tuple[NonEmptyStr, ...] = Field(
        default=(),
        description=(
            "Optional narrowing to specific concepts. Omit it: the point of "
            "this tool is the inventory over every concept at once."
        ),
    )
    min_support: int = Field(
        default=DEFAULT_MIN_CORRESPONDENCE_SUPPORT,
        ge=1,
        description=(
            "Least number of aligned columns a set must show to be returned. "
            "Sets below it are counted in 'suppressed_below_min_support' rather "
            "than dropped silently. Use 1 only to inspect residue."
        ),
    )
    segment: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Return only sets containing this segment. Use 'Ø' or '∅' for an "
            "alignment gap. With 'segment_node_id' the segment must appear in "
            "that node; without it, in any node in scope."
        ),
    )
    segment_node_id: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Restrict the 'segment' filter to one node, for example every set "
            "in which Tongan shows 'ʔ'. Requires 'segment'."
        ),
    )
    segmentation_overlay_id: NonEmptyStr | None = None
    respect_cognate_sets: bool = True
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=30, ge=1, le=200)
    # There is deliberately no include_anchors. An anchor is a form attached to
    # the parent, not one of the compared nodes, so it can never be a column of a
    # correspondence set; admitting one would only perturb how the columns align
    # while contributing nothing a caller could read. Anchors stay visible
    # through get_alignments.

    @model_validator(mode="after")
    def validate_selection(self) -> SummarizeCorrespondencesArgs:
        if len(set(self.node_ids)) != len(self.node_ids):
            raise ValueError("summarize_correspondences node IDs must be unique")
        if len(set(self.concept_ids)) != len(self.concept_ids):
            raise ValueError("summarize_correspondences concept IDs must be unique")
        if self.node_ids and len(self.node_ids) < 2:
            raise ValueError(
                "a correspondence inventory compares at least two nodes; omit "
                "node_ids to use every node in scope"
            )
        if self.segment_node_id is not None and self.segment is None:
            raise ValueError("segment_node_id requires a segment to filter on")
        return self


class SummarizeCorrespondencesResult(WorkbenchModel):
    node_ids: tuple[NonEmptyStr, ...] = Field(
        description="Column order of every returned set's 'segments'."
    )
    alignment_count: int = Field(
        ge=0,
        description="Cognate-set alignments the inventory was built from.",
    )
    total_set_count: int = Field(
        ge=0,
        description="Distinct correspondence sets found, before any filtering.",
    )
    suppressed_below_min_support: int = Field(
        ge=0,
        description=(
            "Sets that passed the segment filter but fell below min_support. "
            "Residue rather than evidence, counted so it is never silent."
        ),
    )
    matched_set_count: int = Field(
        ge=0,
        description=(
            "Sets satisfying both min_support and the segment filter. Those "
            "beyond 'limit' are reachable through 'next_offset'."
        ),
    )
    min_support: int = Field(ge=1)
    sets: tuple[CorrespondenceSet, ...]
    next_offset: int | None = Field(default=None, ge=0)
    segmentation_overlay_id: NonEmptyStr | None = None


class ListAvailableNodesArgs(WorkbenchModel):
    kinds: tuple[EvidenceKind, ...] = ()
    relations: tuple[EvidenceRelation, ...] = ()


class AvailableNodeSummary(WorkbenchModel):
    node_id: NonEmptyStr
    kind: EvidenceKind
    relation: EvidenceRelation
    descendant_leaf_ids: tuple[NonEmptyStr, ...] = ()
    form_count: int = Field(ge=0)
    concept_count: int = Field(ge=0)
    has_committed_hypothesis: bool = Field(
        default=False,
        description=(
            "True when this node was reconstructed earlier in this run and its "
            "committed rules can be retrieved with get_node_reconstruction."
        ),
    )


class ListAvailableNodesResult(WorkbenchModel):
    nodes: tuple[AvailableNodeSummary, ...]


class PriorCommittedRule(WorkbenchModel):
    """One rule from an already-completed node session, exposed read-only."""

    dsl: NonEmptyStr
    source_child_ids: tuple[NonEmptyStr, ...]
    confidence: float = Field(gt=0.0, le=1.0)


class PriorNodeReconstruction(WorkbenchModel):
    node_id: NonEmptyStr
    rules: tuple[PriorCommittedRule, ...]
    anomalies: tuple[AnomalyReport, ...] = ()
    summary: NonEmptyStr
    identity_reconstruction: bool


class GetNodeReconstructionArgs(WorkbenchModel):
    node_id: NonEmptyStr = Field(
        description=(
            "One already-reconstructed internal node ID, as reported by "
            "list_available_nodes with has_committed_hypothesis true."
        ),
    )


class GetNodeReconstructionResult(WorkbenchModel):
    reconstruction: PriorNodeReconstruction
    provenance: Literal["prior_node_hypothesis"] = "prior_node_hypothesis"


class TestSoundLawArgs(WorkbenchModel):
    dsl: NonEmptyStr
    source_child_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)
    concept_ids: tuple[NonEmptyStr, ...] = ()
    segmentation_overlay_id: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> TestSoundLawArgs:
        if len(set(self.source_child_ids)) != len(self.source_child_ids):
            raise ValueError("source_child_ids must be unique")
        return self


class TestSoundLawResult(WorkbenchModel):
    validation_call_id: NonEmptyStr
    parsed_rule: ParsedSoundRule
    source_child_ids: tuple[NonEmptyStr, ...]
    segmentation_overlay_id: NonEmptyStr | None = None
    report: RuleApplicationReport
    supporting_form_ids: tuple[NonEmptyStr, ...]


class CascadeRuleSpec(WorkbenchModel):
    """One rule in an ordered cascade preview.

    A cascade spec carries no validation ID. This call *is* the test, so there
    is nothing to reference yet; per-rule validation_call_id belongs to
    commit_reconstruction, and sending one here is rejected.
    """

    rule_id: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Optional stable label. When omitted, the harness deterministically "
            "derives one from the exact DSL and child scope."
        ),
    )
    dsl: NonEmptyStr = Field(
        description=(
            "One child-to-parent rule in the sound-law DSL, for example "
            "'f > p / #_'. Rules run in the order given."
        ),
    )
    source_child_ids: tuple[NonEmptyStr, ...] = Field(
        min_length=1,
        description=(
            "Active child node IDs this rule is applied to. Only active direct "
            "children of the node being reconstructed are accepted."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def supply_rule_id(cls, value):
        if isinstance(value, dict):
            value = dict(value)
            children = value.get("source_child_ids")
            if isinstance(children, list):
                children = tuple(children)
                value["source_child_ids"] = children
            dsl = value.get("dsl")
            if (
                not value.get("rule_id")
                and isinstance(dsl, str)
                and isinstance(children, tuple)
            ):
                material = dsl.strip() + "\0" + "\0".join(map(str, children))
                value["rule_id"] = (
                    "rule-" + hashlib.sha256(material.encode()).hexdigest()[:12]
                )
        return value

    @model_validator(mode="after")
    def validate_scope(self) -> CascadeRuleSpec:
        if self.rule_id is None:
            raise ValueError("rule_id could not be derived without DSL and child scope")
        if len(set(self.source_child_ids)) != len(self.source_child_ids):
            raise ValueError("cascade source_child_ids must be unique")
        return self


class TestRuleCascadeArgs(WorkbenchModel):
    rules: tuple[CascadeRuleSpec, ...] = Field(min_length=1)
    concept_ids: tuple[NonEmptyStr, ...] = ()
    segmentation_overlay_id: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_rule_ids(self) -> TestRuleCascadeArgs:
        rule_ids = [rule.rule_id for rule in self.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("cascade rule IDs must be unique")
        return self


class CascadeFinalForm(WorkbenchModel):
    child_id: NonEmptyStr
    form: LexicalForm


class ConceptConvergenceReport(WorkbenchModel):
    concept_id: NonEmptyStr
    converged: bool
    parent_forms: tuple[tuple[NonEmptyStr, ...], ...]
    """Distinct parent forms the children produced, sorted. One means agreement."""
    child_count: int = Field(ge=0)


class ChildConvergenceSummary(WorkbenchModel):
    """Did this cascade make the children agree on a parent form?

    Reported, never enforced. A hypothesis under which some children still
    disagree can be entirely legitimate — an unexplained residue is a normal
    state of a comparative argument — so no tool rejects a commit for diverging.
    The model previously had to work this out by eyeballing intermediate forms.
    """

    concepts_evaluated: int = Field(ge=0)
    converged_concepts: int = Field(ge=0)
    child_convergence_rate: float = Field(ge=0.0, le=1.0)
    divergent_concept_ids: tuple[NonEmptyStr, ...] = ()
    """A bounded sample; `concepts_evaluated - converged_concepts` is the count."""
    concepts: tuple[ConceptConvergenceReport, ...] = ()
    """Per-concept detail, omitted on the commit summary to keep the result small."""


class TestRuleCascadeResult(WorkbenchModel):
    validation_call_id: NonEmptyStr
    rules: tuple[ReconstructionRule, ...]
    segmentation_overlay_id: NonEmptyStr | None = None
    reports: tuple[RuleApplicationReport, ...]
    final_forms: tuple[CascadeFinalForm, ...]
    # Defaulted so cascade results recorded before convergence was reported stay
    # loadable inside older trajectories.
    convergence: ChildConvergenceSummary | None = None


class MorphemeSegmentation(WorkbenchModel):
    form_id: NonEmptyStr
    segments: tuple[NonEmptyStr, ...] = Field(min_length=1)


class SegmentMorphemesArgs(WorkbenchModel):
    segmentations: tuple[MorphemeSegmentation, ...] = Field(min_length=1)
    rationale: NonEmptyStr
    base_overlay_id: NonEmptyStr | None = None


class SegmentMorphemesResult(WorkbenchModel):
    segmentation_overlay_id: NonEmptyStr
    forms: tuple[LexicalForm, ...]
    rationale: NonEmptyStr


class ValidationKind(StrEnum):
    """Which kind of same-session call applied a committed rule to real forms.

    Recorded on the committed rule so a trajectory says what backed it. A
    cascade preview is not a weaker record than a standalone test: it applied
    the rule to the same forms *and* in its committed order.
    """

    SOUND_LAW = "test_sound_law"
    RULE_CASCADE = "test_rule_cascade"


class CommittedSoundRule(WorkbenchModel):
    rule_id: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Optional stable label. When omitted, the harness deterministically "
            "derives one from the exact DSL and child scope."
        ),
    )
    dsl: NonEmptyStr = Field(
        description=(
            "The child-to-parent rule text, character-identical to the 'dsl' "
            "argument of the test_sound_law call that validated it, for "
            "example 'f > p / #_'."
        ),
    )
    direction: Literal["child_to_parent"] = Field(
        default="child_to_parent",
        description=(
            "Fixed. Rules are operational child-to-parent transformations; the "
            "harness never inverts a conventional forward historical law."
        ),
    )
    source_child_ids: tuple[NonEmptyStr, ...] = Field(
        min_length=1,
        description=(
            "Active child node IDs this rule is applied to. Must equal the "
            "source_child_ids of the test_sound_law call that validated it."
        ),
    )
    confidence: float = Field(
        gt=0.0,
        le=1.0,
        description=(
            "Your confidence in this rule, in the open-closed interval (0, 1]. "
            "This is your own judgement; the harness cannot derive it. The "
            "deterministic beam uses it as a score weight."
        ),
    )
    validation_call_id: NonEmptyStr | None = Field(
        default=None,
        description=(
            "The validation_call_id of the call that applied this exact rule "
            "to this exact source_child_ids: either a test_sound_law call, or "
            "a test_rule_cascade call whose order contains this rule. "
            "Optional: when omitted the harness resolves it from the "
            "same-session validation whose rule, child scope, and segmentation "
            "overlay are identical to this one. Supply it explicitly only when "
            "several matching validations disagree about which forms the rule "
            "applied to. Setting it here does not make the commit an ordered "
            "cascade; cascade_validation_call_id still means the whole "
            "committed order was previewed."
        ),
    )
    validation_kind: ValidationKind | None = Field(
        default=None,
        description=(
            "Written by the harness, ignored on input: which kind of call the "
            "resolved validation was. Defaulted so records written before it "
            "existed stay loadable."
        ),
    )
    supporting_form_ids: tuple[NonEmptyStr, ...] = Field(
        default=(),
        description=(
            "Exact form IDs this rule applied to. Optional: when omitted it "
            "defaults to the supporting_form_ids reported by the resolved "
            "validation. When supplied it must be a subset of them."
        ),
    )
    rationale: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Rule-specific justification. Optional when the commit carries a "
            "single rule, because the required top-level 'summary' already "
            "states the reasoning for it. Required on every rule of a commit "
            "that carries more than one, since one summary cannot attribute "
            "reasoning to one of several rules."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def supply_rule_id(cls, value):
        if isinstance(value, dict):
            value = dict(value)
            children = value.get("source_child_ids")
            if isinstance(children, list):
                children = tuple(children)
                value["source_child_ids"] = children
            supporting = value.get("supporting_form_ids")
            if isinstance(supporting, list):
                value["supporting_form_ids"] = tuple(supporting)
            dsl = value.get("dsl")
            if (
                not value.get("rule_id")
                and isinstance(dsl, str)
                and isinstance(children, tuple)
            ):
                material = dsl.strip() + "\0" + "\0".join(map(str, children))
                value["rule_id"] = (
                    "rule-" + hashlib.sha256(material.encode()).hexdigest()[:12]
                )
        return value

    @model_validator(mode="after")
    def validate_references(self) -> CommittedSoundRule:
        if self.rule_id is None:
            raise ValueError("rule_id could not be derived without DSL and child scope")
        if len(set(self.source_child_ids)) != len(self.source_child_ids):
            raise ValueError("source_child_ids must be unique")
        if len(set(self.supporting_form_ids)) != len(self.supporting_form_ids):
            raise ValueError("supporting_form_ids must be unique")
        return self


class CommitReconstructionArgs(WorkbenchModel):
    node_id: NonEmptyStr = Field(
        description=(
            "The node_id of the node being reconstructed, exactly as given in "
            "the prompt payload."
        ),
    )
    segmentation_overlay_id: NonEmptyStr | None = Field(
        default=None,
        description=(
            "The segmentation_overlay_id returned by segment_morphemes, when "
            "the committed rules were validated against an overlay. Omit it "
            "when no overlay was used."
        ),
    )
    cascade_validation_call_id: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Only the validation_call_id returned by a successful "
            "test_rule_cascade call. Omit this field if test_rule_cascade was "
            "not called; never use a test_sound_law call ID here. A "
            "test_sound_law ID belongs in the per-rule validation_call_id."
        ),
    )
    rules: tuple[CommittedSoundRule, ...] = Field(
        description=(
            "The ordered rule cascade to commit. Use an empty list for an "
            "identity reconstruction."
        ),
    )
    anomalies: tuple[AnomalyReport, ...] = Field(
        description=(
            "Every unresolved irregularity, each naming a form_id or "
            "concept_id. Use an empty list when none remain."
        ),
    )
    summary: NonEmptyStr = Field(
        description=(
            "A concise statement of the reconstruction and the evidence "
            "supporting it."
        ),
    )

    @model_validator(mode="after")
    def validate_unique_rule_ids(self) -> CommitReconstructionArgs:
        ids = [rule.rule_id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("committed rule IDs must be unique")
        return self


class CommittedReconstruction(WorkbenchModel):
    request: CommitReconstructionArgs
    parsed_rules: tuple[ReconstructionRule, ...]


class CommitReconstructionResult(WorkbenchModel):
    status: Literal["committed"] = "committed"
    reconstruction: CommittedReconstruction
    # The session's last observation should be what its hypothesis actually
    # produced, not just that the commit parsed. Defaulted for older records.
    convergence: ChildConvergenceSummary | None = None


class NodeLexiconSummary(WorkbenchModel):
    node_id: NonEmptyStr
    name: NonEmptyStr
    form_count: int = Field(ge=0)
    concept_count: int = Field(ge=0)


class NodePromptPayload(WorkbenchModel):
    node_id: NonEmptyStr
    active_children: tuple[NodeLexiconSummary, ...] = Field(min_length=2)
    anchor_policy: AnchorPolicy = AnchorPolicy.ADVISORY
    anchors: tuple[LexicalForm, ...] = ()
