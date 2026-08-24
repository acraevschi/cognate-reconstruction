"""How much of the gold proto-form can one branch reach at all?

The DSL has no empty-target insertion, so a branch that deleted a segment can
never restore it however good the model is. This measures that hard limit per
branch, and separates three cases per concept:

  * some single branch reaches the gold form on its own;
  * no branch reaches it, but some branch still retains every gold segment,
    so the answer needs evidence mixed across branches;
  * every branch has deleted something, so no branch-local rule set can win.

**`--method` decides what "reaches" means, and the two are not interchangeable.**
`map` applies a best child-to-parent segment map by dictionary lookup and is the
original measure — every figure recorded before 2026-08-23 is `map`. `cascade`
builds the branch's real ordered rule set through `tools/oracle_ceiling.py` and
runs it through `RuleEngine`, which is what the harness would actually do, and
with `--oracle contextual` it is as strong as the rule language. The difference
is method, not disagreement: the cascade reaches concepts the map does not, and
the middle class — the concepts a change to the combination model has to move —
shrinks accordingly. Report them together; neither should be quoted alone.

The third class is deliberately method-independent: "some branch still retains
every gold segment" is a property of the aligned forms, so `map` and `cascade`
partition the same 46 concepts and only the boundary between the first two moves.

Usage:
    python tools/branch_recoverability.py <benchmark-input.json>
    python tools/branch_recoverability.py polynesian --json
    python tools/branch_recoverability.py polynesian --method cascade --oracle contextual
"""

from __future__ import annotations

import argparse
import collections

import _bootstrap  # noqa: F401  (bind to this checkout; see module)

from cognate_reconstruction.schemas.ingestion import WorkbenchPayload

