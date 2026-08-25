"""The per-correspondence-set commit protocol, end to end through the registry.

The refinement loop `docs/proto_inventory_design.md` §6.6 prescribes is:
survey, polarize, align, assign a value per set, preview, read the unaccounted
columns, refine, preview again, commit. The point of testing it through the
registry rather than through the functions is that prompt 03 exists because the
prescribed workflow had no legal path through the commit contract. If the loop
does not close, it fails here.
"""

from __future__ import annotations

import pytest

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.schemas import LLMToolCall
from cognate_reconstruction.agent.tools import default_tool_registry
from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.schemas.inventory import CorrespondenceCommitment
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm
from cognate_reconstruction.schemas.traversal import (
    EvidenceKind,
    EvidenceRelation,
    NodeEvidence,
)

# Tongan keeps *ʔ, Niuean lost it — the live `tongic` failure, in miniature.
# Neither daughter's string is the answer, which is the whole case for the
# change: `⟨ʔ : Ø⟩ → *ʔ` is unwritable as a branch-scoped rule because the DSL
# cannot insert.
TONGAN = {
    "1205": ("ʔ", "e", "l", "e", "l", "o"),
    "1237": ("ʔ", "a", "t", "a"),
    "1430": ("ʔ", "u", "l", "u"),
    "670": ("t", "a", "l", "i"),
}
NIUEAN = {
    "1205": ("a", "l", "e", "l", "o"),
    "1237": ("a", "t", "a"),
    "1430": ("u", "l", "u"),
    "670": ("t", "a", "l", "i"),
}
# An out-group that still attests the glottal stop, for the restoration case.
SAMOAN = {
    "1205": ("ʔ", "a", "l", "e", "l", "o"),
    "1237": ("ʔ", "a", "t", "a"),
    "1430": ("ʔ", "u", "l", "u"),
    "670": ("t", "a", "l", "i"),
}


def _lexicon(variety_id: str, forms: dict[str, tuple[str, ...]]) -> LanguageLexicon:
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
            for concept_id, segments in sorted(forms.items())
        ),
    )


def _context(*, with_outgroup: bool = False) -> AgentContext:
    children = (_lexicon("Tongan", TONGAN), _lexicon("Niuean", NIUEAN))
    evidence = [
        NodeEvidence(
            node_id=lexicon.variety_id,
            kind=EvidenceKind.OBSERVED,
            relation=EvidenceRelation.ACTIVE_CHILD,
            lexicon=lexicon,
            descendant_leaf_ids=(lexicon.variety_id,),
        )
        for lexicon in children
    ]
    if with_outgroup:
        outgroup = _lexicon("Samoan", SAMOAN)
        evidence.append(
            NodeEvidence(
                node_id="Samoan",
                kind=EvidenceKind.OBSERVED,
                relation=EvidenceRelation.OUTGROUP,
                lexicon=outgroup,
                descendant_leaf_ids=("Samoan",),
            )
        )
    return AgentContext(
        node_id="tongic",
        child_lexicons=children,
        aligner=LingPyAligner(),
        evidence=tuple(evidence),
    )


def _call(registry, context, name, call_id, **arguments):
    return registry.execute(
        LLMToolCall(call_id=call_id, name=name, arguments=arguments), context
    )


def _survey(registry, context, **arguments) -> dict:
    result = _call(
        registry, context, "summarize_correspondences", "survey", min_support=1,
        **arguments,
    )
    assert result.ok, result.error
    return result.result


def _sets_by_reflexes(survey: dict) -> dict[tuple, dict]:
    return {
        tuple(item["segments"]): item for item in survey["sets"]
    }


def _commitment(item: dict, proto: str | None, **extra) -> dict:
    return {
        "set_id": item["set_id"],
        "reflexes": list(item["segments"]),
        "proto_segment": proto,
        "support": item["support"],
        "confidence": 0.9,
        **extra,
    }


# --------------------------------------------------------------------------
# The loop closes
# --------------------------------------------------------------------------


