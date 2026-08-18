"""Serializable reconstruction-step and traversal state."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from cognate_reconstruction.schemas.alignment import CorrespondenceMap
from cognate_reconstruction.schemas.beam import NodeBeamState
from cognate_reconstruction.schemas.common import NonEmptyStr, WorkbenchModel
from cognate_reconstruction.schemas.lexicon import ConceptMetadata, LanguageLexicon
from cognate_reconstruction.schemas.rules import AnomalyReport, RuleApplicationReport


class EvidenceKind(StrEnum):
    OBSERVED = "observed"
    RECONSTRUCTED = "reconstructed"


class EvidenceRelation(StrEnum):
    ACTIVE_CHILD = "active_child"
    DESCENDANT = "descendant"
    OUTGROUP = "outgroup"


class NodeEvidence(WorkbenchModel):
    node_id: NonEmptyStr
    kind: EvidenceKind
    relation: EvidenceRelation
    lexicon: LanguageLexicon
    descendant_leaf_ids: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def validate_identity(self) -> NodeEvidence:
        if self.lexicon.variety_id != self.node_id:
            raise ValueError("evidence node and lexicon IDs must match")
        return self


class NodeReconstructionContext(WorkbenchModel):
    parent_node_id: NonEmptyStr
    active_child_ids: tuple[NonEmptyStr, ...]
    available_nodes: tuple[NodeEvidence, ...]
    concepts: tuple[ConceptMetadata, ...] = ()

    @model_validator(mode="after")
    def validate_context(self) -> NodeReconstructionContext:
        if len(self.active_child_ids) < 2:
            raise ValueError("reconstruction context requires at least two active children")
        if len(set(self.active_child_ids)) != len(self.active_child_ids):
            raise ValueError("active child IDs must be unique")
        node_ids = [node.node_id for node in self.available_nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("available evidence node IDs must be unique")
        concept_ids = [concept.concept_id for concept in self.concepts]
        if len(concept_ids) != len(set(concept_ids)):
            raise ValueError("context concept metadata IDs must be unique")
        return self


class ReconstructionStep(WorkbenchModel):
    parent_node_id: NonEmptyStr
    child_node_ids: tuple[NonEmptyStr, ...]
    input_beams: tuple[NodeBeamState, ...]
    correspondence_maps: tuple[CorrespondenceMap, ...] = ()
    output_beam: NodeBeamState
    rule_reports: tuple[RuleApplicationReport, ...] = ()
    anomaly_reports: tuple[AnomalyReport, ...] = ()
    diagnostics: ReconstructionDiagnostics


class ReconstructionDiagnostics(WorkbenchModel):
    """Transparent mechanical diagnostics, not a linguistic-correctness score."""

    rule_count: int = Field(ge=0)
    rule_complexity_cost: int = Field(ge=0)
    rule_results_evaluated: int = Field(ge=0)
    successful_applications: int = Field(ge=0)
    target_absent: int = Field(ge=0)
    context_mismatches: int = Field(ge=0)
    anchor_mismatches: int = Field(ge=0)
    # Defaulted for append-only readability of diagnostics written before the
    # coverage denominator was made explicit.
    applicable_rule_results: int = Field(default=0, ge=0)
    rule_coverage: float = Field(ge=0.0, le=1.0)
    """Applied share of the results a rule could have changed.

    The denominator is `applicable_rule_results`: evaluated results whose form
    actually contains the rule's target. An in-scope child that never shows the
    target is vacuous for that rule, not a failure of it, so counting it would
    make coverage a measure of scoping convention rather than of the rule.
    `target_absent` stays visible as its own raw count.
    """
    anomaly_count: int = Field(ge=0)
    anomaly_rate: float = Field(ge=0.0)
    identity_reconstruction: bool
    # Convergence. Every counter above measures the *rules*; these measure
    # whether the children ended up agreeing on a parent, which is the only
    # thing a reconstruction is for. All are `None`-defaulted so steps written
    # before they existed stay loadable and read as "not recorded" rather than
    # as a node on which no child ever disagreed.
    #
    # Divergence is scored and reported, never rejected: a linguist may commit a
    # hypothesis under which some children disagree. See
    # `docs/report_reject_or_score.md`.
    child_convergence_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    """Share of concepts on which every attesting active child produced one form.

    Each child contributes its highest-scoring candidate, transformed by its own
    scoped cascade. A concept only one child attests counts as converged — there
    is no second branch to disagree with it — so this measures agreement and not
    coverage. `mean_branch_support` is the number that separates "all five
    children said this" from "one child said this and the rest were silent".
    """
    divergent_concept_count: int | None = Field(default=None, ge=0)
    divergent_concept_ids: tuple[NonEmptyStr, ...] = ()
    """A bounded sample of the divergent concepts; the count is authoritative.

    Truncated at `traversal.convergence.MAX_REPORTED_DIVERGENT_CONCEPTS` so a
    node over a large lexicon cannot put hundreds of IDs in every artifact.
    """
    mean_branch_support: float | None = Field(default=None, ge=0.0, le=1.0)
    """Mean share of the node's active children standing behind the winning form.

    Averaged over concepts, of the active children whose scoped cascade produced
    the top-scoring parent candidate, divided by *all* active children of the
    node rather than by the ones attesting the concept. A concept attested by one
    of five children therefore scores 0.2 even though it converged trivially.
    """
    concepts_inspected: int | None = Field(default=None, ge=0)
    """Concepts the session actually looked at, by ID named in a tool argument.

    Known only to the agent layer and plumbed in, because a commit over 46
    concepts made after inspecting 5 of them is a different object from one made
    after inspecting all 46, and nothing recorded the difference.
    """
    concepts_available: int | None = Field(default=None, ge=0)
    tie_broken_concept_count: int | None = Field(default=None, ge=0)
    """Reported forms chosen by `traversal.beam.TIE_BREAK_POLICY`, not by mass.

    A tie means the evidence did not separate the top two candidates and segment
    order picked the winner. That is a legitimate outcome, and it was previously
    invisible: the beam prints the same two probabilities whether one form won on
    support or on the order of its first differing segment. Counting them lets a
    reader tell how much of a node's output is arbitrary.
    """


class TraversalSnapshot(WorkbenchModel):
    root_node_id: NonEmptyStr
    completed_node_ids: tuple[NonEmptyStr, ...]
    node_beams: tuple[NodeBeamState, ...]
    steps: tuple[ReconstructionStep, ...]
