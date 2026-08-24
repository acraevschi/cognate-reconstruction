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

**Three oracles are pinned here, and none replaces another.** `context_free`
is the measure every recorded baseline used and is asserted unchanged;
`contextual` searches the DSL's own environments as well and is asserted beside
it. A second measure that quietly became the first would make every recorded
before/after uncomparable, so the two are separate assertions on purpose. The
contextual one is likewise not a target: it writes 249 rules across 16 branches
where the context-free one writes 52, many conditioned on a single word, which
is a perfect rule writer rather than a plausible analysis.

`assembly` is the third, and it measures a different architecture rather than a
stronger rule writer: one proto-phoneme per correspondence set at each node,
assembled column by column by the real `ProtoInventoryAssembler`. It is here
because during the migration both architectures exist and a reader needs the
before and the after in one file — `docs/proto_inventory_design.md` §9.3 — and
it is pinned separately for the same reason the first two are. **Its beam-exact
is not comparable to theirs by subtraction.** Under a branch cascade the beam
holds one whole string per branch and beam-exact measures the selection slack;
under assembly one candidate tuple assembles into exactly one form, so the two
numbers converge by construction and there is almost no slack left to measure.
§7.3 of the design says the same thing in one line: the two beams contain
different kinds of thing.

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

# The third measure, recorded 2026-08-24, and the first pinned figure in this
# module that is not a rule cascade at all. Beam width barely moves it — 39/39
# from width 1 to width 10 — which is the same fact the gap assertion below
# states from the other side: assembly has no whole-string selection step for a
# wider beam to feed.
PINNED_ASSEMBLY_TOP_EXACT = 39
PINNED_ASSEMBLY_BEAM_EXACT = 39
PINNED_ASSEMBLY_BY_WIDTH = {
    1: (39, 39),
    3: (39, 39),
    5: (39, 39),
    10: (39, 39),
}

# What the design asks this test to watch under the new architecture, in place
# of the 13-form selection gap it watches under the old one. §9.3: "a large gap
# would mean the assembler is generating candidates it then fails to select
# among, which is the old defect returning at a new level."
MAX_ASSEMBLY_SELECTION_GAP = 2


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
    for oracle in ("context_free", "contextual", "assembly"):
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


def test_the_assembly_oracle_is_pinned_beside_both_cascade_oracles(
    payload,
) -> None:
    """The same question, put to the architecture that replaces the cascade.

    Every branch is no longer given a rule set; every *node* is given one
    proto-phoneme per correspondence set, voted against the withheld gold, and
    the real `ProtoInventoryAssembler` builds each parent form out of the
    children's aligned columns. `docs/proto_inventory_design.md` §9.3 asks for
    exactly this and asks for it to land beside the two figures above rather
    than in place of them.

    **What this oracle is deliberately not given**, because each is a claim
    about one concept where an inventory is a claim about a language:
    `restorations` — which would hand it the `*w` in `1028` YAWN that no
    daughter attests — and `residue_dispositions`. §7.4 records `1028` and `778`
    as concepts the assembly ceiling cannot promise, and they stay unpromised:
    both are still misses here.

    It is also not a target, for the same reason the contextual one is not. It
    commits several hundred sets across the tree, many of them conditioned on an
    environment that is pure over a single word.
    """
    result = _oracle_module().measure(
        payload, PINNED_BEAM_WIDTH, oracle="assembly"
    )
    assert result.oracle == "assembly"
    assert result.evaluated == EVALUATED_CONCEPTS
    assert result.top_exact == PINNED_ASSEMBLY_TOP_EXACT
    assert result.beam_exact == PINNED_ASSEMBLY_BEAM_EXACT
    assert result.gold_node_id == "proto_polynesian"
    # An inventory writes no rules, and the counters say which architecture
    # produced the number rather than reporting 0 for both.
    assert result.rules_written == 0
    assert result.commitments_written is not None
    assert result.commitments_written > 0
    assert len(result.residue_policy_choices) == 7


def test_the_assembly_selection_gap_stays_small(payload) -> None:
    """§9.3's gap assertion, in the new architecture's terms.

    Under a branch cascade the gap is the headline defect: 13 of 46 forms are
    computed and then not reported. Under assembly a candidate tuple assembles
    into exactly one parent form, so a large gap would mean the assembler is
    generating candidates it then fails to select among — the old defect
    returning one level down. It is currently zero.
    """
    result = _oracle_module().measure(
        payload, PINNED_BEAM_WIDTH, oracle="assembly"
    )
    gap = result.beam_exact - result.top_exact
    assert 0 <= gap <= MAX_ASSEMBLY_SELECTION_GAP, (
        "assembly is now computing correct forms it does not report. That is "
        "the whole-string selection defect this architecture removes, "
        "reappearing at the level of candidate tuples."
    )