def test_the_survey_names_every_set_and_the_assembler_reproduces_them() -> None:
    """The set IDs a model is handed must be ones the assembler can match.

    This is the invariant the whole protocol rests on: without it a model
    commits values for sets the assembler never sees, every column falls to
    residue, and the mechanism reads as never having fired.
    """
    context = _context()
    registry = default_tool_registry()
    survey = _survey(registry, context)
    by_reflexes = _sets_by_reflexes(survey)
    assert all(item["set_id"] for item in survey["sets"])
    glottal = by_reflexes[("ʔ", None)]
    assert glottal["support"] == 3

    result = _call(
        registry,
        context,
        "test_proto_assembly",
        "preview",
        commitments=[_commitment(item, item["segments"][0] or item["segments"][1])
                     for item in survey["sets"]],
        residue_policy="drop",
        detail="full",
    )
    assert result.ok, result.error
    payload = result.result
    # Every column of every concept was explained by a committed set.
    assert payload["unaccounted_column_rate"] == 0.0
    assembled = {
        report["concept_id"]: tuple(report["assembled_segments"])
        for report in payload["concepts"]
    }
    # Every column of 1205 came from a committed set, including the initial
    # `ʔ` that only Tongan attests. (This inventory reads the Tongan reflex off
    # every set, so the vowel is `e`; the next test commits `*a` for it.)
    assert assembled["1205"] == ("ʔ", "e", "l", "e", "l", "o")
    assert all(
        column["resolved_by"] == "set"
        for report in payload["concepts"]
        for column in report["columns"]
    )


def test_a_glottal_stop_no_rule_can_insert_is_reconstructed_and_recorded() -> None:
    context = _context()
    registry = default_tool_registry()
    survey = _survey(registry, context)
    by_reflexes = _sets_by_reflexes(survey)
    commitments = [
        _commitment(
            by_reflexes[("ʔ", None)],
            "ʔ",
            rationale="Tongan attests it and Niuean lost it word-initially.",
            directionality_rationale=(
                "Niuean innovated the loss; nothing conditions inserting a "
                "glottal stop word-initially in one branch."
            ),
        ),
        _commitment(by_reflexes[("e", "a")], "a", rationale="Tongan lowered it."),
    ]
    preview = _call(
        registry,
        context,
        "test_proto_assembly",
        "preview",
        commitments=commitments,
        residue_policy="retain_from_witness",
        residue_witness_child_id="Tongan",
    )
    assert preview.ok, preview.error
    # Niuean shows a gap against a reconstructed segment, which is the insertion
    # the DSL cannot write. Recorded, not rejected.
    assert preview.result["non_invertible_child_ids"] == ["Niuean"]
    assert preview.result["cross_branch_assembly_rate"] > 0.0

    commit = _call(
        registry,
        context,
        "commit_reconstruction",
        "commit",
        node_id="tongic",
        inventory={
            "child_node_ids": ["Tongan", "Niuean"],
            "commitments": commitments,
            "residue_policy": "retain_from_witness",
            "residue_witness_child_id": "Tongan",
        },
        anomalies=[],
        summary="Proto-Tongic keeps *ʔ; Niuean lost it.",
    )
    assert commit.ok, commit.error
    reconstruction = commit.result["reconstruction"]
    assert reconstruction["commit_shape"] == "inventory"
    assert reconstruction["proto_phonemes"] == ["a", "ʔ"]
    assert reconstruction["non_invertible_child_ids"] == ["Niuean"]
    assert (
        reconstruction["request"]["assembly_validation_call_id"] == "preview"
    )
    assert commit.result["assembly"]["cross_branch_assembly_rate"] > 0.0


def test_an_empty_inventory_is_an_identity_commit() -> None:
    context = _context()
    registry = default_tool_registry()
    commit = _call(
        registry,
        context,
        "commit_reconstruction",
        "commit",
        node_id="tongic",
        inventory={
            "child_node_ids": ["Tongan", "Niuean"],
            "commitments": [],
            "residue_policy": "retain_from_witness",
            "residue_witness_child_id": "Tongan",
        },
        anomalies=[],
        summary="Nothing yet explains these correspondences.",
    )
    assert commit.ok, commit.error
    assert commit.result["reconstruction"]["proto_phonemes"] == []


# --------------------------------------------------------------------------
# The rejections, and what each of them is refusing
# --------------------------------------------------------------------------


