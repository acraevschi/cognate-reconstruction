"""Which branch innovated, and what the harness makes a session say about it.

Rules are child-to-parent, so "make the children agree" is satisfiable by
rewriting either child toward the other, and nothing in the tool surface ever
asked which one changed. Live runs answered it backwards and were accepted:
`ʔ > Ø / #_` scoped to the Tongic branch that *preserves* the glottal stop,
`f > h` and `t > k` scoped to North Marquesan when Hawaiian innovated both.

Four mechanisms are pinned here, none of which contains a linguistic fact:

- `polarize` retrieves the evidence outside the active children that bears on
  the direction, and reports it as a distribution with no verdict;
- a rule that deletes or merges is detected mechanically and has to carry a
  `directionality_rationale` — rejected on absence, never on content;
- what a commit discards is counted against the available evidence;
- the node's concepts are split deterministically, so a rule fitted to one word
  is measured somewhere it was not fitted.
"""

from __future__ import annotations

from collections.abc import Sequence

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.holdout import split_concepts
from cognate_reconstruction.agent.orchestrator import AgentOrchestrator
from cognate_reconstruction.agent.schemas import (
    LLMMessage,
    LLMToolCall,
    LLMToolDefinition,
    MessageRole,
)
from cognate_reconstruction.agent.tools import default_tool_registry
from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.rules import parse_rule, rule_contrast_reduction
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm
from cognate_reconstruction.schemas.rules import ReconstructionRule
from cognate_reconstruction.schemas.traversal import (
    EvidenceKind,
    EvidenceRelation,
    NodeEvidence,
)
from cognate_reconstruction.traversal.beam import beam_to_lexicon, make_leaf_beam
from cognate_reconstruction.traversal.reconstructor import RuleBasedReconstructor

# The real Tongic case, reduced. Tongan keeps `*ʔ`; Niuean lost it. Two
# out-groups also keep it and two do not, so a majority over daughters points
# the wrong way and only presence outside the node points the right way.
_FORMS: dict[str, dict[str, tuple[str, ...]]] = {
    "Tongan": {
        "rain": ("ʔ", "u", "h", "a"),
        "tongue": ("ʔ", "e", "l", "e", "l", "o"),
        "fish": ("i", "k", "a"),
        "three": ("t", "o", "l", "u"),
    },
    "Niuean": {
        "rain": ("u", "h", "a"),
        "tongue": ("a", "l", "e", "l", "o"),
        "fish": ("i", "k", "a"),
        "three": ("t", "o", "l", "u"),
    },
    "EastUvean": {
        "rain": ("ʔ", "u", "h", "a"),
        "tongue": ("ʔ", "a", "l", "e", "l", "o"),
        "fish": ("i", "k", "a"),
        "three": ("t", "o", "l", "u"),
    },
    "Samoan": {
        "rain": ("u", "a"),
        "tongue": ("a", "l", "e", "l", "o"),
        "fish": ("i", "ʔ", "a"),
        "three": ("t", "o", "l", "u"),
    },
    "Hawaiian": {
        "rain": ("u", "a"),
        "tongue": ("a", "l", "e", "l", "o"),
        "fish": ("i", "ʔ", "a"),
        "three": ("k", "o", "l", "u"),
    },
}

_ACTIVE = ("Tongan", "Niuean")


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


