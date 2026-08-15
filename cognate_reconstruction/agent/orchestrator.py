"""Bounded, retrying native-tool loop for one reconstruction node."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Callable

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.events import (
    AgentEvent,
    AgentEventKind,
    AgentEventSink,
)
from cognate_reconstruction.agent.instructions import load_agent_instructions
from cognate_reconstruction.agent.providers import ProviderTransientError
from cognate_reconstruction.agent.providers.protocol import LLMProvider
from cognate_reconstruction.agent.schemas import (
    LLMMessage,
    LLMToolCall,
    MessageRole,
    NodeLexiconSummary,
    NodePromptPayload,
    ProviderResponse,
    ProviderResponseMetadata,
    ToolExecutionResult,
)
from cognate_reconstruction.agent.tools import ToolRegistry, default_tool_registry
from cognate_reconstruction.agent.trajectory import (
    AgentNodeMetrics,
    AgentRunResult,
    AgentTrajectory,
    TrajectorySink,
)
from cognate_reconstruction.schemas.traversal import ReconstructionStep


class AgentLoopLimitError(RuntimeError):
    pass


class RunBudgetExceeded(RuntimeError):
    pass


class ProtocolStallError(RuntimeError):
    """The model kept repeating one rejected call after a targeted correction.

    Raised instead of silently spending the remaining turn budget: a named stall
    in a trajectory is more useful than an exhausted loop limit.
    """


@dataclass
class _RunState:
    started_at: datetime
    started_monotonic: float
    turn_count: int = 0
    provider_attempts: int = 0
    retry_count: int = 0
    tool_call_count: int = 0
    failed_tool_call_count: int = 0
    tool_failures_by_type: dict[str, int] = field(default_factory=dict)
    truncated_response_count: int = 0
    tool_names: list[str] = field(default_factory=list)
    successful_tool_names: list[str] = field(default_factory=list)
    provider_responses: list[ProviderResponseMetadata] = field(default_factory=list)
    # How often each (tool, error type, error message) signature was rejected in
    # this node, and which of those have already drawn a targeted correction.
    failure_signature_counts: dict[tuple[str, str, str], int] = field(
        default_factory=dict
    )
    corrected_failure_signatures: set[tuple[str, str, str]] = field(
        default_factory=set
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class AgentOrchestrator:
    def __init__(
        self,
        provider: LLMProvider,
        *,
        registry: ToolRegistry | None = None,
        max_turns: int = 24,
        max_tool_calls: int = 64,
        max_retries: int = 2,
        retry_backoff_seconds: float = 1.0,
        max_total_turns: int | None = None,
        max_total_tool_calls: int | None = None,
        max_run_seconds: float | None = None,
        max_total_cost_usd: float | None = None,
        max_repeated_tool_failures: int = 3,
        max_truncated_responses: int = 3,
        instructions: str | None = None,
        trajectory_sink: TrajectorySink | None = None,
        event_sink: AgentEventSink | None = None,
        run_id: str | None = None,
        configuration_sha256: str | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_turns < 1 or max_tool_calls < 1:
            raise ValueError("agent loop limits must be positive")
        if max_retries < 0 or retry_backoff_seconds < 0:
            raise ValueError("retry controls must be non-negative")
        if max_total_turns is not None and max_total_turns < 1:
            raise ValueError("max_total_turns must be positive")
        if max_total_tool_calls is not None and max_total_tool_calls < 1:
            raise ValueError("max_total_tool_calls must be positive")
        if max_run_seconds is not None and max_run_seconds <= 0:
            raise ValueError("max_run_seconds must be positive")
        if max_total_cost_usd is not None and max_total_cost_usd <= 0:
            raise ValueError("max_total_cost_usd must be positive")
        if max_repeated_tool_failures < 1 or max_truncated_responses < 1:
            raise ValueError("unproductive-turn thresholds must be positive")
        self.provider = provider
        self.registry = registry or default_tool_registry()
        self.max_turns = max_turns
        self.max_tool_calls = max_tool_calls
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.max_total_turns = max_total_turns
        self.max_total_tool_calls = max_total_tool_calls
        self.max_run_seconds = max_run_seconds
        self.max_total_cost_usd = max_total_cost_usd
        self.max_repeated_tool_failures = max_repeated_tool_failures
        self.max_truncated_responses = max_truncated_responses
        self.instructions = instructions or load_agent_instructions()
        self.trajectory_sink = trajectory_sink
        self.event_sink = event_sink
        self.run_id = run_id or f"run-{uuid.uuid4()}"
        self.sleep_fn = sleep_fn
        self._run_started = time.monotonic()
        self._total_turns = 0
        self._total_tool_calls = 0
        self._total_cost_usd = 0.0
        self._trajectory_starts: dict[str, float] = {}
        public_configuration = {
            "provider_adapter": type(provider).__name__,
            "model_id": getattr(provider, "model", None),
            "max_turns": max_turns,
            "max_tool_calls": max_tool_calls,
            "max_retries": max_retries,
            "retry_backoff_seconds": retry_backoff_seconds,
            "max_total_turns": max_total_turns,
            "max_total_tool_calls": max_total_tool_calls,
            "max_run_seconds": max_run_seconds,
            "max_total_cost_usd": max_total_cost_usd,
            "max_repeated_tool_failures": max_repeated_tool_failures,
            "max_truncated_responses": max_truncated_responses,
            "instruction_sha256": hashlib.sha256(
                self.instructions.encode()
            ).hexdigest(),
        }
        self.configuration_sha256 = (
            configuration_sha256 or _sha256_json(public_configuration)
        )

    def _emit(
        self,
        kind: AgentEventKind,
        node_id: str,
        message: str,
        **details: object,
    ) -> None:
        if self.event_sink is not None:
            self.event_sink.emit(
                AgentEvent(
                    kind=kind,
                    node_id=node_id,
                    message=message,
                    details=dict(details),
                    run_id=self.run_id,
                )
            )

    def _check_run_budget(self) -> None:
        if (
            self.max_run_seconds is not None
            and time.monotonic() - self._run_started > self.max_run_seconds
        ):
            raise RunBudgetExceeded("run exceeded its wall-clock time limit")
        if (
            self.max_total_cost_usd is not None
            and self._total_cost_usd > self.max_total_cost_usd
        ):
            raise RunBudgetExceeded("run exceeded its reported provider cost limit")

    def _complete_with_retry(
        self,
        node_id: str,
        messages: list[LLMMessage],
        state: _RunState,
    ) -> ProviderResponse:
        definitions = self.registry.definitions()
        for retry_index in range(self.max_retries + 1):
            self._check_run_budget()
            state.provider_attempts += 1
            try:
                raw_response = self.provider.complete(messages, definitions)
                response = (
                    raw_response
                    if isinstance(raw_response, ProviderResponse)
                    else ProviderResponse(message=raw_response)
                )
                state.provider_responses.append(response.metadata)
                if (
                    response.metadata.usage is not None
                    and response.metadata.usage.cost_usd is not None
                ):
                    self._total_cost_usd += response.metadata.usage.cost_usd
                self._check_run_budget()
                return response
            except ProviderTransientError as error:
                if retry_index >= self.max_retries:
                    raise
                state.retry_count += 1
                delay = self.retry_backoff_seconds * (2**retry_index)
                self._emit(
                    AgentEventKind.PROVIDER_RETRY,
                    node_id,
                    f"transient provider failure; retrying in {delay:g}s",
                    retry_index=retry_index + 1,
                    max_retries=self.max_retries,
                    error_type=type(error.__cause__ or error).__name__,
                    error=str(error),
                )
                self.sleep_fn(delay)
        raise AssertionError("unreachable provider retry loop")

    def _record_tool_failure(
        self,
        context: AgentContext,
        state: _RunState,
        call: LLMToolCall,
        result: ToolExecutionResult,
    ) -> tuple[str | None, str | None]:
        """Count a rejected call and decide whether to intervene.

        Returns ``(correction, stall_reason)``. The loop retries transport
        failures, but a rejection reproduced verbatim N times is not transport:
        it is the model failing to read the contract. Correct it once with the
        tool's own remediation, then fail fast rather than spending the budget.

        Occurrences are counted per signature over the whole node rather than
        only in consecutive runs. A live gemma session alternated between two
        commit errors — A, B, A, B — so neither was ever consecutive and a
        strictly consecutive counter would have watched it loop indefinitely.
        """
        error = result.error
        error_type = error.error_type if error is not None else "unknown"
        message = error.message if error is not None else ""
        state.failed_tool_call_count += 1
        state.tool_failures_by_type[error_type] = (
            state.tool_failures_by_type.get(error_type, 0) + 1
        )
        signature = (call.name, error_type, message)
        occurrences = state.failure_signature_counts.get(signature, 0) + 1
        state.failure_signature_counts[signature] = occurrences
        if occurrences < self.max_repeated_tool_failures:
            return None, None
        if signature in state.corrected_failure_signatures:
            return None, (
                f"tool {call.name} produced the same {error_type} rejection "
                f"again ({occurrences} times in this node) after a targeted "
                "correction quoting it; the model is not adapting to the tool "
                "contract"
            )
        state.corrected_failure_signatures.add(signature)
        remediation = error.remediation if error is not None else None
        correction = (
            f"Stop. {occurrences} {call.name} calls in this session were "
            "rejected with exactly the same error, so repeating the same "
            "arguments cannot succeed:\n"
            f"{message}\n"
            "Change the arguments to satisfy the tool schema before calling it "
            "again."
        )
        if remediation:
            correction += f"\n{remediation}"
        self._emit(
            AgentEventKind.PROTOCOL_CORRECTION,
            context.node_id,
            f"injected a targeted correction after repeated {call.name} failures",
            tool_name=call.name,
            error_type=error_type,
            repeated=self.max_repeated_tool_failures,
        )
        return correction, None

    @staticmethod
    def _usage_total(
        responses: list[ProviderResponseMetadata],
        field_name: str,
    ) -> int | None:
        values = [
            getattr(response.usage, field_name)
            for response in responses
            if response.usage is not None
            and getattr(response.usage, field_name) is not None
        ]
        return sum(values) if values else None

    def _metrics(
        self,
        context: AgentContext,
        state: _RunState,
        *,
        finished_at: datetime | None = None,
        duration_seconds: float | None = None,
    ) -> AgentNodeMetrics:
        finished = finished_at or datetime.now(UTC)
        duration = (
            duration_seconds
            if duration_seconds is not None
            else time.monotonic() - state.started_monotonic
        )
        rule_count = len(context.commit.parsed_rules) if context.commit else 0
        anomaly_count = (
            len(context.commit.request.anomalies) if context.commit else 0
        )
        inspection_names = {
            "list_concepts",
            "search_forms",
            "list_available_nodes",
            "get_alignments",
        }
        cost_values = [
            response.usage.cost_usd
            for response in state.provider_responses
            if response.usage is not None and response.usage.cost_usd is not None
        ]
        inspection_count = sum(
            name in inspection_names for name in state.successful_tool_names
        )
        sound_law_tests = state.successful_tool_names.count("test_sound_law")
        return AgentNodeMetrics(
            started_at=state.started_at,
            finished_at=finished,
            duration_seconds=max(0.0, duration),
            turn_count=state.turn_count,
            provider_attempts=state.provider_attempts,
            retry_count=state.retry_count,
            tool_call_count=state.tool_call_count,
            failed_tool_call_count=state.failed_tool_call_count,
            tool_failures_by_type=dict(sorted(state.tool_failures_by_type.items())),
            truncated_response_count=state.truncated_response_count,
            inspection_tool_calls=inspection_count,
            sound_law_tests=sound_law_tests,
            cascade_tests=state.successful_tool_names.count("test_rule_cascade"),
            input_tokens=self._usage_total(
                state.provider_responses, "input_tokens"
            ),
            output_tokens=self._usage_total(
                state.provider_responses, "output_tokens"
            ),
            total_tokens=self._usage_total(
                state.provider_responses, "total_tokens"
            ),
            cost_usd=sum(cost_values) if cost_values else None,
            committed_rule_count=rule_count,
            committed_anomaly_count=anomaly_count,
            committed_without_inspection=(
                context.commit is not None and inspection_count == 0
            ),
            identity_without_testing=(
                context.commit is not None
                and rule_count == 0
                and sound_law_tests == 0
            ),
        )

    def _trajectory(
        self,
        context: AgentContext,
        payload: NodePromptPayload,
        messages: list[LLMMessage],
        state: _RunState,
        *,
        completed: bool,
        failure: str | None = None,
        write_to_sink: bool = True,
    ) -> AgentTrajectory:
        definitions = self.registry.definitions()
        trajectory_id = f"trajectory-{uuid.uuid4()}"
        trajectory = AgentTrajectory(
            trajectory_id=trajectory_id,
            run_id=self.run_id,
            configuration_sha256=self.configuration_sha256,
            node_id=context.node_id,
            provider_adapter=type(self.provider).__name__,
            model_id=getattr(self.provider, "model", None),
            instruction_sha256=hashlib.sha256(
                self.instructions.encode()
            ).hexdigest(),
            tool_schema_sha256=_sha256_json(
                [definition.model_dump(mode="json") for definition in definitions]
            ),
            payload_schema_sha256=_sha256_json(
                NodePromptPayload.model_json_schema()
            ),
            trajectory_schema_sha256=_sha256_json(
                AgentTrajectory.model_json_schema()
            ),
            initial_payload=payload,
            tool_definitions=definitions,
            messages=tuple(messages),
            provider_responses=tuple(state.provider_responses),
            metrics=self._metrics(context, state),
            committed_reconstruction=context.commit,
            completed=completed,
            failure=failure,
        )
        if completed:
            self._trajectory_starts[trajectory_id] = state.started_monotonic
        if write_to_sink and self.trajectory_sink is not None:
            self.trajectory_sink.write(trajectory)
        return trajectory

    def finalize(
        self,
        run_result: AgentRunResult,
        step: ReconstructionStep,
    ) -> AgentRunResult:
        """Attach deterministic outcome data and emit the completed trajectory."""
        now = datetime.now(UTC)
        started = self._trajectory_starts.pop(
            run_result.trajectory.trajectory_id,
            time.monotonic(),
        )
        metrics = run_result.trajectory.metrics.model_copy(
            update={
                "finished_at": now,
                "duration_seconds": max(0.0, time.monotonic() - started),
            }
        )
        trajectory = run_result.trajectory.model_copy(
            update={"reconstruction_step": step, "metrics": metrics}
        )
        if self.trajectory_sink is not None:
            self.trajectory_sink.write(trajectory)
        self._emit(
            AgentEventKind.NODE_COMPLETE,
            step.parent_node_id,
            f"reconstructed {len(step.output_beam.distributions)} concepts",
            child_node_ids=list(step.child_node_ids),
            provider_adapter=trajectory.provider_adapter,
            model_id=trajectory.model_id,
            duration_seconds=metrics.duration_seconds,
            turn_count=metrics.turn_count,
            tool_call_count=metrics.tool_call_count,
            retry_count=metrics.retry_count,
            rule_count=step.diagnostics.rule_count,
            rule_complexity_cost=step.diagnostics.rule_complexity_cost,
            anomaly_count=step.diagnostics.anomaly_count,
            anomaly_rate=step.diagnostics.anomaly_rate,
            rule_coverage=step.diagnostics.rule_coverage,
            output_candidates=sum(
                len(distribution.candidates)
                for distribution in step.output_beam.distributions
            ),
            token_usage={
                "input": metrics.input_tokens,
                "output": metrics.output_tokens,
                "total": metrics.total_tokens,
            },
            cost_usd=metrics.cost_usd,
        )
        return AgentRunResult(
            reconstruction=run_result.reconstruction,
            trajectory=trajectory,
        )

    def run(self, context: AgentContext) -> AgentRunResult:
        payload = NodePromptPayload(
            node_id=context.node_id,
            active_children=tuple(
                NodeLexiconSummary(
                    node_id=lexicon.variety_id,
                    name=lexicon.name,
                    form_count=len(lexicon.forms),
                    concept_count=len({form.concept_id for form in lexicon.forms}),
                )
                for lexicon in context.child_lexicons
            ),
            anchor_policy=context.anchor_policy,
            anchors=context.anchors,
        )
        messages = [
            LLMMessage(role=MessageRole.SYSTEM, content=self.instructions),
            LLMMessage(
                role=MessageRole.USER,
                content=(
                    "Reconstruct the parent represented by this node. Use the tools "
                    "iteratively and finish with commit_reconstruction.\n\n"
                    + payload.model_dump_json(indent=2)
                ),
            ),
        ]
        state = _RunState(
            started_at=datetime.now(UTC),
            started_monotonic=time.monotonic(),
        )
        self._emit(
            AgentEventKind.NODE_START,
            context.node_id,
            "starting reconstruction",
            active_child_ids=list(context.child_ids),
            anchor_policy=context.anchor_policy.value,
            anchor_count=len(context.anchors),
            available_evidence_nodes=len(context.evidence),
            provider_adapter=type(self.provider).__name__,
            model_id=getattr(self.provider, "model", None),
        )
        try:
            for turn_index in range(1, self.max_turns + 1):
                if (
                    self.max_total_turns is not None
                    and self._total_turns >= self.max_total_turns
                ):
                    raise RunBudgetExceeded(
                        "run exceeded its total model-turn limit"
                    )
                self._total_turns += 1
                state.turn_count = turn_index
                self._emit(
                    AgentEventKind.MODEL_TURN,
                    context.node_id,
                    f"requesting model turn {turn_index}",
                    message_count=len(messages),
                    tool_count=len(self.registry.definitions()),
                )
                response = self._complete_with_retry(
                    context.node_id,
                    messages,
                    state,
                )
                reply = response.message
                if reply.role is not MessageRole.ASSISTANT:
                    raise ValueError(
                        "LLM providers must return an assistant message"
                    )
                messages.append(reply)
                self._emit(
                    AgentEventKind.MODEL_RESPONSE,
                    context.node_id,
                    f"model returned {len(reply.tool_calls)} tool call(s)",
                    content=reply.content,
                    tool_names=[call.name for call in reply.tool_calls],
                    provider=response.metadata.provider_id,
                    model_id=response.metadata.model_id,
                    response_id=response.metadata.response_id,
                    usage=(
                        response.metadata.usage.model_dump(mode="json")
                        if response.metadata.usage
                        else None
                    ),
                )
                truncated = response.metadata.finish_reason == "length"
                if truncated:
                    state.truncated_response_count += 1
                    self._emit(
                        AgentEventKind.RESPONSE_TRUNCATED,
                        context.node_id,
                        "model response hit the output limit before finishing",
                        truncated_response_count=state.truncated_response_count,
                        max_truncated_responses=self.max_truncated_responses,
                        had_tool_calls=bool(reply.tool_calls),
                    )
                    if (
                        state.truncated_response_count
                        >= self.max_truncated_responses
                        and not reply.tool_calls
                    ):
                        raise ProtocolStallError(
                            "model output was truncated "
                            f"{state.truncated_response_count} times without "
                            "producing a tool call; reduce reasoning length or "
                            "raise the provider max_tokens option"
                        )
                if not reply.tool_calls:
                    messages.append(
                        LLMMessage(
                            role=MessageRole.USER,
                            content=(
                                "Your previous response was cut off at the output "
                                "limit before it produced a tool call. Reply with a "
                                "single small tool call and no long explanation."
                            )
                            if truncated
                            else (
                                "Continue by calling an available tool. The session "
                                "ends only after a valid commit_reconstruction call."
                            ),
                        )
                    )
                    continue
                # One assistant message may carry several tool calls, and every
                # tool result must follow its call without anything in between.
                # Interventions therefore wait until the whole batch is answered.
                pending_correction: str | None = None
                pending_stall: str | None = None
                for call in reply.tool_calls:
                    if state.tool_call_count >= self.max_tool_calls:
                        raise AgentLoopLimitError(
                            "agent exceeded its per-node tool-call limit"
                        )
                    if (
                        self.max_total_tool_calls is not None
                        and self._total_tool_calls >= self.max_total_tool_calls
                    ):
                        raise RunBudgetExceeded(
                            "run exceeded its total tool-call limit"
                        )
                    state.tool_call_count += 1
                    self._total_tool_calls += 1
                    state.tool_names.append(call.name)
                    self._emit(
                        AgentEventKind.TOOL_CALL,
                        context.node_id,
                        f"calling tool {call.name}",
                        call_id=call.call_id,
                        arguments=call.arguments,
                    )
                    result = self.registry.execute(call, context)
                    if result.ok:
                        state.successful_tool_names.append(call.name)
                    else:
                        correction, stall_reason = self._record_tool_failure(
                            context, state, call, result
                        )
                        pending_correction = pending_correction or correction
                        pending_stall = pending_stall or stall_reason
                    self._emit(
                        AgentEventKind.TOOL_RESULT,
                        context.node_id,
                        f"tool {call.name} "
                        f"{'succeeded' if result.ok else 'failed'}",
                        call_id=call.call_id,
                        result=result.model_dump(mode="json"),
                    )
                    messages.append(
                        LLMMessage(
                            role=MessageRole.TOOL,
                            content=result.model_dump_json(),
                            tool_call_id=call.call_id,
                            name=call.name,
                        )
                    )
                    if context.commit is not None:
                        self._emit(
                            AgentEventKind.NODE_COMMIT,
                            context.node_id,
                            "accepted reconstruction commit",
                            rule_ids=[
                                rule.rule.rule_id
                                for rule in context.commit.parsed_rules
                            ],
                            anomaly_count=len(
                                context.commit.request.anomalies
                            ),
                            cascade_validation_call_id=(
                                context.commit.request.cascade_validation_call_id
                            ),
                        )
                        trajectory = self._trajectory(
                            context,
                            payload,
                            messages,
                            state,
                            completed=True,
                            write_to_sink=False,
                        )
                        return AgentRunResult(
                            reconstruction=context.commit,
                            trajectory=trajectory,
                        )
                if pending_stall is not None:
                    raise ProtocolStallError(pending_stall)
                if pending_correction is not None:
                    messages.append(
                        LLMMessage(
                            role=MessageRole.USER,
                            content=pending_correction,
                        )
                    )
            raise AgentLoopLimitError(
                "agent did not commit within its per-node turn limit"
            )
        except Exception as error:
            failure = f"{type(error).__name__}: {error}"
            self._trajectory(
                context,
                payload,
                messages,
                state,
                completed=False,
                failure=failure,
            )
            self._emit(
                AgentEventKind.NODE_FAILED,
                context.node_id,
                "reconstruction node failed",
                error_type=type(error).__name__,
                error=str(error),
                duration_seconds=time.monotonic() - state.started_monotonic,
                turn_count=state.turn_count,
                tool_call_count=state.tool_call_count,
                retry_count=state.retry_count,
            )
            raise
