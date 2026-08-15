"""Structural identifiers for tool rejections, and how they are classified.

A rejected tool call carries two independent things:

- ``message``: the full human-readable rejection, unchanged and unabridged. It
  is what a person reads out of a trajectory, and what the model reads in the
  tool result.
- ``code``: a short, stable machine identifier used *only* for counting and
  matching — stall detection, failure taxonomies, and the exploratory/protocol
  split.

Keeping them separate is what makes the code safe to collapse. Pydantic embeds
input values in its messages, so "missing ``confidence`` on rule 0" and the same
mistake on rule 1 are different strings for one structural defect; a stall
detector keyed on message text is evaded by a model whose malformed arguments
keep changing. Two genuinely distinct problems sharing one code costs nothing in
auditability, because the message is still there.

The vocabulary is closed: every ``ToolInputError`` names one of these codes,
schema rejections derive a ``schema:`` code structurally, and anything else
falls back to :data:`UNCLASSIFIED_ERROR_CODE`.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from pydantic import ValidationError


class ToolErrorCategory(StrEnum):
    """Whether a rejection carries epistemic content or is pure friction.

    A ``test_sound_law`` rejection for a malformed DSL is the hypothesis tester
    doing its job: the model proposed, the tool said no, the model refined. A
    ``commit_reconstruction`` reference error is protocol friction with no
    linguistic content at all. Counting them identically would score a model
    that explores worse than one that never explores, which is backwards for a
    corpus meant to teach tool use.
    """

    EXPLORATORY = "exploratory"
    PROTOCOL = "protocol"


SCHEMA_ERROR_CODE_PREFIX = "schema:"
"""Prefix of every structurally derived Pydantic-rejection code."""

UNCLASSIFIED_ERROR_CODE = "unclassified"
"""Fallback for a rejection that named no code. Fails closed as protocol."""

MAX_SCHEMA_CODE_FIELDS = 6
"""Field/type pairs rendered in a ``schema:`` code before it is summarised.

A cap keeps codes bounded when a model sends wholesale garbage. Truncation stays
deterministic — the pairs are sorted and the remainder is counted — and the full
Pydantic report is still in ``message``.
"""

TOOL_ERROR_CODES: Mapping[str, ToolErrorCategory] = MappingProxyType(
    {
        # -- exploratory: the model proposed a hypothesis and the tool tested it
        # The DSL text did not parse.
        "dsl-parse-error": ToolErrorCategory.EXPLORATORY,
        # The rule's target and replacement are identical.
        "no-op-rule": ToolErrorCategory.EXPLORATORY,
        # The requested child/concept selection matched no form at all.
        "empty-scope": ToolErrorCategory.EXPLORATORY,
        # -- protocol: argument shape, reference, and bookkeeping friction
        # An omitted validation_call_id matched no same-session validation.
        "validation-unresolved": ToolErrorCategory.PROTOCOL,
        # An omitted validation_call_id matched several validations.
        "validation-ambiguous": ToolErrorCategory.PROTOCOL,
        # An explicit validation_call_id names no recorded validation.
        "validation-unknown": ToolErrorCategory.PROTOCOL,
        # The named validation tested a different DSL.
        "validation-mismatch": ToolErrorCategory.PROTOCOL,
        # The named validation tested a different child scope.
        "scope-mismatch": ToolErrorCategory.PROTOCOL,
        # Commit and validation disagree about the segmentation overlay.
        "overlay-mismatch": ToolErrorCategory.PROTOCOL,
        # A segmentation overlay ID does not exist in this session.
        "unknown-overlay": ToolErrorCategory.PROTOCOL,
        # A segmentation request edited a form twice or changed phonetic tokens.
        "overlay-invalid-edit": ToolErrorCategory.PROTOCOL,
        # Committed supporting_form_ids are not a subset of the validation's.
        "unsupported-forms": ToolErrorCategory.PROTOCOL,
        # The rule applied to no form and cannot back a commit.
        "rule-unsupported": ToolErrorCategory.PROTOCOL,
        # cascade_validation_call_id names no recorded cascade preview.
        "cascade-unknown": ToolErrorCategory.PROTOCOL,
        # Committed rule order, DSL, or scope differs from the tested cascade.
        "cascade-signature-mismatch": ToolErrorCategory.PROTOCOL,
        # The commit names a node other than the one being reconstructed.
        "node-mismatch": ToolErrorCategory.PROTOCOL,
        # This node already has a committed reconstruction.
        "already-committed": ToolErrorCategory.PROTOCOL,
        # A rule is scoped to a node that is not an active child.
        "inactive-children": ToolErrorCategory.PROTOCOL,
        # A referenced evidence, child, or prior-hypothesis node is unavailable.
        "unknown-node": ToolErrorCategory.PROTOCOL,
        # A referenced form ID does not exist.
        "unknown-form": ToolErrorCategory.PROTOCOL,
        # The alignment backend refused the requested selection.
        "alignment-failed": ToolErrorCategory.PROTOCOL,
        # An anomaly cites a form or concept outside the active evidence.
        "anomaly-unknown-reference": ToolErrorCategory.PROTOCOL,
        # The model called a tool that is not registered.
        "unknown-tool": ToolErrorCategory.PROTOCOL,
        # No structural code was attached; see UNCLASSIFIED_ERROR_CODE.
        UNCLASSIFIED_ERROR_CODE: ToolErrorCategory.PROTOCOL,
    }
)
"""The closed vocabulary, and the category each code belongs to.

