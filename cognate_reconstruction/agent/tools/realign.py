"""Re-lay the aligner's columns for concepts it got wrong.

Alignment is load-bearing under the per-set protocol in a way it is not under
branch cascades. A bad alignment used to cost the model a confusing evidence
view; under assembly it costs the model the answer, because the columns *are*
the reconstruction. Concept `1217` FATHER is the measured case: SCA aligns
`m a t u a` against `t a m a` into non-overlapping columns and no assembly over
those columns can reach `t a m a + n a`.

So the columns are correctable, under four constraints in increasing order of how
much they do.

1. **The rows must be the children's own forms.** Dropping the gaps from each row
   must reproduce that child's form under the current segmentation overlay, token
   for token. Material may be moved between columns; it may not be invented,
   deleted, or reordered. The same discipline `segment_morphemes` imposes, one
   level up, and checkable arithmetic rather than judgement.
2. **An override is per concept, never a rule about the evidence.** There is no
   way to say "always align `ʔ` against a gap". Overrides are session-local,
   never cross a node boundary, never enter the checkpoint, and never persist
   into another run.
3. **A realignment must say which set it joins, and the claim is verified.** This
   is the constraint that does the real work, and the reason it is the right
   lever where a bare count is not: *forcing a convenient answer and repairing a
   misalignment look different to this check.* A genuine repair moves a column
   into an already-recurrent correspondence — that is what noticing a
   correspondence *is*. Fitting the alignment to a desired proto-form almost
   always produces a column pattern nothing else in the lexicon shows. So the
   check lets a model realign *toward* established evidence and makes realigning
   *away* from it expensive, which is the asymmetry the comparative method itself
   runs on.
4. **No cap. A soft advisory, and an instruction.** A hard budget was drafted and
   dropped, because how many repairs a node legitimately needs is a property of
   how well SCA handles that family's phonology, which no quantity the harness
   can see predicts — a fixed cap would be tight exactly where repairs are most
   needed. What stands in for it is constraint 3, which scales with the evidence
   rather than with a constant, plus the advisory this tool always returns and
   prominent counters in the diagnostics.

The residual risk is stated rather than engineered away: constraint 3 makes it
hard to fit an alignment to a preferred answer, and nothing makes it impossible.
One hand-aligned concept with a stated rationale is what a linguist does; forty
of them is a different object, and the advisory and the counters are what make
the difference legible to a reader.
"""

from __future__ import annotations

from collections.abc import Sequence

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.schemas import RealignArgs, RealignResult
from cognate_reconstruction.agent.tools.errors import ToolInputError
from cognate_reconstruction.agent.tools.inventory_evidence import node_inventory
from cognate_reconstruction.schemas.common import WorkbenchModel
from cognate_reconstruction.schemas.inventory import AlignmentOverride


def _check_rows_are_the_childrens_forms(
    context: AgentContext,
    override: AlignmentOverride,
    segmentation_overlay_id: str | None,
) -> None:
    """Constraint 1: gapless rows must reproduce each child's form exactly."""
    if len(override.rows) != len(context.child_ids):
        raise ToolInputError(
            f"the override for concept {override.concept_id!r} has "
            f"{len(override.rows)} rows; this node has "
            f"{len(context.child_ids)} active children",
            code="overlay-invalid-edit",
            remediation=(
                "Rows are positional against the active children, in this "
                "order: " + ", ".join(context.child_ids) + ". A child that does "
                "not attest the concept gets a row of nulls."
            ),
        )
    for child_id, row in zip(context.child_ids, override.rows, strict=True):
        gapless = tuple(segment for segment in row if segment is not None)
        forms = [
            form
            for form in context.lexicon(child_id, segmentation_overlay_id).forms
            if form.concept_id == override.concept_id
        ]
        attested = {form.phonetic_segments for form in forms}
        if not gapless:
            if attested:
                raise ToolInputError(
                    f"the override for concept {override.concept_id!r} gives "
                    f"{child_id!r} an all-gap row, but it attests "
                    f"{sorted(attested)}",
                    code="overlay-invalid-edit",
                    remediation=(
                        "An all-gap row deletes a child's whole form from the "
                        "alignment, which is not a realignment. Place the "
                        "child's segments in whichever columns you mean."
                    ),
                )
            continue
        if gapless not in attested:
            raise ToolInputError(
                f"the override for concept {override.concept_id!r} gives "
                f"{child_id!r} the segments {list(gapless)}, which is not a "
                f"form it attests: {sorted(attested)}",
                code="overlay-invalid-edit",
                remediation=(
                    "Dropping the nulls from a row must reproduce that child's "
                    "own form, token for token. You may move material between "
                    "columns; you may not invent, delete, or reorder a segment. "
                    "Morphological boundaries are not part of an alignment row."
                ),
            )


