"""What `schema_version` promises, and what the per-record digest promises.

The literal is bumped when a reader must behave differently, never merely
because fields were added with defaults. These tests hold both halves of that
rule in place: additive drift stays legible without a bump, and a later bump
would not strand the 2.0 files that already exist.
"""

from __future__ import annotations

from pathlib import Path

from cognate_reconstruction import cli
from cognate_reconstruction.agent.schemas import CommittedReconstruction
from cognate_reconstruction.agent.trajectory import (
    INVENTORY_SCHEMA_VERSION,
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


def test_widening_the_version_literal_keeps_existing_files_loadable() -> None:
    """The constraint, now exercised for real rather than in a subclass.

    Bumping later is trivial; un-bumping after files exist in the wild is not.
    The bump is therefore only ever additive to the readable set: a 2.0 record
    written before the per-set commit protocol existed must still load, must
    still say 2.0, and must keep the verdict it already had, under a reader that
    also accepts 3.0.

    This test was written by prompt 05 against a hypothetical `"2.1"` to prove
    the widening it deliberately declined to perform. It is exercised here with
    the real `"3.0"`.
    """
    line = REAL_PRE_CHANGE_TRAJECTORY.read_text(encoding="utf-8").strip()
    loaded = AgentTrajectory.model_validate_json(line)
    assert loaded.schema_version == "2.0"
    assert loaded.node_id == _pre_change().node_id
    # And the new version is genuinely readable too, so the widening is real
    # rather than an unexercised annotation.
    assert (
        AgentTrajectory.model_validate_json(
            loaded.model_copy(
                update={"schema_version": INVENTORY_SCHEMA_VERSION}
            ).model_dump_json(exclude_computed_fields=True)
        ).schema_version
        == "3.0"
    )


def test_the_pre_change_record_keeps_the_verdict_it_already_had() -> None:
    """The union type must not move an existing record across the gate.

    `committed_reconstruction` is now a union, and the smart union has to resolve
    a 2.0 record to `CommittedReconstruction` rather than to the inventory shape.
    If it did not, `committed_no_op_rule_count` would read 0 for the wrong
    reason and the workflow conditions would dispatch down the inventory branch —
    which is exactly the silent loosening `docs/proto_inventory_design.md` §12.2
    is about.
    """
    record = _pre_change()
    assert isinstance(record.committed_reconstruction, CommittedReconstruction)
    assert record.commit_shape == "rules"
    assert record.high_quality is True
    assert record.high_quality_failure_reasons == ()


def test_a_mixed_archive_reports_how_far_the_migration_has_got() -> None:
    """`commit_shapes` is the migration's daily progress signal."""
    old = _pre_change()
    summary = cli._trajectory_summary((old, old))
    assert summary["commit_shapes"] == {"rules": 2}
