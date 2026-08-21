"""Measure a hypothesis on the concepts the session was not reasoning about.

Every other number in a rule report is computed over the forms the model chose
to look at, which is exactly the evidence a rule was fitted to. A rule
generalised from one word therefore scores perfectly on the evidence that
produced it and nothing said otherwise. This runs the same rules over the
node's held-out concepts — a deterministic split seeded from the node ID, see
`agent/holdout.py` — and reports what happens.

It is a report. A rule that never fires on a held-out form may be perfectly
correct and narrowly conditioned; children that still disagree over the
held-out concepts may be an honest residue. Nothing here rejects, exactly as
nothing rejects on divergence; see `docs/report_reject_or_score.md`.
"""

from __future__ import annotations

from collections.abc import Sequence

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.schemas import (
    MAX_REPORTED_HELD_OUT_CONCEPTS,
    HeldOutEvaluation,
)
from cognate_reconstruction.agent.tools.convergence import summarize_outputs
from cognate_reconstruction.schemas.rules import ApplicationStatus, ReconstructionRule


def held_out_evaluation(
    context: AgentContext,
    rules: Sequence[ReconstructionRule],
    *,
    segmentation_overlay_id: str | None,
) -> HeldOutEvaluation | None:
    """Apply `rules` to the held-out concepts alone and summarise the result.

    Returns `None` when the node held nothing out, which happens only when it
    has a single concept: there is no second concept to withhold, and reporting
    an empty evaluation would read as a hypothesis that failed everywhere.
    """
    split = context.concept_split
    held_out = split.held_out
    if not held_out:
        return None
    forms_evaluated = 0
    applications = 0
    target_absent = 0
    context_mismatches = 0
    outputs: dict[str, dict[str, set[tuple[str, ...]]]] = {}
    for child_id in context.child_ids:
        forms = tuple(
            form
            for form in context.lexicon(child_id, segmentation_overlay_id).forms
            if form.concept_id in held_out
        )
        if not forms:
            continue
        child_rules = tuple(
            rule.rule for rule in rules if child_id in rule.source_child_ids
        )
        transformed, reports = context.rule_engine.apply_rules(child_rules, forms)
        for report in reports:
            for result in report.results:
                forms_evaluated += 1
                if result.locations:
                    applications += 1
                if result.status is ApplicationStatus.TARGET_ABSENT:
                    target_absent += 1
                elif result.status is ApplicationStatus.CONTEXT_MISMATCH:
                    context_mismatches += 1
        for form in transformed:
            outputs.setdefault(form.concept_id, {}).setdefault(
                child_id, set()
            ).add(form.segments)
    convergence = summarize_outputs(
        {
            concept_id: {
                child_id: tuple(sorted(segments))
                for child_id, segments in by_child.items()
            }
            for concept_id, by_child in outputs.items()
        },
        include_concepts=False,
    )
    return HeldOutEvaluation(
        concept_count=len(split.held_out_concept_ids),
        concepts_evaluated=len(outputs),
        forms_evaluated=forms_evaluated,
        applications=applications,
        target_absent=target_absent,
        context_mismatches=context_mismatches,
        convergence=convergence,
        held_out_concept_ids=split.held_out_concept_ids[
            :MAX_REPORTED_HELD_OUT_CONCEPTS
        ],
    )


__all__ = ["held_out_evaluation"]
