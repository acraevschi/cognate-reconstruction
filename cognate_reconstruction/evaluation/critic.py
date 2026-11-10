"""Source-linked hypothesis critic and evaluation prototype (R07).

Provides strict schemas, evidence-boundary sanitization, leakage verification,
executable forward-revision integration, surface/mechanical baselines, an LLM
critic prompt/tool interface, deterministic scripted providers for offline
testing, pointer-grounded scoring, and a blinded human evaluation form builder.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from cognate_reconstruction.agent.providers.protocol import LLMProvider
from cognate_reconstruction.agent.schemas import (
    LLMMessage,
    LLMToolCall,
    LLMToolDefinition,
    MessageRole,
    ProviderResponse,
    ProviderResponseMetadata,
    ProviderUsage,
)
from cognate_reconstruction.evaluation.forward import (
    ForwardBranchHypothesis,
    build_residual_autopsy,
    compare_forward_hypotheses,
    compute_corpus_contrast_equivalence,
    evaluate_forward_split,
)
from cognate_reconstruction.schemas.common import NonEmptyStr, WorkbenchModel
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload

CRITIC_EVALUATOR_VERSION = "r07-critic-v1"
CRITIC_CORPUS_VERSION = "r07-critic-corpus-v1"
CRITIC_TOOL_NAME = "submit_hypothesis_critique"
DEFAULT_CRITIC_MODE: Literal["deterministic_full"] = "deterministic_full"
REAL_RUN_AUDIT_MODE: Literal["real_run_provenance_v1"] = "real_run_provenance_v1"


class DefectCategory(StrEnum):
    """Taxonomy of hypothesis defects evaluated by R07."""

    NONE = "none"
    UPSTREAM_TIE_COLLAPSE_MAJORITY = "upstream_tie_collapse_majority"
    SILENT_RESIDUE_DROP_TRUNCATION = "silent_residue_drop_truncation"
    UNINSPECTED_OUTGROUP_CITATION = "uninspected_outgroup_citation"
    WRONG_UNIT_OR_LOOKALIKE_SUPPORT = "wrong_unit_or_lookalike_support"
    FALSE_CONFIDENT_TIE_OR_MISREAD_ABSENCE = "false_confident_tie_or_misread_absence"
    UNIT_PROVENANCE_LOSS = "unit_provenance_loss"
    IDENTITY_CONFIDENCE_LENGTH_BIAS = "identity_confidence_length_bias"
    COUNTEREXAMPLE_OR_BLEEDING_ORDER = "counterexample_or_bleeding_order"


class CritiqueVerdict(StrEnum):
    """Top-level decision of a hypothesis critic on one claim packet."""

    DEFECT_FOUND = "defect_found"
    LEGITIMATE_NO_OBJECTION = "legitimate_no_objection"
    GENUINE_AMBIGUITY_NOTED = "genuine_ambiguity_noted"


class UncertaintyLabel(StrEnum):
    """Epistemic status distinguishing mechanical proof from fallible inference."""

    EXACT_MECHANICAL = "exact_mechanical"
    WARRANTED_INFERENCE_CRITIQUE = "warranted_inference_critique"
    GENUINE_UNDERDETERMINATION = "genuine_underdetermination"
    NO_DEFECT = "no_defect"


class EvidenceChannel(StrEnum):
    """Explicit separation between inference-time daughter evidence and held-out gold."""

    INFERENCE_AVAILABLE_DAUGHTER_FITTING = "inference_available_daughter_fitting"
    OFFLINE_HELD_OUT_SCORER_ONLY = "offline_held_out_scorer_only"


def _coerce_tuples(
    data: Any,
    tuple_fields: Sequence[str],
) -> Any:
    """Allow JSON-loaded lists to validate cleanly against strict tuple fields."""
    if not isinstance(data, Mapping):
        return data
    updated = dict(data)
    for field_name in tuple_fields:
        if field_name in updated and isinstance(updated[field_name], list):
            updated[field_name] = tuple(updated[field_name])
    return updated


class CritiqueClaimRecord(WorkbenchModel):
    """One committed or candidate reconstruction claim to be audited."""

    claim_id: NonEmptyStr
    node_id: NonEmptyStr
    target_concept_id: NonEmptyStr
    unit_id: NonEmptyStr
    set_ids: tuple[NonEmptyStr, ...] = ()
    validation_call_id: NonEmptyStr
    column_indices: tuple[int, ...] = ()
    reflexes: tuple[str | None, ...] = ()
    proto_segment: str | None = None
    confidence: float = Field(gt=0.0, le=1.0)
    support: int = Field(default=1, ge=1)
    rationale: NonEmptyStr
    directionality_rationale: str | None = None
    residue_policy: str = "drop"
    unaccounted_column_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    total_local_sets_at_node: int = Field(default=1, ge=1)
    covered_local_sets_count: int = Field(default=1, ge=0)
    dropped_concept_ids: tuple[str, ...] = ()
    assembled_candidate_unit_id: str | None = None
    child_source_unit_ids: tuple[str, ...] = ()
    competing_beam_candidates: tuple[dict[str, Any], ...] = ()
    forward_cascade_rules: tuple[str, ...] = ()
    candidate_revision_rules: tuple[str, ...] = ()
    candidate_revision_confidence: float | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_list_fields(cls, data: Any) -> Any:
        return _coerce_tuples(
            data,
            (
                "set_ids",
                "column_indices",
                "reflexes",
                "dropped_concept_ids",
                "child_source_unit_ids",
                "competing_beam_candidates",
                "forward_cascade_rules",
                "candidate_revision_rules",
            ),
        )


class CritiqueEvidenceBundle(WorkbenchModel):
    """Inference-available evidence bundle accompanying a critique claim."""

    newick: NonEmptyStr
    active_child_ids: tuple[NonEmptyStr, ...]
    active_child_forms: dict[str, dict[str, Any]]
    outgroup_forms: dict[str, dict[str, Any]] = Field(default_factory=dict)
    missing_outgroup_varieties: tuple[str, ...] = ()
    prior_node_commit_summary: dict[str, Any] | None = None
    trajectory_navigation_summary: dict[str, Any]
    provisional_proxy_note: str | None = None
    contrast_equivalence_summary: dict[str, Any] | None = None
    forward_execution_summary: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_list_fields(cls, data: Any) -> Any:
        return _coerce_tuples(
            data,
            (
                "active_child_ids",
                "missing_outgroup_varieties",
            ),
        )


class ExpectedCritiqueGroundTruth(WorkbenchModel):
    """Sealed ground-truth specification for offline scoring of a critique packet."""

    is_defective: bool
    expected_verdict: CritiqueVerdict
    expected_defect_category: DefectCategory
    accepted_defect_categories: tuple[DefectCategory, ...] = ()
    expected_uncertainty_label: UncertaintyLabel
    required_source_ids: tuple[str, ...] = ()
    required_call_ids: tuple[str, ...] = ()
    required_set_ids: tuple[str, ...] = ()
    required_column_indices: tuple[int, ...] = ()
    expected_repaired_examples: tuple[str, ...] = ()
    expected_newly_broken_examples: tuple[str, ...] = ()
    independent_derivation_note: NonEmptyStr

    @model_validator(mode="before")
    @classmethod
    def _coerce_list_fields(cls, data: Any) -> Any:
        updated = _coerce_tuples(
            data,
            (
                "accepted_defect_categories",
                "required_source_ids",
                "required_call_ids",
                "required_set_ids",
                "required_column_indices",
                "expected_repaired_examples",
                "expected_newly_broken_examples",
            ),
        )
        if isinstance(updated, dict):
            if isinstance(updated.get("expected_verdict"), str):
                updated["expected_verdict"] = CritiqueVerdict(
                    updated["expected_verdict"]
                )
            if isinstance(updated.get("expected_defect_category"), str):
                updated["expected_defect_category"] = DefectCategory(
                    updated["expected_defect_category"]
                )
            if isinstance(updated.get("expected_uncertainty_label"), str):
                updated["expected_uncertainty_label"] = UncertaintyLabel(
                    updated["expected_uncertainty_label"]
                )
            if "accepted_defect_categories" in updated and isinstance(
                updated["accepted_defect_categories"], tuple
            ):
                updated["accepted_defect_categories"] = tuple(
                    DefectCategory(x) if isinstance(x, str) else x
                    for x in updated["accepted_defect_categories"]
                )
        return updated


class CritiquePacket(WorkbenchModel):
    """Full audit packet pairing a claim and evidence bundle with sealed ground truth."""

    packet_id: NonEmptyStr
    blind_code: NonEmptyStr
    split: Literal[
        "development",
        "held_out_evaluation",
        "offline_gold_residual_only",
    ]
    pair_id: NonEmptyStr
    pair_role: Literal[
        "defective_claim",
        "legitimate_paired_control",
        "genuine_ambiguity_control",
        "irrelevant_perturbation_control",
        "offline_gold_residual_control",
    ]
    evidence_channel: EvidenceChannel
    origin_artifact: NonEmptyStr
    claim: CritiqueClaimRecord
    evidence: CritiqueEvidenceBundle
    ground_truth: ExpectedCritiqueGroundTruth

    @model_validator(mode="before")
    @classmethod
    def _coerce_enum_fields(cls, data: Any) -> Any:
        if not isinstance(data, Mapping):
            return data
        updated = dict(data)
        if isinstance(updated.get("evidence_channel"), str):
            updated["evidence_channel"] = EvidenceChannel(
                updated["evidence_channel"]
            )
        return updated


class CriticAssessment(WorkbenchModel):
    """Structured critique output emitted by a baseline, mechanical detector, or LLM critic."""

    packet_id: NonEmptyStr
    evidence_channel: EvidenceChannel = (
        EvidenceChannel.INFERENCE_AVAILABLE_DAUGHTER_FITTING
    )
    verdict: CritiqueVerdict
    defect_category: DefectCategory
    cited_source_ids: tuple[str, ...] = ()
    cited_call_ids: tuple[str, ...] = ()
    cited_set_ids: tuple[str, ...] = ()
    cited_column_indices: tuple[int, ...] = ()
    observed_discrepancy: NonEmptyStr
    potential_consequence: NonEmptyStr
    uncertainty_label: UncertaintyLabel
    discriminating_check_or_falsifier: NonEmptyStr
    repaired_examples: tuple[str, ...] = ()
    newly_broken_examples: tuple[str, ...] = ()
    is_fallible_interpretation: bool = False

    @model_validator(mode="before")
    @classmethod
    def _coerce_list_fields(cls, data: Any) -> Any:
        updated = _coerce_tuples(
            data,
            (
                "cited_source_ids",
                "cited_call_ids",
                "cited_set_ids",
                "cited_column_indices",
                "repaired_examples",
                "newly_broken_examples",
            ),
        )
        if isinstance(updated, dict):
            if isinstance(updated.get("evidence_channel"), str):
                updated["evidence_channel"] = EvidenceChannel(
                    updated["evidence_channel"]
                )
            if isinstance(updated.get("verdict"), str):
                updated["verdict"] = CritiqueVerdict(updated["verdict"])
            if isinstance(updated.get("defect_category"), str):
                updated["defect_category"] = DefectCategory(
                    updated["defect_category"]
                )
            if isinstance(updated.get("uncertainty_label"), str):
                updated["uncertainty_label"] = UncertaintyLabel(
                    updated["uncertainty_label"]
                )
        return updated


def to_model_visible_packet(packet: CritiquePacket) -> dict[str, Any]:
    """Sanitize a ``CritiquePacket`` for model/critic consumption.

    Refuses ``offline_held_out_scorer_only`` / ``offline_gold_residual_only``
    packets and strips all ground-truth labels, pair metadata, origin artifact
    paths, and internal packet IDs.
    """
    if (
        packet.evidence_channel == EvidenceChannel.OFFLINE_HELD_OUT_SCORER_ONLY
        or packet.split == "offline_gold_residual_only"
    ):
        raise ValueError(
            f"Packet {packet.packet_id!r} belongs to channel "
            f"{packet.evidence_channel.value!r} / split {packet.split!r} and "
            "must never be exposed to an inference-time critic."
        )
    claim_dump = packet.claim.model_dump(mode="json")
    claim_dump["claim_id"] = f"claim_{packet.blind_code}"
    evidence_dump = packet.evidence.model_dump(mode="json")
    return {
        "packet_id": packet.blind_code,
        "evidence_channel": packet.evidence_channel.value,
        "claim": claim_dump,
        "evidence": evidence_dump,
    }


def verify_no_critic_leakage(
    packets: Sequence[CritiquePacket],
    model_visible_packets: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Verify that no held-out scorer packet, ground-truth field, or internal ID leaked."""
    serialized = json.dumps(list(model_visible_packets), ensure_ascii=False)

    offline_packets = [
        p
        for p in packets
        if p.evidence_channel == EvidenceChannel.OFFLINE_HELD_OUT_SCORER_ONLY
        or p.split == "offline_gold_residual_only"
    ]
    offline_exposed: list[str] = []
    for p in offline_packets:
        if p.packet_id in serialized or p.blind_code in serialized:
            offline_exposed.append(p.packet_id)

    for vp in model_visible_packets:
        if (
            vp.get("evidence_channel")
            == EvidenceChannel.OFFLINE_HELD_OUT_SCORER_ONLY.value
        ):
            offline_exposed.append(str(vp.get("packet_id", "unknown")))

    forbidden_keys = (
        "ground_truth",
        "expected_verdict",
        "expected_defect_category",
        "accepted_defect_categories",
        "expected_uncertainty_label",
        "independent_derivation_note",
        "pair_role",
        "pair_id",
        "origin_artifact",
    )
    present_forbidden_keys: list[str] = []
    for key in forbidden_keys:
        if f'"{key}"' in serialized:
            present_forbidden_keys.append(key)

    leaked_internal_packet_ids: list[str] = []
    leaked_ground_truth_notes: list[str] = []
    for p in packets:
        if p.packet_id != p.blind_code and f'"{p.packet_id}"' in serialized:
            leaked_internal_packet_ids.append(p.packet_id)
        note = p.ground_truth.independent_derivation_note
        if note and note in serialized:
            leaked_ground_truth_notes.append(p.packet_id)

    ok = (
        not offline_exposed
        and not present_forbidden_keys
        and not leaked_internal_packet_ids
        and not leaked_ground_truth_notes
    )
    return {
        "ok": ok,
        "total_packets_checked": len(packets),
        "model_visible_packet_count": len(model_visible_packets),
        "offline_scorer_only_packets_exposed": sorted(set(offline_exposed)),
        "forbidden_keys_present": present_forbidden_keys,
        "leaked_internal_packet_ids": sorted(set(leaked_internal_packet_ids)),
        "leaked_ground_truth_notes": sorted(set(leaked_ground_truth_notes)),
    }


def evaluate_forward_revision_on_packet(
    ancestor_forms: Mapping[str, Sequence[str]],
    observed_daughter_forms: Mapping[str, Sequence[str]],
    before_rules: Sequence[str],
    after_rules: Sequence[str],
    *,
    parent_node_id: str = "r",
    child_node_id: str = "a",
    evidence_channel: str = "inference_available_daughter_fitting",
) -> dict[str, Any]:
    """Execute and compare original vs. candidate forward cascades on inference-available forms."""
    if evidence_channel == EvidenceChannel.OFFLINE_HELD_OUT_SCORER_ONLY.value:
        raise ValueError(
            "evaluate_forward_revision_on_packet cannot run on "
            "offline_held_out_scorer_only evidence."
        )

    concept_ids = tuple(
        cid for cid in ancestor_forms if cid in observed_daughter_forms
    )
    concept_to_etymon_id = {cid: cid for cid in concept_ids}

    before_hypothesis = ForwardBranchHypothesis(
        hypothesis_id="before_revision",
        parent_node_id=parent_node_id,
        child_node_id=child_node_id,
        rule_sources=tuple(before_rules),
    )
    after_hypothesis = ForwardBranchHypothesis(
        hypothesis_id="after_revision",
        parent_node_id=parent_node_id,
        child_node_id=child_node_id,
        rule_sources=tuple(after_rules),
    )

    before_eval = evaluate_forward_split(
        before_hypothesis,
        split_name="dev_critic_before",
        concept_ids=concept_ids,
        concept_to_etymon_id=concept_to_etymon_id,
        ancestor_forms=ancestor_forms,
        target_daughter_forms=observed_daughter_forms,
    )
    after_eval = evaluate_forward_split(
        after_hypothesis,
        split_name="dev_critic_after",
        concept_ids=concept_ids,
        concept_to_etymon_id=concept_to_etymon_id,
        ancestor_forms=ancestor_forms,
        target_daughter_forms=observed_daughter_forms,
    )

    diff = compare_forward_hypotheses(before_eval, after_eval)
    before_autopsy = build_residual_autopsy(
        before_eval["per_concept"],
        evidence_channel=evidence_channel,
    )
    after_autopsy = build_residual_autopsy(
        after_eval["per_concept"],
        evidence_channel=evidence_channel,
    )
    before_pred = {
        str(item["concept_id"]): item["predicted_segments"]
        for item in before_eval["per_concept"]
    }
    contrast_eq = compute_corpus_contrast_equivalence(
        before_pred,
        observed_daughter_forms,
        concept_ids,
    )

    return {
        "evidence_channel": evidence_channel,
        "parent_node_id": parent_node_id,
        "child_node_id": child_node_id,
        "before_rules": list(before_rules),
        "after_rules": list(after_rules),
        "dev_exact_rate": float(before_eval["validated_only"]["exact_rate"]),
        "after_exact_rate": float(after_eval["validated_only"]["exact_rate"]),
        "before_mean_ned": before_eval["validated_only"]["mean_ned"],
        "after_mean_ned": after_eval["validated_only"]["mean_ned"],
        "mismatched_concept_ids": list(before_autopsy["mismatched_concept_ids"]),
        "after_mismatched_concept_ids": list(
            after_autopsy["mismatched_concept_ids"]
        ),
        "repaired_concept_ids": list(diff["repaired_concept_ids"]),
        "newly_broken_concept_ids": list(diff["newly_broken_concept_ids"]),
        "unchanged_exact_concept_ids": list(
            diff["unchanged_exact_concept_ids"]
        ),
        "unchanged_wrong_concept_ids": list(
            diff["unchanged_wrong_concept_ids"]
        ),
        "delta_validated_exact_count": int(diff["delta_validated_exact_count"]),
        "delta_validated_exact_rate": float(diff["delta_validated_exact_rate"]),
        "delta_validated_mean_ned": diff["delta_validated_mean_ned"],
        "per_concept_changes": list(diff["per_concept_changes"]),
        "before_residual_autopsy": before_autopsy,
        "after_residual_autopsy": after_autopsy,
        "daughter_contrast_equivalence": contrast_eq,
        "observed_forms": {
            f"{child_node_id}:{cid}": list(observed_daughter_forms[cid])
            for cid in concept_ids
        },
    }


def _collect_claim_evidence_pointers(
    claim: CritiqueClaimRecord,
    evidence: CritiqueEvidenceBundle,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[int, ...]]:
    """Collect valid source, call, set, and column pointers from model-visible claim & evidence."""
    sources: list[str] = []
    for k in evidence.active_child_forms:
        if k not in sources:
            sources.append(k)
    for k in evidence.outgroup_forms:
        if k not in sources:
            sources.append(k)
    if evidence.prior_node_commit_summary:
        for k in evidence.prior_node_commit_summary.get("leaf_reflexes", {}):
            if k not in sources:
                sources.append(k)
    if evidence.forward_execution_summary:
        for k in evidence.forward_execution_summary.get("observed_forms", {}):
            if k not in sources:
                sources.append(k)

    calls: list[str] = [claim.validation_call_id]
    for cid in evidence.trajectory_navigation_summary.get(
        "inspected_call_ids", ()
    ):
        if str(cid) not in calls:
            calls.append(str(cid))
    if (
        evidence.prior_node_commit_summary
        and "validation_call_id" in evidence.prior_node_commit_summary
    ):
        prior_call = str(
            evidence.prior_node_commit_summary["validation_call_id"]
        )
        if prior_call not in calls:
            calls.append(prior_call)

    sets: list[str] = list(claim.set_ids)
    if (
        evidence.prior_node_commit_summary
        and "set_id" in evidence.prior_node_commit_summary
    ):
        prior_set = str(evidence.prior_node_commit_summary["set_id"])
        if prior_set not in sets:
            sets.append(prior_set)

    cols: tuple[int, ...] = tuple(claim.column_indices)
    return tuple(sources), tuple(calls), tuple(sets), cols


