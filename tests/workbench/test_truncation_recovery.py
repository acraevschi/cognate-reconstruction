"""Recovering from a truncated response instead of only naming it.

Two recoveries, deliberately unequal. Forcing a tool call stays inside the
harness's own request-building responsibility and is always on; raising
`max_tokens` overrides an option the user supplied and is off unless asked for.
Nothing here judges a reconstruction.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.events import AgentEventKind
from cognate_reconstruction.agent.orchestrator import (
    AgentOrchestrator,
    ProtocolStallError,
)
from cognate_reconstruction.agent.providers import (
    LiteLLMProvider,
    ProviderTransientError,
)
from cognate_reconstruction.agent.schemas import (
    LLMMessage,
    LLMToolCall,
    LLMToolDefinition,
    MessageRole,
    ProviderResponse,
    ProviderResponseMetadata,
    ProviderUsage,
)
from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm


def _lexicon(variety_id: str, initial: str) -> LanguageLexicon:
    return LanguageLexicon(
        variety_id=variety_id,
        name=variety_id,
        forms=(
            LexicalForm(
                form_id=f"{variety_id}:water",
                variety_id=variety_id,
                concept_id="water",
                segments=(initial, "a"),
            ),
        ),
    )


def _context() -> AgentContext:
    return AgentContext(
        node_id="PROTO",
        child_lexicons=(_lexicon("A", "p"), _lexicon("B", "f")),
        aligner=LingPyAligner(),
    )


class _CollectingSink:
    def __init__(self) -> None:
        self.events: list = []

    def emit(self, event) -> None:
        self.events.append(event)

    def recoveries(self) -> list:
        return [
            event
            for event in self.events
            if event.kind is AgentEventKind.TRUNCATION_RECOVERY
        ]


def _commit() -> LLMMessage:
    return LLMMessage(
        role=MessageRole.ASSISTANT,
        tool_calls=(
            LLMToolCall(
                call_id="commit",
                name="commit_reconstruction",
                arguments={
                    "node_id": "PROTO",
                    "rules": [],
                    "anomalies": [],
                    "summary": "Identity reconstruction.",
                },
            ),
        ),
    )


def _truncated(output_tokens: int | None = 128) -> ProviderResponse:
    """A response that spent its whole budget reasoning and called nothing."""
    return ProviderResponse(
        message=LLMMessage(
            role=MessageRole.ASSISTANT,
            content="Let me work through the correspondences at length",
        ),
        metadata=ProviderResponseMetadata(
            finish_reason="length",
            usage=(
                ProviderUsage(output_tokens=output_tokens)
                if output_tokens is not None
                else None
            ),
        ),
    )


class RecordingProvider:
    """Records exactly what each request carried, then follows a script."""

    model = "scripted/truncating"

    def __init__(
        self,
        *,
        truncations: int = 1,
        reject_required: bool = False,
        output_tokens: int | None = 128,
    ) -> None:
        self.truncations = truncations
        self.reject_required = reject_required
        self.output_tokens = output_tokens
        self.turn = 0
        self.tool_choices: list[str] = []
        self.max_tokens_overrides: list[int | None] = []

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[LLMToolDefinition],
        *,
        tool_choice: str = "auto",
        max_tokens_override: int | None = None,
    ) -> ProviderResponse:
        assert tools
        self.tool_choices.append(tool_choice)
        self.max_tokens_overrides.append(max_tokens_override)
        if tool_choice == "required" and self.reject_required:
            raise ValueError("this backend does not support tool_choice=required")
        self.turn += 1
        if self.turn <= self.truncations:
            return _truncated(self.output_tokens)
        return ProviderResponse(message=_commit())


def test_a_truncated_response_forces_a_tool_call_on_the_next_request() -> None:
    provider = RecordingProvider(truncations=1)
    sink = _CollectingSink()
    result = AgentOrchestrator(
        provider,
        instructions="Commit.",
        event_sink=sink,
    ).run(_context())

    assert provider.tool_choices == ["auto", "required"]
    assert result.trajectory.metrics.forced_tool_choice_count == 1
    assert result.trajectory.metrics.truncated_response_count == 1
    forced = [
        event
        for event in sink.recoveries()
        if event.details["action"] == "forced_tool_choice"
    ]
    assert len(forced) == 1
    assert forced[0].details["tool_choice"] == "required"


def test_a_truncated_response_that_did_call_a_tool_forces_nothing() -> None:
    """Truncation with a tool call is not the failure mode being recovered."""

    class TruncatedButCallingProvider:
        model = "scripted/truncated-with-call"

        def __init__(self) -> None:
            self.tool_choices: list[str] = []

        def complete(
            self,
            messages: Sequence[LLMMessage],
            tools: Sequence[LLMToolDefinition],
            *,
            tool_choice: str = "auto",
            max_tokens_override: int | None = None,
        ) -> ProviderResponse:
            assert tools
            self.tool_choices.append(tool_choice)
            return ProviderResponse(
                message=_commit(),
                metadata=ProviderResponseMetadata(finish_reason="length"),
            )

    provider = TruncatedButCallingProvider()
    result = AgentOrchestrator(provider, instructions="Commit.").run(_context())
    assert provider.tool_choices == ["auto"]
    assert result.trajectory.metrics.truncated_response_count == 1
    assert result.trajectory.metrics.forced_tool_choice_count == 0


def test_a_provider_that_rejects_required_falls_back_without_an_extra_stall() -> None:
    provider = RecordingProvider(truncations=1, reject_required=True)
    sink = _CollectingSink()
    result = AgentOrchestrator(
        provider,
        instructions="Commit.",
        event_sink=sink,
    ).run(_context())

    # One forced attempt, one immediate fallback, then the ordinary path.
    assert provider.tool_choices == ["auto", "required", "auto"]
    assert result.trajectory.completed
    assert result.trajectory.metrics.truncated_response_count == 1
    rejected = [
        event
        for event in sink.recoveries()
        if event.details["action"] == "forced_tool_choice_rejected"
    ]
    assert len(rejected) == 1
    assert rejected[0].details["error_type"] == "ValueError"


def test_a_transient_failure_on_the_forced_attempt_is_still_a_transient_failure() -> None:
    """Retry and budget errors belong to the retry loop, not to tool_choice."""

    class TransientOnRequiredProvider:
        model = "scripted/transient-required"

        def __init__(self) -> None:
            self.tool_choices: list[str] = []

        def complete(
            self,
            messages: Sequence[LLMMessage],
            tools: Sequence[LLMToolDefinition],
            *,
            tool_choice: str = "auto",
            max_tokens_override: int | None = None,
        ) -> ProviderResponse:
            assert tools
            self.tool_choices.append(tool_choice)
            if tool_choice == "required":
                raise ProviderTransientError("gateway timeout")
            return _truncated()

    provider = TransientOnRequiredProvider()
    with pytest.raises(ProviderTransientError):
        AgentOrchestrator(
            provider,
            instructions="Commit.",
            max_retries=1,
            retry_backoff_seconds=0,
            sleep_fn=lambda _: None,
        ).run(_context())
    # Retried as a transient failure, never quietly downgraded to "auto".
    assert provider.tool_choices == ["auto", "required", "required"]


def test_every_truncation_gets_its_own_forced_tool_call() -> None:
    """The later truncations are the ones that end the node.

    Forcing once per node meant the second and third truncated responses drew
    no intervention at all, which is backwards: the node dies on the third.
    """
    provider = RecordingProvider(truncations=99)
    with pytest.raises(ProtocolStallError, match="truncated 3 times") as caught:
        AgentOrchestrator(
            provider,
            instructions="Commit.",
            max_turns=32,
            max_truncated_responses=3,
        ).run(_context())
    assert provider.tool_choices == ["auto", "required", "required"]
    assert "requiring a tool call" in str(caught.value)


def test_a_backend_that_refuses_required_is_not_asked_again() -> None:
    """A refusal is a property of the backend, not of one turn."""
    provider = RecordingProvider(truncations=99, reject_required=True)
    sink = _CollectingSink()
    with pytest.raises(ProtocolStallError):
        AgentOrchestrator(
            provider,
            instructions="Commit.",
            max_turns=32,
            max_truncated_responses=3,
            event_sink=sink,
        ).run(_context())
    # One attempt, one refusal, then the ordinary path for the rest of the node.
    assert provider.tool_choices == ["auto", "required", "auto", "auto"]
    refusals = [
        event
        for event in sink.recoveries()
        if event.details["action"] == "forced_tool_choice_rejected"
    ]
    assert len(refusals) == 1


def test_the_truncation_stall_names_the_observed_output_lengths() -> None:
    """`max_tokens` is the operator's lever; guessing at it was the cost."""
    provider = RecordingProvider(truncations=99, output_tokens=2048)
    with pytest.raises(ProtocolStallError) as caught:
        AgentOrchestrator(
            provider,
            instructions="Commit.",
            max_turns=32,
            max_truncated_responses=3,
        ).run(_context())
    message = str(caught.value)
    assert "reported 2048, 2048, 2048 output tokens (max 2048)" in message


