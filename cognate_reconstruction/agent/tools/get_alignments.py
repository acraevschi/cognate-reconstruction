"""Adapter exposing pairwise LingPy alignments to the agent."""

from __future__ import annotations

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.schemas import GetAlignmentsArgs, GetAlignmentsResult
from cognate_reconstruction.agent.tools.errors import ToolInputError
from cognate_reconstruction.schemas.common import WorkbenchModel


def get_alignments(
    raw_arguments: WorkbenchModel,
    context: AgentContext,
    call_id: str,  # noqa: ARG001 - uniform tool signature
) -> GetAlignmentsResult:
    arguments = GetAlignmentsArgs.model_validate(raw_arguments)
    selected = set(arguments.concept_ids)
    selected_forms = set(arguments.form_ids)
    lexicons = []
    for node_id in arguments.node_ids:
        lexicon = context.evidence_lexicon(
            node_id, arguments.segmentation_overlay_id
        )
        if selected or selected_forms:
            lexicon = lexicon.model_copy(
                update={
                    "forms": tuple(
                        form
                        for form in lexicon.forms
                        if (not selected or form.concept_id in selected)
                        and (not selected_forms or form.form_id in selected_forms)
                    )
                }
            )
        lexicons.append(lexicon)
    anchors = (
        tuple(
            anchor
            for anchor in context.active_anchors
            if (not selected or anchor.concept_id in selected)
            and (not selected_forms or anchor.form_id in selected_forms)
        )
        if arguments.include_anchors
        else ()
    )
    # The aligner is deterministic core and knows nothing about tool codes, so
    # the code is attached here at the boundary, as with rule parsing. Without
    # it a refused selection would be the one remaining `unclassified` path a
    # model can reach.
    try:
        alignment_map = context.aligner.align_multiple(
            lexicons,
            anchors,
            respect_cognate_sets=arguments.respect_cognate_sets,
        )
    except ToolInputError:
        raise
    except ValueError as error:
        raise ToolInputError(str(error), code="alignment-failed") from error
    return GetAlignmentsResult(
        alignment_map=alignment_map,
        segmentation_overlay_id=arguments.segmentation_overlay_id,
    )
