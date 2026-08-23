"""The correspondence-set inventory the harness has no tool for.

A comparative linguist works from correspondence *sets*: the n-tuple of aligned
segments across every daughter, and how often it recurs. The harness exposes
alignments in batches instead, so recurrence is never observable. This builds
the whole inventory in one pass over the existing aligner and prints it by
support, which is the shape `summarize_correspondences` should return.

Usage:
    python tools/correspondence_inventory.py <benchmark-input.json> [--min-support 2] [--limit 30]
    python tools/correspondence_inventory.py polynesian --json
    python tools/correspondence_inventory.py polynesian --reading reported

`--reading` decides what one node contributes to an alignment when it has more
than one form for a cognate set. `all` is the historical default and every
recorded baseline used it. `reported` keeps one form per node per (concept,
cognate set), which is what `summarize_correspondences` now does so that the set
IDs it hands a model are columns the assembler can reproduce from one candidate
per child. Both are legitimate; they are kept apart rather than merged so this
script stays the independent second implementation the tool is checked against.
"""

from __future__ import annotations

import argparse
import json

import _bootstrap  # noqa: F401  (bind to this checkout; see module)

from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload


def one_reading_per_node(lexicons):
    """Keep one form per node per (concept, cognate set), the first listed.

    Deliberately re-implemented here rather than imported. The whole point of
    this script is to be a second implementation the typed tool surface can be
    checked against, and importing the thing under test would make the check
    vacuous.
    """
    reduced = []
    for lexicon in lexicons:
        seen = set()
        forms = []
        for form in lexicon.forms:
            key = (form.concept_id, form.cognate_set_id)
            if key in seen:
                continue
            seen.add(key)
            forms.append(form)
        reduced.append(lexicon.model_copy(update={"forms": tuple(forms)}))
    return tuple(reduced)


def build(payload: WorkbenchPayload, *, reading: str = "all"):
    node_ids = [lexicon.variety_id for lexicon in payload.lexicons]
    lexicons = (
        one_reading_per_node(payload.lexicons)
        if reading == "reported"
        else payload.lexicons
    )
    alignment_map = LingPyAligner().align_multiple(lexicons)
    sets: dict[tuple, dict] = {}
    for alignment in alignment_map.alignments:
        rows = {
            member.variety_id: member.aligned_segments
            for member in alignment.members
            if not member.is_anchor
        }
        if len(rows) < 2:
            continue
        width = len(next(iter(rows.values())))
        for column in range(width):
            key = tuple(
                rows[node][column] if node in rows else None for node in node_ids
            )
            if all(segment is None for segment in key):
                continue
            entry = sets.setdefault(key, {"support": 0, "concepts": []})
            entry["support"] += 1
            if alignment.concept_id not in entry["concepts"]:
                entry["concepts"].append(alignment.concept_id)
    return node_ids, alignment_map, sets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        help="A prepared benchmark payload, or the name of a defined benchmark.",
    )
    parser.add_argument("--min-support", type=int, default=2)
    parser.add_argument(
        "--reading",
        choices=("all", "reported"),
        default="all",
        help=(
            "What one node contributes when it has several forms for a cognate "
            "set: every one of them (the historical default, and what every "
            "recorded baseline used), or only the first, which is what "
            "summarize_correspondences does."
        ),
    )
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit one machine-readable object, including the measured source.",
    )
    args = parser.parse_args()

    input_path = _bootstrap.resolve_benchmark(args.input)
    payload = WorkbenchPayload.model_validate_json(
        input_path.read_text(encoding="utf-8")
    )
    node_ids, alignment_map, sets = build(payload, reading=args.reading)
    rows = sorted(sets.items(), key=lambda item: -item[1]["support"])
    kept = [row for row in rows if row[1]["support"] >= args.min_support]
    singletons = sum(1 for _, entry in rows if entry["support"] == 1)
    payload_bytes = len(
        json.dumps([[list(key), entry] for key, entry in rows]).encode()
    )

    if args.json:
        _bootstrap.emit_json(
            {
                **_bootstrap.measurement_envelope(input_path),
                "measurement": "correspondence_inventory",
                "node_ids": list(node_ids),
                "alignments": len(alignment_map.alignments),
                "distinct_sets": len(rows),
                "min_support": args.min_support,
                "sets_at_min_support": len(kept),
                "singletons": singletons,
                "inventory_bytes": payload_bytes,
                "top_sets": [
                    {
                        "correspondence": [
                            segment if segment else None for segment in key
                        ],
                        "support": entry["support"],
                        "example_concepts": entry["concepts"][:3],
                    }
                    for key, entry in kept[: args.limit]
                ],
            }
        )
        return

    print(f"measuring: {_bootstrap.loaded_package_path()}")
    short = {node: node.split(":")[-1][:6] for node in node_ids}
    print(
        f"{len(alignment_map.alignments)} cognate-set alignments over "
        f"{len(node_ids)} nodes -> {len(rows)} distinct correspondence sets"
    )
    print(f"{len(kept)} at support >= {args.min_support}; {singletons} singletons\n")
    header = " ".join(f"{short[node]:>6}" for node in node_ids)
    print(f"{'n':>4}  {header}   example concepts")
    for key, entry in kept[: args.limit]:
        cells = " ".join(f"{(seg if seg else 'Ø'):>6}" for seg in key)
        print(f"{entry['support']:>4}  {cells}   {','.join(entry['concepts'][:3])}")

    print(f"\nwhole-inventory payload: {payload_bytes / 1024:.1f} KB")


if __name__ == "__main__":
    main()
