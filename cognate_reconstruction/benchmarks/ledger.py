"""Whole-batch resource ledger: every attempt's spend, read from its run dir.

The CLI caps (`--max-total-cost-usd`, `--max-run-seconds`, ...) bound one run.
A batch of runs needs the same accounting summed across runs and arms, with
the same rule the run-level accounting keeps: an unknown quantity is never
read as zero. A request without a recorded cost leaves the run's (and the
arm's) total cost unknown; `known_cost_usd` is then a lower bound and
`total_cost_usd` is None.

Each run is read from what it left behind: the run summary (the totals the
run itself enforced), the request journal (everything journaled before it
happened, including effort lost to an abrupt exit) and the trajectories
(the fallback when there is no journal, and the only source of cached and
reasoning token counts). The summary and journal are reconciled exactly as a
resume would (`reconcile_resume_usage`), and each count is then the larger of
that and the journal's own direct count, so neither a stale summary nor a
lost tail reads as less effort.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping

from cognate_reconstruction.agent.request_journal import (
    REQUEST_JOURNAL_VERSION,
    read_request_journal,
    reconcile_resume_usage,
    request_journal_path,
)
from cognate_reconstruction.agent.trajectory import AgentTrajectory, TrajectoryDatasetBuilder

OUTCOMES = ("committed", "fallback", "interrupted", "abandoned", "void", "not_run")
"""Distinct realized run outcomes; each run has exactly one.

