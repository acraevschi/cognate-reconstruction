"""R04 Stage C: multi-outgroup judgment panel, scorer, planned stop and freeze.

Every provider is scripted. The key is re-derived here from the observed
forms and the parsed tree, not from the builder's labels. Baselines go through
the ordinary service, JSONL and both scorers. Nothing here is a model result.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from cognate_reconstruction import cli
from cognate_reconstruction.agent.providers.litellm_provider import LiteLLMProvider
from cognate_reconstruction.benchmarks.ledger import read_run_resources
from cognate_reconstruction.evaluation.judgment import navigation, score_judgment
from cognate_reconstruction.synthesis.diagnostics import build_explicit_case, load_explicit_case
from cognate_reconstruction.tree import parse_newick
from tests.workbench.test_r02_instruments import CASE_A, CASE_B, _price_table, completion_from
from tools.r02_diagnostics import Scripted, StageBBaseline, _identity, run_scripted
from tools.r04_judgment import (
    ARM, STAGE_C, PanelBaseline, evaluate_stage_c, freeze, stage_c_instruction_file,
)

CASE_C = load_explicit_case(STAGE_C)
PAYLOAD_C = build_explicit_case(CASE_C)
C_TEXT = stage_c_instruction_file(CASE_C)
VOWELS = set("aeiou")


def _state(form, unit, locus):
    """1/0 when the form has a piece in the unit, None when it has none."""
    pieces = [m for m in form.cognate_memberships if m.cognate_set_id == unit]
    if not pieces:
        return None
    tokens = [form.segments[i] for i in pieces[0].segment_indices]
    return int(tokens[0] == "h") if locus == "initial" else int(tokens[-1] not in VOWELS)


def _parsimony_reading(tree, states, node):
    """Unit-cost parsimony by brute force over internal states; the node's best value."""
    internal, edges = [], []

    def walk(n, parent):
        label = n.label
        if n.is_leaf:
            edges.append((parent, label))
            return
        internal.append(label)
        if parent is not None:
            edges.append((parent, label))
        for child in n.children:
            walk(child, label)
    walk(tree, None)
    best = {0: None, 1: None}
    for values in itertools.product((0, 1), repeat=len(internal)):
        assign = dict(zip(internal, values))
        cost = 0
        for parent, child in edges:
            child_state = assign[child] if child in assign else states.get(child)
            if child_state is not None:
                cost += assign[parent] != child_state
        value = assign[node]
        best[value] = cost if best[value] is None else min(best[value], cost)
    return "retain" if best[1] < best[0] else "absent" if best[0] < best[1] else "unresolved"


def test_stage_c_key_follows_the_stated_criterion_from_observed_forms():
    tree = parse_newick(CASE_C["newick"])
    forms = {(l.variety_id, f.concept_id): f for l in PAYLOAD_C.lexicons for f in l.forms}
    for opportunity in CASE_C["opportunities"]:
        concept, unit, locus = opportunity["concept_id"], opportunity["unit"], opportunity["locus"]
        states = {v: _state(forms[(v, concept)], unit, locus) if (v, concept) in forms else None
                  for v in ("a", "b", "c", "d", "f")}
        # Exactly one active child shows the material, in this unit.
        assert {states["a"], states["b"]} == {0, 1}
        assert _parsimony_reading(tree, states, "x") == opportunity["expected"], opportunity["opportunity_id"]
        # The operator labels describe the observed forms.
        for node, label in opportunity["outgroup_states"].items():
            form = forms.get((node, concept))
            assert (form is None) == (label == "-")
            if label.startswith("w"):
                assert states[node] is None and form.cognate_memberships[0].cognate_set_id != unit
            elif label == "s1":
                assert states[node] == 0 and len(form.cognate_memberships) == 2
            elif label in ("0", "1"):
                assert states[node] == int(label)
    # Tied items are the only unresolved ones and carry both alternatives.
    targets = CASE_C["targets"]["x"]["forms"]
    for opportunity in CASE_C["opportunities"]:
        alternatives = len(targets[opportunity["concept_id"]])
        assert (opportunity["class"] == "unresolved") == (alternatives == 2)


