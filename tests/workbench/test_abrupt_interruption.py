"""Abrupt process loss: journaled effort is counted, never read as zero.

A `BaseException` that is neither `Exception` nor `KeyboardInterrupt` skips
every finalization path, which is the artifact state an OOM kill, power loss
or `os._exit` leaves behind: the checkpoint and request journal survive, the
node in flight has no trajectory and there is no run summary.

A graceful exit is the opposite case and must stay distinguishable from it:
its run summary covers every session so far, trajectory or not.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from cognate_reconstruction import cli
from cognate_reconstruction.agent import reconstructor, request_journal
from cognate_reconstruction.agent.orchestrator import AgentOrchestrator
from cognate_reconstruction.agent.request_journal import JsonlRequestJournal, read_request_journal
from cognate_reconstruction.agent.schemas import (
    LLMMessage,
    MessageRole,
    ProviderResponse,
    ProviderResponseMetadata,
    ProviderUsage,
)
from cognate_reconstruction.agent.trajectory import TrajectoryDatasetBuilder
from cognate_reconstruction.traversal import CheckpointStore
from tests.workbench.test_recovery_and_provider import _commit_message, _node_id
from tests.workbench.test_resume_integrity import _infer, _prepare

REPO = Path(__file__).resolve().parents[2]


class AbruptExit(BaseException):
    """Bypasses `except (Exception, KeyboardInterrupt)` finalization."""


def _priced(message, cost):
    if cost is None:
        return message
    return ProviderResponse(message=message, metadata=ProviderResponseMetadata(usage=ProviderUsage(cost_usd=cost)))


class Scripted:
    """Commit at every node, except: at `crash_node`, answer without a commit
    `uncommitted` times and then die abruptly on the next call."""

    model = "test-model"

    def __init__(self, *, crash_node=None, uncommitted=1, cost=None, interrupt=AbruptExit):
        self.crash_node = crash_node
        self.uncommitted = uncommitted
        self.cost = cost
        self.interrupt = interrupt
        self.nodes: list[str] = []

    def complete(self, messages, tools, **kwargs):
        node = _node_id(messages)
        self.nodes.append(node)
        if node == self.crash_node:
            if self.uncommitted:
                self.uncommitted -= 1
                return _priced(LLMMessage(role=MessageRole.ASSISTANT, content="no commit yet"), self.cost)
            raise self.interrupt()
        return _priced(_commit_message(node), self.cost)


def _summary(tmp_path):
    return json.loads((tmp_path / "run_summary.json").read_text())


def _journal(tmp_path):
    return [json.loads(line) for line in (tmp_path / "checkpoint.requests.jsonl").read_text().splitlines()]


def _crash(tmp_path, monkeypatch, provider, *extra):
    _prepare(tmp_path)
    with pytest.raises(AbruptExit):
        _infer(tmp_path, monkeypatch, "--run-id", "run-test", *extra, provider=provider)
    assert not (tmp_path / "run_summary.json").exists()
    assert (tmp_path / "checkpoint.requests.jsonl").exists()


def test_first_node_abrupt_loss_counts_journaled_turns_against_the_cap(tmp_path, monkeypatch, capsys):
    """Window (a): empty completed set. Before the fix, resume spent 2 more
    calls under a 2-turn cap and reported 2 turns with complete history."""
    crashed = Scripted(crash_node="X")
    _crash(tmp_path, monkeypatch, crashed, "--max-total-turns", "2")
    assert crashed.nodes == ["X", "X"]
    assert CheckpointStore(tmp_path / "checkpoint.json").load().completed_steps == ()
    resumed = Scripted()
    with pytest.raises(SystemExit):
        _infer(tmp_path, monkeypatch, "--resume", "--max-total-turns", "2", provider=resumed)
    assert resumed.nodes == []
    usage = _summary(tmp_path)["usage"]
    assert usage["turns"] == 2
    assert usage["unrecorded_requests"] == 2
    # One response without cost, one request whose outcome is unknown.
    assert usage["responses_without_cost"] == 2
    assert usage["history_complete"] is False
    assert usage["effort_counts_known"] is True
    assert "journaled by a process that exited" in capsys.readouterr().err


def test_first_node_loss_under_a_larger_cap_resumes_conservatively_and_idempotently(tmp_path, monkeypatch):
    _crash(tmp_path, monkeypatch, Scripted(crash_node="X"), "--max-total-turns", "4")
    resumed = Scripted()
    _infer(tmp_path, monkeypatch, "--resume", "--max-total-turns", "4", provider=resumed)
    assert resumed.nodes == ["X", "ROOT"]
    usage = _summary(tmp_path)["usage"]
    assert (usage["turns"], usage["unrecorded_requests"], usage["history_complete"]) == (4, 2, False)
    # Resuming the completed run again: no calls, no JSONL growth, no double count.
    before = (tmp_path / "trajectories.jsonl").read_bytes()
    again = Scripted()
    _infer(tmp_path, monkeypatch, "--resume", "--max-total-turns", "4", provider=again)
    assert again.nodes == []
    assert (tmp_path / "trajectories.jsonl").read_bytes() == before
    usage = _summary(tmp_path)["usage"]
    assert (usage["turns"], usage["unrecorded_requests"], usage["history_complete"]) == (4, 2, False)


def test_later_node_loss_keeps_completed_nodes_and_counts_only_lost_effort(tmp_path, monkeypatch):
    """Window (b): X is completed and recorded; ROOT's effort is lost."""
    crashed = Scripted(crash_node="ROOT")
    _crash(tmp_path, monkeypatch, crashed, "--max-total-turns", "4")
    assert crashed.nodes == ["X", "ROOT", "ROOT"]
    assert [s.parent_node_id for s in CheckpointStore(tmp_path / "checkpoint.json").load().completed_steps] == ["X"]
    # 1 recorded turn (X) + 2 journaled (ROOT) leave exactly one turn of the cap.
    resumed = Scripted()
    _infer(tmp_path, monkeypatch, "--resume", "--max-total-turns", "4", provider=resumed)
    assert resumed.nodes == ["ROOT"]  # completed-node reuse is unchanged
    usage = _summary(tmp_path)["usage"]
    assert (usage["turns"], usage["unrecorded_requests"], usage["history_complete"]) == (4, 2, False)
    records = TrajectoryDatasetBuilder.read_jsonl(tmp_path / "trajectories.jsonl")
    assert [(t.node_id, t.completed) for t in records] == [("X", True), ("ROOT", True)]


