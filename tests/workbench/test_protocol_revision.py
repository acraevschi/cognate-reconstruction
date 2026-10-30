"""Task05 semantic contracts: explicit choices, immutable handles and exact evidence."""
import json

import pytest
from pydantic import ValidationError

from cognate_reconstruction import cli
from cognate_reconstruction.agent.schemas import LLMToolCall
from cognate_reconstruction.agent.tools import default_tool_registry
from cognate_reconstruction.agent.tools.inventory_evidence import node_inventory
from cognate_reconstruction.rules.engine import RuleEngine
from cognate_reconstruction.rules.parser import parse_rule
from cognate_reconstruction.schemas.inventory import ProtoInventorySpec
from cognate_reconstruction.schemas.traversal import NodeEvidence, EvidenceKind, EvidenceRelation
from tests.workbench.test_evidence_contract import context, form, lex, spec_for
from tools.protocol_revision_probe import replay_saved_calls, stored_controls
from tools.protocol_revision_probe import FIXTURES


def ctx_two():
    return context(lex("A", form("A", ("p", "a"), (("core", (0, 1)),))),
        lex("B", form("B", ("f", "a"), (("core", (0, 1)),))))


def execute(ctx, name, cid, *, protocol="stored-hypothesis", **args):
    return default_tool_registry(inventory_protocol=protocol).execute(
        LLMToolCall(call_id=cid, name=name, arguments=args), ctx)


def choices(ctx, *, null=False):
    inv, _ = node_inventory(ctx, segmentation_overlay_id=None, alignment_overlay_id=None)
    return [{"set_id": s.set_id, "proto_segment": None if null and "f" in s.segments else s.segments[0],
        "confidence": .7, "rationale": "qualified source-unit choice",
        "directionality_rationale": "explicit control; polarity remains uncertain"} for s in inv.sets]


def preview(ctx, cid="preview", **updates):
    args = {"choices": choices(ctx), "residue_policy": "drop"}
    args.update(updates)
    r = execute(ctx, "test_proto_assembly", cid, **args)
    assert r.ok, r.error
    return r.result


def commit(ctx, handle, **args):
    return execute(ctx, "commit_reconstruction", "commit", node_id=ctx.node_id,
        hypothesis_id=handle, anomalies=[], summary="Qualified inspected hypothesis", **args)


@pytest.mark.parametrize("dsl,expected", [("⁵⁵ > ⁴", ("a", "p", "⁴")),
    ("⁵⁵ > z ⁴", ("a", "p", "z", "⁴"))])
def test_literal_rules_emit_new_tokens_and_sequences(dsl, expected):
    observed = form("A", ("a", "p", "⁵⁵"), (("core", (0, 1, 2)),))
    report = RuleEngine().apply_rule(parse_rule(dsl), (observed,))
    assert report.results[0].output_segments == expected
    assert all(t not in observed.segments for t in expected[2:])
    with pytest.raises(ValueError, match="empty"):
        parse_rule("Ø > ⁴")


def test_inspected_snapshot_commits_exactly_and_is_immutable():
    ctx = ctx_two()
    result = preview(ctx, choices=choices(ctx, null=True))
    assert result["executable"] and result["commit_ready"]
    snapshot = ctx.inventory_hypotheses[result["hypothesis_id"]]
    spec = ProtoInventorySpec.model_validate_json(snapshot.spec_json)
    assert any(c.proto_segment is None for c in spec.commitments)
    assert all(c.confidence == .7 for c in spec.commitments)
    with pytest.raises(ValidationError):
        snapshot.spec_json = "{}"
    # Reinspection does not mutate stored bytes or strand the reference.
    assert preview(ctx, "again", choices=choices(ctx, null=True))["hypothesis_id"] == result["hypothesis_id"]
    assert ctx.inventory_hypotheses[result["hypothesis_id"]] is snapshot
    assert execute(ctx, "summarize_correspondences", "resurvey", min_support=1).ok
    accepted = commit(ctx, result["hypothesis_id"])
    assert accepted.ok, accepted.error
    assert ctx.commit.request.commitments == spec.commitments
    assert ctx.commit.request.assembly_validation_call_id == snapshot.validation_call_id
    assert not commit(ctx, result["hypothesis_id"]).ok


def test_missing_explanations_are_exposed_before_terminal_transition():
    ctx = ctx_two()
    sparse = choices(ctx, null=True)
    for c in sparse:
        c.pop("rationale")
        c.pop("directionality_rationale")
    r = preview(ctx, choices=sparse)
    assert r["executable"] and not r["commit_ready"]
    assert {e["code"] for e in r["missing_commit_requirements"]} == {
        "missing-rule-rationale", "missing-directionality-rationale"}
    rejected = commit(ctx, r["hypothesis_id"])
    assert rejected.error.code == "hypothesis-not-ready" and ctx.commit is None
    fixed = preview(ctx, "explained", choices=choices(ctx, null=True))
    assert fixed["hypothesis_id"] != r["hypothesis_id"]
    assert fixed["commit_ready"] and commit(ctx, fixed["hypothesis_id"]).ok


