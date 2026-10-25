#!/usr/bin/env python3
"""Serial experiment launcher with a whole-batch resource ledger.

The CLI caps bound one run; nothing bounded a batch. This launcher runs a
plan's trials strictly in order, one subprocess each, and before every trial
reads the ledger of every trial in the plan from its run directory. It
refuses (and records why) when:

  run_dir_not_empty     the run dir already has artifacts: never re-run a trial
  requires_usable       the named trial's evaluation did not report usable
  arm_cost_unknown      the arm has a request of unknown cost (or uncertified
                        history) while its ceiling limits cost
  cost_reservation_missing / cost_ceiling
                        known spend + this trial's reservation > arm ceiling
  wall_unknown / wall_reservation_missing / wall_ceiling
                        likewise for launcher-measured wall seconds

The harness checks its own cost cap only after each response, so a trial's
cost reservation must include one maximum-size response beyond its run cap.
There are no retries, seeds or reruns. Refusals are recorded, not raised.

Plan (paths relative to the plan file; argv strings may use `{python}`,
`{run_dir}` and `{batch_dir}`; subprocesses run in the plan's directory):

    {"plan_version": "r02-batch-v1", "batch_dir": "...",
     "ceilings": {"<arm>": {"cost_usd": float|null, "wall_seconds": float|null}},
     "trials": [{"trial_id": "...", "arm": "...", "run_dir": "...", "argv": [...],
                 "reservation": {"cost_usd": float|null, "wall_seconds": float|null},
                 "requires_usable": "<trial_id>"|null, "evaluate_argv": [...]|null,
                 "checkpoint_name": "checkpoint.json"}]}

`evaluate_argv` must write `<run_dir>/evaluation.json` containing
`{"stage_gate": {"usable": bool, "reason": str}, ...}`; only `stage_gate` is read.

Writes `batch_dir/batch_events.jsonl` (append-only decisions) and
`batch_dir/batch_ledger.json` (snapshot after every trial).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import _bootstrap  # noqa: F401

from cognate_reconstruction.benchmarks.ledger import batch_totals, read_run_resources

PLAN_VERSION = "r02-batch-v1"
LEDGER_VERSION = "r02-ledger-v1"
EVENTS_FILE = "batch_events.jsonl"
LEDGER_FILE = "batch_ledger.json"
EVALUATION_FILE = "evaluation.json"


def load_plan(path: Path) -> dict:
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("plan_version") != PLAN_VERSION:
        raise ValueError(f"plan_version must be {PLAN_VERSION!r}")
    base = path.resolve().parent
    plan["_base"] = base
    plan["_batch_dir"] = (base / plan["batch_dir"]).resolve()
    seen: list[str] = []
    for trial in plan["trials"]:
        tid = trial["trial_id"]
        if tid in seen:
            raise ValueError(f"duplicate trial_id {tid!r}")
        if trial["arm"] not in plan["ceilings"]:
            raise ValueError(f"trial {tid!r}: arm {trial['arm']!r} has no ceilings entry")
        required = trial.get("requires_usable")
        if required is not None and required not in seen:
            raise ValueError(f"trial {tid!r}: requires_usable {required!r} is not an earlier trial")
        trial["_run_dir"] = (base / trial["run_dir"]).resolve()
        seen.append(tid)
    if len({str(t["_run_dir"]) for t in plan["trials"]}) != len(plan["trials"]):
        raise ValueError("trials must not share a run_dir")
    return plan


def plan_from_events(batch_dir: Path) -> dict:
    """The trials a batch directory's event log names, for `ledger --batch-dir`.

    Ceilings are not recorded in events, so this reads resources only.
    """
    batch_dir = batch_dir.resolve()
    trials: dict[str, dict] = {}
    for event in _events(batch_dir):
        if "run_dir" not in event:
            continue
        trial = trials.setdefault(event["trial_id"], {"trial_id": event["trial_id"], "arm": event["arm"],
                                                      "_run_dir": Path(event["run_dir"])})
        if event.get("checkpoint_name"):
            trial["checkpoint_name"] = event["checkpoint_name"]
    return {"_batch_dir": batch_dir, "ceilings": {}, "trials": list(trials.values())}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _append_event(batch_dir: Path, record: dict) -> None:
    batch_dir.mkdir(parents=True, exist_ok=True)
    with (batch_dir / EVENTS_FILE).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"recorded_at": _now(), **record}, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _events(batch_dir: Path) -> list[dict]:
    path = batch_dir / EVENTS_FILE
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except ValueError:
            continue  # a torn last line from an interrupted launcher
    return records


def _stage_gate(run_dir: Path) -> dict | None:
    try:
        gate = json.loads((run_dir / EVALUATION_FILE).read_text(encoding="utf-8")).get("stage_gate")
    except (OSError, ValueError, AttributeError):
        return None
    if not isinstance(gate, dict) or not isinstance(gate.get("usable"), bool):
        return None
    return gate


def build_ledger(plan: dict) -> dict:
    """Read every trial's run dir and the launcher's own wall-clock records.

    A trial with artifacts but no launcher `finished` record (the launcher
    died mid-trial, or the dir predates it) has unknown wall time: its run's
    elapsed lower bound is reported and `wall_known` is False.
    """
    finished: dict[str, dict] = {}
    for event in _events(plan["_batch_dir"]):
        if event.get("event") in ("finished", "launcher_interrupted"):
            finished.setdefault(event["trial_id"], event)
    trials, runs, ledger_errors = [], [], []
    for trial in plan["trials"]:
        run_dir = trial["_run_dir"]
        entry = {"trial_id": trial["trial_id"], "arm": trial["arm"], "run_dir": str(run_dir)}
        try:
            resources = read_run_resources(run_dir, trial.get("checkpoint_name", "checkpoint.json"))
        except ValueError as error:
            ledger_errors.append(f"{trial['trial_id']}: {error}")
            entry.update(ledger_error=str(error), wall_seconds=None, wall_known=False)
            trials.append(entry)
            continue
        record = finished.get(trial["trial_id"])
        if not resources.present:
            wall, wall_known = 0.0, True
        elif record is not None and record.get("event") == "finished":
            wall, wall_known = float(record["wall_seconds"]), True
        else:
            wall, wall_known = (record or {}).get("wall_seconds", resources.elapsed_seconds), False
        entry.update(wall_seconds=wall, wall_known=wall_known,
                     exit_code=(record or {}).get("exit_code"), stage_gate=_stage_gate(run_dir),
                     resources=resources.as_dict())
        trials.append(entry)
        runs.append((trial["arm"], resources))
    totals = batch_totals(runs)
    for group, members in [("overall", trials), *((arm, [t for t in trials if t["arm"] == arm])
                                                    for arm in sorted({t["arm"] for t in trials} | set(plan["ceilings"])))]:
        target = totals["overall"] if group == "overall" else totals["arms"].setdefault(group, batch_totals([])["overall"])
        target["wall_seconds"] = sum(t["wall_seconds"] or 0.0 for t in members)
        target["wall_known"] = all(t["wall_known"] for t in members)
        target["ledger_errors"] = sum("ledger_error" in t for t in members)
    return {"ledger_version": LEDGER_VERSION, "written_at": _now(), "ceilings": plan["ceilings"],
            "trials": trials, "totals": totals, "ledger_errors": ledger_errors}


def write_ledger(plan: dict, ledger: dict) -> Path:
    path = plan["_batch_dir"] / LEDGER_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def refusal(plan: dict, trial: dict, ledger: dict, *, pending: dict | None = None) -> str | None:
    """Why this trial must not launch now, or None. `pending` adds dry-run
    reservations of earlier trials that would have launched."""
    run_dir = trial["_run_dir"]
    if run_dir.exists() and any(run_dir.iterdir()):
        return "run_dir_not_empty: trials are never re-run or overwritten"
    required = trial.get("requires_usable")
    if required is not None:
        gate = next((t.get("stage_gate") for t in ledger["trials"] if t["trial_id"] == required), None)
        if gate is None or gate["usable"] is not True:
            why = "no evaluation" if gate is None else gate.get("reason", "")
            return f"requires_usable: {required} is not usable ({why})"
    arm = trial["arm"]
    totals = ledger["totals"]["arms"][arm]
    if totals["ledger_errors"]:
        return f"ledger_unreadable: {arm} has an unreadable run history"
    ceiling = plan["ceilings"][arm]
    reservation = trial.get("reservation") or {}
    extra = (pending or {}).get(arm, {"cost_usd": 0.0, "wall_seconds": 0.0})
    if ceiling.get("cost_usd") is not None:
        if not totals["cost_known"]:
            return (f"arm_cost_unknown: {arm} has {totals['unknown_cost_requests']} request(s) of "
                    "unknown cost or uncertified history; known spend "
                    f"${totals['known_cost_usd']:.4f} is only a lower bound")
        if reservation.get("cost_usd") is None:
            return "cost_reservation_missing: the arm has a cost ceiling"
        spent = totals["known_cost_usd"] + extra["cost_usd"]
        if spent + reservation["cost_usd"] > ceiling["cost_usd"]:
            return (f"cost_ceiling: spent ${spent:.4f} + reserved ${reservation['cost_usd']:.4f} "
                    f"> ceiling ${ceiling['cost_usd']:.4f}")
    if ceiling.get("wall_seconds") is not None:
        if not totals["wall_known"]:
            return f"wall_unknown: {arm} has a trial without launcher-measured wall time"
        if reservation.get("wall_seconds") is None:
            return "wall_reservation_missing: the arm has a wall-time ceiling"
        used = totals["wall_seconds"] + extra["wall_seconds"]
        if used + reservation["wall_seconds"] > ceiling["wall_seconds"]:
            return (f"wall_ceiling: used {used:.1f}s + reserved {reservation['wall_seconds']:.1f}s "
                    f"> ceiling {ceiling['wall_seconds']:.1f}s")
    return None


def _argv(plan: dict, trial: dict, argv: list[str]) -> list[str]:
    values = {"{python}": sys.executable, "{run_dir}": str(trial["_run_dir"]),
              "{batch_dir}": str(plan["_batch_dir"])}
    out = []
    for arg in argv:
        for key, value in values.items():
            arg = arg.replace(key, value)
        out.append(arg)
    return out


def _run(argv: list[str], cwd: Path, run_dir: Path, prefix: str) -> int:
    with (run_dir / f"{prefix}stdout.log").open("ab") as out, (run_dir / f"{prefix}stderr.log").open("ab") as err:
        return subprocess.run(argv, cwd=cwd, stdout=out, stderr=err, check=False).returncode


def run_plan(plan: dict, *, dry_run: bool = False) -> list[dict]:
    """Run the plan once, in order; returns this invocation's decisions."""
    batch_dir = plan["_batch_dir"]
    decisions = []
    pending: dict[str, dict] = {}
    for trial in plan["trials"]:
        ledger = build_ledger(plan)
        reason = refusal(plan, trial, ledger, pending=pending if dry_run else None)
        base = {"trial_id": trial["trial_id"], "arm": trial["arm"], "run_dir": str(trial["_run_dir"])}
        if reason is not None:
            decision = {**base, "event": "refused", "reason": reason}
            decisions.append(decision)
            if not dry_run:
                _append_event(batch_dir, decision)
            continue
        if dry_run:
            reservation = trial.get("reservation") or {}
            arm = pending.setdefault(trial["arm"], {"cost_usd": 0.0, "wall_seconds": 0.0})
            for key in arm:
                arm[key] += reservation.get(key) or 0.0
            decisions.append({**base, "event": "would_launch"})
            continue
        run_dir = trial["_run_dir"]
        run_dir.mkdir(parents=True, exist_ok=True)
        argv = _argv(plan, trial, trial["argv"])
        _append_event(batch_dir, {**base, "event": "launched", "argv": argv,
                                  "checkpoint_name": trial.get("checkpoint_name", "checkpoint.json")})
        started = time.monotonic()
        try:
            exit_code = _run(argv, plan["_base"], run_dir, "")
        except KeyboardInterrupt:
            _append_event(batch_dir, {**base, "event": "launcher_interrupted",
                                      "wall_seconds": time.monotonic() - started})
            write_ledger(plan, build_ledger(plan))
            raise
        decision = {**base, "event": "finished", "exit_code": exit_code,
                    "wall_seconds": time.monotonic() - started}
        _append_event(batch_dir, decision)
        decisions.append(decision)
        if trial.get("evaluate_argv"):
            evaluate_exit = _run(_argv(plan, trial, trial["evaluate_argv"]), plan["_base"], run_dir, "evaluate.")
            gate = _stage_gate(run_dir)
            evaluated = {**base, "event": "evaluated", "exit_code": evaluate_exit,
                         "usable": bool(gate and gate["usable"]),
                         "reason": gate.get("reason") if gate else f"no valid stage_gate in {EVALUATION_FILE}"}
            _append_event(batch_dir, evaluated)
            decisions.append(evaluated)
        write_ledger(plan, build_ledger(plan))
    if not dry_run:
        write_ledger(plan, build_ledger(plan))
    return decisions


