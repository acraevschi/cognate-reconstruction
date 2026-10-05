"""The proto-inventory commit: correspondence sets and their proto-phonemes.

The object a node commits under the per-set protocol. Instead of an ordered,
branch-scoped rewrite cascade, a session commits a mapping from correspondence
sets to proto-phonemes; deterministic code assembles each parent form column by
column out of them and *derives* the per-branch rules as a view.

Two properties of that object decide most of what is here.

- **A set carries exactly one value.** Two rules at one node claiming `f > p`
  for one child and `p > f` for another are two claims about one
  correspondence, and a correspondence has one proto-phoneme. The contradiction
  becomes unrepresentable rather than detected.
- **Sets are independent.** `commitments` is a tuple for serialization
  determinism and nothing reads the sequence. There is no rule order, so the
  ordering trap that made a Hawaiian cascade mean two different things
  depending on which rule ran first cannot arise.

See `docs/proto_inventory_design.md` §4 for the specification and §4.4 for the
assembly algorithm these models are the input to.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from cognate_reconstruction.schemas.alignment import GAP_SEGMENT_TOKENS
from cognate_reconstruction.schemas.common import NonEmptyStr, WorkbenchModel
from cognate_reconstruction.schemas.evidence import ColumnBinding, UnitOrderClaim, PieceSource
from cognate_reconstruction.schemas.rules import (
    AnomalyReport,
    ReconstructionRule,
    RuleEnvironment,
)

WRITTEN_GAP_SPELLINGS: frozenset[str] = GAP_SEGMENT_TOKENS | frozenset(
    {"", "null", "None"}
)
"""Every spelling of "there is nothing here" accepted inside `reflexes`.

Wider than `GAP_SEGMENT_TOKENS`, which is the *filter* vocabulary a caller uses
to ask `summarize_correspondences` for the gap. This is the *writing*
vocabulary, and a model writing a JSON array of segments reaches for more than
two things: `Ø` and `∅` because it knows the DSL, and `""` or `"null"` because
it is writing JSON and the field beside it is a string. Measured on the
Polynesian sweep of 2026-08-24, where `['+', '']` and `['+', 'null']` against
the set `['+', None]` were the single largest rejection class and stalled ten
nodes.

**Not case-folded, deliberately.** `ø` U+00F8 is the close-mid front rounded
vowel and a perfectly good segment; only `Ø` U+00D8 means the gap. Folding case
here would silently delete a real reflex, which is a worse failure than the one
this fixes.

`""` cannot collide with a segment either: `NonEmptyStr` refuses it everywhere a
segment is accepted, so it has no other meaning to take away.
"""


def normalize_written_gaps(row: object) -> object:
    """Accept the DSL's gap spellings where the model has to write a gap.

    An alignment gap is `None` in these models, and `null` is what a JSON tool
    argument has to carry. But a model that knows the sound-law DSL knows `Ø`
    and `∅` as the way to say "nothing", and `summarize_correspondences` already
    accepts either in its `segment` filter for exactly this reason — the
    convention is `GAP_SEGMENT_TOKENS` and it predates this protocol.

    Measured rather than guessed: on a live node the model wrote
    `"reflexes": ["∅", "ʔ"]` for the `⟨Ø : ʔ⟩` set, was refused for a support
    mismatch it had not made, and spent two more turns discovering that `null`
    was meant. Normalizing here removes a rejection class without loosening a
    check — the reflex tuple is still compared against the harness's own.

    The accepted spellings live in `WRITTEN_GAP_SPELLINGS`, which is wider
    than the two the first version took: the same failure recurred on the
    Polynesian sweep of 2026-08-24 with `""` and `"null"`, which is what a
    model writing JSON reaches for rather than what a model that knows the
    DSL reaches for.

    The list-to-tuple conversion is not incidental. A `mode="before"` validator
    takes the raw input, so the fields it hands on are validated strictly rather
    than in the JSON mode the tool boundary parses in, where a list is a legal
    tuple. `CommittedSoundRule.supply_rule_id` converts its own list fields for
    exactly this reason and this follows it.

    **Public, and shared with `PolarizeArgs.correspondence`**, which takes the
    same object: the workflow hands the model one row of
    `summarize_correspondences` and asks it to paste that row into `polarize`
    and then into a commitment. Two vocabularies for one row is how the
    interface came to teach that a gap is `null` in one field and refuse it in
    the next.
    """
    if not isinstance(row, (list, tuple)):
        return row
    return tuple(
        None if isinstance(item, str) and item in WRITTEN_GAP_SPELLINGS else item
        for item in row
    )


SET_ID_GAP = "\x1e"
"""Stands in for an alignment gap inside a set-ID digest.

