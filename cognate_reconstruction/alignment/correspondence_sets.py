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

from cognate_reconstruction.alignment.environments import (
    context_tokens,
    observed_readings,
)
from cognate_reconstruction.schemas.alignment import (
    MAX_CORRESPONDENCE_EXAMPLES,
    ComplementaryCandidate,
    CorrespondenceInventory,
    CorrespondenceSet,
    MultipleAlignmentMap,
)
from cognate_reconstruction.schemas.inventory import derive_set_id
from cognate_reconstruction.schemas.lexicon import LanguageLexicon

MAX_COMPLEMENTARY_CANDIDATES = 20
"""Complementary pairs one report carries before it is truncated.

Bounded for the same reason every other survey output is: on the Polynesian
benchmark 41 sets clear `min_support = 2`, and most of the 820 pairs among them
are trivially complementary because most sets occur in a handful of words. The
count of pairs found is reported beside the sample, so the truncation is never
silent, and the sample is ordered by combined support so the pairs a reader is
most likely to care about survive it.
"""


def _column_rows(
    alignment,
    columns: Sequence[str],
) -> tuple[tuple[str | None, ...], ...] | None:
    """One row per selected node, or `None` when fewer than two are present.

    One node may contribute several members to a cognate set through synonyms or
    partial memberships; the last one wins, as in
    `tools/correspondence_inventory.py`. Enumerating their product would
    multiply the inventory by a data property rather than a linguistic one.
    """
    rows = {
        member.variety_id: member.aligned_segments
        for member in alignment.members
        if not member.is_anchor and member.variety_id in set(columns)
    }
    if len(rows) < 2:
        return None
    width = len(next(iter(rows.values())))
    return tuple(
        tuple(rows[node][index] if node in rows else None for index in range(width))
        for node in columns
    )


