"""Behavioral tests for source units reaching execution and parent evidence."""
import json
from pathlib import Path

import pytest

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.schemas import LLMToolCall
from cognate_reconstruction.agent.tools import default_tool_registry
from cognate_reconstruction.agent.tools.inventory_evidence import node_inventory
from cognate_reconstruction.agent.tools.proto_assembly import assemble_node
from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.alignment.units import evidence_map, source_analyses
from cognate_reconstruction.schemas.evidence import EvidencePiece, FormAnalysis, PieceSource
from cognate_reconstruction.schemas.inventory import ProtoInventorySpec, ResiduePolicy, CorrespondenceCommitment
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm
from cognate_reconstruction.schemas.rules import ReconstructionRule
from cognate_reconstruction.rules.parser import parse_rule
from cognate_reconstruction.traversal.assembler import ProtoInventoryAssembler
from cognate_reconstruction.traversal.beam import make_leaf_beam, beam_to_lexicon, normalize_and_prune
from cognate_reconstruction.traversal.reconstructor import RuleBasedReconstructor
from cognate_reconstruction.traversal.checkpoint import FamilyCheckpoint
from cognate_reconstruction import cli


def form(child, segments, units, concept="word", suffix=""):
    fid = f"{child}:{concept}{suffix}"
    pieces = tuple(EvidencePiece(unit_id=unit, cognate_set_id=unit if unit != "boundary" else None,
        kind="cognate" if unit != "boundary" else "boundary", segment_indices=positions,
        sources=(PieceSource(form_id=fid, membership_id=unit, cognate_set_id=unit,
                             segment_indices=positions),)) for unit, positions in units)
    return LexicalForm(form_id=fid, variety_id=child, concept_id=concept, segments=segments,
                       analysis=FormAnalysis(pieces=pieces, claim="source"))


def lex(child, *forms):
    return LanguageLexicon(variety_id=child, name=child, forms=forms)


def context(*lexicons):
    return AgentContext(node_id="P", child_lexicons=lexicons, aligner=LingPyAligner())


def spec_for(ctx, values, **kwargs):
    inventory, _ = node_inventory(ctx, segmentation_overlay_id=None, alignment_overlay_id=None,
                                  unit_orders=kwargs.get("unit_orders", ()))
    commitments = tuple(CorrespondenceCommitment(set_id=item.set_id, reflexes=item.segments,
        proto_segment=values(item), support=item.support, confidence=.9, rationale="scripted explicit claim",
        directionality_rationale="offline hypothesis control") for item in inventory.sets)
    return ProtoInventorySpec(child_node_ids=ctx.child_ids, commitments=commitments,
                              residue_policy=ResiduePolicy.DROP, **kwargs)


def call(ctx, name, cid, **args):
    return default_tool_registry().execute(LLMToolCall(call_id=cid, name=name, arguments=args), ctx)


def preview(ctx, spec, cid="preview", **args):
    data = spec.model_dump(mode="json", exclude={"child_node_ids", "assembly_validation_call_id"})
    return call(ctx, "test_proto_assembly", cid, **data, **args)


def test_equal_reflexes_in_two_units_do_not_share_a_commitment():
    ctx = context(lex("A", form("A", ("p", "+", "p"), (("root", (0,)), ("boundary", (1,)), ("affix", (2,))))),
                  lex("B", form("B", ("f", "+", "f"), (("root", (0,)), ("boundary", (1,)), ("affix", (2,))))))
    inventory, _ = node_inventory(ctx, segmentation_overlay_id=None, alignment_overlay_id=None)
    equal = [item for item in inventory.sets if item.segments == ("p", "f")]
    assert len(equal) == 2 and len({item.set_id for item in equal}) == 2
    spec = spec_for(ctx, lambda item: "t" if item.scope_id == "root" else "k" if item.scope_id == "affix" else "+")
    step, committed = assemble_node(ctx, spec, node_id="P", segmentation_overlay_id=None)
    assert step.output_beam.distributions[0].candidates[0].segments == ("t", "+", "k")
    assert {c.unit_id for c in step.assembly_reports[0].columns} == {"root", "boundary", "affix"}
    assert all(c.evidence_column_id and c.source_positions for c in step.assembly_reports[0].columns)
    assert committed.column_bindings