def _text(ledger: dict) -> str:
    lines = []
    groups = [("overall", ledger["totals"]["overall"]), *sorted(ledger["totals"]["arms"].items())]
    for name, totals in groups:
        cost = (f"${totals['total_cost_usd']:.4f}" if totals["total_cost_usd"] is not None else
                f"UNKNOWN (known ${totals['known_cost_usd']:.4f} + {totals['unknown_cost_requests']} "
                "request(s) of unknown cost)")
        outcomes = ", ".join(f"{k} {v}" for k, v in totals["outcomes"].items() if v) or "none"
        lines += [
            f"{name}: {totals['runs']} trial(s); outcomes: {outcomes}",
            f"  cost {cost}; {totals['provider_requests']} request(s), {totals['turns']} turn(s), "
            f"{totals['tool_calls']} tool call(s)",
            f"  wall {totals['wall_seconds']:.1f}s{'' if totals['wall_known'] else ' (incomplete)'}; "
            f"run elapsed {'>= ' if totals['elapsed_is_lower_bound'] else ''}{totals['elapsed_seconds']:.1f}s",
            f"  tokens: {totals['input_tokens']} in / {totals['output_tokens']} out cumulative; "
            f"max request {totals['max_request_input_tokens']} in, max response "
            f"{totals['max_response_output_tokens']} out",
        ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run the plan's trials in order")
    run.add_argument("--plan", required=True, type=Path)
    run.add_argument("--dry-run", action="store_true", help="report decisions; launch and write nothing")
    show = commands.add_parser("ledger", help="write and print the ledger without running anything")
    source = show.add_mutually_exclusive_group(required=True)
    source.add_argument("--plan", type=Path)
    source.add_argument("--batch-dir", type=Path, help="read trials from batch_events.jsonl")
    show.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    plan = load_plan(args.plan) if args.plan else plan_from_events(args.batch_dir)
    if args.command == "run":
        for decision in run_plan(plan, dry_run=args.dry_run):
            detail = decision.get("reason") or decision.get("exit_code", "")
            print(f"{decision['trial_id']}: {decision['event']} {detail}".rstrip())
        if not args.dry_run:
            print(_text(build_ledger(plan)))
        return 0
    ledger = build_ledger(plan)
    write_ledger(plan, ledger)
    print(json.dumps(ledger, indent=2, sort_keys=True) if args.json else _text(ledger))
    return 0


if __name__ == "__main__":
    sys.exit(main())
