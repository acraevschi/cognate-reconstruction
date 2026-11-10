"""Source-linked hypothesis critic and evaluation prototype (R07).

Provides strict schemas, evidence-boundary sanitization, leakage verification,
executable forward-revision integration, surface/mechanical baselines, an LLM
critic prompt/tool interface, deterministic scripted providers for offline
testing, pointer-grounded scoring, and a blinded human evaluation form builder.
"""

from __future__ import annotations

import json
import random
from collections.abc import Mapping, Sequence
from enum import StrEnum
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

CRITIC_EVALUATOR_VERSION = "r07-critic-v1"
CRITIC_CORPUS_VERSION = "r07-critic-corpus-v1"
CRITIC_TOOL_NAME = "submit_hypothesis_critique"
DEFAULT_CRITIC_MODE: Literal["deterministic_full"] = "deterministic_full"


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


__all__ = [
    "CRITIC_CORPUS_VERSION",
    "CRITIC_EVALUATOR_VERSION",
    "CRITIC_TOOL_NAME",
    "DEFAULT_CRITIC_MODE",
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
    "build_blind_evaluation_sheet",
    "build_critic_user_prompt",
    "critic_system_instructions",
    "critic_tool_definition",
    "evaluate_forward_revision_on_packet",
    "filter_llm_assessment_with_deterministic_guard",
    "parse_critic_response",
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
