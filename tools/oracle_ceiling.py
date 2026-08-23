"""Oracle ceiling for the deterministic reconstruction layer.

Gives every branch the best child-to-parent rule set that a chosen oracle can
write, computed against the withheld gold proto-forms, then runs the real
`RuleBasedReconstructor` bottom-up. This measures the harness, not the model:
it is the accuracy a flawless hypothesis manager would obtain.

Two numbers matter, and it is the gap between them that this exists to watch:

    top   -- the parent form the beam actually reports
    beam  -- whether the correct form is anywhere in the beam at all

A large gap means the combination/selection step is discarding answers the
system already computed.

**Two oracles, and they are not interchangeable.** `--oracle context_free` is
the original: one target per source segment, globally, which is strictly weaker
than the DSL. Every baseline recorded in `docs/analysis_tools.md` and every
figure pinned by the regression test was measured with it, so it keeps its
identity and stays the default. `--oracle contextual` searches the DSL's own
environment vocabulary as well, and is >= the context-free measure per branch by
construction. It lands *beside* the first, never in place of it: silently
redefining the default would make every recorded before/after uncomparable,
which is the failure `tools/_bootstrap.py` exists to prevent at one remove.

Neither is a target. An oracle bounds the architecture and a miss under one is
not a structural limit -- see the note on the contextual builder below.

`measure()` is importable by the regression test in `tests/workbench`, so the
number the suite pins and the number this script prints come from one
implementation. The script stays the runnable form for the full benchmark.

Usage:
    python tools/oracle_ceiling.py <benchmark-input.json> [--beam-width 5]
    python tools/oracle_ceiling.py polynesian --json
    python tools/oracle_ceiling.py polynesian --oracle contextual
    python tools/oracle_ceiling.py synthetic_hard --gold-node east
"""

from __future__ import annotations

import argparse
import collections
import sys
from dataclasses import dataclass, field
from pathlib import Path

import _bootstrap  # noqa: F401  (bind to this checkout; see module)

from cognate_reconstruction.evaluation.metrics import compare_to_nearest
from cognate_reconstruction.rules.engine import RuleEngine
from cognate_reconstruction.rules.parser import parse_rule, NoOpRuleError
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.schemas.lexicon import LexicalForm
from cognate_reconstruction.schemas.rules import ReconstructionRule
from cognate_reconstruction.traversal.beam import make_leaf_beam
from cognate_reconstruction.traversal.reconstructor import RuleBasedReconstructor
from cognate_reconstruction.tree import assign_node_ids, parse_newick, postorder_groups

CONTEXT_FREE = "context_free"
CONTEXTUAL = "contextual"
ORACLES = (CONTEXT_FREE, CONTEXTUAL)


def align_pair(left: tuple[str, ...], right: tuple[str, ...]):
    """SCA-align two token sequences, returning both rows with None for gaps."""
    from lingpy import Multiple

    multiple = Multiple([list(left), list(right)])
    multiple.prog_align(model="sca", mode="global")
    rows = [
        [None if token == "-" else str(token) for token in row]
        for row in multiple.alm_matrix
    ]
    return rows[0], rows[1]


def oracle_map(forms: dict[str, tuple[str, ...]], gold: dict[str, tuple[str, ...]]):
    """Best single-valued segment map from these forms onto the gold forms."""
    counts: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter
    )
    for concept_id, segments in forms.items():
        if concept_id not in gold:
            continue
        source_row, gold_row = align_pair(segments, gold[concept_id])
        for source, target in zip(source_row, gold_row, strict=True):
            if source is not None:
                counts[source][target] += 1
    return {
        source: counter.most_common(1)[0][0] for source, counter in counts.items()
    }


