"""Pydantic-backed native tool registry."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import ValidationError

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.error_codes import (
    UNCLASSIFIED_ERROR_CODE,
    schema_error_code,
)
from cognate_reconstruction.agent.schemas import (
    LLMToolCall,
    LLMToolDefinition,
    ToolError,
    ToolExecutionResult,
)
from cognate_reconstruction.schemas.common import WorkbenchModel

ToolHandler = Callable[[WorkbenchModel, AgentContext, str], WorkbenchModel]
RemediationBuilder = Callable[[AgentContext], str | None]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[WorkbenchModel]
    handler: ToolHandler
    remediation: RemediationBuilder | None = None
    """Fallback remediation for rejections that carry none of their own.

    Schema validation fails before the handler runs, so a tool that can always
    say something concrete about the current session state supplies it here.
    """

    def definition(self) -> LLMToolDefinition:
        return LLMToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.args_model.model_json_schema(),
        )


def _rejection_code(error: Exception) -> str:
    """Name a rejection structurally, whatever raised it.

    A tool that named its own code keeps it. Schema rejections happen before any
    handler runs, so their code is derived from which fields failed and how.
    Anything else is unclassified, which fails closed as a protocol failure.
    """
    code = getattr(error, "code", None)
    if isinstance(code, str) and code:
        return code
    if isinstance(error, ValidationError):
        return schema_error_code(error)
    return UNCLASSIFIED_ERROR_CODE


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"tool {spec.name!r} is already registered")
        self._tools[spec.name] = spec

    def definitions(self) -> tuple[LLMToolDefinition, ...]:
        return tuple(self._tools[name].definition() for name in sorted(self._tools))

    def execute(self, call: LLMToolCall, context: AgentContext) -> ToolExecutionResult:
        spec = self._tools.get(call.name)
        if spec is None:
            return ToolExecutionResult(
                ok=False,
                error=ToolError(
                    error_type="unknown_tool",
                    message=f"unknown tool {call.name!r}",
                    code="unknown-tool",
                ),
            )
        try:
            # JSON validation permits JSON arrays for tuple fields while retaining
            # strict validation for scalar values.
            arguments = spec.args_model.model_validate_json(json.dumps(call.arguments))
            result = spec.handler(arguments, context, call.call_id)
        except (ValidationError, ValueError) as error:
            remediation = getattr(error, "remediation", None)
            if remediation is None and spec.remediation is not None:
                remediation = spec.remediation(context)
            return ToolExecutionResult(
                ok=False,
                error=ToolError(
                    error_type=getattr(error, "error_type", None)
                    or type(error).__name__,
                    message=str(error),
                    code=_rejection_code(error),
                    remediation=remediation,
                ),
            )
        return ToolExecutionResult(ok=True, result=result.model_dump(mode="json"))