@pytest.mark.parametrize("field", ["proto_segment", "confidence"])
def test_compact_path_never_supplies_missing_linguistic_decisions(field):
    ctx = ctx_two()
    items = choices(ctx)
    items[0].pop(field)
    r = execute(ctx, "test_proto_assembly", "bad", choices=items, residue_policy="drop")
    assert not r.ok and field + "=missing" in r.error.code
    assert not ctx.inventory_hypotheses


def test_identity_preview_requires_a_deliberate_empty_collection():
    ctx = ctx_two()
    omitted = execute(ctx, "test_proto_assembly", "omitted",
        residue_policy="retain_from_witness", residue_witness_child_id="A")
    assert not omitted.ok and not ctx.inventory_hypotheses
    explicit = preview(ctx, choices=[], residue_policy="retain_from_witness", residue_witness_child_id="A")
    assert explicit["commit_ready"] and commit(ctx, explicit["hypothesis_id"]).ok
    assert ctx.commit.identity_reconstruction


def test_saved_task05_nested_and_invented_id_calls_stay_rejected_with_shape_guidance():
    from tools.protocol_revision_probe import fixture_context
    saved = json.loads((FIXTURES / "task05_rejections.json").read_text())
    for row in saved["calls"]:
        ctx = fixture_context()
        rejected = execute(ctx, row["name"], row["call_id"], **row["arguments"])
        assert not rejected.ok and rejected.error.code == row["saved_error_code"]
        assert rejected.error.remediation  # includes the new schema fallback or exact-ID guidance
        assert ctx.commit is None and not ctx.inventory_hypotheses


def test_default_instructions_exclude_the_complete_fixture_reference_words():
    from cognate_reconstruction.agent.instructions import load_agent_instructions
    references = json.loads((FIXTURES.parent / "evidence_contract/burmic_units.references.json").read_text())
    instructions = load_agent_instructions()
    for concept in references["concepts"]:
        for alternative in concept["alternatives"]:
            assert " ".join(alternative) not in instructions


@pytest.mark.parametrize("requested,status,queued", [("downloaded", "idle", 0),
    ("loaded", "busy", 0), ("loaded", "idle", 1)])
def test_operator_driver_refuses_catalogue_only_or_busy_models_before_creating_a_run(tmp_path, monkeypatch, requested, status, queued):
    import runpy
    from argparse import Namespace
    driver = runpy.run_path(str(FIXTURES.parents[2] / "skills/run-cognate-reconstruction/driver.py"))
    run = driver["cmd_run"]
    monkeypatch.setitem(run.__globals__, "find_python", lambda: "unused")
    monkeypatch.setitem(run.__globals__, "ensure_lm_studio", lambda *a, **kw: ["loaded", "downloaded"])
    monkeypatch.setitem(run.__globals__, "loaded_lm_studio_models", lambda: [
        {"identifier": "loaded", "status": status, "queued": queued}])
    target = tmp_path / "not-created"
    args = Namespace(preset="lm-studio", api_base=None, no_autostart=True,
        model=requested, run_dir=str(target))
    assert run(args) == 1 and not target.exists()


@pytest.mark.parametrize("extra", [{"inventory": None}, {"rules": []},
    {"segmentation_overlay_id": None}, {"cascade_validation_call_id": "old"}])
def test_handle_cannot_silently_accept_payload_or_overlay_edits(extra):
    ctx = ctx_two()
    handle = preview(ctx)["hypothesis_id"]
    assert not commit(ctx, handle, **extra).ok
    assert ctx.commit is None


def test_handles_do_not_cross_node_sessions_or_resumes():
    ctx = ctx_two()
    handle = preview(ctx)["hypothesis_id"]
    other = ctx_two()
    rejected = commit(other, handle)
    assert rejected.error.code == "hypothesis-unknown"
    other.node_id = "different"
    assert commit(other, handle).error.code == "hypothesis-unknown"


@pytest.mark.parametrize("change", ["value", "confidence", "conditioning", "rationale", "residue"])
def test_deliberate_choice_edits_need_a_new_preview(change):
    ctx = ctx_two()
    old = preview(ctx)
    snap = ctx.inventory_hypotheses[old["hypothesis_id"]]
    spec = json.loads(snap.spec_json)
    if change == "residue":
        spec.update(residue_policy="retain_from_witness", residue_witness_child_id="A")
    else:
        key, val = {"value": ("proto_segment", "t"), "confidence": ("confidence", .5),
            "conditioning": ("conditioning", {"word_initial": True}),
            "rationale": ("rationale", "changed uncertainty explanation")}[change]
        spec["commitments"][0][key] = val
    rejected = execute(ctx, "commit_reconstruction", "bad", node_id=ctx.node_id,
        inventory=spec, anomalies=[], summary="edited spec")
    assert not rejected.ok and rejected.error.code == "missing-assembly-validation"
    args = {k: v for k, v in spec.items() if k not in {"child_node_ids", "assembly_validation_call_id"}}
    new = execute(ctx, "test_proto_assembly", "changed", **args)
    assert new.ok and new.result["hypothesis_id"] != old["hypothesis_id"]
    assert commit(ctx, new.result["hypothesis_id"]).ok


