#!/usr/bin/env python3
"""Launch and triage the cognate-reconstruction harness.

Stdlib only. Run with any python3; the harness itself is invoked through the
`llm_reconstruction` Conda interpreter, which this script locates for you.

    python3 .claude/skills/run-cognate-reconstruction/driver.py preflight
    python3 .claude/skills/run-cognate-reconstruction/driver.py smoke
    python3 .claude/skills/run-cognate-reconstruction/driver.py run --model google/gemma-4-e4b
    python3 .claude/skills/run-cognate-reconstruction/driver.py triage --run-dir runs/<dir>

`run` writes result.json / trajectories.jsonl / events.jsonl / checkpoint.json
into a fresh run directory and then triages it.

The triage report is the point of this driver. A run that ends with
"accepted reconstruction commit" can still have burned most of its tool budget
on schema errors; `infer` alone will not tell you that.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

def find_repo() -> Path:
    """Walk up to the repo root so this file works from any skills/ location.

    The skill is checked in at both .claude/skills/... and skills/..., which sit
    at different depths; a fixed parents[N] index silently resolves to the wrong
    directory in one of them.
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists() and (
            parent / "cognate_reconstruction"
        ).is_dir():
            return parent
    raise SystemExit("cannot locate the cognate_reconstruction repo root")


REPO = find_repo()
DEFAULT_API_BASE = "http://localhost:1234/v1"
LMS_BIN = Path.home() / ".lmstudio" / "bin" / "lms"

# Tools that only read evidence. Used to judge whether a session actually
# looked at anything before committing.
INSPECTION_TOOLS = {
    "list_concepts",
    "search_forms",
    "list_available_nodes",
    "get_alignments",
}

# Rejection codes that mean the hypothesis tester did its job: the model
# proposed a sound law and the parser refused it. Everything else is protocol
# friction. Mirrors TOOL_ERROR_CODES in cognate_reconstruction/agent/
# error_codes.py, duplicated because this driver is stdlib-only.
EXPLORATORY_CODES = {"dsl-parse-error", "no-op-rule", "empty-scope"}


# --------------------------------------------------------------------------
# environment
# --------------------------------------------------------------------------


def find_python() -> str:
    """Locate the interpreter that has cognate_reconstruction installed.

    `conda run` is deliberately avoided: it fails under Claude Code's sandbox
    with "__conda_exe:6: permission denied". Calling the env's python directly
    works and is faster.
    """
    override = os.environ.get("COGNATE_PYTHON")
    if override:
        return override
    candidates = [
        Path("/opt/anaconda3/envs/llm_reconstruction/bin/python"),
        Path.home() / "miniconda3" / "envs" / "llm_reconstruction" / "bin" / "python",
        Path.home() / "anaconda3" / "envs" / "llm_reconstruction" / "bin" / "python",
    ]
    for base in (Path("/opt/anaconda3/envs"), Path.home() / "miniconda3" / "envs"):
        if base.is_dir():
            candidates.extend(sorted(base.glob("*/bin/python")))
    for candidate in candidates:
        if not candidate.exists():
            continue
        probe = subprocess.run(
            [str(candidate), "-c", "import cognate_reconstruction"],
            capture_output=True,
        )
        if probe.returncode == 0:
            return str(candidate)
    return sys.executable


def cli(python: str, *args: str) -> list[str]:
    return [python, "-m", "cognate_reconstruction.cli", *args]


def http_json(url: str, timeout: float = 8.0):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode())


def lm_studio_models(api_base: str) -> list[str]:
    payload = http_json(api_base.rstrip("/") + "/models")
    return [item["id"] for item in payload.get("data", [])]


def ensure_lm_studio(api_base: str, *, autostart: bool = True) -> list[str]:
    """Return loaded model IDs, starting the local server if it is down.

    LM Studio keeps models loaded while its OpenAI-compatible server is off by
    default, so "the model is loaded" does not mean the endpoint answers.
    """
    try:
        return lm_studio_models(api_base)
    except (urllib.error.URLError, OSError, TimeoutError):
        pass
    if not autostart or not LMS_BIN.exists():
        raise SystemExit(
            f"LM Studio is not serving {api_base}.\n"
            f"Start it with: {LMS_BIN} server start\n"
            "(or pass --api-base / use a non-LM-Studio provider)"
        )
    print(f"[driver] LM Studio not answering; running `{LMS_BIN} server start`")
    subprocess.run([str(LMS_BIN), "server", "start"], check=True)
    for _ in range(10):
        time.sleep(1)
        try:
            return lm_studio_models(api_base)
        except (urllib.error.URLError, OSError, TimeoutError):
            continue
    raise SystemExit(f"LM Studio still not answering {api_base} after start")


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------


