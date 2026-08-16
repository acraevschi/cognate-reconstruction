from __future__ import annotations

import json
from collections.abc import Sequence

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
    AgentTrajectory,
    JsonlTrajectorySink,
    TrajectoryDatasetBuilder,
)
from cognate_reconstruction.ingestion import ingest_payload
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.schemas.lexicon import (
    FormProvenance,
    LanguageLexicon,
    LexicalForm,
)


def _lexicon(variety_id: str, initial: str) -> LanguageLexicon:
    return LanguageLexicon(
        variety_id=variety_id,
        name=variety_id,
        forms=tuple(
            LexicalForm(
                form_id=f"{variety_id}:{concept}",
                variety_id=variety_id,
                concept_id=concept,
                segments=(initial, *ending),
                cognate_set_id=f"cog:{concept}",
            )
            for concept, ending in (
                ("water", ("a",)),
                ("fire", ("u", "r")),
            )
        ),
    )


class ComparativeWorkflowProvider:
    model = "scripted/comparative"

    def __init__(self) -> None:
        self.turn = 0

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[LLMToolDefinition],
        *,
        tool_choice: str = "auto",
        max_tokens_override: int | None = None,
    ) -> LLMMessage:
        assert tools
        self.turn += 1
        supporting_form_ids = []
        for message in messages:
            if (
                message.role is MessageRole.TOOL
                and message.name == "test_sound_law"
                and message.content is not None
            ):
                supporting_form_ids = json.loads(message.content)["result"][
                    "supporting_form_ids"
                ]
        calls = {
            1: LLMToolCall(
                call_id="inspect-concepts",
                name="list_concepts",
                arguments={},
            ),
            2: LLMToolCall(
                call_id="align-evidence",
                name="get_alignments",
                arguments={
                    "node_ids": ["A", "B"],
                    "concept_ids": ["water", "fire"],
                    "include_anchors": True,
                },
            ),
            3: LLMToolCall(
                call_id="validate-restore-p",
                name="test_sound_law",
                arguments={
                    "dsl": "f > p / #_",
                    "source_child_ids": ["B"],
                },
            ),
            4: LLMToolCall(
                call_id="preview-cascade",
                name="test_rule_cascade",
                arguments={
                    "rules": [
                        {
                            "rule_id": "restore-p",
                            "dsl": "f > p / #_",
                            "source_child_ids": ["B"],
                        }
                    ]
                },
            ),
            5: LLMToolCall(
                call_id="commit",
                name="commit_reconstruction",
                arguments={
                    "node_id": "PROTO",
                    "cascade_validation_call_id": "preview-cascade",
                    "rules": [
                        {
                            "rule_id": "restore-p",
                            "dsl": "f > p / #_",
                            "source_child_ids": ["B"],
                            "confidence": 0.9,
                            "validation_call_id": "validate-restore-p",
                            "supporting_form_ids": supporting_form_ids,
                            "rationale": "Both B forms show the same initial reflex.",
                        }
                    ],
                    "anomalies": [],
                    "summary": "Restore parent initial p from regular B f.",
                },
            ),
        }
        return LLMMessage(
            role=MessageRole.ASSISTANT,
            tool_calls=(calls[self.turn],),
        )