def test_an_unreported_output_length_is_said_to_be_unknown() -> None:
    provider = RecordingProvider(truncations=99, output_tokens=None)
    with pytest.raises(ProtocolStallError) as caught:
        AgentOrchestrator(
            provider,
            instructions="Commit.",
            max_turns=32,
            max_truncated_responses=2,
        ).run(_context())
    assert "reported no output token count" in str(caught.value)


def test_no_max_tokens_override_is_ever_sent_by_default() -> None:
    provider = RecordingProvider(truncations=99)
    with pytest.raises(ProtocolStallError):
        AgentOrchestrator(
            provider,
            instructions="Commit.",
            max_turns=32,
            max_truncated_responses=4,
        ).run(_context())
    assert provider.max_tokens_overrides == [None, None, None, None]


def test_backoff_escalates_geometrically_and_stops_at_the_ceiling() -> None:
    provider = RecordingProvider(truncations=99, output_tokens=100)
    sink = _CollectingSink()
    with pytest.raises(ProtocolStallError):
        AgentOrchestrator(
            provider,
            instructions="Commit.",
            max_turns=32,
            max_truncated_responses=6,
            allow_truncation_backoff=True,
            truncation_max_tokens_ceiling=350,
            event_sink=sink,
        ).run(_context())

    # 100 observed -> 200 -> 400 clipped to the 350 ceiling -> held there.
    assert provider.max_tokens_overrides == [None, 200, 350, 350, 350, 350]
    applied = [
        event
        for event in sink.recoveries()
        if event.details["action"] == "truncation_backoff"
    ]
    assert [event.details["effective_max_tokens"] for event in applied] == [200, 350]
    skipped = [
        event
        for event in sink.recoveries()
        if event.details["action"] == "truncation_backoff_skipped"
    ]
    assert skipped and skipped[0].details["reason"] == "ceiling_reached"


