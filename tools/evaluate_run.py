#!/usr/bin/env python3
"""Read-only task02-v1 evaluator for finished and abandoned run directories."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from cognate_reconstruction.agent.trajectory import AgentTrajectory, TrajectoryDatasetBuilder
from cognate_reconstruction.evaluation.run import load_result_or_summary, evaluate_run, render_text, trajectory_from_artifact
from cognate_reconstruction.schemas.benchmark import BenchmarkDefinition
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--payload", required=True, type=Path, help="Frozen planned payload")
    parser.add_argument("--definition", type=Path, help="Explicit binding annotations for legacy payloads; no rebuild")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = WorkbenchPayload.model_validate_json(args.payload.read_text())
    selection_provenance = None
    if args.definition:
        definition = BenchmarkDefinition.model_validate_json(args.definition.read_text())
        selection_provenance = {
            "definition": str(args.definition),
            "concept_selection": definition.concept_selection.value,
            "selection_source_variety_id": definition.selection_source_variety_id,
            "uses_target_cognacy": definition.concept_selection.value == "fully_cognate_with_target",
            "note": "Declared recipe metadata; frozen payload is not rebuilt or reselected.",
        }
        annotations = {(t.node_id, t.source_variety_id): t for t in definition.targets}
        bindings = []
        for b in payload.historical_form_bindings:
            target = annotations.get((b.node_id, b.source_variety_id))
            bindings.append(b.model_copy(update={
                "target_validity": target.target_validity,
                "target_validity_note": target.target_validity_note,
            }) if target else b)
        payload = payload.model_copy(update={"historical_form_bindings": tuple(bindings)})
    reports = []
    for run_dir in args.run_dirs:
        if run_dir.is_file():
            run_dir = run_dir.parent
        result_path = run_dir / "result.json"
        result = load_result_or_summary(run_dir)
        trajectories_path = run_dir / "trajectories.jsonl"
        trajectories = (tuple(TrajectoryDatasetBuilder.read_jsonl(trajectories_path))
                        if trajectories_path.exists() else tuple(
                            # Some banked results embed trajectories without JSONL.
                            trajectory_from_artifact(t)
                            for t in (result or {}).get("trajectories", ())
                        ))
        report = evaluate_run(payload, result, trajectories, selection_provenance=selection_provenance)
        if (run_dir / "VOID.txt").exists() or (run_dir.parent / "VOID.txt").exists():
            report = report.model_copy(update={"linguistic_exclusion_reason": "operator_marked_void"})
        reports.append({"run_dir": str(run_dir), "report": report.model_dump(mode="json"),
                        "saved_historical_target_evaluations": (result or {}).get("historical_target_evaluations")})
        if not args.json:
            print(f"Run: {run_dir}\n{render_text(report)}")
    if args.json:
        print(json.dumps({"evaluator_version": "task02-v1", "runs": reports}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
