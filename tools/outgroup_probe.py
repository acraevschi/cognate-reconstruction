"""Can out-group evidence break the ties the scorer currently breaks blindly?

`tools/tiebreak_probe.py` shows *that* equal-mass candidates are separated by
segment order. This asks whether the harness already holds evidence that would
separate them on cladistic grounds instead.

The argument is standard and does not need a theory of sound change: if a node's
children disagree and one variant also appears outside the node, that variant was
present before the node split, so it is the retention. The evidence is already in
the payload — every leaf outside the subtree — and the deterministic scorer has
never looked at it.

Four policies are scored against the withheld gold, plus the ceiling:

    alphabetical         what the scorer does today (TIE_BREAK_POLICY)
    outgroup-daughters   nearest candidate by mean edit distance to every
                         out-group daughter
    outgroup-clades      a candidate's distinctive segments, counted once per
                         out-group clade, presence only
    morphs+clades        morph count first, then outgroup-clades
    ceiling              ties where gold is one of the two candidates at all

**Two ways to get this wrong, both measured here on purpose.**

`outgroup-daughters` averages over daughters and therefore degenerates into a
majority vote — it loses exactly the glottal-stop cases, because most Polynesian
daughters lost the segment. Topology is what keeps the cladistic argument
distinct from counting languages, so support is counted per clade.

Counting *absence* as out-group evidence scores worse than alphabetical order. A
candidate lacking a segment has no distinctive segments to attest, and an empty
set is trivially "supported"; presence shows a segment predates the split, while
absence is equally consistent with independent loss. That asymmetry is the whole
argument, and under it retention-over-loss falls out of cladistics rather than
having to be assumed separately.

Morphology still has to be handled first. Material added at a morph boundary —
reduplication, a fossilized preposition, a compound — is innovation however well
attested its segments are elsewhere, so it must never be read as a retention.

Note what the probe cannot do: **the root has no out-group.** The technique is
unavailable exactly where the reported reconstruction is produced.

Usage:
    python tools/outgroup_probe.py <benchmark-input.json> [--node tongic]
    python tools/outgroup_probe.py polynesian --json
"""

from __future__ import annotations

import argparse
from pathlib import Path

import _bootstrap  # noqa: F401  (bind to this checkout; see module)

from cognate_reconstruction.schemas.beam import ConceptCandidateDistribution
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.schemas.lexicon import LanguageLexicon
from cognate_reconstruction.schemas.rules import ReconstructionRule
from cognate_reconstruction.traversal.beam import decided_by_tie_break, make_leaf_beam
from cognate_reconstruction.traversal.reconstructor import RuleBasedReconstructor
from cognate_reconstruction.tree import assign_node_ids, parse_newick, postorder_groups

from oracle_ceiling import build_rules, oracle_map  # noqa: E402  (same directory)

Segments = tuple[str, ...]

BOUNDARIES = frozenset({"+", "-"})


def morph_count(segments: Segments) -> int:
    return sum(token in BOUNDARIES for token in segments)


def edit_distance(left: Segments, right: Segments) -> float:
    """Normalized Levenshtein distance over tokens, not characters."""
    previous = list(range(len(right) + 1))
    for index, token in enumerate(left, 1):
        current = [index]
        for offset, other in enumerate(right, 1):
            current.append(
                min(
                    previous[offset] + 1,
                    current[offset - 1] + 1,
                    previous[offset - 1] + (token != other),
                )
            )
        previous = current
    return previous[-1] / max(len(left), len(right), 1)


def outgroup_clades(
    root, node, node_ids, *, granularity: str = "sibling"
) -> tuple[tuple[str, ...], ...]:
    """Subtrees disjoint from `node`, as tuples of their leaf IDs.

    Walking from the node to the root, every sibling subtree at every ancestor is
    one out-group clade. Counting support per clade rather than per daughter is
    what stops the cladistic argument collapsing into a majority vote; treating
    near and distant clades alike is a simplification, and a nearer sibling is
    the stronger witness.

    `granularity` decides how finely a sibling is broken up. Under `"subclade"`
    each sibling contributes its own children as separate witnesses, which reads
    as more evidence but structurally collapses into daughter-counting: on the
    Polynesian benchmark five of seven nodes end up with exactly one clade per
    daughter, `marquesic` yielding all eight non-marquesic daughters. That said,
    it does not change the score here — both settings total 23 and 25 — so the
    collapse is a reason to prefer `"sibling"` on principle, not a measured cost.
    Run both when adding a family; a divergence is the interesting case.
    """
    parents = {}

    def walk(current):
        for child in current.children:
            parents[id(child)] = current
            walk(child)

    walk(root)
    inside = {id(leaf) for leaf in node.get_leaves()}
    clades: list[tuple[str, ...]] = []
    cursor = node
    while id(cursor) in parents:
        parent = parents[id(cursor)]
        for sibling in parent.children:
            if sibling is cursor:
                continue
            groups = (
                sibling.children
                if granularity == "subclade" and sibling.children
                else (sibling,)
            )
            for group in groups:
                leaves = tuple(
                    node_ids[id(leaf)]
                    for leaf in group.get_leaves()
                    if id(leaf) not in inside
                )
                if leaves:
                    clades.append(leaves)
        cursor = parent
    return tuple(clades)


