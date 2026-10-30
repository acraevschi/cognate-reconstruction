"""Whole-batch ledger and serial launcher, over an offline fake batch.

Every trial is the real `infer` CLI in a subprocess with a scripted provider,
so the run summary, request journal and trajectories under test are the ones
the harness writes. Nothing contacts a model or a server.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from cognate_reconstruction.benchmarks.ledger import OUTCOMES, batch_totals, read_run_resources
from tests.workbench.test_abrupt_interruption import Scripted, _crash, _summary
from tests.workbench.test_resume_integrity import _infer, _prepare

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
_spec = importlib.util.spec_from_file_location("experiment_batch", REPO / "tools/experiment_batch.py")
experiment_batch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(experiment_batch)

FAKE_INFER = """
import argparse, os, sys
sys.path.insert(0, {repo!r})
from cognate_reconstruction import cli
from cognate_reconstruction.agent.schemas import (
    LLMMessage, MessageRole, ProviderResponse, ProviderResponseMetadata, ProviderUsage)
from tests.workbench.test_recovery_and_provider import _commit_message, _node_id
from tests.workbench.test_resume_integrity import _payload

parser = argparse.ArgumentParser()
parser.add_argument("run_dir")
parser.add_argument("--cost", type=float, default=0.25)
parser.add_argument("--unpriced-at")
parser.add_argument("--abrupt-at")
parser.add_argument("--tokens", type=int, nargs=2, default=(100, 10))
parser.add_argument("--void", action="store_true")
args, extra = parser.parse_known_args()

class Provider:
    model = "test-model"
    calls = 0
    def complete(self, messages, tools, **kwargs):
        node = _node_id(messages)
        if node == args.abrupt_at:
            os._exit(17)  # request journaled, never answered, no summary
        Provider.calls += 1
        n = Provider.calls  # sizes grow per call: the maximum differs from the sum
        usage = ProviderUsage(
            cost_usd=None if node == args.unpriced_at else args.cost,
            input_tokens=args.tokens[0] * n, output_tokens=args.tokens[1] * n,
            total_tokens=(args.tokens[0] + args.tokens[1]) * n, cached_input_tokens=5 * n)
        return ProviderResponse(message=_commit_message(node),
                                metadata=ProviderResponseMetadata(usage=usage))

d = args.run_dir
os.makedirs(d, exist_ok=True)
if args.void:
    open(os.path.join(d, "VOID.txt"), "w").write("operator: excluded\\n")
open(os.path.join(d, "input.json"), "w").write(_payload().model_dump_json())
cli.LiteLLMProvider = lambda *a, **k: Provider()
try:
    cli.main(["infer", "--input", d + "/input.json", "--model", "test-model",
              "--output", d + "/result.json", "--trajectories", d + "/trajectories.jsonl",
              "--checkpoint", d + "/checkpoint.json", "--quiet", "--no-events",
              "--run-id", "run-" + os.path.basename(d), *extra])
except SystemExit as stop:
    sys.exit(stop.code)
"""

FAKE_EVALUATE = """
import json, sys
usable = sys.argv[2] == "usable"
with open(sys.argv[1] + "/evaluation.json", "w") as handle:
    json.dump({"stage_gate": {"usable": usable, "reason": "fake gate: " + sys.argv[2]}, "score": 0.5}, handle)