def _context(
    *,
    reconstructed: tuple[str, ...] = (),
    outside: bool = True,
    relation: EvidenceRelation = EvidenceRelation.OUTGROUP,
) -> AgentContext:
    """The Tongic node, with the rest of the family available as evidence.

    `reconstructed` names out-group nodes to present as already reconstructed
    rather than observed, which is how the observed/reconstructed distinction is
    exercised without inventing a second fixture.
    """
    evidence: list[NodeEvidence] = []
    for variety_id in _FORMS:
        if variety_id not in _ACTIVE and not outside:
            continue
        evidence.append(
            NodeEvidence(
                node_id=variety_id,
                kind=(
                    EvidenceKind.RECONSTRUCTED
                    if variety_id in reconstructed
                    else EvidenceKind.OBSERVED
                ),
                relation=(
                    EvidenceRelation.ACTIVE_CHILD
                    if variety_id in _ACTIVE
                    else relation
                ),
                lexicon=_lexicon(variety_id),
                descendant_leaf_ids=(variety_id,),
            )
        )
    return AgentContext(
        node_id="tongic",
        child_lexicons=tuple(_lexicon(variety_id) for variety_id in _ACTIVE),
        aligner=LingPyAligner(),
        evidence=tuple(evidence),
    )


def _call(name: str, context: AgentContext, call_id: str = "call", **arguments):
    return default_tool_registry().execute(
        LLMToolCall(call_id=call_id, name=name, arguments=arguments), context
    )


def _registry_call(registry, name, context, call_id, **arguments):
    return registry.execute(
        LLMToolCall(call_id=call_id, name=name, arguments=arguments), context
    )


# ---------------------------------------------------------------------------
# polarize
# ---------------------------------------------------------------------------


def test_polarize_reports_what_the_rest_of_the_tree_shows() -> None:
    result = _call(
        "polarize",
        _context(),
        child_ids=list(_ACTIVE),
        correspondence=["ʔ", "Ø"],
        position="initial",
    )
    assert result.ok, result.error
    payload = result.result
    assert payload["columns_matched"] == 2
    assert set(payload["matched_concept_ids"]) == {"rain", "tongue"}
    by_node = {item["node_id"]: item for item in payload["nodes"]}
    # The active children are never reported back to the caller: the question is
    # what lies outside them.
    assert set(by_node) == {"EastUvean", "Samoan", "Hawaiian"}
    assert [item["segment"] for item in by_node["EastUvean"]["observations"]] == ["ʔ"]
    # A gap is a real observation and is reported as null rather than dropped.
    assert [item["segment"] for item in by_node["Samoan"]["observations"]] == [None]
    assert by_node["EastUvean"]["relation"] == "outgroup"
    # Presence only: `ʔ` names the node that shows it, and the two nodes that
    # lack it are not listed as evidence against it.
    assert payload["candidates"] == [
        {
            "segment": "ʔ",
            "observed_node_ids": ["EastUvean"],
            "reconstructed_node_ids": [],
        }
    ]


def test_polarize_marks_a_reconstructed_node_as_not_attestation() -> None:
    """A prior hypothesis is reported, and reported as not being evidence."""
    result = _call(
        "polarize",
        _context(reconstructed=("EastUvean",)),
        child_ids=list(_ACTIVE),
        correspondence=["ʔ", "Ø"],
        position="initial",
    )
    assert result.ok, result.error
    by_node = {item["node_id"]: item for item in result.result["nodes"]}
    assert by_node["EastUvean"]["kind"] == "reconstructed"
    assert by_node["EastUvean"]["is_attestation"] is False
    assert by_node["Samoan"]["is_attestation"] is True
    # And the summary keeps the two apart rather than totalling them.
    candidate = result.result["candidates"][0]
    assert candidate["observed_node_ids"] == []
    assert candidate["reconstructed_node_ids"] == ["EastUvean"]


def test_polarize_says_so_when_the_node_has_no_outgroup() -> None:
    """The root is where the reported reconstruction is made and where this fails."""
    result = _call(
        "polarize",
        _context(outside=False),
        child_ids=list(_ACTIVE),
        correspondence=["ʔ", "Ø"],
    )
    assert result.ok, result.error
    assert result.result["nodes"] == []
    assert result.result["columns_matched"] == 0
    assert "no node outside the active children" in result.result["note"].lower()


