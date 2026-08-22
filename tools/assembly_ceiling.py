"""Can a proto-form be *assembled* from its daughters' aligned columns?

The companion measure to `oracle_ceiling.py`, and the two answer different
questions. The oracle asks what a perfect *rule writer* could reach when a
proto-form has to be one branch's whole output, selected from a beam. This asks
what a perfect *assembler* could reach when each column of the multiple
alignment contributes one proto-phoneme, or nothing — the shape
`docs/proto_inventory_design.md` proposes.

That makes reachability decidable rather than searchable: it is a subsequence
problem over the columns, so this script computes an exact bound in one pass and
needs no beam, no model, and no rules.

Three variants, and only two of them say anything:

    flat         align every daughter at the scored node and assemble once
    node-local   assemble at each internal node from its children, bottom-up
    free-choice  any proto-phoneme, not only one some daughter attests

**`node-local` is the honest number**, because assembly would happen at each
node over that node's active children, exactly as rules do now. `flat` is not an
upper bound on it and is not meant as one: a single n-way alignment over ten
daughters is a worse view of some concepts than the smaller alignments the
bottom-up pass makes, and on Polynesian node-local comes out one concept *above*
flat for exactly that reason. `free-choice` is computed to be dismissed: the
alignment essentially always has enough columns, so the bound is vacuous, and it
is printed only so nobody re-derives it and believes it.

The reflex-restricted variants are a **lower** bound on what assembly can reach,
because a proto-phoneme genuinely need not be one of its reflexes — Polynesian
`1028` YAWN reconstructs a `w` no daughter shows. A miss here is therefore no
more a structural limit than an oracle miss is.

Usage:
    python tools/assembly_ceiling.py <benchmark-input.json>
    python tools/assembly_ceiling.py polynesian --json
    python tools/assembly_ceiling.py runs/benchmarks/synthetic_hard.json --gold-node east
"""

from __future__ import annotations

import argparse
import collections
from pathlib import Path

import _bootstrap  # noqa: F401  (bind to this checkout; see module)

from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.tree import assign_node_ids, parse_newick, postorder_groups

from oracle_ceiling import select_binding  # noqa: E402  (same directory)

INFINITE = float("inf")


def align_rows(sequences: list[tuple[str, ...]]) -> list[tuple[str | None, ...]]:
    """SCA-align n token sequences, returning every row with None for a gap.

    Deliberately the same call `oracle_ceiling.align_pair` makes, over
    `form.segments` rather than `phonetic_segments`: gold proto-forms carry
    morphological boundaries — `ʔ a h u + a f i` — and a column that could never
    contribute a `+` would make those concepts unreachable by construction
    rather than by measurement.
    """
    from lingpy import Multiple

    if len(sequences) == 1:
        return [tuple(sequences[0])]
    multiple = Multiple([list(sequence) for sequence in sequences])
    multiple.prog_align(model="sca", mode="global")
    return [
        tuple(None if token == "-" else str(token) for token in row)
        for row in multiple.alm_matrix
    ]


def column_options(rows: list[tuple[str | None, ...]]) -> list[frozenset[str]]:
    """What each aligned column could contribute: the segments some row attests."""
    if not rows:
        return []
    return [
        frozenset(token for token in column if token is not None)
        for column in zip(*rows, strict=True)
    ]


