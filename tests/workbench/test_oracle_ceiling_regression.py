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

**Two oracles are pinned here, and neither replaces the other.** `context_free`
is the measure every recorded baseline used and is asserted unchanged;
`contextual` searches the DSL's own environments as well and is asserted beside
it. A second measure that quietly became the first would make every recorded
before/after uncomparable, so the two are separate assertions on purpose. The
contextual one is likewise not a target: it writes 249 rules across 16 branches
where the context-free one writes 52, many conditioned on a single word, which
is a perfect rule writer rather than a plausible analysis.

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
from types import SimpleNamespace

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

# 39 until 2026-08-22, when `measure()` started scoring against *every* gold
# alternative through `compare_to_nearest`, as `HistoricalTargetEvaluation`
# already did. Two of these 46 concepts carry alternatives and `1443` WALK
# carries four; the dict comprehension that built the gold kept only the last of
# them, so a beam holding `ʔ a l u` was scored a miss against `f a n o`. Top-1
# did not move. See `docs/proto_inventory_design.md` §0.5.
PINNED_BEAM_EXACT = 40

# Recorded 2026-08-20, matching `docs/analysis_tools.md`. Top-1 first,
# beam-exact second. Beam-exact re-recorded 2026-08-22 for the reason above;
# top-1 is unchanged at every width, including through the `order_rules()`
# ordering fix landed the same day.
PINNED_BY_WIDTH = {
    1: (22, 22),
    3: (26, 36),
    5: (27, 40),
    10: (26, 40),
}

