"""Strict provider-neutral schemas for the hypothesis-manager layer."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from cognate_reconstruction.schemas.alignment import (
    ComplementaryCandidate,
    CorrespondenceDetail,
    CorrespondenceSet,
    MultipleAlignmentMap,
)
from cognate_reconstruction.schemas.common import NonEmptyStr, WorkbenchModel
from cognate_reconstruction.schemas.inventory import (
    AlignmentOverride,
    AssemblyDetail,
    ColumnResolution,
    CommitProtoInventoryArgs,
    CommittedProtoInventory,
    ConceptAssemblyReport,
    CorrespondenceCommitment,
    ProtoInventorySpec,
    ResidueDisposition,
    ResiduePolicy,
    SegmentRestoration,
    normalize_written_gaps,
)
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


def derive_rule_id(dsl: str, source_child_ids: Sequence[str]) -> str:
    """The stable label a rule gets when the model supplies none.

    Derived from the exact DSL and child scope, so the same rule proposed by
    `test_sound_law`, previewed inside `test_rule_cascade`, and committed all
    carry one ID. That matters now that a rejection can name a `rule_id` the
    model has to find in an earlier tool result: the parser's own fallback is
    derived from the DSL alone, and two rules differing only in scope would
    collide under it.
    """
    material = dsl.strip() + "\0" + "\0".join(map(str, source_child_ids))
    return "rule-" + hashlib.sha256(material.encode()).hexdigest()[:12]


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
    cached_input_tokens: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Prompt tokens the provider served from its cache. A SUBSET of "
            "input_tokens, never an addition to them: the provider counts a "
            "cached token as prompt input and discounts its price. Every call "
            "in a node session repeats one prefix — the agent instructions and "
            "the tool schemas — so a run where this stays null or zero is "
            "paying full price for the same preamble on every turn, which is "
            "worth knowing before a sweep rather than after one. Defaulted, so "
            "records written before it existed read as 'not recorded' rather "
            "than as a run that cached nothing."
        ),
    )
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
    subject: NonEmptyStr | None = Field(
        default=None,
        exclude=True,
        description=(
            "Which items this rejection is about, as a stable digest, when the "
            "check could identify them. Read only by the stall detector, which "
            "counts a repeat only when the same offenders come back. "
            "exclude=True on purpose: it is harness bookkeeping, so it must not "
            "reach the model in the tool result and must not change a "
            "trajectory byte. It is recoverable from 'message', which names the "
            "offenders in full."
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
    alignment_overlay_id: NonEmptyStr | None = Field(
        default=None,
        description=(
            "The alignment_overlay_id returned by realign, to survey the "
            "columns as you re-laid them. It is part of every returned set_id, "
            "so a commit must cite IDs derived under the overlay it names."
        ),
    )
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
    alignment_overlay_id: NonEmptyStr | None = Field(
        default=None,
        description=(
            "The alignment overlay these sets were derived under, if any. It is "
            "part of every set_id, so a set cited under a different overlay is "
            "a set the harness cannot reproduce."
        ),
    )
    complementary_candidates: tuple[ComplementaryCandidate, ...] = Field(
        default=(),
        description=(
            "Pairs of the returned sets whose occurrences never share an "
            "environment, with the tokens observed beside each. A fact about "
            "the distribution, not a proposal: whether the pair is one phoneme "
            "with a conditioned split or simply two phonemes is your judgement, "
            "and you assert it with merges_with_set_id."
        ),
    )
    complementary_candidate_count: int = Field(
        default=0,
        ge=0,
        description=(
            "Complementary pairs found among the returned sets. Larger than the "
            "sample when the list was truncated."
        ),
    )


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


class ColumnPosition(StrEnum):
    """Where in the word a matching alignment column has to sit."""

    ANY = "any"
    INITIAL = "initial"
    FINAL = "final"


class PolarizeArgs(WorkbenchModel):
    """Ask what the rest of the tree shows where the active children disagree.

    Not a prior and not a verdict: this is data retrieval. The evidence that
    settles the direction of a change is already in the payload — every
    observed node outside the active children, plus any node already
    reconstructed in this run — and the deterministic layer has never looked at
    it.

    Give it one correspondence, as `child_ids` plus the segment each of those
    children shows, which is a row of `summarize_correspondences` pasted back —
    including its nulls, since a child that shows nothing in a column is the
    ordinary case this tool is asked about. Naming a single child is legal and
    means "columns where this child shows this segment".
    """

    child_ids: tuple[NonEmptyStr, ...] = Field(
        min_length=1,
        description=(
            "Active children whose segments define the correspondence, in the "
            "order 'correspondence' gives them."
        ),
    )
    correspondence: tuple[NonEmptyStr | None, ...] = Field(
        min_length=1,
        description=(
            "One segment per entry of 'child_ids', positionally. A child that "
            "shows nothing in this column is null — which is what a "
            "summarize_correspondences row carries, so a row can be pasted "
            "back unchanged. 'Ø', '∅', '' and 'null' are accepted and mean the "
            "same as null."
        ),
    )
    concept_ids: tuple[NonEmptyStr, ...] = Field(
        default=(),
        description="Optional narrowing to specific concepts. Omit it to use every concept.",
    )
    node_ids: tuple[NonEmptyStr, ...] = Field(
        default=(),
        description=(
            "Optional narrowing to specific nodes outside the active children. "
            "Omit it to consult every available node."
        ),
    )
    position: ColumnPosition = Field(
        default=ColumnPosition.ANY,
        description=(
            "Restrict to columns that are word-initial or word-final for every "
            "named child, which is how a change conditioned by a word edge is "
            "polarized without pulling alignments."
        ),
    )
    segmentation_overlay_id: NonEmptyStr | None = None
    respect_cognate_sets: bool = True

    @field_validator("correspondence", mode="before")
    @classmethod
    def accept_gap_spellings(cls, value):
        """The same writing vocabulary a commitment's `reflexes` accepts.

        `WRITTEN_GAP_SPELLINGS` and `normalize_written_gaps` are shared with
        `CorrespondenceCommitment` rather than restated, because the model is
        told to paste one row of `summarize_correspondences` from the survey
        into the commitment and the same row into this tool. Two vocabularies
        for one row is the contradiction this removes: a survey row containing
        a gap carries `None`, which the previous `tuple[NonEmptyStr, ...]`
        refused outright — 5 `schema:correspondence[]=string_type` rejections
        on the Polynesian sweep of 2026-08-24 — while the docstring above told
        the model to paste it back.

        A *field* validator rather than the model-level one the two inventory
        models use, for the reason `normalize_written_gaps` documents: a
        `mode="before"` model validator hands every other field on in strict
        python mode, and `child_ids`, `concept_ids` and `node_ids` arrive from
        the tool boundary as JSON lists. Scoping it to the one field it is
        about leaves them alone.
        """
        return normalize_written_gaps(value)

    @model_validator(mode="after")
    def validate_selection(self) -> PolarizeArgs:
        if len(set(self.child_ids)) != len(self.child_ids):
            raise ValueError("polarize child IDs must be unique")
        if len(self.correspondence) != len(self.child_ids):
            raise ValueError(
                "polarize needs exactly one segment per child: "
                f"{len(self.child_ids)} child_ids against "
                f"{len(self.correspondence)} correspondence entries"
            )
        if len(set(self.node_ids)) != len(self.node_ids):
            raise ValueError("polarize node IDs must be unique")
        if len(set(self.concept_ids)) != len(self.concept_ids):
            raise ValueError("polarize concept IDs must be unique")
        return self


class PolarizeSegmentObservation(WorkbenchModel):
    """What one node shows in the matched columns, and how often."""

    segment: str | None = Field(
        description="The aligned segment, or null for an alignment gap."
    )
    count: int = Field(ge=1, description="Matched columns in which it appears.")
    example_concept_ids: tuple[NonEmptyStr, ...] = ()


class PolarizeNodeReport(WorkbenchModel):
    """One node outside the active children, and what it shows."""

    node_id: NonEmptyStr
    relation: EvidenceRelation = Field(
        description=(
            "'outgroup' lies outside this node's subtree and can therefore "
            "witness a state predating the split. 'descendant' lies inside it "
            "and cannot."
        ),
    )
    kind: EvidenceKind
    is_attestation: bool = Field(
        description=(
            "False for a reconstructed node. A reconstructed form is a prior "
            "hypothesis from another session, carries no independent evidential "
            "weight, and must not be cited as support."
        ),
    )
    descendant_leaf_ids: tuple[NonEmptyStr, ...] = Field(
        default=(),
        description=(
            "The leaves this node covers, so several nodes belonging to one "
            "clade can be recognised as one witness rather than counted "
            "separately."
        ),
    )
    columns_covered: int = Field(
        ge=0,
        description="Matched columns in which this node attests the concept at all.",
    )
    observations: tuple[PolarizeSegmentObservation, ...] = ()


class PolarizeCandidateSummary(WorkbenchModel):
    """One of the competing segments, and which outside nodes show it.

    Presence only. A node that lacks the segment is not listed as evidence
    against it: lacking a segment is equally consistent with never having had it
    and with having lost it, while showing it puts the segment outside the node
    under study.
    """

    segment: NonEmptyStr
    observed_node_ids: tuple[NonEmptyStr, ...] = ()
    reconstructed_node_ids: tuple[NonEmptyStr, ...] = ()


class PolarizeResult(WorkbenchModel):
    """A distributional summary, deliberately without a verdict.

    Nothing here says which value is original. That judgement is yours, it
    depends on how the change would have to have run, and the place it is
    recorded is the committed rule's `directionality_rationale`.

    Two limits this cannot report around. The argument inherits the supplied
    classification: it is only as good as the tree, and it is circular if the
    tree was induced from the same distance data. And **the root has no
    out-group** — nothing lies outside it — so the technique is unavailable
    exactly where the reported reconstruction is made.

    That second limit does not show up as an empty `nodes` list. At the root
    every available node is a `descendant`: it lies inside this node's subtree
    and shows what these children became, which is the proposition under test
    rather than evidence about it. Read `relation` on every entry, and read
    `note`, which counts out-groups and descendants separately for this reason.
    """

    child_ids: tuple[NonEmptyStr, ...]
    correspondence: tuple[NonEmptyStr | None, ...] = Field(
        description=(
            "The correspondence as the harness read it, with every accepted "
            "gap spelling normalized to null. Echoed so a request written with "
            "'Ø' and one written with null are visibly the same request."
        ),
    )
    columns_matched: int = Field(
        ge=0,
        description="Aligned columns in which the named children show this correspondence.",
    )
    matched_concept_count: int = Field(ge=0)
    matched_concept_ids: tuple[NonEmptyStr, ...] = Field(
        default=(),
        description="A bounded sample; 'matched_concept_count' is authoritative.",
    )
    nodes: tuple[PolarizeNodeReport, ...] = ()
    candidates: tuple[PolarizeCandidateSummary, ...] = ()
    segmentation_overlay_id: NonEmptyStr | None = None
    note: NonEmptyStr = Field(
        description="The same counts in one deterministic sentence, with no verdict."
    )


MAX_POLARIZE_EXAMPLE_CONCEPTS = 12
"""Matched concept IDs echoed on a polarize result before truncation."""


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


class PriorCommittedSet(WorkbenchModel):
    """One correspondence set from an already-completed node, read-only.

    `set_id` is deliberately stripped. A set ID is derived from a reflex tuple
    over *that* node's children under *that* node's overlays, so it is
    meaningless anywhere else and citing one here would be citing a set this
    node's data cannot reproduce.
    """

    reflexes: tuple[str | None, ...] = Field(min_length=2)
    proto_segment: NonEmptyStr | None = None
    support: int = Field(ge=1)
    confidence: float = Field(gt=0.0, le=1.0)


class PriorNodeInventory(WorkbenchModel):
    """The inventory committed at one already-reconstructed node.

    Mirrors `PriorNodeReconstruction` and carries the same framing: a prior
    node's inventory is another session's hypothesis, carries no independent
    evidential weight, and must never appear as support for a commitment here.
    It carries `child_node_ids` beside the reflex tuples because without them
    another node cannot interpret a single column.
    """

    node_id: NonEmptyStr
    child_node_ids: tuple[NonEmptyStr, ...] = Field(min_length=2)
    proto_phonemes: tuple[NonEmptyStr, ...] = ()
    sets: tuple[PriorCommittedSet, ...] = ()
    derived_rules: tuple[PriorCommittedRule, ...] = ()
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
    reconstruction: PriorNodeReconstruction | None = None
    """The prior node's rules, when it committed under the branch-cascade shape."""
    inventory: PriorNodeInventory | None = None
    """The prior node's inventory, when it committed under the per-set shape.

    Exactly one of the two is present. Both shapes stay readable during the
    migration, because a run walks nodes committed under whichever protocol was
    current when each of them ran.
    """
    provenance: Literal["prior_node_hypothesis"] = "prior_node_hypothesis"

    @model_validator(mode="after")
    def validate_one_shape(self) -> GetNodeReconstructionResult:
        if (self.reconstruction is None) == (self.inventory is None):
            raise ValueError(
                "a prior node hypothesis is either a rule set or an inventory"
            )
        return self


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