def test_a_commitment_citing_a_set_the_data_does_not_contain_is_refused() -> None:
    context = _context()
    registry = default_tool_registry()
    survey = _survey(registry, context)
    commitment = _commitment(_sets_by_reflexes(survey)[("ʔ", None)], "ʔ")
    commitment["set_id"] = "cs-000000000000"
    result = _call(
        registry,
        context,
        "test_proto_assembly",
        "preview",
        commitments=[commitment],
        residue_policy="drop",
    )
    assert not result.ok
    assert result.error.code == "unknown-correspondence-set"
    # The remediation names the set the model actually meant.
    assert "under a different ID" in result.error.remediation


def test_altering_a_sets_support_is_refused() -> None:
    context = _context()
    registry = default_tool_registry()
    survey = _survey(registry, context)
    commitment = _commitment(_sets_by_reflexes(survey)[("ʔ", None)], "ʔ")
    commitment["support"] = 99
    result = _call(
        registry,
        context,
        "test_proto_assembly",
        "preview",
        commitments=[commitment],
        residue_policy="drop",
    )
    assert not result.ok
    assert result.error.code == "correspondence-support-mismatch"
    assert "Set 'support' to 3" in result.error.remediation


def test_committing_without_a_covering_preview_is_refused() -> None:
    context = _context()
    registry = default_tool_registry()
    survey = _survey(registry, context)
    commitments = [_commitment(_sets_by_reflexes(survey)[("ʔ", None)], "ʔ")]
    commit = _call(
        registry,
        context,
        "commit_reconstruction",
        "commit",
        node_id="tongic",
        inventory={
            "child_node_ids": ["Tongan", "Niuean"],
            "commitments": commitments,
            "residue_policy": "drop",
        },
        anomalies=[],
        summary="Proto-Tongic keeps *ʔ.",
    )
    assert not commit.ok
    assert commit.error.code == "missing-assembly-validation"


def test_a_commit_carrying_both_shapes_is_refused() -> None:
    context = _context()
    registry = default_tool_registry()
    commit = _call(
        registry,
        context,
        "commit_reconstruction",
        "commit",
        node_id="tongic",
        rules=[{"dsl": "ʔ > Ø / #_", "source_child_ids": ["Tongan"], "confidence": 0.9}],
        inventory={
            "child_node_ids": ["Tongan", "Niuean"],
            "commitments": [],
            "residue_policy": "drop",
        },
        anomalies=[],
        summary="Both at once.",
    )
    assert not commit.ok
    assert commit.error.code.startswith("schema:")
    assert "never both" in commit.error.message


def test_a_set_that_reconstructs_nothing_needs_a_directionality_rationale() -> None:
    context = _context()
    registry = default_tool_registry()
    survey = _survey(registry, context)
    commitments = [_commitment(_sets_by_reflexes(survey)[("ʔ", None)], None)]
    preview = _call(
        registry,
        context,
        "test_proto_assembly",
        "preview",
        commitments=commitments,
        residue_policy="drop",
    )
    assert preview.ok, preview.error
    commit = _call(
        registry,
        context,
        "commit_reconstruction",
        "commit",
        node_id="tongic",
        inventory={
            "child_node_ids": ["Tongan", "Niuean"],
            "commitments": commitments,
            "residue_policy": "drop",
        },
        anomalies=[],
        summary="Tongan innovated the glottal stop.",
    )
    assert not commit.ok
    assert commit.error.code == "missing-directionality-rationale"
    # Rejected on absence, never on content: the same claim with any sentence
    # attached is accepted and left for a reviewer.
    commitments[0]["directionality_rationale"] = "Tongan innovated it."
    accepted = _call(
        registry,
        _context(),
        "commit_reconstruction",
        "commit",
        node_id="tongic",
        inventory={
            "child_node_ids": ["Tongan", "Niuean"],
            "commitments": commitments,
            "residue_policy": "drop",
        },
        anomalies=[],
        summary="Tongan innovated the glottal stop.",
    )
    # A fresh context has no preview, so this one is refused for that instead —
    # which is the point: the directionality check passed.
    assert accepted.error.code == "missing-assembly-validation"


