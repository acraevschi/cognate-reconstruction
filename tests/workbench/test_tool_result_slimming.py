"""What tool results stop showing the model, and what the harness still keeps.

Across 323 recorded node sessions, accepted tool results were 71.5% of every
prompt character. Three kinds of content in them were never cited by a model
and are not inputs to any tool: forms a rule's target does not occur in, listed
as "exceptions"; the pairwise correspondence views under `get_alignments`'s
`summary`; and the source provenance carried by every form. These tests pin
that each is gone from what the model reads, that what it does read is intact,
and that the harness-side record each tool keeps is unchanged.
"""

from __future__ import annotations

import json

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.schemas import (
    LLMToolCall,
    SearchFormsArgs,
    model_facing_form,
)
from cognate_reconstruction.agent.tools import default_tool_registry
from cognate_reconstruction.agent.tools.evidence import search_forms
from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.rules import RuleEngine, parse_rule
from cognate_reconstruction.schemas.lexicon import (
    CognateMembership,
    CognateMembershipInterpretation,
    CognateMembershipProvenance,
    CognateMembershipScope,
    FormProvenance,
    LanguageLexicon,
    LexicalForm,
)
from cognate_reconstruction.schemas.rules import ApplicationStatus

_PROVENANCE = FormProvenance(
    dataset_id="fixture",
    source_form_id="row-1",
    source_reference="A long bibliographic reference the model never cites.",
)


def _membership(
    form_id: str,
    cognate_set_id: str,
    *,
    scope: CognateMembershipScope = CognateMembershipScope.WHOLE_FORM,
    interpretation: CognateMembershipInterpretation = (
        CognateMembershipInterpretation.ASSERTED
    ),
    segment_indices: tuple[int, ...] = (),
) -> CognateMembership:
    return CognateMembership(
        membership_id=f"{form_id}:{cognate_set_id}",
        cognate_set_id=cognate_set_id,
        scope=scope,
        interpretation=interpretation,
        segment_indices=segment_indices,
        slice_unit="segment" if segment_indices else None,
        provenance=CognateMembershipProvenance(
            dataset_id="fixture",
            source_table="CognateTable",
            source_row=7,
            source_cognateset_id=cognate_set_id,
            source_reference="Another reference.",
        ),
    )


def _whole(variety_id: str, concept_id: str, segments: tuple[str, ...]) -> LexicalForm:
    form_id = f"{variety_id}:{concept_id}"
    return LexicalForm(
        form_id=form_id,
        variety_id=variety_id,
        concept_id=concept_id,
        segments=segments,
        cognate_set_id=f"cog-{concept_id}",
        cognate_memberships=(_membership(form_id, f"cog-{concept_id}"),),
        provenance=_PROVENANCE,
    )


def _partial(variety_id: str) -> LexicalForm:
    """A compound whose two parts belong to two different cognate sets."""
    form_id = f"{variety_id}:sun"
    return LexicalForm(
        form_id=form_id,
        variety_id=variety_id,
        concept_id="sun",
        segments=("p", "a", "+", "t", "i"),
        cognate_memberships=tuple(
            _membership(
                form_id,
                cognate_set_id,
                scope=CognateMembershipScope.SEGMENT_SLICE,
                interpretation=CognateMembershipInterpretation.PARTIAL_COGNATE,
                segment_indices=indices,
            )
            for cognate_set_id, indices in (("cog-day", (0, 1)), ("cog-eye", (3, 4)))
        ),
        provenance=_PROVENANCE,
    )


def _context() -> AgentContext:
    lexicons = tuple(
        LanguageLexicon(
            variety_id=variety_id,
            name=variety_id,
            forms=(
                _whole(variety_id, "water", (initial, "a")),
                _whole(variety_id, "fire", (initial, "u", "r")),
                _whole(variety_id, "moon", ("m", "a")),
                _partial(variety_id),
            ),
        )
        for variety_id, initial in (("A", "p"), ("B", "f"))
    )
    return AgentContext(node_id="PROTO", child_lexicons=lexicons, aligner=LingPyAligner())


def _execute(state: AgentContext, name: str, call_id: str = "call", **arguments):
    result = default_tool_registry().execute(
        LLMToolCall(call_id=call_id, name=name, arguments=arguments), state
    )
    assert result.ok, result.error
    return result.result


# --------------------------------------------------------------------------
# 1. a form without the target is not an exception
# --------------------------------------------------------------------------


def test_a_form_without_the_target_is_not_an_exception() -> None:
    report = RuleEngine().apply_rule(
        parse_rule("p > f / _#"),
        (
            _whole("A", "applies", ("a", "p")),
            _whole("A", "context", ("p", "a")),
            _whole("A", "absent", ("m", "a")),
        ),
    )
    statuses = [result.status for result in report.results]
    assert statuses == [
        ApplicationStatus.APPLIED,
        ApplicationStatus.CONTEXT_MISMATCH,
        ApplicationStatus.TARGET_ABSENT,
    ]
    # The record of every form stays; only the exception list narrows.
    assert report.exceptions == (report.results[1],)


