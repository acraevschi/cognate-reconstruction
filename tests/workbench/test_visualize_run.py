"""The session-facing run view.

`inspect-run` says what a run concluded. `visualize-run` says how the agent got
there, and the things worth pinning down are the ones a reader would silently
be misled by: that a call is paired with the answer it actually received, that a
rejection keeps its own classification, that a tool this view has never heard of
is not quietly filed under a phase it was never in, and that a node still in
flight is never dressed up as a finished record.

The view reports; it does not filter. A session the workflow gate rejected has
to render in full, with the reason attached — a visualizer that hid it would be
a gate wearing a different name.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from cognate_reconstruction import cli
from cognate_reconstruction.agent.schemas import (
    LLMMessage,
    LLMToolCall,
    MessageRole,
)
from cognate_reconstruction.inspect_run import load_run
from cognate_reconstruction.visualize_run import (
    DEFAULT_OUTPUT_NAME,
    TOOL_PHASES,
    build_live_state,
    build_state,
    build_timeline,
    digest_arguments,
    digest_result,
    render_page,
    traversal_tree,
)

FIXTURE = Path(__file__).parent / "fixtures" / "trajectory_real_pre_change.jsonl"


@dataclass(frozen=True)
class _Session:
    """Only what `build_timeline` reads, so a case can state its own messages."""

    messages: tuple[LLMMessage, ...]


def _call(call_id: str, name: str, **arguments) -> LLMMessage:
    return LLMMessage(
        role=MessageRole.ASSISTANT,
        content="",
        tool_calls=(LLMToolCall(call_id=call_id, name=name, arguments=arguments),),
    )


def _ok(call_id: str, name: str, result: dict) -> LLMMessage:
    return LLMMessage(
        role=MessageRole.TOOL,
        content=json.dumps({"ok": True, "result": result}),
        tool_call_id=call_id,
        name=name,
    )


def _rejected(call_id: str, name: str, code: str | None, message: str) -> LLMMessage:
    return LLMMessage(
        role=MessageRole.TOOL,
        content=json.dumps(
            {
                "ok": False,
                "result": None,
                "error": {
                    "error_type": "ToolInputError",
                    "message": message,
                    "code": code,
                    "remediation": "do it the other way",
                },
            }
        ),
        tool_call_id=call_id,
        name=name,
    )


def _run_dir(tmp_path: Path) -> Path:
    """A run directory holding one real pre-change trajectory and nothing else."""
    directory = tmp_path / "run"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "trajectories.jsonl").write_text(
        FIXTURE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return directory


# ---------------------------------------------------------------------------
# the timeline
# ---------------------------------------------------------------------------


def test_each_call_is_paired_with_the_answer_it_received() -> None:
    """Answers are matched by call id, not by position.

    A provider is free to answer out of order, and a view that zipped the two
    lists would attribute one call's result to another — the most dangerous
    thing this module could get wrong, because the output still looks plausible.
    """
    session = _Session(
        messages=(
            _call("b", "polarize", child_ids=["x", "y"], correspondence=["ʔ", "Ø"]),
            _call("a", "summarize_correspondences", node_ids=["x", "y"]),
            _ok("a", "summarize_correspondences", {"matched_set_count": 27}),
            _ok("b", "polarize", {"columns_matched": 12, "matched_concept_count": 10}),
        )
    )
    turns = build_timeline(session)
    first, second = turns[0]["calls"][0], turns[1]["calls"][0]
    assert first["name"] == "polarize"
    assert "columns 12" in first["result_digest"]
    assert second["name"] == "summarize_correspondences"
    assert "sets matched 27" in second["result_digest"]


def test_a_rejection_keeps_its_code_its_category_and_its_remediation() -> None:
    session = _Session(
        messages=(
            _call("c", "commit_reconstruction", node_id="n", rules=[]),
            _rejected("c", "commit_reconstruction", "missing-rule-rationale", "no"),
        )
    )
    call = build_timeline(session)[0]["calls"][0]
    assert call["ok"] is False
    assert call["answered"] is True
    assert call["error_code"] == "missing-rule-rationale"
    assert call["error_category"] in {"protocol", "exploratory"}
    assert call["remediation"] == "do it the other way"


def test_an_unanswered_call_is_not_read_as_a_success() -> None:
    """A run killed between the call and its result must not look like a pass."""
    session = _Session(messages=(_call("d", "polarize", correspondence=["a", "b"]),))
    call = build_timeline(session)[0]["calls"][0]
    assert call["ok"] is False
    assert call["answered"] is False
    assert call["result_digest"] == "no recorded answer"


def test_an_unknown_tool_is_shown_as_other_rather_than_guessed_into_a_phase() -> None:
    """The phase map groups tool names for display and must not extrapolate.

    A tool added after this module was written has no place in the ribbon; the
    honest rendering is "other", not the phase whose name it happens to rhyme
    with.
    """
    assert "assess_change" not in TOOL_PHASES
    session = _Session(
        messages=(
            _call("e", "assess_change", whatever=1),
            _ok("e", "assess_change", {"score": 1}),
        )
    )
    assert build_timeline(session)[0]["calls"][0]["phase"] == "other"


def test_every_shipped_tool_has_a_phase() -> None:
    """The ribbon is only legible if the tools a run actually uses are mapped."""
    from cognate_reconstruction.agent.tools import default_tool_registry

    shipped = {definition.name for definition in default_tool_registry().definitions()}
    assert shipped <= set(TOOL_PHASES), sorted(shipped - set(TOOL_PHASES))


def test_digests_report_what_the_call_named_without_interpreting_it() -> None:
    text = digest_arguments(
        "test_sound_law",
        {"dsl": "ʔ > Ø / _V", "concept_ids": ["1", "2", "3", "4"], "source_child_ids": ["a:Tongan"]},
    )
    assert "ʔ > Ø / _V" in text
    assert "concepts 1, 2, 3 (+1)" in text
    assert "Tongan" in text


def test_a_result_with_no_mapped_fields_still_says_something() -> None:
    assert "count 3" in digest_result("some_new_tool", {"count": 3, "nested": {"x": 1}})


def test_a_payload_over_the_cap_is_truncated_and_says_so() -> None:
    session = _Session(
        messages=(
            _call("f", "get_alignments", concept_ids=["1"]),
            _ok("f", "get_alignments", {"blob": "x" * 5000}),
        )
    )
    call = build_timeline(session, payload_chars=400)[0]["calls"][0]
    assert len(call["result_json"]) < 600
    assert "trajectories.jsonl" in call["result_json"]


# ---------------------------------------------------------------------------
# the whole run
# ---------------------------------------------------------------------------


def test_a_real_pre_change_trajectory_renders_with_its_rejection_sequence(
    tmp_path,
) -> None:
    """The 2.0 fixture kept to catch schema drift must also stay viewable."""
    state = build_state(load_run(_run_dir(tmp_path)))
    node = state["nodes"]["PROTO"]
    assert node["source"] == "trajectory"
    assert node["status"] == "committed"
    commits = [
        call
        for turn in node["turns"]
        for call in turn["calls"]
        if call["name"] == "commit_reconstruction"
    ]
    assert [call["ok"] for call in commits] == [False, False, False, True]
    assert node["ribbon"][0]["phase"] == "survey"
    assert node["ribbon"][-1]["phase"] == "commit"


def test_the_page_is_one_self_contained_file(tmp_path) -> None:
    page = render_page(build_state(load_run(_run_dir(tmp_path))))
    assert page.startswith("<!doctype html>")
    assert not re.search(r"<(script|link|img)[^>]*\b(src|href)=", page)


def test_the_embedded_state_cannot_close_the_script_tag(tmp_path) -> None:
    """Model text reaches the page as data and must not be able to leave it."""
    directory = _run_dir(tmp_path)
    record = json.loads((directory / "trajectories.jsonl").read_text().splitlines()[0])
    record["messages"].append(
        {
            "role": "assistant",
            "content": "</script><script>window.__owned = 1;</script>",
            "tool_calls": [],
            "tool_call_id": None,
            "name": None,
        }
    )
    (directory / "trajectories.jsonl").write_text(
        json.dumps(record) + "\n", encoding="utf-8"
    )
    page = render_page(build_state(load_run(directory)))
    assert "window.__owned" not in page.split("window.__STATE__")[0]
    assert "<\\/script>" in page


def test_the_javascript_globals_survive_templating(tmp_path) -> None:
    """The state placeholder must not also rewrite the global it is assigned to."""
    page = render_page(build_state(load_run(_run_dir(tmp_path))), live=True)
    assert "window.__STATE__ = {" in page
    assert "window.__LIVE__ = true;" in page
    assert "%%STATE%%" not in page and "%%SCRIPT%%" not in page


# ---------------------------------------------------------------------------
# the tree, and what a failed node costs the nodes above it
# ---------------------------------------------------------------------------


def _result_with_failure(tmp_path: Path) -> Path:
    """A run whose middle node failed, so the root read an identity fallback."""
    directory = tmp_path / "tree"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "result.json").write_text(
        json.dumps(
            {
                "snapshot": {
                    "steps": [
                        {"parent_node_id": "low", "child_node_ids": ["leaf_a", "leaf_b"]},
                        {"parent_node_id": "mid", "child_node_ids": ["low", "leaf_c"]},
                        {"parent_node_id": "root", "child_node_ids": ["mid", "leaf_d"]},
                    ]
                },
                "internal_nodes": [],
                "trajectories": [],
                "historical_target_evaluations": [],
                "node_failures": [
                    {
                        "node_id": "mid",
                        "child_node_ids": ["low", "leaf_c"],
                        "error_type": "AgentLoopLimitError",
                        "reason": "no commit within the turn limit",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return directory


def test_the_tree_keeps_the_leaves_the_model_actually_read(tmp_path) -> None:
    tree = traversal_tree(load_run(_result_with_failure(tmp_path)))
    assert tree["roots"] == ["root"]
    assert tree["children"]["low"] == ("leaf_a", "leaf_b")
    assert tree["order"] == ["low", "mid", "root"]


def test_a_node_says_which_failed_sessions_sit_beneath_it(tmp_path) -> None:
    """The reason the tree is worth drawing: loss low down is loss higher up."""
    state = build_state(load_run(_result_with_failure(tmp_path)))
    assert state["nodes"]["root"]["fallbacks_beneath"] == ["mid"]
    assert state["nodes"]["mid"]["failure_fallback"] is True
    assert state["nodes"]["low"]["fallbacks_beneath"] == []


def test_an_internal_node_with_no_session_record_is_not_drawn_as_a_leaf(
    tmp_path,
) -> None:
    """A reconstructed node without a record is not an input language."""
    state = build_state(load_run(_result_with_failure(tmp_path)))
    assert set(state["nodes"]) == {"low", "mid", "root"}
    assert state["nodes"]["low"]["status"] == "unrecorded"
    assert state["nodes"]["low"]["note"]
    assert state["nodes"]["mid"]["status"] == "failed"


def test_a_gate_rejected_session_is_reported_in_full_not_filtered(tmp_path) -> None:
    """This view reports. Dropping a rejected session would make it a gate."""
    directory = _run_dir(tmp_path)
    state = build_state(load_run(directory))
    trajectory = load_run(directory).trajectories[0]
    node = state["nodes"][trajectory.node_id]
    assert node["high_quality"] == trajectory.high_quality
    assert list(node["quality_reasons"]) == list(
        trajectory.high_quality_failure_reasons
    )
    assert node["turns"], "a rejected session still shows its turns"


# ---------------------------------------------------------------------------
# live mode
# ---------------------------------------------------------------------------


def _events(directory: Path, *records: dict) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "events.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )
    return directory


def test_a_directory_with_nothing_in_it_yet_is_not_an_error(tmp_path) -> None:
    state = build_live_state(tmp_path / "empty")
    assert state["nodes"] == {}
    assert state["notes"]


def test_a_node_in_flight_renders_from_events_and_is_labelled_as_such(
    tmp_path,
) -> None:
    directory = _events(
        tmp_path / "live",
        {
            "kind": "node_start",
            "node_id": "mid",
            "message": "starting reconstruction",
            "details": {"active_child_ids": ["leaf_a", "leaf_b"], "model_id": "m"},
        },
        {
            "kind": "model_turn",
            "node_id": "mid",
            "message": "requesting model turn 1",
            "details": {},
        },
        {
            "kind": "tool_call",
            "node_id": "mid",
            "message": "calling tool polarize",
            "details": {
                "call_id": "1",
                "arguments": {"correspondence": ["ʔ", "Ø"], "child_ids": ["leaf_a"]},
            },
        },
        {
            "kind": "tool_result",
            "node_id": "mid",
            "message": "tool polarize succeeded",
            "details": {
                "call_id": "1",
                "error_code": None,
                "result": {"ok": True, "result": {"columns_matched": 4}},
            },
        },
    )
    state = build_live_state(directory)
    node = state["nodes"]["mid"]
    assert node["source"] == "events"
    assert node["status"] == "running"
    assert state["active_nodes"] == ["mid"]
    assert node["note"], "an in-flight node must say it is not a finished record"
    call = node["turns"][0]["calls"][0]
    assert call["name"] == "polarize" and call["ok"] is True
    assert "ʔ ~ Ø" in call["arguments_digest"]
    assert state["tree"]["children"]["mid"] == ["leaf_a", "leaf_b"]


def test_a_partly_written_event_line_does_not_sink_the_view(tmp_path) -> None:
    directory = tmp_path / "torn"
    directory.mkdir(parents=True)
    (directory / "events.jsonl").write_text(
        json.dumps(
            {
                "kind": "node_start",
                "node_id": "mid",
                "message": "starting",
                "details": {"active_child_ids": ["a"]},
            }
        )
        + "\n{\"kind\": \"tool_ca",
        encoding="utf-8",
    )
    assert "mid" in build_live_state(directory)["nodes"]


# ---------------------------------------------------------------------------
# the command
# ---------------------------------------------------------------------------


def test_the_command_writes_a_page_next_to_the_run_by_default(
    tmp_path, capsys
) -> None:
    directory = _run_dir(tmp_path)
    cli.main(["visualize-run", "--run-dir", str(directory)])
    destination = directory / DEFAULT_OUTPUT_NAME
    assert destination.exists()
    assert str(destination) in capsys.readouterr().out
    assert "<!doctype html>" in destination.read_text(encoding="utf-8")


def test_the_command_honours_an_explicit_destination(tmp_path) -> None:
    directory = _run_dir(tmp_path)
    destination = tmp_path / "elsewhere" / "view.html"
    cli.main(
        ["visualize-run", "--run-dir", str(directory), "--html", str(destination)]
    )
    assert destination.exists()


def test_a_directory_that_is_not_a_run_is_refused(tmp_path, capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["visualize-run", "--run-dir", str(tmp_path / "nope")])
    assert raised.value.code == 2
    assert "not a run directory" in capsys.readouterr().err
