"""Preview what a proposed proto-inventory assembles, before committing it.

The successor to both `test_sound_law`'s validation role and
`test_rule_cascade`'s: it is the one call a commit is checked against, and it is
the call the refinement loop closes on. A session assigns values to sets, previews
the whole proposed inventory, reads the unaccounted columns and the assembled
forms, refines — conditions a set, splits one, changes a value — and previews
again. The refined inventory is validated by the same call that is the commit's
evidence, so there is no object that first exists inside a preview and then needs
a separate standalone test to be committable.

**Coverage is over sets, not over concepts**, and that is what makes the
invariant satisfiable on a large family. On Polynesian a preview covers all 46
concepts for 27.8 KB; on a 900-concept family it must be batched, and requiring
every *concept* to have been previewed would make a commit need dozens of calls.
It is the sets that are the claims.

**What this must not become.** `test_rule_cascade` is the cautionary tale: 399 KB
across three calls at one live node, against 22 KB for all the evidence that node
inspected, and never compactable because it carries the IDs a commit is checked
against. Three constraints hold the line, and all three are design-time:

- no pairwise correspondence views — they are the quadratic term in the node
  count, and an assembly preview has no use for them;
- `detail` defaults to `"summary"`, so the per-column resolutions come back only
  when asked for;
- the result is *split* so its bulky half can be dropped from the live prompt
  while the validation ID, the covered set IDs, and the verdict stay. That split
  had to be right in the first version, because a result schema is recorded in
  trajectories the moment the tool ships.
"""

from __future__ import annotations

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.schemas import (
    AssemblyDetail,
    TestProtoAssemblyArgs,
    TestProtoAssemblyResult,
)
from cognate_reconstruction.agent.tools.errors import ToolInputError
from cognate_reconstruction.alignment.correspondence_sets import (
    one_reading_per_node,
)
from cognate_reconstruction.agent.tools.inventory_evidence import (
    check_complementary_splits,
    node_inventory,
    verify_commitments,
    verify_restorations,
    column_bindings, expand_shared_claims,
)
from cognate_reconstruction.schemas.common import WorkbenchModel
from cognate_reconstruction.schemas.inventory import (
    CommitProtoInventoryArgs,
    CommittedProtoInventory,
    ProtoInventorySpec,
    ResiduePolicy,
)
from cognate_reconstruction.schemas.traversal import ReconstructionStep
from cognate_reconstruction.traversal.assembler import (
    ProtoInventoryAssembler,
    derive_branch_rules,
)
from cognate_reconstruction.traversal.beam import make_leaf_beam
from cognate_reconstruction.schemas.evidence import digest, EVIDENCE_CONTRACT_VERSION


def _validate_residue_policy(
    context: AgentContext,
    residue_policy: ResiduePolicy,
    residue_witness_child_id: str | None,
) -> None:
    if residue_policy is ResiduePolicy.RETAIN_FROM_WITNESS:
        if residue_witness_child_id is None:
            raise ToolInputError(
                "residue_policy 'retain_from_witness' needs a "
                "residue_witness_child_id",
                code="inactive-children",
                remediation=(
                    "Name the active child whose material is carried through "
                    "where no committed set explains a column. That is a "
                    "qualified witness choice, not proof of conservatism. "
                    "A witness gap emits nothing. Active children: "
                    + ", ".join(context.child_ids)
                ),
            )
        if residue_witness_child_id not in context.child_ids:
            raise ToolInputError(
                f"residue witness {residue_witness_child_id!r} is not an active "
                "child of this node",
                code="inactive-children",
                remediation="Active children: " + ", ".join(context.child_ids),
            )
    elif residue_witness_child_id is not None:
        raise ToolInputError(
            "residue_witness_child_id is only meaningful with residue_policy "
            "'retain_from_witness'",
            code="inactive-children",
            remediation=(
                "Under 'drop' an unexplained column contributes nothing, so "
                "there is no witness to name. Omit the field, or switch the "
                "policy."
            ),
        )


