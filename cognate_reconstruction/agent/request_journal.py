"""Durable record of node-session effort, and how a resume reconciles it.

A finalized trajectory is the run's record of a node session's effort, and the
run summary is the record of the process's totals, but both are written only
when a session or the process ends. A process that dies abruptly (power, OOM
kill, `os._exit`, a BaseException that skips finalization) leaves neither for
the work in flight, so a resume used to read that effort as zero.

The journal is written and fsynced *before* each counted model turn, provider
request and tool call, and after each provider response with what it is known
to have cost. After every run summary the CLI appends a `usage_recorded`
marker. A resume therefore reads the journal in two parts: everything up to the
last marker is covered by the saved summary; after it, a session with a
trajectory is recorded effort and a session without one was lost.
"""
from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable, Mapping, Protocol, Sequence

from cognate_reconstruction.agent.trajectory import AgentTrajectory

REQUEST_JOURNAL_VERSION = "request-journal-v1"

USAGE_RECORDED_EVENT = "usage_recorded"
"""Written after a run summary is durable: earlier records are covered by it."""

USAGE_ACCOUNTING_VERSION = "abrupt-loss-v1"
"""Semantics of the run-summary `usage` record.

`history_complete` is false whenever any effort is unrecorded, including
journaled sessions lost to an abrupt exit. `effort_counts_known` says the
turn/tool-call counts still cover every counted turn and call (the journal
supplies them), so those caps remain enforceable. The elapsed value is then a
lower bound, and requests without a recorded response are counted in
`responses_without_cost`. Records without this key predate the journal.
"""

USAGE_TOTALS = (
    "turns", "tool_calls", "reported_cost_usd", "responses_without_cost",
    "elapsed_seconds", "unrecorded_requests",
)
"""The cumulative quantities a resume restores; all are non-negative."""


class RequestJournalError(RuntimeError):
    """The journal could not be written, so effort cannot be recorded first.

    A run-level stop, like a budget: falling back over it would let every
    remaining node fail the same way and report the run as completed.
    """

    failure_kind = "request_journal_failure"


class RequestJournal(Protocol):
    def record(self, event: str, **fields: object) -> None: ...


