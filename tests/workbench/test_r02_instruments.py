"""R02 Stage A/B instruments: fixtures, scorers, baselines and evidence isolation.

Every provider is scripted. Stage A's operator executes the supplied
hypothesis; deviations are scripted too, to show what the checker refuses.
Stage B's baselines and controls go through the ordinary service, JSONL and
the normal evaluator. Nothing here is a model result.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from cognate_reconstruction import cli
from cognate_reconstruction.agent.instructions import load_agent_instructions
from cognate_reconstruction.agent.providers.litellm_provider import LiteLLMProvider
from cognate_reconstruction.agent.schemas import LLMMessage, LLMToolCall, MessageRole
from cognate_reconstruction.benchmarks.ledger import read_run_resources
from cognate_reconstruction.evaluation.decisions import score_decisions
from cognate_reconstruction.evaluation.run import evaluate_run
from cognate_reconstruction.evaluation.usability import check_stage_a, instruction_block
from cognate_reconstruction.synthesis.diagnostics import build_explicit_case, load_explicit_case
from tools.r02_diagnostics import (
    STAGE_A, STAGE_B, StageAOperator, StageBBaseline, evaluate_stage_a, evaluate_stage_b,
    fixed_daughter_step, run_scripted, stage_a_instruction_file, stage_b_instruction_file,
)

CASE_A = load_explicit_case(STAGE_A)
CASE_B = load_explicit_case(STAGE_B)
PAYLOAD_A = build_explicit_case(CASE_A)
PAYLOAD_B = build_explicit_case(CASE_B)
PACKAGED = load_agent_instructions()
B_TEXT = stage_b_instruction_file(CASE_B)
PROTOCOLS = ("stored-hypothesis", "full-payload")


# Stage A -------------------------------------------------------------------

def completion_from(provider, usage=(2000, 300)):
    """An OpenAI-shaped completion function driving a scripted provider.

    Arguments cross as JSON strings in both directions, as from a real
    provider, so the native JSON boundary and the LiteLLM adapter are exercised.
    """
    def complete(*, model, messages, tools, tool_choice, **options):
        converted = [LLMMessage(
            role=MessageRole(m["role"]), content=m.get("content"),
            tool_calls=tuple(LLMToolCall(call_id=c["id"], name=c["function"]["name"],
                                         arguments=json.loads(c["function"]["arguments"]))
                             for c in m.get("tool_calls", ())),
            tool_call_id=m.get("tool_call_id"), name=m.get("name")) for m in messages]
        reply = provider.complete(converted, tools)
        return {"id": "r", "model": model, "choices": [{"finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": reply.content, "tool_calls": [
                {"id": c.call_id, "type": "function",
                 "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                for c in reply.tool_calls]}}],
            "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1],
                      "total_tokens": sum(usage)}}
    return complete


def _price_table(tmp_path):
    path = tmp_path / "prices.json"
    path.write_text(json.dumps({"price_table_version": "price-table-v1", "prices": [{
        "model": "test-model", "input_usd_per_million": 0.75, "output_usd_per_million": 3.75,
        "valid_through": "2099-12-31", "tier": "test", "source_url": "https://example.invalid",
        "read_on": "2026-10-25"}]}))
    return path


def _cli_stage_a(run_dir, monkeypatch, provider, protocol):
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "input.json").write_text(PAYLOAD_A.model_dump_json())
    instructions = run_dir / "instructions.md"
    instructions.write_text(stage_a_instruction_file(CASE_A, protocol))
    real = LiteLLMProvider
    monkeypatch.setattr(cli, "LiteLLMProvider", lambda model, **kw: real(
        model, completion_fn=completion_from(provider), **kw))
    cli.main(["infer", "--input", str(run_dir / "input.json"), "--model", "test-model",
              "--output", str(run_dir / "result.json"), "--trajectories", str(run_dir / "trajectories.jsonl"),
              "--checkpoint", str(run_dir / "checkpoint.json"), "--events", str(run_dir / "events.jsonl"),
              "--agent-instructions", str(instructions), "--inventory-protocol", protocol,
              "--price-table", str(_price_table(run_dir)), "--max-total-cost-usd", "1",
              "--max-turns", "12", "--run-id", f"r02-a-{protocol}", "--quiet"])


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_stage_a_supplied_hypothesis_succeeds_through_the_native_cli_path(tmp_path, monkeypatch, protocol):
    run_dir = tmp_path / "a"
    _cli_stage_a(run_dir, monkeypatch, StageAOperator(CASE_A, protocol), protocol)
    report = evaluate_stage_a(CASE_A, run_dir, protocol)
    assert report["outcome"] == "success", report
    assert all(report["criteria"].values()) and report["stage_gate"]["usable"]
    assert report["readback"] and all(report["readback"].values())
    assert report["shape_matches_supplied"]
    # The nonempty token condition survives the JSON round trip into the artifact.
    trajectory = [json.loads(line) for line in (run_dir / "trajectories.jsonl").read_text().splitlines()][-1]
    conditions = [c["conditioning"] for c in trajectory["committed_reconstruction"]["request"]["commitments"]
                  if c.get("conditioning")]
    assert conditions and all(c["right"]["tokens"] == ["i"] for c in conditions)
    # The ordinary run summary and the batch ledger agree on priced effort.
    resources = read_run_resources(run_dir)
    summary = json.loads((run_dir / "run_summary.json").read_text())["usage"]
    assert resources.cost_known and resources.turns == summary["turns"] == 5
    assert resources.known_cost_usd == pytest.approx(summary["reported_cost_usd"])


class SkipRevision(StageAOperator):
    def next_call(self, node, prompt, results):
        if len(results) == 2:  # preview the revised hypothesis directly
            return "test_proto_assembly", self.hypothesis(results[0]["sets"], results[1]["sets"], revised=True)
        if len(results) == 3:
            return "commit_reconstruction", {"node_id": node, "anomalies": [], "summary": "s",
                                             "hypothesis_id": results[2]["hypothesis_id"]}
        return super().next_call(node, prompt, results)


class PatternInsteadOfUnit(StageAOperator):
    """Nulls the m:m recurrence pattern, which also holds core units."""

    def hypothesis(self, patterns, local, revised):
        hypothesis = super().hypothesis(patterns, local, revised)
        mm = next(p for p in patterns if p["segments"] == ["m", "m"])
        hypothesis["choices"] = [c for c in hypothesis["choices"]
                                 if c["set_id"] not in mm["member_set_ids"]]
        hypothesis["shared_claims"].append({
            "pattern_id": mm["set_id"], "member_set_ids": mm["member_set_ids"], "proto_segment": None,
            "confidence": .7, "rationale": "r", "directionality_rationale": "d"})
        return hypothesis


class WrongCondition(StageAOperator):
    def hypothesis(self, patterns, local, revised):
        hypothesis = super().hypothesis(patterns, local, revised)
        hypothesis["shared_claims"][0]["conditioning"] = {"right": {"tokens": ["a"]}}
        return hypothesis


class IdentityOnly(StageAOperator):
    def next_call(self, node, prompt, results):
        return "commit_reconstruction", {"node_id": node, "rules": [], "anomalies": [], "summary": "s"}


@pytest.mark.parametrize("operator,outcome,usable", [
    (SkipRevision, "usable_revision_protocol_deviation", True),
    (PatternInsteadOfUnit, "committed_other_hypothesis", False),
    (WrongCondition, "committed_other_hypothesis", False),
    (IdentityOnly, "committed_other_hypothesis", False),
])
def test_stage_a_checker_separates_deviations(tmp_path, operator, outcome, usable):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    run_scripted(PAYLOAD_A, operator(CASE_A, "stored-hypothesis"), protocol="stored-hypothesis",
                 instructions=stage_a_instruction_file(CASE_A, "stored-hypothesis"), out_dir=run_dir)
    report = evaluate_stage_a(CASE_A, run_dir, "stored-hypothesis")
    assert (report["outcome"], report["stage_gate"]["usable"]) == (outcome, usable), report["criteria"]
    if operator is PatternInsteadOfUnit:
        # The unit-scope error deletes core m: the output shows it.
        assert report["output"]["q05"]["segments"] == ["a", "n"]
        assert report["commit_extra_claims"]
    if operator is WrongCondition:
        assert report["output"]["q01"]["segments"] == ["f", "i"]


class EmptyConditioning(StageAOperator):
    """`{}` conditions nothing; the audit found it read as a different claim."""

    def hypothesis(self, patterns, local, revised):
        hypothesis = super().hypothesis(patterns, local, revised)
        for row in hypothesis["choices"]:
            row["conditioning"] = {}
        return hypothesis


class ProseThenFix(StageAOperator):
    """Original; revised with other prose and a missing directionality (not
    commit-ready); the revised claims fixed in a third preview; commit that."""

    def next_call(self, node, prompt, results):
        if len(results) < 3:
            return super().next_call(node, prompt, results)
        patterns, local = results[0]["sets"], results[1]["sets"]
        if len(results) == 3:
            draft = self.hypothesis(patterns, local, revised=True)
            draft["shared_claims"][0]["rationale"] = "reworded rationale"
            draft["choices"][0].pop("directionality_rationale")
            return "test_proto_assembly", draft
        if len(results) == 4:
            assert not results[3]["commit_ready"]
            return "test_proto_assembly", self.hypothesis(patterns, local, revised=True)
        return "commit_reconstruction", {"node_id": node, "anomalies": [], "summary": "s",
                                         "hypothesis_id": results[4]["hypothesis_id"]}


class InventoryCommitInStoredProfile(StageAOperator):
    def next_call(self, node, prompt, results):
        if len(results) == 4:
            from tools.r02_diagnostics import _children
            # The stored profile's inventory path takes full commitments.
            self.protocol = "full-payload"
            inventory = {"child_node_ids": _children(prompt),
                         **self.hypothesis(results[0]["sets"], results[1]["sets"], revised=True)}
            self.protocol = "stored-hypothesis"
            return "commit_reconstruction", {"node_id": node, "anomalies": [], "summary": "s",
                                             "inventory": inventory}
        return super().next_call(node, prompt, results)


@pytest.mark.parametrize("operator", [EmptyConditioning, ProseThenFix, InventoryCommitInStoredProfile])
def test_stage_a_checker_accepts_equivalent_correct_executions(tmp_path, operator):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    run_scripted(PAYLOAD_A, operator(CASE_A, "stored-hypothesis"), protocol="stored-hypothesis",
                 instructions=stage_a_instruction_file(CASE_A, "stored-hypothesis"), out_dir=run_dir)
    report = evaluate_stage_a(CASE_A, run_dir, "stored-hypothesis")
    assert report["outcome"] == "success", report["criteria"]


def test_stage_a_without_a_session_or_commit_is_not_usable():
    report = check_stage_a(CASE_A, PAYLOAD_A, None, None, protocol="stored-hypothesis")
    assert report["outcome"] == "no_session" and not report["stage_gate"]["usable"]


def test_stage_instructions_are_separate_hashed_arms_over_the_packaged_text():
    block = instruction_block(CASE_A, "stored-hypothesis")
    text = stage_a_instruction_file(CASE_A, "stored-hypothesis")
    assert text.startswith(PACKAGED.rstrip("\n")) and text.endswith(block)
    digest = lambda value: hashlib.sha256(value.encode()).hexdigest()
    assert digest(PACKAGED).startswith("0b9d91cf")
    assert digest(text) != digest(PACKAGED)
    # B states its identification criterion, never an item, label or answer.
    assert B_TEXT.startswith(PACKAGED.rstrip("\n")) and "fewer changes" in B_TEXT
    assert digest(B_TEXT) not in (digest(PACKAGED), digest(text))
    assert "## Stage A" not in B_TEXT and "u07" not in B_TEXT
    for o in CASE_B["opportunities"]:
        assert o["concept_id"] not in B_TEXT and o["opportunity_id"] not in B_TEXT
    assert "hypothesis_id of the revised preview" in block
    assert "inventory exactly as previewed" in instruction_block(CASE_A, "full-payload")


# Stage B -------------------------------------------------------------------

def _run_b(tmp_path, policy, protocol="stored-hypothesis"):
    run_dir = tmp_path / policy
    run_dir.mkdir(parents=True)
    run_scripted(PAYLOAD_B, StageBBaseline(CASE_B, policy, protocol), protocol=protocol,
                 instructions=B_TEXT, out_dir=run_dir)
    return run_dir


@pytest.mark.parametrize("policy,correct,pairs", [
    ("identity", 10, 0), ("union", 10, 0), ("intersection", 8, 0),
    ("outgroup-witness", 18, 6), ("oracle", 18, 6),
])
def test_stage_b_baselines_through_the_ordinary_path(tmp_path, policy, correct, pairs):
    report = evaluate_stage_b(CASE_B, _run_b(tmp_path, policy))
    primary = report["decisions"]["primary"]
    assert (primary["model_committed_correct"], primary["planned_opportunities"]) == (correct, 18)
    assert report["decisions"]["matched_pairs"]["both_correct"] == pairs
    assert report["task02_evaluation"]["targets"][0]["evaluation"]["evaluator_version"] == "task02-v1"


def test_stage_b_deployable_rule_works_in_both_profiles(tmp_path):
    for protocol in PROTOCOLS:
        report = evaluate_stage_b(CASE_B, _run_b(tmp_path / protocol, "outgroup-witness", protocol))
        assert report["decisions"]["primary"]["correct"] == 18
        assert report["decisions"]["decided_by"] == {"explicit_claim": 18}


def test_fixed_daughters_cannot_solve_the_panel(tmp_path):
    run_dir = _run_b(tmp_path, "identity")
    steps = {s["parent_node_id"]: s for s in json.loads((run_dir / "result.json").read_text())["snapshot"]["steps"]}
    from cognate_reconstruction.schemas.traversal import ReconstructionStep
    step = ReconstructionStep.model_validate_json(json.dumps(steps["x"]))
    scores = {v: score_decisions(CASE_B, {"x": fixed_daughter_step(step, PAYLOAD_B, v)})
              for v in ("a", "b", "c")}
    assert {v: s["primary"]["correct"] for v, s in scores.items()} == {"a": 8, "b": 10, "c": 11}
    assert all(s["matched_pairs"]["both_correct"] == 0 for v, s in scores.items() if v != "c")
    # Copying the outgroup gives other values (g for k), never a solution.
    assert scores["c"]["primary"]["readings"]["other"] == 7


def _oracle_step(tmp_path):
    run_dir = _run_b(tmp_path, "oracle")
    result = json.loads((run_dir / "result.json").read_text())
    return run_dir, result


def _replace_x(result, transform):
    result = json.loads(json.dumps(result))
    for step in result["snapshot"]["steps"]:
        if step["parent_node_id"] == "x":
            step["output_beam"]["distributions"] = transform(step["output_beam"]["distributions"])
    return result


def _score(result):
    from cognate_reconstruction.schemas.traversal import ReconstructionStep
    steps = {s["parent_node_id"]: ReconstructionStep.model_validate_json(json.dumps(s))
             for s in result["snapshot"]["steps"]}
    return score_decisions(CASE_B, steps)["primary"], evaluate_run(PAYLOAD_B, result, ())


def test_decision_scorer_controls_through_the_normal_evaluator(tmp_path):
    _, result = _oracle_step(tmp_path)
    perfect, report = _score(result)
    assert perfect["correct"] == 18 and report.raw_target_summary.output_top_hits == 16

    def drop_analysis(distributions):
        for d in distributions:
            for c in d["candidates"]:
                c["analysis"] = None
        return distributions
    unknown, report = _score(_replace_x(result, drop_analysis))
    # Deleting analysis cannot raise the primary rate: it shrinks scorable, not planned.
    assert unknown["planned_opportunities"] == 18 and unknown["correct"] == 0
    assert unknown["readings"] == {"unscorable": 18}
    assert report.raw_target_summary.output_top_hits == 16  # raw exact is unaffected

    missing, report = _score(_replace_x(result, lambda ds: ds[:7]))
    assert missing["planned_opportunities"] == 18 and missing["correct"] < 18
    assert missing["readings"].get("missing", 0) > 0
    assert report.raw_target_summary.missing_outputs == 9

    def reorder(distributions):
        for d in distributions:
            for c in d["candidates"]:
                pieces = c["analysis"]["pieces"]
                if len(pieces) == 3:  # core + boundary + suffix -> suffix + boundary + core
                    tokens = c["segments"]
                    spans = [[tokens[i] for i in p["segment_indices"]] for p in pieces]
                    order = [2, 1, 0]
                    flat, start = [], 0
                    for index in order:
                        piece = pieces[index]
                        width = len(piece["segment_indices"])
                        piece["segment_indices"] = list(range(start, start + width))
                        flat += spans[index]
                        start += width
                    c["segments"] = flat
                    c["analysis"]["pieces"] = [pieces[i] for i in order]
        return distributions
    reordered, report = _score(_replace_x(result, reorder))
    # Piece retention is order-free; raw whole-word exact is not.
    assert reordered["correct"] == 18
    assert report.raw_target_summary.output_top_hits == 14

    def add_suffix(distributions):
        for d in distributions:
            if d["concept_id"] == "w02":  # S1: suffix c61 should be absent
                c = d["candidates"][0]
                n = len(c["segments"])
                c["segments"] = c["segments"] + ["+", "k", "o"]
                c["analysis"]["pieces"] += [
                    {"unit_id": "boundary:extra", "cognate_set_id": None, "kind": "boundary",
                     "segment_indices": [n], "sources": [], "column_ids": []},
                    {"unit_id": "cog:c61", "cognate_set_id": "c61", "kind": "cognate",
                     "segment_indices": [n + 1, n + 2], "sources": [], "column_ids": []}]
        return distributions
    extra, _ = _score(_replace_x(result, add_suffix))
    assert extra["correct"] == 17

    def wrong_value(distributions):
        for d in distributions:
            if d["concept_id"] == "w09":  # R1: final k replaced by g
                d["candidates"][0]["segments"][-1] = "g"
        return distributions
    other, _ = _score(_replace_x(result, wrong_value))
    assert other["correct"] == 17 and other["readings"]["other"] == 1

    def relabel(distributions):
        for d in distributions:
            if d["concept_id"] == "w11":  # A1: keeps `t o k` under another label
                for piece in d["candidates"][0]["analysis"]["pieces"]:
                    piece["cognate_set_id"] = "relabelled"
        return distributions
    relabelled, _ = _score(_replace_x(result, relabel))
    # A lost unit label is never credited as the absent edge.
    assert relabelled["correct"] == 17 and relabelled["readings"]["unit_missing"] == 1


def test_fallback_output_is_not_a_model_decision(tmp_path):
    _, result = _oracle_step(tmp_path)
    from cognate_reconstruction.schemas.traversal import ReconstructionStep
    steps = {s["parent_node_id"]: ReconstructionStep.model_validate_json(json.dumps(s))
             for s in result["snapshot"]["steps"]}
    fallback = steps["x"].model_copy(update={"diagnostics": steps["x"].diagnostics.model_copy(
        update={"failure_fallback": True})})
    primary = score_decisions(CASE_B, {"x": fallback})["primary"]
    assert primary["correct"] == 18 and primary["model_committed_correct"] == 0


# Definitions and isolation ------------------------------------------------

def test_stage_b_expected_decisions_follow_the_stated_identification_rule():
    observed = CASE_B["observed"]
    for o in CASE_B["opportunities"]:
        units = {v: dict(observed[v].get(o["concept_id"], [])) for v in ("a", "b", "c")}

        def has(variety):
            if o["locus"] == "piece":
                return o["unit"] in units[variety]
            text = units[variety].get(o["unit"])
            if text is None:
                return False
            edge = text.split()[-1 if o["locus"] == "final" else 0]
            return edge == o["token"] or (variety == "c" and (o["token"], edge) == ("k", "g"))
        daughters = [has("a"), has("b")]
        assert sum(daughters) == 1, o  # exactly one active child has the material
        if o["concept_id"] not in observed["c"]:
            assert o["expected"] == "unresolved" and o["class"] == "ambiguous"
        else:
            assert o["expected"] == ("retain" if has("c") else "absent"), o
    # The two complementary etyma are attested whole in no daughter.
    targets = CASE_B["targets"]["x"]["forms"]
    for design in ("C1", "C2"):
        concept = next(c for c, d in CASE_B["design_ids"].items() if d == design)
        target = targets[concept][0]
        assert all(observed[v][concept] != target for v in ("a", "b"))


def test_stage_b_recurrence_holds_both_answers_and_no_visible_cue_predicts_them():
    # a ends every core in k (retained or added) and b never does, so the
    # a-only final k is one recurrent pattern holding both answers.
    finals = [o for o in CASE_B["opportunities"] if o["token"] == "k" and o["class"] == "primary"
              and o["basis"] in ("outgroup_presence", "outgroup_absence")]
    assert sorted(o["expected"] for o in finals) == ["absent"] * 6 + ["retain"] * 4
    # Matched pairs differ only in c: same vowel before k, same stem kind.
    observed = CASE_B["observed"]
    for pair, (first, second) in CASE_B["matched_pairs"].items():
        one, two = (next(o for o in CASE_B["opportunities"] if o["opportunity_id"] == m) for m in (first, second))
        assert {one["expected"], two["expected"]} == {"retain", "absent"}
        def shape(o):
            a, b = observed["a"][o["concept_id"]], observed["b"][o["concept_id"]]
            a_core, b_core = a[0][1].split(), b[0][1].split()
            vowel = a_core[-2] if o["locus"] == "final" else None
            return (len(a), len(b), a_core[-1], b_core[-1], vowel)
        assert shape(one) == shape(two), pair
    # The audit's no-outgroup heuristics are at chance on the pairs.
    def heuristic(o):
        a = dict(observed["a"][o["concept_id"]])[next(iter(dict(observed["a"][o["concept_id"]])))].split()
        b_core = observed["b"][o["concept_id"]][0][1].split()
        if o["locus"] == "piece":  # drop b's suffix when a's stem has a k that b lacks
            return "absent" if a[-1] == "k" and b_core[-1] != "k" else "retain"
        return "absent" if len(a) > 1 and a[-2] == "u" else "retain"  # drop k after u
    primary = [o for o in CASE_B["opportunities"] if o["class"] == "primary"]
    correct = {o["opportunity_id"] for o in primary if heuristic(o) == o["expected"]}
    pairs = sum(all(m in correct for m in members) for members in CASE_B["matched_pairs"].values())
    assert pairs <= 3 and len(correct) <= 12


def _visible(payload):
    return json.dumps({"lexicons": [l.model_dump(mode="json") for l in payload.lexicons],
                       "concepts": [c.model_dump(mode="json") for c in payload.concepts],
                       "newick": payload.newick})


def test_operator_fields_never_enter_model_evidence():
    for case, payload in ((CASE_A, PAYLOAD_A), (CASE_B, PAYLOAD_B)):
        visible = _visible(payload)
        for key in ("question", "independent_evidence", "equivalent_solutions", "generated_history"):
            if key in case:
                assert case[key] not in visible
        for opportunity in case.get("opportunities", ()):
            assert opportunity["opportunity_id"] not in visible
            assert opportunity["design_id"] not in visible
        assert "Stage A" not in visible
    # A and B share no unit IDs or concepts.
    units = lambda c: {u for forms in c["observed"].values() for pieces in forms.values() for u, _ in pieces}
    assert not units(CASE_A) & units(CASE_B)
    assert not set(CASE_A["observed"]["a"]) & set(CASE_B["observed"]["a"])


class Recording(StageBBaseline):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.requests = []

    def complete(self, messages, tools, **kwargs):
        self.requests.append(json.dumps([m.model_dump(mode="json") for m in messages])
                             + json.dumps([t.model_dump(mode="json") for t in tools]))
        return super().complete(messages, tools, **kwargs)


def test_scorer_only_targets_never_reach_a_request(tmp_path):
    sentinel = "QZSENTINELQZ"
    bindings = tuple(b.model_copy(update={
        "target_validity_note": sentinel,
        "forms": b.forms + (b.forms[0].model_copy(update={
            "form_id": "x:sentinel", "segments": (sentinel,), "cognate_memberships": ()}),),
    }) for b in PAYLOAD_B.historical_form_bindings)
    payload = PAYLOAD_B.model_copy(update={"historical_form_bindings": bindings})
    provider = Recording(CASE_B, "outgroup-witness")
    run_scripted(payload, provider, protocol="stored-hypothesis", instructions=B_TEXT)
    joined = "\n".join(provider.requests)
    assert sentinel not in joined
    assert "## Stage A" not in joined and "u07" not in joined and "## Stage B task" in joined
    assert all(o["opportunity_id"] not in joined for o in CASE_B["opportunities"])
    # The comparison request: the same scripted policy without the sentinel sends identical bytes.
    plain = Recording(CASE_B, "outgroup-witness")
    run_scripted(PAYLOAD_B, plain, protocol="stored-hypothesis", instructions=B_TEXT)
    assert plain.requests == provider.requests


def test_stage_b_stays_scorable_when_the_cost_cap_stops_the_root_session(tmp_path, monkeypatch):
    # Each fake response costs 0.002625 under the table; x needs three
    # responses (survey, preview, commit), so a 0.008 cap is crossed only by
    # the root's first response. The run is interrupted, x stays scored.
    run_dir = tmp_path / "b"
    run_dir.mkdir()
    (run_dir / "input.json").write_text(PAYLOAD_B.model_dump_json())
    real = LiteLLMProvider
    monkeypatch.setattr(cli, "LiteLLMProvider", lambda model, **kw: real(
        model, completion_fn=completion_from(StageBBaseline(CASE_B, "outgroup-witness")), **kw))
    with pytest.raises(SystemExit):
        cli.main(["infer", "--input", str(run_dir / "input.json"), "--model", "test-model",
                  "--output", str(run_dir / "result.json"), "--trajectories", str(run_dir / "trajectories.jsonl"),
                  "--checkpoint", str(run_dir / "checkpoint.json"), "--no-events", "--quiet",
                  "--price-table", str(_price_table(run_dir)), "--max-total-cost-usd", "0.008",
                  "--run-id", "r02-b-capped"])
    assert not (run_dir / "result.json").exists()
    report = evaluate_stage_b(CASE_B, run_dir)
    assert report["run_status"] == "interrupted"
    assert report["decisions"]["primary"]["correct"] == 18
    assert report["stage_gate"]["usable"]
    resources = read_run_resources(run_dir)
    assert resources.outcome == "interrupted" and resources.cost_known
    assert 0.008 <= resources.known_cost_usd <= 0.008 + 0.002625


FAKE_INFER = r'''
import json, sys
sys.path.insert(0, {repo!r})
from cognate_reconstruction import cli
from cognate_reconstruction.agent.providers.litellm_provider import LiteLLMProvider
from tests.workbench.test_r02_instruments import completion_from, CASE_A, CASE_B
from tools.r02_diagnostics import StageAOperator, StageBBaseline
from tests.workbench.test_r02_instruments import IdentityOnly

argv = sys.argv[1:]
arm = argv[argv.index("--preset") + 1]
stage_a = any(a.endswith("stage-a.payload.json") for a in argv)
# Scripted stand-ins: the paid arm follows the supplied hypothesis, the local
# arm commits identity in Stage A (unusable), so its Stage B must be refused.
if stage_a:
    provider = StageAOperator(CASE_A, "stored-hypothesis") if arm == "gemini" else IdentityOnly(CASE_A, "stored-hypothesis")
else:
    provider = StageBBaseline(CASE_B, "outgroup-witness")
out, skip = [], 0
for index, value in enumerate(argv):
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
    out.append(value)
real = LiteLLMProvider
cli.LiteLLMProvider = lambda model, **kw: real(model, completion_fn=completion_from(provider), **kw)
cli.main(["infer"] + out)
'''


def test_frozen_plan_runs_serially_with_gating_and_a_whole_batch_ledger(tmp_path):
    import subprocess
    import sys
    from tools.r02_diagnostics import freeze
    repo = Path(__file__).resolve().parents[2]
    batch = tmp_path / "batch"
    freeze(batch)
    table = _price_table(tmp_path)
    script = tmp_path / "fake_infer.py"
    script.write_text(FAKE_INFER.format(repo=str(repo), table=str(table)))
    plan = json.loads((batch / "plan.json").read_text())
    for trial in plan["trials"]:
        assert trial["argv"][1:4] == ["-m", "cognate_reconstruction.cli", "infer"]
        # Each request's timeout is clipped to the retry budget; the budget
        # must not silently replace the frozen timeout.
        option = lambda name: float(trial["argv"][trial["argv"].index(name) + 1])
        assert option("--max-retry-seconds") >= option("--timeout")
        trial["argv"] = ["{python}", str(script)] + trial["argv"][4:]
    (batch / "plan.json").write_text(json.dumps(plan))
    done = subprocess.run([sys.executable, str(repo / "tools/experiment_batch.py"), "run",
                           "--plan", str(batch / "plan.json")], capture_output=True, text=True, cwd=repo)
    assert done.returncode == 0, done.stderr[-3000:]
    events = [json.loads(line) for line in (batch / "batch_events.jsonl").read_text().splitlines()]
    decisions = [(e["trial_id"], e["event"]) for e in events if e["event"] in ("launched", "refused")]
    assert decisions == [("A-gemini", "launched"), ("B-gemini", "launched"),
                         ("A-local", "launched"), ("B-local", "refused")]
    ledger = json.loads((batch / "batch_ledger.json").read_text())
    gemini = ledger["totals"]["arms"]["gemini"]
    assert gemini["cost_known"] and 0 < gemini["known_cost_usd"] < plan["ceilings"]["gemini"]["cost_usd"]
    assert gemini["max_request_input_tokens"] == 2000 and gemini["input_tokens"] == 2000 * gemini["provider_requests"]
    b = json.loads((batch / "runs/b-gemini/evaluation.json").read_text())
    assert b["decisions"]["primary"]["correct"] == 18
    a_local = json.loads((batch / "runs/a-local/evaluation.json").read_text())
    assert a_local["outcome"] == "committed_other_hypothesis" and not a_local["stage_gate"]["usable"]
    # A second invocation launches nothing and doubles no output.
    again = subprocess.run([sys.executable, str(repo / "tools/experiment_batch.py"), "run",
                            "--plan", str(batch / "plan.json")], capture_output=True, text=True, cwd=repo)
    assert again.returncode == 0
    later = [json.loads(line) for line in (batch / "batch_events.jsonl").read_text().splitlines()][len(events):]
    assert {e["event"] for e in later} == {"refused"}


def test_local_sampler_variant_sends_gemma_s_published_sampler(tmp_path, monkeypatch):
    # R03's local requests carried only temperature 0.1 and max_tokens; the
    # follow-up arm must send every sampler value itself, and nothing else may change.
    from tools.r02_diagnostics import freeze
    freeze(tmp_path, ("local-vendor-sampling",))
    plan = json.loads((tmp_path / "plan.json").read_text())
    assert [t["trial_id"] for t in plan["trials"]] == ["A-local-vendor-sampling", "B-local-vendor-sampling"]
    assert set(plan["ceilings"]) == {"local-vendor-sampling"}
    config = json.loads((tmp_path / "inputs/local-vendor-sampling.provider-config.json").read_text())
    assert config == {"max_tokens": 16384, "top_k": 64, "top_p": 0.95, "repeat_penalty": 1.0, "min_p": 0.0}
    argv = plan["trials"][0]["argv"]
    assert argv[argv.index("--temperature") + 1] == "1.0"
    args = cli._parser().parse_args([a.replace("{run_dir}", str(tmp_path)) for a in argv[3:]] + ["--no-preflight"])
    provider, _, public, _ = cli._provider_and_configuration(args)
    assert public["temperature"] == 1.0
    assert {k: provider.completion_kwargs[k] for k in config} == config
    # The default freeze is untouched by the variant: no temperature flag, max_tokens only.
    freeze(tmp_path / "default")
    default = json.loads((tmp_path / "default/plan.json").read_text())
    assert all("--temperature" not in t["argv"] for t in default["trials"])
    assert json.loads((tmp_path / "default/inputs/local.provider-config.json").read_text()) == {"max_tokens": 16384}


def test_qwen_arm_sends_the_model_card_s_precise_sampler(tmp_path):
    # R03c: Qwen at its card's thinking-mode "precise coding" sampler, with
    # presence_penalty sent as 0 so no server default can penalise re-cited IDs.
    from tools.r02_diagnostics import freeze
    freeze(tmp_path, ("local-qwen",))
    plan = json.loads((tmp_path / "plan.json").read_text())
    assert [t["trial_id"] for t in plan["trials"]] == ["A-local-qwen", "B-local-qwen"]
    config = json.loads((tmp_path / "inputs/local-qwen.provider-config.json").read_text())
    assert config == {"max_tokens": 16384, "top_k": 20, "top_p": 0.95, "min_p": 0.0,
                      "repeat_penalty": 1.0, "presence_penalty": 0.0}
    argv = plan["trials"][0]["argv"]
    assert argv[argv.index("--model") + 1] == "qwen3.6-35b-a3b"
    args = cli._parser().parse_args([a.replace("{run_dir}", str(tmp_path)) for a in argv[3:]] + ["--no-preflight"])
    provider, _, public, _ = cli._provider_and_configuration(args)
    assert public["temperature"] == 0.6
    assert {k: provider.completion_kwargs[k] for k in config} == config


def test_reasoning_arm_differs_from_r03b_only_by_reasoning_history(tmp_path):
    from tools.r02_diagnostics import freeze
    freeze(tmp_path / "base", ("local-vendor-sampling",))
    freeze(tmp_path / "keep", ("local-vendor-sampling-reasoning",))
    base = json.loads((tmp_path / "base/plan.json").read_text())["trials"][0]["argv"]
    keep = json.loads((tmp_path / "keep/plan.json").read_text())["trials"][0]["argv"]
    strip = lambda argv, root: [a.replace(str(root), "X").replace("local-vendor-sampling-reasoning", "local-vendor-sampling")
                                for a in argv]
    extra = ["--reasoning-history", "keep", "--reasoning-history-budget", "16000", "--reasoning-history-head", "200"]
    keep_n, base_n = strip(keep, tmp_path / "keep"), strip(base, tmp_path / "base")
    at = keep_n.index("--reasoning-history")
    assert keep_n[at:at + len(extra)] == extra and keep_n[:at] + keep_n[at + len(extra):] == base_n
    args = cli._parser().parse_args([a.replace("{run_dir}", str(tmp_path)) for a in keep[3:]] + ["--no-preflight"])
    _, _, public, _ = cli._provider_and_configuration(args)
    assert public["reasoning_history"] == {"mode": "keep", "budget_tokens": 16000, "older_head_tokens": 200}
