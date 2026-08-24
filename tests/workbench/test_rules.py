from __future__ import annotations

import pytest

from cognate_reconstruction.rules import RuleEngine, parse_rule
from cognate_reconstruction.schemas.lexicon import LexicalForm
from cognate_reconstruction.schemas.rules import ApplicationStatus


def form(form_id: str, segments: tuple[str, ...]) -> LexicalForm:
    return LexicalForm(
        form_id=form_id,
        variety_id="child",
        concept_id="concept",
        segments=segments,
    )


def test_final_rule_diff_and_candidate_provenance() -> None:
    rule = parse_rule("p > f / _#", rule_id="final-frication")
    report = RuleEngine().apply_rule(
        rule,
        (form("matches", ("a", "p")), form("wrong-context", ("p", "a"))),
        source_candidate_ids={"matches": "candidate-7"},
    )
    assert report.words_applied == 1
    assert report.results[0].output_segments == ("a", "f")
    assert report.results[0].source_candidate_id == "candidate-7"
    assert report.results[1].status is ApplicationStatus.CONTEXT_MISMATCH
    assert report.exceptions == (report.results[1],)


def test_morphological_boundary_is_not_transparent() -> None:
    rule = parse_rule("k > tʃ / _i")
    report = RuleEngine().apply_rule(rule, (form("f", ("k", "+", "i")),))
    assert report.results[0].status is ApplicationStatus.CONTEXT_MISMATCH


def test_morphological_boundary_can_be_explicit_context() -> None:
    rule = parse_rule("k > tʃ / _ +")
    report = RuleEngine().apply_rule(rule, (form("f", ("k", "+", "i")),))
    assert report.results[0].output_segments == ("tʃ", "+", "i")


def test_anchor_mismatch_is_mechanically_applied() -> None:
    rule = parse_rule("p > f")
    report = RuleEngine().apply_rule(
        rule,
        (form("anchor", ("p",)),),
        anchor_expected={"anchor": ("v",)},
    )
    assert report.results[0].status is ApplicationStatus.ANCHOR_MISMATCH
    assert report.words_applied == 1


@pytest.mark.parametrize(
    "dsl",
    (
        "p > p",
        "p > p / #_",
        "t s > t s / _#",
    ),
)
def test_parser_rejects_no_op_rules(dsl: str) -> None:
    with pytest.raises(ValueError, match="empty rule set"):
        parse_rule(dsl)


def test_a_cascade_may_not_delete_the_whole_word() -> None:
    """A rule may delete material; a cascade may not delete a form.

    Before this guard, `apply_rules` discovered the case by handing pydantic an
    empty segment tuple, so the failure surfaced as a bare `ValidationError`
    from inside `traversal/reconstructor.py` with no rule, form, or node named.
    It is reachable from both commit shapes — a cascade of deletions under
    `rules`, and under `inventory` any *derived* view where enough sets
    reconstruct nothing, which is where it was found: at Proto-Tongic, the
    oracle's inventory derives `l > Ø` for Niuean, and Niuean's `k i l i` had
    already lost `k` and both `i` by the time that rule ran.

    The refusal is per (rule, form): the form is carried through unchanged, the
    rest of the cascade still runs, and the report says which rule was refused.
    """
    engine = RuleEngine()
    cascade = [parse_rule("k > Ø"), parse_rule("i > Ø"), parse_rule("l > Ø")]
    produced, reports = engine.apply_rules(cascade, (form("f", ("k", "i", "l", "i")),))
    assert produced[0].segments == ("l",)
    assert [report.results[0].status for report in reports] == [
        ApplicationStatus.APPLIED,
        ApplicationStatus.APPLIED,
        ApplicationStatus.WOULD_EMPTY_FORM,
    ]
    refused = reports[-1].results[0]
    # Applicable and not applied, so `rule_coverage` sees a rule that could have
    # fired and did not, rather than one that was vacuous.
    assert refused.status is not ApplicationStatus.TARGET_ABSENT
    assert refused.locations == ()
    assert refused.target_occurrences == 1
    assert refused.output_segments == ("l",)


def test_a_rule_that_empties_one_form_still_applies_to_the_others() -> None:
    """The refusal is per form, not per rule.

    A rule scoped to a child applies to every form that child attests, and
    exactly one of them being a single segment is not a reason to leave the
    others alone.
    """
    report = RuleEngine().apply_rule(
        parse_rule("a > Ø"), (form("short", ("a",)), form("long", ("a", "k", "a")))
    )
    short, long = report.results
    assert short.status is ApplicationStatus.WOULD_EMPTY_FORM
    assert short.output_segments == ("a",)
    assert long.status is ApplicationStatus.APPLIED
    assert long.output_segments == ("k",)