def _run(policy, out_dir=None):
    provider = StageBBaseline(CASE_C, policy) if policy in ("identity", "union", "intersection",
                                                            "outgroup-witness") else PanelBaseline(CASE_C, policy)
    return run_scripted(PAYLOAD_C, provider, protocol="stored-hypothesis", instructions=C_TEXT, out_dir=out_dir)


def _judge(tmp_path, policy):
    run_dir = tmp_path / policy
    run_dir.mkdir()
    _run(policy, run_dir)
    return evaluate_stage_c(CASE_C, run_dir)["judgment"]


@pytest.mark.parametrize("policy,correct,pairs,label", [
    ("identification", 19, 5, "criterion-sensitive on this panel"),
    ("outgroup-witness", 13, 1, "witness-rule level"),
    ("unanimous", 15, 3, "baseline-level"),
    ("majority-of-three", 14, 3, "baseline-level"),
    ("spelling-majority", 14, 3, "baseline-level"),
    ("union", 10, 0, "uniform (regularity) reading"),
    ("intersection", 9, 0, "uniform (regularity) reading"),
    ("identity", 9, 0, "baseline-level"),
])
def test_shallow_rules_each_miss_a_component_the_criterion_does_not(tmp_path, policy, correct, pairs, label):
    judgment = _judge(tmp_path, policy)
    assert judgment["primary"]["planned_opportunities"] == 19
    assert judgment["primary"]["model_committed_correct"] == correct
    assert judgment["matched_pairs"]["model_both_correct"] == pairs
    assert judgment["labels"]["value"] == label
    sets = judgment["shallow_rule_error_sets"]
    if policy in sets:
        assert sets[policy]["model_correct"] == 0 and sets[policy]["rule_errors"] >= 4
    if policy == "identification":
        assert all(d["model_correct"] == d["rule_errors"] for d in sets.values())


def test_uncertainty_reading_separates_marked_ties_from_confident_claims(tmp_path):
    criterion = _judge(tmp_path, "identification")["uncertainty"]
    assert (criterion["ties_marked"], criterion["false_confident_claims"], criterion["decided_hedged"]) == (4, 0, 0)
    witness = _judge(tmp_path, "outgroup-witness")["uncertainty"]
    # Six wrong decisions and four ties, all at the rule's fixed 0.7.
    assert (witness["ties_marked"], witness["decided_incorrect_confident"], witness["ties_confident"]) == (0, 6, 4)
    # A policy that hedges everything marks every tie but is not warranted.
    hedge = _judge(tmp_path, "presence-only")
    assert hedge["uncertainty"]["ties_marked"] == 2 and hedge["labels"]["uncertainty"] == "partial"


def test_navigation_shows_which_outgroup_forms_a_session_read(tmp_path):
    reading = _judge(tmp_path, "identification")
    assert reading["navigation"]["concepts_with_every_outgroup_form_seen"] == 19
    assert reading["navigation"]["calls"]["search_forms"] == 1
    # The survey alone shows presence only, never a lacking or other-unit form.
    survey_only = _judge(tmp_path, "outgroup-witness")
    assert survey_only["navigation"]["outgroup_forms_seen"] == []
    assert survey_only["navigation"]["survey_outgroup_profiles"] == 1
    # Alignments over the outgroups show their forms too.
    concepts = sorted(CASE_C["observed"]["a"])[:2]

    class Aligning(Scripted):
        def next_call(self, node, prompt, results):
            if node != "x" or results:
                return _identity(node)
            return "get_alignments", {"node_ids": ["a", "b", "c", "d", "f"], "concept_ids": concepts,
                                      "detail": "summary", "reading": "local"}
    result = run_scripted(PAYLOAD_C, Aligning(), protocol="stored-hypothesis", instructions=C_TEXT)
    seen = navigation(CASE_C, {t.node_id: t for t in result.trajectories}["x"])["outgroup_forms_seen"]
    assert seen == sorted(f"{o}:{c}" for o in ("c", "d", "f") for c in concepts if c in CASE_C["observed"][o])
    # Scoped polarize per one-sided correspondence set also inspects every outgroup's state.
    class Polarizing(Scripted):
        def __init__(self):
            self.sets = None
            self.index = 0

        def next_call(self, node, prompt, results):
            if node != "x":
                return _identity(node)
            if not results:
                return "summarize_correspondences", {"reading": "local", "min_support": 1,
                                                      "limit": 200, "include_outgroup": True}
            if self.sets is None:
                self.sets = [s for s in results[0]["sets"] if None in s["segments"]]
            if self.index < len(self.sets):
                item = self.sets[self.index]
                self.index += 1
                return "polarize", {"child_ids": ["a", "b"], "correspondence": item["segments"],
                                    "set_id": item["set_id"]}
            return _identity(node)

    pol_result = run_scripted(PAYLOAD_C, Polarizing(), protocol="stored-hypothesis", instructions=C_TEXT)
    pol_nav = navigation(CASE_C, {t.node_id: t for t in pol_result.trajectories}["x"])
    assert pol_nav["calls"]["polarize"] == len(CASE_C["opportunities"])
    assert pol_nav["concepts_with_every_outgroup_form_seen"] == 19