def _order_sources(produced: dict[str, set[str | None]]) -> list[str]:
    """Order rule sources so no source's output is consumed by a later rule.

    The general form of `order_rules`, taking every replacement a source's rules
    emit rather than a single one, because the contextual oracle writes several
    rules per source. A source is free to be emitted once nothing it produces is
    still a pending source.
    """
    remaining = dict(produced)
    ordered: list[str] = []
    while remaining:
        free = [
            source
            for source, targets in remaining.items()
            if not ((targets - {source}) & remaining.keys())
        ]
        if not free:
            # Cycle: emit the rest in a stable order and let the caller see the
            # damage rather than silently pretending the oracle was clean.
            print(
                f"  [cycle] unorderable rules dropped: {sorted(remaining)}",
                file=sys.stderr,
            )
            break
        for source in sorted(free):
            ordered.append(source)
            remaining.pop(source)
    return ordered


def order_rules(mapping: dict[str, str | None]) -> list[tuple[str, str | None]]:
    """Order x>y rules so no rule consumes another rule's output.

    Rules are an ordered cascade, so a rule mapping k>t placed before one
    mapping t>s would turn every original k into s. A rule whose target is
    another rule's replacement must therefore run first. Cycles (a true swap)
    cannot be expressed without a scratch symbol and are dropped.

    So the documented example orders the chain shift from its far end:

        order_rules({"k": "t", "t": "s"})  ->  [("t", "s"), ("k", "t")]

    This ran backwards from `febf03b` to 2026-08-22 -- it emitted a source once
    nothing mapped *into* it, which is the other direction -- and cost Hawaiian
    seven of 46 forms, because `*t > k` and `*k > ʔ` make its oracle map a chain
    shift and the reversed order turned `ʔ a k a` into `t a t a` rather than
    gold `k a t a`. `tests/workbench/test_oracle_ceiling_regression.py` now pins
    this docstring's own example.
    """
    changing = {
        source: target for source, target in mapping.items() if source != target
    }
    order = _order_sources({source: {target} for source, target in changing.items()})
    return [(source, changing[source]) for source in order]


BOUNDARIES = {"+", "-"}


def _render(source: str, target: str | None, environment: "Environment | None") -> str:
    change = f"{source} > {target if target else 'Ø'}"
    if environment is None:
        return change
    left = " ".join(part for part in (
        "#" if environment.word_initial else "", environment.left or "",
    ) if part)
    right = " ".join(part for part in (
        environment.right or "", "#" if environment.word_final else "",
    ) if part)
    return f"{change} / {left}_{right}"


def _rule(child_id: str, text: str) -> ReconstructionRule | None:
    try:
        parsed = parse_rule(text)
    except (NoOpRuleError, ValueError):
        return None
    return ReconstructionRule(
        rule=parsed, source_child_ids=(child_id,), confidence=1.0
    )


def _writable(mapping: dict[str, str | None]) -> dict[str, str | None]:
    # Morphological boundaries may constrain a context but cannot be targets or
    # replacements, so the oracle simply cannot touch them. That is a real limit
    # of the DSL and is left visible rather than worked around.
    return {
        source: target
        for source, target in mapping.items()
        if source not in BOUNDARIES and target not in BOUNDARIES
    }


def build_rules(child_id: str, mapping: dict[str, str]) -> list[ReconstructionRule]:
    """The context-free cascade: one rule per changed source segment."""
    rules = []
    for source, target in order_rules(_writable(mapping)):
        rule = _rule(child_id, _render(source, target, None))
        if rule is not None:
            rules.append(rule)
    return rules


# --------------------------------------------------------------------------
# The context-sensitive oracle.
#
# A rule writer as strong as the rule language, which the context-free one is
# not. It exists to keep "the architecture cannot reach this form" from being
# asserted on the strength of a measure that was never able to say it.
#
# It is also emphatically not a plausible analysis: on Polynesian it writes
# several times as many rules as the context-free oracle, many conditioned on a
# single word. That is what an oracle is for -- it bounds the architecture and
# is not a target. Quoting its top-1 as "what a good model should get" is the
# same category error as quoting a context-free miss as a structural limit.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Environment:
    """One environment the DSL can spell, over single tokens and word edges."""

    left: str | None = None
    right: str | None = None
    word_initial: bool = False
    word_final: bool = False

    @property
    def parts(self) -> int:
        return sum(
            (self.left is not None, self.right is not None,
             self.word_initial, self.word_final)
        )


