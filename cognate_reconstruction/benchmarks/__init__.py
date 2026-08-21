"""Declarative benchmark definitions and the builder that runs them."""

from cognate_reconstruction.benchmarks.builder import (
    BenchmarkBuildReport,
    build_benchmark,
    load_definition,
    select_concepts,
)
from cognate_reconstruction.benchmarks.registry import (
    BUILD_DIR,
    DEFINITION_DIR,
    SYNTHETIC_DIR,
    answer_key_path,
    available_definitions,
    available_synthetic_families,
    definition_path,
    payload_path,
    resolve_payload,
    synthetic_definition_path,
)

__all__ = [
    "BUILD_DIR",
    "SYNTHETIC_DIR",
    "answer_key_path",
    "available_synthetic_families",
    "synthetic_definition_path",
    "BenchmarkBuildReport",
    "DEFINITION_DIR",
    "available_definitions",
    "build_benchmark",
    "definition_path",
    "load_definition",
    "payload_path",
    "resolve_payload",
    "select_concepts",
]