def test_missing_and_fallback_outputs_stay_in_the_denominators(tmp_path):
    result = _run("identification")
    step = next(s for s in result.snapshot.steps if s.parent_node_id == "x")
    trajectory = {t.node_id: t for t in result.trajectories}
    full = score_judgment(CASE_C, {"x": step}, model_committed={"x": True}, trajectories_by_node=trajectory)
    assert full["primary"]["model_committed_correct"] == 19
    # No output at all: every opportunity is missing, nothing is credited, and labels say no commit.
    empty = score_judgment(CASE_C, {}, model_committed={}, trajectories_by_node={})
    assert empty["primary"]["planned_opportunities"] == 19 and empty["primary"]["model_committed_correct"] == 0
    assert empty["primary"]["readings"] == {"missing": 19} and empty["uncertainty"]["ties_marked"] == 0
    assert empty["labels"]["value"] == "no commit" and empty["labels"]["uncertainty"] == "no commit"
    # A fallback commit's correct outputs are not model decisions, its ties are not marked, and labels say no commit.
    fallback = step.model_copy(update={"diagnostics": step.diagnostics.model_copy(update={"failure_fallback": True})})
    reading = score_judgment(CASE_C, {"x": fallback}, model_committed={"x": True}, trajectories_by_node=trajectory)
    assert reading["primary"]["model_committed_correct"] == 0 and reading["uncertainty"]["ties_marked"] == 0
    assert reading["labels"]["value"] == "no commit" and reading["labels"]["uncertainty"] == "no commit"
    # Analysis removed: unscorable, never credited as absent.
    stripped = step.model_copy(update={"output_beam": step.output_beam.model_copy(update={"distributions": tuple(
        d.model_copy(update={"candidates": tuple(c.model_copy(update={"analysis": None}) for c in d.candidates)})
        for d in step.output_beam.distributions)})})
    blind = score_judgment(CASE_C, {"x": stripped}, model_committed={"x": True}, trajectories_by_node=trajectory)
    assert blind["primary"]["readings"] == {"unscorable": 19} and blind["primary"]["model_committed_correct"] == 0


class Recording(PanelBaseline):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.requests = []

    def complete(self, messages, tools, **kwargs):
        self.requests.append(json.dumps([m.model_dump(mode="json") for m in messages])
                             + json.dumps([t.model_dump(mode="json") for t in tools]))
        return super().complete(messages, tools, **kwargs)