def assemble(
    columns: list[frozenset[str]], gold: tuple[str, ...]
) -> tuple[int, tuple[str, ...]]:
    """The assembly closest to `gold`, and how many edits away it is.

    Each column emits one of its attested segments or nothing, left to right, so
    the reachable forms are exactly the assemblies of that choice. Zero edits
    means gold is reachable; the returned form is what a single-candidate
    assembler would carry upward when it is not.

    Ties are broken toward the *longer* assembly, because a node that cannot
    reach gold still hands its material to the node above, and discarded
    material cannot be recovered there.
    """
    width, length = len(columns), len(gold)
    # Score is (edits, -segments emitted), so `min` prefers fewer edits and then
    # the longer assembly.
    best = [[(INFINITE, 0)] * (length + 1) for _ in range(width + 1)]
    back: list[list[tuple[int, int, str | None] | None]] = [
        [None] * (length + 1) for _ in range(width + 1)
    ]
    best[0][0] = (0, 0)

    def offer(row, column, score, origin):
        if score < best[row][column]:
            best[row][column] = score
            back[row][column] = origin

    for index in range(width + 1):
        for consumed in range(length + 1):
            edits, emitted = best[index][consumed]
            if edits == INFINITE:
                continue
            if index < width:
                options = columns[index]
                # Emit nothing from this column. Emitting a segment gold does
                # not want is never better than this, so it is not a transition.
                offer(index + 1, consumed, (edits, emitted), (index, consumed, None))
                if consumed < length:
                    if gold[consumed] in options:
                        offer(
                            index + 1,
                            consumed + 1,
                            (edits, emitted - 1),
                            (index, consumed, gold[consumed]),
                        )
                    elif options:
                        offer(
                            index + 1,
                            consumed + 1,
                            (edits + 1, emitted - 1),
                            (index, consumed, min(options)),
                        )
            if consumed < length:
                # A gold segment no column produced.
                offer(index, consumed + 1, (edits + 1, emitted), (index, consumed, ""))

    tokens: list[str] = []
    position = (width, length)
    while position != (0, 0):
        origin = back[position[0]][position[1]]
        if origin is None:
            break
        previous_index, previous_consumed, token = origin
        if token:
            tokens.append(token)
        position = (previous_index, previous_consumed)
    tokens.reverse()
    return best[width][length][0], tuple(tokens)


def reaches(columns: list[frozenset[str]], targets: tuple[tuple[str, ...], ...]):
    """The nearest assembly over every gold alternative, exactly as scoring does."""
    return min(
        (assemble(columns, target) for target in targets),
        key=lambda item: item[0],
    )


def _by_concept(payload: WorkbenchPayload) -> dict[str, dict[str, list]]:
    per_node: dict[str, dict[str, list]] = collections.defaultdict(
        lambda: collections.defaultdict(list)
    )
    for lexicon in payload.lexicons:
        for form in lexicon.forms:
            per_node[lexicon.variety_id][form.concept_id].append(form.segments)
    return per_node


