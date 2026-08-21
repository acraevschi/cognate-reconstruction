"""The artifact-facing run report.

`inspect-run` reads what a run left behind and says what happened. Two things
are load-bearing and tested here: the `high_quality` verdict must come with the
specific condition it failed, and the cross-node section must stay an
observation — no score, no gate, no effect on anything the harness computes.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

import pytest

from cognate_reconstruction import cli
from cognate_reconstruction.agent.schemas import (
    LLMMessage,
    LLMToolCall,
    LLMToolDefinition,
    MessageRole,
)
from cognate_reconstruction.agent.trajectory import TrajectoryDatasetBuilder
from cognate_reconstruction.inspect_run import (
    build_report,
    cross_node_observations,
    load_run,
    render_html,
)
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm

NEWICK = "(language_a,(language_b,language_c)INNER)PROTO;"

RESTORE_P = {
    "dsl": "f > p / #_",
    "source_child_ids": ["language_b"],
    "confidence": 0.9,
}


def _lexicon(variety_id: str, initial: str) -> LanguageLexicon:
    return LanguageLexicon(
        variety_id=variety_id,
        name=variety_id,
        forms=tuple(
            LexicalForm(
                form_id=f"{variety_id}:{concept}",
                variety_id=variety_id,
                concept_id=concept,
                segments=(initial, *rest),
                cognate_set_id=f"cog:{concept}",
            )
            for concept, rest in (("water", ("a",)), ("fire", ("u", "r")))
        ),
    )


class ScriptedFamilyProvider:
    """Inspect, test each scripted rule, then commit — once per node.

    Every node gets a fresh conversation, so the turn counter is per node. The
    node under way is read back out of the payload the orchestrator built.
    """

    model = "scripted/family"

    def __init__(self, scripts: dict[str, list[dict]]) -> None:
        self.scripts = scripts
        self.turns: Counter[str] = Counter()

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[LLMToolDefinition],
        *,
        tool_choice: str = "auto",
        max_tokens_override: int | None = None,
    ) -> LLMMessage:
        assert tools
        match = re.search(r'"node_id":\s*"([^"]+)"', messages[1].content or "")
        assert match is not None
        node_id = match.group(1)
        self.turns[node_id] += 1
        turn = self.turns[node_id]
        rules = self.scripts[node_id]
        if turn == 1:
            call = LLMToolCall(
                call_id=f"inspect:{node_id}", name="list_concepts", arguments={}
            )
        elif turn <= 1 + len(rules):
            rule = rules[turn - 2]
            call = LLMToolCall(
                call_id=f"test:{node_id}:{turn}",
                name="test_sound_law",
                arguments={
                    "dsl": rule["dsl"],
                    "source_child_ids": rule["source_child_ids"],
                },
            )
        else:
            call = LLMToolCall(
                call_id=f"commit:{node_id}",
                name="commit_reconstruction",
                arguments={
                    "node_id": node_id,
                    "rules": rules,
                    "anomalies": [],
                    "summary": f"Reconstruction of {node_id} from its children.",
                },
            )
        return LLMMessage(role=MessageRole.ASSISTANT, tool_calls=(call,))


def _run_family(tmp_path: Path, monkeypatch, scripts: dict[str, list[dict]]) -> Path:
    """Drive the real CLI over a three-language family and return its run dir."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    run_dir = tmp_path / "run"
    input_path = tmp_path / "input.json"
    payload = WorkbenchPayload(
        lexicons=(
            _lexicon("language_a", "f"),
            _lexicon("language_b", "f"),
            _lexicon("language_c", "p"),
        ),
        newick=NEWICK,
    )
    input_path.write_text(payload.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(
        cli,
        "LiteLLMProvider",
        lambda *args, **kwargs: ScriptedFamilyProvider(scripts),
    )
    cli.main(
        [
            "infer",
            "--input",
            str(input_path),
            "--model",
            "scripted/family",
            "--output",
            str(run_dir / "result.json"),
            "--trajectories",
            str(run_dir / "trajectories.jsonl"),
            "--events",
            str(run_dir / "events.jsonl"),
            "--quiet",
        ]
    )
    return run_dir


def _two_rule_scripts() -> dict[str, list[dict]]:
    """INNER commits one tested rule; PROTO commits two and skips the cascade."""
    return {
        "INNER": [dict(RESTORE_P)],
        "PROTO": [
            {
                "dsl": "f > p / #_",
                "source_child_ids": ["language_a"],
                "confidence": 0.8,
                "rationale": "language_a keeps f where INNER already shows p.",
            },
            {
                "dsl": "r > l / _#",
                "source_child_ids": ["language_a", "INNER"],
                "confidence": 0.6,
                "rationale": "Final r is an innovation in both branches.",
            },
        ],
    }


def test_inspect_run_reports_both_nodes_and_the_quality_reason(
    tmp_path, monkeypatch, capsys
) -> None:
    run_dir = _run_family(tmp_path, monkeypatch, _two_rule_scripts())
    capsys.readouterr()

    cli.main(["inspect-run", "--run-dir", str(run_dir)])
    report = capsys.readouterr().out

    assert "NODE INNER" in report
    assert "NODE PROTO" in report
    # Committed hypothesis, in the model's own terms.
    assert "f > p / #_" in report
    assert "r > l / _#" in report
    assert "language_a keeps f where INNER already shows p." in report
    # Deterministic outcome.
    assert "rule coverage" in report
    assert "complexity cost" in report
    # Printed beside coverage, because coverage rises when rules fire and the
    # cheapest way to make a rule fire is to delete a distinction.
    assert "contrast loss" in report
    assert "delete or merge a distinction" in report
    # The one number in the block not computed over the evidence the rules were
    # fitted to. Named "held-out concepts" rather than "held out" because a
    # second, unrelated thing is now also held out at these nodes: the gold
    # proto-forms, which are the answer key and never leave the node split.
    assert "held-out concepts" in report
    # The part that saves the most human time: not just that the gate failed
    # but which condition failed it.
    assert "high_quality" in report
    assert (
        "2 rules were committed without a test_rule_cascade preview"
        in " ".join(report.split())
    )
    # Reconstructed forms for both internal nodes.
    assert "RECONSTRUCTED FORMS" in report
    assert "p u l" in report


def test_inspect_run_works_without_an_event_log(
    tmp_path, monkeypatch, capsys
) -> None:
    run_dir = _run_family(tmp_path, monkeypatch, _two_rule_scripts())
    (run_dir / "events.jsonl").unlink()
    capsys.readouterr()

    cli.main(["inspect-run", "--run-dir", str(run_dir)])
    report = capsys.readouterr().out
    assert "no events.jsonl" in report
    assert "NODE PROTO" in report
    assert "SESSION SHAPE" in report


def test_inspect_run_html_is_a_single_self_contained_file(
    tmp_path, monkeypatch, capsys
) -> None:
    run_dir = _run_family(tmp_path, monkeypatch, _two_rule_scripts())
    destination = tmp_path / "report.html"
    capsys.readouterr()

    cli.main(["inspect-run", "--run-dir", str(run_dir), "--html", str(destination)])
    document = destination.read_text(encoding="utf-8")

    assert "<html" in document and "</html>" in document
    for forbidden in ("http://", "https://", "src=", "href="):
        assert forbidden not in document, forbidden
    assert "INNER" in document and "PROTO" in document
    # Wide content scrolls inside its own container rather than the page.
    assert "class='scroll'" in document
    # Readable in both renderings.
    assert "prefers-color-scheme: dark" in document


def _observations(run_dir: Path):
    artifacts = load_run(run_dir)
    return cross_node_observations(artifacts.trajectories, artifacts.result)


CONSISTENT = {
    "INNER": [dict(RESTORE_P)],
    "PROTO": [
        {
            "dsl": "f > p / #_",
            "source_child_ids": ["language_a"],
            "confidence": 0.9,
        }
    ],
}

CONTRADICTORY = {
    "INNER": [dict(RESTORE_P)],
    "PROTO": [
        {
            "dsl": "f > b / #_",
            "source_child_ids": ["language_a"],
            "confidence": 0.9,
        }
    ],
}

SPREAD = {
    "INNER": [{**RESTORE_P, "confidence": 0.6}],
    "PROTO": [
        {
            "dsl": "f > p / #_",
            "source_child_ids": ["language_a"],
            "confidence": 1.0,
        }
    ],
}


def test_a_consistent_family_produces_no_observations(
    tmp_path, monkeypatch
) -> None:
    run_dir = _run_family(tmp_path, monkeypatch, CONSISTENT)
    assert _observations(run_dir) == ()


def test_adjacent_nodes_mapping_one_segment_two_ways_are_flagged(
    tmp_path, monkeypatch
) -> None:
    """Both rules are legitimately validated; only their combination is odd."""
    run_dir = _run_family(tmp_path, monkeypatch, CONTRADICTORY)
    observations = _observations(run_dir)
    kinds = {observation.kind for observation in observations}
    assert "contradictory_mapping" in kinds
    contradiction = next(
        item for item in observations if item.kind == "contradictory_mapping"
    )
    assert contradiction.nodes == ("PROTO", "INNER")
    assert "`f > b / #_`" in contradiction.detail
    assert "`f > p / #_`" in contradiction.detail
    # An observation, never a verdict.
    for word in ("error", "invalid", "wrong", "score"):
        assert word not in contradiction.detail.lower()


def test_the_same_rule_at_two_nodes_with_different_confidence_is_observed(
    tmp_path, monkeypatch
) -> None:
    run_dir = _run_family(tmp_path, monkeypatch, SPREAD)
    observations = _observations(run_dir)
    spread = [item for item in observations if item.kind == "confidence_spread"]
    assert len(spread) == 1
    assert spread[0].nodes == ("INNER", "PROTO")
    assert "INNER 0.60" in spread[0].detail
    assert "PROTO 1.00" in spread[0].detail


def test_cross_node_observations_change_no_verdict(tmp_path, monkeypatch) -> None:
    """The whole section is report-only, and this is what that means.

    A contradictory family and a consistent one differ in what the report says
    and in nothing else: same quality verdicts, same diagnostics, same beam
    output. Scoring the contradiction would change what counts as a valid
    reconstruction, which is a research-owner decision, not this report's.
    """
    consistent = _run_family(tmp_path / "consistent", monkeypatch, CONSISTENT)
    contradictory = _run_family(tmp_path / "contradictory", monkeypatch, CONTRADICTORY)

    verdicts = []
    for run_dir in (consistent, contradictory):
        trajectories = TrajectoryDatasetBuilder.read_jsonl(
            run_dir / "trajectories.jsonl"
        )
        verdicts.append(
            {item.node_id: item.high_quality for item in trajectories}
        )
        report = build_report(load_run(run_dir))
        # Nothing in the quality section mentions the cross-node section.
        for node in report.nodes:
            for reason in node.quality_reasons:
                assert "cross-node" not in reason.lower()
    assert verdicts[0] == verdicts[1] == {"INNER": True, "PROTO": True}

    assert _observations(consistent) == ()
    assert _observations(contradictory)


def test_the_cross_node_section_says_it_judges_nothing(
    tmp_path, monkeypatch, capsys
) -> None:
    run_dir = _run_family(tmp_path, monkeypatch, CONTRADICTORY)
    capsys.readouterr()
    cli.main(["inspect-run", "--run-dir", str(run_dir)])
    text = " ".join(capsys.readouterr().out.split())
    assert "does not judge historical correctness" in text
    assert "Mechanical observations only" in text

    report = build_report(load_run(run_dir))
    assert "does not judge historical correctness" in " ".join(
        render_html(report).split()
    )


def test_a_failed_node_without_a_result_file_still_reports(
    tmp_path, monkeypatch, capsys
) -> None:
    """The degraded case is exactly when someone needs the report most."""
    source = _run_family(tmp_path / "source", monkeypatch, CONSISTENT)
    trajectory = TrajectoryDatasetBuilder.read_jsonl(
        source / "trajectories.jsonl"
    )[0]
    failed = trajectory.model_copy(
        update={
            "completed": False,
            "failure": "AgentLoopLimitError: node exceeded 24 turns",
            "committed_reconstruction": None,
            "reconstruction_step": None,
        }
    )
    run_dir = tmp_path / "failed"
    run_dir.mkdir(parents=True)
    (run_dir / "trajectories.jsonl").write_text(
        failed.model_dump_json(exclude_computed_fields=True) + "\n",
        encoding="utf-8",
    )
    capsys.readouterr()

    cli.main(["inspect-run", "--run-dir", str(run_dir)])
    report = " ".join(capsys.readouterr().out.split())
    assert "[FAILED]" in report
    assert "AgentLoopLimitError" in report
    assert "nothing was committed" in report
    assert "no result.json" in report
    assert "the node did not complete" in report


def test_a_run_directory_with_neither_artifact_is_refused(tmp_path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="neither result.json"):
        load_run(empty)


def test_forms_are_capped_unless_every_one_is_asked_for(
    tmp_path, monkeypatch
) -> None:
    run_dir = _run_family(tmp_path, monkeypatch, CONSISTENT)
    artifacts = load_run(run_dir)
    capped = build_report(artifacts, form_limit=1)
    assert [node.omitted_forms for node in capped.nodes] == [1, 1]
    complete = build_report(artifacts, form_limit=None)
    assert [node.omitted_forms for node in complete.nodes] == [0, 0]
    assert all(len(node.forms) == 2 for node in complete.nodes)


def test_the_report_reads_result_json_for_the_best_lexicon(
    tmp_path, monkeypatch
) -> None:
    """`result.json` carries computed fields its own model forbids on read-back.

    The report therefore parses it as JSON and validates the fragments it uses.
    If that ever stops being true, this test is where it shows up.
    """
    run_dir = _run_family(tmp_path, monkeypatch, CONSISTENT)
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    assert "words_applied" in json.dumps(result)
    forms = {
        node.node_id: dict(node.forms) for node in build_report(load_run(run_dir)).nodes
    }
    assert forms["PROTO"] == {"water": "p a", "fire": "p u r"}
