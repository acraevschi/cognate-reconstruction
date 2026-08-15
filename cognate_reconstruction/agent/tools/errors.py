"""Tool rejections: the error type tools raise, and DSL parsing that uses it.

``ToolInputError`` itself is defined in
:mod:`cognate_reconstruction.agent.error_codes`, next to the closed code
vocabulary it names, and is re-exported here because that is where tool authors
look for it. It cannot live in this package: ``agent/context.py`` raises it too,
and importing anything from ``agent.tools`` there would close an import cycle.
"""

from __future__ import annotations

from cognate_reconstruction.agent.error_codes import ToolInputError
from cognate_reconstruction.rules.parser import NoOpRuleError, parse_rule
from cognate_reconstruction.schemas.rules import ParsedSoundRule

__all__ = ["ToolInputError", "parse_rule_or_reject"]


def parse_rule_or_reject(
    dsl: str,
    *,
    rule_id: str | None = None,
) -> ParsedSoundRule:
    """Parse one rule, converting a parser refusal into a coded rejection.

    Both outcomes are exploratory: the model proposed a sound law and the
    deterministic parser evaluated it. The two codes stay distinct because a rule
    that does not parse and a rule that changes nothing call for different
    repairs.
    """
    try:
        return parse_rule(dsl, rule_id=rule_id)
    except NoOpRuleError as error:
        raise ToolInputError(str(error), code="no-op-rule") from error
    except ValueError as error:
        raise ToolInputError(str(error), code="dsl-parse-error") from error
