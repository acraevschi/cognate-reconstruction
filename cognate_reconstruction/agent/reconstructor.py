"""Agentic NodeReconstructor wrapper keeping the deterministic core LLM-free."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.orchestrator import AgentOrchestrator
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
from cognate_reconstruction.schemas.traversal import NodeReconstructionContext
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


class AgenticNodeReconstructor:
    """Run one hypothesis-manager session, then invoke deterministic scoring."""

    def __init__(
        self,
        orchestrator: AgentOrchestrator,
        *,
        deterministic: RuleBasedReconstructor | None = None,
        aligner: AlignmentProvider | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.deterministic = deterministic or RuleBasedReconstructor()
        self.aligner = aligner or LingPyAligner()
        self.run_results: list[AgentRunResult] = []
        # Committed hypotheses from nodes already completed in this family run.
        # Each node still gets a fresh conversation; this is retrieved through a
        # bounded tool, not merged into the prompt.
        self.prior_reconstructions: dict[str, PriorNodeReconstruction] = {}

    def clear_run_results(self) -> None:
        self.run_results.clear()
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
        run_result = self.orchestrator.run(context)
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
        )
        finalized = self.orchestrator.finalize(run_result, step)
        self.run_results.append(finalized)
        self.prior_reconstructions[parent_node_id] = summarize_commit(
            parent_node_id, committed
        )
        return step

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
