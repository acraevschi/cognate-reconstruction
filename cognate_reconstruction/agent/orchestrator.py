"""Bounded, retrying native-tool loop for one reconstruction node."""

from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable

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
from cognate_reconstruction.agent.providers import ProviderError
from cognate_reconstruction.agent.providers.errors import normalized_provider_error
from cognate_reconstruction.agent.providers.protocol import LLMProvider
from cognate_reconstruction.agent.request_journal import (
    USAGE_ACCOUNTING_VERSION,
    USAGE_TOTALS,
    RequestJournal,
    RequestJournalError,
)
from cognate_reconstruction.agent.schemas import (
    COMMIT_REQUIREMENT_NOTES,
    CommittedHypothesis,
    CommittedReconstruction,
    ConceptHoldout,
    GetAlignmentsArgs,
    GetNodeReconstructionArgs,
    LLMMessage,
    LLMToolCall,
    ListAvailableNodesArgs,
    ListConceptsArgs,
    MessageRole,
    NodeLexiconSummary,
    NodePromptPayload,
    PolarizeArgs,
    ProviderResponse,
    ProviderResponseMetadata,
    SearchFormsArgs,
    SummarizeCorrespondencesArgs,
    ToolError,
    ToolExecutionResult,
)
from cognate_reconstruction.agent.tools import ToolRegistry, default_tool_registry
from cognate_reconstruction.agent.tools.heldout import held_out_evaluation
from cognate_reconstruction.agent.trajectory import (
    INVENTORY_SCHEMA_VERSION,
    EVIDENCE_SCHEMA_VERSION,
    TRAJECTORY_SCHEMA_VERSION,
    AgentNodeMetrics,
    AgentRunResult,
    AgentTrajectory,
    TrajectorySink,
)
from cognate_reconstruction.schemas.common import WorkbenchModel
from cognate_reconstruction.schemas.inventory import CommittedProtoInventory
from cognate_reconstruction.schemas.traversal import ReconstructionStep


def _commit_event_fields(commit: CommittedHypothesis) -> dict[str, object]:
    """What a NODE_COMMIT event says, under whichever protocol was used.

    An inventory has no rule IDs and no cascade to reference, so an event shaped
    for rules would report an empty list and read as an identity commit. It says
    what it actually committed instead.
    """
    if isinstance(commit, CommittedProtoInventory):
        return {
            "commit_shape": "inventory",
            "committed_set_count": len(commit.request.commitments),
            "proto_phonemes": list(commit.proto_phonemes),
            "residue_policy": commit.request.residue_policy.value,
            "anomaly_count": len(commit.request.anomalies),
            "assembly_validation_call_id": (
                commit.request.assembly_validation_call_id
            ),
        }
    return {
        "commit_shape": "rules",
        "rule_ids": [rule.rule.rule_id for rule in commit.parsed_rules],
        "anomaly_count": len(commit.request.anomalies),
        "cascade_validation_call_id": (
            commit.request.cascade_validation_call_id
        ),
    }


class AgentLoopLimitError(RuntimeError):
    pass


class RunBudgetExceeded(RuntimeError):
    failure_kind = "resource_interruption"


class RunCancelled(RuntimeError):
    failure_kind = "cancelled"



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


_FailureSignature = tuple[str, str, str]
"""What the stall detector counts: tool name, error code, and offenders.

The third slot is `ToolInputError.subject` when the check that refused the call
could identify *what* was wrong, and `""` otherwise. Without it the signature
cannot tell "the same mistake on a new item" from "the same mistake again", and
§7.12 measured the cost of that on real data: across the after condition's
Polynesian seeds the model repaired the item the harness named **21 times out of
21** it was given a turn, and 9 of 13 stalled nodes never once re-sent a call the
harness had rejected. Those nodes were ended for not adapting while adapting.

This does not weaken the rule for a genuine repeat. A model that re-sends the
same payload produces the same offenders and therefore the same signature, which
is why the one node that sent a byte-identical call three times still stalls —
pinned by `test_a_model_repeating_itself_still_stalls`.
"""

_SUCCESS_SIGNATURE: _FailureSignature = ("", "<success>", "")
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

Read-only evidence, and nothing else. A `test_sound_law`, `test_rule_cascade`, or
`test_proto_assembly` result carries the validation ID a commit is checked
against, `segment_morphemes` and `realign` carry overlay IDs, and a
`commit_reconstruction` result ends the session: none of those are re-derivable
from a later call, so none are eligible however much context they cost.

`test_proto_assembly` is the one to watch, because it is the successor to the
largest observed context consumer in a live run — `test_rule_cascade` at 399 KB
across three calls at one node — and it is ineligible here for exactly the same
reason. What keeps it affordable is not compaction but its *shape*: the part a
commit is checked against is a few hundred bytes, the per-concept evidence is
re-derivable by calling the tool again, and `detail` defaults to omitting the
per-column resolutions. Compaction today is all-or-nothing per tool message, so
that split has to be in the result rather than in the compactor.
"""

PREVIEW_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "test_proto_assembly",
        "test_rule_cascade",
        "test_sound_law",
    }
)
"""Preview tools eligible for watermark-gated stub compaction (R03 §19.4).

Below `compaction_watermark_tokens` (or when it is `None`), preview results are
never rewritten so provider prefix caches remain intact. Once observed prompt
tokens cross the watermark, older accepted previews superseded by a newer
accepted preview of the same tool are replaced in `_MessageLog.prompt` with a
deterministic stub preserving validation/hypothesis handles and outcome counts,
while `_MessageLog.audit` (`trajectories.jsonl`) remains completely uncompacted.
"""

MIN_PREVIEW_COMPACTION_SAVINGS_BYTES: int = 256
"""Minimum positive UTF-8 byte reduction required to stub a superseded preview.

Replacing an empty or micro-sized identity probe (`805 B -> 873 B`) yields negative
or negligible savings while mutating early prompt messages and invalidating hundreds
of thousands of cached prefix tokens.
"""

WATERMARK_COMPACTABLE_READ_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        "summarize_correspondences",
        "get_alignments",
        "search_forms",
    }
)
"""High-volume read-only survey/inspection tools eligible for watermark page stubbing."""

WATERMARK_READ_ONLY_KEEP_LIVE_PER_TOOL: int = 2
"""Newest accepted live pages per high-volume read-only tool kept verbatim above watermark."""

MIN_READ_ONLY_COMPACTION_SAVINGS_BYTES: int = 1024
"""Minimum positive UTF-8 byte reduction required to stub an older read-only page."""

_PAGINATION_ARGUMENT_KEYS: frozenset[str] = frozenset({"offset", "limit"})

_COMPACTABLE_ARGS_MODELS: dict[str, type[WorkbenchModel]] = {
    "get_alignments": GetAlignmentsArgs,
    "summarize_correspondences": SummarizeCorrespondencesArgs,
    "search_forms": SearchFormsArgs,
    "list_concepts": ListConceptsArgs,
    "list_available_nodes": ListAvailableNodesArgs,
    "get_node_reconstruction": GetNodeReconstructionArgs,
    "polarize": PolarizeArgs,
}

_SELECTION_ARGUMENT_KEYS: frozenset[str] = frozenset(
    {"node_ids", "node_id", "concept_ids", "form_ids", "cognate_set_ids"}
)
"""Arguments that name *what* was asked for, rather than how.