def test_the_assembly_oracle_holds_at_every_documented_beam_width(
    payload,
) -> None:
    """Flat across the curve, which is the point rather than an accident.

    The cascade oracles gain 5 forms of beam-exact between width 1 and width 3
    because a wider beam keeps more whole strings to choose among. Assembly
    gains nothing, because there is nothing left to choose.
    """
    module = _oracle_module()
    measured = {
        width: (result.top_exact, result.beam_exact)
        for width in PINNED_ASSEMBLY_BY_WIDTH
        for result in (module.measure(payload, width, oracle="assembly"),)
    }
    assert measured == PINNED_ASSEMBLY_BY_WIDTH


def test_assembly_graded_distances_and_mechanism_reports_are_recorded(
    payload,
) -> None:
    """The graded ceiling and the two per-node reports §7 reads.

    `cross_branch_assembly_rate` is condition 3's instrument: a rate of 0 at
    every node would mean the mixing mechanism never fired and whatever moved
    was not this change. Nothing here is a gate — these are reports, asserted so
    that a change which silently zeroes one is visible.
    """
    result = _oracle_module().measure(
        payload, PINNED_BEAM_WIDTH, oracle="assembly"
    )
    assert result.mean_top_normalized_edit_distance == pytest.approx(
        0.031, abs=0.005
    )
    assert result.mean_beam_best_normalized_edit_distance == pytest.approx(
        0.031, abs=0.005
    )
    assert result.mean_top_bcubed_f1 == pytest.approx(0.983, abs=0.005)
    assert result.nodes_with_cross_branch_assembly == 7
    assert result.mean_cross_branch_assembly_rate > 0.5
    # Every column of every reported assembly was explained by a committed set.
    # This is not §7.2's floor of 0.125 and must not be quoted as it: that floor
    # is measured over the survey's own reading with a value committed for every
    # set it returns, and this is measured over the columns the winning
    # candidate tuple produced.
    assert result.mean_unaccounted_column_rate == pytest.approx(0.0, abs=1e-9)


def test_the_assembly_oracle_refuses_to_write_a_branch_cascade() -> None:
    """`branch_rules` is a per-branch question and assembly is not one.

    `tools/branch_recoverability.py` offers `BRANCH_ORACLES` for this reason. The
    refusal is asserted rather than left to a `KeyError` further in, because the
    two flags spell the same word and the failure would otherwise surface as a
    wrong number rather than as an error.
    """
    module = _oracle_module()
    assert module.BRANCH_ORACLES == ("context_free", "contextual")
    assert module.ORACLES == ("context_free", "contextual", "assembly")
    with pytest.raises(SystemExit) as refused:
        module.branch_rules("child", {}, {}, {}, "assembly")
    assert "per-branch" in str(refused.value)


def test_column_targets_prices_an_unattested_emission_like_a_miss() -> None:
    """The cost model, pinned as the mistake it was written to stop making.

    Priced below a miss, the assignment DP scatters a short gold form across
    whichever columns come first. On Polynesian `1237` WHERE that put `f e a`
    into the three columns of Tongan's `ʔ i +` prefix — three unattested
    emissions at 1/3 the price of leaving one gold segment uncovered — and every
    one of those columns then voted for a phoneme it has no relation to.
    """
    module = _oracle_module()
    columns = [frozenset({"ʔ"}), frozenset({"i"}), frozenset({"+"}),
               frozenset({"f"}), frozenset({"eː"})]
    cost, assignment = module.column_targets(columns, ("f", "e", "a"))
    assert assignment[3] == "f", (
        "the column both children show `f` in must be the one that emits `f`"
    )
    assert assignment[0] is None and assignment[1] is None
    # Two prices paid: one unattested emission and one uncovered gold segment.
    assert cost == 2


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


# ---------------------------------------------------------------------------
# The instrument and the implementation must see the same columns
# ---------------------------------------------------------------------------


