from __future__ import annotations

from pathlib import Path

import pytest

from cognate_reconstruction.alignment import LingPyAligner
from cognate_reconstruction.ingestion import ingest_payload, load_cldf_dataset
from cognate_reconstruction.ingestion.cldf import _segment_indices
from cognate_reconstruction.ingestion.compatibility import tree_glottocode_for
from cognate_reconstruction.schemas.lexicon import (
    CognateMembershipInterpretation,
    CognateMembershipScope,
)
from cognate_reconstruction.tree import parse_newick, postorder_groups


FIXTURE = Path("examples/lexibank_fixture")


def test_native_cldf_loader_preserves_identity_tokens_and_provenance() -> None:
    loaded = load_cldf_dataset(FIXTURE)
    assert [item.variety_id for item in loaded.lexicons] == [
        "lexibank_fixture:A",
        "lexibank_fixture:B",
    ]
    left = loaded.lexicons[0]
    assert left.source_language_id == "A"
    assert left.source_glottocode == "lang1234"
    assert left.tree_glottocode == "lang1234"
    assert len(left.forms) == 2
    assert all(form.provenance.segment_source == "Segments" for form in left.forms)
    assert all(
        form.provenance.source_glottocode == "lang1234"
        and form.provenance.tree_glottocode == "lang1234"
        and form.provenance.source_language_id == "A"
        for form in left.forms
    )
    assert all(
        form.provenance.source_reference
        and form.provenance.source_reference.endswith("cldf-metadata.json")
        for form in left.forms
    )
    water = next(
        form for form in left.forms if form.provenance.source_form_id == "a-water"
    )
    assert water.cognate_set_id is None
    assert water.cognate_set_ids == (
        "lexibank_fixture:water-1",
        "lexibank_fixture:water-alt",
    )
    assert {
        membership.interpretation
        for membership in water.cognate_memberships
    } == {CognateMembershipInterpretation.ALTERNATIVE_ANALYSIS}
    assert all(
        membership.provenance.source_table == "CognateTable"
        and membership.provenance.source_membership_id
        and membership.provenance.alignment == ("p", "a")
        for membership in water.cognate_memberships
    )
    right = loaded.lexicons[1]
    partial = next(
        form
        for form in right.forms
        if form.provenance.source_form_id == "b-water"
    ).cognate_memberships[0]
    assert partial.scope is CognateMembershipScope.SEGMENT_SLICE
    assert partial.interpretation is CognateMembershipInterpretation.PARTIAL_COGNATE
    assert partial.segment_indices == (0, 1)
    assert partial.slice_unit == "segment"
    assert partial.provenance.source_segment_slice == ("1:2",)
    assert partial.provenance.source_slice_unit == "segment"
    # The unsegmented orthographic row is deliberately not split.
    assert "lexibank_fixture:a-raw-only" not in {
        form.form_id for form in left.forms
    }


def test_alignment_surfaces_alternative_and_partial_memberships() -> None:
    loaded = load_cldf_dataset(FIXTURE)
    alignment_map = LingPyAligner().align_multiple(loaded.lexicons)
    water = next(
        alignment
        for alignment in alignment_map.alignments
        if alignment.cognate_set_id == "lexibank_fixture:water-1"
    )
    assert {member.variety_id for member in water.members} == {
        "lexibank_fixture:A",
        "lexibank_fixture:B",
    }
    by_variety = {member.variety_id: member for member in water.members}
    assert (
        by_variety["lexibank_fixture:A"].membership_interpretation
        is CognateMembershipInterpretation.ALTERNATIVE_ANALYSIS
    )
    assert (
        by_variety["lexibank_fixture:B"].membership_scope
        is CognateMembershipScope.SEGMENT_SLICE
    )
    assert by_variety["lexibank_fixture:B"].source_segment_indices == (0, 1)
    assert by_variety["lexibank_fixture:B"].source_slice_unit == "segment"


def test_tree_glottocode_compatibility_never_rewrites_source_identity() -> None:
    tree_glottocode, rules = tree_glottocode_for(
        dataset_id="tlopo",
        source_language_id="pan",
        language_name="Proto-Austronesian",
        source_glottocode=None,
    )
    assert tree_glottocode == "aust1307"
    assert rules == ("tlopo-local-pan",)


def test_custom_lexibank_morpheme_slice_maps_to_phonetic_positions() -> None:
    assert _segment_indices(
        ("2",),
        segments=("p", "a", "+", "m", "i"),
        slice_unit="morpheme",
        membership_id="fixture:membership",
    ) == (3, 4)


def test_fixture_supplied_tree_is_normalized_and_traversable() -> None:
    loaded = load_cldf_dataset(FIXTURE)
    newick = (FIXTURE / "tree.nwk").read_text(encoding="utf-8")
    dataset = ingest_payload(loaded.to_payload(newick=newick))
    assert dataset.tree.newick == (
        "('lexibank_fixture:A','lexibank_fixture:B')PROTO;"
    )
    groups = list(postorder_groups(parse_newick(dataset.tree.newick)))
    assert len(groups) == 1
    assert len(groups[0][0]) == 2


def test_duplicate_supplied_tree_leaf_ids_are_rejected() -> None:
    loaded = load_cldf_dataset(FIXTURE)
    with pytest.raises(ValueError, match="duplicate leaf IDs"):
        ingest_payload(
            loaded.to_payload(
                newick=(
                    "('lexibank_fixture:A','lexibank_fixture:A',"
                    "'lexibank_fixture:B')PROTO;"
                )
            )
        )
