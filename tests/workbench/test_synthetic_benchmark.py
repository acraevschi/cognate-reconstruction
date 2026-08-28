"""The synthetic generator has to round-trip, or nothing built on it means anything.

A generated family is only a benchmark if the gold is actually recoverable from
the daughters by the rule language the model has to use. If applying the exact
inverse cascade as committed rules does not give the proto-forms back, then a
model that did everything right would still score wrong, and every number
measured on the family would be noise dressed as evidence.

That is the first test here. The rest pin the properties the families were
built to have: the hidden gold never appears in the payload, a branch that
deletes a segment is recorded as one no rule can undo, the noise knob is off
unless asked for and deterministic when asked for, and a rule scoped to a
branch the answer key left empty is reported as pointed the wrong way.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from datetime import UTC, datetime

from cognate_reconstruction.agent.schemas import (
    CommitReconstructionArgs,
    CommittedReconstruction,
    CommittedSoundRule,
    LLMMessage,
    LLMToolDefinition,
    MessageRole,
    NodeLexiconSummary,
    NodePromptPayload,
)
from cognate_reconstruction.agent.trajectory import (
    AgentNodeMetrics,
    AgentTrajectory,
)
from cognate_reconstruction.rules.engine import RuleEngine
from cognate_reconstruction.rules.parser import parse_rule
from cognate_reconstruction.schemas.historical import (
    GoldEvidenceKind,
    HistoricalFormRole,
)
from cognate_reconstruction.schemas.inventory import (
    CommitProtoInventoryArgs,
    CommittedProtoInventory,
    CorrespondenceCommitment,
    ResiduePolicy,
    derive_set_id,
)
from cognate_reconstruction.schemas.synthetic import SyntheticFamilyDefinition
from cognate_reconstruction.synthesis import generate_family, score_run
from cognate_reconstruction.synthesis.scoring import (
    BranchScore,
    CommittedBranchRule,
    committed_branch_rules,
)

FAMILIES = Path(__file__).resolve().parents[2] / "benchmarks" / "synthetic"


def _definition(name: str) -> SyntheticFamilyDefinition:
    return SyntheticFamilyDefinition.model_validate_json(
        (FAMILIES / f"{name}.json").read_text(encoding="utf-8")
    )


@pytest.mark.parametrize(
    "name", ["synthetic_regular", "synthetic_hard", "synthetic_noisy"]
)
def test_every_shipped_family_generates(name: str) -> None:
    result = generate_family(_definition(name))
    assert result.payload.lexicons
    assert result.answer_key.branches
    assert result.payload.historical_form_bindings


def test_the_inverse_cascade_recovers_the_proto_forms(tmp_path) -> None:
    """The soundness property, stated as bluntly as it can be.

    Take a proto-lexicon and a known cascade, generate the daughters, then apply
    the exact inverse cascade as a committed rule set. The proto-forms must come
    back segment for segment.
    """
    definition = SyntheticFamilyDefinition(
        name="roundtrip",
        description="A two-branch family with one substitution per branch.",
        newick="(left,right)proto;",
        proto_lexicon=(
            {"concept_id": "water", "segments": ("p", "a", "k", "u")},
            {"concept_id": "fire", "segments": ("t", "a", "m", "i")},
            {"concept_id": "stone", "segments": ("k", "u", "p", "a")},
        ),
        branches=(
            {"node_id": "left", "rules": ("p > f",)},
            {"node_id": "right", "rules": ("k > x",)},
        ),
    )
    result = generate_family(definition)
    lexicons = {
        lexicon.variety_id: lexicon for lexicon in result.payload.lexicons
    }
    proto = {
        form.concept_id: form.segments
        for form in result.payload.historical_form_bindings[0].forms
    }
    engine = RuleEngine()
    for branch in result.answer_key.branches:
        assert branch.invertible, branch.node_id
        recovered, _ = engine.apply_rules(
            tuple(parse_rule(text) for text in branch.inverse_rules),
            lexicons[branch.node_id].forms,
        )
        assert {
            form.concept_id: form.segments for form in recovered
        } == proto, (
            f"the inverse cascade for {branch.node_id} did not recover the "
            "proto-forms, so this family is not a sound benchmark"
        )


def test_the_shipped_regular_family_round_trips_on_every_branch() -> None:
    """The same property on the checked-in control family, not a toy."""
    result = generate_family(_definition("synthetic_regular"))
    engine = RuleEngine()
    lexicons = {
        lexicon.variety_id: lexicon
        for lexicon in result.answer_key.node_lexicons
    }
    for branch in result.answer_key.branches:
        assert branch.invertible, branch.node_id
        recovered, _ = engine.apply_rules(
            tuple(parse_rule(text) for text in branch.inverse_rules),
            lexicons[branch.node_id].forms,
        )
        expected = {
            form.concept_id: form.segments
            for form in lexicons[branch.parent_node_id].forms
        }
        assert {
            form.concept_id: form.segments for form in recovered
        } == expected


def test_the_gold_is_hidden_and_labelled_as_gold_by_construction() -> None:
    result = generate_family(_definition("synthetic_hard"))
    lexicon_ids = {
        lexicon.variety_id for lexicon in result.payload.lexicons
    }
    for binding in result.payload.historical_form_bindings:
        assert binding.role is HistoricalFormRole.TARGET
        assert binding.source_variety_id not in lexicon_ids
        assert binding.node_id not in lexicon_ids
        # Not "attested". A synthetic gold is exact and unmemorizable and is
        # also not evidence about any speech community.
        assert binding.gold_evidence_kind is GoldEvidenceKind.SYNTHETIC
    assert {
        binding.node_id for binding in result.payload.historical_form_bindings
    } == {"proto", "west", "east"}


def test_a_deleting_branch_is_recorded_as_one_no_rule_can_undo() -> None:
    """The DSL limitation, expressed rather than hidden.

    There is no empty-target insertion, so a branch that lost a segment can
    never restore it. A generated family whose gold required one would be
    unreachable rather than hard, so the generator records which branches those
    are instead of letting a scorer charge the model for an unwritable rule.
    """
    result = generate_family(_definition("synthetic_hard"))
    by_node = {branch.node_id: branch for branch in result.answer_key.branches}
    assert by_node["d2"].rules == ("ʔ > Ø / #_",)
    assert not by_node["d2"].invertible
    assert by_node["d2"].inverse_rules == ()
    # The one branch that keeps the segment every other branch lost. Nothing
    # above it could reconstruct the glottal stop without it.
    assert "ʔ" in {
        segment
        for lexicon in result.payload.lexicons
        if lexicon.variety_id == "d1"
        for form in lexicon.forms
        for segment in form.segments
    }
    for other in ("d2", "d3", "d4", "d5"):
        assert "ʔ" not in {
            segment
            for lexicon in result.payload.lexicons
            if lexicon.variety_id == other
            for form in lexicon.forms
            for segment in form.segments
        }


def test_the_chain_shift_needs_its_inverse_in_the_right_order() -> None:
    """Ordering is the point of a chain shift, so the wrong order must fail."""
    result = generate_family(_definition("synthetic_hard"))
    east = next(
        branch
        for branch in result.answer_key.branches
        if branch.node_id == "east"
    )
    assert east.rules == ("t > s", "k > t")
    assert east.inverse_rules == ("t > k", "s > t")
    lexicons = {
        lexicon.variety_id: lexicon
        for lexicon in result.answer_key.node_lexicons
    }
    engine = RuleEngine()
    expected = {
        form.concept_id: form.segments
        for form in lexicons["proto"].forms
    }
    correct, _ = engine.apply_rules(
        tuple(parse_rule(text) for text in east.inverse_rules),
        lexicons["east"].forms,
    )
    assert {form.concept_id: form.segments for form in correct} == expected
    reversed_order, _ = engine.apply_rules(
        tuple(parse_rule(text) for text in reversed(east.inverse_rules)),
        lexicons["east"].forms,
    )
    assert {
        form.concept_id: form.segments for form in reversed_order
    } != expected


def test_noise_is_off_by_default_and_deterministic_when_on() -> None:
    clean = generate_family(_definition("synthetic_regular"))
    assert clean.answer_key.noise_records == ()

    first = generate_family(_definition("synthetic_noisy"))
    second = generate_family(_definition("synthetic_noisy"))
    assert first.answer_key.noise_records == second.answer_key.noise_records
    assert first.payload.lexicons == second.payload.lexicons
    assert {
        record.kind for record in first.answer_key.noise_records
    } == {"irregular_form", "loan", "semantic_mismatch"}
    # The answer key's lexicons are the regular output; the payload is what the
    # model sees. They differ exactly where noise was applied.
    regular = {
        lexicon.variety_id: {
            form.concept_id: form.segments for form in lexicon.forms
        }
        for lexicon in first.answer_key.node_lexicons
    }
    observed = {
        lexicon.variety_id: {
            form.concept_id: form.segments for form in lexicon.forms
        }
        for lexicon in first.payload.lexicons
    }
    perturbed = {
        (node_id, concept_id)
        for node_id, forms in observed.items()
        for concept_id, segments in forms.items()
        if regular[node_id][concept_id] != segments
    }
    assert perturbed


def _score_with(committed: dict[str, tuple[str, ...]]):
    """Score a hand-built commit set without needing a live run."""
    result = generate_family(_definition("synthetic_regular"))
    key = result.answer_key
    by_child = {
        answer.node_id: answer.parent_node_id for answer in key.branches
    }
    rules = tuple(
        CommittedBranchRule(
            parent_node_id=by_child[child_id],
            child_node_id=child_id,
            dsl=dsl,
            confidence=1.0,
            directionality_rationale="scripted",
        )
        for child_id, cascade in committed.items()
        for dsl in cascade
    )

    return score_run(key, (), branch_rules=(rules, ("proto",), ()))


def test_the_true_cascade_scores_perfectly_and_a_wrong_branch_is_reported() -> None:
    """Directionality, checked mechanically rather than read out of the prose.

    `d1` innovated nothing in the control family. A rule scoped to it is a rule
    pointed at a branch that did not change, which is exactly the failure prompt
    04 asks the model to reason about and which nothing has been able to check.
    """
    truthful = _score_with(
        {"d2": ("x > k",), "d3": ("θ > t",), "d4": ("o > u",), "inner_a": ("f > p",)}
    )
    assert truthful.rule_precision == 1.0
    assert truthful.rule_recall == 1.0
    assert truthful.misdirected_rule_count == 0
    for branch in truthful.branches:
        if branch.functional_recovery_rate is not None:
            assert branch.functional_recovery_rate == 1.0

    # One change spelled twice is one change. The engine treats `x > k` and
    # `x > k / _` as identical, so counting both against a single true rule
    # would report a recall above 1.0 — which is not a rounding artifact but a
    # score claiming more was recovered than existed.
    duplicated = _score_with({"d2": ("x > k", "x > k / _")})
    assert duplicated.rule_precision == 1.0
    assert duplicated.rule_recall is not None and duplicated.rule_recall <= 1.0
    branch = next(item for item in duplicated.branches if item.node_id == "d2")
    assert len(branch.matched_rules) == 2
    assert branch.matched_true_rules == ("x > k",)
    assert branch.recall == 1.0

    misdirected = _score_with({"d1": ("f > p",), "inner_a": ("f > p",)})
    assert misdirected.misdirected_rule_count == 1
    assert "d1" in misdirected.as_dict()["misdirected_branches"]
    wrong: BranchScore = next(
        branch for branch in misdirected.branches if branch.node_id == "d1"
    )
    assert wrong.innovated is False
    assert wrong.committed_rules == ("f > p",)
    assert wrong.misdirected_rationales == ("scripted",)


def test_every_gold_evidence_kind_has_a_readable_note() -> None:
    """A report must not be the thing that crashes on a new enum member.

    `GoldEvidenceKind.SYNTHETIC` was added after `inspect-run` learned to print
    the kind, and the first synthetic run report raised `KeyError` instead of
    printing anything. The lookup goes through a helper with a fallback now, and
    this pins that every member is covered rather than merely survivable.
    """
    from cognate_reconstruction.inspect_run import GOLD_KIND_NOTE, gold_kind_note

    assert set(GOLD_KIND_NOTE) == set(GoldEvidenceKind)
    for kind in GoldEvidenceKind:
        assert gold_kind_note(kind)
    assert gold_kind_note(None) is None
    # The distinction the note exists to keep visible.
    assert "not an observation" in gold_kind_note(
        GoldEvidenceKind.RECONSTRUCTED
    )
    assert "not a language" in gold_kind_note(GoldEvidenceKind.SYNTHETIC)


# ---------------------------------------------------------------------------
# The same claim, committed either way, scores the same
#
# §9.2 of `docs/proto_inventory_design.md` says `score-synthetic` keeps rule
# precision, rule recall, functional recovery and `misdirected_rule_count`
# comparable across the migration by scoring an inventory's *derived* cascade.
# `_branch_claims` does that, and until now nothing exercised it: every test
# above builds `CommittedBranchRule` objects by hand, which is downstream of the
# branch that reads a commit. A regression there would leave the whole suite
# green while `score-synthetic` reported zero rules for every inventory session
# in a sweep — which reads as a model that committed nothing, not as a scorer
# that could not see it.
# ---------------------------------------------------------------------------

INNER_B_CHILDREN = ("d3", "d4")
"""`synthetic_regular`'s second subgroup: d3 innovated `t > θ`, d4 `u > o`.

