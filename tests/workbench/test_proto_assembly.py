"""The deterministic assembler: §4.4 of `docs/proto_inventory_design.md`.

Every case here is a property the design argues for in prose and would be silent
if it broke. The two worked examples from §5 are real rows of the Polynesian
benchmark and are the reason the change exists: the `*ʔ` set is reconstructed
from three daughters against a vowel set attested by a different nine, and the
`*t`/`*k` pair assembles concept 1355 with no rule order at all.
"""

from __future__ import annotations

import math

import pytest

from cognate_reconstruction.alignment.correspondence_sets import (
    build_correspondence_sets,
)
from cognate_reconstruction.alignment.environments import (
    UNDECIDED,
    environment_matches,
    observed_readings,
)
from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.rules.parser import parse_rule
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm
from cognate_reconstruction.schemas.rules import ReconstructionRule
from cognate_reconstruction.traversal.beam import make_leaf_beam
from cognate_reconstruction.traversal.reconstructor import RuleBasedReconstructor
from cognate_reconstruction.schemas.beam import (
    CandidateDerivation,
    ConceptCandidateDistribution,
    NodeBeamState,
    ReconstructionCandidate,
)
from cognate_reconstruction.schemas.inventory import (
    CommitProtoInventoryArgs,
    CommittedProtoInventory,
    CorrespondenceCommitment,
    ResidueDisposition,
    ResiduePolicy,
    SegmentRestoration,
    derive_set_id,
)
from cognate_reconstruction.schemas.rules import (
    RuleEnvironment,
    SegmentExpression,
)
from cognate_reconstruction.traversal.assembler import (
    ProtoInventoryAssembler,
    build_plan,
    derive_branch_rules,
    inventory_contrast_reductions,
    resolve_columns,
)

POLYNESIAN = (
    "EastFutuna",
    "EastUvea",
    "Hawaiian",
    "Maori",
    "Niuean",
    "NorthMarquesan",
    "Rarotongan",
    "Samoan",
    "Tahitian",
    "Tongan",
)


def _commitment(
    reflexes: tuple[str | None, ...],
    proto: str | None,
    *,
    children: tuple[str, ...] = POLYNESIAN,
    support: int = 3,
    confidence: float = 0.9,
    conditioning: RuleEnvironment | None = None,
    **extra,
) -> CorrespondenceCommitment:
    return CorrespondenceCommitment(
        set_id=derive_set_id(
            reflexes,
            children,
            segmentation_overlay_id=None,
            alignment_overlay_id=None,
        ),
        reflexes=reflexes,
        proto_segment=proto,
        support=support,
        confidence=confidence,
        conditioning=conditioning,
        **extra,
    )


def _inventory(
    commitments,
    *,
    children: tuple[str, ...] = POLYNESIAN,
    policy: ResiduePolicy = ResiduePolicy.RETAIN_FROM_WITNESS,
    witness: str | None = "Tongan",
    dispositions: tuple[ResidueDisposition, ...] = (),
    restorations: tuple[SegmentRestoration, ...] = (),
    node_id: str = "proto_polynesian",
) -> CommittedProtoInventory:
    request = CommitProtoInventoryArgs(
        node_id=node_id,
        child_node_ids=children,
        commitments=tuple(commitments),
        residue_policy=policy,
        residue_witness_child_id=witness if policy
        is ResiduePolicy.RETAIN_FROM_WITNESS
        else None,
        residue_dispositions=dispositions,
        restorations=restorations,
        summary="test inventory",
    )
    derived = derive_branch_rules(request.commitments, children)
    return CommittedProtoInventory(
        request=request,
        proto_phonemes=tuple(
            sorted(
                {
                    item.proto_segment
                    for item in request.commitments
                    if item.proto_segment is not None
                }
            )
        ),
        derived_rules=derived.rules,
        non_invertible_child_ids=derived.non_invertible_child_ids,
    )


def _beam(node_id: str, forms: dict[str, tuple[tuple[str, ...], ...]]) -> NodeBeamState:
    """A child beam with an explicit candidate list per concept."""
    distributions = []
    for concept_id, candidates in sorted(forms.items()):
        mass = 1.0 / len(candidates)
        distributions.append(
            ConceptCandidateDistribution(
                concept_id=concept_id,
                candidates=tuple(
                    ReconstructionCandidate(
                        candidate_id=f"{node_id}:{concept_id}:{index}",
                        segments=segments,
                        probability=mass,
                        log_score=math.log(mass),
                        derivations=(
                            CandidateDerivation(
                                derivation_id=f"observed:{node_id}:{concept_id}:{index}",
                                child_candidate_ids=(),
                            ),
                        ),
                    )
                    for index, segments in enumerate(candidates)
                ),
            )
        )
    return NodeBeamState(
        node_id=node_id, distributions=tuple(distributions), beam_width=5
    )


