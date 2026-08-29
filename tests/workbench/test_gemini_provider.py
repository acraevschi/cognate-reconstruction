"""The Gemini path: thought signatures, schema translation, and the preset.

Gemini is reached through LiteLLM like every other backend, so most of the
adapter needs no Gemini-specific code. Three things do not survive that
generality on their own, and each is pinned here: the thought signature LiteLLM
smuggles through the tool-call ID, the JSON Schema dialect Gemini accepts, and
the preset that names the model and the key.
"""

from __future__ import annotations

import argparse
import json

import pytest

from cognate_reconstruction import cli
from cognate_reconstruction.agent.providers import LiteLLMProvider
from cognate_reconstruction.agent.providers.litellm_provider import (
    THOUGHT_SIGNATURE_SEPARATOR,
)
from cognate_reconstruction.agent.schemas import (
    LLMMessage,
    LLMToolCall,
    LLMToolDefinition,
    MessageRole,
)
from cognate_reconstruction.agent.tools import default_tool_registry

SIGNATURE = "Cq4BAdHtim9zaGFkb3d5IGludGVybmFsIHN0YXRl"
_TOOL = (
    LLMToolDefinition(
        name="commit_reconstruction",
        description="commit",
        parameters={"type": "object"},
    ),
)


def _responder(captured: dict, call_id: str, extra_call_fields: dict | None = None):
    def completion(**kwargs):
        captured.update(kwargs)
        call = {
            "id": call_id,
            "function": {"name": "commit_reconstruction", "arguments": "{}"},
            **(extra_call_fields or {}),
        }
        return {
            "id": "response-1",
            "model": "gemini-3.7-flash",
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {"content": None, "tool_calls": [call]},
                }
            ],
        }

    return completion


def _complete(provider: LiteLLMProvider, messages=None):
    return provider.complete(
        messages or (LLMMessage(role=MessageRole.USER, content="reconstruct"),),
        _TOOL,
    )


def test_thought_signature_is_stripped_from_the_id_the_model_is_shown() -> None:
    """The ID the harness records is the short one, not the signed one.

    A committed hypothesis quotes the validation_call_id of the test that
    licensed it. If the signature stayed on, the model would have to reproduce a
    kilobyte of base64 to cite its own evidence.
    """
    captured: dict = {}
    provider = LiteLLMProvider(
        "gemini/gemini-3.7-flash",
        completion_fn=_responder(
            captured, f"call_abc123{THOUGHT_SIGNATURE_SEPARATOR}{SIGNATURE}"
        ),
    )
    response = _complete(provider)
    assert response.tool_calls[0].call_id == "call_abc123"
    assert SIGNATURE not in response.tool_calls[0].call_id


def test_the_signature_is_restored_on_the_next_request() -> None:
    """Gemini 3 rejects a tool-call turn replayed without its signature."""
    captured: dict = {}
    provider = LiteLLMProvider(
        "gemini/gemini-3.7-flash",
        completion_fn=_responder(
            captured, f"call_abc123{THOUGHT_SIGNATURE_SEPARATOR}{SIGNATURE}"
        ),
    )
    first = _complete(provider)
    _complete(
        provider,
        (
            LLMMessage(role=MessageRole.USER, content="reconstruct"),
            first.message,
            LLMMessage(
                role=MessageRole.TOOL,
                content="{}",
                tool_call_id="call_abc123",
                name="commit_reconstruction",
            ),
        ),
    )
    replayed = captured["messages"][1]["tool_calls"][0]
    assert replayed["id"] == "call_abc123"
    assert replayed["provider_specific_fields"] == {"thought_signature": SIGNATURE}


def test_a_signature_sent_beside_the_id_is_carried_too() -> None:
    captured: dict = {}
    provider = LiteLLMProvider(
        "gemini/gemini-3.7-flash",
        completion_fn=_responder(
            captured,
            "call_abc123",
            {"provider_specific_fields": {"thought_signature": SIGNATURE}},
        ),
    )
    first = _complete(provider)
    assert first.tool_calls[0].call_id == "call_abc123"
    _complete(
        provider,
        (LLMMessage(role=MessageRole.USER, content="again"), first.message),
    )
    replayed = captured["messages"][1]["tool_calls"][0]
    assert replayed["provider_specific_fields"] == {"thought_signature": SIGNATURE}


