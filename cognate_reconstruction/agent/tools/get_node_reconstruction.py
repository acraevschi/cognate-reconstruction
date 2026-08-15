"""Read-only access to hypotheses committed at already-completed nodes.

The comparative method is iterative: a correspondence established at one node
constrains its neighbours. Each node still gets its own independent session, so
without this the model re-derives the family's correspondences from scratch at
every internal node and nothing makes adjacent, mutually contradictory rule
inventories visible.

What is exposed is a prior *hypothesis*, never evidence, and it has no effect on
scoring. Cross-node scoring — carrying a parent's confidence into a child's
beam, or penalising inconsistency — would change what counts as a valid
reconstruction and is a research-owner decision.
"""

from __future__ import annotations

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.schemas import (
    CommittedReconstruction,
    GetNodeReconstructionArgs,
    GetNodeReconstructionResult,
    PriorCommittedRule,
    PriorNodeReconstruction,
)
from cognate_reconstruction.agent.tools.errors import ToolInputError
from cognate_reconstruction.schemas.common import WorkbenchModel


def summarize_commit(
    node_id: str,
    commit: CommittedReconstruction,
) -> PriorNodeReconstruction:
    """Reduce a completed commit to the read-only record other nodes may see.

    Session-local bookkeeping — validation call IDs, supporting form IDs,
    overlay IDs — belongs to the node that produced it and is deliberately left
    out; those IDs mean nothing in another session.
    """
    return PriorNodeReconstruction(
        node_id=node_id,
        rules=tuple(
            PriorCommittedRule(
                dsl=rule.rule.source,
                source_child_ids=rule.source_child_ids,
                confidence=rule.confidence,
            )
            for rule in commit.parsed_rules
        ),
        anomalies=commit.request.anomalies,
        summary=commit.request.summary,
        identity_reconstruction=not commit.parsed_rules,
    )


def get_node_reconstruction(
    raw_arguments: WorkbenchModel,
    context: AgentContext,
    call_id: str,  # noqa: ARG001 - uniform tool signature
) -> GetNodeReconstructionResult:
    arguments = GetNodeReconstructionArgs.model_validate(raw_arguments)
    for prior in context.prior_reconstructions:
        if prior.node_id == arguments.node_id:
            return GetNodeReconstructionResult(reconstruction=prior)
    available = sorted(prior.node_id for prior in context.prior_reconstructions)
    raise ToolInputError(
        f"no committed hypothesis is available for node {arguments.node_id!r}",
        remediation=(
            "Nodes with a retrievable hypothesis in this run: "
            + (", ".join(available) if available else "none")
            + ". Post-order traversal reaches a node only after all of its "
            "descendants, so a node above or beside this one has not been "
            "reconstructed yet."
        ),
    )
