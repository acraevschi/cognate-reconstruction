"""Focused behavioral tests for two-level intermediate propagation and robustness."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cognate_reconstruction.traversal.assembler import ProtoInventoryAssembler
from tools.propagation_robustness_probe import (
    BANKED_RUNS,
    SUITE_PATH,
    replay_banked_runs,
    run_presentation_invariance_checks,
    run_two_level_study,
)


def test_assembler_rejects_invalid_tied_confidence_threshold() -> None:
    with pytest.raises(ValueError, match="tied_confidence_threshold"):
        ProtoInventoryAssembler(tied_confidence_threshold=0.0)
    with pytest.raises(ValueError, match="tied_confidence_threshold"):
        ProtoInventoryAssembler(tied_confidence_threshold=1.1)


def test_two_level_propagation_asymmetry_and_interventions() -> None:
    assert SUITE_PATH.exists()
    arms = run_two_level_study()

    a1 = arms["a1_single_winner_absent_on_tie"]
    a2 = arms["a2_single_winner_over_retain"]
    b1 = arms["b1_privileged_oracle_x_full"]
    b2 = arms["b2_privileged_oracle_x_segments_only"]
    c1 = arms["c1_tied_beam_retention"]
    c2 = arms["c2_leaf_witness_at_r"]
    d1 = arms["d1_tree_rotation_y_before_x"]

    # Asymmetry at x -> r: premature deletion / tie-collapse at x (a1) drops r to 4/8,
    # whereas over-retention at x (a2) is discounted at r (8/8 at r while x stays 4/8).
    assert a1["x_decisions"]["primary_correct"] == 4
    assert a1["r_decisions"]["primary_correct"] == 4
    assert a1["r_validated"]["top_exact_matches"] == 6
    assert a1["r_validated"]["cognate_unit_exact_matches"] == 6

    assert a2["x_decisions"]["primary_correct"] == 4
    assert a2["r_decisions"]["primary_correct"] == 8
    assert a2["r_validated"]["top_exact_matches"] == 10
    assert a2["r_validated"]["cognate_unit_exact_matches"] == 10

    # Option 1 privileged controls: full (b1) vs segments-only (b2)
    assert b1["origin_metadata"]["privileged_operator_control"] is True
    assert b1["origin_metadata"]["deployable_baseline"] is False
    assert b1["r_validated"]["top_exact_matches"] == 10
    assert b1["r_validated"]["cognate_unit_exact_matches"] == 10
    assert b1["r_decisions"]["primary_correct"] == 8
    # Unrecoverable root merger L1 (c011 *w o -> *l o) remains false even under oracle x
    assert b1["r_underdetermined"]["concepts"]["c011"]["top_segments"] == ["l", "o"]
    assert b1["r_underdetermined"]["concepts"]["c011"]["top_exact"] is False

    assert b2["origin_metadata"]["privileged_operator_control"] is True
    assert b2["r_validated"]["top_exact_matches"] == 10
    assert b2["r_validated"]["cognate_unit_exact_matches"] == 0
    assert b2["r_decisions"]["primary_correct"] == 0
    assert b2["r_decisions"]["counts_by_reading"] == {"unit_missing": 8}

    # Option 2a: retaining tied alternatives in x's beam (c1) rescues r to 8/8 and 10/10
    # and preserves both *k o and *k o t on L2 (c012) at r.
    assert c1["r_decisions"]["primary_correct"] == 8
    assert c1["r_validated"]["top_exact_matches"] == 10
    assert c1["r_validated"]["cognate_unit_exact_matches"] == 10
    assert c1["beam_widths"]["x_multi_candidate_concepts"] == [
        "c001",
        "c002",
        "c003",
        "c004",
        "c012",
    ]
    assert {tuple(c["segments"]) for c in c1["beam_widths"]["r_l2_candidates"]} == {
        ("k", "o"),
        ("k", "o", "t"),
    }
    assert c1["r_underdetermined"]["concepts"]["c012"]["beam_exact"] is True

    # Option 2b: raw leaf witnesses at r (c2) rescue R1-R4 via non-invertible <x Ø : y g> -> *k
    # but cannot restore -t on L2 (c012) when both x and y lost -t in their beams.
    assert c2["r_decisions"]["primary_correct"] == 8
    assert c2["r_non_invertible_child_ids"] == ["x"]
    assert [c["segments"] for c in c2["beam_widths"]["r_l2_candidates"]] == [["k", "o"]]
    assert c2["l2_root_restoration_check"] == {
        "ok": False,
        "error_code": "restoration-without-outgroup",
        "error_message": "1 restoration(s) were requested at a node with no out-group, so nothing can license one",
    }

    # Option 3 tree rotation ((c,d)y,(a,b)x)r; changes real information availability at x
    assert d1["traversal_order"] == ["y", "x", "r"]
    assert d1["x_outgroup_node_ids"] == ["c", "d", "y"]
    assert d1["x_decisions"]["primary_correct"] == 8
    assert d1["r_decisions"]["primary_correct"] == 8


def test_presentation_invariance_and_weight_sensitivity() -> None:
    inv = run_presentation_invariance_checks()

    assert inv["commitment_order_reversal"]["x_top_forms_identical"] is True
    assert inv["commitment_order_reversal"]["r_top_forms_identical"] is True
    assert inv["commitment_order_reversal"]["x_evidence_revision_identical"] is True

    assert inv["child_order_swap_ba_vs_ab"]["x_evidence_revision_changed"] is True
    assert inv["child_order_swap_ba_vs_ab"]["x_top_forms_identical"] is True
    assert inv["child_order_swap_ba_vs_ab"]["r_top_forms_identical"] is True

    dup = inv["source_duplication"]
    assert dup["single_form_candidate_count_orig"] == 1
    assert dup["single_form_candidate_count_dup"] == 1
    assert dup["single_form_probability_orig"] == 1.0
    assert dup["single_form_probability_dup"] == 1.0
    assert dup["single_form_source_count_orig"] == 1
    assert dup["single_form_source_count_dup"] == 2
    assert dup["two_variant_equal_probs"] == {"f i": 0.5, "f i k": 0.5}
    assert dup["two_variant_duplicated_probs"] == {"f i k": 0.6667, "f i": 0.3333}

    sens = inv["operational_weight_sensitivity"]
    assert sens["l2_r_decided_by_tie_break_at_095"] is False
    assert sens["l2_r_decided_by_tie_break_at_100"] is True
    assert sens["l2_r_candidates_at_identity_100"] == [
        {"segments": ["k", "o"], "probability": 0.5},
        {"segments": ["k", "o", "t"], "probability": 0.5},
    ]
    assert sens["validated_r_top_forms_identical_095_vs_100"] is True


def test_banked_live_replays_preserve_single_winner_and_expand_ties() -> None:
    if not all((ROOT / meta["run_dir"] / "checkpoint.json").exists() for meta in BANKED_RUNS.values()):
        pytest.skip("banked experiment run directories not present")
    replays = replay_banked_runs()

    for label in ("b-gemini", "c-gemini-r04", "c-local-qwen38-27b-r04"):
        entry = replays[label]
        assert entry["single_winner_reproduces_banked_beam_exactly"] is True
        assert entry["non_tied_concepts_changed_count"] == 0
        for cid, detail in entry["tied_concepts"].items():
            assert len(detail["x_single_candidates"]) == 1
            assert len(detail["x_tied_candidates"]) == 2
            assert detail["x_single_decided_by_tie_break"] is False
            assert detail["x_tied_decided_by_tie_break"] is True
            assert [c["probability"] for c in detail["x_tied_candidates"]] == [0.5, 0.5]
