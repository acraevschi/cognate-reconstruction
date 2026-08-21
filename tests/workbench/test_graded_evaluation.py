"""Graded held-out evaluation: near misses, structure, and the selection gap.

Exact token equality cannot tell a reconstruction one segment away from
Proto-Polynesian `ʔ a l e l o` from one sharing nothing with it. Both score
zero, which means the metric cannot say whether a change helped. These pin the
three measures that can, and the properties that make them worth reading
together rather than picking one.
"""

from __future__ import annotations

import pytest

from cognate_reconstruction.evaluation.metrics import (
    align,
    bcubed,
    compare_to_nearest,
    edit_distance,
    normalized_edit_distance,
)
from cognate_reconstruction.schemas.metrics import MetricDistribution


def test_distance_is_measured_in_segments_not_characters() -> None:
    """`a ː` is one sound written with two code points.

    A character-level distance would score a long-vowel mismatch as two errors
    and a phonemic tokenization as noise.
    """
    assert edit_distance(("f", "aː"), ("f", "a")) == 1
    assert normalized_edit_distance(("f", "aː"), ("f", "a")) == 0.5
    assert edit_distance(("aː",), ("a",)) == 1


def test_normalized_distance_separates_a_near_miss_from_an_unrelated_form() -> None:
    """The whole reason this module exists, in two assertions."""
    gold = ("ʔ", "a", "l", "e", "l", "o")
    near = ("a", "l", "e", "l", "o")
    unrelated = ("f", "a", "n", "o")
    assert not near == gold and not unrelated == gold
    assert normalized_edit_distance(near, gold) == pytest.approx(1 / 6)
    assert normalized_edit_distance(unrelated, gold) > 0.6
    # Exact match cannot tell these apart at all.
    assert (near == gold) == (unrelated == gold)


def test_empty_sequences_are_identical_rather_than_a_division_by_zero() -> None:
    assert normalized_edit_distance((), ()) == 0.0
    assert bcubed((), ()).f1 == 1.0


def test_alignment_is_deterministic_and_costs_the_edit_distance() -> None:
    left, right = align(("a", "l", "e"), ("ʔ", "a", "l", "e"))
    assert left == (None, "a", "l", "e")
    assert right == ("ʔ", "a", "l", "e")
    assert sum(a != b for a, b in zip(left, right, strict=True)) == edit_distance(
        ("a", "l", "e"), ("ʔ", "a", "l", "e")
    )


def test_bcubed_scores_structure_and_not_identity() -> None:
    """The property that makes B-Cubed a complement to edit distance.

    `p a` against `b e` is wrong in every segment, and wrong *consistently*: one
    sound corresponds to one sound throughout. B-Cubed scores that 1.0 while
    normalized edit distance scores it 1.0 in the other direction. A prediction
    that took one branch's reflex wholesale is a different failure from one that
    guessed, and only the pair of numbers separates them.
    """
    assert bcubed(("p", "a"), ("b", "e")).f1 == 1.0
    assert normalized_edit_distance(("p", "a"), ("b", "e")) == 1.0
    # An inconsistent correspondence does lose points: one p answers to b and
    # the other to t.
    scores = bcubed(("p", "a", "p", "a"), ("b", "a", "t", "a"))
    assert scores.precision == pytest.approx(0.75)
    assert scores.recall == pytest.approx(1.0)
    assert scores.f1 == pytest.approx(6 / 7)


def test_bcubed_is_symmetric_in_f1_and_reports_both_directions() -> None:
    forward = bcubed(("p", "a", "p", "a"), ("b", "a", "t", "a"))
    backward = bcubed(("b", "a", "t", "a"), ("p", "a", "p", "a"))
    assert forward.f1 == pytest.approx(backward.f1)
    assert forward.precision == pytest.approx(backward.recall)


def test_a_candidate_is_graded_against_the_nearest_gold_alternative() -> None:
    """Exact matching accepts any listed variant, so grading must too.

    A concept may carry several gold proto-forms. Penalising a reconstruction
    for matching the second-listed one would make the score depend on the order
    of a source's variant list.
    """
    comparison = compare_to_nearest(("f", "a"), [("p", "a"), ("f", "a")])
    assert comparison.nearest_target == ("f", "a")
    assert comparison.exact
    assert comparison.normalized_edit_distance == 0.0
    # Ties are resolved deterministically, so the graded alternative can be
    # printed as the thing the score was computed against.
    tie = compare_to_nearest(("x", "a"), [("z", "a"), ("p", "a")])
    assert tie.nearest_target == ("p", "a")


def test_a_distribution_of_one_reports_itself_rather_than_raising() -> None:
    summary = MetricDistribution.of([0.4])
    assert summary is not None
    assert summary.count == 1
    assert summary.mean == summary.median == summary.p25 == summary.p75 == 0.4
    assert summary.standard_deviation == 0.0


def test_an_unmeasured_metric_is_none_and_not_a_zeroed_record() -> None:
    """A metric nobody measured and a metric measured as zero differ.

    Collapsing them is how an empty run comes to read as a perfect one.
    """
    assert MetricDistribution.of([]) is None