MAX_REPORTED_HELD_OUT_CONCEPTS = 12
"""Held-out concept IDs echoed in a tool result before the list is truncated.

The full list is already in the prompt payload, so this is a reminder rather
than the record; the counts beside it are authoritative.
"""


class HeldOutEvaluation(WorkbenchModel):
    """What a hypothesis does on the concepts this node held out.

    The node's concepts are split once, deterministically, from the node ID;
    see `agent/holdout.py`. The rest of a rule report is computed over the
    concepts the session selected, which is exactly the evidence a rule was
    fitted to — so a rule generalized from one word scores perfectly there and
    says nothing. This block is the same rule measured somewhere it was not
    fitted.

    Nothing here rejects. A rule that applies to no held-out form may be
    perfectly correct and narrowly conditioned; a low held-out convergence rate
    may be an honest residue. It is a report, and a poor one is meant to
    *look* poor rather than to be forbidden.

    Anchors are deliberately not applied, exactly as in the commit-time
    convergence summary: this measures the rules against the children's own
    forms.
    """

    concept_count: int = Field(
        ge=0,
        description="Held-out concepts at this node, whatever the call's scope.",
    )
    concepts_evaluated: int = Field(
        ge=0,
        description="Held-out concepts at least one active child attests.",
    )
    forms_evaluated: int = Field(ge=0)
    applications: int = Field(
        ge=0,
        description="Rule results that changed a held-out form.",
    )
    target_absent: int = Field(ge=0)
    context_mismatches: int = Field(
        ge=0,
        description=(
            "Held-out forms containing the target but never in the rule's "
            "environment. A rule conditioned to fit the development set shows "
            "up here."
        ),
    )
    convergence: ChildConvergenceSummary | None = None
    """Whether the children agree on a parent over the held-out concepts alone."""
    held_out_concept_ids: tuple[NonEmptyStr, ...] = ()
    """A bounded sample; `concept_count` is authoritative."""