Membership is asserted by the test suite against every code the tools raise, so
a new raise site cannot quietly introduce an unlisted code.
"""


def classify_tool_error_code(code: str | None) -> ToolErrorCategory:
    """Classify one rejection code, failing closed as ``PROTOCOL``.

    Every ``schema:`` code is protocol by construction: a rejection produced
    before the handler ran is an argument-shape problem, never a hypothesis that
    the tool evaluated and refused.
    """
    if code is None:
        return ToolErrorCategory.PROTOCOL
    if code.startswith(SCHEMA_ERROR_CODE_PREFIX):
        return ToolErrorCategory.PROTOCOL
    return TOOL_ERROR_CODES.get(code, ToolErrorCategory.PROTOCOL)


def normalize_error_location(location: tuple[object, ...]) -> str:
    """Render one Pydantic error location with list indices collapsed.

    ``("rules", 0, "confidence")`` and ``("rules", 1, "confidence")`` both render
    as ``rules[].confidence``. That collapse is the point: which element of a
    list was malformed is an input value, not a different mistake, and treating
    it as one is what lets repeated-failure detection see a loop.
    """
    parts: list[str] = []
    for item in location:
        if isinstance(item, int):
            if parts:
                parts[-1] += "[]"
            else:
                parts.append("[]")
        else:
            parts.append(str(item))
    return ".".join(parts) or "<root>"


def schema_error_code(error: ValidationError) -> str:
    """Derive a stable code from the shape of a Pydantic rejection.

    The code is the sorted set of ``(normalized location, error type)`` pairs,
    for example ``schema:rules[].confidence=missing,rules[].dsl=missing``. It
    depends only on which fields failed and how, never on the offending values,
    so it is identical across calls that repeat one mistake with different
    arguments.
    """
    pairs = sorted(
        {
            (normalize_error_location(tuple(item["loc"])), str(item["type"]))
            for item in error.errors()
        }
    )
    shown = pairs[:MAX_SCHEMA_CODE_FIELDS]
    rendered = ",".join(f"{location}={kind}" for location, kind in shown)
    remaining = len(pairs) - len(shown)
    if remaining:
        rendered += f",+{remaining}"
    return SCHEMA_ERROR_CODE_PREFIX + (rendered or "invalid")


class ToolInputError(ValueError):
    """A rejected tool call that also names its code and how to recover.

    ``remediation`` is deterministic text derived from recorded session state,
    never model prose. It is returned inside the tool result and therefore lands
    in the trajectory, so it must stay stable for identical session state.

    ``code`` is required. It is the machine identifier described in this
    module's docstring, and it must be a member of :data:`TOOL_ERROR_CODES`.

    The class lives here rather than in ``agent/tools/errors.py`` — which
    re-exports it — because ``agent/context.py`` raises it too, and importing
    anything from the ``agent.tools`` package there would close an import cycle.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str,
        remediation: str | None = None,
        error_type: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.remediation = remediation
        self.error_type = error_type or type(self).__name__
