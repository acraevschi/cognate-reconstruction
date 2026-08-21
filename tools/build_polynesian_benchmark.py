"""Thin wrapper around `build-benchmark --name polynesian`.

The selection logic that used to live here — pick ten daughters, keep the
concepts where every one of them shares a cognate set with the Proto-Polynesian
entry, bind the proto variety as a hidden `target` — is now a supported CLI
subcommand driven by a declarative definition, so a second family is a file
rather than a second script. See `benchmarks/polynesian.json` and
`cognate_reconstruction/benchmarks/`.

This wrapper stays because the documented invocation and the analysis tools'
default input path both reference it.

Usage:
    python tools/build_polynesian_benchmark.py
    python tools/build_polynesian_benchmark.py --output somewhere/else.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import _bootstrap  # noqa: F401  (bind to this checkout; see module)

from cognate_reconstruction.benchmarks import payload_path
from cognate_reconstruction.cli import main as cli_main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=payload_path("polynesian"))
    args = parser.parse_args()
    print(f"measuring: {_bootstrap.loaded_package_path()}", file=sys.stderr)
    cli_main(["build-benchmark", "--name", "polynesian", "--output", str(args.output)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
