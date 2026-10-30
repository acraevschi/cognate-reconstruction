#!/usr/bin/env python3
"""R04 Stage C instruments: payload, scripted baselines, measurement, evaluation, freeze.

Stage C (`benchmarks/diagnostic/r04-stage-c-v1.json`) is R03's narrowed
question: one-sided material at node x with three outgroups, other-unit forms,
missing forms and tied items, where R02's deployable outgroup-witness rule is
not the answer. Every provider here is scripted and offline. The baselines are
fixed evidence-only policies; `identification` applies the stated criterion
and is the panel's ceiling by construction, `oracle` reads the scorer's
expected decisions and only validates the scorer. None is a model result.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tools import _bootstrap  # noqa: F401

from cognate_reconstruction.agent.instructions import load_agent_instructions
from cognate_reconstruction.evaluation.judgment import JUDGMENT_VERSION, score_judgment, stage_c_instructions
from cognate_reconstruction.evaluation.run import evaluate_run
from cognate_reconstruction.synthesis.diagnostics import build_explicit_case, load_explicit_case

from tools.r02_diagnostics import (
    ARMS, CONTEXT_LIMIT_TOKENS, GEMINI_PRICE_TABLE, ROOT, SURVEY_LIMIT, WALL_OVERHEAD_SECONDS,
    Scripted, StageBBaseline, _children, _file_hash, _hash, _identity, _row, _steps,
    behavioural_digests, first_node_prompt, fixed_daughter_step, read_run_dir, run_scripted,
    source_manifest,
)

STAGE_C = ROOT / "benchmarks/diagnostic/r04-stage-c-v1.json"
OUTGROUPS = ("c", "d", "f")
VOWELS = frozenset("aeiou")
# R02's StageBBaseline serves the policies that need no outgroup forms. Its
# oracle keys expectations by unit, which the h+k concepts (two positions in
# one unit) would collapse, so Stage C has its own per-position oracle.
B_POLICIES = ("identity", "union", "intersection", "outgroup-witness")
PANEL_POLICIES = ("identification", "unanimous", "majority-of-three", "spelling-majority",
                  "presence-only", "state-c", "state-d", "state-f", "oracle")
FIXED_COPIES = ("a", "b", *OUTGROUPS)


def _fitch(k: int, m: int) -> str:
    """Star tree ((a,b)x, k observed outgroups)r with one daughter showing the material."""
    present, absent = 1 + min(k - m, m + 1), 1 + min(k - m + 1, m)
    return "retain" if present < absent else "absent" if absent < present else "unresolved"


class PanelBaseline(Scripted):
    """A fixed policy that also reads the outgroups' forms, as a model would.

    One local survey (its outgroup witnesses: presence only, per unit), then
    one `search_forms` over the outgroups for their forms and cognate units,
    then a preview and a handle commit. Per one-sided set: `m` outgroups
    witness it in its unit, `k` have a form in that unit.

    - `identification`: the stated criterion (Fitch on the star; ties kept at 0.5);
    - `unanimous`: keep when every outgroup with a same-unit form witnesses it;
    - `majority-of-three`: keep when two of three witness it (no form = lacking);
    - `spelling-majority`: keep when at least half of the outgroups with any form
      for the concept show the reflex by spelling, ignoring units and boundaries;
    - `presence-only`: the tool note's doctrine, any witness keeps and no
      witness is a tie, kept at 0.5;
    - `state-<o>`: follow one outgroup's same-unit state;
    - `oracle`: the scorer's expected decision per unit position (a scorer
      control that reads gold, never a baseline).
    """

    def __init__(self, case, policy):
        if policy not in PANEL_POLICIES:
            raise ValueError(policy)
        self.case, self.policy = case, policy
        self.model = f"scripted/r04-stage-c-{policy}"
        self.node = case["opportunities"][0]["node_id"]

    @staticmethod
    def _spelled(segments, locus):
        tokens = [t for t in segments if t not in ("+", "-")]
        if locus == "initial":
            return tokens[:1] == ["h"]
        vowel = next((i for i, t in enumerate(tokens) if t in VOWELS), None)
        return vowel is not None and vowel + 1 < len(tokens) and tokens[vowel + 1] not in VOWELS

    def decide(self, item, witnesses, forms):
        present = next(s for s in item["segments"] if s is not None)
        locus = "initial" if present == "h" else "final"
        unit = item["scope_id"].removeprefix("cog:")
        concept = item["example_concept_ids"][0]
        concept_forms = {o: f for (o, c), f in forms.items() if c == concept}
        available = {o for o, f in concept_forms.items()
                     if any(m["cognate_set_id"] == unit for m in f.get("cognate_memberships", ()))}
        m, k = len(witnesses & available), len(available)
        if self.policy == "oracle":
            expected = next(o["expected"] for o in self.case["opportunities"]
                            if o["concept_id"] == concept and o["unit"] == unit and o["token"] == present)
            return (None if expected == "absent" else present), (.5 if expected == "unresolved" else .9)
        if self.policy == "identification":
            value = _fitch(k, m)
            return (present, .5) if value == "unresolved" else (present if value == "retain" else None, .9)
        if self.policy == "unanimous":
            keep = k > 0 and m == k
        elif self.policy == "majority-of-three":
            keep = m >= 2
        elif self.policy == "spelling-majority":
            spelled = [self._spelled(f["segments"], locus) for f in concept_forms.values()]
            keep = bool(spelled) and 2 * sum(spelled) >= len(spelled)
        elif self.policy == "presence-only":
            return (present, .7) if m else (present, .5)
        else:
            keep = self.policy.removeprefix("state-") in witnesses
        return (present if keep else None), .7

    def next_call(self, node, prompt, results):
        if node != self.node:
            return _identity(node)
        if not results:
            return "summarize_correspondences", {"reading": "local", "min_support": 1,
                                                  "limit": SURVEY_LIMIT, "include_outgroup": True}
        if len(results) == 1:
            return "search_forms", {"scope": "available_tree", "node_ids": list(OUTGROUPS), "limit": 200}
        survey, search = results[0], results[1]
        witnesses = {row["set_id"]: {w["node_id"] for w in row["witnesses"] if w.get("segment")}
                     for row in survey.get("outgroup_reflexes", ())}
        forms = {(hit["node_id"], hit["form"]["concept_id"]): hit["form"] for hit in search["hits"]}
        rows = []
        for item in survey["sets"]:
            if None not in item["segments"] or all(s is None for s in item["segments"]):
                continue
            value, confidence = self.decide(item, witnesses.get(item["set_id"], set()), forms)
            rows.append(_row(item, value, confidence, "stored-hypothesis",
                             f"Scripted {self.policy} baseline; not a model decision.",
                             "Scripted baseline policy; polarity is the policy's assumption."))
        hypothesis = {"choices": rows, "residue_policy": "retain_from_witness", "residue_witness_child_id": "a"}
        previews = [r for r in results if "hypothesis_id" in r]
        if not previews:
            return "test_proto_assembly", hypothesis
        return "commit_reconstruction", {"node_id": node, "anomalies": [], "hypothesis_id": previews[-1]["hypothesis_id"],
                                         "summary": f"Scripted {self.policy} baseline."}


def stage_c_instruction_file(case) -> str:
    return stage_c_instructions(case, load_agent_instructions())


def evaluate_stage_c(case, run_dir: Path) -> dict:
    payload = build_explicit_case(case)
    result, trajectories, checkpoint = read_run_dir(run_dir)
    steps = _steps(result, checkpoint)
    latest = {t.node_id: t for t in trajectories}
    committed = {node: bool(t.completed and t.committed_reconstruction is not None) for node, t in latest.items()}
    judgment = score_judgment(case, steps, model_committed=committed, trajectories_by_node=latest)
    report = evaluate_run(payload, result, trajectories) if result is not None else None
    node = case["opportunities"][0]["node_id"]
    usable = bool(committed.get(node)) and not (node in steps and steps[node].diagnostics.failure_fallback)
    return {"stage": "C", "judgment": judgment,
            "run_status": (result or {}).get("status", "completed" if result else "no_result"),
            "failure_kind": (result or {}).get("failure_kind"),
            "interruption_reason": (result or {}).get("interruption_reason"),
            "task02_evaluation": report.model_dump(mode="json") if report is not None else None,
            "stage_gate": {"usable": usable, "reason": "scored node committed by the model" if usable
                           else "scored node not committed by the model"}}


def _summary(report: dict, role: str) -> dict:
    judgment = report["judgment"]
    raw = (report["task02_evaluation"] or {}).get("raw_target_summary") or {}
    return {
        "primary_correct": judgment["primary"]["model_committed_correct"],
        "planned": judgment["primary"]["planned_opportunities"],
        "readings": judgment["primary"]["readings"],
        "rule_error_sets": {r: f"{d['model_correct']}/{d['rule_errors']}"
                            for r, d in judgment["shallow_rule_error_sets"].items()},
        "pairs": judgment["matched_pairs"]["model_both_correct"],
        "ties_marked": judgment["uncertainty"]["ties_marked"],
        "false_confident_claims": judgment["uncertainty"]["false_confident_claims"],
        "unresolved_readings": {r["opportunity_id"]: r["reading"] for r in judgment["opportunities"]
                                if r["class"] != "primary"},
        "labels": judgment["labels"],
        "raw_top_exact": raw.get("output_top_hits"), "raw_planned": raw.get("planned_concepts"),
        "role": role,
    }


def controls() -> dict:
    """Every Stage C baseline through the ordinary service and both scorers."""
    from tempfile import TemporaryDirectory
    case = load_explicit_case(STAGE_C)
    payload = build_explicit_case(case)
    instructions = stage_c_instruction_file(case)
    out = {"live_model_calls": 0, "stage_c": {}}
    roles = {"oracle": "gold-assisted scorer control", "identification": "the stated criterion (ceiling)",
             "outgroup-witness": "R02's frozen deployable rule"}
    with TemporaryDirectory(prefix="r04-controls-") as tmp:
        for policy in B_POLICIES + PANEL_POLICIES:
            run_dir = Path(tmp) / policy
            run_dir.mkdir()
            provider = StageBBaseline(case, policy) if policy in B_POLICIES else PanelBaseline(case, policy)
            run_scripted(payload, provider, protocol="stored-hypothesis", instructions=instructions, out_dir=run_dir)
            out["stage_c"][policy] = _summary(evaluate_stage_c(case, run_dir), roles.get(policy, "diagnostic baseline"))
        identity = run_scripted(payload, StageBBaseline(case, "identity"), protocol="stored-hypothesis",
                                instructions=instructions)
        node = case["opportunities"][0]["node_id"]
        step = next(s for s in identity.snapshot.steps if s.parent_node_id == node)
        for variety in FIXED_COPIES:
            judgment = score_judgment(case, {node: fixed_daughter_step(step, payload, variety)},
                                      model_committed={node: False})
            out["stage_c"][f"copy-{variety}"] = {
                "primary_correct": judgment["primary"]["correct"], "planned": judgment["primary"]["planned_opportunities"],
                "readings": judgment["primary"]["readings"],
                "role": "fixed-daughter diagnostic" if variety in ("a", "b") else "fixed outgroup copy (diagnostic only)"}
    return out


def measure() -> dict:
    """Model-visible sizes of the identification baseline's session at x."""
    from cognate_reconstruction.agent.schemas import MessageRole
    case = load_explicit_case(STAGE_C)
    result = run_scripted(build_explicit_case(case), PanelBaseline(case, "identification"),
                          protocol="stored-hypothesis", instructions=stage_c_instruction_file(case))
    rows = []
    for trajectory in result.trajectories:
        tool_results = [m.content or "" for m in trajectory.messages if m.role is MessageRole.TOOL]
        rows.append({"node_id": trajectory.node_id,
                     "system_chars": len(trajectory.messages[0].content or ""),
                     "node_prompt_chars": len(trajectory.messages[1].content or ""),
                     "tool_schema_chars": len(json.dumps([d.model_dump(mode="json") for d in trajectory.tool_definitions])),
                     "tool_result_chars": [len(r) for r in tool_results],
                     "transcript_chars_at_end": sum(len(m.content or "") + len(json.dumps(
                         [c.arguments for c in m.tool_calls])) for m in trajectory.messages)})
    return {"sessions": rows}