"""


@pytest.fixture
def scripts(tmp_path):
    infer = tmp_path / "fake_infer.py"
    infer.write_text(FAKE_INFER.format(repo=str(REPO)))
    evaluate = tmp_path / "fake_evaluate.py"
    evaluate.write_text(FAKE_EVALUATE)
    return infer, evaluate


def _trial(scripts, trial_id, arm, *flags, cost=1.0, wall=None, requires=None, gate=None):
    infer, evaluate = scripts
    return {
        "trial_id": trial_id, "arm": arm, "run_dir": f"runs/{trial_id}",
        "argv": ["{python}", str(infer), "{run_dir}", *flags],
        "reservation": {"cost_usd": cost, "wall_seconds": wall},
        "requires_usable": requires,
        "evaluate_argv": ["{python}", str(evaluate), "{run_dir}", gate] if gate else None,
    }


def _plan(tmp_path, trials, ceilings):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"plan_version": "r02-batch-v1", "batch_dir": "batch",
                                "ceilings": ceilings, "trials": trials}))
    return path


def _launch(plan_path):
    plan = experiment_batch.load_plan(plan_path)
    return experiment_batch.run_plan(plan), plan


def _decisions(decisions):
    return {d["trial_id"]: d["event"] for d in decisions if d["event"] in ("refused", "finished")}


def _ledger(tmp_path):
    return json.loads((tmp_path / "batch" / "batch_ledger.json").read_text())


PAID = {"cost_usd": 10.0, "wall_seconds": None}


def test_priced_run_is_fully_accounted_with_request_size_and_cumulative_tokens(tmp_path, scripts):
    """(i) and (x): known cost, exact request count, max size beside the sum."""
    decisions, _ = _launch(_plan(tmp_path, [_trial(scripts, "a1", "paid")], {"paid": PAID}))
    assert _decisions(decisions) == {"a1": "finished"}
    run = read_run_resources(tmp_path / "runs/a1")
    assert run.outcome == "committed" and run.cost_known and not run.legacy
    assert (run.provider_requests, run.responses_with_cost, run.unknown_cost_requests) == (2, 2, 0)
    assert run.total_cost_usd == pytest.approx(0.5)
    assert (run.input_tokens, run.output_tokens, run.total_tokens) == (300, 30, 330)
    assert (run.max_request_input_tokens, run.max_response_output_tokens) == (200, 20)
    assert run.cached_input_tokens == 15
    assert run.elapsed_is_lower_bound is False
    totals = _ledger(tmp_path)["totals"]
    assert totals["overall"]["max_request_input_tokens"] == 200
    assert totals["overall"]["input_tokens"] == 300
    assert totals["arms"]["paid"]["total_cost_usd"] == pytest.approx(0.5)
    assert totals["overall"]["wall_seconds"] > 0 and totals["overall"]["wall_known"]
    events = [json.loads(line) for line in (tmp_path / "batch/batch_events.jsonl").read_text().splitlines()]
    assert [e["event"] for e in events] == ["launched", "finished"]


def test_unpriced_response_makes_cost_unknown_and_refuses_later_paid_trials(tmp_path, scripts):
    """(ii) and (ix): an unknown-cost request stops its paid arm only."""
    trials = [
        _trial(scripts, "p1", "paid", "--unpriced-at", "ROOT"),
        _trial(scripts, "p2", "paid"),
        _trial(scripts, "l1", "local", "--cost", "0", cost=None),
    ]
    decisions, _ = _launch(_plan(tmp_path, trials, {"paid": PAID, "local": {"cost_usd": None, "wall_seconds": None}}))
    assert _decisions(decisions) == {"p1": "finished", "p2": "refused", "l1": "finished"}
    refused = next(d for d in decisions if d["trial_id"] == "p2")
    assert refused["reason"].startswith("arm_cost_unknown")
    p1 = read_run_resources(tmp_path / "runs/p1")
    assert (p1.cost_known, p1.total_cost_usd, p1.unknown_cost_requests) == (False, None, 1)
    assert p1.known_cost_usd == pytest.approx(0.25)
    paid = _ledger(tmp_path)["totals"]["arms"]["paid"]
    assert paid["total_cost_usd"] is None and paid["known_cost_usd"] == pytest.approx(0.25)
    assert paid["outcomes"]["not_run"] == 1
    assert not (tmp_path / "runs/p2").exists()
    overall = _ledger(tmp_path)["totals"]["overall"]
    assert overall["total_cost_usd"] is None  # unknown anywhere is unknown in the sum


def test_abrupt_loss_carries_unknown_cost_and_a_lower_bound_elapsed(tmp_path, scripts):
    """(iii): request_start without request_end, and no run summary."""
    trials = [_trial(scripts, "a1", "paid", "--abrupt-at", "ROOT"), _trial(scripts, "a2", "paid")]
    decisions, _ = _launch(_plan(tmp_path, trials, {"paid": PAID}))
    finished = next(d for d in decisions if d["event"] == "finished")
    assert finished["exit_code"] == 17
    assert _decisions(decisions)["a2"] == "refused"
    run = read_run_resources(tmp_path / "runs/a1")
    assert not run.summary_present and run.journal_present
    assert run.outcome == "abandoned"
    assert (run.provider_requests, run.unrecorded_requests, run.unknown_cost_requests) == (2, 1, 1)
    assert run.known_cost_usd == pytest.approx(0.25) and run.total_cost_usd is None
    assert run.elapsed_is_lower_bound and not run.history_complete
    assert run.history_certified  # the journal still certifies the counts


def test_whole_batch_cost_ceiling_refuses_the_trial_that_would_exceed_it(tmp_path, scripts):
    """(iv): reservations are per trial; the ceiling is per arm across trials."""
    # Each run spends $0.50: spent + reservation is 0.6, 1.1, then 1.6 > 1.2.
    trials = [_trial(scripts, f"c{i}", "paid", cost=0.6) for i in (1, 2, 3)]
    decisions, _ = _launch(_plan(tmp_path, trials, {"paid": {"cost_usd": 1.2, "wall_seconds": None}}))
    assert _decisions(decisions) == {"c1": "finished", "c2": "finished", "c3": "refused"}
    reason = next(d["reason"] for d in decisions if d["trial_id"] == "c3")
    assert reason.startswith("cost_ceiling") and "spent $1.0000" in reason
    assert _ledger(tmp_path)["totals"]["arms"]["paid"]["outcomes"]["committed"] == 2


def test_stage_gate_refuses_b_on_an_unusable_a_and_launches_it_on_a_usable_one(tmp_path, scripts):
    """(v)"""
    trials = [
        _trial(scripts, "a_bad", "paid", gate="unusable"),
        _trial(scripts, "b_bad", "paid", requires="a_bad"),
        _trial(scripts, "a_good", "paid", gate="usable"),
        _trial(scripts, "b_good", "paid", requires="a_good"),
    ]
    decisions, _ = _launch(_plan(tmp_path, trials, {"paid": PAID}))
    assert _decisions(decisions) == {"a_bad": "finished", "b_bad": "refused",
                                     "a_good": "finished", "b_good": "finished"}
    reason = next(d["reason"] for d in decisions if d["trial_id"] == "b_bad")
    assert reason.startswith("requires_usable") and "fake gate: unusable" in reason
    evaluated = [d for d in decisions if d["event"] == "evaluated"]
    assert [(d["trial_id"], d["usable"]) for d in evaluated] == [("a_bad", False), ("a_good", True)]


def test_void_run_counts_its_resources_but_is_not_a_linguistic_outcome(tmp_path, scripts):
    """(vi)"""
    _launch(_plan(tmp_path, [_trial(scripts, "v1", "paid", "--void")], {"paid": PAID}))
    run = read_run_resources(tmp_path / "runs/v1")
    assert run.void and run.outcome == "void" and run.result_written
    paid = _ledger(tmp_path)["totals"]["arms"]["paid"]
    assert paid["outcomes"]["void"] == 1 and paid["linguistic_runs"] == 0
    assert paid["known_cost_usd"] == pytest.approx(0.5) and paid["provider_requests"] == 2
    assert set(paid["outcomes"]) == set(OUTCOMES)


def test_duplicate_trajectory_record_is_not_double_counted(tmp_path, scripts):
    """(vii): an exact duplicate is one session; the legacy path relies on it."""
    _launch(_plan(tmp_path, [_trial(scripts, "d1", "paid")], {"paid": PAID}))
    run_dir = tmp_path / "runs/d1"
    path = run_dir / "trajectories.jsonl"
    lines = path.read_text().splitlines()
    path.write_text("\n".join([*lines, lines[0]]) + "\n")
    run = read_run_resources(run_dir)
    assert (run.distinct_trajectories, run.duplicate_trajectory_records) == (2, 1)
    assert run.turns == 2 and run.total_cost_usd == pytest.approx(0.5)
    # Without the journal, trajectories are the fallback and still not doubled.
    (run_dir / "checkpoint.requests.jsonl").unlink()
    legacy = read_run_resources(run_dir)
    assert legacy.legacy and legacy.requests_source == "trajectories"
    assert legacy.turns == 2 and legacy.provider_requests == 2 and legacy.input_tokens == 300


def test_rerunning_a_plan_relaunches_nothing_and_doubles_no_output(tmp_path, scripts):
    """(viii)"""
    plan_path = _plan(tmp_path, [_trial(scripts, "r1", "paid"), _trial(scripts, "r2", "paid")], {"paid": PAID})
    _launch(plan_path)
    before = (tmp_path / "runs/r1/trajectories.jsonl").read_bytes()
    first = _ledger(tmp_path)["totals"]["overall"]
    decisions, _ = _launch(plan_path)
    assert _decisions(decisions) == {"r1": "refused", "r2": "refused"}
    assert all(d["reason"].startswith("run_dir_not_empty") for d in decisions)
    assert (tmp_path / "runs/r1/trajectories.jsonl").read_bytes() == before
    second = _ledger(tmp_path)["totals"]["overall"]
    assert (second["known_cost_usd"], second["provider_requests"], second["runs"]) == (
        first["known_cost_usd"], first["provider_requests"], 2)
    assert second["wall_seconds"] == pytest.approx(first["wall_seconds"])


def test_wall_ceiling_and_dry_run_and_ledger_subcommand(tmp_path, scripts, capsys):
    """The dry run charges each would-be trial its full reservation; the real
    run charges launcher-measured wall time, so the second trial is refused
    once any time has been used."""
    plan_path = _plan(tmp_path, [_trial(scripts, f"w{i}", "local", cost=None, wall=99.9) for i in (1, 2)],
                      {"local": {"cost_usd": None, "wall_seconds": 100.0}})
    plan = experiment_batch.load_plan(plan_path)
    preview = experiment_batch.run_plan(plan, dry_run=True)
    assert [d["event"] for d in preview] == ["would_launch", "refused"]
    assert not (tmp_path / "batch").exists() and not (tmp_path / "runs").exists()
    experiment_batch.main(["ledger", "--plan", str(plan_path), "--json"])
    ledger = json.loads(capsys.readouterr().out)
    assert ledger["totals"]["overall"]["outcomes"]["not_run"] == 2
    experiment_batch.main(["run", "--plan", str(plan_path)])
    out = capsys.readouterr().out
    assert "w1: finished 0" in out and "w2: refused wall_ceiling" in out
    assert "max request 200 in" in out and "300 in / 30 out cumulative" in out
    experiment_batch.main(["ledger", "--batch-dir", str(tmp_path / "batch"), "--json"])
    outcomes = json.loads(capsys.readouterr().out)["totals"]["overall"]["outcomes"]
    assert (outcomes["committed"], outcomes["not_run"]) == (1, 1)


def test_batch_totals_keep_outcomes_distinct_and_unknown_cost_unknown(tmp_path):
    missing = read_run_resources(tmp_path / "never")
    assert missing.outcome == "not_run" and missing.cost_known and missing.total_cost_usd == 0.0
    crashed = tmp_path / "crashed"
    crashed.mkdir()
    (crashed / "stderr.log").write_text("Traceback ...\n")
    lost = read_run_resources(crashed)
    # Launched but left no summary or journal: its effort is not known to be zero.
    assert lost.outcome == "abandoned" and not lost.history_certified and lost.total_cost_usd is None
    totals = batch_totals([("x", missing), ("x", lost), ("y", missing)])
    assert totals["arms"]["x"]["outcomes"] == {**dict.fromkeys(OUTCOMES, 0), "not_run": 1, "abandoned": 1}
    assert totals["arms"]["x"]["total_cost_usd"] is None
    assert totals["arms"]["y"]["total_cost_usd"] == 0.0


def test_ledger_agrees_with_a_real_cli_run_and_with_its_resume_accounting(tmp_path, monkeypatch):
    """A run driven in-process through the CLI: the ledger reads what the run
    summary says, and after an abrupt loss it reads what a resume restores."""
    priced = tmp_path / "priced"
    priced.mkdir()
    _prepare(priced)
    _infer(priced, monkeypatch, "--run-id", "run-test", provider=Scripted(cost=0.25))
    usage = _summary(priced)["usage"]
    run = read_run_resources(priced)
    assert (run.turns, run.tool_calls, run.known_cost_usd, run.unknown_cost_requests) == (
        usage["turns"], usage["tool_calls"], usage["reported_cost_usd"], usage["responses_without_cost"])
    assert run.elapsed_seconds == pytest.approx(usage["elapsed_seconds"])
    assert run.usage_accounting_version == usage["usage_accounting_version"] == "abrupt-loss-v1"

    lost = tmp_path / "lost"
    lost.mkdir()
    _crash(lost, monkeypatch, Scripted(crash_node="X"), "--max-total-turns", "2")
    before = read_run_resources(lost)
    with pytest.raises(SystemExit):
        _infer(lost, monkeypatch, "--resume", "--max-total-turns", "2", provider=Scripted())
    restored = _summary(lost)["usage"]
    assert (before.turns, before.unrecorded_requests, before.unknown_cost_requests) == (
        restored["turns"], restored["unrecorded_requests"], restored["responses_without_cost"]) == (2, 2, 2)
    assert (before.history_complete, before.effort_counts_known) == (
        restored["history_complete"], restored["effort_counts_known"]) == (False, True)
    after = read_run_resources(lost)
    assert after.outcome == "interrupted" and after.turns == 2 and after.total_cost_usd is None
