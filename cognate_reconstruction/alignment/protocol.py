"""Structural interface for replaceable alignment implementations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from cognate_reconstruction.schemas.alignment import (
    CorrespondenceDetail,
    CorrespondenceMap,
    MultipleAlignmentMap,
)
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm


class AlignmentFailure(ValueError):
    """The alignment engine refused one group of material.

    LingPy is a third-party library reached through
    `alignment/lingpy_adapter.py`, and its pairwise distance divides by the
    summed self-similarity of the two rows. On degenerate material — measured:
    two boundary-only rows of unequal length, such as `['+']` against
    `['+', '+']` — that sum is zero and a bare `ZeroDivisionError` leaves a C
    module and travels to the top of the process. It killed a live sweep on
    2026-08-29 after five of seven nodes had already committed, and the run
    wrote no `result.json`.

    It is a `ValueError` on purpose. `registry.execute` and
    `agent/tools/polarize.py` already code a refused alignment as a tool error
    with `ValueError`, so every model-facing caller keeps the handling it has.
    A caller that can do without the alignment — `correspondence_maps` is a
    report, not a gate — catches this and degrades instead of dying.
    """


class AlignmentProvider(Protocol):
    def align(
        self,
        left: LanguageLexicon,
        right: LanguageLexicon,
        anchors: tuple[LexicalForm, ...] = (),
        *,
        include_boundaries: bool = True,
    ) -> CorrespondenceMap: ...

    def align_multiple(
        self,
        lexicons: Sequence[LanguageLexicon],
        anchors: tuple[LexicalForm, ...] = (),
        *,
        respect_cognate_sets: bool = True,
        correspondence_detail: CorrespondenceDetail = CorrespondenceDetail.FULL,
        include_boundaries: bool = True,
    ) -> MultipleAlignmentMap: ...
