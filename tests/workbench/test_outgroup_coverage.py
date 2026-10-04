"""Out-group evidence is retrieved once and committed against fifteen times.

§7.17 read the browsing tools' 2% share of all calls as the model not reaching
for material outside its own group. Per *node* that reading is wrong — on the
banked Polynesian sweep every non-root node called `polarize` and every one got
an out-group back. Per *correspondence* it is worse than 2% suggested: a call
covers one correspondence and a node commits many, so most committed sets never
had anything outside the group retrieved for them.

`tools/outgroup_coverage.py` reports both readings from one walk. This pins what
it reports, and pins the root exclusion, which is the part a reader would
otherwise get backwards: nothing lies outside the root, so a root that retrieved
no out-group retrieved everything there was.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE = REPO_ROOT / "tools" / "outgroup_coverage.py"


def _polarize_message(relations: list[str]) -> dict:
    """A tool message shaped like the real envelope: payload under `result`."""
    return {
        "role": "tool",
        "name": "polarize",
        "tool_call_id": "1",
        "tool_calls": [],
        "content": json.dumps(
            {"result": {"nodes": [{"relation": r} for r in relations]}}
        ),
    }


def _record(node_id: str, *, units: int, messages: list[dict], calls: int) -> dict:
    return {
        "node_id": node_id,
        "messages": messages,
        "metrics": {"committed_rule_count": units, "tool_call_count": calls},
        "committed_reconstruction": {"commit_shape": "inventory"},
    }


def _write_case(tmp_path: Path) -> Path:
    run_dir = tmp_path / "seed-00"
    run_dir.mkdir()
    (run_dir / "result.json").write_text(
        json.dumps(
            {
                "internal_nodes": [
                    {"node_id": "inner"},
                    {"node_id": "browser"},
                    {"node_id": "root"},
                ]
            }
        ),
        encoding="utf-8",
    )
    records = [
        # Retrieved an out-group once, then committed ten sets against it.
        _record(
            "inner",
            units=10,
            calls=4,
            messages=[_polarize_message(["outgroup", "descendant"])],
        ),
        # Reached for a browsing tool as well, and committed two.
        _record(
            "browser",
            units=2,
            calls=3,
            messages=[
                _polarize_message(["outgroup"]),
                {
                    "role": "tool",
                    "name": "search_forms",
                    "tool_call_id": "2",
                    "tool_calls": [],
                    "content": "{}",
                },
            ],
        ),
        # The root. Its polarize call can only ever see descendants, and that is
        # not a failure to retrieve evidence.
        _record(
            "root",
            units=8,
            calls=2,
            messages=[_polarize_message(["descendant", "descendant"])],
        ),
    ]
    (run_dir / "trajectories.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )
    return run_dir


def _run(run_dir: Path) -> dict:
    completed = subprocess.run(
        [sys.executable, str(PROBE), str(run_dir), "--json"],
        capture_output=True,
        text=True,
        check=True,
        cwd=REPO_ROOT,
    )
    return json.loads(completed.stdout)


def test_per_node_reaching_is_reported_apart_from_per_correspondence_coverage(
    tmp_path: Path,
) -> None:
    summary = _run(_write_case(tmp_path))["summary"]
    # Two non-root nodes, both of which reached outside and both of which got
    # something back. This is the reading §7.17's 2% obscured.
    assert summary["below_the_root"] == 2
    assert summary["below_the_root_calling_polarize"] == 2
    assert summary["below_the_root_receiving_an_outgroup"] == 2
    assert summary["below_the_root_using_a_browsing_tool"] == 1
    # And the reading the script exists for: 2 calls against 12 committed units.
    assert summary["committed_units_below_the_root"] == 12
    assert summary["polarize_calls_below_the_root"] == 2
    assert summary["correspondence_coverage"] == 2 / 12


def test_the_root_is_excluded_rather_than_counted_as_a_failure(
    tmp_path: Path,
) -> None:
    """The root's 8 units and its out-groupless call must not reach the ratio.

    Nothing lies outside the root, so counting it would report the absence of
    evidence to retrieve as a failure to retrieve evidence — and it would do so
    on every run, training a reader to ignore the number.
    """
    payload = _run(_write_case(tmp_path))
    summary = payload["summary"]
    assert summary["root_records"] == 1
    assert summary["node_records"] == 3
    # 12, not 20: the root's 8 committed units are outside the denominator.
    assert summary["committed_units_below_the_root"] == 12
    root_row = next(row for row in payload["rows"] if row["is_root"])
    assert root_row["node_id"] == "root"
    assert root_row["polarize_calls"] == 1
    assert root_row["polarize_calls_with_outgroup"] == 0


def test_a_run_without_result_json_treats_every_node_as_below_the_root(
    tmp_path: Path,
) -> None:
    """The safe direction: an unknown root can only make coverage look worse.

    A seed that failed before writing `result.json` still has trajectories worth
    counting, and guessing a root from them would be inventing structure.
    """
    run_dir = _write_case(tmp_path)
    (run_dir / "result.json").unlink()
    summary = _run(run_dir)["summary"]
    assert summary["below_the_root"] == 3
    assert summary["committed_units_below_the_root"] == 20
    assert summary["correspondence_coverage"] == 3 / 20