def test_backoff_is_recorded_in_the_metrics_of_a_run_it_rescued() -> None:
    provider = RecordingProvider(truncations=1, output_tokens=100)
    result = AgentOrchestrator(
        provider,
        instructions="Commit.",
        allow_truncation_backoff=True,
        truncation_max_tokens_ceiling=4096,
    ).run(_context())
    assert provider.max_tokens_overrides == [None, 200]
    assert result.trajectory.metrics.truncation_backoff_applied == 1
    assert result.trajectory.metrics.forced_tool_choice_count == 1


def test_backoff_needs_a_reported_output_length_to_stay_above_the_user_option() -> None:
    """Without an observed base there is no way to promise a raise, so none."""
    provider = RecordingProvider(truncations=99, output_tokens=None)
    sink = _CollectingSink()
    with pytest.raises(ProtocolStallError):
        AgentOrchestrator(
            provider,
            instructions="Commit.",
            max_turns=32,
            max_truncated_responses=3,
            allow_truncation_backoff=True,
            truncation_max_tokens_ceiling=4096,
            event_sink=sink,
        ).run(_context())
    assert provider.max_tokens_overrides == [None, None, None]
    skipped = [
        event
        for event in sink.recoveries()
        if event.details["action"] == "truncation_backoff_skipped"
    ]
    assert skipped[0].details["reason"] == "no_reported_output_tokens"


def test_backoff_without_a_ceiling_is_refused() -> None:
    with pytest.raises(ValueError, match="truncation_max_tokens_ceiling"):
        AgentOrchestrator(
            RecordingProvider(),
            instructions="Commit.",
            allow_truncation_backoff=True,
        )


def test_a_nonpositive_ceiling_is_refused() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        AgentOrchestrator(
            RecordingProvider(),
            instructions="Commit.",
            allow_truncation_backoff=True,
            truncation_max_tokens_ceiling=0,
        )


def test_the_backoff_settings_are_part_of_the_configuration_hash() -> None:
    base = AgentOrchestrator(RecordingProvider(), instructions="x")
    enabled = AgentOrchestrator(
        RecordingProvider(),
        instructions="x",
        allow_truncation_backoff=True,
        truncation_max_tokens_ceiling=4096,
    )
    higher = AgentOrchestrator(
        RecordingProvider(),
        instructions="x",
        allow_truncation_backoff=True,
        truncation_max_tokens_ceiling=8192,
    )
    assert base.configuration_sha256 != enabled.configuration_sha256
    assert enabled.configuration_sha256 != higher.configuration_sha256


def test_an_override_never_mutates_the_stored_provider_options() -> None:
    captured: list[dict] = []

    def completion(**kwargs: object) -> object:
        captured.append(dict(kwargs))
        return {
            "id": "response-1",
            "model": "provider/model",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "done", "tool_calls": []},
                }
            ],
        }

    provider = LiteLLMProvider(
        "provider/model",
        completion_kwargs={"max_tokens": 512, "api_base": "http://x.test/v1"},
        completion_fn=completion,
    )
    tools = (
        LLMToolDefinition(
            name="commit_reconstruction",
            description="commit",
            parameters={"type": "object"},
        ),
    )
    messages = (LLMMessage(role=MessageRole.USER, content="test"),)

    provider.complete(messages, tools, tool_choice="required", max_tokens_override=2048)
    provider.complete(messages, tools)

    assert captured[0]["tool_choice"] == "required"
    assert captured[0]["max_tokens"] == 2048
    # The user's option is untouched, so the next request uses it again.
    assert provider.completion_kwargs == {
        "max_tokens": 512,
        "api_base": "http://x.test/v1",
    }
    assert captured[1]["tool_choice"] == "auto"
    assert captured[1]["max_tokens"] == 512