def test_the_cascade_summary_lists_only_forms_the_target_occurs_in() -> None:
    state = _context()
    payload = _execute(
        state,
        "test_rule_cascade",
        rules=[{"dsl": "f > p / #_", "source_child_ids": ["B"]}],
    )
    (summary,) = payload["report_summaries"]
    assert summary["forms_evaluated"] == 4
    assert summary["words_applied"] == 2
    # "moon" and "sun" have no f: counted as evaluated, not listed.
    assert summary["exceptions"] == []

    full = _execute(
        state,
        "test_rule_cascade",
        call_id="full",
        rules=[{"dsl": "f > p / #_", "source_child_ids": ["B"]}],
        detail="full",
    )
    (report,) = full["reports"]
    assert report["exceptions"] == []
    assert {result["status"] for result in report["results"]} == {
        "applied",
        "target_absent",
    }


def test_a_sound_law_preview_keeps_every_result_and_only_real_exceptions() -> None:
    state = _context()
    payload = _execute(
        state,
        "test_sound_law",
        dsl="f > p / _a",
        source_child_ids=["B"],
    )
    results = payload["report"]["results"]
    assert len(results) == 4
    # fire has f, but not before a: the one real exception.
    assert [item["form_id"] for item in payload["report"]["exceptions"]] == ["B:fire"]


# --------------------------------------------------------------------------
# 2. forms as a tool result shows them
# --------------------------------------------------------------------------


def test_a_form_shows_its_evidence_and_not_its_source() -> None:
    view = model_facing_form(_whole("A", "water", ("p", "a")))
    assert view == {
        "form_id": "A:water",
        "variety_id": "A",
        "concept_id": "water",
        "segments": ["p", "a"],
        "cognate_set_id": "cog-water",
        "analysis": None,
        "morphological_boundary_tokens": ["+", "-"],
    }


def test_partial_cognacy_keeps_its_memberships_without_their_provenance() -> None:
    """The shorthand is null here, so the memberships are the only cognacy."""
    view = model_facing_form(_partial("A"))
    assert view["cognate_set_id"] is None
    assert "provenance" not in view
    assert view["cognate_memberships"] == [
        {
            "membership_id": "A:sun:cog-day",
            "cognate_set_id": "cog-day",
            "scope": "segment_slice",
            "interpretation": "partial_cognate",
            "segment_indices": [0, 1],
            "slice_unit": "segment",
        },
        {
            "membership_id": "A:sun:cog-eye",
            "cognate_set_id": "cog-eye",
            "scope": "segment_slice",
            "interpretation": "partial_cognate",
            "segment_indices": [3, 4],
            "slice_unit": "segment",
        },
    ]


def test_a_doubtful_judgement_keeps_its_membership() -> None:
    form = _whole("A", "water", ("p", "a"))
    membership = form.cognate_memberships[0]
    doubtful = form.model_copy(
        update={
            "cognate_memberships": (
                membership.model_copy(
                    update={
                        "provenance": membership.provenance.model_copy(
                            update={"doubt": True}
                        )
                    }
                ),
            )
        }
    )
    view = model_facing_form(doubtful)
    assert view["cognate_set_id"] == "cog-water"
    assert view["cognate_memberships"][0]["doubt"] is True
    assert "provenance" not in view["cognate_memberships"][0]


def test_search_forms_shows_the_slim_form_and_keeps_the_full_one() -> None:
    state = _context()
    payload = _execute(state, "search_forms", concept_ids=["sun", "water"])
    forms = {hit["form"]["form_id"]: hit["form"] for hit in payload["hits"]}
    assert set(forms) == {"A:sun", "B:sun", "A:water", "B:water"}
    text = json.dumps(payload)
    assert "provenance" not in text
    assert "source_reference" not in text
    assert "cognate_memberships" not in forms["A:water"]
    assert [m["cognate_set_id"] for m in forms["A:sun"]["cognate_memberships"]] == [
        "cog-day",
        "cog-eye",
    ]
    # Only serialization changes: the result object still holds the full form.
    result = search_forms(SearchFormsArgs(concept_ids=("water",)), state, "direct")
    assert result.hits[0].form.provenance == _PROVENANCE
    assert result.hits[0].form.cognate_memberships


def test_cascade_final_forms_drop_provenance_and_convergence_still_reads_them() -> None:
    state = _context()
    payload = _execute(
        state,
        "test_rule_cascade",
        call_id="cascade",
        rules=[{"dsl": "f > p / #_", "source_child_ids": ["B"]}],
    )
    assert "provenance" not in json.dumps(payload["final_forms"])
    assert payload["convergence"] is not None
    stored = state.cascade_validations["cascade"]
    assert all(final.form.provenance == _PROVENANCE for final in stored.final_forms)


# --------------------------------------------------------------------------
# 3. get_alignments
# --------------------------------------------------------------------------


def test_alignment_summary_omits_pairwise_views_and_full_keeps_them() -> None:
    state = _context()
    summary = _execute(
        state, "get_alignments", node_ids=["A", "B"], concept_ids=["water", "fire"]
    )
    full = _execute(
        state,
        "get_alignments",
        call_id="full",
        node_ids=["A", "B"],
        concept_ids=["water", "fire"],
        detail="full",
    )
    assert summary["alignment_map"]["pairwise_correspondences"] == []
    assert summary["alignment_map"]["alignments"] == full["alignment_map"]["alignments"]
    assert len(full["alignment_map"]["pairwise_correspondences"]) == 1