def test_in_flight_request_makes_cost_unknown_and_a_cost_cap_refuses(tmp_path, monkeypatch):
    """Window (c): a request was sent and no response was recorded."""
    _crash(tmp_path, monkeypatch, Scripted(crash_node="X", cost=0.25), "--max-total-cost-usd", "10")
    resumed = Scripted(cost=0.25)
    with pytest.raises(SystemExit):
        _infer(tmp_path, monkeypatch, "--resume", "--max-total-cost-usd", "10", provider=resumed)
    assert resumed.nodes == []
    summary = _summary(tmp_path)
    assert "abrupt exit" in summary["interruption_reason"]
    assert "fresh run" in summary["interruption_reason"]
    # The recorded response's cost is restored; the in-flight one is not zeroed.
    assert summary["usage"]["reported_cost_usd"] == pytest.approx(0.25)
    assert summary["usage"]["responses_without_cost"] == 1
    # Refusal is stable: another resume makes no call either.
    with pytest.raises(SystemExit):
        _infer(tmp_path, monkeypatch, "--resume", "--max-total-cost-usd", "10", provider=resumed)
    assert resumed.nodes == []


def test_in_flight_request_without_a_cost_cap_continues_with_cost_flagged(tmp_path, monkeypatch):
    _crash(tmp_path, monkeypatch, Scripted(crash_node="X", cost=0.25))
    resumed = Scripted(cost=0.25)
    _infer(tmp_path, monkeypatch, "--resume", provider=resumed)
    assert resumed.nodes == ["X", "ROOT"]
    usage = _summary(tmp_path)["usage"]
    assert usage["reported_cost_usd"] == pytest.approx(0.75)  # a known lower bound
    assert usage["responses_without_cost"] == 1
    assert usage["history_complete"] is False


