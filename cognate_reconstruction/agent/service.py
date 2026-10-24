"""High-level family inference results built on deterministic traversal."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence

from cognate_reconstruction.agent.reconstructor import AgenticNodeReconstructor
from cognate_reconstruction.agent.orchestrator import failed_node_trajectory, RunCancelled
from cognate_reconstruction.agent.providers import ProviderError
from cognate_reconstruction.agent.events import AgentEventKind
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
    lifecycle_summary: dict | None = None


def _best_lexicon(beam: NodeBeamState) -> LanguageLexicon:
    """The top candidate per concept, with its analysis carried as-is.

    Built like `traversal.beam.beam_to_lexicon`, restricted to the first
    candidate. The analysis is copied, never re-derived from the spelling, so
    pieces the beam left unknown stay unknown here.
    """
    return LanguageLexicon(
        variety_id=beam.node_id,
        name=beam.node_id,
        forms=tuple(
            LexicalForm(
                form_id=distribution.candidates[0].candidate_id,
                variety_id=beam.node_id,
                concept_id=distribution.concept_id,
                segments=distribution.candidates[0].segments,
                analysis=distribution.candidates[0].analysis,
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
        self.last_run_summary: dict | None = None

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
        self.last_run_summary = None
        self.reconstructor.clear_run_results()
        self.reconstructor.seed_prior_reconstructions(seed_trajectories)
        active_anchors = _merge_node_forms(
            _forms_by_node(
                dataset.historical_form_bindings,
                HistoricalFormRole.ANCHOR,
            ),
            anchors_by_node,
        )
        partial_steps = []
        planned_payload = WorkbenchPayload(
            lexicons=dataset.lexicons, newick=dataset.tree.newick,
            historical_form_bindings=dataset.historical_form_bindings,
        )
        try:
            snapshot = TreeTraverser(
                beam_width=self.beam_width, reconstructor=self.reconstructor,
            ).traverse(
                dataset, anchors_by_node=active_anchors,
                resume_steps=resume_steps, on_step_complete=on_step_complete,
                on_step_recorded=partial_steps.append,
            )
        except (Exception, KeyboardInterrupt) as caught:
            error = RunCancelled("run cancelled by keyboard interrupt") if isinstance(caught, KeyboardInterrupt) else caught
            failed = failed_node_trajectory(error)
            trajectories = list(seed_trajectories) + self.reconstructor.trajectories
            if failed is not None and failed not in trajectories:
                trajectories.append(failed)
            reason = error.stop_reason if isinstance(error, ProviderError) else str(error)
            partial = {"status": "interrupted", "interruption_reason": reason,
                       "snapshot": {"steps": partial_steps},
                       "node_failures": [f.model_dump(mode="json") for f in self.reconstructor.node_failures]}
            report = evaluate_run(planned_payload, partial, trajectories)
            self.last_run_summary = self._lifecycle_summary(
                report, trajectories, restored=resume_steps or {}, error=error,
            )
            # Preserve realized fallback outputs as such, too, without inventing
            # a full result or steps for unattempted nodes.
            self.last_run_summary["snapshot"] = {
                "steps": [step.model_dump(mode="json", exclude_computed_fields=True) for step in partial_steps]
            }
            self.last_run_summary["node_failures"] = partial["node_failures"]
            self.reconstructor.orchestrator._emit(
                AgentEventKind.RUN_INTERRUPTED, failed.node_id if failed else "run",
                "run interrupted; completed-node progress retained",
                **{k: v for k, v in self.last_run_summary.items() if k not in {"snapshot", "evaluation_report"}},
            )
            raise error
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
            (*seed_trajectories, *self.reconstructor.trajectories),
        )
        target_evaluations = tuple(t.evaluation for t in evaluation_report.targets)
        all_trajectories = tuple(seed_trajectories) + tuple(self.reconstructor.trajectories)
        self.last_run_summary = self._lifecycle_summary(
            evaluation_report, all_trajectories, restored=resume_steps or {},
        )
        return FamilyReconstructionResult(
            snapshot=snapshot,
            internal_nodes=internal_nodes,
            trajectories=all_trajectories,
            historical_target_evaluations=target_evaluations,
            node_failures=node_failures,
            evaluation_report=evaluation_report,
            lifecycle_summary=self.last_run_summary,
        )

    def _lifecycle_summary(self, report, trajectories, *, restored, error=None):
        orchestrator = self.reconstructor.orchestrator
        metadata = error.metadata if isinstance(error, ProviderError) else None
        attempted = sorted(set(report.attempted_node_ids) | set(restored))
        return {
            "recovery_version": "provider-recovery-v1", "run_id": orchestrator.run_id,
            "configuration_sha256": orchestrator.configuration_sha256,
            "status": "interrupted" if error else report.run_status,
            "complete": error is None,
            "failure_kind": metadata.kind.value if metadata else (getattr(error, "failure_kind", None) or "unknown") if error else None,
            "failure_error_type": type(error).__name__ if error else None,
            "interruption_reason": error.stop_reason if metadata else str(error) if error else None,
            "provider_failure": metadata.model_dump(mode="json") if metadata else None,
            "planned_node_ids": [n.node_id for n in report.operational_nodes],
            "attempted_node_ids": attempted,
            "active_trajectory_ids": [t.trajectory_id for t in trajectories],
            "completed_node_ids": list(report.completed_node_ids),
            "restored_node_ids": sorted(restored),
            "unattempted_node_ids": sorted(set(n.node_id for n in report.operational_nodes) - set(attempted)),
            "fallback_node_ids": [n.node_id for n in report.operational_nodes if n.status == "identity_fallback"],
            "missing_evaluation_outputs": report.raw_target_summary.missing_outputs,
            "evaluation_report": report.model_dump(mode="json"),
            "usage": orchestrator.usage_snapshot(),
            "retry_settings": {
                "max_retries": orchestrator.max_retries,
                "retry_backoff_seconds": orchestrator.retry_backoff_seconds,
                "max_retry_seconds": orchestrator.max_retry_seconds,
                "retry_max_delay_seconds": orchestrator.retry_max_delay_seconds,
            },
            "resume_boundary": "completed_nodes_only; interrupted node restarts from its initial context",
        }
