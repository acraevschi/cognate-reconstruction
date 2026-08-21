"""Report what a hypothesis gives up, and who else still shows it.

`rules/contrast.py` decides, mechanically, whether a rule deletes material or
merges two distinct sequences into one. This turns that into something a
session and a reviewer can read: which rule, which children, which segments,
and how many of the node's available nodes still attest the material being
discarded.

The count is a count. "This rule removes `ʔ`, attested in 3 of 10 available
nodes" is a fact about the evidence, not a claim about sound change — contrast
loss is ordinary and a harness that forbade it would be wrong. What the report
does buy is that the one rule the harness can never undo for the model is
visible at the moment it is proposed, and that a commit carrying one has to say
which branch innovated. See `docs/report_reject_or_score.md`.
"""

from __future__ import annotations

from collections.abc import Sequence

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.schemas import (
    MAX_REPORTED_ATTESTING_NODES,
    ContrastReductionReport,
)
from cognate_reconstruction.rules.contrast import (
    ContrastReduction,
    cascade_contrast_reductions,
)
from cognate_reconstruction.schemas.lexicon import LanguageLexicon
from cognate_reconstruction.schemas.traversal import EvidenceKind


def _contains(sequence: tuple[str, ...], pattern: tuple[str, ...]) -> bool:
    width = len(pattern)
    if not width:
        return False
    return any(
        sequence[index : index + width] == pattern
        for index in range(len(sequence) - width + 1)
    )


def _attests(lexicon: LanguageLexicon, segments: tuple[str, ...]) -> bool:
    return any(_contains(form.segments, segments) for form in lexicon.forms)


def _render(segments: Sequence[str]) -> str:
    return " ".join(segments) if segments else "Ø"


def _note(
    reduction: ContrastReduction,
    attesting: Sequence[str],
    observed_count: int,
    available_count: int,
) -> str:
    scope = ", ".join(reduction.source_child_ids) or "the scoped children"
    discarded = _render(reduction.discarded_segments)
    if reduction.deletes:
        action = f'"{reduction.source}" deletes {discarded} from [{scope}]'
    else:
        action = (
            f'"{reduction.source}" merges {discarded} into '
            f"{_render(reduction.merged_into)} for [{scope}]"
        )
    if not attesting:
        return (
            f"{action}; no node in the available evidence attests {discarded} "
            f"({available_count} available)"
        )
    shown = attesting[:MAX_REPORTED_ATTESTING_NODES]
    listed = ", ".join(shown)
    named = f"including {listed}" if len(shown) < len(attesting) else listed
    return (
        f"{action}; {discarded} is attested in {len(attesting)} of "
        f"{available_count} available nodes ({observed_count} observed): "
        f"{named}"
    )


def _report(
    context: AgentContext,
    reduction: ContrastReduction,
) -> ContrastReductionReport:
    kinds = {item.node_id: item.kind for item in context.evidence}
    attesting = [
        lexicon.variety_id
        for lexicon in context.available_lexicons
        if _attests(lexicon, reduction.discarded_segments)
    ]
    observed = [
        node_id
        for node_id in attesting
        # A context built without an evidence set has only observed children.
        if kinds.get(node_id, EvidenceKind.OBSERVED) is EvidenceKind.OBSERVED
    ]
    available_count = len(context.available_lexicons)
    return ContrastReductionReport(
        rule_id=reduction.rule_id,
        dsl=reduction.source,
        source_child_ids=reduction.source_child_ids,
        deletes=reduction.deletes,
        merges=reduction.merges,
        discarded_segments=reduction.discarded_segments,
        merged_into=reduction.merged_into,
        attesting_node_ids=tuple(attesting[:MAX_REPORTED_ATTESTING_NODES]),
        attesting_node_count=len(attesting),
        observed_attesting_node_count=len(observed),
        available_node_count=available_count,
        note=_note(reduction, attesting, len(observed), available_count),
    )


def contrast_reduction_reports(
    context: AgentContext,
    rules: Sequence,
    *,
    segmentation_overlay_id: str | None,
) -> tuple[ContrastReductionReport, ...]:
    """Every rule of an ordered cascade that removes a distinction, in order.

    Each child is walked through its own scoped subsequence, so a rule sees the
    forms the cascade will actually hand it rather than the child's
    untransformed lexicon.
    """
    forms_by_child = {
        child_id: context.lexicon(child_id, segmentation_overlay_id).forms
        for child_id in context.child_ids
    }
    return tuple(
        _report(context, reduction)
        for reduction in cascade_contrast_reductions(
            rules, forms_by_child, engine=context.rule_engine
        )
    )


__all__ = ["contrast_reduction_reports"]
