"""R01 finding 1: token-conditioned claims survive the native JSON boundary.

Before the repair a model-level `mode="before"` validator on
`CorrespondenceCommitment` handed `conditioning` on in strict python mode, so
`{"right": {"tokens": ["i"]}}` was refused by full-payload previews and a
compact preview was commit-ready but failed when its JSON snapshot was read at
commit. These cases go through `ToolRegistry.execute` and real artifacts, not
only typed objects.
"""
import json

import pytest
from pydantic import ValidationError

from cognate_reconstruction.agent.instructions import load_agent_instructions
from cognate_reconstruction.agent.orchestrator import AgentOrchestrator
from cognate_reconstruction.agent.reconstructor import AgenticNodeReconstructor
from cognate_reconstruction.agent.schemas import (
    CascadeRuleSpec, CommittedSoundRule, LLMMessage, LLMToolCall, MessageRole,
)
from cognate_reconstruction.agent.schemas import TestProtoAssemblyArgs as ProtoAssemblyArgs
from cognate_reconstruction.agent.service import ReconstructionService
from cognate_reconstruction.agent.tools import default_tool_registry
from cognate_reconstruction.agent.tools.inventory_evidence import node_inventory
from cognate_reconstruction.agent.trajectory import JsonlTrajectorySink, TrajectoryDatasetBuilder
from cognate_reconstruction.evaluation.run import trajectory_from_artifact
from cognate_reconstruction.ingestion import ingest_payload
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.schemas.inventory import (
    AlignmentOverride, CorrespondenceCommitment, ProtoInventorySpec, ResiduePolicy, SharedCorrespondenceClaim,
)
from cognate_reconstruction.schemas.rules import RuleEnvironment, SegmentExpression
from cognate_reconstruction.traversal.checkpoint import CheckpointStore, FamilyCheckpoint
from tests.workbench.test_evidence_contract import context, form, lex

PROTOCOLS = ("stored-hypothesis", "full-payload")
RIGHT_I = {"right": {"tokens": ["i"]}}
LEFT_I = {"left": {"tokens": ["i"]}}
# (A, B, conditioning): the conditioned p:f column, with the context it names.
CONDITIONED = {
    "right": (("p", "i"), ("f", "i"), RIGHT_I),
    "left": (("i", "p"), ("i", "f"), LEFT_I),
    "right-with-boundary-vocabulary": (("p", "i"), ("f", "i"),
        {"right": {"tokens": ["i"], "morphological_boundary_tokens": ["+"]}}),
    "word-initial-control": (("p", "i"), ("f", "i"), {"word_initial": True}),
}


def one_word(a, b):
    return context(lex("A", form("A", a, (("core", tuple(range(len(a)))),))),
                   lex("B", form("B", b, (("core", tuple(range(len(b)))),))))


def pf_set(ctx):
    inv, _ = node_inventory(ctx, segmentation_overlay_id=None, alignment_overlay_id=None)
    return next(s for s in inv.sets if "f" in s.segments)


def execute(ctx, protocol, name, cid, **args):
    return default_tool_registry(inventory_protocol=protocol).execute(
        LLMToolCall(call_id=cid, name=name, arguments=args), ctx)


def claim(ctx, conditioning, *, value="p", full=False):
    s = pf_set(ctx)
    row = {"set_id": s.set_id, "proto_segment": value, "confidence": .8,
           "rationale": "offline conditioned transcription control", "conditioning": conditioning}
    if full:
        row.update(reflexes=list(s.segments), support=s.support)
    return row


