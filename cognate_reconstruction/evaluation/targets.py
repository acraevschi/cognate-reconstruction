"""Versioned, report-only comparisons. Gold is consumed only after inference."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from cognate_reconstruction.evaluation.metrics import compare_to_nearest
from cognate_reconstruction.evaluation.diagnostics import token_diagnostics, with_unit_diagnostics
from cognate_reconstruction.schemas.historical import (
    GradedTargetMetrics, HistoricalFormBinding, HistoricalTargetEvaluation,
    TargetConceptEvaluation, TargetValidity, SelectionEvaluation,
)
from cognate_reconstruction.schemas.metrics import MetricDistribution
from cognate_reconstruction.schemas.lexicon import LexicalForm, LanguageLexicon
from cognate_reconstruction.schemas.traversal import ReconstructionStep

EVALUATOR_VERSION = "task02-v1"

# Explicit migration of one known legacy binding; never interpret reference prose.
LEGACY_BINDINGS = {
    ("burmic", "hillburmish:OldBurmese"): (
        TargetValidity.PROVISIONAL_PROXY,
        "Old Burmese is ancestral to Burmese only, not Achang or Xiandao; "
        "legacy exact-identity annotation; raw scores retained.",
    ),
}

def binding_validity(node_id, source_variety_id, declared=None, note=None):
    if declared is not None:
        return declared, note
    return LEGACY_BINDINGS.get((node_id, source_variety_id), (None, note))

def _graded_metrics(
    concepts: Sequence[TargetConceptEvaluation],
) -> GradedTargetMetrics:
    """Summarize the graded per-concept scores, means beside their spread.

    Concepts with no reconstruction at all are skipped rather than scored as
    maximally wrong: a missing form is a coverage fact, already counted by
    `missing_reconstruction_concepts`, and folding it in as NED 1.0 would let a
    node improve its distance by producing fewer forms.
    """
    top_ned = [
        concept.top_normalized_edit_distance
        for concept in concepts
        if concept.top_normalized_edit_distance is not None
    ]
    beam_ned = [
        concept.beam_best_normalized_edit_distance
        for concept in concepts
        if concept.beam_best_normalized_edit_distance is not None
    ]
    gap = None
    if top_ned and beam_ned:
        gap = max(
            0.0,
            sum(top_ned) / len(top_ned) - sum(beam_ned) / len(beam_ned),
        )
    return GradedTargetMetrics(
        top_edit_distance=MetricDistribution.of(
            [
                concept.top_edit_distance
                for concept in concepts
                if concept.top_edit_distance is not None
            ]
        ),
        top_normalized_edit_distance=MetricDistribution.of(top_ned),
        beam_best_normalized_edit_distance=MetricDistribution.of(beam_ned),
        top_bcubed_f1=MetricDistribution.of(
            [
                concept.top_bcubed_f1
                for concept in concepts
                if concept.top_bcubed_f1 is not None
            ]
        ),
        normalized_edit_distance_selection_gap=gap,
    )


def _evaluate_target(
    binding: HistoricalFormBinding,
    step: ReconstructionStep | None,
    *,
    observed_lexicons: Sequence[LanguageLexicon] | None = None,
    model_committed: bool | None = None,
    descendant_fallback_node_ids: tuple[str, ...] | None = None,
) -> HistoricalTargetEvaluation:
    target_by_concept: dict[str, list[LexicalForm]] = defaultdict(list)
    for form in binding.forms:
        target_by_concept[form.concept_id].append(form)
    distributions = {
        distribution.concept_id: distribution
        for distribution in (step.output_beam.distributions if step else ())
    }
    concepts = []
    missing = top_matches = beam_matches = 0
    for concept_id, forms in sorted(target_by_concept.items()):
        alternatives = tuple(dict.fromkeys(form.segments for form in forms))
        distribution = distributions.get(concept_id)
        graded: dict[str, object] = {}
        top = None
        if distribution is None or not distribution.candidates:
            missing += 1
            top_id = None
            top_segments = None
            top_exact = beam_exact = False
        else:
            top = distribution.candidates[0]
            top_id = top.candidate_id
            top_segments = top.segments
            top_exact = top.segments in alternatives
            beam_exact = any(
                candidate.segments in alternatives
                for candidate in distribution.candidates
            )
            comparison = compare_to_nearest(top.segments, alternatives)
            # Which retained candidate came closest, not merely whether one was
            # exact. Ties go to the earlier candidate, which is the higher-mass
            # one, so the reported best is the one the beam ranked highest among
            # equally close candidates.
            best_candidate, best_comparison = min(
                (
                    (candidate, compare_to_nearest(candidate.segments, alternatives))
                    for candidate in distribution.candidates
                ),
                key=lambda item: item[1].normalized_edit_distance,
            )
            graded = {
                "nearest_target_segments": comparison.nearest_target,
                "top_edit_distance": comparison.edit_distance,
                "top_normalized_edit_distance": comparison.normalized_edit_distance,
                "top_bcubed_precision": comparison.bcubed_precision,
                "top_bcubed_recall": comparison.bcubed_recall,
                "top_bcubed_f1": comparison.bcubed_f1,
                "beam_best_candidate_id": best_candidate.candidate_id,
                "beam_best_candidate_segments": best_candidate.segments,
                "beam_best_edit_distance": best_comparison.edit_distance,
                "beam_best_normalized_edit_distance": (
                    best_comparison.normalized_edit_distance
                ),
            }
        top_matches += top_exact
        beam_matches += beam_exact
        concepts.append(
            TargetConceptEvaluation(
                concept_id=concept_id,
                target_form_ids=tuple(form.form_id for form in forms),
                target_segment_alternatives=alternatives,
                top_candidate_id=top_id,
                top_candidate_segments=top_segments,
                top_exact_match=top_exact,
                beam_exact_match=beam_exact,
                token_diagnostics=with_unit_diagnostics(token_diagnostics(
                    top_segments, alternatives,
                    unresolved_scope=(binding.source_variety_id == "hillburmish:ProtoBurmish"
                                      and concept_id == "406"),
                ), top, forms),
                **graded,
            )
        )
    denominator = len(concepts)
    selection = None
    if observed_lexicons is not None:
        observed: dict[str, set[tuple[str, ...]]] = defaultdict(set)
        for lexicon in observed_lexicons:
            for form in lexicon.forms:
                observed[form.concept_id].add(form.segments)
        eligible = tuple(c.concept_id for c in concepts if observed[c.concept_id])
        reachable = tuple(c.concept_id for c in concepts
                          if observed[c.concept_id].intersection(c.target_segment_alternatives))
        outside_top = tuple(c.concept_id for c in concepts
                            if c.concept_id in eligible and c.concept_id not in reachable
                            and c.top_exact_match)
        outside_beam = tuple(c.concept_id for c in concepts
                             if c.concept_id in eligible and c.concept_id not in reachable
                             and c.beam_exact_match)
        selection = SelectionEvaluation(
            eligible_concept_ids=eligible, oracle_reachable_concept_ids=reachable,
            outside_selection_top_hit_ids=outside_top,
            outside_selection_beam_hit_ids=outside_beam,
            eligible_concepts=len(eligible), oracle_reachable_concepts=len(reachable),
            outside_selection_top_hits=len(outside_top), outside_selection_beam_hits=len(outside_beam),
        )
    validity, validity_note = binding_validity(
        binding.node_id, binding.source_variety_id,
        binding.target_validity, binding.target_validity_note,
    )
    return HistoricalTargetEvaluation(
        node_id=binding.node_id,
        source_variety_id=binding.source_variety_id,
        source_reference=binding.source_reference,
        target_form_count=len(binding.forms),
        evaluated_concepts=denominator,
        missing_reconstruction_concepts=missing,
        top_exact_matches=top_matches,
        beam_exact_matches=beam_matches,
        top_exact_rate=top_matches / denominator if denominator else 0.0,
        beam_exact_rate=beam_matches / denominator if denominator else 0.0,
        concepts=tuple(concepts),
        gold_evidence_kind=binding.gold_evidence_kind,
        failure_fallback=step.diagnostics.failure_fallback if step else False,
        graded=_graded_metrics(concepts),
        evaluator_version=EVALUATOR_VERSION,
        target_validity=validity, target_validity_note=validity_note,
        model_committed=model_committed,
        descendant_fallback_node_ids=descendant_fallback_node_ids,
        selection=selection,
    )
