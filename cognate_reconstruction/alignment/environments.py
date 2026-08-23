"""One definition of "the environment of an aligned column", used everywhere.

Three separate mechanisms in this repository ask what lies beside a
correspondence: the `complementary_candidates` report that hands a model the
tokens distinguishing two sets, the `non-complementary-split` rejection that
checks a claimed conditioned split against the data, and the assembler's
two-pass resolution of a conditioned column. If they disagreed about what
"adjacent" means, a model would be handed tokens and then refused for using
them, with no way to see why. So the definition lives here once.

**Adjacency.** The columns of one alignment, in order, skipping every column
that contributes no segment. A column contributes nothing when no node shows a
segment in it (an all-gap column, which `build_correspondence_sets` also skips)
or, once an inventory exists, when the committed set covering it reconstructs
nothing. A column that puts no segment in the proto-form is not part of the
proto-environment.

**What a column reads as.** One rule: *a column reads as what it contributes to
the proto-form, and as what the nodes show where nothing has decided that yet.*

- before any inventory exists — which is the state `summarize_correspondences`
  reports from — nothing has decided anything, so every column reads as the
  distinct non-gap segments its nodes show;
- once an inventory exists, a column a committed set covers reads as that set's
  single `proto_segment`, a column the residue policy carries through reads as
  the witness's segment, and a column that contributes nothing — a dropped
  residue, or a set that reconstructs nothing — reads as the empty set and is
  skipped when walking.

The complementarity check and the assembler therefore resolve the columns the
same way, through the same code, before either looks at an environment.

The consequence worth stating, because it is the one asymmetry left: a token a
model was handed by the report is always accepted where it was observed, unless
the model's *own* inventory reconstructs that column as something else. The
goalposts can only be moved by the commit being checked, which is legible in
the commit.

**Satisfaction is membership, not agreement.** `left = ("e",)` is satisfied
when `e` is among the tokens the preceding column reads as — not when every
node shows `e` there. The report unions across nodes, so the check has to
accept the union it reported.

**A word edge is `#`.** It cannot collide with a segment because
`rules/parser.py::_tokens` refuses `#` inside a segment expression.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from cognate_reconstruction.schemas.rules import RuleEnvironment

WORD_EDGE_TOKEN = "#"
"""How a word edge is reported among context tokens.

`rules/parser.py::_tokens` refuses `#` inside a segment expression, so this can
never be confused with a segment a node actually shows.
"""

ColumnReading = frozenset[str] | None
"""What one column reads as: its tokens, or `None` for "not yet decided".

An empty frozenset means the column contributes nothing and is skipped when
walking. `None` means a caller could not decide the column yet — the assembler's
pass-2 case — and any environment whose evaluation reaches it is undecidable
rather than false.
"""

UNDECIDED = "undecided"
"""Sentinel returned by `environment_matches` when a reading was `None`."""


def observed_column_tokens(
    rows: Sequence[Sequence[str | None]],
    column_index: int,
) -> frozenset[str]:
    """The distinct non-gap segments the nodes show in one aligned column."""
    return frozenset(
        row[column_index]
        for row in rows
        if column_index < len(row) and row[column_index] is not None
    )


def observed_readings(
    rows: Sequence[Sequence[str | None]],
) -> tuple[frozenset[str], ...]:
    """Read every column of an alignment as the segments its nodes show."""
    width = max((len(row) for row in rows), default=0)
    return tuple(observed_column_tokens(rows, index) for index in range(width))


def _neighbours(
    readings: Sequence[ColumnReading],
    index: int,
    *,
    forward: bool,
) -> tuple[list[frozenset[str]], bool]:
    """Walk away from `index`, skipping empty columns, until a `None` is hit.

    Returns the readings passed, nearest first, and whether the walk ran to the
    edge of the alignment without meeting an undecided column. A `False` second
    element means "there may be more material out there that nobody has decided
    yet", which is what makes a word-edge test undecidable.
    """
    positions = (
        range(index + 1, len(readings)) if forward else range(index - 1, -1, -1)
    )
    passed: list[frozenset[str]] = []
    for position in positions:
        reading = readings[position]
        if reading is None:
            return passed, False
        if reading:
            passed.append(reading)
    return passed, True


def environment_matches(
    environment: RuleEnvironment,
    readings: Sequence[ColumnReading],
    index: int,
) -> bool | str:
    """Does the column at `index` sit in `environment`?

    Returns `True`, `False`, or :data:`UNDECIDED` when the answer depends on a
    column whose reading is `None`. Callers that have decided every column — the
    report and the complementarity check — never see the third value; the
    assembler's pass 2 does, and that is exactly the "deciding neighbour is
    itself still ambiguous" case §4.4 of `docs/proto_inventory_design.md`
    requires to fall to residue.
    """
    left_tokens = (
        environment.left.tokens if environment.left is not None else ()
    )
    right_tokens = (
        environment.right.tokens if environment.right is not None else ()
    )
    undecided = False

    before, before_complete = _neighbours(readings, index, forward=False)
    after, after_complete = _neighbours(readings, index, forward=True)

    if environment.word_initial:
        if before:
            return False
        if not before_complete:
            undecided = True
    if environment.word_final:
        if after:
            return False
        if not after_complete:
            undecided = True

    # `left` reads left-to-right, so its last token is the one adjacent to the
    # target; `before` is nearest-first, so the two are zipped in reverse.
    for offset, token in enumerate(reversed(left_tokens)):
        if offset >= len(before):
            return UNDECIDED if not before_complete else False
        if token not in before[offset]:
            return False
    for offset, token in enumerate(right_tokens):
        if offset >= len(after):
            return UNDECIDED if not after_complete else False
        if token not in after[offset]:
            return False
    return UNDECIDED if undecided else True


def context_tokens(
    readings: Sequence[ColumnReading],
    index: int,
) -> tuple[frozenset[str], frozenset[str]]:
    """The tokens immediately left and right of one column, edges included.

    A word edge contributes :data:`WORD_EDGE_TOKEN` rather than nothing, so a
    set occurring only word-initially reports `{"#"}` on the left rather than an
    empty set that would read as "no information".
    """
    before, before_complete = _neighbours(readings, index, forward=False)
    after, after_complete = _neighbours(readings, index, forward=True)
    left = (
        before[0]
        if before
        else (frozenset({WORD_EDGE_TOKEN}) if before_complete else frozenset())
    )
    right = (
        after[0]
        if after
        else (frozenset({WORD_EDGE_TOKEN}) if after_complete else frozenset())
    )
    return left, right


def readings_from(
    rows: Sequence[Sequence[str | None]],
    decided: Mapping[int, ColumnReading],
) -> tuple[ColumnReading, ...]:
    """Read every column as what it contributes to the proto-form.

    `decided[index]` is what an inventory resolved the column to: a one-token
    set, the empty set for a column that contributes nothing, or `None` for a
    column nobody has decided yet. A column absent from `decided` falls back to
    the segments the nodes show, which is exactly what the pre-inventory report
    hands a model — so the degenerate case, an empty `decided`, is the report's
    own reading and the two can never drift apart.
    """
    width = max((len(row) for row in rows), default=0)
    return tuple(
        decided[index] if index in decided else observed_column_tokens(rows, index)
        for index in range(width)
    )


__all__ = [
    "UNDECIDED",
    "WORD_EDGE_TOKEN",
    "ColumnReading",
    "context_tokens",
    "environment_matches",
    "readings_from",
    "observed_column_tokens",
    "observed_readings",
]
