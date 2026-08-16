"""Commit-protocol ergonomics: resolution, defaulting, and remediation.

Every case here removes a transcription step or improves a diagnostic. None of
them removes a check: a non-empty committed rule still requires an exact
same-session validation of the identical DSL, child scope, and overlay.
"""

from __future__ import annotations

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.schemas import (
    CommitReconstructionArgs,
    LLMToolCall,
)
from cognate_reconstruction.agent.tools import default_tool_registry
from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm


def _lexicon(variety_id: str, initial: str) -> LanguageLexicon:
    return LanguageLexicon(
        variety_id=variety_id,
        name=variety_id,
        forms=tuple(
            LexicalForm(
                form_id=f"{variety_id}:{concept}",
                variety_id=variety_id,
                concept_id=concept,
                segments=(initial, *ending),
            )
            for concept, ending in (("water", ("a",)), ("fire", ("u", "r")))
        ),
    )


def _context() -> AgentContext:
    return AgentContext(
        node_id="PROTO",
        child_lexicons=(_lexicon("A", "p"), _lexicon("B", "f")),
        aligner=LingPyAligner(),
    )


def _validate(registry, state, call_id: str, **arguments) -> None:
    result = registry.execute(
        LLMToolCall(call_id=call_id, name="test_sound_law", arguments=arguments),
        state,
    )
    assert result.ok, result.error


def _commit(registry, state, **arguments):
    return registry.execute(
        LLMToolCall(
            call_id="commit",
            name="commit_reconstruction",
            arguments={
                "node_id": "PROTO",
                "anomalies": [],
                "summary": "Restore parent initial p from regular B f.",
                **arguments,
            },
        ),
        state,
    )


def test_omitted_validation_call_id_resolves_from_the_unique_exact_match() -> None:
    state = _context()
    registry = default_tool_registry()
    _validate(
        registry,
        state,
        "validate-restore-p",
        dsl="f > p / #_",
        source_child_ids=["B"],
    )
    result = _commit(
        registry,
        state,
        rules=[
            {
                "dsl": "f > p / #_",
                "source_child_ids": ["B"],
                "confidence": 0.9,
            }
        ],
    )
    assert result.ok, result.error
    assert state.commit is not None
    # The resolved ID is written back so the trajectory stays explicit about
    # which validation backs the committed rule.
    committed = state.commit.request.rules[0]
    assert committed.validation_call_id == "validate-restore-p"
    assert set(committed.supporting_form_ids) == {"B:water", "B:fire"}


def test_unmatched_rule_is_rejected_and_lists_the_session_validations() -> None:
    state = _context()
    registry = default_tool_registry()
    _validate(
        registry,
        state,
        "validate-restore-p",
        dsl="f > p / #_",
        source_child_ids=["B"],
    )
    result = _commit(
        registry,
        state,
        rules=[
            {
                "dsl": "f > b / #_",
                "source_child_ids": ["B"],
                "confidence": 0.9,
            }
        ],
    )
    assert not result.ok
    assert result.error is not None
    assert "no same-session test_sound_law validation matches" in result.error.message
    remediation = result.error.remediation or ""
    assert '("validate-restore-p", "f > p / #_", [B])' in remediation
    assert state.commit is None


def test_ambiguous_matches_are_rejected_rather_than_silently_chosen() -> None:
    state = _context()
    registry = default_tool_registry()
    # Same DSL and scope, different evidence batches: two genuinely distinct
    # records with different supporting_form_ids.
    _validate(
        registry,
        state,
        "validate-water",
        dsl="f > p / #_",
        source_child_ids=["B"],
        concept_ids=["water"],
    )
    _validate(
        registry,
        state,
        "validate-both",
        dsl="f > p / #_",
        source_child_ids=["B"],
    )
    result = _commit(
        registry,
        state,
        rules=[
            {
                "dsl": "f > p / #_",
                "source_child_ids": ["B"],
                "confidence": 0.9,
            }
        ],
    )
    assert not result.ok
    assert result.error is not None
    assert "2 same-session validations match" in result.error.message
    assert "validate-water" in (result.error.remediation or "")
    assert state.commit is None

    # Naming one explicitly resolves the ambiguity.
    chosen = _commit(
        registry,
        state,
        rules=[
            {
                "dsl": "f > p / #_",
                "source_child_ids": ["B"],
                "confidence": 0.9,
                "validation_call_id": "validate-water",
            }
        ],
    )
    assert chosen.ok, chosen.error
    assert state.commit is not None
    assert state.commit.request.rules[0].supporting_form_ids == ("B:water",)


