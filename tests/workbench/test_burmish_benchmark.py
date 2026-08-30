"""A second gold node, which is what condition 6 needs and Polynesian lacks.

Condition 6 asks whether a reconstructed child makes a usable parent. Answering
it needs two gold nodes, one above the other. `benchmarks/polynesian.json` has
one, so the question cannot be put there at all.

`hillburmish` has nine varieties and only `ProtoBurmish` is a reconstruction.
Old Burmese is an *attested* older stage, and it is the only other candidate.
Binding it to an internal node is a temporary measure the research owner
approved; `benchmarks/burmish.json` records it as such, and this file pins the
two things that make it removable and the one measurement that makes it
necessary.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cognate_reconstruction.benchmarks import build_benchmark, load_definition
from cognate_reconstruction.ingestion import normalize_tree
from cognate_reconstruction.ingestion.preparation import assert_targets_are_hidden
from cognate_reconstruction.schemas.inventory import CorrespondenceCommitment
from cognate_reconstruction.traversal.assembler import derive_branch_rules
from cognate_reconstruction.tree import parse_newick
from cognate_reconstruction.tree.core import internal_node_ids, postorder_groups

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFINITIONS = REPO_ROOT / "benchmarks"

DAUGHTERS = frozenset(
    f"hillburmish:{name}"
    for name in (
        "AchangLongchuan",
        "Xiandao",
        "Rangoon",
        "Atsi",
        "Bola",
        "Lashi",
        "Maru",
    )
)


@pytest.fixture(scope="module")
def burmish():
    return load_definition(DEFINITIONS / "burmish.json")


def test_both_gold_nodes_are_bound_and_neither_gold_variety_leaks(
    burmish,
) -> None:
    payload, report = build_benchmark(burmish, base_path=DEFINITIONS)
    assert report.daughter_count == 7
    assert set(report.target_node_ids) == {"proto_burmish", "burmic"}
    assert set(report.gold_evidence_kinds) == {"reconstructed", "attested"}
    # Run the check rather than trusting the definition. A second target is
    # exactly when this gets forgotten.
    assert_targets_are_hidden(payload)
    assert {lexicon.variety_id for lexicon in payload.lexicons} == DAUGHTERS


def test_both_gold_nodes_survive_normalization_and_are_traversed(
    burmish,
) -> None:
    payload, _ = build_benchmark(burmish, base_path=DEFINITIONS)
    root = normalize_tree(parse_newick(payload.newick), set(DAUGHTERS))
    nodes = internal_node_ids(root)
    assert nodes == ("maruic", "burmic", "proto_burmish")
    # `burmic` is reconstructed before `proto_burmish` and is one of its
    # children, which is the shape condition 6 is a question about.
    groups = list(postorder_groups(root))
    parent_of_burmic = next(
        parent for children, parent in groups
        if any(child.label == "burmic" for child in children)
    )
    assert parent_of_burmic.label == "proto_burmish"


def test_a_node_above_one_child_is_collapsed_and_cannot_be_gold() -> None:
    """Why the binding is at `burmic` and not at a Burmese-only node.

    Rangoon is the only Southern Burmish variety in the dataset, so any node
    written above Rangoon alone has one child. `normalize_tree` removes it
    silently, and `postorder_groups` refuses it if it survives. Lama's (2012)
    `SouthernBurmish` is exactly such a node; Nishi's (1999) `burmic`, which
    also contains Achang and Xiandao, is not.
    """
    newick = (
        "(('hillburmish:Atsi','hillburmish:Maru')maruic,"
        "('hillburmish:Rangoon')southern_burmish)proto_burmish;"
    )
    leaves = {"hillburmish:Atsi", "hillburmish:Maru", "hillburmish:Rangoon"}
    normalized = normalize_tree(parse_newick(newick), leaves)
    assert "southern_burmish" not in internal_node_ids(normalized)
    with pytest.raises(ValueError, match="has 1 child"):
        list(postorder_groups(parse_newick(newick)))


def test_dropping_the_temporary_binding_changes_nothing_else(burmish) -> None:
    """The binding is temporary, so removing it must be one deletion.

    `concept_selection_source_variety_id` is stated explicitly for this reason:
    without it the selection follows `targets[0]`, and the concept set would
    silently depend on the order of a list someone is about to edit.
    """
    _, both = build_benchmark(burmish, base_path=DEFINITIONS)
    dropped = burmish.model_copy(update={"targets": burmish.targets[:1]})
    _, without = build_benchmark(dropped, base_path=DEFINITIONS)
    assert without.target_node_ids == ("proto_burmish",)
    assert without.selected_concept_ids == both.selected_concept_ids


def test_a_segment_the_dsl_cannot_name_is_reported_not_raised() -> None:
    """`pylexibank` spells a grapheme/phoneme pair with a literal slash.

    `ṅ/ŋ` is one segment. `parse_rule` reads the slash as the environment
    separator, so rendering a derived rule for it raised `ValueError` out of
    `derive_branch_rules`, ended the node, and through `_fallback_step` ended
    the run. Measured over the 174 local CLDF datasets, 104 carry at least one
    such segment — `meloniromance` among them, so `benchmarks/romance.json`
    could not be assembled either, before `hillburmish` existed.
    """
    commitment = CorrespondenceCommitment(
        set_id="s1",
        reflexes=("ṅ/ŋ", "n"),
        proto_segment="ŋ",
        support=4,
        confidence=0.9,
    )
    derived = derive_branch_rules((commitment,), ("A", "B"))
    assert derived.unspellable_reflex_child_ids == ("A",)
    # The other child still gets its rule; only the branch that cannot be
    # spelled loses one.
    assert len(derived.rules) == 1
    assert derived.rules[0].source_child_ids == ("B",)