def _extract_forward_revision_examples(
    evidence: CritiqueEvidenceBundle,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Extract repaired and newly broken example concept IDs from forward execution summary."""
    fwd = evidence.forward_execution_summary
    if not fwd:
        return (), ()
    repaired = tuple(
        str(x)
        for x in (
            fwd.get("repaired_examples")
            or fwd.get("repaired_concept_ids")
            or ()
        )
    )
    newly_broken = tuple(
        str(x)
        for x in (
            fwd.get("newly_broken_examples")
            or fwd.get("newly_broken_concept_ids")
            or ()
        )
    )
    return repaired, newly_broken


def _rationale_mentions_outgroup(
    claim: CritiqueClaimRecord,
    evidence: CritiqueEvidenceBundle,
) -> bool:
    combined = (
        f"{claim.rationale} {claim.directionality_rationale or ''}".lower()
    )
    if "outgroup" in combined or "witness" in combined or "external" in combined:
        return True
    for form_id, info in evidence.outgroup_forms.items():
        var_id = form_id.split(":")[0].lower()
        if form_id.lower() in combined:
            return True
        if var_id and (
            f" {var_id} " in f" {combined} "
            or f"({var_id})" in combined
            or f"node {var_id}" in combined
            or f"variety {var_id}" in combined
        ):
            return True
        if isinstance(info, Mapping):
            node = str(info.get("variety_id") or info.get("node_id") or "").lower()
            if node and f" {node} " in f" {combined} ":
                return True
    return False


def _has_length_biased_beam_candidates(claim: CritiqueClaimRecord) -> bool:
    if (
        len(claim.competing_beam_candidates) < 2
        or not claim.reflexes
        or len(set(claim.reflexes)) != 1
        or claim.reflexes[0] is None
        or claim.confidence >= 1.0
    ):
        return False
    lengths: list[int] = []
    probs: list[float] = []
    for cand in claim.competing_beam_candidates:
        if "segment_count" in cand and isinstance(cand["segment_count"], int):
            lengths.append(cand["segment_count"])
        elif "length" in cand and isinstance(cand["length"], int):
            lengths.append(cand["length"])
        elif "segments" in cand:
            segs = cand["segments"]
            if isinstance(segs, (list, tuple)):
                lengths.append(len(segs))
            elif isinstance(segs, str):
                lengths.append(len(segs.split()))
        elif "form" in cand and isinstance(cand["form"], str):
            lengths.append(len(cand["form"].split()))

        for prob_key in (
            "probability",
            "prob",
            "score",
            "probability_at_claimed_confidence",
        ):
            if prob_key in cand and isinstance(cand[prob_key], (int, float)):
                probs.append(round(float(cand[prob_key]), 6))
                break

    return len(set(lengths)) > 1 and (not probs or len(set(probs)) > 1)


def run_existing_residue_ambiguity_baseline(
    packet: CritiquePacket,
) -> CriticAssessment:
    """Baseline checking only surface unaccounted column rate (`unaccounted_column_rate > 0.0`)."""
    sources, calls, sets, cols = _collect_claim_evidence_pointers(
        packet.claim, packet.evidence
    )
    if packet.claim.unaccounted_column_rate > 0.0:
        return CriticAssessment(
            packet_id=packet.packet_id,
            evidence_channel=packet.evidence_channel,
            verdict=CritiqueVerdict.DEFECT_FOUND,
            defect_category=DefectCategory.SILENT_RESIDUE_DROP_TRUNCATION,
            cited_source_ids=sources,
            cited_call_ids=calls,
            cited_set_ids=sets,
            cited_column_indices=cols,
            observed_discrepancy=(
                f"Unaccounted column rate is {packet.claim.unaccounted_column_rate:.2f} "
                f"under residue_policy={packet.claim.residue_policy!r}."
            ),
            potential_consequence=(
                "Uncommitted local correspondence sets are silently dropped, "
                "truncating reconstructed parent forms."
            ),
            uncertainty_label=UncertaintyLabel.EXACT_MECHANICAL,
            discriminating_check_or_falsifier=(
                "Inspect ConceptAssemblyReport.unaccounted_columns and switch "
                "residue_policy to retain or commit all local sets."
            ),
            is_fallible_interpretation=False,
        )
    return CriticAssessment(
        packet_id=packet.packet_id,
        evidence_channel=packet.evidence_channel,
        verdict=CritiqueVerdict.LEGITIMATE_NO_OBJECTION,
        defect_category=DefectCategory.NONE,
        cited_source_ids=sources,
        cited_call_ids=calls,
        cited_set_ids=sets,
        cited_column_indices=cols,
        observed_discrepancy="Unaccounted column rate is 0.0; no surface residue warning.",
        potential_consequence="None detected by residue-rate baseline.",
        uncertainty_label=UncertaintyLabel.NO_DEFECT,
        discriminating_check_or_falsifier="Check unaccounted_column_rate == 0.0.",
        is_fallible_interpretation=False,
    )


def run_fixed_evidence_checklist_baseline(
    packet: CritiquePacket,
) -> CriticAssessment:
    """Rigid surface checklist baseline susceptible to relabelling and missing-outgroup false positives."""
    claim = packet.claim
    evidence = packet.evidence
    sources, calls, sets, cols = _collect_claim_evidence_pointers(
        claim, evidence
    )
    repaired, newly_broken = _extract_forward_revision_examples(evidence)

    if claim.unaccounted_column_rate > 0.0:
        return CriticAssessment(
            packet_id=packet.packet_id,
            evidence_channel=packet.evidence_channel,
            verdict=CritiqueVerdict.DEFECT_FOUND,
            defect_category=DefectCategory.SILENT_RESIDUE_DROP_TRUNCATION,
            cited_source_ids=sources,
            cited_call_ids=calls,
            cited_set_ids=sets,
            cited_column_indices=cols,
            observed_discrepancy=(
                f"Checklist rule 1 triggered: unaccounted_column_rate={claim.unaccounted_column_rate:.2f} > 0."
            ),
            potential_consequence="Silent truncation of uncommitted correspondence columns.",
            uncertainty_label=UncertaintyLabel.EXACT_MECHANICAL,
            discriminating_check_or_falsifier="Commit all local sets or set residue_policy='retain'.",
            is_fallible_interpretation=False,
        )

    if (
        not evidence.trajectory_navigation_summary.get(
            "concept_outgroup_forms_seen", True
        )
        and evidence.outgroup_forms
    ):
        return CriticAssessment(
            packet_id=packet.packet_id,
            evidence_channel=packet.evidence_channel,
            verdict=CritiqueVerdict.DEFECT_FOUND,
            defect_category=DefectCategory.UNINSPECTED_OUTGROUP_CITATION,
            cited_source_ids=sources,
            cited_call_ids=calls,
            cited_set_ids=sets,
            cited_column_indices=cols,
            observed_discrepancy=(
                "Checklist rule 2 triggered: concept_outgroup_forms_seen is False "
                "while outgroup_forms exist."
            ),
            potential_consequence="Outgroup cited without non-survey tool inspection.",
            uncertainty_label=UncertaintyLabel.EXACT_MECHANICAL,
            discriminating_check_or_falsifier="Call polarize or get_alignments on the target concept.",
            is_fallible_interpretation=False,
        )

    if (
        evidence.contrast_equivalence_summary is not None
        and float(
            evidence.contrast_equivalence_summary.get("raw_exact_rate", 1.0)
        )
        < 1.0
    ):
        return CriticAssessment(
            packet_id=packet.packet_id,
            evidence_channel=packet.evidence_channel,
            verdict=CritiqueVerdict.DEFECT_FOUND,
            defect_category=DefectCategory.COUNTEREXAMPLE_OR_BLEEDING_ORDER,
            cited_source_ids=sources,
            cited_call_ids=calls,
            cited_set_ids=sets,
            cited_column_indices=cols,
            observed_discrepancy=(
                "Checklist surface symbol rule triggered: raw_exact_rate < 1.0 "
                "regardless of bijective contrast equivalence."
            ),
            potential_consequence="Flagged symbol mismatch against reference label.",
            uncertainty_label=UncertaintyLabel.WARRANTED_INFERENCE_CRITIQUE,
            discriminating_check_or_falsifier="Compare raw proto symbols directly.",
            repaired_examples=repaired,
            newly_broken_examples=newly_broken,
            is_fallible_interpretation=True,
        )

    if (
        claim.proto_segment is not None
        and None in claim.reflexes
        and len(evidence.missing_outgroup_varieties) >= 2
    ):
        return CriticAssessment(
            packet_id=packet.packet_id,
            evidence_channel=packet.evidence_channel,
            verdict=CritiqueVerdict.DEFECT_FOUND,
            defect_category=DefectCategory.WRONG_UNIT_OR_LOOKALIKE_SUPPORT,
            cited_source_ids=sources,
            cited_call_ids=calls,
            cited_set_ids=sets,
            cited_column_indices=cols,
            observed_discrepancy=(
                "Checklist 2-of-3 outgroup rule triggered: fewer than 2 outgroups "
                "attest the piece because 2 outgroups are missing."
            ),
            potential_consequence="Assumed innovation due to missing outgroup varieties.",
            uncertainty_label=UncertaintyLabel.WARRANTED_INFERENCE_CRITIQUE,
            discriminating_check_or_falsifier="Require 2 of 3 outgroups to attest the segment.",
            is_fallible_interpretation=True,
        )

    return CriticAssessment(
        packet_id=packet.packet_id,
        evidence_channel=packet.evidence_channel,
        verdict=CritiqueVerdict.LEGITIMATE_NO_OBJECTION,
        defect_category=DefectCategory.NONE,
        cited_source_ids=sources,
        cited_call_ids=calls,
        cited_set_ids=sets,
        cited_column_indices=cols,
        observed_discrepancy="No surface checklist rule triggered.",
        potential_consequence="None.",
        uncertainty_label=UncertaintyLabel.NO_DEFECT,
        discriminating_check_or_falsifier="Surface checklist passed.",
        is_fallible_interpretation=False,
    )


def _detect_mechanical_defect(
    packet_id: str,
    evidence_channel: EvidenceChannel,
    claim: CritiqueClaimRecord,
    evidence: CritiqueEvidenceBundle,
) -> CriticAssessment | None:
    """Return a provable mechanical `CriticAssessment` if a deterministic invariant fails, else None."""
    sources, calls, sets, cols = _collect_claim_evidence_pointers(
        claim, evidence
    )
    repaired, newly_broken = _extract_forward_revision_examples(evidence)

    # 1. Uninspected outgroup citation
    if not evidence.trajectory_navigation_summary.get(
        "concept_outgroup_forms_seen", True
    ) and _rationale_mentions_outgroup(claim, evidence):
        return CriticAssessment(
            packet_id=packet_id,
            evidence_channel=evidence_channel,
            verdict=CritiqueVerdict.DEFECT_FOUND,
            defect_category=DefectCategory.UNINSPECTED_OUTGROUP_CITATION,
            cited_source_ids=sources,
            cited_call_ids=calls,
            cited_set_ids=sets,
            cited_column_indices=cols,
            observed_discrepancy=(
                "Claim rationale cites outgroup support for this concept, but "
                "trajectory_navigation_summary.concept_outgroup_forms_seen is False "
                "(only survey presence or no non-survey tool inspected the outgroup form)."
            ),
            potential_consequence=(
                "Polarization relies on uninspected outgroup forms that may belong "
                "to a different cognate unit or lack the claimed alignment column."
            ),
            uncertainty_label=UncertaintyLabel.EXACT_MECHANICAL,
            discriminating_check_or_falsifier=(
                f"Inspect {claim.target_concept_id!r} outgroup forms with "
                "search_forms, get_alignments, or single-concept polarize before citing."
            ),
            is_fallible_interpretation=False,
        )

    # 2. Silent residue drop truncation
    if (
        claim.residue_policy == "drop"
        and claim.unaccounted_column_rate > 0.0
        and len(claim.dropped_concept_ids) > 0
    ):
        return CriticAssessment(
            packet_id=packet_id,
            evidence_channel=evidence_channel,
            verdict=CritiqueVerdict.DEFECT_FOUND,
            defect_category=DefectCategory.SILENT_RESIDUE_DROP_TRUNCATION,
            cited_source_ids=sources,
            cited_call_ids=calls,
            cited_set_ids=sets,
            cited_column_indices=cols,
            observed_discrepancy=(
                f"Committed inventory covers {claim.covered_local_sets_count}/"
                f"{claim.total_local_sets_at_node} local sets under residue_policy='drop' "
                f"(unaccounted_column_rate={claim.unaccounted_column_rate:.4f}), "
                f"silently truncating concepts {list(claim.dropped_concept_ids)}."
            ),
            potential_consequence=(
                "Uncommitted columns are deleted from assembled parent forms, "
                "producing truncated or empty reconstructions."
            ),
            uncertainty_label=UncertaintyLabel.EXACT_MECHANICAL,
            discriminating_check_or_falsifier=(
                "Preview with test_proto_assembly and verify unaccounted_columns == 0 "
                "or use residue_policy='retain' with explicit local commitments."
            ),
            is_fallible_interpretation=False,
        )

    # 3. Loss of cognate-unit FormAnalysis provenance
    if (
        claim.assembled_candidate_unit_id == "whole:unknown"
        and len(claim.child_source_unit_ids) > 0
        and all(u.startswith("cog:") for u in claim.child_source_unit_ids)
    ):
        return CriticAssessment(
            packet_id=packet_id,
            evidence_channel=evidence_channel,
            verdict=CritiqueVerdict.DEFECT_FOUND,
            defect_category=DefectCategory.UNIT_PROVENANCE_LOSS,
            cited_source_ids=sources,
            cited_call_ids=calls,
            cited_set_ids=sets,
            cited_column_indices=cols,
            observed_discrepancy=(
                f"Assembled candidate carries unit_id='whole:unknown' despite all "
                f"child source forms carrying explicit cognate units {list(claim.child_source_unit_ids)}."
            ),
            potential_consequence=(
                "Upper-node traversal loses cognate-unit scoping and cannot align "
                "or polarize this parent form against same-unit outgroups."
            ),
            uncertainty_label=UncertaintyLabel.EXACT_MECHANICAL,
            discriminating_check_or_falsifier=(
                "Verify ReconstructionCandidate.analysis.pieces preserve cog:* "
                "cognate_set_id provenance from child_source_unit_ids."
            ),
            is_fallible_interpretation=False,
        )

    # 4. Identity-confidence column-length bias
    if _has_length_biased_beam_candidates(claim):
        return CriticAssessment(
            packet_id=packet_id,
            evidence_channel=evidence_channel,
            verdict=CritiqueVerdict.DEFECT_FOUND,
            defect_category=DefectCategory.IDENTITY_CONFIDENCE_LENGTH_BIAS,
            cited_source_ids=sources,
            cited_call_ids=calls,
            cited_set_ids=sets,
            cited_column_indices=cols,
            observed_discrepancy=(
                f"Identity correspondence {list(claim.reflexes)} -> *{claim.proto_segment} "
                f"is committed at confidence={claim.confidence} (< 1.0), multiplying "
                "per-column confidence across unequal candidate lengths and breaking "
                "an exact tie in competing_beam_candidates in favor of the shorter candidate."
            ),
            potential_consequence=(
                "Arbitrary identity confidence < 1.0 induces a systematic length "
                "penalty against longer multi-column candidates."
            ),
            uncertainty_label=UncertaintyLabel.EXACT_MECHANICAL,
            discriminating_check_or_falsifier=(
                "Re-run test_proto_assembly with identity retention confidence=1.0 "
                "and verify competing_beam_candidates return to 0.5000 / 0.5000."
            ),
            is_fallible_interpretation=False,
        )

    # 5. Executable forward cascade / revision mismatch
    fwd = evidence.forward_execution_summary
    contrast = evidence.contrast_equivalence_summary or {}
    is_bijective_equiv = bool(contrast.get("is_bijective_relabelling", False)) and (
        float(contrast.get("corpus_bcubed_f1", 0.0)) >= 0.999999
        and (
            fwd is None
            or (
                float(fwd.get("dev_exact_rate", 1.0)) >= 1.0
                and not fwd.get("mismatched_concept_ids")
                and not newly_broken
            )
        )
    )
    if fwd is not None and not is_bijective_equiv:
        dev_exact_rate = float(fwd.get("dev_exact_rate", 1.0))
        mismatched = tuple(fwd.get("mismatched_concept_ids") or ())
        if (dev_exact_rate < 1.0 and len(mismatched) > 0) or len(newly_broken) > 0:
            return CriticAssessment(
                packet_id=packet_id,
                evidence_channel=evidence_channel,
                verdict=CritiqueVerdict.DEFECT_FOUND,
                defect_category=DefectCategory.COUNTEREXAMPLE_OR_BLEEDING_ORDER,
                cited_source_ids=sources,
                cited_call_ids=calls,
                cited_set_ids=sets,
                cited_column_indices=cols,
                observed_discrepancy=(
                    f"Forward cascade execution on inference-available daughter forms "
                    f"yields dev_exact_rate={dev_exact_rate:.4f} with mismatched concepts "
                    f"{list(mismatched)}, repaired={list(repaired)}, newly_broken={list(newly_broken)}."
                ),
                potential_consequence=(
                    "Bleeding rule order or unconditioned lateral rule fails to "
                    "derive observed daughter reflexes on inference-available concepts."
                ),
                uncertainty_label=UncertaintyLabel.EXACT_MECHANICAL,
                discriminating_check_or_falsifier=(
                    "Execute evaluate_forward_revision_on_packet on inference-available "
                    "daughter forms and verify repaired_examples and newly_broken_examples."
                ),
                repaired_examples=repaired,
                newly_broken_examples=newly_broken,
                is_fallible_interpretation=False,
            )

    return None


def _is_same_unit_outgroup(
    info: Mapping[str, Any],
    claim_unit_id: str,
) -> bool:
    if "same_unit_as_target" in info:
        return bool(info["same_unit_as_target"])
    if "same_unit" in info:
        return bool(info["same_unit"])
    if "in_target_unit" in info:
        return bool(info["in_target_unit"])
    if "unit_ids" in info and isinstance(info["unit_ids"], (list, tuple)):
        return claim_unit_id in [str(u) for u in info["unit_ids"]]
    unit = info.get("unit_id") or info.get("cognate_set_id") or info.get("scope_id")
    if unit is None:
        return True
    return str(unit) == claim_unit_id


def _outgroup_column_segment(
    info: Mapping[str, Any],
    column_indices: Sequence[int],
    claim_unit_id: str = "",
) -> str | None:
    if (
        claim_unit_id
        and "piece_breakdown" in info
        and isinstance(info["piece_breakdown"], (list, tuple))
    ):
        for piece in info["piece_breakdown"]:
            if isinstance(piece, Mapping) and str(piece.get("unit_id")) == claim_unit_id:
                piece_segs = piece.get("segments", ())
                if isinstance(piece_segs, (list, tuple)):
                    if column_indices and 0 <= column_indices[0] < len(piece_segs):
                        val = piece_segs[column_indices[0]]
                        return None if val in (None, "Ø", "∅", "-", "") else str(val)
                    return None
    for key in ("segment", "aligned_segment", "reflex", "column_segment"):
        if key in info:
            val = info[key]
            if val is None or val in ("Ø", "∅", "-", ""):
                return None
            return str(val)
    if "segments" in info and isinstance(info["segments"], (list, tuple)):
        segs = info["segments"]
        if column_indices and 0 <= column_indices[0] < len(segs):
            val = segs[column_indices[0]]
            return None if val in (None, "Ø", "∅", "-", "") else str(val)
        if len(segs) == 1:
            val = segs[0]
            return None if val in (None, "Ø", "∅", "-", "") else str(val)
    return None


def _is_hedged_tie_without_same_unit_outgroup(
    claim: CritiqueClaimRecord,
    evidence: CritiqueEvidenceBundle,
) -> bool:
    if claim.confidence > 0.50 or len(set(claim.reflexes)) < 2:
        return False
    same_unit_count = 0
    for info in evidence.outgroup_forms.values():
        if _is_same_unit_outgroup(info, claim.unit_id):
            same_unit_count += 1
            seg = _outgroup_column_segment(info, claim.column_indices, claim.unit_id)
            if seg is not None:
                return False
    return same_unit_count == 0


def run_deterministic_mechanical_detector(
    packet: CritiquePacket,
) -> CriticAssessment:
    """Run only provable mechanical, navigation, provenance, length-bias, and execution checks.

    Deliberately abstains from judging natural-language comparative rationales
    when all forms were inspected in the trajectory and no mechanical invariant
    was violated.
    """
    mech = _detect_mechanical_defect(
        packet.packet_id,
        packet.evidence_channel,
        packet.claim,
        packet.evidence,
    )
    if mech is not None:
        return mech

    sources, calls, sets, cols = _collect_claim_evidence_pointers(
        packet.claim, packet.evidence
    )
    if _is_hedged_tie_without_same_unit_outgroup(
        packet.claim, packet.evidence
    ):
        return CriticAssessment(
            packet_id=packet.packet_id,
            evidence_channel=packet.evidence_channel,
            verdict=CritiqueVerdict.GENUINE_AMBIGUITY_NOTED,
            defect_category=DefectCategory.NONE,
            cited_source_ids=sources,
            cited_call_ids=calls,
            cited_set_ids=sets,
            cited_column_indices=cols,
            observed_discrepancy=(
                "1-1 daughter tie with 0 same-unit outgroup witnesses is "
                f"appropriately hedged at confidence={packet.claim.confidence:.2f} <= 0.50."
            ),
            potential_consequence="None; genuine underdetermination is explicitly recorded.",
            uncertainty_label=UncertaintyLabel.GENUINE_UNDERDETERMINATION,
            discriminating_check_or_falsifier=(
                "Only an additional same-unit outgroup or historical attestation "
                "could polarize this column."
            ),
            is_fallible_interpretation=False,
        )

    return CriticAssessment(
        packet_id=packet.packet_id,
        evidence_channel=packet.evidence_channel,
        verdict=CritiqueVerdict.LEGITIMATE_NO_OBJECTION,
        defect_category=DefectCategory.NONE,
        cited_source_ids=sources,
        cited_call_ids=calls,
        cited_set_ids=sets,
        cited_column_indices=cols,
        observed_discrepancy="No mechanical, navigation, provenance, or forward-execution invariant violated.",
        potential_consequence="None detected by deterministic mechanical checks.",
        uncertainty_label=UncertaintyLabel.NO_DEFECT,
        discriminating_check_or_falsifier="All mechanical invariants satisfied.",
        is_fallible_interpretation=False,
    )


def _detect_comparative_inference_defect(
    packet_id: str,
    evidence_channel: EvidenceChannel,
    claim: CritiqueClaimRecord,
    evidence: CritiqueEvidenceBundle,
) -> CriticAssessment | None:
    """Evaluate fallible comparative/inferential defects after mechanical checks pass."""
    sources, calls, sets, cols = _collect_claim_evidence_pointers(
        claim, evidence
    )

    # 1. Upstream tie collapse masquerading as parent majority
    prior = evidence.prior_node_commit_summary
    if prior is not None and claim.confidence > 0.50:
        prior_conf = prior.get("confidence")
        prior_was_tie = (
            bool(prior.get("was_unresolved_tie"))
            or bool(prior.get("tie_collapsed"))
            or bool(prior.get("is_tie"))
            or (prior_conf is not None and float(prior_conf) <= 0.50)
        )
        if prior_was_tie:
            return CriticAssessment(
                packet_id=packet_id,
                evidence_channel=evidence_channel,
                verdict=CritiqueVerdict.DEFECT_FOUND,
                defect_category=DefectCategory.UPSTREAM_TIE_COLLAPSE_MAJORITY,
                cited_source_ids=sources,
                cited_call_ids=calls,
                cited_set_ids=sets,
                cited_column_indices=cols,
                observed_discrepancy=(
                    "Parent claim treats an upstream child node's collapsed 1-1 "
                    "tie point-estimate as creating a parent-level majority with "
                    f"confidence={claim.confidence:.2f} > 0.50."
                ),
                potential_consequence=(
                    "Arbitrary tie-breaking at the intermediate node manufactures "
                    "false directional certainty at the parent node."
                ),
                uncertainty_label=UncertaintyLabel.WARRANTED_INFERENCE_CRITIQUE,
                discriminating_check_or_falsifier=(
                    "Inspect prior_node_commit_summary.leaf_reflexes and confidence; "
                    "propagate the tie at confidence <= 0.50 unless polarized by a distinct outgroup."
                ),
                is_fallible_interpretation=True,
            )

    # 2. Outgroup unit mismatch / lookalike support vs. false confident tie / misread absence
    if len(set(claim.reflexes)) >= 2:
        same_unit_outgroups: list[tuple[str, str | None]] = []
        other_unit_outgroups: list[tuple[str, str | None]] = []
        has_suffix_lookalike = False
        for form_id, info in evidence.outgroup_forms.items():
            seg = _outgroup_column_segment(info, claim.column_indices, claim.unit_id)
            if _is_same_unit_outgroup(info, claim.unit_id):
                same_unit_outgroups.append((form_id, seg))
                if (
                    seg is None
                    and "piece_breakdown" in info
                    and isinstance(info["piece_breakdown"], (list, tuple))
                    and len(info["piece_breakdown"]) >= 2
                ):
                    has_suffix_lookalike = True
            else:
                other_unit_outgroups.append((form_id, seg))

        same_unit_non_null = [
            seg for _, seg in same_unit_outgroups if seg is not None
        ]
        same_unit_null_count = sum(
            1 for _, seg in same_unit_outgroups if seg is None
        )

        # Case 2a: Claim says "no outgroup" / tie and retains segment when same-unit outgroup attests absence
        if (
            claim.proto_segment is not None
            and None in claim.reflexes
            and len(same_unit_outgroups) >= 1
            and len(same_unit_non_null) == 0
            and same_unit_null_count >= 1
        ):
            return CriticAssessment(
                packet_id=packet_id,
                evidence_channel=evidence_channel,
                verdict=CritiqueVerdict.DEFECT_FOUND,
                defect_category=DefectCategory.FALSE_CONFIDENT_TIE_OR_MISREAD_ABSENCE,
                cited_source_ids=sources,
                cited_call_ids=calls,
                cited_set_ids=sets,
                cited_column_indices=cols,
                observed_discrepancy=(
                    f"Same-unit outgroup form(s) {[fid for fid, _ in same_unit_outgroups]} "
                    f"in {claim.unit_id!r} lack the segment (attesting absence), yet the claim "
                    f"retains *{claim.proto_segment} and treats absence of a survey witness as 'no outgroup'."
                ),
                potential_consequence=(
                    "Attested outgroup segment absence is misread as missing evidence, "
                    "causing systematic over-retention of daughter innovations."
                ),
                uncertainty_label=UncertaintyLabel.WARRANTED_INFERENCE_CRITIQUE,
                discriminating_check_or_falsifier=(
                    "Distinguish an outgroup variety lacking a cognate form from an "
                    "outgroup variety whose cognate form in claim.unit_id lacks the segment."
                ),
                is_fallible_interpretation=True,
            )

        if claim.confidence > 0.50:
            contradicted_by_same_unit_majority = False
            if claim.proto_segment is not None and None in claim.reflexes:
                if (
                    len(same_unit_outgroups) >= 2
                    and same_unit_null_count > len(same_unit_non_null)
                ):
                    contradicted_by_same_unit_majority = True
            elif claim.proto_segment is None and None in claim.reflexes:
                if len(same_unit_non_null) > same_unit_null_count:
                    contradicted_by_same_unit_majority = True
            elif claim.proto_segment is not None and same_unit_non_null:
                for alt in set(same_unit_non_null):
                    if (
                        alt != claim.proto_segment
                        and same_unit_non_null.count(alt)
                        > same_unit_non_null.count(claim.proto_segment)
                    ):
                        contradicted_by_same_unit_majority = True
                        break

            if (
                contradicted_by_same_unit_majority
                or (has_suffix_lookalike and same_unit_null_count > len(same_unit_non_null))
                or (len(other_unit_outgroups) > 0 and len(same_unit_non_null) == 0 and claim.proto_segment is not None)
            ):
                return CriticAssessment(
                    packet_id=packet_id,
                    evidence_channel=evidence_channel,
                    verdict=CritiqueVerdict.DEFECT_FOUND,
                    defect_category=DefectCategory.WRONG_UNIT_OR_LOOKALIKE_SUPPORT,
                    cited_source_ids=sources,
                    cited_call_ids=calls,
                    cited_set_ids=sets,
                    cited_column_indices=cols,
                    observed_discrepancy=(
                        f"Claim reconstructs *{claim.proto_segment} for unit {claim.unit_id!r} "
                        "by relying on a different-unit/suffix lookalike or contradicting the "
                        "same-unit multi-outgroup criterion."
                    ),
                    potential_consequence=(
                        "Non-cognate or suffix lookalike forms override same-unit outgroup parsimony."
                    ),
                    uncertainty_label=UncertaintyLabel.WARRANTED_INFERENCE_CRITIQUE,
                    discriminating_check_or_falsifier=(
                        "Filter outgroup forms to unit_id == claim.unit_id (excluding suffix pieces) "
                        "and apply the multi-outgroup parsimony criterion."
                    ),
                    is_fallible_interpretation=True,
                )

            if (
                len(claim.reflexes) == 2
                and len(same_unit_non_null) == 0
                and len(same_unit_outgroups) == 0
            ):
                return CriticAssessment(
                    packet_id=packet_id,
                    evidence_channel=evidence_channel,
                    verdict=CritiqueVerdict.DEFECT_FOUND,
                    defect_category=DefectCategory.FALSE_CONFIDENT_TIE_OR_MISREAD_ABSENCE,
                    cited_source_ids=sources,
                    cited_call_ids=calls,
                    cited_set_ids=sets,
                    cited_column_indices=cols,
                    observed_discrepancy=(
                        f"Active children disagree {list(claim.reflexes)} with 0 same-unit "
                        f"outgroup observations, yet confidence={claim.confidence:.2f} > 0.50."
                    ),
                    potential_consequence=(
                        "Unpolarized 1-1 tie is committed as a high-confidence directed change."
                    ),
                    uncertainty_label=UncertaintyLabel.WARRANTED_INFERENCE_CRITIQUE,
                    discriminating_check_or_falsifier=(
                        "When 0 same-unit outgroup witnesses exist on a 1-1 tie, cap confidence at <= 0.50."
                    ),
                    is_fallible_interpretation=True,
                )

    return None


def run_deterministic_full_detector(
    packet: CritiquePacket,
    *,
    include_comparative_trace_rules: bool = True,
) -> CriticAssessment:
    """Run mechanical checks followed by deterministic cross-node/unit trace rules."""
    if not include_comparative_trace_rules:
        return run_deterministic_mechanical_detector(packet)
    mech = _detect_mechanical_defect(
        packet.packet_id,
        packet.evidence_channel,
        packet.claim,
        packet.evidence,
    )
    if mech is not None:
        return mech
    comp = _detect_comparative_inference_defect(
        packet.packet_id,
        packet.evidence_channel,
        packet.claim,
        packet.evidence,
    )
    if comp is not None:
        return comp
    return run_deterministic_mechanical_detector(packet)


def critic_tool_definition() -> LLMToolDefinition:
    """Return the Gemini-compatible tool definition for `submit_hypothesis_critique`."""
    return LLMToolDefinition(
        name=CRITIC_TOOL_NAME,
        description=(
            "Submit a structured, source-linked critique of one reconstruction "
            "claim packet using only inference-available evidence."
        ),
        parameters={
            "type": "object",
            "properties": {
                "packet_id": {
                    "type": "string",
                    "description": "The packet_id (blind code) of the evaluated packet.",
                },
                "verdict": {
                    "type": "string",
                    "enum": [v.value for v in CritiqueVerdict],
                    "description": (
                        "Top-level verdict: 'defect_found', 'legitimate_no_objection', "
                        "or 'genuine_ambiguity_noted'."
                    ),
                },
                "defect_category": {
                    "type": "string",
                    "enum": [c.value for c in DefectCategory],
                    "description": (
                        "Specific defect category when verdict == 'defect_found', "
                        "or 'none' otherwise."
                    ),
                },
                "cited_source_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Exact form IDs (variety:concept) from active_child_forms, "
                        "outgroup_forms, prior_node_commit_summary.leaf_reflexes, "
                        "or forward_execution_summary.observed_forms."
                    ),
                },
                "cited_call_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Exact tool call IDs from claim.validation_call_id, "
                        "trajectory_navigation_summary.inspected_call_ids, or "
                        "prior_node_commit_summary.validation_call_id."
                    ),
                },
                "cited_set_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Exact correspondence set IDs from claim.set_ids or "
                        "prior_node_commit_summary.set_id."
                    ),
                },
                "cited_column_indices": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "0-based alignment column indices from claim.column_indices.",
                },
                "observed_discrepancy": {
                    "type": "string",
                    "description": "Concrete discrepancy found, or verification of soundness.",
                },
                "potential_consequence": {
                    "type": "string",
                    "description": "Downstream impact on reconstruction or forward prediction.",
                },
                "uncertainty_label": {
                    "type": "string",
                    "enum": [u.value for u in UncertaintyLabel],
                    "description": (
                        "Epistemic status: 'exact_mechanical', 'warranted_inference_critique', "
                        "'genuine_underdetermination', or 'no_defect'."
                    ),
                },
                "discriminating_check_or_falsifier": {
                    "type": "string",
                    "description": "Specific check, query, or revision test that verifies this assessment.",
                },
                "repaired_examples": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Concept IDs repaired by candidate_revision_rules on inference-available data.",
                },
                "newly_broken_examples": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Concept IDs newly broken by candidate_revision_rules on inference-available data.",
                },
            },
            "required": [
                "packet_id",
                "verdict",
                "defect_category",
                "cited_source_ids",
                "cited_call_ids",
                "cited_set_ids",
                "cited_column_indices",
                "observed_discrepancy",
                "potential_consequence",
                "uncertainty_label",
                "discriminating_check_or_falsifier",
                "repaired_examples",
                "newly_broken_examples",
            ],
            "additionalProperties": False,
        },
    )


def critic_system_instructions() -> str:
    """Return system instructions for the R07 source-linked hypothesis critic."""
    return "\n".join(
        [
            "You are a rigorous comparative-method hypothesis critic auditing a single reconstruction claim packet.",
            "Call `submit_hypothesis_critique` with your structured assessment grounded strictly in the packet's IDs.",
            "",
            "## Defect Taxonomy to Check",
            "1. `uninspected_outgroup_citation`: Rationale cites outgroup support when `trajectory_navigation_summary.concept_outgroup_forms_seen` is False.",
            "2. `silent_residue_drop_truncation`: `residue_policy == 'drop'` with `unaccounted_column_rate > 0.0` and non-empty `dropped_concept_ids`.",
            "3. `unit_provenance_loss`: `assembled_candidate_unit_id == 'whole:unknown'` when `child_source_unit_ids` carry explicit `cog:*` provenance.",
            "4. `identity_confidence_length_bias`: Identity retention (`[x, x] -> *x`) committed at `confidence < 1.0` where `competing_beam_candidates` have unequal lengths and unequal probabilities.",
            "5. `counterexample_or_bleeding_order`: `forward_execution_summary` shows `dev_exact_rate < 1.0` or `newly_broken_concept_ids` on inference-available daughter data (and not a bijective relabelling).",
            "6. `upstream_tie_collapse_majority`: Parent claim uses a collapsed 1-1 tie from `prior_node_commit_summary` (`confidence <= 0.50` or disagreeing `leaf_reflexes`) to claim a confident majority (`confidence > 0.50`).",
            "7. `wrong_unit_or_lookalike_support`: Polarization relies on an outgroup form from a different cognate unit (`unit_id != claim.unit_id`) or contradicts the majority of same-unit outgroups.",
            "8. `false_confident_tie_or_misread_absence`: Active children disagree with `confidence > 0.50` when same-unit outgroups are tied or absent/gap (`None` misread as positive evidence).",
            "",
            "## Strict Negative Rules (Preventing False Objections)",
            "1. Do NOT treat sparse support (`support == 1` in a local unit), missing outgroup varieties (`missing_outgroup_varieties`), lexical irregularity, or disagreement with a single `provisional_proxy_note` as a defect.",
            "2. Repeated identical retention (`[p, p] -> *p` across multiple units) is retention, NOT a merger.",
            "3. `assembled_candidate_unit_id == 'whole:unknown'` is legitimate when `child_source_unit_ids` are themselves `'whole:unknown'`.",
            "4. An unanchored proto-symbol relabelling (`*ɢ` vs `*q`) with `is_bijective_relabelling == True` and `1.0` daughter reflex fit is observationally equivalent and must NOT be flagged as an error.",
            "5. Active-child order swap `(b, a)` vs `(a, b)` or commitment order reversal is an irrelevant presentation perturbation; when a `1-1` tie with `0` same-unit outgroups is hedged at `confidence <= 0.50`, return `verdict = 'genuine_ambiguity_noted'`, `defect_category = 'none'`, `uncertainty_label = 'genuine_underdetermination'`.",
            "6. Never invent or hallucinate IDs. Cite every relevant `source_id`, `call_id`, `set_id`, and `column_indices` present in the packet.",
        ]
    )


def build_critic_user_prompt(visible_packet: Mapping[str, Any]) -> str:
    """Format a sanitized model-visible packet into a prompt for the critic."""
    compact_json = json.dumps(visible_packet, indent=2, ensure_ascii=False)
    return (
        "Audit the following reconstruction claim packet and submit your critique "
        f"via `{CRITIC_TOOL_NAME}`:\n\n```json\n{compact_json}\n```"
    )


def parse_critic_response(
    response: ProviderResponse | LLMMessage,
    *,
    packet: CritiquePacket,
) -> CriticAssessment:
    """Parse a `ProviderResponse` (or `LLMMessage`) into a validated `CriticAssessment`."""
    message = (
        response.message
        if isinstance(response, ProviderResponse)
        else response
    )
    raw_args: dict[str, Any] | None = None
    for call in message.tool_calls:
        if call.name == CRITIC_TOOL_NAME:
            raw_args = dict(call.arguments)
            break
    if raw_args is None and message.tool_calls:
        raw_args = dict(message.tool_calls[0].arguments)
    if raw_args is None and message.content:
        text = message.content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        try:
            parsed_json = json.loads(text)
            if isinstance(parsed_json, dict):
                raw_args = parsed_json
        except json.JSONDecodeError:
            raw_args = None
    if raw_args is None:
        return CriticAssessment(
            packet_id=packet.packet_id,
            evidence_channel=packet.evidence_channel,
            verdict=CritiqueVerdict.GENUINE_AMBIGUITY_NOTED,
            defect_category=DefectCategory.NONE,
            uncertainty_label=UncertaintyLabel.GENUINE_UNDERDETERMINATION,
            observed_discrepancy="unparseable_response: provider response contained no valid submit_hypothesis_critique payload.",
            potential_consequence="Critique could not be validated from malformed response.",
            discriminating_check_or_falsifier="Inspect raw provider response in trajectories.jsonl.",
            is_fallible_interpretation=True,
        )

    raw_args["packet_id"] = packet.packet_id
    raw_args["evidence_channel"] = packet.evidence_channel.value
    raw_args["is_fallible_interpretation"] = True
    return CriticAssessment.model_validate(raw_args)


def _assess_visible_packet(
    visible_packet: Mapping[str, Any],
    *,
    mode: Literal[
        "accurate",
        "over_objecting",
        "verbose_relabeller",
        "hallucinated_pointers",
    ],
) -> CriticAssessment:
    """Compute a scripted `CriticAssessment` purely from a model-visible packet dict."""
    packet_id = str(visible_packet.get("packet_id", "unknown_packet"))
    channel_str = str(
        visible_packet.get(
            "evidence_channel",
            EvidenceChannel.INFERENCE_AVAILABLE_DAUGHTER_FITTING.value,
        )
    )
    evidence_channel = EvidenceChannel(channel_str)
    claim = CritiqueClaimRecord.model_validate(visible_packet["claim"])
    evidence = CritiqueEvidenceBundle.model_validate(visible_packet["evidence"])
    sources, calls, sets, cols = _collect_claim_evidence_pointers(
        claim, evidence
    )
    repaired, newly_broken = _extract_forward_revision_examples(evidence)

    if mode == "verbose_relabeller":
        if claim.unaccounted_column_rate > 0.0:
            return CriticAssessment(
                packet_id=packet_id,
                evidence_channel=evidence_channel,
                verdict=CritiqueVerdict.DEFECT_FOUND,
                defect_category=DefectCategory.SILENT_RESIDUE_DROP_TRUNCATION,
                cited_source_ids=sources,
                cited_call_ids=calls,
                cited_set_ids=sets,
                cited_column_indices=cols,
                observed_discrepancy=(
                    "Upon an extensive comparative-method review of the phonological "
                    "alignment matrix and segment distribution across the active daughter "
                    f"branches, the unaccounted column rate of {claim.unaccounted_column_rate:.2f} "
                    "under the drop policy indicates that unmapped correspondence sets "
                    "were omitted during proto-form assembly."
                ),
                potential_consequence=(
                    "This surface omission truncates the reconstructed lexeme for "
                    f"concepts {list(claim.dropped_concept_ids)}."
                ),
                uncertainty_label=UncertaintyLabel.WARRANTED_INFERENCE_CRITIQUE,
                discriminating_check_or_falsifier=(
                    "Inspect the assembly report for unaccounted columns."
                ),
                is_fallible_interpretation=True,
            )
        return CriticAssessment(
            packet_id=packet_id,
            evidence_channel=evidence_channel,
            verdict=CritiqueVerdict.LEGITIMATE_NO_OBJECTION,
            defect_category=DefectCategory.NONE,
            cited_source_ids=sources,
            cited_call_ids=calls,
            cited_set_ids=sets,
            cited_column_indices=cols,
            observed_discrepancy=(
                "A thorough philological and comparative inspection of the active "
                "daughter reflexes, correspondence sets, and topological outgroup "
                "witnesses confirms that the surface unaccounted column rate is zero "
                "and the proposed reconstruction is regular."
            ),
            potential_consequence="No adverse downstream phonological consequences.",
            uncertainty_label=UncertaintyLabel.NO_DEFECT,
            discriminating_check_or_falsifier=(
                "Confirm that unaccounted_column_rate remains 0.0."
            ),
            is_fallible_interpretation=True,
        )

    # First check deterministic mechanical defects, then comparative defects
    accurate = _detect_mechanical_defect(
        packet_id, evidence_channel, claim, evidence
    )
    if accurate is None:
        accurate = _detect_comparative_inference_defect(
            packet_id, evidence_channel, claim, evidence
        )

    if accurate is None:
        if _is_hedged_tie_without_same_unit_outgroup(claim, evidence):
            accurate = CriticAssessment(
                packet_id=packet_id,
                evidence_channel=evidence_channel,
                verdict=CritiqueVerdict.GENUINE_AMBIGUITY_NOTED,
                defect_category=DefectCategory.NONE,
                cited_source_ids=sources,
                cited_call_ids=calls,
                cited_set_ids=sets,
                cited_column_indices=cols,
                observed_discrepancy=(
                    "1-1 daughter disagreement with 0 same-unit outgroup witnesses "
                    f"is properly hedged at confidence={claim.confidence:.2f} <= 0.50; "
                    "child presentation order is a non-defect symmetry."
                ),
                potential_consequence="None; genuine underdetermination is preserved.",
                uncertainty_label=UncertaintyLabel.GENUINE_UNDERDETERMINATION,
                discriminating_check_or_falsifier=(
                    "Requires external same-unit outgroup or historical attestation to break the tie."
                ),
                is_fallible_interpretation=True,
            )
        else:
            accurate = CriticAssessment(
                packet_id=packet_id,
                evidence_channel=evidence_channel,
                verdict=CritiqueVerdict.LEGITIMATE_NO_OBJECTION,
                defect_category=DefectCategory.NONE,
                cited_source_ids=sources,
                cited_call_ids=calls,
                cited_set_ids=sets,
                cited_column_indices=cols,
                observed_discrepancy=(
                    "Claim is supported by inspected same-unit evidence, preserves "
                    "unit provenance, and satisfies forward execution and contrast equivalence."
                ),
                potential_consequence="None; reconstruction is sound under stated criteria.",
                uncertainty_label=UncertaintyLabel.NO_DEFECT,
                discriminating_check_or_falsifier=(
                    "Verify same-unit alignment and forward cascade exactness."
                ),
                repaired_examples=repaired,
                newly_broken_examples=newly_broken,
                is_fallible_interpretation=True,
            )

    if mode == "accurate":
        return accurate.model_copy(update={"is_fallible_interpretation": True})

    if mode == "hallucinated_pointers":
        return accurate.model_copy(
            update={
                "cited_source_ids": ("z:y99",),
                "cited_call_ids": ("call-fake-999",),
                "cited_set_ids": ("csu-000000",),
                "cited_column_indices": (99,),
                "is_fallible_interpretation": True,
            }
        )

    # mode == "over_objecting"
    if accurate.verdict == CritiqueVerdict.DEFECT_FOUND:
        return accurate.model_copy(update={"is_fallible_interpretation": True})

    # Trap 1: eval_c02 (missing outgroups treated as evidence against retention)
    if (
        claim.proto_segment is not None
        and None in claim.reflexes
        and len(evidence.missing_outgroup_varieties) >= 2
    ):
        return CriticAssessment(
            packet_id=packet_id,
            evidence_channel=evidence_channel,
            verdict=CritiqueVerdict.DEFECT_FOUND,
            defect_category=DefectCategory.WRONG_UNIT_OR_LOOKALIKE_SUPPORT,
            cited_source_ids=sources,
            cited_call_ids=calls,
            cited_set_ids=sets,
            cited_column_indices=cols,
            observed_discrepancy=(
                "False objection: only 1 of 3 outgroups attests the segment because "
                f"outgroups {list(evidence.missing_outgroup_varieties)} are missing."
            ),
            potential_consequence="Over-objecting critic penalizes missing outgroup data.",
            uncertainty_label=UncertaintyLabel.WARRANTED_INFERENCE_CRITIQUE,
            discriminating_check_or_falsifier="Demand 2/3 outgroup presence regardless of missing varieties.",
            is_fallible_interpretation=True,
        )

    # Trap 2: eval_c03 (hedged tie / child order swap)
    if claim.confidence <= 0.50 and len(set(claim.reflexes)) >= 2:
        return CriticAssessment(
            packet_id=packet_id,
            evidence_channel=evidence_channel,
            verdict=CritiqueVerdict.DEFECT_FOUND,
            defect_category=DefectCategory.FALSE_CONFIDENT_TIE_OR_MISREAD_ABSENCE,
            cited_source_ids=sources,
            cited_call_ids=calls,
            cited_set_ids=sets,
            cited_column_indices=cols,
            observed_discrepancy=(
                "False objection: active-child order swap / 1-1 tie flagged as "
                "a defect despite confidence <= 0.50."
            ),
            potential_consequence="Over-objecting critic rejects properly hedged ties.",
            uncertainty_label=UncertaintyLabel.WARRANTED_INFERENCE_CRITIQUE,
            discriminating_check_or_falsifier="Reject any unresolved 1-1 tie.",
            is_fallible_interpretation=True,
        )

    # Trap 3: eval_c04 (provisional proxy disagreement)
    if evidence.provisional_proxy_note:
        return CriticAssessment(
            packet_id=packet_id,
            evidence_channel=evidence_channel,
            verdict=CritiqueVerdict.DEFECT_FOUND,
            defect_category=DefectCategory.WRONG_UNIT_OR_LOOKALIKE_SUPPORT,
            cited_source_ids=sources,
            cited_call_ids=calls,
            cited_set_ids=sets,
            cited_column_indices=cols,
            observed_discrepancy=(
                "False objection: reconstructed segment disagrees with single "
                f"provisional proxy note ({evidence.provisional_proxy_note})."
            ),
            potential_consequence="Over-objecting critic treats provisional proxy as gold.",
            uncertainty_label=UncertaintyLabel.WARRANTED_INFERENCE_CRITIQUE,
            discriminating_check_or_falsifier="Match provisional proxy segment.",
            is_fallible_interpretation=True,
        )

    # Trap 4: eval_c05 (*ɢ vs *q bijective relabelling)
    if (
        evidence.contrast_equivalence_summary is not None
        and float(
            evidence.contrast_equivalence_summary.get("raw_exact_rate", 1.0)
        )
        < 1.0
        and bool(
            evidence.contrast_equivalence_summary.get(
                "is_bijective_relabelling", False
            )
        )
    ):
        return CriticAssessment(
            packet_id=packet_id,
            evidence_channel=evidence_channel,
            verdict=CritiqueVerdict.DEFECT_FOUND,
            defect_category=DefectCategory.COUNTEREXAMPLE_OR_BLEEDING_ORDER,
            cited_source_ids=sources,
            cited_call_ids=calls,
            cited_set_ids=sets,
            cited_column_indices=cols,
            observed_discrepancy=(
                "False objection: unanchored proto-symbol choice (*ɢ vs *q) has "
                "raw_exact_rate < 1.0 despite is_bijective_relabelling=True."
            ),
            potential_consequence="Over-objecting critic penalizes equivalent symbol relabelling.",
            uncertainty_label=UncertaintyLabel.WARRANTED_INFERENCE_CRITIQUE,
            discriminating_check_or_falsifier="Enforce raw symbol identity.",
            repaired_examples=repaired,
            newly_broken_examples=newly_broken,
            is_fallible_interpretation=True,
        )

    # Trap 5: dev_d03_legit (sparse support == 1 / repeated identical retention)
    if (
        claim.support == 1
        and len(set(claim.reflexes)) == 1
        and claim.reflexes
        and claim.reflexes[0] is not None
        and claim.assembled_candidate_unit_id != "whole:unknown"
        and len(claim.competing_beam_candidates) <= 1
        and evidence.prior_node_commit_summary is None
        and evidence.forward_execution_summary is None
    ):
        return CriticAssessment(
            packet_id=packet_id,
            evidence_channel=evidence_channel,
            verdict=CritiqueVerdict.DEFECT_FOUND,
            defect_category=DefectCategory.FALSE_CONFIDENT_TIE_OR_MISREAD_ABSENCE,
            cited_source_ids=sources,
            cited_call_ids=calls,
            cited_set_ids=sets,
            cited_column_indices=cols,
            observed_discrepancy=(
                "False objection: singleton local support (support=1) or repeated "
                "identical retention across units treated as unconditioned merger."
            ),
            potential_consequence="Over-objecting critic rejects legitimate singleton retention.",
            uncertainty_label=UncertaintyLabel.WARRANTED_INFERENCE_CRITIQUE,
            discriminating_check_or_falsifier="Require support >= 2 on every local unit.",
            is_fallible_interpretation=True,
        )

    return accurate.model_copy(update={"is_fallible_interpretation": True})


class FakeCriticProvider(LLMProvider):
    """Deterministic offline provider supporting 4 scripted critic modes at $0 cost."""

    def __init__(
        self,
        mode: Literal[
            "accurate",
            "over_objecting",
            "verbose_relabeller",
            "hallucinated_pointers",
        ] = "accurate",
        *,
        packets: Sequence[CritiquePacket] = (),
    ) -> None:
        if mode not in (
            "accurate",
            "over_objecting",
            "verbose_relabeller",
            "hallucinated_pointers",
        ):
            raise ValueError(f"Unsupported FakeCriticProvider mode: {mode!r}")
        self.mode: Literal[
            "accurate",
            "over_objecting",
            "verbose_relabeller",
            "hallucinated_pointers",
        ] = mode
        self._packets_by_code: dict[str, CritiquePacket] = {}
        for p in packets:
            self._packets_by_code[p.blind_code] = p
            self._packets_by_code[p.packet_id] = p
        self.call_count: int = 0

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[LLMToolDefinition] = (),
        *,
        tool_choice: str = "auto",
        max_tokens_override: int | None = None,
    ) -> ProviderResponse:
        del tools, tool_choice, max_tokens_override
        self.call_count += 1

        user_msg = next(
            (m for m in reversed(messages) if m.role is MessageRole.USER),
            None,
        )
        if user_msg is None or not user_msg.content:
            raise ValueError("FakeCriticProvider requires a USER message with packet JSON.")

        content = user_msg.content
        if "```json" in content:
            json_part = content.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "{" in content:
            start = content.index("{")
            end = content.rindex("}") + 1
            json_part = content[start:end]
        else:
            raise ValueError("Could not locate JSON packet in user prompt.")

        visible_packet = json.loads(json_part)
        assessment = _assess_visible_packet(visible_packet, mode=self.mode)
        args = {
            "packet_id": str(visible_packet.get("packet_id", assessment.packet_id)),
            "verdict": assessment.verdict.value,
            "defect_category": assessment.defect_category.value,
            "cited_source_ids": list(assessment.cited_source_ids),
            "cited_call_ids": list(assessment.cited_call_ids),
            "cited_set_ids": list(assessment.cited_set_ids),
            "cited_column_indices": list(assessment.cited_column_indices),
            "observed_discrepancy": assessment.observed_discrepancy,
            "potential_consequence": assessment.potential_consequence,
            "uncertainty_label": assessment.uncertainty_label.value,
            "discriminating_check_or_falsifier": (
                assessment.discriminating_check_or_falsifier
            ),
            "repaired_examples": list(assessment.repaired_examples),
            "newly_broken_examples": list(assessment.newly_broken_examples),
        }
        tool_call = LLMToolCall(
            call_id=f"call_critic_{self.call_count:03d}",
            name=CRITIC_TOOL_NAME,
            arguments=args,
        )
        assistant_msg = LLMMessage(
            role=MessageRole.ASSISTANT,
            content=None,
            tool_calls=(tool_call,),
        )
        return ProviderResponse(
            message=assistant_msg,
            metadata=ProviderResponseMetadata(
                provider_id="fake_critic",
                model_id=f"fake-critic-{self.mode}",
                response_id=f"resp_critic_{self.call_count:03d}",
                finish_reason="tool_calls",
                usage=ProviderUsage(
                    input_tokens=0,
                    output_tokens=0,
                    total_tokens=0,
                    cost_usd=0.0,
                    cost_source="provider_reported",
                    provider_reported_cost_usd=0.0,
                ),
            ),
        )

    def assess_packet(self, packet: CritiquePacket) -> CriticAssessment:
        """Convenience method to run the provider over one `CritiquePacket`."""
        return run_llm_critic_on_packet(packet, self)


_COMPARATIVE_DEFECT_CATEGORIES: frozenset[DefectCategory] = frozenset(
    {
        DefectCategory.UPSTREAM_TIE_COLLAPSE_MAJORITY,
        DefectCategory.WRONG_UNIT_OR_LOOKALIKE_SUPPORT,
        DefectCategory.FALSE_CONFIDENT_TIE_OR_MISREAD_ABSENCE,
    }
)


def _valid_pointer_universe(
    packet: CritiquePacket,
) -> tuple[set[str], set[str], set[str], set[int]]:
    """Return the valid (source_ids, call_ids, set_ids, column_indices) universe for `packet`."""
    valid_source_ids: set[str] = (
        set(packet.evidence.active_child_forms.keys())
        | set(packet.evidence.outgroup_forms.keys())
        | set(
            (packet.evidence.prior_node_commit_summary or {})
            .get("leaf_reflexes", {})
            .keys()
        )
        | set(
            (packet.evidence.forward_execution_summary or {})
            .get("observed_forms", {})
            .keys()
        )
    )
    valid_call_ids: set[str] = {
        packet.claim.validation_call_id,
        *(
            str(c)
            for c in packet.evidence.trajectory_navigation_summary.get(
                "inspected_call_ids", ()
            )
        ),
    }
    if (
        packet.evidence.prior_node_commit_summary
        and "validation_call_id" in packet.evidence.prior_node_commit_summary
    ):
        valid_call_ids.add(
            str(
                packet.evidence.prior_node_commit_summary["validation_call_id"]
            )
        )

    valid_set_ids: set[str] = set(packet.claim.set_ids)
    if (
        packet.evidence.prior_node_commit_summary
        and "set_id" in packet.evidence.prior_node_commit_summary
    ):
        valid_set_ids.add(
            str(packet.evidence.prior_node_commit_summary["set_id"])
        )

    valid_column_indices: set[int] = set(packet.claim.column_indices) | {
        0,
        1,
        2,
        3,
        4,
    }
    return valid_source_ids, valid_call_ids, valid_set_ids, valid_column_indices


def filter_llm_assessment_with_deterministic_guard(
    assessment: CriticAssessment,
    packet: CritiquePacket,
) -> CriticAssessment:
    """Filter hallucinated pointers and enforce deterministic epistemic `uncertainty_label`."""
    (
        valid_source_ids,
        valid_call_ids,
        valid_set_ids,
        valid_column_indices,
    ) = _valid_pointer_universe(packet)

    filtered_sources = tuple(
        s for s in assessment.cited_source_ids if s in valid_source_ids
    )
    filtered_calls = tuple(
        c for c in assessment.cited_call_ids if c in valid_call_ids
    )
    filtered_sets = tuple(
        s for s in assessment.cited_set_ids if s in valid_set_ids
    )
    filtered_cols = tuple(
        col
        for col in assessment.cited_column_indices
        if col in valid_column_indices
    )

    if assessment.verdict == CritiqueVerdict.GENUINE_AMBIGUITY_NOTED:
        enforced_label = UncertaintyLabel.GENUINE_UNDERDETERMINATION
    elif (
        assessment.verdict == CritiqueVerdict.LEGITIMATE_NO_OBJECTION
        or assessment.defect_category == DefectCategory.NONE
    ):
        enforced_label = UncertaintyLabel.NO_DEFECT
    elif assessment.defect_category in _COMPARATIVE_DEFECT_CATEGORIES:
        enforced_label = UncertaintyLabel.WARRANTED_INFERENCE_CRITIQUE
    else:
        enforced_label = UncertaintyLabel.EXACT_MECHANICAL

    return assessment.model_copy(
        update={
            "cited_source_ids": filtered_sources,
            "cited_call_ids": filtered_calls,
            "cited_set_ids": filtered_sets,
            "cited_column_indices": filtered_cols,
            "uncertainty_label": enforced_label,
            "is_fallible_interpretation": True,
        }
    )


def run_llm_critic_on_packet(
    packet: CritiquePacket,
    provider: LLMProvider,
    *,
    apply_deterministic_guard: bool = False,
) -> CriticAssessment:
    """Sanitize `packet`, prompt `provider` with `submit_hypothesis_critique`, and parse."""
    visible = to_model_visible_packet(packet)
    messages = (
        LLMMessage(
            role=MessageRole.SYSTEM,
            content=critic_system_instructions(),
        ),
        LLMMessage(
            role=MessageRole.USER,
            content=build_critic_user_prompt(visible),
        ),
    )
    response = provider.complete(
        messages,
        (critic_tool_definition(),),
        tool_choice="required",
    )
    parsed = parse_critic_response(response, packet=packet)
    if apply_deterministic_guard:
        return filter_llm_assessment_with_deterministic_guard(parsed, packet)
    return parsed


def run_llm_critic_on_packets(
    packets: Sequence[CritiquePacket],
    provider: LLMProvider,
    *,
    apply_deterministic_guard: bool = False,
) -> dict[str, CriticAssessment]:
    """Run `provider` over every inference-available packet in `packets`."""
    return {
        p.packet_id: run_llm_critic_on_packet(
            p, provider, apply_deterministic_guard=apply_deterministic_guard
        )
        for p in packets
        if p.evidence_channel
        != EvidenceChannel.OFFLINE_HELD_OUT_SCORER_ONLY
        and p.split != "offline_gold_residual_only"
    }


def run_default_hypothesis_critic(
    packet: CritiquePacket,
    *,
    mode: Literal[
        "deterministic_full",
        "deterministic_mechanical",
        "llm",
    ] = DEFAULT_CRITIC_MODE,
    provider: LLMProvider | None = None,
    apply_deterministic_guard: bool = True,
) -> CriticAssessment:
    """Run the adopted default hypothesis critic (`deterministic_full` at $0 cost by default)."""
    if mode == "deterministic_full":
        return run_deterministic_full_detector(
            packet, include_comparative_trace_rules=True
        )
    if mode == "deterministic_mechanical":
        return run_deterministic_mechanical_detector(packet)
    if mode == "llm":
        if provider is None:
            raise ValueError("provider is required when mode='llm'.")
        return run_llm_critic_on_packet(
            packet,
            provider,
            apply_deterministic_guard=apply_deterministic_guard,
        )
    raise ValueError(f"Unsupported critic mode: {mode!r}")


def run_default_critic_report(
    packets: Sequence[CritiquePacket],
    *,
    mode: Literal[
        "deterministic_full",
        "deterministic_mechanical",
        "llm",
    ] = DEFAULT_CRITIC_MODE,
    provider: LLMProvider | None = None,
    apply_deterministic_guard: bool = True,
) -> dict[str, Any]:
    """Run the default hypothesis critic across `packets` and return scored report ($0 cost by default)."""
    eligible_packets = [
        p
        for p in packets
        if p.evidence_channel
        != EvidenceChannel.OFFLINE_HELD_OUT_SCORER_ONLY
        and p.split != "offline_gold_residual_only"
    ]
    assessments: dict[str, CriticAssessment] = {
        p.packet_id: run_default_hypothesis_critic(
            p,
            mode=mode,
            provider=provider,
            apply_deterministic_guard=apply_deterministic_guard,
        )
        for p in eligible_packets
    }
    scored = score_critic_assessments(eligible_packets, assessments)
    return {
        **scored,
        "mode": mode,
        "default_critic_mode": DEFAULT_CRITIC_MODE,
        "apply_deterministic_guard": apply_deterministic_guard,
        "cost_usd": 0.0 if mode != "llm" else None,
        "assessments": {
            pid: a.model_dump(mode="json") for pid, a in assessments.items()
        },
        "scored": scored,
    }


class _KeyedResultList(list):  # type: ignore[type-arg]
    """A JSON-serializable list of result dicts that also supports lookup by ID key."""

    def __init__(self, items: Sequence[dict[str, Any]], id_key: str) -> None:
        super().__init__(items)
        self._id_key = id_key
        self._by_id: dict[str, dict[str, Any]] = {
            str(item[id_key]): item for item in items if id_key in item
        }

    def __getitem__(self, index_or_key: int | slice | str) -> Any:  # type: ignore[override]
        if isinstance(index_or_key, str):
            return self._by_id[index_or_key]
        return super().__getitem__(index_or_key)

    def __contains__(self, item_or_key: object) -> bool:
        if isinstance(item_or_key, str):
            return item_or_key in self._by_id
        return super().__contains__(item_or_key)

    def get(self, key: str, default: Any = None) -> Any:
        return self._by_id.get(key, default)

    def keys(self) -> list[str]:
        return list(self._by_id.keys())

    def values(self) -> list[dict[str, Any]]:
        return list(self)

    def items(self) -> list[tuple[str, dict[str, Any]]]:
        return [(str(item[self._id_key]), item) for item in self]


def score_critic_assessments(
    packets: Sequence[CritiquePacket],
    assessments: Mapping[str, CriticAssessment] | Sequence[CriticAssessment],
) -> dict[str, Any]:
    """Score critic assessments against sealed packet ground truth with pointer verification."""
    if not isinstance(assessments, Mapping):
        assessments_map: dict[str, CriticAssessment] = {
            a.packet_id: a for a in assessments
        }
    else:
        assessments_map = dict(assessments)
    per_packet_rows: list[dict[str, Any]] = []
    defective_count = 0
    non_defective_count = 0
    defect_detections = 0
    actionable_true_positives = 0
    missed_defect_packet_ids: list[str] = []
    false_objections = 0
    false_objection_packet_ids: list[str] = []
    total_objections_raised = 0
    zero_hallucination_count = 0
    defect_pointer_complete_count = 0

    for packet in packets:
        gt = packet.ground_truth
        if gt.is_defective:
            defective_count += 1
        else:
            non_defective_count += 1

        valid_source_ids: set[str] = (
            set(packet.evidence.active_child_forms.keys())
            | set(packet.evidence.outgroup_forms.keys())
            | set(
                (packet.evidence.prior_node_commit_summary or {})
                .get("leaf_reflexes", {})
                .keys()
            )
            | set(
                (packet.evidence.forward_execution_summary or {})
                .get("observed_forms", {})
                .keys()
            )
        )
        valid_call_ids: set[str] = {
            packet.claim.validation_call_id,
            *(
                str(c)
                for c in packet.evidence.trajectory_navigation_summary.get(
                    "inspected_call_ids", ()
                )
            ),
        }
        if (
            packet.evidence.prior_node_commit_summary
            and "validation_call_id" in packet.evidence.prior_node_commit_summary
        ):
            valid_call_ids.add(
                str(
                    packet.evidence.prior_node_commit_summary[
                        "validation_call_id"
                    ]
                )
            )

        valid_set_ids: set[str] = set(packet.claim.set_ids)
        if (
            packet.evidence.prior_node_commit_summary
            and "set_id" in packet.evidence.prior_node_commit_summary
        ):
            valid_set_ids.add(
                str(packet.evidence.prior_node_commit_summary["set_id"])
            )

        valid_column_indices: set[int] = set(packet.claim.column_indices) | {
            0,
            1,
            2,
            3,
            4,
        }

        assessment = assessments_map.get(packet.packet_id) or assessments_map.get(
            packet.blind_code
        )
        if assessment is None:
            if gt.is_defective:
                missed_defect_packet_ids.append(packet.packet_id)
            per_packet_rows.append(
                {
                    "packet_id": packet.packet_id,
                    "blind_code": packet.blind_code,
                    "pair_id": packet.pair_id,
                    "pair_role": packet.pair_role,
                    "is_defective": gt.is_defective,
                    "assessment_present": False,
                    "verdict": None,
                    "defect_category": None,
                    "uncertainty_label": None,
                    "verdict_correct": False,
                    "category_correct": False,
                    "uncertainty_label_correct": False,
                    "hallucinated_sources": [],
                    "hallucinated_calls": [],
                    "hallucinated_sets": [],
                    "hallucinated_cols": [],
                    "missing_required_sources": list(gt.required_source_ids),
                    "missing_required_calls": list(gt.required_call_ids),
                    "missing_required_sets": list(gt.required_set_ids),
                    "missing_required_cols": list(gt.required_column_indices),
                    "pointers_valid": False,
                    "pointers_exact_and_valid": False,
                    "revision_examples_correct": False,
                    "actionable_hit": False,
                    "false_objection": False,
                    "packet_correct": False,
                }
            )
            continue

        if assessment.verdict == CritiqueVerdict.DEFECT_FOUND:
            total_objections_raised += 1

        if gt.is_defective:
            verdict_correct = assessment.verdict == CritiqueVerdict.DEFECT_FOUND
        else:
            verdict_correct = (
                assessment.verdict
                in (
                    CritiqueVerdict.LEGITIMATE_NO_OBJECTION,
                    CritiqueVerdict.GENUINE_AMBIGUITY_NOTED,
                )
                and assessment.defect_category == DefectCategory.NONE
            )

        category_correct = (
            assessment.defect_category == gt.expected_defect_category
            or assessment.defect_category in gt.accepted_defect_categories
        )
        uncertainty_label_correct = (
            assessment.uncertainty_label == gt.expected_uncertainty_label
        )

        hallucinated_sources = sorted(
            set(assessment.cited_source_ids) - valid_source_ids
        )
        hallucinated_calls = sorted(
            set(assessment.cited_call_ids) - valid_call_ids
        )
        hallucinated_sets = sorted(
            set(assessment.cited_set_ids) - valid_set_ids
        )
        hallucinated_cols = sorted(
            set(assessment.cited_column_indices) - valid_column_indices
        )

        missing_required_sources = sorted(
            set(gt.required_source_ids) - set(assessment.cited_source_ids)
        )
        missing_required_calls = sorted(
            set(gt.required_call_ids) - set(assessment.cited_call_ids)
        )
        missing_required_sets = sorted(
            set(gt.required_set_ids) - set(assessment.cited_set_ids)
        )
        missing_required_cols = sorted(
            set(gt.required_column_indices)
            - set(assessment.cited_column_indices)
        )

        pointers_valid = not (
            hallucinated_sources
            or hallucinated_calls
            or hallucinated_sets
            or hallucinated_cols
        )
        pointers_exact_and_valid = pointers_valid and not (
            missing_required_sources
            or missing_required_calls
            or missing_required_sets
            or missing_required_cols
        )

        if pointers_valid:
            zero_hallucination_count += 1
        if gt.is_defective and pointers_exact_and_valid:
            defect_pointer_complete_count += 1

        if gt.expected_repaired_examples or gt.expected_newly_broken_examples:
            revision_examples_correct = set(assessment.repaired_examples) == set(
                gt.expected_repaired_examples
            ) and set(assessment.newly_broken_examples) == set(
                gt.expected_newly_broken_examples
            )
        else:
            revision_examples_correct = True

        detected = (
            gt.is_defective
            and assessment.verdict == CritiqueVerdict.DEFECT_FOUND
            and category_correct
        )
        if gt.is_defective:
            if detected:
                defect_detections += 1
            else:
                missed_defect_packet_ids.append(packet.packet_id)

        actionable_hit = (
            gt.is_defective
            and verdict_correct
            and category_correct
            and pointers_exact_and_valid
            and revision_examples_correct
        )
        if actionable_hit:
            actionable_true_positives += 1

        is_false_obj = (not gt.is_defective) and (
            assessment.verdict == CritiqueVerdict.DEFECT_FOUND
            or assessment.defect_category != DefectCategory.NONE
        )
        if is_false_obj:
            false_objections += 1
            false_objection_packet_ids.append(packet.packet_id)

        packet_correct = (
            actionable_hit
            if gt.is_defective
            else (verdict_correct and category_correct and pointers_valid)
        )

        per_packet_rows.append(
            {
                "packet_id": packet.packet_id,
                "blind_code": packet.blind_code,
                "pair_id": packet.pair_id,
                "pair_role": packet.pair_role,
                "is_defective": gt.is_defective,
                "assessment_present": True,
                "verdict": assessment.verdict.value,
                "defect_category": assessment.defect_category.value,
                "uncertainty_label": assessment.uncertainty_label.value,
                "verdict_correct": verdict_correct,
                "category_correct": category_correct,
                "uncertainty_label_correct": uncertainty_label_correct,
                "hallucinated_sources": hallucinated_sources,
                "hallucinated_calls": hallucinated_calls,
                "hallucinated_sets": hallucinated_sets,
                "hallucinated_cols": hallucinated_cols,
                "missing_required_sources": missing_required_sources,
                "missing_required_calls": missing_required_calls,
                "missing_required_sets": missing_required_sets,
                "missing_required_cols": missing_required_cols,
                "pointers_valid": pointers_valid,
                "pointers_exact_and_valid": pointers_exact_and_valid,
                "revision_examples_correct": revision_examples_correct,
                "actionable_hit": actionable_hit,
                "false_objection": is_false_obj,
                "packet_correct": packet_correct,
            }
        )

    total_packets = len(packets)
    missed_known_defects = defective_count - defect_detections
    actionable_precision = (
        actionable_true_positives / total_objections_raised
        if total_objections_raised > 0
        else 0.0
    )
    raw_defect_precision = (
        defect_detections / total_objections_raised
        if total_objections_raised > 0
        else 0.0
    )
    actionable_recall = (
        actionable_true_positives / defective_count
        if defective_count > 0
        else 0.0
    )
    raw_defect_recall = (
        defect_detections / defective_count if defective_count > 0 else 0.0
    )
    false_objection_rate = (
        false_objections / non_defective_count
        if non_defective_count > 0
        else 0.0
    )
    pointer_validity_rate = (
        zero_hallucination_count / total_packets if total_packets > 0 else 0.0
    )
    defect_pointer_completeness_rate = (
        defect_pointer_complete_count / defective_count
        if defective_count > 0
        else 0.0
    )

    by_pair: dict[str, list[dict[str, Any]]] = {}
    for row in per_packet_rows:
        by_pair.setdefault(str(row["pair_id"]), []).append(row)

    multi_member_pairs = {
        pid: members for pid, members in by_pair.items() if len(members) >= 2
    }
    active_pairs = multi_member_pairs if multi_member_pairs else by_pair

    per_pair_rows: list[dict[str, Any]] = []
    matched_pairs_both_correct = 0
    for pair_id, members in active_pairs.items():
        both_ok = all(bool(m["packet_correct"]) for m in members)
        if both_ok:
            matched_pairs_both_correct += 1
        per_pair_rows.append(
            {
                "pair_id": pair_id,
                "packet_ids": [str(m["packet_id"]) for m in members],
                "both_correct": both_ok,
                "member_outcomes": {
                    str(m["packet_id"]): bool(m["packet_correct"])
                    for m in members
                },
            }
        )

    matched_pairs_total = len(per_pair_rows)
    matched_pair_accuracy = (
        matched_pairs_both_correct / matched_pairs_total
        if matched_pairs_total > 0
        else 0.0
    )

    return {
        "evaluator_version": CRITIC_EVALUATOR_VERSION,
        "total_packets": total_packets,
        "defective_packets": defective_count,
        "non_defective_packets": non_defective_count,
        "defect_detections": defect_detections,
        "actionable_true_positives": actionable_true_positives,
        "missed_known_defects": missed_known_defects,
        "missed_defect_packet_ids": missed_defect_packet_ids,
        "false_objections": false_objections,
        "false_objection_packet_ids": false_objection_packet_ids,
        "total_objections_raised": total_objections_raised,
        "actionable_precision": actionable_precision,
        "raw_defect_precision": raw_defect_precision,
        "actionable_recall": actionable_recall,
        "raw_defect_recall": raw_defect_recall,
        "false_objection_rate": false_objection_rate,
        "pointer_validity_rate": pointer_validity_rate,
        "defect_pointer_completeness_rate": defect_pointer_completeness_rate,
        "matched_pairs_total": matched_pairs_total,
        "matched_pairs_both_correct": matched_pairs_both_correct,
        "matched_pair_exact_count": matched_pairs_both_correct,
        "matched_pair_accuracy": matched_pair_accuracy,
        "per_pair_results": _KeyedResultList(per_pair_rows, "pair_id"),
        "per_packet_results": _KeyedResultList(per_packet_rows, "packet_id"),
    }


def build_blind_evaluation_sheet(
    packets: Sequence[CritiquePacket],
    *,
    seed: int = 20261110,
) -> dict[str, Any]:
    """Deterministically shuffle packets and build a blinded human rating sheet + sealed key."""
    eligible_packets = [
        p
        for p in packets
        if p.evidence_channel
        != EvidenceChannel.OFFLINE_HELD_OUT_SCORER_ONLY
        and p.split != "offline_gold_residual_only"
    ]
    shuffled = list(eligible_packets)
    rng = random.Random(seed)
    rng.shuffle(shuffled)

    presentation_order = [p.blind_code for p in shuffled]
    verdict_options = " | ".join(v.value for v in CritiqueVerdict)
    category_options = " | ".join(c.value for c in DefectCategory)

    md_lines: list[str] = [
        "# Blinded Hypothesis Critique Evaluation Sheet (R07)",
        "",
        f"- **Corpus Version**: `{CRITIC_CORPUS_VERSION}`",
        f"- **Evaluator Version**: `{CRITIC_EVALUATOR_VERSION}`",
        f"- **Randomization Seed**: `{seed}`",
        f"- **Total Blinded Packets**: `{len(shuffled)}`",
        "",
        "## Instructions for Human Rater",
        "Each item below presents an anonymized reconstruction claim and its inference-available "
        "evidence bundle. Ground-truth labels, pair roles, and internal packet IDs have been "
        "removed and stored separately in `sealed_answer_key`.",
        "",
    ]

    sealed_answer_key: list[dict[str, Any]] = []
    blind_items: list[dict[str, Any]] = []

    for idx, packet in enumerate(shuffled, start=1):
        visible = to_model_visible_packet(packet)
        blind_items.append(
            {
                "item_number": idx,
                "blind_code": packet.blind_code,
                "visible_packet": visible,
            }
        )
        md_lines.extend(
            [
                f"## Item {idx:02d} — Blind Code `{packet.blind_code}`",
                "",
                f"- **Target Node / Concept / Unit**: `{packet.claim.node_id}` / `{packet.claim.target_concept_id}` / `{packet.claim.unit_id}`",
                f"- **Claimed Reflexes -> Proto Segment**: `{list(packet.claim.reflexes)}` -> `*{packet.claim.proto_segment}` (confidence `{packet.claim.confidence}`)",
                f"- **Set IDs / Validation Call**: `{list(packet.claim.set_ids)}` / `{packet.claim.validation_call_id}`",
                f"- **Rationale**: {packet.claim.rationale}",
                "",
                "### Rater Recording Form",
                f"- **Verdict** ({verdict_options}): `[ ]`",
                f"- **Defect Type** ({category_options}): `[ ]`",
                "- **Helpfulness of Cited Pointers** (exact_and_helpful | partial | hallucinated_or_unhelpful): `[ ]`",
                "- **Suggested Check / Revision Valid?** (yes | no | not_applicable): `[ ]`",
                "- **Time Spent (minutes)**: `[ ]`",
                "- **Notes**:",
                "",
                "---",
                "",
            ]
        )
        sealed_answer_key.append(
            {
                "item_number": idx,
                "blind_code": packet.blind_code,
                "packet_id": packet.packet_id,
                "split": packet.split,
                "pair_id": packet.pair_id,
                "pair_role": packet.pair_role,
                "is_defective": packet.ground_truth.is_defective,
                "expected_verdict": packet.ground_truth.expected_verdict.value,
                "expected_defect_category": (
                    packet.ground_truth.expected_defect_category.value
                ),
                "expected_uncertainty_label": (
                    packet.ground_truth.expected_uncertainty_label.value
                ),
                "required_source_ids": list(
                    packet.ground_truth.required_source_ids
                ),
                "required_call_ids": list(
                    packet.ground_truth.required_call_ids
                ),
                "required_set_ids": list(packet.ground_truth.required_set_ids),
                "required_column_indices": list(
                    packet.ground_truth.required_column_indices
                ),
                "independent_derivation_note": (
                    packet.ground_truth.independent_derivation_note
                ),
            }
        )

    return {
        "evaluator_version": CRITIC_EVALUATOR_VERSION,
        "corpus_version": CRITIC_CORPUS_VERSION,
        "seed": seed,
        "packet_count": len(shuffled),
        "presentation_order": presentation_order,
        "blind_items": blind_items,
        "markdown_form": "\n".join(md_lines),
        "sealed_answer_key": sealed_answer_key,
    }


# ---------------------------------------------------------------------------
# Real-family run-directory deterministic provenance & trace critic (B01)
# ---------------------------------------------------------------------------

REAL_RUN_DEFECT_CATEGORIES: tuple[str, ...] = (
    DefectCategory.SILENT_RESIDUE_DROP_TRUNCATION.value,
    DefectCategory.UNINSPECTED_OUTGROUP_CITATION.value,
    DefectCategory.UNIT_PROVENANCE_LOSS.value,
    DefectCategory.IDENTITY_CONFIDENCE_LENGTH_BIAS.value,
    DefectCategory.UPSTREAM_TIE_COLLAPSE_MAJORITY.value,
)

_NEGATIVE_OUTGROUP_DISCLAIMER_RE = re.compile(
    r"\b(?:"
    r"no\s+(?:external\s+)?out-?groups?"
    r"|without\s+(?:any\s+)?(?:external\s+)?out-?groups?"
    r"|(?:0|zero)\s+(?:external\s+)?out-?groups?"
    r"|out-?groups?\s+(?:are\s+|is\s+)?(?:absent|missing|unavailable|none|lacking)"
    r"|lacks?\s+(?:any\s+)?(?:external\s+)?out-?groups?"
    r"|lacking\s+(?:any\s+)?(?:external\s+)?out-?groups?"
    r")\b",
    re.IGNORECASE,
)
_POSITIVE_OUTGROUP_TERM_RE = re.compile(
    r"\b(?:out-?groups?|external\s+(?:witness(?:es)?|clades?|branches?|variet(?:y|ies)|nodes?))\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _RunTopology:
    """Tree topology and observed leaf lexicons resolved for a run audit."""

    root_node_id: str | None
    postorder_internal_ids: tuple[str, ...]
    clade_leaves_by_node: dict[str, frozenset[str]]
    all_leaves: frozenset[str]
    leaf_forms_by_variety_concept: dict[tuple[str, str], tuple[Any, ...]]
    children_by_internal: dict[str, tuple[str, ...]]


def resolve_audit_payload(definition: str | Path) -> WorkbenchPayload:
    """Resolve a benchmark short name, benchmark JSON, diagnostic case JSON, or payload JSON."""
    from cognate_reconstruction.benchmarks.builder import (
        build_benchmark,
        load_definition,
    )
    from cognate_reconstruction.benchmarks.registry import (
        available_definitions,
        available_synthetic_families,
        definition_path,
        payload_path,
        synthetic_definition_path,
    )
    from cognate_reconstruction.schemas.benchmark import BenchmarkDefinition
    from cognate_reconstruction.schemas.synthetic import (
        SyntheticFamilyDefinition,
    )
    from cognate_reconstruction.synthesis.diagnostics import (
        EXPLICIT_SUITE_VERSIONS,
        build_case,
        build_explicit_case,
    )
    from cognate_reconstruction.synthesis.generator import generate_family

    ref_str = str(definition)
    candidate = Path(ref_str).expanduser()

    if not candidate.exists():
        if ref_str in available_definitions():
            built_file = payload_path(ref_str)
            if built_file.exists():
                return WorkbenchPayload.model_validate_json(
                    built_file.read_text(encoding="utf-8")
                )
            defn_file = definition_path(ref_str)
            defn = load_definition(defn_file)
            payload, _ = build_benchmark(defn, base_path=defn_file.parent)
            return payload
        if ref_str in available_synthetic_families():
            built_file = payload_path(ref_str)
            if built_file.exists():
                return WorkbenchPayload.model_validate_json(
                    built_file.read_text(encoding="utf-8")
                )
            syn_file = synthetic_definition_path(ref_str)
            syn_defn = SyntheticFamilyDefinition.model_validate_json(
                syn_file.read_text(encoding="utf-8")
            )
            return generate_family(syn_defn).payload
        raise ValueError(
            f"Cannot resolve audit definition {ref_str!r}: neither an existing "
            f"file nor a registered benchmark ({', '.join(available_definitions()) or 'none'})."
        )

    raw_text = candidate.read_text(encoding="utf-8")
    raw = json.loads(raw_text)
    if not isinstance(raw, Mapping):
        raise ValueError(
            f"Audit definition {candidate} must contain a JSON object."
        )

    if "lexicons" in raw:
        return WorkbenchPayload.model_validate_json(raw_text)

    if "dataset_path" in raw and "daughters" in raw:
        bench_name = str(raw.get("name") or "")
        if (
            bench_name
            and bench_name in available_definitions()
            and candidate.resolve() == definition_path(bench_name).resolve()
            and payload_path(bench_name).exists()
        ):
            return WorkbenchPayload.model_validate_json(
                payload_path(bench_name).read_text(encoding="utf-8")
            )
        defn = BenchmarkDefinition.model_validate_json(raw_text)
        payload, _ = build_benchmark(defn, base_path=candidate.resolve().parent)
        return payload

    if raw.get("suite_version") in EXPLICIT_SUITE_VERSIONS:
        return build_explicit_case(dict(raw))

    if (
        "cases" in raw
        and isinstance(raw["cases"], Sequence)
        and len(raw["cases"]) > 0
    ):
        return build_case(dict(raw["cases"][0])).payload

    if "tree" in raw and "proto_lexicon" in raw:
        syn_defn = SyntheticFamilyDefinition.model_validate_json(raw_text)
        return generate_family(syn_defn).payload

    raise ValueError(
        f"Unrecognized JSON schema in audit definition {candidate}."
    )


def _auto_resolve_payload_for_run(
    directory: Path,
    *,
    result: Mapping[str, Any] | None,
    summary: Mapping[str, Any] | None,
    input_sha256: str | None,
) -> WorkbenchPayload | None:
    """Attempt to resolve a `WorkbenchPayload` from run metadata or matching input digests."""
    from cognate_reconstruction.benchmarks.registry import (
        BUILD_DIR,
        REPO_ROOT,
    )

    for meta in (summary, result):
        if not isinstance(meta, Mapping):
            continue
        for key in ("payload_path", "input_path", "definition", "benchmark"):
            val = meta.get(key)
            if isinstance(val, str) and val.strip():
                for base in (directory, REPO_ROOT):
                    cand = (base / val).expanduser()
                    if cand.exists():
                        try:
                            return resolve_audit_payload(cand)
                        except Exception:
                            pass
                try:
                    return resolve_audit_payload(val)
                except Exception:
                    pass

    ancestors: list[Path] = [directory]
    if directory.parent != directory:
        ancestors.append(directory.parent)
        if directory.parent.parent != directory.parent:
            ancestors.append(directory.parent.parent)

    candidate_files: list[Path] = []
    for anc in ancestors:
        inputs_dir = anc / "inputs"
        if inputs_dir.is_dir():
            candidate_files.extend(
                sorted(p for p in inputs_dir.glob("*.json") if p.is_file())
            )
    if BUILD_DIR.is_dir():
        candidate_files.extend(
            sorted(
                p
                for p in BUILD_DIR.glob("*.json")
                if p.is_file() and not p.name.endswith(".answer-key.json")
            )
        )

    if input_sha256:
        for cf in candidate_files:
            try:
                digest = hashlib.sha256(cf.read_bytes()).hexdigest()
            except OSError:
                continue
            if digest == input_sha256:
                try:
                    return resolve_audit_payload(cf)
                except Exception:
                    continue

    for anc in ancestors:
        inputs_dir = anc / "inputs"
        if inputs_dir.is_dir():
            payload_files = sorted(inputs_dir.glob("*.payload.json"))
            if len(payload_files) == 1:
                try:
                    return resolve_audit_payload(payload_files[0])
                except Exception:
                    pass
        for mf in sorted(anc.glob("manifest*.json")):
            try:
                mblob = json.loads(mf.read_text(encoding="utf-8"))
            except Exception:
                continue
            defn_ref = mblob.get("definition") if isinstance(mblob, Mapping) else None
            if isinstance(defn_ref, str) and defn_ref.strip():
                for base in (anc, REPO_ROOT):
                    cand = (base / defn_ref).expanduser()
                    if cand.exists():
                        try:
                            return resolve_audit_payload(cand)
                        except Exception:
                            pass
                try:
                    return resolve_audit_payload(defn_ref)
                except Exception:
                    pass

    return None


def _build_topology(
    payload: WorkbenchPayload | None,
    *,
    result: Mapping[str, Any] | None,
    summary: Mapping[str, Any] | None,
    steps_by_node: Mapping[str, Any],
) -> _RunTopology | None:
    """Build `_RunTopology` from `payload` (preferred) or embedded `snapshot`."""
    from cognate_reconstruction.tree import (
        assign_node_ids,
        internal_node_ids,
        parse_newick,
    )

    if payload is not None and payload.newick:
        root = parse_newick(payload.newick)
        ids = assign_node_ids(root)
        root_id = ids[id(root)]
        postorder = internal_node_ids(root)
        clade_leaves: dict[str, frozenset[str]] = {}
        children_map: dict[str, tuple[str, ...]] = {}

        def _visit(node: Any) -> frozenset[str]:
            nid = ids[id(node)]
            if node.is_leaf:
                ls = frozenset({nid})
            else:
                acc: set[str] = set()
                ch_ids: list[str] = []
                for ch in node.children:
                    ch_ids.append(ids[id(ch)])
                    acc |= _visit(ch)
                children_map[nid] = tuple(ch_ids)
                ls = frozenset(acc)
            clade_leaves[nid] = ls
            return ls

        all_leaves = _visit(root)
        leaf_forms: dict[tuple[str, str], tuple[Any, ...]] = {}
        for lex in payload.lexicons:
            by_concept: dict[str, list[Any]] = {}
            for form in lex.forms:
                by_concept.setdefault(form.concept_id, []).append(form)
            for cid, flist in by_concept.items():
                leaf_forms[(lex.variety_id, cid)] = tuple(flist)

        return _RunTopology(
            root_node_id=root_id,
            postorder_internal_ids=postorder,
            clade_leaves_by_node=clade_leaves,
            all_leaves=all_leaves,
            leaf_forms_by_variety_concept=leaf_forms,
            children_by_internal=children_map,
        )

    snapshot = (result or {}).get("snapshot") or (summary or {}).get("snapshot")
    if isinstance(snapshot, Mapping) and snapshot.get("root_node_id"):
        root_id = str(snapshot["root_node_id"])
        children_map = {}
        postorder_list: list[str] = []
        for raw_step in snapshot.get("steps") or ():
            if isinstance(raw_step, Mapping) and raw_step.get("parent_node_id"):
                pid = str(raw_step["parent_node_id"])
                cids = tuple(str(x) for x in (raw_step.get("child_node_ids") or ()))
                children_map[pid] = cids
                if pid not in postorder_list:
                    postorder_list.append(pid)
        for pid, step in steps_by_node.items():
            if pid not in children_map:
                children_map[pid] = tuple(step.child_node_ids)
                postorder_list.append(pid)

        if root_id in children_map:
            clade_leaves = {}

            def _leaves_of(nid: str) -> frozenset[str]:
                if nid in clade_leaves:
                    return clade_leaves[nid]
                if nid not in children_map:
                    clade_leaves[nid] = frozenset({nid})
                    return clade_leaves[nid]
                acc: set[str] = set()
                for ch in children_map[nid]:
                    acc |= _leaves_of(ch)
                clade_leaves[nid] = frozenset(acc)
                return clade_leaves[nid]

            all_leaves = _leaves_of(root_id)
            return _RunTopology(
                root_node_id=root_id,
                postorder_internal_ids=tuple(postorder_list),
                clade_leaves_by_node=clade_leaves,
                all_leaves=all_leaves,
                leaf_forms_by_variety_concept={},
                children_by_internal=children_map,
            )

    return None


def _text_cites_external_outgroup(
    text: str,
    *,
    external_node_ids: frozenset[str],
    own_clade_node_ids: frozenset[str],
) -> tuple[bool, tuple[str, ...]]:
    """Return `(cites_outgroup, explicitly_named_external_varieties)` for a rationale string.

    Ignores negative disclaimers such as 'no outgroup' or 'without outgroup'
    unless an external variety or positive outgroup corroboration is also cited.
    """
    cleaned = text.strip()
    if not cleaned:
        return False, ()
    lowered = cleaned.lower()

    own_tokens: set[str] = set()
    for own_id in own_clade_node_ids:
        own_tokens.add(own_id.lower())
        short_own = own_id.split(":")[-1].lower()
        if short_own:
            own_tokens.add(short_own)

    named_external: list[str] = []
    for ext_id in sorted(external_node_ids):
        ext_low = ext_id.lower()
        short_ext = ext_id.split(":")[-1].lower()
        matched = False
        if ":" in ext_low and ext_low in lowered:
            matched = True
        elif f"{ext_low}:" in lowered:
            matched = True
        elif len(short_ext) >= 3 and short_ext not in own_tokens:
            if re.search(rf"\b{re.escape(short_ext)}s?\b", lowered):
                matched = True
        elif 1 <= len(short_ext) <= 2 and short_ext not in own_tokens:
            # Short synthetic IDs (e.g. 'c', 'd', 'f'): require explicit node/variety/outgroup context
            if re.search(
                rf"(?:\b(?:node|variety|clade|branch|out-?groups?)\s+{re.escape(short_ext)}\b"
                rf"|out-?groups?\s*\([^)]*\b{re.escape(short_ext)}\b)",
                lowered,
            ):
                matched = True
        if matched:
            named_external.append(ext_id)

    stripped_of_disclaimers = _NEGATIVE_OUTGROUP_DISCLAIMER_RE.sub(" ", lowered)
    has_positive_outgroup_term = bool(
        _POSITIVE_OUTGROUP_TERM_RE.search(stripped_of_disclaimers)
    )
    if named_external or has_positive_outgroup_term:
        return True, tuple(named_external)
    return False, ()


def _collect_navigation_evidence(
    trajectory: Any,
    external_node_ids: frozenset[str],
) -> tuple[
    set[tuple[str, str]],
    set[str],
    set[tuple[str | None, ...]],
    list[str],
    dict[str, set[str]],
    dict[str, tuple[str | None, ...]],
    set[str],
]:
    """Extract inspected outgroup sightings, polarized sets/correspondences, and surveyed local sets."""
    from cognate_reconstruction.evaluation.judgment import _form_sightings
    from cognate_reconstruction.evaluation.usability import tool_exchanges
    from cognate_reconstruction.schemas.inventory import normalize_written_gaps

    seen_outgroup_forms: set[tuple[str, str]] = set()
    polarized_set_ids: set[str] = set()
    polarized_correspondences: set[tuple[str | None, ...]] = set()
    inspection_call_ids: list[str] = []
    survey_set_to_concepts: dict[str, set[str]] = {}
    survey_set_to_reflexes: dict[str, tuple[str | None, ...]] = {}
    surveyed_local_set_ids: set[str] = set()

    if trajectory is None:
        return (
            seen_outgroup_forms,
            polarized_set_ids,
            polarized_correspondences,
            inspection_call_ids,
            survey_set_to_concepts,
            survey_set_to_reflexes,
            surveyed_local_set_ids,
        )

    non_survey_inspection_tools = frozenset(
        {
            "search_forms",
            "get_alignments",
            "polarize",
            "get_node_reconstruction",
        }
    )

    pattern_members: dict[str, tuple[str, ...]] = {}
    for ex in tool_exchanges(trajectory):
        if not ex["ok"]:
            continue
        name = ex["name"]
        res = ex["result"]
        args = ex["arguments"]

        if name == "summarize_correspondences":
            reading = res.get("reading") or args.get("reading")
            for row in res.get("sets") or ():
                if not isinstance(row, Mapping):
                    continue
                sid = row.get("set_id")
                if not isinstance(sid, str) or not sid:
                    continue
                segs = row.get("segments")
                norm_segs = (
                    tuple(normalize_written_gaps(segs))
                    if isinstance(segs, (list, tuple))
                    else None
                )
                ex_cids = [
                    str(c) for c in (row.get("example_concept_ids") or ()) if c
                ]
                members = [
                    str(m) for m in (row.get("member_set_ids") or ()) if m
                ]
                if members:
                    pattern_members[sid] = tuple(members)
                    surveyed_local_set_ids.update(members)
                    for m in members:
                        if norm_segs is not None and m not in survey_set_to_reflexes:
                            survey_set_to_reflexes[m] = norm_segs
                        if ex_cids:
                            survey_set_to_concepts.setdefault(m, set()).update(
                                ex_cids
                            )
                else:
                    if reading in (None, "local") or sid.startswith(
                        ("csu-", "cs-")
                    ):
                        surveyed_local_set_ids.add(sid)
                    if norm_segs is not None:
                        survey_set_to_reflexes[sid] = norm_segs
                    if ex_cids:
                        survey_set_to_concepts.setdefault(sid, set()).update(
                            ex_cids
                        )
            continue

        if name in non_survey_inspection_tools:
            before_count = len(seen_outgroup_forms)
            _form_sightings(res, external_node_ids, seen_outgroup_forms)
            returned_outgroup = len(seen_outgroup_forms) > before_count

            if name == "polarize":
                node_reports = [
                    nr
                    for nr in (res.get("nodes") or ())
                    if isinstance(nr, Mapping)
                    and (
                        nr.get("relation") == "outgroup"
                        or nr.get("node_id") in external_node_ids
                    )
                ]
                if node_reports:
                    returned_outgroup = True
                    for w in res.get("witnesses") or ():
                        if (
                            isinstance(w, Mapping)
                            and w.get("node_id") in external_node_ids
                            and w.get("concept_id")
                        ):
                            seen_outgroup_forms.add(
                                (str(w["node_id"]), str(w["concept_id"]))
                            )
                    arg_cids = [
                        str(c) for c in (args.get("concept_ids") or ()) if c
                    ]
                    matched_cids = [
                        str(c)
                        for c in (res.get("matched_concept_ids") or ())
                        if c
                    ]
                    for cid in set(arg_cids) | set(matched_cids):
                        for nr in node_reports:
                            if (
                                nr.get("columns_covered", 0) > 0
                                or cid in arg_cids
                            ):
                                seen_outgroup_forms.add(
                                    (str(nr["node_id"]), cid)
                                )
                    if not arg_cids:
                        pol_sid = res.get("set_id") or args.get("set_id")
                        if isinstance(pol_sid, str) and pol_sid:
                            polarized_set_ids.add(pol_sid)
                            for m in pattern_members.get(pol_sid, ()):
                                polarized_set_ids.add(m)
                        corr = res.get("correspondence") or args.get(
                            "correspondence"
                        )
                        if isinstance(corr, (list, tuple)):
                            polarized_correspondences.add(
                                tuple(normalize_written_gaps(corr))
                            )

            if name == "get_node_reconstruction":
                target_nid = args.get("node_id") or res.get("node_id")
                if target_nid in external_node_ids:
                    for form_row in res.get("forms") or ():
                        if isinstance(form_row, Mapping) and form_row.get(
                            "concept_id"
                        ):
                            seen_outgroup_forms.add(
                                (str(target_nid), str(form_row["concept_id"]))
                            )
                            returned_outgroup = True

            if returned_outgroup and ex["call_id"] not in inspection_call_ids:
                inspection_call_ids.append(str(ex["call_id"]))

    return (
        seen_outgroup_forms,
        polarized_set_ids,
        polarized_correspondences,
        inspection_call_ids,
        survey_set_to_concepts,
        survey_set_to_reflexes,
        surveyed_local_set_ids,
    )


def _analysis_has_explicit_cognate_units(analysis: Any) -> bool:
    """True when a `FormAnalysis` has explicit `cog:*` pieces and no `unknown` pieces."""
    if analysis is None or not getattr(analysis, "pieces", None):
        return False
    non_structural = [
        p
        for p in analysis.pieces
        if p.kind not in ("boundary", "restoration")
    ]
    if not non_structural:
        return False
    return all(
        (p.cognate_set_id is not None or str(p.unit_id).startswith("cog:"))
        and p.kind != "unknown"
        and p.unit_id != "whole:unknown"
        for p in non_structural
    )


def _analysis_lost_unit_provenance(analysis: Any) -> bool:
    """True when an assembled `FormAnalysis` is missing or degraded to `whole:unknown`."""
    if analysis is None or not getattr(analysis, "pieces", None):
        return True
    non_structural = [
        p
        for p in analysis.pieces
        if p.kind not in ("boundary", "restoration")
    ]
    if not non_structural:
        return True
    return any(
        p.unit_id == "whole:unknown"
        or p.kind == "unknown"
        or (
            p.cognate_set_id is None
            and not str(p.unit_id).startswith("cog:")
        )
        for p in non_structural
    )


def audit_run_directory(
    run_dir: str | Path,
    payload: WorkbenchPayload | None = None,
) -> dict[str, Any]:
    """Deterministically audit a family reconstruction run directory at $0 cost.

    Supports completed runs (`result.json`), `--stop-after-node` planned-stop
    checkpoints, and incomplete/stalled runs (`trajectories.jsonl` +
    `checkpoint.json` + `run_summary.json`). Checks strictly the 5 exact,
    alignment-safe real-family provenance and trace invariants:

    1. `silent_residue_drop_truncation`
    2. `uninspected_outgroup_citation` (non-root nodes with external outgroups only)
    3. `unit_provenance_loss`
    4. `identity_confidence_length_bias`
    5. `upstream_tie_collapse_majority`
    """
    from cognate_reconstruction.agent.trajectory import TrajectoryDatasetBuilder
    from cognate_reconstruction.alignment.units import source_analyses
    from cognate_reconstruction.evaluation.run import (
        step_from_artifact,
        trajectory_from_artifact,
    )
    from cognate_reconstruction.evaluation.usability import tool_exchanges
    from cognate_reconstruction.schemas.inventory import (
        CommittedProtoInventory,
        ConceptAssemblyReport,
        derive_set_id,
        normalize_written_gaps,
    )
    from cognate_reconstruction.traversal.beam import decided_by_tie_break
    from cognate_reconstruction.traversal.checkpoint import CheckpointStore

    directory = Path(run_dir).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError(f"Not a run directory: {directory}")

    summary_path = directory / "run_summary.json"
    summary: dict[str, Any] | None = (
        json.loads(summary_path.read_text(encoding="utf-8"))
        if summary_path.exists()
        else None
    )
    result_path = directory / "result.json"
    raw_result: dict[str, Any] | None = (
        json.loads(result_path.read_text(encoding="utf-8"))
        if result_path.exists()
        else None
    )
    # Match `load_result_or_summary`: an interrupted summary overrides a stale pre-resume result.json
    effective_result: Mapping[str, Any] | None = (
        summary
        if (summary is not None and summary.get("status") == "interrupted")
        else (raw_result if raw_result is not None else summary)
    )

    checkpoint = None
    checkpoint_path = directory / "checkpoint.json"
    if checkpoint_path.exists():
        checkpoint = CheckpointStore(checkpoint_path).load()

    traj_path = directory / "trajectories.jsonl"
    raw_trajectories = (
        tuple(TrajectoryDatasetBuilder.read_jsonl(traj_path))
        if traj_path.exists()
        else tuple(
            trajectory_from_artifact(t)
            for t in (effective_result or {}).get("trajectories", ())
        )
    )

    if (
        not raw_trajectories
        and effective_result is None
        and checkpoint is None
    ):
        raise ValueError(
            f"Run directory {directory} contains no result.json, run_summary.json, "
            "checkpoint.json, or trajectories.jsonl."
        )

    artifact_run_id = (
        (effective_result or {}).get("run_id")
        or ((effective_result or {}).get("lifecycle_summary") or {}).get("run_id")
        or (checkpoint.run_id if checkpoint is not None else None)
    )
    lifecycle = (
        (effective_result or {}).get("lifecycle_summary")
        or effective_result
        or {}
    )
    active_traj_ids = lifecycle.get("active_trajectory_ids")

    trajectories_by_node: dict[str, Any] = {}
    for traj in raw_trajectories:
        if artifact_run_id is not None and traj.run_id != artifact_run_id:
            continue
        if (
            isinstance(active_traj_ids, Sequence)
            and active_traj_ids
            and traj.trajectory_id not in active_traj_ids
        ):
            continue
        trajectories_by_node[traj.node_id] = traj
    # If active_trajectory_ids excluded a failed/stalled attempt, still keep latest attempt per node
    for traj in raw_trajectories:
        if artifact_run_id is not None and traj.run_id != artifact_run_id:
            continue
        trajectories_by_node.setdefault(traj.node_id, traj)

    steps_by_node: dict[str, Any] = {}
    if checkpoint is not None:
        steps_by_node.update(checkpoint.steps_by_node)
    snapshot = (effective_result or {}).get("snapshot")
    if isinstance(snapshot, Mapping):
        for raw_step in snapshot.get("steps") or ():
            step = step_from_artifact(raw_step)
            steps_by_node.setdefault(step.parent_node_id, step)
    for node_id, traj in trajectories_by_node.items():
        if traj.completed and traj.reconstruction_step is not None:
            steps_by_node.setdefault(node_id, traj.reconstruction_step)

    if payload is None:
        payload = _auto_resolve_payload_for_run(
            directory,
            result=raw_result,
            summary=summary,
            input_sha256=(
                checkpoint.input_sha256 if checkpoint is not None else None
            ),
        )

    topology = _build_topology(
        payload,
        result=raw_result,
        summary=summary,
        steps_by_node=steps_by_node,
    )
    if topology is None:
        raise ValueError(
            f"Cannot determine family tree topology for {directory} without a "
            "WorkbenchPayload; pass payload=... (or --definition on CLI)."
        )

    # Determine run_status
    if summary is not None and summary.get("status") == "interrupted":
        if summary.get("failure_kind") == "planned_stop":
            run_status = "planned_stop"
        else:
            run_status = "incomplete"
    elif raw_result is not None and (
        raw_result.get("status") in (None, "completed")
    ):
        run_status = "completed"
    elif summary is not None and summary.get("status") == "completed":
        run_status = "completed"
    else:
        run_status = "incomplete"

    node_failures = {
        str(f["node_id"])
        for f in (effective_result or {}).get("node_failures", ())
        if isinstance(f, Mapping) and f.get("node_id")
    }
    fallback_nodes = (
        {
            nid
            for nid, st in steps_by_node.items()
            if st.diagnostics.failure_fallback
        }
        | {str(x) for x in (lifecycle.get("fallback_node_ids") or ()) if x}
        | (
            node_failures
            if (
                raw_result is not None
                and (summary is None or summary.get("status") != "interrupted")
            )
            else set()
        )
    )

    attempted_from_summary = {
        str(x)
        for x in ((summary or {}).get("attempted_node_ids") or ())
        if x
    }
    visited_nodes = (
        set(trajectories_by_node.keys())
        | set(steps_by_node.keys())
        | attempted_from_summary
    )
    nodes_audited: list[str] = [
        nid for nid in topology.postorder_internal_ids if nid in visited_nodes
    ]
    for extra_nid in list(trajectories_by_node.keys()) + list(
        steps_by_node.keys()
    ):
        if extra_nid not in nodes_audited:
            nodes_audited.append(extra_nid)
    unattempted_nodes: list[str] = [
        nid
        for nid in topology.postorder_internal_ids
        if nid not in nodes_audited
    ]

    # Helper to query available concepts & active child source IDs for a node
    def _active_child_ids_for(nid: str, step: Any, traj: Any) -> tuple[str, ...]:
        if step is not None:
            return tuple(step.child_node_ids)
        if nid in topology.children_by_internal:
            return topology.children_by_internal[nid]
        if traj is not None and getattr(traj, "initial_payload", None) is not None:
            return tuple(
                c.node_id for c in traj.initial_payload.active_children
            )
        return ()

    def _child_concepts_and_sources(
        child_ids: Sequence[str],
        step: Any,
    ) -> tuple[dict[str, set[str]], dict[tuple[str, str], list[str]]]:
        """Return `(attesting_children_by_concept, form_ids_by_child_concept)`."""
        attesting: dict[str, set[str]] = {}
        form_ids: dict[tuple[str, str], list[str]] = {}
        if step is not None and step.input_beams:
            for ib in step.input_beams:
                for dist in ib.distributions:
                    attesting.setdefault(dist.concept_id, set()).add(ib.node_id)
                    fids = form_ids.setdefault(
                        (ib.node_id, dist.concept_id), []
                    )
                    if (
                        ib.node_id,
                        dist.concept_id,
                    ) in topology.leaf_forms_by_variety_concept:
                        for lf in topology.leaf_forms_by_variety_concept[
                            (ib.node_id, dist.concept_id)
                        ]:
                            if lf.form_id not in fids:
                                fids.append(lf.form_id)
                    else:
                        for cand in dist.candidates:
                            if cand.candidate_id not in fids:
                                fids.append(cand.candidate_id)
            return attesting, form_ids

        for ch_id in child_ids:
            if ch_id in steps_by_node:
                ch_beam = steps_by_node[ch_id].output_beam
                for dist in ch_beam.distributions:
                    attesting.setdefault(dist.concept_id, set()).add(ch_id)
                    fids = form_ids.setdefault((ch_id, dist.concept_id), [])
                    for cand in dist.candidates:
                        if cand.candidate_id not in fids:
                            fids.append(cand.candidate_id)
            else:
                for (vid, cid), flist in topology.leaf_forms_by_variety_concept.items():
                    if vid == ch_id:
                        attesting.setdefault(cid, set()).add(ch_id)
                        fids = form_ids.setdefault((ch_id, cid), [])
                        for lf in flist:
                            if lf.form_id not in fids:
                                fids.append(lf.form_id)
        return attesting, form_ids

    # Track per-node committed claim maps and tied-column summaries for upstream_tie_collapse_majority
    committed_claims_by_node: dict[str, dict[str, dict[str, Any]]] = {}
    validation_call_by_node: dict[str, str | None] = {}

    defect_counts_by_category: dict[str, int] = {
        cat: 0 for cat in REAL_RUN_DEFECT_CATEGORIES
    }
    nodes_report: dict[str, dict[str, Any]] = {}
    all_defects: list[dict[str, Any]] = []

    for node_id in nodes_audited:
        step = steps_by_node.get(node_id)
        traj = trajectories_by_node.get(node_id)
        is_fallback = node_id in fallback_nodes or bool(
            step is not None and step.diagnostics.failure_fallback
        )
        committed_obj = (
            getattr(traj, "committed_reconstruction", None)
            if traj is not None
            else None
        )
        is_committed = bool(
            not is_fallback
            and step is not None
            and (traj is None or traj.completed)
        )
        child_ids = _active_child_ids_for(node_id, step, traj)
        attesting_by_concept, form_ids_by_child_concept = (
            _child_concepts_and_sources(child_ids, step)
        )
        available_concepts = set(attesting_by_concept.keys())

        own_leaves = topology.clade_leaves_by_node.get(node_id, frozenset())
        ext_leaves = topology.all_leaves - own_leaves
        is_root = (
            node_id == topology.root_node_id or len(ext_leaves) == 0
        )
        ext_internal = frozenset(
            other_nid
            for other_nid, other_leaves in topology.clade_leaves_by_node.items()
            if other_leaves
            and other_leaves <= ext_leaves
            and other_nid not in topology.all_leaves
        )
        ext_all_nodes = ext_leaves | ext_internal
        own_clade_nodes = (
            own_leaves
            | frozenset(child_ids)
            | frozenset(
                other_nid
                for other_nid, other_leaves in topology.clade_leaves_by_node.items()
                if other_leaves and other_leaves <= own_leaves
            )
            | frozenset({node_id})
        )

        (
            seen_outgroup_forms,
            polarized_set_ids,
            polarized_correspondences,
            inspection_call_ids,
            survey_set_to_concepts,
            survey_set_to_reflexes,
            surveyed_local_set_ids,
        ) = _collect_navigation_evidence(traj, ext_all_nodes)

        exchanges = tool_exchanges(traj) if traj is not None else []
        accepted_previews = [
            e
            for e in exchanges
            if e["name"] == "test_proto_assembly" and e["ok"]
        ]
        last_preview = accepted_previews[-1] if accepted_previews else None

        # Extract inventory metrics, claims, and assembly reports from committed inventory or last preview
        inventory_source: Literal[
            "committed", "last_preview", "rules_commit", "none"
        ] = "none"
        residue_policy: str | None = None
        unaccounted_column_count: int | None = None
        assembled_column_count: int | None = None
        unaccounted_column_rate: float | None = None
        uncovered_set_ids: list[str] = []
        uncovered_set_count: int | None = None
        completely_dropped_concepts: list[str] = []
        partially_truncated_concepts: list[str] = []
        uncovered_concept_ids: list[str] = []
        uncovered_concept_count: int | None = None
        validation_call_id: str | None = None
        resolved_preview_call_id: str | None = None
        node_summary_text: str = ""
        is_identity_short_circuit = False
        active_reports: tuple[Any, ...] = ()
        claims_to_audit: list[dict[str, Any]] = []
        preview_set_to_concepts: dict[str, set[str]] = {}
        preview_set_to_columns: dict[str, set[int]] = {}

        if is_committed and isinstance(committed_obj, CommittedProtoInventory):
            inventory_source = "committed"
            req = committed_obj.request
            residue_policy = req.residue_policy.value
            node_summary_text = req.summary or ""
            is_identity_short_circuit = committed_obj.identity_reconstruction
            validation_call_id = req.assembly_validation_call_id or (
                str(last_preview["call_id"]) if last_preview else None
            )
            active_reports = step.assembly_reports if step is not None else ()

            if is_identity_short_circuit:
                assembled_column_count = 0
                unaccounted_column_count = 0
                unaccounted_column_rate = 0.0
                uncovered_set_ids = []
                uncovered_set_count = 0
                uncovered_concept_ids = []
                uncovered_concept_count = 0
            else:
                diag = step.diagnostics
                assembled_column_count = (
                    diag.assembled_column_count
                    if diag.assembled_column_count is not None
                    else sum(r.column_count for r in active_reports)
                )
                unaccounted_column_count = (
                    diag.unaccounted_column_count
                    if diag.unaccounted_column_count is not None
                    else sum(
                        r.unaccounted_column_count for r in active_reports
                    )
                )
                unaccounted_column_rate = (
                    float(diag.unaccounted_column_rate)
                    if diag.unaccounted_column_rate is not None
                    else (
                        unaccounted_column_count / assembled_column_count
                        if assembled_column_count
                        else 0.0
                    )
                )

                covered_sets = {c.set_id for c in req.commitments}
                local_sets: set[str] = set(surveyed_local_set_ids)
                local_sets.update(
                    b.set_id for b in committed_obj.column_bindings
                )
                for r in active_reports:
                    for col in r.columns:
                        if col.set_id is not None:
                            local_sets.add(col.set_id)
                        elif (
                            committed_obj.evidence_contract_version == "legacy"
                            and col.resolved_by == "residue_policy"
                        ):
                            local_sets.add(
                                derive_set_id(
                                    col.reflexes,
                                    step.child_node_ids,
                                    segmentation_overlay_id=req.segmentation_overlay_id,
                                    alignment_overlay_id=req.alignment_overlay_id,
                                )
                            )
                if (
                    unaccounted_column_count > 0
                    and len(local_sets - covered_sets) == 0
                    and step.input_beams
                ):
                    try:
                        from cognate_reconstruction.agent.context import (
                            AgentContext,
                        )
                        from cognate_reconstruction.agent.tools.inventory_evidence import (
                            node_inventory,
                        )
                        from cognate_reconstruction.alignment.lingpy_adapter import (
                            LingPyAligner,
                        )
                        from cognate_reconstruction.traversal.beam import (
                            beam_to_lexicon,
                        )

                        ctx = AgentContext(
                            node_id=node_id,
                            child_lexicons=tuple(
                                beam_to_lexicon(b) for b in step.input_beams
                            ),
                            child_beams=step.input_beams,
                            aligner=LingPyAligner(),
                        )
                        inv_sets, _ = node_inventory(
                            ctx,
                            segmentation_overlay_id=req.segmentation_overlay_id,
                            alignment_overlay_id=req.alignment_overlay_id,
                            unit_orders=req.unit_orders,
                        )
                        local_sets.update(s.set_id for s in inv_sets.sets)
                    except Exception:
                        pass

                uncovered_set_ids = sorted(local_sets - covered_sets)
                uncovered_set_count = len(uncovered_set_ids)

                output_concepts = {
                    d.concept_id for d in step.output_beam.distributions
                }
                completely_dropped_concepts = sorted(
                    available_concepts - output_concepts
                )
                partially_truncated_concepts = sorted(
                    r.concept_id
                    for r in active_reports
                    if r.unaccounted_column_count > 0
                )
                uncovered_concept_ids = sorted(
                    set(completely_dropped_concepts)
                    | set(partially_truncated_concepts)
                )
                uncovered_concept_count = len(uncovered_concept_ids)

            claim_map: dict[str, dict[str, Any]] = {}
            for c in req.commitments:
                entry = {
                    "set_id": c.set_id,
                    "reflexes": tuple(c.reflexes),
                    "proto_segment": c.proto_segment,
                    "confidence": float(c.confidence),
                    "rationale": c.rationale or "",
                    "directionality_rationale": c.directionality_rationale
                    or "",
                }
                claims_to_audit.append(entry)
                claim_map[c.set_id] = entry
            committed_claims_by_node[node_id] = claim_map
            validation_call_by_node[node_id] = validation_call_id

        elif is_committed and committed_obj is not None:
            # Rule cascade commit shape
            inventory_source = "rules_commit"
            req = getattr(committed_obj, "request", None)
            node_summary_text = getattr(req, "summary", "") or ""
            validation_call_id = getattr(
                req, "cascade_validation_call_id", None
            )
            validation_call_by_node[node_id] = validation_call_id
            for r_item in getattr(req, "rules", ()) or ():
                claims_to_audit.append(
                    {
                        "set_id": getattr(r_item, "rule_id", None) or "rule",
                        "reflexes": None,
                        "proto_segment": None,
                        "confidence": float(getattr(r_item, "confidence", 1.0)),
                        "rationale": getattr(r_item, "rationale", "") or "",
                        "directionality_rationale": getattr(
                            r_item, "directionality_rationale", ""
                        )
                        or "",
                    }
                )

        elif is_committed and step is not None:
            # Saved step without trajectory (e.g., checkpointed step without trajectories.jsonl)
            diag = step.diagnostics
            if diag.assembled_column_count is not None or step.assembly_reports:
                inventory_source = "committed"
                active_reports = step.assembly_reports
                assembled_column_count = (
                    diag.assembled_column_count
                    if diag.assembled_column_count is not None
                    else sum(r.column_count for r in active_reports)
                )
                unaccounted_column_count = (
                    diag.unaccounted_column_count
                    if diag.unaccounted_column_count is not None
                    else sum(
                        r.unaccounted_column_count for r in active_reports
                    )
                )
                unaccounted_column_rate = (
                    float(diag.unaccounted_column_rate)
                    if diag.unaccounted_column_rate is not None
                    else (
                        unaccounted_column_count / assembled_column_count
                        if assembled_column_count
                        else 0.0
                    )
                )
                # Infer drop vs retain_from_witness from residue_policy columns when trajectory is absent
                residue_cols = [
                    col
                    for r in active_reports
                    for col in r.columns
                    if col.resolved_by == "residue_policy"
                ]
                output_concepts = {
                    d.concept_id for d in step.output_beam.distributions
                }
                completely_dropped_concepts = sorted(
                    available_concepts - output_concepts
                )
                if completely_dropped_concepts or (
                    residue_cols
                    and all(col.proto_segment is None for col in residue_cols)
                    and any(
                        any(rx is not None for rx in col.reflexes)
                        for col in residue_cols
                    )
                ):
                    residue_policy = "drop"
                elif residue_cols:
                    residue_policy = "retain_from_witness"
                partially_truncated_concepts = sorted(
                    r.concept_id
                    for r in active_reports
                    if r.unaccounted_column_count > 0
                )
                uncovered_concept_ids = sorted(
                    set(completely_dropped_concepts)
                    | set(partially_truncated_concepts)
                )
                uncovered_concept_count = len(uncovered_concept_ids)
                covered_sets = {
                    col.set_id
                    for r in active_reports
                    for col in r.columns
                    if col.set_id is not None
                }
                uncovered_set_count = 0 if unaccounted_column_count == 0 else None

        elif not is_committed and last_preview is not None:
            inventory_source = "last_preview"
            validation_call_id = str(last_preview["call_id"])
            validation_call_by_node[node_id] = validation_call_id

            def _has_full_preview_concepts(ex: Mapping[str, Any]) -> bool:
                res = ex.get("result")
                return (
                    isinstance(res, Mapping)
                    and not res.get("repeat_guard")
                    and not res.get("compacted")
                    and isinstance(res.get("concepts"), Sequence)
                )

            resolved_preview: Mapping[str, Any] = last_preview
            matched_identical = False
            raw_last_res = last_preview.get("result")
            if isinstance(raw_last_res, Mapping) and (
                raw_last_res.get("repeat_guard") is True
                or not _has_full_preview_concepts(last_preview)
            ):
                previews_by_call_id = {
                    str(ex["call_id"]): ex
                    for ex in accepted_previews
                    if ex.get("call_id") is not None
                }
                seen_call_ids: set[str] = set()
                target_call_id = raw_last_res.get("identical_to_call_id")
                candidate_preview: Mapping[str, Any] | None = None
                while (
                    isinstance(target_call_id, str)
                    and target_call_id
                    and target_call_id not in seen_call_ids
                ):
                    seen_call_ids.add(target_call_id)
                    matched_ex = previews_by_call_id.get(target_call_id)
                    if matched_ex is None:
                        break
                    if _has_full_preview_concepts(matched_ex):
                        candidate_preview = matched_ex
                        matched_identical = True
                        break
                    next_res = matched_ex.get("result")
                    target_call_id = (
                        next_res.get("identical_to_call_id")
                        if isinstance(next_res, Mapping)
                        else None
                    )
                if candidate_preview is None:
                    for earlier_ex in reversed(accepted_previews):
                        if _has_full_preview_concepts(earlier_ex):
                            candidate_preview = earlier_ex
                            break
                if candidate_preview is not None:
                    resolved_preview = candidate_preview
                    if candidate_preview.get("call_id") is not None:
                        resolved_preview_call_id = str(
                            candidate_preview["call_id"]
                        )

            prev_res = (
                resolved_preview["result"]
                if isinstance(resolved_preview.get("result"), Mapping)
                else {}
            )
            raw_resolved_args = (
                resolved_preview["arguments"]
                if isinstance(resolved_preview.get("arguments"), Mapping)
                else {}
            )
            raw_last_args = (
                last_preview["arguments"]
                if isinstance(last_preview.get("arguments"), Mapping)
                else {}
            )
            if resolved_preview is last_preview:
                prev_args = raw_last_args
            elif matched_identical:
                prev_args = {
                    **raw_resolved_args,
                    **{
                        k: v
                        for k, v in raw_last_args.items()
                        if v is not None and v != () and v != [] and v != {}
                    },
                }
            else:
                prev_args = {
                    **raw_last_args,
                    **{
                        k: v
                        for k, v in raw_resolved_args.items()
                        if v is not None
                    },
                }

            residue_policy = str(
                prev_res.get("residue_policy")
                or (
                    raw_last_res.get("residue_policy")
                    if isinstance(raw_last_res, Mapping)
                    else None
                )
                or prev_args.get("residue_policy")
                or ""
            ) or None

            raw_concepts = prev_res.get("concepts")
            if isinstance(raw_concepts, Sequence) and not prev_res.get(
                "compacted"
            ):
                parsed_reports: list[Any] = []
                for rc in raw_concepts:
                    if isinstance(rc, Mapping):
                        parsed_reports.append(
                            ConceptAssemblyReport.model_validate_json(
                                json.dumps(rc)
                            )
                        )
                active_reports = tuple(parsed_reports)
                assembled_column_count = sum(
                    r.column_count for r in active_reports
                )
                unaccounted_column_count = sum(
                    r.unaccounted_column_count for r in active_reports
                )
                unaccounted_column_rate = float(
                    prev_res.get(
                        "unaccounted_column_rate",
                        unaccounted_column_count / assembled_column_count
                        if assembled_column_count
                        else 0.0,
                    )
                )
                selected_cids_arg = {
                    str(x) for x in (prev_args.get("concept_ids") or ()) if x
                }
                scope_concepts = (
                    selected_cids_arg
                    if selected_cids_arg
                    else available_concepts
                )
                present_cids = {r.concept_id for r in active_reports}
                completely_dropped_concepts = sorted(
                    scope_concepts - present_cids
                )
                partially_truncated_concepts = sorted(
                    r.concept_id
                    for r in active_reports
                    if r.unaccounted_column_count > 0
                )
                uncovered_concept_ids = sorted(
                    set(completely_dropped_concepts)
                    | set(partially_truncated_concepts)
                )
                uncovered_concept_count = len(uncovered_concept_ids)
            else:
                unaccounted_column_rate = (
                    float(prev_res["unaccounted_column_rate"])
                    if prev_res.get("unaccounted_column_rate") is not None
                    else None
                )

            covered_sets = {
                str(s) for s in (prev_res.get("covered_set_ids") or ()) if s
            }
            for row in list(prev_args.get("choices") or ()) + list(
                prev_args.get("commitments") or ()
            ):
                if isinstance(row, Mapping) and row.get("set_id"):
                    sid = str(row["set_id"])
                    covered_sets.add(sid)
                    raw_ref = row.get("reflexes")
                    norm_ref = (
                        tuple(normalize_written_gaps(raw_ref))
                        if isinstance(raw_ref, (list, tuple))
                        else survey_set_to_reflexes.get(sid)
                    )
                    claims_to_audit.append(
                        {
                            "set_id": sid,
                            "reflexes": norm_ref,
                            "proto_segment": row.get("proto_segment"),
                            "confidence": float(row.get("confidence", 1.0)),
                            "rationale": str(row.get("rationale") or ""),
                            "directionality_rationale": str(
                                row.get("directionality_rationale") or ""
                            ),
                        }
                    )
            for sc in prev_args.get("shared_claims") or ():
                if isinstance(sc, Mapping):
                    for m_sid in sc.get("member_set_ids") or ():
                        sid = str(m_sid)
                        covered_sets.add(sid)
                        claims_to_audit.append(
                            {
                                "set_id": sid,
                                "pattern_id": str(sc.get("pattern_id") or ""),
                                "reflexes": survey_set_to_reflexes.get(sid),
                                "proto_segment": sc.get("proto_segment"),
                                "confidence": float(sc.get("confidence", 1.0)),
                                "rationale": str(sc.get("rationale") or ""),
                                "directionality_rationale": str(
                                    sc.get("directionality_rationale") or ""
                                ),
                            }
                        )

            local_sets = set(surveyed_local_set_ids) | {
                col.set_id
                for r in active_reports
                for col in r.columns
                if col.set_id is not None
            }
            need_alignment_columns = not any(r.columns for r in active_reports)
            if (
                (
                    need_alignment_columns
                    or (
                        len(local_sets - covered_sets) == 0
                        and (
                            (unaccounted_column_rate or 0.0) > 0.0
                            or completely_dropped_concepts
                        )
                    )
                )
                and child_ids
                and payload is not None
            ):
                try:
                    from cognate_reconstruction.agent.context import (
                        AgentContext,
                    )
                    from cognate_reconstruction.agent.tools.inventory_evidence import (
                        column_bindings,
                        node_inventory,
                    )
                    from cognate_reconstruction.alignment.lingpy_adapter import (
                        LingPyAligner,
                    )
                    from cognate_reconstruction.traversal.beam import (
                        beam_to_lexicon,
                    )

                    by_var = {l.variety_id: l for l in payload.lexicons}
                    ch_lexs = tuple(
                        beam_to_lexicon(steps_by_node[cid].output_beam)
                        if cid in steps_by_node
                        else by_var[cid]
                        for cid in child_ids
                        if cid in steps_by_node or cid in by_var
                    )
                    if len(ch_lexs) == len(child_ids):
                        ctx = AgentContext(
                            node_id=node_id,
                            child_lexicons=ch_lexs,
                            aligner=LingPyAligner(),
                        )
                        inv_sets, alignment_map = node_inventory(
                            ctx,
                            segmentation_overlay_id=prev_args.get(
                                "segmentation_overlay_id"
                            ),
                            alignment_overlay_id=prev_args.get(
                                "alignment_overlay_id"
                            ),
                        )
                        local_sets.update(s.set_id for s in inv_sets.sets)
                        binding_by_col_id = {
                            b.column_id: b
                            for b in column_bindings(alignment_map, child_ids)
                        }
                        for aln in alignment_map.alignments:
                            for col_idx, ecol in enumerate(
                                aln.evidence_columns
                            ):
                                b = binding_by_col_id.get(ecol.column_id)
                                if b is not None:
                                    preview_set_to_concepts.setdefault(
                                        b.set_id, set()
                                    ).add(aln.concept_id)
                                    preview_set_to_columns.setdefault(
                                        b.set_id, set()
                                    ).add(col_idx)
                except Exception:
                    pass

            if local_sets or not covered_sets:
                uncovered_set_ids = sorted(local_sets - covered_sets)
                uncovered_set_count = len(uncovered_set_ids)

            is_identity_short_circuit = (
                len(covered_sets) == 0
                and not prev_args.get("residue_dispositions")
                and not prev_args.get("restorations")
                and not prev_args.get("unit_orders")
            )
            if is_identity_short_circuit:
                assembled_column_count = 0
                unaccounted_column_count = 0
                unaccounted_column_rate = 0.0
                uncovered_set_ids = []
                uncovered_set_count = 0
                completely_dropped_concepts = []
                partially_truncated_concepts = []
                uncovered_concept_ids = []
                uncovered_concept_count = 0

        # Build set_id -> concepts map combining assembly reports, preview alignments, and survey examples
        set_to_concepts: dict[str, set[str]] = {
            sid: set(cids) for sid, cids in survey_set_to_concepts.items()
        }
        set_to_columns: dict[str, set[int]] = {}
        for sid, cids in preview_set_to_concepts.items():
            set_to_concepts.setdefault(sid, set()).update(cids)
        for sid, cols in preview_set_to_columns.items():
            set_to_columns.setdefault(sid, set()).update(cols)
        for r in active_reports:
            for col in r.columns:
                if col.set_id is not None:
                    set_to_concepts.setdefault(col.set_id, set()).add(
                        r.concept_id
                    )
                    set_to_columns.setdefault(col.set_id, set()).add(
                        col.column_index
                    )

        def _sources_for_concepts(cids: Sequence[str]) -> list[str]:
            out: list[str] = []
            for cid in sorted(set(cids)):
                for ch_id in child_ids:
                    for fid in form_ids_by_child_concept.get((ch_id, cid), ()):
                        if fid not in out:
                            out.append(fid)
            return out

        node_call_ids = list(
            dict.fromkeys(
                cid
                for cid in (validation_call_id, resolved_preview_call_id)
                if cid
            )
        )
        node_defects: list[dict[str, Any]] = []

        # -------------------------------------------------------------------
        # Invariant 1: silent_residue_drop_truncation
        # -------------------------------------------------------------------
        if (
            residue_policy == "drop"
            and not is_identity_short_circuit
            and (
                (unaccounted_column_rate is not None and unaccounted_column_rate > 0.0)
                or len(completely_dropped_concepts) > 0
            )
        ):
            unacc_col_indices = sorted(
                {
                    col.column_index
                    for r in active_reports
                    for col in r.columns
                    if col.resolved_by == "residue_policy"
                }
                or {
                    idx
                    for sid in uncovered_set_ids
                    for idx in set_to_columns.get(sid, ())
                }
            )
            rate_val = float(unaccounted_column_rate or 0.0)
            col_detail = (
                f"{unaccounted_column_count}/{assembled_column_count} assembled columns; "
                if unaccounted_column_count is not None
                and assembled_column_count is not None
                else ""
            )
            concept_detail = (
                f", {uncovered_concept_count} uncovered/truncated concept(s)"
                if uncovered_concept_count is not None
                else ""
            )
            defect = {
                "category": DefectCategory.SILENT_RESIDUE_DROP_TRUNCATION.value,
                "node_id": node_id,
                "inventory_source": inventory_source,
                "summary": (
                    f"Node {node_id!r} ({inventory_source}) uses residue_policy='drop' "
                    f"with unaccounted_column_rate={rate_val:.4f} "
                    f"({col_detail}{uncovered_set_count} uncovered correspondence set(s)"
                    f"{concept_detail})."
                ),
                "residue_policy": residue_policy,
                "unaccounted_column_count": unaccounted_column_count,
                "assembled_column_count": assembled_column_count,
                "unaccounted_column_rate": rate_val,
                "uncovered_set_count": uncovered_set_count,
                "uncovered_concept_count": uncovered_concept_count,
                "completely_dropped_concept_ids": completely_dropped_concepts,
                "partially_truncated_concept_ids": partially_truncated_concepts,
                "call_ids": list(node_call_ids),
                "set_ids": uncovered_set_ids,
                "concept_ids": uncovered_concept_ids,
                "source_ids": _sources_for_concepts(uncovered_concept_ids),
                "column_indices": unacc_col_indices,
            }
            node_defects.append(defect)

        # -------------------------------------------------------------------
        # Invariant 2: uninspected_outgroup_citation (non-root nodes only!)
        # -------------------------------------------------------------------
        if (
            not is_root
            and len(ext_leaves) > 0
            and traj is not None
        ):
            def _outgroups_attesting_concept(cid: str) -> set[str]:
                attesting_ogs: set[str] = set()
                for og_var in ext_leaves:
                    if (og_var, cid) in topology.leaf_forms_by_variety_concept:
                        attesting_ogs.add(og_var)
                for og_int in ext_internal:
                    if og_int in steps_by_node:
                        if any(
                            d.concept_id == cid
                            for d in steps_by_node[
                                og_int
                            ].output_beam.distributions
                        ):
                            attesting_ogs.add(og_int)
                return attesting_ogs

            claim_outgroup_defect_emitted = False
            for cl in claims_to_audit:
                combined_text = (
                    f"{cl['rationale']} {cl['directionality_rationale']}".strip()
                )
                cites_og, named_ext = _text_cites_external_outgroup(
                    combined_text,
                    external_node_ids=ext_all_nodes,
                    own_clade_node_ids=own_clade_nodes,
                )
                if not cites_og:
                    continue

                sid = str(cl["set_id"])
                pat_id = str(cl.get("pattern_id") or "")
                ref_tuple = cl.get("reflexes")
                if (
                    sid in polarized_set_ids
                    or (pat_id and pat_id in polarized_set_ids)
                    or (
                        ref_tuple is not None
                        and ref_tuple in polarized_correspondences
                    )
                ):
                    continue

                cids = sorted(set_to_concepts.get(sid, set()))
                cids_with_og = [
                    cid for cid in cids if _outgroups_attesting_concept(cid)
                ]

                if cids:
                    if not cids_with_og:
                        # No external outgroup attests any concept in this set; only a defect
                        # if the session never inspected ANY outgroup at all yet claimed support.
                        is_uninspected = (
                            len(seen_outgroup_forms) == 0
                            and len(polarized_correspondences) == 0
                        )
                    else:
                        seen_any_for_claim = any(
                            seen_cid == cid
                            for cid in cids_with_og
                            for _og, seen_cid in seen_outgroup_forms
                        )
                        is_uninspected = not seen_any_for_claim
                else:
                    is_uninspected = (
                        len(seen_outgroup_forms) == 0
                        and len(polarized_correspondences) == 0
                    )

                if is_uninspected:
                    claim_outgroup_defect_emitted = True
                    og_source_ids: list[str] = []
                    for cid in cids_with_og:
                        for og_var in sorted(_outgroups_attesting_concept(cid)):
                            for lf in topology.leaf_forms_by_variety_concept.get(
                                (og_var, cid), ()
                            ):
                                if lf.form_id not in og_source_ids:
                                    og_source_ids.append(lf.form_id)
                    src_ids = _sources_for_concepts(cids) + og_source_ids
                    call_ptrs = list(node_call_ids)
                    node_defects.append(
                        {
                            "category": DefectCategory.UNINSPECTED_OUTGROUP_CITATION.value,
                            "node_id": node_id,
                            "inventory_source": inventory_source,
                            "summary": (
                                f"Claim {sid!r} on non-root node {node_id!r} cites external "
                                f"outgroup corroboration ({list(named_ext) if named_ext else ['outgroup']}), but "
                                "trajectory navigation (search_forms, get_alignments, polarize) "
                                f"never inspected outgroup forms for its concept(s) {cids}."
                            ),
                            "call_ids": call_ptrs,
                            "set_ids": [sid],
                            "concept_ids": cids,
                            "source_ids": src_ids,
                            "column_indices": sorted(
                                set_to_columns.get(sid, set())
                            ),
                        }
                    )

            if (
                not claim_outgroup_defect_emitted
                and node_summary_text
                and len(seen_outgroup_forms) == 0
                and len(polarized_correspondences) == 0
            ):
                cites_og, named_ext = _text_cites_external_outgroup(
                    node_summary_text,
                    external_node_ids=ext_all_nodes,
                    own_clade_node_ids=own_clade_nodes,
                )
                if cites_og:
                    node_defects.append(
                        {
                            "category": DefectCategory.UNINSPECTED_OUTGROUP_CITATION.value,
                            "node_id": node_id,
                            "inventory_source": inventory_source,
                            "summary": (
                                f"Summary on non-root node {node_id!r} cites external "
                                f"outgroup corroboration ({list(named_ext) if named_ext else ['outgroup']}) with "
                                "zero non-survey outgroup tool inspections in the trajectory."
                            ),
                            "call_ids": list(node_call_ids),
                            "set_ids": [],
                            "concept_ids": [],
                            "source_ids": [],
                            "column_indices": [],
                        }
                    )

        # -------------------------------------------------------------------
        # Invariant 3: unit_provenance_loss
        # -------------------------------------------------------------------
        if is_committed and step is not None:
            input_dists_by_concept: dict[str, list[tuple[str, Any]]] = {}
            for ib in step.input_beams:
                for dist in ib.distributions:
                    input_dists_by_concept.setdefault(
                        dist.concept_id, []
                    ).append((ib.node_id, dist))

            lost_provenance_concepts: list[str] = []
            for out_dist in step.output_beam.distributions:
                cid = out_dist.concept_id
                child_entries = input_dists_by_concept.get(cid, [])
                if not child_entries:
                    continue

                children_have_explicit_cog = True
                for ch_id, ch_dist in child_entries:
                    cands_with_analysis = [
                        c for c in ch_dist.candidates if c.analysis is not None
                    ]
                    if cands_with_analysis:
                        if not all(
                            _analysis_has_explicit_cognate_units(c.analysis)
                            for c in cands_with_analysis
                        ):
                            children_have_explicit_cog = False
                            break
                    elif (
                        ch_id,
                        cid,
                    ) in topology.leaf_forms_by_variety_concept:
                        leaf_forms = topology.leaf_forms_by_variety_concept[
                            (ch_id, cid)
                        ]
                        if not leaf_forms or not all(
                            all(
                                _analysis_has_explicit_cognate_units(sa)
                                for sa in source_analyses(lf)
                            )
                            for lf in leaf_forms
                        ):
                            children_have_explicit_cog = False
                            break
                    else:
                        children_have_explicit_cog = False
                        break

                if not children_have_explicit_cog:
                    continue

                if any(
                    _analysis_lost_unit_provenance(cand.analysis)
                    for cand in out_dist.candidates
                ):
                    lost_provenance_concepts.append(cid)

            if lost_provenance_concepts:
                lost_cids = sorted(set(lost_provenance_concepts))
                affected_sets = sorted(
                    {
                        col.set_id
                        for r in active_reports
                        if r.concept_id in set(lost_cids)
                        for col in r.columns
                        if col.set_id is not None
                    }
                )
                node_defects.append(
                    {
                        "category": DefectCategory.UNIT_PROVENANCE_LOSS.value,
                        "node_id": node_id,
                        "inventory_source": inventory_source,
                        "summary": (
                            f"Assembled output_beam at node {node_id!r} loses explicit "
                            f"cog:* FormAnalysis provenance (emitting whole:unknown or "
                            f"missing cognate_set_id) across {len(lost_cids)} concept(s) "
                            "whose active child inputs carried explicit cog:* memberships."
                        ),
                        "call_ids": (
                            [validation_call_id] if validation_call_id else []
                        ),
                        "set_ids": affected_sets,
                        "concept_ids": lost_cids,
                        "source_ids": _sources_for_concepts(lost_cids),
                        "column_indices": [],
                    }
                )

        # -------------------------------------------------------------------
        # Invariant 4: identity_confidence_length_bias
        # -------------------------------------------------------------------
        if (
            is_committed
            and step is not None
            and isinstance(committed_obj, CommittedProtoInventory)
        ):
            biased_identity_claims = [
                c
                for c in committed_obj.request.commitments
                if len(c.reflexes) >= 2
                and None not in c.reflexes
                and len(set(c.reflexes)) == 1
                and c.proto_segment == c.reflexes[0]
                and c.confidence < 1.0
            ]
            unequal_length_dists = [
                d
                for d in step.output_beam.distributions
                if len(d.candidates) >= 2
                and len({len(cand.segments) for cand in d.candidates}) > 1
                and len(
                    {round(float(cand.probability), 6) for cand in d.candidates}
                )
                > 1
            ]
            if biased_identity_claims and unequal_length_dists:
                biased_sids = [c.set_id for c in biased_identity_claims]
                biased_cids = sorted(d.concept_id for d in unequal_length_dists)
                biased_cols = sorted(
                    {
                        col.column_index
                        for r in active_reports
                        if r.concept_id in set(biased_cids)
                        for col in r.columns
                        if col.set_id in set(biased_sids)
                    }
                )
                min_conf = min(c.confidence for c in biased_identity_claims)
                node_defects.append(
                    {
                        "category": DefectCategory.IDENTITY_CONFIDENCE_LENGTH_BIAS.value,
                        "node_id": node_id,
                        "inventory_source": inventory_source,
                        "summary": (
                            f"Node {node_id!r} commits {len(biased_identity_claims)} unanimous "
                            f"identity correspondence(s) at confidence < 1.0 (min={min_conf:.2f}) "
                            f"while output_beam has {len(biased_cids)} competing multi-candidate "
                            f"distribution(s) of unequal segment length ({biased_cids}), "
                            "biasing log-mass against longer candidates."
                        ),
                        "call_ids": (
                            [validation_call_id] if validation_call_id else []
                        ),
                        "set_ids": biased_sids,
                        "concept_ids": biased_cids,
                        "source_ids": _sources_for_concepts(biased_cids),
                        "column_indices": biased_cols,
                    }
                )

        # -------------------------------------------------------------------
        # Invariant 5: upstream_tie_collapse_majority
        # -------------------------------------------------------------------
        if active_reports and claims_to_audit and child_ids:
            parent_claims_by_set = {
                str(cl["set_id"]): cl for cl in claims_to_audit
            }
            for child_idx, ch_id in enumerate(child_ids):
                ch_step = steps_by_node.get(ch_id)
                if ch_step is None or ch_step.diagnostics.failure_fallback:
                    continue
                ch_claims = committed_claims_by_node.get(ch_id, {})
                ch_val_call = validation_call_by_node.get(ch_id)

                # Prefer the beam parent actually consumed for `ch_id`
                ch_beam = (
                    step.input_beams[child_idx]
                    if (
                        step is not None
                        and child_idx < len(step.input_beams)
                        and step.input_beams[child_idx].node_id == ch_id
                    )
                    else ch_step.output_beam
                )
                ch_dist_by_cid = {
                    d.concept_id: d for d in ch_beam.distributions
                }
                ch_rep_by_cid = {
                    r.concept_id: r for r in ch_step.assembly_reports
                }

                for p_rep in active_reports:
                    cid = p_rep.concept_id
                    ch_dist = ch_dist_by_cid.get(cid)
                    if ch_dist is None or len(ch_dist.candidates) != 1:
                        # Either child does not attest cid or tied-beam expansion retained >=2 candidates
                        continue

                    ch_rep = ch_rep_by_cid.get(cid)
                    tied_child_cols: list[Any] = []
                    if ch_rep is not None:
                        for c_col in ch_rep.columns:
                            c_claim = (
                                ch_claims.get(c_col.set_id)
                                if c_col.set_id is not None
                                else None
                            )
                            is_low_conf_tie = (
                                c_claim is not None
                                and float(c_claim["confidence"]) <= 0.50
                                and len(set(c_col.reflexes)) > 1
                            )
                            is_tie_broken_col = bool(
                                c_col.decided_by_equal_confidence
                                or c_col.competing_set_ids
                            )
                            if is_low_conf_tie or is_tie_broken_col:
                                tied_child_cols.append(c_col)

                    ch_dist_tie_broken = decided_by_tie_break(ch_dist) or (
                        ch_dist.pre_prune_candidate_count is not None
                        and ch_dist.pre_prune_candidate_count > 1
                        and (ch_step.diagnostics.tie_broken_concept_count or 0)
                        > 0
                    )
                    if not tied_child_cols and not ch_dist_tie_broken:
                        continue

                    attesting_indices = [
                        i
                        for i, cid_child in enumerate(child_ids)
                        if cid_child in attesting_by_concept.get(cid, set())
                    ]
                    if len(attesting_indices) < 2:
                        continue

                    for p_col in p_rep.columns:
                        if p_col.set_id is None:
                            continue
                        p_claim = parent_claims_by_set.get(p_col.set_id)
                        if (
                            p_claim is None
                            or float(p_claim["confidence"]) <= 0.50
                        ):
                            continue
                        attesting_reflexes = {
                            p_col.reflexes[i]
                            for i in attesting_indices
                            if i < len(p_col.reflexes)
                        }
                        if len(attesting_reflexes) <= 1:
                            continue

                        matched_child_cols = [
                            c_col
                            for c_col in tied_child_cols
                            if (
                                p_col.unit_id is None
                                or c_col.unit_id is None
                                or p_col.unit_id == c_col.unit_id
                            )
                            and child_idx < len(p_col.reflexes)
                            and p_col.reflexes[child_idx] == c_col.proto_segment
                        ]
                        if not matched_child_cols and not (
                            not tied_child_cols and ch_dist_tie_broken
                        ):
                            continue

                        call_ptrs = [
                            x
                            for x in (validation_call_id, ch_val_call)
                            if x is not None
                        ]
                        set_ptrs = [p_col.set_id] + [
                            c_col.set_id
                            for c_col in matched_child_cols
                            if c_col.set_id is not None
                            and c_col.set_id != p_col.set_id
                        ]
                        node_defects.append(
                            {
                                "category": DefectCategory.UPSTREAM_TIE_COLLAPSE_MAJORITY.value,
                                "node_id": node_id,
                                "upstream_child_node_id": ch_id,
                                "inventory_source": inventory_source,
                                "summary": (
                                    f"Parent claim {p_col.set_id!r} on node {node_id!r} "
                                    f"(concept {cid!r}, confidence={float(p_claim['confidence']):.2f} > 0.50) "
                                    f"depends on active child {ch_id!r}'s single-winner collapsed tie "
                                    "(committed at confidence <= 0.50 or tie-broken without tied-beam expansion)."
                                ),
                                "call_ids": call_ptrs,
                                "set_ids": set_ptrs,
                                "concept_ids": [cid],
                                "source_ids": _sources_for_concepts([cid]),
                                "column_indices": [p_col.column_index],
                            }
                        )

        for d in node_defects:
            defect_counts_by_category[d["category"]] += 1
            all_defects.append(d)

        nodes_report[node_id] = {
            "node_id": node_id,
            "is_root": is_root,
            "committed": is_committed,
            "failure_fallback": is_fallback,
            "inventory_source": inventory_source,
            "residue_policy": residue_policy,
            "unaccounted_column_count": unaccounted_column_count,
            "assembled_column_count": assembled_column_count,
            "unaccounted_column_rate": unaccounted_column_rate,
            "uncovered_set_count": uncovered_set_count,
            "uncovered_concept_count": uncovered_concept_count,
            "defect_count": len(node_defects),
            "defects": node_defects,
        }

    return {
        "evaluator_version": CRITIC_EVALUATOR_VERSION,
        "audit_mode": REAL_RUN_AUDIT_MODE,
        "run_dir": str(directory),
        "run_id": artifact_run_id,
        "run_status": run_status,
        "root_node_id": topology.root_node_id,
        "nodes_audited": nodes_audited,
        "unattempted_nodes": unattempted_nodes,
        "fallback_node_ids": sorted(fallback_nodes),
        "total_defect_count": len(all_defects),
        "defect_counts_by_category": defect_counts_by_category,
        "nodes": nodes_report,
        "defects": all_defects,
    }


__all__ = [
    "CRITIC_CORPUS_VERSION",
    "CRITIC_EVALUATOR_VERSION",
    "CRITIC_TOOL_NAME",
    "DEFAULT_CRITIC_MODE",
    "REAL_RUN_AUDIT_MODE",
    "REAL_RUN_DEFECT_CATEGORIES",
    "CriticAssessment",
    "CritiqueClaimRecord",
    "CritiqueEvidenceBundle",
    "CritiquePacket",
    "CritiqueVerdict",
    "DefectCategory",
    "EvidenceChannel",
    "ExpectedCritiqueGroundTruth",
    "FakeCriticProvider",
    "UncertaintyLabel",
    "audit_run_directory",
    "build_blind_evaluation_sheet",
    "build_critic_user_prompt",
    "critic_system_instructions",
    "critic_tool_definition",
    "evaluate_forward_revision_on_packet",
    "filter_llm_assessment_with_deterministic_guard",
    "parse_critic_response",
    "resolve_audit_payload",
    "run_default_critic_report",
    "run_default_hypothesis_critic",
    "run_deterministic_full_detector",
    "run_deterministic_mechanical_detector",
    "run_existing_residue_ambiguity_baseline",
    "run_fixed_evidence_checklist_baseline",
    "run_llm_critic_on_packet",
    "run_llm_critic_on_packets",
    "score_critic_assessments",
    "to_model_visible_packet",
    "verify_no_critic_leakage",
]
