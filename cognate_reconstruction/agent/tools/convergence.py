"""Tell the session what its hypothesis did to the children's agreement.

`test_rule_cascade` and `commit_reconstruction` both answer, deterministically,
the question the model otherwise has to reconstruct by eye from intermediate
forms: after each child's own scoped cascade, do the branches end up saying the
same thing about the parent?

Both funnel through `traversal.convergence.report_convergence`, the same
arithmetic the deterministic step records in `ReconstructionDiagnostics`, so the
number the model reads at commit time and the number in the artifact cannot
disagree.

Nothing here rejects. A commit whose children diverge is accepted exactly as
before; see `docs/report_reject_or_score.md` for why this is a score and a
report rather than a gate.
"""

from __future__ import annotations

from collections.abc import Sequence

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.schemas import (
    ChildConvergenceSummary,
    ConceptConvergenceReport,
    TestRuleCascadeResult,
)
from cognate_reconstruction.schemas.lexicon import LexicalForm
from cognate_reconstruction.schemas.rules import ReconstructionRule
from cognate_reconstruction.traversal.convergence import (
    MAX_REPORTED_DIVERGENT_CONCEPTS,
    report_convergence,
)


def _summarize(
    outputs_by_concept: dict[str, dict[str, tuple[tuple[str, ...], ...]]],
    *,
    include_concepts: bool,
) -> ChildConvergenceSummary:
    report = report_convergence(outputs_by_concept)
    return ChildConvergenceSummary(
        concepts_evaluated=report.concepts_evaluated,
        converged_concepts=report.converged_concept_count,
        child_convergence_rate=report.rate,
        divergent_concept_ids=report.reported_divergent_concept_ids,
        concepts=tuple(
            ConceptConvergenceReport(
                concept_id=concept.concept_id,
                converged=concept.converged,
                parent_forms=concept.parent_forms,
                child_count=concept.child_count,
            )
            for concept in report.concepts
        )
        if include_concepts
        else (),
    )


def cascade_convergence(result: TestRuleCascadeResult) -> ChildConvergenceSummary:
    """Convergence over the forms a cascade preview already produced."""
    outputs_by_concept: dict[str, dict[str, set[tuple[str, ...]]]] = {}
    for final in result.final_forms:
        outputs_by_concept.setdefault(final.form.concept_id, {}).setdefault(
            final.child_id, set()
        ).add(final.form.segments)
    return _summarize(
        {
            concept_id: {
                child_id: tuple(sorted(segments))
                for child_id, segments in by_child.items()
            }
            for concept_id, by_child in outputs_by_concept.items()
        },
        include_concepts=True,
    )


def commit_convergence(
    context: AgentContext,
    parsed_rules: Sequence[ReconstructionRule],
    *,
    segmentation_overlay_id: str | None,
) -> ChildConvergenceSummary:
    """Convergence over every child form under the rules actually committed.

    Runs the committed cascade rather than reusing a cascade preview: a commit
    need not reference one, and when it does the preview may have been scoped to
    a subset of concepts. This is the whole node, which is what the diagnostics
    will record.

    Per-concept detail is omitted; a node over a large lexicon would otherwise
    put its entire concept list into the final tool result the session reads.
    """
    outputs_by_concept: dict[str, dict[str, set[tuple[str, ...]]]] = {}
    for child_id in context.child_ids:
        child_rules = tuple(
            rule.rule for rule in parsed_rules if child_id in rule.source_child_ids
        )
        forms: tuple[LexicalForm, ...] = context.lexicon(
            child_id, segmentation_overlay_id
        ).forms
        if not forms:
            continue
        transformed, _reports = context.rule_engine.apply_rules(child_rules, forms)
        for form in transformed:
            outputs_by_concept.setdefault(form.concept_id, {}).setdefault(
                child_id, set()
            ).add(form.segments)
    return _summarize(
        {
            concept_id: {
                child_id: tuple(sorted(segments))
                for child_id, segments in by_child.items()
            }
            for concept_id, by_child in outputs_by_concept.items()
        },
        include_concepts=False,
    )


__all__ = [
    "MAX_REPORTED_DIVERGENT_CONCEPTS",
    "cascade_convergence",
    "commit_convergence",
]
