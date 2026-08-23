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
    CommittedHypothesis,
    GetNodeReconstructionArgs,
    GetNodeReconstructionResult,
    PriorCommittedRule,
    PriorCommittedSet,
    PriorNodeInventory,
    PriorNodeReconstruction,
)
from cognate_reconstruction.agent.tools.errors import ToolInputError
from cognate_reconstruction.schemas.common import WorkbenchModel
from cognate_reconstruction.schemas.inventory import CommittedProtoInventory


def _prior_rule(rule) -> PriorCommittedRule:
    return PriorCommittedRule(
        dsl=rule.rule.source,
        source_child_ids=rule.source_child_ids,
        confidence=rule.confidence,
    )


def summarize_inventory(
    node_id: str,
    commit: CommittedProtoInventory,
) -> PriorNodeInventory:
    """Reduce a completed inventory commit to what other nodes may see.

    **`set_id` is stripped**, and that is not tidiness. A set ID is derived from
    a reflex tuple over *that* node's children under *that* node's overlays, so
    it names nothing here; carrying it across would invite a commitment citing a
    set this node's data cannot reproduce. `child_node_ids` is carried instead,
    because without it a reflex tuple cannot be read at all.
    """
    return PriorNodeInventory(
        node_id=node_id,
        child_node_ids=commit.request.child_node_ids,
        proto_phonemes=commit.proto_phonemes,
        sets=tuple(
            PriorCommittedSet(
                reflexes=item.reflexes,
                proto_segment=item.proto_segment,
                support=item.support,
                confidence=item.confidence,
            )
            for item in commit.request.commitments
        ),
        derived_rules=tuple(_prior_rule(rule) for rule in commit.derived_rules),
        anomalies=commit.request.anomalies,
        summary=commit.request.summary,
        identity_reconstruction=commit.identity_reconstruction,
    )


def summarize_commit(
    node_id: str,
    commit: CommittedHypothesis,
) -> PriorNodeReconstruction | PriorNodeInventory:
    """Reduce a completed commit to the read-only record other nodes may see.

    Session-local bookkeeping — validation call IDs, supporting form IDs,
    overlay IDs — belongs to the node that produced it and is deliberately left
    out; those IDs mean nothing in another session.
    """
    if isinstance(commit, CommittedProtoInventory):
        return summarize_inventory(node_id, commit)
    return PriorNodeReconstruction(
        node_id=node_id,
        rules=tuple(_prior_rule(rule) for rule in commit.parsed_rules),
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
    for prior in context.prior_inventories:
        if prior.node_id == arguments.node_id:
            return GetNodeReconstructionResult(inventory=prior)
    available = sorted(
        [prior.node_id for prior in context.prior_reconstructions]
        + [prior.node_id for prior in context.prior_inventories]
    )
    raise ToolInputError(
        f"no committed hypothesis is available for node {arguments.node_id!r}",
        code="unknown-node",
        remediation=(
            "Nodes with a retrievable hypothesis in this run: "
            + (", ".join(available) if available else "none")
            + ". Post-order traversal reaches a node only after all of its "
            "descendants, so a node above or beside this one has not been "
            "reconstructed yet."
        ),
    )