def realign(
    raw_arguments: WorkbenchModel,
    context: AgentContext,
    call_id: str,  # noqa: ARG001 - uniform tool signature
) -> RealignResult:
    arguments = RealignArgs.model_validate(raw_arguments)
    concepts = [override.concept_id for override in arguments.overrides]
    if len(concepts) != len(set(concepts)):
        raise ToolInputError(
            "a realign request may re-lay each concept only once",
            code="overlay-invalid-edit",
            remediation=(
                "Put every column of one concept into a single override. Two "
                "overrides for one concept cannot both be applied."
            ),
        )
    available = {form.concept_id for form in context.all_forms}
    unknown = sorted(set(concepts) - available)
    if unknown:
        raise ToolInputError(
            f"no form at this node carries concepts: {unknown}",
            code="empty-scope",
        )
    for override in arguments.overrides:
        _check_rows_are_the_childrens_forms(
            context, override, arguments.segmentation_overlay_id
        )

    before, _map = node_inventory(
        context,
        segmentation_overlay_id=arguments.segmentation_overlay_id,
        alignment_overlay_id=arguments.base_alignment_overlay_id,
    )
    overlay_id = context.store_alignment_overlay(
        arguments.overrides,
        base_overlay_id=arguments.base_alignment_overlay_id,
    )
    after, _map = node_inventory(
        context,
        segmentation_overlay_id=arguments.segmentation_overlay_id,
        alignment_overlay_id=overlay_id,
    )
    delta = _verify_joins(arguments.overrides, before, after, context, overlay_id)

    invalidated = tuple(
        item.set_id
        for item in before.sets
        if item.set_id not in {other.set_id for other in after.sets}
    )
    overrides = context.alignment_overrides(overlay_id)
    node_concepts = len(available)
    return RealignResult(
        alignment_overlay_id=overlay_id,
        joined_set_support_delta=delta,
        invalidated_set_ids=invalidated,
        override_concept_count=len(overrides),
        node_concept_count=node_concepts,
        new_set_override_count=sum(
            override.joins_set_id is None for override in overrides
        ),
        advisory=_advisory(len(overrides), node_concepts, len(invalidated)),
    )


def _verify_joins(
    overrides: Sequence[AlignmentOverride],
    before,
    after,
    context: AgentContext,
    overlay_id: str,
) -> dict[str, int]:
    """Constraint 3: a named set must actually gain support.

    Refused rather than reported, because this is the check that separates a
    repair from a fit. The overlay is discarded on refusal — an overlay a commit
    could cite while its own claim was refuted would be worse than no overlay.
    """
    support_before = {item.set_id: item.support for item in before.sets}
    support_after = {item.set_id: item.support for item in after.sets}
    delta: dict[str, int] = {}
    for override in overrides:
        named = override.joins_set_id
        if named is None:
            continue
        gained = support_after.get(named, 0) - support_before.get(named, 0)
        delta[named] = gained
        if gained > 0:
            continue
        del context.alignment_overlays[overlay_id]
        raise ToolInputError(
            f"the realignment of concept {override.concept_id!r} claims to join "
            f"set {named!r}, which gained {gained} column(s) of support",
            code="realignment-does-not-join-set",
            remediation=(
                "A realignment that joins a set moves a column into a "
                "correspondence the lexicon already shows elsewhere — which is "
                "what noticing a correspondence is. If the column you moved "
                "belongs to a pattern nothing else attests, that is a legitimate "
                "first attestation: set joins_set_id to null, which is counted "
                "separately as a new-set override. If the set ID is stale, "
                "re-run summarize_correspondences under the overlay you are "
                "building on."
                + (
                    f" Set {named!r} is not in this node's data at all."
                    if named not in support_before and named not in support_after
                    else f" Its support went "
                    f"{support_before.get(named, 0)} → "
                    f"{support_after.get(named, 0)}."
                )
            ),
        )
    return delta


def _advisory(overrides: int, node_concepts: int, invalidated: int) -> str:
    """The soft line this tool always returns, modelled on `contrast_reduction`.

    It refuses nothing. It is the repo's existing pattern for "this is
    legitimate, common, and worth your attention before you commit":
    `test_sound_law` already reports that a rule discards `ʔ` attested in 3 of 10
    nodes and refuses nothing.
    """
    line = (
        f"{overrides} of {node_concepts} concept(s) at this node now carry an "
        "alignment override."
    )
    if invalidated:
        line += (
            f" {invalidated} correspondence set ID(s) derived under the previous "
            "alignment no longer exist; cite IDs from a survey taken under this "
            "overlay."
        )
    line += (
        " Realigning is for the case where the aligner has misaligned a form — "
        "a compound against a simplex, two lexemes in one concept — and not a "
        "routine step. A session realigning a large share of its concepts is "
        "fitting the evidence rather than reading it, and the count is recorded "
        "where a reviewer sees it."
    )
    return line


__all__ = ["realign"]