MAX_REPORTED_ATTESTING_NODES = 10
"""Attesting node IDs listed on a contrast report before the list is truncated."""


class ContrastReductionReport(WorkbenchModel):
    """A rule that removes a distinction, and who else still shows it.

    Detected mechanically by applying the rule to the forms it is scoped to and
    asking whether the induced mapping deletes material or sends two distinct
    inputs to one output. Both are arithmetic over the forms and carry no
    linguistic claim; see `rules/contrast.py`.

    The attestation counts are a count over the available evidence, not an
    argument: "this rule removes `ʔ`, attested in 3 of 10 available nodes" says
    what the tree still shows, and says nothing about whether the parent had it.
    Reconstructed nodes are counted separately because a reconstructed form is a
    prior hypothesis, not attestation.

    A rule reported here requires a `directionality_rationale` when it is
    committed. Nothing here rejects on its own: contrast loss is ordinary sound
    change, and a harness that forbade it would be wrong.
    """

    rule_id: NonEmptyStr
    dsl: NonEmptyStr
    source_child_ids: tuple[NonEmptyStr, ...]
    deletes: bool = Field(
        description="The rule's replacement is empty, so it removes material."
    )
    merges: bool = Field(
        description=(
            "Two distinct segment sequences in the scoped children end up as "
            "one, so a contrast those children make is gone from the parent."
        ),
    )
    discarded_segments: tuple[NonEmptyStr, ...] = Field(
        description="The rule's target: the material that stops surfacing."
    )
    merged_into: tuple[NonEmptyStr, ...] = Field(
        default=(),
        description="What the target became, empty for a deletion.",
    )
    attesting_node_ids: tuple[NonEmptyStr, ...] = Field(
        default=(),
        description=(
            "Available nodes whose forms still contain the discarded material. "
            "A bounded sample; the counts are authoritative."
        ),
    )
    attesting_node_count: int = Field(ge=0)
    observed_attesting_node_count: int = Field(
        ge=0,
        description=(
            "Of those, the nodes that are observed rather than reconstructed. "
            "Only these are attestation."
        ),
    )
    available_node_count: int = Field(ge=0)
    note: NonEmptyStr = Field(
        description="The same counts in one deterministic sentence."
    )


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
    # Both defaulted so validations recorded before these existed stay loadable
    # inside older trajectories.
    contrast_reduction: ContrastReductionReport | None = None
    """Set when this rule deletes or merges a distinction the children make."""
    held_out: HeldOutEvaluation | None = None
    """The same rule on the concepts this node held out, whatever was selected."""


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
                value["rule_id"] = derive_rule_id(dsl, children)
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