def preview_and_commit(ctx, protocol, conditioning, *, witness="A"):
    """Native input -> preview -> terminal commit, as JSON tool arguments only."""
    residue = {"residue_policy": "retain_from_witness", "residue_witness_child_id": witness}
    full = protocol == "full-payload"
    collection = {"commitments": [claim(ctx, conditioning, full=True)]} if full else {
        "choices": [claim(ctx, conditioning)]}
    preview = execute(ctx, protocol, "test_proto_assembly", "pv", detail="full", **residue, **collection)
    assert preview.ok, preview.error
    assert preview.result["executable"] and preview.result["commit_ready"]
    terminal = {"node_id": ctx.node_id, "anomalies": [], "summary": "conditioned control"}
    if full:
        terminal["inventory"] = {"child_node_ids": list(ctx.child_ids), **residue, **collection}
    else:
        terminal["hypothesis_id"] = preview.result["hypothesis_id"]
    committed = execute(ctx, protocol, "commit_reconstruction", "cm", **terminal)
    assert committed.ok, committed.error
    return preview.result, committed.result


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("case", sorted(CONDITIONED))
def test_conditioned_claim_previews_and_actually_commits_in_both_profiles(protocol, case):
    a, b, conditioning = CONDITIONED[case]
    ctx = one_word(a, b)
    preview, _ = preview_and_commit(ctx, protocol, conditioning)
    committed = ctx.commit.request.commitments
    assert len(committed) == 1
    assert committed[0].conditioning == RuleEnvironment.model_validate_json(json.dumps(conditioning))
    assert [c["assembled_segments"] for c in preview["concepts"]] == [list(a)]


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_condition_decides_output_after_snapshot_readback(protocol):
    # Residue witness B would give `f i`; only the applied right-`i` claim gives `p i`.
    applied = one_word(("p", "i"), ("f", "i"))
    preview, _ = preview_and_commit(applied, protocol, RIGHT_I, witness="B")
    assert [c["assembled_segments"] for c in preview["concepts"]] == [["p", "i"]]
    unmet = one_word(("p", "i"), ("f", "i"))
    preview, _ = preview_and_commit(unmet, protocol, {"right": {"tokens": ["u"]}}, witness="B")
    assert [c["assembled_segments"] for c in preview["concepts"]] == [["f", "i"]]


@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("conditioning,code_part", [
    ({"right": {"tokens": [1]}}, "string_type"),
    ({"right": {"tokens": "i"}}, "tuple_type"),
    ({"right": {"tokens": [""]}}, "string_too_short"),
    ({"right": {"tokens": ["i"], "morphological_boundary_tokens": ["#"]}}, "value_error"),
    ({"right": {"tokens": ["i"], "unexpected": True}}, "extra_forbidden"),
    ({"word_initial": "true"}, "bool_type"),
])
def test_malformed_conditioning_stays_rejected(protocol, conditioning, code_part):
    ctx = one_word(("p", "i"), ("f", "i"))
    full = protocol == "full-payload"
    collection = {"commitments": [claim(ctx, conditioning, full=True)]} if full else {
        "choices": [claim(ctx, conditioning)]}
    result = execute(ctx, protocol, "test_proto_assembly", "bad", residue_policy="drop", **collection)
    assert not result.ok
    assert code_part in result.error.message
    assert ctx.inventory_hypotheses == {}


def test_strict_scalars_and_python_mode_are_unchanged():
    base = {"set_id": "x", "reflexes": ["p", "f"], "support": 1, "proto_segment": "p", "confidence": .8}
    for bad in ({"support": "1"}, {"confidence": "0.8"}, {"reflexes": ["p", 1]},
                {"reflexes": "pf"}, {"reflexes": ["p"]}):
        with pytest.raises(ValidationError):
            CorrespondenceCommitment.model_validate_json(json.dumps({**base, **bad}))
    assert CorrespondenceCommitment.model_validate_json(
        json.dumps({**base, "reflexes": ["Ø", "f"]})).reflexes == (None, "f")
    # Python-mode strictness is not loosened: lists are still not tuples there.
    with pytest.raises(ValidationError):
        CorrespondenceCommitment.model_validate({**base, "reflexes": ("p", "f"),
            "conditioning": RIGHT_I})