# --------------------------------------------------------------------------
# §5.1 — *ʔ on concept 1205 TONGUE: two sets, two different witnesses
# --------------------------------------------------------------------------

TONGUE = {
    "EastFutuna": ("ʔ", "a", "l", "e", "l", "o"),
    "EastUvea": ("ʔ", "a", "l", "e", "l", "o"),
    "Hawaiian": ("a", "l", "e", "l", "o"),
    "Maori": ("a", "r", "e", "r", "o"),
    "Niuean": ("a", "l", "e", "l", "o"),
    "NorthMarquesan": ("a", "ʔ", "e", "ʔ", "o"),
    "Rarotongan": ("a", "r", "e", "r", "o"),
    "Samoan": ("a", "l", "e", "l", "o"),
    "Tahitian": ("a", "r", "e", "r", "o"),
    "Tongan": ("ʔ", "e", "l", "e", "l", "o"),
}

TONGUE_ROWS = (
    ("ʔ", "a", "l", "e", "l", "o"),
    ("ʔ", "a", "l", "e", "l", "o"),
    (None, "a", "l", "e", "l", "o"),
    (None, "a", "r", "e", "r", "o"),
    (None, "a", "l", "e", "l", "o"),
    (None, "a", "ʔ", "e", "ʔ", "o"),
    (None, "a", "r", "e", "r", "o"),
    (None, "a", "l", "e", "l", "o"),
    (None, "a", "r", "e", "r", "o"),
    ("ʔ", "e", "l", "e", "l", "o"),
)

GLOTTAL_SET = ("ʔ", "ʔ", None, None, None, None, None, None, None, "ʔ")
LATERAL_SET = ("l", "l", "l", "r", "l", "ʔ", "r", "l", "r", "l")
VOWEL_A_SET = ("a", "a", "a", "a", "a", "a", "a", "a", "a", "e")
VOWEL_E_SET = ("e",) * 10
VOWEL_O_SET = ("o",) * 10


def _tongue_inventory(**kwargs) -> CommittedProtoInventory:
    return _inventory(
        (
            _commitment(GLOTTAL_SET, "ʔ", support=3),
            _commitment(LATERAL_SET, "l", support=8),
            _commitment(VOWEL_A_SET, "a", support=1, confidence=0.5),
            _commitment(VOWEL_E_SET, "e", support=6),
            _commitment(VOWEL_O_SET, "o", support=6),
        ),
        **kwargs,
    )


def test_the_glottal_set_assembles_a_form_no_branch_produces() -> None:
    """§5.1. `ʔ` comes from three daughters, `a` from nine, and not the same nine."""
    plan = build_plan(
        POLYNESIAN,
        _tongue_inventory().request.commitments,
        residue_policy=ResiduePolicy.RETAIN_FROM_WITNESS,
        residue_witness_child_id="Tongan",
    )
    outcomes, stats = resolve_columns(TONGUE_ROWS, "1205", plan)
    assert tuple(
        outcome.resolution.proto_segment for outcome in outcomes
    ) == ("ʔ", "a", "l", "e", "l", "o")
    assert stats.unaccounted == 0
    assert all(
        outcome.resolution.resolved_by == "set" for outcome in outcomes
    )
    # The evidence is genuinely mixed: `ʔ` comes from three daughters and `a`
    # from nine, and the two are not the same nine.
    assert [
        node
        for node, reflex in zip(POLYNESIAN, GLOTTAL_SET, strict=True)
        if reflex is not None
    ] == ["EastFutuna", "EastUvea", "Tongan"]
    assert VOWEL_A_SET.count("a") == 9 and VOWEL_A_SET[-1] == "e"
    # §5.1's "no branch produced it" is inaccurate for this flat ten-daughter
    # illustration and the design records the correction: EastFutuna and
    # EastUvea show the gold form verbatim. The claim is exactly true at the
    # `tongic` node the same section argues from, which is a separate case here.
    assert TONGUE["EastFutuna"] == ("ʔ", "a", "l", "e", "l", "o")


def test_a_gap_against_a_reconstructed_segment_is_recorded_not_rejected() -> None:
    """§4.3. The insertion the DSL cannot write becomes a recorded fact."""
    derived = derive_branch_rules(
        _tongue_inventory().request.commitments, POLYNESIAN
    )
    assert set(derived.non_invertible_child_ids) == {
        "Hawaiian",
        "Maori",
        "Niuean",
        "NorthMarquesan",
        "Rarotongan",
        "Samoan",
        "Tahitian",
    }
    # Tongic keeps `ʔ`, so no rule is derived for it from that set at all.
    tongan = [
        rule.rule.source
        for rule in derived.rules
        if rule.source_child_ids == ("Tongan",)
    ]
    assert tongan == ["e > a"]
    maori = sorted(
        rule.rule.source
        for rule in derived.rules
        if rule.source_child_ids == ("Maori",)
    )
    assert maori == ["r > l"]