def test_loss_after_a_priced_response_restores_known_cost_but_not_time(tmp_path, monkeypatch):
    """Crash between a recorded response and the next turn: spend is known."""
    original = AgentOrchestrator._journal

    def dies_before_second_turn(self, event, node_id, state, **fields):
        if event == "turn" and fields.get("turn") == 2:
            raise AbruptExit()
        original(self, event, node_id, state, **fields)

    caps = ("--max-total-cost-usd", "10", "--max-total-turns", "3")
    monkeypatch.setattr(AgentOrchestrator, "_journal", dies_before_second_turn)
    _crash(tmp_path, monkeypatch, Scripted(crash_node="X", cost=0.25), *caps)
    monkeypatch.setattr(AgentOrchestrator, "_journal", original)
    resumed = Scripted(cost=0.25)
    _infer(tmp_path, monkeypatch, "--resume", *caps, provider=resumed)
    assert resumed.nodes == ["X", "ROOT"]
    usage = _summary(tmp_path)["usage"]
    assert usage["reported_cost_usd"] == pytest.approx(0.75)
    assert (usage["responses_without_cost"], usage["turns"], usage["unrecorded_requests"]) == (0, 3, 1)
    assert usage["history_complete"] is False


def test_lost_effort_makes_elapsed_unknown_and_a_time_cap_refuses(tmp_path, monkeypatch):
    _crash(tmp_path, monkeypatch, Scripted(crash_node="X"), "--max-run-seconds", "1000")
    resumed = Scripted()
    with pytest.raises(SystemExit):
        _infer(tmp_path, monkeypatch, "--resume", "--max-run-seconds", "1000", provider=resumed)
    assert resumed.nodes == []
    reason = _summary(tmp_path)["interruption_reason"]
    assert "time limit" in reason and "fresh run" in reason


def test_journal_record_is_durable_before_each_provider_request(tmp_path, monkeypatch):
    journal = tmp_path / "checkpoint.requests.jsonl"
    seen = []

    class Checking(Scripted):
        def complete(self, messages, tools, **kwargs):
            last = json.loads(journal.read_text().splitlines()[-1])
            seen.append((last["event"], last["node_id"]))
            return super().complete(messages, tools, **kwargs)

    _prepare(tmp_path)
    _infer(tmp_path, monkeypatch, "--run-id", "run-test", provider=Checking())
    assert seen == [("request_start", "X"), ("request_start", "ROOT")]
    records = [json.loads(line) for line in journal.read_text().splitlines()]
    finalized = {t.trajectory_id for t in TrajectoryDatasetBuilder.read_jsonl(tmp_path / "trajectories.jsonl")}
    assert {r["trajectory_id"] for r in records if "trajectory_id" in r} == finalized


def test_keyboard_interrupt_mid_request_is_graceful_but_its_cost_is_unknown(tmp_path, monkeypatch):
    _prepare(tmp_path)
    with pytest.raises((SystemExit, KeyboardInterrupt)):
        _infer(tmp_path, monkeypatch, "--run-id", "run-test", "--max-total-turns", "4",
               provider=Scripted(crash_node="ROOT", cost=0.25, interrupt=KeyboardInterrupt))
    summary = _summary(tmp_path)
    assert summary["complete"] is False
    assert summary["usage"]["history_complete"] is True
    # The interrupted request may have been billed; it is not counted as free.
    assert summary["usage"]["responses_without_cost"] == 1
    assert [r["outcome"] for r in _journal(tmp_path) if r["event"] == "request_end"][-1] == "abandoned"
    assert _journal(tmp_path)[-1]["event"] == "usage_recorded"
    resumed = Scripted()
    _infer(tmp_path, monkeypatch, "--resume", "--max-total-turns", "4", provider=resumed)
    assert resumed.nodes == ["ROOT"]
    usage = _summary(tmp_path)["usage"]
    assert (usage["turns"], usage["unrecorded_requests"], usage["history_complete"]) == (4, 0, True)


def test_keyboard_interrupt_mid_request_stops_a_cost_capped_resume(tmp_path, monkeypatch):
    _prepare(tmp_path)
    with pytest.raises((SystemExit, KeyboardInterrupt)):
        _infer(tmp_path, monkeypatch, "--run-id", "run-test", "--max-total-cost-usd", "10",
               provider=Scripted(crash_node="ROOT", cost=0.25, interrupt=KeyboardInterrupt))
    resumed = Scripted(cost=0.25)
    with pytest.raises(SystemExit):
        _infer(tmp_path, monkeypatch, "--resume", "--max-total-cost-usd", "10", provider=resumed)
    assert resumed.nodes == []
    assert "cost unavailable" in _summary(tmp_path)["interruption_reason"]