A control character, so it can never collide with a segment and `None` can
never hash the same as a node that literally shows `Ø`.
"""

SET_ID_SEPARATOR = "\x1d"
"""Separates the digest's sections, for the same reason."""


def derive_set_id(
    reflexes: Sequence[str | None],
    child_node_ids: Sequence[str],
    *,
    segmentation_overlay_id: str | None,
    alignment_overlay_id: str | None,
) -> str:
    """Name one correspondence set by its content alone.

    Stable within a session and reproducible outside one, so a model can cite a
    set the harness produced and the harness can re-derive it from the node's
    own forms rather than trusting the citation.

    **Both overlays are in the digest.** A segmentation overlay changes what a
    segment is and an alignment overlay changes which columns exist, so either
    changes what a *set* is. The consequence a model has to know is that a
    `realign` call invalidates every set ID derived under the previous overlay;
    `RealignResult.invalidated_set_ids` returns them by name so this is cheaper
    to learn than through a rejection at commit time.
    """
    material = "\0".join(
        [
            *(SET_ID_GAP if item is None else item for item in reflexes),
            SET_ID_SEPARATOR,
            *child_node_ids,
            SET_ID_SEPARATOR,
            segmentation_overlay_id or "",
            alignment_overlay_id or "",
        ]
    )
    return "cs-" + hashlib.sha256(material.encode()).hexdigest()[:12]