def test_matching_dsl_with_a_different_child_scope_is_still_rejected() -> None:
    state = _context()
    registry = default_tool_registry()
    _validate(
        registry,
        state,
        "validate-restore-p",
        dsl="f > p / #_",
        source_child_ids=["B"],
    )
    omitted = _commit(
        registry,
        state,
        rules=[
            {
                "dsl": "f > p / #_",
                "source_child_ids": ["A", "B"],
                "confidence": 0.9,
            }
        ],
    )
    assert not omitted.ok
    assert omitted.error is not None
    assert "no same-session test_sound_law validation matches" in omitted.error.message

    explicit = _commit(
        registry,
        state,
        rules=[
            {
                "dsl": "f > p / #_",
                "source_child_ids": ["A", "B"],
                "confidence": 0.9,
                "validation_call_id": "validate-restore-p",
            }
        ],
    )
    assert not explicit.ok
    assert explicit.error is not None
    assert "not validated for this child scope" in explicit.error.message
    assert state.commit is None


def test_supporting_form_ids_outside_the_validation_are_still_rejected() -> None:
    state = _context()
    registry = default_tool_registry()
    _validate(
        registry,
        state,
        "validate-water",
        dsl="f > p / #_",
        source_child_ids=["B"],
        concept_ids=["water"],
    )
    result = _commit(
        registry,
        state,
        rules=[
            {
                "dsl": "f > p / #_",
                "source_child_ids": ["B"],
                "confidence": 0.9,
                "validation_call_id": "validate-water",
                "supporting_form_ids": ["B:water", "B:fire"],
            }
        ],
    )
    assert not result.ok
    assert result.error is not None
    assert "cites unsupported forms: ['B:fire']" in result.error.message
    assert "Omit supporting_form_ids" in (result.error.remediation or "")
    assert state.commit is None


def test_schema_rejection_also_carries_the_validation_catalogue() -> None:
    state = _context()
    registry = default_tool_registry()
    _validate(
        registry,
        state,
        "validate-restore-p",
        dsl="f > p / #_",
        source_child_ids=["B"],
    )
    # confidence is a model judgement and stays required; the rejection now
    # explains where the validation reference comes from all the same.
    result = _commit(
        registry,
        state,
        rules=[{"dsl": "f > p / #_", "source_child_ids": ["B"]}],
    )
    assert not result.ok
    assert result.error is not None
    assert "confidence" in result.error.message
    assert '("validate-restore-p", "f > p / #_", [B])' in (
        result.error.remediation or ""
    )


def test_unknown_cascade_id_is_answered_with_the_cascade_catalogue() -> None:
    state = _context()
    registry = default_tool_registry()
    _validate(
        registry,
        state,
        "validate-restore-p",
        dsl="f > p / #_",
        source_child_ids=["B"],
    )
    result = _commit(
        registry,
        state,
        cascade_validation_call_id="validate-restore-p",
        rules=[
            {
                "dsl": "f > p / #_",
                "source_child_ids": ["B"],
                "confidence": 0.9,
            }
        ],
    )
    assert not result.ok
    assert result.error is not None
    assert "unknown cascade validation call" in result.error.message
    assert "cascade_validation_call_id must be omitted" in (
        result.error.remediation or ""
    )