def _fail_after_commit_once(monkeypatch, node="ROOT"):
    """Raise an ordinary error after `node` commits, as an ambiguous overlay
    or a changed evidence column would, and only in the first process."""
    original = reconstructor._apply_overlay
    failed = []

    def apply(child, context, overlay_id):
        if context.node_id == node and not failed:
            failed.append(node)
            raise ValueError("segmentation overlay is ambiguous")
        return original(child, context, overlay_id)

    monkeypatch.setattr(reconstructor, "_apply_overlay", apply)
    return failed


def test_post_commit_failure_is_graceful_and_a_time_capped_resume_proceeds(tmp_path, monkeypatch, capsys):
    """Review defect D1: the committed session never reaches the JSONL, but
    the run summary records its effort, so it is not effort lost to a crash."""
    _prepare(tmp_path)
    failed = _fail_after_commit_once(monkeypatch)
    with pytest.raises(SystemExit):
        _infer(tmp_path, monkeypatch, "--run-id", "run-test", "--max-run-seconds", "1000",
               provider=Scripted())
    assert failed == ["ROOT"]
    assert _summary(tmp_path)["usage"]["history_complete"] is True
    capsys.readouterr()
    resumed = Scripted()
    _infer(tmp_path, monkeypatch, "--resume", "--max-run-seconds", "1000", provider=resumed)
    assert resumed.nodes == ["ROOT"]
    usage = _summary(tmp_path)["usage"]
    assert (usage["turns"], usage["unrecorded_requests"], usage["history_complete"]) == (3, 0, True)
    assert "incomplete" not in capsys.readouterr().err


def test_effort_after_a_summary_adds_to_it_rather_than_competing_with_it(tmp_path, monkeypatch):
    """A graceful post-commit failure, then an abrupt loss on resume: the lost
    turns are added to the summary's, including the session the JSONL lacks."""
    _prepare(tmp_path)
    _fail_after_commit_once(monkeypatch)
    with pytest.raises(SystemExit):
        _infer(tmp_path, monkeypatch, "--run-id", "run-test", provider=Scripted())
    with pytest.raises(AbruptExit):
        _infer(tmp_path, monkeypatch, "--resume", provider=Scripted(crash_node="ROOT"))
    resumed = Scripted()
    _infer(tmp_path, monkeypatch, "--resume", provider=resumed)
    assert resumed.nodes == ["ROOT"]
    usage = _summary(tmp_path)["usage"]
    # X 1 + ROOT 1 (summary) + ROOT 2 (lost) + ROOT 1 (this resume).
    assert (usage["turns"], usage["unrecorded_requests"], usage["history_complete"]) == (5, 2, False)


def test_unwritable_journal_stops_the_run_instead_of_falling_back(tmp_path, monkeypatch, capsys):
    """Review defect D3: no request is sent unjournaled, and no node becomes
    an identity fallback because the disk refused a write."""
    original = JsonlRequestJournal.record

    def refuses_requests(self, event, **fields):
        if event == "request_start":
            raise OSError(28, "No space left on device")
        original(self, event, **fields)

    monkeypatch.setattr(JsonlRequestJournal, "record", refuses_requests)
    provider = Scripted()
    _prepare(tmp_path)
    with pytest.raises(SystemExit):
        _infer(tmp_path, monkeypatch, "--run-id", "run-test", provider=provider)
    assert provider.nodes == []
    assert "FAILED NODE" not in capsys.readouterr().err
    summary = _summary(tmp_path)
    assert summary["failure_error_type"] == "RequestJournalError"
    assert "No space left" in summary["interruption_reason"]
    assert not (tmp_path / "result.json").exists()


def test_torn_journal_tail_survives_repeated_resumes(tmp_path, monkeypatch):
    """Review defect D2: the next process must not append to a torn line."""
    _crash(tmp_path, monkeypatch, Scripted(crash_node="X"), "--max-total-turns", "9")
    with (tmp_path / "checkpoint.requests.jsonl").open("a") as handle:
        handle.write('{"run_id": "run-test", "eve')
    with pytest.raises(AbruptExit):
        _infer(tmp_path, monkeypatch, "--resume", "--max-total-turns", "9",
               provider=Scripted(crash_node="ROOT"))
    assert all(isinstance(record, dict) for record in _journal(tmp_path))  # every line parses
    resumed = Scripted()
    _infer(tmp_path, monkeypatch, "--resume", "--max-total-turns", "9", provider=resumed)
    assert resumed.nodes == ["ROOT"]
    usage = _summary(tmp_path)["usage"]
    # X 2 lost + X 1 + ROOT 2 lost + ROOT 1.
    assert (usage["turns"], usage["unrecorded_requests"]) == (6, 4)