def test_polarize_does_not_let_a_descendant_read_as_out_group_support() -> None:
    """The root case, which is not an empty node list.

    At the root every available node is a descendant: it lies inside the
    subtree and shows what these children became, which is the proposition
    under test rather than evidence about it. A live run at
    `proto_polynesian` got 14 descendants back under a note reading "14 node(s)
    outside the active children were inspected" — true, and indistinguishable
    from out-group support, which is the exact cladistic error this tool exists
    to prevent.
    """
    result = _call(
        "polarize",
        _context(relation=EvidenceRelation.DESCENDANT),
        child_ids=list(_ACTIVE),
        correspondence=["ʔ", "Ø"],
        position="initial",
    )
    assert result.ok, result.error
    assert {item["relation"] for item in result.result["nodes"]} == {"descendant"}
    note = result.result["note"]
    assert "every one of them is a descendant" in note
    assert "no out-group" in note
    # The distributional detail is still returned; what changed is that the
    # summary cannot be read as support.
    assert result.result["candidates"][0]["segment"] == "ʔ"


def test_polarize_counts_out_groups_and_descendants_apart() -> None:
    note = _call(
        "polarize",
        _context(),
        child_ids=list(_ACTIVE),
        correspondence=["ʔ", "Ø"],
    ).result["note"]
    assert "3 out-group node(s) were inspected" in note
    assert "descendant" not in note


def test_polarize_rejects_a_correspondence_that_does_not_match_its_children() -> None:
    result = _call(
        "polarize",
        _context(),
        child_ids=list(_ACTIVE),
        correspondence=["ʔ"],
    )
    assert not result.ok
    assert "one segment per child" in result.error.message


def test_polarize_refuses_a_node_inside_the_active_children() -> None:
    result = _call(
        "polarize",
        _context(),
        child_ids=list(_ACTIVE),
        correspondence=["ʔ", "Ø"],
        node_ids=["Tongan"],
    )
    assert not result.ok
    assert result.error.code == "unknown-node"


def test_polarize_position_restricts_to_the_word_edge() -> None:
    """`fish` has a medial `ʔ` in two out-groups; an initial query must miss it."""
    anywhere = _call(
        "polarize",
        _context(),
        child_ids=["Tongan"],
        correspondence=["ʔ"],
    )
    initial = _call(
        "polarize",
        _context(),
        child_ids=["Tongan"],
        correspondence=["ʔ"],
        position="initial",
    )
    assert anywhere.ok and initial.ok
    assert anywhere.result["columns_matched"] == 2
    assert initial.result["columns_matched"] == 2
    by_node = {item["node_id"]: item for item in initial.result["nodes"]}
    assert "fish" not in set(initial.result["matched_concept_ids"])
    assert by_node["Samoan"]["columns_covered"] == 2


# ---------------------------------------------------------------------------
# detecting a lost contrast
# ---------------------------------------------------------------------------


def _forms(variety_id: str, **concepts: str) -> tuple[LexicalForm, ...]:
    return tuple(
        LexicalForm(
            form_id=f"{variety_id}:{concept_id}",
            variety_id=variety_id,
            concept_id=concept_id,
            segments=tuple(segments),
        )
        for concept_id, segments in concepts.items()
    )


def test_a_deleting_rule_is_a_contrast_reduction() -> None:
    reduction = rule_contrast_reduction(
        parse_rule("ʔ > Ø / #_"), _forms("Tongan", rain="ʔuha")
    )
    assert reduction is not None
    assert reduction.deletes and not reduction.merges
    assert reduction.discarded_segments == ("ʔ",)


def test_a_non_injective_rule_is_a_contrast_reduction() -> None:
    """`t > k` in a child that already has `k`: two inputs, one output."""
    reduction = rule_contrast_reduction(
        parse_rule("t > k"), _forms("NM", one="tolu", two="kolu")
    )
    assert reduction is not None
    assert reduction.merges and not reduction.deletes
    assert reduction.discarded_segments == ("t",)
    assert reduction.merged_into == ("k",)