def test_a_backend_without_signatures_sends_no_provider_fields() -> None:
    """The local OpenAI-compatible path must be byte-for-byte what it was."""
    captured: dict = {}
    provider = LiteLLMProvider(
        "openai/local-model", completion_fn=_responder(captured, "call_abc123")
    )
    first = _complete(provider)
    _complete(
        provider,
        (LLMMessage(role=MessageRole.USER, content="again"), first.message),
    )
    assert captured["messages"][1]["tool_calls"][0] == {
        "id": "call_abc123",
        "type": "function",
        "function": {"name": "commit_reconstruction", "arguments": "{}"},
    }


@pytest.mark.parametrize(
    "call_id", ["call_abc123", f"{THOUGHT_SIGNATURE_SEPARATOR}sig", "plain"]
)
def test_ids_without_a_signature_are_left_alone(call_id: str) -> None:
    captured: dict = {}
    provider = LiteLLMProvider(
        "gemini/gemini-3.7-flash", completion_fn=_responder(captured, call_id)
    )
    assert _complete(provider).tool_calls[0].call_id == call_id


def test_every_tool_schema_survives_gemini_s_dialect() -> None:
    """Gemini takes an OpenAPI subset, not the JSON Schema Pydantic emits.

    The thirteen tools are described by Pydantic models, so their schemas carry
    $defs, $ref, additionalProperties, and exclusiveMinimum. LiteLLM rewrites
    them; this asserts the rewrite is total, because a leftover keyword is a
    400 on the first call of every run rather than a degraded one.
    """
    from litellm.llms.vertex_ai.gemini.vertex_and_google_ai_studio_gemini import (
        VertexGeminiConfig,
    )

    definitions = default_tool_registry().definitions()
    declarations = VertexGeminiConfig()._map_function(
        value=[
            {
                "type": "function",
                "function": {
                    "name": definition.name,
                    "description": definition.description,
                    # LiteLLM rewrites in place; the harness's own schemas are
                    # not its to mutate.
                    "parameters": json.loads(json.dumps(definition.parameters)),
                },
            }
            for definition in definitions
        ],
        optional_params={},
    )[0]["function_declarations"]

    assert len(declarations) == len(definitions)
    rejected = {"$ref", "$defs", "additionalProperties", "exclusiveMinimum"}
    seen: set[str] = set()

    def walk(value: object) -> None:
        if isinstance(value, dict):
            seen.update(map(str, value))
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(declarations)
    assert not seen & rejected


