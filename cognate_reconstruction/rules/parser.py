"""Parser for the deliberately small version-one sound-law DSL."""

from __future__ import annotations

import hashlib

from cognate_reconstruction.schemas.rules import (
    ParsedSoundRule,
    RuleEnvironment,
    SegmentExpression,
)


class NoOpRuleError(ValueError):
    """A syntactically valid rule that cannot change any token sequence.

    A subclass rather than a message check: callers that need to tell "the model
    wrote nonsense" apart from "the model wrote a rule that does nothing" should
    not have to match on prose. It stays a ``ValueError`` so existing handling is
    unaffected.
    """


def _tokens(text: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    stripped = text.strip()
    if stripped in {"", "Ø", "∅"}:
        if allow_empty:
            return ()
        raise ValueError("empty segment expression is not allowed here")
    if "#" in stripped or "_" in stripped:
        raise ValueError("word boundary and focus markers are only valid in environments")
    return tuple(stripped.split()) if any(char.isspace() for char in stripped) else (stripped,)


def parse_rule(source: str, *, rule_id: str | None = None) -> ParsedSoundRule:
    """Parse ``target > replacement / environment`` into a literal AST."""
    if source.count(">") != 1:
        raise ValueError("a sound rule must contain exactly one '>'")
    change, separator, raw_environment = source.partition("/")
    if separator and "/" in raw_environment:
        raise ValueError("a sound rule may contain at most one environment separator")
    raw_target, raw_replacement = change.split(">", 1)

    if separator:
        if raw_environment.count("_") != 1:
            raise ValueError("an explicit environment must contain exactly one '_'")
        raw_left, raw_right = raw_environment.split("_", 1)
        left_text = raw_left.strip()
        right_text = raw_right.strip()
        word_initial = left_text.startswith("#")
        word_final = right_text.endswith("#")
        if word_initial:
            left_text = left_text[1:].strip()
        if word_final:
            right_text = right_text[:-1].strip()
        if "#" in left_text or "#" in right_text:
            raise ValueError("'#' is only valid at an outer word boundary")
        environment = RuleEnvironment(
            left=SegmentExpression(tokens=_tokens(left_text)) if left_text else None,
            right=SegmentExpression(tokens=_tokens(right_text)) if right_text else None,
            word_initial=word_initial,
            word_final=word_final,
        )
    else:
        environment = RuleEnvironment()

    target_tokens = _tokens(raw_target)
    replacement_tokens = _tokens(raw_replacement, allow_empty=True)
    if target_tokens == replacement_tokens:
        raise NoOpRuleError(
            "a sound rule must change its target; represent identity "
            "reconstruction with an empty rule set"
        )

    normalized_source = source.strip()
    stable_id = rule_id or (
        f"rule-{hashlib.sha256(normalized_source.encode()).hexdigest()[:12]}"
    )
    return ParsedSoundRule(
        rule_id=stable_id,
        source=normalized_source,
        target=SegmentExpression(tokens=target_tokens),
        replacement=SegmentExpression(tokens=replacement_tokens),
        environment=environment,
    )
