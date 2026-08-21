"""High-level family inference results built on deterministic traversal."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence

from cognate_reconstruction.agent.reconstructor import AgenticNodeReconstructor
from cognate_reconstruction.agent.trajectory import AgentTrajectory
from cognate_reconstruction.evaluation.metrics import compare_to_nearest
from cognate_reconstruction.schemas.beam import NodeBeamState
from cognate_reconstruction.schemas.common import NonEmptyStr, WorkbenchModel
from cognate_reconstruction.schemas.ingestion import IngestedDataset
from cognate_reconstruction.schemas.historical import (
    GradedTargetMetrics,
    HistoricalFormBinding,
    HistoricalFormRole,
    HistoricalTargetEvaluation,
    TargetConceptEvaluation,
)
from cognate_reconstruction.schemas.metrics import MetricDistribution
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm
from cognate_reconstruction.schemas.traversal import TraversalSnapshot
from cognate_reconstruction.schemas.traversal import (
    NodeFailureRecord,
    ReconstructionStep,
)
from cognate_reconstruction.traversal.traverser import TreeTraverser


class InternalNodeVocabulary(WorkbenchModel):
    node_id: NonEmptyStr
    best_lexicon: LanguageLexicon
    beam: NodeBeamState


class FamilyReconstructionResult(WorkbenchModel):
    snapshot: TraversalSnapshot
    internal_nodes: tuple[InternalNodeVocabulary, ...]
    trajectories: tuple[AgentTrajectory, ...]
    historical_target_evaluations: tuple[HistoricalTargetEvaluation, ...] = ()
    node_failures: tuple[NodeFailureRecord, ...] = ()
    """Nodes whose session failed and whose parent is an identity fallback.

    Defaulted empty so results written before the fallback existed still load.
    The corresponding steps carry `diagnostics.failure_fallback`, so a reader
    that only has the snapshot can still tell them apart; this is where the
    reason and the failed trajectory's ID live.
    """


def _best_lexicon(beam: NodeBeamState) -> LanguageLexicon:
    return LanguageLexicon(
        variety_id=beam.node_id,
        name=beam.node_id,
        forms=tuple(
            LexicalForm(
                form_id=distribution.candidates[0].candidate_id,
                variety_id=beam.node_id,
                concept_id=distribution.concept_id,
                segments=distribution.candidates[0].segments,
            )
            for distribution in beam.distributions
        ),
    )


def _forms_by_node(
    bindings: Sequence[HistoricalFormBinding],
    role: HistoricalFormRole,
) -> dict[str, tuple[LexicalForm, ...]]:
    grouped: dict[str, list[LexicalForm]] = defaultdict(list)
    for binding in bindings:
        if binding.role is role:
            grouped[binding.node_id].extend(binding.forms)
    return {node_id: tuple(forms) for node_id, forms in grouped.items()}


def _merge_node_forms(
    embedded: Mapping[str, Sequence[LexicalForm]],
    supplied: Mapping[str, Sequence[LexicalForm]] | None,
) -> dict[str, tuple[LexicalForm, ...]]:
    merged = {
        node_id: list(forms) for node_id, forms in embedded.items()
    }
    for node_id, forms in (supplied or {}).items():
        merged.setdefault(node_id, []).extend(forms)
    seen: set[str] = set()
    for node_id, forms in merged.items():
        for form in forms:
            if form.variety_id != node_id:
                raise ValueError(
                    f"form {form.form_id!r} is bound to node {node_id!r} but "
                    f"uses variety_id {form.variety_id!r}"
                )
            if form.form_id in seen:
                raise ValueError(
                    f"anchor form ID {form.form_id!r} is duplicated across "
                    "embedded and external inputs"
                )
            seen.add(form.form_id)
    return {node_id: tuple(forms) for node_id, forms in merged.items()}


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
    step: ReconstructionStep,
) -> HistoricalTargetEvaluation:
    target_by_concept: dict[str, list[LexicalForm]] = defaultdict(list)
    for form in binding.forms:
        target_by_concept[form.concept_id].append(form)
    distributions = {
        distribution.concept_id: distribution
        for distribution in step.output_beam.distributions
    }
    concepts = []
    missing = top_matches = beam_matches = 0
    for concept_id, forms in sorted(target_by_concept.items()):
        alternatives = tuple(dict.fromkeys(form.segments for form in forms))
        distribution = distributions.get(concept_id)
        graded: dict[str, object] = {}
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
                **graded,
            )
        )
    denominator = len(concepts)
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
        failure_fallback=step.diagnostics.failure_fallback,
        graded=_graded_metrics(concepts),
    )


class ReconstructionService:
    """Reconstruct every internal vocabulary and return audit/training artifacts."""

    def __init__(
        self,
        reconstructor: AgenticNodeReconstructor,
    ) -> None:
        self.reconstructor = reconstructor
        self.beam_width = reconstructor.deterministic.beam_width

    def reconstruct_family(
        self,
        dataset: IngestedDataset,
        *,
        anchors_by_node: Mapping[str, Sequence[LexicalForm]] | None = None,
        resume_steps: Mapping[str, ReconstructionStep] | None = None,
        seed_trajectories: Sequence[AgentTrajectory] = (),
        on_step_complete: Callable[[ReconstructionStep], None] | None = None,
    ) -> FamilyReconstructionResult:
        # Seeds are taken here rather than set by the caller beforehand:
        # `clear_run_results` wipes prior hypotheses, so anything seeded ahead
        # of this call would vanish without a trace.
        self.reconstructor.clear_run_results()
        self.reconstructor.seed_prior_reconstructions(seed_trajectories)
        active_anchors = _merge_node_forms(
            _forms_by_node(
                dataset.historical_form_bindings,
                HistoricalFormRole.ANCHOR,
            ),
            anchors_by_node,
        )
        snapshot = TreeTraverser(
            beam_width=self.beam_width,
            reconstructor=self.reconstructor,
        ).traverse(
            dataset,
            anchors_by_node=active_anchors,
            resume_steps=resume_steps,
            on_step_complete=on_step_complete,
        )
        internal_nodes = tuple(
            InternalNodeVocabulary(
                node_id=step.parent_node_id,
                best_lexicon=_best_lexicon(step.output_beam),
                beam=step.output_beam,
            )
            for step in snapshot.steps
        )
        # A fallback node still has a beam — that is the point of it — so it is
        # still an internal node here. What separates it from a reconstruction
        # is the step's `failure_fallback` flag and this list.
        node_failures = tuple(self.reconstructor.node_failures)
        steps_by_node = {
            step.parent_node_id: step for step in snapshot.steps
        }
        # Every target binding is evaluated, not only the first: a dataset that
        # supplies proto-forms for intermediate nodes as well as the root gets a
        # score at each of them. A node whose session failed still has a beam —
        # the identity fallback — so it still produces an evaluation, and that
        # evaluation is marked `failure_fallback` rather than being silently
        # counted as a reconstruction.
        target_evaluations = tuple(
            _evaluate_target(binding, steps_by_node[binding.node_id])
            for binding in dataset.historical_form_bindings
            if binding.role is HistoricalFormRole.TARGET
            and binding.node_id in steps_by_node
        )
        return FamilyReconstructionResult(
            snapshot=snapshot,
            internal_nodes=internal_nodes,
            trajectories=tuple(self.reconstructor.trajectories),
            historical_target_evaluations=target_evaluations,
            node_failures=node_failures,
        )