def test_conditioned_models_round_trip_json_exactly():
    left_right = RuleEnvironment(left=SegmentExpression(tokens=("a", "+")),
        right=SegmentExpression(tokens=("i",)), word_final=True)
    commitment = CorrespondenceCommitment(set_id="csu-x", reflexes=("p", None), support=2,
        proto_segment="p", confidence=.8, conditioning=left_right, rationale="r")
    shared = SharedCorrespondenceClaim(pattern_id="csp-x", member_set_ids=("csu-x",),
        proto_segment="p", confidence=.8, rationale="r", conditioning=left_right)
    spec = ProtoInventorySpec(child_node_ids=("A", "B"), commitments=(commitment,),
        shared_claims=(shared,), residue_policy=ResiduePolicy.DROP)
    for value in (commitment, shared, spec):
        assert type(value).model_validate_json(value.model_dump_json()) == value
    args = ProtoAssemblyArgs.model_validate_json(spec.model_dump_json(
        exclude={"child_node_ids", "assembly_validation_call_id"}))
    assert args.commitments == (commitment,)


@pytest.mark.parametrize("model,raw", [
    (CommittedSoundRule, {"dsl": "f > p / _i", "source_child_ids": ["B"], "confidence": .8,
        "supporting_form_ids": ["B:word"], "rationale": "r"}),
    (CascadeRuleSpec, {"dsl": "f > p / _i", "source_child_ids": ["B"]}),
    (AlignmentOverride, {"concept_id": "w", "rows": [["p", "Ø"], ["f", "i"]],
        "analysis_ids": ["a", None], "rationale": "r"}),
])
def test_other_models_with_model_level_before_validators_round_trip(model, raw):
    # The remaining model-level `before` validators convert every container
    # field they hand on; a JSON round-trip of a populated value keeps that true.
    value = model.model_validate_json(json.dumps(raw))
    assert model.model_validate_json(value.model_dump_json()) == value


def test_conditioned_shared_claim_commits_through_handle():
    ctx = context(*(lex(ch, *(form(ch, (token, "i"), ((concept, (0, 1)),), concept=concept)
        for concept in ("one", "two", "three"))) for ch, token in (("A", "p"), ("B", "f"))))
    inv, _ = node_inventory(ctx, segmentation_overlay_id=None, alignment_overlay_id=None)
    pattern = next(p for p in inv.recurrence_patterns if "f" in p.segments)
    shared = {"pattern_id": pattern.set_id, "member_set_ids": list(pattern.member_set_ids),
        "proto_segment": "p", "confidence": .8, "rationale": "selected recurrent members",
        "conditioning": RIGHT_I}
    preview = execute(ctx, "stored-hypothesis", "test_proto_assembly", "pv", choices=[],
        shared_claims=[shared], residue_policy="retain_from_witness", residue_witness_child_id="B")
    assert preview.ok and preview.result["commit_ready"], preview.error
    committed = execute(ctx, "stored-hypothesis", "commit_reconstruction", "cm", node_id=ctx.node_id,
        hypothesis_id=preview.result["hypothesis_id"], anomalies=[], summary="shared conditioned control")
    assert committed.ok, committed.error
    assert ctx.commit.approved_shared_claims[0].conditioning.right.tokens == ("i",)
    assert {c.conditioning.right.tokens for c in ctx.commit.request.commitments} == {("i",)}


def test_conditioning_edit_needs_new_preview_and_old_handle_stays_immutable():
    ctx = one_word(("p", "i"), ("f", "i"))
    residue = {"residue_policy": "retain_from_witness", "residue_witness_child_id": "A"}
    first = execute(ctx, "stored-hypothesis", "test_proto_assembly", "pv1", choices=[claim(ctx, RIGHT_I)], **residue)
    edited = execute(ctx, "stored-hypothesis", "test_proto_assembly", "pv2",
        choices=[claim(ctx, {"word_initial": True})], **residue)
    again = execute(ctx, "stored-hypothesis", "test_proto_assembly", "pv3", choices=[claim(ctx, RIGHT_I)], **residue)
    assert first.ok and edited.ok and again.ok
    assert first.result["hypothesis_id"] != edited.result["hypothesis_id"]
    assert first.result["hypothesis_id"] == again.result["hypothesis_id"]
    assert first.result["hypothesis_digest"] == again.result["hypothesis_digest"]
    committed = execute(ctx, "stored-hypothesis", "commit_reconstruction", "cm", node_id=ctx.node_id,
        hypothesis_id=first.result["hypothesis_id"], anomalies=[], summary="original conditioned claim")
    assert committed.ok, committed.error
    assert ctx.commit.request.commitments[0].conditioning.right.tokens == ("i",)
    assert ctx.commit.request.commitments[0].conditioning.word_initial is False