These are compared as sets on unpaginated calls, with absent or empty meaning
"everything", so a widening call supersedes a narrower one. On paginated calls,
`[later_offset, later_offset + later_limit]` supersedes
`[earlier_offset, earlier_offset + earlier_limit]` when all non-pagination
arguments match.
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


def _normalize_tool_arguments(
    arguments: Mapping[str, object],
    args_model: type[WorkbenchModel] | None,
) -> dict[str, object]:
    """Populate schema defaults when `arguments` validates against `args_model`."""
    if args_model is None:
        return dict(arguments)
    try:
        validated = args_model.model_validate_json(json.dumps(dict(arguments)))
    except Exception:
        return dict(arguments)
    return validated.model_dump(mode="json")


def _pagination_bounds(arguments: Mapping[str, object]) -> tuple[int, int] | None:
    """Return `(offset, offset + limit)` when valid integer pagination is present."""
    if "limit" not in arguments:
        return None
    raw_offset = arguments.get("offset", 0)
    raw_limit = arguments.get("limit")
    if (
        isinstance(raw_offset, bool)
        or not isinstance(raw_offset, int)
        or raw_offset < 0
        or isinstance(raw_limit, bool)
        or not isinstance(raw_limit, int)
        or raw_limit < 1
    ):
        return None
    return raw_offset, raw_offset + raw_limit


def _supersedes(
    later: dict[str, object],
    earlier: dict[str, object],
    *,
    args_model: type[WorkbenchModel] | None = None,
) -> bool:
    """Does a later call re-request everything an earlier one asked for?

    Deliberately strict. Two calls that overlap without one covering the other —
    concepts 1 and 2, then concepts 3 and 4 — are *not* superseded: the earlier
    result still holds evidence the later one never returned, and dropping it
    would silently take back something the model may still be reasoning from.
    Absent and empty are treated alike for selections, since both mean "no
    filter" across this tool surface. When both calls carry bounded pagination,
    `[later_offset, later_offset + later_limit]` supersedes
    `[earlier_offset, earlier_offset + earlier_limit]` only when all
    non-pagination arguments match.
    """
    norm_later = _normalize_tool_arguments(later, args_model)
    norm_earlier = _normalize_tool_arguments(earlier, args_model)
    later_bounds = _pagination_bounds(norm_later)
    earlier_bounds = _pagination_bounds(norm_earlier)
    paginated = later_bounds is not None and earlier_bounds is not None
    if paginated:
        later_start, later_end = later_bounds
        earlier_start, earlier_end = earlier_bounds
        if not (later_start <= earlier_start and later_end >= earlier_end):
            return False

    keys_to_compare = set(norm_later) | set(norm_earlier)
    if paginated:
        keys_to_compare -= _PAGINATION_ARGUMENT_KEYS

    for key in keys_to_compare:
        if key in _SELECTION_ARGUMENT_KEYS:
            if paginated:
                if (
                    key == "node_ids"
                    and args_model is not None
                    and issubclass(args_model, SummarizeCorrespondencesArgs)
                ):
                    if list(norm_later.get(key) or ()) != list(norm_earlier.get(key) or ()):
                        return False
                elif _selection_values(norm_later.get(key)) != _selection_values(
                    norm_earlier.get(key)
                ):
                    return False
                continue
            later_selection = _selection_values(norm_later.get(key))
            if later_selection is None:
                continue
            earlier_selection = _selection_values(norm_earlier.get(key))
            if earlier_selection is None or not earlier_selection <= later_selection:
                return False
        elif norm_later.get(key) != norm_earlier.get(key):
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


@dataclass(frozen=True)
class _PreviewResultRecord:
    """Where one accepted preview tool result sits while live in the prompt."""

    index: int
    call_id: str
    name: str
    argument_sha256: str
    validation_id: str
    inventory_id: str | None
    executable: bool
    commit_ready: bool | None
    covered_set_count: int | None
    unaccounted_column_rate: float | None
    residue_policy: str | None = None


@dataclass(frozen=True)
class _CompactedPreviewRecord:
    """Preserved handle metadata and stub for an already-compacted preview."""

    call_id: str
    name: str
    argument_sha256: str
    validation_id: str
    inventory_id: str | None
    executable: bool
    commit_ready: bool | None
    covered_set_count: int | None
    unaccounted_column_rate: float | None
    residue_policy: str | None
    superseded_by: str
    stub: dict[str, Any]


def _estimate_prompt_tokens(messages: list[LLMMessage]) -> int:
    """Conservative fallback token estimate (`len(json_bytes) // 3`) when usage omits input_tokens."""
    serialized = json.dumps(
        [message.model_dump(mode="json") for message in messages],
        separators=(",", ":"),
    ).encode("utf-8")
    return len(serialized) // 3


def _extract_preview_record(
    index: int,
    call: LLMToolCall,
    argument_sha256: str,
    payload: Mapping[str, Any],
) -> _PreviewResultRecord:
    validation_id = str(payload.get("validation_call_id") or call.call_id)
    raw_hyp_id = payload.get("hypothesis_id")
    inventory_id = raw_hyp_id if isinstance(raw_hyp_id, str) else None
    if call.name == "test_proto_assembly":
        executable = bool(payload.get("executable", True))
        raw_ready = payload.get("commit_ready")
        commit_ready = raw_ready if isinstance(raw_ready, bool) else None
        covered = payload.get("covered_set_ids")
        covered_set_count = len(covered) if isinstance(covered, (list, tuple)) else 0
        raw_rate = payload.get("unaccounted_column_rate")
        unaccounted_column_rate = (
            float(raw_rate)
            if isinstance(raw_rate, (int, float)) and not isinstance(raw_rate, bool)
            else 0.0
        )
        raw_policy = payload.get("residue_policy")
        residue_policy = str(raw_policy) if raw_policy is not None else None
    else:
        executable = True
        commit_ready = None
        covered_set_count = None
        unaccounted_column_rate = None
        residue_policy = None
    return _PreviewResultRecord(
        index=index,
        call_id=call.call_id,
        name=call.name,
        argument_sha256=argument_sha256,
        validation_id=validation_id,
        inventory_id=inventory_id,
        executable=executable,
        commit_ready=commit_ready,
        covered_set_count=covered_set_count,
        unaccounted_column_rate=unaccounted_column_rate,
        residue_policy=residue_policy,
    )