def test_a_shift_into_a_segment_the_child_lacks_is_not_a_merger() -> None:
    """The mapping stays injective, so nothing was given up and nothing is asked."""
    assert (
        rule_contrast_reduction(parse_rule("t > k"), _forms("NM", one="tolu"))
        is None
    )


def test_a_rule_that_never_fires_reduces_nothing() -> None:
    assert (
        rule_contrast_reduction(parse_rule("q > Ø"), _forms("NM", one="tolu"))
        is None
    )


def test_a_conditioned_split_is_not_a_merger() -> None:
    """`t` surviving elsewhere is one input with two images, not two with one."""
    assert (
        rule_contrast_reduction(
            parse_rule("t > k / _a"), _forms("NM", one="ta", two="tolu")
        )
        is None
    )


def test_an_earlier_rule_can_create_the_segment_a_later_one_merges_into() -> None:
    """The cascade is walked in order, so a rule sees the forms it will receive."""
    registry = default_tool_registry()
    context = _context()
    # `h > k` gives Tongan a `k` in `rain`; only then does `t > k` merge.
    result = _registry_call(
        registry,
        "test_rule_cascade",
        context,
        "cascade",
        rules=[
            {"dsl": "h > k", "source_child_ids": ["Tongan"]},
            {"dsl": "t > k", "source_child_ids": ["Tongan"]},
        ],
    )
    assert result.ok, result.error
    flagged = {item["dsl"] for item in result.result["contrast_reductions"]}
    assert flagged == {"h > k", "t > k"}


# ---------------------------------------------------------------------------
# the requirement at commit time
# ---------------------------------------------------------------------------


def _commit(registry, context, rules, **overrides):
    return _registry_call(
        registry,
        "commit_reconstruction",
        context,
        "commit",
        node_id="tongic",
        rules=rules,
        anomalies=[],
        summary="Parent initial glottal stop.",
        **overrides,
    )


def test_the_tongic_case_is_flagged_counted_and_rejected_until_answered() -> None:
    """Tongan `ʔuha` against Niuean `uha`, exactly as a live run committed it.

    Tongan is the branch that *preserves* `*ʔ`, so deleting it there is the
    wrong direction. The harness cannot know that — it is a linguistic
    judgement — so it does the three things it can: flag the rule, count who
    else still shows the segment, and refuse the commit until the claim about
    which branch innovated is written down.
    """
    registry = default_tool_registry()
    context = _context()
    validation = _registry_call(
        registry,
        "test_sound_law",
        context,
        "validate",
        dsl="ʔ > Ø / #_",
        source_child_ids=["Tongan"],
    )
    assert validation.ok, validation.error
    reduction = validation.result["contrast_reduction"]
    assert reduction is not None
    assert reduction["deletes"] is True
    assert reduction["discarded_segments"] == ["ʔ"]
    # Four of the five available nodes still show `ʔ` somewhere — Tongan and
    # East Uvean initially, Samoan and Hawaiian medially in `fish`. Niuean is
    # the one that lost it everywhere, which is the shape of the real case.
    assert reduction["attesting_node_count"] == 4
    assert reduction["observed_attesting_node_count"] == 4
    assert reduction["available_node_count"] == 5
    assert set(reduction["attesting_node_ids"]) == {
        "Tongan",
        "EastUvean",
        "Samoan",
        "Hawaiian",
    }
    assert "attested in 4 of 5 available nodes" in reduction["note"]

    rule = {
        "dsl": "ʔ > Ø / #_",
        "source_child_ids": ["Tongan"],
        "confidence": 0.9,
    }
    rejected = _commit(registry, context, [rule])
    assert not rejected.ok
    assert rejected.error.code == "missing-directionality-rationale"
    # The rejection names the exact rule, as the multi-rule rationale one does.
    assert reduction["rule_id"] in (rejected.error.remediation or "")
    assert context.commit is None

    accepted = _commit(
        registry,
        context,
        [
            {
                **rule,
                "directionality_rationale": (
                    "Claiming Niuean innovated the loss; Tongan retains *ʔ."
                ),
            }
        ],
    )
    assert accepted.ok, accepted.error
    assert context.commit is not None
    committed = context.commit.request.rules[0]
    assert committed.directionality_rationale is not None
    # And the commit result still carries what was given up.
    assert accepted.result["contrast_reductions"][0]["discarded_segments"] == ["ʔ"]