def test_compound_simplex_shared_core_in_different_positions():
    ctx = context(lex("A", form("A", ("p", "a", "+", "k"), (("core", (0, 1)), ("boundary", (2,)), ("extraA", (3,))))),
                  lex("B", form("B", ("s", "+", "f", "a"), (("extraB", (0,)), ("boundaryB", (1,)), ("core", (2, 3))))))
    spec = spec_for(ctx, lambda item: next((s for s in item.segments if s), None) if item.scope_id == "core" else None)
    step, _ = assemble_node(ctx, spec, node_id="P", segmentation_overlay_id=None)
    assert step.output_beam.distributions[0].candidates[0].segments == ("p", "a")
    core_columns = [c for c in step.assembly_reports[0].columns if c.unit_id == "core"]
    assert core_columns[0].reflexes == ("p", "f")
    assert [s.segment_indices for s in core_columns[0].source_positions] == [(0,), (2,)]


def test_conflicting_orders_need_an_explicit_claim_and_survive_serialization():
    ctx = context(lex("A", form("A", ("p", "k"), (("root", (0,)), ("affix", (1,))))),
                  lex("B", form("B", ("k", "f"), (("affix", (0,)), ("root", (1,))))))
    with pytest.raises(ValueError, match="unit_orders"):
        evidence_map(ctx.child_lexicons, ctx.aligner)
    from cognate_reconstruction.schemas.evidence import UnitOrderClaim
    order = UnitOrderClaim(concept_id="word", unit_ids=("root", "affix"), rationale="explicit ancestral order hypothesis")
    spec = spec_for(ctx, lambda item: "p" if item.scope_id == "root" else "k", unit_orders=(order,))
    step, committed = assemble_node(ctx, spec, node_id="P", segmentation_overlay_id=None)
    top = step.output_beam.distributions[0].candidates[0]
    assert top.segments == ("p", "k") and top.analysis.order_status == "model_claim"
    from cognate_reconstruction.schemas.inventory import CommittedProtoInventory
    assert CommittedProtoInventory.model_validate_json(committed.model_dump_json()) == committed
    # An ordering claim must execute even with no correspondence commitments;
    # it is a distinct claim from an empty identity inventory.
    ordering_only = ProtoInventorySpec(child_node_ids=ctx.child_ids, commitments=(), unit_orders=(order,),
        residue_policy=ResiduePolicy.RETAIN_FROM_WITNESS, residue_witness_child_id="B")
    ordered_step, ordered_commit = assemble_node(ctx, ordering_only, node_id="P", segmentation_overlay_id=None)
    assert ordered_step.output_beam.distributions[0].candidates[0].segments == ("f", "k")
    assert not ordered_commit.identity_reconstruction


def test_preview_is_exact_to_values_policy_confidence_and_evidence():
    ctx = context(lex("A", form("A", ("p",), (("root", (0,)),))),
                  lex("B", form("B", ("f",), (("root", (0,)),))))
    spec = spec_for(ctx, lambda _: "p")
    assert preview(ctx, spec).ok
    changed = spec.model_copy(update={"commitments": tuple(c.model_copy(update={"proto_segment": "t"}) for c in spec.commitments)})
    rejected = call(ctx, "commit_reconstruction", "bad", node_id="P", anomalies=[], inventory=changed.model_dump(mode="json"), summary="changed claim")
    assert not rejected.ok and rejected.error.code == "missing-assembly-validation"
    assert "exactly" in rejected.error.remediation
    # Re-surveying identical evidence does not strand the existing validation.
    assert call(ctx, "summarize_correspondences", "again", min_support=1, include_outgroup=False).ok
    assert call(ctx, "commit_reconstruction", "good", node_id="P", anomalies=[], inventory=spec.model_dump(mode="json"), summary="same hypothesis").ok


def test_unknown_and_legacy_whole_form_have_a_usable_identity_path():
    a = LexicalForm(form_id="a", variety_id="A", concept_id="word", segments=("p", "a"))
    b = LexicalForm(form_id="b", variety_id="B", concept_id="word", segments=("f", "a"))
    ctx = context(lex("A", a), lex("B", b))
    spec = spec_for(ctx, lambda item: item.segments[0])
    step, _ = assemble_node(ctx, spec, node_id="P", segmentation_overlay_id=None)
    top = step.output_beam.distributions[0].candidates[0]
    assert top.segments == ("p", "a") and top.analysis.pieces[0].cognate_set_id is None
    beams = tuple(make_leaf_beam(l, beam_width=4) for l in ctx.child_lexicons)
    identity = RuleBasedReconstructor(beam_width=4).reconstruct("I", beams)
    assert all(c.analysis is not None for c in identity.output_beam.distributions[0].candidates)


