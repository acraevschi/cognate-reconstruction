"""Oracle ceiling for the deterministic reconstruction layer.

Gives every branch the best child-to-parent segment map that the real DSL can
express, computed against the withheld gold proto-forms, then runs the real
`RuleBasedReconstructor` bottom-up. This measures the harness, not the model:
it is the accuracy a flawless hypothesis manager would obtain.

Two numbers matter, and it is the gap between them that this exists to watch:

    top   -- the parent form the beam actually reports
    beam  -- whether the correct form is anywhere in the beam at all

A large gap means the combination/selection step is discarding answers the
system already computed.

`measure()` is importable by the regression test in `tests/workbench`, so the
number the suite pins and the number this script prints come from one
implementation. The script stays the runnable form for the full benchmark.

Usage:
    python tools/oracle_ceiling.py <benchmark-input.json> [--beam-width 5]
    python tools/oracle_ceiling.py polynesian --json
"""

from __future__ import annotations

import argparse
import collections
import sys
from dataclasses import dataclass, field
from pathlib import Path

import _bootstrap  # noqa: F401  (bind to this checkout; see module)

from cognate_reconstruction.evaluation.metrics import compare_to_nearest
from cognate_reconstruction.rules.parser import parse_rule, NoOpRuleError
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.schemas.rules import ReconstructionRule
from cognate_reconstruction.traversal.beam import make_leaf_beam
from cognate_reconstruction.traversal.reconstructor import RuleBasedReconstructor
from cognate_reconstruction.tree import assign_node_ids, parse_newick, postorder_groups


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


def order_rules(mapping: dict[str, str | None]) -> list[tuple[str, str | None]]:
    """Order x>y rules so no rule consumes another rule's output.

    Rules are an ordered cascade, so a rule mapping k>t placed before one
    mapping t>s would turn every original k into s. A rule whose target is
    another rule's replacement must therefore run first. Cycles (a true swap)
    cannot be expressed without a scratch symbol and are dropped.
    """
    changing = {
        source: target for source, target in mapping.items() if source != target
    }
    edges = {
        source: {
            other
            for other, other_target in changing.items()
            if other_target == source and other != source
        }
        for source in changing
    }
    ordered: list[tuple[str, str | None]] = []
    remaining = dict(changing)
    while remaining:
        free = [
            source
            for source in remaining
            if not (edges[source] & remaining.keys())
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
            ordered.append((source, remaining.pop(source)))
    return ordered


BOUNDARIES = {"+", "-"}


def build_rules(child_id: str, mapping: dict[str, str]) -> list[ReconstructionRule]:
    # Morphological boundaries may constrain a context but cannot be targets or
    # replacements, so the oracle simply cannot touch them. That is a real limit
    # of the DSL and is left visible rather than worked around.
    mapping = {
        source: target
        for source, target in mapping.items()
        if source not in BOUNDARIES and target not in BOUNDARIES
    }
    rules = []
    for source, target in order_rules(mapping):
        text = f"{source} > {target if target else 'Ø'}"
        try:
            parsed = parse_rule(text)
        except (NoOpRuleError, ValueError):
            continue
        rules.append(
            ReconstructionRule(
                rule=parsed, source_child_ids=(child_id,), confidence=1.0
            )
        )
    return rules


@dataclass(frozen=True)
class OracleMeasurement:
    """What a flawless hypothesis manager would score under this architecture.

    Exact counts and graded distances side by side. The graded numbers matter
    for the same reason they matter for a live run: a top-1 miss that is one
    segment away and a top-1 miss that is unrelated are different failures, and
    the exact counters cannot tell them apart.
    """

    root_node_id: str
    beam_width: int
    evaluated: int
    top_exact: int
    beam_exact: int
    mean_top_normalized_edit_distance: float
    mean_beam_best_normalized_edit_distance: float
    mean_top_bcubed_f1: float
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
        }


def measure(payload: WorkbenchPayload, beam_width: int = 5) -> OracleMeasurement:
    """Run the real reconstructor with a perfect rule set on every branch."""
    bindings = [
        binding
        for binding in payload.historical_form_bindings
        if binding.role.value == "target"
    ]
    if not bindings:
        raise SystemExit("input has no historical target binding to score against")
    binding = bindings[0]
    gold = {form.concept_id: form.segments for form in binding.forms}

    root = parse_newick(payload.newick)
    node_ids = assign_node_ids(root)
    lexicons = {lexicon.variety_id: lexicon for lexicon in payload.lexicons}

    beams = {}
    forms_by_node: dict[str, dict[str, tuple[str, ...]]] = {}
    for leaf in root.get_leaves():
        beams[id(leaf)] = make_leaf_beam(lexicons[leaf.label], beam_width=beam_width)
        forms_by_node[leaf.label] = {
            form.concept_id: form.segments for form in lexicons[leaf.label].forms
        }

    reconstructor = RuleBasedReconstructor(beam_width=beam_width)
    root_id = node_ids[id(root)]
    for children, parent in postorder_groups(root):
        parent_id = node_ids[id(parent)]
        child_ids = [node_ids[id(child)] for child in children]
        rules: list[ReconstructionRule] = []
        for child_id in child_ids:
            rules.extend(build_rules(child_id, oracle_map(forms_by_node[child_id], gold)))
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

    top_hits = beam_hits = evaluated = 0
    misses = []
    top_neds: list[float] = []
    beam_neds: list[float] = []
    bcubed_scores: list[float] = []
    for distribution in beams[id(root)].distributions:
        target = gold.get(distribution.concept_id)
        if target is None:
            continue
        evaluated += 1
        candidates = [candidate.segments for candidate in distribution.candidates]
        if candidates[0] == target:
            top_hits += 1
        else:
            misses.append((distribution.concept_id, candidates[0], target))
        if target in candidates:
            beam_hits += 1
        top = compare_to_nearest(candidates[0], (target,))
        top_neds.append(top.normalized_edit_distance)
        bcubed_scores.append(top.bcubed_f1)
        beam_neds.append(
            min(
                compare_to_nearest(segments, (target,)).normalized_edit_distance
                for segments in candidates
            )
        )
    return OracleMeasurement(
        root_node_id=root_id,
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
        misses=tuple(misses),
    )


def run(payload_path: Path, beam_width: int, *, as_json: bool = False) -> int:
    payload = WorkbenchPayload.model_validate_json(
        payload_path.read_text(encoding="utf-8")
    )
    result = measure(payload, beam_width)
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
        f"root node: {result.root_node_id}   beam width: {beam_width}   "
        f"concepts: {result.evaluated}"
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
        "--json",
        action="store_true",
        help="Emit one machine-readable object, including the measured source.",
    )
    args = parser.parse_args()
    return run(
        _bootstrap.resolve_benchmark(args.input),
        args.beam_width,
        as_json=args.json,
    )


if __name__ == "__main__":
    raise SystemExit(main())