class TestRuleCascadeResult(WorkbenchModel):
    validation_call_id: NonEmptyStr
    rules: tuple[ReconstructionRule, ...]
    segmentation_overlay_id: NonEmptyStr | None = None
    reports: tuple[RuleApplicationReport, ...]
    final_forms: tuple[CascadeFinalForm, ...]
    # Defaulted so cascade results recorded before convergence was reported stay
    # loadable inside older trajectories.
    convergence: ChildConvergenceSummary | None = None
    contrast_reductions: tuple[ContrastReductionReport, ...] = ()
    """Rules of this order that delete or merge a distinction, in order.

    Each one will need a `directionality_rationale` when it is committed.
    """
    held_out: HeldOutEvaluation | None = None


class TestProtoAssemblyArgs(WorkbenchModel):
    """Preview what a proposed inventory assembles, before committing it."""

    commitments: tuple[CorrespondenceCommitment, ...] = Field(
        description=(
            "The correspondence-set commitments to preview. Order carries no "
            "meaning. An empty list previews the identity reconstruction an "
            "empty inventory commits."
        ),
    )
    restorations: tuple[SegmentRestoration, ...] = ()
    residue_policy: ResiduePolicy = Field(
        description=(
            "What happens to a column no committed set explains. Required, with "
            "no default, exactly as at commit time — previewing under a "
            "different policy from the one you commit would preview a different "
            "reconstruction."
        ),
    )
    residue_witness_child_id: NonEmptyStr | None = None
    residue_dispositions: tuple[ResidueDisposition, ...] = ()
    concept_ids: tuple[NonEmptyStr, ...] = Field(
        default=(),
        description=(
            "Concepts to assemble; empty previews every concept at this node. "
            "Coverage for a commit is over *sets*, not concepts, so batching a "
            "large family across several calls is fine — their coverage unions."
        ),
    )
    segmentation_overlay_id: NonEmptyStr | None = None
    alignment_overlay_id: NonEmptyStr | None = None
    detail: AssemblyDetail = Field(
        default=AssemblyDetail.SUMMARY,
        description=(
            "'summary' (the default) returns the assembled forms and the "
            "per-concept counts; 'full' adds the per-column resolutions, which "
            "is what to read when a form came out wrong and you need to see "
            "which column did it."
        ),
    )