def test_equal_surfaces_retain_incompatible_analyses_and_all_derivations():
    a = lex("A", form("A", ("p",), (("root", (0,)),), suffix="1"),
                  form("A", ("p",), (("other", (0,)),), suffix="2"))
    beam = make_leaf_beam(a, beam_width=5)
    assert len(beam.distributions[0].candidates) == 2
    assert len({c.candidate_id for c in beam.distributions[0].candidates}) == 2
    assert {f.analysis.pieces[0].unit_id for f in beam_to_lexicon(beam).forms} == {"root", "other"}
    c = beam.distributions[0].candidates[0]
    merged = normalize_and_prune("P", "word", [(c.segments, 0, c.derivations[0]),
        (c.segments, 0, c.derivations[0].model_copy(update={"derivation_id": "other-derivation"}))], beam_width=5)
    assert len(merged.candidates) == 1 and len(merged.candidates[0].derivations) == 2
    sibling = make_leaf_beam(lex("B", form("B", ("p",), (("root", (0,)),))), beam_width=5)
    identity = RuleBasedReconstructor(beam_width=5).reconstruct("P", (beam, sibling))
    assert {c.analysis.pieces[0].unit_id for c in identity.output_beam.distributions[0].candidates} == {"root", "other"}
    assert all(c.derivations[0].branch_analyses for c in identity.output_beam.distributions[0].candidates)


def test_changed_rules_keep_derivation_but_mark_unit_analysis_unresolved():
    a = make_leaf_beam(lex("A", form("A", ("p", "a"), (("root", (0, 1)),))), beam_width=5)
    b = make_leaf_beam(lex("B", form("B", ("f", "a"), (("root", (0, 1)),))), beam_width=5)
    rule = ReconstructionRule(rule=parse_rule("p > t"), source_child_ids=("A",), confidence=.9)
    step = RuleBasedReconstructor(beam_width=5).reconstruct("P", (a, b), rules=(rule,))
    changed = next(c for c in step.output_beam.distributions[0].candidates if c.segments == ("t", "a"))
    assert changed.analysis.claim == "unresolved_rules"
    assert changed.analysis.pieces[0].cognate_set_id is None
    assert changed.analysis.pieces[0].sources


def test_evaluation_reads_independent_complete_units_and_preserves_unknown_scope():
    from cognate_reconstruction.evaluation.diagnostics import token_diagnostics, with_unit_diagnostics
    output = form("A", ("p", "a"), (("root", (0,)), ("suffix", (1,))))
    target = form("GOLD", ("a", "p"), (("suffix", (0,)), ("root", (1,))))
    diagnostics = with_unit_diagnostics(token_diagnostics(output.segments, (target.segments,)), output, (target,))
    assert diagnostics.cognate_unit_exact
    assert diagnostics.cognate_unit_comparisons[0]["shared_units_reordered"]
    oldman = with_unit_diagnostics(token_diagnostics(output.segments, (target.segments,), unresolved_scope=True), output, (target,))
    assert oldman.cognate_unit_exact is None and oldman.morphology_status == "unresolved_lexical_scope"


def test_parent_receives_the_approved_pieces_after_two_levels():
    def build_pair(left, right, proto):
        ctx = context(lex(left, form(left, ("p", "a"), (("root", (0,)), ("suffix", (1,))))),
                      lex(right, form(right, ("f", "a"), (("root", (0,)), ("suffix", (1,))))))
        return assemble_node(ctx, spec_for(ctx, lambda item: proto if item.scope_id == "root" else "a"),
                             node_id=left + right, segmentation_overlay_id=None)[0]
    one, two = build_pair("A", "B", "p"), build_pair("C", "D", "f")
    ctx = context(beam_to_lexicon(one.output_beam), beam_to_lexicon(two.output_beam))
    spec = spec_for(ctx, lambda item: "t" if item.scope_id == "root" else "a")
    _, committed = assemble_node(ctx, spec, node_id="ROOT", segmentation_overlay_id=None)
    step = ProtoInventoryAssembler(beam_width=5).reconstruct("ROOT", (one.output_beam, two.output_beam), inventory=committed)
    top = step.output_beam.distributions[0].candidates[0]
    assert top.segments == ("t", "a")
    assert [p.unit_id for p in top.analysis.pieces] == ["root", "suffix"]
    assert all(p.sources and p.column_ids for p in top.analysis.pieces)
    assert all(c.resolved_by == "set" for c in step.assembly_reports[0].columns)