def test_a_signed_turn_becomes_a_valid_gemini_request() -> None:
    """Assemble the request Google would actually receive, without sending it.

    The adapter, the tool schemas, and the signature carry-over are each pinned
    above; this crosses all three through LiteLLM's own request builder, so a
    LiteLLM upgrade that moves the signature or the schema dialect fails here
    rather than on the first live call of a run.
    """
    from litellm.litellm_core_utils.litellm_logging import Logging
    from litellm.llms.vertex_ai.gemini.transformation import (
        sync_transform_request_body,
    )
    from litellm.utils import get_optional_params

    captured: dict = {}
    provider = LiteLLMProvider(
        "gemini/gemini-3.7-flash",
        completion_kwargs={"api_key": "test-key", "temperature": 0.1},
        completion_fn=_responder(
            captured, f"call_abc123{THOUGHT_SIGNATURE_SEPARATOR}{SIGNATURE}"
        ),
    )
    definitions = default_tool_registry().definitions()
    opening = (
        LLMMessage(role=MessageRole.SYSTEM, content="the agent instructions"),
        LLMMessage(role=MessageRole.USER, content="reconstruct PROTO"),
    )
    first = provider.complete(opening, definitions)
    provider.complete(
        (
            *opening,
            first.message,
            LLMMessage(
                role=MessageRole.TOOL,
                content='{"ok":true}',
                tool_call_id="call_abc123",
                name="commit_reconstruction",
            ),
        ),
        definitions,
    )
    optional_params = get_optional_params(
        model="gemini-3.7-flash",
        custom_llm_provider="gemini",
        temperature=0.1,
        tools=captured["tools"],
        tool_choice="auto",
        reasoning_effort="high",
    )
    body = sync_transform_request_body(
        gemini_api_key="test-key",
        messages=captured["messages"],
        api_base=None,
        model="gemini-3.7-flash",
        client=None,
        timeout=None,
        extra_headers=None,
        optional_params=optional_params,
        logging_obj=Logging(
            model="gemini-3.7-flash",
            messages=captured["messages"],
            stream=False,
            call_type="completion",
            start_time=None,
            litellm_call_id="test",
            function_id="test",
        ),
        custom_llm_provider="gemini",
        litellm_params={},
        vertex_project=None,
        vertex_location=None,
        vertex_auth_header=None,
    )

    model_turn = body["contents"][1]
    assert model_turn["role"] == "model"
    assert model_turn["parts"][0]["thoughtSignature"] == SIGNATURE
    # Gemini's wire format has no tool-call IDs, so the short ID must not
    # appear either: the signature is the only thing that had to survive.
    assert "call_abc123" not in json.dumps(body, default=str)
    assert len(body["tools"][0]["function_declarations"]) == len(definitions)
    assert body["system_instruction"]["parts"][0]["text"] == "the agent instructions"
    assert body["generationConfig"]["temperature"] == 0.1
    assert body["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "high"
    assert body["toolConfig"]["functionCallingConfig"]["mode"] == "AUTO"


def _usage_response(usage: dict):
    def completion(**_):
        return {
            "id": "response-1",
            "model": "gemini-3.7-flash",
            "choices": [
                {"finish_reason": "stop", "message": {"content": "done"}}
            ],
            "usage": usage,
        }

    return completion


def test_cached_prompt_tokens_are_recorded_from_gemini_s_spelling() -> None:
    provider = LiteLLMProvider(
        "gemini/gemini-3.7-flash",
        completion_fn=_usage_response(
            {
                "prompt_tokens": 20880,
                "completion_tokens": 182,
                "total_tokens": 21062,
                "prompt_tokens_details": {"cached_tokens": 20004},
            }
        ),
    )
    usage = _complete(provider).metadata.usage
    assert usage is not None
    assert usage.input_tokens == 20880
    # A subset of the prompt, not an addition to it: the provider counted these
    # as input and discounted the price. Adding them would double-count.
    assert usage.cached_input_tokens == 20004


def test_cached_prompt_tokens_are_recorded_from_the_other_spelling() -> None:
    """Anthropic-shaped backends report the same number under another name."""
    provider = LiteLLMProvider(
        "anthropic/claude",
        completion_fn=_usage_response(
            {
                "prompt_tokens": 20880,
                "completion_tokens": 182,
                "total_tokens": 21062,
                "cache_read_input_tokens": 20004,
            }
        ),
    )
    usage = _complete(provider).metadata.usage
    assert usage is not None
    assert usage.cached_input_tokens == 20004


def test_a_provider_that_reports_no_cache_records_none_not_zero() -> None:
    """A backend without caching and a cold cache are different facts."""
    provider = LiteLLMProvider(
        "openai/local-model",
        completion_fn=_usage_response(
            {"prompt_tokens": 100, "completion_tokens": 5, "total_tokens": 105}
        ),
    )
    usage = _complete(provider).metadata.usage
    assert usage is not None
    assert usage.input_tokens == 100
    assert usage.cached_input_tokens is None


def test_a_response_reporting_only_a_cache_hit_still_carries_usage() -> None:
    provider = LiteLLMProvider(
        "gemini/gemini-3.7-flash",
        completion_fn=_usage_response({"prompt_tokens_details": {"cached_tokens": 7}}),
    )
    usage = _complete(provider).metadata.usage
    assert usage is not None
    assert usage.cached_input_tokens == 7


@pytest.mark.parametrize(
    "model",
    ["gemini/gemini-3.7-flash", "anthropic/claude", "openai/o-series"],
)
def test_reasoning_tokens_are_recorded_whatever_the_backend(model: str) -> None:
    """One spelling covers every provider that reports thinking.

    Gemini, the Anthropic thinking models, the OpenAI reasoning models and xAI
    all land in completion_tokens_details.reasoning_tokens, so this needs no
    per-provider branch — unlike the cached count, which has two spellings.
    """
    provider = LiteLLMProvider(
        model,
        completion_fn=_usage_response(
            {
                "prompt_tokens": 20880,
                "completion_tokens": 528,
                "total_tokens": 21408,
                "completion_tokens_details": {"reasoning_tokens": 400},
            }
        ),
    )
    usage = _complete(provider).metadata.usage
    assert usage is not None
    assert usage.output_tokens == 528
    # A subset of the completion, not an addition: providers bill thinking at
    # the output rate and count it there.
    assert usage.reasoning_output_tokens == 400


def test_a_backend_that_reports_no_thinking_records_none_not_zero() -> None:
    """LM Studio reports no details block; that is silence, not zero thinking."""
    provider = LiteLLMProvider(
        "openai/local-model",
        completion_fn=_usage_response(
            {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        ),
    )
    usage = _complete(provider).metadata.usage
    assert usage is not None
    assert usage.output_tokens == 50
    assert usage.reasoning_output_tokens is None
    assert usage.cached_input_tokens is None


def test_the_reasoning_share_is_summed_across_a_session() -> None:
    from cognate_reconstruction.agent.orchestrator import AgentOrchestrator
    from cognate_reconstruction.agent.schemas import (
        ProviderResponseMetadata,
        ProviderUsage,
    )

    responses = [
        ProviderResponseMetadata(
            usage=ProviderUsage(output_tokens=182, reasoning_output_tokens=120)
        ),
        ProviderResponseMetadata(
            usage=ProviderUsage(output_tokens=346, reasoning_output_tokens=280)
        ),
        ProviderResponseMetadata(usage=ProviderUsage(output_tokens=60)),
    ]
    assert (
        AgentOrchestrator._usage_total(responses, "reasoning_output_tokens") == 400
    )


def test_the_cached_share_is_summed_across_a_session() -> None:
    """The node metric is the session total, the way the other counters are."""
    from cognate_reconstruction.agent.orchestrator import AgentOrchestrator
    from cognate_reconstruction.agent.schemas import (
        ProviderResponseMetadata,
        ProviderUsage,
    )

    responses = [
        ProviderResponseMetadata(
            usage=ProviderUsage(input_tokens=20880, cached_input_tokens=0)
        ),
        ProviderResponseMetadata(
            usage=ProviderUsage(input_tokens=21343, cached_input_tokens=20004)
        ),
        ProviderResponseMetadata(usage=ProviderUsage(input_tokens=21500)),
    ]
    total = AgentOrchestrator._usage_total(responses, "cached_input_tokens")
    assert total == 20004


def test_inspect_run_reads_a_subset_as_a_share_not_a_count() -> None:
    from cognate_reconstruction.inspect_run import _share

    assert _share(117000, 130778, "cached") == " (117000 cached, 89%)"
    assert _share(400, 528, "reasoning") == " (400 reasoning, 76%)"


@pytest.mark.parametrize(
    ("part", "whole"), [(None, 130778), (117000, None), (117000, 0)]
)
def test_inspect_run_stays_silent_when_nothing_was_reported(part, whole) -> None:
    """A backend that does not report must not grow misleading zeroes.

    Nor may a zero denominator divide: a node that recorded no tokens at all is
    a real state, not an arithmetic error.
    """
    from cognate_reconstruction.inspect_run import _share

    assert _share(part, whole, "cached") == ""


def _infer_args(*extra: str, preflight: bool = False) -> argparse.Namespace:
    """Parse a real `infer` command line rather than hand-building a namespace.

    _provider_and_configuration reads far more of the namespace than the
    provider settings, and a hand-built one goes stale the moment a flag is
    added.
    """
    argv = ["infer", "--input", "unused.json", "--preset", "gemini"]
    if not any(item == "--model" for item in extra):
        argv += ["--model", "gemini-3.7-flash"]
    if not preflight:
        argv.append("--no-preflight")
    return cli._parser().parse_args(argv + list(extra))


def test_the_preset_routes_the_model_and_reads_the_default_key(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    provider, _, public, _ = cli._provider_and_configuration(_infer_args())
    assert provider.model == "gemini/gemini-3.7-flash"
    assert provider.completion_kwargs["api_key"] == "test-key"
    # The default host is LiteLLM's own; sending it back would be a no-op that
    # still had to be spelled correctly.
    assert "api_base" not in provider.completion_kwargs
    assert public["model"] == "gemini/gemini-3.7-flash"
    assert public["preset"] == "gemini"


def test_an_already_routed_model_is_not_prefixed_twice(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    for model in ("gemini/gemini-3.7-flash", "vertex_ai/gemini-3.7-flash"):
        provider, _, _, _ = cli._provider_and_configuration(_infer_args("--model", model))
        assert provider.model == model


def test_the_reasoning_budget_reaches_the_provider_and_the_digest(
    monkeypatch,
) -> None:
    """Gemini 3 thinks at 'low' unless told, so this is a behavioural setting."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    provider, digest, public, _ = cli._provider_and_configuration(
        _infer_args("--reasoning-effort", "high")
    )
    assert provider.completion_kwargs["reasoning_effort"] == "high"
    assert public["reasoning_effort"] == "high"
    _, other, _, _ = cli._provider_and_configuration(_infer_args())
    assert digest != other


def test_gemini_defaults_to_the_temperature_google_documents(monkeypatch) -> None:
    """0.1 is right for a local server and documented as harmful here.

    Google's guidance, echoed by a LiteLLM warning on every call: a Gemini 3
    model sampled below 1.0 can loop, reason worse, and fail on hard tasks.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    provider, _, public, _ = cli._provider_and_configuration(_infer_args())
    assert provider.completion_kwargs["temperature"] == 1.0
    assert public["temperature"] == 1.0


def test_an_explicit_temperature_still_wins(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    provider, _, public, _ = cli._provider_and_configuration(
        _infer_args("--temperature", "0.0")
    )
    assert provider.completion_kwargs["temperature"] == 0.0
    assert public["temperature"] == 0.0


def test_the_local_default_temperature_is_unchanged() -> None:
    """The preset must not move the number every banked local run was made at."""
    args = cli._parser().parse_args(
        [
            "infer",
            "--input",
            "unused.json",
            "--preset",
            "lm-studio",
            "--model",
            "local",
            "--no-preflight",
        ]
    )
    provider, _, public, _ = cli._provider_and_configuration(args)
    assert provider.completion_kwargs["temperature"] == 0.1
    assert public["temperature"] == 0.1


def test_the_digest_records_the_temperature_that_was_sent(monkeypatch) -> None:
    """Spelling a default out loud must not change the hash."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    _, implicit, _, _ = cli._provider_and_configuration(_infer_args())
    _, explicit, _, _ = cli._provider_and_configuration(
        _infer_args("--temperature", "1.0")
    )
    assert implicit == explicit


def test_a_seeded_run_against_gemini_is_refused(tmp_path, monkeypatch) -> None:
    """Gemini has no seed. A sweep that thinks it seeded would misreport."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    config = tmp_path / "provider.json"
    config.write_text(json.dumps({"seed": 1000}), encoding="utf-8")
    with pytest.raises(ValueError, match="does not support 'seed'"):
        cli._provider_and_configuration(_infer_args("--provider-config", str(config)))


def test_a_missing_key_is_named_before_any_call(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        cli._provider_and_configuration(_infer_args())


def test_the_preflight_lists_only_models_that_can_generate(monkeypatch) -> None:
    captured: dict = {}

    class _Response:
        def read(self):
            return json.dumps(
                {
                    "models": [
                        {
                            "name": "models/gemini-3.7-flash",
                            "supportedGenerationMethods": ["generateContent"],
                        },
                        {
                            "name": "models/text-embedding-004",
                            "supportedGenerationMethods": ["embedContent"],
                        },
                    ]
                }
            ).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def _urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["headers"] = request.headers
        return _Response()

    monkeypatch.setattr(cli, "urlopen", _urlopen)
    assert cli._gemini_models(cli.DEFAULT_GEMINI_BASE, "test-key") == (
        "gemini-3.7-flash",
    )
    # The key rides in a header. Query strings reach proxies and access logs.
    assert "test-key" not in captured["url"]
    assert captured["headers"]["X-goog-api-key"] == "test-key"


def test_an_unserved_model_is_refused_before_the_run(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(cli, "_gemini_models", lambda *_: ("gemini-3.7-flash",))
    with pytest.raises(ValueError, match="is not served by the Gemini API"):
        cli._provider_and_configuration(
            _infer_args("--model", "gemini-9-imaginary", preflight=True)
        )