def test_unknown_history_is_reported_before_an_exhausted_turn_count(tmp_path, monkeypatch):
    """The per-turn history check runs before the total-turn check, so the
    refusal names the real cause rather than a count that only looks spent."""
    _prepare(tmp_path)
    with pytest.raises(SystemExit):
        _infer(tmp_path, monkeypatch, "--run-id", "run-test", "--max-total-turns", "2",
               provider=Scripted(crash_node="ROOT", uncommitted=0, interrupt=KeyboardInterrupt))
    # As an earlier resume that found its history unknown would have left it.
    summary = _summary(tmp_path)
    assert summary["usage"]["turns"] == 2
    summary["usage"].update(effort_counts_known=False, history_complete=False)
    (tmp_path / "run_summary.json").write_text(json.dumps(summary))
    with pytest.raises(SystemExit):
        _infer(tmp_path, monkeypatch, "--resume", "--max-total-turns", "2", provider=Scripted())
    assert "usage history unavailable" in _summary(tmp_path)["interruption_reason"]


def test_fresh_run_refuses_a_journal_left_at_its_checkpoint_path(tmp_path, monkeypatch, capsys):
    _prepare(tmp_path)
    (tmp_path / "checkpoint.requests.jsonl").write_text("")
    provider = Scripted()
    with pytest.raises(SystemExit):
        _infer(tmp_path, monkeypatch, "--run-id", "run-test", provider=provider)
    assert provider.nodes == []
    assert "request journal already exists" in capsys.readouterr().err


def test_each_journal_record_is_fsynced(tmp_path, monkeypatch):
    synced = []
    monkeypatch.setattr(request_journal.os, "fsync", synced.append)
    journal = JsonlRequestJournal(tmp_path / "j.jsonl", run_id="r", configuration_sha256="c")
    journal.record("turn", trajectory_id="t")
    journal.record("tool_call", trajectory_id="t")
    assert len(synced) == 2


def test_retry_only_change_still_resumes_after_abrupt_loss(tmp_path, monkeypatch, capsys):
    _crash(tmp_path, monkeypatch, Scripted(crash_node="ROOT"), "--max-retries", "0", "--max-total-turns", "5")
    resumed = Scripted()
    _infer(tmp_path, monkeypatch, "--resume", "--max-retries", "4", "--max-retry-seconds", "600",
           "--max-total-turns", "5", provider=resumed)
    assert resumed.nodes == ["ROOT"]
    assert "operational retry settings changed" in capsys.readouterr().err
    assert _summary(tmp_path)["usage"]["turns"] == 4


def _make_legacy(tmp_path):
    """Remove what this repair adds: the journal and the checkpoint marker."""
    (tmp_path / "checkpoint.requests.jsonl").unlink()
    store = CheckpointStore(tmp_path / "checkpoint.json")
    checkpoint = store.load()
    settings = {k: v for k, v in checkpoint.operational_settings.items() if k != cli.REQUEST_JOURNAL_SETTING}
    store.save(checkpoint.model_copy(update={"operational_settings": settings}))


def test_legacy_complete_run_with_summary_stays_resumable_and_complete(tmp_path, monkeypatch):
    _prepare(tmp_path)
    _infer(tmp_path, monkeypatch, "--run-id", "run-test", "--max-total-turns", "2")
    _make_legacy(tmp_path)
    resumed = Scripted()
    _infer(tmp_path, monkeypatch, "--resume", "--max-total-turns", "2", provider=resumed)
    assert resumed.nodes == []
    usage = _summary(tmp_path)["usage"]
    assert (usage["turns"], usage["history_complete"]) == (2, True)


