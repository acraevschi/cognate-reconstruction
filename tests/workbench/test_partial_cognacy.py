"""Cognacy coded one morpheme at a time, which is where `hillburmish` keeps it.

`hillburmish` did not load at all. The loader looked for a FormTable
`Cognateset_ID` column or a `CognateTable`, and the dataset publishes neither:
measured over all 4032 rows of `data/lexibank/hillburmish/cldf/forms.csv`,
`Cognacy` is empty in 4032 and `Partial_Cognacy` is populated in 4032. The
entire cognate signal sat in the one column the loader did not read.

1679 of those rows (42%) carry more than one cognate ID, and *exactly* those
1679 carry a `+` boundary. So the data says which piece of a compound is the
cognate piece, morpheme by morpheme, and nothing here has to guess it.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from cognate_reconstruction.alignment import LingPyAligner
from cognate_reconstruction.ingestion import load_cldf_dataset
from cognate_reconstruction.ingestion.cldf import CLDFIngestionError
from cognate_reconstruction.schemas.alignment import CorrespondenceDetail
from cognate_reconstruction.schemas.lexicon import (
    CognateMembershipInterpretation,
    CognateMembershipScope,
)

HILLBURMISH = Path("data/lexibank/hillburmish")
FIXTURE = Path("examples/lexibank_fixture")


def _partial_cognacy_dataset(
    root: Path,
    *,
    forms: str,
    keep_cognate_table: bool,
) -> Path:
    """A copy of the fixture whose cognacy lives in `Partial_Cognacy`."""
    shutil.copytree(FIXTURE, root)
    cldf = root / "cldf"
    metadata = json.loads((cldf / "cldf-metadata.json").read_text())
    tables = metadata["tables"]
    if not keep_cognate_table:
        metadata["tables"] = [
            table for table in tables if table["url"] != "cognates.csv"
        ]
        (cldf / "cognates.csv").unlink()
    for table in metadata["tables"]:
        if table["url"] != "forms.csv":
            continue
        table["tableSchema"]["columns"].append(
            {"name": "Partial_Cognacy", "datatype": "string"}
        )
    (cldf / "cldf-metadata.json").write_text(json.dumps(metadata))
    (cldf / "forms.csv").write_text(forms)
    return root


def test_hillburmish_loads_and_every_form_keeps_its_cognacy() -> None:
    loaded = load_cldf_dataset(HILLBURMISH)
    assert loaded.num_forms == 4032
    assert len(loaded.lexicons) == 9
    assert all(
        form.cognate_memberships
        for lexicon in loaded.lexicons
        for form in lexicon.forms
    )


def test_a_compound_becomes_one_membership_per_morpheme() -> None:
    """The traced example from the prompt, end to end.

    `Rangoon-962_alleverything-1`: segments `m̥ ɑ̃ ²² + tθ ɑ ⁵³ + m̥ j ɑ ⁵³`,
    `Partial_Cognacy = 3078 536 3079`.
    """
    loaded = load_cldf_dataset(HILLBURMISH)
    form = next(
        item
        for lexicon in loaded.lexicons
        for item in lexicon.forms
        if item.form_id == "hillburmish:Rangoon-962_alleverything-1"
    )
    assert form.segments == (
        "m̥", "ɑ̃", "²²", "+", "tθ", "ɑ", "⁵³", "+", "m̥", "j", "ɑ", "⁵³",
    )
    assert [item.cognate_set_id for item in form.cognate_memberships] == [
        "hillburmish:3078",
        "hillburmish:536",
        "hillburmish:3079",
    ]
    assert [
        item.segment_indices for item in form.cognate_memberships
    ] == [(0, 1, 2), (4, 5, 6), (8, 9, 10, 11)]
    assert all(
        item.scope is CognateMembershipScope.SEGMENT_SLICE
        and item.interpretation
        is CognateMembershipInterpretation.PARTIAL_COGNATE
        and item.slice_unit == "morpheme"
        and item.provenance.source_table == "FormTable"
        for item in form.cognate_memberships
    )
    # The one-based inclusive slice is kept verbatim, as it is for a
    # CognateTable, so the source row can be reconstructed from provenance.
    assert [
        item.provenance.source_segment_slice
        for item in form.cognate_memberships
    ] == [("1",), ("2",), ("3",)]
    # The shorthand stays null: this is a partial analysis, not one
    # unambiguous whole-form set.
    assert form.cognate_set_id is None


def test_a_simplex_form_is_still_read_one_morpheme_at_a_time() -> None:
    """One reading of the column, whether or not the form has a boundary."""
    loaded = load_cldf_dataset(HILLBURMISH)
    form = next(
        item
        for lexicon in loaded.lexicons
        for item in lexicon.forms
        if item.form_id == "hillburmish:Rangoon-928_i-1"
    )
    membership, = form.cognate_memberships
    assert membership.cognate_set_id == "hillburmish:665"
    assert membership.scope is CognateMembershipScope.SEGMENT_SLICE
    assert membership.segment_indices == (0, 1, 2)


def test_a_morpheme_aligns_against_the_morpheme_that_shares_its_id(
    tmp_path: Path,
) -> None:
    """Position does not decide the pairing. The cognate ID does.

    The two forms carry the same two morphemes in opposite orders, so a reading
    that matched morpheme 1 to morpheme 1 would align `p a k i` against
    `a k a`. Nothing in the harness picks the pairing: `_alignment_inputs`
    groups by the `cognate_set_id` the data recorded.
    """
    forms = """ID,Language_ID,Parameter_ID,Form,Segments,Partial_Cognacy
