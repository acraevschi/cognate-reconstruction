"""Branch agreement must reach the score, and convergence must be measurable.

Two defects are pinned here. The first is that `outputs` was a *set*, so four
children proposing one parent form and one child proposing another produced two
candidates with identical scores, and the winner was decided by the lexicographic
order of the segment tuple — rename the minority segment and the node changes its
mind. The second is that nothing measured whether a reconstruction made the
children agree at all: every diagnostic counted rules.

`tools/tiebreak_probe.py` is the runnable form of the first case; this is the
regression that keeps it fixed.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.inspection import inspected_concept_ids
from cognate_reconstruction.agent.orchestrator import AgentOrchestrator
from cognate_reconstruction.agent.schemas import (
    LLMMessage,
    LLMToolCall,
    LLMToolDefinition,
    MessageRole,
)
from cognate_reconstruction.agent.tools import default_tool_registry
from cognate_reconstruction.agent.trajectory import TrajectoryDatasetBuilder
from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.rules import parse_rule
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm
from cognate_reconstruction.schemas.rules import ReconstructionRule
from cognate_reconstruction.schemas.traversal import ReconstructionStep
from cognate_reconstruction.traversal.beam import make_leaf_beam
from cognate_reconstruction.traversal.reconstructor import RuleBasedReconstructor

PRE_CHANGE_TRAJECTORY = (
    Path(__file__).parent / "fixtures" / "trajectory_real_pre_change.jsonl"
)


def lexicon(variety_id: str, **concepts: str) -> LanguageLexicon:
    return LanguageLexicon(
        variety_id=variety_id,
        name=variety_id,
        forms=tuple(
            LexicalForm(
                form_id=f"{variety_id}:{concept_id}",
                variety_id=variety_id,
                concept_id=concept_id,
                segments=tuple(segments),
            )
            for concept_id, segments in concepts.items()
        ),
    )


def reconstruct(
    children: Sequence[LanguageLexicon],
    rules: Sequence[ReconstructionRule] = (),
    *,
    beam_width: int = 5,
    **kwargs: object,
) -> ReconstructionStep:
    beams = [make_leaf_beam(item, beam_width=beam_width) for item in children]
    return RuleBasedReconstructor(beam_width=beam_width).reconstruct(
        "PROTO", beams, rules=rules, **kwargs
    )


# ---------------------------------------------------------------------------
# branch support
# ---------------------------------------------------------------------------


def test_four_supporting_branches_outrank_one() -> None:
    """Case A of `tools/tiebreak_probe.py`: 4-vs-1 must not be a tie."""
    step = reconstruct(
        [lexicon(f"c{index}", probe="aka") for index in range(1, 5)]
        + [lexicon("c5", probe="aʔa")]
    )
    candidates = step.output_beam.distributions[0].candidates
    assert candidates[0].segments == ("a", "k", "a")
    assert math.isclose(candidates[0].probability, 0.8)
    assert math.isclose(candidates[1].probability, 0.2)


def test_majority_still_wins_when_the_minority_segment_sorts_first() -> None:
    """Case B, the actual bug: the same shape with `W` in place of `ʔ`.

    `W` sorts before `k`, so under the old flat branch penalty — equal scores
    broken by segment order — the one-branch form won the node. Nothing about
    the evidence changed between this test and the one above, so nothing about
    the outcome may change either.
    """
    step = reconstruct(
        [lexicon(f"c{index}", probe="aka") for index in range(1, 5)]
        + [lexicon("c5", probe="aWa")]
    )
    candidates = step.output_beam.distributions[0].candidates
    assert candidates[0].segments == ("a", "k", "a")
    assert math.isclose(candidates[0].probability, 0.8)


def test_equal_support_scores_exactly_as_the_old_branch_penalty_did() -> None:
    """Two branches, one form each, is still an even split.

    The support weight generalizes `-log(len(outputs))` rather than replacing it
    with something new: where every distinct output has equal support the two
    rules agree exactly, which is every binary node whose children disagree.
    """
    step = reconstruct([lexicon("A", probe="ak"), lexicon("B", probe="at")])
    candidates = step.output_beam.distributions[0].candidates
    assert len(candidates) == 2
    assert all(
        math.isclose(candidate.probability, 0.5) for candidate in candidates
    )
    assert all(
        math.isclose(candidate.log_score, -math.log(2))
        for candidate in candidates
    )


def test_derivations_name_the_branches_behind_each_candidate() -> None:
    step = reconstruct(
        [lexicon("A", probe="ak"), lexicon("B", probe="ak"), lexicon("C", probe="at")]
    )
    supporters = {
        candidate.segments: set(candidate.derivations[0].supporting_child_ids)
        for candidate in step.output_beam.distributions[0].candidates
    }
    assert supporters[("a", "k")] == {"A", "B"}
    assert supporters[("a", "t")] == {"C"}


def test_a_rule_that_reconciles_the_minority_gives_the_form_full_support() -> None:
    step = reconstruct(
        [lexicon(f"c{index}", probe="aka") for index in range(1, 5)]
        + [lexicon("c5", probe="aʔa")],
        rules=[
            ReconstructionRule(
                rule=parse_rule("ʔ > k"), source_child_ids=("c5",), confidence=0.9
            )
        ],
    )
    candidates = step.output_beam.distributions[0].candidates
    assert len(candidates) == 1
    assert candidates[0].segments == ("a", "k", "a")
    assert len(candidates[0].derivations[0].supporting_child_ids) == 5


# ---------------------------------------------------------------------------
# convergence diagnostics
# ---------------------------------------------------------------------------


def contradictory_children() -> tuple[LanguageLexicon, LanguageLexicon]:
    """The shape of the live Tongan/Niuean node.

    One session committed `f > p / _eː` scoped to one child and `p > f / _e`
    scoped to the other: mutually contradictory claims about the same
    correspondence, both accepted at confidence 1.0, guaranteeing that the
    children could not agree on a parent form.
    """
    return (
        lexicon("Tongan", one="fe", two="pe"),
        lexicon("Niuean", one="fe", two="pe"),
    )


def test_contradictory_cross_child_rules_produce_low_convergence() -> None:
    tongan, niuean = contradictory_children()
    step = reconstruct(
        [tongan, niuean],
        rules=[
            ReconstructionRule(
                rule=parse_rule("f > p / _e", rule_id="tongan-side"),
                source_child_ids=("Tongan",),
                confidence=1.0,
            ),
            ReconstructionRule(
                rule=parse_rule("p > f / _e", rule_id="niuean-side"),
                source_child_ids=("Niuean",),
                confidence=1.0,
            ),
        ],
    )
    diagnostics = step.diagnostics
    assert diagnostics.child_convergence_rate == 0.0
    assert diagnostics.divergent_concept_count == 2
    assert set(diagnostics.divergent_concept_ids) == {"one", "two"}
    # Every rule fired exactly as written, so the rule diagnostics report a
    # flawless node. Convergence is the only number that sees the problem.
    assert diagnostics.rule_coverage == 1.0
    assert math.isclose(diagnostics.mean_branch_support, 0.5)


def test_divergence_is_scored_and_reported_but_never_rejected() -> None:
    """The step exists, carries a full beam, and raises nothing."""
    tongan, niuean = contradictory_children()
    step = reconstruct(
        [tongan, niuean],
        rules=[
            ReconstructionRule(
                rule=parse_rule("f > p / _e"),
                source_child_ids=("Tongan",),
                confidence=1.0,
            ),
        ],
    )
    assert len(step.output_beam.distributions) == 2
    assert step.diagnostics.child_convergence_rate < 1.0


def test_agreeing_children_report_full_convergence_and_support() -> None:
    step = reconstruct(
        [
            lexicon("A", one="pa", two="ku"),
            lexicon("B", one="pa", two="ku"),
            lexicon("C", one="pa", two="ku"),
        ]
    )
    diagnostics = step.diagnostics
    assert diagnostics.child_convergence_rate == 1.0
    assert diagnostics.divergent_concept_count == 0
    assert diagnostics.divergent_concept_ids == ()
    assert math.isclose(diagnostics.mean_branch_support, 1.0)


def test_branch_support_separates_agreement_from_attestation() -> None:
    """A concept only one child attests converges trivially; support says so."""
    step = reconstruct(
        [
            lexicon("A", shared="pa", lonely="ti"),
            lexicon("B", shared="pa"),
            lexicon("C", shared="pa"),
        ]
    )
    assert step.diagnostics.child_convergence_rate == 1.0
    # 'shared' has 3 of 3 children behind the winner, 'lonely' has 1 of 3.
    assert math.isclose(step.diagnostics.mean_branch_support, (1.0 + 1 / 3) / 2)


def test_tie_broken_forms_are_counted_so_arbitrary_choices_are_visible() -> None:
    """A reader must be able to tell an evidenced form from a coin-flip.

    Two children, one form each, is a genuine tie: `TIE_BREAK_POLICY` picks the
    winner on segment order and the beam prints p=0.50 either way. The count is
    the only thing that says so.
    """
    tied = reconstruct(
        [
            lexicon("A", one="ak", two="pa"),
            lexicon("B", one="at", two="pa"),
        ]
    )
    assert tied.diagnostics.tie_broken_concept_count == 1
    assert tied.diagnostics.concepts_available == 2

    # Four branches against one is no longer a tie, which is the whole point of
    # weighting by support.
    supported = reconstruct(
        [lexicon(f"c{index}", probe="aka") for index in range(1, 5)]
        + [lexicon("c5", probe="aWa")]
    )
    assert supported.diagnostics.tie_broken_concept_count == 0


def test_a_single_candidate_is_never_counted_as_tie_broken() -> None:
    step = reconstruct([lexicon("A", one="pa"), lexicon("B", one="pa")])
    assert len(step.output_beam.distributions[0].candidates) == 1
    assert step.diagnostics.tie_broken_concept_count == 0


def test_evidence_coverage_defaults_to_unrecorded_without_an_agent_layer() -> None:
    """A purely deterministic run must not claim it inspected nothing."""
    step = reconstruct([lexicon("A", one="pa"), lexicon("B", one="pa")])
    assert step.diagnostics.concepts_inspected is None
    assert step.diagnostics.concepts_available == 1

    inspected = reconstruct(
        [lexicon("A", one="pa", two="ku"), lexicon("B", one="pa", two="ku")],
        inspected_concept_ids=("one", "elsewhere"),
    )
    assert inspected.diagnostics.concepts_inspected == 1
    assert inspected.diagnostics.concepts_available == 2


# ---------------------------------------------------------------------------
# convergence reported to the model
# ---------------------------------------------------------------------------


def agent_context() -> AgentContext:
    tongan, niuean = contradictory_children()
    return AgentContext(
        node_id="PROTO",
        child_lexicons=(tongan, niuean),
        aligner=LingPyAligner(),
    )


def test_cascade_result_reports_per_concept_convergence() -> None:
    context = agent_context()
    result = default_tool_registry().execute(
        LLMToolCall(
            call_id="cascade",
            name="test_rule_cascade",
            arguments={
                "rules": [
                    {
                        "rule_id": "tongan-side",
                        "dsl": "f > p / _e",
                        "source_child_ids": ["Tongan"],
                    }
                ]
            },
        ),
        context,
    )
    assert result.ok and result.result is not None
    convergence = result.result["convergence"]
    assert convergence["concepts_evaluated"] == 2
    assert convergence["converged_concepts"] == 1
    assert convergence["child_convergence_rate"] == 0.5
    assert convergence["divergent_concept_ids"] == ["one"]
    by_concept = {item["concept_id"]: item for item in convergence["concepts"]}
    assert by_concept["one"]["converged"] is False
    assert by_concept["two"]["converged"] is True


def test_commit_result_reports_convergence_and_still_commits() -> None:
    context = agent_context()
    registry = default_tool_registry()
    validation = registry.execute(
        LLMToolCall(
            call_id="validate",
            name="test_sound_law",
            arguments={"dsl": "f > p / _e", "source_child_ids": ["Tongan"]},
        ),
        context,
    )
    assert validation.ok
    result = registry.execute(
        LLMToolCall(
            call_id="commit",
            name="commit_reconstruction",
            arguments={
                "node_id": "PROTO",
                "rules": [
                    {
                        "rule_id": "tongan-side",
                        "dsl": "f > p / _e",
                        "source_child_ids": ["Tongan"],
                        "confidence": 1.0,
                        "validation_call_id": "validate",
                        # Tongan already has `p`, so this rule merges `f` into
                        # it and the commit contract requires the claim to be
                        # stated. The harness never reads what it says.
                        "directionality_rationale": (
                            "Claiming Tongan innovated f from parent p."
                        ),
                    }
                ],
                "anomalies": [],
                "summary": "One-sided claim about the same correspondence.",
            },
        ),
        context,
    )
    assert result.ok and result.result is not None
    assert result.result["status"] == "committed"
    convergence = result.result["convergence"]
    assert convergence["child_convergence_rate"] == 0.5
    assert convergence["divergent_concept_ids"] == ["one"]
    # A commit summary stays small: the per-concept listing is cascade-only.
    assert convergence["concepts"] == []


# ---------------------------------------------------------------------------
# evidence coverage plumbing
# ---------------------------------------------------------------------------


def test_named_and_unscoped_calls_both_count_as_inspection() -> None:
    available = {"one", "two"}
    forms = {"Tongan:one": "one"}
    assert inspected_concept_ids(
        "get_alignments",
        {"node_ids": ["Tongan", "Niuean"], "concept_ids": ["one"]},
        concepts_by_form_id=forms,
        available_concept_ids=available,
    ) == {"one"}
    assert inspected_concept_ids(
        "get_alignments",
        {"form_ids": ["Tongan:one"]},
        concepts_by_form_id=forms,
        available_concept_ids=available,
    ) == {"one"}
    # An unscoped survey is the widest look the harness offers, not the narrowest.
    assert (
        inspected_concept_ids(
            "summarize_correspondences",
            {"node_ids": ["Tongan", "Niuean"]},
            concepts_by_form_id=forms,
            available_concept_ids=available,
        )
        == available
    )
    # A paginated search that names nothing claims nothing.
    assert (
        inspected_concept_ids(
            "search_forms",
            {"limit": 50},
            concepts_by_form_id=forms,
            available_concept_ids=available,
        )
        == set()
    )
    # Unknown IDs cannot push coverage past what exists.
    assert (
        inspected_concept_ids(
            "get_alignments",
            {"concept_ids": ["invented"]},
            concepts_by_form_id=forms,
            available_concept_ids=available,
        )
        == set()
    )


class InspectingProvider:
    """Looks at one concept, tests a law, then commits."""

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
        self.turn += 1
        if self.turn == 1:
            return LLMMessage(
                role=MessageRole.ASSISTANT,
                tool_calls=(
                    LLMToolCall(
                        call_id="look",
                        name="get_alignments",
                        arguments={
                            "node_ids": ["Tongan", "Niuean"],
                            "concept_ids": ["one"],
                        },
                    ),
                ),
            )
        if self.turn == 2:
            return LLMMessage(
                role=MessageRole.ASSISTANT,
                tool_calls=(
                    LLMToolCall(
                        call_id="validate",
                        name="test_sound_law",
                        arguments={
                            "dsl": "f > p / _e",
                            "source_child_ids": ["Tongan"],
                            "concept_ids": ["one"],
                        },
                    ),
                ),
            )
        return LLMMessage(
            role=MessageRole.ASSISTANT,
            tool_calls=(
                LLMToolCall(
                    call_id="commit",
                    name="commit_reconstruction",
                    arguments={
                        "node_id": "PROTO",
                        "rules": [
                            {
                                "rule_id": "tongan-side",
                                "dsl": "f > p / _e",
                                "source_child_ids": ["Tongan"],
                                "confidence": 1.0,
                                "validation_call_id": "validate",
                                "directionality_rationale": (
                                    "Claiming Tongan innovated f from parent p."
                                ),
                            }
                        ],
                        "anomalies": [],
                        "summary": "Committed after inspecting one concept.",
                    },
                ),
            ),
        )


def test_a_session_records_how_much_evidence_it_looked_at() -> None:
    run_result = AgentOrchestrator(
        InspectingProvider(), instructions="Look, test, commit."
    ).run(agent_context())
    metrics = run_result.trajectory.metrics
    assert metrics.concepts_inspected == 1
    assert metrics.concepts_available == 2
    assert run_result.inspected_concept_ids == ("one",)


# ---------------------------------------------------------------------------
# append-only readability
# ---------------------------------------------------------------------------


def test_a_step_written_before_convergence_existed_still_loads() -> None:
    trajectory = TrajectoryDatasetBuilder.read_jsonl(PRE_CHANGE_TRAJECTORY)[0]
    step = trajectory.reconstruction_step
    assert step is not None
    diagnostics = step.diagnostics
    # Absent means "not recorded", never "nothing converged" or "nothing seen".
    assert diagnostics.child_convergence_rate is None
    assert diagnostics.divergent_concept_count is None
    assert diagnostics.divergent_concept_ids == ()
    assert diagnostics.mean_branch_support is None
    assert diagnostics.concepts_inspected is None
    assert diagnostics.concepts_available is None
    assert diagnostics.tie_broken_concept_count is None
    # And the record it was read from carries none of these keys at all.
    raw = json.loads(PRE_CHANGE_TRAJECTORY.read_text(encoding="utf-8").splitlines()[0])
    assert "child_convergence_rate" not in raw["reconstruction_step"]["diagnostics"]
    derivation = raw["reconstruction_step"]["output_beam"]["distributions"][0][
        "candidates"
    ][0]["derivations"][0]
    assert "supporting_child_ids" not in derivation