def test_identity_commit_needs_no_validation_and_says_so() -> None:
    state = _context()
    registry = default_tool_registry()
    result = _commit(registry, state, rules=[])
    assert result.ok, result.error
    assert state.commit is not None
    assert state.commit.parsed_rules == ()


def _validate_two_rules(registry, state) -> None:
    _validate(
        registry,
        state,
        "validate-restore-p",
        dsl="f > p / #_",
        source_child_ids=["B"],
    )
    _validate(
        registry,
        state,
        "validate-final-l",
        dsl="r > l / _#",
        source_child_ids=["A", "B"],
    )


def _two_rules(*rationales: str | None) -> list[dict]:
    specs = (
        ("restore-p", "f > p / #_", ["B"]),
        ("final-l", "r > l / _#", ["A", "B"]),
    )
    rules = []
    for (rule_id, dsl, scope), rationale in zip(specs, rationales, strict=True):
        rule = {
            "rule_id": rule_id,
            "dsl": dsl,
            "source_child_ids": scope,
            "confidence": 0.8,
        }
        if rationale is not None:
            rule["rationale"] = rationale
        rules.append(rule)
    return rules


def test_a_multi_rule_commit_missing_a_rationale_names_the_offending_rules() -> None:
    """One summary cannot say why each of several rules is there."""
    state = _context()
    registry = default_tool_registry()
    _validate_two_rules(registry, state)
    result = _commit(
        registry,
        state,
        rules=_two_rules("Regular initial correspondence in B.", None),
    )
    assert not result.ok
    assert result.error is not None
    assert result.error.code == "missing-rule-rationale"
    assert "1 of 2 committed rules omit 'rationale'" in result.error.message
    remediation = result.error.remediation or ""
    assert "'final-l'" in remediation
    # The rule that supplied one is not named as an offender.
    assert "'restore-p'" not in remediation
    assert state.commit is None


def test_a_multi_rule_commit_with_every_rationale_is_accepted() -> None:
    state = _context()
    registry = default_tool_registry()
    _validate_two_rules(registry, state)
    result = _commit(
        registry,
        state,
        rules=_two_rules(
            "Regular initial correspondence in B.",
            "Both children lose final r to l.",
        ),
    )
    assert result.ok, result.error
    assert state.commit is not None
    assert [rule.rationale for rule in state.commit.request.rules] == [
        "Regular initial correspondence in B.",
        "Both children lose final r to l.",
    ]


def test_a_single_rule_commit_still_needs_no_rationale() -> None:
    """The measured transcription friction was entirely on this shape."""
    state = _context()
    registry = default_tool_registry()
    _validate(
        registry,
        state,
        "validate-restore-p",
        dsl="f > p / #_",
        source_child_ids=["B"],
    )
    result = _commit(
        registry,
        state,
        rules=[
            {"dsl": "f > p / #_", "source_child_ids": ["B"], "confidence": 0.9}
        ],
    )
    assert result.ok, result.error
    assert state.commit is not None
    assert state.commit.request.rules[0].rationale is None


def test_the_rationale_rule_is_stated_in_the_field_description() -> None:
    """The model reads the schema; the requirement cannot live only in code."""
    rule_schema = CommitReconstructionArgs.model_json_schema()["$defs"][
        "CommittedSoundRule"
    ]["properties"]
    description = rule_schema["rationale"]["description"]
    assert "Required on every rule" in description
    assert "more than one" in description


def test_every_committed_rule_field_is_described_for_the_model() -> None:
    schema = CommitReconstructionArgs.model_json_schema()
    rule_schema = schema["$defs"]["CommittedSoundRule"]["properties"]
    assert all(
        "description" in rule_schema[name] for name in rule_schema
    ), sorted(name for name in rule_schema if "description" not in rule_schema[name])
    validation = rule_schema["validation_call_id"]["description"]
    assert "test_sound_law" in validation
    assert "cascade_validation_call_id" in validation
    assert all("description" in schema["properties"][name] for name in schema["properties"])