def test_a_non_complementary_split_is_refused_against_the_columns() -> None:
    context = _context()
    registry = default_tool_registry()
    survey = _survey(registry, context)
    by_reflexes = _sets_by_reflexes(survey)
    left = _commitment(
        by_reflexes[("l", "l")],
        "l",
        conditioning={"word_initial": True},
        rationale="claimed word-initial",
    )
    right = _commitment(
        by_reflexes[("t", "t")],
        "l",
        conditioning={"word_final": True},
        rationale="claimed word-final",
        merges_with_set_id=left["set_id"],
    )
    result = _call(
        registry,
        context,
        "test_proto_assembly",
        "preview",
        commitments=[left, right],
        residue_policy="drop",
    )
    assert not result.ok
    assert result.error.code == "non-complementary-split"


def test_a_restoration_at_a_node_with_no_outgroup_is_refused() -> None:
    context = _context()
    registry = default_tool_registry()
    result = _call(
        registry,
        context,
        "test_proto_assembly",
        "preview",
        commitments=[],
        residue_policy="drop",
        restorations=[
            {
                "concept_id": "1205",
                "before_column_index": 0,
                "proto_segment": "ʔ",
                "restored_from_node_ids": ["Samoan"],
                "directionality_rationale": "both children lost it",
            }
        ],
    )
    assert not result.ok
    assert result.error.code == "restoration-without-outgroup"


def test_a_restoration_citing_an_unattesting_outgroup_is_refused() -> None:
    context = _context(with_outgroup=True)
    registry = default_tool_registry()
    result = _call(
        registry,
        context,
        "test_proto_assembly",
        "preview",
        commitments=[],
        residue_policy="drop",
        restorations=[
            {
                "concept_id": "670",
                "before_column_index": 0,
                "proto_segment": "ʔ",
                "restored_from_node_ids": ["Samoan"],
                "directionality_rationale": "both children lost it",
            }
        ],
    )
    assert not result.ok
    assert result.error.code == "restoration-unattested"


def test_a_restoration_citing_a_descendant_is_refused() -> None:
    """The cladistic error `polarize` was built to prevent.

    The node genuinely has an out-group, so the refusal is about *which* node
    was cited rather than about the node having none: a descendant lies inside
    the subtree and shows what these children became.
    """
    context = _context(with_outgroup=True)
    inside = _lexicon("TonganDialect", TONGAN)
    context.evidence = (
        *context.evidence,
        NodeEvidence(
            node_id="TonganDialect",
            kind=EvidenceKind.OBSERVED,
            relation=EvidenceRelation.DESCENDANT,
            lexicon=inside,
            descendant_leaf_ids=("TonganDialect",),
        ),
    )
    registry = default_tool_registry()
    result = _call(
        registry,
        context,
        "test_proto_assembly",
        "preview",
        commitments=[],
        residue_policy="drop",
        restorations=[
            {
                "concept_id": "1205",
                "before_column_index": 0,
                "proto_segment": "ʔ",
                "restored_from_node_ids": ["TonganDialect"],
                "directionality_rationale": "both children lost it",
            }
        ],
    )
    assert not result.ok
    assert result.error.code == "restoration-cites-descendant"


def test_the_residue_witness_must_be_an_active_child() -> None:
    context = _context()
    registry = default_tool_registry()
    result = _call(
        registry,
        context,
        "test_proto_assembly",
        "preview",
        commitments=[],
        residue_policy="retain_from_witness",
        residue_witness_child_id="Samoan",
    )
    assert not result.ok
    assert result.error.code == "inactive-children"


# --------------------------------------------------------------------------
# realign
# --------------------------------------------------------------------------


def test_a_realignment_must_reproduce_the_childrens_own_forms() -> None:
    context = _context()
    registry = default_tool_registry()
    result = _call(
        registry,
        context,
        "realign",
        "realign",
        overrides=[
            {
                "concept_id": "1237",
                "rows": [["ʔ", "a", "t", "a"], ["ʔ", "a", "t", "a"]],
                "joins_set_id": None,
                "rationale": "invented a glottal stop for Niuean",
            }
        ],
        rationale="fitting the alignment",
    )
    assert not result.ok
    assert result.error.code == "overlay-invalid-edit"
    assert "not a form it attests" in result.error.message


