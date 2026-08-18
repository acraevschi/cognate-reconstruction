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

Usage:
    python tools/oracle_ceiling.py <benchmark-input.json> [--beam-width 5]
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

import _bootstrap  # noqa: F401  (bind to this checkout; see module)

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


def run(payload_path: Path, beam_width: int) -> int:
    payload = WorkbenchPayload.model_validate_json(
        payload_path.read_text(encoding="utf-8")
    )
    bindings = [
        binding
        for binding in payload.historical_form_bindings
        if binding.role.value == "target"
    ]
    if not bindings:
        print("input has no historical target binding to score against")
        return 1
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

    print(f"benchmark: {payload_path}")
    # State which source produced the number. A figure quoted from this tool is
    # meaningless without it: the script and the package it measures can come
    # from different checkouts. See tools/_bootstrap.py.
    print(f"measuring: {_bootstrap.loaded_package_path()}")
    print(f"root node: {root_id}   beam width: {beam_width}   concepts: {evaluated}")
    print()
    print(f"  top  exact  {top_hits:>3}/{evaluated}  {top_hits / evaluated:6.1%}   "
          "what the beam reports")
    print(f"  beam exact  {beam_hits:>3}/{evaluated}  {beam_hits / evaluated:6.1%}   "
          "correct form present anywhere in the beam")
    print(f"  selection gap                {(beam_hits - top_hits) / evaluated:6.1%}   "
          "computed but not chosen")
    print()
    print("first 12 misses (reported | gold):")
    for concept_id, got, want in misses[:12]:
        print(f"  {concept_id:<10} {' '.join(got):<22} | {' '.join(want)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--beam-width", type=int, default=5)
    args = parser.parse_args()
    return run(args.input, args.beam_width)


if __name__ == "__main__":
    raise SystemExit(main())
