"""One family run under the per-set protocol, from prompt to artifact.

The commit-protocol tests drive the registry directly; this drives the whole
harness — orchestrator, traversal, beam, trajectory, `inspect-run` — under a
scripted session that surveys, previews, and commits an inventory. What it is
for is the seam: the deterministic step must come out of the *assembler* rather
than the rule reconstructor, the trajectory must stamp 3.0, and every reader
downstream must handle a commit with no `parsed_rules`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from cognate_reconstruction import inspect_run
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
from cognate_reconstruction.schemas.inventory import CommittedProtoInventory
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm

# Tongan keeps the glottal stop; Niuean lost it. Neither daughter's string is
# the parent, so this is exactly the shape no branch-scoped cascade can write.
FORMS = {
    "Tongan": {
        "tongue": ("ʔ", "e", "l", "e", "l", "o"),
        "shadow": ("ʔ", "a", "t", "a"),
        "head": ("ʔ", "u", "l", "u"),
    },
    "Niuean": {
        "tongue": ("a", "l", "e", "l", "o"),
        "shadow": ("a", "t", "a"),
        "head": ("u", "l", "u"),
    },
}


def _lexicon(variety_id: str) -> LanguageLexicon:
    return LanguageLexicon(
        variety_id=variety_id,
        name=variety_id,
        forms=tuple(
            LexicalForm(
                form_id=f"{variety_id}:{concept_id}",
                variety_id=variety_id,
                concept_id=concept_id,
                segments=segments,
                cognate_set_id=f"cog:{concept_id}",
            )
            for concept_id, segments in sorted(FORMS[variety_id].items())
        ),
    )


class InventoryWorkflowProvider:
    """Survey, preview, refine, preview, commit — §6.6's loop, scripted."""

    model = "scripted/inventory"

    def __init__(self) -> None:
        self.turn = 0
        self.commitments: list[dict] = []

    def _read_survey(self, messages: Sequence[LLMMessage]) -> None:
        for message in messages:
            if (
                message.role is MessageRole.TOOL
                and message.name == "summarize_correspondences"
                and message.content is not None
            ):
                sets = json.loads(message.content)["result"]["sets"]
                by_reflexes = {
                    tuple(item["segments"]): item for item in sets
                }
                # Column order is the tree's: (Niuean, Tongan).
                values = {
                    (None, "ʔ"): "ʔ",
                    ("a", "e"): "a",
                    ("l", "l"): "l",
                    ("a", "a"): "a",
                    ("t", "t"): "t",
                    ("u", "u"): "u",
                    ("o", "o"): "o",
                    ("e", "e"): "e",
                }
                self.commitments = [
                    {
                        "set_id": item["set_id"],
                        "reflexes": list(item["segments"]),
                        "proto_segment": values[tuple(item["segments"])],
                        "support": item["support"],
                        "confidence": 0.9,
                        "rationale": "read off the correspondence survey",
                        "directionality_rationale": (
                            "Niuean innovated the loss of the glottal stop."
                        ),
                    }
                    for item in sets
                    if tuple(item["segments"]) in values
                ]

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
        self._read_survey(messages)
        if self.turn == 1:
            call = LLMToolCall(
                call_id="survey",
                name="summarize_correspondences",
                arguments={"min_support": 1},
            )
        elif self.turn == 2:
            call = LLMToolCall(
                call_id="preview",
                name="test_proto_assembly",
                arguments={
                    "commitments": self.commitments,
                    "residue_policy": "retain_from_witness",
                    "residue_witness_child_id": "Tongan",
                },
            )
        else:
            call = LLMToolCall(
                call_id="commit",
                name="commit_reconstruction",
                arguments={
                    "node_id": "tongic",
                    "inventory": {
                        "child_node_ids": ["Niuean", "Tongan"],
                        "commitments": self.commitments,
                        "residue_policy": "retain_from_witness",
                        "residue_witness_child_id": "Tongan",
                    },
                    "anomalies": [],
                    "summary": (
                        "Proto-Tongic keeps *ʔ; Niuean lost it word-initially."
                    ),
                },
            )
        return LLMMessage(role=MessageRole.ASSISTANT, tool_calls=(call,))


def _run(tmp_path):
    dataset = ingest_payload(
        WorkbenchPayload(
            lexicons=(_lexicon("Niuean"), _lexicon("Tongan")),
            newick="(Niuean,Tongan)tongic;",
        )
    )
    provider = InventoryWorkflowProvider()
    path = tmp_path / "trajectories.jsonl"
    service = ReconstructionService(
        AgenticNodeReconstructor(
            AgentOrchestrator(
                provider,
                instructions="Survey, preview, commit an inventory.",
                trajectory_sink=JsonlTrajectorySink(path),
                run_id="run-inventory",
                configuration_sha256="config-inventory",
            )
        )
    )
    return service.reconstruct_family(dataset), path


def test_a_scripted_inventory_run_assembles_forms_no_branch_produced(
    tmp_path,
) -> None:
    result, path = _run(tmp_path)
    best = {
        form.concept_id: form.segments
        for form in result.internal_nodes[0].best_lexicon.forms
    }
    # `ʔ` comes from Tongan, the first vowel of `tongue` from Niuean, and
    # neither daughter's whole string is the answer.
    assert best["tongue"] == ("ʔ", "a", "l", "e", "l", "o")
    assert best["tongue"] not in set(FORMS["Tongan"].values())
    assert best["tongue"] not in set(FORMS["Niuean"].values())
    assert best["shadow"] == ("ʔ", "a", "t", "a")
    assert best["head"] == ("ʔ", "u", "l", "u")


