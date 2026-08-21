"""Every node with gold is scored, a fallback node is never scored as one, and
a sweep reports the spread rather than a number.

Three separate claims, kept in one file because they are the same claim seen
from three distances: a reconstruction score has to say which node it belongs
to, whether that node was actually reconstructed, and how much it varies.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from cognate_reconstruction.agent.orchestrator import AgentOrchestrator
from cognate_reconstruction.agent.reconstructor import AgenticNodeReconstructor
from cognate_reconstruction.agent.schemas import (
    LLMMessage,
    LLMToolCall,
    LLMToolDefinition,
    MessageRole,
)
from cognate_reconstruction.agent.service import ReconstructionService
from cognate_reconstruction.benchmarks.sweep import aggregate, read_seed
from cognate_reconstruction.ingestion import ingest_payload
from cognate_reconstruction.schemas.historical import (
    GoldEvidenceKind,
    HistoricalFormBinding,
    HistoricalFormRole,
)
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm

CONCEPTS = ("water", "fire", "stone")
FORMS = {
    "A": {"water": ("p", "a"), "fire": ("p", "u", "r"), "stone": ("k", "a")},
    "B": {"water": ("p", "a"), "fire": ("p", "u", "r"), "stone": ("k", "a")},
    "C": {"water": ("p", "a"), "fire": ("p", "u", "l"), "stone": ("k", "o")},
}
GOLD = {
    "INNER": {"water": ("p", "a"), "fire": ("p", "u", "r"), "stone": ("k", "a")},
    # Deliberately one segment off at `stone`, so the root scores worse than the
    # inner node and a per-node report is the only way to see it.
    "PROTO": {"water": ("p", "a"), "fire": ("p", "u", "r"), "stone": ("k", "u")},
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
            )
            for concept_id, segments in FORMS[variety_id].items()
        ),
    )


def _binding(node_id: str) -> HistoricalFormBinding:
    return HistoricalFormBinding(
        node_id=node_id,
        role=HistoricalFormRole.TARGET,
        source_variety_id=f"gold:{node_id}",
        forms=tuple(
            LexicalForm(
                form_id=f"gold:{node_id}:{concept_id}",
                variety_id=node_id,
                concept_id=concept_id,
                segments=segments,
            )
            for concept_id, segments in GOLD[node_id].items()
        ),
        gold_evidence_kind=GoldEvidenceKind.RECONSTRUCTED,
    )


class _IdentityProvider:
    model = "scripted/identity"

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[LLMToolDefinition],
        *,
        tool_choice: str = "auto",
        max_tokens_override: int | None = None,
    ) -> LLMMessage:
        # The prompt is a sentence followed by the JSON payload; the node ID
        # is the payload's first field.
        content = messages[1].content or ""
        node_id = json.loads(content[content.index("{") :])["node_id"]
        return LLMMessage(
            role=MessageRole.ASSISTANT,
            tool_calls=(
                LLMToolCall(
                    call_id="commit",
                    name="commit_reconstruction",
                    arguments={
                        "node_id": node_id,
                        "rules": [],
                        "anomalies": [],
                        "summary": "Identity reconstruction for the target test.",
                    },
                ),
            ),
        )


def _run():
    dataset = ingest_payload(
        WorkbenchPayload(
            lexicons=(_lexicon("A"), _lexicon("B"), _lexicon("C")),
            newick="((A,B)INNER,C)PROTO;",
            historical_form_bindings=(_binding("INNER"), _binding("PROTO")),
        )
    )
    service = ReconstructionService(
        AgenticNodeReconstructor(
            AgentOrchestrator(
                _IdentityProvider(),
                run_id="multi-target",
                configuration_sha256="multi-target-config",
            )
        )
    )
    return service.reconstruct_family(dataset)


def test_every_internal_node_carrying_gold_is_evaluated() -> None:
    """Not only the root. A dataset supplying intermediate proto-forms gets a
    score at each of them, which is how a family with a good root and bad lower
    nodes becomes distinguishable from a uniformly mediocre one."""
    result = _run()
    by_node = {
        evaluation.node_id: evaluation
        for evaluation in result.historical_target_evaluations
    }
    assert set(by_node) == {"INNER", "PROTO"}
    assert by_node["INNER"].top_exact_rate == 1.0
    # The root misses `stone` by one segment, which exact match reports as a
    # miss and the graded metrics quantify.
    assert by_node["PROTO"].top_exact_rate < 1.0


def test_graded_metrics_reach_the_result_and_quantify_the_miss() -> None:
    result = _run()
    root = next(
        evaluation
        for evaluation in result.historical_target_evaluations
        if evaluation.node_id == "PROTO"
    )
    stone = next(
        concept for concept in root.concepts if concept.concept_id == "stone"
    )
    assert not stone.top_exact_match
    assert stone.top_edit_distance == 1
    assert stone.top_normalized_edit_distance == 0.5
    assert stone.nearest_target_segments == ("k", "u")
    # Structurally consistent even though the segment is wrong, which is what
    # separates a near miss from a guess.
    assert stone.top_bcubed_f1 == 1.0
    graded = root.graded
    assert graded is not None
    assert graded.top_normalized_edit_distance is not None
    assert graded.top_normalized_edit_distance.count == 3
    assert graded.normalized_edit_distance_selection_gap is not None
    assert graded.top_bcubed_f1 is not None
    # The gold's nature travels with the score.
    assert root.gold_evidence_kind is GoldEvidenceKind.RECONSTRUCTED
    assert not root.failure_fallback


def _write_run(path: Path, *, fallback_nodes: tuple[str, ...] = ()) -> None:
    """A minimal run directory, enough for the sweep reader."""
    result = _run()
    payload = json.loads(result.model_dump_json())
    payload["node_failures"] = [
        {
            "node_id": node_id,
            "child_node_ids": [],
            "error_type": "AgentLoopLimitError",
            "reason": "agent did not commit within its per-node turn limit",
            "trajectory_id": None,
        }
        for node_id in fallback_nodes
    ]
    for evaluation in payload["historical_target_evaluations"]:
        if evaluation["node_id"] in fallback_nodes:
            evaluation["failure_fallback"] = True
    path.mkdir(parents=True, exist_ok=True)
    (path / "result.json").write_text(json.dumps(payload), encoding="utf-8")
    (path / "trajectories.jsonl").write_text(
        "\n".join(
            trajectory.model_dump_json() for trajectory in result.trajectories
        )
        + "\n",
        encoding="utf-8",
    )


def test_a_sweep_never_counts_a_fallback_node_as_a_reconstruction(
    tmp_path,
) -> None:
    """The false number this harness exists to avoid.

    A run that walked over two dead nodes still has beams for them, and those
    beams are the harness's identity fallback, not reconstructions. Counting
    them as completions, or scoring them against gold, would report a run of
    seven reconstructions when it made five.
    """
    finished = tmp_path / "seed-00"
    _write_run(finished, fallback_nodes=("PROTO",))
    outcome = read_seed(0, "seed0", finished, 0)
    assert outcome.result_written
    assert outcome.fallback_nodes == ("PROTO",)

    summary = aggregate([outcome], benchmark="fixture", model="scripted", oracle=None)
    gold = summary["gold_targets"]
    assert gold["excluded_fallback_evaluations"] == 1
    assert gold["scored_evaluations"] == 1
    assert set(gold["by_node"]) == {"INNER"}
    assert summary["failure_taxonomy"] == {"AgentLoopLimitError": 1}


def test_a_sweep_distinguishes_an_abandoned_run_from_one_with_losses(
    tmp_path,
) -> None:
    """Two different results, and a runner that conflates them reports neither.

    A seed that exhausted `--max-failed-nodes` raises `TooManyNodeFailuresError`
    and writes no `result.json` at all, so its losses are not in `node_failures`
    either. It is counted in the taxonomy under its own name.
    """
    finished = tmp_path / "seed-00"
    _write_run(finished)
    abandoned = tmp_path / "seed-01"
    abandoned.mkdir()
    (abandoned / "trajectories.jsonl").write_text("", encoding="utf-8")

    outcomes = [
        read_seed(0, "seed0", finished, 0),
        read_seed(1, "seed1", abandoned, 2),
    ]
    assert not outcomes[0].abandoned
    assert outcomes[1].abandoned
    summary = aggregate(
        outcomes, benchmark="fixture", model="scripted", oracle=None
    )
    assert summary["seeds"] == 2
    assert summary["seeds_with_result"] == 1
    assert summary["seeds_abandoned"] == 1
    assert summary["failure_taxonomy"]["run-abandoned-no-result"] == 1


def test_a_sweep_reports_spread_rather_than_a_quotable_single_number(
    tmp_path,
) -> None:
    """Make the single number hard to quote by accident.

    Two seeds go in; every rate comes out as a distribution with a count and a
    standard deviation attached, and the per-seed table sits beside it.
    """
    for index in range(2):
        _write_run(tmp_path / f"seed-{index:02d}")
    outcomes = [
        read_seed(index, f"seed{index}", tmp_path / f"seed-{index:02d}", 0)
        for index in range(2)
    ]
    summary = aggregate(
        outcomes, benchmark="fixture", model="scripted", oracle=None
    )
    top = summary["gold_targets"]["top_exact_rate"]
    assert top["count"] == 4
    assert "standard_deviation" in top
    assert len(summary["seed_outcomes"]) == 2
    ned = summary["gold_targets"]["mean_top_normalized_edit_distance"]
    assert ned is not None and ned["count"] == 4
    # Per-node, so a good root and a bad lower node cannot average away.
    assert set(summary["gold_targets"]["by_node"]) == {"INNER", "PROTO"}


def test_inspect_run_puts_the_gold_score_inside_the_outcome_block(
    tmp_path,
) -> None:
    """An accuracy is the number most likely to be quoted alone.

    So it goes inside `DETERMINISTIC OUTCOME`, below rule coverage, contrast
    loss, convergence, the held-out concept split, branch support, and the
    tie-break count — because a node can be exact on half its concepts by
    discarding a distinction its sisters preserved, and the block is the
    arrangement that keeps that visible.

    The two senses of "held out" are also checked apart here. One is a split of
    the session's own concepts; the other is the answer key.
    """
    from cognate_reconstruction.inspect_run import build_report, load_run, render_text

    run_dir = tmp_path / "run"
    _write_run(run_dir)
    report = render_text(build_report(load_run(run_dir)))
    assert "DETERMINISTIC OUTCOME" in report
    assert "gold exact" in report
    assert "gold distance" in report
    assert "normalized edit distance, lower is better" in report
    assert "gold b-cubed" in report
    assert "structural agreement F1, higher is better" in report
    # Inside the block, not above it: every one of these lines precedes it.
    outcome = report.index("gold exact")
    for earlier in ("rule coverage", "contrast loss", "child convergence",
                    "held-out concepts", "tie-broken forms"):
        assert report.index(earlier) < outcome, earlier
    # The two "held out" senses are named apart.
    assert "held-out concepts" in report
    assert "held out " not in report.replace("held-out concepts", "")


def test_inspect_run_marks_a_gold_score_computed_over_a_fallback_node(
    tmp_path,
) -> None:
    """A node that failed is not a node that reconstructed.

    Its beam is the harness's identity commit, so the score against gold
    measures the fallback. The number is still printed — suppressing it would
    hide that the node exists — and it is printed with what it is.
    """
    from cognate_reconstruction.inspect_run import build_report, load_run, render_text

    run_dir = tmp_path / "run"
    _write_run(run_dir, fallback_nodes=("PROTO",))
    report = render_text(build_report(load_run(run_dir)))
    assert "gold caveat" in report
    assert "this node was NOT reconstructed" in report
    assert "THIS NODE WAS NOT RECONSTRUCTED" in report
