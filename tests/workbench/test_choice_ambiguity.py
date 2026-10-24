"""Competing applicable choices are identified by choice, not by set.

Review finding 3: under units-v2 two conditioned claims on one local set can
both hold in a column (`#_` and `_#` on a one-token word). The resolution policy
is unchanged — higher confidence wins, equal confidence falls to ascending
proto segment then set ID — but the competition has to be visible in the
preview, the committed step, its JSON and the aggregate diagnostics.
"""
import json

import pytest

from cognate_reconstruction.agent.schemas import LLMToolCall
from cognate_reconstruction.agent.tools import default_tool_registry
from cognate_reconstruction.agent.tools.inventory_evidence import node_inventory
from cognate_reconstruction.schemas.inventory import (
    ColumnResolution,
    CorrespondenceCommitment,
    ResiduePolicy,
)
from cognate_reconstruction.schemas.rules import RuleEnvironment
from cognate_reconstruction.schemas.traversal import (
    ReconstructionDiagnostics,
    ReconstructionStep,
)
from cognate_reconstruction.traversal.assembler import (
    ProtoInventoryAssembler,
    _choose_column_commitment,
    _competing_choices,
    build_plan,
    resolve_columns,
)
from cognate_reconstruction.traversal.beam import make_leaf_beam
from tests.workbench.test_evidence_contract import context, form, lex

INITIAL = {"word_initial": True}
FINAL = {"word_final": True}


def one_token_context():
    return context(lex("A", form("A", ("p",), (("root", (0,)),))),
                   lex("B", form("B", ("f",), (("root", (0,)),))))


def execute(ctx, protocol, name, cid, **args):
    return default_tool_registry(inventory_protocol=protocol).execute(
        LLMToolCall(call_id=cid, name=name, arguments=args), ctx)


def overlapping_claims(ctx, initial_confidence, final_confidence):
    inv, _ = node_inventory(ctx, segmentation_overlay_id=None, alignment_overlay_id=None)
    (local,) = inv.sets
    base = {"set_id": local.set_id, "rationale": "scripted conditioned control",
            "directionality_rationale": "scripted control; polarity not identified"}
    return local, [
        {**base, "proto_segment": "p", "conditioning": INITIAL, "confidence": initial_confidence},
        {**base, "proto_segment": "t", "conditioning": FINAL, "confidence": final_confidence},
    ]


def preview_and_commit(ctx, protocol, claims, local):
    if protocol == "stored-hypothesis":
        preview = execute(ctx, protocol, "test_proto_assembly", "pv", choices=claims,
                          residue_policy="drop", detail="full")
        assert preview.ok, preview.error
        committed = execute(ctx, protocol, "commit_reconstruction", "c", node_id=ctx.node_id,
                            hypothesis_id=preview.result["hypothesis_id"], anomalies=[],
                            summary="Overlapping conditioned control")
    else:
        full = [{**claim, "reflexes": list(local.segments), "support": local.support}
                for claim in claims]
        preview = execute(ctx, protocol, "test_proto_assembly", "pv", commitments=full,
                          residue_policy="drop", detail="full")
        assert preview.ok, preview.error
        committed = execute(ctx, protocol, "commit_reconstruction", "c", node_id=ctx.node_id,
                            inventory={"child_node_ids": list(ctx.child_ids), "commitments": full,
                                       "residue_policy": "drop"},
                            anomalies=[], summary="Overlapping conditioned control")
    assert committed.ok, committed.error
    return preview.result


@pytest.mark.parametrize("protocol", ["stored-hypothesis", "full-payload"])
@pytest.mark.parametrize("initial,final,emitted,loser,tie", [
    (.7, .9, "t", ("p", .7, INITIAL), False),   # higher confidence wins
    (.9, .9, "p", ("t", .9, FINAL), True),      # equal: ascending proto segment
])
def test_overlapping_conditioned_claims_on_one_set_are_reported(
        protocol, initial, final, emitted, loser, tie):
    ctx = one_token_context()
    local, claims = overlapping_claims(ctx, initial, final)
    result = preview_and_commit(ctx, protocol, claims, local)

    # Preview: commit-ready, unchanged emission, and the competition is visible.
    assert result["commit_ready"]
    (column,) = result["concepts"][0]["columns"]
    assert column["proto_segment"] == emitted and column["set_id"] == local.set_id
    assert result["ambiguous_columns"] == [column]
    assert column["competing_set_ids"] == []  # same set: no distinct-set competitor
    (rival,) = column["competing_choices"]
    assert (rival["set_id"], rival["proto_segment"], rival["confidence"]) == (local.set_id, *loser[:2])
    assert RuleEnvironment.model_validate_json(json.dumps(rival["conditioning"])) == \
        RuleEnvironment.model_validate_json(json.dumps(loser[2]))
    assert column["decided_by_equal_confidence"] is tie

    # Committed record: the step built from the committed inventory agrees.
    step = ProtoInventoryAssembler().reconstruct(
        ctx.node_id, tuple(make_leaf_beam(item, beam_width=5) for item in ctx.child_lexicons),
        inventory=ctx.commit)
    assert step.output_beam.distributions[0].candidates[0].segments == (emitted,)
    (committed_column,) = step.assembly_reports[0].columns
    assert committed_column.model_dump(mode="json") == column
    assert step.diagnostics.columns_with_competing_choices == 1
    assert step.diagnostics.columns_decided_by_equal_confidence == int(tie)
    # Historical count is unchanged: no other *set* matched this column.
    assert step.diagnostics.columns_decided_by_tie_break == 0

    # Serialization: JSON readback preserves the competing choices exactly.
    readback = ReconstructionStep.model_validate_json(step.model_dump_json())
    assert readback == step
    assert readback.assembly_reports[0].columns[0].competing_choices == committed_column.competing_choices