@dataclass(frozen=True)
class Occurrence:
    """One aligned column, with the child-side neighbours a rule could name."""

    target: str | None
    left: str | None
    right: str | None
    word_initial: bool
    word_final: bool

    def matches(self, environment: Environment) -> bool:
        if environment.word_initial and not self.word_initial:
            return False
        if environment.word_final and not self.word_final:
            return False
        if environment.left is not None and self.left != environment.left:
            return False
        if environment.right is not None and self.right != environment.right:
            return False
        return True


def observe(
    forms: dict[str, tuple[str, ...]], gold: dict[str, tuple[str, ...]]
) -> dict[str, list[Occurrence]]:
    """Every source segment's aligned gold target, with its child-side context.

    Neighbours are read from the child form itself, not from the aligned row:
    the rule engine matches contexts against the form it is applying to, and a
    gap in the alignment is not a token there.
    """
    occurrences: dict[str, list[Occurrence]] = collections.defaultdict(list)
    for concept_id, segments in forms.items():
        if concept_id not in gold:
            continue
        source_row, gold_row = align_pair(segments, gold[concept_id])
        index = -1
        for source, target in zip(source_row, gold_row, strict=True):
            if source is None:
                continue
            index += 1
            occurrences[source].append(
                Occurrence(
                    target=target,
                    left=segments[index - 1] if index > 0 else None,
                    right=(
                        segments[index + 1]
                        if index + 1 < len(segments)
                        else None
                    ),
                    word_initial=index == 0,
                    word_final=index + 1 == len(segments),
                )
            )
    return dict(occurrences)


def candidate_environments(occurrences: list[Occurrence]) -> list[Environment]:
    """The bounded space this oracle searches: what the DSL can actually spell.

    Word-initial, word-final, a single left token, a single right token, and the
    four two-part combinations of those. Multi-token contexts are expressible
    and deliberately not searched -- the space is bounded so the oracle stays a
    measurement rather than a search problem.
    """
    lefts = sorted({item.left for item in occurrences if item.left is not None})
    rights = sorted({item.right for item in occurrences if item.right is not None})
    environments = [
        Environment(word_initial=True),
        Environment(word_final=True),
        *(Environment(left=left) for left in lefts),
        *(Environment(right=right) for right in rights),
        Environment(word_initial=True, word_final=True),
        *(Environment(word_initial=True, right=right) for right in rights),
        *(Environment(left=left, word_final=True) for left in lefts),
        *(
            Environment(left=left, right=right)
            for left in lefts
            for right in rights
        ),
    ]
    return environments


def conditioned_rules(
    source: str, occurrences: list[Occurrence]
) -> tuple[list[tuple[str | None, Environment]], str | None]:
    """Conditioned splits of one source segment, plus its unconditioned default.

    An environment is usable only if it is *pure*: every occurrence it matches
    shares one gold target. A mixed environment would be a rule that is wrong
    somewhere it fires, and the point of an oracle is to be right wherever it
    can be, not to guess.
    """
    default = collections.Counter(
        item.target for item in occurrences
    ).most_common(1)[0][0]
    exceptions = [item for item in occurrences if item.target != default]
    if not exceptions:
        return [], default

    usable: list[tuple[int, int, str, str | None, Environment]] = []
    for environment in candidate_environments(occurrences):
        matched = [item for item in occurrences if item.matches(environment)]
        if not matched:
            continue
        targets = {item.target for item in matched}
        if len(targets) != 1:
            continue
        target = targets.pop()
        if target == default:
            continue
        usable.append(
            (-len(matched), -environment.parts, _render(source, target, environment),
             target, environment)
        )

    selected: list[tuple[str | None, Environment]] = []
    covered: set[int] = set()
    outstanding = {id(item) for item in exceptions}
    for _, _, _, target, environment in sorted(usable, key=lambda item: item[:3]):
        matched = {
            id(item) for item in exceptions if item.matches(environment)
        }
        if not matched - covered:
            continue
        selected.append((target, environment))
        covered |= matched
        if covered >= outstanding:
            break
    # Most specific first: every selected environment is pure over the observed
    # data, but two of them can still overlap on a token the cascade produces
    # later, and the narrower statement is the one that should win there.
    selected.sort(key=lambda item: -item[1].parts)
    return selected, default


