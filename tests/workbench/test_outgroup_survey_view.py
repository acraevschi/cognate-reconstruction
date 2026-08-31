"""Sibling evidence reaches the node without it having to ask for it.

`polarize` answers one question about one correspondence. Measured across the
banked sweeps by `tools/outgroup_coverage.py`, every non-root node called it and
every one got an out-group back — and it covered 11% of what Gemma committed and
24.8% of what Qwen committed, because a call covers one correspondence and a
node commits fifteen to thirty sets. The reaching was never the problem; the
ratio was.

So `summarize_correspondences` now carries the same reading for every set it
returns, computed once for the survey, and it is on by default because a flag
the model has to set is a flag §7.17 already measured does not get set.

These tests pin the three properties that make the technique sound rather than
merely cheaper — it agrees with `polarize`, it reports presence only, and it
never lets the root look as though it had evidence — and the two that keep it
affordable.
"""

from __future__ import annotations

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.schemas import LLMToolCall
from cognate_reconstruction.agent.tools import default_tool_registry
from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm
from cognate_reconstruction.schemas.traversal import (
    EvidenceKind,
    EvidenceRelation,
    NodeEvidence,
)

CONCEPTS = ("water", "fire", "stone", "tree")


def _lexicon(variety_id: str, initial: str) -> LanguageLexicon:
    return LanguageLexicon(
        variety_id=variety_id,
        name=variety_id,
        forms=tuple(
            LexicalForm(
                form_id=f"{variety_id}:{concept}",
                variety_id=variety_id,
                concept_id=concept,
                segments=(initial, vowel),
            )
            for concept, vowel in zip(CONCEPTS, ("a", "u", "i", "o"), strict=True)
        ),
    )


def _context(relation: EvidenceRelation = EvidenceRelation.OUTGROUP) -> AgentContext:
    """Two children that disagree on the initial, and two nodes outside them.

    A keeps `p`, B has `f`. The outside nodes also show `p`, which is what makes
    `p` the retention and `f` B's innovation — the judgement stays the model's,
    but the evidence for it is what this view has to deliver.
    """
    return AgentContext(
        node_id="PROTO",
        child_lexicons=(_lexicon("A", "p"), _lexicon("B", "f")),
        aligner=LingPyAligner(),
        evidence=(
            NodeEvidence(
                node_id="OUT1",
                lexicon=_lexicon("OUT1", "p"),
                kind=EvidenceKind.OBSERVED,
                relation=relation,
            ),
            NodeEvidence(
                node_id="OUT2",
                lexicon=_lexicon("OUT2", "p"),
                kind=EvidenceKind.OBSERVED,
                relation=relation,
            ),
        ),
    )


def _summarize(context, **arguments):
    result = default_tool_registry().execute(
        LLMToolCall(
            call_id="c", name="summarize_correspondences", arguments=arguments
        ),
        context,
    )
    assert result.ok, result.error
    return result.result


def test_the_outgroup_reading_arrives_without_being_asked_for() -> None:
    """On by default. A flag the model must set is a flag it does not set."""
    payload = _summarize(_context())
    profiles = payload["outgroup_reflexes"]
    assert profiles, "the survey returned no out-group reading at all"
    by_segment = {
        reflex["segment"]: set(reflex["node_ids"])
        for profile in profiles
        for reflex in profile["reflexes"]
    }
    # `p` is attested outside the group; that is the retention evidence.
    assert by_segment["p"] == {"OUT1", "OUT2"}
    # And `f`, B's innovation, is attested nowhere outside it.
    assert "f" not in by_segment


def test_only_sets_whose_children_disagree_are_profiled() -> None:
    """The cost control, and it is a property of the question.

    A set where every child shows the same segment has no competing value to
    choose between, so an out-group reading of it answers a question nobody
    asked. On the real Polynesian `tongic` node this is what takes the addition
    from 3.9x the result to 1.5x, and it drops nothing informative.
    """
    payload = _summarize(_context())
    profiled = {profile["set_id"] for profile in payload["outgroup_reflexes"]}
    for item in payload["sets"]:
        children_disagree = len(set(item["segments"])) > 1
        if not children_disagree:
            assert item["set_id"] not in profiled, (
                f"set {item['set_id']} has children that agree and was still "
                "profiled, so the survey is paying for evidence about a "
                "question that does not arise"
            )


def test_absence_is_never_reported_as_evidence() -> None:
    """A node showing nothing attests nothing, and it is the widest row.

    `tools/outgroup_probe.py` measured that scoring absence lands *below*
    alphabetical tie-breaking, so a gap is excluded on the technique's own
    terms rather than to save space. It happens to save the most space too: a
    gap is usually shown by every outside node at once, so it prints the
    longest node list in the result.
    """
    payload = _summarize(_context())
    for profile in payload["outgroup_reflexes"]:
        for reflex in profile["reflexes"]:
            assert reflex["segment"], "a gap was reported as out-group evidence"


def test_a_node_whose_outside_is_all_descendants_says_so() -> None:
    """The root case. Nothing lies outside it, and the note must not imply it does.

    A descendant lies *inside* this node's subtree and shows what these children
    became, which is the proposition under test rather than evidence about it.
    Counting the two together is the cladistic error `polarize` exists to
    prevent, and at the root it would fire on every run.
    """
    payload = _summarize(_context(EvidenceRelation.DESCENDANT))
    note = payload["outgroup_note"]
    assert "every one is a descendant" in note
    assert "nothing lies outside" in note


def test_turning_it_off_restores_the_narrow_result(): 
    """The suppressing flag exists so the cost can be removed and measured.

    It is also what a paired sweep's control arm runs, so it must leave the rest
    of the result untouched rather than merely emptying the new fields.
    """
    wide = _summarize(_context())
    narrow = _summarize(_context(), include_outgroup=False)
    assert narrow["outgroup_reflexes"] == []
    assert narrow["outgroup_note"] == ""
    assert narrow["sets"] == wide["sets"]
    assert narrow["complementary_candidates"] == wide["complementary_candidates"]


def test_the_survey_and_polarize_agree_about_one_correspondence() -> None:
    """The property that makes this a cheaper `polarize` rather than a rival.

    The survey imports `matching_column` and `outside_nodes` from `polarize`
    instead of reimplementing them, precisely so the two cannot disagree about
    which columns show a correspondence. If they did, the model would hold two
    different answers to one question and nothing would say which was right.
    """
    context = _context()
    payload = _summarize(context)
    profiled = {
        profile["set_id"]: profile for profile in payload["outgroup_reflexes"]
    }
    target = next(
        item
        for item in payload["sets"]
        if item["set_id"] in profiled and set(item["segments"]) == {"p", "f"}
    )
    result = default_tool_registry().execute(
        LLMToolCall(
            call_id="p",
            name="polarize",
            arguments={
                "child_ids": list(payload["node_ids"]),
                "correspondence": list(target["segments"]),
            },
        ),
        context,
    )
    assert result.ok, result.error
    from_polarize = {
        (node["node_id"], observation["segment"])
        for node in result.result["nodes"]
        for observation in node["observations"]
    }
    from_survey = {
        (node_id, reflex["segment"])
        for reflex in profiled[target["set_id"]]["reflexes"]
        for node_id in reflex["node_ids"]
    }
    # The survey reports presence only, so it is a subset of what polarize
    # returns, and every presence it reports must be one polarize also saw.
    assert from_survey
    assert from_survey <= from_polarize