class TestProtoAssemblyResult(WorkbenchModel):
    """What a proposed inventory assembles, split at the compaction line.

    Everything above `concepts` is what a commit is checked against and must
    survive for the whole session: a few hundred bytes. Everything below is
    re-derivable by calling this tool again, which is exactly the test
    `COMPACTABLE_TOOL_NAMES` applies.

    That split has to be the shape from the first version, because a result
    schema is recorded in trajectories the moment the tool ships.
    `test_rule_cascade` is the cautionary tale and the resemblance is
    uncomfortable — both are the call that validates a commit, both carry an ID
    that cannot be re-derived — and it measured 399 KB across three calls at one
    live node against 22 KB for all the evidence that node inspected.
    """

    # --- the part a commit is checked against; never compactable, tiny ---
    validation_call_id: NonEmptyStr
    covered_set_ids: tuple[NonEmptyStr, ...] = ()
    unaccounted_column_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    cross_branch_assembly_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    ambiguous_columns: tuple[ColumnResolution, ...] = Field(
        default=(),
        description=(
            "Columns more than one committed set matched. Disambiguate them by "
            "conditioning one of the sets, by splitting a set, or by saying in "
            "your summary that the evidence does not decide; otherwise the beam "
            "picks by mass and then by an arbitrary segment order."
        ),
    )
    assembled_concept_count: int = Field(default=0, ge=0)
    segmentation_overlay_id: NonEmptyStr | None = None
    alignment_overlay_id: NonEmptyStr | None = None
    residue_policy: ResiduePolicy | None = None
    # --- the bulky, re-derivable part ---
    concepts: tuple[ConceptAssemblyReport, ...] = ()
    derived_rules: tuple[ReconstructionRule, ...] = ()
    non_invertible_child_ids: tuple[NonEmptyStr, ...] = ()
    """Children some committed set assigns a gap against a reconstructed segment.

    Not an error. It is the insertion the DSL cannot write, recorded rather than
    rejected: the parent segment comes from the set, so the form assembles
    anyway and only the *derived view* for that child cannot be spelled.
    """
    unconditioned_context_child_ids: tuple[NonEmptyStr, ...] = ()
    """Children whose derived rule lost its conditioning environment."""
    boundary_change_child_ids: tuple[NonEmptyStr, ...] = ()
    """Children a committed set makes rewrite a morphological boundary.

    Also not an error, and the same shape as the two above: the form assembles
    from its columns either way, and it is only the derived per-branch cascade
    that cannot spell the change, because `+` and `-` are refused as rule
    targets and as insertions on purpose.
    """


