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
from cognate_reconstruction.schemas.rules import (
    AnomalyReport,
    ReconstructionRule,
    RuleEnvironment,
)

def _normalize_gaps(row: object) -> object:
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

    The list-to-tuple conversion is not incidental. A `mode="before"` validator
    takes the raw input, so the fields it hands on are validated strictly rather
    than in the JSON mode the tool boundary parses in, where a list is a legal
    tuple. `CommittedSoundRule.supply_rule_id` converts its own list fields for
    exactly this reason and this follows it.
    """
    if not isinstance(row, (list, tuple)):
        return row
    return tuple(
        None if isinstance(item, str) and item in GAP_SEGMENT_TOKENS else item
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
            "The set_id of the correspondence set this commits a value for, "
            "exactly as returned by summarize_correspondences or "
            "test_proto_assembly. The harness re-derives the set from this "
            "node's own forms and refuses a commitment whose cited set it "
            "cannot reproduce. A realign call invalidates every set_id derived "
            "under the previous alignment overlay."
        ),
    )
    reflexes: tuple[str | None, ...] = Field(
        min_length=2,
        description=(
            "The set's segments, positional against child_node_ids. Use null "
            "for an alignment gap; 'Ø' and '∅' are accepted and mean the same. "
            "Required even though set_id determines it: a commit a human "
            "cannot read without re-running a tool is not an audit record."
        ),
    )
    proto_segment: NonEmptyStr | None = Field(
        description=(
            "The proto-phoneme you reconstruct for this set, or null for 'this "
            "set reconstructs nothing' — every branch showing material here "
            "innovated it. It is deliberately not restricted to the segments in "
            "'reflexes': Proto-Polynesian *w survives as v or as nothing in "
            "every daughter, and a schema that could only emit an observed "
            "reflex would make it unreconstructable."
        ),
    )
    conditioning: RuleEnvironment | None = Field(
        default=None,
        description=(
            "The environment in which this commitment holds, in the DSL's own "
            "left/right/word-edge vocabulary. Evaluated in *proto* terms: the "
            "neighbouring proto-phonemes, not any one child's segments."
        ),
    )
    merges_with_set_id: NonEmptyStr | None = Field(
        default=None,
        description=(
            "This set and that one are one phoneme in complementary "
            "distribution. Both commitments must name the same proto_segment "
            "and both must carry a conditioning; the harness checks the claim "
            "against the node's own columns and refuses it if they share an "
            "environment."
        ),
    )
    support: int = Field(
        ge=1,
        description=(
            "Aligned columns showing this set, copied from the harness's own "
            "inventory. Re-derived and refused on mismatch: it is the one "
            "number separating a correspondence from residue and it must not "
            "be a model claim."
        ),
    )
    confidence: float = Field(
        gt=0.0,
        le=1.0,
        description=(
            "Your confidence in this reconstruction, in (0, 1]. Your own "
            "judgement; the deterministic assembler uses it as a score weight."
        ),
    )
    rationale: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Set-specific justification. Optional on a single-commitment "
            "inventory, where the required top-level 'summary' carries it; "
            "required on every commitment of an inventory carrying more than "
            "one."
        ),
    )
    directionality_rationale: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Which branch innovated, and why you believe it. Required on any "
            "commitment that discards material — a non-null reflex against a "
            "null proto_segment, or two sets sharing one proto_segment without "
            "complementary conditioning. The harness detects those "
            "mechanically and never judges what you write; it records that you "
            "wrote it."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def accept_gap_spellings(cls, value):
        if not isinstance(value, dict) or "reflexes" not in value:
            return value
        return {**value, "reflexes": _normalize_gaps(value["reflexes"])}

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
    """Carry through whatever `residue_witness_child_id` shows, unexplained.

    **An unaccounted column carries through; it does not vanish.** That is what
    makes assembly monotonic: committing more sets refines a reconstruction and
    committing none leaves it where the children are, with no cliff between the
    two. Naming a witness is a linguistic claim — *this branch is the most
    conservative* — made once, recorded, and readable by a reviewer.
    """

    DROP = "drop"
    """Treat unexplained material as branch-specific innovation.

    The opt-in, not the default reading. A model choosing this asserts that
    everything its inventory does not explain is innovation, which is a strong
    claim and usually a wrong one on a partial inventory.

    A `majority_reflex` option was drafted here and removed: "carry the segment
    most children show" is a majority vote over daughters, and
    `tools/outgroup_probe.py` measured that averaging over daughters scores
    exactly what alphabetical order scores, because it degenerates into a vote
    over shared innovations. See `docs/proto_inventory_design.md` §6.3.
    """


class ResidueDisposition(WorkbenchModel):
    """One named exception to the residue policy, for a column looked at."""

    concept_id: NonEmptyStr
    column_index: int = Field(ge=0)
    proto_segment: NonEmptyStr | None
    explanation: NonEmptyStr


class SegmentRestoration(WorkbenchModel):
    """A segment every active child lost, restored on cited out-group evidence.

    Not a correspondence, and deliberately not routed through one: nothing
    corresponds, which is the entire situation. `build_correspondence_sets`
    skips all-gap columns outright, and retaining them would make `support`
    count columns the model itself inserted — the one number that must never be
    a model claim. So this is a per-position claim, beside `ResidueDisposition`
    rather than among the commitments.
    """

    concept_id: NonEmptyStr
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


class ProtoInventorySpec(WorkbenchModel):
    """The inventory a `commit_reconstruction` call carries, as the model sends it.

    Split from `CommitProtoInventoryArgs` — which adds the fields both commit
    shapes share — so that one tool takes `rules` xor `inventory` without
    duplicating `node_id`, `summary`, and `anomalies` into a second argument
    model that could drift from the first.
    """

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
            "A successful test_proto_assembly call covering this inventory. "
            "Optional only in the sense that the harness resolves it from the "
            "session's previews when omitted; the same-session preview itself "
            "is not optional."
        ),
    )
    commitments: tuple[CorrespondenceCommitment, ...] = Field(
        description=(
            "This node's correspondence-set commitments. Order carries no "
            "meaning — sets are independent and nothing reads the sequence. An "
            "empty inventory is an identity reconstruction, the same claim "
            "rules=[] makes, with the same deterministic result."
        ),
    )
    residue_policy: ResiduePolicy = Field(
        description=(
            "Required, with no default. What happens to a column no committed "
            "set explains: 'retain_from_witness' carries through whatever one "
            "named child shows and marks it unexplained, 'drop' asserts the "
            "material is branch-specific innovation and contributes nothing."
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
            (item.concept_id, item.column_index)
            for item in self.residue_dispositions
        ]
        if len(positions) != len(set(positions)):
            raise ValueError(
                "a residue disposition may name each concept column only once"
            )
        restored = [
            (item.concept_id, item.before_column_index)
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
    that only makes sense beside the tool call it came from.
    """

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
        )


class AssemblyDetail(StrEnum):
    """How much of an assembly preview's working trace comes back."""

    SUMMARY = "summary"
    FULL = "full"


class ColumnResolution(WorkbenchModel):
    """How one alignment column got its proto value, or failed to."""

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
    """One concept's alignment, re-laid by the model.

    Session-local, immutable, ID'd, and never permanent: overrides never cross a
    node boundary, never enter the checkpoint, and never persist into another
    run. The rows must be the children's own forms — dropping the gaps from each
    row must reproduce that child's form token for token — so material may be
    moved between columns but never invented, deleted, or reordered.
    """

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
        return {**value, "rows": tuple(_normalize_gaps(row) for row in rows)}

    @model_validator(mode="after")
    def validate_width(self) -> AlignmentOverride:
        widths = {len(row) for row in self.rows}
        if len(widths) != 1:
            raise ValueError("every override row must have the same width")
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
    "derive_set_id",
]
