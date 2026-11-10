#!/usr/bin/env python3
"""B02 real-family benchmark driver: candidate freeze, staged gate, resume & evaluation.

Wraps the single-checkpoint two-stage Burmish live benchmark workflow (`B02`):
  - `freeze`: writes `inputs/{price-table.json,provider-config.json,burmish.payload.json}`,
    `source_manifest.json`, and `manifest.b02-burmish.json` (with all tones 100% intact).
  - `run-stage1`: launches `cli.py infer --stop-after-node maruic` (`$3.50` / `1500s`).
  - `gate-stage1`: runs `$0` `inspect_run` + `audit_run_directory` on `maruic` and writes
    `<run_dir>/gate_stage1.json`.
  - `run-stage2-resume`: verifies `gate_stage1.json` (`usable == True`) and resumes the
    exact same checkpoint directory (`--resume`) with cumulative caps `$8.50` / `3600s`
    (`8.50 + 0.909312 = US$9.409312 <= US$10.00` worst-case upper bound).
  - `evaluate`: runs `$0` `audit_run_directory`, official `task02-v1` + `task04-units-v1`
    full-form evaluation, `R06` full-form `compute_corpus_contrast_equivalence`
    (`corpus_bcubed_f1`, `is_bijective_relabelling`, tones 100% intact), `$0` offline
    counterfactual assembly replay (`tied_confidence_threshold = None` vs `0.5`), and
    certified `batch_ledger.json` via `read_run_resources` (reporting both uncached table
    upper-bound cost and cached-adjusted USD cost).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tools import _bootstrap  # noqa: F401

from cognate_reconstruction.agent.instructions import load_agent_instructions
from cognate_reconstruction.agent.orchestrator import AgentOrchestrator
from cognate_reconstruction.agent.providers.pricing import load_price_table, price_for
from cognate_reconstruction.agent.reconstructor import AgenticNodeReconstructor
from cognate_reconstruction.agent.schemas import (
    LLMMessage,
    LLMToolCall,
    MessageRole,
)
from cognate_reconstruction.agent.service import ReconstructionService
from cognate_reconstruction.agent.tools import default_tool_registry
from cognate_reconstruction.agent.tools.inventory_evidence import column_bindings
from cognate_reconstruction.agent.trajectory import TrajectoryDatasetBuilder
from cognate_reconstruction.alignment.correspondence_sets import unit_set_id
from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.alignment.units import evidence_map, source_analyses
from cognate_reconstruction.benchmarks import build_benchmark, definition_path, load_definition
from cognate_reconstruction.benchmarks.ledger import RunResources, batch_totals, read_run_resources
from cognate_reconstruction.evaluation.forward import compute_corpus_contrast_equivalence
from cognate_reconstruction.evaluation.run import (
    evaluate_run,
    load_result_or_summary,
    step_from_artifact,
)
from cognate_reconstruction.ingestion import ingest_payload
from cognate_reconstruction.inspect_run import inspect_run
from cognate_reconstruction.schemas.historical import HistoricalFormRole
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.schemas.inventory import CommittedProtoInventory
from cognate_reconstruction.schemas.lexicon import LexicalForm
from cognate_reconstruction.schemas.rules import AnchorPolicy
from cognate_reconstruction.schemas.traversal import ReconstructionStep
from cognate_reconstruction.synthesis.diagnostics import build_explicit_case, load_explicit_case
from cognate_reconstruction.traversal import (
    CheckpointStore,
    ProtoInventoryAssembler,
    RuleBasedReconstructor,
)
from cognate_reconstruction.traversal.beam import beam_to_lexicon, make_leaf_beam
from cognate_reconstruction.tree import assign_node_ids, parse_newick, postorder_groups

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXPERIMENT_DIR = ROOT / "runs/experiments/b02-burmish-gemini-benchmark"
BURMISH_DEFINITION = ROOT / "benchmarks/burmish.json"
GEMINI_PRICE_TABLE = ROOT / "examples/pricing/gemini-3.8-flash.price-table.json"

LOCAL_ONLY = (
    "tools/failure_audit.py",
    "tests/workbench/test_failure_audit.py",
    "tests/fixtures/failure_audit/",
)

ARM_NAME = "burmish-gemini"
RUN_ID = "b02-burmish-gemini"
MODEL = "gemini-3.8-flash"
PRESET = "gemini"
HARNESS_MODEL = "gemini/gemini-3.8-flash"
REASONING_EFFORT = "medium"
TEMPERATURE = 1.0
TIMEOUT_SECONDS = 300
MAX_OUTPUT_TOKENS = 32_768
CONTEXT_LIMIT_TOKENS = 1_048_576
TIED_CONFIDENCE_THRESHOLD = 0.5
COMPACTION_WATERMARK_TOKENS = 256_000
LOCAL_QWEN_WATERMARK_TOKENS = 96_000
MAX_TURNS = 36
MAX_TOOL_CALLS = 64
MAX_TOTAL_TURNS = 108
BEAM_WIDTH = 5
GATE_NODE_ID = "maruic"

STAGE1_CAPS = {
    "stop_after_node": GATE_NODE_ID,
    "max_turns": MAX_TURNS,
    "max_tool_calls": MAX_TOOL_CALLS,
    "max_run_seconds": 1500.0,
    "max_total_cost_usd": 3.50,
}

STAGE2_CUMULATIVE_CAPS = {
    "stop_after_node": None,
    "max_turns": MAX_TURNS,
    "max_tool_calls": MAX_TOOL_CALLS,
    "max_run_seconds": 3600.0,
    "max_total_cost_usd": 8.50,
}

HARD_COST_CEILING_USD = 10.00
HARD_WALL_CEILING_SECONDS = 3900.0
WALL_OVERHEAD_SECONDS = 150.0
LEDGER_VERSION = "r02-ledger-v1"
EVENTS_FILE = "batch_events.jsonl"
LEDGER_FILE = "batch_ledger.json"
GATE_FILE = "gate_stage1.json"
EVALUATION_FILE = "evaluation.json"

TONE_TOKEN_PATTERN = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+")

BURMISH_DATASET_SUMMARY: dict[str, Any] = {
    "definition_path": "benchmarks/burmish.json",
    "definition_sha256": "fb9cd9660f08dea3d4d69bf5b7e82a1c345b6143d8f08039b089041d1856128d",
    "normalized_tree_newick": (
        "(('hillburmish:Atsi','hillburmish:Bola','hillburmish:Lashi','hillburmish:Maru')maruic,"
        "('hillburmish:AchangLongchuan','hillburmish:Xiandao','hillburmish:Rangoon')burmic)proto_burmish;"
    ),
    "normalized_tree_sha256": "fa7b48177b087cf728295be4a5ef163b9001ab69b2f6f6f9aa7cb776d7343f5c",
    "tones_policy": "preserved_100_percent_intact_no_tone_stripping",
    "postorder_internal_nodes": [
        {
            "node_id": "maruic",
            "children": [
                "hillburmish:Atsi",
                "hillburmish:Bola",
                "hillburmish:Lashi",
                "hillburmish:Maru",
            ],
            "leaf_count": 4,
            "target_binding": None,
            "units_v2_leaf_beam_inventory": {
                "local_csu_sets": 738,
                "recurrence_csp_patterns": 320,
                "recurrence_support_ge_2": 113,
                "candidate_tuples": 91,
                "projected_columns": 2460,
            },
        },
        {
            "node_id": "burmic",
            "children": [
                "hillburmish:AchangLongchuan",
                "hillburmish:Xiandao",
                "hillburmish:Rangoon",
            ],
            "leaf_count": 3,
            "target_binding": {
                "source_variety_id": "hillburmish:OldBurmese",
                "gold_evidence_kind": "attested",
                "target_validity": "provisional_proxy",
                "concept_count": 37,
                "form_count": 38,
                "multi_variant_concept_count": 1,
            },
            "units_v2_leaf_beam_inventory": {
                "local_csu_sets": 543,
                "recurrence_csp_patterns": 210,
                "recurrence_support_ge_2": 90,
                "candidate_tuples": 57,
                "projected_columns": 926,
            },
        },
        {
            "node_id": "proto_burmish",
            "children": ["maruic", "burmic"],
            "leaf_count": 7,
            "target_binding": {
                "source_variety_id": "hillburmish:ProtoBurmish",
                "gold_evidence_kind": "reconstructed",
                "target_validity": "validated_target",
                "concept_count": 54,
                "form_count": 92,
                "multi_variant_concept_count": 23,
            },
            "units_v2_identity_child_beam_inventory": {
                "local_csu_sets": 1823,
                "recurrence_csp_patterns": 419,
                "recurrence_support_ge_2": 207,
                "candidate_tuples": 588,
                "projected_columns": 7720,
            },
        },
    ],
}

DETERMINISTIC_CEILINGS_TONES_INTACT: dict[str, Any] = {
    "beam_width": 5,
    "alignment_reading": (
        "LingPy global SCA, boundaries='include', tones 100% intact, "
        "legacy_whole_string leaf beams in oracle_ceiling.py"
    ),
    "proto_burmish": {
        "evaluated_concepts": 54,
        "selection_bar_exact": 0,
        "oracle_context_free": {
            "top_exact": 7,
            "top_exact_rate": 0.12963,
            "beam_exact": 15,
            "beam_exact_rate": 0.277778,
            "mean_top_ned": 0.489644,
            "mean_beam_ned": 0.295811,
            "mean_top_bcubed_f1": 0.90954,
            "rules_written": 236,
        },
        "oracle_contextual": {
            "top_exact": 16,
            "top_exact_rate": 0.296296,
            "beam_exact": 26,
            "beam_exact_rate": 0.481481,
            "mean_top_ned": 0.292615,
            "mean_beam_ned": 0.178395,
            "mean_top_bcubed_f1": 0.960443,
            "rules_written": 621,
            "fallback_branches": 1,
        },
        "oracle_assembly": {
            "top_exact": 42,
            "top_exact_rate": 0.777778,
            "beam_exact": 42,
            "beam_exact_rate": 0.777778,
            "mean_top_ned": 0.07037,
            "mean_beam_ned": 0.07037,
            "mean_top_bcubed_f1": 0.988598,
            "commitments_written": 529,
            "mean_unaccounted_column_rate": 0.0,
        },
        "assembly_ceiling": {
            "flat_reachable": 5,
            "flat_rate": 0.092593,
            "node_local_reachable": 6,
            "node_local_rate": 0.111111,
            "free_choice_vacuous": 54,
        },
    },
    "burmic_provisional_proxy": {
        "evaluated_concepts": 37,
        "selection_bar_exact": 0,
        "oracle_context_free": {
            "top_exact": 11,
            "top_exact_rate": 0.297297,
            "beam_exact": 15,
            "beam_exact_rate": 0.405405,
            "mean_top_ned": 0.370967,
            "mean_beam_ned": 0.199721,
            "mean_top_bcubed_f1": 0.951593,
            "rules_written": 194,
        },
        "oracle_contextual": {
            "top_exact": 10,
            "top_exact_rate": 0.27027,
            "beam_exact": 17,
            "beam_exact_rate": 0.459459,
            "mean_top_ned": 0.312484,
            "mean_beam_ned": 0.196761,
            "mean_top_bcubed_f1": 0.955025,
            "rules_written": 380,
            "fallback_branches": 1,
        },
        "oracle_assembly": {
            "top_exact": 25,
            "top_exact_rate": 0.675676,
            "beam_exact": 25,
            "beam_exact_rate": 0.675676,
            "mean_top_ned": 0.090015,
            "mean_beam_ned": 0.090015,
            "mean_top_bcubed_f1": 0.974465,
            "commitments_written": 335,
            "mean_unaccounted_column_rate": 0.17058,
        },
        "assembly_ceiling": {
            "flat_reachable": 4,
            "flat_rate": 0.108108,
            "node_local_reachable": 4,
            "node_local_rate": 0.108108,
            "free_choice_vacuous": 34,
        },
    },
}

PRE_R01_BANKED_SWEEPS: dict[str, Any] = {
    "model": "gemini/gemini-3.7-flash",
    "r06_reference_convention": (
        "per-concept TargetConceptEvaluation.nearest_target_segments from task02-v1 "
        "compare_to_nearest(top_candidate_segments, target_segment_alternatives), tones 100% intact"
    ),
    "seeds": {
        "burmish-gemini-t36-r2/seed-00": {
            "configuration_sha256": "147f4fe2334eb494e64dae0089adf373bacb8dfaab7879b4a3199fb93aef59ec",
            "nodes_committed": 2,
            "fallback_nodes": ["maruic"],
            "turns": 70,
            "tool_calls": 70,
            "failed_tool_calls": 14,
            "input_tokens": 10993316,
            "cached_input_tokens": 9068585,
            "output_tokens": 187813,
            "recorded_cost_usd": 2.827991,
            "proto_burmish": {
                "n": 54,
                "top_exact": 0,
                "beam_exact": 0,
                "mean_ned": 0.707279,
                "mean_beam_ned": 0.672083,
                "word_bcubed_f1": 0.861123,
                "cognate_unit_exact_scored": 0,
                "corpus_bcubed_precision": 0.436447,
                "corpus_bcubed_recall": 0.353021,
                "corpus_bcubed_f1": 0.390326,
                "is_bijective_relabelling": False,
            },
            "burmic": {
                "n": 37,
                "top_exact": 0,
                "beam_exact": 0,
                "mean_ned": 0.672351,
                "mean_beam_ned": 0.672351,
                "word_bcubed_f1": 0.9611,
                "cognate_unit_exact_scored": 0,
                "corpus_bcubed_precision": 0.497648,
                "corpus_bcubed_recall": 0.450734,
                "corpus_bcubed_f1": 0.473031,
                "is_bijective_relabelling": False,
            },
        },
        "burmish-gemini-t36-r2/seed-01": {
            "configuration_sha256": "147f4fe2334eb494e64dae0089adf373bacb8dfaab7879b4a3199fb93aef59ec",
            "nodes_committed": 3,
            "fallback_nodes": [],
            "turns": 68,
            "tool_calls": 68,
            "failed_tool_calls": 9,
            "input_tokens": 8603720,
            "cached_input_tokens": 7106853,
            "output_tokens": 144557,
            "recorded_cost_usd": 2.197753,
            "proto_burmish": {
                "n": 54,
                "top_exact": 0,
                "beam_exact": 0,
                "mean_ned": 0.706526,
                "mean_beam_ned": 0.706526,
                "word_bcubed_f1": 0.889002,
                "cognate_unit_exact_scored": 0,
                "corpus_bcubed_precision": 0.48792,
                "corpus_bcubed_recall": 0.458766,
                "corpus_bcubed_f1": 0.472894,
                "is_bijective_relabelling": False,
            },
            "burmic": {
                "n": 37,
                "top_exact": 1,
                "top_exact_rate": 0.027027,
                "beam_exact": 1,
                "mean_ned": 0.666645,
                "mean_beam_ned": 0.666645,
                "word_bcubed_f1": 0.9611,
                "cognate_unit_exact_scored": 0,
                "corpus_bcubed_precision": 0.509023,
                "corpus_bcubed_recall": 0.407705,
                "corpus_bcubed_f1": 0.452765,
                "is_bijective_relabelling": False,
            },
        },
        "burmish-gemini-t36-r3/seed-00": {
            "configuration_sha256": "517718f2f5fcf856ce0a4b00df2607ece3442d874b4d3fd9eb298894ee5c0234",
            "nodes_committed": 3,
            "fallback_nodes": [],
            "turns": 56,
            "tool_calls": 57,
            "failed_tool_calls": 7,
            "input_tokens": 6129945,
            "cached_input_tokens": 4685875,
            "output_tokens": 133648,
            "recorded_cost_usd": 1.935673,
            "proto_burmish": {
                "n": 54,
                "top_exact": 0,
                "beam_exact": 0,
                "mean_ned": 0.738608,
                "mean_beam_ned": 0.738608,
                "word_bcubed_f1": 0.857031,
                "cognate_unit_exact_scored": 0,
                "corpus_bcubed_precision": 0.438775,
                "corpus_bcubed_recall": 0.358123,
                "corpus_bcubed_f1": 0.394367,
                "is_bijective_relabelling": False,
            },
            "burmic": {
                "n": 37,
                "top_exact": 0,
                "beam_exact": 0,
                "mean_ned": 0.714843,
                "mean_beam_ned": 0.714843,
                "word_bcubed_f1": 0.957849,
                "cognate_unit_exact_scored": 0,
                "corpus_bcubed_precision": 0.478188,
                "corpus_bcubed_recall": 0.414191,
                "corpus_bcubed_f1": 0.443895,
                "is_bijective_relabelling": False,
            },
        },
        "burmish-gemini-t36-r3/seed-01": {
            "configuration_sha256": "517718f2f5fcf856ce0a4b00df2607ece3442d874b4d3fd9eb298894ee5c0234",
            "nodes_committed": 3,
            "fallback_nodes": [],
            "turns": 60,
            "tool_calls": 60,
            "failed_tool_calls": 5,
            "input_tokens": 7185950,
            "cached_input_tokens": 6092787,
            "output_tokens": 137682,
            "recorded_cost_usd": 1.793139,
            "proto_burmish": {
                "n": 54,
                "top_exact": 0,
                "beam_exact": 0,
                "mean_ned": 0.689469,
                "mean_beam_ned": 0.689469,
                "word_bcubed_f1": 0.890353,
                "cognate_unit_exact_scored": 0,
                "corpus_bcubed_precision": 0.472987,
                "corpus_bcubed_recall": 0.483164,
                "corpus_bcubed_f1": 0.478021,
                "is_bijective_relabelling": False,
            },
            "burmic": {
                "n": 37,
                "top_exact": 0,
                "beam_exact": 0,
                "mean_ned": 0.682561,
                "mean_beam_ned": 0.682561,
                "word_bcubed_f1": 0.961427,
                "cognate_unit_exact_scored": 0,
                "corpus_bcubed_precision": 0.520808,
                "corpus_bcubed_recall": 0.490494,
                "corpus_bcubed_f1": 0.505197,
                "is_bijective_relabelling": False,
            },
        },
    },
    "aggregate_4_seeds": {
        "nodes_committed_over_attempted": "11/12",
        "proto_burmish": {
            "repeated_evaluations": 216,
            "top_exact": 0,
            "beam_exact": 0,
            "mean_ned": 0.710471,
            "sd_ned": 0.020482,
            "mean_word_bcubed_f1": 0.874377,
            "sd_word_bcubed_f1": 0.017754,
            "mean_corpus_bcubed_precision": 0.459032,
            "mean_corpus_bcubed_recall": 0.413269,
            "mean_corpus_bcubed_f1": 0.433902,
            "sd_corpus_bcubed_f1": 0.048058,
            "any_bijective_relabelling": False,
        },
        "burmic": {
            "repeated_evaluations": 148,
            "top_exact": 1,
            "beam_exact": 1,
            "mean_ned": 0.6841,
            "sd_ned": 0.021527,
            "mean_word_bcubed_f1": 0.960369,
            "sd_word_bcubed_f1": 0.001687,
            "mean_corpus_bcubed_precision": 0.501417,
            "mean_corpus_bcubed_recall": 0.440781,
            "mean_corpus_bcubed_f1": 0.468722,
            "sd_corpus_bcubed_f1": 0.027203,
            "any_bijective_relabelling": False,
        },
    },
}


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def default_run_dir(experiment_dir: Path) -> Path:
    return experiment_dir / "runs" / ARM_NAME


def _has_tone_tokens(payload: WorkbenchPayload) -> bool:
    for lex in payload.lexicons:
        for form in lex.forms:
            if any(TONE_TOKEN_PATTERN.search(seg) for seg in form.segments):
                return True
    return False


def load_benchmark_payload(
    source: str | Path | None = None,
    *,
    experiment_dir: Path = DEFAULT_EXPERIMENT_DIR,
) -> tuple[WorkbenchPayload, Path, str]:
    """Load or build a benchmark `WorkbenchPayload` without altering tone tokens."""
    if source is None:
        frozen_payload = experiment_dir / "inputs" / "burmish.payload.json"
        if frozen_payload.exists():
            text = frozen_payload.read_text(encoding="utf-8")
            return WorkbenchPayload.model_validate_json(text), frozen_payload, _hash_text(text)
        source = BURMISH_DEFINITION

    candidate = Path(source)
    if not candidate.exists() and isinstance(source, str) and not source.endswith(".json"):
        candidate = definition_path(source)
    if not candidate.exists():
        candidate = ROOT / str(source)
    candidate = candidate.resolve()

    raw_text = candidate.read_text(encoding="utf-8")
    raw_obj = json.loads(raw_text)
    if isinstance(raw_obj, dict) and "newick" in raw_obj and "lexicons" in raw_obj:
        return WorkbenchPayload.model_validate_json(raw_text), candidate, _hash_text(raw_text)
    if isinstance(raw_obj, dict) and ("suite_version" in raw_obj or "opportunities" in raw_obj):
        payload = build_explicit_case(load_explicit_case(candidate))
        rendered = payload.model_dump_json(indent=2) + "\n"
        return payload, candidate, _hash_text(rendered)

    definition = load_definition(candidate)
    built = build_benchmark(definition, base_path=candidate.parent)
    payload = built[0] if isinstance(built, tuple) else built
    rendered = payload.model_dump_json(indent=2) + "\n"
    return payload, candidate, _hash_text(rendered)


def source_manifest() -> dict[str, Any]:
    """Code identity: HEAD, tracked diff digest, and per-file hashes (local audit files excluded)."""
    git = lambda *a: subprocess.run(
        ["git", *a], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    roots = ("cognate_reconstruction", "tools", "tests", "skills", "benchmarks", "examples")
    files = [
        f
        for f in git("ls-files", "--cached", "--others", "--exclude-standard", *roots).split("\n")
        if f
        and not f.startswith(LOCAL_ONLY)
        and (ROOT / f).is_file()
        and "__pycache__" not in f
    ]
    return {
        "head": git("rev-parse", "HEAD").strip(),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD").strip(),
        "source_roots": list(roots),
        "tracked_diff_sha256": _hash_text(git("diff", "HEAD", "--binary", "--", *roots)),
        "dirty_paths": sorted(
            line[3:]
            for line in git("status", "--porcelain", "--", *roots).splitlines()
            if not line[3:].startswith(LOCAL_ONLY)
        ),
        "excluded_local_only": list(LOCAL_ONLY),
        "files": {f: _file_hash(ROOT / f) for f in sorted(files)},
    }


def behavioural_digests(protocol: str, instructions_path: Path | None = None) -> dict[str, str]:
    from types import SimpleNamespace
    from cognate_reconstruction import cli

    args = SimpleNamespace(
        inventory_protocol=protocol,
        agent_instructions=str(instructions_path) if instructions_path else None,
        anchors=None,
    )
    return cli._behavioural_input_digests(args)


def first_node_prompt(
    payload: WorkbenchPayload,
    instructions: str,
    protocol: str,
    node_id: str,
    *,
    tied_confidence_threshold: float | None = TIED_CONFIDENCE_THRESHOLD,
) -> dict[str, Any]:
    """Digest of the exact first request a session at `node_id` receives (`$0` scripted peek)."""
    captured: dict[str, dict[str, Any]] = {}

    class _PeekProvider:
        model = "scripted/b02-peek"

        def complete(self, messages, tools, **kwargs):
            prompt = messages[1].content
            match = re.search(r'"node_id":\s*"([^"]+)"', prompt)
            current = match.group(1) if match else ""
            if current == node_id and node_id not in captured:
                captured[node_id] = {
                    "system_sha256": _hash_text(messages[0].content or ""),
                    "node_prompt_sha256": _hash_text(prompt),
                    "tool_definitions_sha256": _hash_text(
                        json.dumps([t.model_dump(mode="json") for t in tools])
                    ),
                    "node_prompt_chars": len(prompt),
                }
            return LLMMessage(
                role=MessageRole.ASSISTANT,
                tool_calls=(
                    LLMToolCall(
                        call_id=f"peek-{current}",
                        name="commit_reconstruction",
                        arguments={
                            "node_id": current,
                            "rules": [],
                            "anomalies": [],
                            "summary": "scripted prompt digest peek",
                        },
                    ),
                ),
            )

    service = ReconstructionService(
        AgenticNodeReconstructor(
            AgentOrchestrator(
                _PeekProvider(),
                registry=default_tool_registry(inventory_protocol=protocol),
                instructions=instructions,
                run_id="b02-prompt-peek",
                configuration_sha256="b02-prompt-peek",
                compaction_watermark_tokens=COMPACTION_WATERMARK_TOKENS,
            ),
            tied_confidence_threshold=tied_confidence_threshold,
        )
    )
    try:
        service.reconstruct_family(ingest_payload(payload), stop_after_node=node_id)
    except Exception:
        if node_id not in captured:
            raise
    return captured[node_id]


def resource_bound(
    *,
    cost_cap_usd: float,
    max_run_seconds: float,
    max_turns_total: int,
    price,
    expected_cached_usd_range: Sequence[float],
) -> dict[str, Any]:
    headroom = (
        CONTEXT_LIMIT_TOKENS * price.input_usd_per_million
        + MAX_OUTPUT_TOKENS * price.output_usd_per_million
    ) / 1_000_000
    worst = cost_cap_usd + headroom
    return {
        "paid": True,
        "cost_cap_usd": cost_cap_usd,
        "one_response_headroom_usd": round(headroom, 6),
        "headroom_basis": (
            f"{CONTEXT_LIMIT_TOKENS} input tokens (context limit) and "
            f"{MAX_OUTPUT_TOKENS} output tokens at the uncached table price"
        ),
        "worst_case_upper_bound_usd": round(worst, 6),
        "cost_reservation_usd": round(worst + 0.005, 2),
        "within_10_usd_hard_ceiling": worst <= HARD_COST_CEILING_USD,
        "expected_cached_spend_usd_range": list(expected_cached_usd_range),
        "max_turns_total": max_turns_total,
        "worst_case_output_tokens": max_turns_total * MAX_OUTPUT_TOKENS,
        "max_run_seconds": max_run_seconds,
        "wall_reservation_seconds": max_run_seconds + WALL_OVERHEAD_SECONDS,
    }


def _common_semantic_infer_flags(
    inputs_dir: Path,
    *,
    payload_path: Path | None = None,
) -> list[str]:
    resolved_payload = payload_path or (inputs_dir / "burmish.payload.json")
    return [
        "--input",
        str(resolved_payload),
        "--preset",
        PRESET,
        "--model",
        MODEL,
        "--reasoning-effort",
        REASONING_EFFORT,
        "--price-table",
        str(inputs_dir / "price-table.json"),
        "--provider-config",
        str(inputs_dir / "provider-config.json"),
        "--inventory-protocol",
        "stored-hypothesis",
        "--tied-confidence-threshold",
        str(TIED_CONFIDENCE_THRESHOLD),
        "--compaction-watermark-tokens",
        str(COMPACTION_WATERMARK_TOKENS),
        "--max-turns",
        str(MAX_TURNS),
        "--max-tool-calls",
        str(MAX_TOOL_CALLS),
        "--max-failed-nodes",
        "0",
        "--max-retries",
        "3",
        "--max-retry-seconds",
        str(TIMEOUT_SECONDS),
        "--timeout",
        str(TIMEOUT_SECONDS),
        "--reasoning-history",
        "auto",
    ]


def stage1_argv(
    experiment_dir: Path = DEFAULT_EXPERIMENT_DIR,
    *,
    run_dir: Path | None = None,
    payload_path: Path | None = None,
    python_executable: str = "{python}",
    extra_args: Sequence[str] = (),
) -> list[str]:
    experiment_dir = experiment_dir.resolve()
    inputs_dir = experiment_dir / "inputs"
    target_run = (run_dir or default_run_dir(experiment_dir)).resolve()
    return [
        python_executable,
        "-m",
        "cognate_reconstruction.cli",
        "infer",
        *_common_semantic_infer_flags(inputs_dir, payload_path=payload_path),
        "--output",
        str(target_run / "result.json"),
        "--trajectories",
        str(target_run / "trajectories.jsonl"),
        "--events",
        str(target_run / "events.jsonl"),
        "--checkpoint",
        str(target_run / "checkpoint.json"),
        "--run-id",
        RUN_ID,
        "--stop-after-node",
        GATE_NODE_ID,
        "--max-total-cost-usd",
        f"{STAGE1_CAPS['max_total_cost_usd']:.2f}",
        "--max-run-seconds",
        str(int(STAGE1_CAPS["max_run_seconds"])),
        "--quiet",
        *extra_args,
    ]


def stage2_resume_argv(
    experiment_dir: Path = DEFAULT_EXPERIMENT_DIR,
    *,
    run_dir: Path | None = None,
    payload_path: Path | None = None,
    python_executable: str = "{python}",
    extra_args: Sequence[str] = (),
) -> list[str]:
    experiment_dir = experiment_dir.resolve()
    inputs_dir = experiment_dir / "inputs"
    target_run = (run_dir or default_run_dir(experiment_dir)).resolve()
    return [
        python_executable,
        "-m",
        "cognate_reconstruction.cli",
        "infer",
        *_common_semantic_infer_flags(inputs_dir, payload_path=payload_path),
        "--output",
        str(target_run / "result.json"),
        "--trajectories",
        str(target_run / "trajectories.jsonl"),
        "--events",
        str(target_run / "events.jsonl"),
        "--checkpoint",
        str(target_run / "checkpoint.json"),
        "--resume",
        "--max-total-cost-usd",
        f"{STAGE2_CUMULATIVE_CAPS['max_total_cost_usd']:.2f}",
        "--max-run-seconds",
        str(int(STAGE2_CUMULATIVE_CAPS["max_run_seconds"])),
        "--quiet",
        *extra_args,
    ]


def _collect_banked_critic_baselines(burmish_payload: WorkbenchPayload) -> dict[str, Any] | None:
    try:
        from cognate_reconstruction.evaluation.critic import audit_run_directory
    except ImportError:
        return None

    out: dict[str, Any] = {}
    stage_c_def = ROOT / "benchmarks/diagnostic/r04-stage-c-v1.json"
    if not stage_c_def.exists():
        stage_c_def = ROOT / "benchmarks/diagnostic/stage-c-multi-outgroup-v1.json"
    stage_c_payload = (
        build_explicit_case(load_explicit_case(stage_c_def)) if stage_c_def.exists() else None
    )

    stage_c_runs = {
        "r04_c_gemini": ROOT / "runs/experiments/r04-stage-c-20261029-v2/runs/c-gemini-r04",
        "r04_c_local_qwen36_35b": (
            ROOT / "runs/experiments/r04c-local-qwen36-35b-20261030/runs/c-local-qwen36-35b-r04"
        ),
    }
    for label, rdir in stage_c_runs.items():
        if rdir.exists() and stage_c_payload is not None:
            audit = audit_run_directory(rdir, payload=stage_c_payload)
            out[label] = {
                "run_dir": str(rdir.relative_to(ROOT)),
                "run_status": audit.get("run_status"),
                "nodes_audited": audit.get("nodes_audited"),
                "total_defect_count": audit.get("total_defect_count"),
                "defect_counts_by_category": audit.get("defect_counts_by_category"),
            }

    burmish_seeds = {
        "burmish-gemini-t36-r2/seed-00": ROOT / "runs/sweeps/burmish-gemini-t36-r2/seed-00",
        "burmish-gemini-t36-r2/seed-01": ROOT / "runs/sweeps/burmish-gemini-t36-r2/seed-01",
        "burmish-gemini-t36-r3/seed-00": ROOT / "runs/sweeps/burmish-gemini-t36-r3/seed-00",
        "burmish-gemini-t36-r3/seed-01": ROOT / "runs/sweeps/burmish-gemini-t36-r3/seed-01",
    }
    burmish_audits: dict[str, Any] = {}
    for seed_label, sdir in burmish_seeds.items():
        if sdir.exists():
            audit = audit_run_directory(sdir, payload=burmish_payload)
            nodes_summary = {
                nid: {
                    "is_root": ninfo.get("is_root"),
                    "committed": ninfo.get("committed"),
                    "failure_fallback": ninfo.get("failure_fallback"),
                    "residue_policy": ninfo.get("residue_policy"),
                    "unaccounted_column_count": ninfo.get("unaccounted_column_count"),
                    "assembled_column_count": ninfo.get("assembled_column_count"),
                    "unaccounted_column_rate": ninfo.get("unaccounted_column_rate"),
                    "uncovered_set_count": ninfo.get("uncovered_set_count"),
                    "uncovered_concept_count": ninfo.get("uncovered_concept_count"),
                    "defect_count": ninfo.get("defect_count", 0),
                }
                for nid, ninfo in (audit.get("nodes") or {}).items()
            }
            burmish_audits[seed_label] = {
                "run_status": audit.get("run_status"),
                "nodes_audited": audit.get("nodes_audited"),
                "fallback_node_ids": audit.get("fallback_node_ids"),
                "total_defect_count": audit.get("total_defect_count"),
                "defect_counts_by_category": audit.get("defect_counts_by_category"),
                "proto_burmish_defect_count": (
                    (audit.get("nodes") or {}).get("proto_burmish") or {}
                ).get("defect_count", 0),
                "nodes": nodes_summary,
            }
    if burmish_audits:
        out["pre_r01_burmish_sweeps"] = burmish_audits
    return out or None


def freeze(
    experiment_dir: Path = DEFAULT_EXPERIMENT_DIR,
    *,
    definition: Path = BURMISH_DEFINITION,
    price_table_source: Path = GEMINI_PRICE_TABLE,
    include_banked_critic_baselines: bool = True,
) -> dict[str, Any]:
    """Write frozen inputs, `source_manifest.json`, and `manifest.b02-burmish.json`."""
    experiment_dir = experiment_dir.resolve()
    inputs_dir = experiment_dir / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)

    payload, resolved_def, _ = load_benchmark_payload(definition, experiment_dir=experiment_dir)
    if not _has_tone_tokens(payload):
        raise ValueError("Frozen Burmish payload must preserve tone tokens intact")

    payload_text = payload.model_dump_json(indent=2) + "\n"
    (inputs_dir / "burmish.payload.json").write_text(payload_text, encoding="utf-8")
    (inputs_dir / "price-table.json").write_bytes(price_table_source.read_bytes())
    (inputs_dir / "provider-config.json").write_text(
        json.dumps({"max_tokens": MAX_OUTPUT_TOKENS}, indent=2) + "\n",
        encoding="utf-8",
    )

    table, table_sha = load_price_table(inputs_dir / "price-table.json")
    price = price_for(table, HARNESS_MODEL, date.today())

    sources = source_manifest()
    source_manifest_path = experiment_dir / "source_manifest.json"
    source_manifest_path.write_text(json.dumps(sources, indent=2) + "\n", encoding="utf-8")

    input_hashes = {p.name: _file_hash(p) for p in sorted(inputs_dir.iterdir()) if p.is_file()}
    instructions = load_agent_instructions()
    stage1_bound = resource_bound(
        cost_cap_usd=STAGE1_CAPS["max_total_cost_usd"],
        max_run_seconds=STAGE1_CAPS["max_run_seconds"],
        max_turns_total=MAX_TURNS,
        price=price,
        expected_cached_usd_range=(0.50, 0.90),
    )
    stage2_bound = resource_bound(
        cost_cap_usd=STAGE2_CUMULATIVE_CAPS["max_total_cost_usd"],
        max_run_seconds=STAGE2_CUMULATIVE_CAPS["max_run_seconds"],
        max_turns_total=MAX_TOTAL_TURNS,
        price=price,
        expected_cached_usd_range=(1.80, 2.80),
    )

    critic_baselines = (
        _collect_banked_critic_baselines(payload) if include_banked_critic_baselines else None
    )
    try:
        from cognate_reconstruction.evaluation.critic import CRITIC_EVALUATOR_VERSION
    except ImportError:
        CRITIC_EVALUATOR_VERSION = "r07-critic-v1"

    target_run = default_run_dir(experiment_dir)
    s1_argv = stage1_argv(experiment_dir, run_dir=target_run)
    s2_argv = stage2_resume_argv(experiment_dir, run_dir=target_run)

    try:
        rel_def = str(resolved_def.relative_to(ROOT))
    except ValueError:
        rel_def = str(resolved_def)

    manifest: dict[str, Any] = {
        "experiment": experiment_dir.name,
        "frozen_on": str(date.today()),
        "stage": "B02",
        "status": (
            "candidate manifest frozen in B01 ($0 offline); live paid execution "
            "deferred to Session B02 under strict <= US$10.00 upper-bound ceiling"
        ),
        "source": {
            k: sources[k]
            for k in ("head", "branch", "source_roots", "tracked_diff_sha256", "dirty_paths")
        },
        "source_manifest_sha256": _file_hash(source_manifest_path),
        "definition": rel_def,
        "definition_sha256": _file_hash(resolved_def),
        "payload_path": str((inputs_dir / "burmish.payload.json")),
        "payload_sha256": input_hashes["burmish.payload.json"],
        "tones_preserved": True,
        "question": (
            "On real CLDF Burmish (maruic, burmic, proto_burmish; 54 root concepts, "
            "37 Old Burmese proxy concepts, morpheme-sliced cog:* units, and 4 contrastive "
            "tone categories kept 100% intact), how does gemini/gemini-3.8-flash "
            "(medium thinking, max_tokens=32768, --tied-confidence-threshold 0.5, "
            "--compaction-watermark-tokens 256000) perform against pre-R01 banked Gemini "
            "sweeps and deterministic ceilings on both symbol-exact/NED metrics and R06 "
            "corpus-wide phonological+tonal contrast preservation?"
        ),
        "inputs": input_hashes,
        "price_table": {
            "source_path": "examples/pricing/gemini-3.8-flash.price-table.json",
            "sha256": table_sha,
            "entry": json.loads(price.model_dump_json()),
        },
        "evaluator_versions": {
            "task02": "task02-v1",
            "units": "task04-units-v1",
            "evidence_contract": "units-v2",
            "forward_contrast": "r06-forward-v1",
            "critic": CRITIC_EVALUATOR_VERSION,
            "critic_audit_mode": "real_run_provenance_v1",
            "ledger": LEDGER_VERSION,
            "usage_accounting": "abrupt-loss-v1",
        },
        "model_visible": {
            "instructions_sha256": _hash_text(instructions),
            "packaged_instructions_sha256": _hash_text(instructions),
            **behavioural_digests("stored-hypothesis", None),
            "first_request_maruic": first_node_prompt(
                payload,
                instructions,
                "stored-hypothesis",
                GATE_NODE_ID,
                tied_confidence_threshold=TIED_CONFIDENCE_THRESHOLD,
            ),
            "downstream_requests": (
                "burmic uses leaf beams; proto_burmish depends on committed maruic and burmic beams"
            ),
        },
        "native_profile": "stored-hypothesis",
        "runtime_upgrades": {
            "tied_confidence_threshold": TIED_CONFIDENCE_THRESHOLD,
            "compaction_watermark_tokens": COMPACTION_WATERMARK_TOKENS,
            "local_qwen_reserved_watermark_tokens": LOCAL_QWEN_WATERMARK_TOKENS,
        },
        "trials": 1,
        "replication": "single staged checkpointed run (Stage 1 maruic gate -> Stage 2 --resume); no automatic reruns or seeds",
        "budget_ceiling": {
            "hard_upper_bound_usd": HARD_COST_CEILING_USD,
            "stage1_cost_cap_usd": STAGE1_CAPS["max_total_cost_usd"],
            "stage2_cumulative_cost_cap_usd": STAGE2_CUMULATIVE_CAPS["max_total_cost_usd"],
            "one_response_headroom_usd": stage2_bound["one_response_headroom_usd"],
            "worst_case_cumulative_upper_bound_usd": stage2_bound["worst_case_upper_bound_usd"],
            "within_10_usd_hard_ceiling": stage2_bound["within_10_usd_hard_ceiling"],
            "expected_actual_cached_spend_usd_range": [1.80, 2.80],
            "hard_wall_seconds": HARD_WALL_CEILING_SECONDS,
            "stage2_cumulative_max_run_seconds": STAGE2_CUMULATIVE_CAPS["max_run_seconds"],
        },
        "arm": {
            ARM_NAME: {
                "model": MODEL,
                "preset": PRESET,
                "harness_model": HARNESS_MODEL,
                "reasoning_effort": REASONING_EFFORT,
                "temperature": TEMPERATURE,
                "timeout": TIMEOUT_SECONDS,
                "max_output_tokens": MAX_OUTPUT_TOKENS,
                "tied_confidence_threshold": TIED_CONFIDENCE_THRESHOLD,
                "compaction_watermark_tokens": COMPACTION_WATERMARK_TOKENS,
                "shared_run_dir": str(target_run),
                "run_id": RUN_ID,
                "stage1_maruic_gate": {
                    "caps": STAGE1_CAPS,
                    "resources": stage1_bound,
                    "argv": s1_argv,
                    "driver_argv": [
                        "{python}",
                        str(ROOT / "tools/real_family_benchmark_probe.py"),
                        "run-stage1",
                        "--experiment-dir",
                        str(experiment_dir),
                    ],
                },
                "gate_stage1": {
                    "cost_usd": 0.0,
                    "checks": [
                        "maruic in checkpoint.steps_by_node",
                        "not step.diagnostics.failure_fallback",
                        "latest maruic trajectory completed with committed_reconstruction",
                        "inspect_run and audit_run_directory executed offline ($0)",
                    ],
                    "driver_argv": [
                        "{python}",
                        str(ROOT / "tools/real_family_benchmark_probe.py"),
                        "gate-stage1",
                        "--experiment-dir",
                        str(experiment_dir),
                    ],
                },
                "stage2_full_tree_resume": {
                    "requires_stage1_gate_usable": True,
                    "resumes_shared_checkpoint": str(target_run / "checkpoint.json"),
                    "caps": STAGE2_CUMULATIVE_CAPS,
                    "resources": stage2_bound,
                    "argv": s2_argv,
                    "driver_argv": [
                        "{python}",
                        str(ROOT / "tools/real_family_benchmark_probe.py"),
                        "run-stage2-resume",
                        "--experiment-dir",
                        str(experiment_dir),
                    ],
                },
                "evaluate": {
                    "cost_usd": 0.0,
                    "driver_argv": [
                        "{python}",
                        str(ROOT / "tools/real_family_benchmark_probe.py"),
                        "evaluate",
                        "--experiment-dir",
                        str(experiment_dir),
                    ],
                },
            }
        },
        "dataset": BURMISH_DATASET_SUMMARY,
        "deterministic_ceilings_tones_intact": DETERMINISTIC_CEILINGS_TONES_INTACT,
        "pre_r01_banked_sweeps": PRE_R01_BANKED_SWEEPS,
        "pre_r01_critic_audit_baselines": critic_baselines,
    }

    manifest_path = experiment_dir / "manifest.b02-burmish.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {
        "manifest_path": str(manifest_path),
        "manifest_sha256": _file_hash(manifest_path),
        "source_manifest_sha256": manifest["source_manifest_sha256"],
        "inputs": input_hashes,
        "budget_ceiling": manifest["budget_ceiling"],
        "model_visible": manifest["model_visible"],
    }


def _append_batch_event(experiment_dir: Path, record: Mapping[str, Any]) -> None:
    experiment_dir.mkdir(parents=True, exist_ok=True)
    with (experiment_dir / EVENTS_FILE).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"recorded_at": _now(), **record}, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _read_batch_events(experiment_dir: Path) -> list[dict[str, Any]]:
    path = experiment_dir / EVENTS_FILE
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def compute_cached_adjusted_cost_usd(
    resources: RunResources,
    price_table_path: Path | None = None,
) -> dict[str, Any]:
    """Compute cached-adjusted USD spend alongside the uncached `pricing.py` upper bound."""
    resolved_table = price_table_path or GEMINI_PRICE_TABLE
    if not resolved_table.exists():
        resolved_table = GEMINI_PRICE_TABLE
    table, table_sha = load_price_table(resolved_table)
    price = price_for(table, HARNESS_MODEL, date.today())

    cached_tokens = int(resources.cached_input_tokens or 0)
    uncached_input_tokens = max(0, int(resources.input_tokens) - cached_tokens)
    cached_rate = float(price.cached_input_usd_per_million or 0.0)
    cached_adjusted_known = (
        uncached_input_tokens * price.input_usd_per_million
        + cached_tokens * cached_rate
        + int(resources.output_tokens) * price.output_usd_per_million
    ) / 1_000_000
    cache_hit_rate = (
        (cached_tokens / resources.input_tokens) if resources.input_tokens > 0 else 0.0
    )
    return {
        "price_table_sha256": table_sha,
        "input_usd_per_million": price.input_usd_per_million,
        "cached_input_usd_per_million": cached_rate,
        "output_usd_per_million": price.output_usd_per_million,
        "input_tokens": resources.input_tokens,
        "cached_input_tokens": cached_tokens,
        "uncached_input_tokens": uncached_input_tokens,
        "output_tokens": resources.output_tokens,
        "reasoning_output_tokens": resources.reasoning_output_tokens,
        "cache_hit_rate": round(cache_hit_rate, 6),
        "uncached_table_known_cost_usd": round(resources.known_cost_usd, 6),
        "uncached_table_total_cost_usd": (
            round(resources.total_cost_usd, 6) if resources.total_cost_usd is not None else None
        ),
        "cached_adjusted_known_cost_usd": round(cached_adjusted_known, 6),
        "cached_adjusted_total_cost_usd": (
            round(cached_adjusted_known, 6) if resources.cost_known else None
        ),
    }


def write_batch_ledger(
    experiment_dir: Path,
    *,
    run_dir: Path | None = None,
) -> dict[str, Any]:
    """Certify the single shared checkpointed run via `read_run_resources` and write `batch_ledger.json`."""
    experiment_dir = experiment_dir.resolve()
    target_run = (run_dir or default_run_dir(experiment_dir)).resolve()
    resources = read_run_resources(target_run)
    events = _read_batch_events(experiment_dir)
    stage_walls = [
        float(ev["wall_seconds"])
        for ev in events
        if ev.get("run_dir") == str(target_run)
        and ev.get("event") in ("stage1_finished", "stage2_finished")
        and isinstance(ev.get("wall_seconds"), (int, float))
    ]
    if not resources.present:
        wall_seconds, wall_known = 0.0, True
    elif stage_walls:
        wall_seconds, wall_known = sum(stage_walls), True
    else:
        wall_seconds, wall_known = resources.elapsed_seconds, False

    gate_data = None
    if (target_run / GATE_FILE).exists():
        try:
            gate_data = json.loads((target_run / GATE_FILE).read_text(encoding="utf-8")).get(
                "stage_gate"
            )
        except (OSError, ValueError):
            gate_data = None

    price_table_path = experiment_dir / "inputs" / "price-table.json"
    cost_breakdown = compute_cached_adjusted_cost_usd(resources, price_table_path)
    totals = batch_totals([(ARM_NAME, resources)])
    for bucket in (totals["overall"], totals["arms"].setdefault(ARM_NAME, totals["overall"])):
        bucket["wall_seconds"] = wall_seconds
        bucket["wall_known"] = wall_known
        bucket["ledger_errors"] = 0
        bucket["cached_adjusted_known_cost_usd"] = cost_breakdown["cached_adjusted_known_cost_usd"]
        bucket["cached_adjusted_total_cost_usd"] = cost_breakdown["cached_adjusted_total_cost_usd"]

    ledger = {
        "ledger_version": LEDGER_VERSION,
        "written_at": _now(),
        "ceilings": {
            ARM_NAME: {
                "cost_usd": HARD_COST_CEILING_USD,
                "stage2_cumulative_cap_usd": STAGE2_CUMULATIVE_CAPS["max_total_cost_usd"],
                "wall_seconds": HARD_WALL_CEILING_SECONDS,
            }
        },
        "trials": [
            {
                "trial_id": RUN_ID,
                "arm": ARM_NAME,
                "run_dir": str(target_run),
                "wall_seconds": wall_seconds,
                "wall_known": wall_known,
                "stage_gate": gate_data,
                "resources": resources.as_dict(),
                "cost_breakdown": cost_breakdown,
            }
        ],
        "totals": totals,
        "ledger_errors": [],
    }
    ledger_path = experiment_dir / LEDGER_FILE
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = ledger_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp_path.replace(ledger_path)
    return ledger


def _run_logged_subprocess(argv: Sequence[str], *, cwd: Path, run_dir: Path, prefix: str) -> int:
    run_dir.mkdir(parents=True, exist_ok=True)
    with (
        (run_dir / f"{prefix}stdout.log").open("ab") as out,
        (run_dir / f"{prefix}stderr.log").open("ab") as err,
    ):
        return subprocess.run(list(argv), cwd=cwd, stdout=out, stderr=err, check=False).returncode


def run_stage1(
    experiment_dir: Path = DEFAULT_EXPERIMENT_DIR,
    *,
    run_dir: Path | None = None,
    payload_path: Path | None = None,
    dry_run: bool = False,
    extra_infer_args: Sequence[str] = (),
) -> dict[str, Any]:
    """Launch Stage 1 (`--stop-after-node maruic`) into a clean shared `run_dir`."""
    experiment_dir = experiment_dir.resolve()
    target_run = (run_dir or default_run_dir(experiment_dir)).resolve()
    if target_run.exists() and any(target_run.iterdir()):
        reason = f"run_dir_not_empty: {target_run} already contains artifacts"
        if not dry_run:
            _append_batch_event(
                experiment_dir,
                {
                    "event": "stage1_refused",
                    "trial_id": RUN_ID,
                    "arm": ARM_NAME,
                    "run_dir": str(target_run),
                    "reason": reason,
                },
            )
        return {"launched": False, "refused": True, "reason": reason, "run_dir": str(target_run)}

    argv = stage1_argv(
        experiment_dir,
        run_dir=target_run,
        payload_path=payload_path,
        python_executable=sys.executable,
        extra_args=extra_infer_args,
    )
    if dry_run:
        return {"launched": False, "dry_run": True, "run_dir": str(target_run), "argv": argv}

    _append_batch_event(
        experiment_dir,
        {
            "event": "stage1_started",
            "trial_id": RUN_ID,
            "arm": ARM_NAME,
            "run_dir": str(target_run),
            "argv": argv,
        },
    )
    t0 = time.monotonic()
    rc = _run_logged_subprocess(argv, cwd=ROOT, run_dir=target_run, prefix="stage1.")
    wall = time.monotonic() - t0
    _append_batch_event(
        experiment_dir,
        {
            "event": "stage1_finished",
            "trial_id": RUN_ID,
            "arm": ARM_NAME,
            "run_dir": str(target_run),
            "exit_code": rc,
            "wall_seconds": round(wall, 4),
        },
    )
    ledger = write_batch_ledger(experiment_dir, run_dir=target_run)
    return {
        "launched": True,
        "exit_code": rc,
        "wall_seconds": round(wall, 4),
        "run_dir": str(target_run),
        "ledger": ledger,
    }


def gate_stage1(
    run_dir: Path | None = None,
    *,
    experiment_dir: Path = DEFAULT_EXPERIMENT_DIR,
    payload: WorkbenchPayload | None = None,
    gate_node_id: str = GATE_NODE_ID,
) -> dict[str, Any]:
    """Audit Stage 1 (`$0` `inspect_run` + `audit_run_directory`) and write `gate_stage1.json`."""
    from cognate_reconstruction.evaluation.critic import audit_run_directory

    experiment_dir = experiment_dir.resolve()
    target_run = (run_dir or default_run_dir(experiment_dir)).resolve()
    if payload is None:
        payload, _, _ = load_benchmark_payload(None, experiment_dir=experiment_dir)

    inspect_text, _ = inspect_run(target_run)
    (target_run / "inspect_stage1.txt").write_text(inspect_text, encoding="utf-8")

    critic_report = audit_run_directory(target_run, payload=payload)
    checkpoint_path = target_run / "checkpoint.json"
    checkpoint = CheckpointStore(checkpoint_path).load() if checkpoint_path.exists() else None
    summary_path = target_run / "run_summary.json"
    run_summary = (
        json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    )
    trajectories = (
        list(TrajectoryDatasetBuilder.read_jsonl(target_run / "trajectories.jsonl"))
        if (target_run / "trajectories.jsonl").exists()
        else []
    )
    gate_trajs = [t for t in trajectories if t.node_id == gate_node_id]
    latest_traj = gate_trajs[-1] if gate_trajs else None

    step = checkpoint.steps_by_node.get(gate_node_id) if checkpoint is not None else None
    in_checkpoint = step is not None
    not_fallback = bool(step is not None and not step.diagnostics.failure_fallback)
    traj_committed = bool(
        latest_traj is not None
        and latest_traj.completed
        and latest_traj.committed_reconstruction is not None
    )
    usable = in_checkpoint and not_fallback and traj_committed
    if not in_checkpoint:
        reason = f"{gate_node_id} missing from checkpoint.steps_by_node"
    elif not not_fallback:
        reason = f"{gate_node_id} fell back to identity reconstruction"
    elif not traj_committed:
        reason = f"{gate_node_id} trajectory did not complete with a model commitment"
    else:
        reason = f"{gate_node_id} committed cleanly without fallback"

    peak_input_tokens = max(
        (
            r.usage.input_tokens
            for t in gate_trajs
            for r in t.provider_responses
            if r.usage is not None and r.usage.input_tokens is not None
        ),
        default=None,
    )
    resources = read_run_resources(target_run)
    price_table_path = experiment_dir / "inputs" / "price-table.json"
    cost_breakdown = compute_cached_adjusted_cost_usd(resources, price_table_path)

    gate_payload: dict[str, Any] = {
        "gate_version": "b02-stage1-gate-v1",
        "evaluated_at": _now(),
        "run_dir": str(target_run),
        "gate_node_id": gate_node_id,
        "usable": usable,
        "stage_gate": {"usable": usable, "reason": reason},
        "checks": {
            "in_checkpoint_steps": in_checkpoint,
            "not_failure_fallback": not_fallback,
            "trajectory_committed": traj_committed,
        },
        "diagnostics": {
            "unaccounted_column_rate": (
                step.diagnostics.unaccounted_column_rate if step is not None else None
            ),
            "unaccounted_column_count": (
                step.diagnostics.unaccounted_column_count if step is not None else None
            ),
            "assembled_column_count": (
                step.diagnostics.assembled_column_count if step is not None else None
            ),
            "committed_set_count": (
                step.diagnostics.committed_set_count if step is not None else None
            ),
            "proto_phoneme_count": (
                step.diagnostics.proto_phoneme_count if step is not None else None
            ),
            "turns": latest_traj.metrics.turn_count if latest_traj is not None else 0,
            "tool_calls": latest_traj.metrics.tool_call_count if latest_traj is not None else 0,
            "failed_tool_calls": (
                latest_traj.metrics.failed_tool_call_count if latest_traj is not None else 0
            ),
            "compacted_tool_results": (
                latest_traj.metrics.compacted_tool_results if latest_traj is not None else 0
            ),
            "peak_prompt_input_tokens": peak_input_tokens,
            "compaction": run_summary.get("compaction"),
        },
        "critic_audit": {
            "total_defect_count": critic_report.get("total_defect_count", 0),
            "defect_counts_by_category": critic_report.get("defect_counts_by_category", {}),
            "node_audit": (critic_report.get("nodes") or {}).get(gate_node_id),
            "defects": [
                d for d in critic_report.get("defects", ()) if d.get("node_id") == gate_node_id
            ],
        },
        "resources": resources.as_dict(),
        "cost_breakdown": cost_breakdown,
        "inspect_report_path": str(target_run / "inspect_stage1.txt"),
    }
    (target_run / GATE_FILE).write_text(
        json.dumps(gate_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_batch_ledger(experiment_dir, run_dir=target_run)
    return gate_payload


def run_stage2_resume(
    experiment_dir: Path = DEFAULT_EXPERIMENT_DIR,
    *,
    run_dir: Path | None = None,
    payload_path: Path | None = None,
    dry_run: bool = False,
    require_gate: bool = True,
    extra_infer_args: Sequence[str] = (),
) -> dict[str, Any]:
    """Resume the Stage 1 checkpoint directory through `burmic` and `proto_burmish`."""
    experiment_dir = experiment_dir.resolve()
    target_run = (run_dir or default_run_dir(experiment_dir)).resolve()

    if (target_run / "result.json").exists():
        reason = f"already_completed: {target_run / 'result.json'} already exists"
        return {"launched": False, "refused": True, "reason": reason, "run_dir": str(target_run)}
    if not (target_run / "checkpoint.json").exists():
        reason = f"checkpoint_missing: {target_run / 'checkpoint.json'} does not exist"
        return {"launched": False, "refused": True, "reason": reason, "run_dir": str(target_run)}

    if require_gate:
        gate_path = target_run / GATE_FILE
        if not gate_path.exists():
            reason = f"stage1_gate_missing: run gate-stage1 first ({gate_path})"
            return {"launched": False, "refused": True, "reason": reason, "run_dir": str(target_run)}
        gate_data = json.loads(gate_path.read_text(encoding="utf-8"))
        if gate_data.get("usable") is not True:
            why = (gate_data.get("stage_gate") or {}).get("reason", "unusable")
            reason = f"stage1_gate_not_usable: {why}"
            if not dry_run:
                _append_batch_event(
                    experiment_dir,
                    {
                        "event": "stage2_refused",
                        "trial_id": RUN_ID,
                        "arm": ARM_NAME,
                        "run_dir": str(target_run),
                        "reason": reason,
                    },
                )
            return {"launched": False, "refused": True, "reason": reason, "run_dir": str(target_run)}

    prior_resources = read_run_resources(target_run)
    if not prior_resources.cost_known:
        reason = (
            f"stage1_cost_unknown: {prior_resources.unknown_cost_requests} request(s) of unknown cost"
        )
        return {"launched": False, "refused": True, "reason": reason, "run_dir": str(target_run)}
    if prior_resources.known_cost_usd >= STAGE2_CUMULATIVE_CAPS["max_total_cost_usd"]:
        reason = (
            f"stage2_cap_exhausted: prior spend ${prior_resources.known_cost_usd:.4f} "
            f">= ${STAGE2_CUMULATIVE_CAPS['max_total_cost_usd']:.2f}"
        )
        return {"launched": False, "refused": True, "reason": reason, "run_dir": str(target_run)}

    argv = stage2_resume_argv(
        experiment_dir,
        run_dir=target_run,
        payload_path=payload_path,
        python_executable=sys.executable,
        extra_args=extra_infer_args,
    )
    if dry_run:
        return {"launched": False, "dry_run": True, "run_dir": str(target_run), "argv": argv}

    _append_batch_event(
        experiment_dir,
        {
            "event": "stage2_started",
            "trial_id": RUN_ID,
            "arm": ARM_NAME,
            "run_dir": str(target_run),
            "argv": argv,
        },
    )
    t0 = time.monotonic()
    rc = _run_logged_subprocess(argv, cwd=ROOT, run_dir=target_run, prefix="stage2.")
    wall = time.monotonic() - t0
    _append_batch_event(
        experiment_dir,
        {
            "event": "stage2_finished",
            "trial_id": RUN_ID,
            "arm": ARM_NAME,
            "run_dir": str(target_run),
            "exit_code": rc,
            "wall_seconds": round(wall, 4),
        },
    )
    ledger = write_batch_ledger(experiment_dir, run_dir=target_run)
    return {
        "launched": True,
        "exit_code": rc,
        "wall_seconds": round(wall, 4),
        "run_dir": str(target_run),
        "ledger": ledger,
    }


def compute_r06_contrast_by_target(eval_report) -> dict[str, dict[str, Any]]:
    """Compute R06 full-form `compute_corpus_contrast_equivalence` per target node (tones intact)."""
    out: dict[str, dict[str, Any]] = {}
    for target in eval_report.targets:
        evaluation = target.evaluation
        concept_ids = [c.concept_id for c in evaluation.concepts]
        inferred_forms = {c.concept_id: c.top_candidate_segments for c in evaluation.concepts}
        reference_forms = {
            c.concept_id: (
                c.nearest_target_segments
                if c.nearest_target_segments is not None
                else (
                    c.target_segment_alternatives[0] if c.target_segment_alternatives else None
                )
            )
            for c in evaluation.concepts
        }
        contrast = compute_corpus_contrast_equivalence(
            inferred_forms, reference_forms, concept_ids
        )
        tone_in_ref = any(
            seg is not None and bool(TONE_TOKEN_PATTERN.search(seg))
            for form in reference_forms.values()
            if form is not None
            for seg in form
        )
        tone_in_inf = any(
            seg is not None and bool(TONE_TOKEN_PATTERN.search(seg))
            for form in inferred_forms.values()
            if form is not None
            for seg in form
        )
        out[target.node_id] = {
            "target_validity": (
                evaluation.target_validity.value if evaluation.target_validity else None
            ),
            "output_kind": target.output_kind,
            "evaluated_concept_count": contrast["evaluated_concept_count"],
            "corpus_bcubed_precision": contrast["corpus_bcubed_precision"],
            "corpus_bcubed_recall": contrast["corpus_bcubed_recall"],
            "corpus_bcubed_f1": contrast["corpus_bcubed_f1"],
            "is_bijective_relabelling": contrast["is_bijective_relabelling"],
            "tone_tokens_in_reference": tone_in_ref,
            "tone_tokens_in_inferred": tone_in_inf,
        }
    return out


def counterfactual_assembly_replay(
    run_dir: Path,
    payload: WorkbenchPayload,
    *,
    beam_width: int = BEAM_WIDTH,
    anchor_policy: AnchorPolicy | str | None = None,
    anchor_match_factor: float | None = None,
    anchors_by_node: Mapping[str, Sequence[LexicalForm]] | None = None,
) -> dict[str, Any]:
    """$0 offline replay of saved node commits under `tied_confidence_threshold=None` vs `0.5`."""
    dataset = ingest_payload(payload)
    root = parse_newick(dataset.tree.newick)
    ids = assign_node_ids(root)
    lex_by_id = {lex.variety_id: lex for lex in dataset.lexicons}

    active_anchors: dict[str, list[LexicalForm]] = {}
    for binding in dataset.historical_form_bindings:
        if binding.role is HistoricalFormRole.ANCHOR:
            active_anchors.setdefault(binding.node_id, []).extend(binding.forms)
    for nid, forms in (anchors_by_node or {}).items():
        active_anchors.setdefault(nid, []).extend(forms)

    result_raw = load_result_or_summary(run_dir)
    summary_path = run_dir / "run_summary.json"
    run_summary = (
        json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    )
    cfg = run_summary.get("configuration") if isinstance(run_summary, dict) else None
    resolved_anchor_policy = AnchorPolicy(
        anchor_policy
        if anchor_policy is not None
        else (cfg.get("anchor_policy") if isinstance(cfg, dict) and cfg.get("anchor_policy") else AnchorPolicy.ADVISORY)
    )
    resolved_anchor_factor = float(
        anchor_match_factor
        if anchor_match_factor is not None
        else (cfg.get("anchor_match_factor") if isinstance(cfg, dict) and cfg.get("anchor_match_factor") is not None else 100.0)
    )

    checkpoint = (
        CheckpointStore(run_dir / "checkpoint.json").load()
        if (run_dir / "checkpoint.json").exists()
        else None
    )
    live_steps: dict[str, ReconstructionStep] = {}
    for raw_step in ((result_raw or {}).get("snapshot") or {}).get("steps", ()):
        step = step_from_artifact(raw_step)
        live_steps[step.parent_node_id] = step
    if checkpoint is not None:
        for node_id, step in checkpoint.steps_by_node.items():
            live_steps.setdefault(node_id, step)

    trajectories = (
        list(TrajectoryDatasetBuilder.read_jsonl(run_dir / "trajectories.jsonl"))
        if (run_dir / "trajectories.jsonl").exists()
        else []
    )
    latest_committed = {
        t.node_id: t.committed_reconstruction
        for t in trajectories
        if t.completed and t.committed_reconstruction is not None
    }

    aligner = LingPyAligner()
    leaf_beams = {
        ids[id(leaf)]: make_leaf_beam(lex_by_id[leaf.label], beam_width=beam_width)
        for leaf in root.get_leaves()
    }
    source_unit_scopes = {
        piece.unit_id
        for lex in dataset.lexicons
        for form in lex.forms
        for analysis in source_analyses(form)
        for piece in analysis.pieces
    }
    regimes: dict[str, dict[str, ReconstructionStep]] = {}
    rebound_by_regime: dict[str, dict[str, dict[str, Any]]] = {}
    for label, threshold in (("single_winner_none", None), ("tied_beam_0_5", 0.5)):
        asm = ProtoInventoryAssembler(
            beam_width=beam_width,
            anchor_policy=resolved_anchor_policy,
            anchor_match_factor=resolved_anchor_factor,
            aligner=aligner,
            tied_confidence_threshold=threshold,
        )
        rule_rec = RuleBasedReconstructor(
            beam_width=beam_width,
            anchor_policy=resolved_anchor_policy,
            anchor_match_factor=resolved_anchor_factor,
            aligner=aligner,
        )
        beams = dict(leaf_beams)
        steps_out: dict[str, ReconstructionStep] = {}
        rebound_nodes: dict[str, dict[str, Any]] = {}
        for children, parent in postorder_groups(root):
            node_id = ids[id(parent)]
            child_ids = tuple(ids[id(c)] for c in children)
            if any(cid not in beams for cid in child_ids):
                continue
            child_beams = tuple(beams[cid] for cid in child_ids)
            node_anchors = tuple(active_anchors.get(node_id, ()))
            committed = latest_committed.get(node_id)
            if isinstance(committed, CommittedProtoInventory):
                replay_inventory = committed
                if committed.evidence_contract_version == "units-v2":
                    reading, _ = evidence_map(
                        tuple(beam_to_lexicon(b) for b in child_beams),
                        aligner,
                        unit_orders=committed.request.unit_orders,
                        overlay_ids=(
                            committed.request.segmentation_overlay_id,
                            committed.request.alignment_overlay_id,
                        ),
                    )
                    if reading.evidence_revision != committed.evidence_revision:
                        new_bindings = column_bindings(reading, child_ids)
                        live_child_beams = tuple(
                            live_steps[cid].output_beam if cid in live_steps else leaf_beams[cid]
                            for cid in child_ids
                            if cid in live_steps or cid in leaf_beams
                        )
                        live_scopes: set[str | None] = set()
                        if len(live_child_beams) == len(child_ids):
                            live_reading, _ = evidence_map(
                                tuple(beam_to_lexicon(b) for b in live_child_beams),
                                aligner,
                                unit_orders=committed.request.unit_orders,
                                overlay_ids=(
                                    committed.request.segmentation_overlay_id,
                                    committed.request.alignment_overlay_id,
                                ),
                            )
                            live_scopes.update(
                                col.scope_id
                                for aln in live_reading.alignments
                                for col in aln.evidence_columns
                            )
                        all_scopes = (
                            {
                                col.scope_id
                                for aln in reading.alignments
                                for col in aln.evidence_columns
                            }
                            | {getattr(b, "scope_id", None) for b in committed.column_bindings}
                            | live_scopes
                            | {u for uo in committed.request.unit_orders for u in uo.unit_ids}
                            | source_unit_scopes
                            | {"whole:unknown", None}
                        )
                        old_to_new_set_id: dict[str, str] = {}
                        for comm in committed.request.commitments:
                            for sc in all_scopes:
                                candidate_old = unit_set_id(
                                    comm.reflexes,
                                    sc,
                                    tuple(child_ids),
                                    committed.evidence_revision,
                                )
                                if candidate_old == comm.set_id:
                                    old_to_new_set_id[comm.set_id] = unit_set_id(
                                        comm.reflexes,
                                        sc,
                                        tuple(child_ids),
                                        reading.evidence_revision,
                                    )
                                    break
                        rebound_commitments = tuple(
                            comm.model_copy(
                                update={
                                    "set_id": old_to_new_set_id[comm.set_id],
                                    "merges_with_set_id": (
                                        old_to_new_set_id.get(
                                            comm.merges_with_set_id,
                                            comm.merges_with_set_id,
                                        )
                                        if comm.merges_with_set_id is not None
                                        else None
                                    ),
                                }
                            )
                            for comm in committed.request.commitments
                            if comm.set_id in old_to_new_set_id
                        )
                        rebound_shared_claims = tuple(
                            claim.model_copy(
                                update={
                                    "member_set_ids": tuple(
                                        old_to_new_set_id.get(sid, sid)
                                        for sid in claim.member_set_ids
                                    )
                                }
                            )
                            for claim in committed.approved_shared_claims
                        )
                        replay_inventory = CommittedProtoInventory.model_validate_json(
                            committed.model_copy(
                                update={
                                    "evidence_revision": reading.evidence_revision,
                                    "column_bindings": new_bindings,
                                    "approved_shared_claims": rebound_shared_claims,
                                    "request": committed.request.model_copy(
                                        update={"commitments": rebound_commitments}
                                    ),
                                }
                            ).model_dump_json()
                        )
                        rebound_nodes[node_id] = {
                            "original_evidence_revision": committed.evidence_revision,
                            "rebound_evidence_revision": reading.evidence_revision,
                            "rebound_set_id_map": dict(old_to_new_set_id),
                            "rebound_merges_with_pairs": [
                                {
                                    "set_id": c.set_id,
                                    "merges_with_set_id": c.merges_with_set_id,
                                }
                                for c in replay_inventory.request.commitments
                                if c.merges_with_set_id is not None
                            ],
                        }
                step = asm.reconstruct(
                    node_id,
                    child_beams,
                    inventory=replay_inventory,
                    anomalies=replay_inventory.request.anomalies,
                    anchors=node_anchors,
                )
            elif committed is not None:
                step = rule_rec.reconstruct(
                    node_id,
                    child_beams,
                    rules=committed.parsed_rules,
                    anomalies=committed.request.anomalies,
                    anchors=node_anchors,
                )
            elif node_id in live_steps:
                step = rule_rec.reconstruct(node_id, child_beams, anchors=node_anchors)
            else:
                continue
            steps_out[node_id] = step
            beams[node_id] = step.output_beam
        regimes[label] = steps_out
        rebound_by_regime[label] = rebound_nodes

    regime_summaries: dict[str, Any] = {}
    for label, steps_map in regimes.items():
        synthetic_result = {
            "snapshot": {
                "steps": [
                    s.model_dump(mode="json", exclude_computed_fields=True)
                    for s in steps_map.values()
                ]
            }
        }
        rep = evaluate_run(payload, synthetic_result, trajectories=())
        r06 = compute_r06_contrast_by_target(rep)
        regime_summaries[label] = {
            "nodes_replayed": sorted(steps_map),
            "rebound_nodes": rebound_by_regime[label],
            "validated_target_summary": rep.validated_target_summary.model_dump(mode="json"),
            "raw_target_summary": rep.raw_target_summary.model_dump(mode="json"),
            "targets": {
                t.node_id: {
                    "top_exact_matches": t.evaluation.top_exact_matches,
                    "beam_exact_matches": t.evaluation.beam_exact_matches,
                    "evaluated_concepts": t.evaluation.evaluated_concepts,
                    "top_exact_rate": t.evaluation.top_exact_rate,
                    "beam_exact_rate": t.evaluation.beam_exact_rate,
                    "mean_top_ned": (
                        t.evaluation.graded.top_normalized_edit_distance.mean
                        if t.evaluation.graded
                        and t.evaluation.graded.top_normalized_edit_distance
                        else None
                    ),
                    "r06_contrast": r06.get(t.node_id),
                }
                for t in rep.targets
            },
            "multi_candidate_concept_counts": {
                nid: sum(1 for d in step.output_beam.distributions if len(d.candidates) > 1)
                for nid, step in steps_map.items()
            },
        }

    node_deltas: dict[str, Any] = {}
    for nid in sorted(set(regimes["single_winner_none"]) & set(regimes["tied_beam_0_5"])):
        s_none = regimes["single_winner_none"][nid]
        s_tied = regimes["tied_beam_0_5"][nid]
        dist_none = {d.concept_id: d for d in s_none.output_beam.distributions}
        dist_tied = {d.concept_id: d for d in s_tied.output_beam.distributions}
        common = sorted(set(dist_none) & set(dist_tied))
        top_changed = [
            cid
            for cid in common
            if dist_none[cid].candidates[0].segments != dist_tied[cid].candidates[0].segments
        ]
        beam_changed = [
            cid
            for cid in common
            if [c.segments for c in dist_none[cid].candidates]
            != [c.segments for c in dist_tied[cid].candidates]
        ]
        committed_obj = latest_committed.get(nid)
        low_conf_count = (
            sum(1 for c in committed_obj.request.commitments if c.confidence <= 0.5)
            if isinstance(committed_obj, CommittedProtoInventory)
            else 0
        )
        live_matches_tied = (
            live_steps[nid].output_beam.model_dump(mode="json")
            == s_tied.output_beam.model_dump(mode="json")
            if nid in live_steps
            else None
        )
        node_deltas[nid] = {
            "low_confidence_le_0_5_commitments": low_conf_count,
            "top_candidate_changed_concepts": top_changed,
            "beam_candidates_changed_concepts": beam_changed,
            "live_beam_matches_tied_0_5_replay": live_matches_tied,
        }

    return {
        "replay_cost_usd": 0.0,
        "regimes": regime_summaries,
        "node_deltas": node_deltas,
    }


def evaluate_benchmark_run(
    run_dir: Path | None = None,
    *,
    experiment_dir: Path = DEFAULT_EXPERIMENT_DIR,
    payload: WorkbenchPayload | None = None,
) -> dict[str, Any]:
    """Full `$0` post-run evaluation: critic, `task02-v1`, `R06` contrast, replay & ledger."""
    from cognate_reconstruction.evaluation.critic import audit_run_directory

    experiment_dir = experiment_dir.resolve()
    target_run = (run_dir or default_run_dir(experiment_dir)).resolve()
    if payload is None:
        payload, _, _ = load_benchmark_payload(None, experiment_dir=experiment_dir)
    if not _has_tone_tokens(payload):
        raise ValueError("Evaluation payload must preserve tone tokens intact")

    result_raw = load_result_or_summary(target_run)
    trajectories = (
        list(TrajectoryDatasetBuilder.read_jsonl(target_run / "trajectories.jsonl"))
        if (target_run / "trajectories.jsonl").exists()
        else []
    )
    summary_path = target_run / "run_summary.json"
    run_summary = (
        json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    )

    task02_report = evaluate_run(payload, result_raw, trajectories)
    r06_contrast = compute_r06_contrast_by_target(task02_report)
    critic_report = audit_run_directory(target_run, payload=payload)
    replay_report = counterfactual_assembly_replay(target_run, payload)
    ledger = write_batch_ledger(experiment_dir, run_dir=target_run)
    resources = read_run_resources(target_run)
    cost_breakdown = compute_cached_adjusted_cost_usd(
        resources, experiment_dir / "inputs" / "price-table.json"
    )

    per_node_curves: dict[str, Any] = {}
    for traj in trajectories:
        resp_inputs = [
            r.usage.input_tokens
            for r in traj.provider_responses
            if r.usage is not None and r.usage.input_tokens is not None
        ]
        resp_cached = [
            r.usage.cached_input_tokens
            for r in traj.provider_responses
            if r.usage is not None and r.usage.cached_input_tokens is not None
        ]
        per_node_curves[traj.node_id] = {
            "trajectory_id": traj.trajectory_id,
            "completed": traj.completed,
            "turns": traj.metrics.turn_count,
            "tool_calls": traj.metrics.tool_call_count,
            "failed_tool_calls": traj.metrics.failed_tool_call_count,
            "compacted_tool_results": traj.metrics.compacted_tool_results,
            "peak_input_tokens": max(resp_inputs) if resp_inputs else None,
            "total_input_tokens": sum(resp_inputs) if resp_inputs else 0,
            "total_cached_input_tokens": sum(resp_cached) if resp_cached else 0,
            "fits_96k_local_qwen_watermark": (
                (max(resp_inputs) <= LOCAL_QWEN_WATERMARK_TOKENS) if resp_inputs else None
            ),
        }

    usable = (
        task02_report.run_status == "finished"
        and len(task02_report.completed_node_ids) == 3
    )
    report: dict[str, Any] = {
        "evaluation_version": "b02-real-family-eval-v1",
        "evaluated_at": _now(),
        "run_dir": str(target_run),
        "tones_preserved": True,
        "stage_gate": {
            "usable": usable,
            "reason": (
                "all 3 Burmish internal nodes committed without fallback"
                if usable
                else f"run_status={task02_report.run_status}"
            ),
        },
        "runtime_metadata": {
            "tied_confidence_threshold": run_summary.get("tied_confidence_threshold"),
            "compaction_watermark_tokens": run_summary.get("compaction_watermark_tokens"),
            "compaction": run_summary.get("compaction"),
            "effective_run_caps": run_summary.get("effective_run_caps"),
        },
        "task02_evaluation": task02_report.model_dump(mode="json"),
        "r06_corpus_contrast_equivalence": r06_contrast,
        "critic_audit": critic_report,
        "counterfactual_tied_beam_replay": replay_report,
        "per_node_prompt_cache_profile": per_node_curves,
        "resources": resources.as_dict(),
        "cost_breakdown": cost_breakdown,
        "batch_ledger_path": str(experiment_dir / LEDGER_FILE),
    }
    (target_run / EVALUATION_FILE).write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    fr = sub.add_parser(
        "freeze",
        help="Write frozen B02 inputs, source_manifest.json, and manifest.b02-burmish.json",
    )
    fr.add_argument("--experiment-dir", type=Path, default=DEFAULT_EXPERIMENT_DIR)
    fr.add_argument("--definition", type=Path, default=BURMISH_DEFINITION)

    s1 = sub.add_parser(
        "run-stage1",
        help="Launch Stage 1 (maruic gate: --stop-after-node maruic, $3.50 / 1500s)",
    )
    s1.add_argument("--experiment-dir", type=Path, default=DEFAULT_EXPERIMENT_DIR)
    s1.add_argument("--run-dir", type=Path)
    s1.add_argument("--payload", type=Path)
    s1.add_argument("--dry-run", action="store_true")

    g1 = sub.add_parser(
        "gate-stage1",
        help="Run $0 inspect_run + audit_run_directory on Stage 1 and write gate_stage1.json",
    )
    g1.add_argument("--experiment-dir", type=Path, default=DEFAULT_EXPERIMENT_DIR)
    g1.add_argument("--run-dir", type=Path)
    g1.add_argument("--definition", type=str)

    s2 = sub.add_parser(
        "run-stage2-resume",
        help="Resume Stage 1 checkpoint (--resume) through burmic + proto_burmish ($8.50 / 3600s)",
    )
    s2.add_argument("--experiment-dir", type=Path, default=DEFAULT_EXPERIMENT_DIR)
    s2.add_argument("--run-dir", type=Path)
    s2.add_argument("--payload", type=Path)
    s2.add_argument("--dry-run", action="store_true")

    ev = sub.add_parser(
        "evaluate",
        help="Run $0 full evaluation (critic, task02-v1, R06 contrast, replay, certified ledger)",
    )
    ev.add_argument("--experiment-dir", type=Path, default=DEFAULT_EXPERIMENT_DIR)
    ev.add_argument("--run-dir", type=Path)
    ev.add_argument("--definition", type=str)

    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    if args.command == "freeze":
        out = freeze(args.experiment_dir, definition=args.definition)
        print(json.dumps(out, indent=2))
    elif args.command == "run-stage1":
        out = run_stage1(
            args.experiment_dir,
            run_dir=args.run_dir,
            payload_path=args.payload,
            dry_run=args.dry_run,
        )
        print(json.dumps(out, indent=2))
        if out.get("refused") or (out.get("launched") and out.get("exit_code", 0) != 0):
            raise SystemExit(1)
    elif args.command == "gate-stage1":
        payload = (
            load_benchmark_payload(args.definition, experiment_dir=args.experiment_dir)[0]
            if args.definition
            else None
        )
        out = gate_stage1(args.run_dir, experiment_dir=args.experiment_dir, payload=payload)
        print(json.dumps(out["stage_gate"], indent=2))
        if not out["usable"]:
            raise SystemExit(1)
    elif args.command == "run-stage2-resume":
        out = run_stage2_resume(
            args.experiment_dir,
            run_dir=args.run_dir,
            payload_path=args.payload,
            dry_run=args.dry_run,
        )
        print(json.dumps(out, indent=2))
        if out.get("refused") or (out.get("launched") and out.get("exit_code", 0) != 0):
            raise SystemExit(1)
    elif args.command == "evaluate":
        payload = (
            load_benchmark_payload(args.definition, experiment_dir=args.experiment_dir)[0]
            if args.definition
            else None
        )
        out = evaluate_benchmark_run(
            args.run_dir, experiment_dir=args.experiment_dir, payload=payload
        )
        print(
            json.dumps(
                {
                    "stage_gate": out["stage_gate"],
                    "r06_corpus_contrast_equivalence": out["r06_corpus_contrast_equivalence"],
                    "critic_total_defects": out["critic_audit"].get("total_defect_count"),
                    "cost_breakdown": out["cost_breakdown"],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