# From the sibling script rather than re-implemented, deliberately and unlike the
# relationship these scripts have with the package: the point of `--method
# cascade` is to ask *the oracle's own* question of each branch, so a second
# cascade builder here would measure something else and quietly call it the same
# thing. `_apply` is private to `oracle_ceiling` and is imported anyway, because
# the alternative is a duplicate three-line `RuleEngine` call that could drift.
from oracle_ceiling import (  # noqa: E402  (same directory)
    CONTEXT_FREE,
    BRANCH_ORACLES,
    _apply,
    align_pair,
    branch_rules,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        help="A prepared benchmark payload, or the name of a defined benchmark.",
    )
    parser.add_argument(
        "--method",
        choices=("map", "cascade"),
        default="map",
        help=(
            "How a branch is given its best shot at the gold form: a segment "
            "map applied by lookup (the original measure, and every figure "
            "recorded before 2026-08-23), or the branch's real ordered cascade "
            "run through RuleEngine."
        ),
    )
    parser.add_argument(
        "--oracle",
        choices=BRANCH_ORACLES,
        default=CONTEXT_FREE,
        help=(
            "Which rule writer builds the cascade. Only meaningful with "
            "--method cascade; 'contextual' searches the DSL's own environment "
            "vocabulary and is >= 'context_free' per branch by construction."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit one machine-readable object, including the measured source.",
    )
    args = parser.parse_args()
    if args.method == "map" and args.oracle != CONTEXT_FREE:
        parser.error("--oracle only applies to --method cascade")

    input_path = _bootstrap.resolve_benchmark(args.input)
    payload = WorkbenchPayload.model_validate_json(
        input_path.read_text(encoding="utf-8")
    )
    binding = next(
        item
        for item in payload.historical_form_bindings
        if item.role.value == "target"
    )
    gold = {form.concept_id: form.segments for form in binding.forms}
    # Gold alternatives, as `oracle_ceiling` scores them: a concept may bind
    # several proto-forms and reaching any of them is reaching it.
    gold_alternatives: dict[str, tuple[tuple[str, ...], ...]] = {}
    for form in binding.forms:
        previous = gold_alternatives.get(form.concept_id, ())
        if form.segments not in previous:
            gold_alternatives[form.concept_id] = (*previous, form.segments)
    lexicons = {item.variety_id: item for item in payload.lexicons}

    rows = collections.defaultdict(dict)
    counts = collections.defaultdict(collections.Counter)
    for variety_id, lexicon in lexicons.items():
        for form in lexicon.forms:
            if form.concept_id not in gold:
                continue
            source, target = align_pair(form.segments, gold[form.concept_id])
            rows[form.concept_id][variety_id] = (source, target)
            for left, right in zip(source, target, strict=True):
                if left is not None:
                    counts[variety_id][left, right] += 1

    best = {}
    for variety_id, counter in counts.items():
        grouped = collections.defaultdict(collections.Counter)
        for (left, right), total in counter.items():
            grouped[left][right] += total
        best[variety_id] = {
            left: values.most_common(1)[0][0] for left, values in grouped.items()
        }

    # Under `--method cascade`, what each branch actually produces when its own
    # oracle rule set is run over its own forms — the real ordered cascade
    # through `RuleEngine`, which is what the harness would do, rather than a
    # dictionary lookup that is strictly weaker than the rule language.
    produced_by_branch: dict[str, dict[str, tuple[str, ...]]] = {}
    fell_back: list[str] = []
    if args.method == "cascade":
        for variety_id, lexicon in lexicons.items():
            forms = {
                form.concept_id: form.segments
                for form in lexicon.forms
                if form.concept_id in gold
            }
            rules, fallback = branch_rules(
                variety_id, forms, gold, gold_alternatives, args.oracle
            )
            if fallback:
                fell_back.append(variety_id)
            produced_by_branch[variety_id] = _apply(rules, forms)

    deleted = collections.Counter()
    one_branch = mixed = impossible = 0
    # Which concepts land in each class, not only how many. The middle class is
    # the concrete prediction a change to the combination model has to move:
    # these are the forms no single branch can produce, so they are exactly the
    # ones per-correspondence-set assembly is supposed to make reachable.
    by_class: dict[str, list[str]] = {
        "single_branch": [],
        "needs_mixing": [],
        "unreachable": [],
    }
    for concept_id, per_variety in rows.items():
        reached = False
        retains = False
        for variety_id, (source, target) in per_variety.items():
            intact = all(
                left is not None
                for left, right in zip(source, target, strict=True)
                if right is not None
            )
            if not intact:
                deleted[variety_id] += 1
            else:
                retains = True
            if args.method == "cascade":
                predicted = produced_by_branch[variety_id].get(concept_id)
                if predicted in gold_alternatives.get(concept_id, ()):
                    reached = True
                continue
            predicted = tuple(
                value
                for value in (best[variety_id].get(seg, seg) for seg in source)
                if value is not None
            )
            if predicted == gold[concept_id]:
                reached = True
        if reached:
            one_branch += 1
            by_class["single_branch"].append(concept_id)
        elif retains:
            mixed += 1
            by_class["needs_mixing"].append(concept_id)
        else:
            impossible += 1
            by_class["unreachable"].append(concept_id)
    for concepts in by_class.values():
        concepts.sort()

    total = len(rows)
    if args.json:
        _bootstrap.emit_json(
            {
                **_bootstrap.measurement_envelope(input_path),
                "measurement": "branch_recoverability",
                "method": args.method,
                "oracle": args.oracle if args.method == "cascade" else None,
                "contextual_fallback_branches": sorted(fell_back),
                "concepts_scored": total,
                "reachable_from_a_single_branch": one_branch,
                "needs_evidence_mixed_across_branches": mixed,
                "unreachable_from_every_branch": impossible,
                "concepts_needing_evidence_mixed_across_branches": by_class[
                    "needs_mixing"
                ],
                "concepts_unreachable_from_every_branch": by_class["unreachable"],
                "deletion_losses_by_branch": {
                    variety_id: number for variety_id, number in deleted.most_common()
                },
                "note": (
                    "The DSL has no empty-target insertion, so a branch that "
                    "deleted a segment can never restore it. The middle number "
                    "bounds what any amount of better selection can achieve. "
                    "It depends on --method: a segment map is strictly weaker "
                    "than the rule language, so the map figure over-counts the "
                    "middle class."
                ),
            }
        )
        return
    print(f"measuring: {_bootstrap.loaded_package_path()}")
    method = args.method
    if method == "cascade":
        method = f"cascade, --oracle {args.oracle}"
        if fell_back:
            method += f" ({len(fell_back)} branch(es) fell back to context-free)"
    print(f"concepts scored: {total}   method: {method}\n")
    print(f"  reachable from a single branch          {one_branch:>3}")
    print(f"  needs evidence mixed across branches    {mixed:>3}"
          f"   {', '.join(by_class['needs_mixing'])}")
    print(f"  every branch deleted a gold segment     {impossible:>3}"
          f"   {', '.join(by_class['unreachable'])}\n")
    print("concepts where a branch deleted a gold segment (that branch can never be right):")
    for variety_id, number in deleted.most_common():
        print(f"  {variety_id.split(':')[-1]:<18} {number:>3}/{total}")


if __name__ == "__main__":
    main()