def clade_support(
    concept_id: str,
    distinctive: frozenset[str],
    clades: tuple[tuple[str, ...], ...],
    forms: dict[str, dict[str, Segments]],
) -> int:
    """Out-group clades attesting every distinctive segment. None, no evidence.

    The empty set is deliberately scored zero rather than as trivially attested:
    "this candidate lacks a segment" is not out-group evidence for anything.
    """
    real = {token for token in distinctive if token not in BOUNDARIES}
    if not real:
        return 0
    return sum(
        any(
            concept_id in forms[leaf] and real <= set(forms[leaf][concept_id])
            for leaf in clade
        )
        for clade in clades
    )


def choose(
    policy: str,
    distribution: ConceptCandidateDistribution,
    clades: tuple[tuple[str, ...], ...],
    forms: dict[str, dict[str, Segments]],
) -> Segments:
    first = distribution.candidates[0].segments
    second = distribution.candidates[1].segments
    concept_id = distribution.concept_id
    if policy == "alphabetical":
        return min(first, second)
    if policy == "outgroup-daughters":
        leaves = [leaf for clade in clades for leaf in clade]
        def nearness(candidate: Segments) -> float:
            distances = [
                edit_distance(candidate, forms[leaf][concept_id])
                for leaf in leaves
                if concept_id in forms[leaf]
            ]
            return sum(distances) / len(distances) if distances else 1.0
        return first if nearness(first) <= nearness(second) else second
    support_first = clade_support(
        concept_id, frozenset(first) - frozenset(second), clades, forms
    )
    support_second = clade_support(
        concept_id, frozenset(second) - frozenset(first), clades, forms
    )
    cladistic = first if support_first >= support_second else second
    if policy == "outgroup-clades":
        return cladistic
    if policy == "morphs+clades":
        if morph_count(first) != morph_count(second):
            return first if morph_count(first) < morph_count(second) else second
        return cladistic
    raise ValueError(f"unknown policy {policy!r}")


POLICIES = ("alphabetical", "outgroup-daughters", "outgroup-clades", "morphs+clades")


