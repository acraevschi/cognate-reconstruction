"""What it costs to look at the evidence.

A live benchmark could not be completed because inspecting evidence cost more
context than reasoning about it: one `get_alignments` call for six concepts
across two languages returned 31 KB, and the same call across ten languages
returned nearly 3 MB, because every pairwise view re-embedded the alignments and
every correspondence carried the aligner's whole working trace.

These tests cover the four things that changed: the compact alignment payload,
the correspondence-set inventory, the correspondence maps recorded in a
reconstruction step, and dropping superseded tool results from the live prompt.
Sizes are asserted as ratios rather than byte counts so they measure the shape of
the payload and not the width of a field name.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import pytest
from pydantic import ValidationError

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.events import AgentEventKind
from cognate_reconstruction.agent.orchestrator import (
    COMPACTABLE_TOOL_NAMES,
    AgentOrchestrator,
    _supersedes,
)
from cognate_reconstruction.agent.schemas import (
    LLMMessage,
    LLMToolCall,
    LLMToolDefinition,
    MessageRole,
)
from cognate_reconstruction.agent.tools import default_tool_registry
from cognate_reconstruction.agent.trajectory import AgentTrajectory
from cognate_reconstruction.alignment import build_correspondence_sets
from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.schemas.alignment import (
    MAX_CORRESPONDENCE_EXAMPLES,
    AlignmentMember,
    AlignmentResult,
    CorrespondenceDetail,
    CorrespondenceExample,
    CorrespondenceMap,
    CorrespondenceSummary,
    MultipleAlignmentMap,
)
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm
from cognate_reconstruction.schemas.traversal import (
    EvidenceKind,
    EvidenceRelation,
    NodeEvidence,
    NodeReconstructionContext,
)
from cognate_reconstruction.traversal import RuleBasedReconstructor
from cognate_reconstruction.traversal.beam import make_leaf_beam

# Four cognate sets whose correspondences recur: initial t~t~k, medial l~l~r,
# and a Tongan-style ʔ against a gap. Enough for support counts above one.
_FORMS: dict[str, dict[str, tuple[str, ...]]] = {
    "A": {
        "three": ("t", "o", "l", "u"),
        "hand": ("l", "i", "m", "a"),
        "fish": ("ʔ", "i", "k", "a"),
        "sky": ("l", "a", "ŋ", "i"),
    },
    "B": {
        "three": ("t", "o", "l", "u"),
        "hand": ("l", "i", "m", "a"),
        "fish": ("ʔ", "i", "k", "a"),
        "sky": ("l", "a", "ŋ", "i"),
    },
    "C": {
        "three": ("k", "o", "r", "u"),
        "hand": ("r", "i", "m", "a"),
        "fish": ("i", "k", "a"),
        "sky": ("r", "a", "ŋ", "i"),
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
                cognate_set_id=f"cog-{concept_id}",
            )
            for concept_id, segments in _FORMS[variety_id].items()
        ),
    )


def _context(*variety_ids: str) -> AgentContext:
    lexicons = tuple(_lexicon(variety_id) for variety_id in variety_ids)
    return AgentContext(
        node_id="PROTO",
        child_lexicons=lexicons,
        aligner=LingPyAligner(),
        evidence=tuple(
            NodeEvidence(
                node_id=lexicon.variety_id,
                kind=EvidenceKind.OBSERVED,
                relation=EvidenceRelation.ACTIVE_CHILD,
                lexicon=lexicon,
            )
            for lexicon in lexicons
        ),
    )


def _call(name: str, **arguments):
    context = arguments.pop("context")
    return default_tool_registry().execute(
        LLMToolCall(call_id=f"{name}-call", name=name, arguments=arguments),
        context,
    )


def _bytes(payload) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode())


def _alignment_map(result) -> MultipleAlignmentMap:
    # Tool results are JSON, and these models are strict: a JSON array is a
    # tuple only through JSON validation, exactly as the registry validates
    # arguments.
    return MultipleAlignmentMap.model_validate_json(
        json.dumps(result.result["alignment_map"])
    )


# --------------------------------------------------------------------------
# 1. the alignment payload
# --------------------------------------------------------------------------


def test_summary_is_the_default_and_carries_counts_without_the_trace() -> None:
    result = _call(
        "get_alignments",
        context=_context("A", "B", "C"),
        node_ids=["A", "B", "C"],
        concept_ids=["three", "hand", "fish", "sky"],
    )
    assert result.ok
    payload = _alignment_map(result)
    assert payload.detail is CorrespondenceDetail.SUMMARY

    summaries = [
        summary
        for pairwise in payload.pairwise_correspondences
        for summary in pairwise.correspondences
    ]
    assert summaries
    # The count is the true occurrence count; the trace is not present at all,
    # and the examples are a bounded sample rather than the trace.
    assert all(not summary.example_observations for summary in summaries)
    assert all(
        0 < len(summary.example_columns) <= MAX_CORRESPONDENCE_EXAMPLES
        for summary in summaries
    )
    recurring = {
        (summary.left_segment, summary.right_segment): summary.count
        for summary in payload.pairwise_correspondences[1].correspondences
    }
    assert payload.pairwise_correspondences[1].left_variety_id == "A"
    assert payload.pairwise_correspondences[1].right_variety_id == "C"
    assert recurring[("l", "r")] == 3
    assert recurring[("t", "k")] == 1


def test_pairwise_views_reference_the_alignments_instead_of_copying_them() -> None:
    context = _context("A", "B", "C")
    concepts = ["three", "hand", "fish", "sky"]
    result = _call(
        "get_alignments",
        context=context,
        node_ids=["A", "B", "C"],
        concept_ids=concepts,
    )
    payload = _alignment_map(result)
    known = {alignment.alignment_id for alignment in payload.alignments}
    assert len(known) == len(concepts)
    for pairwise in payload.pairwise_correspondences:
        assert pairwise.alignment_ids
        # Every reference resolves against the single copy of the alignments.
        assert set(pairwise.alignment_ids) <= known
        for summary in pairwise.correspondences:
            for example in summary.example_columns:
                assert example.alignment_id in known
                alignment = next(
                    item
                    for item in payload.alignments
                    if item.alignment_id == example.alignment_id
                )
                assert example.column_index < len(alignment.members[0].aligned_segments)


def test_the_compact_payload_is_smaller_and_stops_growing_quadratically() -> None:
    """The ten-language number is the one that matters.

    Under the old shape each of the N·(N−1)/2 pairwise views carried its own copy
    of the alignments, so adding a language multiplied the payload. Here the
    three-node summary must stay close to a fixed cost per pair rather than
    re-serializing the alignments per pair.
    """
    context = _context("A", "B", "C")
    concepts = ["three", "hand", "fish", "sky"]
    summary = _call(
        "get_alignments",
        context=context,
        node_ids=["A", "B", "C"],
        concept_ids=concepts,
        detail="summary",
    )
    full = _call(
        "get_alignments",
        context=context,
        node_ids=["A", "B", "C"],
        concept_ids=concepts,
        detail="full",
    )
    assert summary.ok and full.ok
    assert _bytes(summary.result) < _bytes(full.result)

    payload = _alignment_map(summary)
    alignments_bytes = _bytes(
        [alignment.model_dump(mode="json") for alignment in payload.alignments]
    )
    pairwise_bytes = _bytes(
        [
            pairwise.model_dump(mode="json")
            for pairwise in payload.pairwise_correspondences
        ]
    )
    # Three pairwise views together must not cost what three copies of the
    # alignments would have cost.
    assert pairwise_bytes < 3 * alignments_bytes


def test_full_detail_still_returns_every_column_occurrence() -> None:
    result = _call(
        "get_alignments",
        context=_context("A", "C"),
        node_ids=["A", "C"],
        concept_ids=["three", "hand", "sky"],
        detail="full",
    )
    payload = _alignment_map(result)
    assert payload.detail is CorrespondenceDetail.FULL
    summaries = payload.pairwise_correspondences[0].correspondences
    assert summaries
    for summary in summaries:
        assert len(summary.example_observations) == summary.count
        observation = summary.example_observations[0]
        assert observation.left_segment == summary.left_segment
        assert observation.right_segment == summary.right_segment
        # Contexts are what makes the full trace expensive, and they are here.
        assert len(observation.left_context) == 2


def test_the_example_sample_stays_bounded_while_the_count_does_not() -> None:
    """Recurrence is what the count is for, so it must not be capped with it."""
    repeated = tuple(
        LanguageLexicon(
            variety_id=variety_id,
            name=variety_id,
            forms=tuple(
                LexicalForm(
                    form_id=f"{variety_id}:c{index}",
                    variety_id=variety_id,
                    concept_id=f"c{index}",
                    segments=(segment, "a"),
                    cognate_set_id=f"cog-{index}",
                )
                for index in range(6)
            ),
        )
        for variety_id, segment in (("A", "t"), ("B", "k"))
    )
    pairwise = LingPyAligner().align_multiple(
        repeated, correspondence_detail=CorrespondenceDetail.SUMMARY
    ).pairwise_correspondences[0]
    summary = next(
        item
        for item in pairwise.correspondences
        if (item.left_segment, item.right_segment) == ("t", "k")
    )
    assert summary.count == 6
    assert len(summary.example_columns) == MAX_CORRESPONDENCE_EXAMPLES
    # Three pointers means three *different* pointers.
    assert len(set(summary.example_columns)) == MAX_CORRESPONDENCE_EXAMPLES


def test_a_correspondence_count_may_exceed_its_sample_but_never_lie() -> None:
    example = CorrespondenceExample(alignment_id="msa-1:water:cog-1", column_index=0)
    sampled = CorrespondenceSummary(
        left_segment="t",
        right_segment="k",
        count=9,
        anchor_count=0,
        example_columns=(example,),
    )
    assert sampled.count == 9
    assert len(sampled.example_columns) == 1

    with pytest.raises(ValidationError, match="cannot exceed the occurrence count"):
        CorrespondenceSummary(
            left_segment="t",
            right_segment="k",
            count=1,
            anchor_count=0,
            example_columns=(example, example),
        )
    with pytest.raises(ValidationError, match="cannot exceed the total count"):
        CorrespondenceSummary(
            left_segment="t",
            right_segment="k",
            count=1,
            anchor_count=2,
        )


def test_a_pairwise_reference_to_an_unknown_alignment_is_rejected() -> None:
    member = AlignmentMember(
        form_id="A:water",
        variety_id="A",
        concept_id="water",
        aligned_segments=("t",),
    )
    alignment = AlignmentResult(
        alignment_id="msa-1:water:cog-1",
        concept_id="water",
        members=(member, member.model_copy(update={"variety_id": "B", "form_id": "B:water"})),
    )
    with pytest.raises(ValidationError, match="unknown alignment IDs"):
        MultipleAlignmentMap(
            variety_ids=("A", "B"),
            alignments=(alignment,),
            pairwise_correspondences=(
                CorrespondenceMap(
                    left_variety_id="A",
                    right_variety_id="B",
                    alignment_ids=("msa-1:elsewhere:cog-9",),
                    correspondences=(),
                ),
            ),
        )


# --------------------------------------------------------------------------
# 2. the correspondence-set inventory
# --------------------------------------------------------------------------


def test_correspondence_sets_are_ordered_by_support_over_all_concepts() -> None:
    result = _call("summarize_correspondences", context=_context("A", "B", "C"))
    assert result.ok
    payload = result.result
    assert payload["node_ids"] == ["A", "B", "C"]
    assert payload["alignment_count"] == 4
    supports = [item["support"] for item in payload["sets"]]
    assert supports == sorted(supports, reverse=True)

    rows = {tuple(item["segments"]): item for item in payload["sets"]}
    # l ~ l ~ r recurs in three cognate sets; t ~ t ~ k occurs once and is
    # therefore residue under the default min_support.
    assert rows[("l", "l", "r")]["support"] == 3
    assert rows[("l", "l", "r")]["concept_count"] == 3
    assert set(rows[("l", "l", "r")]["example_concept_ids"]) == {
        "hand",
        "sky",
        "three",
    }
    assert ("t", "t", "k") not in rows
    assert payload["min_support"] == 2
    assert payload["suppressed_below_min_support"] > 0
    assert (
        payload["total_set_count"]
        == payload["matched_set_count"] + payload["suppressed_below_min_support"]
    )


def test_min_support_one_returns_the_residue_it_otherwise_counts() -> None:
    context = _context("A", "B", "C")
    default = _call("summarize_correspondences", context=context).result
    everything = _call(
        "summarize_correspondences", context=context, min_support=1, limit=200
    ).result
    assert everything["matched_set_count"] == everything["total_set_count"]
    assert everything["suppressed_below_min_support"] == 0
    assert (
        everything["matched_set_count"]
        == default["matched_set_count"] + default["suppressed_below_min_support"]
    )
    singletons = {
        tuple(item["segments"])
        for item in everything["sets"]
        if item["support"] == 1
    }
    assert ("t", "t", "k") in singletons


def test_the_segment_filter_answers_which_sets_show_one_segment_in_one_node() -> None:
    context = _context("A", "B", "C")
    anywhere = _call(
        "summarize_correspondences", context=context, segment="ʔ", min_support=1
    ).result
    assert anywhere["matched_set_count"] == 1
    assert tuple(anywhere["sets"][0]["segments"]) == ("ʔ", "ʔ", None)

    in_c = _call(
        "summarize_correspondences",
        context=context,
        segment="ʔ",
        segment_node_id="C",
        min_support=1,
    ).result
    assert in_c["matched_set_count"] == 0
    # The unfiltered total is still reported, so an empty page is legible.
    assert in_c["total_set_count"] == anywhere["total_set_count"]


def test_a_gap_is_askable_with_the_same_marker_the_dsl_uses() -> None:
    context = _context("A", "B", "C")
    for marker in ("Ø", "∅"):
        gaps = _call(
            "summarize_correspondences",
            context=context,
            segment=marker,
            segment_node_id="C",
            min_support=1,
        ).result
        assert gaps["matched_set_count"] >= 1
        assert all(item["segments"][2] is None for item in gaps["sets"])


def test_the_inventory_is_paginated_rather_than_batched() -> None:
    context = _context("A", "B", "C")
    whole = _call(
        "summarize_correspondences", context=context, min_support=1, limit=200
    ).result
    first = _call(
        "summarize_correspondences", context=context, min_support=1, limit=2
    ).result
    assert len(first["sets"]) == 2
    assert first["next_offset"] == 2
    assert first["matched_set_count"] == whole["matched_set_count"]
    rest = _call(
        "summarize_correspondences",
        context=context,
        min_support=1,
        limit=200,
        offset=first["next_offset"],
    ).result
    assert rest["next_offset"] is None
    assert first["sets"] + rest["sets"] == whole["sets"]


def test_an_unknown_node_is_refused_structurally() -> None:
    context = _context("A", "B", "C")
    unknown = _call(
        "summarize_correspondences", context=context, node_ids=["A", "nowhere"]
    )
    assert not unknown.ok
    assert unknown.error.code == "unknown-node"

    bad_filter = _call(
        "summarize_correspondences",
        context=context,
        segment="ʔ",
        segment_node_id="nowhere",
    )
    assert not bad_filter.ok
    assert bad_filter.error.code == "unknown-node"


def test_selected_nodes_fix_the_column_order() -> None:
    context = _context("A", "B", "C")
    reversed_selection = _call(
        "summarize_correspondences",
        context=context,
        node_ids=["C", "A"],
        min_support=1,
        limit=200,
    ).result
    assert reversed_selection["node_ids"] == ["C", "A"]
    rows = {tuple(item["segments"]) for item in reversed_selection["sets"]}
    assert ("r", "l") in rows
    assert ("l", "r") not in rows


def test_the_aggregation_ignores_anchors() -> None:
    """An anchor is supplementary evidence and cannot create support."""
    lexicons = tuple(_lexicon(variety_id) for variety_id in ("A", "C"))
    anchor = LexicalForm(
        form_id="anchor:hand",
        variety_id="PROTO",
        concept_id="hand",
        segments=("l", "i", "m", "a"),
        cognate_set_id="cog-hand",
    )
    aligner = LingPyAligner()
    without = build_correspondence_sets(
        aligner.align_multiple(lexicons, correspondence_detail=CorrespondenceDetail.SUMMARY)
    )
    with_anchor = build_correspondence_sets(
        aligner.align_multiple(
            lexicons, (anchor,), correspondence_detail=CorrespondenceDetail.SUMMARY
        )
    )
    assert with_anchor.sets == without.sets


# --------------------------------------------------------------------------
# 3. correspondence_maps on a reconstruction step
# --------------------------------------------------------------------------


def _evidence_context(*variety_ids: str) -> NodeReconstructionContext:
    return NodeReconstructionContext(
        parent_node_id="PROTO",
        active_child_ids=variety_ids,
        available_nodes=tuple(
            NodeEvidence(
                node_id=variety_id,
                kind=EvidenceKind.OBSERVED,
                relation=EvidenceRelation.ACTIVE_CHILD,
                lexicon=_lexicon(variety_id),
            )
            for variety_id in variety_ids
        ),
    )


def test_a_reconstruction_step_records_what_its_children_corresponded_in() -> None:
    children = tuple(
        make_leaf_beam(_lexicon(variety_id), beam_width=2) for variety_id in ("A", "C")
    )
    step = RuleBasedReconstructor(beam_width=2).reconstruct(
        "PROTO",
        children,
        evidence_context=_evidence_context("A", "C"),
    )
    assert len(step.correspondence_maps) == 1
    recorded = step.correspondence_maps[0]
    assert (recorded.left_variety_id, recorded.right_variety_id) == ("A", "C")
    counts = {
        (summary.left_segment, summary.right_segment): summary.count
        for summary in recorded.correspondences
    }
    assert counts[("l", "r")] == 3
    assert counts[("ʔ", None)] == 1
    # The compact rendering: counts and references, not the aligner's trace.
    assert all(not summary.example_observations for summary in recorded.correspondences)
    assert recorded.alignment_ids


def test_recorded_correspondences_change_no_score() -> None:
    children = tuple(
        make_leaf_beam(_lexicon(variety_id), beam_width=2) for variety_id in ("A", "C")
    )
    reconstructor = RuleBasedReconstructor(beam_width=2)
    without = reconstructor.reconstruct("PROTO", children)
    with_context = reconstructor.reconstruct(
        "PROTO", children, evidence_context=_evidence_context("A", "C")
    )
    # No evidence context is the only state in which nothing is recorded, and it
    # is the one every deterministic caller and analysis script uses.
    assert without.correspondence_maps == ()
    assert with_context.correspondence_maps
    assert without.output_beam == with_context.output_beam
    assert without.diagnostics == with_context.diagnostics


# --------------------------------------------------------------------------
# 4. dropping superseded tool results from the live prompt
# --------------------------------------------------------------------------


def test_supersession_needs_coverage_rather_than_mere_overlap() -> None:
    narrow = {"node_ids": ["A", "B"], "concept_ids": ["three"]}
    wider = {"node_ids": ["A", "B"], "concept_ids": ["three", "hand"]}
    disjoint = {"node_ids": ["A", "B"], "concept_ids": ["sky"]}

    assert _supersedes(narrow, narrow)
    assert _supersedes(wider, narrow)
    assert not _supersedes(narrow, wider)
    # Same nodes, different concepts: the earlier result still holds evidence
    # the later call never returned.
    assert not _supersedes(disjoint, narrow)
    # An unrestricted selection covers a narrow one.
    assert _supersedes({"node_ids": ["A", "B"]}, narrow)
    # Anything that is not a selection must match exactly.
    assert not _supersedes({**narrow, "detail": "summary"}, {**narrow, "detail": "full"})
    assert not _supersedes({**narrow, "offset": 30}, {**narrow, "offset": 0})


class _RepeatingProvider:
    """Asks for the same evidence twice, then a disjoint batch, then commits."""

    model = "scripted/repeating"

    def __init__(self) -> None:
        self.turn = 0
        self.prompts: list[tuple[LLMMessage, ...]] = []

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[LLMToolDefinition],
        *,
        tool_choice: str = "auto",
        max_tokens_override: int | None = None,
    ) -> LLMMessage:
        assert tools
        self.prompts.append(tuple(messages))
        self.turn += 1
        script = {
            1: LLMToolCall(
                call_id="align-1",
                name="get_alignments",
                arguments={"node_ids": ["A", "C"], "concept_ids": ["three"]},
            ),
            2: LLMToolCall(
                call_id="align-2",
                name="get_alignments",
                arguments={"node_ids": ["A", "C"], "concept_ids": ["three"]},
            ),
            3: LLMToolCall(
                call_id="align-3",
                name="get_alignments",
                arguments={"node_ids": ["A", "C"], "concept_ids": ["sky"]},
            ),
            4: LLMToolCall(
                call_id="validate",
                name="test_sound_law",
                arguments={"dsl": "r > l", "source_child_ids": ["C"]},
            ),
            5: LLMToolCall(
                call_id="validate-again",
                name="test_sound_law",
                arguments={"dsl": "r > l", "source_child_ids": ["C"]},
            ),
        }
        if self.turn in script:
            return LLMMessage(
                role=MessageRole.ASSISTANT, tool_calls=(script[self.turn],)
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
                                "dsl": "r > l",
                                "source_child_ids": ["C"],
                                "confidence": 0.8,
                                # Named explicitly: this session validated the
                                # same rule twice on purpose, so an omitted ID
                                # would be ambiguous rather than resolvable.
                                "validation_call_id": "validate",
                            }
                        ],
                        "anomalies": [],
                        "summary": "C shows r for parent l.",
                    },
                ),
            ),
        )


class _CollectingSink:
    def __init__(self) -> None:
        self.events: list = []

    def emit(self, event) -> None:
        self.events.append(event)


def _tool_message(messages: Sequence[LLMMessage], call_id: str) -> LLMMessage:
    return next(
        message
        for message in messages
        if message.role is MessageRole.TOOL and message.tool_call_id == call_id
    )


def test_a_superseded_evidence_result_leaves_the_prompt_but_not_the_record() -> None:
    provider = _RepeatingProvider()
    sink = _CollectingSink()
    result = AgentOrchestrator(provider, event_sink=sink).run(_context("A", "C"))

    # The audit record keeps every result in full.
    recorded = _tool_message(result.trajectory.messages, "align-1")
    assert '"ok":true' in recorded.content.replace(" ", "")
    assert "alignment_map" in recorded.content
    assert "compacted" not in recorded.content

    # The prompt the model last saw carries a placeholder in its place.
    final_prompt = provider.prompts[-1]
    placeholder = json.loads(_tool_message(final_prompt, "align-1").content)
    assert placeholder == {
        "compacted": True,
        "tool": "get_alignments",
        "call_id": "align-1",
        "superseded_by": "align-2",
        "note": placeholder["note"],
    }
    assert "get_alignments" in placeholder["note"]

    # The newest result for the tool is never compacted, and a disjoint
    # selection is not superseded by it either.
    for live in ("align-2", "align-3"):
        assert "alignment_map" in _tool_message(final_prompt, live).content

    assert result.trajectory.metrics.compacted_tool_results == 1
    compactions = [
        event for event in sink.events if event.kind is AgentEventKind.CONTEXT_COMPACTION
    ]
    assert len(compactions) == 1
    assert compactions[0].details["call_id"] == "align-1"
    assert compactions[0].details["superseded_by"] == "align-2"
    assert compactions[0].details["tool_name"] == "get_alignments"


def test_validations_and_commits_are_never_compacted() -> None:
    provider = _RepeatingProvider()
    result = AgentOrchestrator(provider).run(_context("A", "C"))
    final_prompt = provider.prompts[-1]
    # Two identical test_sound_law calls: the first result still has to be
    # readable, because it holds the validation ID a commit is checked against.
    for call_id in ("validate", "validate-again"):
        content = _tool_message(final_prompt, call_id).content
        assert "validation_call_id" in content
        assert "compacted" not in content
    assert "test_sound_law" not in COMPACTABLE_TOOL_NAMES
    assert "commit_reconstruction" not in COMPACTABLE_TOOL_NAMES
    assert result.trajectory.metrics.compacted_tool_results == 1


def test_compaction_preserves_call_and_result_adjacency() -> None:
    provider = _RepeatingProvider()
    AgentOrchestrator(provider).run(_context("A", "C"))
    prompt = provider.prompts[-1]
    for index, message in enumerate(prompt):
        if message.role is not MessageRole.ASSISTANT or not message.tool_calls:
            continue
        answers = prompt[index + 1 : index + 1 + len(message.tool_calls)]
        assert [reply.tool_call_id for reply in answers] == [
            call.call_id for call in message.tool_calls
        ]
        assert all(reply.role is MessageRole.TOOL for reply in answers)


def test_compaction_can_be_switched_off() -> None:
    provider = _RepeatingProvider()
    result = AgentOrchestrator(
        provider, compact_superseded_tool_results=False
    ).run(_context("A", "C"))
    assert result.trajectory.metrics.compacted_tool_results == 0
    assert "alignment_map" in _tool_message(provider.prompts[-1], "align-1").content


def test_metrics_written_before_compaction_existed_still_load() -> None:
    """Trajectories are append-only readable: a new counter needs a default."""
    record = json.loads(
        AgentOrchestrator(_RepeatingProvider())
        .run(_context("A", "C"))
        .trajectory.model_dump_json(exclude_computed_fields=True)
    )
    del record["metrics"]["compacted_tool_results"]
    restored = AgentTrajectory.model_validate_json(json.dumps(record))
    assert restored.metrics.compacted_tool_results == 0


def test_the_inventory_counts_as_evidence_inspection() -> None:
    """A session that surveyed correspondences has inspected evidence."""

    class _InventoryThenCommit:
        model = "scripted/inventory"

        def __init__(self) -> None:
            self.turn = 0

        def complete(self, messages, tools, *, tool_choice="auto", max_tokens_override=None):
            self.turn += 1
            if self.turn == 1:
                return LLMMessage(
                    role=MessageRole.ASSISTANT,
                    tool_calls=(
                        LLMToolCall(
                            call_id="survey",
                            name="summarize_correspondences",
                            arguments={},
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
                            "rules": [],
                            "anomalies": [],
                            "summary": "Identity: A and B agree throughout.",
                        },
                    ),
                ),
            )

    result = AgentOrchestrator(_InventoryThenCommit()).run(_context("A", "B"))
    assert result.trajectory.metrics.inspection_tool_calls == 1
    assert not result.trajectory.metrics.committed_without_inspection
