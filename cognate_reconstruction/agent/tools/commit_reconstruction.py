"""Validated terminal tool for committing a node reconstruction."""

from __future__ import annotations

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.schemas import (
    CommitReconstructionArgs,
    CommitReconstructionResult,
    CommittedReconstruction,
    CommittedSoundRule,
    TestSoundLawResult,
)
from cognate_reconstruction.agent.tools.errors import (
    ToolInputError,
    parse_rule_or_reject,
)
from cognate_reconstruction.schemas.common import WorkbenchModel
from cognate_reconstruction.schemas.rules import ReconstructionRule


def describe_session_validations(context: AgentContext) -> str:
    """Render the join key between a validation and a committed rule.

    A commit has to reference validations recorded earlier in the same session.
    Listing them as ``(validation_call_id, dsl, source_child_ids)`` triples turns
    that join into a lookup. The text is derived only from recorded session
    state, so it is stable for a given session and safe to store in a
    trajectory.
    """
    lines: list[str] = []
    if context.validations:
        lines.append(
            "Successful test_sound_law validations in this session "
            "(validation_call_id, dsl, source_child_ids):"
        )
        lines.extend(
            f'  - ("{call_id}", "{validation.parsed_rule.source}", '
            f"[{', '.join(validation.source_child_ids)}])"
            + (
                f" tested on overlay {validation.segmentation_overlay_id}"
                if validation.segmentation_overlay_id is not None
                else ""
            )
            for call_id, validation in context.validations.items()
        )
        lines.append(
            "Per-rule validation_call_id is optional: omit it and the harness "
            "resolves the unique same-session validation whose DSL, child "
            "scope, and overlay are identical to the committed rule. "
            "supporting_form_ids may be omitted too; it then defaults to that "
            "validation's forms."
        )
    else:
        lines.append(
            "No test_sound_law validation has succeeded in this session. Every "
            "committed rule needs one; call test_sound_law first, or commit "
            '"rules": [] for an identity reconstruction.'
        )
    if context.cascade_validations:
        lines.append(
            "Successful test_rule_cascade validations "
            "(the only valid cascade_validation_call_id values):"
        )
        lines.extend(
            f'  - "{call_id}" for the order '
            + " then ".join(f'"{rule.rule.source}"' for rule in cascade.rules)
            for call_id, cascade in context.cascade_validations.items()
        )
    else:
        lines.append(
            "No test_rule_cascade call has succeeded in this session, so "
            "cascade_validation_call_id must be omitted."
        )
    return "\n".join(lines)


