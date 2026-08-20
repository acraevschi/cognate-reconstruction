"""Agentic NodeReconstructor wrapper keeping the deterministic core LLM-free."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.orchestrator import (
    AgentOrchestrator,
    RunBudgetExceeded,
    failed_node_trajectory,
)
from cognate_reconstruction.agent.schemas import PriorNodeReconstruction
from cognate_reconstruction.agent.tools import summarize_commit
from cognate_reconstruction.agent.trajectory import AgentRunResult, AgentTrajectory
from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.alignment.protocol import AlignmentProvider
from cognate_reconstruction.schemas.beam import NodeBeamState
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm
from cognate_reconstruction.schemas.rules import (
    AnomalyReport,
    ParsedSoundRule,
    ReconstructionRule,
)
from cognate_reconstruction.schemas.traversal import EvidenceKind, ReconstructionStep
from cognate_reconstruction.schemas.traversal import (
    NodeFailureRecord,
    NodeReconstructionContext,
)
from cognate_reconstruction.traversal.beam import beam_to_lexicon
from cognate_reconstruction.traversal.reconstructor import RuleBasedReconstructor


def _apply_overlay(
    beam: NodeBeamState,
    context: AgentContext,
    overlay_id: str | None,
) -> NodeBeamState:
    if overlay_id is None:
        return beam
    original = context.lexicon(beam.node_id)
    overlaid = context.lexicon(beam.node_id, overlay_id)
    overlaid_by_id = {form.form_id: form for form in overlaid.forms}
    distributions = tuple(
        distribution.model_copy(
            update={
                "candidates": tuple(
                    candidate.model_copy(
                        update={
                            "segments": _overlay_candidate_segments(
                                distribution.concept_id,
                                candidate.candidate_id,
                                candidate.segments,
                                original,
                                overlaid_by_id,
                            )
                        }
                    )
                    for candidate in distribution.candidates
                )
            }
        )
        for distribution in beam.distributions
    )
    return beam.model_copy(update={"distributions": distributions})


def _overlay_candidate_segments(
    concept_id: str,
    candidate_id: str,
    candidate_segments: tuple[str, ...],
    original: LanguageLexicon,
    overlaid_by_id: dict[str, LexicalForm],
) -> tuple[str, ...]:
    # Reconstructed-node lexicons already use candidate IDs directly.
    if candidate_id in overlaid_by_id:
        return overlaid_by_id[candidate_id].segments
    # Observed leaf beams merge forms by concept and segment sequence, so map
    # the candidate back to every source form it represents.
    source_forms = tuple(
        form
        for form in original.forms
        if form.concept_id == concept_id and form.segments == candidate_segments
    )
    if not source_forms:
        raise ValueError(
            f"segmentation overlay cannot resolve beam candidate {candidate_id!r}"
        )
    outputs = {
        overlaid_by_id[form.form_id].segments for form in source_forms
    }
    if len(outputs) != 1:
        raise ValueError(
            f"segmentation overlay is ambiguous for merged beam candidate "
            f"{candidate_id!r}; source forms produced different segmentations"
        )
    return next(iter(outputs))


DEFAULT_MAX_FAILED_NODES = 3
"""Dead nodes a family run tolerates before it stops.

