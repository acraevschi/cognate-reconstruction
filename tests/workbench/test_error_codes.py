"""The closed rejection vocabulary and the structural codes derived from it.

These are mechanical identifiers used for counting and matching. Nothing here
judges a reconstruction; the exploratory/protocol split describes how a session
went, never whether its linguistics are right.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from cognate_reconstruction.agent.error_codes import (
    MAX_SCHEMA_CODE_FIELDS,
    SCHEMA_ERROR_CODE_PREFIX,
    TOOL_ERROR_CODES,
    UNCLASSIFIED_ERROR_CODE,
    ToolErrorCategory,
    classify_tool_error_code,
    normalize_error_location,
    schema_error_code,
)
from cognate_reconstruction.agent.schemas import CommitReconstructionArgs

AGENT_PACKAGE = Path(__file__).resolve().parents[2] / "cognate_reconstruction" / "agent"


def _rejection(payload: dict) -> ValidationError:
    with pytest.raises(ValidationError) as raised:
        CommitReconstructionArgs.model_validate_json(json.dumps(payload))
    return raised.value


def _commit(rules: list[dict], **overrides) -> dict:
    return {
        "node_id": "PROTO",
        "rules": rules,
        "anomalies": [],
        "summary": "Restore parent initial p.",
        **overrides,
    }


_VALID_RULE = {
    "dsl": "f > p / #_",
    "source_child_ids": ["B"],
    "confidence": 0.9,
}


def test_list_indices_collapse_so_one_mistake_has_one_code() -> None:
    """`rules.0.confidence` and `rules.1.confidence` are the same mistake."""
    first = schema_error_code(
        _rejection(_commit([{"dsl": "f > p / #_", "source_child_ids": ["B"]}]))
    )
    second = schema_error_code(
        _rejection(
            _commit(
                [
                    dict(_VALID_RULE),
                    {"dsl": "k > tʃ / _i", "source_child_ids": ["A"]},
                ]
            )
        )
    )
    assert first == second == "schema:rules[].confidence=missing"


def test_a_different_field_produces_a_different_code() -> None:
    missing_dsl = schema_error_code(
        _rejection(_commit([{"source_child_ids": ["B"], "confidence": 0.9}]))
    )
    missing_summary = schema_error_code(
        _rejection({"node_id": "PROTO", "rules": [], "anomalies": []})
    )
    assert missing_dsl == "schema:rules[].dsl=missing"
    assert missing_summary == "schema:summary=missing"
    assert missing_dsl != missing_summary


def test_the_code_ignores_the_offending_values() -> None:
    """Pydantic embeds inputs in messages; the code must not inherit that."""
    codes = {
        schema_error_code(
            _rejection(_commit([{"dsl": dsl, "source_child_ids": ["B"]}]))
        )
        for dsl in ("f > p / #_", "k > tʃ / _i", "n > m / _p")
    }
    assert len(codes) == 1


def test_the_derivation_is_deterministic_across_calls() -> None:
    error = _rejection(_commit([{"source_child_ids": ["B"]}]))
    codes = {schema_error_code(error) for _ in range(5)}
    assert len(codes) == 1
    # Several distinct failures in one call are sorted, not emitted in
    # dictionary order.
    assert next(iter(codes)) == (
        "schema:rules[].confidence=missing,rules[].dsl=missing"
    )


def test_many_distinct_failures_are_summarised_but_stay_stable() -> None:
    payload = _commit([dict(_VALID_RULE)])
    payload.update({f"unexpected_{index}": index for index in range(12)})
    code = schema_error_code(_rejection(payload))
    assert code.startswith(SCHEMA_ERROR_CODE_PREFIX)
    assert code.count("=") == MAX_SCHEMA_CODE_FIELDS
    assert code.endswith(",+6")
    assert code == schema_error_code(_rejection(payload))


@pytest.mark.parametrize(
    ("location", "expected"),
    (
        (("rules", 0, "confidence"), "rules[].confidence"),
        (("rules", 11, "confidence"), "rules[].confidence"),
        (("rules", 0, "source_child_ids", 2), "rules[].source_child_ids[]"),
        (("summary",), "summary"),
        ((), "<root>"),
        ((0,), "[]"),
    ),
)
def test_locations_normalize_predictably(location, expected: str) -> None:
    assert normalize_error_location(location) == expected


def _raised_codes() -> set[str]:
    """Every `code="..."` literal in the agent package.

    Read out of the source rather than listed here so a new raise site with an
    unlisted code fails this test instead of silently widening the vocabulary.
    """
    found: set[str] = set()
    for path in sorted(AGENT_PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg == "code" and isinstance(keyword.value, ast.Constant):
                    if isinstance(keyword.value.value, str):
                        found.add(keyword.value.value)
    return found


def test_every_code_the_tools_raise_is_in_the_vocabulary() -> None:
    raised = _raised_codes()
    assert raised
    assert raised <= set(TOOL_ERROR_CODES)


def test_every_code_in_the_vocabulary_is_explicitly_classified() -> None:
    assert TOOL_ERROR_CODES
    for code, category in TOOL_ERROR_CODES.items():
        assert isinstance(category, ToolErrorCategory), code
        assert classify_tool_error_code(code) is category


def test_the_exploratory_set_is_exactly_the_hypothesis_tester_refusing() -> None:
    exploratory = {
        code
        for code, category in TOOL_ERROR_CODES.items()
        if category is ToolErrorCategory.EXPLORATORY
    }
    assert exploratory == {"dsl-parse-error", "no-op-rule", "empty-scope"}


SKILL_COPIES = (
    Path(__file__).resolve().parents[2] / ".claude" / "skills"
    / "run-cognate-reconstruction",
    Path(__file__).resolve().parents[2] / "skills" / "run-cognate-reconstruction",
)


def _driver_exploratory_codes(driver: Path) -> set[str]:
    """Read `EXPLORATORY_CODES` out of the driver without importing it."""
    tree = ast.parse(driver.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        names = {t.id for t in node.targets if isinstance(t, ast.Name)}
        if "EXPLORATORY_CODES" in names:
            return set(ast.literal_eval(node.value))
    raise AssertionError(f"EXPLORATORY_CODES not found in {driver}")


@pytest.mark.parametrize("skill", SKILL_COPIES, ids=lambda path: path.parent.name)
def test_the_triage_driver_agrees_with_the_real_classification(skill: Path) -> None:
    """The driver is stdlib-only, so it hand-copies the exploratory set.

    That duplication is deliberate — the driver must run without the harness
    installed — so it is guarded here instead of removed. Drift shows up as a
    triage report that quietly miscategorises failures.
    """
    driver = skill / "driver.py"
    if not driver.exists():
        pytest.skip(f"{skill} is not present in this checkout")
    expected = {
        code
        for code, category in TOOL_ERROR_CODES.items()
        if category is ToolErrorCategory.EXPLORATORY
    }
    assert _driver_exploratory_codes(driver) == expected


def test_both_skill_copies_stay_byte_identical() -> None:
    """The skill is checked in twice; the copies must not diverge."""
    private, public = SKILL_COPIES
    if not private.is_dir():
        pytest.skip(".claude/skills is not present in this checkout")
    names = {path.name for path in public.iterdir() if path.is_file()}
    assert names == {path.name for path in private.iterdir() if path.is_file()}
    for name in sorted(names):
        assert (private / name).read_bytes() == (public / name).read_bytes(), name


@pytest.mark.parametrize(
    "code",
    (
        None,
        "",
        "a-code-nobody-defined",
        "schema:rules[].confidence=missing",
        SCHEMA_ERROR_CODE_PREFIX + "anything",
        UNCLASSIFIED_ERROR_CODE,
    ),
)
def test_anything_unclassified_fails_closed_as_protocol(code) -> None:
    assert classify_tool_error_code(code) is ToolErrorCategory.PROTOCOL