def test_the_rejection_names_only_the_rules_that_lost_a_contrast() -> None:
    registry = default_tool_registry()
    context = _context()
    rules = [
        # Merges Tongan `t` into a `k` it already has: flagged.
        {"dsl": "t > k", "source_child_ids": ["Tongan"]},
        # Shifts Niuean `h` to a `s` no child has: injective, not flagged.
        {"dsl": "h > s", "source_child_ids": ["Niuean"]},
    ]
    cascade = _registry_call(
        registry, "test_rule_cascade", context, "cascade", rules=rules
    )
    assert cascade.ok, cascade.error
    reductions = cascade.result["contrast_reductions"]
    assert [item["dsl"] for item in reductions] == ["t > k"]

    result = _commit(
        registry,
        context,
        [
            {**rule, "confidence": 0.8, "rationale": f"Because {rule['dsl']}."}
            for rule in rules
        ],
    )
    assert not result.ok
    assert result.error.code == "missing-directionality-rationale"
    remediation = result.error.remediation or ""
    assert reductions[0]["rule_id"] in remediation
    assert "h > s" not in remediation


def test_the_harness_never_judges_what_the_rationale_says() -> None:
    """Rejection is on absence. Content is a reviewer's problem, not a check."""
    registry = default_tool_registry()
    context = _context()
    _registry_call(
        registry,
        "test_sound_law",
        context,
        "validate",
        dsl="ʔ > Ø / #_",
        source_child_ids=["Tongan"],
    )
    result = _commit(
        registry,
        context,
        [
            {
                "dsl": "ʔ > Ø / #_",
                "source_child_ids": ["Tongan"],
                "confidence": 0.9,
                "directionality_rationale": "x",
            }
        ],
    )
    assert result.ok, result.error


def test_an_identity_commit_needs_no_directionality_rationale() -> None:
    registry = default_tool_registry()
    context = _context()
    result = _commit(registry, context, [])
    assert result.ok, result.error


# ---------------------------------------------------------------------------
# the held-out split
# ---------------------------------------------------------------------------


def test_the_split_is_deterministic_and_independent_of_input_order() -> None:
    concepts = ["rain", "tongue", "fish", "three", "hand", "sky", "star"]
    first = split_concepts("tongic", concepts)
    second = split_concepts("tongic", list(reversed(concepts)))
    assert first == second
    assert set(first.development_concept_ids) | set(first.held_out_concept_ids) == set(
        concepts
    )
    assert not set(first.development_concept_ids) & set(first.held_out_concept_ids)
    assert len(first.held_out_concept_ids) == 2


def test_sibling_nodes_hold_out_different_concepts() -> None:
    """Seeded from the node ID, so a family is not scored on one fixed subset."""
    concepts = [f"c{index}" for index in range(40)]
    assert split_concepts("tongic", concepts).held_out_concept_ids != (
        split_concepts("futunic", concepts).held_out_concept_ids
    )


def test_a_node_with_one_concept_holds_nothing_out() -> None:
    split = split_concepts("tongic", ["rain"])
    assert split.held_out_concept_ids == ()
    assert split.development_concept_ids == ("rain",)