def build_contextual_rules(
    child_id: str, forms: dict[str, tuple[str, ...]], gold: dict[str, tuple[str, ...]]
) -> list[ReconstructionRule]:
    """A cascade using the DSL's environments, ordered by the same feeding rule."""
    observations = observe(forms, gold)
    conditioned: dict[str, list[tuple[str | None, Environment]]] = {}
    defaults: dict[str, str | None] = {}
    for source, occurrences in observations.items():
        if source in BOUNDARIES:
            continue
        splits, default = conditioned_rules(source, occurrences)
        # A boundary cannot be a replacement, though it may still condition one.
        splits = [item for item in splits if item[0] not in BOUNDARIES]
        if default in BOUNDARIES:
            default = source
        conditioned[source] = splits
        defaults[source] = default

    produced = {
        source: {defaults[source], *(target for target, _ in conditioned[source])}
        for source in defaults
        if defaults[source] != source or conditioned[source]
    }
    rules: list[ReconstructionRule] = []
    for source in _order_sources(produced):
        for target, environment in conditioned[source]:
            rule = _rule(child_id, _render(source, target, environment))
            if rule is not None:
                rules.append(rule)
        rule = _rule(child_id, _render(source, defaults[source], None))
        if rule is not None:
            rules.append(rule)
    return rules


def _apply(rules: list[ReconstructionRule], forms: dict[str, tuple[str, ...]]):
    lexical = [
        LexicalForm(
            form_id=f"probe:{concept_id}",
            variety_id="probe",
            concept_id=concept_id,
            segments=segments,
        )
        for concept_id, segments in sorted(forms.items())
    ]
    produced, _ = RuleEngine().apply_rules(
        [rule.rule for rule in rules], lexical
    )
    return {form.concept_id: form.segments for form in produced}


def _exact(
    produced: dict[str, tuple[str, ...]],
    gold_alternatives: dict[str, tuple[tuple[str, ...], ...]],
) -> int:
    return sum(
        1
        for concept_id, segments in produced.items()
        if segments in gold_alternatives.get(concept_id, ())
    )


def branch_rules(
    child_id: str,
    forms: dict[str, tuple[str, ...]],
    gold: dict[str, tuple[str, ...]],
    gold_alternatives: dict[str, tuple[tuple[str, ...], ...]],
    oracle: str,
) -> tuple[list[ReconstructionRule], bool]:
    """This branch's cascade, and whether the contextual builder fell back.

    The contextual oracle is >= the context-free one per branch *by
    construction* and not by argument: where its extra rules would score fewer
    exact forms on this branch, the context-free cascade is used instead. A
    measure that claimed to be a superset and was not would be worse than no
    measure.
    """
    context_free = build_rules(child_id, oracle_map(forms, gold))
    if oracle == CONTEXT_FREE:
        return context_free, False
    contextual = build_contextual_rules(child_id, forms, gold)
    if _exact(_apply(contextual, forms), gold_alternatives) < _exact(
        _apply(context_free, forms), gold_alternatives
    ):
        return context_free, True
    return contextual, False


