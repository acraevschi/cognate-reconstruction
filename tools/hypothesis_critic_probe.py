#!/usr/bin/env python3
"""R07 source-linked hypothesis critic probe: independent derivation checks,
offline baselines, fake-provider controls, freeze, serial live pass, and evaluation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import _bootstrap  # noqa: F401

from cognate_reconstruction.agent.provider_config import (
    api_key_from_environment,
    load_provider_options,
)
from cognate_reconstruction.agent.providers.litellm_provider import LiteLLMProvider
from cognate_reconstruction.agent.providers.pricing import (
    load_price_table,
    price_for,
    price_setting,
)
from cognate_reconstruction.agent.request_journal import (
    REQUEST_JOURNAL_VERSION,
    USAGE_ACCOUNTING_VERSION,
    USAGE_RECORDED_EVENT,
    JsonlRequestJournal,
)
from cognate_reconstruction.agent.schemas import (
    LLMMessage,
    MessageRole,
    NodeLexiconSummary,
    NodePromptPayload,
)
from cognate_reconstruction.agent.trajectory import (
    AgentNodeMetrics,
    AgentTrajectory,
)
from cognate_reconstruction.benchmarks.ledger import read_run_resources
from cognate_reconstruction.cli import (
    DEFAULT_GEMINI_BASE,
    DEFAULT_GEMINI_KEY_ENV,
    _gemini_models,
)
from cognate_reconstruction.evaluation.critic import (
    CRITIC_CORPUS_VERSION,
    CRITIC_EVALUATOR_VERSION,
    CRITIC_TOOL_NAME,
    DEFAULT_CRITIC_MODE,
    CriticAssessment,
    CritiquePacket,
    EvidenceChannel,
    FakeCriticProvider,
    audit_run_directory,
    build_blind_evaluation_sheet,
    build_critic_user_prompt,
    critic_system_instructions,
    critic_tool_definition,
    evaluate_forward_revision_on_packet,
    filter_llm_assessment_with_deterministic_guard,
    parse_critic_response,
    resolve_audit_payload,
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
from cognate_reconstruction.synthesis.diagnostics import (
    build_case,
    load_explicit_case,
    load_suite,
)
from tools.model_diagnostic_probe import (
    ARMS,
    CONTEXT_LIMIT_TOKENS,
    GEMINI_PRICE_TABLE,
    ROOT,
    WALL_OVERHEAD_SECONDS,
    _file_hash,
    _hash,
    source_manifest,
)

CORPUS_PATH = ROOT / "benchmarks/diagnostic/r07-hypothesis-critic-v1.json"
STAGE_C_PATH = ROOT / "benchmarks/diagnostic/stage-c-multi-outgroup-v1.json"
TWO_LEVEL_PATH = ROOT / "benchmarks/diagnostic/two-level-propagation-v1.json"
FORWARD_PATH = ROOT / "benchmarks/diagnostic/forward-prediction-v1.json"
DEFAULT_RESULTS_OUT = (
    ROOT / "docs/research/hypothesis_criticism_feasibility_results.json"
)

ARM_NAME = "gemini-r07-critic"
ARM = {
    **ARMS["gemini"],
    "max_output_tokens": 16_384,
    "timeout": 300,
    "ceiling": {"cost_usd": 1.50, "wall_seconds": 1200.0},
    "caps": {
        "max_packets": 10,
        "max_turns": 10,
        "max_tool_calls": 10,
        "max_run_seconds": 1080,
        "max_total_cost_usd": 0.60,
        "max_prompt_tokens_per_packet": 32_768,
    },
}


def load_corpus_packets(path: Path = CORPUS_PATH) -> tuple[dict[str, Any], list[CritiquePacket]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("corpus_version") != CRITIC_CORPUS_VERSION:
        raise ValueError(
            f"Expected corpus_version={CRITIC_CORPUS_VERSION!r}, got {raw.get('corpus_version')!r}"
        )
    packets = [CritiquePacket.model_validate(item) for item in raw["packets"]]
    return raw, packets


def verify_independent_ground_truth(
    packets: list[CritiquePacket] | None = None,
) -> dict[str, Any]:
    """Independently verify packet ground-truth labels against source fixtures and R06 execution.

    Ensures evaluation labels are grounded in independent Fitch parsimony,
    source cognacy memberships, navigation logs, log-mass arithmetic, and
    RuleEngine forward execution rather than copied from detector outputs.
    """
    if packets is None:
        _, packets = load_corpus_packets()
    by_id = {p.packet_id: p for p in packets}

    stage_c = load_explicit_case(STAGE_C_PATH)
    stage_c_opp_by_concept = {}
    for opp in stage_c["opportunities"]:
        stage_c_opp_by_concept.setdefault(opp["concept_id"], []).append(opp)

    checks: dict[str, dict[str, Any]] = {}

    # 1. Verify Stage C Fitch parsimony & unit memberships on y01, y03, y04, y05, y07, y09, y14
    for pid, cid, expected_reading in [
        ("eval_c02_legitimate_inspected_shifted_outgroup", "y04", "retain"),
        ("eval_e01_upstream_tie_collapse", "y05", "unresolved"),
        ("eval_e03_suffix_lookalike_scope_confusion", "y14", "absent"),
        ("eval_c01_legitimate_parent_majority", "y07", "retain"),
        ("eval_c03_genuine_tie_and_child_swap_invariance", "y09", "unresolved"),
        ("eval_e02_uninspected_and_wrong_unit_outgroup", "y01", "absent"),
        ("dev_d01_legit_complete_local_coverage_drop", "y03", "unresolved"),
    ]:
        pkt = by_id[pid]
        opps = [
            o
            for o in stage_c_opp_by_concept[cid]
            if o["locus"] == "final"
        ]
        assert len(opps) == 1, f"Expected 1 final opportunity on {cid}"
        opp = opps[0]
        target_unit = opp["unit"]
        same_unit_present = 0
        same_unit_total = 0
        for og in ("c", "d", "f"):
            pieces = stage_c["observed"][og].get(cid, [])
            for unit_id, seg_str in pieces:
                if unit_id == target_unit:
                    same_unit_total += 1
                    toks = seg_str.split()
                    if len(toks) >= 2 and toks[-1] not in ("a", "e", "i", "o", "u"):
                        same_unit_present += 1
        if same_unit_present > same_unit_total / 2:
            fitch = "retain"
        elif same_unit_present < same_unit_total / 2:
            fitch = "absent"
        else:
            fitch = "unresolved"
        ok = (
            fitch == expected_reading
            and opp["expected"] == expected_reading
            and f"cog:{target_unit}" == pkt.claim.unit_id
        )
        checks[pid] = {
            "ok": ok,
            "concept_id": cid,
            "unit_id": f"cog:{target_unit}",
            "same_unit_outgroup_present": same_unit_present,
            "same_unit_outgroup_total": same_unit_total,
            "derived_fitch_reading": fitch,
            "stage_c_key_expected": opp["expected"],
        }

    # 2. Verify R05 log-mass length penalty on eval_e04 vs eval_c04
    # Across the 4 child-beam tuples (k o, k o), (k o, k o t), (k o t, k o), (k o t, k o t):
    # *k o receives 0.25 * 0.95^2 * (1.0 + 0.5 + 0.5); *k o t receives 0.25 * 0.95^2 * (0.5 + 0.5 + 0.95).
    m_short_095 = 0.25 * (0.95**2) * (1.0 + 0.5 + 0.5)
    m_long_095 = 0.25 * (0.95**2) * (0.5 + 0.5 + 0.95)
    z_095 = m_short_095 + m_long_095
    p_short_095 = round(m_short_095 / z_095, 4)
    p_long_095 = round(m_long_095 / z_095, 4)
    e04 = by_id["eval_e04_identity_confidence_length_bias"]
    cands_e04 = e04.claim.competing_beam_candidates
    checks["eval_e04_identity_confidence_length_bias"] = {
        "ok": (
            p_short_095 == 0.5063
            and p_long_095 == 0.4937
            and cands_e04[0]["probability"] == p_short_095
            and cands_e04[1]["probability"] == p_long_095
        ),
        "derived_probabilities_at_095": [p_short_095, p_long_095],
        "derived_probabilities_at_100": [0.5, 0.5],
    }

    # 3. Verify R06 forward cascade & revision diff on eval_e05 and contrast equivalence on eval_c05
    fwd_case = json.loads(FORWARD_PATH.read_text(encoding="utf-8"))["cases"][0]
    built_fwd = build_case(fwd_case)
    dev_cids = list(fwd_case["development_concept_ids"])
    proto_map = {
        entry["concept_id"]: list(entry["segments"])
        for entry in fwd_case["family"]["proto_lexicon"]
    }
    anc_q = {cid: proto_map[cid] for cid in dev_cids}
    anc_g = {
        cid: ["ɢ" if tok == "q" else tok for tok in segs]
        for cid, segs in anc_q.items()
    }
    lex_a = next(lex for lex in built_fwd.payload.lexicons if lex.variety_id == "a")
    obs_a_map = {f.concept_id: list(f.segments) for f in lex_a.forms}
    obs_a = {cid: obs_a_map[cid] for cid in dev_cids}
    e05 = by_id["eval_e05_bleeding_order_and_leaky_revision"]
    rev_check = evaluate_forward_revision_on_packet(
        anc_q,
        obs_a,
        e05.claim.forward_cascade_rules,
        e05.claim.candidate_revision_rules,
        parent_node_id="r",
        child_node_id="a",
    )
    checks["eval_e05_bleeding_order_and_leaky_revision"] = {
        "ok": (
            rev_check["mismatched_concept_ids"] == ["d01", "d02"]
            and rev_check["repaired_concept_ids"]
            == list(e05.ground_truth.expected_repaired_examples)
            and rev_check["newly_broken_concept_ids"]
            == list(e05.ground_truth.expected_newly_broken_examples)
        ),
        "mismatched_before": rev_check["mismatched_concept_ids"],
        "repaired": rev_check["repaired_concept_ids"],
        "newly_broken": rev_check["newly_broken_concept_ids"],
    }

    c05 = by_id["eval_c05_bijective_proto_relabelling"]
    c05_check = evaluate_forward_revision_on_packet(
        anc_g,
        obs_a,
        c05.claim.forward_cascade_rules,
        c05.claim.forward_cascade_rules,
        parent_node_id="r",
        child_node_id="a",
    )
    from cognate_reconstruction.evaluation.forward import (
        compute_corpus_contrast_equivalence,
    )

    proto_eq = compute_corpus_contrast_equivalence(anc_g, anc_q, dev_cids)
    checks["eval_c05_bijective_proto_relabelling"] = {
        "ok": (
            c05_check["dev_exact_rate"] == 1.0
            and proto_eq["is_bijective_relabelling"] is True
            and proto_eq["corpus_bcubed_f1"] == 1.0
        ),
        "dev_exact_rate": c05_check["dev_exact_rate"],
        "proto_is_bijective_relabelling": proto_eq["is_bijective_relabelling"],
        "proto_corpus_bcubed_f1": proto_eq["corpus_bcubed_f1"],
    }

    # 4. Verify two-level-propagation-v1 fixture integrity for dev_d02 and eval_c04
    two_level = load_suite(TWO_LEVEL_PATH)["cases"][0]
    built_tl = build_case(two_level)
    checks["two_level_propagation_v1_link"] = {
        "ok": len(built_tl.payload.lexicons) == 4,
        "c009_expected": two_level["opportunities_by_node"]["r"][0]["concept_id"],
    }

    all_ok = all(item["ok"] for item in checks.values())
    return {
        "ok": all_ok,
        "checked_count": len(checks),
        "checks": checks,
    }


def controls(live_run_dir: Path | None = None) -> dict[str, Any]:
    """Run all offline baselines, deterministic detectors, fake-provider controls, and leakage checks."""
    raw_corpus, packets = load_corpus_packets()
    dev_packets = [p for p in packets if p.split == "development"]
    eval_packets = [p for p in packets if p.split == "held_out_evaluation"]
    gold_guard_packets = [
        p for p in packets if p.split == "offline_gold_residual_only"
    ]

    visible_dev = [to_model_visible_packet(p) for p in dev_packets]
    visible_eval = [to_model_visible_packet(p) for p in eval_packets]
    leakage_dev = verify_no_critic_leakage(packets, visible_dev)
    leakage_eval = verify_no_critic_leakage(packets, visible_eval)

    # Verify offline_gold_residual_only packets are strictly refused by to_model_visible_packet
    refused_gold_ids: list[str] = []
    for gp in gold_guard_packets:
        try:
            to_model_visible_packet(gp)
        except ValueError:
            refused_gold_ids.append(gp.packet_id)

    derivation_verification = verify_independent_ground_truth(packets)

    def _run_split(subset: list[CritiquePacket]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, fn in [
            (
                "existing_residue_ambiguity_baseline",
                run_existing_residue_ambiguity_baseline,
            ),
            (
                "fixed_evidence_checklist_baseline",
                run_fixed_evidence_checklist_baseline,
            ),
            (
                "deterministic_mechanical_detector",
                run_deterministic_mechanical_detector,
            ),
            (
                "deterministic_full_trace_detector",
                run_deterministic_full_detector,
            ),
        ]:
            assessments = {p.packet_id: fn(p) for p in subset}
            out[name] = score_critic_assessments(subset, assessments)

        for mode in (
            "accurate",
            "over_objecting",
            "verbose_relabeller",
            "hallucinated_pointers",
        ):
            provider = FakeCriticProvider(mode=mode, packets=subset)
            assessments = run_llm_critic_on_packets(subset, provider)
            out[f"fake_critic_{mode}"] = score_critic_assessments(
                subset, assessments
            )
        return out

    blind_sheet = build_blind_evaluation_sheet(eval_packets, seed=20261110)
    eval_split_results = _run_split(eval_packets)
    live_evaluation: dict[str, Any] | None = None
    if live_run_dir is not None and (live_run_dir / "evaluation.json").exists():
        live_evaluation = json.loads(
            (live_run_dir / "evaluation.json").read_text(encoding="utf-8")
        )
        eval_split_results["live_gemini_3_8_flash_critic"] = live_evaluation[
            "scored"
        ]

    return {
        "corpus_version": raw_corpus["corpus_version"],
        "evaluator_version": CRITIC_EVALUATOR_VERSION,
        "corpus_sha256": _file_hash(CORPUS_PATH),
        "live_model_calls": 0,
        "independent_ground_truth_verification": derivation_verification,
        "evidence_boundary_checks": {
            "development_leakage_check": leakage_dev,
            "held_out_evaluation_leakage_check": leakage_eval,
            "offline_gold_guard_packets_count": len(gold_guard_packets),
            "offline_gold_guard_refused_ids": refused_gold_ids,
            "all_offline_gold_packets_refused": len(refused_gold_ids)
            == len(gold_guard_packets),
        },
        "development_split_results": _run_split(dev_packets),
        "held_out_evaluation_split_results": eval_split_results,
        "live_experiment_summary": live_evaluation,
        "blind_evaluation_sheet": {
            "seed": 20261110,
            "presentation_order": blind_sheet["presentation_order"],
            "item_count": len(blind_sheet["presentation_order"]),
        },
    }


def resource_bound(price) -> dict[str, Any]:
    caps = ARM["caps"]
    cap_tokens = ARM["max_output_tokens"]
    context_headroom = (
        CONTEXT_LIMIT_TOKENS * price.input_usd_per_million
        + cap_tokens * price.output_usd_per_million
    ) / 1_000_000
    packet_headroom = (
        caps["max_prompt_tokens_per_packet"] * price.input_usd_per_million
        + cap_tokens * price.output_usd_per_million
    ) / 1_000_000
    worst = caps["max_total_cost_usd"] + context_headroom
    return {
        "paid": True,
        "cost_cap_usd": caps["max_total_cost_usd"],
        "one_response_headroom_usd": round(context_headroom, 6),
        "one_response_packet_bound_headroom_usd": round(packet_headroom, 6),
        "headroom_basis": (
            f"{CONTEXT_LIMIT_TOKENS} input tokens (Gemini context limit) and "
            f"{cap_tokens} output tokens at the explicit table price "
            f"(packet-capped headroom at {caps['max_prompt_tokens_per_packet']} input tokens: "
            f"US${packet_headroom:.6f})"
        ),
        "worst_case_trial_usd": round(worst, 6),
        "cost_reservation_usd": round(worst + 0.002, 2),
        "max_packets": caps["max_packets"],
        "max_turns_total": caps["max_turns"],
        "worst_case_output_tokens": caps["max_turns"] * cap_tokens,
        "max_run_seconds": caps["max_run_seconds"],
        "wall_reservation_seconds": caps["max_run_seconds"]
        + WALL_OVERHEAD_SECONDS,
    }


def trial_argv(inputs: Path) -> list[str]:
    caps = ARM["caps"]
    return [
        "{python}",
        str(ROOT / "tools/hypothesis_critic_probe.py"),
        "run-live",
        "--inputs-dir",
        str(inputs),
        "--run-dir",
        "{run_dir}",
        "--model",
        ARM["model"],
        "--preset",
        ARM["preset"],
        "--reasoning-effort",
        ARM["reasoning_effort"],
        "--provider-config",
        str(inputs / f"{ARM_NAME}.provider-config.json"),
        "--price-table",
        str(inputs / "price-table.json"),
        "--run-id",
        f"r07-critic-{ARM_NAME}",
        "--timeout",
        str(ARM["timeout"]),
        "--max-total-cost-usd",
        str(caps["max_total_cost_usd"]),
        "--max-run-seconds",
        str(caps["max_run_seconds"]),
    ]


def _preregistration_markdown(
    manifest: dict[str, Any],
    manifest_sha: str,
    plan_sha: str,
) -> str:
    bound = manifest["arm"][ARM_NAME]["resources"]
    return "\n".join(
        [
            "# R07 Pre-Registration — Source-Linked Hypothesis Critic (`r07-hypothesis-critic-20261110`)",
            "",
            f"- **Date frozen:** `{manifest['frozen_on']}`",
            f"- **Manifest SHA-256:** `{manifest_sha}`",
            f"- **Plan SHA-256:** `{plan_sha}`",
            f"- **Source manifest SHA-256:** `{manifest['source_manifest_sha256']}` (`HEAD {manifest['source']['head']}`)",
            f"- **Corpus definition:** `{manifest['definition']}` (`{manifest['definition_sha256']}`)",
            f"- **Evaluator version:** `{CRITIC_EVALUATOR_VERSION}`",
            "",
            "## 1. Research Question and Hypothesis",
            "Can an assisted LLM critic (`gemini/gemini-3.8-flash`, `medium` thinking) consuming compact,",
            "source-linked claim-evidence packets on the `inference_available_daughter_fitting` channel",
            "locate the comparative and scope defects that a pure mechanical detector misses (`eval_e01`",
            "upstream tie-collapse masquerading as parent majority; `eval_e03` suffix-unit look-alike",
            "confusion) while retaining all 3 mechanical/execution defect detections (`eval_e02`,",
            "`eval_e04`, `eval_e05`), citing exact non-hallucinated source/call/set/column pointers,",
            "and raising **zero false objections** on the 5 paired legitimate/ambiguous/perturbation",
            "controls (`eval_c01`–`eval_c05`)?",
            "",
            "## 2. Frozen Held-Out Design and Anonymized Presentation",
            "- **Development split (`D01`–`D06`, 3 pairs):** Used only for offline development/tuning; never sent in the live evaluation pass.",
            "- **Offline gold residual guard (`G01`–`G02`):** Refused mechanically by `to_model_visible_packet`; never sent to the model.",
            "- **Held-out blind assessment split (`P01`–`P10`, 5 matched pairs = 10 packets):**",
            "  - Presented in deterministic randomized blind order (`seed = 20261110`):",
            f"    `{manifest['presentation_order']}`",
            "  - Stripped of `ground_truth`, `pair_id`, `pair_role`, `origin_artifact`, and internal `packet_id`.",
            "",
            "## 3. Primary Metrics and Baselines",
            "1. **Actionable Precision (`actionable_precision`):** Share of raised objections that match the defective packet, defect category, required source/call/set/column pointers (with zero hallucinated pointers), and executable revision side-effect examples.",
            "2. **Missed Known Defects (`missed_known_defects` / 5):** Defective packets missed or misclassified.",
            "3. **False Objections (`false_objections` / 5):** Legitimate or genuinely ambiguous paired controls flagged as defective.",
            "4. **Pointer Validity & Completeness (`pointer_validity_rate`, `defect_pointer_completeness_rate`):** Exact citation of `source_ids`, `call_ids`, `set_ids`, and `column_indices`.",
            "5. **Matched-Pair Accuracy (`matched_pairs_both_correct` / 5):** Pairs where both the defective claim is actionably caught and its paired legitimate control receives no false objection.",
            "",
            "## 4. Resource Envelope and Stopping Rules",
            f"- **Authorized ceiling:** **US\\${manifest['arm'][ARM_NAME]['ceiling']['cost_usd']:.2f}** upper-bound table cost and **{manifest['arm'][ARM_NAME]['ceiling']['wall_seconds']:.0f} s** (20 minutes) paid wall time.",
            f"- **Run cap:** **US\\${bound['cost_cap_usd']:.2f}** + one-response worst-case headroom **US\\${bound['one_response_headroom_usd']:.6f}** = **US\\${bound['worst_case_trial_usd']:.6f}** (reservation **US\\${bound['cost_reservation_usd']:.2f} <= US\\$1.50**).",
            f"- **Wall cap:** **{bound['max_run_seconds']} s** + **{WALL_OVERHEAD_SECONDS} s** overhead = **{bound['wall_reservation_seconds']} s <= 1,200 s**.",
            "- **Stopping rules:** Single serial pass over the 10 held-out packets (`P01`–`P10`), 0 automatic retries (`num_retries=0`), no search or grounding. Stop immediately if the cost cap, wall cap, or a provider failure is reached. Never queue additional seeds or switch models.",
            "",
            "## 5. Pre-Registered Continuation Criterion",
            "- **Recommend continuation (bounded offline/on-demand critic report):** Only if the live critic achieves higher `actionable_true_positives` and `matched_pairs_both_correct` than `deterministic_mechanical_detector` (`> 3/5`) with `false_objections <= 1` and `pointer_validity_rate == 1.0`.",
            "- **Defer/reject model critic in favor of deterministic detector:** If the live critic produces excessive false objections (`>= 2/5`), hallucinates pointers, or fails to beat the deterministic detector (`3/5` mechanical, `5/5` full trace detector).",
            "",
        ]
    )


def freeze(output_dir: Path) -> dict[str, Any]:
    """Freeze inputs, anonymized held-out packets, manifest, launch plan, and pre-registration."""
    output_dir = output_dir.resolve()
    inputs = output_dir / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)

    raw_corpus, packets = load_corpus_packets()
    eval_packets = [p for p in packets if p.split == "held_out_evaluation"]
    blind_sheet = build_blind_evaluation_sheet(eval_packets, seed=20261110)

    by_blind = {p.blind_code: p for p in eval_packets}
    ordered_eval_packets = [
        by_blind[code] for code in blind_sheet["presentation_order"]
    ]
    visible_packets = [to_model_visible_packet(p) for p in ordered_eval_packets]
    leakage = verify_no_critic_leakage(packets, visible_packets)
    if not leakage["ok"]:
        raise ValueError(f"Leakage check failed during freeze: {leakage}")

    (inputs / "held-out-visible-packets.json").write_text(
        json.dumps(
            {
                "corpus_version": CRITIC_CORPUS_VERSION,
                "evaluator_version": CRITIC_EVALUATOR_VERSION,
                "seed": 20261110,
                "presentation_order": blind_sheet["presentation_order"],
                "packets": visible_packets,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    instructions_text = critic_system_instructions()
    (inputs / "critic-instructions.md").write_text(
        instructions_text + "\n", encoding="utf-8"
    )
    (inputs / "price-table.json").write_bytes(GEMINI_PRICE_TABLE.read_bytes())
    (inputs / f"{ARM_NAME}.provider-config.json").write_text(
        json.dumps({"max_tokens": ARM["max_output_tokens"]}, indent=2) + "\n",
        encoding="utf-8",
    )

    (output_dir / "blind_evaluation_sheet.md").write_text(
        blind_sheet["markdown_form"] + "\n", encoding="utf-8"
    )
    (output_dir / "sealed_answer_key.json").write_text(
        json.dumps(blind_sheet["sealed_answer_key"], indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    table, table_sha = load_price_table(inputs / "price-table.json")
    price = price_for(table, ARM["harness_model"], date.today())
    sources = source_manifest()
    (output_dir / "source_manifest.json").write_text(
        json.dumps(sources, indent=2) + "\n", encoding="utf-8"
    )
    input_hashes = {p.name: _file_hash(p) for p in sorted(inputs.iterdir())}
    bound = resource_bound(price)
    argv = trial_argv(inputs)
    tool_def = critic_tool_definition()
    tool_schema_sha = _hash(
        json.dumps([tool_def.model_dump(mode="json")], sort_keys=True)
    )
    first_prompt = build_critic_user_prompt(visible_packets[0])

    manifest = {
        "experiment": output_dir.name,
        "frozen_on": str(date.today()),
        "stage": "R07-hypothesis-critic",
        "status": "frozen manifest; independent read-only review required before single live serial pass",
        "source": {
            k: sources[k]
            for k in (
                "head",
                "branch",
                "source_roots",
                "tracked_diff_sha256",
                "dirty_paths",
            )
        },
        "source_manifest_sha256": _file_hash(
            output_dir / "source_manifest.json"
        ),
        "definition": str(CORPUS_PATH.relative_to(ROOT)),
        "definition_sha256": _file_hash(CORPUS_PATH),
        "corpus_version": raw_corpus["corpus_version"],
        "question": (
            "Can gemini-3.8-flash (medium thinking) identify source-linked comparative "
            "and mechanical defects across the 10 anonymized held-out packets (5 matched pairs) "
            "with exact evidence pointers and zero false objections on legitimate paired controls?"
        ),
        "presentation_order": blind_sheet["presentation_order"],
        "leakage_verification": leakage,
        "inputs": input_hashes,
        "price_table": {
            "sha256": table_sha,
            "entry": json.loads(price.model_dump_json()),
        },
        "evaluator_versions": {
            "critic": CRITIC_EVALUATOR_VERSION,
            "corpus": CRITIC_CORPUS_VERSION,
            "forward": "r06-forward-v1",
            "ledger": "r02-ledger-v1",
            "usage_accounting": USAGE_ACCOUNTING_VERSION,
        },
        "model_visible": {
            "instructions_sha256": _hash(instructions_text),
            "critic_tool_schema_sha256": tool_schema_sha,
            "held_out_visible_packets_sha256": input_hashes[
                "held-out-visible-packets.json"
            ],
            "first_packet_prompt_sha256": _hash(first_prompt),
            "first_packet_prompt_chars": len(first_prompt),
        },
        "trials": 1,
        "replication": "none; single-seed serial pass over 10 frozen held-out packets, 0 retries",
        "arm": {
            ARM_NAME: {
                "model": ARM["model"],
                "preset": ARM["preset"],
                "harness_model": ARM["harness_model"],
                "reasoning_effort": ARM["reasoning_effort"],
                "thinking_config": {
                    "thinkingLevel": ARM["reasoning_effort"],
                    "includeThoughts": True,
                },
                "temperature": 1.0,
                "max_output_tokens": ARM["max_output_tokens"],
                "timeout": ARM["timeout"],
                "ceiling": ARM["ceiling"],
                "caps": ARM["caps"],
                "resources": bound,
                "argv": argv,
            }
        },
    }
    manifest_path = output_dir / "manifest.r07-critic.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    plan = {
        "plan_version": "r02-batch-v1",
        "batch_dir": ".",
        "ceilings": {ARM_NAME: ARM["ceiling"]},
        "trials": [
            {
                "trial_id": f"R07-{ARM_NAME}",
                "arm": ARM_NAME,
                "run_dir": f"runs/r07-{ARM_NAME}",
                "argv": argv,
                "reservation": {
                    "cost_usd": bound["cost_reservation_usd"],
                    "wall_seconds": bound["wall_reservation_seconds"],
                },
                "requires_usable": None,
                "evaluate_argv": [
                    "{python}",
                    str(ROOT / "tools/hypothesis_critic_probe.py"),
                    "evaluate",
                    "--run-dir",
                    "{run_dir}",
                ],
            }
        ],
    }
    plan_path = output_dir / "plan.json"
    plan_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")

    manifest_sha = _file_hash(manifest_path)
    plan_sha = _file_hash(plan_path)
    prereg_text = _preregistration_markdown(manifest, manifest_sha, plan_sha)
    (output_dir / "preregistration.md").write_text(
        prereg_text + "\n", encoding="utf-8"
    )

    return {
        "manifest_sha256": manifest_sha,
        "plan_sha256": plan_sha,
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "preregistration_sha256": _file_hash(output_dir / "preregistration.md"),
        "inputs": input_hashes,
        "model_visible": manifest["model_visible"],
        "resources": bound,
    }


def run_live(
    inputs_dir: Path,
    run_dir: Path,
    *,
    model: str = "gemini-3.8-flash",
    preset: str = "gemini",
    reasoning_effort: str = "medium",
    provider_config_path: Path,
    price_table_path: Path,
    run_id: str = "r07-critic-gemini-r07-critic",
    timeout: float = 300.0,
    max_total_cost_usd: float = 0.60,
    max_run_seconds: float = 1080.0,
    completion_fn=None,
    no_preflight: bool = False,
) -> dict[str, Any]:
    """Execute the single serial pass of the critic over the frozen held-out packets."""
    inputs_dir = inputs_dir.resolve()
    run_dir = run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    visible_blob = json.loads(
        (inputs_dir / "held-out-visible-packets.json").read_text(
            encoding="utf-8"
        )
    )
    visible_packets: list[dict[str, Any]] = visible_blob["packets"]
    instructions_text = (inputs_dir / "critic-instructions.md").read_text(
        encoding="utf-8"
    ).strip()

    _, all_packets = load_corpus_packets()
    leakage = verify_no_critic_leakage(all_packets, visible_packets)
    if not leakage["ok"]:
        raise ValueError(f"Refusing live critic run due to leakage: {leakage}")
    packet_by_blind = {
        p.blind_code: p for p in all_packets if p.split == "held_out_evaluation"
    }

    options = load_provider_options(str(provider_config_path))
    harness_model = (
        model if model.startswith("gemini/") else f"gemini/{model}"
    )
    raw_model = harness_model.partition("/")[2]

    if preset == "gemini" and completion_fn is None:
        api_key = api_key_from_environment(DEFAULT_GEMINI_KEY_ENV)
        if not api_key:
            raise ValueError(
                f"Missing {DEFAULT_GEMINI_KEY_ENV} environment variable for live Gemini run"
            )
        if not no_preflight:
            available = _gemini_models(DEFAULT_GEMINI_BASE, api_key)
            if raw_model not in available:
                raise ValueError(
                    f"Model {raw_model!r} is not reported by Gemini API preflight"
                )
        options["api_key"] = api_key

    options["thinkingConfig"] = {
        "thinkingLevel": reasoning_effort,
        "includeThoughts": True,
    }
    options["temperature"] = 1.0
    options["timeout"] = timeout

    table, table_sha = load_price_table(price_table_path)
    price = price_for(table, harness_model, date.today())
    provider = LiteLLMProvider(
        harness_model,
        completion_kwargs=options,
        completion_fn=completion_fn,
        price=price,
    )

    tool_def = critic_tool_definition()
    instruction_sha = _hash(instructions_text)
    tool_schema_sha = _hash(
        json.dumps([tool_def.model_dump(mode="json")], sort_keys=True)
    )
    payload_schema_sha = _hash(
        json.dumps(NodePromptPayload.model_json_schema(), sort_keys=True)
    )
    traj_schema_sha = _hash(
        json.dumps(AgentTrajectory.model_json_schema(), sort_keys=True)
    )
    cfg_setting = {
        "stage": "R07-hypothesis-critic",
        "model": harness_model,
        "preset": preset,
        "thinking_level": reasoning_effort,
        "temperature": 1.0,
        "max_tokens": options.get("max_tokens"),
        "instructions_sha256": instruction_sha,
        "tool_schema_sha256": tool_schema_sha,
        "packets_sha256": _file_hash(
            inputs_dir / "held-out-visible-packets.json"
        ),
        "price": price_setting(price, table_sha),
        "request_journal": REQUEST_JOURNAL_VERSION,
    }
    cfg_sha = _hash(json.dumps(cfg_setting, sort_keys=True))

    journal = JsonlRequestJournal(
        run_dir / "checkpoint.requests.jsonl",
        run_id=run_id,
        configuration_sha256=cfg_sha,
    )

    trajectories: list[AgentTrajectory] = []
    assessments_by_id: dict[str, dict[str, Any]] = {}
    per_request_log: list[dict[str, Any]] = []

    total_turns = 0
    total_tool_calls = 0
    total_cost_usd = 0.0
    unknown_cost_requests = 0
    run_started = time.monotonic()
    interrupted = False
    interruption_reason: str | None = None
    failure_kind: str | None = None

    for idx, vis_pkt in enumerate(visible_packets, start=1):
        elapsed_so_far = time.monotonic() - run_started
        if elapsed_so_far >= max_run_seconds:
            interrupted = True
            interruption_reason = (
                f"Run wall time {elapsed_so_far:.2f}s reached max_run_seconds={max_run_seconds:.2f}s"
            )
            failure_kind = "wall_budget_exceeded"
            break
        if total_cost_usd >= max_total_cost_usd:
            interrupted = True
            interruption_reason = (
                f"Cumulative cost US${total_cost_usd:.6f} reached max_total_cost_usd=US${max_total_cost_usd:.2f}"
            )
            failure_kind = "cost_budget_exceeded"
            break
        if unknown_cost_requests > 0:
            interrupted = True
            interruption_reason = "Stopping after a request with unknown cost"
            failure_kind = "unknown_cost_request"
            break

        blind_code = str(vis_pkt["packet_id"])
        sealed_pkt = packet_by_blind[blind_code]
        traj_id = f"{run_id}-{blind_code}"
        user_prompt = build_critic_user_prompt(vis_pkt)
        messages = (
            LLMMessage(role=MessageRole.SYSTEM, content=instructions_text),
            LLMMessage(role=MessageRole.USER, content=user_prompt),
        )

        started_dt = datetime.now(UTC)
        t0 = time.monotonic()
        journal.record("turn", trajectory_id=traj_id, node_id=blind_code)
        total_turns += 1
        journal.record(
            "request_start",
            trajectory_id=traj_id,
            node_id=blind_code,
            attempt=1,
        )
        try:
            response = provider.complete(
                messages,
                (tool_def,),
                tool_choice="required",
            )
        except Exception as exc:
            dur = time.monotonic() - t0
            journal.record(
                "request_end",
                trajectory_id=traj_id,
                node_id=blind_code,
                attempt=1,
                outcome="error",
                duration_seconds=dur,
                response_state="unknown",
                retryable=False,
                error=str(exc),
            )
            unknown_cost_requests += 1
            interrupted = True
            interruption_reason = f"Provider error on {blind_code}: {exc}"
            failure_kind = "provider_error"
            break

        dur = time.monotonic() - t0
        finished_dt = datetime.now(UTC)
        usage = response.metadata.usage
        req_cost = usage.cost_usd if usage is not None else None
        in_tok = usage.input_tokens if usage is not None else None
        out_tok = usage.output_tokens if usage is not None else None
        tot_tok = usage.total_tokens if usage is not None else None
        cached_tok = usage.cached_input_tokens if usage is not None else None
        reason_tok = usage.reasoning_output_tokens if usage is not None else None

        journal.record(
            "request_end",
            trajectory_id=traj_id,
            node_id=blind_code,
            attempt=1,
            outcome="response",
            duration_seconds=dur,
            cost_usd=req_cost,
            input_tokens=in_tok,
            output_tokens=out_tok,
            total_tokens=tot_tok,
        )
        if req_cost is not None:
            total_cost_usd += float(req_cost)
        else:
            unknown_cost_requests += 1

        call_count_this_turn = len(response.message.tool_calls)
        for tc in response.message.tool_calls:
            journal.record(
                "tool_call",
                trajectory_id=traj_id,
                node_id=blind_code,
                call_id=tc.call_id,
                tool_name=tc.name,
            )
            total_tool_calls += 1

        assessment = parse_critic_response(response, packet=sealed_pkt)
        assessments_by_id[sealed_pkt.packet_id] = assessment.model_dump(
            mode="json"
        )

        active_children_summaries = tuple(
            NodeLexiconSummary(
                node_id=cid,
                name=cid,
                form_count=1,
                concept_count=1,
            )
            for cid in sealed_pkt.evidence.active_child_ids
        )
        traj = AgentTrajectory(
            trajectory_id=traj_id,
            run_id=run_id,
            configuration_sha256=cfg_sha,
            node_id=blind_code,
            provider_adapter="LiteLLMProvider",
            model_id=harness_model,
            instruction_sha256=instruction_sha,
            tool_schema_sha256=tool_schema_sha,
            payload_schema_sha256=payload_schema_sha,
            trajectory_schema_sha256=traj_schema_sha,
            initial_payload=NodePromptPayload(
                node_id=blind_code,
                active_children=active_children_summaries,
            ),
            tool_definitions=(tool_def,),
            messages=(*messages, response.message),
            provider_responses=(response.metadata,),
            metrics=AgentNodeMetrics(
                started_at=started_dt,
                finished_at=finished_dt,
                duration_seconds=dur,
                turn_count=1,
                provider_attempts=1,
                retry_count=0,
                tool_call_count=call_count_this_turn,
                inspection_tool_calls=0,
                sound_law_tests=0,
                cascade_tests=0,
                input_tokens=in_tok,
                output_tokens=out_tok,
                total_tokens=tot_tok,
                cached_input_tokens=cached_tok,
                reasoning_output_tokens=reason_tok,
                cost_usd=req_cost,
                committed_rule_count=1,
                committed_anomaly_count=0,
                committed_without_inspection=False,
                identity_without_testing=False,
            ),
            completed=False,
            failure="critic_packet_completed",
        )
        trajectories.append(traj)
        per_request_log.append(
            {
                "request_index": idx,
                "blind_code": blind_code,
                "packet_id": sealed_pkt.packet_id,
                "input_tokens": in_tok,
                "cached_input_tokens": cached_tok or 0,
                "output_tokens": out_tok,
                "reasoning_output_tokens": reason_tok or 0,
                "table_cost_usd": round(req_cost or 0.0, 6),
                "duration_seconds": round(dur, 3),
                "verdict": assessment.verdict.value,
                "defect_category": assessment.defect_category.value,
            }
        )

    total_elapsed = time.monotonic() - run_started
    traj_path = run_dir / "trajectories.jsonl"
    traj_path.write_text(
        "".join(t.model_dump_json() + "\n" for t in trajectories),
        encoding="utf-8",
    )

    (run_dir / "critic_assessments.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "model": harness_model,
                "evaluator_version": CRITIC_EVALUATOR_VERSION,
                "packets_evaluated": len(assessments_by_id),
                "assessments": assessments_by_id,
                "requests": per_request_log,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    status = "interrupted" if interrupted else "completed"
    summary_payload = {
        "status": status,
        "run_id": run_id,
        "configuration_sha256": cfg_sha,
        "failure_kind": failure_kind,
        "interruption_reason": interruption_reason,
        "packets_attempted": len(per_request_log),
        "packets_completed": len(assessments_by_id),
        "usage": {
            "usage_accounting_version": USAGE_ACCOUNTING_VERSION,
            "turns": total_turns,
            "tool_calls": total_tool_calls,
            "reported_cost_usd": round(total_cost_usd, 6),
            "responses_without_cost": unknown_cost_requests,
            "elapsed_seconds": round(total_elapsed, 4),
            "unrecorded_requests": 0,
            "effort_counts_known": True,
            "history_complete": True,
        },
    }
    (run_dir / "run_summary.json").write_text(
        json.dumps(summary_payload, indent=2) + "\n", encoding="utf-8"
    )
    if not interrupted:
        (run_dir / "result.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": "completed",
                    "configuration_sha256": cfg_sha,
                    "lifecycle_summary": {
                        "run_id": run_id,
                        "configuration_sha256": cfg_sha,
                        "fallback_node_ids": [],
                    },
                    "packets_completed": len(assessments_by_id),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    journal.record(USAGE_RECORDED_EVENT)
    return summary_payload


def audit(
    *,
    split: Literal[
        "held_out_evaluation",
        "development",
        "all",
    ] = "held_out_evaluation",
    mode: Literal[
        "deterministic_full",
        "deterministic_mechanical",
    ] = DEFAULT_CRITIC_MODE,
    output: Path | None = None,
) -> dict[str, Any]:
    """Run the default offline deterministic hypothesis critic report at $0 cost."""
    raw_corpus, all_packets = load_corpus_packets()
    if split == "held_out_evaluation":
        selected = [p for p in all_packets if p.split == "held_out_evaluation"]
    elif split == "development":
        selected = [p for p in all_packets if p.split == "development"]
    elif split == "all":
        selected = [
            p
            for p in all_packets
            if p.split in ("development", "held_out_evaluation")
        ]
    else:
        raise ValueError(f"Unsupported audit split: {split!r}")

    report = run_default_critic_report(selected, mode=mode)
    payload = {
        "corpus_version": raw_corpus["corpus_version"],
        "evaluator_version": CRITIC_EVALUATOR_VERSION,
        "split": split,
        "live_model_calls": 0,
        **report,
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(payload, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
    return payload


def evaluate(run_dir: Path, *, mode: str = "auto") -> dict[str, Any]:
    """Evaluate a completed or interrupted critic run directory and write `evaluation.json`."""
    run_dir = run_dir.resolve()
    _, all_packets = load_corpus_packets()
    eval_packets = [p for p in all_packets if p.split == "held_out_evaluation"]
    by_id = {p.packet_id: p for p in eval_packets}

    assessments_path = run_dir / "critic_assessments.json"
    llm_assessments: dict[str, CriticAssessment] = {}
    requests_log: list[dict[str, Any]] = []
    if assessments_path.exists():
        blob = json.loads(assessments_path.read_text(encoding="utf-8"))
        for pid, raw_a in (blob.get("assessments") or {}).items():
            llm_assessments[pid] = CriticAssessment.model_validate(raw_a)
        requests_log = list(blob.get("requests") or [])

    if mode == "deterministic_full" or (
        mode == "auto" and not assessments_path.exists()
    ):
        effective_mode = "deterministic_full"
        assessments = {
            p.packet_id: run_deterministic_full_detector(p)
            for p in eval_packets
        }
    elif mode == "deterministic_mechanical":
        effective_mode = "deterministic_mechanical"
        assessments = {
            p.packet_id: run_deterministic_mechanical_detector(p)
            for p in eval_packets
        }
    else:
        effective_mode = "llm"
        assessments = llm_assessments

    scored = score_critic_assessments(eval_packets, assessments)
    deterministic_guard_filtered_scored: dict[str, Any] | None = None
    if assessments_path.exists():
        filtered_llm = {
            pid: filter_llm_assessment_with_deterministic_guard(a, by_id[pid])
            for pid, a in llm_assessments.items()
            if pid in by_id
        }
        deterministic_guard_filtered_scored = score_critic_assessments(
            eval_packets, filtered_llm
        )

    resources = read_run_resources(run_dir)

    in_tokens = resources.input_tokens or 0
    out_tokens = resources.output_tokens or 0
    cached_tokens = resources.cached_input_tokens or 0
    uncached_in = max(0, in_tokens - cached_tokens)
    cached_adjusted_cost = (
        uncached_in * 0.75 + cached_tokens * 0.075 + out_tokens * 3.75
    ) / 1_000_000

    if effective_mode in ("deterministic_full", "deterministic_mechanical") and not assessments_path.exists():
        usable = len(assessments) == len(eval_packets)
        usable_reason = (
            f"all {len(eval_packets)} held-out critique packets evaluated with {effective_mode} ($0 cost)"
        )
    else:
        usable = (
            len(assessments) == len(eval_packets)
            and resources.cost_known
            and not resources.interrupted
        )
        usable_reason = (
            "all 10 held-out critique packets evaluated with certified cost"
            if usable
            else f"evaluated {len(assessments)}/{len(eval_packets)} packets (interrupted={resources.interrupted})"
        )
    report: dict[str, Any] = {
        "stage": "R07-hypothesis-critic",
        "evaluator_version": CRITIC_EVALUATOR_VERSION,
        "corpus_version": CRITIC_CORPUS_VERSION,
        "mode": effective_mode,
        "default_critic_mode": DEFAULT_CRITIC_MODE,
        "scored": scored,
        "requests": requests_log,
        "resources": {
            **resources.as_dict(),
            "upper_bound_table_cost_usd": round(
                resources.known_cost_usd, 6
            ),
            "cached_adjusted_cost_usd": round(cached_adjusted_cost, 6),
        },
        "stage_gate": {
            "usable": usable,
            "reason": usable_reason,
        },
    }
    if deterministic_guard_filtered_scored is not None:
        report["deterministic_guard_filtered_scored"] = (
            deterministic_guard_filtered_scored
        )
    (run_dir / "evaluation.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return report


def audit_run(
    run_dir: Path,
    *,
    definition: str | Path | None = None,
    output: Path | None = None,
) -> dict[str, Any]:
    """Run alignment-safe deterministic provenance and trace audit on a run directory ($0 cost)."""
    resolved_payload = (
        resolve_audit_payload(definition) if definition is not None else None
    )
    report = audit_run_directory(run_dir, payload=resolved_payload)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    aud = sub.add_parser(
        "audit",
        help="Run the adopted default offline deterministic hypothesis critic report ($0 cost)",
    )
    aud.add_argument(
        "--split",
        choices=("held_out_evaluation", "development", "all"),
        default="held_out_evaluation",
    )
    aud.add_argument(
        "--mode",
        choices=("deterministic_full", "deterministic_mechanical"),
        default=DEFAULT_CRITIC_MODE,
    )
    aud.add_argument("--output", type=Path, default=None)

    aud_run = sub.add_parser(
        "audit-run",
        help="Deterministically audit a family reconstruction run directory ($0 cost)",
    )
    aud_run.add_argument(
        "--run-dir",
        type=Path,
        required=True,
        help="Completed, planned-stop, or incomplete run directory to audit",
    )
    aud_run.add_argument(
        "--definition",
        type=str,
        default=None,
        help="Benchmark short name (burmish, polynesian, romance) or JSON definition/payload path",
    )
    aud_run.add_argument("--output", type=Path, default=None)

    ctrl = sub.add_parser(
        "controls",
        help="Run offline baselines, detectors, fake-provider controls, and derivation checks",
    )
    ctrl.add_argument("--output", type=Path, default=None)
    ctrl.add_argument("--live-run-dir", type=Path, default=None)

    fr = sub.add_parser(
        "freeze",
        help="Write frozen R07 inputs, manifest, pre-registration, and launch plan",
    )
    fr.add_argument("--output-dir", type=Path, required=True)

    rl = sub.add_parser(
        "run-live",
        help="Execute the single-seed serial critic pass over frozen held-out packets",
    )
    rl.add_argument("--inputs-dir", type=Path, required=True)
    rl.add_argument("--run-dir", type=Path, required=True)
    rl.add_argument("--model", default="gemini-3.8-flash")
    rl.add_argument("--preset", default="gemini")
    rl.add_argument("--reasoning-effort", default="medium")
    rl.add_argument("--provider-config", type=Path, required=True)
    rl.add_argument("--price-table", type=Path, required=True)
    rl.add_argument("--run-id", default="r07-critic-gemini-r07-critic")
    rl.add_argument("--timeout", type=float, default=300.0)
    rl.add_argument("--max-total-cost-usd", type=float, default=0.60)
    rl.add_argument("--max-run-seconds", type=float, default=1080.0)
    rl.add_argument("--no-preflight", action="store_true")

    ev = sub.add_parser(
        "evaluate",
        help="Score a critic run directory and write evaluation.json",
    )
    ev.add_argument("--run-dir", type=Path, required=True)
    ev.add_argument(
        "--mode",
        choices=("auto", "deterministic_full", "deterministic_mechanical", "llm"),
        default="auto",
    )

    args = parser.parse_args()
    if args.command == "audit":
        payload = audit(
            split=args.split,
            mode=args.mode,
            output=args.output,
        )
        print(json.dumps(payload, indent=2, default=str))
    elif args.command == "audit-run":
        report = audit_run(
            args.run_dir,
            definition=args.definition,
            output=args.output,
        )
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    elif args.command == "controls":
        payload = controls(args.live_run_dir)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(payload, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(payload, indent=2, default=str))
    elif args.command == "freeze":
        print(json.dumps(freeze(args.output_dir), indent=2))
    elif args.command == "run-live":
        summary = run_live(
            args.inputs_dir,
            args.run_dir,
            model=args.model,
            preset=args.preset,
            reasoning_effort=args.reasoning_effort,
            provider_config_path=args.provider_config,
            price_table_path=args.price_table,
            run_id=args.run_id,
            timeout=args.timeout,
            max_total_cost_usd=args.max_total_cost_usd,
            max_run_seconds=args.max_run_seconds,
            no_preflight=args.no_preflight,
        )
        print(json.dumps(summary, indent=2))
    elif args.command == "evaluate":
        report = evaluate(args.run_dir, mode=args.mode)
        print(json.dumps(report["stage_gate"]))


if __name__ == "__main__":
    main()