def test_the_split_survives_a_resume_unchanged() -> None:
    """A resumed node rebuilds its children from checkpointed beams.

    The split is a function of the node ID and the concepts those children
    carry, and of nothing else — not of call order, not of which lexicon object
    the context was handed — so the node holds out the same concepts before and
    after.
    """
    live = _context()
    resumed = AgentContext(
        node_id="tongic",
        child_lexicons=tuple(
            beam_to_lexicon(make_leaf_beam(_lexicon(variety_id), beam_width=5))
            for variety_id in _ACTIVE
        ),
        aligner=LingPyAligner(),
    )
    assert live.concept_split.held_out_concept_ids == (
        resumed.concept_split.held_out_concept_ids
    )
    assert live.concept_split.held_out_concept_ids


def test_a_cascade_reports_the_held_out_set_it_was_not_fitted_to() -> None:
    context = _context()
    held_out = set(context.concept_split.held_out_concept_ids)
    assert held_out
    development = sorted(set(context.concept_split.development_concept_ids))
    result = _call(
        "test_rule_cascade",
        context,
        rules=[{"dsl": "ʔ > Ø / #_", "source_child_ids": ["Tongan"]}],
        concept_ids=development,
    )
    assert result.ok, result.error
    summary = result.result["held_out"]
    # Reported over the node's held-out concepts, whatever the call selected.
    assert summary["concept_count"] == len(held_out)
    assert set(summary["held_out_concept_ids"]) == held_out
    assert summary["convergence"] is not None


def test_a_commit_reports_held_out_convergence() -> None:
    registry = default_tool_registry()
    context = _context()
    _registry_call(
        registry,
        "test_sound_law",
        context,
        "validate",
        dsl="ʔ > Ø / #_",
        source_child_ids=["Tongan"],
    )
    result = _commit(
        registry,
        context,
        [
            {
                "dsl": "ʔ > Ø / #_",
                "source_child_ids": ["Tongan"],
                "confidence": 0.9,
                "directionality_rationale": "Niuean innovated the loss.",
            }
        ],
    )
    assert result.ok, result.error
    summary = result.result["held_out"]
    assert summary["concept_count"] == len(context.concept_split.held_out_concept_ids)
    assert 0.0 <= summary["convergence"]["child_convergence_rate"] <= 1.0


def test_a_rule_fitted_to_one_word_looks_worse_on_the_held_out_set() -> None:
    """The point of the split, in one comparison.

    `ʔ > Ø / #_` reconciles the children on the concepts where Tongan has an
    initial `ʔ`. On the held-out concepts, which have none, it fires on nothing.
    """
    context = _context()
    result = _call(
        "test_sound_law",
        context,
        dsl="ʔ > Ø / #_",
        source_child_ids=["Tongan"],
        concept_ids=["rain"],
    )
    assert result.ok, result.error
    assert result.result["report"]["words_applied"] == 1
    assert result.result["held_out"]["applications"] == 0


# ---------------------------------------------------------------------------
# the diagnostic that keeps rule_coverage honest
# ---------------------------------------------------------------------------


def test_the_step_counts_rules_that_bought_coverage_by_deleting() -> None:
    beams = [
        make_leaf_beam(_lexicon(variety_id), beam_width=5) for variety_id in _ACTIVE
    ]
    step = RuleBasedReconstructor(beam_width=5).reconstruct(
        "tongic",
        beams,
        rules=[
            ReconstructionRule(
                rule=parse_rule("ʔ > Ø / #_", rule_id="drop-glottal"),
                source_child_ids=("Tongan",),
                confidence=0.9,
            )
        ],
    )
    assert step.diagnostics.rule_coverage == 1.0
    assert step.diagnostics.contrast_reducing_rule_count == 1


def test_an_identity_step_reduces_no_contrast() -> None:
    beams = [
        make_leaf_beam(_lexicon(variety_id), beam_width=5) for variety_id in _ACTIVE
    ]
    step = RuleBasedReconstructor(beam_width=5).reconstruct("tongic", beams)
    assert step.diagnostics.contrast_reducing_rule_count == 0


# ---------------------------------------------------------------------------
# what the session is told before it starts
# ---------------------------------------------------------------------------