@dataclass(frozen=True)
class OracleMeasurement:
    """What a flawless hypothesis manager would score under this architecture.

    Exact counts and graded distances side by side. The graded numbers matter
    for the same reason they matter for a live run: a top-1 miss that is one
    segment away and a top-1 miss that is unrelated are different failures, and
    the exact counters cannot tell them apart.
    """

    root_node_id: str
    gold_node_id: str
    oracle: str
    beam_width: int
    evaluated: int
    top_exact: int
    beam_exact: int
    mean_top_normalized_edit_distance: float
    mean_beam_best_normalized_edit_distance: float
    mean_top_bcubed_f1: float
    rules_written: int = 0
    branches: int = 0
    fallback_branches: int = 0
    misses: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = field(
        default=()
    )

    @property
    def top_exact_rate(self) -> float:
        return self.top_exact / self.evaluated if self.evaluated else 0.0

    @property
    def beam_exact_rate(self) -> float:
        return self.beam_exact / self.evaluated if self.evaluated else 0.0

    @property
    def selection_gap(self) -> float:
        """Beam-exact minus top-1: answers computed and then not reported."""
        return self.beam_exact_rate - self.top_exact_rate

    @property
    def normalized_edit_distance_selection_gap(self) -> float:
        return (
            self.mean_top_normalized_edit_distance
            - self.mean_beam_best_normalized_edit_distance
        )

    def as_dict(self) -> dict:
        return {
            "root_node_id": self.root_node_id,
            # Which node's gold produced this number. `measuring:` already stops
            # a figure being quoted from the wrong checkout; nothing used to stop
            # one being quoted from the wrong node, and on a multi-gold family
            # that is exactly what happened.
            "gold_node_id": self.gold_node_id,
            "oracle": self.oracle,
            "beam_width": self.beam_width,
            "evaluated_concepts": self.evaluated,
            "top_exact": self.top_exact,
            "beam_exact": self.beam_exact,
            "top_exact_rate": self.top_exact_rate,
            "beam_exact_rate": self.beam_exact_rate,
            "selection_gap": self.selection_gap,
            "mean_top_normalized_edit_distance": (
                self.mean_top_normalized_edit_distance
            ),
            "mean_beam_best_normalized_edit_distance": (
                self.mean_beam_best_normalized_edit_distance
            ),
            "normalized_edit_distance_selection_gap": (
                self.normalized_edit_distance_selection_gap
            ),
            "mean_top_bcubed_f1": self.mean_top_bcubed_f1,
            "rules_written": self.rules_written,
            "branches": self.branches,
            "fallback_branches": self.fallback_branches,
        }


def select_binding(payload: WorkbenchPayload, root_id: str, requested: str | None):
    """The gold binding to score against, defaulting to the tree root's own.

    `bindings[0]` used to be taken unconditionally. On a family carrying gold at
    several nodes that is whichever binding was written first -- `east` on
    `synthetic_hard`, not `proto` -- so the root beam was scored against a
    non-root gold and published under the root's name. Defaulting to the root's
    binding, and refusing to guess where the root has none, is the whole fix.
    """
    bindings = [
        binding
        for binding in payload.historical_form_bindings
        if binding.role.value == "target"
    ]
    if not bindings:
        raise SystemExit("input has no historical target binding to score against")
    by_node = {binding.node_id: binding for binding in bindings}
    if requested is not None:
        if requested not in by_node:
            raise SystemExit(
                f"no target binding at {requested!r}; this input has gold at "
                f"{', '.join(sorted(by_node))}"
            )
        return by_node[requested]
    if root_id in by_node:
        return by_node[root_id]
    raise SystemExit(
        f"the root {root_id!r} carries no gold binding, and scoring a beam "
        f"against another node's gold is a measurement with the wrong label. "
        f"Pass --gold-node from: {', '.join(sorted(by_node))}"
    )


