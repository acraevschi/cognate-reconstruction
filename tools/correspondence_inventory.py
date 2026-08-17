"""The correspondence-set inventory the harness has no tool for.

A comparative linguist works from correspondence *sets*: the n-tuple of aligned
segments across every daughter, and how often it recurs. The harness exposes
alignments in batches instead, so recurrence is never observable. This builds
the whole inventory in one pass over the existing aligner and prints it by
support, which is the shape `summarize_correspondences` should return.

Usage:
    python tools/correspondence_inventory.py <benchmark-input.json> [--min-support 2] [--limit 30]
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload


def build(payload: WorkbenchPayload):
    node_ids = [lexicon.variety_id for lexicon in payload.lexicons]
    alignment_map = LingPyAligner().align_multiple(payload.lexicons)
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
    parser.add_argument("input", type=Path)
    parser.add_argument("--min-support", type=int, default=2)
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args()

    payload = WorkbenchPayload.model_validate_json(
        args.input.read_text(encoding="utf-8")
    )
    node_ids, alignment_map, sets = build(payload)
    rows = sorted(sets.items(), key=lambda item: -item[1]["support"])
    kept = [row for row in rows if row[1]["support"] >= args.min_support]
    singletons = sum(1 for _, entry in rows if entry["support"] == 1)

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

    payload_bytes = len(
        json.dumps([[list(key), entry] for key, entry in rows]).encode()
    )
    print(f"\nwhole-inventory payload: {payload_bytes / 1024:.1f} KB")


if __name__ == "__main__":
    main()