def assemble_node(
    context: AgentContext,
    spec: ProtoInventorySpec,
    *,
    node_id: str,
    segmentation_overlay_id: str | None,
    concept_ids: tuple[str, ...] = (),
    summary: str = "assembly preview",
    anomalies: tuple = (),
) -> tuple[ReconstructionStep, CommittedProtoInventory]:
    """Run the assembler over this node's own forms under a proposed inventory.

    Shared by the preview and the commit so the number a session reads before it
    commits and the number the artifact records cannot disagree — the same
    argument `traversal/convergence.py` makes for the measure it replaced.

    The child beams here are the children's *reported* forms, one candidate each,
    rather than their full reconstructed beams. That is the right evidence for a
    preview — it answers "what does this inventory say about the lexicon in front
    of me", which is the question a session is asking — and it has to be the same
    reduction the survey applies, or the preview would align columns the set IDs
    were not derived from and report residue that the real step will not see. The
    real parent beam is built later by `agent/reconstructor.py` from the actual
    child beams, where every retained candidate is a tuple to assemble.
    """
    inventory_sets, alignment_map = node_inventory(
        context,
        segmentation_overlay_id=segmentation_overlay_id,
        alignment_overlay_id=spec.alignment_overlay_id,
        unit_orders=spec.unit_orders,
    )
    submitted_shared = spec.shared_claims
    spec = expand_shared_claims(spec, inventory_sets)
    verify_commitments(context, spec.commitments, inventory_sets)
    check_complementary_splits(
        context,
        spec.commitments,
        alignment_map,
        residue_policy=spec.residue_policy,
        residue_witness_child_id=spec.residue_witness_child_id,
    )
    verify_restorations(context, spec.restorations, alignment_map, segmentation_overlay_id)
    verify_positions(spec, alignment_map)

    derived = derive_branch_rules(spec.commitments, context.child_ids)
    committed = CommittedProtoInventory(
        evidence_contract_version=EVIDENCE_CONTRACT_VERSION,
        approved_shared_claims=submitted_shared,
        derived_rules_scope="unscoped_view",
        evidence_revision=alignment_map.evidence_revision,
        column_bindings=column_bindings(alignment_map, context.child_ids),
        request=CommitProtoInventoryArgs(
            node_id=node_id,
            segmentation_overlay_id=segmentation_overlay_id,
            summary=summary,
            anomalies=anomalies,
            **dict(spec),
        ),
        proto_phonemes=tuple(
            sorted(
                {
                    item.proto_segment
                    for item in spec.commitments
                    if item.proto_segment is not None
                }
            )
        ),
        derived_rules=derived.rules,
        non_invertible_child_ids=derived.non_invertible_child_ids,
    )
    selected = set(concept_ids)
    lexicons = []
    for child_id in context.child_ids:
        lexicon = context.lexicon(child_id, segmentation_overlay_id)
        lexicons.append(lexicon)
    beams = [make_leaf_beam(lexicon, beam_width=max(1, len(lexicon.forms) * 16))
             for lexicon in lexicons]
    if context.child_beams:
        from cognate_reconstruction.agent.reconstructor import _apply_overlay
        beams = [_apply_overlay(beam, context, segmentation_overlay_id)
                 for beam in context.child_beams]
    assembler = ProtoInventoryAssembler(
        beam_width=max((beam.beam_width for beam in beams), default=1),
        anchor_policy=context.anchor_policy,
        aligner=context.aligner,
        engine=context.rule_engine,
        semantic_cache=context.unit_alignment_cache,
    )
    step = assembler.reconstruct(
        node_id,
        tuple(beams),
        inventory=committed,
        anchors=context.active_anchors,
        overrides=context.alignment_overrides(spec.alignment_overlay_id),
    )
    if selected:
        reports = tuple(r for r in step.assembly_reports if r.concept_id in selected)
        columns = sum(r.column_count for r in reports)
        unaccounted = sum(r.unaccounted_column_count for r in reports)
        step = step.model_copy(update={
            "output_beam": step.output_beam.model_copy(update={"distributions": tuple(
                d for d in step.output_beam.distributions if d.concept_id in selected)}),
            "assembly_reports": reports,
            "diagnostics": step.diagnostics.model_copy(update={
                "assembled_column_count": columns, "unaccounted_column_count": unaccounted,
                "unaccounted_column_rate": unaccounted / columns if columns else 0.0,
                "concepts_available": len(selected),
                "cross_branch_assembly_rate": sum(r.cross_branch_assembled for r in reports) / len(reports) if reports else 0.0}),
        })
    return step, committed