def _build_preview_compaction_stub(
    record: _PreviewResultRecord,
    superseded_by: str,
) -> dict[str, Any]:
    return {
        "compacted": True,
        "tool": record.name,
        "call_id": record.call_id,
        "argument_sha256": record.argument_sha256,
        "validation_id": record.validation_id,
        "validation_call_id": record.validation_id,
        "inventory_id": record.inventory_id,
        "hypothesis_id": record.inventory_id,
        "executable": record.executable,
        "commit_ready": record.commit_ready,
        "covered_set_count": record.covered_set_count,
        "unaccounted_column_rate": record.unaccounted_column_rate,
        "superseded_by": superseded_by,
        "note": (
            f"The full output of this {record.name} preview was compacted after "
            f"crossing the prompt token watermark because later {record.name} "
            f"call {superseded_by} superseded it. Its validation_id / inventory_id "
            "handles remain valid for commit_reconstruction; do not re-submit "
            "identical arguments."
        ),
    }


def _extract_read_only_summary(
    record: _ToolResultRecord,
    live_content: str,
) -> dict[str, Any]:
    payload: Mapping[str, Any] = {}
    try:
        parsed = json.loads(live_content)
        if isinstance(parsed, Mapping) and isinstance(parsed.get("result"), Mapping):
            payload = parsed["result"]
    except Exception:
        payload = {}

    args = record.arguments
    if record.name == "summarize_correspondences":
        sets = payload.get("sets")
        set_list = sets if isinstance(sets, list) else ()
        summary: dict[str, Any] = {
            "reading": payload.get("reading") or args.get("reading", "recurrence"),
            "offset": args.get("offset", 0),
            "limit": args.get("limit", 30),
            "min_support": payload.get("min_support", args.get("min_support", 2)),
            "total_set_count": payload.get("total_set_count"),
            "matched_set_count": payload.get("matched_set_count"),
            "suppressed_below_min_support": payload.get(
                "suppressed_below_min_support"
            ),
            "returned_set_count": len(set_list),
            "next_offset": payload.get("next_offset"),
            "first_set_ids": [
                item["set_id"]
                for item in set_list[:5]
                if isinstance(item, Mapping) and isinstance(item.get("set_id"), str)
            ],
        }
        if "min_attested_children" in args:
            summary["min_attested_children"] = args["min_attested_children"]
        if args.get("segment") is not None:
            summary["segment"] = args.get("segment")
        return summary

    if record.name == "get_alignments":
        alignment_map = payload.get("alignment_map")
        amap = alignment_map if isinstance(alignment_map, Mapping) else {}
        alignments = amap.get("alignments")
        align_list = alignments if isinstance(alignments, list) else ()
        concept_ids = sorted(
            {
                item["concept_id"]
                for item in align_list
                if isinstance(item, Mapping)
                and isinstance(item.get("concept_id"), str)
            }
        ) or list(args.get("concept_ids") or ())
        return {
            "detail": amap.get("detail") or args.get("detail", "summary"),
            "node_ids": list(amap.get("variety_ids") or args.get("node_ids") or ()),
            "concept_ids": concept_ids,
            "alignment_count": len(align_list),
            "segmentation_overlay_id": payload.get("segmentation_overlay_id"),
        }

    if record.name == "search_forms":
        hits = payload.get("hits")
        hit_list = hits if isinstance(hits, list) else ()
        raw_offset = args.get("offset", 0)
        offset = (
            raw_offset
            if isinstance(raw_offset, int) and not isinstance(raw_offset, bool)
            else 0
        )
        next_offset = payload.get("next_offset")
        total_matches = offset + len(hit_list) if next_offset is None else None
        return {
            "scope": args.get("scope", "active_children"),
            "offset": offset,
            "limit": args.get("limit", 50),
            "hit_count": len(hit_list),
            "total_matches": total_matches,
            "next_offset": next_offset,
        }

    return {"arguments": dict(args)}


