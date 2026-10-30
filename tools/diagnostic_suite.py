#!/usr/bin/env python3
"""Generate task02-v1 cases and offline perfect/identity/wrong score controls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import _bootstrap  # noqa: F401

from cognate_reconstruction.agent.orchestrator import AgentOrchestrator
from cognate_reconstruction.agent.reconstructor import AgenticNodeReconstructor
from cognate_reconstruction.agent.schemas import LLMMessage, LLMToolCall, MessageRole
from cognate_reconstruction.agent.service import ReconstructionService
from cognate_reconstruction.evaluation.diagnostics import compare_cognate_units, pieces
from cognate_reconstruction.alignment.units import source_analyses
from cognate_reconstruction.evaluation.run import evaluate_run
from cognate_reconstruction.ingestion import ingest_payload
from cognate_reconstruction.schemas.beam import (
    ConceptCandidateDistribution, NodeBeamState, ReconstructionCandidate,
)
from cognate_reconstruction.synthesis.diagnostics import build_case, load_suite


class IdentityProvider:
    """Offline protocol baseline; no model service is called."""
    model = "scripted/identity"

    def complete(self, messages, tools, **kwargs):
        content = messages[1].content
        node = json.loads(content[content.index("{"):])["node_id"]
        return LLMMessage(role=MessageRole.ASSISTANT, tool_calls=(LLMToolCall(
            call_id="identity", name="commit_reconstruction", arguments={
                "node_id": node, "rules": [], "anomalies": [],
                "summary": "Offline identity baseline.",
            },
        ),))


def score_controls(built):
    result = ReconstructionService(AgenticNodeReconstructor(AgentOrchestrator(
        IdentityProvider(), run_id="offline-diagnostic", configuration_sha256="scripted",
    ))).reconstruct_family(ingest_payload(built.payload))
    reports = {"identity": result.evaluation_report}
    # These are metric fixtures, explicitly not model reconstructions. Generated
    # gold is read only here, after the scripted baseline has finished.
    bindings = {b.node_id: b for b in built.payload.historical_form_bindings}
    for label in ("perfect_fixture", "wrong_fixture"):
        steps = []
        for step in result.snapshot.steps:
            binding = bindings.get(step.parent_node_id)
            if binding is None:
                steps.append(step)
                continue
            distributions = tuple(ConceptCandidateDistribution(
                concept_id=form.concept_id, candidates=(ReconstructionCandidate(
                    candidate_id=f"fixture:{label}:{form.form_id}",
                    segments=form.segments if label == "perfect_fixture" else ("WRONG",),
                    probability=1.0, log_score=0.0, derivations=(),
                    analysis=source_analyses(form)[0] if label == "perfect_fixture" else None,
                ),),
            ) for form in binding.forms)
            steps.append(step.model_copy(update={"output_beam": NodeBeamState(
                node_id=binding.node_id, distributions=distributions, beam_width=1,
            )}))
        # Completion facts are scripted fixture labels here. They are never
        # written as model trajectories or used to claim live quality.
        scripted = [t.model_copy(update={"reconstruction_step": next(
            s for s in steps if s.parent_node_id == t.node_id
        )}) for t in result.trajectories]
        reports[label] = evaluate_run(built.payload, {"snapshot": {"steps": steps}}, scripted)
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--definition", type=Path, default=Path(__file__).resolve().parents[1] / "benchmarks/diagnostic/synthetic-diagnostic-suite-v1.json")
    parser.add_argument("--output-dir", type=Path, help="Write separate runnable payloads and answer keys")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    suite = load_suite(args.definition)
    outputs = []
    for case in suite["cases"]:
        built = build_case(case)
        if args.output_dir:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            (args.output_dir / f"{case['case_id']}.json").write_text(built.payload.model_dump_json(indent=2))
            answer = {"generated_truth": built.answer_key.model_dump(mode="json"),
                      "evaluation_notes": {k: v for k, v in case.items() if k != "family"}}
            (args.output_dir / f"{case['case_id']}.answer-key.json").write_text(json.dumps(answer, indent=2))
        controls = score_controls(built)
        row = {"case_id": case["case_id"], "identifiability": case["identifiability"],
               "controls": {label: {
                   "raw": report.raw_target_summary.model_dump(mode="json"),
                   "validated": report.validated_target_summary.model_dump(mode="json"),
                   "by_node": [{"node_id": t.node_id, "exact": t.evaluation.top_exact_matches,
                                "planned": t.evaluation.evaluated_concepts,
                                "selection": t.evaluation.selection.model_dump(mode="json")}
                               for t in report.targets],
               } for label, report in controls.items()}}
        if "target_unit_layouts" in case:
            from evidence_repair_controls import run_controls
            from tempfile import TemporaryDirectory
            with TemporaryDirectory(prefix="task04-normal-morphology-") as control_dir:
                row["normal_unit_controls"] = run_controls(control_dir)
            row["piece_control"] = []
            binding = built.payload.historical_form_bindings[0]
            for form in binding.forms:
                units = list(zip(case["target_unit_layouts"][form.concept_id], pieces(form.segments), strict=True))
                row["piece_control"].append({"concept_id": form.concept_id,
                    "perfect": compare_cognate_units(units, units),
                    "reordered_extra": compare_cognate_units(list(reversed(units)) + [("extra", ("z", "a"))], units),
                    "wrong": compare_cognate_units([(key, ("WRONG",)) for key, _ in units], units)})
        outputs.append(row)
    result = {"evaluator_version": "task02-v1", "live_model_calls": 0,
              "note": "Perfect/wrong are scoring fixtures; identity uses a scripted provider. Not live mechanism performance.",
              "cases": outputs}
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for row in outputs:
            print(row["case_id"], row["identifiability"])
            for label, control in row["controls"].items():
                s = control["raw"]
                print(f"  {label}: {s['output_top_hits']}/{s['planned_concepts']} raw; "
                      f"{control['validated']['planned_concepts']} validated planned")


if __name__ == "__main__":
    main()