def cmd_preflight(args: argparse.Namespace) -> int:
    python = find_python()
    ok = True

    print(f"repo            {REPO}")
    print(f"python          {python}")
    version = subprocess.run(
        [python, "-c", "import sys; print(sys.version.split()[0])"],
        capture_output=True, text=True,
    ).stdout.strip()
    print(f"python version  {version}")

    probe = subprocess.run(
        [python, "-c",
         "import cognate_reconstruction as c; print(getattr(c,'__version__','?'))"],
        capture_output=True, text=True,
    )
    if probe.returncode == 0:
        print(f"harness         {probe.stdout.strip()}")
    else:
        print("harness         NOT IMPORTABLE -- run: make install")
        ok = False

    # litellm ships no __version__ attribute; ask the package metadata instead.
    litellm = subprocess.run(
        [python, "-c",
         "from importlib.metadata import version; print(version('litellm'))"],
        capture_output=True, text=True,
    )
    if litellm.returncode == 0:
        print(f"litellm         {litellm.stdout.strip()}")
    else:
        print("litellm         MISSING -- live inference will fail; run: make install")
        ok = False

    try:
        models = ensure_lm_studio(args.api_base, autostart=not args.no_autostart)
        print(f"lm studio       {args.api_base} ({len(models)} models)")
        for model in models:
            print(f"  - {model}")
    except SystemExit as error:
        print(f"lm studio       {error}")
        ok = False

    print("\nOK" if ok else "\nPREFLIGHT FAILED")
    return 0 if ok else 1


def cmd_smoke(args: argparse.Namespace) -> int:
    """Deterministic path only. Needs no model and no network."""
    python = find_python()
    failures = 0

    # Subprocesses inherit stdout, so flush our own prints to keep the
    # interleaved output in the order a reader expects.
    print("== unit suite ==", flush=True)
    suite = subprocess.run([python, "-m", "pytest", "-q"], cwd=REPO)
    failures += suite.returncode != 0

    print("\n== CLDF fixture ingestion ==", flush=True)
    listing = subprocess.run(
        cli(python, "list-lexibank-varieties", "--dataset", "examples/lexibank_fixture"),
        cwd=REPO,
    )
    failures += listing.returncode != 0

    output = Path(args.output)
    prepare = subprocess.run(
        cli(python, "prepare-lexibank",
            "--dataset", "examples/lexibank_fixture",
            "--newick-file", "examples/lexibank_fixture/tree.nwk",
            "--output", str(output)),
        cwd=REPO,
    )
    failures += prepare.returncode != 0
    if output.exists():
        payload = json.loads(output.read_text())
        forms = sum(len(lex["forms"]) for lex in payload["lexicons"])
        print(f"\nprepared {output}: "
              f"{len(payload['lexicons'])} varieties, {forms} forms")

    print("\nSMOKE OK" if not failures else f"\nSMOKE FAILED ({failures} step(s))")
    return 1 if failures else 0