def measure(
    payload: WorkbenchPayload,
    beam_width: int = 5,
    *,
    oracle: str = CONTEXT_FREE,
    gold_node_id: str | None = None,
) -> OracleMeasurement:
    """Run the real reconstructor with a perfect rule set on every branch."""
    if oracle not in ORACLES:
        raise SystemExit(f"unknown oracle {oracle!r}; choose from {ORACLES}")
    root = parse_newick(payload.newick)
    node_ids = assign_node_ids(root)
    root_id = node_ids[id(root)]
    binding = select_binding(payload, root_id, gold_node_id)

    # Two views of the same gold, and the split is deliberate. Rule construction
    # needs one aligned target per concept and a segment map is single-valued,
    # so it keeps the original last-one-wins reading. *Evaluation* honours every
    # alternative, exactly as `HistoricalTargetEvaluation` does through
    # `compare_to_nearest`: on Polynesian `1443` WALK carries four gold forms and
    # scoring against only the last of them is a defect of this script, not a
    # property of the harness.
    gold = {form.concept_id: form.segments for form in binding.forms}
    alternatives: dict[str, list[tuple[str, ...]]] = collections.defaultdict(list)
    for form in binding.forms:
        alternatives[form.concept_id].append(form.segments)
    gold_alternatives = {
        # Deduplicated in order, exactly as `agent/service.py` does, so the two
        # readings of the same binding cannot differ.
        concept_id: tuple(dict.fromkeys(forms))
        for concept_id, forms in alternatives.items()
    }

    lexicons = {lexicon.variety_id: lexicon for lexicon in payload.lexicons}
    beams = {}
    forms_by_node: dict[str, dict[str, tuple[str, ...]]] = {}
    for leaf in root.get_leaves():
        beams[id(leaf)] = make_leaf_beam(lexicons[leaf.label], beam_width=beam_width)
        forms_by_node[leaf.label] = {
            form.concept_id: form.segments for form in lexicons[leaf.label].forms
        }

    reconstructor = RuleBasedReconstructor(beam_width=beam_width)
    scored_node = None
    rules_written = branches = fallbacks = 0
    for children, parent in postorder_groups(root):
        parent_id = node_ids[id(parent)]
        child_ids = [node_ids[id(child)] for child in children]
        rules: list[ReconstructionRule] = []
        for child_id in child_ids:
            built, fell_back = branch_rules(
                child_id, forms_by_node[child_id], gold, gold_alternatives, oracle
            )
            rules.extend(built)
            rules_written += len(built)
            branches += 1
            fallbacks += fell_back
        step = reconstructor.reconstruct(
            parent_id,
            tuple(beams[id(child)] for child in children),
            rules=rules,
        )
        beams[id(parent)] = step.output_beam
        forms_by_node[parent_id] = {
            distribution.concept_id: distribution.candidates[0].segments
            for distribution in step.output_beam.distributions
        }
        if parent_id == binding.node_id:
            scored_node = beams[id(parent)]
    if scored_node is None:
        raise SystemExit(
            f"gold node {binding.node_id!r} is not an internal node of this tree"
        )

    top_hits = beam_hits = evaluated = 0
    misses = []
    top_neds: list[float] = []
    beam_neds: list[float] = []
    bcubed_scores: list[float] = []
    for distribution in scored_node.distributions:
        targets = gold_alternatives.get(distribution.concept_id)
        if targets is None:
            continue
        evaluated += 1
        candidates = [candidate.segments for candidate in distribution.candidates]
        top = compare_to_nearest(candidates[0], targets)
        if candidates[0] in targets:
            top_hits += 1
        else:
            # The alternative the score was computed against, not the last one
            # written down: printing a different gold from the one that graded
            # the form is how the multi-gold defect stayed invisible.
            misses.append(
                (distribution.concept_id, candidates[0], top.nearest_target)
            )
        if any(target in candidates for target in targets):
            beam_hits += 1
        top_neds.append(top.normalized_edit_distance)
        bcubed_scores.append(top.bcubed_f1)
        beam_neds.append(
            min(
                compare_to_nearest(segments, targets).normalized_edit_distance
                for segments in candidates
            )
        )
    return OracleMeasurement(
        root_node_id=root_id,
        gold_node_id=binding.node_id,
        oracle=oracle,
        beam_width=beam_width,
        evaluated=evaluated,
        top_exact=top_hits,
        beam_exact=beam_hits,
        mean_top_normalized_edit_distance=(
            sum(top_neds) / len(top_neds) if top_neds else 0.0
        ),
        mean_beam_best_normalized_edit_distance=(
            sum(beam_neds) / len(beam_neds) if beam_neds else 0.0
        ),
        mean_top_bcubed_f1=(
            sum(bcubed_scores) / len(bcubed_scores) if bcubed_scores else 0.0
        ),
        rules_written=rules_written,
        branches=branches,
        fallback_branches=fallbacks,
        misses=tuple(misses),
    )