def test_legacy_checkpoint_without_summary_is_not_certified_complete(tmp_path, monkeypatch):
    """The reviewer's state in an old run directory: an empty checkpoint, no
    summary, no trajectories. It may hide lost effort, so caps refuse."""
    _crash(tmp_path, monkeypatch, Scripted(crash_node="X"), "--max-total-turns", "9")
    _make_legacy(tmp_path)
    resumed = Scripted()
    with pytest.raises(SystemExit):
        _infer(tmp_path, monkeypatch, "--resume", "--max-total-turns", "9", provider=resumed)
    assert resumed.nodes == []
    assert "usage history unavailable" in _summary(tmp_path)["interruption_reason"]


def test_legacy_checkpoint_without_summary_or_caps_resumes_flagged(tmp_path, monkeypatch):
    _crash(tmp_path, monkeypatch, Scripted(crash_node="X"))
    _make_legacy(tmp_path)
    resumed = Scripted()
    _infer(tmp_path, monkeypatch, "--resume", provider=resumed)  # no caps: may continue
    assert resumed.nodes == ["X", "ROOT"]
    usage = _summary(tmp_path)["usage"]
    assert (usage["history_complete"], usage["effort_counts_known"]) == (False, False)


def test_journaled_run_whose_journal_is_missing_is_missing_history(tmp_path, monkeypatch):
    _crash(tmp_path, monkeypatch, Scripted(crash_node="X"), "--max-total-turns", "9")
    (tmp_path / "checkpoint.requests.jsonl").unlink()
    resumed = Scripted()
    with pytest.raises(SystemExit):
        _infer(tmp_path, monkeypatch, "--resume", "--max-total-turns", "9", provider=resumed)
    assert resumed.nodes == []
    assert "usage history unavailable" in _summary(tmp_path)["interruption_reason"]


def test_torn_final_journal_record_is_tolerated_but_corruption_is_not(tmp_path):
    path = tmp_path / "j.jsonl"
    good = json.dumps({"run_id": "r", "configuration_sha256": "c", "event": "turn", "trajectory_id": "t"})
    path.write_text(good + "\n" + '{"run_id": "r", "eve')
    assert len(read_request_journal(path, "r", "c")) == 1
    # The writer drops the torn record before appending the next one.
    JsonlRequestJournal(path, run_id="r", configuration_sha256="c").record("turn", trajectory_id="t")
    assert len(read_request_journal(path, "r", "c")) == 2
    path.write_text('{"torn\n' + good + "\n")
    with pytest.raises(ValueError, match="corrupt request journal"):
        read_request_journal(path, "r", "c")
    assert read_request_journal(tmp_path / "absent.jsonl", "r", "c") is None


_EXIT_SCRIPT = """
import os, sys
sys.path.insert(0, {repo!r})
from cognate_reconstruction import cli
from cognate_reconstruction.agent.schemas import LLMMessage, MessageRole
from tests.workbench.test_recovery_and_provider import _node_id

class Dies:
    model = "test-model"
    calls = 0
    def complete(self, messages, tools, **kwargs):
        Dies.calls += 1
        if Dies.calls == 1:
            return LLMMessage(role=MessageRole.ASSISTANT, content="no commit yet")
        os._exit(17)

cli.LiteLLMProvider = lambda *a, **k: Dies()
d = {tmp!r}
cli.main(["infer", "--input", d + "/input.json", "--model", "test-model",
          "--output", d + "/result.json", "--trajectories", d + "/trajectories.jsonl",
          "--checkpoint", d + "/checkpoint.json", "--quiet", "--no-events",
          "--run-id", "run-test", "--max-total-turns", "3"])
"""


def test_os_exit_mid_node_in_a_subprocess(tmp_path, monkeypatch):
    _prepare(tmp_path)
    script = tmp_path / "dies.py"
    script.write_text(_EXIT_SCRIPT.format(repo=str(REPO), tmp=str(tmp_path)))
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    completed = subprocess.run([sys.executable, str(script)], cwd=tmp_path, env=env,
                               capture_output=True, text=True, timeout=120)
    assert completed.returncode == 17, completed.stderr
    assert not (tmp_path / "run_summary.json").exists()
    resumed = Scripted()
    with pytest.raises(SystemExit):
        _infer(tmp_path, monkeypatch, "--resume", "--max-total-turns", "3", provider=resumed)
    # Two journaled turns + X's one: ROOT cannot start under the cap of 3.
    assert resumed.nodes == ["X"]
    usage = _summary(tmp_path)["usage"]
    assert (usage["turns"], usage["unrecorded_requests"], usage["history_complete"]) == (3, 2, False)