def test_unconditioned_single_claim_is_not_ambiguous():
    ctx = one_token_context()
    local, claims = overlapping_claims(ctx, .9, .9)
    result = preview_and_commit(ctx, "stored-hypothesis", claims[:1], local)
    assert result["ambiguous_columns"] == []
    (column,) = result["concepts"][0]["columns"]
    assert column["competing_choices"] == [] and column["decided_by_equal_confidence"] is False


def commitment(set_id, proto, confidence, conditioning=None):
    return CorrespondenceCommitment(
        set_id=set_id, reflexes=("p", "f"), proto_segment=proto, support=1,
        confidence=confidence,
        conditioning=None if conditioning is None else RuleEnvironment(**conditioning))


def test_choice_identity_deduplicates_identical_claims_without_changing_the_winner():
    """Defensive: a validated spec cannot repeat a claim, so this pins the
    ordering and identity contract rather than a reachable state."""
    winner = commitment("s1", "t", .9, FINAL)
    winner_copy = commitment("s1", "t", .5, FINAL)  # same choice, graded differently
    rival = commitment("s1", "p", .7, INITIAL)
    rival_copy = commitment("s1", "p", .6, INITIAL)
    other_set = commitment("s2", "p", .7, INITIAL)
    satisfied = (rival_copy, winner_copy, other_set, rival, winner)
    best = _choose_column_commitment(satisfied)
    assert best is winner
    rivals = _competing_choices(best, satisfied)
    # Runner-up first; each choice identity once; the winner's duplicate omitted.
    assert [(r.set_id, r.proto_segment, r.confidence) for r in rivals] == [
        ("s1", "p", .7), ("s2", "p", .7)]


def test_reports_written_before_competing_choices_still_load():
    old = {"column_index": 0, "reflexes": ["p", "f"], "set_id": "s1", "proto_segment": "t",
           "resolved_by": "conditioned_set", "competing_set_ids": ["s2"]}
    loaded = ColumnResolution.model_validate_json(json.dumps(old))
    assert loaded.competing_set_ids == ("s2",)
    assert loaded.competing_choices == () and loaded.decided_by_equal_confidence is False
    fields = ReconstructionDiagnostics.model_json_schema()["properties"]
    assert "columns_with_competing_choices" in fields
    assert "columns_with_competing_choices" not in ReconstructionDiagnostics.model_json_schema().get("required", ())


def resolve_one_token(*commitments):
    plan = build_plan(("A", "B"), commitments, residue_policy=ResiduePolicy.DROP)
    (outcome,), stats = resolve_columns((("p",), ("f",)), "root", plan)
    return outcome.resolution, stats


@pytest.mark.parametrize("rival_value,equal", [("p", True), ("t", False)])
def test_equal_confidence_counts_only_when_the_value_was_arbitrary(rival_value, equal):
    resolution, stats = resolve_one_token(
        commitment("s1", "t", .9, FINAL), commitment("s1", rival_value, .9, INITIAL))
    assert resolution.proto_segment == ("p" if equal else "t")
    assert len(resolution.competing_choices) == 1
    assert resolution.decided_by_equal_confidence is equal
    assert (stats.competing, stats.equal_confidence) == (1, int(equal))


def test_a_distinct_competing_set_keeps_the_historical_count():
    """Legacy reflex binding: two sets with the same reflexes both apply."""
    resolution, stats = resolve_one_token(
        commitment("s1", "t", .9, FINAL), commitment("s2", "p", .7, INITIAL))
    assert (resolution.set_id, resolution.competing_set_ids) == ("s1", ("s2",))
    assert (stats.tie_broken, stats.competing, stats.equal_confidence) == (1, 1, 0)