# --------------------------------------------------------------------------
# §5.2 — *t and *k on concept 1355 LAUGH: no rule order at all
# --------------------------------------------------------------------------

T_SET = ("t", "t", "k", "t", "t", "t", "t", "t", "t", "t")
K_SET = ("k", "k", "ʔ", "k", "k", "ʔ", "k", "ʔ", "ʔ", "k")

LAUGH_ROWS = (
    ("k", "a", "t", "a"),
    ("k", "a", "t", "a"),
    ("ʔ", "a", "k", "a"),
    ("k", "a", "t", "a"),
    ("k", "a", "t", "a"),
    ("ʔ", "a", "t", "a"),
    ("k", "a", "t", "a"),
    ("ʔ", "a", "t", "a"),
    ("ʔ", "a", "t", "a"),
    ("k", "a", "t", "a"),
)


def test_the_hawaiian_chain_shift_needs_no_order() -> None:
    """§2.2. As a cascade this needs `k > t` strictly before `ʔ > k`."""
    commitments = (
        _commitment(K_SET, "k", support=4),
        _commitment(T_SET, "t", support=9),
        _commitment(("a",) * 10, "a", support=20),
    )
    plan = build_plan(
        POLYNESIAN,
        commitments,
        residue_policy=ResiduePolicy.DROP,
    )
    outcomes, stats = resolve_columns(LAUGH_ROWS, "1355", plan)
    assert tuple(
        outcome.resolution.proto_segment for outcome in outcomes
    ) == ("k", "a", "t", "a")
    assert stats.unaccounted == 0
    # The same reconstruction as Hawaiian rules is order-dependent; the derived
    # view carries both, and neither can shadow the other because a target and
    # environment belong to one set.
    derived = derive_branch_rules(commitments, POLYNESIAN)
    hawaiian = sorted(
        rule.rule.source
        for rule in derived.rules
        if rule.source_child_ids == ("Hawaiian",)
    )
    assert hawaiian == ["k > t", "ʔ > k"]


def test_one_target_and_environment_can_carry_only_one_value() -> None:
    """§2.1/§3. The contradiction case is unrepresentable, not merely detected.

    North Marquesan's `ʔ` reflects `*l` in one set of words and `*k` in another.
    Written as a branch cascade that is `ʔ > l` and `ʔ > k` with the same target,
    the same empty environment, and the same scope — the parser accepts both and
    the second is dead. As two sets it is two rules whose *sources* differ only
    in what the sisters show, and the derived cascade keeps both because they
    came from different correspondences.
    """
    commitments = (
        _commitment(LATERAL_SET, "l", support=8),
        _commitment(K_SET, "k", support=4),
    )
    derived = derive_branch_rules(commitments, POLYNESIAN)
    marquesan = sorted(
        rule.rule.source
        for rule in derived.rules
        if rule.source_child_ids == ("NorthMarquesan",)
    )
    assert marquesan == ["ʔ > k", "ʔ > l"]
    # Two commitments cannot carry one (set_id, conditioning) pair, which is
    # what makes the ambiguity a property of the daughter rather than of the
    # commit: the two rules above come from two different reflex tuples.
    assert commitments[0].set_id != commitments[1].set_id


# --------------------------------------------------------------------------
# §4.4 — residue, the empty inventory, and monotonicity
# --------------------------------------------------------------------------


def test_an_unaccounted_column_carries_through_from_the_witness() -> None:
    plan = build_plan(
        POLYNESIAN,
        (_commitment(GLOTTAL_SET, "ʔ", support=3),),
        residue_policy=ResiduePolicy.RETAIN_FROM_WITNESS,
        residue_witness_child_id="Tongan",
    )
    outcomes, stats = resolve_columns(TONGUE_ROWS, "1205", plan)
    assert tuple(
        outcome.resolution.proto_segment for outcome in outcomes
    ) == ("ʔ", "e", "l", "e", "l", "o")
    assert stats.unaccounted == 5
    assert stats.residue_policy_decided == 5


def test_dropping_residue_is_an_assertion_and_says_so() -> None:
    """The same one-set inventory under `drop` reconstructs `ʔ` and nothing else."""
    plan = build_plan(
        POLYNESIAN,
        (_commitment(GLOTTAL_SET, "ʔ", support=3),),
        residue_policy=ResiduePolicy.DROP,
    )
    outcomes, _stats = resolve_columns(TONGUE_ROWS, "1205", plan)
    assert tuple(
        outcome.resolution.proto_segment
        for outcome in outcomes
        if outcome.resolution.proto_segment is not None
    ) == ("ʔ",)