def test_bound_work_rejects_without_discarding_a_candidate_analysis():
    a = lex("A", *(form("A", ("p",), ((f"unit{i}", (0,)),), suffix=str(i)) for i in range(3)))
    b = lex("B", *(form("B", ("f",), ((f"unit{i}", (0,)),), suffix=str(i)) for i in range(3)))
    with pytest.raises(ValueError, match="requires 9.*limit 4.*no analysis was discarded"):
        evidence_map((a, b), LingPyAligner(), max_tuples=4)
    reading, work = evidence_map((a, b), LingPyAligner())
    assert work.candidate_tuples == len(reading.alignments) == 9


def test_old_checkpoint_names_the_semantic_incompatibility():
    old = FamilyCheckpoint(schema_version="1.0", run_id="old", input_sha256="i",
                           configuration_sha256="c", normalized_tree_sha256="t")
    reasons = cli._resume_mismatches(old, input_sha256="i", tree_sha256="t", configuration_sha256="c", components={})
    assert len(reasons) == 1 and "lacks units-v1" in reasons[0]


def test_boundary_and_analysis_overlays_invalidate_sets_and_previews():
    ctx = context(lex("A", form("A", ("p", "a"), (("root", (0, 1)),))),
                  lex("B", form("B", ("f", "a"), (("root", (0, 1)),))))
    spec = spec_for(ctx, lambda item: item.segments[0])
    assert preview(ctx, spec).ok
    edit = call(ctx, "segment_morphemes", "edit", segmentations=[{
        "form_id": "A:word", "segments": ["p", "+", "a"]}], rationale="boundary-only hypothesis")
    assert edit.ok, edit.error
    overlay = edit.result["segmentation_overlay_id"]
    stale = preview(ctx, spec, cid="stale", segmentation_overlay_id=overlay)
    assert not stale.ok and stale.error.code == "unknown-correspondence-set"
    assert "Re-run summarize_correspondences" in stale.error.remediation
    survey = call(ctx, "summarize_correspondences", "survey", segmentation_overlay_id=overlay,
                  min_support=1, include_outgroup=False)
    assert survey.ok, survey.error
    current = spec.model_copy(update={"commitments": tuple(CorrespondenceCommitment(
        set_id=s["set_id"], reflexes=tuple(s["segments"]), proto_segment=s["segments"][0],
        support=s["support"], confidence=.9, rationale="same explicit values", directionality_rationale="control")
        for s in survey.result["sets"])})
    assert preview(ctx, current, cid="new", segmentation_overlay_id=overlay).ok
    assert call(ctx, "commit_reconstruction", "commit", node_id="P", anomalies=[],
        segmentation_overlay_id=overlay, inventory=current.model_dump(mode="json"), summary="updated evidence").ok


def test_realignment_is_exact_to_unit_and_analysis_and_join_remains_usable():
    ctx = context(lex("A", form("A", ("p", "a", "k"), (("root", (0, 1)), ("suffix", (2,))))),
                  lex("B", form("B", ("f", "a", "k"), (("root", (0, 1)), ("suffix", (2,))))))
    bad = call(ctx, "realign", "bad", overrides=[{"concept_id": "word", "rows": [["p", "a", "k"], ["f", "a", "k"]], "rationale": "whole"}], rationale="whole")
    assert not bad.ok and "unit_id" in bad.error.remediation
    old, _ = node_inventory(ctx, segmentation_overlay_id=None, alignment_overlay_id=None)
    edit = call(ctx, "realign", "good", overrides=[{"concept_id": "word", "unit_id": "root", "rows": [["p", "a"], ["f", "a"]], "rationale": "named unit"}], rationale="named unit")
    assert edit.ok, edit.error
    overlay = edit.result["alignment_overlay_id"]
    after, _ = node_inventory(ctx, segmentation_overlay_id=None, alignment_overlay_id=overlay)
    assert not {s.set_id for s in old.sets}.intersection(s.set_id for s in after.sets)
    assert ctx.alignment_overrides(overlay)[0].analysis_ids


