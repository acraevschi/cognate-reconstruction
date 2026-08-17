"""Aggregate n-way alignments into correspondence sets by support.

A comparative linguist works from correspondence *sets*: the n-tuple of aligned
segments across every daughter, and how often it recurs. Alignments alone do not
show recurrence, and asking for them in batches hides it — the whole inventory
over every cognate set is both smaller and more decidable than a handful of
alignments over a few concepts.

This is pure aggregation over an existing `MultipleAlignmentMap`; it runs no
aligner of its own and imports no LingPy. `tools/correspondence_inventory.py` is
the prototype it was derived from and produces the same sets.
"""

from __future__ import annotations

from collections.abc import Sequence

from cognate_reconstruction.schemas.alignment import (
    MAX_CORRESPONDENCE_EXAMPLES,
    CorrespondenceInventory,
    CorrespondenceSet,
    MultipleAlignmentMap,
)


def _sort_key(item: CorrespondenceSet) -> tuple[int, tuple[str, ...]]:
    """Order by descending support, then by rendered segments.

    Segments hold `None` for a gap and cannot be compared against strings, so
    the tie-break renders a gap as the empty string. The tie-break exists only
    to make the order total: two sets with equal support have no evidential
    ranking between them, and an arbitrary-but-stable order is preferable to one
    that depends on dictionary insertion.
    """
    return (
        -item.support,
        tuple("" if segment is None else segment for segment in item.segments),
    )


def build_correspondence_sets(
    alignment_map: MultipleAlignmentMap,
    *,
    node_ids: Sequence[str] | None = None,
    max_example_concepts: int = MAX_CORRESPONDENCE_EXAMPLES,
) -> CorrespondenceInventory:
    """Build the complete correspondence-set inventory over one alignment map.

    `node_ids` fixes the column order of every set and defaults to the map's own
    `variety_ids`. Anchor members are excluded: an anchor is supplementary
    evidence, and letting one into a support count would make the count depend on
    whether an anchor happened to be supplied.
    """
    if max_example_concepts < 0:
        raise ValueError("max_example_concepts must be non-negative")
    columns = tuple(node_ids) if node_ids is not None else alignment_map.variety_ids
    if len(columns) < 2 or len(set(columns)) != len(columns):
        raise ValueError("a correspondence inventory needs at least two distinct nodes")

    selected = set(columns)
    supports: dict[tuple[str | None, ...], int] = {}
    concepts: dict[tuple[str | None, ...], list[str]] = {}
    for alignment in alignment_map.alignments:
        # One node may contribute several members to a cognate set through
        # synonyms or partial memberships; the last one wins, as in the
        # prototype. Enumerating their product would multiply the inventory by a
        # data property rather than a linguistic one.
        rows = {
            member.variety_id: member.aligned_segments
            for member in alignment.members
            if not member.is_anchor and member.variety_id in selected
        }
        if len(rows) < 2:
            continue
        width = len(next(iter(rows.values())))
        for column in range(width):
            key = tuple(rows[node][column] if node in rows else None for node in columns)
            if all(segment is None for segment in key):
                continue
            supports[key] = supports.get(key, 0) + 1
            seen = concepts.setdefault(key, [])
            if alignment.concept_id not in seen:
                seen.append(alignment.concept_id)

    sets = sorted(
        (
            CorrespondenceSet(
                segments=key,
                support=support,
                concept_count=len(concepts[key]),
                example_concept_ids=tuple(concepts[key][:max_example_concepts]),
            )
            for key, support in supports.items()
        ),
        key=_sort_key,
    )
    return CorrespondenceInventory(
        node_ids=tuple(columns),
        alignment_count=len(alignment_map.alignments),
        sets=tuple(sets),
    )
