"""Preview an ordered, branch-scoped rule cascade over the full selected data."""

from __future__ import annotations

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.schemas import (
    CascadeFinalForm,
    TestRuleCascadeArgs,
    TestRuleCascadeResult,
)
from cognate_reconstruction.agent.tools.errors import (
    ToolInputError,
    parse_rule_or_reject,
)
from cognate_reconstruction.schemas.common import WorkbenchModel
from cognate_reconstruction.schemas.rules import ReconstructionRule


def test_rule_cascade(
    raw_arguments: WorkbenchModel,
    context: AgentContext,
    call_id: str,
) -> TestRuleCascadeResult:
    arguments = TestRuleCascadeArgs.model_validate(raw_arguments)
    active_children = set(context.child_ids)
    parsed = tuple(
        ReconstructionRule(
            rule=parse_rule_or_reject(spec.dsl, rule_id=spec.rule_id),
            source_child_ids=spec.source_child_ids,
            # Preview is mechanical; confidence belongs to the later commit.
            confidence=1.0,
        )
        for spec in arguments.rules
    )
    for rule in parsed:
        unknown = sorted(set(rule.source_child_ids) - active_children)
        if unknown:
            raise ToolInputError(
                f"cascade rule {rule.rule.rule_id!r} targets inactive children: "
                f"{unknown}",
                code="inactive-children",
            )

    selected_concepts = set(arguments.concept_ids)
    anchors_by_concept: dict[str, dict[str, tuple[str, ...]]] = {}
    for anchor in context.active_anchors:
        anchors_by_concept.setdefault(anchor.concept_id, {})[
            anchor.form_id
        ] = anchor.segments

    reports = []
    final_forms = []
    for child_id in context.child_ids:
        child_rules = tuple(
            rule.rule for rule in parsed if child_id in rule.source_child_ids
        )
        forms = tuple(
            form
            for form in context.lexicon(
                child_id,
                arguments.segmentation_overlay_id,
            ).forms
            if not selected_concepts or form.concept_id in selected_concepts
        )
        if not forms:
            continue
        anchor_expected = {
            form.form_id: anchors_by_concept.get(form.concept_id, {})
            for form in forms
        }
        transformed, child_reports = context.rule_engine.apply_rules(
            child_rules,
            forms,
            anchor_expected=anchor_expected,
        )
        reports.extend(child_reports)
        final_forms.extend(
            CascadeFinalForm(child_id=child_id, form=form) for form in transformed
        )
    if not final_forms:
        raise ToolInputError(
            "no forms matched the requested cascade scope",
            code="empty-scope",
        )
    result = TestRuleCascadeResult(
        validation_call_id=call_id,
        rules=parsed,
        segmentation_overlay_id=arguments.segmentation_overlay_id,
        reports=tuple(reports),
        final_forms=tuple(final_forms),
    )
    context.cascade_validations[call_id] = result
    return result
