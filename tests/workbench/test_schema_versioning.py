"""What `schema_version` promises, and what the per-record digest promises.

The literal is bumped when a reader must behave differently, never merely
because fields were added with defaults. These tests hold both halves of that
rule in place: additive drift stays legible without a bump, and a later bump
would not strand the 2.0 files that already exist.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from cognate_reconstruction import cli
from cognate_reconstruction.agent.trajectory import (
    TRAJECTORY_SCHEMA_VERSION,
    AgentTrajectory,
    TrajectoryDatasetBuilder,
)

REAL_PRE_CHANGE_TRAJECTORY = (
    Path(__file__).parent / "fixtures" / "trajectory_real_pre_change.jsonl"
)


def _pre_change() -> AgentTrajectory:
    return TrajectoryDatasetBuilder.read_jsonl(REAL_PRE_CHANGE_TRAJECTORY)[0]


def test_schema_variants_separate_old_records_from_current_ones() -> None:
    """A 2.0 record with the new counters and one without are distinguishable."""
    old = _pre_change()
    current_digest = cli._current_trajectory_schema_sha256()
    # Same record, restamped as if this build had written it. Only the digest
    # differs, which is exactly the distinction under test.
    current = old.model_copy(
        update={
            "trajectory_id": "trajectory:current",
            "trajectory_schema_sha256": current_digest,
        }
    )
    assert old.trajectory_schema_sha256 != current_digest
    assert old.schema_version == current.schema_version == TRAJECTORY_SCHEMA_VERSION

    summary = cli._trajectory_summary((old, current, current))
    assert summary["current_trajectory_schema_sha256"] == current_digest
    assert summary["schema_variants"] == [
        {
            "trajectory_schema_sha256": current_digest,
            "records": 2,
            "current": True,
        },
        {
            "trajectory_schema_sha256": old.trajectory_schema_sha256,
            "records": 1,
            "current": False,
        },
    ]


def test_schema_variants_report_a_wholly_outdated_file_honestly() -> None:
    """With no current record present, the reader still learns what current is."""
    old = _pre_change()
    summary = cli._trajectory_summary((old,))
    assert [variant["current"] for variant in summary["schema_variants"]] == [False]
    assert (
        summary["current_trajectory_schema_sha256"]
        != old.trajectory_schema_sha256
    )


class _WidenedTrajectory(AgentTrajectory):
    """`AgentTrajectory` as it would look after a future reader-visible bump."""

    schema_version: Literal["2.0", "2.1"] = "2.1"


def test_widening_the_version_literal_keeps_existing_files_loadable() -> None:
    """Capture the constraint before anyone needs it.

    Bumping later is trivial; un-bumping after files exist in the wild is not.
    The bump is therefore only ever additive to the readable set: a 2.0 record
    written today must still load, and must still say 2.0, under a reader that
    also accepts 2.1.
    """
    line = REAL_PRE_CHANGE_TRAJECTORY.read_text(encoding="utf-8").strip()
    widened = _WidenedTrajectory.model_validate_json(line)
    assert widened.schema_version == "2.0"
    assert widened.node_id == _pre_change().node_id
    # And the new version is genuinely readable too, so the widening is real
    # rather than an unexercised annotation.
    assert (
        _WidenedTrajectory.model_validate_json(
            widened.model_copy(
                update={"schema_version": "2.1"}
            ).model_dump_json(exclude_computed_fields=True)
        ).schema_version
        == "2.1"
    )