def measure(
    payload: WorkbenchPayload, gold_node_id: str | None = None
) -> dict:
    root = parse_newick(payload.newick)
    node_ids = assign_node_ids(root)
    root_id = node_ids[id(root)]
    binding = select_binding(payload, root_id, gold_node_id)
    alternatives: dict[str, list[tuple[str, ...]]] = collections.defaultdict(list)
    for form in binding.forms:
        alternatives[form.concept_id].append(form.segments)
    gold = {
        concept_id: tuple(dict.fromkeys(forms))
        for concept_id, forms in alternatives.items()
    }

    forms_by_node = _by_concept(payload)
    descendants = {root_id: [leaf.label for leaf in root.get_leaves()]}
    for children, parent in postorder_groups(root):
        for child in children:
            descendants[node_ids[id(child)]] = [
                leaf.label for leaf in child.get_leaves()
            ]

    # --- flat: every daughter of the scored node in one alignment -----------
    flat_reachable, flat_missed, free_reachable, free_missed = 0, [], 0, []
    for concept_id, targets in sorted(gold.items()):
        rows = [
            segments
            for leaf in descendants[binding.node_id]
            for segments in forms_by_node.get(leaf, {}).get(concept_id, ())
        ]
        if not rows:
            flat_missed.append(concept_id)
            free_missed.append(concept_id)
            continue
        columns = column_options(align_rows(rows))
        if reaches(columns, targets)[0] == 0:
            flat_reachable += 1
        else:
            flat_missed.append(concept_id)
        if any(len(target) <= len(columns) for target in targets):
            free_reachable += 1
        else:
            free_missed.append(concept_id)

    # --- node-local: bottom-up, one assembled candidate per node ------------
    rows_by_node = {
        leaf.label: forms_by_node.get(leaf.label, {}) for leaf in root.get_leaves()
    }
    node_local_reachable, node_local_missed = 0, []
    for children, parent in postorder_groups(root):
        parent_id = node_ids[id(parent)]
        child_ids = [node_ids[id(child)] for child in children]
        concepts = sorted(
            {
                concept_id
                for child_id in child_ids
                for concept_id in rows_by_node[child_id]
            }
        )
        produced: dict[str, list[tuple[str, ...]]] = {}
        for concept_id in concepts:
            rows = [
                segments
                for child_id in child_ids
                for segments in rows_by_node[child_id].get(concept_id, ())
            ]
            targets = gold.get(concept_id)
            columns = column_options(align_rows(rows))
            if targets is None:
                # No gold here to aim at; carry the longest child form upward so
                # a concept scored only at a higher node is not thrown away.
                produced[concept_id] = [max(rows, key=len)]
                continue
            produced[concept_id] = [reaches(columns, targets)[1]]
        rows_by_node[parent_id] = produced
        if parent_id == binding.node_id:
            for concept_id, targets in sorted(gold.items()):
                candidate = produced.get(concept_id, [()])[0]
                if candidate in targets:
                    node_local_reachable += 1
                else:
                    node_local_missed.append(concept_id)

    total = len(gold)
    return {
        "root_node_id": root_id,
        "gold_node_id": binding.node_id,
        "concepts_scored": total,
        "flat_reachable": flat_reachable,
        "node_local_reachable": node_local_reachable,
        "free_choice_reachable": free_reachable,
        "flat_unreachable_concepts": flat_missed,
        "node_local_unreachable_concepts": sorted(node_local_missed),
        "free_choice_unreachable_concepts": free_missed,
        "note": (
            "A column may contribute only a segment some daughter attests, so "
            "flat and node-local are lower bounds: a proto-phoneme need not be "
            "one of its reflexes. free_choice is vacuous and is reported only "
            "so it is not re-derived and believed."
        ),
    }


def run(payload_path: Path, gold_node_id: str | None, *, as_json: bool) -> int:
    payload = WorkbenchPayload.model_validate_json(
        payload_path.read_text(encoding="utf-8")
    )
    result = measure(payload, gold_node_id)
    if as_json:
        _bootstrap.emit_json(
            {
                **_bootstrap.measurement_envelope(payload_path),
                "measurement": "assembly_ceiling",
                **result,
            }
        )
        return 0
    total = result["concepts_scored"]
    print(f"benchmark: {payload_path}")
    print(f"measuring: {_bootstrap.loaded_package_path()}")
    print(
        f"root node: {result['root_node_id']}   "
        f"gold node: {result['gold_node_id']}   concepts: {total}"
    )
    print()
    for key, label in (
        ("flat_reachable", "flat        align every daughter at once"),
        ("node_local_reachable", "node-local  assemble bottom-up, one per node"),
        ("free_choice_reachable", "free-choice any phoneme (vacuous; see below)"),
    ):
        value = result[key]
        share = value / total if total else 0.0
        print(f"  {label:<46} {value:>3}/{total}  {share:6.1%}")
    print()
    print("node-local is the honest number: assembly happens at each node over")
    print("that node's active children, exactly as rules do now. free-choice is")
    print("printed to be dismissed — the alignment always has enough columns.")
    print()
    for key, label in (
        ("flat_unreachable_concepts", "flat cannot reach"),
        ("node_local_unreachable_concepts", "node-local cannot reach"),
    ):
        concepts = result[key]
        print(f"  {label:<26} {', '.join(concepts) if concepts else '(none)'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        help="A prepared benchmark payload, or the name of a defined benchmark.",
    )
    parser.add_argument(
        "--gold-node",
        default=None,
        help=(
            "Which node's gold binding to assemble against. Defaults to the "
            "tree root's; required where the root carries none."
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
        args.gold_node,
        as_json=args.json,
    )


if __name__ == "__main__":
    raise SystemExit(main())