def test_assembly_is_monotonic_in_the_committed_sets() -> None:
    """Committing more sets refines the reconstruction; there is no cliff."""
    witness = TONGUE["Tongan"]
    steps = []
    for count in range(0, 6):
        commitments = _tongue_inventory().request.commitments[:count]
        plan = build_plan(
            POLYNESIAN,
            commitments,
            residue_policy=ResiduePolicy.RETAIN_FROM_WITNESS,
            residue_witness_child_id="Tongan",
        )
        outcomes, stats = resolve_columns(TONGUE_ROWS, "1205", plan)
        steps.append((stats.unaccounted, tuple(
            outcome.resolution.proto_segment for outcome in outcomes
        )))
    # Nothing committed leaves the reconstruction exactly where the witness is.
    assert steps[0][1] == witness
    # Residue only ever shrinks as sets are added.
    assert [item[0] for item in steps] == sorted(
        (item[0] for item in steps), reverse=True
    )
    assert steps[-1][1] == ("ʔ", "a", "l", "e", "l", "o")


def test_an_empty_inventory_short_circuits_to_the_identity_beam() -> None:
    """§4.4. Asserting nothing is not assembling nothing."""
    assembler = ProtoInventoryAssembler(beam_width=5)
    children = (
        _beam("A", {"water": (("p", "a"),)}),
        _beam("B", {"water": (("f", "a"),)}),
    )
    step = assembler.reconstruct(
        "PROTO",
        children,
        inventory=_inventory((), children=("A", "B"), witness="A"),
    )
    assert step.diagnostics.identity_reconstruction is True
    assert step.diagnostics.committed_set_count == 0
    assert step.assembly_reports == ()
    forms = {
        candidate.segments
        for distribution in step.output_beam.distributions
        for candidate in distribution.candidates
    }
    # Only forms a child actually produced, exactly as `rules: []` gives today.
    assert forms == {("p", "a"), ("f", "a")}


# --------------------------------------------------------------------------
# §4.4 — conditioning, in proto terms, in two passes
# --------------------------------------------------------------------------


def _palatal_inventory() -> tuple[CorrespondenceCommitment, ...]:
    children = ("A", "B")
    return (
        # ⟨A t : B s⟩ is *t generally and *ts before the *i column.
        _commitment(
            ("t", "s"),
            "t",
            children=children,
            support=4,
        ),
        _commitment(
            ("t", "s"),
            "ts",
            children=children,
            support=4,
            conditioning=RuleEnvironment(right=SegmentExpression(tokens=("i",))),
        ),
        _commitment(("i", "i"), "i", children=children, support=3),
        _commitment(("a", "a"), "a", children=children, support=3),
    )


def test_a_conditioned_set_is_resolved_against_proto_neighbours() -> None:
    plan = build_plan(
        ("A", "B"),
        _palatal_inventory(),
        residue_policy=ResiduePolicy.DROP,
    )
    before_i, _stats = resolve_columns((("t", "i"), ("s", "i")), "c1", plan)
    assert [item.resolution.proto_segment for item in before_i] == ["ts", "i"]
    assert before_i[0].resolution.resolved_by == "conditioned_set"
    before_a, _stats = resolve_columns((("t", "a"), ("s", "a")), "c2", plan)
    assert [item.resolution.proto_segment for item in before_a] == ["t", "a"]
    assert before_a[0].resolution.resolved_by == "set"


def test_a_conditioned_column_whose_neighbour_is_undecided_falls_to_residue() -> None:
    """§4.4. Two passes terminate; there is no fixpoint to chase."""
    children = ("A", "B")
    commitments = (
        # Both columns are conditioned on each other, so neither can be decided
        # in pass 1 and neither is decidable in pass 2.
        _commitment(
            ("t", "s"),
            "ts",
            children=children,
            support=2,
            conditioning=RuleEnvironment(right=SegmentExpression(tokens=("i",))),
        ),
        _commitment(
            ("i", "e"),
            "i",
            children=children,
            support=2,
            conditioning=RuleEnvironment(left=SegmentExpression(tokens=("ts",))),
        ),
    )
    plan = build_plan(
        children,
        commitments,
        residue_policy=ResiduePolicy.RETAIN_FROM_WITNESS,
        residue_witness_child_id="A",
    )
    outcomes, stats = resolve_columns((("t", "i"), ("s", "e")), "c1", plan)
    assert stats.unaccounted == 2
    assert [item.resolution.resolved_by for item in outcomes] == [
        "residue_policy",
        "residue_policy",
    ]
    assert [item.resolution.proto_segment for item in outcomes] == ["t", "i"]