def _build_read_only_compaction_stub(
    record: _ToolResultRecord,
    live_content: str,
    argument_sha256: str,
) -> dict[str, Any]:
    return {
        "ok": True,
        "compacted": True,
        "compaction_kind": "watermark_read_only_page",
        "tool": record.name,
        "call_id": record.call_id,
        "argument_sha256": argument_sha256,
        "summary": _extract_read_only_summary(record, live_content),
        "note": (
            "Earlier read-only inspection page compacted above context watermark; "
            "re-issue the tool call if exact rows are needed again."
        ),
    }


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
    # Fixed when the session starts so journaled effort can be matched with
    # the trajectory that eventually records it (or found to have none).
    trajectory_id: str = field(default_factory=lambda: f"trajectory-{uuid.uuid4()}")
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
    # Parallel to `recent_call_signatures`, one flag per slot: True when that
    # call was a protocol rejection that showed measurable repair. §7.14 is why.
    recent_repairs: deque[bool] = field(default_factory=deque)
    # Fewest offenders any rejection of each (tool, code) has yet named. The
    # next one is repair only if it goes below this, which is what stops a
    # sawtooth from buying turns forever.
    best_offender_count: dict[tuple[str, str], int] = field(default_factory=dict)
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
    live_preview_results: list[_PreviewResultRecord] = field(default_factory=list)
    compacted_previews: dict[tuple[str, str], _CompactedPreviewRecord] = field(
        default_factory=dict
    )
    compacted_tool_results: int = 0
    compacted_preview_results: int = 0
    compacted_read_only_results: int = 0
    watermark_trigger_count: int = 0
    repeat_guard_hits: int = 0
    latest_prompt_tokens: int = 0
    peak_prompt_tokens: int = 0
    last_response_had_input_tokens: bool = False
    pending_audit_message: LLMMessage | None = None
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
        max_retries: int = 6,
        retry_backoff_seconds: float = 10.0,
        max_retry_seconds: float = 300.0,
        retry_max_delay_seconds: float = 60.0,
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
        compaction_watermark_tokens: int | None = None,
        instructions: str | None = None,
        trajectory_sink: TrajectorySink | None = None,
        event_sink: AgentEventSink | None = None,
        run_id: str | None = None,
        configuration_sha256: str | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        clock_fn: Callable[[], float] = time.monotonic,
        jitter_fn: Callable[[float], float] = lambda _: 0.0,
        cancelled_fn: Callable[[], bool] = lambda: False,
        request_journal: RequestJournal | None = None,
    ) -> None:
        if max_turns < 1 or max_tool_calls < 1:
            raise ValueError("agent loop limits must be positive")
        if max_retries < 0 or not math.isfinite(retry_backoff_seconds) or retry_backoff_seconds < 0:
            raise ValueError("retry controls must be finite and non-negative")
        if any(not math.isfinite(v) or v <= 0 for v in (max_retry_seconds, retry_max_delay_seconds)):
            raise ValueError("retry time bounds must be finite and positive")
        if max_total_turns is not None and max_total_turns < 1:
            raise ValueError("max_total_turns must be positive")
        if max_total_tool_calls is not None and max_total_tool_calls < 1:
            raise ValueError("max_total_tool_calls must be positive")
        if max_run_seconds is not None and (not math.isfinite(max_run_seconds) or max_run_seconds <= 0):
            raise ValueError("max_run_seconds must be positive")
        if max_total_cost_usd is not None and (not math.isfinite(max_total_cost_usd) or max_total_cost_usd <= 0):
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
        if (
            compaction_watermark_tokens is not None
            and (
                isinstance(compaction_watermark_tokens, bool)
                or compaction_watermark_tokens < 1
            )
        ):
            raise ValueError("compaction_watermark_tokens must be positive")
        self.provider = provider
        self.registry = registry or default_tool_registry()
        self.max_turns = max_turns
        self.max_tool_calls = max_tool_calls
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.max_retry_seconds = max_retry_seconds
        self.retry_max_delay_seconds = retry_max_delay_seconds
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
        self.compaction_watermark_tokens = compaction_watermark_tokens
        self.instructions = instructions or load_agent_instructions()
        self.trajectory_sink = trajectory_sink
        self.event_sink = event_sink
        self.run_id = run_id or f"run-{uuid.uuid4()}"
        self.sleep_fn = sleep_fn
        self.clock_fn = clock_fn
        self.jitter_fn = jitter_fn
        self.cancelled_fn = cancelled_fn
        self.request_journal = request_journal
        self._run_started = self.clock_fn()
        self._total_turns = 0
        self._total_tool_calls = 0
        self._total_cost_usd = 0.0
        self._responses_without_cost = 0
        self._usage_history_complete = True
        # True while turn/tool-call totals cover all counted effort, even when
        # history is otherwise incomplete (journal-recovered abrupt loss).
        self._effort_counts_known = True
        self._unrecorded_requests = 0
        self._trajectory_starts: dict[str, float] = {}
        self._node_compaction: dict[str, dict[str, Any]] = {}
        public_configuration = {
            "provider_adapter": type(provider).__name__,
            "model_id": getattr(provider, "model", None),
            "max_turns": max_turns,
            "max_tool_calls": max_tool_calls,
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
        if compaction_watermark_tokens is not None:
            public_configuration["compaction_watermark_tokens"] = (
                compaction_watermark_tokens
            )
        self.configuration_sha256 = (
            configuration_sha256 or _sha256_json(public_configuration)
        )

    def compaction_summary(self) -> dict[str, Any]:
        """Per-node and cumulative watermark compaction statistics for run_summary.json."""
        nodes = self._node_compaction
        return {
            "compaction_watermark_tokens": self.compaction_watermark_tokens,
            "watermark_trigger_count": sum(
                int(item.get("watermark_trigger_count", 0))
                for item in nodes.values()
            ),
            "compacted_preview_results": sum(
                int(item.get("compacted_preview_results", 0))
                for item in nodes.values()
            ),
            "compacted_read_only_results": sum(
                int(item.get("compacted_read_only_results", 0))
                for item in nodes.values()
            ),
            "compacted_tool_results": sum(
                int(item.get("compacted_tool_results", 0))
                for item in nodes.values()
            ),
            "repeat_guard_hits": sum(
                int(item.get("repeat_guard_hits", 0))
                for item in nodes.values()
            ),
            "peak_prompt_tokens": (
                max(
                    (
                        int(item["peak_prompt_tokens"])
                        for item in nodes.values()
                        if item.get("peak_prompt_tokens") is not None
                    ),
                    default=0,
                )
            ),
            "per_node": {
                node_id: dict(item) for node_id, item in sorted(nodes.items())
            },
        }

    def restore_compaction_summary(
        self,
        saved: Mapping[str, Any] | None,
        *,
        keep_node_ids: Iterable[str] | None = None,
    ) -> None:
        """Restore checkpointed nodes' compaction counters across `--resume`."""
        if not saved:
            return
        per_node = saved.get("per_node")
        if not isinstance(per_node, Mapping):
            return
        allowed = set(keep_node_ids) if keep_node_ids is not None else None
        for node_id, entry in per_node.items():
            if not isinstance(node_id, str) or not isinstance(entry, Mapping):
                continue
            if allowed is not None and node_id not in allowed:
                continue
            self._node_compaction[node_id] = dict(entry)

    def usage_snapshot(self) -> dict[str, int | float]:
        return {
            "turns": self._total_turns, "tool_calls": self._total_tool_calls,
            "reported_cost_usd": self._total_cost_usd,
            "responses_without_cost": self._responses_without_cost,
            "elapsed_seconds": max(0.0, self.clock_fn() - self._run_started),
            "history_complete": self._usage_history_complete,
            "effort_counts_known": self._effort_counts_known,
            "unrecorded_requests": self._unrecorded_requests,
            "usage_accounting_version": USAGE_ACCOUNTING_VERSION,
        }

    def restore_usage(self, usage: dict) -> None:
        """Restore the same seed's cumulative caps without replaying requests."""
        for key in USAGE_TOTALS:
            value = usage.get(key, 0)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"invalid recorded run usage: {key}")
        complete = bool(usage.get("history_complete", True))
        # Records from before the journal carry only `history_complete`, and
        # for them incomplete history meant unknown counts.
        self._effort_counts_known = bool(usage.get("effort_counts_known", complete))
        # Unknown counts are incomplete history, whatever the record says.
        self._usage_history_complete = complete and self._effort_counts_known
        self._unrecorded_requests = int(usage.get("unrecorded_requests", 0))
        self._total_turns = int(usage.get("turns", 0))
        self._total_tool_calls = int(usage.get("tool_calls", 0))
        self._total_cost_usd = float(usage.get("reported_cost_usd", 0.0))
        self._responses_without_cost = int(usage.get("responses_without_cost", 0))
        self._run_started -= float(usage.get("elapsed_seconds", 0.0))

    def _journal(self, event: str, node_id: str, state: _RunState, **fields: object) -> None:
        """Record effort before it starts; the effort must not start otherwise."""
        if self.request_journal is None:
            return
        try:
            self.request_journal.record(event, node_id=node_id, trajectory_id=state.trajectory_id, **fields)
        except RequestJournalError:
            raise
        except Exception as error:
            raise RequestJournalError(
                f"request journal unwritable, so effort cannot be recorded before it starts: {error}"
            ) from error

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

    def _check_usage_history(self) -> None:
        """Refuse caps whose quantity is unknown after lost effort."""
        if not self._effort_counts_known and any(v is not None for v in (
            self.max_run_seconds, self.max_total_turns, self.max_total_tool_calls, self.max_total_cost_usd,
        )):
            raise RunBudgetExceeded("run usage history unavailable; cannot enforce cumulative caps")
        if not self._usage_history_complete and self.max_run_seconds is not None:
            raise RunBudgetExceeded(
                "run usage history incomplete: active time of effort lost to an abrupt "
                f"exit ({self._unrecorded_requests} unrecorded provider request(s)) is unknown; "
                "cannot enforce the run time limit. Caps are part of the resume "
                "configuration, so start a fresh run (new checkpoint and run ID) "
                "with a limit reduced by your own estimate of the lost time"
            )

    def _check_run_budget(self) -> None:
        if self.cancelled_fn():
            raise RunCancelled("run cancelled")
        self._check_usage_history()
        if self.max_total_cost_usd is not None and self._responses_without_cost:
            if self._unrecorded_requests:
                raise RunBudgetExceeded(
                    "provider cost unavailable; cannot enforce the run cost cap: "
                    f"{self._responses_without_cost} request(s) have no recorded cost, and "
                    f"{self._unrecorded_requests} request(s) were lost to an abrupt exit, so "
                    "their spend is unknown. Caps are part of the resume configuration, "
                    "so start a fresh run (new checkpoint and run ID) with a cap "
                    "reduced by the provider-reported spend of the lost requests"
                )
            raise RunBudgetExceeded("provider cost unavailable; cannot enforce the run cost cap")
        if (
            self.max_run_seconds is not None
            and self.clock_fn() - self._run_started >= self.max_run_seconds
        ):
            raise RunBudgetExceeded("run exceeded its wall-clock time limit")
        if (
            self.max_total_cost_usd is not None
            and self._total_cost_usd >= self.max_total_cost_usd
        ):
            raise RunBudgetExceeded("run exceeded its reported provider cost limit")

    def _wait_for_retry(self, delay: float, *, deadline: float, error: ProviderError) -> None:
        # Poll cancellation and caps during backoff, even with a long Retry-After.
        remaining = delay
        while remaining > 0:
            self._check_run_budget()
            if self.clock_fn() >= deadline:
                error.stop_reason = "retry_elapsed_limit"
                raise error
            interval = min(remaining, 0.25)
            self.sleep_fn(interval)
            remaining -= interval
        self._check_run_budget()

    def _complete_with_retry(
        self,
        node_id: str,
        messages: list[LLMMessage],
        state: _RunState,
        *,
        tool_choice: str = "auto",
    ) -> ProviderResponse:
        definitions = self.registry.definitions()
        request_started = self.clock_fn()
        last_error = None
        for retry_index in range(self.max_retries + 1):
            self._check_run_budget()
            if last_error is not None and self.clock_fn() - request_started >= self.max_retry_seconds:
                last_error.stop_reason = "retry_elapsed_limit"
                raise last_error
            state.provider_attempts += 1
            self._journal("request_start", node_id, state, attempt=state.provider_attempts)
            attempt_started = self.clock_fn()
            try:
                try:
                    request_options = {"tool_choice": tool_choice,
                                       "max_tokens_override": state.effective_max_tokens}
                    if getattr(self.provider, "supports_timeout_override", False):
                        remaining = self.max_retry_seconds - (self.clock_fn() - request_started)
                        if self.max_run_seconds is not None:
                            remaining = min(remaining, self.max_run_seconds - (self.clock_fn() - self._run_started))
                        request_options["timeout_override"] = max(0.001, remaining)
                    raw_response = self.provider.complete(messages, definitions, **request_options)
                except (TimeoutError, ConnectionError) as error:
                    raise normalized_provider_error(error) from error
                except ProviderError:
                    raise
                except (Exception, KeyboardInterrupt):
                    # The request may have been sent, and nothing prices it:
                    # its spend is unknown, as for a request lost to an abrupt
                    # exit, not zero.
                    self._responses_without_cost += 1
                    self._journal(
                        "request_end", node_id, state, attempt=state.provider_attempts,
                        outcome="abandoned", duration_seconds=max(0.0, self.clock_fn() - attempt_started),
                    )
                    raise
                response = (raw_response if isinstance(raw_response, ProviderResponse)
                            else ProviderResponse(message=raw_response))
                state.provider_responses.append(response.metadata)
                usage = response.metadata.usage
                if usage is not None and usage.input_tokens is not None:
                    state.last_response_had_input_tokens = True
                    state.latest_prompt_tokens = usage.input_tokens
                else:
                    state.last_response_had_input_tokens = False
                    state.latest_prompt_tokens = _estimate_prompt_tokens(messages)
                state.peak_prompt_tokens = max(
                    state.peak_prompt_tokens, state.latest_prompt_tokens
                )
                if response.message.role is MessageRole.ASSISTANT:
                    state.pending_audit_message = response.message
                self._journal(
                    "request_end", node_id, state, attempt=state.provider_attempts, outcome="response",
                    duration_seconds=max(0.0, self.clock_fn() - attempt_started),
                    cost_usd=usage.cost_usd if usage is not None else None,
                    input_tokens=usage.input_tokens if usage is not None else None,
                    output_tokens=usage.output_tokens if usage is not None else None,
                    total_tokens=usage.total_tokens if usage is not None else None,
                )
                if usage is not None and usage.cost_usd is not None:
                    self._total_cost_usd += usage.cost_usd
                else:
                    self._responses_without_cost += 1
                    if self.max_total_cost_usd is not None:
                        raise RunBudgetExceeded("provider cost unavailable; cannot enforce the run cost cap")
                self._check_run_budget()
                return response
            except ProviderError as error:
                last_error = error
                metadata = error.metadata
                self._journal(
                    "request_end", node_id, state, attempt=state.provider_attempts, outcome="error",
                    duration_seconds=max(0.0, self.clock_fn() - attempt_started),
                    response_state=metadata.response_state, retryable=metadata.retryable,
                )
                if metadata.response_state == "unknown" and not metadata.retryable:
                    self._responses_without_cost += 1
                elapsed = max(0.0, self.clock_fn() - request_started)
                remaining = self.max_retry_seconds - elapsed
                if self.max_run_seconds is not None:
                    remaining = min(remaining, self.max_run_seconds -
                                    (self.clock_fn() - self._run_started))
                base = min(self.retry_max_delay_seconds,
                           self.retry_backoff_seconds * (2 ** min(retry_index, 32)))
                jitter = self.jitter_fn(base)
                if not math.isfinite(jitter) or jitter < 0:
                    raise ValueError("retry jitter must be finite and non-negative")
                delay = max(min(self.retry_max_delay_seconds, base + jitter),
                            metadata.retry_after_seconds or 0.0)
                reason = ("not_retryable" if not metadata.retryable else
                          "attempt_limit" if retry_index >= self.max_retries else
                          "retry_elapsed_limit" if remaining <= 0 else
                          ("retry_after_exceeds_budget" if metadata.retry_after_seconds is not None else "backoff_exceeds_budget") if delay >= remaining else None)
                if reason is not None:
                    error.stop_reason = reason
                    raise
                self._emit(
                    AgentEventKind.PROVIDER_RETRY, node_id,
                    f"provider request rejected; retrying in {delay:g}s",
                    retry_index=retry_index + 1, max_retries=self.max_retries,
                    delay_seconds=delay, elapsed_seconds=elapsed,
                    remaining_seconds=remaining,
                    provider_failure=metadata.model_dump(mode="json"),
                )
                self._wait_for_retry(delay, deadline=request_started + self.max_retry_seconds, error=error)
                state.retry_count += 1
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
        except (ProviderError, RunBudgetExceeded, RunCancelled):
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

    def _is_repair(
        self,
        state: _RunState,
        tool_name: str,
        code: str,
        error: ToolError | None,
    ) -> bool:
        """Did this rejection name fewer offenders than the last one like it?

        The window rule counts protocol rejections and cannot see that the model
        is fixing them. §7.14 measured what that costs: at one node the model
        was told about 13 bad rows, repaired all 13 in a single turn, reached an
        accepted preview, and was ended anyway because the window was full.

        So a rejection that shows measurable repair no longer counts toward
        saturation. Repair is a **strict decrease below the fewest offenders
        this `(tool, code)` has ever named** — the best so far, not the last.

        **Best-so-far rather than last is what makes the rule safe, and a test
        found it.** Compared against the last count, a model alternating 9, 8,
        9, 8 marks every second rejection a repair, and half a window of
        repairs never saturates: the model buys turns forever by re-breaking a
        row it just fixed. Against the best so far, the second 8 is not below
        8, so only genuine new ground counts.

        **It cannot be exploited to run forever.** The best-so-far count is a
        non-negative integer that only ever decreases, so a node has at most as
        many repairs as its first rejection had offenders, and then it either
        commits or saturates. A model that never improves is refused exactly as
        it is today, and nothing here touches the repeated-signature rule.

        Checks that cannot count their offenders report `None` and are
        unchanged: a schema rejection is never a repair.
        """
        count = getattr(error, "offender_count", None) if error is not None else None
        key = (tool_name, code)
        if count is None:
            # No signal. Leave any earlier count in place: a schema slip between
            # two mismatch rejections must not erase the progress between them.
            return False
        best = state.best_offender_count.get(key)
        if best is None:
            state.best_offender_count[key] = count
            return False
        if count < best:
            state.best_offender_count[key] = count
            return True
        return False

    def _record_call_signature(
        self,
        state: _RunState,
        signature: _FailureSignature,
        repair: bool = False,
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
        state.recent_repairs.append(repair)
        while len(window) > self.stall_window_calls:
            window.popleft()
        while len(state.recent_repairs) > self.stall_window_calls:
            state.recent_repairs.popleft()
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
        subject = getattr(error, "subject", None) if error is not None else None
        signature = (call.name, code, subject or "")
        repair = self._is_repair(state, call.name, code, error)
        occurrences = self._record_call_signature(state, signature, repair)
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
            and not repaired
            for entry, repaired in zip(
                state.recent_call_signatures, state.recent_repairs
            )
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
        spec = getattr(self.registry, "_tools", {}).get(call.name)
        args_model = (
            getattr(spec, "args_model", None)
            or _COMPACTABLE_ARGS_MODELS.get(call.name)
        )
        superseded = [
            record
            for record in state.live_tool_results
            if record.name == call.name
            and record.call_id != call.call_id
            and _supersedes(call.arguments, record.arguments, args_model=args_model)
        ]
        for record in superseded:
            messages.replace_prompt_content(
                record.index,
                _compaction_placeholder(record.name, record.call_id, call.call_id),
            )
            state.live_tool_results.remove(record)
            state.compacted_tool_results += 1
            state.compacted_read_only_results += 1
            self._emit(
                AgentEventKind.CONTEXT_COMPACTION,
                context.node_id,
                f"dropped a superseded {record.name} result from the prompt",
                tool_name=record.name,
                call_id=record.call_id,
                superseded_by=call.call_id,
                compacted_tool_results=state.compacted_tool_results,
            )

    def _compact_watermark_previews(
        self,
        context: AgentContext,
        state: _RunState,
        messages: _MessageLog,
        *,
        record_trigger: bool = True,
    ) -> int:
        """Compact older superseded preview results once observed prompt tokens cross the watermark."""
        if (
            not self.compact_superseded_tool_results
            or self.compaction_watermark_tokens is None
            or state.latest_prompt_tokens < self.compaction_watermark_tokens
        ):
            return 0
        newest_by_tool: dict[str, _PreviewResultRecord] = {}
        for record in state.live_preview_results:
            newest_by_tool[record.name] = record
        candidates = [
            record
            for record in state.live_preview_results
            if newest_by_tool[record.name].call_id != record.call_id
        ]
        eligible: list[tuple[_PreviewResultRecord, str, dict[str, Any], str]] = []
        for record in candidates:
            superseded_by = newest_by_tool[record.name].call_id
            stub = _build_preview_compaction_stub(record, superseded_by)
            stub_json = json.dumps(stub)
            live_content = messages.prompt[record.index].content or ""
            live_bytes = len(live_content.encode("utf-8"))
            stub_bytes = len(stub_json.encode("utf-8"))
            if live_bytes - stub_bytes >= MIN_PREVIEW_COMPACTION_SAVINGS_BYTES:
                eligible.append((record, superseded_by, stub, stub_json))
        if not eligible:
            return 0
        if record_trigger:
            state.watermark_trigger_count += 1
        for record, superseded_by, stub, stub_json in eligible:
            messages.replace_prompt_content(record.index, stub_json)
            state.live_preview_results.remove(record)
            state.compacted_previews[(record.name, record.argument_sha256)] = (
                _CompactedPreviewRecord(
                    call_id=record.call_id,
                    name=record.name,
                    argument_sha256=record.argument_sha256,
                    validation_id=record.validation_id,
                    inventory_id=record.inventory_id,
                    executable=record.executable,
                    commit_ready=record.commit_ready,
                    covered_set_count=record.covered_set_count,
                    unaccounted_column_rate=record.unaccounted_column_rate,
                    residue_policy=record.residue_policy,
                    superseded_by=superseded_by,
                    stub=stub,
                )
            )
            state.compacted_tool_results += 1
            state.compacted_preview_results += 1
            self._emit(
                AgentEventKind.CONTEXT_COMPACTION,
                context.node_id,
                f"compacted superseded {record.name} preview above token watermark",
                action="watermark_preview_compaction",
                tool_name=record.name,
                call_id=record.call_id,
                argument_sha256=record.argument_sha256,
                validation_id=record.validation_id,
                inventory_id=record.inventory_id,
                superseded_by=superseded_by,
                observed_prompt_tokens=state.latest_prompt_tokens,
                compaction_watermark_tokens=self.compaction_watermark_tokens,
                compacted_tool_results=state.compacted_tool_results,
                compacted_preview_results=state.compacted_preview_results,
            )
        return len(eligible)

    def _compact_watermark_read_only(
        self,
        context: AgentContext,
        state: _RunState,
        messages: _MessageLog,
        *,
        record_trigger: bool = True,
    ) -> int:
        """Compact 3rd-newest and older high-volume read-only pages once prompt tokens cross the watermark."""
        if (
            not self.compact_superseded_tool_results
            or self.compaction_watermark_tokens is None
            or state.latest_prompt_tokens < self.compaction_watermark_tokens
        ):
            return 0
        by_tool: dict[str, list[_ToolResultRecord]] = {}
        for record in state.live_tool_results:
            if record.name in WATERMARK_COMPACTABLE_READ_ONLY_TOOLS:
                by_tool.setdefault(record.name, []).append(record)
        older_call_ids: set[str] = set()
        for records in by_tool.values():
            if len(records) > WATERMARK_READ_ONLY_KEEP_LIVE_PER_TOOL:
                for record in records[:-WATERMARK_READ_ONLY_KEEP_LIVE_PER_TOOL]:
                    older_call_ids.add(record.call_id)
        if not older_call_ids:
            return 0
        eligible: list[tuple[_ToolResultRecord, str, str, int]] = []
        for record in state.live_tool_results:
            if record.call_id not in older_call_ids:
                continue
            live_content = messages.prompt[record.index].content or ""
            arg_sha = _sha256_json(record.arguments)
            stub = _build_read_only_compaction_stub(record, live_content, arg_sha)
            stub_json = json.dumps(stub)
            live_bytes = len(live_content.encode("utf-8"))
            stub_bytes = len(stub_json.encode("utf-8"))
            saved_bytes = live_bytes - stub_bytes
            if saved_bytes >= MIN_READ_ONLY_COMPACTION_SAVINGS_BYTES:
                eligible.append((record, arg_sha, stub_json, saved_bytes))
        if not eligible:
            return 0
        if record_trigger:
            state.watermark_trigger_count += 1
        for record, arg_sha, stub_json, saved_bytes in eligible:
            messages.replace_prompt_content(record.index, stub_json)
            state.live_tool_results.remove(record)
            state.compacted_tool_results += 1
            state.compacted_read_only_results += 1
            self._emit(
                AgentEventKind.CONTEXT_COMPACTION,
                context.node_id,
                f"compacted older {record.name} read-only page above token watermark",
                action="watermark_read_only_compaction",
                tool_name=record.name,
                call_id=record.call_id,
                argument_sha256=arg_sha,
                saved_bytes=saved_bytes,
                observed_prompt_tokens=state.latest_prompt_tokens,
                compaction_watermark_tokens=self.compaction_watermark_tokens,
                compacted_tool_results=state.compacted_tool_results,
                compacted_read_only_results=state.compacted_read_only_results,
            )
        return len(eligible)

    def _compact_above_watermark(
        self,
        context: AgentContext,
        state: _RunState,
        messages: _MessageLog,
    ) -> None:
        """Run watermark-gated preview and read-only page compaction, counting one trigger if either fires."""
        compacted_previews = self._compact_watermark_previews(
            context, state, messages, record_trigger=False
        )
        compacted_read_only = self._compact_watermark_read_only(
            context, state, messages, record_trigger=False
        )
        if compacted_previews or compacted_read_only:
            state.watermark_trigger_count += 1

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
            else self.clock_fn() - state.started_monotonic
        )
        commit = context.commit
        # `committed_rule_count` counts committed *claims*: rules under the
        # branch-cascade protocol, correspondence sets under the per-set one.
        # See `AgentNodeMetrics.committed_rule_count` for why the field name is
        # kept.
        if commit is None:
            rule_count = 0
        elif isinstance(commit, CommittedProtoInventory):
            rule_count = len(commit.request.commitments)
        else:
            rule_count = len(commit.parsed_rules)
        anomaly_count = len(commit.anomalies) if commit else 0
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
                commit.parsed_rules,
                segmentation_overlay_id=(
                    commit.request.segmentation_overlay_id
                ),
            )
            if isinstance(commit, CommittedReconstruction)
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
            assembly_tests=state.successful_tool_names.count(
                "test_proto_assembly"
            ),
            input_tokens=self._usage_total(
                state.provider_responses, "input_tokens"
            ),
            output_tokens=self._usage_total(
                state.provider_responses, "output_tokens"
            ),
            total_tokens=self._usage_total(
                state.provider_responses, "total_tokens"
            ),
            cached_input_tokens=self._usage_total(
                state.provider_responses, "cached_input_tokens"
            ),
            reasoning_output_tokens=self._usage_total(
                state.provider_responses, "reasoning_output_tokens"
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
                commit is not None
                and rule_count == 0
                and sound_law_tests == 0
                and state.successful_tool_names.count("test_proto_assembly") == 0
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
        failure_kind: str | None = None,
        failure_error_type: str | None = None,
        provider_failure=None,
        interruption_reason: str | None = None,
        write_to_sink: bool = True,
    ) -> AgentTrajectory:
        definitions = self.registry.definitions()
        trajectory_id = state.trajectory_id
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
            schema_version=EVIDENCE_SCHEMA_VERSION,
            initial_payload=payload,
            tool_definitions=definitions,
            messages=tuple(messages),
            provider_responses=tuple(state.provider_responses),
            metrics=self._metrics(context, state),
            committed_reconstruction=context.commit,
            completed=completed,
            failure=failure,
            failure_kind=failure_kind,
            failure_error_type=failure_error_type,
            provider_failure=provider_failure,
            interruption_reason=interruption_reason,
        )
        self._node_compaction[context.node_id] = {
            "watermark_trigger_count": state.watermark_trigger_count,
            "compacted_preview_results": state.compacted_preview_results,
            "compacted_read_only_results": state.compacted_read_only_results,
            "compacted_tool_results": state.compacted_tool_results,
            "repeat_guard_hits": state.repeat_guard_hits,
            "latest_prompt_tokens": state.latest_prompt_tokens,
            "peak_prompt_tokens": state.peak_prompt_tokens,
        }
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

    def emit_correspondence_map_degraded(
        self,
        node_id: str,
        *,
        reason: str,
    ) -> None:
        """Record that a node kept its beam but lost its correspondence report.

        `correspondence_maps` is a report and nothing scores it, so the node is
        not a failure and does not appear in `node_failures`. Without this event
        a degraded run would be indistinguishable from a clean one in the
        timeline, which is the swallow this guard was written to avoid.
        """
        self._emit(
            AgentEventKind.CORRESPONDENCE_MAP_DEGRADED,
            node_id,
            "the aligner refused a group; this node has no correspondence maps",
            reason=reason,
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
            self.clock_fn(),
        )
        metrics = run_result.trajectory.metrics.model_copy(
            update={
                "finished_at": now,
                "duration_seconds": max(0.0, self.clock_fn() - started),
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
                # Each is part of a total above, not additional to it:
                # cached_input of "input", reasoning_output of "output".
                "cached_input": metrics.cached_input_tokens,
                "reasoning_output": metrics.reasoning_output_tokens,
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
            started_monotonic=self.clock_fn(),
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
                # Unknown history outranks a count that only looks exhausted.
                self._check_usage_history()
                if (
                    self.max_total_turns is not None
                    and self._total_turns >= self.max_total_turns
                ):
                    raise RunBudgetExceeded(
                        "run exceeded its total model-turn limit"
                    )
                self._total_turns += 1
                state.turn_count = turn_index
                self._journal("turn", context.node_id, state, turn=turn_index)
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
                    state.pending_audit_message = None
                    raise ValueError(
                        "LLM providers must return an assistant message"
                    )
                messages.append(reply)
                state.pending_audit_message = None
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
                    if not state.last_response_had_input_tokens:
                        state.latest_prompt_tokens = _estimate_prompt_tokens(
                            messages.prompt
                        )
                        state.peak_prompt_tokens = max(
                            state.peak_prompt_tokens, state.latest_prompt_tokens
                        )
                    self._compact_above_watermark(context, state, messages)
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
                    self._journal("tool_call", context.node_id, state, call_id=call.call_id)
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
                    repeat_hit = False
                    arg_sha = (
                        _sha256_json(call.arguments)
                        if call.name in PREVIEW_TOOL_NAMES
                        else ""
                    )
                    prior_compacted = (
                        state.compacted_previews.get((call.name, arg_sha))
                        if call.name in PREVIEW_TOOL_NAMES
                        else None
                    )
                    if prior_compacted is not None:
                        repeat_hit = True
                        state.repeat_guard_hits += 1
                        if (
                            call.name == "test_proto_assembly"
                            and prior_compacted.call_id in context.assembly_validations
                        ):
                            context.assembly_validations[call.call_id] = (
                                context.assembly_validations[prior_compacted.call_id]
                            )
                        elif (
                            call.name == "test_rule_cascade"
                            and prior_compacted.call_id in context.cascade_validations
                        ):
                            context.cascade_validations[call.call_id] = (
                                context.cascade_validations[prior_compacted.call_id]
                            )
                        elif (
                            call.name == "test_sound_law"
                            and prior_compacted.call_id in context.validations
                        ):
                            context.validations[call.call_id] = (
                                context.validations[prior_compacted.call_id]
                            )
                        result = ToolExecutionResult(
                            ok=True,
                            result={
                                "repeat_guard": True,
                                "tool": call.name,
                                "call_id": call.call_id,
                                "identical_to_call_id": prior_compacted.call_id,
                                "argument_sha256": arg_sha,
                                "validation_id": prior_compacted.validation_id,
                                "validation_call_id": prior_compacted.validation_id,
                                "inventory_id": prior_compacted.inventory_id,
                                "hypothesis_id": prior_compacted.inventory_id,
                                "executable": prior_compacted.executable,
                                "commit_ready": prior_compacted.commit_ready,
                                "covered_set_count": prior_compacted.covered_set_count,
                                "unaccounted_column_rate": (
                                    prior_compacted.unaccounted_column_rate
                                ),
                                "residue_policy": prior_compacted.residue_policy,
                                "preserved_stub": prior_compacted.stub,
                                "note": (
                                    f"Identical to earlier compacted {call.name} "
                                    f"call {prior_compacted.call_id!r} "
                                    f"(argument_sha256={arg_sha}); result unchanged. "
                                    "Its preserved validation_id / inventory_id "
                                    "handles remain valid for commit_reconstruction; "
                                    "modify your hypothesis before previewing again "
                                    "or commit now."
                                ),
                            },
                        )
                        self._emit(
                            AgentEventKind.CONTEXT_COMPACTION,
                            context.node_id,
                            f"blocked duplicate {call.name} preview matching compacted call {prior_compacted.call_id}",
                            action="repeat_preview_guard",
                            tool_name=call.name,
                            call_id=call.call_id,
                            identical_to_call_id=prior_compacted.call_id,
                            argument_sha256=arg_sha,
                            repeat_guard_hits=state.repeat_guard_hits,
                        )
                    else:
                        result = self.registry.execute(call, context)
                    if result.ok:
                        if not repeat_hit:
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
                        elif (
                            not repeat_hit
                            and call.name in PREVIEW_TOOL_NAMES
                            and result.result is not None
                        ):
                            state.live_preview_results.append(
                                _extract_preview_record(
                                    index,
                                    call,
                                    arg_sha,
                                    result.result,
                                )
                            )
                    if context.commit is not None:
                        self._emit(
                            AgentEventKind.NODE_COMMIT,
                            context.node_id,
                            "accepted reconstruction commit",
                            **_commit_event_fields(context.commit),
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
                if not state.last_response_had_input_tokens:
                    state.latest_prompt_tokens = _estimate_prompt_tokens(
                        messages.prompt
                    )
                    state.peak_prompt_tokens = max(
                        state.peak_prompt_tokens, state.latest_prompt_tokens
                    )
                self._compact_above_watermark(context, state, messages)
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
        except (Exception, KeyboardInterrupt) as caught:
            if state.pending_audit_message is not None:
                messages.audit.append(state.pending_audit_message)
                state.pending_audit_message = None
            error = RunCancelled("run cancelled by keyboard interrupt") if isinstance(caught, KeyboardInterrupt) else caught
            interruption = isinstance(error, (ProviderError, RunBudgetExceeded, RunCancelled, RequestJournalError))
            cause = (error.metadata.kind.value if isinstance(error, ProviderError)
                     else getattr(error, "failure_kind", None) or
                     ("model_protocol_failure" if isinstance(error, (AgentLoopLimitError, ProtocolStallError)) else "unknown"))
            reason = error.stop_reason if isinstance(error, ProviderError) else str(error) if interruption else None
            failure = f"{type(error).__name__}: {error}"
            trajectory = self._trajectory(
                context,
                payload,
                messages.audit,
                state,
                completed=False,
                failure=failure,
                failure_kind=cause,
                failure_error_type=type(error).__name__,
                provider_failure=error.metadata if isinstance(error, ProviderError) else None,
                interruption_reason=reason,
            )
            try:
                setattr(error, NODE_TRAJECTORY_ATTRIBUTE, trajectory)
            except AttributeError:
                # An exception type that forbids attributes must still
                # propagate; losing the hand-off is better than masking it.
                pass
            self._emit(
                AgentEventKind.NODE_INTERRUPTED if interruption else AgentEventKind.NODE_FAILED,
                context.node_id,
                "reconstruction node interrupted" if interruption else "reconstruction node failed",
                failure_kind=cause, interruption_reason=reason,
                provider_failure=error.metadata.model_dump(mode="json") if isinstance(error, ProviderError) else None,
                error_type=type(error).__name__,
                error=str(error),
                duration_seconds=self.clock_fn() - state.started_monotonic,
                turn_count=state.turn_count,
                tool_call_count=state.tool_call_count,
                retry_count=state.retry_count,
            )
            raise error
