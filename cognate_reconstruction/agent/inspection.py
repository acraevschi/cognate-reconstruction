"""Which concepts a node session actually looked at.

Live runs committed reconstructions over 46 concepts after inspecting 5, 12, 12
and 8 of them, and no artifact recorded the difference: a commit that surveyed
everything and a commit that glanced at a handful produced identical records.
This module derives the coverage figure that `ReconstructionDiagnostics` and
`AgentNodeMetrics` report.

It is derived from tool *arguments*, not from tool results, so it says what the
session asked to see. A rejected call still counts — asking to look is looking,
and the rejection is already counted elsewhere.

The one subtlety worth stating: several tools treat an empty concept scope as
"every concept". A `summarize_correspondences` call that narrows to nothing is
the widest survey the harness offers, so reading its empty `concept_ids` as
"inspected zero concepts" would invert the number it is meant to report.
`WHOLE_LEXICON_WHEN_UNSCOPED` names exactly those tools; every other tool
contributes only the IDs it actually names.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any

WHOLE_LEXICON_WHEN_UNSCOPED = frozenset(
    {
        "summarize_correspondences",
        "polarize",
        "test_sound_law",
        "test_rule_cascade",
    }
)
"""Tools that cover every concept of their scope when `concept_ids` is empty.

`get_alignments` is excluded because its own validator refuses a call naming
neither concepts nor forms. `search_forms` is excluded because an unscoped
search is paginated and returns one bounded page, not the lexicon. `list_concepts`
is excluded because listing concept names is not inspecting their forms.
"""

_CONCEPT_KEYS = frozenset({"concept_id", "concept_ids"})
_FORM_KEYS = frozenset({"form_id", "form_ids", "supporting_form_ids"})


def _named_values(arguments: Mapping[str, Any], keys: Collection[str]) -> set[str]:
    """Collect string values stored under the given keys, nested lists included.

    Tool arguments arrive as provider-supplied JSON rather than as validated
    models — this runs before, or independently of, the tool's own parsing — so
    anything that is not a string is skipped rather than trusted.
    """
    found: set[str] = set()

    def walk(node: Any, key: str | None) -> None:
        if isinstance(node, Mapping):
            for child_key, value in node.items():
                walk(value, child_key)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value, key)
        elif isinstance(node, str) and key in keys:
            found.add(node)

    walk(arguments, None)
    return found


def inspected_concept_ids(
    tool_name: str,
    arguments: Mapping[str, Any],
    *,
    concepts_by_form_id: Mapping[str, str],
    available_concept_ids: Collection[str],
) -> set[str]:
    """Concepts one tool call brought into view, restricted to real ones.

    Unknown IDs are dropped: a hallucinated concept name in a rejected call is
    not evidence anybody inspected, and letting it through would make coverage
    exceed 100%.
    """
    available = set(available_concept_ids)
    named = _named_values(arguments, _CONCEPT_KEYS) & available
    named |= {
        concepts_by_form_id[form_id]
        for form_id in _named_values(arguments, _FORM_KEYS)
        if form_id in concepts_by_form_id
    }
    if not named and tool_name in WHOLE_LEXICON_WHEN_UNSCOPED:
        return available
    return named
