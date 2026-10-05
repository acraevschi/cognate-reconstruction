"""Session-local immutable inventory references; all execution uses the full contract."""
from __future__ import annotations

from pydantic import Field, model_validator

from cognate_reconstruction.agent.schemas import (
    CommitReconstructionArgs, TestProtoAssemblyArgs,
)
from cognate_reconstruction.agent.tools.errors import ToolInputError
from cognate_reconstruction.agent.tools.inventory_evidence import node_inventory
from cognate_reconstruction.schemas.common import NonEmptyStr, WorkbenchModel
from cognate_reconstruction.schemas.evidence import digest
from cognate_reconstruction.schemas.inventory import CorrespondenceCommitment, ProtoInventorySpec
from cognate_reconstruction.schemas.rules import RuleEnvironment


class LocalCorrespondenceChoice(WorkbenchModel):
    """Explicit linguistic decisions; the local ID supplies only reflexes/counts."""
    set_id: NonEmptyStr = Field(description="Exact local csu-* ID under the selected evidence/overlays; csp-* requires shared_claims.")
    proto_segment: NonEmptyStr | None = Field(description="Required value, including explicit null. Never inferred from evidence.")
    confidence: float = Field(gt=0.0, le=1.0, description="Required confidence in (0, 1]; never defaulted.")
    rationale: NonEmptyStr | None = None
    directionality_rationale: NonEmptyStr | None = None
    conditioning: RuleEnvironment | None = None
    merges_with_set_id: NonEmptyStr | None = None


class StoredAssemblyArgs(TestProtoAssemblyArgs):
    """Preview flat local choices or compatible full commitments; explicitly state a claim list, including [] for identity."""
    model_config = {"json_schema_extra": {"anyOf": [
        {"required": ["choices"]}, {"required": ["commitments"]},
        {"required": ["shared_claims"]},
    ]}}
    commitments: tuple[CorrespondenceCommitment, ...] = ()
    choices: tuple[LocalCorrespondenceChoice, ...] = Field(default=(), description="Top-level flat list: one local set_id/value/confidence/explanation per item, not per concept or whole form. Do not nest choices inside commitments. Resolves only reflexes/support. Explicit [] means identity; overlapping claims are rejected.")

    @model_validator(mode="after")
    def explicit_claim_collection(self):
        if not self.model_fields_set & {"choices", "commitments", "shared_claims"}:
            raise ValueError("state choices, commitments or shared_claims explicitly; [] is deliberate identity, omission is not a decision")
        return self


class StoredCommitArgs(CommitReconstructionArgs):
    """Reference the exact inspected inventory; final reporting remains explicit."""
    hypothesis_id: NonEmptyStr | None = Field(default=None, description="Same-session test_proto_assembly handle with commit_ready=true. Commit it with node_id, summary and anomalies; omit inventory, rules and overlays. To change any choice or explanation, preview a new hypothesis.")

    @model_validator(mode="after")
    def exclusive_reference(self):
        if self.hypothesis_id is not None and self.model_fields_set & {
            "inventory", "rules", "segmentation_overlay_id", "cascade_validation_call_id"
        }:
            raise ValueError("hypothesis_id commits an immutable inventory; omit payload/overlay fields and preview any edits first")
        return self


class StoredInventoryHypothesis(WorkbenchModel):
    """Serialized snapshot avoids mutable nested mappings or unvalidated model_copy edits."""
    node_id: NonEmptyStr
    spec_json: NonEmptyStr
    segmentation_overlay_id: NonEmptyStr | None
    evidence_revision: NonEmptyStr
    hypothesis_digest: NonEmptyStr
    validation_call_id: NonEmptyStr
    commit_ready: bool
    witness_evidence_digest: NonEmptyStr


def describe_inventory_input(context):
    """Shape guidance only; never flatten a rejected claim or supply linguistic values."""
    return (
        "test_proto_assembly takes a top-level flat choices list: each item names one exact local "
        "csu-* token-correspondence row, not a whole concept/form. Supply set_id, explicit "
        "proto_segment (value or null), confidence, and the required explanations. Do not nest "
        "choices inside commitments or group them by concept. Full commitments instead require "
        "one exact reflex per active child (including nulls), harness support and the same "
        "linguistic decisions. Shared claims explicitly select csp-* pattern members. "
        "Use the current local survey IDs under the same orders/overlays; inventing IDs or support "
        "does not select evidence. To abstain, explicitly supply choices=[] or commitments=[] "
        "with the intended residue policy. No missing values, IDs or explanations are inferred."
    )