def test_operator_fields_and_targets_never_reach_a_request():
    sentinel = "QZSENTINELQZ"
    bindings = tuple(b.model_copy(update={
        "target_validity_note": sentinel,
        "forms": b.forms + (b.forms[0].model_copy(update={
            "form_id": "x:sentinel", "segments": (sentinel,), "cognate_memberships": ()}),),
    }) for b in PAYLOAD_C.historical_form_bindings)
    payload = PAYLOAD_C.model_copy(update={"historical_form_bindings": bindings})
    provider = Recording(CASE_C, "identification")
    run_scripted(payload, provider, protocol="stored-hypothesis", instructions=C_TEXT)
    joined = "\n".join(provider.requests)
    assert sentinel not in joined and "## Stage C task" in joined
    assert "## Stage B task" not in joined and "## Stage A" not in joined
    for opportunity in CASE_C["opportunities"]:
        assert opportunity["opportunity_id"] not in joined
        assert f'"{opportunity["design_id"]}"' not in joined
    for key in ("outgroup_states", "shallow_rule_errors", *CASE_C["shallow_rules"], CASE_C["generated_history"],
                CASE_C["independent_evidence"], CASE_C["question"]):
        assert key not in joined
    plain = Recording(CASE_C, "identification")
    run_scripted(PAYLOAD_C, plain, protocol="stored-hypothesis", instructions=C_TEXT)
    assert plain.requests == provider.requests
    # The criterion block names no concept, unit, design label or outgroup reflex token.
    block = " ".join(CASE_C["task_block"])
    assert not any(o["concept_id"] in block or o["unit"] in block for o in CASE_C["opportunities"])
    assert "kʰ" not in block
    assert "regularly corresponding reflex" in block
    assert "any general instruction above or a note in a tool result" in block
    assert "c's g, d's k and f's kʰ correspond to k" not in CASE_C["independent_evidence"]
    # Stage C shares no concept or unit ID with the R02 development stages.
    units = lambda c: {u for forms in c["observed"].values() for pieces in forms.values() for u, _ in pieces}
    for other in (CASE_A, CASE_B):
        assert not units(CASE_C) & units(other)
        assert not set(CASE_C["observed"]["a"]) & set(other["observed"]["a"])


def _cli(run_dir, monkeypatch, provider, *extra):
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "input.json").write_text(PAYLOAD_C.model_dump_json())
    (run_dir / "instructions.md").write_text(C_TEXT)
    real = LiteLLMProvider
    monkeypatch.setattr(cli, "LiteLLMProvider", lambda model, **kw: real(
        model, completion_fn=completion_from(provider), **kw))
    cli.main(["infer", "--input", str(run_dir / "input.json"), "--model", "test-model",
              "--output", str(run_dir / "result.json"), "--trajectories", str(run_dir / "trajectories.jsonl"),
              "--checkpoint", str(run_dir / "checkpoint.json"), "--events", str(run_dir / "events.jsonl"),
              "--agent-instructions", str(run_dir / "instructions.md"), "--reasoning-history", "drop",
              "--price-table", str(_price_table(run_dir)), "--max-total-cost-usd", "1",
              "--run-id", "r04-c-scripted", "--quiet", *extra])


def test_planned_stop_scores_x_and_never_attempts_the_root(tmp_path, monkeypatch):
    run_dir = tmp_path / "c"
    _cli(run_dir, monkeypatch, PanelBaseline(CASE_C, "identification"), "--stop-after-node", "x")
    assert not (run_dir / "result.json").exists()
    summary = json.loads((run_dir / "run_summary.json").read_text())
    assert (summary["status"], summary["failure_kind"], summary["stop_after_node"]) == ("interrupted", "planned_stop", "x")
    nodes = {json.loads(line)["node_id"] for line in (run_dir / "trajectories.jsonl").read_text().splitlines()}
    assert nodes == {"x"}
    journal = [json.loads(line) for line in (run_dir / "checkpoint.requests.jsonl").read_text().splitlines()]
    assert {e.get("node_id") for e in journal if e.get("event") == "request_start"} == {"x"}
    report = evaluate_stage_c(CASE_C, run_dir)
    assert report["stage_gate"]["usable"] and report["failure_kind"] == "planned_stop"
    assert report["judgment"]["primary"]["model_committed_correct"] == 19
    resources = read_run_resources(run_dir)
    assert resources.outcome == "interrupted" and resources.cost_known and resources.unknown_cost_requests == 0


