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

from cognate_reconstruction.rules.engine import RuleEngine
from cognate_reconstruction.rules.parser import parse_rule
from cognate_reconstruction.schemas.historical import (
    GoldEvidenceKind,
    HistoricalFormRole,
)
from cognate_reconstruction.schemas.synthetic import SyntheticFamilyDefinition
from cognate_reconstruction.synthesis import generate_family, score_run
from cognate_reconstruction.synthesis.scoring import (
    BranchScore,
    CommittedBranchRule,
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
