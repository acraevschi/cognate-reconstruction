"""Mechanism distinctions are observable; generated truth is not identifiability."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from cognate_reconstruction.agent.orchestrator import AgentOrchestrator
from cognate_reconstruction.agent.reconstructor import AgenticNodeReconstructor
from cognate_reconstruction.agent.service import ReconstructionService
from cognate_reconstruction.evaluation.diagnostics import compare_cognate_units, pieces
from cognate_reconstruction.evaluation.targets import _evaluate_target
from cognate_reconstruction.ingestion import ingest_payload
from cognate_reconstruction.rules.engine import RuleEngine
from cognate_reconstruction.rules.parser import parse_rule
from cognate_reconstruction.schemas.beam import NodeBeamState, ReconstructionCandidate, ConceptCandidateDistribution
from cognate_reconstruction.schemas.historical import TargetValidity
from cognate_reconstruction.schemas.synthetic import SyntheticFamilyDefinition
from cognate_reconstruction.synthesis.diagnostics import load_suite, build_case
from cognate_reconstruction.synthesis.generator import generate_family
from tests.workbench.test_evaluation_contract import InspectThenCommit

ROOT = Path(__file__).resolve().parents[2]
SUITE = load_suite(ROOT / "benchmarks/diagnostic/task02-v1.json")


@pytest.mark.parametrize("case", SUITE["cases"], ids=lambda c:c["case_id"])
def test_each_case_runs_scripted_and_perfect_wrong_fixtures_separate(case):
    built = build_case(case)
    result = ReconstructionService(AgenticNodeReconstructor(AgentOrchestrator(
        InspectThenCommit(),
    ))).reconstruct_family(ingest_payload(built.payload))
    assert all(t.completed for t in result.trajectories)
    if case["identifiability"] == "underdetermined":
        assert result.evaluation_report.validated_target_summary.planned_concepts == 0
        assert result.evaluation_report.validated_target_summary.end_to_end_model_top_exact_rate is None
        assert all(t.evaluation.target_validity is TargetValidity.UNDERDETERMINED
                   for t in result.evaluation_report.targets)
    else:
        assert result.evaluation_report.validated_target_summary.planned_concepts > 0
    for target in result.evaluation_report.targets:
        binding = next(b for b in built.payload.historical_form_bindings if b.node_id == target.node_id)
        step = next(s for s in result.snapshot.steps if s.parent_node_id == target.node_id)
        for label, expected in (("perfect",1), ("wrong",0)):
            beam = NodeBeamState(node_id=binding.node_id,beam_width=1,distributions=tuple(
                ConceptCandidateDistribution(concept_id=f.concept_id,candidates=(
                    ReconstructionCandidate(candidate_id=f"fixture:{f.form_id}",segments=f.segments if label == "perfect" else ("WRONG",),
                                            probability=1.0,log_score=0.0,derivations=()),
                )) for f in binding.forms))
            score = _evaluate_target(binding,step.model_copy(update={"output_beam":beam}))
            assert score.top_exact_rate == expected
            assert score.graded.top_normalized_edit_distance.mean == 1-expected


def test_complementary_retention_requires_both_branches_for_every_word():
    built = build_case(SUITE["cases"][0])
    gold = {f.concept_id:f.segments for f in built.payload.historical_form_bindings[0].forms}
    by_node = {l.variety_id:{f.concept_id:f.segments for f in l.forms} for l in built.payload.lexicons}
    for concept, tokens in gold.items():
        assert all(forms[concept] != tokens for forms in by_node.values())
        assert by_node["a"][concept] + by_node["b"][concept][-1:] == tokens
        assert by_node["d"][concept] == by_node["a"][concept]
        assert by_node["c"][concept] == by_node["b"][concept]
    assert len(gold) == 6  # recurrent independent concepts, not a one-word puzzle


def test_conditioning_has_repeated_changed_examples_and_unchanged_controls():
    built = build_case(next(c for c in SUITE["cases"] if c["case_id"] == "conditioned"))
    lex = {l.variety_id:l for l in built.answer_key.node_lexicons}
    correct,_ = RuleEngine().apply_rules((parse_rule("f > p / _i"),),lex["a"].forms)
    wrong,_ = RuleEngine().apply_rules((parse_rule("p > f"),),lex["c"].forms)
    expected = {f.concept_id:f.segments for f in lex["p"].forms}
    assert {f.concept_id:f.segments for f in correct} == expected
    assert {f.concept_id:f.segments for f in wrong} != expected
    assert sum(f.segments[0] == "f" for f in lex["a"].forms) == 2


def test_morphology_recovers_units_without_claiming_whole_word_order():
    case = next(c for c in SUITE["cases"] if c["case_id"] == "morphology")
    built = build_case(case)
    gold_forms = {f.concept_id:f for f in built.payload.historical_form_bindings[0].forms}
    a = next(l for l in built.payload.lexicons if l.variety_id == "a")
    b = next(l for l in built.payload.lexicons if l.variety_id == "b")
    for form in b.forms:
        target = gold_forms[form.concept_id]
        gold_units = list(zip(case["target_unit_layouts"][form.concept_id],pieces(target.segments),strict=True))
        observed_units = [(m.cognate_set_id,form.segments_for_membership(m)) for m in form.cognate_memberships]
        score = compare_cognate_units(observed_units,gold_units)
        assert score["unit_exact_rate"] == 1 and score["shared_units_reordered"]
        assert not score["whole_analysis_exact"]
        extra = next(f for f in a.forms if f.concept_id == form.concept_id)
        extra_units = [(m.cognate_set_id,extra.segments_for_membership(m)) for m in extra.cognate_memberships]
        assert compare_cognate_units(extra_units,gold_units)["extra_unit_ids"] == ["u4"]


def test_two_level_propagation_uses_intermediate_targets_and_preserves_level():
    built = build_case(next(c for c in SUITE["cases"] if c["case_id"] == "propagation"))
    lex = {l.variety_id:l for l in built.answer_key.node_lexicons}
    engine = RuleEngine()
    x,_ = engine.apply_rules((parse_rule("f > p / #_"),),lex["a"].forms)
    assert {f.concept_id:f.segments for f in x} == {f.concept_id:f.segments for f in lex["x"].forms}
    root,_ = engine.apply_rules((parse_rule("g > k / _#"),),x)
    assert {f.concept_id:f.segments for f in root} == {f.concept_id:f.segments for f in lex["p"].forms}
    assert {b.node_id for b in built.payload.historical_form_bindings} == {"x","y","p"}
    p_initial = {f.concept_id:f.segments for f in lex["p"].forms if f.segments[0] == "p"}
    for l in built.payload.lexicons:
        assert all(f.segments != p_initial[f.concept_id] for f in l.forms if f.concept_id in p_initial)


def test_lost_contrast_has_an_observationally_equivalent_ancestor():
    case = next(c for c in SUITE["cases"] if c["case_id"] == "lost_contrast")
    original = build_case(case)
    alternate = json.loads(json.dumps(case["family"]))
    for f,text in zip(alternate["proto_lexicon"],case["alternative_proto_lexicon"],strict=True):
        f["segments"] = text.split()
    alternate["branches"] = []
    other = generate_family(SyntheticFamilyDefinition.model_validate_json(json.dumps(alternate)))
    assert [[f.segments for f in l.forms] for l in original.payload.lexicons] == [
        [f.segments for f in l.forms] for l in other.payload.lexicons]
    assert original.payload.historical_form_bindings[0].forms != other.payload.historical_form_bindings[0].forms


def test_suite_has_no_answer_notes_in_model_evidence():
    for case in SUITE["cases"]:
        built = build_case(case)
        # The definition and key are operator artifacts. Runtime evidence is
        # lexicons/concepts/tree, with targets in their separate hidden binding.
        observed = json.dumps({"lexicons":[l.model_dump(mode="json") for l in built.payload.lexicons],
                               "concepts":[c.model_dump(mode="json") for c in built.payload.concepts]})
        for field in ("independent_evidence","equivalent_solutions","target_unit_layouts",
                      "alternative_proto_lexicon","target_validity_note"):
            assert field not in observed


def test_diagnostic_cli_writes_separate_keys_and_no_unique_score_for_lost_contrast(tmp_path):
    command=[sys.executable,str(ROOT / "tools/diagnostic_suite.py"),"--output-dir",str(tmp_path),"--json"]
    completed=subprocess.run(command,capture_output=True,text=True,check=True)
    report=json.loads(completed.stdout)
    assert report["live_model_calls"]==0 and len(report["cases"])==6
    retention=next(c for c in report["cases"] if c["case_id"]=="retention")
    assert retention["controls"]["identity"]["raw"]["output_top_hits"]==0
    assert retention["controls"]["perfect_fixture"]["raw"]["output_top_hits"]==6
    lost=next(c for c in report["cases"] if c["case_id"]=="lost_contrast")
    assert lost["controls"]["perfect_fixture"]["validated"]["end_to_end_model_top_exact_rate"] is None
    for case in SUITE["cases"]:
        observed=json.loads((tmp_path / f"{case['case_id']}.json").read_text())
        key=json.loads((tmp_path / f"{case['case_id']}.answer-key.json").read_text())
        assert "generated_truth" not in observed and "evaluation_notes" not in observed
        assert "generated_truth" in key and "evaluation_notes" in key
