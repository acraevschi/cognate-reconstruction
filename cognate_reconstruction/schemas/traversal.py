"""Serializable reconstruction-step and traversal state."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from cognate_reconstruction.schemas.alignment import CorrespondenceMap
from cognate_reconstruction.schemas.beam import NodeBeamState
from cognate_reconstruction.schemas.common import NonEmptyStr, WorkbenchModel
from cognate_reconstruction.schemas.inventory import ConceptAssemblyReport
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
    """Per-rule diffs from a branch-cascade commit; empty on an inventory step.

    Kept and left empty rather than removed. It is serialized into every
    existing `result.json` and `checkpoint.json`, so removing it would make
    those unloadable under `extra="forbid"` for no gain — the same argument that
    kept `tool_failures_by_type` under a name that no longer describes it. A
    reader tells the two commit shapes apart by which of this and
    `assembly_reports` is populated.
    """
    assembly_reports: tuple[ConceptAssemblyReport, ...] = ()
    """Per concept, what the assembler did; empty on a branch-cascade step.

    The compact rendering — set IDs per column, the assembled form, the
    unaccounted count — never the alignment rows. The `correspondence_maps`
    measurement is the precedent and the warning: 448 KB of a 10,017 KB result
    for something no reader had asked for.
    """
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
    contrast_reducing_rule_count: int | None = Field(default=None, ge=0)
    """Committed rules that delete a segment or merge two into one.

    The counterweight to `rule_coverage`, printed beside it. Coverage rises when
    rules fire, and the cheapest way to make rules fire is to delete a
    distinction — so a node that scored high coverage by discarding contrasts
    would otherwise read as the best node in the run. This says how much of that
    coverage was bought that way.

    It is a count, not a verdict. Contrast loss is ordinary sound change and
    nothing rejects on it; what the commit contract requires is that each such
    rule carries a `directionality_rationale` saying which branch innovated. See
    `rules/contrast.py` for the detection and
    `docs/report_reject_or_score.md` for why it is reported rather than scored.
    `None` means the step predates the counter, not that no rule reduced a
    contrast.
    """
    correspondence_map_failure: NonEmptyStr | None = None
    """Why `correspondence_maps` is empty, when the aligner refused the node.

    `None` means nothing was refused. It does *not* mean maps were built: an
    empty tuple is also what a node with fewer than two child lexicons, or with
    no evidence context, has always produced.

    The field exists so a degraded step is visibly different from a clean one.
    `correspondence_maps` is a report and nothing scores it, so a node whose
    alignment failed keeps running with an empty report — but a reader must be
    able to tell that the report is empty *because the aligner refused*, not
    because there was nothing to align. Defaulted to `None` so steps written
    before the field stay loadable.
    """
    identity_reconstruction: bool
    # Defaulted false so every step written before node-failure fallback
    # existed reads as what it was: a node that actually ran.
    failure_fallback: bool = False
    """This node's session failed and the harness committed identity for it.

    Not a linguistic claim, and deliberately *not* `identity_reconstruction`,
    which says a session inspected the evidence and concluded that the parent
    equals its children. Both are true of a fallback step — no rule was
    applied — and only this one says no reconstruction was ever proposed. It
    exists so a run with two dead nodes cannot read as a run with seven
    reconstructions.
    """
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
    # Proto-inventory assembly. Every counter below is `None` on a step built
    # from a branch-cascade commit and on every step written before the protocol
    # existed, so absence reads as "this node did not assemble" rather than as a
    # node that assembled nothing. All are reports: none filters a trajectory,
    # weights a candidate, or decides whether a run was valid. See
    # `docs/report_reject_or_score.md`.
    committed_set_count: int | None = Field(default=None, ge=0)
    """Correspondence sets the committed inventory carries."""
    proto_phoneme_count: int | None = Field(default=None, ge=0)
    """Distinct proto-phonemes reconstructed at this node.

    The first-class object the whole protocol exists to produce. Deliberately
    never scored: "is this inventory typologically credible?" would need typology
    data this repository does not hold, would fire on correct runs — Proto-
    Polynesian's inventory is unusual and correct — and the moment it reached
    `high_quality` it would define "typologically ordinary" as "valid".
    """
    assembled_column_count: int | None = Field(default=None, ge=0)
    """Alignment columns the assembly resolved, over every concept."""
    unaccounted_column_count: int | None = Field(default=None, ge=0)
    unaccounted_column_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    """Share of columns resolved by `residue_policy` rather than by a set.

    What replaces `rule_coverage`, and a better shape: coverage is now over
    alignment columns rather than over (rule × in-scope child) pairs, so the
    scoping defect — `f > p / #_` scoped to three children scoring 0.33 against
    the identical reconstruction scoped to one scoring 1.0 — cannot recur. A
    column is explained or it is not, and how many children the set names does
    not enter the fraction.

    Nothing rejects on the rate. Under `min_support = 2` on Polynesian 175 of
    216 sets are singletons; a node whose residue rate is high may be a node
    looking honestly at a messy lexicon.
    """
    cross_branch_assembly_rate: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    """Share of concepts no single child's derived cascade reproduces.

    The number that says whether the new capability did anything at all. It is
    decidable in one pass over the children — apply each child's derived
    cascade, compare — with no prior knowledge of which concepts mixed, and its
    converse doubles as the verification of those derived rules.
    """
    columns_decided_by_residue_policy: int | None = Field(default=None, ge=0)
    """Successor to `tie_broken_concept_count`'s first half.

    Under assembly, ties between whole strings mostly disappear and the
    arbitrariness moves into the columns. Without this the beam would print one
    candidate at p = 1.00 whether every column was evidenced or half of them
    were defaults.
    """
    columns_decided_by_tie_break: int | None = Field(default=None, ge=0)
    """Columns two committed sets both matched, decided by `TIE_BREAK_POLICY`.

    Shown to the model first: `test_proto_assembly` lists every such column so
    the session can condition one of the sets, split a set, or say in the
    summary that the evidence does not decide. The policy stays the last resort
    and stays documented as arbitrary.
    """
    mean_set_support: float | None = Field(default=None, ge=0.0)
    """Mean support of the committed sets.

    What separates an inventory built on recurrence from one built on one word
    each. Committing a support-1 set is legal and deliberately so — the whole
    Polynesian benchmark has 175 singletons against 41 recurrent sets — but it
    is visible.
    """
    restored_segment_count: int | None = Field(default=None, ge=0)
    """Segments every active child lost, restored on cited out-group evidence."""
    alignment_overrides: int | None = Field(default=None, ge=0)
    """Concepts at this node carrying a model-supplied alignment.

    A node that reconstructed most of its concepts through hand-aligned
    overlays is a node whose reconstruction is the model's alignment, and a
    reader must be able to see that in one line. Reported and not enforced:
    "was this realignment *right*?" is a linguistic question.
    """
    override_singleton_sets_created: int | None = Field(default=None, ge=0)
    """Overrides that named no set to join, and so bypassed the join check."""
    held_out_unaccounted_column_rate: float | None = Field(
        default=None, ge=0.0, le=1.0
    )
    """The committed inventory applied to the concepts this node withheld.

    The direct analogue of `held_out_convergence_rate`, and it catches the same
    thing: an inventory fitted to five concepts explains nothing on the concepts
    it never saw. Reported, never enforced.
    """
    contrast_reducing_set_count: int | None = Field(default=None, ge=0)
    """Committed sets that delete a segment or merge two into one.

    The successor to `contrast_reducing_rule_count`, computed from the inventory
    rather than by applying a cascade: two sets sharing one `proto_segment`
    without complementary conditioning is a merger, and a non-null reflex
    against a null `proto_segment` is a deletion. Same arithmetic, same
    discipline, better evidence — it now sees the merger *as* a merger rather
    than inferring it from a mapping.
    """


class NodeFailureRecord(WorkbenchModel):
    """One node whose session failed, and what the traversal did about it.

    Kept beside the results rather than in place of them: the walk continued
    over an identity fallback, so the parent beam exists and every node above
    it was still reconstructed. The trajectory of the failed session is written
    to `trajectories.jsonl` exactly as before and is named here by ID.
    """

    node_id: NonEmptyStr
    child_node_ids: tuple[NonEmptyStr, ...] = ()
    error_type: NonEmptyStr
    reason: NonEmptyStr
    trajectory_id: NonEmptyStr | None = None


class TraversalSnapshot(WorkbenchModel):
    root_node_id: NonEmptyStr
    completed_node_ids: tuple[NonEmptyStr, ...]
    node_beams: tuple[NodeBeamState, ...]
    steps: tuple[ReconstructionStep, ...]