def test_disposition_targets_an_exact_alternative_column():
    a = lex("A", form("A", ("p",), (("root", (0,)),), suffix="1"),
                  form("A", ("p",), (("other", (0,)),), suffix="2"))
    ctx = context(a, lex("B", form("B", ("f",), (("root", (0,)),))))
    from cognate_reconstruction.schemas.inventory import ResidueDisposition
    blank = ProtoInventorySpec(child_node_ids=ctx.child_ids, commitments=(), residue_policy=ResiduePolicy.RETAIN_FROM_WITNESS,
        residue_witness_child_id="A", residue_dispositions=(ResidueDisposition(concept_id="word", column_index=0,
            proto_segment="t", explanation="explicit sparse claim"),))
    ambiguous = preview(ctx, blank)
    assert not ambiguous.ok and "ambiguous" in ambiguous.error.message
    reading, _ = evidence_map(ctx.child_lexicons, ctx.aligner)
    target = next(a.evidence_columns[0].column_id for a in reading.alignments if a.evidence_columns[0].unit_id == "root")
    exact = blank.model_copy(update={"residue_dispositions": tuple(d.model_copy(update={"evidence_column_id": target}) for d in blank.residue_dispositions)})
    assert preview(ctx, exact, cid="exact").ok
    step, _ = assemble_node(ctx, exact, node_id="P", segmentation_overlay_id=None)
    decided = [c for r in step.assembly_reports for c in r.columns if c.resolved_by == "residue_disposition"]
    # A tuple with the other analysis cannot receive the claimed value merely
    # because it has the same surface and index.
    assert all(c.evidence_column_id == target for c in decided)


def test_polytomy_missing_daughter_and_selected_preview_share_evidence():
    ctx = context(*(lex(child, form(child, (token,), (("root", (0,)),)))
                    for child, token in (("A", "p"), ("B", "f"), ("C", "p"))), lex("D"))
    spec = spec_for(ctx, lambda _: "p")
    full, committed = assemble_node(ctx, spec, node_id="P", segmentation_overlay_id=None)
    selected, _ = assemble_node(ctx, spec, node_id="P", segmentation_overlay_id=None, concept_ids=("word",))
    assert selected.output_beam == full.output_beam
    assert committed.request.child_node_ids == ("A", "B", "C", "D")
    assert all(c.reflexes[-1] is None for c in full.assembly_reports[0].columns)


def test_explicit_model_analysis_never_comes_from_output_resemblance():
    ctx = context(lex("A", LexicalForm(form_id="a", variety_id="A", concept_id="word", segments=("p",))),
                  lex("B", LexicalForm(form_id="b", variety_id="B", concept_id="word", segments=("p",))))
    assert all(a.pieces[0].cognate_set_id is None for l in ctx.child_lexicons for f in l.forms for a in source_analyses(f))
    result = call(ctx, "segment_morphemes", "claim", segmentations=[{
        "form_id": f, "segments": ["p"], "analysis_claim": [{"unit_id": "model:root", "cognate_set_id": "claimed-root", "segment_indices": [0]}]} for f in ("a", "b")], rationale="model claims these are one cognate unit")
    assert result.ok, result.error
    overlaid = ctx.lexicon("A", result.result["segmentation_overlay_id"]).forms[0]
    assert overlaid.analysis.claim == "model"
    assert overlaid.analysis.pieces[0].cognate_set_id == "claimed-root"
    assert overlaid.analysis.pieces[0].sources[0].cognate_set_id is None
    conflicting = overlaid.model_copy(update={"variety_id": "B", "form_id": "b",
        "analysis": overlaid.analysis.model_copy(update={"pieces": tuple(
            piece.model_copy(update={"cognate_set_id": "different-claim"}) for piece in overlaid.analysis.pieces)})})
    with pytest.raises(ValueError, match="conflicting cognate claims"):
        evidence_map((lex("A", overlaid), lex("B", conflicting)), ctx.aligner)


def test_frozen_real_defects_replay_and_source_unit_control_repairs_pairing():
    import importlib.util
    import sys
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "tools"))
    spec = importlib.util.spec_from_file_location("unit_probe", root / "tools/evidence_contract_probe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.run_probe()
    rows = {r["concept_id"]: r for r in result["concepts"]}
    assert rows["96"]["legacy_top"].count("w") == 2
    assert rows["96"]["units_control_top"].count("w") == 1
    assert "+" in rows["239"]["legacy_top"] and "+" not in rows["239"]["units_control_top"]
    assert len(rows["239"]["analysis"]["pieces"]) == 1
    crawl_sources = [s for c in rows["96"]["core_columns"] for s in c["source_positions"]]
    assert all(s["segment_indices"][0] < 4 for s in crawl_sources if "Rangoon" in s["form_id"])