def _resolve_validation(
    committed: CommittedSoundRule,
    parsed_source: str,
    context: AgentContext,
    overlay_id: str | None,
) -> tuple[str, TestSoundLawResult]:
    """Bind one committed rule to its exact same-session validation.

    Explicit IDs are looked up directly. An omitted ID is resolved only by exact
    equality of DSL, child scope, and segmentation overlay, and only when that
    match is unique: this removes a transcription step, never a check.
    """
    if committed.validation_call_id is not None:
        try:
            return (
                committed.validation_call_id,
                context.validations[committed.validation_call_id],
            )
        except KeyError as error:
            raise ToolInputError(
                f"rule {committed.rule_id!r} references an unknown validation "
                f"call {committed.validation_call_id!r}",
                code="validation-unknown",
                remediation=describe_session_validations(context),
            ) from error
    scope = set(committed.source_child_ids)
    matches = [
        (call_id, validation)
        for call_id, validation in context.validations.items()
        if validation.parsed_rule.source == parsed_source
        and set(validation.source_child_ids) == scope
        and validation.segmentation_overlay_id == overlay_id
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ToolInputError(
            f"rule {committed.rule_id!r} omitted validation_call_id and no "
            "same-session test_sound_law validation matches its exact DSL, "
            "child scope, and segmentation overlay",
            code="validation-unresolved",
            remediation=describe_session_validations(context),
        )
    raise ToolInputError(
        f"rule {committed.rule_id!r} omitted validation_call_id but "
        f"{len(matches)} same-session validations match its DSL, child scope, "
        "and overlay; name the intended one explicitly",
        code="validation-ambiguous",
        remediation=describe_session_validations(context),
    )


def _require_rationales_on_multi_rule_commits(
    rules: tuple[CommittedSoundRule, ...],
) -> None:
    """Require per-rule reasoning exactly where the summary cannot carry it.

    `rationale` is optional in the schema because transcription burden on
    `commit_reconstruction` was the harness's dominant failure mode, and the
    measured friction was entirely on single-rule commits, where the required
    top-level `summary` says everything a per-rule note would.

    A multi-rule commit is the case that argument does not cover: one summary
    cannot attribute reasoning to one of several rules, so a corpus filter would
    have to discard *every* multi-rule commit for missing reasoning. That is a
    worse outcome than one extra required string on the minority call.
    """
    if len(rules) <= 1:
        return
    missing = [rule.rule_id for rule in rules if rule.rationale is None]
    if not missing:
        return
    raise ToolInputError(
        f"{len(missing)} of {len(rules)} committed rules omit 'rationale'. It "
        "is required on every rule of a commit that carries more than one, "
        "because the single top-level 'summary' cannot attribute reasoning to "
        "an individual rule",
        code="missing-rule-rationale",
        remediation=(
            "Add a 'rationale' to each of these rules: "
            + ", ".join(f"{rule_id!r}" for rule_id in missing)
            + ". A one-rule commit still needs none; the 'summary' carries it."
        ),
    )


def commit_reconstruction(
    raw_arguments: WorkbenchModel,
    context: AgentContext,
    call_id: str,  # noqa: ARG001 - uniform tool signature
) -> CommitReconstructionResult:
    arguments = CommitReconstructionArgs.model_validate(raw_arguments)
    if context.commit is not None:
        raise ToolInputError(
            "this node already has a committed reconstruction",
            code="already-committed",
        )
    if arguments.node_id != context.node_id:
        raise ToolInputError(
            f"commit node {arguments.node_id!r} does not match active node {context.node_id!r}",
            code="node-mismatch",
        )
    if (
        arguments.segmentation_overlay_id is not None
        and arguments.segmentation_overlay_id not in context.overlays
    ):
        raise ToolInputError(
            f"unknown segmentation overlay {arguments.segmentation_overlay_id!r}",
            code="unknown-overlay",
        )
    _require_rationales_on_multi_rule_commits(arguments.rules)
    active_children = set(context.child_ids)
    parsed_rules: list[ReconstructionRule] = []
    resolved_rules: list[CommittedSoundRule] = []
    for committed in arguments.rules:
        unknown = sorted(set(committed.source_child_ids) - active_children)
        if unknown:
            raise ToolInputError(
                f"rule {committed.rule_id!r} targets inactive children: {unknown}",
                code="inactive-children",
            )
        parsed = parse_rule_or_reject(committed.dsl, rule_id=committed.rule_id)
        validation_call_id, validation = _resolve_validation(
            committed,
            parsed.source,
            context,
            arguments.segmentation_overlay_id,
        )
        if parsed.source != validation.parsed_rule.source:
            raise ToolInputError(
                f"rule {committed.rule_id!r} was not validated with this exact DSL",
                code="validation-mismatch",
                remediation=describe_session_validations(context),
            )
        if set(committed.source_child_ids) != set(validation.source_child_ids):
            raise ToolInputError(
                f"rule {committed.rule_id!r} was not validated for this child scope",
                code="scope-mismatch",
                remediation=describe_session_validations(context),
            )
        if validation.segmentation_overlay_id != arguments.segmentation_overlay_id:
            raise ToolInputError(
                f"rule {committed.rule_id!r} was not validated on the committed "
                "segmentation overlay",
                code="overlay-mismatch",
                remediation=describe_session_validations(context),
            )
        # Deterministic engine output, not a model claim: an omitted list is
        # filled in from the validation rather than retyped by the model.
        supporting = (
            committed.supporting_form_ids or validation.supporting_form_ids
        )
        unsupported = sorted(
            set(supporting) - set(validation.supporting_form_ids)
        )
        if unsupported:
            raise ToolInputError(
                f"rule {committed.rule_id!r} cites unsupported forms: {unsupported}",
                code="unsupported-forms",
                remediation=(
                    f"validation {validation_call_id!r} supports only "
                    f"{list(validation.supporting_form_ids)}. Omit "
                    "supporting_form_ids to use exactly that list."
                ),
            )
        if not supporting:
            raise ToolInputError(
                f"rule {committed.rule_id!r} applied to no form in validation "
                f"{validation_call_id!r} and cannot be committed",
                code="rule-unsupported",
                remediation=(
                    "Retest the rule against forms it actually changes, widen "
                    "its child scope, or drop it from the commit."
                ),
            )
        resolved_rules.append(
            committed.model_copy(
                update={
                    "validation_call_id": validation_call_id,
                    "supporting_form_ids": tuple(supporting),
                }
            )
        )
        parsed_rules.append(
            ReconstructionRule(
                rule=parsed,
                source_child_ids=committed.source_child_ids,
                confidence=committed.confidence,
            )
        )
    # The stored request records the resolved IDs, so the trajectory stays
    # explicit about which validation backs each committed rule.
    arguments = arguments.model_copy(update={"rules": tuple(resolved_rules)})

    if arguments.cascade_validation_call_id is not None:
        try:
            cascade = context.cascade_validations[
                arguments.cascade_validation_call_id
            ]
        except KeyError as error:
            raise ToolInputError(
                "commit references an unknown cascade validation call; "
                "cascade_validation_call_id must come from a successful "
                "test_rule_cascade result, or be omitted when no cascade "
                "preview was run",
                code="cascade-unknown",
                remediation=describe_session_validations(context),
            ) from error
        if cascade.segmentation_overlay_id != arguments.segmentation_overlay_id:
            raise ToolInputError(
                "ordered cascade was not tested on the committed segmentation overlay",
                code="overlay-mismatch",
            )
        committed_signature = tuple(
            (
                rule.rule.source,
                rule.source_child_ids,
            )
            for rule in parsed_rules
        )
        validated_signature = tuple(
            (
                rule.rule.source,
                rule.source_child_ids,
            )
            for rule in cascade.rules
        )
        if committed_signature != validated_signature:
            raise ToolInputError(
                "committed rule order, DSL, or child scope differs from the "
                "tested cascade",
                code="cascade-signature-mismatch",
                remediation=describe_session_validations(context),
            )

    active_form_ids = {form.form_id for form in context.all_forms} | {
        anchor.form_id for anchor in context.active_anchors
    }
    active_concept_ids = {form.concept_id for form in context.all_forms} | {
        anchor.concept_id for anchor in context.active_anchors
    }
    for anomaly in arguments.anomalies:
        if anomaly.form_id is not None and anomaly.form_id not in active_form_ids:
            raise ToolInputError(
                f"anomaly references unknown form {anomaly.form_id!r}",
                code="anomaly-unknown-reference",
            )
        if anomaly.concept_id is not None and anomaly.concept_id not in active_concept_ids:
            raise ToolInputError(
                f"anomaly references unknown concept {anomaly.concept_id!r}",
                code="anomaly-unknown-reference",
            )

    reconstruction = CommittedReconstruction(
        request=arguments,
        parsed_rules=tuple(parsed_rules),
    )
    context.commit = reconstruction
    return CommitReconstructionResult(reconstruction=reconstruction)