class RealignArgs(WorkbenchModel):
    """Re-lay the aligner's columns for concepts it got wrong.

    For the case where SCA has misaligned a form — a compound against a simplex,
    two lexemes in one concept — and not a routine step. The default is to
    accept the aligner's output.
    """

    overrides: tuple[AlignmentOverride, ...] = Field(min_length=1)
    base_alignment_overlay_id: NonEmptyStr | None = None
    segmentation_overlay_id: NonEmptyStr | None = None
    rationale: NonEmptyStr


class RealignResult(WorkbenchModel):
    alignment_overlay_id: NonEmptyStr
    joined_set_support_delta: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Per named joins_set_id, how much support it actually gained. The "
            "claim is verified: a realignment whose named set does not gain the "
            "columns claimed for it is refused."
        ),
    )
    invalidated_set_ids: tuple[NonEmptyStr, ...] = Field(
        default=(),
        description=(
            "Set IDs derived under the previous alignment overlay that no "
            "longer exist. A realignment changes which columns exist, so it "
            "changes what a set is; cite IDs from a survey taken under the new "
            "overlay."
        ),
    )
    override_concept_count: int = Field(default=0, ge=0)
    node_concept_count: int = Field(default=0, ge=0)
    new_set_override_count: int = Field(
        default=0,
        ge=0,
        description=(
            "Overrides that named no set to join. Legal — the first attestation "
            "of a real correspondence has to be expressible — and counted "
            "separately, because it is the mode that bypasses the join check."
        ),
    )
    advisory: NonEmptyStr
    """How much of this node now carries an override. Never a refusal.

    Modelled on `contrast_reduction`: this is legitimate, common, and worth your
    attention before you commit. A session realigning a large share of its
    concepts is fitting the evidence rather than reading it.
    """


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
    directionality_rationale: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Which branch innovated, and why you believe it. Required on any "
            "rule that deletes a segment or merges two segments into one — the "
            "harness detects those mechanically and names the exact rule_ids "
            "when it rejects a commit for omitting this. Say which of the "
            "children changed, what the change is called if it has a name, and "
            "what evidence outside those children polarizes it. The harness "
            "never judges what you write; it only records that you wrote it, "
            "because a merger is not reversible and nothing downstream can "
            "recover the reasoning afterwards."
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
                value["rule_id"] = derive_rule_id(dsl, children)
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
        default=(),
        description=(
            "The ordered rule cascade to commit, under the branch-cascade "
            "protocol. Mutually exclusive with 'inventory'; a call carrying "
            "both is refused. Omit both for an identity reconstruction."
        ),
    )
    inventory: ProtoInventorySpec | None = Field(
        default=None,
        description=(
            "The proto-inventory to commit, under the per-correspondence-set "
            "protocol: a value for each correspondence set, plus the policy for "
            "columns no set explains. Mutually exclusive with 'rules'."
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
        if self.rules and self.inventory is not None:
            raise ValueError(
                "a commit carries either 'rules' or 'inventory', never both: "
                "they are two protocols for the same claim and the harness "
                "cannot tell which one you meant"
            )
        if self.inventory is not None and self.cascade_validation_call_id is not None:
            raise ValueError(
                "cascade_validation_call_id has no meaning for an inventory "
                "commit: correspondence sets are independent and there is no "
                "order to preview"
            )
        return self


class CommittedReconstruction(WorkbenchModel):
    commit_shape: Literal["rules"] = "rules"
    """Which protocol this commit was made under.

    Defaulted, so every record written before the per-set protocol existed reads
    as what it is. It is what lets a reader of a mixed archive branch without
    probing which request shape is present.
    """
    request: CommitReconstructionArgs
    parsed_rules: tuple[ReconstructionRule, ...]

    @property
    def identity_reconstruction(self) -> bool:
        return not self.parsed_rules

    @property
    def anomalies(self) -> tuple[AnomalyReport, ...]:
        return self.request.anomalies


CommittedHypothesis = CommittedReconstruction | CommittedProtoInventory
"""What a node committed, under either protocol.

A plain union rather than a tagged one, deliberately. A discriminated union
requires its tag in the input, and every 2.0 record on disk was written before
`commit_shape` existed — tagging would make the whole existing archive
unloadable to buy a dispatch the two shapes' disjoint required fields already
give unambiguously. `CommittedReconstruction` is first so an old record matches
first.
"""


class CommitReconstructionResult(WorkbenchModel):
    status: Literal["committed"] = "committed"
    reconstruction: CommittedHypothesis
    # The session's last observation should be what its hypothesis actually
    # produced, not just that the commit parsed. Defaulted for older records.
    convergence: ChildConvergenceSummary | None = None
    """Did the children agree, under a committed cascade?

    `None` on an inventory commit, and not because it was not computed: one
    candidate tuple assembles into exactly one parent form, so branch divergence
    about the parent is structurally impossible and the measure has no subject.
    `assembly` carries what replaced it.
    """
    contrast_reductions: tuple[ContrastReductionReport, ...] = ()
    """What this commit gave up, and how much of the tree still shows it."""
    held_out: HeldOutEvaluation | None = None
    """The committed cascade on the concepts the node held out."""
    assembly: TestProtoAssemblyResult | None = None
    """What the committed inventory assembles, over every concept at this node.

    Recomputed from the commit rather than lifted out of the preview: a preview
    may have been scoped to a subset of concepts, and the last thing a session
    sees should be what its hypothesis produced over the whole node.
    """
    held_out_unaccounted_column_rate: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "The committed inventory on the concepts this node withheld: the "
            "share of *their* columns no committed set explains. Reported, "
            "never enforced — an inventory fitted to five concepts is meant to "
            "look poor here, not to be forbidden."
        ),
    )


