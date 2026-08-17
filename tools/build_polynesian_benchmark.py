"""Rebuild the Proto-Polynesian benchmark input from local CLDF.

`data/lexibank/walworthpolynesian` ships Proto-Polynesian as a language, so it
supplies a real gold proto that can be withheld from the model. This selects ten
daughters spanning the standard subgrouping, keeps only the concepts where every
one of them shares a cognate set with the Proto-Polynesian entry, and binds the
proto variety as a hidden `target` at the root.

The result is the benchmark the analysis tools in this directory take as their
argument, and the baselines recorded in `docs/analysis_tools.md` come from it.
The generated payload is ~1.3 MB and derived, so it is written under `runs/`
(gitignored) rather than committed; the recipe — this script plus the tree and
bindings in `examples/` — is what lives in the repository.

Usage:
    python tools/build_polynesian_benchmark.py
    python tools/build_polynesian_benchmark.py --output somewhere/else.json
"""

from __future__ import annotations

import argparse
import collections
import csv
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATASET = REPO / "data" / "lexibank" / "walworthpolynesian"
TREE = REPO / "examples" / "polynesian_benchmark_tree.nwk"
BINDINGS = REPO / "examples" / "polynesian_benchmark_bindings.json"
GOLD_LANGUAGE = "Polynesian"

# Ten daughters spanning the standard subgrouping: Tongic, three Samoic-Outlier
# varieties, and both branches of Central Eastern. The tree in examples/ groups
# them; Nuclear Polynesian is left as a three-way polytomy because Samoic is
# paraphyletic and the harness supports unresolved nodes natively.
DAUGHTERS = [
    "Tongan",
    "Niuean",
    "Samoan",
    "EastFutuna",
    "EastUvea",
    "Hawaiian",
    "NorthMarquesan",
    "Maori",
    "Tahitian",
    "Rarotongan",
]


def select_concepts() -> list[str]:
    """Concepts where every daughter shares a cognate set with the gold proto.

    Requiring shared cognacy with the proto entry, rather than mere presence,
    is what makes the benchmark a test of reconstruction instead of a test of
    cognate judgement. Returns Concepticon IDs, which is what --concept-id takes.
    """
    forms = DATASET / "cldf" / "forms.csv"
    parameters = DATASET / "cldf" / "parameters.csv"
    if not forms.exists():
        raise SystemExit(f"missing local CLDF: {forms}")

    with parameters.open(encoding="utf-8") as handle:
        concepticon = {
            row["ID"]: row["Concepticon_ID"] or row["ID"]
            for row in csv.DictReader(handle)
        }
    grouped: dict[str, dict[str, list[dict]]] = collections.defaultdict(
        lambda: collections.defaultdict(list)
    )
    with forms.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            grouped[row["Parameter_ID"]][row["Language_ID"]].append(row)

    selected = []
    for parameter_id, by_language in sorted(grouped.items()):
        if GOLD_LANGUAGE not in by_language:
            continue
        if not all(name in by_language for name in DAUGHTERS):
            continue
        gold_sets = {
            value
            for row in by_language[GOLD_LANGUAGE]
            for value in row["Cognacy"].split()
        }
        shared = all(
            gold_sets
            & {
                value
                for row in by_language[name]
                for value in row["Cognacy"].split()
            }
            for name in DAUGHTERS
        )
        if shared:
            selected.append(concepticon[parameter_id])
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO / "runs" / "benchmarks" / "polynesian.json",
    )
    args = parser.parse_args()

    concepts = select_concepts()
    print(f"{len(concepts)} concepts fully cognate across {len(DAUGHTERS)} daughters")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "cognate_reconstruction.cli",
        "prepare-lexibank",
        "--dataset",
        str(DATASET),
        "--output",
        str(args.output),
        "--newick-file",
        str(TREE),
        "--historical-bindings",
        str(BINDINGS),
    ]
    for name in DAUGHTERS:
        command += ["--variety-id", f"walworthpolynesian:{name}"]
    for concept_id in concepts:
        command += ["--concept-id", concept_id]

    result = subprocess.run(command, cwd=REPO, text=True, capture_output=True)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
