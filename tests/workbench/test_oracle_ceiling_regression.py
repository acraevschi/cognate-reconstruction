"""Pin the deterministic reconstruction quality, not only its mechanics.

The rest of the suite proves the harness does exactly what it was told. It says
nothing about whether the answers are good, so a change to `traversal/beam.py`
or `traversal/reconstructor.py` can make every reconstruction worse while 279
tests pass. That happened in miniature already: the contrast-loss counter added
to `traversal/reconstructor.py` was only known not to have moved the score
because a human remembered to run `tools/oracle_ceiling.py` by hand.

**What the oracle is.** Every branch is given the best child-to-parent segment
map computed directly against the withheld gold, and the real
`RuleBasedReconstructor` then runs bottom-up. The model's only job — choosing
rules — has been done perfectly, so whatever comes out bounds what any model
can score under the current architecture.

**What the oracle is not, and this is the part a reader must carry away.**
`oracle_map()` assigns one target per source segment, *globally*: it is
context-free, while the DSL has left and right contexts and word edges. Tongan
`ʔ e l e l o` reaches gold `ʔ a l e l o` with the single rule `e > a / ʔ_`,
which the DSL expresses and the oracle cannot write. Morphological boundaries
are skipped outright, because the DSL forbids them as rule targets, and rules
whose ordering would form a cycle are dropped. So these figures bound *this
oracle*, never the rule language: a miss here is not evidence that the
architecture cannot reach the form, and quoting one as a structural limit is
the mistake `prompts/06-proto-inventory.md` records.

**Why the gap is asserted and not only the accuracies.** A change that raises
top-1 while lowering beam-exact has traded candidates away rather than chosen
better among them, and an accuracy-only assertion would call that a win. Branch
support is the counter-example worth remembering: it raised top-1 at every beam
width and lowered beam-exact at none, which is the shape a genuine selection
fix has.

The fixture is the real 46-concept Polynesian benchmark with per-form
provenance and cognate memberships stripped. The oracle reads segments, the
tree, and the gold binding and nothing else, so the fixture reproduces the
full-dataset numbers exactly — verified against
`runs/benchmarks/polynesian.json`, which `tools/oracle_ceiling.py` still runs
against directly.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from cognate_reconstruction.schemas.ingestion import WorkbenchPayload

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "polynesian_benchmark_segments.json"
)

# Beam width is pinned, and pinning it is a decision rather than a detail: width
# 10 scores *below* width 5 on this benchmark — an ordinary beam-search
# artifact, where a wider beam keeps a distractor that accumulates enough mass
# to win — so a test that did not pin the width would read that as a
# regression.
PINNED_BEAM_WIDTH = 5
EVALUATED_CONCEPTS = 46
PINNED_TOP_EXACT = 27
PINNED_BEAM_EXACT = 39

# Recorded 2026-08-20, matching `docs/analysis_tools.md`. Top-1 first,
# beam-exact second.
PINNED_BY_WIDTH = {
    1: (22, 22),
    3: (26, 36),
    5: (27, 39),
    10: (26, 39),
}


def _oracle_module():
    """Import `tools/oracle_ceiling.py` as the module it is.

    `tools/` is deliberately outside the package and not importable, which is
    right for an analysis instrument and inconvenient for exactly one caller:
    this test, which must pin the same measurement the script prints. Importing
    the file keeps a single implementation instead of a copy that drifts.
    """
    tools = str(REPO_ROOT / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    spec = importlib.util.spec_from_file_location(
        "oracle_ceiling", REPO_ROOT / "tools" / "oracle_ceiling.py"
    )
    module = importlib.util.module_from_spec(spec)
    # Registered before execution because the module defines a dataclass, and
    # `dataclasses` resolves annotations through `sys.modules`.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def payload() -> WorkbenchPayload:
    return WorkbenchPayload.model_validate_json(
        FIXTURE.read_text(encoding="utf-8")
    )


def test_oracle_ceiling_and_its_selection_gap_are_unchanged(payload) -> None:
    result = _oracle_module().measure(payload, PINNED_BEAM_WIDTH)
    assert result.root_node_id == "proto_polynesian"
    assert result.evaluated == EVALUATED_CONCEPTS
    assert result.top_exact == PINNED_TOP_EXACT, (
        "top-1 exact accuracy under oracle rules moved. If this is an "
        "improvement, check beam-exact below before recording it: a change "
        "that raises top-1 while lowering beam-exact traded candidates away."
    )
    assert result.beam_exact == PINNED_BEAM_EXACT, (
        "the correct form is now in the beam a different number of times. "
        "This is the number a selection change must not move."
    )
    # The headline. 26.1 points of accuracy are lost after the model has
    # finished, in how a parent is chosen from child evidence.
    assert result.beam_exact - result.top_exact == 12
    assert result.selection_gap == pytest.approx(12 / 46, abs=1e-9)


def test_oracle_ceiling_holds_at_every_documented_beam_width(payload) -> None:
    """The whole width curve, because the shape of a change is the evidence.

    Widening the beam does not close the selection gap — beam-exact saturates
    at width 5 — and top-1 peaks there rather than rising monotonically. Both
    facts are in `docs/analysis_tools.md`, and a change that alters either is
    worth a human reading the diff.
    """
    module = _oracle_module()
    measured = {
        width: (result.top_exact, result.beam_exact)
        for width in PINNED_BY_WIDTH
        for result in (module.measure(payload, width),)
    }
    assert measured == PINNED_BY_WIDTH


def test_graded_oracle_distances_are_recorded_beside_the_exact_counts(
    payload,
) -> None:
    """The graded ceiling, so a near-miss regression is visible too.

    Exact counts move in steps of 1/46. A change that leaves every concept in
    the same match/miss bucket while making the misses worse would not move
    them at all, and normalized edit distance would.
    """
    result = _oracle_module().measure(payload, PINNED_BEAM_WIDTH)
    assert result.mean_top_normalized_edit_distance == pytest.approx(
        0.158, abs=0.005
    )
    assert result.mean_beam_best_normalized_edit_distance == pytest.approx(
        0.043, abs=0.005
    )
    assert result.mean_top_bcubed_f1 == pytest.approx(0.960, abs=0.005)
    # Non-negative by construction: the reported form is in the beam.
    assert result.normalized_edit_distance_selection_gap > 0.0


def test_the_fixture_is_the_real_benchmark_when_the_corpus_is_present() -> None:
    """Guard the claim in this module's docstring rather than asserting it.

    `data/lexibank/` is a user-managed local corpus and is not committed, so
    this skips where the corpus is absent. Where it is present, it proves the
    stripped fixture and the real payload are the same measurement — which is
    the only reason the pinned numbers may be quoted as full-dataset figures.
    """
    real = REPO_ROOT / "runs" / "benchmarks" / "polynesian.json"
    if not real.exists():
        pytest.skip("runs/benchmarks/polynesian.json has not been built")
    module = _oracle_module()
    fixture_result = module.measure(
        WorkbenchPayload.model_validate_json(
            FIXTURE.read_text(encoding="utf-8")
        ),
        PINNED_BEAM_WIDTH,
    )
    real_result = module.measure(
        WorkbenchPayload.model_validate_json(real.read_text(encoding="utf-8")),
        PINNED_BEAM_WIDTH,
    )
    assert (fixture_result.top_exact, fixture_result.beam_exact) == (
        real_result.top_exact,
        real_result.beam_exact,
    )
    assert fixture_result.evaluated == real_result.evaluated