class CorrespondenceCommitment(WorkbenchModel):
    """One correspondence set, and the proto-phoneme reconstructed from it."""

    set_id: NonEmptyStr = Field(
        description=(
            'Exact local csu-* ID under this evidence/orders/overlays. Re-derived; stale or pattern IDs cannot authorize a local commitment.'
        ),
    )
    reflexes: tuple[str | None, ...] = Field(
        min_length=2,
        description=(
            'Required: exactly one entry per active child in child_node_ids order, including null gaps. Ø/∅ normalize to null. Full payloads must match the surveyed tuple.'
        ),
    )
    proto_segment: NonEmptyStr | None = Field(
        description=(
            'Required proto value or explicit null for no parent material; omission is refused. New output symbols are allowed; expressibility does not establish historical truth.'
        ),
    )
    conditioning: RuleEnvironment | None = Field(
        default=None,
        description=(
            'Optional environment evaluated on reconstructed neighbours, using literal left/right/word-edge DSL vocabulary.'
        ),
    )
    merges_with_set_id: NonEmptyStr | None = Field(
        default=None,
        description=(
            'Explicit complementary split claim. Both commitments need equal proto values and conditioning; overlapping environments are refused.'
        ),
    )
    support: int = Field(
        ge=1,
        description=(
            'Exact harness local count: supplied etyma plus unresolved concept/unit opportunities, under independent-etyma-v1. Refused on mismatch; not a model estimate.'
        ),
    )
    confidence: float = Field(
        gt=0.0,
        le=1.0,
        description=(
            'Required explicit confidence in (0,1], with no default; used as a score weight and never inferred.'
        ),
    )
    rationale: NonEmptyStr | None = Field(
        default=None,
        description=(
            'Required for every expanded local commitment when there is more than one. A single-set full inventory may use the final summary.'
        ),
    )
    directionality_rationale: NonEmptyStr | None = Field(
        default=None,
        description=(
            'Required for null against non-null material or distinct reflex tuples sharing a value without complementary conditioning. State proposed history, evidence and uncertainty; repeated identical retention is not a merger. Presence is checked, historical truth is not.'
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def accept_gap_spellings(cls, value):
        if not isinstance(value, dict) or "reflexes" not in value:
            return value
        return {**value, "reflexes": normalize_written_gaps(value["reflexes"])}

    @model_validator(mode="after")
    def validate_merger_claim(self) -> CorrespondenceCommitment:
        if self.merges_with_set_id is None:
            return self
        if self.merges_with_set_id == self.set_id:
            raise ValueError("a correspondence set cannot merge with itself")
        if self.conditioning is None:
            raise ValueError(
                "a commitment claiming a conditioned split must carry a "
                "'conditioning'"
            )
        return self


class ResiduePolicy(StrEnum):
    """What happens to an alignment column no committed set explains."""

    RETAIN_FROM_WITNESS = "retain_from_witness"
    """Use the named child on unexplained columns; its gaps emit nothing.

    This records a qualified witness choice, not proof of conservatism.
    """

    DROP = "drop"
    """Contribute nothing on unexplained columns; record this omission claim."""


class ResidueDisposition(WorkbenchModel):
    """One named exception to the residue policy, for a column looked at."""

    concept_id: NonEmptyStr
    column_index: int = Field(ge=0)
    evidence_column_id: NonEmptyStr | None = None
    proto_segment: NonEmptyStr | None
    explanation: NonEmptyStr


class SegmentRestoration(WorkbenchModel):
    """A segment every active child lost, restored on cited out-group evidence."""

    concept_id: NonEmptyStr
    before_evidence_column_id: NonEmptyStr | None = None
    unit_id: NonEmptyStr | None = None
    before_column_index: int = Field(
        ge=0,
        description=(
            "Insert before this column of the alignment under the committed "
            "overlays. Indices are into that alignment and are unaffected by "
            "other restorations, so they stay stable however many are "
            "committed. At most one restoration per (concept_id, "
            "before_column_index)."
        ),
    )
    proto_segment: NonEmptyStr
    restored_from_node_ids: tuple[NonEmptyStr, ...] = Field(
        min_length=1,
        description=(
            "Out-group nodes whose evidence licenses this. Verified: each must "
            "genuinely attest the segment in the corresponding position, and "
            "must be an out-group rather than a descendant. The root has no "
            "out-group, so nothing licenses a restoration there."
        ),
    )
    directionality_rationale: NonEmptyStr = Field(
        description=(
            "Required, never optional here: restoring a segment *is* the claim "
            "that every active branch lost it."
        ),
    )


class SharedCorrespondenceClaim(WorkbenchModel):
    """One model-approved value over an explicit collection of local sets.

    A descriptive pattern is a retrieval handle, never automatic equivalence.
    Exclude local exceptions or provide different conditioned values. Counts and
    reflexes are re-derived for each member, rather than retranscribed.
    """
    pattern_id: NonEmptyStr
    member_set_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)
    proto_segment: NonEmptyStr | None
    confidence: float = Field(gt=0.0, le=1.0)
    rationale: NonEmptyStr
    directionality_rationale: NonEmptyStr | None = None
    conditioning: RuleEnvironment | None = None

    @model_validator(mode="after")
    def unique_members(self):
        if len(set(self.member_set_ids)) != len(self.member_set_ids):
            raise ValueError("shared claim must name each local set once")
        return self


class ProtoInventorySpec(WorkbenchModel):
    """The inventory a `commit_reconstruction` call carries, as the model sends it."""

    unit_orders: tuple[UnitOrderClaim, ...] = ()

    child_node_ids: tuple[NonEmptyStr, ...] = Field(
        min_length=2,
        description=(
            "Column order for every commitment's 'reflexes'. Must be exactly "
            "this node's active children."
        ),
    )
    alignment_overlay_id: NonEmptyStr | None = Field(
        default=None,
        description=(
            "The alignment_overlay_id returned by realign, when the committed "
            "sets were derived under one. Omit it when no realignment was made."
        ),
    )
    assembly_validation_call_id: NonEmptyStr | None = Field(
        default=None,
        description=(
            'Optional exact same-session preview ID; omitted IDs resolve from previews of identical hypotheses/evidence. Nonempty/structural claims require validation.'
        ),
    )
    shared_claims: tuple[SharedCorrespondenceClaim, ...] = ()
    commitments: tuple[CorrespondenceCommitment, ...] = Field(
        description=(
            'Local commitments; order has no meaning. Shared claims, structural decisions and residue policy also form part of the exact hypothesis.'
        ),
    )
    residue_policy: ResiduePolicy = Field(
        description=(
            'Required: retain_from_witness uses the named child on unexplained columns (a witness gap emits nothing); drop contributes nothing. Unaccounted columns remain reported.'
        ),
    )
    residue_witness_child_id: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Required by 'retain_from_witness', refused otherwise: the child "
            "whose material is carried through where nothing explains it."
        ),
    )
    residue_dispositions: tuple[ResidueDisposition, ...] = ()
    restorations: tuple[SegmentRestoration, ...] = ()

    @model_validator(mode="after")
    def validate_inventory(self) -> ProtoInventorySpec:
        if len(set(self.child_node_ids)) != len(self.child_node_ids):
            raise ValueError("child_node_ids must be unique")
        # A (set, conditioning) pair carries exactly one value, and that pair is
        # the unit of uniqueness — not the set alone.
        #
        # An earlier draft of the design rejected duplicate `set_id`s outright
        # (§4.1) while §4.4 resolved columns that "more than one commitment
        # matches". Those cannot both hold: `set_id` is a pure function of the
        # reflex tuple, the child order and the overlays, so identical reflexes
        # always give identical IDs and a per-set uniqueness rule makes the
        # multi-match branch unreachable. It also forbids a real analysis —
        # ⟨A t : B s⟩ reconstructing *t generally and *ts before *i is one
        # correspondence with a conditioned split, and there is no second reflex
        # tuple to hang the second value on. Uniqueness over the pair keeps what
        # the rule was for (the same claim cannot be committed twice) and makes
        # the elsewhere-condition expressible.
        claims = [
            (item.set_id, item.conditioning.model_dump_json()
             if item.conditioning is not None else None)
            for item in self.commitments
        ]
        if len(claims) != len(set(claims)):
            raise ValueError(
                "a correspondence set may be committed once per conditioning "
                "environment; two commitments name the same set with the same "
                "conditioning"
            )
        width = len(self.child_node_ids)
        for item in self.commitments:
            if len(item.reflexes) != width:
                raise ValueError(
                    "every commitment needs one reflex per child node "
                    f"({width}); {item.set_id!r} carries {len(item.reflexes)}"
                )
        if self.residue_policy is ResiduePolicy.RETAIN_FROM_WITNESS:
            if self.residue_witness_child_id is None:
                raise ValueError(
                    "residue_policy 'retain_from_witness' requires "
                    "residue_witness_child_id"
                )
            if self.residue_witness_child_id not in self.child_node_ids:
                raise ValueError(
                    "residue_witness_child_id must be one of child_node_ids"
                )
        elif self.residue_witness_child_id is not None:
            raise ValueError(
                "residue_witness_child_id is only meaningful with "
                "residue_policy 'retain_from_witness'"
            )
        positions = [
            (item.concept_id, item.evidence_column_id or item.column_index)
            for item in self.residue_dispositions
        ]
        if len(positions) != len(set(positions)):
            raise ValueError(
                "a residue disposition may name each concept column only once"
            )
        restored = [
            (item.concept_id, item.before_evidence_column_id or item.before_column_index)
            for item in self.restorations
        ]
        if len(restored) != len(set(restored)):
            raise ValueError(
                "a restoration may name each concept position only once"
            )
        return self


