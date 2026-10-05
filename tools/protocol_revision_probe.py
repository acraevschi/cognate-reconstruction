"""Offline saved-call replay and immutable-hypothesis controls; no provider requests."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tools import _bootstrap  # noqa: F401

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.instructions import load_agent_instructions
from cognate_reconstruction.agent.orchestrator import AgentOrchestrator
from cognate_reconstruction.agent.reconstructor import AgenticNodeReconstructor
from cognate_reconstruction.agent.schemas import (
    LLMMessage, LLMToolCall, MessageRole, COMMIT_REQUIREMENT_NOTES,
    NodePromptPayload, NodeLexiconSummary, ConceptHoldout,
)
from cognate_reconstruction.agent.service import ReconstructionService
from cognate_reconstruction.agent.tools import default_tool_registry
from cognate_reconstruction.agent.tools.inventory_evidence import node_inventory
from cognate_reconstruction.agent.trajectory import JsonlTrajectorySink
from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.evaluation.run import evaluate_run, trajectory_from_artifact
from cognate_reconstruction.ingestion import ingest_payload
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.synthesis.diagnostics import build_case, load_suite
from tools.evidence_repair_controls import MorphologyProvider

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/protocol_revision"


def fixture_context():
    payload = WorkbenchPayload.model_validate_json((FIXTURES / "observed_input.json").read_text())
    # Only observed input, no targets/answer keys/target annotations.
    assert not payload.historical_form_bindings
    return AgentContext(node_id="burmic", child_lexicons=payload.lexicons,
        concepts=payload.concepts, aligner=LingPyAligner())


def replay_saved_calls():
    saved = json.loads((FIXTURES / "task03_rejections.json").read_text())
    ctx = fixture_context()
    inventory, _ = node_inventory(ctx, segmentation_overlay_id=None, alignment_overlay_id=None)
    def key(row):
        return row["scope_id"], tuple(row["segments"]), tuple(row["example_concept_ids"])
    current = {key(s.model_dump(mode="json")): s.set_id for s in inventory.sets}
    ids = {s["set_id"]: current[key(s)] for s in saved["saved_local_sets"]}
    rows = []
    for row in saved["calls"]:
        # Exact saved arguments first: older semantic IDs are deliberately not accepted.
        raw = default_tool_registry(inventory_protocol="full-payload").execute(
            LLMToolCall(call_id=row["call_id"], name=row["name"], arguments=row["arguments"]), ctx)
        # Rebind ONLY harness IDs through exact saved scope/reflex/concept identity.
        # Wrong tuples, missing linguistic values and malformed fields stay wrong.
        args = json.loads(json.dumps(row["arguments"]))
        target = args.get("inventory", args)
        for item in target.get("commitments", []):
            item["set_id"] = ids[item["set_id"]]
        result = default_tool_registry(inventory_protocol="full-payload").execute(
            LLMToolCall(call_id="rebound-" + row["call_id"], name=row["name"], arguments=args), ctx)
        assert not raw.ok and not result.ok
        rows.append({"call_id": row["call_id"], "saved_code": row["saved_error_code"],
            "exact_replay_code": raw.error.code, "rebound_code": result.error.code})
    return rows


class StoredMorphologyProvider(MorphologyProvider):
    model = "scripted/task05-stored-morphology"

    def complete(self, messages, tools, **kwargs):
        reply = super().complete(messages, tools, **kwargs)
        old = reply.tool_calls[0]
        args = dict(old.arguments)
        if old.name == "test_proto_assembly":
            args["choices"] = [{k: v for k, v in c.items() if k not in {"reflexes", "support"}}
                for c in args.pop("commitments")]
        elif old.name == "commit_reconstruction":
            preview = json.loads(next(m.content for m in reversed(messages)
                if m.role is MessageRole.TOOL and m.name == "test_proto_assembly"))["result"]
            assert preview["executable"] and preview["commit_ready"]
            args.pop("inventory")
            args["hypothesis_id"] = preview["hypothesis_id"]
        return LLMMessage(role=MessageRole.ASSISTANT, tool_calls=(LLMToolCall(
            call_id=old.call_id, name=old.name, arguments=args),))


def stored_controls(output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    suite = load_suite(ROOT / "benchmarks/diagnostic/task02-v1.json")
    built = build_case(next(c for c in suite["cases"] if c["case_id"] == "morphology"))
    payload = built.payload.model_copy(update={"newick": "((a,b)x,c)p;"})
    rows = []
    for mode in ("correct", "wrong", "extra", "missing", "reordered"):
        path = output_dir / (mode + ".jsonl")
        if path.exists():
            raise ValueError("choose a fresh output directory; do not append controls to old trajectories")
        service = ReconstructionService(AgenticNodeReconstructor(AgentOrchestrator(
            StoredMorphologyProvider(payload, mode), trajectory_sink=JsonlTrajectorySink(path),
            instructions=load_agent_instructions(), run_id="task05-" + mode,
            configuration_sha256="scripted-task05-" + mode)))
        result = service.reconstruct_family(ingest_payload(payload))
        trajectories = tuple(trajectory_from_artifact(json.loads(line)) for line in path.read_text().splitlines())
        report = evaluate_run(payload, json.loads(result.model_dump_json(exclude_computed_fields=True)), trajectories)
        assert all(t.completed and t.metrics.protocol_failure_count == 0 for t in trajectories)
        root = report.targets[0].evaluation
        rows.append({"mode": mode, "raw_exact": root.top_exact_matches,
            "completed_nodes": [t.node_id for t in trajectories],
            "validated_planned": report.validated_target_summary.planned_concepts,
            "concepts": [{"concept_id": c.concept_id, "diagnostics": c.token_diagnostics.model_dump(mode="json")}
                for c in root.concepts]})
    return rows


def size(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return {"characters": len(text), "utf8_bytes": len(text.encode()),
        "sha256": hashlib.sha256(text.encode()).hexdigest()}


def payload_sizes():
    return {"instructions": size(load_agent_instructions()), "commit_notes": size(COMMIT_REQUIREMENT_NOTES),
        "tool_definitions": {p: size([d.model_dump(mode="json") for d in
            default_tool_registry(inventory_protocol=p).definitions()])
            for p in ("full-payload", "stored-hypothesis")},
        "interpretation": "Serialized character/UTF-8 sizes, not model-independent token counts."}


def measure_saved_payloads():
    """Measure the unchanged node and saved eleven-choice hypothesis, without a model."""
    ctx = fixture_context()
    node = NodePromptPayload(node_id=ctx.node_id, active_children=tuple(
        NodeLexiconSummary(node_id=l.variety_id, name=l.name, form_count=len(l.forms),
            concept_count=len({f.concept_id for f in l.forms})) for l in ctx.child_lexicons),
        anchor_policy=ctx.anchor_policy, anchors=ctx.anchors,
        concept_holdout=ConceptHoldout(development_concept_ids=ctx.concept_split.development_concept_ids,
            held_out_concept_ids=ctx.concept_split.held_out_concept_ids,
            held_out_share=ctx.concept_split.held_out_share), commit_requirements=COMMIT_REQUIREMENT_NOTES)
    result = payload_sizes()
    result["node_payload"] = size(node.model_dump_json(indent=2))
    result["combined"] = {p: {k: result["instructions"][k] + result["node_payload"][k] + s[k]
        for k in ("characters", "utf8_bytes")} for p, s in result["tool_definitions"].items()}
    saved = json.loads((FIXTURES / "task03_rejections.json").read_text())
    full = saved["saved_executable_preview"]
    compact = {**full, "choices": [{k: v for k, v in c.items() if k not in {"reflexes", "support"}}
        for c in full["commitments"]]}
    compact.pop("commitments")
    inventory, _ = node_inventory(ctx, segmentation_overlay_id=None, alignment_overlay_id=None)
    key = lambda s: (s["scope_id"], tuple(s["segments"]), tuple(s["example_concept_ids"]))
    current = {key(s.model_dump(mode="json")): s.set_id for s in inventory.sets}
    ids = {s["set_id"]: current[key(s)] for s in saved["saved_local_sets"]}
    ready = json.loads(json.dumps(compact))
    for c in ready["choices"]:
        c.update(set_id=ids[c["set_id"]],
            rationale="operator transcription control; no historical endorsement",
            directionality_rationale="operator control; available observations do not establish unique polarity")
    registry = default_tool_registry()
    preview = registry.execute(LLMToolCall(call_id="cost-preview", name="test_proto_assembly", arguments=ready), ctx)
    assert preview.ok and preview.result["commit_ready"], preview.error
    terminal = {"node_id": ctx.node_id, "hypothesis_id": preview.result["hypothesis_id"],
        "anomalies": [], "summary": "operator transcription control; saved values unchanged, not a quality claim"}
    committed = registry.execute(LLMToolCall(call_id="cost-commit", name="commit_reconstruction", arguments=terminal), ctx)
    assert committed.ok, committed.error
    spec = ctx.commit.request.model_dump(mode="json")
    full_commit = {"node_id": ctx.node_id, "inventory": {k: v for k, v in spec.items()
        if k not in {"node_id", "summary", "anomalies", "segmentation_overlay_id"}},
        "summary": terminal["summary"], "anomalies": []}
    result["saved_call_costs"] = {"unready_saved_preview": size(full),
        "same_decisions_compact_preview": size(compact), "ready_operator_preview": size(ready),
        "ready_full_commit": size(full_commit), "ready_handle_commit": size(terminal),
        "expanded_commitments": len(ctx.commit.request.commitments),
        "interpretation": "Saved values unchanged; raw preview was unready. Operator explanations only in labelled transcription control, not new model decisions."}
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--measure-only", action="store_true", help="Only sizes and a saved-call transcription control; no two-level controls.")
    args = parser.parse_args()
    if args.measure_only:
        print(json.dumps(measure_saved_payloads(), indent=2))
    else:
        if args.output_dir is None:
            parser.error("--output-dir is required for the two-level controls")
        print(json.dumps({"version": "task05-offline-v1", "live_model_calls": 0,
            "saved_calls": replay_saved_calls(), "sizes": payload_sizes(),
            "stored_controls": stored_controls(args.output_dir)}, indent=2))
