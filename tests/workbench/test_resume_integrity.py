"""What a resumed run restores, and what it refuses to resume at all.

Two halves of one problem. A resumed run must recover the hypotheses committed
at nodes it will not re-execute, and it must refuse when the inputs that decide
model behaviour are no longer the ones the checkpoint was written under.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path

import pytest

from cognate_reconstruction import cli
from cognate_reconstruction.agent.orchestrator import AgentOrchestrator
from cognate_reconstruction.agent.reconstructor import AgenticNodeReconstructor
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


class LookupThenCommitProvider:
    """Ask what node X committed, then commit; record what came back."""

    model = "scripted/lookup"

    def __init__(self, lookup_node: str = "X") -> None:
        self.lookup_node = lookup_node
        self.turns_by_node: dict[str, int] = {}
        self.retrieved: dict[str, dict] = {}
        self.lookup_errors: dict[str, str] = {}

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
        turn = self.turns_by_node.get(node_id, 0) + 1
        self.turns_by_node[node_id] = turn
        for message in messages:
            if (
                message.role is not MessageRole.TOOL
                or message.name != "get_node_reconstruction"
                or message.content is None
            ):
                continue
            body = json.loads(message.content)
            if body["ok"]:
                self.retrieved[node_id] = body["result"]["reconstruction"]
            else:
                self.lookup_errors[node_id] = body["error"]["message"]
        if turn == 1:
            return LLMMessage(
                role=MessageRole.ASSISTANT,
                tool_calls=(
                    LLMToolCall(
                        call_id=f"prior:{node_id}",
                        name="get_node_reconstruction",
                        arguments={"node_id": self.lookup_node},
                    ),
                ),
            )
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


class RuleCommitProvider:
    """Commit one real, validated rule so the seeded record has content."""

    model = "scripted/rule-commit"

    def __init__(self) -> None:
        self.turns_by_node: dict[str, int] = {}

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
        turn = self.turns_by_node.get(node_id, 0) + 1
        self.turns_by_node[node_id] = turn
        if turn == 1:
            return LLMMessage(
                role=MessageRole.ASSISTANT,
                tool_calls=(
                    LLMToolCall(
                        call_id=f"validate:{node_id}",
                        name="test_sound_law",
                        arguments={
                            "dsl": "f > p / #_",
                            "source_child_ids": ["B"],
                        },
                    ),
                ),
            )
        return LLMMessage(
            role=MessageRole.ASSISTANT,
            tool_calls=(
                LLMToolCall(
                    call_id=f"commit:{node_id}",
                    name="commit_reconstruction",
                    arguments={
                        "node_id": node_id,
                        "rules": [
                            {
                                "dsl": "f > p / #_",
                                "source_child_ids": ["B"],
                                "confidence": 0.8,
                            }
                        ],
                        "anomalies": [],
                        "summary": f"Initial p reconstructed at {node_id}.",
                    },
                ),
            ),
        )


def _service(provider, trajectory_path: Path) -> ReconstructionService:
    # `fail_fast` because these cases simulate an *interrupted* run: the node
    # that fails must stop the traversal, which is what leaves a checkpoint
    # with earlier nodes in it and nothing above them.
    return ReconstructionService(
        AgenticNodeReconstructor(
            AgentOrchestrator(
                provider,
                instructions="Commit.",
                trajectory_sink=JsonlTrajectorySink(trajectory_path),
                run_id="run-test",
                configuration_sha256="config-hash",
            ),
            fail_fast=True,
        )
    )


def _first_node_only(tmp_path: Path) -> tuple:
    """Run X to completion and stop, exactly as an interrupted run would."""
    dataset = ingest_payload(_payload())
    trajectory_path = tmp_path / "trajectories.jsonl"
    checkpoint = FamilyCheckpoint(
        run_id="run-test",
        input_sha256="input-hash",
        configuration_sha256="config-hash",
        normalized_tree_sha256="tree-hash",
    )

    class StopAfterX(RuleCommitProvider):
        def complete(self, messages, tools, **kwargs):
            if _node_id(messages) == "ROOT":
                raise RuntimeError("interrupted before ROOT")
            return super().complete(messages, tools, **kwargs)

    captured: list = []
    with pytest.raises(RuntimeError, match="interrupted"):
        _service(StopAfterX(), trajectory_path).reconstruct_family(
            dataset,
            on_step_complete=captured.append,
        )
    for step in captured:
        checkpoint = checkpoint.with_step(step)
    return dataset, checkpoint, trajectory_path


def test_a_resumed_node_can_read_what_a_checkpointed_node_committed(
    tmp_path,
) -> None:
    dataset, checkpoint, trajectory_path = _first_node_only(tmp_path)
    assert [step.parent_node_id for step in checkpoint.completed_steps] == ["X"]

    provider = LookupThenCommitProvider()
    seeds = TrajectoryDatasetBuilder.read_jsonl(trajectory_path)
    _service(provider, trajectory_path).reconstruct_family(
        dataset,
        resume_steps=checkpoint.steps_by_node,
        seed_trajectories=seeds,
    )

    assert set(provider.turns_by_node) == {"ROOT"}
    retrieved = provider.retrieved["ROOT"]
    assert retrieved["node_id"] == "X"
    assert retrieved["rules"] == [
        {"dsl": "f > p / #_", "source_child_ids": ["B"], "confidence": 0.8}
    ]
    assert retrieved["summary"] == "Initial p reconstructed at X."
    # Session-local bookkeeping stays out of the restored record, exactly as it
    # does for a node reconstructed live in this process.
    assert "validation_call_id" not in json.dumps(retrieved)


def test_without_seeding_a_resumed_node_finds_nothing(tmp_path) -> None:
    """The regression this exists to prevent, stated as its own case."""
    dataset, checkpoint, trajectory_path = _first_node_only(tmp_path)
    provider = LookupThenCommitProvider()
    _service(provider, trajectory_path).reconstruct_family(
        dataset,
        resume_steps=checkpoint.steps_by_node,
    )
    assert "ROOT" not in provider.retrieved
    assert "no committed hypothesis" in provider.lookup_errors["ROOT"]


def test_seeds_survive_the_clear_that_starts_every_family_run(tmp_path) -> None:
    """`reconstruct_family` clears prior hypotheses; seeding must outlive that.

    Seeding the reconstructor directly before the call is the tempting shape
    and is silently wiped, so the seeds are handed to `reconstruct_family`
    instead. This fails if that ordering is ever inverted.
    """
    dataset, checkpoint, trajectory_path = _first_node_only(tmp_path)
    seeds = TrajectoryDatasetBuilder.read_jsonl(trajectory_path)
    provider = LookupThenCommitProvider()
    reconstructor = AgenticNodeReconstructor(
        AgentOrchestrator(
            provider,
            instructions="Commit.",
            trajectory_sink=JsonlTrajectorySink(trajectory_path),
            run_id="run-test",
            configuration_sha256="config-hash",
        )
    )
    # Pre-seeding is the mistake: the clear at the top of the run erases it.
    assert reconstructor.seed_prior_reconstructions(seeds) == 1
    reconstructor.clear_run_results()
    assert reconstructor.prior_reconstructions == {}

    ReconstructionService(reconstructor).reconstruct_family(
        dataset,
        resume_steps=checkpoint.steps_by_node,
        seed_trajectories=seeds,
    )
    assert provider.retrieved["ROOT"]["node_id"] == "X"


def test_seeding_ignores_incomplete_trajectories(tmp_path) -> None:
    _, _, trajectory_path = _first_node_only(tmp_path)
    loaded = TrajectoryDatasetBuilder.read_jsonl(trajectory_path)
    failed = loaded[0].model_copy(
        update={
            "completed": False,
            "committed_reconstruction": None,
            "reconstruction_step": None,
            "failure": "AgentLoopLimitError: no commit",
        }
    )
    reconstructor = AgenticNodeReconstructor(
        AgentOrchestrator(
            LookupThenCommitProvider(),
            instructions="Commit.",
            run_id="run-test",
        )
    )
    assert reconstructor.seed_prior_reconstructions((failed,)) == 0
    assert reconstructor.prior_reconstructions == {}


# --- The CLI's own filters and the checkpoint hash ---------------------------


class AutoCommitProvider:
    model = "test-model"

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
                        "summary": "Identity reconstruction.",
                    },
                ),
            ),
        )


def _infer(tmp_path: Path, monkeypatch, *extra: str, provider=None) -> None:
    scripted = provider or AutoCommitProvider()
    monkeypatch.setattr(
        cli,
        "LiteLLMProvider",
        lambda *args, **kwargs: scripted,
    )
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
            "--checkpoint",
            str(tmp_path / "checkpoint.json"),
            "--quiet",
            "--no-events",
            *extra,
        ]
    )


def _prepare(tmp_path: Path) -> None:
    (tmp_path / "input.json").write_text(
        _payload().model_dump_json(), encoding="utf-8"
    )


class InterruptedFirstPassProvider(RuleCommitProvider):
    """Commit a real validated rule at X, then die before ROOT.

    The realistic way a half-finished checkpoint comes to exist, so the
    artifacts under test are the ones a real interruption leaves behind: X
    completed, ROOT written as a failed trajectory.
    """

    def complete(self, messages, tools, **kwargs):
        if _node_id(messages) == "ROOT":
            raise RuntimeError("interrupted before ROOT")
        return super().complete(messages, tools, **kwargs)


def _half_finished_checkpoint(tmp_path: Path, monkeypatch) -> FamilyCheckpoint:
    """A real CLI checkpoint left behind by a run that died at its second node."""
    _prepare(tmp_path)
    with pytest.raises(SystemExit):
        _infer(
            tmp_path,
            monkeypatch,
            "--run-id",
            "run-test",
            # An interruption, not a node the harness could fall back over.
            "--fail-fast",
            provider=InterruptedFirstPassProvider(),
        )
    checkpoint = CheckpointStore(tmp_path / "checkpoint.json").load()
    assert [step.parent_node_id for step in checkpoint.completed_steps] == ["X"]
    return checkpoint


def test_a_resumed_cli_run_retrieves_the_checkpointed_node_s_committed_rules(
    tmp_path, monkeypatch, capsys
) -> None:
    """End to end through `infer --resume`, which is where this has to work."""
    _half_finished_checkpoint(tmp_path, monkeypatch)
    provider = LookupThenCommitProvider()
    _infer(tmp_path, monkeypatch, "--resume", provider=provider)

    assert "seeded 1 prior committed hypothesis" in capsys.readouterr().err
    assert set(provider.turns_by_node) == {"ROOT"}
    assert provider.retrieved["ROOT"]["rules"] == [
        {"dsl": "f > p / #_", "source_child_ids": ["B"], "confidence": 0.8}
    ]


def _rewrite_completed_trajectory(tmp_path: Path, **updates) -> None:
    """Edit the one completed record in place, leaving the failed one alone."""
    path = tmp_path / "trajectories.jsonl"
    rewritten = []
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record["completed"]:
            record.update(updates)
        rewritten.append(json.dumps(record))
    path.write_text("\n".join(rewritten) + "\n", encoding="utf-8")


def test_a_trajectory_from_another_configuration_is_not_seeded(
    tmp_path, monkeypatch, capsys
) -> None:
    _half_finished_checkpoint(tmp_path, monkeypatch)
    _rewrite_completed_trajectory(
        tmp_path, configuration_sha256="a-different-configuration"
    )
    _infer(tmp_path, monkeypatch, "--resume")
    assert "seeded 0 prior committed hypotheses" in capsys.readouterr().err


def test_a_trajectory_from_another_run_is_not_seeded(
    tmp_path, monkeypatch, capsys
) -> None:
    """The configuration hash cannot tell two invocations apart.

    Same model, same input, same settings hash identically, and
    `--trajectories` defaults to one file in the working directory, so two runs
    append to it. Seeding across them would pair one run's checkpointed lexicon
    with another run's rules — the model would read rules that did not produce
    the forms in front of it.
    """
    _half_finished_checkpoint(tmp_path, monkeypatch)
    _rewrite_completed_trajectory(
        tmp_path, run_id="run-a-different-invocation"
    )
    provider = LookupThenCommitProvider()
    _infer(tmp_path, monkeypatch, "--resume", provider=provider)

    assert "seeded 0 prior committed hypotheses" in capsys.readouterr().err
    assert "ROOT" not in provider.retrieved


def test_a_trajectory_for_an_unfinished_node_is_not_seeded(
    tmp_path, monkeypatch, capsys
) -> None:
    _half_finished_checkpoint(tmp_path, monkeypatch)
    # ROOT has a record in the file but is not in the checkpoint: it will be
    # re-run, and seeding it would let that node read a hypothesis for itself.
    _rewrite_completed_trajectory(tmp_path, node_id="ROOT")
    _infer(tmp_path, monkeypatch, "--resume")
    assert "seeded 0 prior committed hypotheses" in capsys.readouterr().err


def test_a_missing_trajectory_file_warns_and_still_resumes(
    tmp_path, monkeypatch, capsys
) -> None:
    _half_finished_checkpoint(tmp_path, monkeypatch)
    (tmp_path / "trajectories.jsonl").unlink()

    _infer(tmp_path, monkeypatch, "--resume")
    captured = capsys.readouterr().err
    assert "does not exist" in captured
    assert "seeded 0 prior committed hypotheses" in captured
    # Degraded, not broken: the run still finished both nodes.
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert {item["node_id"] for item in result["internal_nodes"]} == {"X", "ROOT"}


def test_a_corrupt_trajectory_file_surfaces_instead_of_being_swallowed(
    tmp_path, monkeypatch, capsys
) -> None:
    _half_finished_checkpoint(tmp_path, monkeypatch)
    (tmp_path / "trajectories.jsonl").write_text(
        '{"trajectory_id": "broken"}\n', encoding="utf-8"
    )
    with pytest.raises(SystemExit) as caught:
        _infer(tmp_path, monkeypatch, "--resume")
    assert caught.value.code == 2
    assert "could not load prior hypotheses" in capsys.readouterr().err


def test_an_unchanged_configuration_still_resumes(tmp_path, monkeypatch) -> None:
    _half_finished_checkpoint(tmp_path, monkeypatch)
    _infer(tmp_path, monkeypatch, "--resume")
    store = CheckpointStore(tmp_path / "checkpoint.json")
    assert [step.parent_node_id for step in store.load().completed_steps] == [
        "X",
        "ROOT",
    ]


def test_changed_agent_instructions_refuse_to_resume_and_say_so(
    tmp_path, monkeypatch, capsys
) -> None:
    _half_finished_checkpoint(tmp_path, monkeypatch)
    monkeypatch.setattr(
        cli,
        "load_agent_instructions",
        lambda: "Completely different instructions.",
    )
    with pytest.raises(SystemExit) as caught:
        _infer(tmp_path, monkeypatch, "--resume")
    assert caught.value.code == 2
    assert "the agent instructions" in capsys.readouterr().err


def test_a_changed_tool_schema_refuses_to_resume_and_says_so(
    tmp_path, monkeypatch, capsys
) -> None:
    _half_finished_checkpoint(tmp_path, monkeypatch)
    original = cli.default_tool_registry

    def narrower_registry():
        registry = original()
        definitions = registry.definitions()
        registry.definitions = lambda: definitions[:-1]
        return registry

    monkeypatch.setattr(cli, "default_tool_registry", narrower_registry)
    with pytest.raises(SystemExit) as caught:
        _infer(tmp_path, monkeypatch, "--resume")
    assert caught.value.code == 2
    assert "the tool schemas" in capsys.readouterr().err


def test_a_changed_anchor_file_refuses_to_resume_and_says_so(
    tmp_path, monkeypatch, capsys
) -> None:
    _half_finished_checkpoint(tmp_path, monkeypatch)
    anchors = tmp_path / "anchors.json"
    anchors.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "anchors": {
                    "X": [
                        {
                            "form_id": "anchor:X:water",
                            "variety_id": "X",
                            "concept_id": "water",
                            "segments": ["p", "a"],
                            "provenance": {
                                "source_reference": "Fixture citation",
                            },
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as caught:
        _infer(tmp_path, monkeypatch, "--resume", "--anchors", str(anchors))
    assert caught.value.code == 2
    assert "the anchor file" in capsys.readouterr().err


def test_a_changed_stall_threshold_resumes_and_says_it_changed(
    tmp_path, monkeypatch, capsys
) -> None:
    """The one change a stall invites must not be the one that refuses.

    Loosening a give-up threshold cannot change a committed rule, a validated
    cascade, or a beam: it decides only how long the harness keeps trying. When
    it was hashed, recovering from a protocol stall meant re-running the entire
    family, which is how three attempts at a seven-node benchmark produced no
    evaluable result at all.
    """
    _half_finished_checkpoint(tmp_path, monkeypatch)
    _infer(
        tmp_path,
        monkeypatch,
        "--resume",
        "--max-truncated-responses",
        "9",
        "--max-repeated-tool-failures",
        "6",
        "--stall-window-calls",
        "24",
    )
    err = capsys.readouterr().err
    # Reported, never silent: a resumed run must not disagree with its own
    # configuration without saying so.
    assert "the give-up thresholds changed" in err
    assert "the provider and limit settings" not in err
    assert [
        step.parent_node_id
        for step in CheckpointStore(tmp_path / "checkpoint.json").load().completed_steps
    ] == ["X", "ROOT"]


def test_a_changed_semantic_setting_still_refuses_to_resume(
    tmp_path, monkeypatch, capsys
) -> None:
    """The split is between give-up thresholds and everything else."""
    _half_finished_checkpoint(tmp_path, monkeypatch)
    with pytest.raises(SystemExit) as caught:
        _infer(tmp_path, monkeypatch, "--resume", "--temperature", "0.9")
    assert caught.value.code == 2
    assert "the provider and limit settings" in capsys.readouterr().err


def test_a_checkpoint_without_component_digests_still_refuses_generically(
    tmp_path, monkeypatch, capsys
) -> None:
    """An older checkpoint knows a hash changed but not which part.

    The message degrades to the old wording rather than guessing, which is the
    honest reading of a record that never stored the parts.
    """
    _half_finished_checkpoint(tmp_path, monkeypatch)
    store = CheckpointStore(tmp_path / "checkpoint.json")
    stale = store.load().model_copy(
        update={
            "configuration_sha256": "written-under-another-configuration",
            "configuration_components": {},
        }
    )
    store.save(stale)
    with pytest.raises(SystemExit) as caught:
        _infer(tmp_path, monkeypatch, "--resume")
    assert caught.value.code == 2
    assert "the configuration" in capsys.readouterr().err


def test_the_cli_and_the_trajectory_agree_on_both_hashes(
    tmp_path, monkeypatch
) -> None:
    """The checkpoint's digests must be the same values a trajectory reports."""
    _prepare(tmp_path)
    _infer(tmp_path, monkeypatch, "--run-id", "run-test")
    checkpoint = CheckpointStore(tmp_path / "checkpoint.json").load()
    trajectory = TrajectoryDatasetBuilder.read_jsonl(
        tmp_path / "trajectories.jsonl"
    )[0]
    assert (
        checkpoint.configuration_components["the agent instructions"]
        == trajectory.instruction_sha256
    )
    assert (
        checkpoint.configuration_components["the tool schemas"]
        == trajectory.tool_schema_sha256
    )


def test_backoff_without_a_ceiling_is_refused_at_the_command_line(
    tmp_path, monkeypatch, capsys
) -> None:
    _prepare(tmp_path)
    with pytest.raises(SystemExit) as caught:
        _infer(tmp_path, monkeypatch, "--allow-truncation-backoff")
    assert caught.value.code == 2
    assert "--truncation-max-tokens-ceiling" in capsys.readouterr().err
