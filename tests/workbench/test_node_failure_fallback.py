"""One dead node must not discard the nodes that worked.

A 7-node benchmark failed three times without ever producing an evaluable
result: each run died at one node and the exception propagated before
`result.json` was written, taking three clean commits with it. The traversal
now records the failure, commits an identity parent so the beam is defined, and
continues — while making it impossible to read the outcome as a reconstruction.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path

import pytest

from cognate_reconstruction import cli
from cognate_reconstruction.agent.orchestrator import (
    AgentOrchestrator,
    RunBudgetExceeded,
)
from cognate_reconstruction.agent.reconstructor import (
    AgenticNodeReconstructor,
    TooManyNodeFailuresError,
)
from cognate_reconstruction.agent.schemas import (
    LLMMessage,
    LLMToolCall,
    LLMToolDefinition,
    MessageRole,
)
from cognate_reconstruction.agent.service import ReconstructionService
from cognate_reconstruction.agent.trajectory import (
    JsonlTrajectorySink,
    TrajectoryDatasetBuilder,
)
from cognate_reconstruction.ingestion import ingest_payload
from cognate_reconstruction.inspect_run import build_report, load_run, render_text
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm
from cognate_reconstruction.traversal import CheckpointStore, FamilyCheckpoint


def _lexicon(variety_id: str, initial: str = "p") -> LanguageLexicon:
    return LanguageLexicon(
        variety_id=variety_id,
        name=variety_id,
        forms=(
            LexicalForm(
                form_id=f"{variety_id}:water",
                variety_id=variety_id,
                concept_id="water",
                segments=(initial, "a"),
            ),
        ),
    )


def _payload() -> WorkbenchPayload:
    """Two internal nodes: X reconstructs (A,B), then ROOT reconstructs (X,C)."""
    return WorkbenchPayload(
        lexicons=(_lexicon("A", "p"), _lexicon("B", "f"), _lexicon("C", "f")),
        newick="((A,B)X,C)ROOT;",
    )


def _node_id(messages: Sequence[LLMMessage]) -> str:
    match = re.search(r'"node_id":\s*"([^"]+)"', messages[1].content or "")
    assert match is not None
    return match.group(1)


class CommitProvider:
    """Commit an identity reconstruction at every node."""

    model = "scripted/commit"

    def __init__(self, *, fail_at: tuple[str, ...] = (), error: type[Exception] = RuntimeError) -> None:
        self.fail_at = fail_at
        self.error = error
        self.nodes: list[str] = []

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[LLMToolDefinition],
        *,
        tool_choice: str = "auto",
        max_tokens_override: int | None = None,
    ) -> LLMMessage:
        assert tools
        node_id = _node_id(messages)
        self.nodes.append(node_id)
        if node_id in self.fail_at:
            raise self.error(f"the session at {node_id} went nowhere")
        return LLMMessage(
            role=MessageRole.ASSISTANT,
            tool_calls=(
                LLMToolCall(
                    call_id=f"commit:{node_id}",
                    name="commit_reconstruction",
                    arguments={
                        "node_id": node_id,
                        "rules": [],
                        "anomalies": [],
                        "summary": f"Identity reconstruction at {node_id}.",
                    },
                ),
            ),
        )


def _service(
    provider,
    trajectory_path: Path | None = None,
    **kwargs,
) -> ReconstructionService:
    return ReconstructionService(
        AgenticNodeReconstructor(
            AgentOrchestrator(
                provider,
                instructions="Commit.",
                max_retries=0,
                trajectory_sink=(
                    JsonlTrajectorySink(trajectory_path)
                    if trajectory_path is not None
                    else None
                ),
                run_id="run-test",
                configuration_sha256="config-hash",
            ),
            **kwargs,
        )
    )


def test_a_failed_node_no_longer_discards_the_run(tmp_path) -> None:
    dataset = ingest_payload(_payload())
    provider = CommitProvider(fail_at=("X",))
    result = _service(provider, tmp_path / "trajectories.jsonl").reconstruct_family(
        dataset
    )
    # The walk reached the root, which is the whole point.
    assert [node.node_id for node in result.internal_nodes] == ["X", "ROOT"]
    assert [failure.node_id for failure in result.node_failures] == ["X"]
    failure = result.node_failures[0]
    assert failure.error_type == "RuntimeError"
    assert "went nowhere" in failure.reason
    assert failure.child_node_ids == ("A", "B")
    # The failed session's own record is named, and is in the result.
    assert failure.trajectory_id is not None
    assert {item.node_id for item in result.trajectories} == {"X", "ROOT"}
    assert [item.completed for item in result.trajectories] == [False, True]


def test_the_fallback_step_says_it_is_not_a_reconstruction(tmp_path) -> None:
    """`identity_reconstruction` means something else and is not overloaded."""
    dataset = ingest_payload(_payload())
    result = _service(CommitProvider(fail_at=("X",))).reconstruct_family(dataset)
    steps = {step.parent_node_id: step for step in result.snapshot.steps}
    assert steps["X"].diagnostics.failure_fallback is True
    # True as well, because no rule was applied — which is exactly why it could
    # not carry the distinction on its own.
    assert steps["X"].diagnostics.identity_reconstruction is True
    assert steps["ROOT"].diagnostics.failure_fallback is False
    assert steps["ROOT"].diagnostics.identity_reconstruction is True
    # The parent beam exists, which is what lets the walk continue.
    assert steps["X"].output_beam.distributions


def test_a_fallback_node_is_kept_out_of_the_checkpoint(tmp_path) -> None:
    """A resume has to re-run the node that failed, not inherit its fallback.

    And not only that node: every node above it was combined from a beam the
    failed node did not produce, so checkpointing those would freeze the
    failure into the run permanently.
    """
    dataset = ingest_payload(_payload())
    saved: list[str] = []
    _service(CommitProvider(fail_at=("X",))).reconstruct_family(
        dataset,
        on_step_complete=lambda step: saved.append(step.parent_node_id),
    )
    assert saved == []

    saved.clear()
    _service(CommitProvider(fail_at=("ROOT",))).reconstruct_family(
        dataset,
        on_step_complete=lambda step: saved.append(step.parent_node_id),
    )
    # X succeeded and is below the failure, so it is checkpointed as usual.
    assert saved == ["X"]


def test_fail_fast_restores_the_abort(tmp_path) -> None:
    dataset = ingest_payload(_payload())
    with pytest.raises(RuntimeError, match="went nowhere"):
        _service(CommitProvider(fail_at=("X",)), fail_fast=True).reconstruct_family(
            dataset
        )


def test_max_failed_nodes_stops_a_run_that_is_failing_everywhere(tmp_path) -> None:
    dataset = ingest_payload(_payload())
    with pytest.raises(TooManyNodeFailuresError) as caught:
        _service(
            CommitProvider(fail_at=("X", "ROOT")),
            max_failed_nodes=1,
        ).reconstruct_family(dataset)
    assert "2 nodes failed" in str(caught.value)
    assert [failure.node_id for failure in caught.value.failures] == ["X", "ROOT"]


def test_max_failed_nodes_zero_is_fail_fast_with_a_record(tmp_path) -> None:
    dataset = ingest_payload(_payload())
    with pytest.raises(TooManyNodeFailuresError):
        _service(
            CommitProvider(fail_at=("X",)),
            max_failed_nodes=0,
        ).reconstruct_family(dataset)


def test_a_run_budget_is_never_absorbed_into_a_fallback(tmp_path) -> None:
    """A budget stops the run; converting it into identity nodes would lie."""
    dataset = ingest_payload(_payload())
    with pytest.raises(RunBudgetExceeded):
        _service(
            CommitProvider(fail_at=("X",), error=RunBudgetExceeded)
        ).reconstruct_family(dataset)


def test_a_fallback_node_is_excluded_from_export_and_high_quality(tmp_path) -> None:
    dataset = ingest_payload(_payload())
    result = _service(CommitProvider(fail_at=("X",))).reconstruct_family(dataset)
    failed = next(item for item in result.trajectories if item.node_id == "X")
    assert failed.high_quality is False
    assert failed.high_quality_failure_reasons[0].startswith(
        "the node did not complete"
    )
    examples = TrajectoryDatasetBuilder().build(result.trajectories)
    assert [example.node_id for example in examples] == ["ROOT"]
    curated = TrajectoryDatasetBuilder().build(
        result.trajectories, high_quality_only=True
    )
    # ROOT is filtered here too, for an unrelated reason (this scripted session
    # commits without inspecting anything); what matters is that the fallback
    # node cannot reach a curated corpus.
    assert "X" not in {example.node_id for example in curated}


# --- through the CLI --------------------------------------------------------


def _infer(tmp_path: Path, monkeypatch, *extra: str, provider) -> None:
    monkeypatch.setattr(cli, "LiteLLMProvider", lambda *a, **k: provider)
    (tmp_path / "input.json").write_text(
        _payload().model_dump_json(), encoding="utf-8"
    )
    # `--run-id` is refused on resume; the checkpoint carries it instead.
    run_id = () if "--resume" in extra else ("--run-id", "run-test")
    cli.main(
        [
            "infer",
            "--input",
            str(tmp_path / "input.json"),
            "--model",
            "test-model",
            "--output",
            str(tmp_path / "result.json"),
            "--trajectories",
            str(tmp_path / "trajectories.jsonl"),
            "--events",
            str(tmp_path / "events.jsonl"),
            "--checkpoint",
            str(tmp_path / "checkpoint.json"),
            *run_id,
            "--quiet",
            *extra,
        ]
    )


def test_the_cli_writes_a_result_and_names_the_dead_node(
    tmp_path, monkeypatch, capsys
) -> None:
    _infer(tmp_path, monkeypatch, provider=CommitProvider(fail_at=("X",)))
    err = capsys.readouterr().err
    assert "FAILED NODE X: RuntimeError" in err
    # The count people quote does not include the fallback.
    assert "1 reconstructed internal nodes" in err
    result = json.loads((tmp_path / "result.json").read_text())
    assert [item["node_id"] for item in result["node_failures"]] == ["X"]
    # Nothing was checkpointed: the failure is below the root.
    assert CheckpointStore(tmp_path / "checkpoint.json").load().completed_steps == ()


def test_fail_fast_through_the_cli_writes_no_result(tmp_path, monkeypatch) -> None:
    with pytest.raises(SystemExit) as caught:
        _infer(
            tmp_path,
            monkeypatch,
            "--fail-fast",
            provider=CommitProvider(fail_at=("X",)),
        )
    assert caught.value.code == 2
    assert not (tmp_path / "result.json").exists()


def test_inspect_run_puts_the_fallback_where_it_cannot_be_missed(
    tmp_path, monkeypatch
) -> None:
    _infer(tmp_path, monkeypatch, provider=CommitProvider(fail_at=("X",)))
    report = build_report(load_run(tmp_path))
    assert report.fallback_nodes == ("X",)
    text = render_text(report)
    # Above the per-node detail, in the header, and on the node itself.
    assert "1 NODE(S) WERE NOT RECONSTRUCTED: X" in text
    assert text.index("WERE NOT RECONSTRUCTED") < text.index("NODE X")
    assert "FAILED - IDENTITY FALLBACK" in text
    assert "1 reconstructed internal node(s)" in text
    node = next(item for item in report.nodes if item.node_id == "X")
    assert node.failure_fallback is True
    assert next(item for item in report.nodes if item.node_id == "ROOT").failure_fallback is False


def test_a_resumed_run_re_runs_the_node_that_failed(tmp_path, monkeypatch) -> None:
    """The recovery the stall invites, end to end.

    The give-up thresholds are no longer hashed, so the operator can loosen
    exactly the flag the failure told them to loosen and resume.
    """
    _infer(tmp_path, monkeypatch, provider=CommitProvider(fail_at=("X",)))
    assert CheckpointStore(tmp_path / "checkpoint.json").load().completed_steps == ()

    recovered = CommitProvider()
    _infer(
        tmp_path,
        monkeypatch,
        "--resume",
        "--max-repeated-tool-failures",
        "6",
        "--stall-window-calls",
        "24",
        provider=recovered,
    )
    assert recovered.nodes == ["X", "ROOT"]
    result = json.loads((tmp_path / "result.json").read_text())
    assert result["node_failures"] == []
    assert [
        step.parent_node_id
        for step in CheckpointStore(tmp_path / "checkpoint.json").load().completed_steps
    ] == ["X", "ROOT"]


def test_a_run_id_is_required_to_stay_stable_across_that_resume(
    tmp_path, monkeypatch
) -> None:
    """Guard the seeding filter: the resumed run keeps the checkpoint's run ID."""
    _infer(tmp_path, monkeypatch, provider=CommitProvider(fail_at=("ROOT",)))
    trajectories = TrajectoryDatasetBuilder.read_jsonl(
        tmp_path / "trajectories.jsonl"
    )
    assert {item.run_id for item in trajectories} == {"run-test"}
    checkpoint = CheckpointStore(tmp_path / "checkpoint.json").load()
    assert checkpoint.run_id == "run-test"
    assert isinstance(checkpoint, FamilyCheckpoint)
