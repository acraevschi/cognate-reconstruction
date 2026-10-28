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


def test_the_digest_records_reasoning_history_only_when_kept(monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    provider, default_digest, default, _ = cli._provider_and_configuration(_args())
    _, drop_digest, _, _ = cli._provider_and_configuration(_args("--reasoning-history", "drop"))
    # The default is auto; with nothing to read it falls back to drop, says so,
    # and hashes exactly like an explicit drop (and like runs before auto).
    assert "reasoning_history" not in default and default_digest == drop_digest
    assert provider.reasoning_decision == {"requested": "auto (default)", "mode": "drop",
                                           "reason": "no chat template to read (pass --chat-template)"}
    assert "dropping earlier reasoning" in capsys.readouterr().err
    provider, _, kept, _ = cli._provider_and_configuration(_args("--reasoning-history", "keep"))
    assert kept["reasoning_history"] == {"mode": "keep", "budget_tokens": 16000, "older_head_tokens": 200}
    assert provider.reasoning_history == ReasoningHistory(16000, 200)
    with pytest.raises(ValueError, match="Gemini keeps thought signatures"):
        cli._provider_and_configuration(cli._parser().parse_args(
            ["infer", "--input", "x.json", "--model", "gemini-3.8-flash", "--preset", "gemini", "--no-preflight",
             "--reasoning-history", "keep"]))


# --reasoning-history auto: decided from the chat template. The templates below
# are synthetic stand-ins for the two vendor patterns, not the vendors' files.
CONTINUING = (  # Gemma 4's shape: one model turn through tool results
    "{%- for m in messages -%}"
    "{%- if m.role == 'assistant' -%}<model>{% if m.reasoning_content %}<thought>{{ m.reasoning_content }}</thought>{% endif %}"
    "{% for c in m.tool_calls %}<call>{{ c.function.name }}</call>{% endfor %}"
    "{%- elif m.role == 'tool' -%}<result>{{ m.content }}</result>"
    "{%- else -%}<{{ m.role }}>{{ m.content }}</{{ m.role }}>{%- endif -%}"
    "{%- endfor -%}"
    "{%- if add_generation_prompt and messages[-1].role != 'tool' -%}<model>{%- endif -%}")
NEW_TURN = (  # Qwen3.6's shape: every step a new assistant turn that opens <think>
    "{%- for m in messages -%}"
    "<{{ m.role }}>{% if m.reasoning_content %}<think>{{ m.reasoning_content }}</think>{% endif %}"
    "{{ m.content }}{% for c in (m.tool_calls or []) %}<call>{{ c.function.name }}</call>{% endfor %}</{{ m.role }}>"
    "{%- endfor -%}"
    "{%- if add_generation_prompt -%}<assistant><think>{%- endif -%}")
IGNORING = CONTINUING.replace("{% if m.reasoning_content %}<thought>{{ m.reasoning_content }}</thought>{% endif %}", "")


def test_template_analysis_separates_the_three_patterns():
    from cognate_reconstruction.agent.providers.chat_template import analyze_template
    cases = {CONTINUING: (True, False, "keep"), NEW_TURN: (True, True, "drop"), IGNORING: (False, False, "drop")}
    for template, (consumes, new_turn, mode) in cases.items():
        analysis = analyze_template(template)
        assert (analysis.consumes_reasoning, analysis.new_turn_after_tool, analysis.mode) == (consumes, new_turn, mode)


def test_a_template_that_cannot_render_a_tool_loop_is_refused():
    from cognate_reconstruction.agent.providers.chat_template import TemplateAnalysisError, analyze_template
    with pytest.raises(TemplateAnalysisError, match="does not render"):
        analyze_template("{{ raise_exception('tools unsupported') }}")


def _lm_studio_home(tmp_path, *, hub=False, override=False):
    import json as _json
    root = tmp_path / ".lmstudio"
    models = root / "models"
    (models / "pub/Model-MLX-4bit").mkdir(parents=True)
    (models / "pub/Model-MLX-4bit/chat_template.jinja").write_text(CONTINUING)
    (models / "pub/Model-MLX-8bit").mkdir(parents=True)
    (models / "pub/Model-MLX-8bit/tokenizer_config.json").write_text(_json.dumps({"chat_template": NEW_TURN}))
    (root / "settings.json").write_text(_json.dumps({"downloadsFolder": str(models)}))
    if hub:
        (root / "hub/models/vendor/model").mkdir(parents=True)
        (root / "hub/models/vendor/model/model.yaml").write_text(
            "model: vendor/model\nbase:\n  - key: pub/model-mlx-4bit\n  - key: pub/model-mlx-8bit\n"
            "customFields:\n  - key: enableThinking\n    defaultValue: true\n"
            "    effects:\n      - type: setJinjaVariable\n        variable: enable_thinking\n")
    if override:
        (root / ".internal/user-concrete-model-default-config/pub").mkdir(parents=True)
        (root / ".internal/user-concrete-model-default-config/pub/Model-MLX-4bit.json").write_text(
            '{"operation": {"fields": [{"key": "llm.prediction.promptTemplate", "value": {}}]}}')
    return tmp_path


def _ps(*entries):
    import json as _json
    return lambda argv: _json.dumps(list(entries))


def test_lm_studio_templates_are_located_by_folder_or_through_the_hub(tmp_path):
    from cognate_reconstruction.agent.providers.chat_template import TemplateAnalysisError, locate_lm_studio_template
    home = _lm_studio_home(tmp_path, hub=True)
    direct = locate_lm_studio_template("m8", home=home, run=_ps({"identifier": "m8", "path": "pub/Model-MLX-8bit"}))
    assert (direct.source, direct.variables, direct.text) == ("pub/Model-MLX-8bit/tokenizer_config.json", {}, NEW_TURN)
    hub = locate_lm_studio_template("vendor/model", home=home, run=_ps(
        {"identifier": "vendor/model", "path": "vendor/model", "quantization": {"name": "4bit"}}))
    assert (hub.source, hub.variables) == ("pub/Model-MLX-4bit/chat_template.jinja", {"enable_thinking": True})
    with pytest.raises(TemplateAnalysisError, match="resolves to"):
        locate_lm_studio_template("vendor/model", home=home, run=_ps({"identifier": "vendor/model", "path": "vendor/model"}))
    with pytest.raises(TemplateAnalysisError, match="not loaded"):
        locate_lm_studio_template("other", home=home, run=_ps())
    overridden = _lm_studio_home(tmp_path / "o", override=True)
    with pytest.raises(TemplateAnalysisError, match="overrides the prompt template"):
        locate_lm_studio_template("m4", home=overridden, run=_ps({"identifier": "m4", "path": "pub/Model-MLX-4bit"}))


def test_the_probe_compares_prompt_tokens_with_and_without_the_field():
    from cognate_reconstruction.agent.providers.chat_template import probe_reasoning_consumption
    bodies = []

    def post(body):
        bodies.append(body)
        rendered = any(m.get("reasoning_content") for m in body["messages"])
        return {"usage": {"prompt_tokens": 85 + (345 if rendered else 0)}}

    assert probe_reasoning_consumption("http://x/v1", None, "m", post=post) == {
        "prompt_tokens_without": 85, "prompt_tokens_with": 430, "consumed": True}
    assert all(b["max_tokens"] == 1 and isinstance(b["messages"][2]["tool_calls"][0]["function"]["arguments"], str)
               for b in bodies)


def test_auto_resolves_from_the_template_and_records_why(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    continuing, new_turn = tmp_path / "continuing.jinja", tmp_path / "new.jinja"
    continuing.write_text(CONTINUING)
    new_turn.write_text(NEW_TURN)
    provider, _, public, _ = cli._provider_and_configuration(_args("--chat-template", str(continuing)))
    assert provider.reasoning_history == ReasoningHistory(16000, 200)
    assert public["reasoning_history"] == {"mode": "keep", "budget_tokens": 16000, "older_head_tokens": 200}
    record = provider.reasoning_decision
    assert (record["requested"], record["mode"], record["template_source"], record["probe"]) == (
        "auto (default)", "keep", "file:continuing.jinja", None)
    provider, _, public, _ = cli._provider_and_configuration(_args("--reasoning-history", "auto", "--chat-template", str(new_turn)))
    assert provider.reasoning_history is None and "reasoning_history" not in public
    assert (provider.reasoning_decision["requested"], provider.reasoning_decision["mode"],
            provider.reasoning_decision["new_turn_after_tool"]) == ("auto", "drop", True)
    gemini, _, public, _ = cli._provider_and_configuration(cli._parser().parse_args(
        ["infer", "--input", "x.json", "--model", "gemini-3.8-flash", "--preset", "gemini", "--no-preflight"]))
    assert "reasoning_history" not in public
    assert gemini.reasoning_decision == {"requested": "auto (default)", "reason": "Gemini keeps thought signatures",
                                         "mode": "drop"}


def test_auto_refuses_when_the_server_disagrees_with_the_template(tmp_path, monkeypatch):
    template = tmp_path / "continuing.jinja"
    template.write_text(CONTINUING)
    monkeypatch.setattr(cli, "_lm_studio_models", lambda base, key: ("m",))
    monkeypatch.setattr(cli, "probe_reasoning_consumption", lambda base, key, model: {
        "prompt_tokens_without": 85, "prompt_tokens_with": 85, "consumed": False})
    argv = ["infer", "--input", "x.json", "--model", "m", "--preset", "lm-studio", "--chat-template", str(template)]
    with pytest.raises(ValueError, match="server ignored it"):
        cli._provider_and_configuration(cli._parser().parse_args(argv + ["--reasoning-history", "auto"]))
    # The same disagreement under the default falls back to drop instead.
    provider, _, _, _ = cli._provider_and_configuration(cli._parser().parse_args(argv))
    assert provider.reasoning_history is None and "server ignored it" in provider.reasoning_decision["reason"]


def test_explicit_auto_refuses_what_the_default_falls_back_from(monkeypatch):
    from cognate_reconstruction.agent.providers.chat_template import TemplateAnalysisError

    def not_loaded(model):
        raise TemplateAnalysisError(f"{model!r} is not loaded in LM Studio")

    monkeypatch.setattr(cli, "locate_lm_studio_template", not_loaded)
    with pytest.raises(ValueError, match="--reasoning-history auto: .*not loaded"):
        cli._provider_and_configuration(cli._parser().parse_args(
            ["infer", "--input", "x.json", "--model", "no-such-model", "--preset", "lm-studio", "--no-preflight",
             "--reasoning-history", "auto"]))


def test_the_run_summary_carries_the_decision_only_when_there_is_one():
    summary = {"run_id": "r", "status": "finished"}
    assert cli._with_reasoning_history(summary, None) is summary
    decided = {"requested": "auto", "mode": "drop", "reason": "the template opens a new turn after a tool result"}
    assert cli._with_reasoning_history(summary, decided) == {**summary, "reasoning_history": decided}