def test_a_derived_environment_is_spelled_in_the_childs_own_segments() -> None:
    """§4.4. A commitment's conditioning is proto; a derived rule's is not."""
    derived = derive_branch_rules(_palatal_inventory(), ("A", "B"))
    sources = sorted(
        (rule.source_child_ids[0], rule.rule.source) for rule in derived.rules
    )
    assert sources == [
        ("A", "t > ts / _i"),
        ("B", "s > t"),
        ("B", "s > ts / _i"),
    ]
    assert derived.unconditioned_context_child_ids == ()


def test_a_gap_in_the_deciding_column_drops_the_derived_environment() -> None:
    """It does not reach past the gap: that is a non-local environment."""
    children = ("A", "B")
    commitments = (
        _commitment(
            ("t", "s"),
            "ts",
            children=children,
            support=2,
            conditioning=RuleEnvironment(right=SegmentExpression(tokens=("i",))),
        ),
        _commitment(("i", None), "i", children=children, support=2),
    )
    derived = derive_branch_rules(commitments, children)
    assert derived.unconditioned_context_child_ids == ("B",)
    assert sorted(
        (rule.source_child_ids[0], rule.rule.source) for rule in derived.rules
    ) == [("A", "t > ts / _i"), ("B", "s > ts")]
    assert derived.non_invertible_child_ids == ("B",)


# --------------------------------------------------------------------------
# The shared environment definition
# --------------------------------------------------------------------------


def test_adjacency_skips_columns_that_contribute_nothing() -> None:
    rows = (("t", None, "i"), ("t", None, "i"))
    readings = observed_readings(rows)
    environment = RuleEnvironment(right=SegmentExpression(tokens=("i",)))
    assert environment_matches(environment, readings, 0) is True


def test_a_word_edge_is_decidable_and_an_undecided_column_is_not() -> None:
    rows = (("t", "a"), ("t", "a"))
    readings = observed_readings(rows)
    assert (
        environment_matches(RuleEnvironment(word_initial=True), readings, 0)
        is True
    )
    partial = (None, frozenset({"a"}))
    assert (
        environment_matches(RuleEnvironment(word_initial=True), partial, 1)
        == UNDECIDED
    )


# --------------------------------------------------------------------------
# Contrast, restorations, and the whole-node path
# --------------------------------------------------------------------------


def test_contrast_reduction_reads_a_merger_off_the_inventory() -> None:
    children = ("A", "B")
    commitments = (
        _commitment(("l", "l"), "l", children=children, support=5),
        _commitment(("l", "n"), "l", children=children, support=2),
        _commitment(("h", None), None, children=children, support=2),
    )
    reductions = {
        item.set_id: item for item in inventory_contrast_reductions(commitments)
    }
    assert len(reductions) == 3
    assert reductions[commitments[0].set_id].merges is True
    assert reductions[commitments[2].set_id].deletes is True


def test_a_claimed_conditioned_split_is_not_counted_as_a_merger() -> None:
    children = ("A", "B")
    left = _commitment(
        ("l", "l"),
        "l",
        children=children,
        support=5,
        conditioning=RuleEnvironment(word_initial=True),
    )
    right = _commitment(
        ("l", "n"),
        "l",
        children=children,
        support=2,
        conditioning=RuleEnvironment(word_final=True),
        merges_with_set_id=left.set_id,
    )
    assert inventory_contrast_reductions((left, right)) == ()


def test_a_restoration_inserts_before_its_column() -> None:
    children = ("A", "B")
    inventory = _inventory(
        (
            _commitment(("a", "a"), "a", children=children, support=3),
            _commitment(("t", "t"), "t", children=children, support=3),
        ),
        children=children,
        policy=ResiduePolicy.DROP,
        witness=None,
        restorations=(
            SegmentRestoration(
                concept_id="water",
                before_column_index=0,
                proto_segment="ʔ",
                restored_from_node_ids=("OUT",),
                directionality_rationale="both children lost it; OUT keeps it",
            ),
        ),
        node_id="INNER",
    )
    assembler = ProtoInventoryAssembler(beam_width=5)
    step = assembler.reconstruct(
        "INNER",
        (
            _beam("A", {"water": (("a", "t"),)}),
            _beam("B", {"water": (("a", "t"),)}),
        ),
        inventory=inventory,
    )
    assert step.output_beam.distributions[0].candidates[0].segments == (
        "ʔ",
        "a",
        "t",
    )
    assert step.diagnostics.restored_segment_count == 1