def run(
    payload_path: Path,
    focus: str | None,
    granularity: str,
    *,
    as_json: bool = False,
) -> int:
    payload = WorkbenchPayload.model_validate_json(
        payload_path.read_text(encoding="utf-8")
    )
    targets = [
        binding
        for binding in payload.historical_form_bindings
        if binding.role.value == "target"
    ]
    if not targets:
        print("input has no historical target binding to score against")
        return 1
    gold: dict[str, Segments] = {
        form.concept_id: form.segments for form in targets[0].forms
    }

    root = parse_newick(payload.newick)
    node_ids = assign_node_ids(root)
    lexicons: dict[str, LanguageLexicon] = {
        lexicon.variety_id: lexicon for lexicon in payload.lexicons
    }
    # Schema-validated forms throughout: segments stay token tuples, never the
    # space-joined strings a display helper would produce.
    forms: dict[str, dict[str, Segments]] = {
        variety_id: {form.concept_id: form.segments for form in lexicon.forms}
        for variety_id, lexicon in lexicons.items()
    }

    beams = {}
    branch_forms: dict[str, dict[str, Segments]] = {}
    for leaf in root.get_leaves():
        beams[id(leaf)] = make_leaf_beam(lexicons[leaf.label], beam_width=5)
        branch_forms[leaf.label] = dict(forms[leaf.label])

    reconstructor = RuleBasedReconstructor(beam_width=5)
    # Rows are collected rather than printed as they are computed, so the text
    # report and the `--json` object are two renderings of one measurement
    # instead of two traversals that could drift.
    rows: list[dict] = []
    if not as_json:
        print(f"benchmark: {payload_path}")
        print(f"measuring: {_bootstrap.loaded_package_path()}")
        print(f"out-group granularity: {granularity}\n")
        header = f"{'node':<20}{'ties':>5}{'ceiling':>9}"
        for policy in POLICIES:
            header += f"{policy:>21}"
        print(header)

    totals = {policy: 0 for policy in POLICIES}
    total_ties = total_ceiling = 0
    for children, parent in postorder_groups(root):
        parent_id = node_ids[id(parent)]
        rules: list[ReconstructionRule] = []
        for child in children:
            child_id = node_ids[id(child)]
            rules.extend(build_rules(child_id, oracle_map(branch_forms[child_id], gold)))
        step = reconstructor.reconstruct(
            parent_id,
            tuple(beams[id(child)] for child in children),
            rules=rules,
        )
        beams[id(parent)] = step.output_beam
        branch_forms[parent_id] = {
            distribution.concept_id: distribution.candidates[0].segments
            for distribution in step.output_beam.distributions
        }

        clades = outgroup_clades(root, parent, node_ids, granularity=granularity)
        ties = [
            distribution
            for distribution in step.output_beam.distributions
            if decided_by_tie_break(distribution)
            and distribution.concept_id in gold
        ]
        if not ties:
            continue
        ceiling = sum(
            gold[d.concept_id] in (d.candidates[0].segments, d.candidates[1].segments)
            for d in ties
        )
        total_ties += len(ties)
        total_ceiling += ceiling
        row = f"{parent_id:<20}{len(ties):>5}{ceiling:>9}"
        record = {
            "node_id": parent_id,
            "ties": len(ties),
            "ceiling": ceiling,
            "outgroup_clades": len(clades),
            "policies": {},
        }
        for policy in POLICIES:
            if not clades:
                row += f"{'no out-group':>21}"
                record["policies"][policy] = None
                continue
            hits = sum(
                choose(policy, d, clades, forms) == gold[d.concept_id] for d in ties
            )
            totals[policy] += hits
            row += f"{hits:>21}"
            record["policies"][policy] = hits
        rows.append(record)
        if not as_json:
            print(row)
            if focus == parent_id:
                _print_detail(ties, clades, forms, gold)

    if as_json:
        _bootstrap.emit_json(
            {
                **_bootstrap.measurement_envelope(payload_path),
                "measurement": "outgroup_probe",
                "granularity": granularity,
                "total_ties": total_ties,
                "ceiling": total_ceiling,
                "policy_totals": dict(totals),
                "nodes": rows,
                "note": (
                    "A node with no out-group is the root: nothing lies "
                    "outside it, so the technique is unavailable exactly where "
                    "the reported reconstruction is made. A run in which "
                    "outgroup-daughters and outgroup-clades converge has "
                    "probably reintroduced the majority vote."
                ),
            }
        )
        return 0
    footer = f"{'total':<20}{total_ties:>5}{total_ceiling:>9}"
    for policy in POLICIES:
        footer += f"{totals[policy]:>21}"
    print("-" * len(footer))
    print(footer)
    print(
        "\nA node with no out-group is the root: nothing lies outside it, so the\n"
        "technique is unavailable exactly where the reported reconstruction is made."
    )
    return 0


def _print_detail(ties, clades, forms, gold) -> None:
    print(f"\n  ties at this node, winnable ones marked; {len(clades)} out-group clades")
    print(
        f"  {'concept':<9}{'candidate A':<18}{'candidate B':<18}"
        f"{'gold':<18}{'support':>9}"
    )
    for distribution in ties:
        first = distribution.candidates[0].segments
        second = distribution.candidates[1].segments
        target = gold[distribution.concept_id]
        support_first = clade_support(
            distribution.concept_id, frozenset(first) - frozenset(second), clades, forms
        )
        support_second = clade_support(
            distribution.concept_id, frozenset(second) - frozenset(first), clades, forms
        )
        mark = "A" if target == first else "B" if target == second else "-"
        print(
            f"  {distribution.concept_id:<9}{' '.join(first):<18}"
            f"{' '.join(second):<18}{' '.join(target):<18}"
            f"{support_first}/{len(clades)} v {support_second}/{len(clades)}"
            f"   gold={mark}"
        )
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        help="A prepared benchmark payload, or the name of a defined benchmark.",
    )
    parser.add_argument(
        "--node",
        help="Print every tie at this node, with the out-group support behind each.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit one machine-readable object, including the measured source.",
    )
    parser.add_argument(
        "--granularity",
        choices=("sibling", "subclade"),
        default="sibling",
        help=(
            "How finely to split each out-group sibling. 'subclade' looks like "
            "more evidence and degenerates into daughter-counting at deep nodes."
        ),
    )
    args = parser.parse_args()
    return run(
        _bootstrap.resolve_benchmark(args.input),
        args.node,
        args.granularity,
        as_json=args.json,
    )


if __name__ == "__main__":
    raise SystemExit(main())