@pytest.mark.parametrize("change", ["source", "supplementary"])
def test_stale_evidence_is_rejected_on_handles_and_full_payloads(change):
    ctx = ctx_two()
    old = preview(ctx)
    snap = ctx.inventory_hypotheses[old["hypothesis_id"]]
    if change == "source":
        ctx.child_lexicons = (lex("A", form("A", ("t", "a"), (("core", (0, 1)),))), ctx.child_lexicons[1])
    else:
        ctx.evidence = (NodeEvidence(node_id="O", lexicon=lex("O", form("O", ("p", "a"), (("core", (0, 1)),))),
            kind=EvidenceKind.OBSERVED, relation=EvidenceRelation.OUTGROUP),)
    assert commit(ctx, old["hypothesis_id"]).error.code == "hypothesis-stale"
    full = execute(ctx, "commit_reconstruction", "full", node_id=ctx.node_id,
        inventory=json.loads(snap.spec_json), anomalies=[], summary="stale full")
    assert not full.ok
    new = preview(ctx, "current")
    assert new["hypothesis_id"] != old["hypothesis_id"]
    assert commit(ctx, new["hypothesis_id"]).ok


def test_shared_choices_preserve_submitted_members_and_local_exception():
    ctx = context(*(lex(ch, *(form(ch, (token,), ((concept, (0,)),), concept=concept)
        for concept in ("one", "two", "three"))) for ch, token in (("A", "p"), ("B", "f"))))
    inv, _ = node_inventory(ctx, segmentation_overlay_id=None, alignment_overlay_id=None)
    pattern = inv.recurrence_patterns[0]
    shared = {"pattern_id": pattern.set_id, "member_set_ids": list(pattern.member_set_ids[:2]),
        "proto_segment": "p", "confidence": .8, "rationale": "selected local retentions"}
    local = {"set_id": pattern.member_set_ids[2], "proto_segment": "t", "confidence": .5,
        "rationale": "explicit uncertain local exception"}
    old = preview(ctx, choices=[local], shared_claims=[shared])
    overlap = execute(ctx, "test_proto_assembly", "overlap", choices=[{**local, "set_id": shared["member_set_ids"][0]}],
        shared_claims=[shared], residue_policy="drop")
    assert not overlap.ok
    assert commit(ctx, old["hypothesis_id"]).ok
    assert len(ctx.commit.request.commitments) == 3
    assert ctx.commit.approved_shared_claims[0].member_set_ids == tuple(shared["member_set_ids"])


def test_full_payload_mode_and_rules_still_work():
    ctx = ctx_two()
    spec = spec_for(ctx, lambda s: s.segments[0])
    args = spec.model_dump(mode="json", exclude={"child_node_ids", "assembly_validation_call_id"})
    p = execute(ctx, "test_proto_assembly", "p", protocol="full-payload", **args)
    assert p.ok and p.result["commit_ready"] and p.result["hypothesis_id"] is None
    assert execute(ctx, "commit_reconstruction", "c", protocol="full-payload", node_id=ctx.node_id,
        inventory=spec.model_dump(mode="json"), summary="Full payload compatibility", anomalies=[]).ok
    for protocol in ("full-payload", "stored-hypothesis"):
        other = ctx_two()
        assert execute(other, "test_sound_law", "law", protocol=protocol, dsl="f > p", source_child_ids=["B"]).ok
        assert execute(other, "commit_reconstruction", "rule", protocol=protocol, node_id=other.node_id,
            rules=[{"dsl": "f > p", "source_child_ids": ["B"], "confidence": .8}],
            summary="Qualified operational rewrite", anomalies=[]).ok


def test_saved_malformed_classes_reproduce_without_filling_decisions():
    rows = replay_saved_calls()
    assert len(rows) == 7
    assert all(r["rebound_code"] == r["saved_code"] for r in rows)


def test_stored_path_reaches_parent_serialization_and_normal_evaluation(tmp_path):
    rows = stored_controls(tmp_path)
    assert [r["raw_exact"] for r in rows] == [4, 0, 0, 0, 0]
    assert all(r["completed_nodes"] == ["x", "p"] for r in rows)
    assert all(r["validated_planned"] == 0 for r in rows)  # order remains underdetermined


def test_instruction_and_protocol_arms_have_independent_strict_hashes(tmp_path):
    parser = cli._parser()
    path = tmp_path / "arm.md"
    path.write_text("Explicit test wording")
    base = parser.parse_args(["infer", "--input", "unused", "--model", "test", "--no-preflight"])
    # Behavioral hashes are pure/read-only and require no provider call.
    a = cli._behavioural_input_digests(base)
    base.agent_instructions = str(path)
    b = cli._behavioural_input_digests(base)
    assert a["the agent instructions"] != b["the agent instructions"]
    assert a["the tool schemas"] == b["the tool schemas"]
    base.inventory_protocol = "full-payload"
    c = cli._behavioural_input_digests(base)
    assert c["the agent instructions"] == b["the agent instructions"]
    assert c["the tool schemas"] != b["the tool schemas"]