def cmd_run(args: argparse.Namespace) -> int:
    python = find_python()

    if args.preset == "lm-studio":
        models = ensure_lm_studio(args.api_base, autostart=not args.no_autostart)
        bare = args.model.removeprefix("openai/")
        if bare not in models:
            print(f"model {bare!r} is not loaded in LM Studio.\nLoaded: "
                  + ", ".join(models), file=sys.stderr)
            return 1

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", args.model.lower()).strip("-")
    run_dir = Path(args.run_dir) if args.run_dir else REPO / "runs" / f"{slug}-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    command = cli(
        python, "infer",
        "--input", args.input,
        "--model", args.model,
        "--output", str(run_dir / "result.json"),
        "--trajectories", str(run_dir / "trajectories.jsonl"),
        "--events", str(run_dir / "events.jsonl"),
        "--checkpoint", str(run_dir / "checkpoint.json"),
        "--temperature", str(args.temperature),
        "--max-turns", str(args.max_turns),
        "--max-tool-calls", str(args.max_tool_calls),
    )
    if args.preset:
        command += ["--preset", args.preset]
    if args.api_base and args.preset != "lm-studio":
        command += ["--api-base", args.api_base]
    if args.api_key_env:
        command += ["--api-key-env", args.api_key_env]
    if args.quiet:
        command += ["--quiet"]

    print(f"[driver] run dir {run_dir}")
    print(f"[driver] {' '.join(command)}\n")
    started = time.monotonic()
    log_path = run_dir / "console.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command, cwd=REPO, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        for line in process.stdout:
            log.write(line)
            if not args.quiet:
                sys.stdout.write(line)
        code = process.wait()
    elapsed = time.monotonic() - started

    print(f"\n[driver] infer exited {code} after {elapsed:.1f}s "
          f"(console log: {log_path})")
    # A nonzero exit still leaves a failed trajectory worth reading.
    triage(run_dir)
    return code


# --------------------------------------------------------------------------
# triage
# --------------------------------------------------------------------------


def error_code(error: dict) -> str:
    """The structural code the harness assigned to a rejection.

    Codes are stable across calls that repeat one mistake with different
    arguments, which is what makes them countable. Runs recorded before codes
    existed fall back to the old prose signature, which is not.
    """
    code = error.get("code")
    if code:
        return code
    return "legacy:" + error_signature(error)


def error_signature(error: dict) -> str:
    """Collapse a tool error message into a readable one-line summary."""
    kind = error.get("error_type", "?")
    message = error.get("message", "")
    fields = re.findall(r"^([A-Za-z_][\w.]*)\n\s+(.+?)\s\[type=", message, re.M)
    if fields:
        return f"{kind}: " + "; ".join(f"{name} {reason}" for name, reason in fields[:3])
    return f"{kind}: {message.splitlines()[0][:140]}" if message else kind