class _IdentityProvider:
    """Commits identity immediately; the payload is what is under test."""

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[LLMToolDefinition],
        *,
        tool_choice: str = "auto",
        max_tokens_override: int | None = None,
    ) -> LLMMessage:
        return LLMMessage(
            role=MessageRole.ASSISTANT,
            tool_calls=(
                LLMToolCall(
                    call_id="commit",
                    name="commit_reconstruction",
                    arguments={
                        "node_id": "tongic",
                        "rules": [],
                        "anomalies": [],
                        "summary": "Identity.",
                    },
                ),
            ),
        )


def test_the_prompt_payload_states_the_requirement_and_the_split() -> None:
    """A requirement that lives only in code is discovered by being rejected."""
    context = _context()
    run_result = AgentOrchestrator(
        _IdentityProvider(), instructions="Commit."
    ).run(context)
    payload = run_result.trajectory.initial_payload
    assert payload.concept_holdout is not None
    assert payload.concept_holdout.held_out_concept_ids == (
        context.concept_split.held_out_concept_ids
    )
    requirements = " ".join(payload.commit_requirements)
    assert "directionality_rationale" in requirements
    assert "polarize" in requirements
    # And the requirement reaches the model as prompt text, not only as schema.
    rendered = payload.model_dump_json()
    assert "directionality_rationale" in rendered


class _DeletingProvider:
    """Validates the Tongic deletion, then commits it with its rationale."""

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
                        call_id="validate",
                        name="test_sound_law",
                        arguments={
                            "dsl": "ʔ > Ø / #_",
                            "source_child_ids": ["Tongan"],
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
                        "node_id": "tongic",
                        "rules": [
                            {
                                "dsl": "ʔ > Ø / #_",
                                "source_child_ids": ["Tongan"],
                                "confidence": 0.9,
                                "directionality_rationale": (
                                    "Niuean innovated the loss."
                                ),
                            }
                        ],
                        "anomalies": [],
                        "summary": "Parent had no initial glottal stop.",
                    },
                ),
            ),
        )


def test_the_trajectory_records_held_out_convergence() -> None:
    """Recomputed from the commit, so it survives a compacted tool result."""
    context = _context()
    run_result = AgentOrchestrator(
        _DeletingProvider(), instructions="Test, then commit."
    ).run(context)
    metrics = run_result.trajectory.metrics
    assert metrics.held_out_concept_count == len(
        context.concept_split.held_out_concept_ids
    )
    assert metrics.held_out_convergence_rate is not None
    assert 0.0 <= metrics.held_out_convergence_rate <= 1.0


def test_the_rejection_separates_the_finding_from_the_claim_it_asks_for() -> None:
    """A live run pasted the harness's own count back as its rationale.

    The harness cannot reject that — content is never judged — so the fix is in
    what the rejection asks for, not in what it checks. The counts are labelled
    as the finding, and the request names the claim separately.
    """
    registry = default_tool_registry()
    context = _context()
    _registry_call(
        registry,
        "test_sound_law",
        context,
        "validate",
        dsl="ʔ > Ø / #_",
        source_child_ids=["Tongan"],
    )
    result = _commit(
        registry,
        context,
        [{"dsl": "ʔ > Ø / #_", "source_child_ids": ["Tongan"], "confidence": 0.9}],
    )
    assert not result.ok
    remediation = result.error.remediation or ""
    assert "What the harness found:" in remediation
    assert "which of the active children" in remediation
    assert "Restating the counts above is not an answer" in remediation
    # And a rationale that does restate them is still accepted: the harness
    # records the claim, it does not grade it.
    accepted = _commit(
        registry,
        context,
        [
            {
                "dsl": "ʔ > Ø / #_",
                "source_child_ids": ["Tongan"],
                "confidence": 0.9,
                "directionality_rationale": "ʔ is attested in 4 of 5 nodes.",
            }
        ],
    )
    assert accepted.ok, accepted.error