def test_a_whole_node_reports_what_it_assembled() -> None:
    children = ("A", "B")
    inventory = _inventory(
        (
            _commitment(("p", "f"), "p", children=children, support=2),
            _commitment(("a", "a"), "a", children=children, support=2),
        ),
        children=children,
        policy=ResiduePolicy.RETAIN_FROM_WITNESS,
        witness="A",
        node_id="PROTO",
    )
    assembler = ProtoInventoryAssembler(beam_width=5)
    step = assembler.reconstruct(
        "PROTO",
        (
            _beam("A", {"water": (("p", "a"),)}),
            _beam("B", {"water": (("f", "a"),)}),
        ),
        inventory=inventory,
    )
    diagnostics = step.diagnostics
    assert step.output_beam.distributions[0].candidates[0].segments == ("p", "a")
    assert diagnostics.committed_set_count == 2
    assert diagnostics.proto_phoneme_count == 2
    assert diagnostics.assembled_column_count == 2
    assert diagnostics.unaccounted_column_count == 0
    assert diagnostics.unaccounted_column_rate == 0.0
    assert diagnostics.mean_set_support == 2.0
    assert diagnostics.identity_reconstruction is False
    # A's own cascade is empty and A's form *is* the assembled form, so this
    # concept did not need evidence mixed across the branches.
    assert diagnostics.cross_branch_assembly_rate == 0.0
    assert step.rule_reports == ()
    assert len(step.assembly_reports) == 1
    assert step.assembly_reports[0].assembled_segments == ("p", "a")


def test_cross_branch_assembly_is_detected_when_no_child_reproduces_the_form() -> None:
    """The mechanism check: `⟨ʔ : Ø⟩ → *ʔ` at a two-child node."""
    children = ("Tongan", "Niuean")
    inventory = _inventory(
        (
            _commitment(("ʔ", None), "ʔ", children=children, support=12),
            _commitment(("e", "a"), "a", children=children, support=4),
            _commitment(("l", "l"), "l", children=children, support=10),
            _commitment(("o", "o"), "o", children=children, support=8),
        ),
        children=children,
        policy=ResiduePolicy.RETAIN_FROM_WITNESS,
        witness="Tongan",
        node_id="tongic",
    )
    assembler = ProtoInventoryAssembler(beam_width=5)
    step = assembler.reconstruct(
        "tongic",
        (
            _beam("Tongan", {"1205": (("ʔ", "e", "l", "e", "l", "o"),)}),
            _beam("Niuean", {"1205": (("a", "l", "e", "l", "o"),)}),
        ),
        inventory=inventory,
    )
    assembled = step.output_beam.distributions[0].candidates[0].segments
    assert assembled == ("ʔ", "a", "l", "e", "l", "o")
    assert step.diagnostics.cross_branch_assembly_rate == 1.0
    assert step.assembly_reports[0].cross_branch_assembled is True
    # Niuean cannot be written at all: it shows a gap against *ʔ.
    assert inventory.non_invertible_child_ids == ("Niuean",)


def test_a_concept_fewer_than_two_children_attest_passes_through() -> None:
    children = ("A", "B")
    inventory = _inventory(
        (_commitment(("p", "f"), "p", children=children, support=2),),
        children=children,
        policy=ResiduePolicy.DROP,
        witness=None,
        node_id="PROTO",
    )
    assembler = ProtoInventoryAssembler(beam_width=5)
    step = assembler.reconstruct(
        "PROTO",
        (
            _beam("A", {"water": (("p", "a"),), "fire": (("k", "u"),)}),
            _beam("B", {"water": (("f", "a"),)}),
        ),
        inventory=inventory,
    )
    by_concept = {
        distribution.concept_id: distribution.candidates[0].segments
        for distribution in step.output_beam.distributions
    }
    assert by_concept["fire"] == ("k", "u")
    assert [report.concept_id for report in step.assembly_reports] == [
        "fire",
        "water",
    ]
    assert by_concept["water"] == ("p",)


def test_the_child_node_ids_must_match_the_child_beams() -> None:
    assembler = ProtoInventoryAssembler(beam_width=5)
    inventory = _inventory(
        (_commitment(("p", "f"), "p", children=("A", "B"), support=2),),
        children=("A", "B"),
        policy=ResiduePolicy.DROP,
        witness=None,
    )
    with pytest.raises(ValueError, match="child_node_ids"):
        assembler.reconstruct(
            "PROTO",
            (
                _beam("A", {"water": (("p", "a"),)}),
                _beam("C", {"water": (("f", "a"),)}),
            ),
            inventory=inventory,
        )


