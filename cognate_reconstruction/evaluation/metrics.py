"""Graded comparison of one reconstructed form against a gold form.

Exact token equality answers one question — is this string the gold string —
and refuses every other. A reconstruction one segment away from
Proto-Polynesian `ʔ a l e l o` and a reconstruction sharing nothing with it
both score zero, so the number cannot say whether a change helped.

The three measures here are the ones the field has used since the SIGTYP 2022
shared task on cognate reflex prediction: edit distance, normalized edit
distance, and B-Cubed F1. They are computed over segment tokens, never over
characters, because a token in this repository is a phonological segment and
`a ː` is one sound written with two code points.

Nothing in this module scores, gates, or filters anything. It produces numbers
for `HistoricalTargetEvaluation`, which is a report; see
`docs/report_reject_or_score.md`.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass

GAP = "-"
"""The symbol standing in for an alignment gap in the B-Cubed partitions.

One symbol, not one per position, so every gap in a word belongs to the same
class. That follows the shared-task implementations, which align into two
strings padded with a literal gap character and then read those strings
directly.
"""


AlignedRow = tuple[str | None, ...]


def align(
    left: Sequence[str],
    right: Sequence[str],
) -> tuple[AlignedRow, AlignedRow]:
    """Unit-cost (Levenshtein) global alignment of two token sequences.

    Needleman-Wunsch with match 0, substitution 1, and indel 1, so the number
    of non-identical columns is exactly the edit distance. Deliberately *not*
    the SCA alignment used elsewhere in the harness: a sound-class alignment
    embeds a similarity model, and a metric that changes when the model is
    retuned is not a metric. This alignment depends on nothing but the tokens.

    The backtrace prefers a diagonal step, then a deletion from `left`, then an
    insertion from `right`, so the alignment is a deterministic function of the
    inputs. Gaps come back as `None`.
    """
    rows, columns = len(left), len(right)
    costs = [[0] * (columns + 1) for _ in range(rows + 1)]
    for i in range(1, rows + 1):
        costs[i][0] = i
    for j in range(1, columns + 1):
        costs[0][j] = j
    for i in range(1, rows + 1):
        for j in range(1, columns + 1):
            substitution = costs[i - 1][j - 1] + (left[i - 1] != right[j - 1])
            costs[i][j] = min(
                substitution,
                costs[i - 1][j] + 1,
                costs[i][j - 1] + 1,
            )
    aligned_left: list[str | None] = []
    aligned_right: list[str | None] = []
    i, j = rows, columns
    while i > 0 or j > 0:
        if (
            i > 0
            and j > 0
            and costs[i][j]
            == costs[i - 1][j - 1] + (left[i - 1] != right[j - 1])
        ):
            aligned_left.append(left[i - 1])
            aligned_right.append(right[j - 1])
            i -= 1
            j -= 1
        elif i > 0 and costs[i][j] == costs[i - 1][j] + 1:
            aligned_left.append(left[i - 1])
            aligned_right.append(None)
            i -= 1
        else:
            aligned_left.append(None)
            aligned_right.append(right[j - 1])
            j -= 1
    return tuple(reversed(aligned_left)), tuple(reversed(aligned_right))


def edit_distance(left: Sequence[str], right: Sequence[str]) -> int:
    """Unit-cost Levenshtein distance in segments, not characters."""
    previous = list(range(len(right) + 1))
    for i, left_token in enumerate(left, start=1):
        current = [i]
        for j, right_token in enumerate(right, start=1):
            current.append(
                min(
                    previous[j - 1] + (left_token != right_token),
                    previous[j] + 1,
                    current[j - 1] + 1,
                )
            )
        previous = current
    return previous[-1]


def normalized_edit_distance(
    left: Sequence[str],
    right: Sequence[str],
) -> float:
    """Edit distance over the length of the longer sequence, in [0, 1].

    The denominator is `max(len(left), len(right))`, which is the convention
    the SIGTYP 2022 evaluation used and the one `lingpy.align.pairwise.edit_dist
    (..., normalized=True)` implements. Two empty sequences are identical, so
    they score 0.0 rather than dividing by zero.

    Lower is better. That is the opposite polarity to every accuracy in this
    repository and is worth stating wherever the number is printed.
    """
    if not left and not right:
        return 0.0
    return edit_distance(left, right) / max(len(left), len(right))


@dataclass(frozen=True)
class BCubedScores:
    precision: float
    recall: float
    f1: float


def bcubed(left: Sequence[str], right: Sequence[str]) -> BCubedScores:
    """B-Cubed precision, recall, and F1 over the columns of the alignment.

    **The exact definition implemented here**, because there are variants and an
    undocumented one is comparable to nothing:

    1. Align `left` (the reconstruction) and `right` (the gold form) with
       `align` above — unit-cost Levenshtein, gaps written as one shared `-`
       symbol.
    2. Treat the alignment's columns as the item set. Each string partitions
       that set: two columns are in the same class of `left` when `left` shows
       the same symbol in both, and likewise for `right`.
    3. For each column `i`, following Bagga & Baldwin's B-Cubed,

           precision(i) = |L(i) ∩ R(i)| / |L(i)|
           recall(i)    = |L(i) ∩ R(i)| / |R(i)|

       where `L(i)` and `R(i)` are `i`'s classes under `left` and `right`.
    4. Precision and recall are the unweighted means over columns; F1 is their
       harmonic mean, and 0.0 when both are 0.

    **This measures structural agreement, not identity, and that is the point.**
    `p a` against `b e` scores 1.0 here while its normalized edit distance is
    1.0 — the reconstruction is wrong in every segment but wrong *consistently*,
    which is a systematic correspondence rather than noise. A prediction that
    got one branch's reflex wholesale is a different failure from one that
    guessed, and B-Cubed is the number that separates them. Read it beside the
    edit distances, never instead of them.
    """
    aligned_left, aligned_right = align(left, right)
    if not aligned_left:
        return BCubedScores(precision=1.0, recall=1.0, f1=1.0)
    columns = tuple(
        (
            GAP if a is None else a,
            GAP if b is None else b,
        )
        for a, b in zip(aligned_left, aligned_right, strict=True)
    )
    left_classes: dict[str, int] = {}
    right_classes: dict[str, int] = {}
    pair_counts: dict[tuple[str, str], int] = {}
    for a, b in columns:
        left_classes[a] = left_classes.get(a, 0) + 1
        right_classes[b] = right_classes.get(b, 0) + 1
        pair_counts[(a, b)] = pair_counts.get((a, b), 0) + 1
    precision = statistics.fmean(
        pair_counts[(a, b)] / left_classes[a] for a, b in columns
    )
    recall = statistics.fmean(
        pair_counts[(a, b)] / right_classes[b] for a, b in columns
    )
    denominator = precision + recall
    return BCubedScores(
        precision=precision,
        recall=recall,
        f1=(2 * precision * recall / denominator) if denominator else 0.0,
    )


@dataclass(frozen=True)
class GradedComparison:
    """One candidate against the gold alternative it comes closest to."""

    nearest_target: tuple[str, ...]
    edit_distance: int
    normalized_edit_distance: float
    bcubed_precision: float
    bcubed_recall: float
    bcubed_f1: float
    exact: bool


def compare_to_nearest(
    candidate: Sequence[str],
    alternatives: Sequence[Sequence[str]],
) -> GradedComparison:
    """Grade one candidate against whichever gold alternative it is closest to.

    A concept may carry several gold proto-forms — a source listing variants, or
    two reconstructions of one etymon. Exact matching already accepts any of
    them, so a graded score has to as well, or a reconstruction would be
    penalised for matching the second-listed variant.

    Ties are broken by edit distance and then by the alternative's own token
    order, so the chosen alternative is a deterministic function of the inputs
    and can be printed as the thing the score was computed against.
    """
    if not alternatives:
        raise ValueError("a graded comparison needs at least one gold alternative")
    tokens = tuple(candidate)
    nearest = min(
        (tuple(alternative) for alternative in alternatives),
        key=lambda alternative: (
            normalized_edit_distance(tokens, alternative),
            edit_distance(tokens, alternative),
            alternative,
        ),
    )
    scores = bcubed(tokens, nearest)
    return GradedComparison(
        nearest_target=nearest,
        edit_distance=edit_distance(tokens, nearest),
        normalized_edit_distance=normalized_edit_distance(tokens, nearest),
        bcubed_precision=scores.precision,
        bcubed_recall=scores.recall,
        bcubed_f1=scores.f1,
        exact=tokens == nearest,
    )