class NodeLexiconSummary(WorkbenchModel):
    node_id: NonEmptyStr
    name: NonEmptyStr
    form_count: int = Field(ge=0)
    concept_count: int = Field(ge=0)


class ConceptHoldout(WorkbenchModel):
    """This node's concepts, split once and reproducibly.

    Shown rather than hidden. The split is a discipline device, not an
    adversarial test set: inspecting a held-out concept is comparative work, not
    cheating, and a split the session could not see would only produce a number
    it could not act on. What it buys is that every rule report carries a second
    column measured somewhere the rule was not fitted.
    """

    development_concept_ids: tuple[NonEmptyStr, ...] = ()
    held_out_concept_ids: tuple[NonEmptyStr, ...] = ()
    held_out_share: float = Field(default=0.0, ge=0.0, lt=1.0)


class NodePromptPayload(WorkbenchModel):
    node_id: NonEmptyStr
    active_children: tuple[NodeLexiconSummary, ...] = Field(min_length=2)
    anchor_policy: AnchorPolicy = AnchorPolicy.ADVISORY
    anchors: tuple[LexicalForm, ...] = ()
    # Both defaulted so payloads stored in trajectories written before they
    # existed stay loadable.
    concept_holdout: ConceptHoldout | None = None
    commit_requirements: tuple[NonEmptyStr, ...] = Field(
        default=(),
        description=(
            "Requirements the harness enforces at commit time, stated before "
            "the session starts rather than discovered through a rejection."
        ),
    )