Child-to-parent, that is `θ > t` on d3 and `o > u` on d4 — one rule each, on
different segments, so a derived cascade that mixed the two branches up would be
visible rather than absorbed.
"""


def _inventory_commit() -> CommittedProtoInventory:
    def commitment(reflexes, proto, support, rationale):
        return CorrespondenceCommitment(
            set_id=derive_set_id(
                reflexes,
                INNER_B_CHILDREN,
                segmentation_overlay_id=None,
                alignment_overlay_id=None,
            ),
            reflexes=reflexes,
            proto_segment=proto,
            support=support,
            confidence=1.0,
            rationale=rationale,
            directionality_rationale=f"scripted:{proto}",
        )

    return CommittedProtoInventory(
        request=CommitProtoInventoryArgs(
            node_id="inner_b",
            child_node_ids=INNER_B_CHILDREN,
            commitments=(
                commitment(("θ", "t"), "t", 9, "d3 spirantised *t."),
                commitment(("u", "o"), "u", 7, "d4 lowered *u."),
            ),
            residue_policy=ResiduePolicy.RETAIN_FROM_WITNESS,
            residue_witness_child_id="d4",
            anomalies=(),
            summary="Proto-inner_b *t and *u; d3 and d4 each innovated once.",
        )
    )


def _rules_commit() -> CommittedReconstruction:
    return CommittedReconstruction(
        request=CommitReconstructionArgs(
            node_id="inner_b",
            rules=(
                CommittedSoundRule(
                    dsl="θ > t",
                    source_child_ids=("d3",),
                    confidence=1.0,
                    rationale="d3 spirantised *t.",
                    directionality_rationale="scripted:t",
                ),
                CommittedSoundRule(
                    dsl="o > u",
                    source_child_ids=("d4",),
                    confidence=1.0,
                    rationale="d4 lowered *u.",
                    directionality_rationale="scripted:u",
                ),
            ),
            anomalies=(),
            summary="Proto-inner_b *t and *u; d3 and d4 each innovated once.",
        ),
        parsed_rules=(),
    )


def _completed_trajectory(
    commit, node_id: str = "inner_b", children=INNER_B_CHILDREN
) -> AgentTrajectory:
    now = datetime.now(UTC)
    return AgentTrajectory(
        trajectory_id="trajectory:scoring",
        schema_version="3.0",
        run_id="run:scoring",
        configuration_sha256="0" * 64,
        node_id=node_id,
        provider_adapter="ScriptedProvider",
        instruction_sha256="1" * 64,
        tool_schema_sha256="2" * 64,
        payload_schema_sha256="3" * 64,
        trajectory_schema_sha256="4" * 64,
        initial_payload=NodePromptPayload(
            node_id=node_id,
            active_children=tuple(
                NodeLexiconSummary(
                    node_id=child, name=child, form_count=1, concept_count=1
                )
                for child in children
            ),
        ),
        tool_definitions=(
            LLMToolDefinition(
                name="commit_reconstruction",
                description="commit",
                parameters={"type": "object"},
            ),
        ),
        messages=(LLMMessage(role=MessageRole.SYSTEM, content="system"),),
        metrics=AgentNodeMetrics(
            started_at=now,
            finished_at=now,
            duration_seconds=1.0,
            turn_count=4,
            provider_attempts=4,
            retry_count=0,
            tool_call_count=5,
            failed_tool_call_count=0,
            protocol_failure_count=0,
            inspection_tool_calls=2,
            sound_law_tests=0,
            cascade_tests=0,
            assembly_tests=1,
            committed_rule_count=0,
            committed_anomaly_count=0,
            committed_without_inspection=False,
            identity_without_testing=False,
        ),
        committed_reconstruction=commit,
        completed=True,
    )


def test_an_inventory_commit_scores_as_the_cascade_it_derives() -> None:
    """The migration invariant, as an equality rather than as prose."""
    key = generate_family(_definition("synthetic_regular")).answer_key

    inventory = score_run(key, (_completed_trajectory(_inventory_commit()),))
    rules = score_run(key, (_completed_trajectory(_rules_commit()),))

    assert inventory.as_dict() == rules.as_dict()
    assert inventory.rule_precision == 1.0
    assert inventory.misdirected_rule_count == 0
    for node_id in INNER_B_CHILDREN:
        branch = next(item for item in inventory.branches if item.node_id == node_id)
        assert branch.functional_recovery_rate == 1.0
        assert branch.recall == 1.0


def test_a_derived_rule_carries_its_commitments_directionality_rationale() -> None:
    """Which is what makes `misdirected_rationales` mean anything either way.

    A derived rule has no rationale of its own — it is a view of a commitment —
    so `DerivedBranchRules` records which set each rule came from and
    `_branch_claims` reads the rationale back off that set. Without the
    provenance, an inventory session would score as one that stated no direction
    at all.
    """
    claims = committed_branch_rules((_completed_trajectory(_inventory_commit()),))[0]
    assert {(rule.child_node_id, rule.dsl) for rule in claims} == {
        ("d3", "θ > t"),
        ("d4", "o > u"),
    }
    assert {rule.directionality_rationale for rule in claims} == {
        "scripted:t",
        "scripted:u",
    }


def test_an_inventory_that_names_a_branch_that_did_not_change_is_caught() -> None:
    """`misdirected_rule_count` has to survive the change of commit shape.

    It is the one measurement in this file that checks *directionality* rather
    than accuracy, and it works by noticing a rule scoped to a branch the answer
    key gave no rule at all. Under an inventory nobody scopes anything: the
    scope is derived from which child's reflex differs from the committed value.
    So this asserts the derivation points at the right branch by making it point
    at the wrong one.

    `inner_a`'s children are `d1`, which innovated nothing, and `d2`, which
    innovated `k > x`. Reconstructing the set ⟨d1 k : d2 x⟩ as `*x` says `d1`
    changed and `d2` did not, which is the whole claim reversed — and the
    derived cascade puts the rule on `d1`, where the answer key has none.
    """
    key = generate_family(_definition("synthetic_regular")).answer_key
    children = ("d1", "d2")
    backwards = CommittedProtoInventory(
        request=CommitProtoInventoryArgs(
            node_id="inner_a",
            child_node_ids=children,
            commitments=(
                CorrespondenceCommitment(
                    set_id=derive_set_id(
                        ("k", "x"),
                        children,
                        segmentation_overlay_id=None,
                        alignment_overlay_id=None,
                    ),
                    reflexes=("k", "x"),
                    proto_segment="x",
                    support=6,
                    confidence=1.0,
                    directionality_rationale="scripted, and backwards",
                ),
            ),
            residue_policy=ResiduePolicy.DROP,
            anomalies=(),
            summary="Backwards on purpose.",
        )
    )
    score = score_run(
        key, (_completed_trajectory(backwards, "inner_a", children),)
    )
    assert score.misdirected_rule_count == 1
    assert "d1" in score.as_dict()["misdirected_branches"]
    wrong = next(item for item in score.branches if item.node_id == "d1")
    assert wrong.innovated is False
    assert wrong.committed_rules == ("k > x",)
    assert wrong.misdirected_rationales == ("scripted, and backwards",)