class CommitProtoInventoryArgs(ProtoInventorySpec):
    """The whole inventory commit as it is persisted.

    The spec the model sent, plus the fields `commit_reconstruction` takes for
    either commit shape. This is what `CommittedProtoInventory.request` holds,
    so a trajectory records one self-contained object rather than a fragment
    that only makes sense beside the tool call it came from."""

    node_id: NonEmptyStr
    segmentation_overlay_id: NonEmptyStr | None = None
    anomalies: tuple[AnomalyReport, ...] = ()
    summary: NonEmptyStr


class CommittedProtoInventory(WorkbenchModel):
    """One node's committed inventory, with everything derived from it.

    Mirrors `CommittedReconstruction`, and carries `commit_shape` so a reader
    of a mixed archive can branch without probing which request shape is
    present.
    """

    evidence_contract_version: Literal["legacy", "units-v1", "units-v2"] = "legacy"
    derived_rules_scope: Literal["global", "unscoped_view"] = "global"
    evidence_revision: NonEmptyStr | None = None
    column_bindings: tuple[ColumnBinding, ...] = ()
    approved_shared_claims: tuple[SharedCorrespondenceClaim, ...] = ()

    commit_shape: Literal["inventory"] = "inventory"
    request: CommitProtoInventoryArgs
    proto_phonemes: tuple[NonEmptyStr, ...] = ()
    """The node's inventory: sorted distinct non-null proto_segments.

    The first-class object this whole change exists to produce, and what
    `inspect-run` prints. Derived, never supplied.
    """
    derived_rules: tuple[ReconstructionRule, ...] = ()
    """The per-branch reflex cascade, derived and verified. A view, never a
    mechanism — which is why insertion never needs to exist."""
    non_invertible_child_ids: tuple[NonEmptyStr, ...] = ()
    """Children whose derived cascade cannot be written at all.

    Some committed set assigns them a gap against a non-null `proto_segment`,
    which is the insertion the DSL cannot express. It is now a recorded fact
    rather than a rejected call. The name follows the `invertible: false`
    convention `schemas/synthetic.py` already uses, so `score-synthetic`
    compares like with like across the migration.
    """

    @model_validator(mode="after")
    def validate_evidence_contract(self):
        if self.evidence_contract_version != "legacy" and self.evidence_revision is None:
            raise ValueError("unit inventory requires its evidence revision")
        if self.evidence_contract_version == "units-v2" and self.request.shared_claims:
            raise ValueError("persisted units-v2 request must contain expanded local commitments")
        for claim in self.approved_shared_claims:
            for set_id in claim.member_set_ids:
                if not any(c.set_id == set_id and c.proto_segment == claim.proto_segment
                           and c.confidence == claim.confidence and c.conditioning == claim.conditioning
                           and c.rationale == claim.rationale and c.directionality_rationale == claim.directionality_rationale
                           for c in self.request.commitments):
                    raise ValueError("approved shared claim must match its expanded local commitments")
        ids = [binding.column_id for binding in self.column_bindings]
        if len(set(ids)) != len(ids):
            raise ValueError("column bindings must name each evidence column once")
        return self

    @property
    def anomalies(self) -> tuple[AnomalyReport, ...]:
        """Anomalies the commit carried, under the rule shape's own name."""
        return self.request.anomalies

    @property
    def identity_reconstruction(self) -> bool:
        """Did this inventory assert anything at all?

        True exactly when the assembler is short-circuited: no commitment, no
        residue disposition, and no restoration. Asserting nothing is a
        categorically different act from asserting something.
        """
        return not (
            self.request.commitments
            or self.request.residue_dispositions
            or self.request.restorations
            or self.request.unit_orders
        )


