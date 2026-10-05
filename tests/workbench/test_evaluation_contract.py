"""Task02-v1: independent questions, explicit denominators and evidence isolation."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from cognate_reconstruction.agent.orchestrator import AgentOrchestrator
from cognate_reconstruction.agent.reconstructor import AgenticNodeReconstructor
from cognate_reconstruction.agent.schemas import LLMMessage, LLMToolCall, MessageRole
from cognate_reconstruction.agent.service import ReconstructionService
from cognate_reconstruction.benchmarks.sweep import aggregate, read_seed, render_text as sweep_text
from cognate_reconstruction.evaluation.diagnostics import compare_cognate_units, token_diagnostics
from cognate_reconstruction.evaluation.metrics import bcubed
from cognate_reconstruction.evaluation.run import evaluate_run, render_text, failure_kind
from cognate_reconstruction.evaluation.targets import _evaluate_target
from cognate_reconstruction.ingestion import ingest_payload
from cognate_reconstruction.inspect_run import RunArtifacts, build_report, render_html, render_text as inspect_text
from cognate_reconstruction.schemas.historical import HistoricalTargetEvaluation, TargetValidity
from cognate_reconstruction.schemas.historical import HistoricalFormBinding, HistoricalFormRole
from cognate_reconstruction.schemas.lexicon import LexicalForm
from cognate_reconstruction.schemas.beam import NodeBeamState
from cognate_reconstruction.schemas.beam import ReconstructionCandidate, ConceptCandidateDistribution
from cognate_reconstruction.schemas.traversal import ReconstructionStep, ReconstructionDiagnostics
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from tests.workbench.test_multi_node_targets_and_sweep import _run, _binding, _lexicon, _IdentityProvider
from tests.workbench.test_node_failure_fallback import CommitProvider


def plan():
    return WorkbenchPayload(
        lexicons=tuple(_lexicon(n) for n in "ABC"), newick="((A,B)INNER,C)PROTO;",
        historical_form_bindings=tuple(_binding(n).model_copy(update={
            "target_validity": TargetValidity.VALIDATED,
        }) for n in ("INNER", "PROTO")),
    )


def raw(result):
    return json.loads(result.model_dump_json(exclude_computed_fields=True))


def test_committed_quality_keeps_copying_and_missing_outputs_visible():
    result = _run()
    steps = list(result.snapshot.steps)
    step = steps[0]
    steps[0] = step.model_copy(update={"output_beam": step.output_beam.model_copy(update={
        "distributions": step.output_beam.distributions[:-1],
    })})
    trajectories = [t.model_copy(update={"reconstruction_step": next(s for s in steps if s.parent_node_id == t.node_id)})
                    for t in result.trajectories]
    report = evaluate_run(plan(), {"snapshot": {"steps": steps}}, trajectories)
    inner = report.targets[0]
    assert inner.output_kind == "committed"
    assert inner.missing_concept_ids == ("water",)  # actual retained order, not a mocked counter
    assert inner.evaluation.top_exact_matches == 2
    assert inner.evaluation.selection.oracle_reachable_concepts == 3
    summary = report.raw_target_summary
    assert summary.planned_concepts == 6 and summary.missing_outputs == 1
    assert summary.committed_node_concepts == 6
    assert summary.conditional_committed_top_exact_rate == pytest.approx(3/6)
    assert summary.conditional_committed_ned_count == 5
    assert summary.end_to_end_model_top_exact_rate == pytest.approx(3/6)


def test_abandoned_run_salvages_only_a_completed_step_and_keeps_plan(tmp_path):
    result = _run()
    first = result.trajectories[0]
    report = evaluate_run(plan(), None, (first,), exit_code=2)
    assert report.run_status == "abandoned_no_result"
    assert report.raw_target_summary.planned_concepts == 6
    assert report.raw_target_summary.available_outputs == 3
    assert report.raw_target_summary.conditional_committed_top_exact_rate == 1
    assert report.raw_target_summary.end_to_end_model_top_exact_rate == 0.5
    assert report.targets[1].missing_concept_ids == ("fire", "stone", "water")
    (tmp_path / "trajectories.jsonl").write_text(first.model_dump_json(exclude_computed_fields=True)+"\n")
    seed = read_seed(0, "abandoned", tmp_path, 2, payload=plan())
    assert seed.abandoned and seed.evaluation_report.raw_target_summary.planned_concepts == 6
    summary = aggregate([seed], benchmark="fixture", model="scripted")
    assert summary["evaluation_views"]["raw_targets"]["missing_outputs"] == 3
    assert "end-to-end model 3/6" in sweep_text(summary)


def test_missing_plan_is_explicit_and_legacy_fields_still_load(tmp_path):
    seed = read_seed(0, "missing", tmp_path, 2)
    summary = aggregate([seed], benchmark="fixture", model="scripted")
    assert summary["evaluation_views"]["seeds_without_plan"] == 1
    assert summary["evaluation_views"]["raw_targets"] is None
    e = raw(_run())["historical_target_evaluations"][0]
    for key in ("evaluator_version", "target_validity", "target_validity_note", "model_committed",
                "descendant_fallback_node_ids", "selection"):
        e.pop(key)
    for concept in e["concepts"]:
        concept.pop("token_diagnostics")
    old = HistoricalTargetEvaluation.model_validate_json(json.dumps(e))
    assert old.evaluator_version is None and old.selection is None
    assert old.top_exact_rate == 1


def test_commit_without_saved_output_has_missing_coverage_not_fabricated_salvage():
    result=_run()
    committed=result.trajectories[0].model_copy(update={"reconstruction_step":None})
    report=evaluate_run(plan(),None,(committed,))
    assert report.targets[0].output_kind=="committed"
    assert report.raw_target_summary.committed_node_concepts==3
    assert report.raw_target_summary.committed_outputs==0
    assert report.raw_target_summary.conditional_committed_top_exact_rate==0
    assert report.raw_target_summary.conditional_committed_mean_ned is None
    incomplete=evaluate_run(plan(),{"snapshot":{"steps":[]}},(committed,))
    assert incomplete.run_status=="result_written_incomplete_or_unknown"


@pytest.mark.parametrize("error_type,expected", [
    ("AgentLoopLimitError", "model_protocol_failure"),
    ("ProtocolStallError", "model_protocol_failure"),
    ("TimeoutError", "infrastructure_interruption_cause_unspecified"),
    ("RateLimitError", "infrastructure_interruption_cause_unspecified"),
    ("RuntimeError", "unknown"),
])
def test_structured_failure_types_are_conservative(error_type, expected):
    result = _run()
    d = raw(result)
    d["snapshot"]["steps"][0]["diagnostics"]["failure_fallback"] = True
    d["node_failures"] = [{"node_id": "INNER", "error_type": error_type,
                           "reason": "do not parse prose to invent a provider cause"}]
    trajectories = (result.trajectories[0].model_copy(update={
        "completed": False, "committed_reconstruction": None,
        "reconstruction_step": None, "failure": "fixture failed session",
    }), result.trajectories[1])
    report = evaluate_run(plan(), d, trajectories)
    assert report.operational_nodes[0].failure_kind == expected
    assert report.targets[0].output_kind == "identity_fallback"
    root = report.targets[1]
    assert root.output_kind == "committed"
    assert root.evaluation.descendant_fallback_node_ids == ("INNER",)
    assert report.raw_target_summary.committed_node_concepts == 3
    assert report.raw_target_summary.fallback_outputs == 3
    assert report.raw_target_summary.fallback_top_hits == 3
    assert report.raw_target_summary.end_to_end_model_top_exact_rate == pytest.approx(1/6)
    assert report.raw_target_summary.end_to_end_output_top_exact_rate == pytest.approx(4/6)


class InspectThenCommit(_IdentityProvider):
    def __init__(self, fail=False):
        self.inspected = set()
        self.fail = fail

    def complete(self, messages, tools, **kwargs):
        wire = json.dumps([m.model_dump(mode="json") for m in messages])
        for sentinel in ("HIDDEN_GOLD_TOKEN", "HIDDEN_BINDING_NOTE", "target_validity",
                         "target_piece_alternatives", "target_unit_layouts"):
            assert sentinel not in wire
            assert sentinel not in json.dumps([t.model_dump(mode="json") for t in tools])
        content = messages[1].content
        initial = json.loads(content[content.index("{"):])
        node = initial["node_id"]
        if self.fail:
            return LLMMessage(role=MessageRole.ASSISTANT, content="No commitment.")
        if node not in self.inspected:
            self.inspected.add(node)
            return LLMMessage(role=MessageRole.ASSISTANT, tool_calls=(LLMToolCall(
                call_id="alignment", name="get_alignments", arguments={
                    "node_ids": [c["node_id"] for c in initial["active_children"]],
                },
            ),))
        return super().complete(messages, tools, **kwargs)


def test_target_content_and_annotations_never_reach_initial_payloads_or_tools():
    payload = plan()
    bindings = tuple(b.model_copy(update={
        "forms": tuple(f.model_copy(update={"segments": ("HIDDEN_GOLD_TOKEN",)}) for f in b.forms),
        "target_validity": TargetValidity.PROVISIONAL_PROXY,
        "target_validity_note": "HIDDEN_BINDING_NOTE",
    }) for b in payload.historical_form_bindings)
    p = payload.model_copy(update={"historical_form_bindings": bindings})
    provider = InspectThenCommit()
    result = ReconstructionService(AgenticNodeReconstructor(AgentOrchestrator(provider))).reconstruct_family(ingest_payload(p))
    assert all(t.completed for t in result.trajectories)
    assert all(any(m.role is MessageRole.TOOL and m.name == "get_alignments" for m in t.messages)
               for t in result.trajectories)
    assert result.evaluation_report.validated_target_summary.planned_concepts == 0
    # Changing only the hidden reference leaves all initial contexts unchanged.
    baseline = _run()
    assert [t.initial_payload for t in baseline.trajectories] == [t.initial_payload for t in result.trajectories]


def test_genuine_scripted_protocol_failure_and_fake_provider_interruption():
    failed = ReconstructionService(AgenticNodeReconstructor(AgentOrchestrator(
        InspectThenCommit(fail=True), max_turns=1, max_retries=0,
    ))).reconstruct_family(ingest_payload(plan()))
    assert not any(t.completed for t in failed.trajectories)
    assert all(n.failure_kind == "model_protocol_failure" for n in failed.evaluation_report.operational_nodes)
    assert failed.evaluation_report.raw_target_summary.committed_outputs == 0
    from cognate_reconstruction.agent.providers import ProviderError
    from cognate_reconstruction.schemas.evaluation import RunEvaluationReport
    interrupted = ReconstructionService(AgenticNodeReconstructor(AgentOrchestrator(
        CommitProvider(fail_at=("INNER",), error=TimeoutError), max_retries=0,
    )))
    with pytest.raises(ProviderError):
        interrupted.reconstruct_family(ingest_payload(plan()))
    report = RunEvaluationReport.model_validate_json(json.dumps(interrupted.last_run_summary["evaluation_report"]))
    assert report.targets[0].failure_kind == "unknown_provider_failure"
    assert report.targets[1].evaluation.descendant_fallback_node_ids == ()
    assert report.targets[1].output_kind == "missing"
    assert report.operational_nodes[1].status == "unvisited_or_missing"


def test_proxy_scores_survive_json_text_and_html_but_not_validated_view():
    result = _run()
    p = plan()
    proxy = p.historical_form_bindings[0].model_copy(update={
        "node_id": "INNER", "source_variety_id": "proxy:old", "target_validity": TargetValidity.PROVISIONAL_PROXY,
        "target_validity_note": "Provisional proxy; no claim of ancestry.",
    })
    p = p.model_copy(update={"historical_form_bindings": (proxy,p.historical_form_bindings[1])})
    report = evaluate_run(p, raw(result), result.trajectories)
    assert report.raw_target_summary.planned_concepts == 6
    assert report.validated_target_summary.planned_concepts == 3
    assert report.targets[0].evaluation.top_exact_rate == 1
    d = raw(result)
    d["evaluation_report"] = report.model_dump(mode="json")
    d["historical_target_evaluations"] = [t.evaluation.model_dump(mode="json") for t in report.targets]
    rendered = build_report(RunArtifacts(Path("/tmp/proxy"), result.trajectories,d,(),()))
    assert "provisional_proxy" in inspect_text(rendered)
    assert "provisional_proxy" in render_html(rendered)
    assert "task01-v1 token partition" in render_html(rendered)
    assert "morphology" in inspect_text(rendered)
    assert "provisional_proxy" in json.dumps(d)
    assert "validated targets: 3 planned" in render_text(report)


def test_legacy_inspect_infers_descendant_fallback_without_changing_exact_scores():
    result=_run()
    saved=raw(result)
    saved.pop("evaluation_report")
    saved["node_failures"]=[{"node_id":"INNER","error_type":"ProtocolStallError","reason":"fixture"}]
    for e in saved["historical_target_evaluations"]:
        e.pop("descendant_fallback_node_ids")
    rendered=build_report(RunArtifacts(Path("/tmp/legacy"),result.trajectories,saved,(),()))
    assert "committed ancestor consumes fallback" in inspect_text(rendered)
    assert "Descendant fallbacks: INNER" in render_html(rendered)


def test_all_alternatives_tone_controls_and_ambiguous_notation_are_preserved():
    result = _run()
    b = plan().historical_form_bindings[0]
    alternate = b.forms[0].model_copy(update={"form_id": "alternate", "segments": ("WRONG",)})
    b = b.model_copy(update={"forms": (alternate,*b.forms)})
    e = _evaluate_target(b,result.snapshot.steps[0])
    water = next(c for c in e.concepts if c.concept_id == "water")
    assert water.top_exact_match and len(water.target_segment_alternatives) == 2
    fathom = token_diagnostics(("l","a","m","⁵⁵"),[("l","a","m","¹")])
    assert fathom.segment_only_exact and not fathom.tone_token_exact
    needle = token_diagnostics(("a","p","⁵⁵"),[("ˀŋ","a","p","⁴"),("ʔ","a","p","⁴")])
    assert not needle.segment_only_exact and len(needle.target_tone_alternatives) == 2
    ambiguous = token_diagnostics(("a⁵",),[("a","⁴")])
    assert ambiguous.segment_only_exact is None
    assert ambiguous.analysis_status == "ambiguous_notation_unscored"
    unmarked = token_diagnostics(("p","a"),[("p","a")])
    assert unmarked.tone_token_exact is None and unmarked.tone_status == "both_unmarked"
    oldman = token_diagnostics(("m","a","ŋ","+","ts","o"),[("dz","a")],unresolved_scope=True)
    assert oldman.morphology_status == "unresolved_lexical_scope" and oldman.cognate_unit_exact is None


def test_morphemes_are_complete_independent_units_not_substrings():
    gold = [("core",("p","a")),("suffix",("t","i"))]
    pred = [("suffix",("t","i")),("core",("p","a")),("extra",("k","u"))]
    score = compare_cognate_units(pred,gold)
    assert score["unit_exact_rate"] == 1 and not score["whole_analysis_exact"]
    assert score["shared_units_reordered"] and score["extra_unit_ids"] == ["extra"]
    assert compare_cognate_units([("core",("p","a","k"))],gold)["unit_exact_rate"] == 0
    assert compare_cognate_units(None,gold)["status"] == "missing_analysis"
    assert compare_cognate_units(gold+gold,gold)["status"] == "ambiguous_analysis"
    assert compare_cognate_units([(k,list(v)) for k,v in gold],gold)["whole_analysis_exact"]


def test_per_word_bcubed_does_not_test_cross_word_consistency():
    assert bcubed(("p","a"),("b","e")).f1 == 1
    assert bcubed(("p","u"),("t","o")).f1 == 1
    # p maps to b in one word and t in another, despite every word being perfect structurally.
    assert bcubed(("p","a","p","u"),("b","e","t","o")).f1 < 1


def test_conflicting_saved_steps_are_refused():
    result = _run()
    d = raw(result)
    candidate = d["snapshot"]["steps"][0]["output_beam"]["distributions"][0]["candidates"][0]
    candidate["segments"] = ["WRONG"] * len(candidate["segments"])
    with pytest.raises(ValueError, match="conflicting saved steps"):
        evaluate_run(plan(),d,result.trajectories)


def test_real_panel_needle_alternatives_child_hit_root_miss_and_scope():
    fixtures = Path(__file__).resolve().parents[1] / "fixtures/evaluation"
    saved = json.loads((fixtures / "task02_panel_scores.json").read_text())
    for record in saved["historical_target_evaluations"]:
        # The checked-in extraction omits unneeded runtime diagnostics; this
        # fixture supplies neutral mechanical counters for a score-only test.
        forms = tuple(LexicalForm(form_id=f"fixture:{record['node_id']}:{c['concept_id']}:{i}",
                                  variety_id=record["node_id"],concept_id=c["concept_id"],segments=tuple(alt))
                      for c in record["concepts"] for i,alt in enumerate(c["target_segment_alternatives"]))
        b = HistoricalFormBinding(node_id=record["node_id"],source_variety_id=record["source_variety_id"],
                                  role=HistoricalFormRole.TARGET,forms=forms)
        saved_step = record
        # The extraction retains top tokens in every score record, but full
        # beams for two traced concepts only. Score those faithful top tokens;
        # do not claim to replay missing beam candidates/probabilities.
        beam=NodeBeamState(node_id=b.node_id,beam_width=1,distributions=tuple(
            ConceptCandidateDistribution(concept_id=c["concept_id"],candidates=(
                ReconstructionCandidate(candidate_id=c["top_candidate_id"],segments=tuple(c["top_candidate_segments"]),
                                        probability=1.0,log_score=0.0,derivations=()),
            )) for c in record["concepts"]))
        step = ReconstructionStep(parent_node_id=b.node_id, child_node_ids=tuple(saved_step["child_node_ids"]),
                                  input_beams=(),output_beam=beam,
                                  diagnostics=ReconstructionDiagnostics(rule_count=0,rule_complexity_cost=0,rule_results_evaluated=0,
                                  successful_applications=0,target_absent=0,context_mismatches=0,anchor_mismatches=0,
                                  rule_coverage=0.0,anomaly_count=0,anomaly_rate=0.0,identity_reconstruction=False))
        e = _evaluate_target(b,step)
        by_id={c.concept_id:c for c in e.concepts}
        for old in record["concepts"]:
            new=by_id[old["concept_id"]]
            assert new.top_exact_match==old["top_exact_match"]
            assert new.top_normalized_edit_distance==old["top_normalized_edit_distance"]
        if b.node_id=="burmic":
            assert by_id["1382"].top_exact_match
            assert e.target_validity is TargetValidity.PROVISIONAL_PROXY
        else:
            assert not by_id["1382"].top_exact_match
            assert len(by_id["1382"].target_segment_alternatives)==2
            assert by_id["81"].token_diagnostics.segment_only_exact
            assert by_id["1350"].token_diagnostics.segment_only_exact
            assert not by_id["96"].token_diagnostics.segment_only_exact
            assert by_id["406"].token_diagnostics.morphology_status=="unresolved_lexical_scope"


def test_read_only_cli_handles_embedded_trajectories_and_preserves_saved_scores(tmp_path):
    result=_run()
    (tmp_path / "payload.json").write_text(plan().model_dump_json())
    saved=raw(result)
    (tmp_path / "result.json").write_text(json.dumps(saved))
    root=Path(__file__).resolve().parents[2]
    completed=subprocess.run([sys.executable,str(root / "tools/evaluate_run.py"),str(tmp_path),
                              "--payload",str(tmp_path / "payload.json"),"--json"],capture_output=True,text=True,check=True)
    report=json.loads(completed.stdout)
    assert report["evaluator_version"]=="task02-v1"
    assert report["runs"][0]["report"]["raw_target_summary"]["planned_concepts"]==6
    assert report["runs"][0]["saved_historical_target_evaluations"]==saved["historical_target_evaluations"]
    assert json.loads((tmp_path / "result.json").read_text())==saved