def test_a_realignment_claiming_a_set_it_does_not_join_is_refused() -> None:
    context = _context()
    registry = default_tool_registry()
    survey = _survey(registry, context)
    lateral = _sets_by_reflexes(survey)[("l", "l")]["set_id"]
    result = _call(
        registry,
        context,
        "realign",
        "realign",
        overrides=[
            {
                "concept_id": "1237",
                "rows": [["ʔ", "a", "t", "a"], [None, "a", "t", "a"]],
                "joins_set_id": lateral,
                "rationale": "claims to add an l:l column, which it does not",
            }
        ],
        rationale="a claim the data refutes",
    )
    assert not result.ok
    assert result.error.code == "realignment-does-not-join-set"
    # The refused overlay is discarded, so no commit can cite it.
    assert context.alignment_overlays == {}


def test_a_new_set_realignment_is_legal_and_counted_separately() -> None:
    context = _context()
    registry = default_tool_registry()
    result = _call(
        registry,
        context,
        "realign",
        "realign",
        overrides=[
            {
                "concept_id": "1237",
                "rows": [["ʔ", "a", "t", "a"], [None, "a", "t", "a"]],
                "joins_set_id": None,
                "rationale": "the first attestation of this correspondence",
            }
        ],
        rationale="repairing one concept",
    )
    assert result.ok, result.error
    payload = result.result
    assert payload["new_set_override_count"] == 1
    assert payload["override_concept_count"] == 1
    assert payload["node_concept_count"] == 4
    assert "1 of 4 concept(s)" in payload["advisory"]
    assert payload["alignment_overlay_id"] in context.alignment_overlays


def test_a_realignment_changes_the_set_ids_and_says_which_ones_died() -> None:
    context = _context()
    registry = default_tool_registry()
    before = _survey(registry, context)
    realigned = _call(
        registry,
        context,
        "realign",
        "realign",
        overrides=[
            {
                "concept_id": "1430",
                "rows": [["ʔ", "u", "l", "u"], [None, "u", "l", "u"]],
                "joins_set_id": None,
                "rationale": "line the glottal stop up against a gap",
            }
        ],
        rationale="repairing one concept",
    )
    assert realigned.ok, realigned.error
    overlay = realigned.result["alignment_overlay_id"]
    after = _survey(registry, context, alignment_overlay_id=overlay)
    before_ids = {item["set_id"] for item in before["sets"]}
    after_ids = {item["set_id"] for item in after["sets"]}
    # Every ID changes, because the overlay is part of the digest.
    assert not (before_ids & after_ids)
    # A commit must cite IDs derived under the overlay it names.
    stale = _commitment(_sets_by_reflexes(before)[("ʔ", None)], "ʔ")
    result = _call(
        registry,
        context,
        "test_proto_assembly",
        "preview",
        commitments=[stale],
        residue_policy="drop",
        alignment_overlay_id=overlay,
    )
    assert not result.ok
    assert result.error.code == "unknown-correspondence-set"


# --------------------------------------------------------------------------
# The complementary-candidate report
# --------------------------------------------------------------------------


def test_the_survey_reports_the_tokens_that_distinguish_a_complementary_pair() -> None:
    """Addition 1. A report that states a conclusion must show its evidence."""
    context = _context()
    registry = default_tool_registry()
    survey = _survey(registry, context)
    assert survey["complementary_candidate_count"] >= 1
    by_ids = {
        tuple(item["set_ids"]): item
        for item in survey["complementary_candidates"]
    }
    assert by_ids
    for candidate in by_ids.values():
        assert candidate["shared_environment_count"] == 0
        assert candidate["distinguishing_node_ids"]
        left, right = candidate["left_context_tokens"]
        right_left, right_right = candidate["right_context_tokens"]
        # Either the left contexts or the right contexts must be disjoint —
        # that is what "never share an environment" is decided on.
        assert not (set(left) & set(right)) or not (
            set(right_left) & set(right_right)
        )
    # `#` marks a word edge and cannot collide with a segment.
    edges = {
        token
        for candidate in by_ids.values()
        for tokens in candidate["left_context_tokens"]
        for token in tokens
    }
    assert "#" in edges