# Freezing ------------------------------------------------------------------

# R04's Gemini arm: R03's profile with the owner's 32,768-token output cap
# (2026-10-28), reasoning history decided by the harness (Gemini resolves to
# drop, which hashes as before), and the traversal stopped after x.
ARM = {**ARMS["gemini"], "max_output_tokens": 32_768,
       "infer_args": ["--reasoning-history", "auto", "--stop-after-node", "x"],
       "ceiling": {"cost_usd": 3.5, "wall_seconds": 2100.0},
       "C": {"max_turns": 36, "max_total_turns": 36, "max_tool_calls": 64,
             "max_run_seconds": 1800, "max_total_cost_usd": 2.5}}
ARM_NAME = "gemini-r04"


def resource_bound(price) -> dict:
    caps, cap_tokens = ARM["C"], ARM["max_output_tokens"]
    headroom = (CONTEXT_LIMIT_TOKENS * price.input_usd_per_million + cap_tokens * price.output_usd_per_million) / 1_000_000
    worst = caps["max_total_cost_usd"] + headroom
    return {"paid": True, "cost_cap_usd": caps["max_total_cost_usd"], "one_response_headroom_usd": round(headroom, 6),
            "headroom_basis": f"{CONTEXT_LIMIT_TOKENS} input tokens (context limit) and {cap_tokens} output tokens at the table price",
            "worst_case_trial_usd": round(worst, 6), "cost_reservation_usd": round(worst + 0.005, 2),
            "max_turns_total": caps["max_total_turns"], "worst_case_output_tokens": caps["max_total_turns"] * cap_tokens,
            "max_run_seconds": caps["max_run_seconds"],
            "wall_reservation_seconds": caps["max_run_seconds"] + WALL_OVERHEAD_SECONDS}