a-water,A,water,pakiaka,p a k i + a k a,900 901
b-water,B,water,akapaki,a k a + p a k i,901 900
"""
    root = _partial_cognacy_dataset(
        tmp_path / "crossed", forms=forms, keep_cognate_table=False
    )
    loaded = load_cldf_dataset(root)
    aligned = LingPyAligner().align_multiple(
        loaded.lexicons, correspondence_detail=CorrespondenceDetail.SUMMARY
    )
    by_set = {
        alignment.cognate_set_id: alignment for alignment in aligned.alignments
    }
    dataset_id = loaded.dataset_id
    assert set(by_set) == {f"{dataset_id}:900", f"{dataset_id}:901"}
    for set_id, expected in (
        (f"{dataset_id}:900", ("p", "a", "k", "i")),
        (f"{dataset_id}:901", ("a", "k", "a")),
    ):
        members = by_set[set_id].members
        assert len(members) == 2
        assert all(
            tuple(
                token for token in member.aligned_segments if token is not None
            )
            == expected
            for member in members
        )


def test_a_count_mismatch_stops_the_load_and_names_the_form(
    tmp_path: Path,
) -> None:
    """Zipping the shorter of the two is how a corpus acquires a fiction."""
    forms = """ID,Language_ID,Parameter_ID,Form,Segments,Partial_Cognacy
a-water,A,water,pakiaka,p a k i + a k a,900
b-water,B,water,aka,a k a,901
"""
    root = _partial_cognacy_dataset(
        tmp_path / "mismatch", forms=forms, keep_cognate_table=False
    )
    with pytest.raises(CLDFIngestionError) as caught:
        load_cldf_dataset(root)
    message = str(caught.value)
    assert "a-water" in message
    assert "1 Partial_Cognacy IDs but 2 morphemes" in message


def test_a_cldf_cognate_table_wins_and_partial_cognacy_is_left_unread(
    tmp_path: Path,
) -> None:
    """One dataset, one reading.

    `Partial_Cognacy` is a Lexibank custom column with no `propertyUrl`. A
    dataset that publishes a `CognateTable` has already said where its cognacy
    lives, and the two number different things: measured on `crossandean`,
    `Cognacy` and `Partial_Cognacy` disagree on 7511 of 7518 rows.
    """
    forms = """ID,Language_ID,Parameter_ID,Form,Segments,Partial_Cognacy
a-water,A,water,pa,p a,900
b-water,B,water,fa,f a,900
"""
    root = _partial_cognacy_dataset(
        tmp_path / "both", forms=forms, keep_cognate_table=True
    )
    loaded = load_cldf_dataset(root)
    memberships = [
        membership
        for lexicon in loaded.lexicons
        for form in lexicon.forms
        for membership in form.cognate_memberships
    ]
    assert memberships, "the CognateTable is still read"
    assert all(
        membership.provenance.source_table == "CognateTable"
        for membership in memberships
    )
    assert not any(
        membership.cognate_set_id.endswith(":900") for membership in memberships
    )


def test_a_dataset_with_no_cognate_evidence_still_says_so(
    tmp_path: Path,
) -> None:
    forms = """ID,Language_ID,Parameter_ID,Form,Segments,Partial_Cognacy
a-water,A,water,pa,p a,
b-water,B,water,fa,f a,
"""
    root = _partial_cognacy_dataset(
        tmp_path / "empty", forms=forms, keep_cognate_table=False
    )
    with pytest.raises(CLDFIngestionError) as caught:
        load_cldf_dataset(root)
    assert "no usable tokenized forms with cognate assignments" in str(
        caught.value
    )