A bound rather than a policy: one node that stalls should not discard the work
of the nodes that succeeded, but a run failing everywhere is producing an
identity tree, not a reconstruction, and should say so by stopping. Small and
fixed because the number that matters is "how many nodes am I willing to read
as unreconstructed", which does not scale with the tree.
"""


class TooManyNodeFailuresError(RuntimeError):
    """More nodes failed than the run was willing to fall back over.

    Carries the records so a caller does not have to re-read the event log to
    say which nodes died.
    """

    def __init__(
        self,
        message: str,
        failures: Sequence[NodeFailureRecord] = (),
    ) -> None:
        super().__init__(message)
        self.failures = tuple(failures)


class AgenticNodeReconstructor:
    """Run one hypothesis-manager session, then invoke deterministic scoring.

    A node session that fails does not, by default, end the family run. The
    failure is recorded, an identity reconstruction is committed for the node so
    the parent beam is defined, and the walk continues — the alternative being a
    build that deletes every object file because one translation unit failed.
    Set `fail_fast` to restore propagation, and `max_failed_nodes` to bound how
    far a run that is failing everywhere gets.
    """

    def __init__(
        self,
        orchestrator: AgentOrchestrator,
        *,
        deterministic: RuleBasedReconstructor | None = None,
        aligner: AlignmentProvider | None = None,
        fail_fast: bool = False,
        max_failed_nodes: int | None = DEFAULT_MAX_FAILED_NODES,
    ) -> None:
        if max_failed_nodes is not None and max_failed_nodes < 0:
            raise ValueError("max_failed_nodes must be non-negative")
        self.orchestrator = orchestrator
        self.deterministic = deterministic or RuleBasedReconstructor()
        self.aligner = aligner or LingPyAligner()
        self.fail_fast = fail_fast
        self.max_failed_nodes = max_failed_nodes
        self.run_results: list[AgentRunResult] = []
        # Every attempted node in traversal order, failures included. The
        # successes are also in `run_results`; this is what a run artifact
        # reports, and a node that died belongs in it.
        self.trajectories: list[AgentTrajectory] = []
        self.node_failures: list[NodeFailureRecord] = []
        # Committed hypotheses from nodes already completed in this family run.
        # Each node still gets a fresh conversation; this is retrieved through a
        # bounded tool, not merged into the prompt.
        self.prior_reconstructions: dict[str, PriorNodeReconstruction] = {}

    def clear_run_results(self) -> None:
        self.run_results.clear()
        self.trajectories.clear()
        self.node_failures.clear()
        self.prior_reconstructions.clear()

    def seed_prior_reconstructions(
        self,
        trajectories: Iterable[AgentTrajectory],
    ) -> int:
        """Restore hypotheses for nodes this process did not run itself.

        Reconstructed lexicons survive a `--resume` because they come from the
        checkpoint's `ReconstructionStep`s; committed hypotheses lived only in
        this dictionary, so a resumed run silently lost half of what crosses a
        node boundary. Trajectories already store the full commit, so replaying
        them through the same `summarize_commit` the live path uses restores
        exactly the record a live node would have produced — nothing is
        reconstructed twice and no new conversion exists to drift.

        Whether a seeded node is *visible* to a later node is still decided by
        the traverser's reconstructed-evidence set, exactly as for a live one.
        Returns the number of nodes seeded. Ordering matters: seeds written
        before `clear_run_results` are wiped, so callers seed after it — which
        is why `ReconstructionService` takes the trajectories rather than
        letting a caller sequence the two itself.
        """
        seeded: set[str] = set()
        for trajectory in trajectories:
            commit = trajectory.committed_reconstruction
            if not trajectory.completed or commit is None:
                continue
            # A node re-run after a failed resume appears more than once; the
            # last record is the one the checkpoint's step came from.
            self.prior_reconstructions[trajectory.node_id] = summarize_commit(
                trajectory.node_id, commit
            )
            seeded.add(trajectory.node_id)
        return len(seeded)

    def reconstruct(
        self,
        parent_node_id: str,
        children: Sequence[NodeBeamState],
        *,
        rules: Sequence[ReconstructionRule | ParsedSoundRule] = (),
        anomalies: Sequence[AnomalyReport] = (),
        anchors: Sequence[LexicalForm] = (),
        evidence_context: NodeReconstructionContext | None = None,
    ) -> ReconstructionStep:
        if rules or anomalies:
            raise ValueError(
                "AgenticNodeReconstructor does not accept precommitted rules or anomalies"
            )
        child_beams = tuple(children)
        active_evidence = (
            {
                item.node_id: item.lexicon
                for item in evidence_context.available_nodes
                if item.node_id in evidence_context.active_child_ids
            }
            if evidence_context is not None
            else {}
        )
        context = AgentContext(
            node_id=parent_node_id,
            child_lexicons=tuple(
                active_evidence.get(child.node_id, beam_to_lexicon(child))
                for child in child_beams
            ),
            aligner=self.aligner,
            # Keep supplied anchors in the prompt and trajectory for audit even
            # under IGNORE. The deterministic scorer still enforces the policy.
            anchors=tuple(anchors),
            anchor_policy=self.deterministic.anchor_policy,
            evidence=evidence_context.available_nodes if evidence_context else (),
            concepts=evidence_context.concepts if evidence_context else (),
            prior_reconstructions=self._visible_prior_reconstructions(
                evidence_context
            ),
        )
        try:
            run_result = self.orchestrator.run(context)
        except RunBudgetExceeded:
            # A budget is a statement about the whole run, not about this node.
            # Falling back over it would spend the rest of the tree fabricating
            # identity nodes and report a stopped run as a completed one.
            raise
        except Exception as error:
            return self._fallback_step(
                parent_node_id,
                child_beams,
                error,
                anchors=anchors,
                evidence_context=evidence_context,
            )
        committed = run_result.reconstruction
        scored_children = tuple(
            _apply_overlay(
                child,
                context,
                committed.request.segmentation_overlay_id,
            )
            for child in child_beams
        )
        step = self.deterministic.reconstruct(
            parent_node_id,
            scored_children,
            rules=committed.parsed_rules,
            anomalies=committed.request.anomalies,
            anchors=anchors,
            evidence_context=evidence_context,
            # Only this layer knows what the session looked at; the step is
            # where a reader goes looking for it.
            inspected_concept_ids=run_result.inspected_concept_ids,
        )
        finalized = self.orchestrator.finalize(run_result, step)
        self.run_results.append(finalized)
        self.trajectories.append(finalized.trajectory)
        self.prior_reconstructions[parent_node_id] = summarize_commit(
            parent_node_id, committed
        )
        return step

    def _fallback_step(
        self,
        parent_node_id: str,
        child_beams: tuple[NodeBeamState, ...],
        error: Exception,
        *,
        anchors: Sequence[LexicalForm],
        evidence_context: NodeReconstructionContext | None,
    ) -> ReconstructionStep:
        """Record a dead node and keep the walk going over an identity parent.

        The fallback is deterministic and claims nothing: no rule is applied, so
        the parent beam is the combination of the children as they stand. It is
        marked `failure_fallback` in the step's diagnostics precisely so nothing
        downstream can mistake it for a reconstruction that concluded identity.

        No hypothesis is recorded for the node, so a later node asking
        `get_node_reconstruction` about it is truthfully told there is none.
        """
        if self.fail_fast:
            raise error
        trajectory = failed_node_trajectory(error)
        record = NodeFailureRecord(
            node_id=parent_node_id,
            child_node_ids=tuple(beam.node_id for beam in child_beams),
            error_type=type(error).__name__,
            reason=str(error) or type(error).__name__,
            trajectory_id=trajectory.trajectory_id if trajectory else None,
        )
        self.node_failures.append(record)
        if trajectory is not None:
            self.trajectories.append(trajectory)
        if (
            self.max_failed_nodes is not None
            and len(self.node_failures) > self.max_failed_nodes
        ):
            raise TooManyNodeFailuresError(
                f"{len(self.node_failures)} nodes failed, more than the "
                f"{self.max_failed_nodes} this run tolerates: "
                + ", ".join(
                    f"{item.node_id} ({item.error_type})"
                    for item in self.node_failures
                ),
                self.node_failures,
            ) from error
        self.orchestrator.emit_node_fallback(
            parent_node_id,
            error_type=record.error_type,
            reason=record.reason,
            failed_node_count=len(self.node_failures),
            max_failed_nodes=self.max_failed_nodes,
        )
        step = self.deterministic.reconstruct(
            parent_node_id,
            child_beams,
            evidence_context=evidence_context,
            anchors=anchors,
        )
        return step.model_copy(
            update={
                "diagnostics": step.diagnostics.model_copy(
                    update={"failure_fallback": True}
                )
            }
        )

    def _visible_prior_reconstructions(
        self,
        evidence_context: NodeReconstructionContext | None,
    ) -> tuple[PriorNodeReconstruction, ...]:
        """Prior hypotheses for nodes this node is already allowed to see.

        Gated on the traverser's own reconstructed-evidence set, which post-order
        populates only after a node completes, so nothing can leak from a node
        that has not been reconstructed yet.
        """
        if evidence_context is None:
            return ()
        return tuple(
            self.prior_reconstructions[item.node_id]
            for item in evidence_context.available_nodes
            if item.kind is EvidenceKind.RECONSTRUCTED
            and item.node_id in self.prior_reconstructions
        )
