"""Focused offline tests for the R07 source-linked hypothesis critic and evaluation prototype."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from cognate_reconstruction.agent.schemas import LLMMessage, MessageRole
from cognate_reconstruction.benchmarks.ledger import read_run_resources
from cognate_reconstruction.evaluation import (
    DEFAULT_CRITIC_MODE as EXPORTED_DEFAULT_CRITIC_MODE,
    filter_llm_assessment_with_deterministic_guard as exported_filter_guard,
    run_default_critic_report as exported_run_default_critic_report,
    run_default_hypothesis_critic as exported_run_default_hypothesis_critic,
    run_deterministic_full_detector as exported_run_deterministic_full_detector,
)
from cognate_reconstruction.evaluation.critic import (
    CRITIC_CORPUS_VERSION,
    CRITIC_EVALUATOR_VERSION,
    CRITIC_TOOL_NAME,
    DEFAULT_CRITIC_MODE,
    CritiqueVerdict,
    DefectCategory,
    FakeCriticProvider,
    UncertaintyLabel,
    build_blind_evaluation_sheet,
    build_critic_user_prompt,
    critic_system_instructions,
    critic_tool_definition,
    evaluate_forward_revision_on_packet,
    filter_llm_assessment_with_deterministic_guard,
    parse_critic_response,
    run_default_critic_report,
    run_default_hypothesis_critic,
    run_deterministic_full_detector,
    run_deterministic_mechanical_detector,
    run_existing_residue_ambiguity_baseline,
    run_fixed_evidence_checklist_baseline,
    run_llm_critic_on_packets,
    score_critic_assessments,
    to_model_visible_packet,
    verify_no_critic_leakage,
)
from tools.hypothesis_critic_probe import (
    CORPUS_PATH,
    GEMINI_PRICE_TABLE,
    ROOT,
    audit,
    controls,
    evaluate,
    freeze,
    load_corpus_packets,
    run_live,
    verify_independent_ground_truth,
)
from tools.experiment_batch import build_ledger, load_plan, refusal


def test_corpus_loading_and_independent_ground_truth_derivations() -> None:
    raw, packets = load_corpus_packets(CORPUS_PATH)
    assert raw["corpus_version"] == CRITIC_CORPUS_VERSION
    assert len(packets) == 18

    dev_packets = [p for p in packets if p.split == "development"]
    eval_packets = [p for p in packets if p.split == "held_out_evaluation"]
    gold_packets = [p for p in packets if p.split == "offline_gold_residual_only"]
    assert len(dev_packets) == 6
    assert len(eval_packets) == 10
    assert len(gold_packets) == 2

    # Verify independent ground-truth derivations against Stage C, R05, and R06 fixtures
    verification = verify_independent_ground_truth(packets)
    assert verification["ok"] is True
    assert verification["checked_count"] == 11
    for check_id, item in verification["checks"].items():
        assert item["ok"] is True, f"Independent derivation check failed on {check_id}: {item}"

    # Verify source-link integrity: every required ground-truth pointer exists in the packet's evidence universe
    for pkt in dev_packets + eval_packets:
        gt = pkt.ground_truth
        ev = pkt.evidence
        valid_source_ids = (
            set(ev.active_child_forms.keys())
            | set(ev.outgroup_forms.keys())
            | set((ev.prior_node_commit_summary or {}).get("leaf_reflexes", {}).keys())
            | set((ev.forward_execution_summary or {}).get("observed_forms", {}).keys())
        )
        valid_call_ids = {
            pkt.claim.validation_call_id,
            *(str(c) for c in ev.trajectory_navigation_summary.get("inspected_call_ids", ())),
        }
        if ev.prior_node_commit_summary and "validation_call_id" in ev.prior_node_commit_summary:
            valid_call_ids.add(str(ev.prior_node_commit_summary["validation_call_id"]))
        valid_set_ids = set(pkt.claim.set_ids)
        if ev.prior_node_commit_summary and "set_id" in ev.prior_node_commit_summary:
            valid_set_ids.add(str(ev.prior_node_commit_summary["set_id"]))
        valid_column_indices = set(pkt.claim.column_indices) | {0, 1, 2, 3, 4}

        assert set(gt.required_source_ids).issubset(valid_source_ids), pkt.packet_id
        assert set(gt.required_call_ids).issubset(valid_call_ids), pkt.packet_id
        assert set(gt.required_set_ids).issubset(valid_set_ids), pkt.packet_id
        assert set(gt.required_column_indices).issubset(valid_column_indices), pkt.packet_id


def test_evidence_channel_boundary_and_leakage_guards() -> None:
    _, packets = load_corpus_packets(CORPUS_PATH)
    dev_packets = [p for p in packets if p.split == "development"]
    eval_packets = [p for p in packets if p.split == "held_out_evaluation"]
    gold_packets = [p for p in packets if p.split == "offline_gold_residual_only"]

    # Offline held-out scorer packets must be mechanically refused by to_model_visible_packet
    for gp in gold_packets:
        with pytest.raises(ValueError, match="must never be exposed"):
            to_model_visible_packet(gp)

    visible_dev = [to_model_visible_packet(p) for p in dev_packets]
    visible_eval = [to_model_visible_packet(p) for p in eval_packets]

    leak_dev = verify_no_critic_leakage(packets, visible_dev)
    leak_eval = verify_no_critic_leakage(packets, visible_eval)
    assert leak_dev["ok"] is True
    assert leak_eval["ok"] is True

    # Planted leakage checks: injecting forbidden keys or internal packet IDs must be caught
    tampered = dict(visible_eval[0])
    tampered["ground_truth"] = {"is_defective": True}
    tampered_res = verify_no_critic_leakage(packets, [tampered])
    assert tampered_res["ok"] is False
    assert "ground_truth" in tampered_res["forbidden_keys_present"]

    leaked_id_res = verify_no_critic_leakage(
        packets,
        [{"packet_id": "P04", "leaked_id": "eval_e01_upstream_tie_collapse"}],
    )
    assert leaked_id_res["ok"] is False
    assert "eval_e01_upstream_tie_collapse" in leaked_id_res["leaked_internal_packet_ids"]


def test_no_mutation_and_forward_revision_evaluation() -> None:
    _, packets = load_corpus_packets(CORPUS_PATH)
    by_id = {p.packet_id: p for p in packets}

    e05 = by_id["eval_e05_bleeding_order_and_leaky_revision"]
    e05_before = copy.deepcopy(e05.model_dump(mode="json"))

    fwd_raw = json.loads((CORPUS_PATH.parent / "forward-prediction-v1.json").read_text(encoding="utf-8"))["cases"][0]
    dev_cids = list(fwd_raw["development_concept_ids"])
    proto_map = {
        entry["concept_id"]: list(entry["segments"])
        for entry in fwd_raw["family"]["proto_lexicon"]
    }
    anc_q = {cid: list(proto_map[cid]) for cid in dev_cids}
    from cognate_reconstruction.synthesis.diagnostics import build_case

    built_fwd = build_case(fwd_raw)
    lex_a = next(lex for lex in built_fwd.payload.lexicons if lex.variety_id == "a")
    obs_a = {f.concept_id: list(f.segments) for f in lex_a.forms if f.concept_id in dev_cids}
    anc_q_before = copy.deepcopy(anc_q)
    obs_a_before = copy.deepcopy(obs_a)

    rev_eval = evaluate_forward_revision_on_packet(
        anc_q,
        obs_a,
        e05.claim.forward_cascade_rules,
        e05.claim.candidate_revision_rules,
        parent_node_id="r",
        child_node_id="a",
    )
    assert rev_eval["mismatched_concept_ids"] == ["d01", "d02"]
    assert rev_eval["repaired_concept_ids"] == ["d01", "d02"]
    assert rev_eval["newly_broken_concept_ids"] == ["d03"]
    assert rev_eval["delta_validated_exact_count"] == 1
    assert anc_q == anc_q_before
    assert obs_a == obs_a_before
    assert e05.model_dump(mode="json") == e05_before


def test_false_positive_controls_and_deterministic_detectors() -> None:
    _, packets = load_corpus_packets(CORPUS_PATH)
    dev_packets = [p for p in packets if p.split == "development"]
    eval_packets = [p for p in packets if p.split == "held_out_evaluation"]

    # Mechanical detector: 3/5 on held-out eval, 0 false objections
    mech_eval = score_critic_assessments(
        eval_packets,
        [run_deterministic_mechanical_detector(p) for p in eval_packets],
    )
    assert mech_eval["actionable_true_positives"] == 3
    assert mech_eval["false_objections"] == 0
    assert mech_eval["actionable_precision"] == 1.0
    assert mech_eval["matched_pair_exact_count"] == 3

    # Full trace+witness detector: 3/3 on dev and 5/5 on held-out eval, 0 false objections
    full_dev_assessments = [run_deterministic_full_detector(p) for p in dev_packets]
    full_dev = score_critic_assessments(dev_packets, full_dev_assessments)
    assert full_dev["actionable_true_positives"] == 3
    assert full_dev["false_objections"] == 0
    assert full_dev["matched_pair_exact_count"] == 3

    full_eval_assessments = [run_deterministic_full_detector(p) for p in eval_packets]
    full_eval = score_critic_assessments(eval_packets, full_eval_assessments)
    assert full_eval["actionable_true_positives"] == 5
    assert full_eval["false_objections"] == 0
    assert full_eval["matched_pair_exact_count"] == 5

    # Explicitly check every legitimate control has DefectCategory.NONE and no false objection
    by_id = {a.packet_id: a for a in full_dev_assessments + full_eval_assessments}
    legit_ids = [p.packet_id for p in dev_packets + eval_packets if not p.ground_truth.is_defective]
    assert len(legit_ids) == 8
    for pid in legit_ids:
        assert by_id[pid].verdict in (
            CritiqueVerdict.LEGITIMATE_NO_OBJECTION,
            CritiqueVerdict.GENUINE_AMBIGUITY_NOTED,
        ), pid
        assert by_id[pid].defect_category is DefectCategory.NONE, pid


def test_baselines_and_fake_critic_provider_modes() -> None:
    _, packets = load_corpus_packets(CORPUS_PATH)
    eval_packets = [p for p in packets if p.split == "held_out_evaluation"]

    residue_base = score_critic_assessments(
        eval_packets,
        [run_existing_residue_ambiguity_baseline(p) for p in eval_packets],
    )
    assert residue_base["actionable_true_positives"] == 1
    assert residue_base["false_objections"] == 0
    assert residue_base["matched_pair_exact_count"] == 1

    checklist_base = score_critic_assessments(
        eval_packets,
        [run_fixed_evidence_checklist_baseline(p) for p in eval_packets],
    )
    assert checklist_base["actionable_true_positives"] == 1
    assert checklist_base["false_objections"] == 3
    assert checklist_base["matched_pair_exact_count"] == 0

    accurate = score_critic_assessments(
        eval_packets,
        run_llm_critic_on_packets(eval_packets, FakeCriticProvider(mode="accurate")),
    )
    assert accurate["actionable_true_positives"] == 5
    assert accurate["false_objections"] == 0
    assert accurate["pointer_validity_rate"] == 1.0
    assert accurate["matched_pair_exact_count"] == 5

    over_obj = score_critic_assessments(
        eval_packets,
        run_llm_critic_on_packets(eval_packets, FakeCriticProvider(mode="over_objecting")),
    )
    assert over_obj["actionable_true_positives"] == 5
    assert over_obj["false_objections"] == 4
    assert over_obj["matched_pair_exact_count"] == 1

    relabeller = score_critic_assessments(
        eval_packets,
        run_llm_critic_on_packets(eval_packets, FakeCriticProvider(mode="verbose_relabeller")),
    )
    assert relabeller["actionable_true_positives"] == 1
    assert relabeller["false_objections"] == 0
    assert relabeller["matched_pair_exact_count"] == 1

    hallucinated = score_critic_assessments(
        eval_packets,
        run_llm_critic_on_packets(eval_packets, FakeCriticProvider(mode="hallucinated_pointers")),
    )
    assert hallucinated["defect_detections"] == 5
    assert hallucinated["actionable_true_positives"] == 0
    assert hallucinated["pointer_validity_rate"] == 0.0
    assert hallucinated["matched_pair_exact_count"] == 0

    # Verify parse_critic_response handles fenced JSON and malformed text cleanly
    p0 = eval_packets[0]
    fenced_msg = LLMMessage(
        role=MessageRole.ASSISTANT,
        content='```json\n{"packet_id": "P04", "verdict": "legitimate_no_objection", "defect_category": "none", "uncertainty_label": "no_defect", "cited_source_ids": [], "cited_call_ids": [], "cited_set_ids": [], "cited_column_indices": [], "observed_discrepancy": "None.", "potential_consequence": "None.", "discriminating_check_or_falsifier": "Check.", "repaired_examples": [], "newly_broken_examples": []}\n```',
    )
    parsed = parse_critic_response(fenced_msg, packet=p0)
    assert parsed.verdict is CritiqueVerdict.LEGITIMATE_NO_OBJECTION

    malformed_msg = LLMMessage(role=MessageRole.ASSISTANT, content="not json at all")
    malformed = parse_critic_response(malformed_msg, packet=p0)
    assert malformed.verdict is CritiqueVerdict.GENUINE_AMBIGUITY_NOTED


def test_freeze_run_live_and_evaluate_with_fake_completion(tmp_path: Path) -> None:
    batch_dir = tmp_path / "r07-rehearsal"
    freeze_res = freeze(batch_dir)
    assert (batch_dir / "manifest.r07-critic.json").exists()
    assert (batch_dir / "plan.json").exists()
    assert (batch_dir / "preregistration.md").exists()
    assert (batch_dir / "inputs/held-out-visible-packets.json").exists()
    assert freeze_res["resources"]["cost_reservation_usd"] <= 1.50

    _, packets = load_corpus_packets(CORPUS_PATH)
    fake_provider = FakeCriticProvider(mode="accurate", packets=packets)

    def _fake_completion(**kwargs: Any) -> Any:
        messages = kwargs["messages"]
        user_text = messages[-1]["content"]
        llm_msgs = [
            LLMMessage(role=MessageRole.SYSTEM, content=messages[0]["content"]),
            LLMMessage(role=MessageRole.USER, content=user_text),
        ]
        prov_resp = fake_provider.complete(llm_msgs)
        tc = prov_resp.message.tool_calls[0]
        tool_call_obj = SimpleNamespace(
            id=tc.call_id,
            function=SimpleNamespace(
                name=tc.name,
                arguments=json.dumps(tc.arguments, sort_keys=True),
            ),
        )
        msg_obj = SimpleNamespace(
            content="",
            tool_calls=[tool_call_obj],
            reasoning_content="Verified packet pointers and evidence channels.",
        )
        choice_obj = SimpleNamespace(message=msg_obj, finish_reason="tool_calls")
        usage_obj = SimpleNamespace(
            prompt_tokens=1500,
            completion_tokens=400,
            total_tokens=1900,
            prompt_tokens_details=SimpleNamespace(cached_tokens=500),
            completion_tokens_details=SimpleNamespace(reasoning_tokens=150),
        )
        return SimpleNamespace(
            id=f"resp-{tc.call_id}",
            model="gemini/gemini-3.8-flash",
            choices=[choice_obj],
            usage=usage_obj,
        )

    run_dir = batch_dir / "runs" / "r07-gemini-r07-critic"
    live_res = run_live(
        batch_dir / "inputs",
        run_dir,
        provider_config_path=batch_dir / "inputs/gemini-r07-critic.provider-config.json",
        price_table_path=GEMINI_PRICE_TABLE,
        completion_fn=_fake_completion,
        no_preflight=True,
    )
    assert live_res["packets_completed"] == 10
    assert live_res["status"] == "completed"

    # Verify ledger certification via read_run_resources and experiment_batch
    ledger_row = read_run_resources(run_dir)
    assert ledger_row.outcome == "committed"
    assert ledger_row.cost_known is True
    assert ledger_row.history_certified is True
    assert ledger_row.input_tokens == 15000
    assert ledger_row.output_tokens == 4000
    assert ledger_row.cached_input_tokens == 5000
    assert ledger_row.reasoning_output_tokens == 1500

    eval_report = evaluate(run_dir)
    assert eval_report["scored"]["actionable_true_positives"] == 5
    assert eval_report["scored"]["false_objections"] == 0
    assert eval_report["scored"]["matched_pair_exact_count"] == 5
    assert eval_report["stage_gate"]["usable"] is True
    assert "deterministic_guard_filtered_scored" in eval_report
    assert (
        eval_report["deterministic_guard_filtered_scored"][
            "actionable_true_positives"
        ]
        == 5
    )


def test_default_critic_mode_guard_filter_and_audit_subcommand(tmp_path: Path) -> None:
    assert DEFAULT_CRITIC_MODE == "deterministic_full"
    assert EXPORTED_DEFAULT_CRITIC_MODE == DEFAULT_CRITIC_MODE
    assert exported_filter_guard is filter_llm_assessment_with_deterministic_guard
    assert exported_run_default_critic_report is run_default_critic_report
    assert exported_run_default_hypothesis_critic is run_default_hypothesis_critic
    assert exported_run_deterministic_full_detector is run_deterministic_full_detector

    _, packets = load_corpus_packets(CORPUS_PATH)
    eval_packets = [p for p in packets if p.split == "held_out_evaluation"]
    by_blind = {p.blind_code: p for p in eval_packets}

    # Verify include_comparative_trace_rules=False falls back to mechanical detector
    mech_fallback = score_critic_assessments(
        eval_packets,
        [
            run_deterministic_full_detector(
                p, include_comparative_trace_rules=False
            )
            for p in eval_packets
        ],
    )
    assert mech_fallback["actionable_true_positives"] == 3
    assert mech_fallback["matched_pair_exact_count"] == 3

    # Verify run_default_hypothesis_critic and run_default_critic_report default to deterministic_full
    default_single = [run_default_hypothesis_critic(p) for p in eval_packets]
    default_scored = score_critic_assessments(eval_packets, default_single)
    assert default_scored["actionable_true_positives"] == 5
    assert default_scored["false_objections"] == 0
    assert default_scored["matched_pair_exact_count"] == 5

    default_report = run_default_critic_report(eval_packets)
    assert default_report["mode"] == "deterministic_full"
    assert default_report["default_critic_mode"] == "deterministic_full"
    assert default_report["actionable_true_positives"] == 5
    assert default_report["false_objections"] == 0
    assert default_report["matched_pair_exact_count"] == 5
    assert default_report["scored"]["actionable_true_positives"] == 5

    # Verify filter_llm_assessment_with_deterministic_guard strips hallucinated pointers
    halluc_provider = FakeCriticProvider(mode="hallucinated_pointers", packets=eval_packets)
    guarded_halluc_report = run_default_critic_report(
        eval_packets,
        mode="llm",
        provider=halluc_provider,
        apply_deterministic_guard=True,
    )
    assert guarded_halluc_report["pointer_validity_rate"] == 1.0
    assert guarded_halluc_report["actionable_true_positives"] == 0
    for row in guarded_halluc_report["per_packet_results"]:
        assert row["hallucinated_sources"] == []
        assert row["hallucinated_calls"] == []
        assert row["hallucinated_sets"] == []
        assert row["hallucinated_cols"] == []

    # Verify filter_llm_assessment_with_deterministic_guard corrects overconfident exact_mechanical
    # labels on Stratum B comparative categories (P02 upstream_tie_collapse_majority and P05 wrong_unit_or_lookalike_support)
    p02 = by_blind["P02"]
    p05 = by_blind["P05"]
    acc_provider = FakeCriticProvider(mode="accurate", packets=[p02, p05])
    raw_p02 = acc_provider.assess_packet(p02).model_copy(
        update={"uncertainty_label": UncertaintyLabel.EXACT_MECHANICAL}
    )
    raw_p05 = acc_provider.assess_packet(p05).model_copy(
        update={"uncertainty_label": UncertaintyLabel.EXACT_MECHANICAL}
    )
    assert raw_p02.defect_category is DefectCategory.UPSTREAM_TIE_COLLAPSE_MAJORITY
    assert raw_p05.defect_category is DefectCategory.WRONG_UNIT_OR_LOOKALIKE_SUPPORT

    guarded_p02 = filter_llm_assessment_with_deterministic_guard(raw_p02, p02)
    guarded_p05 = filter_llm_assessment_with_deterministic_guard(raw_p05, p05)
    assert guarded_p02.uncertainty_label is UncertaintyLabel.WARRANTED_INFERENCE_CRITIQUE
    assert guarded_p02.is_fallible_interpretation is True
    assert guarded_p05.uncertainty_label is UncertaintyLabel.WARRANTED_INFERENCE_CRITIQUE
    assert guarded_p05.is_fallible_interpretation is True

    # Verify audit() in tools/hypothesis_critic_probe.py defaults to mode="deterministic_full"
    audit_out = tmp_path / "audit_report.json"
    audit_res = audit(output=audit_out)
    assert audit_out.exists()
    assert audit_res["mode"] == "deterministic_full"
    assert audit_res["split"] == "held_out_evaluation"
    assert audit_res["live_model_calls"] == 0
    assert audit_res["actionable_true_positives"] == 5
    assert audit_res["false_objections"] == 0
    assert audit_res["matched_pair_exact_count"] == 5

    # Verify evaluate(run_dir) defaults to deterministic_full when critic_assessments.json is absent
    empty_run_dir = tmp_path / "empty_run"
    empty_run_dir.mkdir(parents=True, exist_ok=True)
    det_eval = evaluate(empty_run_dir)
    assert det_eval["mode"] == "deterministic_full"
    assert det_eval["scored"]["actionable_true_positives"] == 5
    assert det_eval["scored"]["false_objections"] == 0
    assert det_eval["scored"]["matched_pair_exact_count"] == 5
    assert det_eval["stage_gate"]["usable"] is True
