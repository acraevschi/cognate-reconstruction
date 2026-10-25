#!/usr/bin/env python3
"""R02 Stage A/B instruments: payloads, scripted controls, measurement, evaluation.

Every provider here is scripted and offline. The Stage A operator executes the
supplied hypothesis exactly (the reference behaviour a live model is compared
with). Stage B operators are baselines: identity, fixed daughters, union,
intersection, the deployable outgroup-witness rule, and a gold-assisted oracle
that is a scorer control, never a baseline. None is a model result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tools import _bootstrap  # noqa: F401

from cognate_reconstruction.agent.instructions import load_agent_instructions
from cognate_reconstruction.agent.orchestrator import AgentOrchestrator
from cognate_reconstruction.agent.reconstructor import AgenticNodeReconstructor
from cognate_reconstruction.agent.schemas import LLMMessage, LLMToolCall, MessageRole
from cognate_reconstruction.agent.service import ReconstructionService
from cognate_reconstruction.agent.tools import default_tool_registry
from cognate_reconstruction.agent.trajectory import JsonlTrajectorySink, TrajectoryDatasetBuilder
from cognate_reconstruction.evaluation.decisions import score_decisions, stage_b_instructions
from cognate_reconstruction.evaluation.run import (
    evaluate_run, load_result_or_summary, step_from_artifact, trajectory_from_artifact,
)
from cognate_reconstruction.evaluation.usability import check_stage_a, stage_a_instructions
from cognate_reconstruction.ingestion import ingest_payload
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.synthesis.diagnostics import build_explicit_case, load_explicit_case
from cognate_reconstruction.traversal.checkpoint import CheckpointStore

ROOT = Path(__file__).resolve().parents[1]
STAGE_A = ROOT / "benchmarks/diagnostic/r02-stage-a-v1.json"
STAGE_B = ROOT / "benchmarks/diagnostic/r02-stage-b-v1.json"
PROTOCOLS = ("stored-hypothesis", "full-payload")
SURVEY_LIMIT = 200


def _node(prompt: str) -> str:
    return re.search(r'"node_id":\s*"([^"]+)"', prompt).group(1)


def _children(prompt: str) -> list[str]:
    payload = json.loads(prompt[prompt.index("{"):])
    return [child["node_id"] for child in payload["active_children"]]


class Scripted:
    """Shared plumbing: one tool call per turn, every tool result must be ok."""

    model = "scripted/r02"

    def complete(self, messages, tools, **kwargs):
        prompt = messages[1].content
        results = [json.loads(m.content) for m in messages if m.role is MessageRole.TOOL]
        for outcome in results:
            if not outcome.get("ok"):
                raise AssertionError(f"scripted control met a refusal: {outcome}")
        name, arguments = self.next_call(_node(prompt), prompt, [r.get("result") or {} for r in results])
        return LLMMessage(role=MessageRole.ASSISTANT, tool_calls=(LLMToolCall(
            call_id=f"{_node(prompt)}-{len(results)}", name=name, arguments=arguments),))

    def next_call(self, node, prompt, results):  # pragma: no cover - interface
        raise NotImplementedError


def _identity(node: str):
    return "commit_reconstruction", {"node_id": node, "rules": [], "anomalies": [],
                                     "summary": "Scripted identity commit; not a reconstruction claim."}


def _row(item, value, confidence, protocol, rationale, directionality=None, conditioning=None):
    row = {"set_id": item["set_id"], "proto_segment": value, "confidence": confidence,
           "rationale": rationale}
    if directionality:
        row["directionality_rationale"] = directionality
    if conditioning:
        row["conditioning"] = conditioning
    if protocol == "full-payload":
        row.update(reflexes=item["segments"], support=item["support"])
    return row


class StageAOperator(Scripted):
    """Executes the supplied Stage A hypothesis, its revision and the commit."""

    model = "scripted/r02-stage-a-operator"

    def __init__(self, case, protocol):
        self.spec = case["supplied_hypothesis"]
        self.protocol = protocol

    def hypothesis(self, patterns, local, revised):
        spec, protocol = self.spec, self.protocol
        shared = []
        for claim in spec["shared_claims"]:
            pattern = next(p for p in patterns if p["segments"] == claim["reflexes"])
            confidence = claim["confidence"]
            if revised and spec["revision"]["label"] == claim["label"]:
                confidence = spec["revision"]["to"]
            row = {"pattern_id": pattern["set_id"], "member_set_ids": pattern["member_set_ids"],
                   "proto_segment": claim["proto_segment"], "confidence": confidence,
                   "rationale": claim["rationale"]}
            for key in ("conditioning", "directionality_rationale"):
                if claim.get(key):
                    row[key] = claim[key]
            shared.append(row)
        rows = []
        for choice in spec["choices"]:
            item = next(s for s in local if s["scope_id"] == f"cog:{choice['unit']}"
                        and s["segments"] == choice["reflexes"])
            rows.append(_row(item, choice["proto_segment"], choice["confidence"], protocol,
                             choice["rationale"], choice.get("directionality_rationale")))
        key = "commitments" if protocol == "full-payload" else "choices"
        return {key: rows, "shared_claims": shared, "residue_policy": spec["residue_policy"],
                "residue_witness_child_id": spec["residue_witness_child_id"]}

    def next_call(self, node, prompt, results):
        if node != self.spec["node_id"]:
            return _identity(node)
        if not results:
            return "summarize_correspondences", {"reading": "recurrence", "min_support": 1, "limit": SURVEY_LIMIT}
        if len(results) == 1:
            return "summarize_correspondences", {"reading": "local", "min_support": 1, "limit": SURVEY_LIMIT}
        patterns, local = results[0]["sets"], results[1]["sets"]
        if len(results) in (2, 3):
            return "test_proto_assembly", self.hypothesis(patterns, local, revised=len(results) == 3)
        commit = {"node_id": node, "anomalies": [], "summary": "Supplied Stage A hypothesis, revised once."}
        if self.protocol == "full-payload":
            commit["inventory"] = {"child_node_ids": _children(prompt), **self.hypothesis(patterns, local, True)}
        else:
            commit["hypothesis_id"] = results[3]["hypothesis_id"]
        return "commit_reconstruction", commit


B_POLICIES = ("identity", "union", "intersection", "outgroup-witness", "oracle")
FIXED_DAUGHTERS = ("a", "b", "c")


class StageBBaseline(Scripted):
    """A fixed policy over the one-sided local sets at the scored node.

    `outgroup-witness` is the deployable evidence-only rule: keep one-sided
    material when the survey reports an outgroup witness in that exact column,
    otherwise null; a missing outgroup form counts as no witness. `oracle`
    reads the scorer's expected decisions and exists only to validate the
    scorer. The unscored root always gets an identity commit.
    """

    def __init__(self, case, policy, protocol="stored-hypothesis"):
        if policy not in B_POLICIES:
            raise ValueError(policy)
        self.case, self.policy, self.protocol = case, policy, protocol
        self.model = f"scripted/r02-stage-b-{policy}"
        self.node = case["opportunities"][0]["node_id"]

    def decide(self, item, witnesses):
        present = next(s for s in item["segments"] if s is not None)
        if self.policy == "union":
            return present
        if self.policy == "intersection":
            return None
        if self.policy == "outgroup-witness":
            return present if witnesses.get(item["set_id"]) else None
        scope = item["scope_id"] or ""
        unit = scope.split(":")[2] if scope.startswith("boundary:") else scope.removeprefix("cog:")
        concept = item["example_concept_ids"][0]
        expected = {o["unit"]: o["expected"] for o in self.case["opportunities"] if o["concept_id"] == concept}
        decision = expected.get(unit, "retain")
        return present if decision in ("retain", "unresolved") else None

    def next_call(self, node, prompt, results):
        if node != self.node or self.policy == "identity":
            return _identity(node)
        if not results:
            return "summarize_correspondences", {"reading": "local", "min_support": 1,
                                                  "limit": SURVEY_LIMIT, "include_outgroup": True}
        survey = results[0]
        witnesses = {row["set_id"]: [w for w in row["witnesses"] if w.get("segment")]
                     for row in survey.get("outgroup_reflexes", ())}
        rows = []
        for item in survey["sets"]:
            if None not in item["segments"] or all(s is None for s in item["segments"]):
                continue
            value = self.decide(item, witnesses)
            rows.append(_row(item, value, .7, self.protocol,
                             f"Scripted {self.policy} baseline; not a model decision.",
                             "Scripted baseline policy; polarity is the policy's assumption."))
        key = "commitments" if self.protocol == "full-payload" else "choices"
        hypothesis = {key: rows, "residue_policy": "retain_from_witness", "residue_witness_child_id": "a"}
        previews = [r for r in results if "hypothesis_id" in r]
        if not previews:
            return "test_proto_assembly", hypothesis
        commit = {"node_id": node, "anomalies": [], "summary": f"Scripted {self.policy} baseline."}
        if self.protocol == "full-payload":
            commit["inventory"] = {"child_node_ids": _children(prompt), **hypothesis}
        else:
            commit["hypothesis_id"] = previews[-1]["hypothesis_id"]
        return "commit_reconstruction", commit


def fixed_daughter_step(step, payload: WorkbenchPayload, variety: str):
    """The scored node's step with every output replaced by one daughter's form.

    A diagnostic copy baseline (the review's copyability check), built from
    observed forms with their source analyses; never a harness commitment.
    Concepts the daughter lacks have no output.
    """
    from cognate_reconstruction.alignment.units import source_analyses
    from cognate_reconstruction.schemas.beam import (
        ConceptCandidateDistribution, NodeBeamState, ReconstructionCandidate,
    )
    lexicon = next(l for l in payload.lexicons if l.variety_id == variety)
    distributions = tuple(ConceptCandidateDistribution(concept_id=form.concept_id, candidates=(
        ReconstructionCandidate(candidate_id=f"fixed-daughter:{form.form_id}", segments=form.segments,
                                probability=1.0, log_score=0.0, derivations=(),
                                analysis=source_analyses(form)[0]),)) for form in lexicon.forms)
    return step.model_copy(update={"output_beam": NodeBeamState(
        node_id=step.parent_node_id, distributions=distributions, beam_width=1), "assembly_reports": ()})


def run_scripted(payload: WorkbenchPayload, provider, *, protocol: str, instructions: str,
                 out_dir: Path | None = None, run_id: str = "r02-scripted"):
    """Run the ordinary service with JSONL and checkpoint; return result and artifacts."""
    sink_path = (out_dir / "trajectories.jsonl") if out_dir else None
    store = CheckpointStore(out_dir / "checkpoint.json") if out_dir else None
    if store is not None:
        from cognate_reconstruction.traversal.checkpoint import FamilyCheckpoint
        store.save(FamilyCheckpoint(run_id=run_id, input_sha256="scripted", configuration_sha256="scripted",
                                    normalized_tree_sha256="scripted"))
    service = ReconstructionService(AgenticNodeReconstructor(AgentOrchestrator(
        provider, registry=default_tool_registry(inventory_protocol=protocol),
        trajectory_sink=JsonlTrajectorySink(sink_path) if sink_path else None,
        instructions=instructions, run_id=run_id, configuration_sha256="scripted-" + run_id)))
    result = service.reconstruct_family(
        ingest_payload(payload),
        on_step_complete=(lambda step: store.save(store.load().with_step(step))) if store else None)
    if out_dir:
        (out_dir / "result.json").write_text(result.model_dump_json(exclude_computed_fields=True))
    return result


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def stage_a_instruction_file(case, protocol: str) -> str:
    return stage_a_instructions(case, protocol, load_agent_instructions())


def stage_b_instruction_file(case) -> str:
    return stage_b_instructions(case, load_agent_instructions())


def read_run_dir(run_dir: Path):
    """Result (or interruption summary), trajectories and checkpoint of one run."""
    result = load_result_or_summary(run_dir)
    trajectories = list(TrajectoryDatasetBuilder.read_jsonl(run_dir / "trajectories.jsonl")) \
        if (run_dir / "trajectories.jsonl").exists() else []
    checkpoint = CheckpointStore(run_dir / "checkpoint.json").load() if (run_dir / "checkpoint.json").exists() else None
    return result, trajectories, checkpoint


def _steps(result, checkpoint=None):
    """Committed steps by node: from the result, else the checkpoint.

    An interrupted run writes no result.json, but nodes committed before the
    stop are checkpointed and stay scorable.
    """
    raw = ((result or {}).get("snapshot") or {}).get("steps")
    if raw:
        return {step.parent_node_id: step for step in map(step_from_artifact, raw)}
    return dict(checkpoint.steps_by_node) if checkpoint is not None else {}


def readback_checks(node: str, result, trajectories, checkpoint) -> dict:
    """Do the committed hypothesis and beam agree across the run's artifacts?"""
    steps = _steps(result)
    latest = {t.node_id: t for t in trajectories}
    jsonl = latest.get(node)
    embedded = next((trajectory_from_artifact(t) for t in (result or {}).get("trajectories", ())
                     if t.get("node_id") == node), None)
    checkpoint_step = (checkpoint.steps_by_node.get(node) if checkpoint is not None else None)
    commit = lambda t: (t.committed_reconstruction.model_dump_json()
                        if t is not None and t.committed_reconstruction is not None else None)
    beam = lambda s: s.output_beam.model_dump_json() if s is not None else None
    return {
        "jsonl_commit_present": commit(jsonl) is not None,
        "jsonl_commit_matches_result": embedded is None or commit(jsonl) == commit(embedded),
        "checkpoint_beam_matches_result": checkpoint_step is not None and beam(checkpoint_step) == beam(steps.get(node)),
        "jsonl_step_matches_result": jsonl is not None and jsonl.reconstruction_step is not None
                                     and beam(jsonl.reconstruction_step) == beam(steps.get(node)),
    }


def evaluate_stage_a(case, run_dir: Path, protocol: str) -> dict:
    payload = build_explicit_case(case)
    node = case["supplied_hypothesis"]["node_id"]
    result, trajectories, checkpoint = read_run_dir(run_dir)
    latest = {t.node_id: t for t in trajectories}
    steps = _steps(result, checkpoint)
    readback = (readback_checks(node, result, trajectories, checkpoint)
                if result is not None and result.get("snapshot") else {"result_present": False})
    return check_stage_a(case, payload, latest.get(node), steps.get(node), protocol=protocol, readback=readback)


def evaluate_stage_b(case, run_dir: Path) -> dict:
    payload = build_explicit_case(case)
    result, trajectories, checkpoint = read_run_dir(run_dir)
    steps = _steps(result, checkpoint)
    latest = {t.node_id: t for t in trajectories}
    committed = {node: bool(t.completed and t.committed_reconstruction is not None) for node, t in latest.items()}
    decisions = score_decisions(case, steps, model_committed=committed)
    report = evaluate_run(payload, result, trajectories) if result is not None else None
    node = case["opportunities"][0]["node_id"]
    usable = bool(committed.get(node)) and not (node in steps and steps[node].diagnostics.failure_fallback)
    return {"stage": "B", "decisions": decisions,
            "run_status": (result or {}).get("status", "completed" if result else "no_result"),
            "task02_evaluation": report.model_dump(mode="json") if report is not None else None,
            "stage_gate": {"usable": usable, "reason": "scored node committed by the model" if usable
                           else "scored node not committed by the model"}}


def measure(case, payload, protocol: str, provider, instructions: str) -> dict:
    """Actual work, caps and model-visible sizes of one scripted session."""
    from cognate_reconstruction.alignment.units import (
        MAX_UNIT_TUPLES, MAX_NODE_TUPLES, MAX_PROJECTED_COLUMNS,
    )
    result = run_scripted(payload, provider, protocol=protocol, instructions=instructions)
    rows = []
    for trajectory in result.trajectories:
        tool_results = [m.content or "" for m in trajectory.messages if m.role is MessageRole.TOOL]
        surveys = [json.loads(c)["result"] for c in tool_results if '"local_set_count"' in c]
        rows.append({
            "node_id": trajectory.node_id,
            "system_chars": len(trajectory.messages[0].content or ""),
            "node_prompt_chars": len(trajectory.messages[1].content or ""),
            "tool_schema_chars": len(json.dumps([d.model_dump(mode="json") for d in trajectory.tool_definitions])),
            "max_tool_result_chars": max(map(len, tool_results), default=0),
            "transcript_chars_at_end": sum(len(m.content or "") + len(json.dumps(
                [c.arguments for c in m.tool_calls])) for m in trajectory.messages),
            "work": surveys[-1]["work"] if surveys else None,
            "local_set_count": surveys[-1]["local_set_count"] if surveys else None,
            "recurrence_pattern_count": surveys[-1]["recurrence_pattern_count"] if surveys else None,
            "committed": trajectory.completed,
        })
    return {"protocol": protocol, "caps": {"tuples_per_concept": MAX_UNIT_TUPLES,
                                           "tuples_per_node": MAX_NODE_TUPLES,
                                           "projected_columns": MAX_PROJECTED_COLUMNS},
            "sessions": rows}


def default_filter_coverage(payload, node_id: str) -> dict:
    """What a default min_support=2 recurrence survey shows of the local material."""
    from cognate_reconstruction.evaluation.usability import node_evidence
    inventory = node_evidence({}, payload, node_id)
    shown = {member for p in inventory.recurrence_patterns if p.support >= 2 for member in p.member_set_ids}
    occurrences = {s.set_id: s.occurrence_count for s in inventory.sets}
    one_sided = [s for s in inventory.sets if None in s.segments]
    return {"local_sets": len(inventory.sets), "recurrence_patterns": len(inventory.recurrence_patterns),
            "local_sets_in_default_patterns": len(shown),
            "occurrences": sum(occurrences.values()),
            "occurrences_in_default_patterns": sum(occurrences[s] for s in shown),
            "one_sided_local_sets": len(one_sided),
            "one_sided_in_default_patterns": sum(s.set_id in shown for s in one_sided),
            "concepts": len({c for s in inventory.sets for c in s.example_concept_ids})}


def controls() -> dict:
    """Stage A in both profiles and every Stage B baseline, scored as a live run would be."""
    from tempfile import TemporaryDirectory
    case_a, case_b = load_explicit_case(STAGE_A), load_explicit_case(STAGE_B)
    payload_a, payload_b = build_explicit_case(case_a), build_explicit_case(case_b)
    out = {"live_model_calls": 0, "stage_a": {}, "stage_b": {}}
    with TemporaryDirectory(prefix="r02-controls-") as tmp:
        for protocol in PROTOCOLS:
            run_dir = Path(tmp) / f"a-{protocol}"
            run_dir.mkdir()
            run_scripted(payload_a, StageAOperator(case_a, protocol), protocol=protocol,
                         instructions=stage_a_instruction_file(case_a, protocol), out_dir=run_dir)
            report = evaluate_stage_a(case_a, run_dir, protocol)
            out["stage_a"][protocol] = {"outcome": report["outcome"], "criteria": report["criteria"],
                                        "stage_gate": report["stage_gate"]}
        for policy in B_POLICIES:
            run_dir = Path(tmp) / f"b-{policy}"
            run_dir.mkdir()
            run_scripted(payload_b, StageBBaseline(case_b, policy), protocol="stored-hypothesis",
                         instructions=stage_b_instruction_file(case_b), out_dir=run_dir)
            report = evaluate_stage_b(case_b, run_dir)
            raw = report["task02_evaluation"]["raw_target_summary"]
            target = report["task02_evaluation"]["targets"][0]["evaluation"]
            out["stage_b"][policy] = {
                "primary_correct": report["decisions"]["primary"]["correct"],
                "planned": report["decisions"]["primary"]["planned_opportunities"],
                "readings": report["decisions"]["primary"]["readings"],
                "matched_pairs_both_correct": report["decisions"]["matched_pairs"]["both_correct"],
                "unresolved_readings": {r["opportunity_id"]: r["reading"] for r in report["decisions"]["unresolved"]},
                "decided_by": report["decisions"]["decided_by"],
                "raw_top_exact": raw["output_top_hits"], "raw_planned": raw["planned_concepts"],
                "mean_top_ned": (target["graded"]["top_normalized_edit_distance"] or {}).get("mean"),
                "outside_selection_top_hits": target["selection"]["outside_selection_top_hits"],
                "oracle_reachable": target["selection"]["oracle_reachable_concepts"],
                "role": ("gold-assisted scorer control" if policy == "oracle" else
                         "deployable evidence-only baseline" if policy == "outgroup-witness" else
                         "diagnostic baseline"),
            }
        identity = run_scripted(payload_b, StageBBaseline(case_b, "identity"), protocol="stored-hypothesis",
                                instructions=stage_b_instruction_file(case_b))
        node = case_b["opportunities"][0]["node_id"]
        step = next(s for s in identity.snapshot.steps if s.parent_node_id == node)
        for variety in FIXED_DAUGHTERS:
            decisions = score_decisions(case_b, {node: fixed_daughter_step(step, payload_b, variety)},
                                        model_committed={node: False})
            out["stage_b"][f"copy-{variety}"] = {
                "primary_correct": decisions["primary"]["correct"],
                "planned": decisions["primary"]["planned_opportunities"],
                "readings": decisions["primary"]["readings"],
                "matched_pairs_both_correct": decisions["matched_pairs"]["both_correct"],
                "unresolved_readings": {r["opportunity_id"]: r["reading"] for r in decisions["unresolved"]},
                "role": ("fixed outgroup copy (not an active child; diagnostic only)" if variety == "c"
                         else "fixed-daughter diagnostic baseline"),
            }
    return out


# Freezing ------------------------------------------------------------------

GEMINI_PRICE_TABLE = ROOT / "examples/pricing/gemini-3.8-flash.price-table.json"
CONTEXT_LIMIT_TOKENS = 1_048_576  # gemini-3.8-flash input limit, official model page read 2026-10-25
MAX_OUTPUT_TOKENS = 16_384        # max_tokens sent to both arms; caps thinking + text for Gemini
LOCAL_ONLY = ("tools/failure_audit.py", "tests/workbench/test_failure_audit.py", "tests/fixtures/failure_audit/")

ARMS = {
    "gemini": {"model": "gemini-3.8-flash", "preset": "gemini", "harness_model": "gemini/gemini-3.8-flash",
               "reasoning_effort": "medium", "price_table": True, "timeout": 300,
               "ceiling": {"cost_usd": 5.0, "wall_seconds": 3600.0},
               "A": {"max_turns": 24, "max_total_turns": 24, "max_run_seconds": 900, "max_total_cost_usd": 0.75},
               "B": {"max_turns": 30, "max_total_turns": 60, "max_run_seconds": 1800, "max_total_cost_usd": 2.25}},
    "local": {"model": "google/gemma-4-26b-a4b", "preset": "lm-studio", "harness_model": "openai/google/gemma-4-26b-a4b",
              "reasoning_effort": None, "price_table": False, "timeout": 600,
              "ceiling": {"cost_usd": None, "wall_seconds": 7200.0},
              "A": {"max_turns": 24, "max_total_turns": 24, "max_run_seconds": 1800, "max_total_cost_usd": None},
              "B": {"max_turns": 30, "max_total_turns": 60, "max_run_seconds": 5000, "max_total_cost_usd": None}},
}
WALL_OVERHEAD_SECONDS = 100


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_manifest() -> dict:
    """Code identity: HEAD, tracked diff digest and per-file hashes (local audit files excluded)."""
    import subprocess
    git = lambda *a: subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    roots = ("cognate_reconstruction", "tools", "tests", "skills", "benchmarks", "examples")
    files = [f for f in git("ls-files", "--cached", "--others", "--exclude-standard", *roots).split("\n")
             if f and not f.startswith(LOCAL_ONLY) and (ROOT / f).is_file() and "__pycache__" not in f]
    return {"head": git("rev-parse", "HEAD").strip(), "branch": git("rev-parse", "--abbrev-ref", "HEAD").strip(),
            # Code, definitions and examples only, so documentation edits do not stale it.
            "source_roots": list(roots),
            "tracked_diff_sha256": _hash(git("diff", "HEAD", "--binary", "--", *roots)),
            "dirty_paths": sorted(line[3:] for line in git("status", "--porcelain", "--", *roots).splitlines()
                                  if not line[3:].startswith(LOCAL_ONLY)),
            "excluded_local_only": list(LOCAL_ONLY),
            "files": {f: _file_hash(ROOT / f) for f in sorted(files)}}


def behavioural_digests(protocol: str, instructions_path: Path | None) -> dict:
    from types import SimpleNamespace
    from cognate_reconstruction import cli
    args = SimpleNamespace(inventory_protocol=protocol, agent_instructions=str(instructions_path) if instructions_path else None,
                           anchors=None)
    return cli._behavioural_input_digests(args)


def first_node_prompt(payload, instructions: str, protocol: str, node: str) -> dict:
    """Digest of the exact first request a session at `node` receives."""
    captured = {}

    class Peek(Scripted):
        def complete(self, messages, tools, **kwargs):
            prompt = messages[1].content
            if _node(prompt) == node and node not in captured:
                captured[node] = {"system_sha256": _hash(messages[0].content), "node_prompt_sha256": _hash(prompt),
                                  "tool_definitions_sha256": _hash(json.dumps([t.model_dump(mode="json") for t in tools])),
                                  "node_prompt_chars": len(prompt)}
            return LLMMessage(role=MessageRole.ASSISTANT, tool_calls=(LLMToolCall(call_id="peek", name="commit_reconstruction",
                arguments={"node_id": _node(prompt), "rules": [], "anomalies": [], "summary": "peek"}),))
    run_scripted(payload, Peek(), protocol=protocol, instructions=instructions)
    return captured[node]


def resource_bound(arm: dict, stage: str, price) -> dict:
    caps = arm[stage]
    if not arm["price_table"]:
        return {"paid": False, "max_run_seconds": caps["max_run_seconds"],
                "wall_reservation_seconds": caps["max_run_seconds"] + WALL_OVERHEAD_SECONDS}
    headroom = (CONTEXT_LIMIT_TOKENS * price.input_usd_per_million
                + MAX_OUTPUT_TOKENS * price.output_usd_per_million) / 1_000_000
    worst = caps["max_total_cost_usd"] + headroom
    return {"paid": True, "cost_cap_usd": caps["max_total_cost_usd"],
            "one_response_headroom_usd": round(headroom, 6),
            "headroom_basis": f"{CONTEXT_LIMIT_TOKENS} input tokens (context limit) and {MAX_OUTPUT_TOKENS} output tokens at the table price",
            "worst_case_trial_usd": round(worst, 6), "cost_reservation_usd": round(worst + 0.005, 2),
            "max_turns_total": caps["max_total_turns"],
            "worst_case_output_tokens": caps["max_total_turns"] * MAX_OUTPUT_TOKENS,
            "max_run_seconds": caps["max_run_seconds"],
            "wall_reservation_seconds": caps["max_run_seconds"] + WALL_OVERHEAD_SECONDS}


def trial_argv(arm_name: str, stage: str, inputs: Path) -> list[str]:
    arm, caps = ARMS[arm_name], ARMS[arm_name][stage]
    argv = ["{python}", "-m", "cognate_reconstruction.cli", "infer",
            "--input", str(inputs / f"stage-{stage.lower()}.payload.json"),
            "--model", arm["model"], "--preset", arm["preset"],
            "--provider-config", str(inputs / f"{arm_name}.provider-config.json"),
            "--inventory-protocol", "stored-hypothesis",
            "--output", "{run_dir}/result.json", "--trajectories", "{run_dir}/trajectories.jsonl",
            "--events", "{run_dir}/events.jsonl", "--checkpoint", "{run_dir}/checkpoint.json",
            "--run-id", f"r02-{stage.lower()}-{arm_name}", "--timeout", str(arm["timeout"]),
            "--max-turns", str(caps["max_turns"]), "--max-tool-calls", "64",
            "--max-total-turns", str(caps["max_total_turns"]), "--max-run-seconds", str(caps["max_run_seconds"]),
            "--max-failed-nodes", "0", "--max-retries", "3",
            # The harness clips each request's timeout to the remaining retry
            # budget, so a smaller budget would silently replace the timeout.
            "--max-retry-seconds", str(arm["timeout"]), "--quiet"]
    argv += ["--agent-instructions", str(inputs / ("stage-a.instructions.stored-hypothesis.md" if stage == "A"
                                                   else "stage-b.instructions.md"))]
    if arm["reasoning_effort"]:
        argv += ["--reasoning-effort", arm["reasoning_effort"]]
    if arm["price_table"]:
        argv += ["--price-table", str(inputs / "price-table.json"),
                 "--max-total-cost-usd", str(caps["max_total_cost_usd"])]
    return argv


def freeze(output_dir: Path) -> dict:
    """Write inputs, per-stage manifests and the serial launch plan."""
    from datetime import date
    from cognate_reconstruction.agent.providers.pricing import load_price_table, price_for
    # Absolute, because the launcher runs each trial from the plan's directory.
    output_dir = output_dir.resolve()
    inputs = output_dir / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    case_a, case_b = load_explicit_case(STAGE_A), load_explicit_case(STAGE_B)
    payload_a, payload_b = build_explicit_case(case_a), build_explicit_case(case_b)
    (inputs / "stage-a.payload.json").write_text(payload_a.model_dump_json(indent=2))
    (inputs / "stage-b.payload.json").write_text(payload_b.model_dump_json(indent=2))
    a_text = stage_a_instruction_file(case_a, "stored-hypothesis")
    (inputs / "stage-a.instructions.stored-hypothesis.md").write_text(a_text)
    b_text = stage_b_instruction_file(case_b)
    (inputs / "stage-b.instructions.md").write_text(b_text)
    (inputs / "price-table.json").write_bytes(GEMINI_PRICE_TABLE.read_bytes())
    for name in ARMS:
        (inputs / f"{name}.provider-config.json").write_text(json.dumps({"max_tokens": MAX_OUTPUT_TOKENS}, indent=2) + "\n")
    table, table_sha = load_price_table(inputs / "price-table.json")
    price = price_for(table, ARMS["gemini"]["harness_model"], date.today())
    sources = source_manifest()
    (output_dir / "source_manifest.json").write_text(json.dumps(sources, indent=2) + "\n")
    input_hashes = {p.name: _file_hash(p) for p in sorted(inputs.iterdir())}
    visible = {
        "A": {"instructions_sha256": _hash(a_text), **behavioural_digests("stored-hypothesis", inputs / "stage-a.instructions.stored-hypothesis.md"),
              "first_request": first_node_prompt(payload_a, a_text, "stored-hypothesis", "r")},
        "B": {"instructions_sha256": _hash(b_text), **behavioural_digests("stored-hypothesis", inputs / "stage-b.instructions.md"),
              "packaged_instructions_sha256": _hash(load_agent_instructions()),
              "first_request_x": first_node_prompt(payload_b, b_text, "stored-hypothesis", "x"),
              "root_request": "depends on the model's committed x beam; not frozen"},
    }
    common = {
        "experiment": output_dir.name, "frozen_on": str(date.today()), "status": "candidate manifest; not independently reviewed; launch not authorized by R02",
        "source": {k: sources[k] for k in ("head", "branch", "source_roots", "tracked_diff_sha256", "dirty_paths")},
        "source_manifest_sha256": _file_hash(output_dir / "source_manifest.json"),
        "inputs": input_hashes, "price_table": {"sha256": table_sha, "entry": json.loads(price.model_dump_json())},
        "evaluator_versions": {"task02": "task02-v1", "units": "task04-units-v1", "evidence_contract": "units-v2",
                               "usability": "r02-usability-v1", "decisions": "r02-decisions-v1",
                               "ledger": "r02-ledger-v1", "usage_accounting": "abrupt-loss-v1"},
        "native_profile": "stored-hypothesis",
        "trials_per_model": 1, "replication": "none prespecified; no automatic retries, reruns or seeds",
        "max_output_tokens": MAX_OUTPUT_TOKENS,
    }
    arms_out = {}
    for name, arm in ARMS.items():
        arms_out[name] = {k: arm[k] for k in ("model", "preset", "harness_model", "reasoning_effort", "timeout", "ceiling")}
        arms_out[name]["temperature"] = 1.0 if arm["preset"] == "gemini" else 0.1
    manifests = {}
    for stage, case, definition in (("A", case_a, STAGE_A), ("B", case_b, STAGE_B)):
        manifests[stage] = {**common, "stage": stage, "definition": str(definition.relative_to(ROOT)),
            "definition_sha256": _file_hash(definition), "suite_version": case["suite_version"],
            "question": case["question"], "model_visible": visible[stage],
            "arms": {name: {**arms_out[name], "caps": ARMS[name][stage], "resources": resource_bound(ARMS[name], stage, price),
                            "argv": trial_argv(name, stage, inputs)} for name in ARMS}}
        (output_dir / f"manifest.stage-{stage.lower()}.json").write_text(json.dumps(manifests[stage], indent=2) + "\n")
    plan = {"plan_version": "r02-batch-v1", "batch_dir": ".",
            "ceilings": {name: ARMS[name]["ceiling"] for name in ARMS}, "trials": []}
    for name in ARMS:  # the stronger arm first: local availability is not its gate
        for stage in ("A", "B"):
            bound = resource_bound(ARMS[name], stage, price)
            plan["trials"].append({
                "trial_id": f"{stage}-{name}", "arm": name, "run_dir": f"runs/{stage.lower()}-{name}",
                "argv": trial_argv(name, stage, inputs),
                "reservation": {"cost_usd": bound.get("cost_reservation_usd"), "wall_seconds": bound["wall_reservation_seconds"]},
                "requires_usable": f"A-{name}" if stage == "B" else None,
                "evaluate_argv": ["{python}", str(ROOT / "tools/r02_diagnostics.py"), "evaluate", "--stage", stage,
                                  "--run-dir", "{run_dir}", "--protocol", "stored-hypothesis"]})
    (output_dir / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    return {"manifests": {k: _file_hash(output_dir / f"manifest.stage-{k.lower()}.json") for k in manifests},
            "plan_sha256": _file_hash(output_dir / "plan.json"), "inputs": input_hashes,
            "source_manifest_sha256": common["source_manifest_sha256"], "model_visible": visible}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="Write payloads and the Stage A instruction files")
    build.add_argument("--output-dir", type=Path, required=True)
    sub.add_parser("controls", help="Run scripted controls and baselines; print JSON")
    meas = sub.add_parser("measure", help="Measure fixture work, caps and visible sizes per profile")
    ev = sub.add_parser("evaluate", help="Score one run directory and write evaluation.json")
    ev.add_argument("--stage", choices=("A", "B"), required=True)
    ev.add_argument("--run-dir", type=Path, required=True)
    ev.add_argument("--protocol", choices=PROTOCOLS, default="stored-hypothesis")
    ev.add_argument("--definition", type=Path)
    fr = sub.add_parser("freeze", help="Write inputs, candidate manifests and the launch plan")
    fr.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        args.output_dir.mkdir(parents=True, exist_ok=True)
        written = {}
        for label, path in (("stage-a", STAGE_A), ("stage-b", STAGE_B)):
            case = load_explicit_case(path)
            text = build_explicit_case(case).model_dump_json(indent=2)
            (args.output_dir / f"{label}.payload.json").write_text(text)
            written[f"{label}.payload.json"] = _hash(text)
        case_a = load_explicit_case(STAGE_A)
        for protocol in PROTOCOLS:
            text = stage_a_instruction_file(case_a, protocol)
            name = f"stage-a.instructions.{protocol}.md"
            (args.output_dir / name).write_text(text)
            written[name] = _hash(text)
        print(json.dumps(written, indent=2))
    elif args.command == "freeze":
        print(json.dumps(freeze(args.output_dir), indent=2))
    elif args.command == "controls":
        print(json.dumps(controls(), indent=2))
    elif args.command == "measure":
        case_a, case_b = load_explicit_case(STAGE_A), load_explicit_case(STAGE_B)
        payload_a, payload_b = build_explicit_case(case_a), build_explicit_case(case_b)
        rows = {"stage_a": [measure(case_a, payload_a, p, StageAOperator(case_a, p), stage_a_instruction_file(case_a, p))
                            for p in PROTOCOLS],
                "stage_b": [measure(case_b, payload_b, p, StageBBaseline(case_b, "outgroup-witness", p),
                                    stage_b_instruction_file(case_b)) for p in PROTOCOLS],
                "default_filter": {"stage_a:r": default_filter_coverage(payload_a, "r"),
                                   "stage_b:x": default_filter_coverage(
                                       payload_b.model_copy(update={"lexicons": tuple(
                                           l for l in payload_b.lexicons if l.variety_id in ("a", "b"))}), "x")}}
        print(json.dumps(rows, indent=2))
    else:
        case = load_explicit_case(args.definition or (STAGE_A if args.stage == "A" else STAGE_B))
        report = evaluate_stage_a(case, args.run_dir, args.protocol) if args.stage == "A" else evaluate_stage_b(case, args.run_dir)
        (args.run_dir / "evaluation.json").write_text(json.dumps(report, indent=2, default=str))
        print(json.dumps(report["stage_gate"]))


if __name__ == "__main__":
    main()
