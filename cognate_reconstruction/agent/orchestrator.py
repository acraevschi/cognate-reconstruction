"""Bounded, retrying native-tool loop for one reconstruction node."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Callable

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.error_codes import (
    UNCLASSIFIED_ERROR_CODE,
    ToolErrorCategory,
    classify_tool_error_code,
)
from cognate_reconstruction.agent.events import (
    AgentEvent,
    AgentEventKind,
    AgentEventSink,
)
from cognate_reconstruction.agent.inspection import inspected_concept_ids
from cognate_reconstruction.agent.instructions import load_agent_instructions
from cognate_reconstruction.agent.providers import ProviderTransientError
from cognate_reconstruction.agent.providers.protocol import LLMProvider
from cognate_reconstruction.agent.schemas import (
    COMMIT_REQUIREMENT_NOTES,
    ConceptHoldout,
    LLMMessage,
    LLMToolCall,
    MessageRole,
    NodeLexiconSummary,
    NodePromptPayload,
    ProviderResponse,
    ProviderResponseMetadata,
    ToolError,
    ToolExecutionResult,
)
from cognate_reconstruction.agent.tools import ToolRegistry, default_tool_registry
from cognate_reconstruction.agent.tools.heldout import held_out_evaluation
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


NODE_TRAJECTORY_ATTRIBUTE = "node_trajectory"
"""Attribute carrying the trajectory of the node session an exception ended.

Set on the exception itself rather than kept on the orchestrator, which runs
every node and would overwrite it. A caller that decides whether one dead node
ends the whole run needs the record of *that* node, and re-deriving it from the
JSONL the sink just wrote would be a second source of truth.
"""


def failed_node_trajectory(error: BaseException) -> AgentTrajectory | None:
    """The trajectory of the node session this exception ended, when it has one.

    `None` for anything raised outside a node session, and for the rare
    exception type that refuses attributes.
    """
    trajectory = getattr(error, NODE_TRAJECTORY_ATTRIBUTE, None)
    return trajectory if isinstance(trajectory, AgentTrajectory) else None


class ProtocolStallError(RuntimeError):
    """The model kept repeating one rejected call after a targeted correction.

    Raised instead of silently spending the remaining turn budget: a named stall
    in a trajectory is more useful than an exhausted loop limit.
    """


_FailureSignature = tuple[str, str]

_SUCCESS_SIGNATURE: _FailureSignature = ("", "<success>")
"""Placeholder recorded for an accepted call so it occupies a window slot."""

COMPACTABLE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "get_alignments",
        "summarize_correspondences",
        "search_forms",
        "list_concepts",
        "list_available_nodes",
        "get_node_reconstruction",
        "polarize",
    }
)
"""Tools whose superseded results may be dropped from the live prompt.

Read-only evidence, and nothing else. A `test_sound_law` or `test_rule_cascade`
result carries the validation ID a commit is checked against, `segment_morphemes`
carries an overlay ID, and a `commit_reconstruction` result ends the session:
none of those are re-derivable from a later call, so none are eligible however
much context they cost.
"""

_SELECTION_ARGUMENT_KEYS: frozenset[str] = frozenset(
    {"node_ids", "node_id", "concept_ids", "form_ids", "cognate_set_ids"}
)
"""Arguments that name *what* was asked for, rather than how.

