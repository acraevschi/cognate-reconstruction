"""A `pylexibank` grapheme/phoneme token is one segment, and it is a spelling.

`pylexibank` writes a segment as `grapheme/phoneme` when an orthography profile
mapped a written character to a different sound. `ṅ/ŋ` is one token. Carried
whole it corresponds with nothing, because no other variety writes it, and the
harness contract is a phonemicized lexicon rather than a transliterated one.

Measured over all 4032 `hillburmish` rows, the left side of eight of the nine
slashed tokens never occurs as a segment of its own: `ṅ`, `ḥ`, `ñ`, `ch`, `o₁`,
`o₂`, `ṅh`, `ñh` all score zero, while `ŋ` occurs 930 times and `ɔ` 542. The
left side is a letter of a script.

What it cost, before this: 24 of the 37 `burmic` gold concepts and 182 of the
900 `romance` gold concepts had no gold alternative that any daughter could
produce.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pytest

from cognate_reconstruction.ingestion import load_cldf_dataset
from cognate_reconstruction.ingestion.cldf import (
    GRAPHEME_PHONEME_RULE_ID,
    CLDFIngestionError,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "examples" / "lexibank_fixture"
HILLBURMISH = REPO_ROOT / "data" / "lexibank" / "hillburmish"
POLYNESIAN = REPO_ROOT / "data" / "lexibank" / "walworthpolynesian"


def _dataset_with_segments(root: Path, segments_by_form: dict[str, str]) -> Path:
    """The checked-in fixture, with some forms respelled."""
    shutil.copytree(FIXTURE, root)
    forms = root / "cldf" / "forms.csv"
    with forms.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
        fields = list(rows[0])
    for row in rows:
        if row["ID"] in segments_by_form:
            row["Segments"] = segments_by_form[row["ID"]]
    with forms.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return root


def test_the_phoneme_replaces_the_token_and_the_spelling_is_kept() -> None:
    loaded = load_cldf_dataset(HILLBURMISH)
    form = next(
        item
        for lexicon in loaded.lexicons
        for item in lexicon.forms
        if item.form_id == "hillburmish:OldBurmese-928_i-1"
    )
    assert form.segments == ("ŋ", "a")
    assert form.provenance.source_segments == ("ṅ/ŋ", "a")
    assert GRAPHEME_PHONEME_RULE_ID in form.provenance.compatibility_rule_ids


def test_a_form_the_adapter_did_not_rewrite_says_nothing_about_it() -> None:
    """`source_segments` is empty on the ordinary case, not a duplicate copy."""
    loaded = load_cldf_dataset(HILLBURMISH)
    form = next(
        item
        for lexicon in loaded.lexicons
        for item in lexicon.forms
        if item.form_id == "hillburmish:Rangoon-928_i-1"
    )
    assert form.segments == ("ŋ", "ɑ", "²²")
    assert form.provenance.source_segments == ()
    assert GRAPHEME_PHONEME_RULE_ID not in form.provenance.compatibility_rule_ids


def test_no_form_in_the_family_still_carries_a_separator() -> None:
    loaded = load_cldf_dataset(HILLBURMISH)
    carried = [
        item.form_id
        for lexicon in loaded.lexicons
        for item in lexicon.forms
        if any("/" in segment for segment in item.segments)
    ]
    assert carried == []


def test_polynesian_is_untouched_so_its_pinned_ceilings_hold() -> None:
    """The recorded baselines were measured on a family with no such token.

    Checked rather than assumed, because a reduction that moved Polynesian
    would make every figure in `docs/benchmarks.md` a figure under a different
    reading.
    """
    loaded = load_cldf_dataset(POLYNESIAN)
    rewritten = [
        item.form_id
        for lexicon in loaded.lexicons
        for item in lexicon.forms
        if item.provenance.source_segments
    ]
    assert rewritten == []


def test_an_empty_grapheme_still_yields_its_phoneme(tmp_path: Path) -> None:
    """`/h` occurs 16 times across four local datasets. The phoneme is intact."""
    root = _dataset_with_segments(
        tmp_path / "empty-grapheme", {"a-water": "/p a"}
    )
    loaded = load_cldf_dataset(root)
    form = next(
        item
        for lexicon in loaded.lexicons
        for item in lexicon.forms
        if item.provenance.source_form_id == "a-water"
    )
    assert form.segments == ("p", "a")


@pytest.mark.parametrize(
    "written",
    ["a/b/c a", "p/ a"],
    ids=["two-separators", "no-phoneme"],
)
def test_a_token_with_no_safe_reading_stops_the_load(
    tmp_path: Path, written: str
) -> None:
    """Neither shape occurs in the 174 local datasets. Neither is guessed at."""
    root = _dataset_with_segments(
        tmp_path / written.replace("/", "-").replace(" ", "_"),
        {"a-water": written},
    )
    with pytest.raises(CLDFIngestionError) as caught:
        load_cldf_dataset(root)
    assert "a-water" in str(caught.value)
    assert "grapheme/phoneme" in str(caught.value)