# The second measure, recorded 2026-08-22. Pinned *beside* the figures above,
# never in place of them.
PINNED_CONTEXTUAL_TOP_EXACT = 33
PINNED_CONTEXTUAL_BEAM_EXACT = 40
PINNED_CONTEXTUAL_BY_WIDTH = {
    1: (22, 22),
    3: (32, 39),
    5: (33, 40),
    10: (33, 40),
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
    # The headline. 28.3 points of accuracy are lost after the model has
    # finished, in how a parent is chosen from child evidence.
    assert result.beam_exact - result.top_exact == 13
    assert result.selection_gap == pytest.approx(13 / 46, abs=1e-9)
    # Which node's gold produced the number, carried in the measurement rather
    # than inferred from the tree. `bindings[0]` used to decide this silently.
    assert result.gold_node_id == "proto_polynesian"
    assert result.oracle == "context_free"
    assert result.as_dict()["gold_node_id"] == "proto_polynesian"


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
    # 0.158 / 0.043 / 0.960 until 2026-08-22. The graded numbers moved with
    # beam-exact and for the same reason: `compare_to_nearest` now grades
    # against the nearest gold alternative rather than the last-listed one.
    assert result.mean_top_normalized_edit_distance == pytest.approx(
        0.147, abs=0.005
    )
    assert result.mean_beam_best_normalized_edit_distance == pytest.approx(
        0.030, abs=0.005
    )
    assert result.mean_top_bcubed_f1 == pytest.approx(0.963, abs=0.005)
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
    stripped = WorkbenchPayload.model_validate_json(
        FIXTURE.read_text(encoding="utf-8")
    )
    full = WorkbenchPayload.model_validate_json(real.read_text(encoding="utf-8"))
    for oracle in ("context_free", "contextual"):
        fixture_result = module.measure(
            stripped, PINNED_BEAM_WIDTH, oracle=oracle
        )
        real_result = module.measure(full, PINNED_BEAM_WIDTH, oracle=oracle)
        assert (fixture_result.top_exact, fixture_result.beam_exact) == (
            real_result.top_exact,
            real_result.beam_exact,
        ), f"the fixture and the real benchmark disagree under {oracle}"
        assert fixture_result.evaluated == real_result.evaluated


def test_order_rules_orders_its_own_docstring_example() -> None:
    """The assertion whose absence let the cascade run backwards for five days.

    `order_rules` has always documented the feeding argument correctly — "a rule
    whose target is another rule's replacement must therefore run first" — and
    from `febf03b` (2026-08-17) to 2026-08-22 it implemented the opposite,
    emitting a source once nothing mapped *into* it. Nothing in the suite
    compared the code to the docstring, and the tree-level figures this module
    pins did not move when it was fixed, so nothing else would have caught it
    either. On the real benchmark it cost Hawaiian seven of 46 forms: its oracle
    map is the chain shift `{ʔ: k, k: t}`, and the reversed order rewrote
    `ʔ a k a` to `t a t a` instead of gold `k a t a`.
    """
    module = _oracle_module()
    assert module.order_rules({"k": "t", "t": "s"}) == [("t", "s"), ("k", "t")]
    # The Hawaiian case in its own right, since that is where it was costing
    # forms and it is the reverse of the docstring example, not a copy of it.
    assert module.order_rules({"ʔ": "k", "k": "t"}) == [("k", "t"), ("ʔ", "k")]
    # A rule that feeds nothing and is fed by nothing is unconstrained, and a
    # deletion is not a source anything can consume.
    assert module.order_rules({"p": "f", "h": None}) == [("h", None), ("p", "f")]


def test_order_rules_still_drops_a_true_swap() -> None:
    """A cycle needs a scratch symbol the DSL has not got, so it is dropped.

    Kept as an assertion because "the oracle is honest about what it cannot
    express" is a documented property of this instrument, and the ordering fix
    rewrote the routine that enforces it.
    """
    assert _oracle_module().order_rules({"p": "b", "b": "p"}) == []


def test_the_contextual_oracle_is_pinned_beside_the_context_free_one(
    payload,
) -> None:
    """A second measure, asserted separately, replacing nothing.

    `oracle_map()` is context-free and the DSL is not, so every "the
    architecture cannot reach this form" conclusion drawn from the pinned
    figures above was a statement about the oracle. This is the same
    reconstructor driven by a rule writer as strong as the rule language:
    per source segment it searches the environments the DSL can spell for ones
    that purely separate one gold target from another.

    It is a bound and not a target. It writes 249 rules over 16 branches where
    the context-free oracle writes 52, and one branch it would make worse falls
    back to the context-free cascade — which is what makes it >= the first
    measure per branch by construction rather than by argument.
    """
    result = _oracle_module().measure(
        payload, PINNED_BEAM_WIDTH, oracle="contextual"
    )
    assert result.oracle == "contextual"
    assert result.evaluated == EVALUATED_CONCEPTS
    assert result.top_exact == PINNED_CONTEXTUAL_TOP_EXACT
    assert result.beam_exact == PINNED_CONTEXTUAL_BEAM_EXACT
    assert result.branches == 16
    assert result.rules_written == 249
    assert result.fallback_branches == 1


def test_the_contextual_oracle_holds_at_every_documented_beam_width(
    payload,
) -> None:
    module = _oracle_module()
    measured = {
        width: (result.top_exact, result.beam_exact)
        for width in PINNED_CONTEXTUAL_BY_WIDTH
        for result in (module.measure(payload, width, oracle="contextual"),)
    }
    assert measured == PINNED_CONTEXTUAL_BY_WIDTH


def test_the_contextual_oracle_never_scores_below_the_context_free_one(
    payload,
) -> None:
    """The invariant that makes the pair meaningful rather than two numbers.

    The contextual builder falls back per branch, so it cannot be worse branch
    for branch; this asserts the tree-level consequence at every documented
    width. A contextual figure that dropped below the context-free one would
    mean the fallback stopped working, and the two measures would no longer be
    comparable at all.
    """
    module = _oracle_module()
    for width in PINNED_BY_WIDTH:
        context_free = module.measure(payload, width)
        contextual = module.measure(payload, width, oracle="contextual")
        assert contextual.top_exact >= context_free.top_exact, width
        assert contextual.beam_exact >= context_free.beam_exact, width


def test_contextual_graded_distances_are_recorded_too(payload) -> None:
    result = _oracle_module().measure(
        payload, PINNED_BEAM_WIDTH, oracle="contextual"
    )
    assert result.mean_top_normalized_edit_distance == pytest.approx(
        0.097, abs=0.005
    )
    assert result.mean_beam_best_normalized_edit_distance == pytest.approx(
        0.024, abs=0.005
    )
    assert result.mean_top_bcubed_f1 == pytest.approx(0.964, abs=0.005)


def test_every_gold_alternative_is_scored_not_only_the_last(payload) -> None:
    """The defect, pinned as the difference it makes rather than as prose.

    `1443` WALK carries four gold proto-forms. `measure()` used to build its
    gold with a dict comprehension over `binding.forms`, so three of them were
    discarded and a beam holding `ʔ a l u` — which is exactly Tongan's form —
    was scored a miss against `f a n o`. `HistoricalTargetEvaluation` has always
    scored through `compare_to_nearest` over `target_segment_alternatives`; this
    asserts the oracle now agrees with the harness it is supposed to bound.
    """
    module = _oracle_module()
    binding = next(
        item
        for item in payload.historical_form_bindings
        if item.role.value == "target"
    )
    counts: dict[str, int] = {}
    for form in binding.forms:
        counts[form.concept_id] = counts.get(form.concept_id, 0) + 1
    assert counts["1443"] == 4, "the fixture no longer carries the defect's case"

    reduced = payload.model_copy(
        update={
            "historical_form_bindings": (
                binding.model_copy(
                    update={
                        "forms": tuple(
                            {form.concept_id: form for form in binding.forms}.values()
                        )
                    }
                ),
            )
        }
    )
    last_only = module.measure(reduced, PINNED_BEAM_WIDTH)
    assert last_only.evaluated == EVALUATED_CONCEPTS
    assert last_only.top_exact == PINNED_TOP_EXACT
    assert last_only.beam_exact == PINNED_BEAM_EXACT - 1


def test_the_gold_binding_defaults_to_the_root_and_is_never_guessed() -> None:
    """`bindings[0]` is not the root's gold on a family with gold at three nodes.

    On `synthetic_hard` the first-written binding is `east`, so the root beam was
    scored against a sister's gold and published under the root's name. The fix
    is two rules: take the root's own binding where there is one, and refuse to
    pick where there is not. Exercised against stubs because the multi-gold
    families are generated rather than committed, and the decision under test is
    the selection, not the payload.
    """
    module = _oracle_module()

    def binding(node_id: str, role: str = "target"):
        return SimpleNamespace(
            node_id=node_id, role=SimpleNamespace(value=role)
        )

    east, proto, west = binding("east"), binding("proto"), binding("west")
    multi = SimpleNamespace(historical_form_bindings=(east, proto, west))
    assert module.select_binding(multi, "proto", None) is proto
    assert module.select_binding(multi, "proto", "east") is east

    rootless = SimpleNamespace(historical_form_bindings=(east, west))
    with pytest.raises(SystemExit) as refused:
        module.select_binding(rootless, "proto", None)
    assert "--gold-node" in str(refused.value)
    assert module.select_binding(rootless, "proto", "west") is west

    with pytest.raises(SystemExit):
        module.select_binding(multi, "proto", "nowhere")
    with pytest.raises(SystemExit):
        module.select_binding(
            SimpleNamespace(historical_form_bindings=(binding("proto", "anchor"),)),
            "proto",
            None,
        )