def trial_argv(inputs: Path) -> list[str]:
    caps = ARM["C"]
    return ["{python}", "-m", "cognate_reconstruction.cli", "infer",
            "--input", str(inputs / "stage-c.payload.json"),
            "--model", ARM["model"], "--preset", ARM["preset"],
            "--provider-config", str(inputs / f"{ARM_NAME}.provider-config.json"),
            "--inventory-protocol", "stored-hypothesis",
            "--output", "{run_dir}/result.json", "--trajectories", "{run_dir}/trajectories.jsonl",
            "--events", "{run_dir}/events.jsonl", "--checkpoint", "{run_dir}/checkpoint.json",
            "--run-id", f"r04-c-{ARM_NAME}", "--timeout", str(ARM["timeout"]),
            "--max-turns", str(caps["max_turns"]), "--max-tool-calls", str(caps["max_tool_calls"]),
            "--max-total-turns", str(caps["max_total_turns"]), "--max-run-seconds", str(caps["max_run_seconds"]),
            "--max-failed-nodes", "0", "--max-retries", "3", "--max-retry-seconds", str(ARM["timeout"]),
            "--quiet", *ARM["infer_args"],
            "--agent-instructions", str(inputs / "stage-c.instructions.md"),
            "--reasoning-effort", ARM["reasoning_effort"],
            "--price-table", str(inputs / "price-table.json"),
            "--max-total-cost-usd", str(caps["max_total_cost_usd"])]