def error_category(code: str) -> str:
    """Classify a code, failing closed as protocol exactly as the harness does."""
    return "exploratory" if code in EXPLORATORY_CODES else "protocol"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def triage(run_dir: Path) -> None:
    run_dir = Path(run_dir)
    events = load_jsonl(run_dir / "events.jsonl")
    trajectories = load_jsonl(run_dir / "trajectories.jsonl")

    if not events:
        print(f"\nno events at {run_dir / 'events.jsonl'}")
        return

    print("\n" + "=" * 74)
    print(f"TRIAGE  {run_dir}")
    print("=" * 74)

    # ---- timeline -------------------------------------------------------
    calls = {}
    for event in events:
        if event["kind"] == "tool_call":
            calls[event["details"]["call_id"]] = {
                "name": event["message"].replace("calling tool ", ""),
                "node": event["node_id"],
            }
    for event in events:
        if event["kind"] == "tool_result":
            entry = calls.get(event["details"]["call_id"])
            if entry is None:
                continue
            result = event["details"]["result"]
            entry["ok"] = result.get("ok", False)
            entry["code"] = (
                error_code(result["error"]) if not result.get("ok") else None
            )
            entry["error"] = (
                error_signature(result["error"]) if not result.get("ok") else None
            )

    turns = [event for event in events if event["kind"] == "model_response"]
    print(f"\nTIMELINE ({len(turns)} model turns, {len(calls)} tool calls)")
    ordered = list(calls.items())
    index = 0
    for number, turn in enumerate(turns, start=1):
        usage = turn["details"].get("usage") or {}
        names = turn["details"].get("tool_names") or []
        header = (f"  turn {number:>3}  in={usage.get('input_tokens', '?'):>7} "
                  f"out={usage.get('output_tokens', '?'):>6}")
        if not names:
            print(f"{header}  (no tool call)")
            continue
        print(header)
        for _ in names:
            if index >= len(ordered):
                break
            _, entry = ordered[index]
            index += 1
            mark = "ok " if entry.get("ok") else "ERR"
            print(f"           {mark}  {entry['name']}")
            code = entry.get("code")
            if code:
                print(f"                  {code}")
            # A legacy code is the message, so printing both says it twice.
            if entry.get("error") and not str(code).startswith("legacy:"):
                print(f"                  {entry['error']}")

    # ---- failure taxonomy ----------------------------------------------
    failed = [entry for entry in calls.values() if not entry.get("ok")]
    total = len(calls)
    protocol = [
        entry for entry in failed
        if error_category(entry.get("code") or "?") == "protocol"
    ]
    print(f"\nFAILED TOOL CALLS: {len(failed)} of {total}"
          + (f"  ({100 * len(failed) / total:.0f}% of tool budget wasted)"
             if total else ""))
    if failed:
        # Only protocol failures count against high_quality. An exploratory
        # rejection is the model proposing a rule and the parser refusing it.
        print(f"  {len(protocol)} protocol, "
              f"{len(failed) - len(protocol)} exploratory")
        tally: dict[tuple[str, str], int] = {}
        variants: dict[tuple[str, str], set] = {}
        examples: dict[tuple[str, str], str] = {}
        for entry in failed:
            key = (entry["name"], entry.get("code") or "?")
            tally[key] = tally.get(key, 0) + 1
            variants.setdefault(key, set()).add(entry["error"] or "?")
            examples.setdefault(key, entry["error"] or "?")
        for (name, code), count in sorted(tally.items(), key=lambda kv: -kv[1]):
            # Distinct messages behind one code make over-collapse visible. A
            # code that keeps showing several unrelated messages is a code that
            # wants splitting; this count is the evidence for that decision.
            # Under a `legacy:` key the message *is* the key, so the spread is
            # always 1 and says nothing.
            distinct = len(variants[(name, code)])
            spread = (
                f"  ({distinct} distinct messages)"
                if distinct > 1 and not code.startswith("legacy:")
                else ""
            )
            print(f"  {count:>3}x  {name}  [{error_category(code)}]  {code}{spread}")
            if not code.startswith("legacy:"):
                print(f"        {examples[(name, code)]}")

    # ---- per-node outcome ----------------------------------------------
    print(f"\nTRAJECTORIES: {len(trajectories)}")
    for trajectory in trajectories:
        metrics = trajectory.get("metrics", {})
        step = trajectory.get("reconstruction_step") or {}
        diagnostics = step.get("diagnostics", {})
        commit = trajectory.get("committed_reconstruction") or {}
        rules = (commit.get("request") or {}).get("rules", [])
        status = "completed" if trajectory.get("completed") else "FAILED"
        print(f"\n  node {trajectory['node_id']}  [{status}]  "
              f"model={trajectory.get('model_id')}")
        if trajectory.get("failure"):
            print(f"    failure: {trajectory['failure']}")
        print(f"    turns={metrics.get('turn_count')} "
              f"tool_calls={metrics.get('tool_call_count')} "
              # absent in trajectories written before failure accounting: show
              # "n/a" rather than a zero that contradicts the taxonomy above.
              f"failed={metrics.get('failed_tool_call_count', 'n/a')} "
              # None means the record predates the exploratory/protocol split,
              # where the total stands in and the verdict is unchanged.
              f"protocol={metrics.get('protocol_failure_count', 'n/a')} "
              f"inspections={metrics.get('inspection_tool_calls')} "
              f"law_tests={metrics.get('sound_law_tests')} "
              f"cascades={metrics.get('cascade_tests')}")
        if metrics.get("tool_failures_by_type"):
            # Keyed on the structural error code, not the exception class.
            print(f"    failures_by_code={metrics['tool_failures_by_type']}")
        if metrics.get("truncated_response_count"):
            print(f"    truncated_responses={metrics['truncated_response_count']}")
        # A run that only reached a tool call because the harness intervened is
        # not the same run as a clean one; say so rather than hiding it.
        if metrics.get("forced_tool_choice_count") or metrics.get(
            "truncation_backoff_applied"
        ):
            print("    truncation_recovery "
                  f"forced_tool_choice={metrics.get('forced_tool_choice_count', 0)} "
                  f"max_tokens_backoff={metrics.get('truncation_backoff_applied', 0)}")
        print(f"    tokens in={metrics.get('input_tokens')} "
              f"out={metrics.get('output_tokens')} "
              f"duration={metrics.get('duration_seconds', 0):.1f}s")
        for rule in rules:
            print(f"    rule  {rule['dsl']!r}  scope={list(rule['source_child_ids'])} "
                  f"conf={rule['confidence']}")
        if diagnostics:
            # coverage is applied / applicable: forms that never contained the
            # target are vacuous for the rule and stay out of the denominator.
            print(f"    diagnostics  rules={diagnostics.get('rule_count')} "
                  f"coverage={diagnostics.get('rule_coverage', 0):.2f} "
                  f"applied={diagnostics.get('successful_applications')}/"
                  f"{diagnostics.get('applicable_rule_results', 'n/a')} applicable "
                  f"of {diagnostics.get('rule_results_evaluated')} evaluated "
                  f"target_absent={diagnostics.get('target_absent')} "
                  f"anomalies={diagnostics.get('anomaly_count')}")

    # ---- reconstructed forms -------------------------------------------
    result_path = run_dir / "result.json"
    if result_path.exists():
        result = json.loads(result_path.read_text())
        print("\nRECONSTRUCTED FORMS")
        for node in result.get("internal_nodes", []):
            for form in (node.get("best_lexicon") or {}).get("forms", []):
                print(f"  {node['node_id']:<20} {form['concept_id']:<16} "
                      f"{' '.join(form['segments'])}")

    # ---- quality --------------------------------------------------------
    python = find_python()
    summary = subprocess.run(
        cli(python, "summarize-trajectories",
            "--input", str(run_dir / "trajectories.jsonl")),
        cwd=REPO, capture_output=True, text=True,
    )
    if summary.returncode == 0:
        data = json.loads(summary.stdout)
        print(f"\nQUALITY  high_quality={data.get('high_quality')}/"
              f"{data.get('trajectory_count')}  "
              f"completed={data.get('completed')} failed={data.get('failed')}")
        print(f"  protocol_failure_rate={data.get('protocol_failure_rate', 0):.2f} "
              f"(threshold {data.get('max_protocol_failure_rate')}) "
              f"above_threshold="
              f"{data.get('trajectories_above_protocol_failure_rate')}")
        print(f"  failures: {data.get('total_protocol_failures')} protocol, "
              f"{data.get('total_exploratory_failures')} exploratory, "
              f"of {data.get('total_failed_tool_calls')} rejected calls")
        if data.get("tool_failures_by_type"):
            print(f"  failures_by_code={data['tool_failures_by_type']}")
        # high_quality is a workflow filter, not a linguistic grade: it now
        # counts rejected calls, but it still says nothing about correctness.
        if data.get("high_quality"):
            print("  Reminder: high_quality is a mechanical workflow filter. Read "
                  "the timeline and the committed rules before exporting.")