def test_the_report_and_the_rejection_read_the_same_environment() -> None:
    """Addition 1, constraint 2, as an executable claim.

    A model handed a distinguishing token must not then be refused for using
    it. Here the glottal-stop set occurs only word-initially, the report says
    so with `#`, and a commitment conditioned on `word_initial` is accepted.
    """
    context = _context()
    registry = default_tool_registry()
    survey = _survey(registry, context)
    by_reflexes = _sets_by_reflexes(survey)
    glottal = by_reflexes[("ʔ", None)]
    candidate = next(
        item
        for item in survey["complementary_candidates"]
        if glottal["set_id"] in item["set_ids"]
    )
    side = item_index = candidate["set_ids"].index(glottal["set_id"])
    assert "#" in candidate["left_context_tokens"][side]
    del item_index

    result = _call(
        registry,
        context,
        "test_proto_assembly",
        "preview",
        commitments=[
            _commitment(glottal, "ʔ", conditioning={"word_initial": True})
        ],
        residue_policy="drop",
    )
    assert result.ok, result.error
    assembled = {
        report["concept_id"]: tuple(report["assembled_segments"])
        for report in result.result["concepts"]
    }
    # The conditioned commitment fired everywhere the report said it would.
    assert assembled["1205"] == ("ʔ",)
    assert "670" not in assembled or assembled.get("670") != ("ʔ",)


# --------------------------------------------------------------------------
# Prior-node hypotheses across the migration
# --------------------------------------------------------------------------


def test_a_prior_inventory_is_exposed_without_its_set_ids() -> None:
    from cognate_reconstruction.agent.tools import summarize_inventory
    from cognate_reconstruction.schemas.inventory import (
        CommitProtoInventoryArgs,
        CommittedProtoInventory,
        CorrespondenceCommitment,
        ResiduePolicy,
        derive_set_id,
    )

    reflexes = ("ʔ", None)
    commit = CommittedProtoInventory(
        request=CommitProtoInventoryArgs(
            node_id="tongic",
            child_node_ids=("Tongan", "Niuean"),
            commitments=(
                CorrespondenceCommitment(
                    set_id=derive_set_id(
                        reflexes,
                        ("Tongan", "Niuean"),
                        segmentation_overlay_id=None,
                        alignment_overlay_id=None,
                    ),
                    reflexes=reflexes,
                    proto_segment="ʔ",
                    support=3,
                    confidence=0.9,
                ),
            ),
            residue_policy=ResiduePolicy.DROP,
            summary="Proto-Tongic keeps *ʔ.",
        ),
        proto_phonemes=("ʔ",),
    )
    prior = summarize_inventory("tongic", commit)
    assert prior.child_node_ids == ("Tongan", "Niuean")
    assert prior.sets[0].reflexes == ("ʔ", None)
    # A set ID names a reflex tuple over *that* node's children under *that*
    # node's overlays, so it is meaningless here and is stripped.
    assert not hasattr(prior.sets[0], "set_id")


def test_a_context_can_only_hold_one_shape_per_prior_node() -> None:
    from cognate_reconstruction.agent.schemas import GetNodeReconstructionResult

    with pytest.raises(ValueError, match="rule set or an inventory"):
        GetNodeReconstructionResult()


def test_a_gap_may_be_written_the_way_the_dsl_writes_one() -> None:
    """Measured on a live node, not guessed.

    A model that knows the sound-law DSL knows `Ø` and `∅` as "nothing", and
    `summarize_correspondences` already accepts either in its `segment` filter.
    Writing `["∅", "ʔ"]` for the `⟨Ø : ʔ⟩` set cost a live session three turns:
    a support mismatch it had not made, then two more finding `null`.
    """
    context = _context()
    registry = default_tool_registry()
    survey = _survey(registry, context)
    glottal = _sets_by_reflexes(survey)[("ʔ", None)]
    for spelling in ("Ø", "∅"):
        commitment = _commitment(glottal, "ʔ")
        commitment["reflexes"] = ["ʔ", spelling]
        result = _call(
            registry,
            _context(),
            "test_proto_assembly",
            "preview",
            commitments=[commitment],
            residue_policy="drop",
        )
        assert result.ok, result.error
        assert result.result["covered_set_ids"] == [glottal["set_id"]]
    # And a segment that merely looks like a gap is still a segment: only the
    # two DSL spellings are normalized.
    commitment = _commitment(glottal, "ʔ")
    commitment["reflexes"] = ["ʔ", "0"]
    refused = _call(
        registry,
        _context(),
        "test_proto_assembly",
        "preview",
        commitments=[commitment],
        residue_policy="drop",
    )
    assert not refused.ok


# --------------------------------------------------------------------------
# The invariant the whole protocol rests on, on a real ten-daughter benchmark
# --------------------------------------------------------------------------

