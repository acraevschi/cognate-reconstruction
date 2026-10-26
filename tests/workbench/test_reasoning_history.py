"""Resending the model's own reasoning within a tool loop (R03 §17a)."""
from __future__ import annotations

import pytest

from cognate_reconstruction import cli
from cognate_reconstruction.agent.providers import LiteLLMProvider
from cognate_reconstruction.agent.providers.litellm_provider import ReasoningHistory
from cognate_reconstruction.agent.schemas import LLMMessage, LLMToolCall, MessageRole


def _response(call_id, reasoning, reasoning_tokens):
    calls = [{"id": call_id, "type": "function", "function": {"name": "lookup", "arguments": "{}"}}] if call_id else []
    return {"choices": [{"message": {"content": "", "tool_calls": calls, "reasoning_content": reasoning},
                         "finish_reason": "tool_calls" if calls else "length"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": reasoning_tokens + 5,
                      "completion_tokens_details": {"reasoning_tokens": reasoning_tokens}}}


class Recorder:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []

    def __call__(self, **kwargs):
        self.requests.append(kwargs["messages"])
        return self.responses.pop(0)


def _loop(provider, steps):
    """Run a tool loop: one user message, then call -> result per step."""
    messages = [LLMMessage(role=MessageRole.SYSTEM, content="s"), LLMMessage(role=MessageRole.USER, content="u")]
    for _ in range(steps):
        reply = provider.complete(messages, ())
        messages.append(reply.message)
        for call in reply.message.tool_calls:
            messages.append(LLMMessage(role=MessageRole.TOOL, content="{}", tool_call_id=call.call_id, name=call.name))
    return messages


def test_reasoning_is_dropped_by_default():
    fake = Recorder([_response("c1", "think one", 3), _response("c2", "think two", 3)])
    _loop(LiteLLMProvider("openai/m", completion_fn=fake), 2)
    assert all("reasoning_content" not in m for m in fake.requests[-1])


def test_recent_reasoning_is_kept_in_full_and_older_steps_keep_a_head():
    long_text = "a" * 400  # 100 tokens at the reported rate
    fake = Recorder([_response("c1", long_text, 100), _response("c2", "b" * 40, 10),
                     _response("c3", "c" * 40, 10), _response("c4", "d", 1)])
    provider = LiteLLMProvider("openai/m", completion_fn=fake,
                               reasoning_history=ReasoningHistory(budget_tokens=25, older_head_tokens=5))
    _loop(provider, 4)
    sent = [m.get("reasoning_content") for m in fake.requests[-1] if m["role"] == "assistant"]
    # Newest first: 10 + 10 fit the budget of 25; the 100-token step does not
    # and keeps its first 5 tokens' worth of characters.
    assert sent == ["a" * 20 + " …", "b" * 40, "c" * 40]
    assert all("reasoning_content" not in m for m in fake.requests[0] if m["role"] != "assistant")


def test_reasoning_before_the_last_user_message_and_from_call_less_responses_is_not_resent():
    fake = Recorder([_response("c1", "before the correction", 4), _response(None, "x" * 4000, 1000),
                     _response("c2", "after", 1), _response("c3", "next", 1)])
    provider = LiteLLMProvider("openai/m", completion_fn=fake, reasoning_history=ReasoningHistory(budget_tokens=10_000))
    messages = _loop(provider, 1)
    # A truncated response that called nothing: its reasoning is not stored.
    provider.complete(messages, ())
    messages.append(LLMMessage(role=MessageRole.USER, content="Stop. A protocol correction."))
    messages = messages + _loop_from(provider, messages, 2)
    sent = {m["tool_calls"][0]["id"]: m.get("reasoning_content") for m in fake.requests[-1]
            if m["role"] == "assistant" and m.get("tool_calls")}
    assert sent == {"c1": None, "c2": "after"}
    assert len(provider._reasoning) == 3


def _loop_from(provider, messages, steps):
    added = []
    for _ in range(steps):
        reply = provider.complete(messages + added, ())
        added.append(reply.message)
        for call in reply.message.tool_calls:
            added.append(LLMMessage(role=MessageRole.TOOL, content="{}", tool_call_id=call.call_id, name=call.name))
    return added


def _args(*extra):
    return cli._parser().parse_args(["infer", "--input", "x.json", "--model", "m", "--preset", "lm-studio",
                                     "--no-preflight", *extra])


def test_the_digest_records_reasoning_history_only_when_kept(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    _, _, default, _ = cli._provider_and_configuration(_args())
    provider, _, kept, _ = cli._provider_and_configuration(_args("--reasoning-history", "keep"))
    assert "reasoning_history" not in default
    assert kept["reasoning_history"] == {"mode": "keep", "budget_tokens": 16000, "older_head_tokens": 200}
    assert provider.reasoning_history == ReasoningHistory(16000, 200)
    with pytest.raises(ValueError, match="Gemini keeps thought signatures"):
        cli._provider_and_configuration(cli._parser().parse_args(
            ["infer", "--input", "x.json", "--model", "gemini-3.8-flash", "--preset", "gemini", "--no-preflight",
             "--reasoning-history", "keep"]))
