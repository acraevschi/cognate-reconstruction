"""Focused behavioral tests for R06 forward-prediction feasibility (`r06-forward-v1`)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cognate_reconstruction.evaluation.forward import (
    ETYMON_SPLIT_VERSION,
    FORWARD_EVALUATOR_VERSION,
    ForwardBranchHypothesis,
    mask_target_daughter_in_payload,
    verify_no_target_leakage,
)
from cognate_reconstruction.synthesis.diagnostics import build_case, load_suite
from tools.forward_prediction_probe import SUITE_PATH, run_study


@pytest.fixture(scope="module")
def study_results() -> dict:
    return run_study()


def test_etymon_cluster_split_and_shared_unit_leakage_refusal(study_results: dict) -> None:
    """Etymon split keeps shared-root concepts (t07, t08) together and refuses leaky splits."""
    assert study_results["evaluator_version"] == FORWARD_EVALUATOR_VERSION
    split = study_results["etymon_split"]
    assert split["split_version"] == ETYMON_SPLIT_VERSION
    assert split["development_etymon_count"] == 8
    assert split["held_out_etymon_count"] == 8
    assert split["development_concept_count"] == 8
    assert split["held_out_concept_count"] == 9
    assert "t07" in split["held_out_concept_ids"]
    assert "t08" in split["held_out_concept_ids"]
    assert split["concept_to_etymon_id"]["t07"] == "etym_t07"
    assert split["concept_to_etymon_id"]["t08"] == "etym_t07"
    assert split["shared_cognate_units_across_split"] == []

    leaky_check = study_results["leaky_etymon_split_check"]
    assert leaky_check["leaky_split_refused"] is True
    assert "forward_prediction_v1:etym_t07" in leaky_check["error_message"]


def test_no_key_or_target_leakage_across_payloads_and_tools(study_results: dict) -> None:
    """Withheld daughter forms and answer-key rules never appear in learner payloads or tool results."""
    for audit_name in ("sister_only_ancestor_inference", "masked_three_child_context"):
        audit = study_results["leakage_audits"][audit_name]
        assert audit["ok"] is True
        assert audit["withheld_concept_count"] == 9
        assert audit["bindings_empty"] is True
        assert audit["masked_daughter_test_forms_present"] == []
        assert audit["leaked_form_ids"] == []
        assert audit["answer_key_rules_in_payload"] is False

    # Verify negative control: if a withheld form remains in payload, verify_no_target_leakage flags it.
    suite = load_suite(SUITE_PATH)
    built = build_case(suite["cases"][0])
    partially_masked = mask_target_daughter_in_payload(
        built.payload,
        target_daughter_id="a",
        masked_concept_ids=["t02", "t03"],  # leaves t01 unmasked
        drop_historical_bindings=False,
    )
    bad_audit = verify_no_target_leakage(
        partially_masked,
        target_daughter_id="a",
        withheld_forms={"t01": ("p", "u", "tʃ", "e"), "t02": ("f", "u", "tʃ", "e")},
        answer_key=built.answer_key,
    )
    assert bad_audit["ok"] is False
    assert bad_audit["bindings_empty"] is False
    assert bad_audit["masked_daughter_test_forms_present"] == ["t01"]
    assert "a:t01" in bad_audit["leaked_form_ids"]


def test_forward_hypothesis_schema_direction_and_control_guards() -> None:
    """ForwardBranchHypothesis enforces explicit parent->child direction, valid rules, and control labels."""
    with pytest.raises(ValidationError):
        ForwardBranchHypothesis(
            hypothesis_id="bad_direction",
            parent_node_id="r",
            child_node_id="a",
            direction="child_to_parent",  # type: ignore[arg-type]
            rule_sources=("k > tʃ / _ i",),
        )

    with pytest.raises(ValidationError, match="parent_node_id and child_node_id must be distinct"):
        ForwardBranchHypothesis(
            hypothesis_id="same_node",
            parent_node_id="a",
            child_node_id="a",
            rule_sources=(),
        )

    with pytest.raises(ValidationError, match="Invalid forward rule"):
        ForwardBranchHypothesis(
            hypothesis_id="empty_target_insertion",
            parent_node_id="r",
            child_node_id="a",
            rule_sources=("Ø > t / _ #",),
        )

    with pytest.raises(ValidationError, match="given_ancestor_control requires privileged_operator_control=True"):
        ForwardBranchHypothesis(
            hypothesis_id="unflagged_oracle",
            parent_node_id="r",
            child_node_id="a",
            ancestor_regime="given_ancestor_control",
            privileged_operator_control=False,
            deployable_baseline=True,
        )


def test_non_invertibility_and_contrast_reductions(study_results: dict) -> None:
    """Forward cascades containing deletions and mergers are non-invertible by arrow swapping."""
    inv_a = study_results["branch_invertibility"]["a"]
    assert inv_a["invertible"] is False
    assert inv_a["syntactically_non_invertible_rules"] == ["t > Ø / _ #"]
    assert inv_a["verified_inverse_rules"] == []
    assert inv_a["naive_arrow_swap_recovery_rate"] < 0.75

    reduction_sources = {r["source"]: r for r in inv_a["contrast_reductions"]}
    assert "i > e / _ #" in reduction_sources
    assert reduction_sources["i > e / _ #"]["merges"] is True
    assert reduction_sources["i > e / _ #"]["deletes"] is False
    assert "t > Ø / _ #" in reduction_sources
    assert reduction_sources["t > Ø / _ #"]["deletes"] is True

    # Derived child-to-parent rules from (b, c) inventory at r also flag c as non-invertible.
    recon_q = study_results["ancestor_reconstructions"]["intended_q_label"]
    assert recon_q["derived_non_invertible_child_ids"] == ["c"]


def test_observational_equivalence_and_held_out_generalization(study_results: dict) -> None:
    """Intended (*q), equivalent symbol (*ɢ), and 2-stage chronology all achieve 8/8 on held-out test."""
    rows = {r["hypothesis_id"]: r for r in study_results["summary_table"]}

    h1 = rows["h1_intended_cascade"]
    h2 = rows["h2_equivalent_ancestral_label"]
    h2b = rows["h2b_equivalent_two_stage_chronology"]

    for h in (h1, h2, h2b):
        assert h["dev_exact_count"] == 8
        assert h["dev_exact_rate"] == 1.0
        assert h["test_validated_exact_count"] == 8
        assert h["test_validated_exact_rate"] == 1.0
        assert h["test_validated_mean_ned"] == 0.0
        assert h["test_proto_corpus_bcubed_f1"] == 1.0
        assert h["test_proto_bijective_relabelling"] is True

    # Raw proto-form exactness against generator's arbitrary *q penalizes h2 (*ɢ),
    # whereas corpus contrast equivalence (1.0) and held-out forward prediction (8/8) do not.
    assert h1["test_proto_raw_exact_rate"] == 1.0
    assert h2["test_proto_raw_exact_rate"] == 0.625

    # Unattested inferred inputs (t01 *p u k i, t05 *p a m u t, t06 *q u l i, t07 *m a q i, t08 *m a q a k i)
    # and unattested predicted reflexes (t01, t02, t04, t06, t07, t08) are tracked explicitly.
    h1_test = study_results["test_evaluations"]["h1_intended_cascade"]
    assert h1_test["unattested_inferred_input_count"] == 5
    assert h1_test["unattested_predicted_reflex_count"] == 6


def test_overfit_bleeding_and_direct_sister_baselines_rejected_on_held_out(study_results: dict) -> None:
    """Overfit dev hypotheses (8/8 dev) and single-sister baselines fail on held-out test."""
    rows = {r["hypothesis_id"]: r for r in study_results["summary_table"]}

    # Overfit hypotheses match h1 on dev (8/8) but collapse to 1/8 on held-out test.
    h4 = rows["h4_overfit_dev_lookup"]
    assert h4["dev_exact_count"] == 8
    assert h4["test_validated_exact_count"] == 1
    assert h4["exception_bound_exceeded"] is True
    assert h4["single_etymon_dev_rule_count"] == 4

    h4b = rows["h4b_overfit_word_specific_zero_exceptions"]
    assert h4b["dev_exact_count"] == 8
    assert h4b["test_validated_exact_count"] == 1
    assert h4b["lexical_exception_count"] == 0
    assert h4b["single_etymon_dev_rule_count"] == 6

    # Bleeding order (h3), unscoped rules (h5), identity (h6), and direct sister baselines (h7, h8)
    # are all strictly outperformed by h1/h2 (8/8) on held-out test.
    assert rows["h3_wrong_order_bleeding"]["test_validated_exact_count"] == 5
    assert rows["h5_naive_unscoped_inventory_rules"]["test_validated_exact_count"] == 5
    assert rows["h6_identity_from_inferred_proto"]["test_validated_exact_count"] == 1
    assert rows["h7_direct_sister_b_cascade"]["test_validated_exact_count"] == 5
    assert rows["h7b_copy_sister_b"]["test_validated_exact_count"] == 0
    assert rows["h8_direct_sister_c_cascade"]["test_validated_exact_count"] == 5
    assert rows["h8b_copy_sister_c"]["test_validated_exact_count"] == 2


def test_missing_output_denominators_and_would_empty_form(study_results: dict) -> None:
    """Missing outputs reduce planned-set exact accuracy and coverage; would_empty_form is refused."""
    h9_dev = study_results["dev_evaluations"]["h9_missing_output_and_would_empty"]
    h9_test = study_results["test_evaluations"]["h9_missing_output_and_would_empty"]

    # On dev d06 (`s a`), `s a > Ø` triggers WOULD_EMPTY_FORM and carries `s a` through unchanged.
    d06_rec = next(item for item in h9_dev["per_concept"] if item["concept_id"] == "d06")
    assert d06_rec["would_empty_form_triggered"] is True
    assert d06_rec["predicted_segments"] == ["s", "a"]

    # On held-out test, t06-t08 have missing ancestor inputs (3 missing of 8 validated).
    val = h9_test["validated_only"]
    assert val["planned_count"] == 8
    assert val["available_count"] == 5
    assert val["missing_count"] == 3
    assert val["coverage"] == 0.625
    assert val["exact_count"] == 5
    assert val["exact_rate"] == 0.625
    assert val["conditional_available_exact_rate"] == 1.0
    assert val["mean_ned"] == 0.0
    assert val["unconditional_mean_ned"] == 0.375


def test_given_vs_inferred_ancestor_and_circularity_control(study_results: dict) -> None:
    """Pan-sister merger u01 separates inferred-ancestor (0/1), circular unmasked (1/1), and given-oracle (1/1)."""
    circ = study_results["in_sample_circularity_control"]
    assert circ["withheld_inferred_u01_exact"] == 0
    assert circ["circular_unmasked_u01_exact"] == 1
    assert circ["privileged_given_oracle_u01_exact"] == 1

    h10 = next(
        r for r in study_results["summary_table"]
        if r["hypothesis_id"] == "h10_privileged_given_ancestor_oracle"
    )
    assert h10["privileged_operator_control"] is True
    assert h10["deployable_baseline"] is False
    assert h10["test_all_planned_exact_count"] == 9
    assert h10["test_all_planned_exact_rate"] == 1.0


def test_diasim_diagnostics_pbebench_ordering_and_r05_crosscheck(study_results: dict) -> None:
    """Residual autopsy, before/after cascade diffs, 24-permutation ordering, and R05 cross-check agree."""
    diag = study_results["diasim_style_diagnostics"]
    autopsy = diag["h3_bleeding_dev_residual_autopsy"]
    assert autopsy["evidence_channel"] == "development_fitting"
    assert autopsy["mismatched_concept_ids"] == ["d01", "d02"]
    assert autopsy["recurring_mismatch_clusters"][0]["pattern"] == "k != tʃ / a_e"

    # Reordering h3 -> h1 repairs d01, d02 on dev and t01, t02, t08 on test with 0 newly broken.
    assert diag["reordering_h3_to_h1_dev_diff"]["repaired_concept_ids"] == ["d01", "d02"]
    assert diag["reordering_h3_to_h1_dev_diff"]["newly_broken_concept_ids"] == []
    assert diag["reordering_h3_to_h1_test_diff"]["repaired_concept_ids"] == ["t01", "t02", "t08"]
    assert diag["reordering_h3_to_h1_test_diff"]["newly_broken_concept_ids"] == []

    # Adding `f > p / #_` to direct sister b cascade repairs t01, t03, t05 but newly breaks t02.
    b_diff = diag["direct_sister_b_add_f_to_p_test_diff"]
    assert b_diff["repaired_concept_ids"] == ["t01", "t03", "t05"]
    assert b_diff["newly_broken_concept_ids"] == ["t02"]

    # Auxiliary 4! = 24 rule-ordering check: exactly 12/24 orders (those with k > tʃ / _i before i > e / _#) win.
    ord_dev = study_results["pbebench_style_auxiliary_ordering"]["dev_permutations"]
    ord_test = study_results["pbebench_style_auxiliary_ordering"]["test_permutations"]
    assert ord_dev["permutation_count"] == 24
    assert ord_dev["exact_match_permutation_count"] == 12
    assert ord_test["permutation_count"] == 24
    assert ord_test["exact_match_permutation_count"] == 12

    # R05 cross-check: preserving tied candidates at x rescues forward prediction on x -> a from 8/12 to 12/12.
    r05 = study_results["r05_two_level_propagation_crosscheck"]
    assert r05["from_a1_collapsed_x_exact_count"] == 8
    assert r05["from_c1_preserved_x_exact_count"] == 12
    assert r05["repaired_by_preserving_x_candidates"] == ["c001", "c002", "c003", "c004"]
    assert r05["newly_broken_concept_ids"] == []