def test_scripted_comparative_workflow_exports_complete_trajectory(
    tmp_path,
) -> None:
    trajectory_path = tmp_path / "trajectories.jsonl"
    dataset = ingest_payload(
        WorkbenchPayload(
            lexicons=(_lexicon("A", "p"), _lexicon("B", "f")),
            newick="(A,B)PROTO;",
        )
    )
    anchor = LexicalForm(
        form_id="anchor:water",
        variety_id="PROTO",
        concept_id="water",
        segments=("p", "a"),
        provenance=FormProvenance(
            source_reference="Curated historical fixture"
        ),
    )
    provider = ComparativeWorkflowProvider()
    service = ReconstructionService(
        AgenticNodeReconstructor(
            AgentOrchestrator(
                provider,
                instructions="Inspect, align, test, preview, then commit.",
                trajectory_sink=JsonlTrajectorySink(trajectory_path),
                run_id="run-e2e",
                configuration_sha256="config-e2e",
            )
        )
    )
    result = service.reconstruct_family(
        dataset,
        anchors_by_node={"PROTO": (anchor,)},
    )
    assert provider.turn == 5
    best_forms = {
        form.concept_id: form.segments
        for form in result.internal_nodes[0].best_lexicon.forms
    }
    assert best_forms == {
        "fire": ("p", "u", "r"),
        "water": ("p", "a"),
    }
    diagnostics = result.snapshot.steps[0].diagnostics
    assert diagnostics.rule_count == 1
    assert diagnostics.successful_applications == 2
    assert diagnostics.rule_coverage == 1.0
    assert diagnostics.anomaly_rate == 0.0

    trajectories = TrajectoryDatasetBuilder.read_jsonl(trajectory_path)
    assert len(trajectories) == 1
    trajectory = trajectories[0]
    assert trajectory.completed
    assert trajectory.initial_payload.anchors == (anchor,)
    assert trajectory.metrics.inspection_tool_calls == 2
    assert trajectory.metrics.sound_law_tests == 1
    assert trajectory.metrics.cascade_tests == 1
    assert trajectory.high_quality
    assert {
        call.name
        for message in trajectory.messages
        for call in message.tool_calls
    } == {
        "list_concepts",
        "get_alignments",
        "test_sound_law",
        "test_rule_cascade",
        "commit_reconstruction",
    }
    sound_law_result = next(
        json.loads(message.content)["result"]
        for message in trajectory.messages
        if message.role is MessageRole.TOOL
        and message.name == "test_sound_law"
        and message.content is not None
    )
    assert set(sound_law_result["supporting_form_ids"]) == {
        "B:fire",
        "B:water",
    }
    examples = TrajectoryDatasetBuilder().build(
        trajectories,
        high_quality_only=True,
    )
    assert len(examples) == 1
    assert examples[0].run_id == "run-e2e"


def test_historical_no_op_trajectory_remains_readable_but_is_not_high_quality(
    tmp_path,
) -> None:
    trajectory_path = tmp_path / "trajectories.jsonl"
    dataset = ingest_payload(
        WorkbenchPayload(
            lexicons=(_lexicon("A", "p"), _lexicon("B", "f")),
            newick="(A,B)PROTO;",
        )
    )
    service = ReconstructionService(
        AgenticNodeReconstructor(
            AgentOrchestrator(
                ComparativeWorkflowProvider(),
                instructions="Inspect, align, test, preview, then commit.",
                trajectory_sink=JsonlTrajectorySink(trajectory_path),
                run_id="run-legacy-no-op",
                configuration_sha256="config-legacy-no-op",
            )
        )
    )
    service.reconstruct_family(dataset)
    trajectory = TrajectoryDatasetBuilder.read_jsonl(trajectory_path)[0]
    assert trajectory.committed_reconstruction is not None
    parsed = trajectory.committed_reconstruction.parsed_rules[0]
    no_op_ast = parsed.rule.model_copy(
        update={
            "source": "p > p / #_",
            "target": parsed.rule.replacement,
        }
    )
    no_op_reconstruction = trajectory.committed_reconstruction.model_copy(
        update={
            "parsed_rules": (
                parsed.model_copy(update={"rule": no_op_ast}),
            )
        }
    )
    historical = trajectory.model_copy(
        update={"committed_reconstruction": no_op_reconstruction}
    )

    loaded = AgentTrajectory.model_validate_json(
        historical.model_dump_json(exclude_computed_fields=True)
    )
    assert loaded.completed
    assert loaded.committed_no_op_rule_count == 1
    assert not loaded.high_quality
    summary = cli._trajectory_summary((loaded,))
    assert summary["committed_no_op_rules"] == 1
    assert summary["trajectories_with_no_op_rules"] == 1
    assert TrajectoryDatasetBuilder().build(
        (loaded,), high_quality_only=True
    ) == ()