COMMIT_REQUIREMENT_NOTES: tuple[str, ...] = (
    "This node's hypothesis is committed as an 'inventory' — one proto_segment "
    "per correspondence set, plus the residue_policy for columns no set "
    "explains — or as a 'rules' cascade. Never both; a call carrying both is "
    "refused. Prefer the inventory: a rule rewrites one child's own segments, "
    "so a parent segment no single child preserves cannot be produced by any "
    "cascade.",
    "Every commitment copies back the set_id, the reflexes and the support "
    "exactly as the harness reported them. The inventory is re-derived from "
    "this node's own forms at commit time: a set the data does not contain is "
    "refused as 'unknown-correspondence-set', and an altered support as "
    "'correspondence-support-mismatch'. Support is the one number separating a "
    "correspondence from residue and it is never a model claim. A realign "
    "invalidates every set_id derived under the previous alignment.",
    "Every committed correspondence set needs a successful same-session "
    "test_proto_assembly covering it. Coverage is over sets rather than "
    "concepts, so several previews over different concept batches union; the "
    "assembly_validation_call_id may be omitted and resolved from them.",
    "Three fields of a commitment are required and are the ones most often "
    "omitted. 'reflexes' carries one entry per active child in order, "
    "including the children showing nothing, written as null: a set only one "
    "child attests is ['ʔ', null] and never ['ʔ']. 'proto_segment' has no "
    "default and must be present even when the value is null, because "
    "'reconstructs nothing' and 'not stated' are different claims. "
    "'confidence' has no default either and belongs on every commitment, not "
    "only the ones you are unsure of; the assembler scores candidates by it, "
    "so there is no value it could safely assume for a set you left it off.",
    "An inventory carrying more than one commitment needs a 'rationale' on "
    "every one of them; the top-level summary cannot attribute reasoning to an "
    "individual set. A one-set inventory needs none. The same asymmetry "
    "applies to a rules commit.",
    "Every non-empty committed rule, under the 'rules' shape, needs a "
    "successful same-session test_sound_law call or test_rule_cascade preview "
    "of the identical rule, child scope, and segmentation overlay.",
    "Anything that discards material needs a 'directionality_rationale' naming "
    "which branch innovated and why: under 'inventory', a non-null reflex "
    "against a null proto_segment, or two sets sharing one proto_segment "
    "without complementary conditioning; under 'rules', a rule that deletes a "
    "segment or merges two into one. The harness detects those mechanically "
    "and rejects a commit that omits it, naming the exact sets or rule_ids; it "
    "never judges what the rationale says.",
    "Reconstructing the value that neutralises a contrast the family still "
    "shows is almost always the wrong direction. Call polarize before "
    "committing any value the children alone do not force.",
    "This node's concepts are split into a development set and a held-out set. "
    "Every report carries a held-out summary; it is reported, never enforced.",
)
"""What a session is told about the commit contract before it starts.

A requirement that lives only in code is one the model discovers by being
rejected, which costs a turn and teaches the wrong lesson — that the harness is
capricious rather than that the claim needs stating. These sentences duplicate
`agent/system_prompt.md` on purpose: the system prompt is the manual and this is the checklist
attached to the specific node.

**Both commit shapes are covered because both are accepted.** Through stages 2
and 3 of `docs/proto_inventory_design.md` a session may commit either, and a
checklist naming only one would be a rejection waiting to happen for the other.
The note that says which to prefer comes first for the same reason the manual
says it early: a session that reaches for the cascade because nothing told it
otherwise has already chosen.
"""