def one_reading_per_node(
    lexicons: Sequence[LanguageLexicon],
) -> tuple[LanguageLexicon, ...]:
    """Keep one form per node per (concept, cognate set), the first listed.

    **A correspondence is between the languages' reported forms**, and this is
    what makes that true of the alignment as well as of the counts. Without it,
    a node contributing several readings of one concept — synonyms at a leaf,
    and *every* retained candidate at a reconstructed internal node — puts all
    of them into one MSA, and `build_correspondence_sets` then keeps one row out
    of the several. Aligning ten alternative readings of a concept and reporting
    one of their rows is not a correspondence between two languages; it is a
    correspondence between one language and an aggregate of another's guesses.

    It is also what makes the set IDs a model is handed *reproducible by the
    assembler*, which aligns one candidate per child. Same strings, same order,
    same columns, so a set cited from the survey is a set the assembler can
    match. Without the reduction the two see different columns at every internal
    node and nothing a model commits would ever match — which would read as the
    mechanism never firing.

    The first form is kept rather than the last because `beam_to_lexicon` emits
    a reconstructed node's candidates in beam order, so the first is the form
    that node reports. At an observed leaf with two synonyms in one cognate set
    the choice is arbitrary and stable, exactly as
    `build_correspondence_sets`'s own last-one-wins convention was.
    """
    reduced = []
    for lexicon in lexicons:
        seen: set[tuple[str, str | None]] = set()
        forms = []
        for form in lexicon.forms:
            key = (form.concept_id, form.cognate_set_id)
            if key in seen:
                continue
            seen.add(key)
            forms.append(form)
        reduced.append(lexicon.model_copy(update={"forms": tuple(forms)}))
    return tuple(reduced)


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
    segmentation_overlay_id: str | None = None,
    alignment_overlay_id: str | None = None,
) -> CorrespondenceInventory:
    """Build the complete correspondence-set inventory over one alignment map.

    `node_ids` fixes the column order of every set and defaults to the map's own
    `variety_ids`. Anchor members are excluded: an anchor is supplementary
    evidence, and letting one into a support count would make the count depend on
    whether an anchor happened to be supplied.

    The two overlay IDs enter every set's `set_id` and nothing else. Both belong
    in the digest because a segmentation overlay changes what a segment is and
    an alignment overlay changes which columns exist, so either changes what a
    set *is*. Callers that are not building an ID a commit will cite may leave
    them alone.
    """
    if max_example_concepts < 0:
        raise ValueError("max_example_concepts must be non-negative")
    columns = tuple(node_ids) if node_ids is not None else alignment_map.variety_ids
    if len(columns) < 2 or len(set(columns)) != len(columns):
        raise ValueError("a correspondence inventory needs at least two distinct nodes")

    supports: dict[tuple[str | None, ...], int] = {}
    concepts: dict[tuple[str | None, ...], list[str]] = {}
    for alignment in alignment_map.alignments:
        node_rows = _column_rows(alignment, columns)
        if node_rows is None:
            continue
        for column in range(len(node_rows[0])):
            key = tuple(row[column] for row in node_rows)
            if all(segment is None for segment in key):
                continue
            supports[key] = supports.get(key, 0) + 1
            seen = concepts.setdefault(key, [])
            if alignment.concept_id not in seen:
                seen.append(alignment.concept_id)

    sets = sorted(
        (
            CorrespondenceSet(
                set_id=derive_set_id(
                    key,
                    columns,
                    segmentation_overlay_id=segmentation_overlay_id,
                    alignment_overlay_id=alignment_overlay_id,
                ),
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


def _set_contexts(
    alignment_map: MultipleAlignmentMap,
    columns: tuple[str, ...],
) -> dict[tuple[str | None, ...], tuple[set[str], set[str]]]:
    """Per reflex tuple, the tokens observed to its left and to its right.

    Adjacency is `alignment/environments.py`'s single definition: the columns of
    one alignment in order, skipping every column no node shows a segment in,
    with a word edge contributing `#`. That is the same walk
    `non-complementary-split` rejects under and the same one the assembler
    resolves a conditioned column with, which is the whole reason this is not
    computed locally here.
    """
    contexts: dict[tuple[str | None, ...], tuple[set[str], set[str]]] = {}
    for alignment in alignment_map.alignments:
        node_rows = _column_rows(alignment, columns)
        if node_rows is None:
            continue
        readings = observed_readings(node_rows)
        for column in range(len(node_rows[0])):
            key = tuple(row[column] for row in node_rows)
            if all(segment is None for segment in key):
                continue
            left, right = context_tokens(readings, column)
            entry = contexts.setdefault(key, (set(), set()))
            entry[0].update(left)
            entry[1].update(right)
    return contexts


def complementary_candidates(
    alignment_map: MultipleAlignmentMap,
    sets: Sequence[CorrespondenceSet],
    *,
    node_ids: Sequence[str],
    limit: int = MAX_COMPLEMENTARY_CANDIDATES,
) -> tuple[tuple[ComplementaryCandidate, ...], int]:
    """Pairs of `sets` whose occurrences never share an environment.

    Returns the bounded sample and the total number of pairs found, so a reader
    always knows whether the list was truncated.

    Complementarity is decided over the **union** of each set's contexts on one
    side: two sets are complementary when nothing they are ever observed to the
    left of is shared, or nothing they are ever observed to the right of is. That
    is both cheap and exactly the case a single `RuleEnvironment` can express —
    an occurrence-level test could report a pair no conditioning could separate.

    This reports and never proposes. Deciding that two correspondences are one
    phoneme with a conditioned split is phonemicising, which is question three
    in `docs/report_reject_or_score.md` and the model's job. The tokens returned
    are segments present in this node's own data; no feature table is consulted,
    no natural class is named, and nothing is ranked.
    """
    if limit < 0:
        raise ValueError("limit must be non-negative")
    columns = tuple(node_ids)
    contexts = _set_contexts(alignment_map, columns)
    scored: list[tuple[tuple[int, str, str], ComplementaryCandidate]] = []
    for index, left_set in enumerate(sets):
        for right_set in sets[index + 1 :]:
            left_context = contexts.get(left_set.segments)
            right_context = contexts.get(right_set.segments)
            if left_context is None or right_context is None:
                continue
            shares_left = bool(left_context[0] & right_context[0])
            shares_right = bool(left_context[1] & right_context[1])
            if shares_left and shares_right:
                continue
            distinguishing = tuple(
                node_id
                for node_id, mine, theirs in zip(
                    columns, left_set.segments, right_set.segments, strict=True
                )
                if mine != theirs
            )
            candidate = ComplementaryCandidate(
                set_ids=(left_set.set_id, right_set.set_id),
                distinguishing_node_ids=distinguishing,
                left_context_tokens=(
                    tuple(sorted(left_context[0])),
                    tuple(sorted(right_context[0])),
                ),
                right_context_tokens=(
                    tuple(sorted(left_context[1])),
                    tuple(sorted(right_context[1])),
                ),
            )
            scored.append(
                (
                    (
                        # By the *weaker* half first. A conditioned split is a
                        # live hypothesis only where both sets are attested;
                        # ordering by combined support puts a set occurring in
                        # twenty words beside one occurring in two at the top of
                        # every page, and complementarity there is an artefact of
                        # the rare set being rare. This is still only a count.
                        -min(left_set.support, right_set.support),
                        -(left_set.support + right_set.support),
                        left_set.set_id,
                        right_set.set_id,
                    ),
                    candidate,
                )
            )
    scored.sort(key=lambda item: item[0])
    return tuple(candidate for _key, candidate in scored[:limit]), len(scored)


__all__ = [
    "MAX_COMPLEMENTARY_CANDIDATES",
    "build_correspondence_sets",
    "complementary_candidates",
    "one_reading_per_node",
]
