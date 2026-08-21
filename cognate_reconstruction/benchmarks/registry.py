"""Where checked-in benchmark definitions live and how a name resolves.

The analysis tools and the multi-seed runner all want to say `polynesian`
rather than a path to a derived file whose location is a convention. This is
that convention, in one place: definitions are checked in under `benchmarks/`
at the repository root, and the payloads they build are derived and go under
`runs/benchmarks/`, which is gitignored.

Both are **checkout-scoped**, like `tools/` and `data/`. An installed
distribution has no `benchmarks/` directory, so `available_definitions()` there
returns nothing and only `--definition <path>` works. That is the intended
boundary: a benchmark definition names a local CLDF dataset the harness never
downloads, so it belongs to a working copy rather than to a wheel.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFINITION_DIR = REPO_ROOT / "benchmarks"
SYNTHETIC_DIR = DEFINITION_DIR / "synthetic"
BUILD_DIR = REPO_ROOT / "runs" / "benchmarks"


def definition_path(name: str) -> Path:
    """The checked-in definition file for a benchmark name."""
    return DEFINITION_DIR / f"{name}.json"


def payload_path(name: str) -> Path:
    """Where `build-benchmark` writes this benchmark's payload by default."""
    return BUILD_DIR / f"{name}.json"


def available_definitions() -> tuple[str, ...]:
    if not DEFINITION_DIR.is_dir():
        return ()
    return tuple(
        sorted(path.stem for path in DEFINITION_DIR.glob("*.json"))
    )


def resolve_payload(reference: str) -> Path:
    """Interpret a CLI argument as either a benchmark name or a payload path.

    A name is only accepted when a definition of that name exists, so a
    mistyped path fails as a missing path rather than being reinterpreted as a
    benchmark nobody defined.
    """
    candidate = Path(reference).expanduser()
    if candidate.exists():
        return candidate
    if reference in available_definitions():
        built = payload_path(reference)
        if built.exists():
            return built
        raise FileNotFoundError(
            f"benchmark {reference!r} is defined but not built. Run:\n"
            f"  python -m cognate_reconstruction.cli build-benchmark "
            f"--name {reference}"
        )
    raise FileNotFoundError(
        f"{reference!r} is neither an existing path nor a defined benchmark. "
        f"Defined benchmarks: {', '.join(available_definitions()) or 'none'}"
    )


def synthetic_definition_path(name: str) -> Path:
    """The checked-in definition file for a synthetic family."""
    return SYNTHETIC_DIR / f"{name}.json"


def available_synthetic_families() -> tuple[str, ...]:
    if not SYNTHETIC_DIR.is_dir():
        return ()
    return tuple(sorted(path.stem for path in SYNTHETIC_DIR.glob("*.json")))


def answer_key_path(name: str) -> Path:
    """Where a synthetic family's answer key goes by default.

    Beside the payload and never inside it. The key is the one artifact that
    must not reach the model, and keeping it a separate file makes an accidental
    inclusion a visible mistake rather than a silent one.
    """
    return BUILD_DIR / f"{name}.answer-key.json"
