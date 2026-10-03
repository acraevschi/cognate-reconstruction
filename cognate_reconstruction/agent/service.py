"""High-level family inference results built on deterministic traversal."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence

from cognate_reconstruction.agent.reconstructor import AgenticNodeReconstructor
from cognate_reconstruction.agent.trajectory import AgentTrajectory
from cognate_reconstruction.evaluation.targets import _evaluate_target
from cognate_reconstruction.evaluation.run import evaluate_run
from cognate_reconstruction.schemas.evaluation import RunEvaluationReport
from cognate_reconstruction.schemas.beam import NodeBeamState
from cognate_reconstruction.schemas.common import NonEmptyStr, WorkbenchModel
from cognate_reconstruction.schemas.ingestion import IngestedDataset, WorkbenchPayload
from cognate_reconstruction.schemas.historical import (
    HistoricalFormBinding,
    HistoricalFormRole,
    HistoricalTargetEvaluation,
)
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
    evaluation_report: RunEvaluationReport | None = None


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
        # Every target binding is evaluated, not only the first: a dataset that
        # supplies proto-forms for intermediate nodes as well as the root gets a
        # score at each of them. A node whose session failed still has a beam —
        # the identity fallback — so it still produces an evaluation, and that
        # evaluation is marked `failure_fallback` rather than being silently
        # counted as a reconstruction.
        evaluation_report = evaluate_run(
            WorkbenchPayload(
                lexicons=dataset.lexicons, newick=dataset.tree.newick,
                historical_form_bindings=dataset.historical_form_bindings,
            ),
            {"snapshot": {"steps": snapshot.steps},
             "node_failures": [f.model_dump(mode="json") for f in node_failures]},
            self.reconstructor.trajectories,
        )
        target_evaluations = tuple(t.evaluation for t in evaluation_report.targets)
        return FamilyReconstructionResult(
            snapshot=snapshot,
            internal_nodes=internal_nodes,
            trajectories=tuple(self.reconstructor.trajectories),
            historical_target_evaluations=target_evaluations,
            node_failures=node_failures,
            evaluation_report=evaluation_report,
        )