def held_out_unaccounted_column_rate(
    context: AgentContext,
    spec: ProtoInventorySpec,
    *,
    node_id: str,
    segmentation_overlay_id: str | None,
) -> float | None:
    """The committed inventory, on the concepts this node never reasoned about.

    The direct analogue of `held_out_convergence_rate`, and it catches what that
    was added for: an inventory fitted to five concepts explains nothing on the
    concepts it never saw. Reported, never enforced — a narrowly evidenced
    inventory is meant to *look* poor here, not to be forbidden.
    """
    held_out = context.concept_split.held_out_concept_ids
    if not held_out or not (spec.commitments or spec.shared_claims):
        return None
    step, _committed = assemble_node(
        context,
        spec,
        node_id=node_id,
        segmentation_overlay_id=segmentation_overlay_id,
        concept_ids=tuple(held_out),
        summary="held-out evaluation",
    )
    return step.diagnostics.unaccounted_column_rate


def assembly_result(
    call_id: str,
    step: ReconstructionStep,
    committed: CommittedProtoInventory,
    spec: ProtoInventorySpec,
    *,
    segmentation_overlay_id: str | None,
    detail: AssemblyDetail,
    context: AgentContext | None = None,
) -> TestProtoAssemblyResult:
    from cognate_reconstruction.agent.tools.commit_reconstruction import inventory_commit_requirements
    missing = inventory_commit_requirements(committed.request.commitments)
    derived = derive_branch_rules(committed.request.commitments, tuple(spec.child_node_ids))
    reports = step.assembly_reports
    if detail is AssemblyDetail.SUMMARY:
        reports = tuple(
            report.model_copy(update={"columns": ()}) for report in reports
        )
    diagnostics = step.diagnostics
    return TestProtoAssemblyResult(
        executable=True,
        commit_ready=not missing,
        missing_commit_requirements=missing,
        witness_evidence_digest=context_evidence_digest(context) if context is not None else None,
        derived_rules_scope=committed.derived_rules_scope,
        evidence_revision=committed.evidence_revision,
        hypothesis_digest=hypothesis_digest(spec, segmentation_overlay_id),
        work=step.diagnostics.assembly_work,
        validation_call_id=call_id,
        covered_set_ids=tuple(
            dict.fromkeys(item.set_id for item in committed.request.commitments)
        ),
        unaccounted_column_rate=diagnostics.unaccounted_column_rate or 0.0,
        cross_branch_assembly_rate=diagnostics.cross_branch_assembly_rate or 0.0,
        ambiguous_columns=tuple(
            column
            for report in step.assembly_reports
            for column in report.columns
            if column.competing_choices or column.competing_set_ids
        ),
        assembled_concept_count=len(step.assembly_reports),
        segmentation_overlay_id=segmentation_overlay_id,
        alignment_overlay_id=spec.alignment_overlay_id,
        residue_policy=spec.residue_policy,
        concepts=reports,
        derived_rules=committed.derived_rules,
        non_invertible_child_ids=committed.non_invertible_child_ids,
        unconditioned_context_child_ids=derived.unconditioned_context_child_ids,
        boundary_change_child_ids=derived.boundary_change_child_ids,
        unspellable_reflex_child_ids=derived.unspellable_reflex_child_ids,
    )