def cmd_triage(args: argparse.Namespace) -> int:
    triage(Path(args.run_dir))
    return 0


# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    pre = sub.add_parser("preflight", help="Check interpreter, deps, and provider.")
    pre.add_argument("--api-base", default=DEFAULT_API_BASE)
    pre.add_argument("--no-autostart", action="store_true")
    pre.set_defaults(func=cmd_preflight)

    smoke = sub.add_parser("smoke", help="Deterministic path only; no model needed.")
    smoke.add_argument("--output", default="/tmp/cognate-reconstruction-fixture.json")
    smoke.set_defaults(func=cmd_smoke)

    run = sub.add_parser("run", help="Live inference into a fresh run dir, then triage.")
    run.add_argument("--model", required=True)
    run.add_argument("--input", default="examples/reconstruction_input.json")
    run.add_argument("--run-dir")
    run.add_argument("--preset", default="lm-studio", choices=["lm-studio", ""])
    run.add_argument("--api-base", default=DEFAULT_API_BASE)
    run.add_argument("--api-key-env")
    run.add_argument("--temperature", type=float, default=0.0)
    run.add_argument("--max-turns", type=int, default=16)
    run.add_argument("--max-tool-calls", type=int, default=32)
    run.add_argument("--no-autostart", action="store_true")
    run.add_argument("--quiet", action="store_true")
    run.set_defaults(func=cmd_run)

    tri = sub.add_parser("triage", help="Report on an existing run directory.")
    tri.add_argument("--run-dir", required=True)
    tri.set_defaults(func=cmd_triage)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