class AssemblyDetail(StrEnum):
    """How much of an assembly preview's working trace comes back."""

    SUMMARY = "summary"
    FULL = "full"


class ColumnResolution(WorkbenchModel):
    """How one alignment column got its proto value, or failed to."""

    source_positions: tuple[PieceSource, ...] = ()
    evidence_column_id: NonEmptyStr | None = None
    unit_id: NonEmptyStr | None = None
    unmatched_reason: NonEmptyStr | None = None

    column_index: int = Field(ge=0)
    reflexes: tuple[str | None, ...]
    set_id: NonEmptyStr | None = None
    proto_segment: NonEmptyStr | None = None
    resolved_by: Literal[
        "set",
        "conditioned_set",
        "residue_policy",
        "residue_disposition",
        "restoration",
    ]
    competing_set_ids: tuple[NonEmptyStr, ...] = ()
    """Other committed sets that also matched this column.

    Populated only where more than one set matched, which is the ambiguity
    `test_proto_assembly` surfaces so the session can disambiguate it before
    committing. Resolving it silently by segment order would be the harness
    making a call the model is better placed to make.
    """


class ConceptAssemblyReport(WorkbenchModel):
    """What the assembler did to one concept.

    The compact rendering only — set IDs, never the alignment rows. The
    `correspondence_maps` measurement is the precedent and the warning: 448 KB
    of a 10,017 KB result for something no reader had asked for.
    """

    unit_ids: tuple[NonEmptyStr, ...] = ()
    unmatched_columns: tuple[ColumnResolution, ...] = ()

    concept_id: NonEmptyStr
    alignment_id: NonEmptyStr
    assembled_segments: tuple[str, ...] = ()
    columns: tuple[ColumnResolution, ...] = ()
    """Per-column resolutions; populated for `detail="full"` only."""
    unaccounted_column_count: int = Field(default=0, ge=0)
    column_count: int = Field(default=0, ge=0)
    matched_anchor_ids: tuple[NonEmptyStr, ...] = ()
    cross_branch_assembled: bool = False
    """No single child's derived cascade reproduces this assembled form.

    Decidable in one pass over the children with no prior knowledge of which
    concepts mixed, and its converse doubles as the verification of the derived
    rules: where some child *does* reproduce the form, that child's rules are
    confirmed against the assembler rather than assumed to agree with it.
    """