`committed`: result written, every node reconstructed. `fallback`: result
written with at least one identity-fallback node. `interrupted`: the run
stopped and said so (`status: interrupted`). `abandoned`: artifacts exist but
no result and no interruption summary (abrupt loss, crash before writing).
`void`: an operator `VOID.txt` excludes it from linguistic results; its
resources still count. `not_run`: no artifacts at all.
"""

LINGUISTIC_OUTCOMES = frozenset({"committed", "fallback"})

_REQUEST_JOURNAL_SETTING = "request_journal"  # mirrors cli.REQUEST_JOURNAL_SETTING


@dataclass(frozen=True)
class RunResources:
    """All-attempt resource totals of one run directory."""

    run_dir: str
    run_id: str | None
    outcome: str
    present: bool
    summary_present: bool
    journal_present: bool
    legacy: bool
    """Read without a request journal: in-flight effort lost to an abrupt exit
    would be undetectable."""
    history_certified: bool
    """The turn/tool-call counts cover every counted effort (the run's
    `effort_counts_known`); False for a missing summary without a journal."""
    history_complete: bool
    effort_counts_known: bool
    usage_accounting_version: str | None
    turns: int
    tool_calls: int
    provider_requests: int
    requests_source: str
    """`journal` (exact), `trajectories` (recorded responses only: a lower
    bound) or `none`."""
    responses_with_cost: int
    known_cost_usd: float
    unknown_cost_requests: int
    """Requests whose spend is unknown: unpriced responses, abandoned or
    in-flight requests, and unknown-state non-retryable errors."""
    unrecorded_requests: int
    cost_known: bool
    total_cost_usd: float | None
    elapsed_seconds: float
    elapsed_is_lower_bound: bool
    input_tokens: int
    output_tokens: int
    total_tokens: int
    responses_without_token_counts: int
    max_request_input_tokens: int | None
    max_response_output_tokens: int | None
    cached_input_tokens: int | None
    reasoning_output_tokens: int | None
    """Cached and reasoning counts come only from trajectories (the journal
    does not carry them); None when no recorded response reported them."""
    distinct_trajectories: int
    duplicate_trajectory_records: int
    result_written: bool
    interrupted: bool
    void: bool

    def as_dict(self) -> dict:
        return asdict(self)


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else None


def _journal_identity(path: Path) -> tuple[str, str] | None:
    """Run ID and configuration of the first readable journal record."""
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("run_id") and record.get("configuration_sha256"):
            return record["run_id"], record["configuration_sha256"]
    return None


@dataclass
class _Counts:
    turns: int = 0
    tool_calls: int = 0
    requests: int = 0
    priced: int = 0
    cost: float = 0.0
    unknown_cost: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    without_tokens: int = 0
    max_input: int | None = None
    max_output: int | None = None


def _journal_counts(records: Iterable[Mapping]) -> _Counts:
    """Direct counts over the whole journal; cost rule as `_unrecorded_effort`."""
    counts = _Counts()
    ends: dict[tuple[object, object], Mapping | None] = {}
    for record in records:
        event = record.get("event")
        if event == "turn":
            counts.turns += 1
        elif event == "tool_call":
            counts.tool_calls += 1
        elif event == "request_start":
            ends[(record.get("trajectory_id"), record.get("attempt"))] = None
        elif event == "request_end":
            ends[(record.get("trajectory_id"), record.get("attempt"))] = record
    counts.requests = len(ends)
    for end in ends.values():
        if end is None:
            counts.unknown_cost += 1
            continue
        if end.get("outcome") == "response":
            if _number(end.get("cost_usd")):
                counts.priced += 1
                counts.cost += end["cost_usd"]
            else:
                counts.unknown_cost += 1
            _add_tokens(counts, end.get("input_tokens"), end.get("output_tokens"), end.get("total_tokens"))
        elif end.get("outcome") == "abandoned" or (
                end.get("response_state") == "unknown" and not end.get("retryable")):
            counts.unknown_cost += 1
    return counts


def _add_tokens(counts: _Counts, input_tokens, output_tokens, total_tokens) -> None:
    if not (_number(input_tokens) or _number(output_tokens) or _number(total_tokens)):
        counts.without_tokens += 1
        return
    if _number(input_tokens):
        counts.input_tokens += input_tokens
        counts.max_input = max(counts.max_input or 0, input_tokens)
    if _number(output_tokens):
        counts.output_tokens += output_tokens
        counts.max_output = max(counts.max_output or 0, output_tokens)
    if _number(total_tokens):
        counts.total_tokens += total_tokens
    elif _number(input_tokens) and _number(output_tokens):
        counts.total_tokens += input_tokens + output_tokens


def _trajectory_counts(trajectories: Iterable[AgentTrajectory]) -> _Counts:
    """Legacy fallback: only responses recorded in trajectories are visible."""
    counts = _Counts()
    for trajectory in trajectories:
        counts.turns += trajectory.metrics.turn_count
        counts.tool_calls += trajectory.metrics.tool_call_count
        for response in trajectory.provider_responses:
            counts.requests += 1
            usage = response.usage
            if usage is not None and usage.cost_usd is not None:
                counts.priced += 1
                counts.cost += usage.cost_usd
            else:
                counts.unknown_cost += 1
            _add_tokens(counts, *(None, None, None) if usage is None else
                        (usage.input_tokens, usage.output_tokens, usage.total_tokens))
        failure = trajectory.provider_failure
        if failure is not None and failure.response_state == "unknown" and not failure.retryable:
            counts.requests += 1
            counts.unknown_cost += 1
    return counts


def _subset_tokens(trajectories: Iterable[AgentTrajectory], field: str) -> int | None:
    values = [getattr(r.usage, field) for t in trajectories for r in t.provider_responses
              if r.usage is not None and getattr(r.usage, field) is not None]
    return sum(values) if values else None


def is_void(run_dir: Path) -> bool:
    return (run_dir / "VOID.txt").exists() or (run_dir.parent / "VOID.txt").exists()


def read_run_resources(run_dir: Path, checkpoint_name: str = "checkpoint.json") -> RunResources:
    """Read one run directory's all-attempt totals.

    Raises ValueError for a corrupt journal (anywhere but a torn final line):
    corrupt history is refused, never read as less effort.
    """
    run_dir = Path(run_dir)
    void = is_void(run_dir)
    present = run_dir.is_dir() and any(run_dir.iterdir())
    summary = _read_json(run_dir / "run_summary.json")
    result_path = run_dir / "result.json"
    result = _read_json(result_path)
    journal_path = request_journal_path(run_dir / checkpoint_name)
    run_id = (summary or {}).get("run_id") or (result or {}).get("run_id") or (
        ((result or {}).get("lifecycle_summary") or {}).get("run_id"))
    configuration = (summary or {}).get("configuration_sha256") or (
        ((result or {}).get("lifecycle_summary") or {}).get("configuration_sha256"))
    if run_id is None or configuration is None:
        identity = _journal_identity(journal_path)
        if identity is not None:
            run_id, configuration = run_id or identity[0], configuration or identity[1]
    journal = read_request_journal(journal_path, run_id, configuration) if run_id and configuration else None

    raw: list[AgentTrajectory] = []
    trajectories_path = run_dir / "trajectories.jsonl"
    if trajectories_path.exists():
        raw = [t for t in TrajectoryDatasetBuilder.read_jsonl(trajectories_path)
               if run_id is None or t.run_id == run_id]
    # Exact duplicate records are one session; distinct retries keep their effort.
    trajectories = tuple({t.trajectory_id: t for t in raw}.values())
    if run_id is None and trajectories:
        run_id = trajectories[0].run_id

    checkpoint = None
    checkpoint_path = run_dir / checkpoint_name
    if checkpoint_path.exists():
        from cognate_reconstruction.traversal import CheckpointStore
        checkpoint = CheckpointStore(checkpoint_path).load()
    journaled = journal is not None or (checkpoint is not None and checkpoint.operational_settings.get(
        _REQUEST_JOURNAL_SETTING) == REQUEST_JOURNAL_VERSION)
    saved_usage = (summary or {}).get("usage") or {}
    reconciled = reconcile_resume_usage(
        saved_usage=saved_usage, trajectories=trajectories, journal=journal, journaled=journaled,
        checkpointed_node_ids=checkpoint.steps_by_node if checkpoint is not None else (),
    ).usage
    if not present:
        reconciled = {**reconciled, "effort_counts_known": True, "history_complete": True}

    if journal is not None:
        direct, source = _journal_counts(journal), "journal"
    elif trajectories:
        direct, source = _trajectory_counts(trajectories), "trajectories"
    else:
        direct, source = _Counts(), "none"
    unknown_cost = max(int(reconciled["responses_without_cost"]), direct.unknown_cost)
    known_cost = max(float(reconciled["reported_cost_usd"]), direct.cost)
    certified = bool(reconciled["effort_counts_known"])
    cost_known = certified and unknown_cost == 0
    history_complete = bool(reconciled["history_complete"])
    # As `load_result_or_summary`: an interruption summary overrides a stale result.
    latest = summary if (summary or {}).get("status") == "interrupted" else (result or summary or {})
    interrupted = latest.get("status") == "interrupted"
    result_written = result_path.exists() and not interrupted
    if void:
        outcome = "void"
    elif not present:
        outcome = "not_run"
    elif interrupted:
        outcome = "interrupted"
    elif not result_written:
        outcome = "abandoned"
    elif latest.get("node_failures") or (latest.get("lifecycle_summary") or {}).get("fallback_node_ids"):
        outcome = "fallback"
    else:
        outcome = "committed"
    return RunResources(
        run_dir=str(run_dir), run_id=run_id, outcome=outcome, present=present,
        summary_present=summary is not None, journal_present=journal is not None,
        legacy=present and journal is None, history_certified=certified,
        history_complete=history_complete, effort_counts_known=certified,
        usage_accounting_version=saved_usage.get("usage_accounting_version"),
        turns=max(int(reconciled["turns"]), direct.turns),
        tool_calls=max(int(reconciled["tool_calls"]), direct.tool_calls),
        provider_requests=direct.requests, requests_source=source,
        responses_with_cost=direct.priced, known_cost_usd=known_cost,
        unknown_cost_requests=unknown_cost,
        unrecorded_requests=int(reconciled["unrecorded_requests"]),
        cost_known=cost_known, total_cost_usd=known_cost if cost_known else None,
        elapsed_seconds=float(reconciled["elapsed_seconds"]),
        elapsed_is_lower_bound=present and (not history_complete or summary is None),
        input_tokens=direct.input_tokens, output_tokens=direct.output_tokens,
        total_tokens=direct.total_tokens, responses_without_token_counts=direct.without_tokens,
        max_request_input_tokens=direct.max_input, max_response_output_tokens=direct.max_output,
        cached_input_tokens=_subset_tokens(trajectories, "cached_input_tokens"),
        reasoning_output_tokens=_subset_tokens(trajectories, "reasoning_output_tokens"),
        distinct_trajectories=len(trajectories), duplicate_trajectory_records=len(raw) - len(trajectories),
        result_written=result_written, interrupted=interrupted, void=void,
    )


_SUMMED = (
    "turns", "tool_calls", "provider_requests", "responses_with_cost", "known_cost_usd",
    "unknown_cost_requests", "unrecorded_requests", "elapsed_seconds", "input_tokens",
    "output_tokens", "total_tokens", "responses_without_token_counts",
    "distinct_trajectories", "duplicate_trajectory_records",
)


def _empty_totals() -> dict:
    return {"runs": 0, **dict.fromkeys(_SUMMED, 0), "cost_known": True, "total_cost_usd": 0.0,
            "history_certified": True, "elapsed_is_lower_bound": False, "legacy_runs": 0,
            "max_request_input_tokens": None, "max_response_output_tokens": None,
            "cached_input_tokens": None, "reasoning_output_tokens": None,
            "outcomes": dict.fromkeys(OUTCOMES, 0), "linguistic_runs": 0}


def _add(totals: dict, run: RunResources) -> None:
    totals["runs"] += 1
    for key in _SUMMED:
        totals[key] += getattr(run, key)
    totals["cost_known"] = totals["cost_known"] and run.cost_known
    totals["total_cost_usd"] = totals["known_cost_usd"] if totals["cost_known"] else None
    totals["history_certified"] = totals["history_certified"] and run.history_certified
    totals["elapsed_is_lower_bound"] = totals["elapsed_is_lower_bound"] or run.elapsed_is_lower_bound
    totals["legacy_runs"] += run.legacy
    for key in ("max_request_input_tokens", "max_response_output_tokens"):
        value = getattr(run, key)
        if value is not None:
            totals[key] = max(totals[key] or 0, value)
    for key in ("cached_input_tokens", "reasoning_output_tokens"):
        value = getattr(run, key)
        if value is not None:
            totals[key] = (totals[key] or 0) + value
    totals["outcomes"][run.outcome] += 1
    totals["linguistic_runs"] += run.outcome in LINGUISTIC_OUTCOMES


def batch_totals(runs: Iterable[tuple[str, RunResources]]) -> dict:
    """Sum every attempt per arm and overall, keeping unknown cost unknown.

    `known_cost_usd` is the sum of known spend (a lower bound when
    `cost_known` is False); `total_cost_usd` is None whenever any run in the
    group has a request of unknown cost or uncertified history. Outcome counts
    are distinct categories (`OUTCOMES`); a void run's resources are counted
    but it is not a linguistic run.
    """
    overall = _empty_totals()
    arms: dict[str, dict] = {}
    for arm, run in runs:
        _add(overall, run)
        _add(arms.setdefault(arm, _empty_totals()), run)
    return {"overall": overall, "arms": arms}