def test_proto_assembly(
    raw_arguments: WorkbenchModel,
    context: AgentContext,
    call_id: str,
) -> TestProtoAssemblyResult:
    arguments = TestProtoAssemblyArgs.model_validate(raw_arguments)
    _validate_residue_policy(
        context, arguments.residue_policy, arguments.residue_witness_child_id
    )
    available = {form.concept_id for form in context.all_forms}
    unknown = sorted(set(arguments.concept_ids) - available)
    if unknown:
        raise ToolInputError(
            f"no form at this node carries concepts: {unknown}",
            code="empty-scope",
            remediation=(
                "list_concepts reports every concept the active children "
                "attest. Omit concept_ids to assemble all of them."
            ),
        )
    spec = ProtoInventorySpec(
        child_node_ids=context.child_ids,
        alignment_overlay_id=arguments.alignment_overlay_id,
        commitments=arguments.commitments,
        shared_claims=arguments.shared_claims,
        residue_policy=arguments.residue_policy,
        residue_witness_child_id=arguments.residue_witness_child_id,
        residue_dispositions=arguments.residue_dispositions,
        restorations=arguments.restorations,
        unit_orders=arguments.unit_orders,
    )
    step, committed = assemble_node(
        context,
        spec,
        node_id=context.node_id,
        segmentation_overlay_id=arguments.segmentation_overlay_id,
        concept_ids=arguments.concept_ids,
    )
    result = assembly_result(
        call_id,
        step,
        committed,
        spec,
        segmentation_overlay_id=arguments.segmentation_overlay_id,
        detail=arguments.detail,
        context=context,
    )
    context.assembly_validations[call_id] = result
    return result


def hypothesis_digest(spec, segmentation_overlay_id):
    fields = ("shared_claims", "commitments", "residue_policy", "residue_witness_child_id",
              "residue_dispositions", "restorations", "unit_orders", "alignment_overlay_id")
    value = spec.model_dump(mode="json", include=set(fields))
    # Commitment order has no linguistic meaning; freeze the actual claims.
    value["commitments"] = sorted(value["commitments"], key=digest)
    for claim in value["shared_claims"]:
        claim["member_set_ids"] = sorted(claim["member_set_ids"])
    value["shared_claims"] = sorted(value["shared_claims"], key=digest)
    return digest([value, segmentation_overlay_id])


def context_evidence_digest(context):
    """Freeze supplementary witnesses/anchors as well as the active-column revision."""
    return digest([context.anchor_policy.value,
        [item.model_dump(mode="json") for item in context.evidence],
        [item.model_dump(mode="json") for item in context.active_anchors]])


def verify_positions(spec, alignment_map):
    for item, index, named in [
        *((d, d.column_index, d.evidence_column_id) for d in spec.residue_dispositions),
        *((r, r.before_column_index, r.before_evidence_column_id) for r in spec.restorations),
    ]:
        relevant = [a for a in alignment_map.alignments if a.concept_id == item.concept_id]
        ids = {a.evidence_columns[index].column_id for a in relevant if index < len(a.evidence_columns)}
        append = any(index == len(a.evidence_columns) for a in relevant)
        if named is not None and named not in ids:
            raise ToolInputError("position names a stale or unrelated evidence column", code="alignment-failed",
                remediation="Use evidence_column_id/before_evidence_column_id from a full preview under these exact overlays and analysis.")
        if named is None and (len(ids) > 1 or (append and ids)):
            raise ToolInputError("position index is ambiguous across candidate analyses", code="alignment-failed",
                remediation="Name evidence_column_id for a disposition or before_evidence_column_id for a restoration from the full preview; token equality and column numbers do not select provenance.")
        if not ids and not (append and hasattr(item, "before_column_index")):
            raise ToolInputError("position is outside the current evidence", code="alignment-failed",
                remediation="Inspect this concept with a full preview and use its exact column IDs/indices.")


__all__ = [
    "assemble_node",
    "assembly_result",
    "held_out_unaccounted_column_rate",
    "test_proto_assembly",
]