POLYNESIAN_FIXTURE = (
    __import__("pathlib").Path(__file__).parent
    / "fixtures"
    / "polynesian_benchmark_segments.json"
)


def test_every_set_the_survey_names_is_one_the_assembler_matches() -> None:
    """Ten daughters, 46 concepts, and not one column left to residue.

    This is the invariant that decides whether the mechanism can fire at all,
    and it broke silently the first time: `summarize_correspondences` aligned the
    child *lexicons*, which at an internal node is every retained beam candidate,
    while the assembler aligns one candidate per child. Different alignments mean
    different columns mean reflex tuples that match no committed set — a model
    would commit values for sets the assembler never sees, every column would
    fall to residue, and `cross_branch_assembly_rate` would read 0 everywhere,
    which is the design's own stop condition fired by a defect.

    So: commit a value for *every* set the survey returns and require that the
    assembler explains every column. Anything less is the two views having drifted
    apart again.
    """
    import json

    from cognate_reconstruction.ingestion import ingest_payload
    from cognate_reconstruction.schemas.ingestion import WorkbenchPayload

    payload = WorkbenchPayload.model_validate_json(
        POLYNESIAN_FIXTURE.read_text(encoding="utf-8")
    )
    dataset = ingest_payload(payload)
    context = AgentContext(
        node_id="proto",
        child_lexicons=tuple(dataset.lexicons),
        aligner=LingPyAligner(),
    )
    registry = default_tool_registry()

    sets: list[dict] = []
    offset = 0
    while True:
        page = _call(
            registry,
            context,
            "summarize_correspondences",
            f"survey-{offset}",
            min_support=1,
            limit=200,
            offset=offset,
        )
        assert page.ok, page.error
        sets.extend(page.result["sets"])
        if page.result["next_offset"] is None:
            break
        offset = page.result["next_offset"]
    assert len(sets) > 100

    commitments = [
        {
            "set_id": item["set_id"],
            "reflexes": item["segments"],
            # Any value will do: what is under test is whether the *column* was
            # matched, not what it was matched to.
            "proto_segment": next(
                (segment for segment in item["segments"] if segment), None
            ),
            "support": item["support"],
            "confidence": 0.8,
            "rationale": "one value per set",
            "directionality_rationale": "one value per set",
        }
        for item in sets
    ]
    preview = _call(
        registry,
        context,
        "test_proto_assembly",
        "preview",
        commitments=commitments,
        residue_policy="retain_from_witness",
        residue_witness_child_id=context.child_ids[-1],
    )
    assert preview.ok, preview.error
    result = preview.result
    assert result["assembled_concept_count"] == 46
    assert result["unaccounted_column_rate"] == 0.0
    # And the mechanism fires: on most concepts no single child's derived
    # cascade reproduces the assembled form.
    assert result["cross_branch_assembly_rate"] > 0.5
    # The preview that validates a commit stays affordable. §6.8 budgeted
    # 27.8 KB for the whole node; the half a session must carry to its commit is
    # a fraction of that, which is what makes the rest droppable.
    payload_size = len(json.dumps(result, ensure_ascii=False).encode())
    header = {
        key: value
        for key, value in result.items()
        if key not in ("concepts", "derived_rules")
    }
    header_size = len(json.dumps(header, ensure_ascii=False).encode())
    assert payload_size < 200 * 1024
    assert header_size < 8 * 1024


# --------------------------------------------------------------------------
# §12.5 — a segmentation overlay now changes columns, not only their names
# --------------------------------------------------------------------------


