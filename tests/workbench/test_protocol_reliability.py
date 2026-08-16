"""Failure accounting, unproductive-turn handling, and coverage scoping.

These are workflow and mechanical checks. Nothing here judges whether a
reconstruction is historically correct.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from cognate_reconstruction import cli
from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.events import AgentEventKind
from cognate_reconstruction.agent.orchestrator import (
    AgentOrchestrator,
    ProtocolStallError,
)
from cognate_reconstruction.agent.schemas import (
    LLMMessage,
    LLMToolCall,
    LLMToolDefinition,
    MessageRole,
    ProviderResponse,
    ProviderResponseMetadata,
)
from cognate_reconstruction.agent.trajectory import (
    MAX_PROTOCOL_FAILURE_RATE,
    AgentTrajectory,
    TrajectoryDatasetBuilder,
)
from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.rules import parse_rule
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm
from cognate_reconstruction.schemas.rules import ReconstructionRule
from cognate_reconstruction.traversal import RuleBasedReconstructor
from cognate_reconstruction.traversal.beam import make_leaf_beam

REPO_ROOT = Path(__file__).resolve().parents[2]


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


class MalformedThenValidProvider:
    """Omits confidence twice, then commits correctly."""

    model = "scripted/malformed-then-valid"

    def __init__(self) -> None:
        self.turn = 0

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[LLMToolDefinition],
        *,
        tool_choice: str = "auto",
        max_tokens_override: int | None = None,
    ) -> LLMMessage:
        assert tools
        self.turn += 1
        rule = {"dsl": "f > p / #_", "source_child_ids": ["B"]}
        if self.turn == 1:
            return LLMMessage(
                role=MessageRole.ASSISTANT,
                tool_calls=(
                    LLMToolCall(
                        call_id="inspect",
                        name="list_concepts",
                        arguments={},
                    ),
                ),
            )
        if self.turn == 2:
            return LLMMessage(
                role=MessageRole.ASSISTANT,
                tool_calls=(
                    LLMToolCall(
                        call_id="validate",
                        name="test_sound_law",
                        arguments=dict(rule),
                    ),
                ),
            )
        if self.turn in {3, 4}:
            return LLMMessage(
                role=MessageRole.ASSISTANT,
                tool_calls=(
                    LLMToolCall(
                        call_id=f"bad-commit-{self.turn}",
                        name="commit_reconstruction",
                        arguments={
                            "node_id": "PROTO",
                            "rules": [dict(rule)],
                            "anomalies": [],
                            "summary": "Restore parent initial p.",
                        },
                    ),
                ),
            )
        return LLMMessage(
            role=MessageRole.ASSISTANT,
            tool_calls=(
                LLMToolCall(
                    call_id="commit",
                    name="commit_reconstruction",
                    arguments={
                        "node_id": "PROTO",
                        "rules": [{**rule, "confidence": 0.9}],
                        "anomalies": [],
                        "summary": "Restore parent initial p.",
                    },
                ),
            ),
        )


def test_failed_tool_calls_are_counted_and_broken_down_by_type() -> None:
    provider = MalformedThenValidProvider()
    result = AgentOrchestrator(provider, instructions="Commit.").run(_context())
    metrics = result.trajectory.metrics
    assert metrics.tool_call_count == 5
    assert metrics.failed_tool_call_count == 2
    # The breakdown names the structural defect, not the exception class: the
    # old key for these same two calls was the uninformative "ValidationError".
    assert metrics.tool_failures_by_type == {
        "schema:rules[].confidence=missing": 2
    }
    assert metrics.protocol_failure_count == 2
    assert metrics.protocol_failure_rate == pytest.approx(0.4)


def test_a_high_protocol_failure_rate_disqualifies_a_completed_trajectory(
    tmp_path,
) -> None:
    from cognate_reconstruction.agent.reconstructor import AgenticNodeReconstructor
    from cognate_reconstruction.agent.service import ReconstructionService
    from cognate_reconstruction.agent.trajectory import JsonlTrajectorySink
    from cognate_reconstruction.ingestion import ingest_payload
    from cognate_reconstruction.schemas.ingestion import WorkbenchPayload

    trajectory_path = tmp_path / "trajectories.jsonl"
    dataset = ingest_payload(
        WorkbenchPayload(
            lexicons=(_lexicon("A", "p"), _lexicon("B", "f")),
            newick="(A,B)PROTO;",
        )
    )
    ReconstructionService(
        AgenticNodeReconstructor(
            AgentOrchestrator(
                MalformedThenValidProvider(),
                instructions="Commit.",
                trajectory_sink=JsonlTrajectorySink(trajectory_path),
            )
        )
    ).reconstruct_family(dataset)
    trajectory = TrajectoryDatasetBuilder.read_jsonl(trajectory_path)[0]
    # The reconstruction itself is fine; the session is not exportable.
    assert trajectory.completed
    assert trajectory.reconstruction_step is not None
    assert trajectory.metrics.protocol_failure_rate > MAX_PROTOCOL_FAILURE_RATE
    assert not trajectory.high_quality
    assert TrajectoryDatasetBuilder().build((trajectory,), high_quality_only=True) == ()

    summary = cli._trajectory_summary((trajectory,))
    assert summary["total_failed_tool_calls"] == 2
    assert summary["total_protocol_failures"] == 2
    assert summary["total_exploratory_failures"] == 0
    assert summary["tool_failures_by_type"] == {
        "schema:rules[].confidence=missing": 2
    }
    assert summary["trajectories_above_protocol_failure_rate"] == 1
    assert summary["high_quality"] == 0


def test_one_recoverable_misstep_still_passes_the_protocol_gate() -> None:
    from cognate_reconstruction.agent.trajectory import AgentNodeMetrics

    provider = MalformedThenValidProvider()
    trajectory = AgentOrchestrator(
        provider, instructions="Commit."
    ).run(_context()).trajectory
    # Same session with a single rejection out of five calls: 0.2 <= 0.25.
    metrics = trajectory.metrics.model_copy(
        update={
            "failed_tool_call_count": 1,
            "protocol_failure_count": 1,
            "tool_failures_by_type": {"schema:rules[].confidence=missing": 1},
        }
    )
    assert isinstance(metrics, AgentNodeMetrics)
    assert metrics.protocol_failure_rate <= MAX_PROTOCOL_FAILURE_RATE


class AlwaysMalformedCommitProvider:
    model = "scripted/always-malformed"

    def __init__(self) -> None:
        self.turn = 0

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[LLMToolDefinition],
        *,
        tool_choice: str = "auto",
        max_tokens_override: int | None = None,
    ) -> LLMMessage:
        assert tools
        self.turn += 1
        return LLMMessage(
            role=MessageRole.ASSISTANT,
            tool_calls=(
                LLMToolCall(
                    call_id=f"bad-commit-{self.turn}",
                    name="commit_reconstruction",
                    arguments={
                        "node_id": "PROTO",
                        "rules": [{"source": "f > p / #_"}],
                        "anomalies": [],
                        "summary": "Restore parent initial p.",
                    },
                ),
            ),
        )


def test_a_repeated_identical_rejection_is_corrected_once_then_fails_fast() -> None:
    provider = AlwaysMalformedCommitProvider()
    sink = _CollectingSink()
    orchestrator = AgentOrchestrator(
        provider,
        instructions="Commit.",
        max_turns=32,
        max_repeated_tool_failures=3,
        event_sink=sink,
    )
    with pytest.raises(ProtocolStallError, match="not adapting to the tool contract"):
        orchestrator.run(_context())
    # Three failures, one correction quoting the error, one verbatim repeat.
    assert provider.turn == 4
    corrections = [
        event
        for event in sink.events
        if event.kind is AgentEventKind.PROTOCOL_CORRECTION
    ]
    assert len(corrections) == 1
    assert corrections[0].details["tool_name"] == "commit_reconstruction"


class AlternatingMalformedCommitProvider:
    """Two malformed commits in rotation, so neither error is ever consecutive."""

    model = "scripted/alternating-malformed"

    def __init__(self) -> None:
        self.turn = 0

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[LLMToolDefinition],
        *,
        tool_choice: str = "auto",
        max_tokens_override: int | None = None,
    ) -> LLMMessage:
        assert tools
        self.turn += 1
        variant = (
            {"source": "f > p / #_"}
            if self.turn % 2
            else {"dsl": "f > p / #_", "source_child_ids": ["B"]}
        )
        return LLMMessage(
            role=MessageRole.ASSISTANT,
            tool_calls=(
                LLMToolCall(
                    call_id=f"bad-commit-{self.turn}",
                    name="commit_reconstruction",
                    arguments={
                        "node_id": "PROTO",
                        "rules": [variant],
                        "anomalies": [],
                        "summary": "Restore parent initial p.",
                    },
                ),
            ),
        )


def test_alternating_rejections_are_caught_too() -> None:
    """A live gemma session looped A, B, A, B; consecutive counting misses it."""
    provider = AlternatingMalformedCommitProvider()
    orchestrator = AgentOrchestrator(
        provider,
        instructions="Commit.",
        max_turns=32,
        max_repeated_tool_failures=3,
    )
    with pytest.raises(ProtocolStallError):
        orchestrator.run(_context())
    # Signature A on turns 1/3/5 trips the correction; A again on 7 stalls.
    assert provider.turn == 7


def test_the_correction_message_carries_the_tool_remediation() -> None:
    provider = AlwaysMalformedCommitProvider()
    captured: list[LLMMessage] = []

    class _Recording(AgentOrchestrator):
        def _record_tool_failure(self, context, state, call, result):
            correction, stall = super()._record_tool_failure(
                context, state, call, result
            )
            if correction is not None:
                captured.append(
                    LLMMessage(role=MessageRole.USER, content=correction)
                )
            return correction, stall

    with pytest.raises(ProtocolStallError):
        _Recording(
            provider, instructions="Commit.", max_repeated_tool_failures=2
        ).run(_context())
    assert len(captured) == 1
    content = captured[0].content or ""
    assert "rejected for the same reason" in content
    assert "No test_sound_law validation has succeeded" in content


class VaryingMessageCommitProvider:
    """One structural mistake, dressed differently on every turn.

    Every call omits the per-rule ``confidence``. Nothing else is stable: the
    DSL text changes, and so does the number of rules, so the Pydantic message —
    which embeds the offending input — never repeats and the list indices in the
    error locations keep moving. This is the shape of failure that escaped
    message-keyed stall detection entirely.
    """

    model = "scripted/varying-message"

    def __init__(self) -> None:
        self.turn = 0

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[LLMToolDefinition],
        *,
        tool_choice: str = "auto",
        max_tokens_override: int | None = None,
    ) -> LLMMessage:
        assert tools
        self.turn += 1
        rules = [
            {"dsl": f"f{self.turn}{index} > p / #_", "source_child_ids": ["B"]}
            for index in range(1 + self.turn % 3)
        ]
        return LLMMessage(
            role=MessageRole.ASSISTANT,
            tool_calls=(
                LLMToolCall(
                    call_id=f"bad-commit-{self.turn}",
                    name="commit_reconstruction",
                    arguments={
                        "node_id": "PROTO",
                        "rules": rules,
                        "anomalies": [],
                        "summary": f"Attempt {self.turn}.",
                    },
                ),
            ),
        )


def test_a_stall_is_detected_even_when_the_error_text_keeps_changing() -> None:
    """The regression this whole taxonomy exists for.

    Under the old message-keyed signature this session ran to the turn limit:
    no two rejections were textually identical, so no signature ever reached the
    threshold. Structurally there is one mistake, repeated.
    """
    provider = VaryingMessageCommitProvider()
    seen: list[tuple[str, str]] = []

    class _Recording(AgentOrchestrator):
        def _record_tool_failure(self, context, state, call, result):
            seen.append((result.error.code, result.error.message))
            return super()._record_tool_failure(context, state, call, result)

    with pytest.raises(ProtocolStallError, match="not adapting to the tool contract"):
        _Recording(
            provider,
            instructions="Commit.",
            max_turns=32,
            max_repeated_tool_failures=3,
        ).run(_context())

    assert provider.turn == 4
    codes = {code for code, _ in seen}
    messages = {message for _, message in seen}
    # One code across four rejections whose texts are all different: the
    # collapse is doing the work, not verbatim repetition.
    assert codes == {"schema:rules[].confidence=missing"}
    assert len(messages) == len(seen)


class SpacedFailureProvider:
    """Fails, works productively for a while, fails again, then commits.

    A session that recovers fully between mistakes is not going in circles, and
    a counter with no decay cannot tell the difference.
    """

    model = "scripted/spaced-failures"

    def __init__(self) -> None:
        self.turn = 0
        self.failures = 0

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[LLMToolDefinition],
        *,
        tool_choice: str = "auto",
        max_tokens_override: int | None = None,
    ) -> LLMMessage:
        assert tools
        self.turn += 1
        script = {
            1: ("unvalidated-commit", None),
            2: ("inspect", None),
            3: ("inspect", None),
            4: ("unvalidated-commit", None),
            5: ("inspect", None),
            6: ("inspect", None),
            7: ("unvalidated-commit", None),
            8: ("validate", None),
        }
        kind = script.get(self.turn, ("commit", None))[0]
        if kind == "inspect":
            call = LLMToolCall(
                call_id=f"inspect-{self.turn}",
                name="list_concepts",
                arguments={},
            )
        elif kind == "validate":
            call = LLMToolCall(
                call_id="validate",
                name="test_sound_law",
                arguments={"dsl": "f > p / #_", "source_child_ids": ["B"]},
            )
        elif kind == "unvalidated-commit":
            self.failures += 1
            call = LLMToolCall(
                call_id=f"early-commit-{self.turn}",
                name="commit_reconstruction",
                arguments={
                    "node_id": "PROTO",
                    "rules": [
                        {
                            "dsl": "f > p / #_",
                            "source_child_ids": ["B"],
                            "confidence": 0.9,
                        }
                    ],
                    "anomalies": [],
                    "summary": "Restore parent initial p.",
                },
            )
        else:
            call = LLMToolCall(
                call_id="commit",
                name="commit_reconstruction",
                arguments={
                    "node_id": "PROTO",
                    "rules": [
                        {
                            "dsl": "f > p / #_",
                            "source_child_ids": ["B"],
                            "confidence": 0.9,
                        }
                    ],
                    "anomalies": [],
                    "summary": "Restore parent initial p.",
                },
            )
        return LLMMessage(role=MessageRole.ASSISTANT, tool_calls=(call,))


def test_the_stall_window_forgives_widely_spaced_repeats() -> None:
    provider = SpacedFailureProvider()
    sink = _CollectingSink()
    result = AgentOrchestrator(
        provider,
        instructions="Commit.",
        max_turns=32,
        max_repeated_tool_failures=2,
        stall_window_calls=3,
        event_sink=sink,
    ).run(_context())
    assert provider.failures == 3
    assert not [
        event
        for event in sink.events
        if event.kind is AgentEventKind.PROTOCOL_CORRECTION
    ]
    metrics = result.trajectory.metrics
    assert metrics.failed_tool_call_count == 3
    assert metrics.tool_failures_by_type == {"validation-unresolved": 3}


def test_the_same_spacing_inside_one_window_still_stalls() -> None:
    """Distance is forgiven; density is not. Only the window differs here."""
    with pytest.raises(ProtocolStallError):
        AgentOrchestrator(
            SpacedFailureProvider(),
            instructions="Commit.",
            max_turns=32,
            max_repeated_tool_failures=2,
            stall_window_calls=9,
        ).run(_context())


class CyclingMalformedProvider:
    """Never repeats a mistake, and never gets anywhere either.

    Every turn is a differently-shaped rejection, so no single signature ever
    reaches `max_repeated_tool_failures`. One of them is exploratory — a
    malformed sound law — which must not count toward the window rule.
    """

    model = "scripted/cycling-malformed"

    RULE = {"dsl": "f > p / #_", "source_child_ids": ["B"], "confidence": 0.9}
    SHAPES: tuple[tuple[str, dict], ...] = (
        # missing confidence
        ("commit_reconstruction", {"rules": [{"dsl": "f > p / #_", "source_child_ids": ["B"]}]}),
        # missing dsl
        ("commit_reconstruction", {"rules": [{"source_child_ids": ["B"], "confidence": 0.5}]}),
        # unknown evidence node
        ("get_alignments", {"node_ids": ["A", "nowhere"], "concept_ids": ["water"]}),
        # unknown validation reference
        ("commit_reconstruction", {"rules": [{**RULE, "validation_call_id": "nope"}]}),
        # exploratory: a sound law that does not parse
        ("test_sound_law", {"dsl": "f >> p", "source_child_ids": ["B"]}),
        # unknown form in a segmentation request
        ("segment_morphemes", {"segmentations": [{"form_id": "ghost", "segments": ["p"]}], "rationale": "x"}),
        # commit for the wrong node
        ("commit_reconstruction", {"node_id": "ELSEWHERE", "rules": []}),
        # anomaly citing a concept that does not exist
        (
            "commit_reconstruction",
            {
                "rules": [],
                "anomalies": [
                    {
                        "anomaly_type": "unknown_irregularity",
                        "explanation": "unexplained",
                        "concept_id": "ghost",
                    }
                ],
            },
        ),
        # unknown segmentation overlay
        ("commit_reconstruction", {"rules": [], "segmentation_overlay_id": "seg-nope"}),
    )

    def __init__(self) -> None:
        self.turn = 0

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[LLMToolDefinition],
        *,
        tool_choice: str = "auto",
        max_tokens_override: int | None = None,
    ) -> LLMMessage:
        assert tools
        name, arguments = self.SHAPES[self.turn % len(self.SHAPES)]
        self.turn += 1
        if name == "commit_reconstruction":
            arguments = {
                "node_id": "PROTO",
                "anomalies": [],
                "summary": "Restore parent initial p.",
                **arguments,
            }
        return LLMMessage(
            role=MessageRole.ASSISTANT,
            tool_calls=(
                LLMToolCall(
                    call_id=f"call-{self.turn}",
                    name=name,
                    arguments=arguments,
                ),
            ),
        )


def test_a_model_cycling_through_distinct_malformed_calls_is_stopped(
    tmp_path,
) -> None:
    """The per-signature rule cannot see this; window saturation can.

    Nothing repeats, so the session used to spend its entire turn budget and
    end in `AgentLoopLimitError` with no statement of what went wrong.
    """
    from cognate_reconstruction.agent.trajectory import JsonlTrajectorySink

    provider = CyclingMalformedProvider()
    sink = _CollectingSink()
    trajectory_path = tmp_path / "cycling.jsonl"
    with pytest.raises(ProtocolStallError, match="cycling through malformed calls"):
        AgentOrchestrator(
            provider,
            instructions="Commit.",
            max_turns=32,
            max_repeated_tool_failures=3,
            event_sink=sink,
            trajectory_sink=JsonlTrajectorySink(trajectory_path),
        ).run(_context())

    # Six protocol failures fill the window and draw one correction; the
    # seventh ends the node. The exploratory rejection occupies a slot without
    # counting, which is why it takes eight calls rather than seven.
    assert provider.turn == 8
    metrics = TrajectoryDatasetBuilder.read_jsonl(trajectory_path)[0].metrics
    assert metrics.failed_tool_call_count == 8
    assert metrics.protocol_failure_count == 7
    assert set(metrics.tool_failures_by_type) == {
        "schema:rules[].confidence=missing",
        "schema:rules[].dsl=missing",
        "unknown-node",
        "validation-unknown",
        "dsl-parse-error",
        "unknown-form",
        "node-mismatch",
        "anomaly-unknown-reference",
    }
    corrections = [
        event
        for event in sink.events
        if event.kind is AgentEventKind.PROTOCOL_CORRECTION
    ]
    assert len(corrections) == 1
    assert corrections[0].details["reason"] == "window_saturated"


def test_exploratory_rejections_never_saturate_the_window() -> None:
    """Getting sound laws wrong is using the tools, not failing to use them."""
    provider = ExploratoryFailuresProvider()
    # The signature rule is put out of reach so only the window rule is under
    # test, and the window rule is set as strict as it can be: one failure.
    result = AgentOrchestrator(
        provider,
        instructions="Commit.",
        max_repeated_tool_failures=5,
        stall_window_calls=5,
        max_window_protocol_failures=1,
    ).run(_context())
    assert result.trajectory.metrics.failed_tool_call_count == 2
    assert result.trajectory.metrics.protocol_failure_count == 0


def test_the_window_saturation_threshold_is_validated() -> None:
    with pytest.raises(ValueError, match="max_window_protocol_failures"):
        AgentOrchestrator(
            AlwaysMalformedCommitProvider(),
            instructions="x",
            stall_window_calls=4,
            max_window_protocol_failures=5,
        )


def test_the_stall_window_is_part_of_the_configuration_hash() -> None:
    base = AgentOrchestrator(AlwaysMalformedCommitProvider(), instructions="x")
    widened = AgentOrchestrator(
        AlwaysMalformedCommitProvider(), instructions="x", stall_window_calls=40
    )
    assert base.stall_window_calls == 9
    assert base.configuration_sha256 != widened.configuration_sha256


def test_a_window_narrower_than_the_threshold_is_rejected() -> None:
    with pytest.raises(ValueError, match="stall_window_calls"):
        AgentOrchestrator(
            AlwaysMalformedCommitProvider(),
            instructions="x",
            max_repeated_tool_failures=3,
            stall_window_calls=2,
        )


class TruncatedProvider:
    model = "scripted/truncated"

    def __init__(self) -> None:
        self.turn = 0
        self.saw_truncation_notice = False

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[LLMToolDefinition],
        *,
        tool_choice: str = "auto",
        max_tokens_override: int | None = None,
    ) -> ProviderResponse:
        assert tools
        self.turn += 1
        if messages[-1].role is MessageRole.USER and "cut off" in (
            messages[-1].content or ""
        ):
            self.saw_truncation_notice = True
        return ProviderResponse(
            message=LLMMessage(
                role=MessageRole.ASSISTANT,
                content="Let me think about the correspondences at length",
            ),
            metadata=ProviderResponseMetadata(finish_reason="length"),
        )


def test_truncated_responses_get_a_specific_nudge_then_stop_the_node() -> None:
    provider = TruncatedProvider()
    sink = _CollectingSink()
    orchestrator = AgentOrchestrator(
        provider,
        instructions="Commit.",
        max_turns=32,
        max_truncated_responses=3,
        event_sink=sink,
    )
    with pytest.raises(ProtocolStallError, match="truncated 3 times"):
        orchestrator.run(_context())
    assert provider.turn == 3
    assert provider.saw_truncation_notice
    truncations = [
        event
        for event in sink.events
        if event.kind is AgentEventKind.RESPONSE_TRUNCATED
    ]
    assert len(truncations) == 3
    assert truncations[0].details["had_tool_calls"] is False


def test_unproductive_turn_thresholds_are_part_of_the_configuration_hash() -> None:
    base = AgentOrchestrator(AlwaysMalformedCommitProvider(), instructions="x")
    changed = AgentOrchestrator(
        AlwaysMalformedCommitProvider(),
        instructions="x",
        max_repeated_tool_failures=5,
    )
    truncation = AgentOrchestrator(
        AlwaysMalformedCommitProvider(),
        instructions="x",
        max_truncated_responses=9,
    )
    assert base.configuration_sha256 != changed.configuration_sha256
    assert base.configuration_sha256 != truncation.configuration_sha256


def _run_to_completion(provider, trajectory_path: Path) -> AgentTrajectory:
    """Drive one two-leaf family end to end and return its written trajectory."""
    from cognate_reconstruction.agent.reconstructor import AgenticNodeReconstructor
    from cognate_reconstruction.agent.service import ReconstructionService
    from cognate_reconstruction.agent.trajectory import JsonlTrajectorySink
    from cognate_reconstruction.ingestion import ingest_payload
    from cognate_reconstruction.schemas.ingestion import WorkbenchPayload

    dataset = ingest_payload(
        WorkbenchPayload(
            lexicons=(_lexicon("A", "p"), _lexicon("B", "f")),
            newick="(A,B)PROTO;",
        )
    )
    ReconstructionService(
        AgenticNodeReconstructor(
            AgentOrchestrator(
                provider,
                instructions="Commit.",
                trajectory_sink=JsonlTrajectorySink(trajectory_path),
            )
        )
    ).reconstruct_family(dataset)
    return TrajectoryDatasetBuilder.read_jsonl(trajectory_path)[0]


class ExploratoryFailuresProvider:
    """Proposes two bad sound laws, reads the refusals, then commits a good one.

    Both rejections come from the hypothesis tester: a DSL that does not parse
    and a rule that changes nothing. This is the loop working, and it has the
    same rejected-call count as `MalformedThenValidProvider`, whose two
    rejections are pure commit-schema friction.
    """

    model = "scripted/exploratory-failures"

    def __init__(self) -> None:
        self.turn = 0

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[LLMToolDefinition],
        *,
        tool_choice: str = "auto",
        max_tokens_override: int | None = None,
    ) -> LLMMessage:
        assert tools
        self.turn += 1
        attempts = {2: "f >> p", 3: "p > p", 4: "f > p / #_"}
        if self.turn == 1:
            call = LLMToolCall(
                call_id="inspect", name="list_concepts", arguments={}
            )
        elif self.turn in attempts:
            call = LLMToolCall(
                call_id=f"test-{self.turn}",
                name="test_sound_law",
                arguments={
                    "dsl": attempts[self.turn],
                    "source_child_ids": ["B"],
                },
            )
        else:
            call = LLMToolCall(
                call_id="commit",
                name="commit_reconstruction",
                arguments={
                    "node_id": "PROTO",
                    "rules": [
                        {
                            "dsl": "f > p / #_",
                            "source_child_ids": ["B"],
                            "confidence": 0.9,
                        }
                    ],
                    "anomalies": [],
                    "summary": "Restore parent initial p.",
                },
            )
        return LLMMessage(role=MessageRole.ASSISTANT, tool_calls=(call,))


def test_exploratory_rejections_do_not_cost_a_session_its_quality_flag(
    tmp_path,
) -> None:
    exploratory = _run_to_completion(
        ExploratoryFailuresProvider(), tmp_path / "exploratory.jsonl"
    )
    protocol = _run_to_completion(
        MalformedThenValidProvider(), tmp_path / "protocol.jsonl"
    )

    # Identical mechanical shape: five calls, two of them rejected.
    for trajectory in (exploratory, protocol):
        assert trajectory.metrics.tool_call_count == 5
        assert trajectory.metrics.failed_tool_call_count == 2

    assert exploratory.metrics.protocol_failure_count == 0
    assert exploratory.metrics.tool_failures_by_type == {
        "dsl-parse-error": 1,
        "no-op-rule": 1,
    }
    assert exploratory.metrics.protocol_failure_rate == 0.0
    assert exploratory.high_quality

    assert protocol.metrics.protocol_failure_count == 2
    assert protocol.metrics.protocol_failure_rate == pytest.approx(0.4)
    assert not protocol.high_quality

    summary = cli._trajectory_summary((exploratory,))
    assert summary["total_failed_tool_calls"] == 2
    assert summary["total_protocol_failures"] == 0
    assert summary["total_exploratory_failures"] == 2
    assert summary["high_quality"] == 1


class OneProtocolSlipProvider:
    """Inspects, commits once without a validation, then commits identity."""

    model = "scripted/one-slip"

    def __init__(self) -> None:
        self.turn = 0

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[LLMToolDefinition],
        *,
        tool_choice: str = "auto",
        max_tokens_override: int | None = None,
    ) -> LLMMessage:
        assert tools
        self.turn += 1
        if self.turn == 1:
            call = LLMToolCall(
                call_id="inspect", name="list_concepts", arguments={}
            )
        elif self.turn == 2:
            call = LLMToolCall(
                call_id="early-commit",
                name="commit_reconstruction",
                arguments={
                    "node_id": "PROTO",
                    "rules": [
                        {
                            "dsl": "f > p / #_",
                            "source_child_ids": ["B"],
                            "confidence": 0.9,
                        }
                    ],
                    "anomalies": [],
                    "summary": "Restore parent initial p.",
                },
            )
        else:
            call = LLMToolCall(
                call_id="commit",
                name="commit_reconstruction",
                arguments={
                    "node_id": "PROTO",
                    "rules": [],
                    "anomalies": [],
                    "summary": "No regular correspondence is recoverable here.",
                },
            )
        return LLMMessage(role=MessageRole.ASSISTANT, tool_calls=(call,))


def test_a_single_protocol_slip_in_a_short_session_still_passes(tmp_path) -> None:
    """The rate exists so the gate does not tighten as sessions get longer.

    Without a floor it tightens as they get shorter: one slip in a three-call
    identity commit is 0.33, and the session is disqualified for a single
    misstep it recovered from immediately.
    """
    trajectory = _run_to_completion(
        OneProtocolSlipProvider(), tmp_path / "one-slip.jsonl"
    )
    metrics = trajectory.metrics
    assert metrics.tool_call_count == 3
    assert metrics.protocol_failure_count == 1
    assert metrics.tool_failures_by_type == {"validation-unresolved": 1}
    assert metrics.protocol_failure_rate > MAX_PROTOCOL_FAILURE_RATE
    assert trajectory.high_quality


def test_the_floor_does_not_forgive_a_second_protocol_failure(tmp_path) -> None:
    trajectory = _run_to_completion(
        OneProtocolSlipProvider(), tmp_path / "floor.jsonl"
    )
    worse = trajectory.model_copy(
        update={
            "metrics": trajectory.metrics.model_copy(
                update={
                    "failed_tool_call_count": 2,
                    "protocol_failure_count": 2,
                }
            )
        }
    )
    assert not worse.high_quality


class _RefusingAligner:
    """Stands in for a LingPy refusal without depending on how to provoke one."""

    def align_multiple(self, lexicons, anchors, *, respect_cognate_sets=True):
        raise ValueError("alignment requires at least two distinct lexicons")


def test_an_alignment_refusal_is_coded_rather_than_left_unclassified() -> None:
    from cognate_reconstruction.agent.tools import default_tool_registry

    context = AgentContext(
        node_id="PROTO",
        child_lexicons=(_lexicon("A", "p"), _lexicon("B", "f")),
        aligner=_RefusingAligner(),
    )
    registry = default_tool_registry()
    result = registry.execute(
        LLMToolCall(
            call_id="align",
            name="get_alignments",
            arguments={"node_ids": ["A", "B"], "concept_ids": ["water"]},
        ),
        context,
    )
    assert not result.ok
    assert result.error.code == "alignment-failed"
    assert "two distinct lexicons" in result.error.message

    # The wrap is narrow: a bad node ID is still a node problem, not an
    # alignment one, so the two do not collapse into one signature.
    unknown = registry.execute(
        LLMToolCall(
            call_id="align-2",
            name="get_alignments",
            arguments={"node_ids": ["A", "nowhere"], "concept_ids": ["water"]},
        ),
        context,
    )
    assert unknown.error.code == "unknown-node"


def test_the_cascade_schema_states_that_it_takes_no_validation_id() -> None:
    """A live gemma run put a per-rule validation_call_id in a cascade spec."""
    from cognate_reconstruction.agent.tools import default_tool_registry

    definitions = {
        definition.name: definition
        for definition in default_tool_registry().definitions()
    }
    cascade = definitions["test_rule_cascade"]
    rendered = json.dumps(cascade.parameters)
    assert "carries no validation ID" in rendered
    assert "no validation_call_id" in cascade.description


def test_the_failure_breakdown_reads_under_an_honest_name() -> None:
    trajectory = AgentOrchestrator(
        MalformedThenValidProvider(), instructions="Commit."
    ).run(_context()).trajectory
    metrics = trajectory.metrics
    assert metrics.tool_failures_by_code == metrics.tool_failures_by_type
    assert metrics.tool_failures_by_code
    # The honest name is a read-only view; the persisted field is unchanged, so
    # records written before the rename stay loadable.
    assert "tool_failures_by_code" not in trajectory.model_dump_json(
        exclude_computed_fields=True
    )


def test_the_tool_result_event_carries_the_structural_code() -> None:
    sink = _CollectingSink()
    AgentOrchestrator(
        MalformedThenValidProvider(), instructions="Commit.", event_sink=sink
    ).run(_context())
    codes = [
        event.details["error_code"]
        for event in sink.events
        if event.kind is AgentEventKind.TOOL_RESULT
    ]
    assert codes.count("schema:rules[].confidence=missing") == 2
    assert codes.count(None) == 3


def test_rule_coverage_ignores_children_that_never_showed_the_target() -> None:
    """A correct rule scoped to a whole polytomy is not punished for scoping."""
    children = tuple(
        make_leaf_beam(item, beam_width=2)
        for item in (
            _lexicon("A", "p"),
            _lexicon("B", "f"),
            _lexicon("C", "p"),
        )
    )
    rule = ReconstructionRule(
        rule=parse_rule("f > p / #_", rule_id="restore-p"),
        source_child_ids=("A", "B", "C"),
        confidence=0.9,
    )
    broad = RuleBasedReconstructor(beam_width=2).reconstruct(
        "PROTO", children, rules=(rule,)
    )
    narrow = RuleBasedReconstructor(beam_width=2).reconstruct(
        "PROTO",
        children,
        rules=(rule.model_copy(update={"source_child_ids": ("B",)}),),
    )
    assert broad.diagnostics.rule_coverage == 1.0
    assert broad.diagnostics.rule_coverage == narrow.diagnostics.rule_coverage
    # The vacuous children stay visible as raw counts rather than as failures.
    assert broad.diagnostics.target_absent == 2
    assert broad.diagnostics.rule_results_evaluated == 3
    assert broad.diagnostics.applicable_rule_results == 1
    assert (
        broad.output_beam.distributions[0].candidates[0].segments
        == narrow.output_beam.distributions[0].candidates[0].segments
    )


def test_a_rule_that_misses_its_environment_still_loses_coverage() -> None:
    children = tuple(
        make_leaf_beam(item, beam_width=2)
        for item in (_lexicon("A", "f"), _lexicon("B", "f"))
    )
    # 'f' occurs in both, but never word-finally, so both are real misses.
    rule = ReconstructionRule(
        rule=parse_rule("f > p / _#", rule_id="wrong-environment"),
        source_child_ids=("A", "B"),
        confidence=0.9,
    )
    step = RuleBasedReconstructor(beam_width=2).reconstruct(
        "PROTO", children, rules=(rule,)
    )
    assert step.diagnostics.target_absent == 0
    assert step.diagnostics.context_mismatches == 2
    assert step.diagnostics.applicable_rule_results == 2
    assert step.diagnostics.rule_coverage == 0.0


def _pre_split_high_quality(trajectory: AgentTrajectory) -> bool:
    """The `high_quality` gate exactly as it read before the protocol split.

    Transcribed rather than imported on purpose: this is the claim about the old
    behaviour that backward compatibility is measured against, so it must not
    move when the real gate does.
    """
    metrics = trajectory.metrics
    rate = (
        metrics.failed_tool_call_count / metrics.tool_call_count
        if metrics.tool_call_count
        else 0.0
    )
    return (
        trajectory.completed
        and trajectory.reconstruction_step is not None
        and not trajectory.committed_no_op_rule_count
        and not metrics.committed_without_inspection
        and rate <= MAX_PROTOCOL_FAILURE_RATE
        and not (
            metrics.committed_rule_count > 0
            and metrics.sound_law_tests < metrics.committed_rule_count
        )
        and not (metrics.committed_rule_count > 1 and metrics.cascade_tests == 0)
    )


def _pre_change_trajectory_line() -> str:
    """A 2.0 record as written before failure counters and coverage denominators."""
    payload = json.loads(
        (
            Path(__file__).parent / "fixtures" / "trajectory_pre_failure_metrics.json"
        ).read_text(encoding="utf-8")
    )
    return json.dumps(payload)


def test_trajectories_written_before_these_counters_still_load(tmp_path) -> None:
    line = _pre_change_trajectory_line()
    assert "failed_tool_call_count" not in line
    assert "applicable_rule_results" not in line
    path = tmp_path / "old.jsonl"
    path.write_text(line + "\n", encoding="utf-8")

    loaded = TrajectoryDatasetBuilder.read_jsonl(path)
    assert len(loaded) == 1
    trajectory = loaded[0]
    assert trajectory.metrics.failed_tool_call_count == 0
    assert trajectory.metrics.tool_failures_by_type == {}
    assert trajectory.metrics.truncated_response_count == 0
    # Truncation recovery did not exist when this was written; an absent
    # counter reads as "the harness never intervened", which is true.
    assert trajectory.metrics.forced_tool_choice_count == 0
    assert trajectory.metrics.truncation_backoff_applied == 0
    # The protocol counter is absent, not zero, and falls back to the total.
    assert trajectory.metrics.protocol_failure_count is None
    assert (
        trajectory.metrics.protocol_failures
        == trajectory.metrics.failed_tool_call_count
    )
    assert trajectory.metrics.protocol_failure_rate == 0.0
    assert trajectory.reconstruction_step is not None
    assert trajectory.reconstruction_step.diagnostics.applicable_rule_results == 0
    # Append-only auditability: a clean older record keeps the verdict it had.
    assert trajectory.high_quality
    assert cli._trajectory_summary(loaded)["total_failed_tool_calls"] == 0


@pytest.mark.parametrize(
    "path",
    sorted((REPO_ROOT / "runs").glob("*/trajectories.jsonl"))
    if (REPO_ROOT / "runs").is_dir()
    else [],
)
def test_local_run_artifacts_load_and_keep_their_verdicts(path: Path) -> None:
    """`runs/` is gitignored local evidence; validate it when it is present.

    Append-only auditability means more than "still parses": a record written
    before the exploratory/protocol split must also come back with the exact
    `high_quality` verdict it had, computed here from the pre-split gate.
    """
    loaded = TrajectoryDatasetBuilder.read_jsonl(path)
    assert loaded
    assert all(isinstance(item, AgentTrajectory) for item in loaded)
    for trajectory in loaded:
        metrics = trajectory.metrics
        if metrics.protocol_failure_count is not None:
            continue
        assert metrics.protocol_failures == metrics.failed_tool_call_count
        assert trajectory.high_quality == _pre_split_high_quality(trajectory)
