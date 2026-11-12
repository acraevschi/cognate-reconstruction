"""Session-local immutable inventory references; all execution uses the full contract."""
from __future__ import annotations

import json

from pydantic import Field, ValidationError, model_validator

from cognate_reconstruction.agent.schemas import (
    CommitReconstructionArgs, TestProtoAssemblyArgs,
)
from cognate_reconstruction.agent.tools.errors import ToolInputError
from cognate_reconstruction.agent.tools.inventory_evidence import (
    expand_shared_claims, node_inventory,
)
from cognate_reconstruction.schemas.common import NonEmptyStr, WorkbenchModel
from cognate_reconstruction.schemas.evidence import digest
from cognate_reconstruction.schemas.inventory import (
    CorrespondenceCommitment, ProtoInventorySpec, ResiduePolicy, SharedCorrespondenceClaim,
)
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
    # The one-of rule lives only in `explicit_claim_collection`: LiteLLM's
    # Gemini conversion keeps nothing but a top-level `anyOf`, which dropped
    # every argument of this tool from Gemini requests.
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


def _conditioning_key(environment: RuleEnvironment | None) -> str | None:
    return environment.model_dump_json() if environment is not None else None


class StoredAssemblyV2Args(StoredAssemblyArgs):
    """Preview flat choices, full commitments, or an incremental patch over base_hypothesis_id."""

    base_hypothesis_id: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Optional same-session test_proto_assembly hypothesis_id to patch "
            "incrementally. Inherits its commitments, shared_claims, "
            "residue_policy, overlays, dispositions, restorations, and "
            "unit_orders unless overridden or dropped."
        ),
    )
    drop_set_ids: tuple[NonEmptyStr, ...] = Field(
        default=(),
        description=(
            "Local csu-* set_ids to remove from base_hypothesis_id commitments "
            "and shared_claims before applying new claims."
        ),
    )
    drop_pattern_ids: tuple[NonEmptyStr, ...] = Field(
        default=(),
        description=(
            "Recurrence csp-* pattern_ids whose shared_claims are removed from "
            "base_hypothesis_id before applying new claims."
        ),
    )
    residue_policy: ResiduePolicy | None = Field(
        default=None,
        description=(
            "Policy for unaccounted columns; required when base_hypothesis_id "
            "is omitted, otherwise inherited from base_hypothesis_id unless "
            "overridden. retain_from_witness also needs an active witness."
        ),
    )

    @model_validator(mode="after")
    def explicit_claim_collection(self):
        if self.base_hypothesis_id is None:
            if self.drop_set_ids or self.drop_pattern_ids:
                return self
            if not self.model_fields_set & {"choices", "commitments", "shared_claims"}:
                raise ValueError(
                    "state choices, commitments or shared_claims explicitly; "
                    "[] is deliberate identity, omission is not a decision"
                )
            if self.residue_policy is None:
                raise ValueError(
                    "residue_policy is required when base_hypothesis_id is omitted"
                )
            return self
        if "residue_policy" in self.model_fields_set and self.residue_policy is None:
            raise ValueError(
                "residue_policy cannot be null; omit it to inherit from "
                "base_hypothesis_id or state an explicit policy"
            )
        if not (self.model_fields_set - {"base_hypothesis_id"}):
            raise ValueError(
                "supply at least one patch, policy, or scope field alongside "
                "base_hypothesis_id"
            )
        return self


def describe_inventory_input_v2(context):
    """Shape guidance for stored-hypothesis-v2, including incremental hypothesis patching."""
    return (
        describe_inventory_input(context)
        + " To revise or extend an earlier same-session preview incrementally "
        "without re-emitting unchanged claims, pass base_hypothesis_id with "
        "delta choices, shared_claims, drop_set_ids (local csu-* IDs), "
        "drop_pattern_ids (recurrence csp-* IDs), or policy/scope overrides "
        "under the same evidence_revision."
    )


def _validate_v2_args(raw_arguments) -> StoredAssemblyV2Args:
    if isinstance(raw_arguments, StoredAssemblyV2Args):
        return raw_arguments
    if isinstance(raw_arguments, dict):
        try:
            return StoredAssemblyV2Args.model_validate(raw_arguments)
        except ValidationError:
            try:
                payload = json.dumps(raw_arguments)
            except TypeError:
                raise
            return StoredAssemblyV2Args.model_validate_json(payload)
    return StoredAssemblyV2Args.model_validate(raw_arguments)