def test_a_boundary_overlay_creates_a_column_and_renames_every_set() -> None:
    """The interaction the boundary fix had to be checked against, not assumed.

    `segment_morphemes` writes boundary-only overlays and validates that the
    phonetic tokens are unchanged, and the overlay ID has always entered every
    `set_id` digest. While the aligner stripped boundaries, that digest was the
    *only* thing an overlay changed: the same six columns came back under six
    new names, so `build_correspondence_sets`'s claim that "a segmentation
    overlay changes what a segment is" was true of the ID and of nothing else.

    Now the overlay genuinely adds a column. Both halves are asserted: the new
    `⟨+ : +⟩` set exists, and no set ID survives the overlay — so a set cited
    from a survey run under one segmentation can never silently match a column
    derived under another.
    """
    children = (
        _lexicon("A", {"bird": ("m", "a", "n", "u", "l", "e")}),
        _lexicon("B", {"bird": ("m", "a", "n", "u", "r", "e")}),
    )
    context = AgentContext(
        node_id="PROTO", child_lexicons=children, aligner=LingPyAligner()
    )
    registry = default_tool_registry()

    before = _call(
        registry, context, "summarize_correspondences", "before",
        min_support=1, limit=50,
    )
    assert before.ok, before.error
    assert not [
        item for item in before.result["sets"] if "+" in item["segments"]
    ]

    segmented = _call(
        registry, context, "segment_morphemes", "segment",
        segmentations=[
            {"form_id": "A:bird", "segments": ["m", "a", "n", "u", "+", "l", "e"]},
            {"form_id": "B:bird", "segments": ["m", "a", "n", "u", "+", "r", "e"]},
        ],
        rationale="the reduplicated root starts here",
    )
    assert segmented.ok, segmented.error
    overlay_id = segmented.result["segmentation_overlay_id"]

    after = _call(
        registry, context, "summarize_correspondences", "after",
        min_support=1, limit=50, segmentation_overlay_id=overlay_id,
    )
    assert after.ok, after.error
    boundary = [
        item for item in after.result["sets"] if item["segments"] == ["+", "+"]
    ]
    assert len(boundary) == 1
    assert not (
        {item["set_id"] for item in before.result["sets"]}
        & {item["set_id"] for item in after.result["sets"]}
    )


def test_every_way_a_model_writes_a_gap_means_the_same_gap() -> None:
    """The rejection class that stalled ten nodes on the Polynesian sweep.

    `_normalize_gaps` originally took `Ø` and `∅`, because a model that knows
    the sound-law DSL knows those. A model writing a JSON array of segments
    reaches for something else: on 2026-08-24 the live sweep sent `['+', '']`
    and `['+', 'null']` against the set `['+', None]` twenty-four times, was
    refused each time, and stalled ten nodes out of protocol-failure repeats.

    Widening the accepted spellings loosens no check: the reflex tuple is still
    compared against the harness's own inventory, and `set_id` is still derived
    from it.
    """
    for spelling in ("", "null", "None", "Ø", "∅"):
        commitment = CorrespondenceCommitment(
            set_id="cs-whatever",
            reflexes=["+", spelling],
            proto_segment="+",
            support=3,
            confidence=0.9,
        )
        assert commitment.reflexes == ("+", None), spelling


def test_a_lowercase_slashed_o_is_a_vowel_and_not_a_gap() -> None:
    """Why the gap spellings are matched exactly and never case-folded.

    `ø` U+00F8 is the close-mid front rounded vowel. Only `Ø` U+00D8 means the
    gap. Folding case would silently delete a real reflex, which is a worse
    failure than the one the widening fixes.
    """
    commitment = CorrespondenceCommitment(
        set_id="cs-whatever",
        reflexes=["ø", "a"],
        proto_segment="ø",
        support=3,
        confidence=0.9,
    )
    assert commitment.reflexes == ("ø", "a")


def test_the_required_fields_of_a_commitment_say_so_in_their_descriptions() -> None:
    """The model reads the schema; a requirement cannot live only in code.

    Measured on the four sweeps of 2026-08-24: `commitments[].confidence` was
    omitted 19 times across the two flipped conditions and never once under the
    pre-stage-3 instructions, because it is required, has no default, and its
    description said only what the number means. `proto_segment` and `reflexes`
    were the same failure and were fixed the same way in `655a3e4`.
    """
    properties = CorrespondenceCommitment.model_json_schema()["properties"]
    required = set(CorrespondenceCommitment.model_json_schema()["required"])
    for name in ("confidence", "proto_segment", "reflexes"):
        assert name in required, name
        assert "equired" in properties[name]["description"], name
    confidence = properties["confidence"]["description"]
    assert "no default" in confidence
    assert "score weight" in confidence


def test_no_commitment_field_faces_the_model_undescribed() -> None:
    properties = CorrespondenceCommitment.model_json_schema()["properties"]
    assert all("description" in properties[name] for name in properties), sorted(
        name for name in properties if "description" not in properties[name]
    )
