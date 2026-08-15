"""Versioned trajectory artifacts and backend-neutral training preparation."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from pydantic import Field, model_validator

from cognate_reconstruction.agent.schemas import (
    CommittedReconstruction,
    LLMMessage,
    LLMToolDefinition,
    NodePromptPayload,
    ProviderResponseMetadata,
)
from cognate_reconstruction.schemas.common import NonEmptyStr, WorkbenchModel
from cognate_reconstruction.schemas.traversal import ReconstructionStep

TRAJECTORY_SCHEMA_VERSION = "2.0"

MAX_PROTOCOL_FAILURE_RATE = 0.25
"""Share of a node's tool calls that may be rejected before `high_quality` drops.

This is a workflow heuristic, not a linguistic judgement. A session may misstep
once and recover; a session that spends most of its budget being rejected by the
tool schemas is teaching the wrong protocol, whatever its linguistics.
"""


class AgentNodeMetrics(WorkbenchModel):
    started_at: datetime
    finished_at: datetime
    duration_seconds: float = Field(ge=0.0)
    turn_count: int = Field(ge=0)
    provider_attempts: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    tool_call_count: int = Field(ge=0)
    # Defaulted so trajectories written before failure accounting existed stay
    # loadable; absent counters read as "not recorded", which is zero here.
    failed_tool_call_count: int = Field(default=0, ge=0)
    tool_failures_by_type: dict[str, int] = Field(default_factory=dict)
    truncated_response_count: int = Field(default=0, ge=0)
    inspection_tool_calls: int = Field(ge=0)
    sound_law_tests: int = Field(ge=0)
    cascade_tests: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0.0)
    committed_rule_count: int = Field(ge=0)
    committed_anomaly_count: int = Field(ge=0)
    committed_without_inspection: bool
    identity_without_testing: bool

    @property
    def protocol_failure_rate(self) -> float:
        """Rejected share of attempted tool calls, mechanical not linguistic."""
        if self.tool_call_count == 0:
            return 0.0
        return self.failed_tool_call_count / self.tool_call_count


class AgentTrajectory(WorkbenchModel):
    trajectory_id: NonEmptyStr
    schema_version: Literal["2.0"] = TRAJECTORY_SCHEMA_VERSION
    run_id: NonEmptyStr
    configuration_sha256: NonEmptyStr
    node_id: NonEmptyStr
    provider_adapter: NonEmptyStr
    model_id: NonEmptyStr | None = None
    instruction_sha256: NonEmptyStr
    tool_schema_sha256: NonEmptyStr
    payload_schema_sha256: NonEmptyStr
    trajectory_schema_sha256: NonEmptyStr
    initial_payload: NodePromptPayload
    tool_definitions: tuple[LLMToolDefinition, ...]
    messages: tuple[LLMMessage, ...]
    provider_responses: tuple[ProviderResponseMetadata, ...] = ()
    metrics: AgentNodeMetrics
    committed_reconstruction: CommittedReconstruction | None = None
    reconstruction_step: ReconstructionStep | None = None
    completed: bool
    failure: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> AgentTrajectory:
        if self.completed and self.committed_reconstruction is None:
            raise ValueError("completed trajectories require a committed reconstruction")
        if not self.completed and self.failure is None:
            raise ValueError("incomplete trajectories require a failure explanation")
        if not self.completed and self.reconstruction_step is not None:
            raise ValueError("incomplete trajectories cannot contain a reconstruction step")
        return self

    @property
    def high_quality(self) -> bool:
        """Conservative filter for completed, inspected, reproducible sessions."""
        if not self.completed or self.reconstruction_step is None:
            return False
        if self.committed_no_op_rule_count:
            return False
        if self.metrics.committed_without_inspection:
            return False
        if self.metrics.protocol_failure_rate > MAX_PROTOCOL_FAILURE_RATE:
            return False
        if (
            self.metrics.committed_rule_count > 0
            and self.metrics.sound_law_tests < self.metrics.committed_rule_count
        ):
            return False
        if (
            self.metrics.committed_rule_count > 1
            and self.metrics.cascade_tests == 0
        ):
            return False
        return True

    @property
    def committed_no_op_rule_count(self) -> int:
        """Count historical commits whose rules cannot change any token sequence.

        New no-op DSL rules are rejected by the parser. This artifact-level check
        deliberately remains separate so append-only trajectories written before
        that enforcement can still be loaded, audited, and excluded from curated
        exports.
        """
        if self.committed_reconstruction is None:
            return 0
        return sum(
            rule.rule.target.tokens == rule.rule.replacement.tokens
            for rule in self.committed_reconstruction.parsed_rules
        )


class AgentRunResult(WorkbenchModel):
    reconstruction: CommittedReconstruction
    trajectory: AgentTrajectory


class TrajectorySink(Protocol):
    def write(self, trajectory: AgentTrajectory) -> None: ...


class JsonlTrajectorySink:
    """Append immutable trajectory records without retaining a family run in RAM."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def write(self, trajectory: AgentTrajectory) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(
                trajectory.model_dump_json(exclude_computed_fields=True)
            )
            handle.write("\n")


class TrainingExample(WorkbenchModel):
    example_id: NonEmptyStr
    schema_version: Literal["2.0"] = TRAJECTORY_SCHEMA_VERSION
    run_id: NonEmptyStr
    node_id: NonEmptyStr
    messages: tuple[LLMMessage, ...]
    tool_definitions: tuple[LLMToolDefinition, ...]
    reconstruction_step: ReconstructionStep | None = None
    source_trajectory_id: NonEmptyStr


class TrajectoryDatasetBuilder:
    """Create generic chat/tool examples consumable by later TRL/Unsloth adapters."""

    def build(
        self,
        trajectories: Sequence[AgentTrajectory],
        *,
        include_incomplete: bool = False,
        high_quality_only: bool = False,
        max_anomaly_rate: float | None = None,
    ) -> tuple[TrainingExample, ...]:
        if max_anomaly_rate is not None and max_anomaly_rate < 0:
            raise ValueError("max_anomaly_rate must be non-negative")
        return tuple(
            TrainingExample(
                example_id=f"example:{trajectory.trajectory_id}",
                run_id=trajectory.run_id,
                node_id=trajectory.node_id,
                messages=trajectory.messages,
                tool_definitions=trajectory.tool_definitions,
                reconstruction_step=trajectory.reconstruction_step,
                source_trajectory_id=trajectory.trajectory_id,
            )
            for trajectory in trajectories
            if (trajectory.completed or include_incomplete)
            and (not high_quality_only or trajectory.high_quality)
            and (
                max_anomaly_rate is None
                or trajectory.reconstruction_step is None
                or trajectory.reconstruction_step.diagnostics.anomaly_rate
                <= max_anomaly_rate
            )
        )

    @staticmethod
    def read_jsonl(path: str | Path) -> tuple[AgentTrajectory, ...]:
        trajectories = []
        with Path(path).open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    trajectories.append(AgentTrajectory.model_validate_json(line))
                except Exception as error:
                    raise ValueError(
                        f"invalid trajectory JSONL at line {line_number}: {error}"
                    ) from error
        return tuple(trajectories)

    @staticmethod
    def write_jsonl(
        examples: Iterable[TrainingExample],
        path: str | Path,
    ) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8") as handle:
            for example in examples:
                handle.write(json.dumps(example.model_dump(mode="json"), sort_keys=True))
                handle.write("\n")