def test_alignments_are_cached_by_candidate_tuple() -> None:
    """§6.7. A requirement rather than an optimisation."""
    children = ("A", "B")
    calls: list[int] = []

    class _CountingAligner:
        def __init__(self) -> None:
            from cognate_reconstruction.alignment.lingpy_adapter import (
                LingPyAligner,
            )

            self._inner = LingPyAligner()

        def align(self, *args, **kwargs):  # pragma: no cover - unused here
            return self._inner.align(*args, **kwargs)

        def align_multiple(self, *args, **kwargs):
            calls.append(1)
            return self._inner.align_multiple(*args, **kwargs)

    aligner = _CountingAligner()
    assembler = ProtoInventoryAssembler(beam_width=5, aligner=aligner)
    inventory = _inventory(
        (_commitment(("p", "f"), "p", children=children, support=2),),
        children=children,
        policy=ResiduePolicy.RETAIN_FROM_WITNESS,
        witness="A",
        node_id="PROTO",
    )
    # Two concepts whose children carry the identical strings: four candidate
    # tuples over two distinct alignments.
    assembler.reconstruct(
        "PROTO",
        (
            _beam("A", {"water": (("p", "a"),), "fire": (("p", "a"),)}),
            _beam("B", {"water": (("f", "a"),), "fire": (("f", "a"),)}),
        ),
        inventory=inventory,
    )
    # One n-way call for the shared tuple, plus the correspondence-map call the
    # step records for the evidence context — which is absent here, so exactly
    # one alignment is computed for two concepts.
    assert sum(calls) == 1


def test_the_report_describes_the_form_the_beam_reports() -> None:
    """Two tuples can assemble to one string, and merging can reorder the top.

    `normalize_and_prune` sums the mass of identical forms, so a form two
    candidate tuples produced can outrank the single highest-scoring tuple. If
    the per-concept report were keyed by tuple, it would then describe a
    different reconstruction from the one the beam prints — a report and a
    result disagreeing about the same node.
    """
    children = ("A", "B")
    inventory = _inventory(
        (
            _commitment(("p", "f"), "p", children=children, support=2),
            _commitment(("p", "p"), "p", children=children, support=2),
            _commitment(("a", "a"), "a", children=children, support=2),
        ),
        children=children,
        policy=ResiduePolicy.RETAIN_FROM_WITNESS,
        witness="A",
        node_id="PROTO",
    )
    assembler = ProtoInventoryAssembler(beam_width=5)
    step = assembler.reconstruct(
        "PROTO",
        (
            # Two of A's three readings assemble to the same parent form, so
            # their mass merges and the merged form wins.
            _beam("A", {"water": (("k", "a"), ("p", "a"), ("p", "a", "a"))}),
            _beam("B", {"water": (("f", "a"),)}),
        ),
        inventory=inventory,
    )
    reported = step.output_beam.distributions[0].candidates[0].segments
    assert len(step.assembly_reports) == 1
    assert step.assembly_reports[0].assembled_segments == reported


# --------------------------------------------------------------------------
# §12.5 — morphological boundaries are aligned material
# --------------------------------------------------------------------------

BIRD = {
    "A": ("m", "a", "n", "u", "+", "l", "e", "l", "e"),
    "B": ("m", "a", "n", "u", "+", "r", "e", "r", "e"),
}


def _bird_lexicon(variety_id: str) -> LanguageLexicon:
    return LanguageLexicon(
        variety_id=variety_id,
        name=variety_id,
        forms=(
            LexicalForm(
                form_id=f"{variety_id}:bird",
                variety_id=variety_id,
                concept_id="bird",
                segments=BIRD[variety_id],
            ),
        ),
    )


def test_assembly_keeps_the_boundary_the_rule_path_keeps() -> None:
    """The regression the two commit paths must not disagree about.

    Both children read `m a n u + l e l e`-shaped, so a parent form has a `+`
    under any reading of the evidence. The rule cascade gets that for free —
    `make_leaf_beam` carries `form.segments` and `RuleEngine` rewrites nothing
    it was not told to — while assembly can only emit what some alignment column
    holds. While `LingPyAligner` stripped `+` before aligning, there was no such
    column and the assembled form came out one token short, silently, with
    nothing rejecting and nothing counting it.

    Pinned against *both* paths on purpose. The claim is not "assembly emits a
    boundary" but "assembly emits the same boundary the shipped path does", and
    only a comparison can say that.
    """
    children = ("A", "B")
    beams = tuple(
        make_leaf_beam(_bird_lexicon(child), beam_width=5) for child in children
    )

    rule_step = RuleBasedReconstructor(beam_width=5).reconstruct(
        "PROTO",
        beams,
        rules=[
            ReconstructionRule(
                rule=parse_rule("r > l"),
                source_child_ids=("B",),
                confidence=0.9,
            )
        ],
    )
    rule_forms = {
        candidate.segments
        for candidate in rule_step.output_beam.distributions[0].candidates
    }
    assert BIRD["A"] in rule_forms

    inventory = _inventory(
        (
            _commitment(("m", "m"), "m", children=children, support=1),
            _commitment(("a", "a"), "a", children=children, support=1),
            _commitment(("n", "n"), "n", children=children, support=1),
            _commitment(("u", "u"), "u", children=children, support=1),
            _commitment(("+", "+"), "+", children=children, support=1),
            _commitment(("l", "r"), "l", children=children, support=2),
            _commitment(("e", "e"), "e", children=children, support=2),
        ),
        children=children,
        witness="A",
        node_id="PROTO",
    )
    step = ProtoInventoryAssembler(beam_width=5).reconstruct(
        "PROTO", beams, inventory=inventory
    )
    assembled = step.assembly_reports[0].assembled_segments
    assert assembled == BIRD["A"]
    assert "+" in assembled
    assert step.diagnostics.unaccounted_column_rate == 0.0
    # And the two paths agree about the token that used to go missing.
    assert assembled in rule_forms