def test_the_step_comes_from_the_assembler_and_reports_assembly(
    tmp_path,
) -> None:
    result, _path = _run(tmp_path)
    step = result.snapshot.steps[0]
    diagnostics = step.diagnostics
    assert step.rule_reports == ()
    assert step.assembly_reports
    assert diagnostics.committed_set_count == 8
    assert diagnostics.proto_phoneme_count == 7
    assert diagnostics.unaccounted_column_rate == 0.0
    # The mechanism check, and worth reading carefully because the number is
    # not 1.0 and should not be. `shadow` and `head` are not cross-branch:
    # Tongan's own derived cascade leaves its form unchanged and its form *is*
    # the assembled parent. `tongue` is, because Tongan's derived `e > a` is
    # unconditioned and lowers both of its vowels, so no single child reproduces
    # `ʔ a l e l o`. That is exactly what the definition is for — it measures
    # whether the evidence had to be mixed, not whether the answer was hard.
    assert diagnostics.cross_branch_assembly_rate == 1 / 3
    assert [
        report.concept_id
        for report in step.assembly_reports
        if report.cross_branch_assembled
    ] == ["tongue"]
    assert diagnostics.identity_reconstruction is False
    # Retired rather than reimplemented — one candidate tuple assembles into
    # exactly one parent form, so branch divergence is structurally impossible.
    assert diagnostics.child_convergence_rate is None
    assert diagnostics.contrast_reducing_rule_count is None
    # Two sets reconstruct *a with no conditioning between them, which is a
    # distinction Tongan makes that the parent does not. Read straight off the
    # inventory rather than inferred from a mapping.
    assert diagnostics.contrast_reducing_set_count == 2


def test_the_trajectory_stamps_the_new_version_and_stays_readable(
    tmp_path,
) -> None:
    _result, path = _run(tmp_path)
    trajectories = TrajectoryDatasetBuilder.read_jsonl(path)
    assert len(trajectories) == 1
    trajectory = trajectories[0]
    assert trajectory.completed
    assert trajectory.schema_version == "3.0"
    assert trajectory.commit_shape == "inventory"
    commit = trajectory.committed_reconstruction
    assert isinstance(commit, CommittedProtoInventory)
    assert commit.proto_phonemes == ("a", "e", "l", "o", "t", "u", "ʔ")
    assert commit.non_invertible_child_ids == ("Niuean",)
    # Every derived rule is a real DSL rule, re-parseable and applicable.
    assert commit.derived_rules
    assert trajectory.metrics.assembly_tests == 1
    assert trajectory.metrics.committed_rule_count == 8
    assert trajectory.metrics.sound_law_tests == 0
    # And the gate can see it: a preview covered the inventory, so it passes for
    # a reason rather than by default.
    assert trajectory.high_quality_failure_reasons == ()
    assert trajectory.high_quality is True


def test_inspect_run_prints_the_inventory_rather_than_a_blank_cascade(
    tmp_path,
) -> None:
    _result, path = _run(tmp_path)
    trajectories = TrajectoryDatasetBuilder.read_jsonl(path)
    rows = dict(inspect_run._diagnostic_rows(trajectories[0]))
    assert "proto-inventory" in rows
    assert "7 phoneme(s) from 8 correspondence set(s)" in rows["proto-inventory"]
    assert "unaccounted columns" in rows
    assert "cross-branch assembly" in rows
    assert "non-invertible children" in rows
    # The rule-shaped rows are absent rather than reporting a flawless cascade
    # at a node that never wrote one.
    assert "rule coverage" not in rows
    assert "child convergence" not in rows
    # And the derived cascade is what the cross-node observations read.
    views = inspect_run.committed_rule_views(trajectories)
    assert views
    assert {view.node_id for view in views} == {"tongic"}


def test_the_whole_report_renders_for_an_inventory_node(tmp_path) -> None:
    """Every downstream reader must survive a commit with no `parsed_rules`.

    Three of them indexed `commit.request.rules` directly and would have raised
    `AttributeError` on the first inventory run: `inspect-run`'s rule table, its
    directionality evidence, and `synthesis/scoring.py`'s branch-rule flattening.
    Rendering the whole report is the cheapest way to keep them honest.
    """
    _result, path = _run(tmp_path)
    trajectories = TrajectoryDatasetBuilder.read_jsonl(path)
    artifacts = inspect_run.RunArtifacts(
        run_dir=path.parent,
        trajectories=trajectories,
        events=(),
        result=None,
        notes=(),
    )
    report = inspect_run.build_report(artifacts)
    text = inspect_run.render_text(report)
    assert "proto-inventory" in text
    # The committed *sets* fill the table the rule cascade used to.
    assert "> *ʔ" in text
    assert inspect_run.render_html(report)


def test_score_synthetic_reads_an_inventorys_derived_cascade(tmp_path) -> None:
    """§4.3's reason for deriving the rules at all.

    `misdirected_rule_count` is the one measurement that speaks directly to
    prompt 04's failure and is checkable nowhere but against a synthetic answer
    key. A commit shape that could not produce a branch-scoped rule would have
    destroyed it, so the derived cascade is what these are computed against —
    with the directionality rationale carried over from the commitment each rule
    came from.
    """
    from cognate_reconstruction.synthesis.scoring import committed_branch_rules

    _result, path = _run(tmp_path)
    trajectories = TrajectoryDatasetBuilder.read_jsonl(path)
    rules, committed, failed = committed_branch_rules(trajectories)
    assert committed == ("tongic",)
    assert failed == ()
    assert rules
    assert {rule.child_node_id for rule in rules} <= {"Niuean", "Tongan"}
    # Every derived rule carries the rationale of the set it came from, so the
    # directionality measurement is not silently zeroed by the migration.
    assert all(rule.directionality_rationale for rule in rules)
