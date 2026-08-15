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
    assert metrics.tool_failures_by_type == {"ValidationError": 2}
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
    assert summary["tool_failures_by_type"] == {"ValidationError": 2}
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
            "tool_failures_by_type": {"ValidationError": 1},
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
    assert "rejected with exactly the same error" in content
    assert "No test_sound_law validation has succeeded" in content


class TruncatedProvider:
    model = "scripted/truncated"

    def __init__(self) -> None:
        self.turn = 0
        self.saw_truncation_notice = False

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[LLMToolDefinition],
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
def test_local_run_artifacts_remain_loadable(path: Path) -> None:
    """`runs/` is gitignored local evidence; validate it when it is present."""
    loaded = TrajectoryDatasetBuilder.read_jsonl(path)
    assert loaded
    assert all(isinstance(item, AgentTrajectory) for item in loaded)