def freeze(output_dir: Path) -> dict:
    """Write inputs, the Stage C manifest and the one-trial launch plan."""
    from datetime import date
    from cognate_reconstruction.agent.providers.pricing import load_price_table, price_for
    output_dir = output_dir.resolve()
    inputs = output_dir / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    case = load_explicit_case(STAGE_C)
    payload = build_explicit_case(case)
    (inputs / "stage-c.payload.json").write_text(payload.model_dump_json(indent=2))
    text = stage_c_instruction_file(case)
    (inputs / "stage-c.instructions.md").write_text(text)
    (inputs / "price-table.json").write_bytes(GEMINI_PRICE_TABLE.read_bytes())
    (inputs / f"{ARM_NAME}.provider-config.json").write_text(json.dumps({"max_tokens": ARM["max_output_tokens"]}, indent=2) + "\n")
    table, table_sha = load_price_table(inputs / "price-table.json")
    price = price_for(table, ARM["harness_model"], date.today())
    sources = source_manifest()
    (output_dir / "source_manifest.json").write_text(json.dumps(sources, indent=2) + "\n")
    input_hashes = {p.name: _file_hash(p) for p in sorted(inputs.iterdir())}
    bound = resource_bound(price)
    argv = trial_argv(inputs)
    manifest = {
        "experiment": output_dir.name, "frozen_on": str(date.today()), "stage": "C",
        "status": "candidate manifest; review and the owner's paid envelope are recorded outside this file",
        "source": {k: sources[k] for k in ("head", "branch", "source_roots", "tracked_diff_sha256", "dirty_paths")},
        "source_manifest_sha256": _file_hash(output_dir / "source_manifest.json"),
        "definition": str(STAGE_C.relative_to(ROOT)), "definition_sha256": _file_hash(STAGE_C),
        "suite_version": case["suite_version"], "question": case["question"],
        "inputs": input_hashes, "price_table": {"sha256": table_sha, "entry": json.loads(price.model_dump_json())},
        "evaluator_versions": {"task02": "task02-v1", "units": "task04-units-v1", "evidence_contract": "units-v2",
                               "decisions": "r02-decisions-v1", "judgment": JUDGMENT_VERSION,
                               "ledger": "r02-ledger-v1", "usage_accounting": "abrupt-loss-v1"},
        "model_visible": {"instructions_sha256": _hash(text),
                          "packaged_instructions_sha256": _hash(load_agent_instructions()),
                          **behavioural_digests("stored-hypothesis", inputs / "stage-c.instructions.md"),
                          "first_request_x": first_node_prompt(payload, text, "stored-hypothesis", "x")},
        "native_profile": "stored-hypothesis", "scored_node": "x", "unscored_nodes": "not attempted (--stop-after-node x)",
        "trials": 1, "replication": "none; no automatic retries, reruns or seeds",
        "arm": {ARM_NAME: {**{k: ARM[k] for k in ("model", "preset", "harness_model", "reasoning_effort", "timeout", "ceiling")},
                           "temperature": 1.0, "max_output_tokens": ARM["max_output_tokens"], "caps": ARM["C"],
                           "resources": bound, "argv": argv}},
    }
    (output_dir / "manifest.stage-c.json").write_text(json.dumps(manifest, indent=2) + "\n")
    plan = {"plan_version": "r02-batch-v1", "batch_dir": ".", "ceilings": {ARM_NAME: ARM["ceiling"]}, "trials": [{
        "trial_id": f"C-{ARM_NAME}", "arm": ARM_NAME, "run_dir": f"runs/c-{ARM_NAME}", "argv": argv,
        "reservation": {"cost_usd": bound["cost_reservation_usd"], "wall_seconds": bound["wall_reservation_seconds"]},
        "requires_usable": None,
        "evaluate_argv": ["{python}", str(ROOT / "tools/r04_judgment.py"), "evaluate", "--run-dir", "{run_dir}"]}]}
    (output_dir / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    return {"manifest_sha256": _file_hash(output_dir / "manifest.stage-c.json"),
            "plan_sha256": _file_hash(output_dir / "plan.json"), "inputs": input_hashes,
            "source_manifest_sha256": manifest["source_manifest_sha256"], "model_visible": manifest["model_visible"],
            "resources": bound}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("controls", help="Run every scripted baseline through the scorers; print JSON")
    sub.add_parser("measure", help="Model-visible sizes of the identification baseline's session")
    ev = sub.add_parser("evaluate", help="Score one run directory and write evaluation.json")
    ev.add_argument("--run-dir", type=Path, required=True)
    fr = sub.add_parser("freeze", help="Write inputs, the manifest and the launch plan")
    fr.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "controls":
        print(json.dumps(controls(), indent=2))
    elif args.command == "measure":
        print(json.dumps(measure(), indent=2))
    elif args.command == "freeze":
        print(json.dumps(freeze(args.output_dir), indent=2))
    else:
        report = evaluate_stage_c(load_explicit_case(STAGE_C), args.run_dir)
        (args.run_dir / "evaluation.json").write_text(json.dumps(report, indent=2, default=str))
        print(json.dumps(report["stage_gate"]))


if __name__ == "__main__":
    main()
