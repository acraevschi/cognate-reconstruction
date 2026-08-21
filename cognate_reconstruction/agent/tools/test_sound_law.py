"""Adapter for strict parsing and exact deterministic rule diffs."""

from __future__ import annotations

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.schemas import (
    TestSoundLawArgs,
    TestSoundLawResult,
    derive_rule_id,
)
from cognate_reconstruction.agent.tools.contrast import (
    contrast_reduction_reports,
)
from cognate_reconstruction.agent.tools.errors import (
    ToolInputError,
    parse_rule_or_reject,
)
from cognate_reconstruction.agent.tools.heldout import held_out_evaluation
from cognate_reconstruction.schemas.common import WorkbenchModel
from cognate_reconstruction.schemas.rules import ReconstructionRule


def test_sound_law(
    raw_arguments: WorkbenchModel,
    context: AgentContext,
    call_id: str,
) -> TestSoundLawResult:
    arguments = TestSoundLawArgs.model_validate(raw_arguments)
    unknown = sorted(set(arguments.source_child_ids) - set(context.child_ids))
    if unknown:
        raise ToolInputError(
            f"rule targets inactive children: {unknown}",
            code="inactive-children",
        )
    # The ID a commit of this rule would carry, so the contrast report here
    # and the rejection there name the same rule.
    rule = parse_rule_or_reject(
        arguments.dsl,
        rule_id=derive_rule_id(arguments.dsl, arguments.source_child_ids),
    )
    selected_concepts = set(arguments.concept_ids)
    forms = tuple(
        form
        for child_id in arguments.source_child_ids
        for form in context.lexicon(
            child_id, arguments.segmentation_overlay_id
        ).forms
        if not selected_concepts or form.concept_id in selected_concepts
    )
    if not forms:
        raise ToolInputError(
            "no forms matched the requested child and concept scope",
            code="empty-scope",
        )
    anchors_by_concept: dict[str, dict[str, tuple[str, ...]]] = {}
    for anchor in context.active_anchors:
        anchors_by_concept.setdefault(anchor.concept_id, {})[anchor.form_id] = anchor.segments
    anchor_expected = {
        form.form_id: anchors_by_concept.get(form.concept_id, {}) for form in forms
    }
    report = context.rule_engine.apply_rule(
        rule,
        forms,
        anchor_expected=anchor_expected,
    )
    supporting = tuple(result.form_id for result in report.results if result.locations)
    # Both are measured over the node rather than over the requested selection:
    # a rule tested on one concept is exactly the rule whose behaviour outside
    # that concept nobody had reported.
    scoped = (
        ReconstructionRule(
            rule=rule,
            source_child_ids=arguments.source_child_ids,
            # A single test is mechanical; confidence belongs to the commit.
            confidence=1.0,
        ),
    )
    reductions = contrast_reduction_reports(
        context,
        scoped,
        segmentation_overlay_id=arguments.segmentation_overlay_id,
    )
    result = TestSoundLawResult(
        validation_call_id=call_id,
        parsed_rule=rule,
        source_child_ids=arguments.source_child_ids,
        segmentation_overlay_id=arguments.segmentation_overlay_id,
        report=report,
        supporting_form_ids=supporting,
        contrast_reduction=reductions[0] if reductions else None,
        held_out=held_out_evaluation(
            context,
            scoped,
            segmentation_overlay_id=arguments.segmentation_overlay_id,
        ),
    )
    context.validations[call_id] = result
    return result