def test_stored_assembly_v2(raw_arguments, context, call_id):
    from cognate_reconstruction.agent.tools.proto_assembly import (
        context_evidence_digest, hypothesis_digest, test_proto_assembly,
    )

    args = _validate_v2_args(raw_arguments)
    if args.base_hypothesis_id is None:
        if args.drop_set_ids or args.drop_pattern_ids:
            raise ToolInputError(
                "drop_set_ids and drop_pattern_ids require base_hypothesis_id",
                code="invalid-hypothesis-patch",
                remediation=(
                    "Pass base_hypothesis_id from an earlier same-session "
                    "test_proto_assembly call to drop sets or patterns "
                    "incrementally, or omit drop_set_ids and drop_pattern_ids "
                    "when starting a fresh hypothesis."
                ),
            )
        fresh_fields = {
            k: getattr(args, k)
            for k in args.model_fields_set
            if k not in {"base_hypothesis_id", "drop_set_ids", "drop_pattern_ids"}
        }
        return test_stored_assembly(StoredAssemblyArgs(**fresh_fields), context, call_id)

    base_snapshot = context.inventory_hypotheses.get(args.base_hypothesis_id)
    if base_snapshot is None:
        raise ToolInputError(
            "unknown same-session base_hypothesis_id",
            code="hypothesis-unknown",
            remediation=(
                "Use a hypothesis_id returned by an earlier successful "
                "test_proto_assembly call at this node in the current session; "
                "handles do not cross nodes, sessions, or resumes."
            ),
        )
    base_spec = ProtoInventorySpec.model_validate_json(base_snapshot.spec_json)
    if (
        base_snapshot.node_id != context.node_id
        or tuple(base_spec.child_node_ids) != tuple(context.child_ids)
    ):
        raise ToolInputError(
            "base_hypothesis_id does not match the current node or active children",
            code="hypothesis-stale",
            remediation=(
                "Start a fresh test_proto_assembly hypothesis for this node; "
                "handles are scoped to one node and child order."
            ),
        )

    explicit = args.model_fields_set
    segmentation_overlay_id = (
        args.segmentation_overlay_id
        if "segmentation_overlay_id" in explicit
        else base_snapshot.segmentation_overlay_id
    )
    alignment_overlay_id = (
        args.alignment_overlay_id
        if "alignment_overlay_id" in explicit
        else base_spec.alignment_overlay_id
    )
    unit_orders = (
        args.unit_orders if "unit_orders" in explicit else base_spec.unit_orders
    )
    residue_policy = (
        args.residue_policy
        if "residue_policy" in explicit
        else base_spec.residue_policy
    )
    assert residue_policy is not None
    if "residue_witness_child_id" in explicit:
        residue_witness_child_id = args.residue_witness_child_id
    elif "residue_policy" in explicit and residue_policy is ResiduePolicy.DROP:
        residue_witness_child_id = None
    else:
        residue_witness_child_id = base_spec.residue_witness_child_id
    residue_dispositions = (
        args.residue_dispositions
        if "residue_dispositions" in explicit
        else base_spec.residue_dispositions
    )
    restorations = (
        args.restorations if "restorations" in explicit else base_spec.restorations
    )

    sets, current_reading = node_inventory(
        context,
        segmentation_overlay_id=segmentation_overlay_id,
        alignment_overlay_id=alignment_overlay_id,
        unit_orders=unit_orders,
    )
    if current_reading.evidence_revision != base_snapshot.evidence_revision:
        raise ToolInputError(
            "base_hypothesis_id belongs to an earlier evidence_revision; "
            "re-survey and start a fresh inventory when changing overlays or "
            "unit_orders",
            code="hypothesis-stale",
            remediation=(
                "Changing segmentation_overlay_id, alignment_overlay_id, "
                "unit_orders, or underlying forms creates a new "
                "evidence_revision with new local set_ids. Re-run "
                "summarize_correspondences and preview a fresh inventory "
                "without base_hypothesis_id."
            ),
        )
    if (
        context_evidence_digest(context) != base_snapshot.witness_evidence_digest
        or hypothesis_digest(base_spec, base_snapshot.segmentation_overlay_id)
        != base_snapshot.hypothesis_digest
    ):
        raise ToolInputError(
            "stored base hypothesis no longer matches the current evidence",
            code="hypothesis-stale",
            remediation=(
                "Re-survey and preview a fresh hypothesis under current "
                "evidence; no linguistic values are inferred or migrated."
            ),
        )

    by_id = {s.set_id: s for s in sets.sets}
    incoming_local: list[CorrespondenceCommitment] = list(args.commitments)
    for choice in args.choices:
        item = by_id.get(choice.set_id)
        if item is None:
            raise ToolInputError(
                "choice names an unknown or nonlocal correspondence set",
                code="unknown-correspondence-set",
                remediation=(
                    "Survey under these exact overlays/orders. Use local csu-* "
                    "IDs for choices; csp-* patterns need shared_claims with "
                    "explicit members."
                ),
            )
        incoming_local.append(
            CorrespondenceCommitment(
                reflexes=item.segments, support=item.support, **dict(choice)
            )
        )

    # Validate that incoming claims do not overlap with themselves in the same call.
    incoming_check_spec = ProtoInventorySpec(
        child_node_ids=context.child_ids,
        commitments=tuple(incoming_local),
        shared_claims=args.shared_claims,
        residue_policy=ResiduePolicy.DROP,
    )
    expand_shared_claims(incoming_check_spec, sets)

    patched_local: list[CorrespondenceCommitment] = list(base_spec.commitments)
    patched_shared: list[SharedCorrespondenceClaim] = list(base_spec.shared_claims)

    if args.drop_pattern_ids:
        dropped_patterns = set(args.drop_pattern_ids)
        patched_shared = [
            claim
            for claim in patched_shared
            if claim.pattern_id not in dropped_patterns
        ]

    if args.drop_set_ids:
        dropped_sets = set(args.drop_set_ids)
        patched_local = [
            item for item in patched_local if item.set_id not in dropped_sets
        ]
        next_shared: list[SharedCorrespondenceClaim] = []
        for claim in patched_shared:
            remaining = tuple(
                mid for mid in claim.member_set_ids if mid not in dropped_sets
            )
            if remaining:
                next_shared.append(
                    claim
                    if len(remaining) == len(claim.member_set_ids)
                    else claim.model_copy(update={"member_set_ids": remaining})
                )
        patched_shared = next_shared

    for incoming_claim in args.shared_claims:
        ckey = _conditioning_key(incoming_claim.conditioning)
        claimed_members = set(incoming_claim.member_set_ids)
        patched_local = [
            item
            for item in patched_local
            if not (
                item.set_id in claimed_members
                and _conditioning_key(item.conditioning) == ckey
            )
        ]
        next_shared = []
        for existing in patched_shared:
            existing_ckey = _conditioning_key(existing.conditioning)
            if (
                existing.pattern_id == incoming_claim.pattern_id
                and existing_ckey == ckey
            ):
                continue
            if existing_ckey == ckey:
                remaining = tuple(
                    mid
                    for mid in existing.member_set_ids
                    if mid not in claimed_members
                )
                if remaining:
                    next_shared.append(
                        existing
                        if len(remaining) == len(existing.member_set_ids)
                        else existing.model_copy(update={"member_set_ids": remaining})
                    )
            else:
                next_shared.append(existing)
        next_shared.append(incoming_claim)
        patched_shared = next_shared

    for incoming_item in incoming_local:
        ckey = _conditioning_key(incoming_item.conditioning)
        next_shared = []
        for existing in patched_shared:
            if _conditioning_key(existing.conditioning) == ckey:
                remaining = tuple(
                    mid
                    for mid in existing.member_set_ids
                    if mid != incoming_item.set_id
                )
                if remaining:
                    next_shared.append(
                        existing
                        if len(remaining) == len(existing.member_set_ids)
                        else existing.model_copy(update={"member_set_ids": remaining})
                    )
            else:
                next_shared.append(existing)
        patched_shared = next_shared

        replaced = False
        for idx, existing_local in enumerate(patched_local):
            if (
                existing_local.set_id == incoming_item.set_id
                and _conditioning_key(existing_local.conditioning) == ckey
            ):
                patched_local[idx] = incoming_item
                replaced = True
                break
        if not replaced:
            patched_local.append(incoming_item)

    full = TestProtoAssemblyArgs(
        unit_orders=unit_orders,
        shared_claims=tuple(patched_shared),
        commitments=tuple(patched_local),
        restorations=restorations,
        residue_policy=residue_policy,
        residue_witness_child_id=residue_witness_child_id,
        residue_dispositions=residue_dispositions,
        concept_ids=args.concept_ids,
        segmentation_overlay_id=segmentation_overlay_id,
        alignment_overlay_id=alignment_overlay_id,
        detail=args.detail,
    )
    result = test_proto_assembly(full, context, call_id)
    spec = ProtoInventorySpec(
        child_node_ids=context.child_ids,
        **{
            k: v
            for k, v in dict(full).items()
            if k not in {"concept_ids", "detail", "segmentation_overlay_id"}
        },
    )
    snapshot = StoredInventoryHypothesis(
        node_id=context.node_id,
        spec_json=spec.model_dump_json(),
        segmentation_overlay_id=full.segmentation_overlay_id,
        evidence_revision=result.evidence_revision,
        hypothesis_digest=result.hypothesis_digest,
        validation_call_id=call_id,
        commit_ready=result.commit_ready,
        witness_evidence_digest=result.witness_evidence_digest,
    )
    handle = "hyp-" + digest(
        [
            context.node_id,
            context.child_ids,
            snapshot.hypothesis_digest,
            snapshot.evidence_revision,
            snapshot.witness_evidence_digest,
        ]
    )
    context.inventory_hypotheses.setdefault(handle, snapshot)
    result = result.model_copy(update={"hypothesis_id": handle})
    context.assembly_validations[call_id] = result
    return result