class ConditionedProvider:
    """Scripted: survey, preview explicit choices, commit. Values are supplied, not inferred."""

    model = "scripted/r01-conditioned"

    def __init__(self, protocol):
        self.protocol = protocol

    def decisions(self, node, sets):
        if node == "x":  # children A (`p i`) and B (`f i`)
            item = next(s for s in sets if "f" in s["segments"])
            return [self.row(item, "p", RIGHT_I)], "B"
        item = next(s for s in sets if "b" in s["segments"])  # root: children x and C (`b i`)
        return [self.row(item, "p", None)], "x"

    def row(self, item, value, conditioning):
        row = {"set_id": item["set_id"], "proto_segment": value, "confidence": .8,
               "rationale": "scripted supplied control, not a historical claim"}
        if conditioning is not None:
            row["conditioning"] = conditioning
        if self.protocol == "full-payload":
            row.update(reflexes=item["segments"], support=item["support"])
        return row

    def complete(self, messages, tools, **kwargs):
        prompt = messages[1].content
        node = json.loads(prompt[prompt.index("{"):])["node_id"]
        results = [m for m in messages if m.role is MessageRole.TOOL]
        for message in results:
            assert json.loads(message.content)["ok"], message.content
        if not results:
            name, args = "summarize_correspondences", {"reading": "local", "min_support": 1,
                "limit": 50, "include_outgroup": False}
        else:
            survey = json.loads(results[0].content)["result"]
            rows, witness = self.decisions(node, survey["sets"])
            key = "commitments" if self.protocol == "full-payload" else "choices"
            collection = {key: rows, "residue_policy": "retain_from_witness",
                          "residue_witness_child_id": witness}
            if len(results) == 1:
                name, args = "test_proto_assembly", collection
            else:
                preview = json.loads(results[-1].content)["result"]
                assert preview["commit_ready"]
                name = "commit_reconstruction"
                args = {"node_id": node, "anomalies": [], "summary": "scripted conditioned control"}
                if self.protocol == "full-payload":
                    children = [c["node_id"] for c in json.loads(prompt[prompt.index("{"):])["active_children"]]
                    args["inventory"] = {"child_node_ids": children, **collection}
                else:
                    args["hypothesis_id"] = preview["hypothesis_id"]
        return LLMMessage(role=MessageRole.ASSISTANT, tool_calls=(LLMToolCall(
            call_id=f"{node}-{len(results)}", name=name, arguments=args),))