def test_planned_stop_refuses_an_unknown_node_and_is_a_no_op_at_the_root(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        _cli(tmp_path / "bad", monkeypatch, PanelBaseline(CASE_C, "identification"), "--stop-after-node", "a")
    run_dir = tmp_path / "root"
    _cli(run_dir, monkeypatch, PanelBaseline(CASE_C, "identification"), "--stop-after-node", "r")
    assert (run_dir / "result.json").exists()
    assert json.loads((run_dir / "run_summary.json").read_text())["status"] != "interrupted"
    nodes = {json.loads(line)["node_id"] for line in (run_dir / "trajectories.jsonl").read_text().splitlines()}
    assert nodes == {"x", "r"}


def test_frozen_arm_sends_the_32k_cap_and_reserves_for_it(tmp_path):
    import subprocess
    import sys
    batch = tmp_path / "batch"
    frozen = freeze(batch)
    plan_path = batch / "plan.json"
    plan = json.loads(plan_path.read_text())
    (trial,) = plan["trials"]
    argv = trial["argv"]
    option = lambda name: argv[argv.index(name) + 1]
    assert option("--stop-after-node") == "x" and option("--reasoning-history") == "auto"
    assert option("--reasoning-effort") == "medium" and option("--preset") == "gemini"
    assert float(option("--max-retry-seconds")) >= float(option("--timeout"))
    config = json.loads(Path(option("--provider-config")).read_text())
    assert config == {"max_tokens": 32_768} == {"max_tokens": ARM["max_output_tokens"]}
    bound = frozen["resources"]
    # One maximum response of headroom: the context limit in and the 32,768 cap out.
    assert bound["one_response_headroom_usd"] == pytest.approx((1_048_576 * 0.75 + 32_768 * 3.75) / 1e6)
    assert trial["reservation"]["cost_usd"] >= bound["worst_case_trial_usd"]
    assert trial["reservation"]["cost_usd"] <= plan["ceilings"]["gemini-r04"]["cost_usd"]
    assert trial["reservation"]["wall_seconds"] <= plan["ceilings"]["gemini-r04"]["wall_seconds"]
    repo = Path(__file__).resolve().parents[2]
    dry = subprocess.run([sys.executable, str(repo / "tools/experiment_batch.py"), "run", "--plan",
                          str(plan_path), "--dry-run"], capture_output=True, text=True, cwd=repo)
    assert dry.returncode == 0 and "would_launch" in dry.stdout, dry.stdout + dry.stderr
    manifest = json.loads((batch / "manifest.stage-c.json").read_text())
    assert manifest["model_visible"]["the tool schemas"].startswith("628f0f32")


FAKE_INFER = r'''
import sys
sys.path.insert(0, {repo!r})
from cognate_reconstruction import cli
from cognate_reconstruction.agent.providers.litellm_provider import LiteLLMProvider
from tests.workbench.test_r02_instruments import completion_from
from tests.workbench.test_r04_judgment import CASE_C
from tools.r04_judgment import PanelBaseline

argv, out, skip = sys.argv[1:], [], 0
for value in argv:
    if skip:
        skip -= 1
        continue
    if value in ("--preset", "--reasoning-effort"):
        skip = 1
        continue
    if value == "--model":
        out += ["--model", "test-model"]; skip = 1; continue
    if value == "--price-table":
        out += ["--price-table", {table!r}]; skip = 1; continue
    # Gemini resolves auto to drop; the stand-in model has no template to read.
    out.append("drop" if value == "auto" else value)
real = LiteLLMProvider
cli.LiteLLMProvider = lambda model, **kw: real(model, completion_fn=completion_from(
    PanelBaseline(CASE_C, "identification")), **kw)
cli.main(["infer"] + out)
'''


def test_frozen_plan_runs_once_stops_after_x_and_is_evaluated(tmp_path):
    import subprocess
    import sys
    repo = Path(__file__).resolve().parents[2]
    batch = tmp_path / "batch"
    freeze(batch)
    script = tmp_path / "fake_infer.py"
    script.write_text(FAKE_INFER.format(repo=str(repo), table=str(_price_table(tmp_path))))
    plan = json.loads((batch / "plan.json").read_text())
    plan["trials"][0]["argv"] = ["{python}", str(script)] + plan["trials"][0]["argv"][4:]
    (batch / "plan.json").write_text(json.dumps(plan))
    done = subprocess.run([sys.executable, str(repo / "tools/experiment_batch.py"), "run",
                           "--plan", str(batch / "plan.json")], capture_output=True, text=True, cwd=repo)
    assert done.returncode == 0, done.stderr[-3000:]
    events = [json.loads(line) for line in (batch / "batch_events.jsonl").read_text().splitlines()]
    finished = next(e for e in events if e["event"] == "finished")
    assert finished["exit_code"] == 0
    evaluation = json.loads((batch / "runs/c-gemini-r04/evaluation.json").read_text())
    assert evaluation["stage_gate"]["usable"]
    assert evaluation["judgment"]["primary"]["model_committed_correct"] == 19
    ledger = json.loads((batch / "batch_ledger.json").read_text())
    arm = ledger["totals"]["arms"]["gemini-r04"]
    assert arm["cost_known"] and arm["outcomes"]["interrupted"] == 1


@pytest.mark.parametrize("cut_turn", [1, 2])
def test_a_response_cut_off_at_the_cap_is_recovered_priced_and_x_still_scored(tmp_path, monkeypatch, cut_turn):
    # The R04 arm raises the cap to 32,768 because a cap hit is likely on the
    # harder panel; on the Gemini route such a reply has no text and no call.
    run_dir = tmp_path / f"cut-{cut_turn}"
    run_dir.mkdir()
    (run_dir / "input.json").write_text(PAYLOAD_C.model_dump_json())
    (run_dir / "instructions.md").write_text(C_TEXT)
    table = run_dir / "prices.json"
    table.write_text(json.dumps({"price_table_version": "price-table-v1", "prices": [{
        "model": "gemini/test-model", "input_usd_per_million": 0.75, "output_usd_per_million": 3.75,
        "valid_through": "2099-12-31", "tier": "test", "source_url": "https://example.invalid",
        "read_on": "2026-10-28"}]}))
    scripted = completion_from(PanelBaseline(CASE_C, "identification"))
    sent = []

    def complete(**kwargs):
        sent.append(kwargs["messages"])
        if len(sent) == cut_turn:
            return {"id": "cut", "model": "test", "choices": [{"finish_reason": "length", "message": {
                "content": None}}], "usage": {"prompt_tokens": 2000, "completion_tokens": 32768, "total_tokens": 34768}}
        # As LiteLLM's Gemini mapping does, a content-less model turn is dropped.
        return scripted(**{**kwargs, "messages": [m for m in kwargs["messages"] if not (
            m["role"] == "assistant" and m.get("content") is None and not m.get("tool_calls"))]})
    real = LiteLLMProvider
    monkeypatch.setattr(cli, "LiteLLMProvider", lambda model, **kw: real(model, completion_fn=complete, **kw))
    cli.main(["infer", "--input", str(run_dir / "input.json"), "--model", "gemini/test-model",
              "--output", str(run_dir / "result.json"), "--trajectories", str(run_dir / "trajectories.jsonl"),
              "--checkpoint", str(run_dir / "checkpoint.json"), "--no-events", "--quiet",
              "--agent-instructions", str(run_dir / "instructions.md"), "--reasoning-history", "drop",
              "--price-table", str(table), "--max-total-cost-usd", "1", "--stop-after-node", "x",
              "--run-id", "r04-c-cut"])
    # The empty turn was not sent back as content; the recovery message was.
    after = sent[cut_turn]
    assert after[-2] == {"role": "assistant"}
    assert "cut off at the output limit" in after[-1]["content"]
    report = evaluate_stage_c(CASE_C, run_dir)
    assert report["stage_gate"]["usable"] and report["judgment"]["primary"]["model_committed_correct"] == 19
    resources = read_run_resources(run_dir)
    assert resources.cost_known and resources.unknown_cost_requests == 0
    assert resources.max_response_output_tokens == 32768
