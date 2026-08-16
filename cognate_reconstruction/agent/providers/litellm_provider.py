"""LiteLLM adapter for OpenAI, Anthropic, Gemini, and open-weight models."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from cognate_reconstruction.agent.schemas import (
    LLMMessage,
    LLMToolCall,
    LLMToolDefinition,
    MessageRole,
    ProviderResponse,
    ProviderResponseMetadata,
    ProviderUsage,
)


def _value(item: object, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


class LiteLLMProvider:
    """Normalize LiteLLM's OpenAI-shaped native tool-calling response."""

    def __init__(
        self,
        model: str,
        *,
        completion_kwargs: Mapping[str, Any] | None = None,
        completion_fn: Callable[..., object] | None = None,
    ) -> None:
        self.model = model
        self.completion_kwargs = dict(completion_kwargs or {})
        reserved = {"model", "messages", "tools", "tool_choice"}
        if overlap := sorted(reserved & self.completion_kwargs.keys()):
            raise ValueError(f"completion_kwargs contains reserved keys: {overlap}")
        self._completion_fn = completion_fn

    @staticmethod
    def _message_payload(message: LLMMessage) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": message.role.value}
        if message.content is not None:
            payload["content"] = message.content
        if message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.call_id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments),
                    },
                }
                for call in message.tool_calls
            ]
        if message.tool_call_id is not None:
            payload["tool_call_id"] = message.tool_call_id
            payload["name"] = message.name
        return payload

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[LLMToolDefinition],
        *,
        tool_choice: str = "auto",
        max_tokens_override: int | None = None,
    ) -> ProviderResponse:
        completion = self._completion_fn
        if completion is None:
            try:
                from litellm import completion
            except ImportError as error:  # pragma: no cover - environment dependent
                raise RuntimeError(
                    "LiteLLMProvider requires the optional 'agent' dependency"
                ) from error
        # Merged into a copy: the stored options are the user's, and an
        # override applies to this one request only.
        options = dict(self.completion_kwargs)
        if max_tokens_override is not None:
            options["max_tokens"] = max_tokens_override
        try:
            response = completion(
                model=self.model,
                messages=[self._message_payload(message) for message in messages],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": tool.parameters,
                        },
                    }
                    for tool in tools
                ],
                tool_choice=tool_choice,
                **options,
            )
        except Exception as error:
            if _is_transient_error(error):
                raise ProviderTransientError(str(error)) from error
            raise
        choices = _value(response, "choices")
        if not choices:
            raise ValueError("LLM provider returned no choices")
        raw_message = _value(choices[0], "message")
        calls: list[LLMToolCall] = []
        for raw_call in _value(raw_message, "tool_calls", ()) or ():
            function = _value(raw_call, "function")
            call_id = _value(raw_call, "id")
            name = _value(function, "name")
            if not isinstance(call_id, str) or not call_id.strip():
                raise ValueError("tool call is missing a non-empty ID")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("tool call is missing a non-empty function name")
            raw_arguments = _value(function, "arguments", "{}")
            arguments = (
                json.loads(raw_arguments)
                if isinstance(raw_arguments, str)
                else dict(raw_arguments)
            )
            if not isinstance(arguments, dict):
                raise ValueError("tool-call arguments must decode to a JSON object")
            calls.append(
                LLMToolCall(
                    call_id=call_id,
                    name=name,
                    arguments=arguments,
                )
            )
        raw_usage = _value(response, "usage")
        prompt_tokens = _value(raw_usage, "prompt_tokens")
        completion_tokens = _value(raw_usage, "completion_tokens")
        total_tokens = _value(raw_usage, "total_tokens")
        hidden = _value(response, "_hidden_params", {}) or {}
        response_cost = _value(hidden, "response_cost")
        usage = None
        if any(
            value is not None
            for value in (
                prompt_tokens,
                completion_tokens,
                total_tokens,
                response_cost,
            )
        ):
            usage = ProviderUsage(
                input_tokens=(
                    int(prompt_tokens) if prompt_tokens is not None else None
                ),
                output_tokens=(
                    int(completion_tokens)
                    if completion_tokens is not None
                    else None
                ),
                total_tokens=(
                    int(total_tokens) if total_tokens is not None else None
                ),
                cost_usd=(
                    float(response_cost) if response_cost is not None else None
                ),
            )
        return ProviderResponse(
            message=LLMMessage(
                role=MessageRole.ASSISTANT,
                content=_value(raw_message, "content"),
                tool_calls=tuple(calls),
            ),
            metadata=ProviderResponseMetadata(
                provider_id=(
                    _value(hidden, "custom_llm_provider")
                    or self.model.partition("/")[0]
                ),
                model_id=_value(response, "model") or self.model,
                response_id=_value(response, "id"),
                finish_reason=_value(choices[0], "finish_reason"),
                usage=usage,
            ),
        )


class ProviderTransientError(RuntimeError):
    """Normalized retryable provider or transport failure."""


def _is_transient_error(error: Exception) -> bool:
    if isinstance(error, (TimeoutError, ConnectionError)):
        return True
    status = (
        getattr(error, "status_code", None)
        or getattr(error, "http_status", None)
        or getattr(error, "status", None)
    )
    if status in {408, 409, 425, 429, 500, 502, 503, 504}:
        return True
    name = type(error).__name__.lower()
    return any(
        marker in name
        for marker in (
            "timeout",
            "ratelimit",
            "serviceunavailable",
            "connection",
            "internalserver",
        )
    )
