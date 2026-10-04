"""Offline frozen unit repair controls; never a live-model quality claim."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import tracemalloc
from pathlib import Path

import _bootstrap  # noqa: F401

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.tools.inventory_evidence import node_inventory
from cognate_reconstruction.agent.tools.proto_assembly import assemble_node
from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.schemas.beam import NodeBeamState
from cognate_reconstruction.schemas.inventory import CommittedProtoInventory, CorrespondenceCommitment, ProtoInventorySpec, ResiduePolicy, ConceptAssemblyReport
from cognate_reconstruction.schemas.lexicon import LanguageLexicon
from cognate_reconstruction.traversal.assembler import ProtoInventoryAssembler
from cognate_reconstruction.evaluation.metrics import compare_to_nearest
from cognate_reconstruction.evaluation.diagnostics import partition


DEFAULT_FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/evidence_contract/burmic_units.json"


def run_probe(path=DEFAULT_FIXTURE):
    text = Path(path).read_text()
    fixture = json.loads(text)
    legacy = CommittedProtoInventory.model_validate_json(json.dumps(fixture["legacy_inventory"]))
    children = tuple(NodeBeamState.model_validate_json(json.dumps(b)) for b in fixture["legacy_inputs"])
    old = ProtoInventoryAssembler(beam_width=5).reconstruct(fixture["node_id"], children, inventory=legacy)
    old_forms = {d.concept_id: d.candidates[0].segments for d in old.output_beam.distributions}
    assert old_forms == {r["concept_id"]: tuple(r["assembled_segments"]) for r in fixture["legacy_reports"]}
    assert old.assembly_reports == tuple(ConceptAssemblyReport.model_validate_json(json.dumps(report))
                                       for report in fixture["legacy_reports"])
    values = {tuple(c.reflexes): c.proto_segment for c in legacy.request.commitments if c.conditioning is None}
    lexicons_by_id = {l["variety_id"]: LanguageLexicon.model_validate_json(json.dumps(l)) for l in fixture["lexicons"]}
    ctx = AgentContext(node_id=fixture["node_id"], child_lexicons=tuple(lexicons_by_id[c] for c in fixture["child_ids"]), aligner=LingPyAligner())
    tracemalloc.start()
    start = time.perf_counter()
    inventory, reading = node_inventory(ctx, segmentation_overlay_id=None, alignment_overlay_id=None)
    survey_seconds = time.perf_counter() - start
    # Explicit operator controls, fixed by supplied memberships rather than by
    # target spelling. They are not claims the banked model actually approved.
    core_ids = {"96": "cog:hillburmish:79", "239": "cog:hillburmish:7", "1382": "cog:hillburmish:930"}
    core_scopes = set(core_ids.values())
    commitments = []
    for item in inventory.sets:
        proto = None
        if item.scope_id in core_scopes:
            proto = values.get(item.segments, item.segments[1])
        commitments.append(CorrespondenceCommitment(set_id=item.set_id, reflexes=item.segments,
            proto_segment=proto, support=item.support, confidence=.9,
            rationale="offline source-unit control: preserve shared core; delete other units",
            directionality_rationale="operator hypothesis, not inferred historical polarity"))
    spec = ProtoInventorySpec(child_node_ids=ctx.child_ids, commitments=tuple(commitments), residue_policy=ResiduePolicy.DROP)
    start = time.perf_counter()
    step, committed = assemble_node(ctx, spec, node_id=ctx.node_id, segmentation_overlay_id=None)
    execution_seconds = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    after = {d.concept_id: d.candidates[0] for d in step.output_beam.distributions}
    rows = []
    for concept in fixture["concept_ids"]:
        report = next(r for r in step.assembly_reports if r.concept_id == concept)
        rows.append({"concept_id": concept, "legacy_top": old_forms[concept],
            "units_control_top": after[concept].segments,
            "analysis": after[concept].analysis.model_dump(mode="json"),
            "approved_unit_for_control": core_ids[concept],
            "core_columns": [c.model_dump(mode="json") for c in report.columns if c.unit_id == core_ids[concept]],
            "legacy_columns": next(r for r in fixture["legacy_reports"] if r["concept_id"] == concept)})
    # Reference material is read only after execution. It never participates
    # in the unit control, source analysis, node context or typed tools.
    reference_path = Path(path).with_name(Path(path).stem + ".references.json")
    if reference_path.exists():
        references = json.loads(reference_path.read_text())
        targets = {c["concept_id"]: c["alternatives"] for c in references["concepts"]}
        for row in rows:
            alternatives = targets.get(row["concept_id"])
            if not alternatives:
                continue
            readings = {}
            for label, tokens in (("legacy", row["legacy_top"]), ("unit_control", row["units_control_top"])):
                raw = compare_to_nearest(tokens, alternatives)
                stripped = compare_to_nearest(partition(tokens)[0], [partition(target)[0] for target in alternatives])
                readings[label] = {"raw_exact": raw.exact, "raw_ned": raw.normalized_edit_distance,
                                   "segment_edit_distance": stripped.edit_distance, "segment_ned": stripped.normalized_edit_distance}
            row["post_execution_reference_reading"] = {"node_id": references["node_id"],
                "validity": references["validity"], "alternatives": alternatives, "readings": readings}
    return {"version": "task04-source-controls-v1", "evidence_contract": "units-v2", "evaluator_version": "task02-v1",
        "fixture_sha256": hashlib.sha256(text.encode()).hexdigest(), "source_sha256": fixture["source_sha256"],
        "live_model_calls": 0, "note": "Legacy replay is exact. New outputs are explicit source-unit controls, with old values transferred only within the selected core and witness values elsewhere in that core. No gold enters contexts; no historical quality claim.",
        "cost": {"survey_seconds": survey_seconds, "execution_seconds": execution_seconds,
                 "peak_traced_bytes": peak, "set_count": len(inventory.sets), "bindings": len(committed.column_bindings),
                 "assembly_work": step.diagnostics.assembly_work.model_dump(mode="json")}, "concepts": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run_probe(args.fixture)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for row in result["concepts"]:
            print(row["concept_id"], " ".join(row["legacy_top"]), "→", " ".join(row["units_control_top"]))
        print(json.dumps(result["cost"]))


if __name__ == "__main__":
    main()
