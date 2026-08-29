from __future__ import annotations

import json
import re
from collections.abc import Sequence

import pytest

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.orchestrator import AgentOrchestrator
from cognate_reconstruction.agent.provider_config import load_provider_options
from cognate_reconstruction.agent.providers import (
    LiteLLMProvider,
    ProviderTransientError,
)
from cognate_reconstruction.agent.reconstructor import AgenticNodeReconstructor
from cognate_reconstruction.agent.schemas import (
    LLMMessage,
    LLMToolCall,
    LLMToolDefinition,
    MessageRole,
)
from cognate_reconstruction.agent.service import ReconstructionService
from cognate_reconstruction.agent.trajectory import (
    JsonlTrajectorySink,
    TrajectoryDatasetBuilder,
)
from cognate_reconstruction.alignment import LingPyAligner
from cognate_reconstruction.ingestion import ingest_payload
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm
from cognate_reconstruction.traversal import CheckpointStore, FamilyCheckpoint


def _lexicon(variety_id: str) -> LanguageLexicon:
    return LanguageLexicon(
        variety_id=variety_id,
        name=variety_id,
        forms=(
            LexicalForm(
                form_id=f"{variety_id}:water",
                variety_id=variety_id,
                concept_id="water",
                segments=("p",),
            ),
        ),
    )


def _node_id(messages: Sequence[LLMMessage]) -> str:
    match = re.search(r'"node_id":\s*"([^"]+)"', messages[1].content or "")
    assert match is not None
    return match.group(1)


def _commit_message(node_id: str) -> LLMMessage:
    return LLMMessage(
        role=MessageRole.ASSISTANT,
        tool_calls=(
            LLMToolCall(
                call_id=f"commit:{node_id}",
                name="commit_reconstruction",
                arguments={
                    "node_id": node_id,
                    "rules": [],
                    "anomalies": [],
                    "summary": "Visible identity reconstruction.",
                },
            ),
        ),
    )


class RetryThenCommitProvider:
    model = "scripted/retry"

    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[LLMToolDefinition],
        *,
        tool_choice: str = "auto",
        max_tokens_override: int | None = None,
    ) -> LLMMessage:
        assert tools
        self.calls += 1
        if self.calls == 1:
            raise ProviderTransientError("temporary outage")
        return _commit_message(_node_id(messages))


def test_transient_provider_failure_retries_and_records_metrics() -> None:
    provider = RetryThenCommitProvider()
    context = AgentContext(
        node_id="PROTO",
        child_lexicons=(_lexicon("A"), _lexicon("B")),
        aligner=LingPyAligner(),
    )
    result = AgentOrchestrator(
        provider,
        instructions="Commit.",
        max_retries=1,
        retry_backoff_seconds=0,
        sleep_fn=lambda _: None,
    ).run(context)
    assert provider.calls == 2
    assert result.trajectory.metrics.retry_count == 1
    assert result.trajectory.metrics.provider_attempts == 2


class FailOnSecondNodeProvider:
    model = "scripted/fail-second"

    def __init__(self) -> None:
        self.nodes: list[str] = []

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[LLMToolDefinition],
        *,
        tool_choice: str = "auto",
        max_tokens_override: int | None = None,
    ) -> LLMMessage:
        node_id = _node_id(messages)
        self.nodes.append(node_id)
        if node_id == "ROOT":
            raise ProviderTransientError("provider unavailable")
        return _commit_message(node_id)


class CommitProvider:
    model = "scripted/commit"

    def __init__(self) -> None:
        self.nodes: list[str] = []

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[LLMToolDefinition],
        *,
        tool_choice: str = "auto",
        max_tokens_override: int | None = None,
    ) -> LLMMessage:
        node_id = _node_id(messages)
        self.nodes.append(node_id)
        return _commit_message(node_id)


def test_checkpoint_resume_skips_completed_nodes_and_keeps_failed_trajectory(
    tmp_path,
) -> None:
    dataset = ingest_payload(
        WorkbenchPayload(
            lexicons=(_lexicon("A"), _lexicon("B"), _lexicon("C")),
            newick="((A,B)X,C)ROOT;",
        )
    )
    checkpoint_path = tmp_path / "checkpoint.json"
    trajectory_path = tmp_path / "trajectories.jsonl"
    store = CheckpointStore(checkpoint_path)
    checkpoint = FamilyCheckpoint(
        run_id="run-test",
        input_sha256="input-hash",
        configuration_sha256="config-hash",
        normalized_tree_sha256="tree-hash",
    )
    store.save(checkpoint)

    def save_first(step) -> None:
        nonlocal checkpoint
        checkpoint = checkpoint.with_step(step)
        store.save(checkpoint)

    failing = FailOnSecondNodeProvider()
    first_service = ReconstructionService(
        AgenticNodeReconstructor(
            AgentOrchestrator(
                failing,
                instructions="Commit.",
                max_retries=0,
                trajectory_sink=JsonlTrajectorySink(trajectory_path),
                run_id="run-test",
                configuration_sha256="config-hash",
            ),
            # The interrupted-run shape this case is about: without it the
            # traversal falls back over the dead node and reaches the root.
            fail_fast=True,
        )
    )
    with pytest.raises(ProviderTransientError):
        first_service.reconstruct_family(
            dataset,
            on_step_complete=save_first,
        )
    loaded_checkpoint = store.load()
    assert [step.parent_node_id for step in loaded_checkpoint.completed_steps] == [
        "X"
    ]
    trajectories = TrajectoryDatasetBuilder.read_jsonl(trajectory_path)
    assert [item.completed for item in trajectories] == [True, False]
    assert "ProviderTransientError" in (trajectories[1].failure or "")

    resumed_checkpoint = loaded_checkpoint

    def save_resumed(step) -> None:
        nonlocal resumed_checkpoint
        resumed_checkpoint = resumed_checkpoint.with_step(step)
        store.save(resumed_checkpoint)

    completing = CommitProvider()
    second_service = ReconstructionService(
        AgenticNodeReconstructor(
            AgentOrchestrator(
                completing,
                instructions="Commit.",
                trajectory_sink=JsonlTrajectorySink(trajectory_path),
                run_id="run-test",
                configuration_sha256="config-hash",
            )
        )
    )
    result = second_service.reconstruct_family(
        dataset,
        resume_steps=loaded_checkpoint.steps_by_node,
        on_step_complete=save_resumed,
    )
    assert completing.nodes == ["ROOT"]
    assert [step.parent_node_id for step in store.load().completed_steps] == [
        "X",
        "ROOT",
    ]
    assert len(result.snapshot.steps) == 2
    assert len(result.trajectories) == 1


