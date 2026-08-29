"""A committed node can be a verbatim copy of its child, and nothing said so.

`benchmarks/sweep.py` drops an evaluation whose node fell back, because a
fallback node's beam is the harness's identity commit. It has no opinion about a
node that reached the same place through a *successful* commit. Measured across
the banked sweeps, that happens: on `synthetic_hard-after-r2` every one of the
fifteen committed nodes reproduced another lexicon form for form, and those
evaluations are the ones §7.7 read condition 6 from.

`tools/identity_commit_probe.py` reports it. This pins what it reports.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE = REPO_ROOT / "tools" / "identity_commit_probe.py"


def _form(concept: str, segments: list[str]) -> dict:
    return {"concept_id": concept, "segments": segments}


def _lexicon(variety: str, forms: list[dict]) -> dict:
    return {"variety_id": variety, "name": variety, "forms": forms}


def _write_case(tmp_path: Path) -> tuple[Path, Path]:
    """One payload, one run: a copying node, an honest node, a fallback node."""
    payload = {
        "lexicons": [
            _lexicon("d1", [_form("a", ["p", "a"]), _form("b", ["t", "u"])]),
            _lexicon("d2", [_form("a", ["b", "a"]), _form("b", ["d", "u"])]),
        ],
        "concepts": [{"concept_id": "a"}, {"concept_id": "b"}],
        "newick": "((d1,d2)copier,(d1,d2)honest)root;",
        "historical_form_bindings": [
            {"node_id": "copier", "role": "target", "forms": []},
            {"node_id": "honest", "role": "target", "forms": []},
        ],
    }
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")

    result = {
        "internal_nodes": [
            # Byte-identical to d1. This is the case the probe exists for.
            {
                "node_id": "copier",
                "best_lexicon": _lexicon(
                    "copier", [_form("a", ["p", "a"]), _form("b", ["t", "u"])]
                ),
            },
            # Reconstructs something neither daughter attests.
            {
                "node_id": "honest",
                "best_lexicon": _lexicon(
                    "honest", [_form("a", ["ᵐb", "a"]), _form("b", ["ⁿd", "u"])]
                ),
            },
            # Fell back, so it is out of scope however identical it looks.
            {
                "node_id": "walked_over",
                "best_lexicon": _lexicon(
                    "walked_over", [_form("a", ["p", "a"]), _form("b", ["t", "u"])]
                ),
            },
        ],
        "node_failures": [{"node_id": "walked_over"}],
        "historical_target_evaluations": [
            {"node_id": "copier", "top_exact_rate": 0.75},
            {"node_id": "honest", "top_exact_rate": 0.25},
        ],
    }
    run_dir = tmp_path / "seed-00"
    run_dir.mkdir()
    (run_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
    return payload_path, run_dir


def _run(payload_path: Path, run_dir: Path, *extra: str) -> dict:
    completed = subprocess.run(
        [sys.executable, str(PROBE), str(payload_path), str(run_dir), "--json", *extra],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout)


def test_a_node_identical_to_a_daughter_is_reported_as_a_leaf_copy(
    tmp_path: Path,
) -> None:
    payload_path, run_dir = _write_case(tmp_path)
    rows = {row["node_id"]: row for row in _run(payload_path, run_dir)["rows"]}
    assert rows["copier"]["leaf_copy"] is True
    assert rows["copier"]["closest_leaf"] == "d1"
    assert rows["copier"]["leaf_agreement"] == 1.0


def test_a_node_that_reconstructs_something_new_is_not_flagged(
    tmp_path: Path,
) -> None:
    payload_path, run_dir = _write_case(tmp_path)
    rows = {row["node_id"]: row for row in _run(payload_path, run_dir)["rows"]}
    assert rows["honest"]["leaf_copy"] is False
    assert rows["honest"]["node_copy"] is False
    assert rows["honest"]["leaf_agreement"] == 0.0


def test_a_fallback_node_is_out_of_scope_however_identical_it_is(
    tmp_path: Path,
) -> None:
    """The sweep already excludes it, so counting it here would double-count."""
    payload_path, run_dir = _write_case(tmp_path)
    node_ids = {row["node_id"] for row in _run(payload_path, run_dir)["rows"]}
    assert "walked_over" not in node_ids


def test_a_copy_bound_to_gold_is_named_as_entering_the_scored_set(
    tmp_path: Path,
) -> None:
    """The whole point: this accuracy number rests on a copy of a daughter."""
    payload_path, run_dir = _write_case(tmp_path)
    rows = {row["node_id"]: row for row in _run(payload_path, run_dir)["rows"]}
    assert rows["copier"]["is_gold_node"] is True
    assert rows["copier"]["scored"] is True
    assert rows["copier"]["scored_top_exact_rate"] == 0.75


def test_the_threshold_is_a_knob_and_verbatim_is_the_default(
    tmp_path: Path,
) -> None:
    """A near-copy is not a copy at 1.0, and is one when the bar is lowered."""
    payload_path, run_dir = _write_case(tmp_path)
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    # Make `copier` agree with d1 on one concept of two.
    result["internal_nodes"][0]["best_lexicon"]["forms"][1]["segments"] = ["q", "u"]
    (run_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")

    strict = {row["node_id"]: row for row in _run(payload_path, run_dir)["rows"]}
    assert strict["copier"]["leaf_copy"] is False
    assert strict["copier"]["leaf_agreement"] == 0.5

    loose = {
        row["node_id"]: row
        for row in _run(payload_path, run_dir, "--threshold", "0.5")["rows"]
    }
    assert loose["copier"]["leaf_copy"] is True
