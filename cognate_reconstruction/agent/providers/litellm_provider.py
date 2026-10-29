"""LiteLLM adapter for OpenAI, Anthropic, Gemini, and open-weight models."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from cognate_reconstruction.agent.providers.errors import (
    ProviderTransientError, ProviderError, ProviderFailureMetadata, ProviderFailureKind, normalized_provider_error,
)
from cognate_reconstruction.agent.providers.pricing import TokenPrice, priced_cost
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


# LiteLLM smuggles a Gemini 3 thought signature into the OpenAI-shaped tool-call
# ID, joined by this separator, because the OpenAI contract has nowhere else to
# put it. The signature is transport state, not reconstruction evidence: it must
# come back on the next request or Gemini rejects the turn, but the harness must
# never show it to the model. A committed hypothesis quotes the
# validation_call_id of the test that licensed it, so an ID carrying a kilobyte
# of base64 would be the model's problem to reproduce verbatim, and would land
# in trajectories as noise. The adapter therefore splits the signature off on
# arrival, keeps the short ID everywhere the harness and the model can see, and
# restores the signature on the way out through the field LiteLLM reads first.
THOUGHT_SIGNATURE_SEPARATOR = "__thought__"
# LiteLLM provider prefixes that reach Gemini (AI Studio or Vertex AI).
GEMINI_ROUTES = ("gemini", "vertex_ai")


def _split_thought_signature(call_id: str) -> tuple[str, str | None]:
    prefix, separator, signature = call_id.partition(THOUGHT_SIGNATURE_SEPARATOR)
    if not separator or not prefix or not signature:
        return call_id, None
    return prefix, signature


@dataclass(frozen=True)
class ReasoningHistory:
    """Resend the model's own reasoning within the current tool loop.

    Off by default: earlier steps go back as tool calls only. Gemma 4's template
    renders a whole tool loop as one model turn and shows earlier thoughts only
    when the client sends them, so without them the model sees a run of
    thoughtless calls and continues it with an empty thought (R03 §17a). The
    most recent steps keep their reasoning in full up to `budget_tokens`; older
    ones keep their first `older_head_tokens`, so the pattern of thinking before
    a call stays visible at little cost. Reasoning before the last user message
    is never resent; both supported templates drop it there anyway.
    """

    budget_tokens: int
    older_head_tokens: int = 200

    def __post_init__(self) -> None:
        if self.budget_tokens < 0 or self.older_head_tokens < 0:
            raise ValueError("reasoning history budgets must be non-negative")

    def setting(self) -> dict[str, Any]:
        return {"mode": "keep", "budget_tokens": self.budget_tokens,
                "older_head_tokens": self.older_head_tokens}


class LiteLLMProvider:
    """Normalize LiteLLM's OpenAI-shaped native tool-calling response."""

    supports_timeout_override = True

    def __init__(
        self,
        model: str,
        *,
        completion_kwargs: Mapping[str, Any] | None = None,
        completion_fn: Callable[..., object] | None = None,
        price: TokenPrice | None = None,
        reasoning_history: ReasoningHistory | None = None,
    ) -> None:
        self.model = model
        self.reasoning_history = reasoning_history
        # What `--reasoning-history` decided and why, for the run summary; set by the CLI.
        self.reasoning_decision: dict[str, Any] | None = None
        if price is not None and price.model != model:
            raise ValueError(f"price entry is for {price.model!r}, not {model!r}")
        # An explicit operator price replaces LiteLLM's model-cost map for this
        # model; see `pricing`. The adapter's own figure is still recorded.
        self.price = price
        self.completion_kwargs = dict(completion_kwargs or {})
        reserved = {"model", "messages", "tools", "tool_choice"}
        if overlap := sorted(reserved & self.completion_kwargs.keys()):
            raise ValueError(f"completion_kwargs contains reserved keys: {overlap}")
        if any(self.completion_kwargs.get(key) for key in (
            "num_retries", "max_retries", "retry_policy", "fallbacks", "context_window_fallback_dict",
        )):
            raise ValueError("provider-managed retries/fallbacks are unsupported; use the harness retry controls")
        self._completion_fn = completion_fn
        # Keyed by the short call ID the harness and the model see. Kept on the
        # adapter rather than on LLMToolCall so the audit artifacts stay free of
        # opaque provider state. A session resumed with a fresh adapter loses
        # them, and LiteLLM then substitutes Google's documented
        # skip-the-validator placeholder, which degrades rather than fails.
        self._thought_signatures: dict[str, str] = {}
        # Same keying and the same resume caveat: the text of one response's
        # reasoning and its reported token count, under its first call's ID.
        # Only responses that made a call are kept; a response that spent its
        # budget thinking and called nothing is not worth its tokens again.
        self._reasoning: dict[str, tuple[str, int]] = {}

    def _tool_call_payload(self, call: LLMToolCall) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": call.call_id,
            "type": "function",
            "function": {
                "name": call.name,
                "arguments": json.dumps(call.arguments),
            },
        }
        signature = self._thought_signatures.get(call.call_id)
        if signature is not None:
            payload["provider_specific_fields"] = {"thought_signature": signature}
        return payload

    def _messages_payload(self, messages: Sequence[LLMMessage]) -> list[dict[str, Any]]:
        payload = [self._message_payload(message) for message in messages]
        if self.reasoning_history is None:
            return payload
        last_user = max((i for i, m in enumerate(messages) if m.role is MessageRole.USER), default=-1)
        remaining = self.reasoning_history.budget_tokens
        for index in range(len(messages) - 1, last_user, -1):
            message = messages[index]
            stored = self._reasoning.get(message.tool_calls[0].call_id) if message.tool_calls else None
            if stored is None:
                continue
            text, tokens = stored
            if tokens <= remaining:
                remaining -= tokens
            else:
                # Spent: older steps keep only a head, cut at the same
                # characters-per-token rate the full text had.
                remaining = 0
                head = len(text) * self.reasoning_history.older_head_tokens // max(tokens, 1)
                if head <= 0:
                    continue
                text = text[:head].rstrip() + " …"
            payload[index]["reasoning_content"] = text
        return payload

    def _message_payload(self, message: LLMMessage) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": message.role.value}
        content = message.content
        if (content == "" and message.role is MessageRole.ASSISTANT and not message.tool_calls
                and self.model.partition("/")[0] in GEMINI_ROUTES):
            # A turn cut off with neither text nor a call goes back as Gemini
            # sent it: without content, which LiteLLM drops. An empty text
            # part has never been sent to Gemini; a user message straight
            # after tool results has, in the banked runs, and was answered.
            content = None
        if content is not None:
            payload["content"] = content
        if message.tool_calls:
            payload["tool_calls"] = [
                self._tool_call_payload(call) for call in message.tool_calls
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
        timeout_override: float | None = None,
    ) -> ProviderResponse:
        completion = self._completion_fn
        if completion is None:
            try:
                import litellm
                from litellm import completion
                if litellm.num_retries:
                    raise ProviderError("global LiteLLM retries must be disabled", metadata=ProviderFailureMetadata(kind=ProviderFailureKind.AUTH))
            except ImportError as error:  # pragma: no cover - environment dependent
                raise ProviderError(
                    "LiteLLMProvider requires the optional 'agent' dependency",
                    metadata=ProviderFailureMetadata(kind=ProviderFailureKind.AUTH),
                ) from error
        # Merged into a copy: the stored options are the user's, and an
        # override applies to this one request only.
        options = dict(self.completion_kwargs)
        options["num_retries"] = 0
        options["max_retries"] = 0
        if max_tokens_override is not None:
            options["max_tokens"] = max_tokens_override
        if timeout_override is not None:
            configured = options.get("timeout")
            options["timeout"] = min(float(configured), timeout_override) if isinstance(configured, (int, float)) else timeout_override
        try:
            response = completion(
                model=self.model,
                messages=self._messages_payload(messages),
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
            raise normalized_provider_error(error) from error
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
            call_id, thought_signature = _split_thought_signature(call_id)
            if thought_signature is None:
                thought_signature = _value(
                    _value(raw_call, "provider_specific_fields") or {},
                    "thought_signature",
                )
            if isinstance(thought_signature, str) and thought_signature:
                self._thought_signatures[call_id] = thought_signature
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
        # Two spellings for one number. Gemini reports it under
        # prompt_tokens_details; the Anthropic-shaped backends report
        # cache_read_input_tokens. Either way it is part of prompt_tokens
        # already, so it is recorded beside the total and never added to it.
        cached_tokens = _value(
            _value(raw_usage, "prompt_tokens_details") or {}, "cached_tokens"
        )
        if cached_tokens is None:
            cached_tokens = _value(raw_usage, "cache_read_input_tokens")
        # One spelling covers every backend that reports it — Gemini, the
        # Anthropic thinking models, the OpenAI reasoning models, xAI. Like the
        # cached count it is a subset of a total already recorded, here of the
        # completion tokens, so it is kept beside output_tokens and never added.
        reasoning_tokens = _value(
            _value(raw_usage, "completion_tokens_details") or {},
            "reasoning_tokens",
        )
        hidden = _value(response, "_hidden_params", {}) or {}
        response_cost = _value(hidden, "response_cost")
        reported_cost = float(response_cost) if response_cost is not None else None
        cost, cost_source = reported_cost, ("provider_reported" if reported_cost is not None else None)
        if self.price is not None:
            table_cost = priced_cost(
                self.price,
                int(prompt_tokens) if prompt_tokens is not None else None,
                int(completion_tokens) if completion_tokens is not None else None,
            )
            # Without both token counts the table cannot price the response;
            # the reported figure, if any, is then the only known cost.
            if table_cost is not None:
                cost, cost_source = table_cost, "price_table"
        usage = None
        if any(
            value is not None
            for value in (
                prompt_tokens,
                completion_tokens,
                total_tokens,
                cached_tokens,
                reasoning_tokens,
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
                cached_input_tokens=(
                    int(cached_tokens) if cached_tokens is not None else None
                ),
                reasoning_output_tokens=(
                    int(reasoning_tokens) if reasoning_tokens is not None else None
                ),
                cost_usd=cost,
                cost_source=cost_source,
                provider_reported_cost_usd=reported_cost,
            )
        reasoning_text = _value(raw_message, "reasoning_content")
        if self.reasoning_history is not None and calls and isinstance(reasoning_text, str) and reasoning_text.strip():
            # Without a reported count, about four characters per token.
            count = int(reasoning_tokens) if reasoning_tokens is not None else len(reasoning_text) // 4 + 1
            self._reasoning[calls[0].call_id] = (reasoning_text, count)
        content = _value(raw_message, "content")
        if content is None and not calls:
            # Gemini cut off at max_output_tokens while thinking returns no
            # text and no call. Kept as an empty turn, the orchestrator's
            # truncation recovery runs and the response's usage is recorded;
            # an assistant message with neither would fail validation and,
            # with it, the node, leaving a billed response unpriced.
            content = ""
        return ProviderResponse(
            message=LLMMessage(
                role=MessageRole.ASSISTANT,
                content=content,
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