def test_provider_config_rejects_secrets_and_allows_nonsecret_options(
    tmp_path,
) -> None:
    safe = tmp_path / "safe.json"
    safe.write_text(
        json.dumps({"max_tokens": 128, "extra_headers": {"X-Trace": "yes"}}),
        encoding="utf-8",
    )
    assert load_provider_options(safe)["max_tokens"] == 128

    unsafe = tmp_path / "unsafe.json"
    unsafe.write_text(json.dumps({"api_key": "do-not-store"}), encoding="utf-8")
    with pytest.raises(ValueError, match="reserved"):
        load_provider_options(unsafe)


@pytest.mark.parametrize(
    "option",
    [
        "web_search_options",
        "search_parameters",
        "google_search_retrieval",
        "enable_search",
        "url_context",
    ],
)
def test_provider_config_refuses_to_ground_the_model(tmp_path, option) -> None:
    """No provider option may give the model a source outside the tools.

    Named per provider rather than per API: OpenAI and Anthropic spell it
    web_search_options, LiteLLM turns that one into Gemini's googleSearch, xAI
    uses search_parameters. Blocking the option names blocks all of them,
    including for providers this harness cannot reach yet.
    """
    config = tmp_path / "grounded.json"
    config.write_text(json.dumps({option: {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="source outside the"):
        load_provider_options(config)


def test_grounding_is_refused_however_deeply_it_is_buried(tmp_path) -> None:
    config = tmp_path / "nested.json"
    config.write_text(
        json.dumps({"extra_body": [{"tools": {"google_search": {}}}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"extra_body\[0\].tools.google_search"):
        load_provider_options(config)


def test_the_grounding_refusal_says_what_to_do_instead(tmp_path) -> None:
    """A refusal that only forbids invites working around it."""
    config = tmp_path / "grounded.json"
    config.write_text(json.dumps({"web_search_options": {}}), encoding="utf-8")
    with pytest.raises(ValueError) as raised:
        load_provider_options(config)
    assert "add one rather than opening a side channel" in str(raised.value)


def test_the_local_sampling_options_are_untouched_by_the_new_guards(
    tmp_path,
) -> None:
    """The guard must not cost the LM Studio path a single option.

    These are the exact shapes checked into examples/ and written by every
    banked sweep. A guard that rejected one of them would invalidate the
    local workflow the harness is normally driven with.
    """
    config = tmp_path / "local.json"
    config.write_text(
        json.dumps(
            {"top_k": 64, "top_p": 0.95, "repeat_penalty": 1.0, "seed": 1000}
        ),
        encoding="utf-8",
    )
    assert load_provider_options(config) == {
        "top_k": 64,
        "top_p": 0.95,
        "repeat_penalty": 1.0,
        "seed": 1000,
    }


def test_the_checked_in_local_config_still_loads() -> None:
    from pathlib import Path as _Path

    assert load_provider_options(
        _Path("examples/lm_studio_qwen_config.json")
    ) == {"max_tokens": 1024}


def test_litellm_adapter_constructs_request_and_normalizes_usage() -> None:
    captured = {}

    def completion(**kwargs: object) -> object:
        captured.update(kwargs)
        return {
            "id": "response-1",
            "model": "provider/model",
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "function": {
                                    "name": "commit_reconstruction",
                                    "arguments": '{"node_id":"PROTO","rules":[],"anomalies":[],"summary":"identity"}',
                                },
                            }
                        ],
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 4,
                "total_tokens": 14,
            },
            "_hidden_params": {
                "custom_llm_provider": "provider",
                "response_cost": 0.001,
            },
        }

    provider = LiteLLMProvider(
        "provider/model",
        completion_kwargs={"api_base": "http://provider.test/v1"},
        completion_fn=completion,
    )
    response = provider.complete(
        (LLMMessage(role=MessageRole.USER, content="test"),),
        (
            LLMToolDefinition(
                name="commit_reconstruction",
                description="commit",
                parameters={"type": "object"},
            ),
        ),
    )
    assert captured["model"] == "provider/model"
    assert captured["api_base"] == "http://provider.test/v1"
    assert captured["tool_choice"] == "auto"
    assert response.tool_calls[0].name == "commit_reconstruction"
    assert response.metadata.provider_id == "provider"
    assert response.metadata.usage is not None
    assert response.metadata.usage.total_tokens == 14
    assert response.metadata.usage.cost_usd == 0.001