@pytest.mark.parametrize("protocol", PROTOCOLS)
def test_conditioned_commit_reaches_jsonl_checkpoint_parent_and_result(tmp_path, protocol):
    word = lambda ch, segs: lex(ch, form(ch, segs, (("core", (0, 1)),)))
    payload = WorkbenchPayload(lexicons=(word("A", ("p", "i")), word("B", ("f", "i")),
        word("C", ("b", "i"))), newick="((A,B)x,C)r;")
    path = tmp_path / "trajectory.jsonl"
    store = CheckpointStore(tmp_path / "checkpoint.json")
    store.save(FamilyCheckpoint(run_id="r01", input_sha256="i", configuration_sha256="c",
        normalized_tree_sha256="t"))
    service = ReconstructionService(AgenticNodeReconstructor(AgentOrchestrator(
        ConditionedProvider(protocol), registry=default_tool_registry(inventory_protocol=protocol),
        trajectory_sink=JsonlTrajectorySink(path), instructions=load_agent_instructions(),
        run_id="r01-" + protocol, configuration_sha256="scripted-r01")))
    result = service.reconstruct_family(ingest_payload(payload),
        on_step_complete=lambda step: store.save(store.load().with_step(step)))

    # Committed JSONL readback: the conditioned claim is the one that was previewed.
    lines = path.read_text().splitlines()
    trajectories = [trajectory_from_artifact(json.loads(line)) for line in lines]
    assert [t.node_id for t in trajectories] == ["x", "r"]
    assert all(t.completed for t in trajectories)
    x_commit = trajectories[0].committed_reconstruction.request.commitments
    assert [c.conditioning.right.tokens for c in x_commit] == [("i",)]

    # Checkpoint readback carries the same commitment and the resulting beam.
    steps = store.load().steps_by_node
    assert set(steps) == {"x", "r"}
    x_beam = steps["x"].output_beam
    assert [c.segments for c in x_beam.distributions[0].candidates][:1] == [("p", "i")]

    # Parent use: the root assembled from x's committed `p i`, not from B's `f i`.
    root = next(n for n in result.internal_nodes if n.node_id == "r")
    assert root.best_lexicon.forms[0].segments == ("p", "i")
    reread = type(result).model_validate_json(result.model_dump_json(exclude_computed_fields=True))
    assert reread.internal_nodes[0].best_lexicon.forms[0].segments == ("p", "i")

    # Resume reading: the CLI's JSONL reader and completed-node reuse need no new call.
    seeds = TrajectoryDatasetBuilder.read_jsonl(path)
    assert seeds[0].committed_reconstruction.request.commitments == x_commit
    resumed = ReconstructionService(AgenticNodeReconstructor(AgentOrchestrator(
        NoCallProvider(), registry=default_tool_registry(inventory_protocol=protocol),
        instructions=load_agent_instructions(), run_id="r01-" + protocol,
        configuration_sha256="scripted-r01"))).reconstruct_family(
        ingest_payload(payload), resume_steps=steps, seed_trajectories=seeds)
    assert [n.best_lexicon.forms[0].segments for n in resumed.internal_nodes] == [("p", "i"), ("p", "i")]


class NoCallProvider:
    model = "scripted/no-call"

    def complete(self, messages, tools, **kwargs):
        raise AssertionError("completed conditioned nodes must be reused without a provider call")


SEEDED_HANDLE_SCRIPT = """
import json
from cognate_reconstruction.schemas.lexicon import LexicalForm
from cognate_reconstruction.schemas.rules import SegmentExpression
from tests.workbench.test_conditioned_native_roundtrip import RIGHT_I, one_word, preview_and_commit
dumps = {SegmentExpression(tokens=("i",)).model_dump_json(),
         SegmentExpression.model_validate_json(SegmentExpression(tokens=("i",)).model_dump_json()).model_dump_json(),
         SegmentExpression.model_validate_json('{"tokens":["i"],"morphological_boundary_tokens":["-","+"]}').model_dump_json()}
form = LexicalForm(form_id="f", variety_id="A", concept_id="c", segments=("p",))
preview_and_commit(one_word(("p", "i"), ("f", "i")), "stored-hypothesis", RIGHT_I)
print(json.dumps({"segment_dumps": sorted(dumps),
                  "form_boundaries": json.loads(form.model_dump_json())["morphological_boundary_tokens"]}))
"""


@pytest.mark.parametrize("seed", ["1", "2", "7"])
def test_boundary_sets_serialize_canonically_and_handles_commit_under_any_hash_seed(seed):
    # frozenset dumps followed the string-hash seed, so a stored conditioned
    # handle could be re-digested differently from its own JSON snapshot and
    # refused as stale at commit (seed 7: the default set and its readback
    # dumped in different orders). Each seed runs in a fresh interpreter.
    import os
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": str(root)}
    done = subprocess.run([sys.executable, "-c", SEEDED_HANDLE_SCRIPT], cwd=root, env=env,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-2000:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out == {"segment_dumps": ['{"tokens":["i"],"morphological_boundary_tokens":["+","-"]}'],
                   "form_boundaries": ["+", "-"]}