def test_a_boundary_correspondence_derives_no_rule_and_is_recorded() -> None:
    """`+` and `-` stay untouchable by the DSL now that they are columns.

    `rules/parser.py` refuses a boundary as a rule target and as an insertion,
    deliberately: a cascade that rewrote one would be the harness placing
    morphs. A commitment can now express what the cascade cannot spell — drop a
    boundary, or reconstruct one where a child shows a segment — so the derived
    view records the child and emits no rule, the same way it already records
    the insertion the DSL cannot write.
    """
    children = ("A", "B")
    # The dull, common case: both children show `+`, the proto has `+`, and no
    # rule is derived because reflex and proto agree.
    kept = derive_branch_rules(
        (_commitment(("+", "+"), "+", children=children, support=4),), children
    )
    assert kept.rules == ()
    assert kept.boundary_change_child_ids == ()

    # The case that used to raise out of the assembler: the boundary is dropped.
    dropped = derive_branch_rules(
        (_commitment(("+", "+"), None, children=children, support=4),), children
    )
    assert dropped.rules == ()
    assert dropped.boundary_change_child_ids == ("A", "B")

    # And the mirror: a boundary reconstructed where a child shows a segment.
    restored = derive_branch_rules(
        (_commitment(("a", "a"), "+", children=children, support=4),), children
    )
    assert restored.rules == ()
    assert restored.boundary_change_child_ids == ("A", "B")


def test_one_child_carrying_a_boundary_makes_a_correspondence_not_a_hole() -> None:
    """`⟨+ : Ø⟩` is the signal `polarize` calls decisive, now visible as a set.

    Material added at a morph boundary is innovation however well its segments
    are attested elsewhere, and until boundaries reached the aligner the harness
    had no way to *show* a session that one child has a boundary another lacks.
    It is a correspondence like any other: the model names its value, and the
    harness neither proposes one nor puts a morph anywhere.
    """
    aligner = LingPyAligner()
    simplex = LanguageLexicon(
        variety_id="B",
        name="B",
        forms=(
            LexicalForm(
                form_id="B:bird",
                variety_id="B",
                concept_id="bird",
                segments=("m", "a", "n", "u", "l", "e", "l", "e"),
            ),
        ),
    )
    alignment_map = aligner.align_multiple((_bird_lexicon("A"), simplex))
    inventory = build_correspondence_sets(alignment_map, node_ids=("A", "B"))
    boundary_sets = [
        item for item in inventory.sets if item.segments[0] == "+"
    ]
    assert boundary_sets, [item.segments for item in inventory.sets]
    assert boundary_sets[0].segments == ("+", None)

    # And stripping is still reachable for a caller that wants the phonetic
    # string alone: then there is no such column at all.
    stripped = build_correspondence_sets(
        aligner.align_multiple(
            (_bird_lexicon("A"), simplex), include_boundaries=False
        ),
        node_ids=("A", "B"),
    )
    assert not [item for item in stripped.sets if item.segments[0] == "+"]


def test_a_dash_boundary_survives_the_aligner_that_writes_gaps_with_one() -> None:
    """LingPy spells a gap `-`, and `-` is also a boundary this repo allows.

    Handing one to the aligner unencoded would read every `-` boundary back as
    an alignment gap, which is the same silent one-token loss one level down. It
    does not arise on any benchmark checked in here — Polynesian uses `+` for
    all 148 of its boundaries — which is exactly why it needs a test.
    """
    aligner = LingPyAligner()
    lexicons = tuple(
        LanguageLexicon(
            variety_id=variety_id,
            name=variety_id,
            forms=(
                LexicalForm(
                    form_id=f"{variety_id}:bird",
                    variety_id=variety_id,
                    concept_id="bird",
                    segments=segments,
                ),
            ),
        )
        for variety_id, segments in (
            ("A", ("m", "a", "n", "u", "-", "l", "e")),
            ("B", ("m", "a", "n", "u", "-", "r", "e")),
        )
    )
    alignment_map = aligner.align_multiple(lexicons)
    rows = {
        member.variety_id: member.aligned_segments
        for member in alignment_map.alignments[0].members
    }
    for variety_id, expected in (
        ("A", ("m", "a", "n", "u", "-", "l", "e")),
        ("B", ("m", "a", "n", "u", "-", "r", "e")),
    ):
        assert tuple(
            token for token in rows[variety_id] if token is not None
        ) == expected