def run(
    payload_path: Path,
    beam_width: int,
    *,
    as_json: bool = False,
    oracle: str = CONTEXT_FREE,
    gold_node_id: str | None = None,
) -> int:
    payload = WorkbenchPayload.model_validate_json(
        payload_path.read_text(encoding="utf-8")
    )
    result = measure(
        payload, beam_width, oracle=oracle, gold_node_id=gold_node_id
    )
    if as_json:
        _bootstrap.emit_json(
            {
                **_bootstrap.measurement_envelope(payload_path),
                "measurement": "oracle_ceiling",
                **result.as_dict(),
            }
        )
        return 0
    print(f"benchmark: {payload_path}")
    # State which source produced the number. A figure quoted from this tool is
    # meaningless without it: the script and the package it measures can come
    # from different checkouts. See tools/_bootstrap.py.
    print(f"measuring: {_bootstrap.loaded_package_path()}")
    print(
        f"root node: {result.root_node_id}   gold node: {result.gold_node_id}   "
        f"oracle: {result.oracle}"
    )
    print(
        f"beam width: {beam_width}   concepts: {result.evaluated}   "
        f"rules: {result.rules_written} over {result.branches} branches"
        + (
            f"   ({result.fallback_branches} fell back to context-free)"
            if result.fallback_branches
            else ""
        )
    )
    print()
    print(
        f"  top  exact  {result.top_exact:>3}/{result.evaluated}  "
        f"{result.top_exact_rate:6.1%}   what the beam reports"
    )
    print(
        f"  beam exact  {result.beam_exact:>3}/{result.evaluated}  "
        f"{result.beam_exact_rate:6.1%}   correct form present anywhere in the beam"
    )
    print(
        f"  selection gap                {result.selection_gap:6.1%}   "
        "computed but not chosen"
    )
    print()
    print("  graded, against the same gold (lower is better for NED):")
    print(
        f"    top  NED   {result.mean_top_normalized_edit_distance:6.3f}   "
        "mean normalized edit distance of the reported form"
    )
    print(
        f"    beam NED   {result.mean_beam_best_normalized_edit_distance:6.3f}   "
        "best any retained candidate reached"
    )
    print(
        f"    NED gap    {result.normalized_edit_distance_selection_gap:6.3f}   "
        "distance recoverable by choosing better"
    )
    print(
        f"    B-Cubed F1 {result.mean_top_bcubed_f1:6.3f}   "
        "structural agreement, higher is better"
    )
    print()
    print("first 12 misses (reported | gold):")
    for concept_id, got, want in result.misses[:12]:
        print(f"  {concept_id:<10} {' '.join(got):<22} | {' '.join(want)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        help="A prepared benchmark payload, or the name of a defined benchmark.",
    )
    parser.add_argument("--beam-width", type=int, default=5)
    parser.add_argument(
        "--oracle",
        choices=ORACLES,
        default=CONTEXT_FREE,
        help=(
            "context_free is the measure every recorded baseline used and is "
            "the default for that reason; contextual searches the DSL's own "
            "environments and lands beside it, never in place of it."
        ),
    )
    parser.add_argument(
        "--gold-node",
        default=None,
        help=(
            "Which node's gold binding to score against. Defaults to the tree "
            "root's; required where the root carries none."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit one machine-readable object, including the measured source.",
    )
    args = parser.parse_args()
    return run(
        _bootstrap.resolve_benchmark(args.input),
        args.beam_width,
        as_json=args.json,
        oracle=args.oracle,
        gold_node_id=args.gold_node,
    )


if __name__ == "__main__":
    raise SystemExit(main())