def _assembly_module():
    """Import `tools/assembly_ceiling.py`, the same way as its sibling above."""
    tools = str(REPO_ROOT / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    spec = importlib.util.spec_from_file_location(
        "assembly_ceiling", REPO_ROOT / "tools" / "assembly_ceiling.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _harness_rows(pairs, aligner):
    """`assembly_ceiling.align_rows`, run through the aligner the harness uses.

    `pairs` is `[(node_id, segments), ...]` in the order the instrument feeds
    its matrix. A node contributing two forms contributes two members of one
    variety, which is two rows of that matrix. Column *structure* is compared,
    not row order, so the two need not agree about which row is which.
    """
    from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm

    if len(pairs) == 1:
        return [tuple(pairs[0][1])]
    by_node: dict[str, list[tuple[str, ...]]] = {}
    for node_id, segments in pairs:
        by_node.setdefault(node_id, []).append(segments)
    if len(by_node) < 2:
        # The aligner refuses a single variety; nothing can read a
        # correspondence out of one node anyway.
        return [tuple(segments) for _node, segments in pairs]
    result = aligner.align_multiple(
        [
            LanguageLexicon(
                variety_id=node_id,
                name=node_id,
                forms=tuple(
                    LexicalForm(
                        form_id=f"{node_id}:{index}",
                        variety_id=node_id,
                        concept_id="c",
                        segments=segments,
                    )
                    for index, segments in enumerate(forms)
                ),
            )
            for node_id, forms in by_node.items()
        ]
    )
    if not result.alignments:
        return [tuple(segments) for _node, segments in pairs]
    return [
        member.aligned_segments
        for member in result.alignments[0].members
        if not member.is_anchor
    ]


def test_the_ceiling_instrument_and_the_harness_align_the_same_columns(
    payload: WorkbenchPayload,
) -> None:
    """The check whose absence let a silent regression live in the shipped path.

    `tools/assembly_ceiling.py` has its own `align_rows` and the harness runs
    `LingPyAligner.align_multiple`, and that separation is deliberate: an
    instrument that imported the thing it measures would agree with it by
    construction. The cost of the separation is that the two can drift with
    nothing saying so — which is exactly what happened. The instrument aligned
    `form.segments`, the harness aligned `phonetic_segments`, and so the
    instrument reported a node-local ceiling of 44/46 for an implementation that
    could only reach 38/46. No test in the suite could see it, because no test
    compared them.

    Measured on this fixture at the time of writing: **322 of 322** node-concept
    pairs identical, against **225 of 322** while boundaries were stripped, and
    the node-local ceiling 44/46 under both aligners rather than 44 against 38.

    This asserts the *property*, not those numbers — that every column the
    instrument sees is a column the harness sees. A ceiling measured on one
    alignment does not bound an implementation running another, whatever the two
    happen to score.
    """
    from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
    from cognate_reconstruction.tree import (
        assign_node_ids,
        parse_newick,
        postorder_groups,
    )

    instrument = _assembly_module()
    aligner = LingPyAligner()
    root = parse_newick(payload.newick)
    node_ids = assign_node_ids(root)
    binding = _oracle_module().select_binding(
        payload, node_ids[id(root)], None
    )
    gold: dict[str, tuple[tuple[str, ...], ...]] = {}
    for form in binding.forms:
        previous = gold.get(form.concept_id, ())
        if form.segments not in previous:
            gold[form.concept_id] = (*previous, form.segments)

    forms_by_node: dict[str, dict[str, list[tuple[str, ...]]]] = {}
    for lexicon in payload.lexicons:
        per_concept = forms_by_node.setdefault(lexicon.variety_id, {})
        for form in lexicon.forms:
            per_concept.setdefault(form.concept_id, []).append(form.segments)

    rows_by_node = {
        leaf.label: forms_by_node.get(leaf.label, {}) for leaf in root.get_leaves()
    }
    compared = 0
    reached_instrument: list[str] = []
    reached_harness: list[str] = []
    for children, parent in postorder_groups(root):
        parent_id = node_ids[id(parent)]
        child_ids = [node_ids[id(child)] for child in children]
        produced: dict[str, list[tuple[str, ...]]] = {}
        for concept_id in sorted(
            {c for child_id in child_ids for c in rows_by_node[child_id]}
        ):
            pairs = [
                (child_id, segments)
                for child_id in child_ids
                for segments in rows_by_node[child_id].get(concept_id, ())
            ]
            rows = [segments for _child, segments in pairs]
            columns = instrument.column_options(instrument.align_rows(rows))
            harness_columns = instrument.column_options(
                _harness_rows(pairs, aligner)
            )
            compared += 1
            assert columns == harness_columns, (
                f"the ceiling instrument and the harness's aligner disagree "
                f"about concept {concept_id!r} at {parent_id!r}. A ceiling "
                f"measured on one alignment does not bound an implementation "
                f"running the other."
            )
            targets = gold.get(concept_id)
            if targets is None:
                produced[concept_id] = [max(rows, key=len)]
                continue
            produced[concept_id] = [instrument.reaches(columns, targets)[1]]
            if parent_id == binding.node_id:
                if produced[concept_id][0] in targets:
                    reached_instrument.append(concept_id)
                if instrument.reaches(harness_columns, targets)[1] in targets:
                    reached_harness.append(concept_id)
        rows_by_node[parent_id] = produced

    assert compared > 300, "the walk stopped early and proved almost nothing"
    # And the number the design quotes is a number the implementation can reach.
    assert reached_instrument == reached_harness
    assert len(reached_instrument) == 44