class JsonlRequestJournal:
    """Durable, append-only request journal for one run."""

    def __init__(self, path: str | Path, *, run_id: str, configuration_sha256: str) -> None:
        self.path = Path(path)
        self.run_id = run_id
        self.configuration_sha256 = configuration_sha256
        self._tail_checked = False

    def record(self, event: str, **fields: object) -> None:
        record = {
            "journal_version": REQUEST_JOURNAL_VERSION, "event": event,
            "run_id": self.run_id, "configuration_sha256": self.configuration_sha256,
            "recorded_at": datetime.now(UTC).isoformat(), "pid": os.getpid(), **fields,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self._tail_checked:
            self._drop_torn_tail()
            self._tail_checked = True
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _drop_torn_tail(self) -> None:
        """Remove an unterminated last record left by an interrupted write.

        The reader ignores such a record (see `read_request_journal`).
        Appending after it would join it to the next record, and the joined
        line would be read as corruption by every later resume.
        """
        try:
            handle = self.path.open("r+b")
        except FileNotFoundError:
            return
        with handle:
            content = handle.read()
            if not content or content.endswith(b"\n"):
                return
            handle.truncate(content.rfind(b"\n") + 1)
            handle.flush()
            os.fsync(handle.fileno())


def request_journal_path(checkpoint_path: str | Path) -> Path:
    return Path(checkpoint_path).expanduser().with_suffix(".requests.jsonl")


def read_request_journal(path: Path, run_id: str, configuration_sha256: str) -> list[dict] | None:
    """Journal records for this run, or None when no journal exists.

    Only an unparsable *final* line is tolerated. Each record is fsynced before
    the effort it describes starts, so a torn last write described effort that
    never began, or a response whose loss leaves its request without a
    recorded cost (counted as unknown).
    """
    if not path.exists():
        return None
    lines = path.read_text(encoding="utf-8").splitlines()
    records = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError("record is not an object")
        except ValueError as error:
            if index == len(lines) - 1:
                print(f"warning: ignoring a torn final record in {path}", file=sys.stderr)
                continue
            raise ValueError(f"corrupt request journal {path} line {index + 1}: {error}") from error
        if record.get("run_id") == run_id and record.get("configuration_sha256") == configuration_sha256:
            records.append(record)
    return records


@dataclass(frozen=True)
class UnrecordedEffort:
    """Effort journaled for node sessions that never produced a trajectory.

    Turns, tool calls and requests are exact: each is journaled before it
    happens. Cost is known only for requests with a recorded response; any
    other request is in `responses_without_cost`. Elapsed is a lower bound,
    because the lost process's time after its last record is unknown.
    """

    turns: int = 0
    tool_calls: int = 0
    requests: int = 0
    reported_cost_usd: float = 0.0
    responses_without_cost: int = 0
    elapsed_seconds: float = 0.0

    @property
    def empty(self) -> bool:
        return not (self.turns or self.tool_calls or self.requests)

    def as_usage(self) -> dict[str, int | float]:
        return {
            "turns": self.turns, "tool_calls": self.tool_calls,
            "reported_cost_usd": self.reported_cost_usd,
            "responses_without_cost": self.responses_without_cost,
            "elapsed_seconds": self.elapsed_seconds, "unrecorded_requests": self.requests,
        }


@dataclass(frozen=True)
class JournalTail:
    """The journal after its last `usage_recorded` marker."""

    summary_recorded: bool
    """A marker exists, so a saved run summary covers the records before it."""
    trajectory_ids: frozenset[str]
    """Sessions journaled after the marker, recorded or not."""
    unrecorded: UnrecordedEffort


def journal_tail(records: Sequence[Mapping], recorded_trajectory_ids: set[str]) -> JournalTail:
    markers = [index for index, record in enumerate(records) if record.get("event") == USAGE_RECORDED_EVENT]
    tail = records[markers[-1] + 1:] if markers else records
    trajectory_ids = {record["trajectory_id"] for record in tail if isinstance(record.get("trajectory_id"), str)}
    lost = [record for record in tail if record.get("trajectory_id") in trajectory_ids - recorded_trajectory_ids]
    return JournalTail(bool(markers), frozenset(trajectory_ids), _unrecorded_effort(lost))


def _unrecorded_effort(records: Iterable[Mapping]) -> UnrecordedEffort:
    turns = tool_calls = 0
    ends: dict[tuple[str, object], Mapping | None] = {}
    for record in records:
        event = record.get("event")
        if event == "turn":
            turns += 1
        elif event == "tool_call":
            tool_calls += 1
        elif event == "request_start":
            ends[(record["trajectory_id"], record.get("attempt"))] = None
        elif event == "request_end":
            ends[(record["trajectory_id"], record.get("attempt"))] = record
    cost = elapsed = 0.0
    without_cost = 0
    for end in ends.values():
        if end is None:
            without_cost += 1  # sent; outcome unknown
            continue
        duration = end.get("duration_seconds")
        if _is_non_negative(duration):
            elapsed += duration
        if end.get("outcome") == "response":
            if _is_non_negative(end.get("cost_usd")):
                cost += end["cost_usd"]
            else:
                without_cost += 1
        elif end.get("outcome") == "abandoned" or (
                end.get("response_state") == "unknown" and not end.get("retryable")):
            without_cost += 1
    return UnrecordedEffort(turns=turns, tool_calls=tool_calls, requests=len(ends),
                            reported_cost_usd=cost, responses_without_cost=without_cost,
                            elapsed_seconds=elapsed)


def _is_non_negative(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value) and value >= 0


def trajectory_usage(trajectories: Iterable[AgentTrajectory]) -> dict[str, int | float]:
    """The usage totals the given trajectories record."""
    usage = dict.fromkeys(USAGE_TOTALS, 0)
    for trajectory in trajectories:
        usage["turns"] += trajectory.metrics.turn_count
        usage["tool_calls"] += trajectory.metrics.tool_call_count
        usage["reported_cost_usd"] += trajectory.metrics.cost_usd or 0
        usage["elapsed_seconds"] += trajectory.metrics.duration_seconds
        usage["responses_without_cost"] += sum(
            response.usage is None or response.usage.cost_usd is None
            for response in trajectory.provider_responses)
        failure = trajectory.provider_failure
        usage["responses_without_cost"] += (
            failure is not None and failure.response_state == "unknown" and not failure.retryable)
    return usage


@dataclass(frozen=True)
class ResumeUsage:
    """The cumulative usage a resume restores, and the effort it could not."""

    usage: dict[str, int | float | bool]
    """Totals plus `effort_counts_known` and `history_complete`."""
    unrecorded: UnrecordedEffort


def reconcile_resume_usage(
    *,
    saved_usage: Mapping,
    trajectories: Sequence[AgentTrajectory],
    journal: Sequence[Mapping] | None,
    journaled: bool,
    checkpointed_node_ids: Iterable[str],
) -> ResumeUsage:
    """Combine the saved summary, the trajectories and the journal.

    `journaled` says the checkpoint was written by a run that keeps a journal;
    `journal` is None when that journal is missing, which is missing history,
    never zero effort.
    """
    for key in USAGE_TOTALS:
        if not _is_non_negative(saved_usage.get(key, 0)):
            raise ValueError(f"invalid recorded run usage: {key}")
    if journaled and journal is not None:
        tail = journal_tail(journal, {t.trajectory_id for t in trajectories})
        unrecorded = tail.unrecorded
        later = trajectory_usage(t for t in trajectories if t.trajectory_id in tail.trajectory_ids)
        lost = unrecorded.as_usage()
        totals = {key: saved_usage.get(key, 0) + later[key] + lost[key] for key in USAGE_TOTALS}
        if tail.summary_recorded:
            # A marker certifies a summary; without that summary the effort
            # before the marker is unknown.
            certified = bool(saved_usage)
        else:
            # No process has exited normally yet: the trajectories are the
            # whole record, so every checkpointed node must have one.
            completed = {t.node_id for t in trajectories if t.completed and t.reconstruction_step is not None}
            certified = bool(saved_usage) or set(checkpointed_node_ids) <= completed
    else:
        # A run directory from before the journal, or one whose journal is
        # lost. Its JSONL can be newer than its last summary after an abrupt
        # exit, so keep the larger of each total. A legacy summary is written
        # on every normal exit, and nothing else distinguishes a never-started
        # checkpoint from an abrupt exit mid-node, so without one the history
        # is not certified. A lost journal never certifies it.
        unrecorded = UnrecordedEffort()
        recorded = trajectory_usage(trajectories)
        totals = {key: max(recorded[key], saved_usage.get(key, 0)) for key in USAGE_TOTALS}
        certified = bool(saved_usage) and not journaled
    saved_complete = bool(saved_usage.get("history_complete", True))
    effort_counts_known = certified and bool(saved_usage.get("effort_counts_known", saved_complete))
    usage = {
        **totals,
        "effort_counts_known": effort_counts_known,
        "history_complete": effort_counts_known and saved_complete and unrecorded.empty,
    }
    return ResumeUsage(usage, unrecorded)