class AlignmentOverride(WorkbenchModel):
    """One concept's alignment, re-laid by the model."""

    analysis_ids: tuple[str | None, ...] = ()
    unit_id: NonEmptyStr | None = Field(default=None, description="Exact evidence unit to realign; required for partial evidence. Whole-form legacy edits omit this.")

    concept_id: NonEmptyStr
    rows: tuple[tuple[str | None, ...], ...] = Field(
        min_length=2,
        description=(
            "The re-laid alignment, one row per child, positional against "
            "child_node_ids, with null for a gap. Dropping the nulls from each "
            "row must reproduce that child's form exactly."
        ),
    )
    joins_set_id: NonEmptyStr | None = Field(
        default=None,
        description=(
            "The correspondence set this realignment claims the moved column "
            "joins. Naming one turns an edit into a claim the harness can "
            "verify: the named set must gain support by exactly the number of "
            "columns claimed for it. Null selects new_set mode, which is legal, "
            "is counted separately, and is the mode that bypasses that check."
        ),
    )
    rationale: NonEmptyStr

    @model_validator(mode="before")
    @classmethod
    def accept_gap_spellings(cls, value):
        if not isinstance(value, dict):
            return value
        rows = value.get("rows")
        if not isinstance(rows, (list, tuple)):
            return value
        return {**value, "rows": tuple(normalize_written_gaps(row) for row in rows),
                "analysis_ids": tuple(value.get("analysis_ids", ())) }

    @model_validator(mode="after")
    def validate_width(self) -> AlignmentOverride:
        widths = {len(row) for row in self.rows}
        if len(widths) != 1:
            raise ValueError("every override row must have the same width")
        if self.analysis_ids and len(self.analysis_ids) != len(self.rows):
            raise ValueError("analysis_ids must contain one entry per child row")
        return self


__all__ = [
    "SET_ID_GAP",
    "SET_ID_SEPARATOR",
    "AlignmentOverride",
    "AssemblyDetail",
    "ColumnResolution",
    "CommitProtoInventoryArgs",
    "CommittedProtoInventory",
    "ConceptAssemblyReport",
    "CorrespondenceCommitment",
    "ProtoInventorySpec",
    "ResidueDisposition",
    "ResiduePolicy",
    "SegmentRestoration",
    "WRITTEN_GAP_SPELLINGS",
    "derive_set_id",
    "normalize_written_gaps",
]