def test_stored_assembly(raw_arguments, context, call_id):
    from cognate_reconstruction.agent.tools.proto_assembly import test_proto_assembly
    args = StoredAssemblyArgs.model_validate(raw_arguments)
    sets, _ = node_inventory(context, segmentation_overlay_id=args.segmentation_overlay_id,
        alignment_overlay_id=args.alignment_overlay_id, unit_orders=args.unit_orders)
    by_id = {s.set_id: s for s in sets.sets}
    resolved = list(args.commitments)
    for choice in args.choices:
        item = by_id.get(choice.set_id)
        if item is None:
            raise ToolInputError("choice names an unknown or nonlocal correspondence set",
                code="unknown-correspondence-set",
                remediation="Survey under these exact overlays/orders. Use local csu-* IDs for choices; csp-* patterns need shared_claims with explicit members.")
        resolved.append(CorrespondenceCommitment(reflexes=item.segments, support=item.support,
            **dict(choice)))
    data = dict(args)
    data.pop("choices")
    data["commitments"] = tuple(resolved)
    full = TestProtoAssemblyArgs(**data)
    result = test_proto_assembly(full, context, call_id)
    spec = ProtoInventorySpec(child_node_ids=context.child_ids,
        **{k: v for k, v in dict(full).items() if k not in {
            "concept_ids", "detail", "segmentation_overlay_id"}})
    snapshot = StoredInventoryHypothesis(node_id=context.node_id,
        spec_json=spec.model_dump_json(), segmentation_overlay_id=full.segmentation_overlay_id,
        evidence_revision=result.evidence_revision, hypothesis_digest=result.hypothesis_digest,
        validation_call_id=call_id, commit_ready=result.commit_ready,
        witness_evidence_digest=result.witness_evidence_digest)
    handle = "hyp-" + digest([context.node_id, context.child_ids,
        snapshot.hypothesis_digest, snapshot.evidence_revision, snapshot.witness_evidence_digest])
    # Identical reinspection is safe. The hypothesis bytes never change under a handle;
    # the latest exact validation is used, as on the existing full-payload path.
    context.inventory_hypotheses.setdefault(handle, snapshot)
    result = result.model_copy(update={"hypothesis_id": handle})
    context.assembly_validations[call_id] = result
    return result


def commit_stored_hypothesis(raw_arguments, context, call_id):
    from cognate_reconstruction.agent.tools.commit_reconstruction import commit_reconstruction
    from cognate_reconstruction.agent.tools.proto_assembly import hypothesis_digest, context_evidence_digest
    args = StoredCommitArgs.model_validate(raw_arguments)
    data = dict(args)
    handle = data.pop("hypothesis_id")
    if handle is not None:
        snapshot = context.inventory_hypotheses.get(handle)
        if snapshot is None:
            raise ToolInputError("unknown same-session inventory hypothesis", code="hypothesis-unknown",
                remediation="Use hypothesis_id returned by this node's successful test_proto_assembly; handles do not cross sessions or resumes.")
        spec = ProtoInventorySpec.model_validate_json(snapshot.spec_json)
        _, reading = node_inventory(context, segmentation_overlay_id=snapshot.segmentation_overlay_id,
            alignment_overlay_id=spec.alignment_overlay_id, unit_orders=spec.unit_orders)
        if (snapshot.node_id != context.node_id or spec.child_node_ids != context.child_ids
            or reading.evidence_revision != snapshot.evidence_revision
            or context_evidence_digest(context) != snapshot.witness_evidence_digest
            or hypothesis_digest(spec, snapshot.segmentation_overlay_id) != snapshot.hypothesis_digest):
            raise ToolInputError("stored hypothesis no longer matches the current evidence", code="hypothesis-stale",
                remediation="Re-survey and preview the exact decisions under current evidence; no linguistic values are inferred or migrated.")
        if not snapshot.commit_ready:
            raise ToolInputError("stored hypothesis is executable but missing commit explanations", code="hypothesis-not-ready",
                remediation="Read missing_commit_requirements in its preview. Supply the explanations in a new preview; summary alone cannot fill per-set reasoning.")
        # Reuse ordinary checks, including exact validation coverage, rationale,
        # directionality, restoration, anomaly references and evidence bindings.
        data["inventory"] = spec.model_copy(update={"assembly_validation_call_id": snapshot.validation_call_id})
        data["segmentation_overlay_id"] = snapshot.segmentation_overlay_id
    return commit_reconstruction(CommitReconstructionArgs(**data), context, call_id)