These are compared as sets, with absent or empty meaning "everything", so a
widening call supersedes a narrower one. Every other argument — pagination,
`detail`, filters, flags, overlays — must match exactly, because a later call
that changed one of them asked a different question.
"""


def _selection_values(value: object) -> frozenset[str] | None:
    """One selection argument as a set, or None for "unrestricted"."""
    if value is None:
        return None
    if isinstance(value, str):
        return frozenset({value})
    if isinstance(value, (list, tuple)):
        return frozenset(map(str, value)) or None
    return frozenset({str(value)})


def _supersedes(later: dict[str, object], earlier: dict[str, object]) -> bool:
    """Does a later call re-request everything an earlier one asked for?

    Deliberately strict. Two calls that overlap without one covering the other —
    concepts 1 and 2, then concepts 3 and 4 — are *not* superseded: the earlier
    result still holds evidence the later one never returned, and dropping it
    would silently take back something the model may still be reasoning from.
    Absent and empty are treated alike for selections, since both mean "no
    filter" across this tool surface.
    """
    for key in set(later) | set(earlier):
        if key in _SELECTION_ARGUMENT_KEYS:
            later_selection = _selection_values(later.get(key))
            if later_selection is None:
                continue
            earlier_selection = _selection_values(earlier.get(key))
            if earlier_selection is None or not earlier_selection <= later_selection:
                return False
        elif later.get(key) != earlier.get(key):
            return False
    return True


def _compaction_placeholder(name: str, call_id: str, superseded_by: str) -> str:
    return json.dumps(
        {
            "compacted": True,
            "tool": name,
            "call_id": call_id,
            "superseded_by": superseded_by,
            "note": (
                f"The result of this {name} call was removed from the "
                f"conversation to save context, because the later {name} call "
                f"{superseded_by} requested the same evidence and its result is "
                "still here. Call the tool again if you need it back."
            ),
        }
    )


@dataclass(frozen=True)
class _ToolResultRecord:
    """Where one compactable tool result sits, and what it asked for."""

    index: int
    call_id: str
    name: str
    arguments: dict[str, object]


@dataclass
class _MessageLog:
    """The conversation in the two forms it has to exist in.

    `audit` is complete and is what the trajectory records. `prompt` is what the
    provider is sent, and is the only one compaction touches: an alignment
    payload fetched on turn 4 was still being charged for on turn 26, which is
    how a two-language node reached 109k input tokens without committing.

    They are deliberately allowed to diverge. A trajectory whose tool results
    had been replaced by placeholders would be worthless both as an audit record
    and as supervision, so the full content stays there and the
    `context_compaction` events say where the live prompt differed.
    """

    audit: list[LLMMessage] = field(default_factory=list)
    prompt: list[LLMMessage] = field(default_factory=list)

    def append(self, message: LLMMessage) -> int:
        self.audit.append(message)
        self.prompt.append(message)
        return len(self.prompt) - 1

    def replace_prompt_content(self, index: int, content: str) -> None:
        self.prompt[index] = self.prompt[index].model_copy(
            update={"content": content}
        )


@dataclass
class _RunState:
    started_at: datetime
    started_monotonic: float
    turn_count: int = 0
    provider_attempts: int = 0
    retry_count: int = 0
    tool_call_count: int = 0
    failed_tool_call_count: int = 0
    protocol_failure_count: int = 0
    tool_failures_by_type: dict[str, int] = field(default_factory=dict)
    truncated_response_count: int = 0
    forced_tool_choice_count: int = 0
    truncation_backoff_count: int = 0
    # Set by a truncated response that carried no tool call, consumed by the
    # next request. Every such truncation gets its own attempt, because the
    # first one is not the one that ends the node; only a backend that *refused*
    # `"required"` is written off, since it will not start honouring it later.
    force_tool_choice_next: bool = False
    forced_tool_choice_attempted: bool = False
    forced_tool_choice_refused: bool = False
    # Reported output length of each truncated response, in order. `None` for a
    # provider that reported no usage, which is not the same as zero.
    truncated_output_tokens: list[int | None] = field(default_factory=list)
    # The raised ceiling in force for this node, or None while the user's own
    # provider option is in effect untouched.
    effective_max_tokens: int | None = None
    tool_names: list[str] = field(default_factory=list)
    successful_tool_names: list[str] = field(default_factory=list)
    provider_responses: list[ProviderResponseMetadata] = field(default_factory=list)
    # The trailing window of (tool, error code) signatures, successes included so
    # that productive work pushes old failures out, and the signatures that have
    # already drawn a targeted correction.
    recent_call_signatures: deque[_FailureSignature] = field(
        default_factory=deque
    )
    corrected_failure_signatures: set[_FailureSignature] = field(
        default_factory=set
    )
    corrected_window_saturation: bool = False
    # Accepted results of read-only evidence tools that are still live in the
    # prompt, oldest first, and how many have been replaced by a placeholder.
    live_tool_results: list[_ToolResultRecord] = field(default_factory=list)
    compacted_tool_results: int = 0
    # Concepts named in tool arguments over the session, so a commit made after
    # looking at 5 of 46 concepts is legible as such.
    inspected_concept_ids: set[str] = field(default_factory=set)


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
        stall_window_calls: int | None = None,
        max_window_protocol_failures: int | None = None,
        max_truncated_responses: int = 3,
        allow_truncation_backoff: bool = False,
        truncation_max_tokens_ceiling: int | None = None,
        compact_superseded_tool_results: bool = True,
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
        window = (
            stall_window_calls
            if stall_window_calls is not None
            else 3 * max_repeated_tool_failures
        )
        if window < max_repeated_tool_failures:
            raise ValueError(
                "stall_window_calls must be at least max_repeated_tool_failures, "
                "or no signature could ever reach the threshold"
            )
        saturation = (
            max_window_protocol_failures
            if max_window_protocol_failures is not None
            else min(2 * max_repeated_tool_failures, window)
        )
        if not 1 <= saturation <= window:
            raise ValueError(
                "max_window_protocol_failures must be between 1 and "
                "stall_window_calls, or it could never be reached"
            )
        if allow_truncation_backoff and truncation_max_tokens_ceiling is None:
            raise ValueError(
                "allow_truncation_backoff requires "
                "truncation_max_tokens_ceiling; an unbounded override of a "
                "user-supplied provider option is not offered"
            )
        if (
            truncation_max_tokens_ceiling is not None
            and truncation_max_tokens_ceiling < 1
        ):
            raise ValueError("truncation_max_tokens_ceiling must be positive")
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
        self.stall_window_calls = window
        self.max_window_protocol_failures = saturation
        self.max_truncated_responses = max_truncated_responses
        self.allow_truncation_backoff = allow_truncation_backoff
        self.truncation_max_tokens_ceiling = truncation_max_tokens_ceiling
        self.compact_superseded_tool_results = compact_superseded_tool_results
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
            "stall_window_calls": window,
            "max_window_protocol_failures": saturation,
            "max_truncated_responses": max_truncated_responses,
            "allow_truncation_backoff": allow_truncation_backoff,
            "truncation_max_tokens_ceiling": truncation_max_tokens_ceiling,
            "compact_superseded_tool_results": compact_superseded_tool_results,
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
        *,
        tool_choice: str = "auto",
    ) -> ProviderResponse:
        definitions = self.registry.definitions()
        for retry_index in range(self.max_retries + 1):
            self._check_run_budget()
            state.provider_attempts += 1
            try:
                raw_response = self.provider.complete(
                    messages,
                    definitions,
                    tool_choice=tool_choice,
                    max_tokens_override=state.effective_max_tokens,
                )
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

    def _request_turn(
        self,
        node_id: str,
        messages: list[LLMMessage],
        state: _RunState,
    ) -> tuple[ProviderResponse, str]:
        """Request one turn, forcing a tool call if the last one was cut off.

        Most truncations are the model spending its whole output budget on
        reasoning prose before emitting any call, and `max_tokens` belongs to
        the user's `--provider-config` rather than to the harness. What the
        harness does own is how it builds the request, so the recovery that
        crosses no configuration boundary is to stop letting the model choose
        whether to call a tool at all.

        Not every backend honours `"required"`, and one that *refuses* it is
        written off for the rest of the node: it will not change its mind, and
        looping on it would burn the same budget the truncation already cost.
        Short of a refusal the intervention is offered to every truncated
        no-tool response rather than once per node. Once per node meant that a
        node ending on its third truncation got help on the first and nothing
        on the two that followed — and the later ones are the expensive ones,
        because they are what ends the node.

        Returns the response and the `tool_choice` that actually produced it.
        """
        if not state.force_tool_choice_next:
            return self._complete_with_retry(node_id, messages, state), "auto"
        state.force_tool_choice_next = False
        state.forced_tool_choice_attempted = True
        state.forced_tool_choice_count += 1
        self._emit(
            AgentEventKind.TRUNCATION_RECOVERY,
            node_id,
            "requiring a tool call after a truncated response produced none",
            action="forced_tool_choice",
            tool_choice="required",
            truncated_response_count=state.truncated_response_count,
        )
        try:
            response = self._complete_with_retry(
                node_id,
                messages,
                state,
                tool_choice="required",
            )
        except (ProviderTransientError, RunBudgetExceeded):
            # Neither is about `tool_choice`; retries and budgets own them.
            raise
        except Exception as error:
            state.forced_tool_choice_refused = True
            self._emit(
                AgentEventKind.TRUNCATION_RECOVERY,
                node_id,
                "provider rejected a required tool call; retrying with auto "
                "and not requiring one again on this node",
                action="forced_tool_choice_rejected",
                error_type=type(error).__name__,
                error=str(error),
            )
            return self._complete_with_retry(node_id, messages, state), "auto"
        return response, "required"

    def _apply_truncation_backoff(
        self,
        node_id: str,
        state: _RunState,
        response: ProviderResponse,
    ) -> None:
        """Raise the effective `max_tokens` for the rest of this node.

        Off unless the operator asked for it, because `max_tokens` is the
        user's own provider option and overriding it silently would make a run
        differ from its own configuration. The base is the truncated response's
        reported output length, which is what the effective limit actually was;
        without a reported length there is no way to guarantee the raised value
        stays above what the user configured, so nothing is applied.
        """
        ceiling = self.truncation_max_tokens_ceiling
        # The constructor rejects the enabled-without-a-ceiling pairing, so the
        # second half of this is belt and braces for a direct caller.
        if not self.allow_truncation_backoff or ceiling is None:
            return
        current = state.effective_max_tokens
        if current is None:
            usage = response.metadata.usage
            current = usage.output_tokens if usage is not None else None
        if current is None:
            self._emit(
                AgentEventKind.TRUNCATION_RECOVERY,
                node_id,
                "cannot raise max_tokens: the provider reported no output "
                "token count to raise it above",
                action="truncation_backoff_skipped",
                reason="no_reported_output_tokens",
            )
            return
        raised = min(2 * current, ceiling)
        if raised <= current:
            self._emit(
                AgentEventKind.TRUNCATION_RECOVERY,
                node_id,
                "cannot raise max_tokens further: the ceiling is already reached",
                action="truncation_backoff_skipped",
                reason="ceiling_reached",
                effective_max_tokens=current,
                ceiling=ceiling,
            )
            return
        state.effective_max_tokens = raised
        state.truncation_backoff_count += 1
        self._emit(
            AgentEventKind.TRUNCATION_RECOVERY,
            node_id,
            f"raised the effective max_tokens from {current} to {raised}",
            action="truncation_backoff",
            previous_max_tokens=current,
            effective_max_tokens=raised,
            ceiling=ceiling,
            backoff_count=state.truncation_backoff_count,
        )

    def _truncation_stall_reason(self, state: _RunState) -> str:
        """Say what was already tried, so the remaining remedy is the operator's.

        A bare "raise max_tokens" was misleading once the harness started
        intervening on its own: the reader needs to know whether forcing a tool
        call and raising the budget were attempted and still failed.
        """
        reason = (
            "model output was truncated "
            f"{state.truncated_response_count} times without producing a tool "
            "call"
        )
        # The operator's remaining lever is `max_tokens`, and choosing a new
        # value by guesswork is what the previous message left them to do. What
        # the model actually spent is recorded on every truncated response.
        observed = [
            tokens for tokens in state.truncated_output_tokens if tokens is not None
        ]
        if observed:
            reason += (
                "; those responses reported "
                + ", ".join(str(tokens) for tokens in observed)
                + f" output tokens (max {max(observed)})"
            )
            if state.effective_max_tokens is not None:
                reason += (
                    " against an effective max_tokens of "
                    f"{state.effective_max_tokens}"
                )
        elif state.truncated_output_tokens:
            reason += (
                "; the provider reported no output token count for them, so "
                "how far past the budget the model was reaching is unknown"
            )
        attempted = []
        if state.forced_tool_choice_attempted:
            attempted.append("requiring a tool call")
        if state.truncation_backoff_count:
            attempted.append(
                "raising max_tokens to "
                f"{state.effective_max_tokens} over "
                f"{state.truncation_backoff_count} backoff step(s)"
            )
        if attempted:
            reason += f"; the harness already tried {' and '.join(attempted)}"
        remedy = "raise the provider max_tokens option or use a smaller prompt"
        if not self.allow_truncation_backoff:
            remedy = (
                "raise the provider max_tokens option, or enable "
                "--allow-truncation-backoff with a ceiling"
            )
        return f"{reason}; {remedy}"

    def _record_call_signature(
        self,
        state: _RunState,
        signature: _FailureSignature,
    ) -> int:
        """Append one call to the trailing window and count that signature in it.

        The window is bounded, and successes occupy slots too, so a repeat that
        is far away from its predecessors is forgiven while a dense cluster is
        not. That is the real distinction between a session that recovered and
        moved on and one that is going in circles: resetting on success instead
        would be fooled by the obvious interleave — bad commit, good
        ``test_sound_law``, bad commit — which is exactly what a stuck model
        produces.
        """
        window = state.recent_call_signatures
        window.append(signature)
        while len(window) > self.stall_window_calls:
            window.popleft()
        return sum(entry == signature for entry in window)

    def _record_tool_failure(
        self,
        context: AgentContext,
        state: _RunState,
        call: LLMToolCall,
        result: ToolExecutionResult,
    ) -> tuple[str | None, str | None]:
        """Count a rejected call and decide whether to intervene.

        Returns ``(correction, stall_reason)``. The loop retries transport
        failures, but one mistake reproduced N times is not transport: it is the
        model failing to read the contract. Correct it once with the tool's own
        remediation, then fail fast rather than spending the budget.

        The signature is ``(tool name, structural error code)``, not the error
        text. Pydantic embeds input values in its messages, so a model that
        keeps varying its malformed arguments produced a fresh message — and a
        fresh signature — for one unchanging mistake, and looped until the turn
        limit. Occurrences are also counted across the window rather than only
        in consecutive runs, because a live gemma session alternated between two
        commit errors so that neither was ever consecutive.
        """
        error = result.error
        error_type = error.error_type if error is not None else "unknown"
        message = error.message if error is not None else ""
        code = (error.code if error is not None else None) or UNCLASSIFIED_ERROR_CODE
        state.failed_tool_call_count += 1
        if classify_tool_error_code(code) is ToolErrorCategory.PROTOCOL:
            state.protocol_failure_count += 1
        state.tool_failures_by_type[code] = (
            state.tool_failures_by_type.get(code, 0) + 1
        )
        signature = (call.name, code)
        occurrences = self._record_call_signature(state, signature)
        if occurrences < self.max_repeated_tool_failures:
            return self._window_intervention(context, state, error)
        if signature in state.corrected_failure_signatures:
            return None, (
                f"tool {call.name} produced the same {code} rejection again "
                f"({occurrences} times in the last {self.stall_window_calls} "
                "calls) after a targeted correction quoting it; the model is "
                "not adapting to the tool contract"
            )
        state.corrected_failure_signatures.add(signature)
        remediation = error.remediation if error is not None else None
        correction = (
            f"Stop. {occurrences} of your last {self.stall_window_calls} tool "
            f"calls were {call.name} calls rejected for the same reason "
            f"({code}), so varying the same malformed arguments cannot "
            "succeed:\n"
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
            error_code=code,
            reason="repeated_signature",
            repeated=occurrences,
            window=self.stall_window_calls,
        )
        return correction, None

    def _window_intervention(
        self,
        context: AgentContext,
        state: _RunState,
        error: ToolError | None,
    ) -> tuple[str | None, str | None]:
        """Catch a model that is stuck without ever repeating one mistake.

        The per-signature rule needs the *same* code N times. A model that
        produces a differently-shaped protocol error on every turn — a missing
        field here, an unknown reference there — never satisfies it and simply
        runs out of turns with no diagnosis. Saturation of the window is the
        general condition: it does not care which mistakes they were, only that
        the recent past is mostly rejected calls.

        Exploratory rejections are excluded. A model working through malformed
        sound laws is using the tools as intended, however many it gets wrong,
        and ending its node for that would punish exactly the behaviour the
        trajectories are meant to teach.
        """
        failures = sum(
            entry != _SUCCESS_SIGNATURE
            and classify_tool_error_code(entry[1]) is ToolErrorCategory.PROTOCOL
            for entry in state.recent_call_signatures
        )
        if failures < self.max_window_protocol_failures:
            return None, None
        codes = sorted(
            {
                entry[1]
                for entry in state.recent_call_signatures
                if entry != _SUCCESS_SIGNATURE
                and classify_tool_error_code(entry[1]) is ToolErrorCategory.PROTOCOL
            }
        )
        if state.corrected_window_saturation:
            return None, (
                f"{failures} of the last {len(state.recent_call_signatures)} "
                "tool calls were rejected on protocol grounds even after a "
                f"correction naming them ({', '.join(codes)}); the model is "
                "cycling through malformed calls rather than adapting to the "
                "tool contract"
            )
        state.corrected_window_saturation = True
        correction = (
            f"Stop. {failures} of your last "
            f"{len(state.recent_call_signatures)} tool calls were rejected "
            "before they ran, for these reasons: "
            f"{', '.join(codes)}. You are not converging on the tool contract. "
            "Re-read the schema of the tool you are calling and send one "
            "minimal, complete call."
        )
        remediation = error.remediation if error is not None else None
        if remediation:
            correction += f"\n{remediation}"
        self._emit(
            AgentEventKind.PROTOCOL_CORRECTION,
            context.node_id,
            "injected a targeted correction after repeated protocol rejections",
            reason="window_saturated",
            error_codes=codes,
            repeated=failures,
            window=self.stall_window_calls,
        )
        return correction, None

    def _compact_superseded_results(
        self,
        context: AgentContext,
        state: _RunState,
        messages: _MessageLog,
        call: LLMToolCall,
    ) -> None:
        """Drop from the live prompt what this call just re-requested.

        Looking at the evidence costs more context than reasoning about it, and
        nothing was ever released: every payload stayed in the prompt for the
        rest of the node. This reclaims only the safe part of that — a result
        whose selection a later call covers in full, for a read-only tool that
        can be called again — and leaves the newest result for each tool in
        place, so the model never ends a turn with no copy of what it asked for.

        The replacement is content-only. Message order is untouched, so every
        tool call is still immediately followed by its own tool message.
        """
        if not self.compact_superseded_tool_results:
            return
        if call.name not in COMPACTABLE_TOOL_NAMES:
            return
        superseded = [
            record
            for record in state.live_tool_results
            if record.name == call.name
            and record.call_id != call.call_id
            and _supersedes(call.arguments, record.arguments)
        ]
        for record in superseded:
            messages.replace_prompt_content(
                record.index,
                _compaction_placeholder(record.name, record.call_id, call.call_id),
            )
            state.live_tool_results.remove(record)
            state.compacted_tool_results += 1
            self._emit(
                AgentEventKind.CONTEXT_COMPACTION,
                context.node_id,
                f"dropped a superseded {record.name} result from the prompt",
                tool_name=record.name,
                call_id=record.call_id,
                superseded_by=call.call_id,
                compacted_tool_results=state.compacted_tool_results,
            )

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
            "summarize_correspondences",
            "get_alignments",
            "polarize",
        }
        cost_values = [
            response.usage.cost_usd
            for response in state.provider_responses
            if response.usage is not None and response.usage.cost_usd is not None
        ]
        inspection_count = sum(
            name in inspection_names for name in state.successful_tool_names
        )
        available_concept_ids = {form.concept_id for form in context.all_forms}
        sound_law_tests = state.successful_tool_names.count("test_sound_law")
        # Recomputed from the commit rather than lifted out of the tool result,
        # so a trajectory carries the number even when the result message was
        # truncated or compacted away.
        held_out = (
            held_out_evaluation(
                context,
                context.commit.parsed_rules,
                segmentation_overlay_id=(
                    context.commit.request.segmentation_overlay_id
                ),
            )
            if context.commit is not None
            else None
        )
        return AgentNodeMetrics(
            started_at=state.started_at,
            finished_at=finished,
            duration_seconds=max(0.0, duration),
            turn_count=state.turn_count,
            provider_attempts=state.provider_attempts,
            retry_count=state.retry_count,
            tool_call_count=state.tool_call_count,
            failed_tool_call_count=state.failed_tool_call_count,
            protocol_failure_count=state.protocol_failure_count,
            tool_failures_by_type=dict(sorted(state.tool_failures_by_type.items())),
            truncated_response_count=state.truncated_response_count,
            forced_tool_choice_count=state.forced_tool_choice_count,
            truncation_backoff_applied=state.truncation_backoff_count,
            compacted_tool_results=state.compacted_tool_results,
            inspection_tool_calls=inspection_count,
            concepts_inspected=len(
                state.inspected_concept_ids & available_concept_ids
            ),
            concepts_available=len(available_concept_ids),
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
            held_out_concept_count=(
                len(context.concept_split.held_out_concept_ids)
            ),
            held_out_convergence_rate=(
                held_out.convergence.child_convergence_rate
                if held_out is not None and held_out.convergence is not None
                else None
            ),
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

    def emit_node_fallback(
        self,
        node_id: str,
        *,
        error_type: str,
        reason: str,
        failed_node_count: int,
        max_failed_nodes: int | None,
    ) -> None:
        """Record that the traversal continued over a dead node.

        `node_failed` says the session ended; this says what the run did next,
        which is the part an operator reading the timeline cannot infer.
        """
        self._emit(
            AgentEventKind.NODE_FALLBACK,
            node_id,
            "committing an identity fallback for a failed node and continuing",
            error_type=error_type,
            reason=reason,
            failed_node_count=failed_node_count,
            max_failed_nodes=max_failed_nodes,
        )

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
            inspected_concept_ids=run_result.inspected_concept_ids,
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
            # Stated before the session starts rather than discovered through a
            # rejection: a requirement that lives only in code teaches the model
            # that the harness is capricious, not that the claim needs making.
            concept_holdout=ConceptHoldout(
                development_concept_ids=context.concept_split.development_concept_ids,
                held_out_concept_ids=context.concept_split.held_out_concept_ids,
                held_out_share=context.concept_split.held_out_share,
            ),
            commit_requirements=COMMIT_REQUIREMENT_NOTES,
        )
        messages = _MessageLog()
        messages.append(
            LLMMessage(role=MessageRole.SYSTEM, content=self.instructions)
        )
        messages.append(
            LLMMessage(
                role=MessageRole.USER,
                content=(
                    "Reconstruct the parent represented by this node. Use the tools "
                    "iteratively and finish with commit_reconstruction.\n\n"
                    + payload.model_dump_json(indent=2)
                ),
            )
        )
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
                    message_count=len(messages.prompt),
                    tool_count=len(self.registry.definitions()),
                    tool_choice=(
                        "required" if state.force_tool_choice_next else "auto"
                    ),
                    max_tokens_override=state.effective_max_tokens,
                )
                response, tool_choice = self._request_turn(
                    context.node_id,
                    messages.prompt,
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
                    tool_choice=tool_choice,
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
                    state.truncated_output_tokens.append(
                        response.metadata.usage.output_tokens
                        if response.metadata.usage is not None
                        else None
                    )
                    self._emit(
                        AgentEventKind.RESPONSE_TRUNCATED,
                        context.node_id,
                        "model response hit the output limit before finishing",
                        truncated_response_count=state.truncated_response_count,
                        max_truncated_responses=self.max_truncated_responses,
                        had_tool_calls=bool(reply.tool_calls),
                        forced_tool_choice_attempted=(
                            state.forced_tool_choice_attempted
                        ),
                        output_tokens=state.truncated_output_tokens[-1],
                    )
                    if (
                        state.truncated_response_count
                        >= self.max_truncated_responses
                        and not reply.tool_calls
                    ):
                        raise ProtocolStallError(
                            self._truncation_stall_reason(state)
                        )
                    if not reply.tool_calls:
                        # Recover before the next request rather than only
                        # naming the condition: require a tool call, and raise
                        # the token budget if the operator allowed it.
                        if not state.forced_tool_choice_refused:
                            state.force_tool_choice_next = True
                        self._apply_truncation_backoff(
                            context.node_id, state, response
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
                    state.inspected_concept_ids |= inspected_concept_ids(
                        call.name,
                        call.arguments,
                        concepts_by_form_id={
                            form.form_id: form.concept_id
                            for form in context.all_forms
                        },
                        available_concept_ids={
                            form.concept_id for form in context.all_forms
                        },
                    )
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
                        self._record_call_signature(state, _SUCCESS_SIGNATURE)
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
                        error_code=(
                            result.error.code if result.error is not None else None
                        ),
                        result=result.model_dump(mode="json"),
                    )
                    index = messages.append(
                        LLMMessage(
                            role=MessageRole.TOOL,
                            content=result.model_dump_json(),
                            tool_call_id=call.call_id,
                            name=call.name,
                        )
                    )
                    if result.ok:
                        # Only an accepted read-only result is ever dropped: a
                        # rejection is small and carries the correction the model
                        # still has to read.
                        self._compact_superseded_results(
                            context, state, messages, call
                        )
                        if call.name in COMPACTABLE_TOOL_NAMES:
                            state.live_tool_results.append(
                                _ToolResultRecord(
                                    index=index,
                                    call_id=call.call_id,
                                    name=call.name,
                                    arguments=dict(call.arguments),
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
                            messages.audit,
                            state,
                            completed=True,
                            write_to_sink=False,
                        )
                        return AgentRunResult(
                            reconstruction=context.commit,
                            trajectory=trajectory,
                            inspected_concept_ids=tuple(
                                sorted(state.inspected_concept_ids)
                            ),
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
            trajectory = self._trajectory(
                context,
                payload,
                messages.audit,
                state,
                completed=False,
                failure=failure,
            )
            try:
                setattr(error, NODE_TRAJECTORY_ATTRIBUTE, trajectory)
            except AttributeError:
                # An exception type that forbids attributes must still
                # propagate; losing the hand-off is better than masking it.
                pass
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
