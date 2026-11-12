"""B03 protocol scaling tests: stored-hypothesis-v2 patching and true-merger filtering."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from cognate_reconstruction import cli
from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.instructions import load_agent_instructions
from cognate_reconstruction.agent.schemas import LLMToolCall
from cognate_reconstruction.agent.tools import default_tool_registry
from cognate_reconstruction.agent.tools.commit_reconstruction import (
    inventory_commit_requirements,
)
from cognate_reconstruction.agent.tools.inventory_evidence import node_inventory
from cognate_reconstruction.agent.tools.stored_hypothesis import (
    StoredAssemblyV2Args,
    describe_inventory_input,
    describe_inventory_input_v2,
)
from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.ingestion import ingest_payload
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.schemas.inventory import (
    CorrespondenceCommitment,
    ProtoInventorySpec,
    ResiduePolicy,
    derive_set_id,
)
from cognate_reconstruction.traversal.assembler import inventory_contrast_reductions
from tests.workbench.test_evidence_contract import context, form, lex

ROOT = Path(__file__).resolve().parents[2]
B02_PAYLOAD_PATH = (
    ROOT / "runs/experiments/b02-burmish-gemini-benchmark/inputs/burmish.payload.json"
)
B02_TRAJECTORY_PATH = (
    ROOT
    / "runs/experiments/b02-burmish-gemini-benchmark/runs/burmish-gemini/trajectories.jsonl"
)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_text(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _exec(
    ctx: AgentContext,
    name: str,
    call_id: str,
    *,
    protocol: str = "stored-hypothesis-v2",
    **arguments,
):
    registry = default_tool_registry(inventory_protocol=protocol)
    return registry.execute(
        LLMToolCall(call_id=call_id, name=name, arguments=arguments),
        ctx,
    )


def _commitment(
    reflexes: tuple[str | None, ...],
    proto: str | None,
    *,
    children: tuple[str, ...],
    support: int = 2,
    confidence: float = 0.9,
    rationale: str = "test commitment",
    directionality_rationale: str | None = None,
) -> CorrespondenceCommitment:
    return CorrespondenceCommitment(
        set_id=derive_set_id(
            reflexes,
            children,
            segmentation_overlay_id=None,
            alignment_overlay_id=None,
        ),
        reflexes=reflexes,
        proto_segment=proto,
        support=support,
        confidence=confidence,
        rationale=rationale,
        directionality_rationale=directionality_rationale,
    )


def _three_concept_context() -> AgentContext:
    return context(
        lex(
            "A",
            form("A", ("p", "a"), (("one", (0, 1)),), concept="one"),
            form("A", ("p", "a"), (("two", (0, 1)),), concept="two"),
            form("A", ("p", "i"), (("three", (0, 1)),), concept="three"),
        ),
        lex(
            "B",
            form("B", ("f", "a"), (("one", (0, 1)),), concept="one"),
            form("B", ("f", "a"), (("two", (0, 1)),), concept="two"),
            form("B", ("f", "i"), (("three", (0, 1)),), concept="three"),
        ),
    )


# ---------------------------------------------------------------------------
# 1. Digest invariance of v1 ("stored-hypothesis" / "full-payload") & v2 wire
# ---------------------------------------------------------------------------


def test_v1_stored_hypothesis_digests_stay_bit_for_bit_invariant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    v1_instructions = load_agent_instructions()
    assert v1_instructions == load_agent_instructions(
        inventory_protocol="stored-hypothesis"
    )
    assert v1_instructions == load_agent_instructions(inventory_protocol="full-payload")
    assert (
        _sha256_text(v1_instructions)
        == "0b9d91cf5f5fd469fea1f5ec277ab436b7a412d4d2a87b94a766ff37166dc46d"
    )

    digests_v1 = cli._behavioural_input_digests(
        SimpleNamespace(
            inventory_protocol="stored-hypothesis",
            agent_instructions=None,
            anchors=None,
        )
    )
    assert (
        digests_v1["the agent instructions"]
        == "0b9d91cf5f5fd469fea1f5ec277ab436b7a412d4d2a87b94a766ff37166dc46d"
    )
    assert (
        digests_v1["the tool schemas"]
        == "628f0f32eca43a872c7fb72c90e67b1ba3e00b9a1f9b4057e1cf702175584a72"
    )

    r04_manifest_path = (
        ROOT / "runs/experiments/r04-stage-c-20261029-v2/manifest.stage-c.json"
    )
    if r04_manifest_path.exists():
        monkeypatch.setenv("GEMINI_API_KEY", "offline-dummy-key")
        r04_argv = json.loads(r04_manifest_path.read_text(encoding="utf-8"))["arm"][
            "gemini-r04"
        ]["argv"][3:]
        _, recomputed_sha, _, _ = cli._provider_and_configuration(
            cli._parser().parse_args([*r04_argv, "--no-preflight"])
        )
        assert (
            recomputed_sha
            == "339adb1338add17c78a0b5477d9c0b9dd85b64501e2be314951627861adce38a"
        )


def test_v2_instructions_cli_and_gemini_tool_schema_wire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    v2_instructions = load_agent_instructions(inventory_protocol="stored-hypothesis-v2")
    assert v2_instructions.startswith(load_agent_instructions().rstrip("\n"))
    assert (
        "## Incremental Hypothesis Patching & Multi-Daughter Survey (stored-hypothesis-v2)"
        in v2_instructions
    )
    assert "base_hypothesis_id" in v2_instructions
    assert "min_attested_children=2" in v2_instructions

    with pytest.raises(ValueError, match="unknown inventory protocol"):
        load_agent_instructions(inventory_protocol="unknown-v99")

    parsed = cli._parser().parse_args(
        [
            "infer",
            "--input",
            "unused.json",
            "--model",
            "test-model",
            "--inventory-protocol",
            "stored-hypothesis-v2",
            "--no-preflight",
        ]
    )
    assert parsed.inventory_protocol == "stored-hypothesis-v2"
    digests_v2 = cli._behavioural_input_digests(parsed)
    assert digests_v2["the agent instructions"] == _sha256_text(v2_instructions)
    assert digests_v2["the agent instructions"] != _sha256_text(
        load_agent_instructions()
    )
    assert (
        digests_v2["the tool schemas"]
        != "628f0f32eca43a872c7fb72c90e67b1ba3e00b9a1f9b4057e1cf702175584a72"
    )

    # Zero-arg monkeypatches of cli.load_agent_instructions remain compatible across all protocols.
    with monkeypatch.context() as mp:
        mp.setattr(cli, "load_agent_instructions", lambda: "Zero-arg stub.")
        for proto in ("full-payload", "stored-hypothesis", "stored-hypothesis-v2"):
            stub_args = SimpleNamespace(
                inventory_protocol=proto, agent_instructions=None
            )
            assert cli._selected_instructions(stub_args) == "Zero-arg stub."

    remediation = describe_inventory_input_v2(None)
    assert remediation.startswith(describe_inventory_input(None))
    for field_name in ("base_hypothesis_id", "drop_set_ids", "drop_pattern_ids"):
        assert field_name in remediation

    # Verify Gemini function-declaration conversion preserves every v2 property cleanly.
    from litellm.llms.vertex_ai.gemini.vertex_and_google_ai_studio_gemini import (
        VertexGeminiConfig,
    )

    definitions = default_tool_registry(
        inventory_protocol="stored-hypothesis-v2"
    ).definitions()
    declarations = VertexGeminiConfig()._map_function(
        value=[
            {
                "type": "function",
                "function": {
                    "name": d.name,
                    "description": d.description,
                    "parameters": json.loads(json.dumps(d.parameters)),
                },
            }
            for d in definitions
        ],
        optional_params={},
    )[0]["function_declarations"]
    sent = {d["name"]: d.get("parameters") or {} for d in declarations}
    for d in definitions:
        assert set(d.parameters.get("properties", {})) == set(
            sent[d.name].get("properties", {})
        )
    rejected_keys = {"$ref", "$defs", "additionalProperties", "exclusiveMinimum"}
    seen_keys: set[str] = set()

    def walk(obj: object) -> None:
        if isinstance(obj, dict):
            seen_keys.update(map(str, obj))
            for val in obj.values():
                walk(val)
        elif isinstance(obj, list):
            for val in obj:
                walk(val)

    walk(declarations)
    assert not (seen_keys & rejected_keys)


# ---------------------------------------------------------------------------
# 2. stored-hypothesis-v2 incremental patching semantics
# ---------------------------------------------------------------------------


def test_v2_schema_requires_explicit_claims_when_fresh_and_delta_when_patching() -> None:
    with pytest.raises(ValidationError, match="state choices"):
        StoredAssemblyV2Args.model_validate({"residue_policy": ResiduePolicy.DROP})
    with pytest.raises(ValidationError, match="residue_policy is required"):
        StoredAssemblyV2Args.model_validate({"choices": ()})
    with pytest.raises(ValidationError, match="supply at least one patch"):
        StoredAssemblyV2Args.model_validate({"base_hypothesis_id": "hyp-abc"})

    ctx = _three_concept_context()
    bad_drop = _exec(
        ctx,
        "test_proto_assembly",
        "bad-drop",
        choices=[],
        drop_set_ids=["csu-123"],
        residue_policy="drop",
    )
    assert not bad_drop.ok
    assert bad_drop.error.code == "invalid-hypothesis-patch"

    bare_drop = _exec(
        ctx,
        "test_proto_assembly",
        "bare-drop",
        drop_pattern_ids=["csp-123"],
    )
    assert not bare_drop.ok
    assert bare_drop.error.code == "invalid-hypothesis-patch"


def test_v2_incremental_upsert_supersedes_smoke_choice_carves_exception_and_commits() -> None:
    ctx = _three_concept_context()
    inv, _ = node_inventory(ctx, segmentation_overlay_id=None, alignment_overlay_id=None)
    pf_pattern = next(p for p in inv.recurrence_patterns if p.segments == ("p", "f"))
    aa_pattern = next(p for p in inv.recurrence_patterns if p.segments == ("a", "a"))
    ii_local = next(s for s in inv.sets if s.segments == ("i", "i"))
    assert len(pf_pattern.member_set_ids) == 3

    # Step 1: Smoke-test 1 local choice from pf_pattern + witness residue policy.
    smoke_member = pf_pattern.member_set_ids[0]
    p1 = _exec(
        ctx,
        "test_proto_assembly",
        "p1",
        choices=[
            {
                "set_id": smoke_member,
                "proto_segment": "p",
                "confidence": 0.8,
                "rationale": "initial smoke choice",
            },
            {
                "set_id": ii_local.set_id,
                "proto_segment": "i",
                "confidence": 0.95,
                "rationale": "front vowel retention",
            },
        ],
        residue_policy="retain_from_witness",
        residue_witness_child_id="A",
    )
    assert p1.ok, p1.error
    h1 = p1.result["hypothesis_id"]
    snap1_before = ctx.inventory_hypotheses[h1].model_dump_json()

    # Same-call self-overlap (smoke_member in BOTH choices and shared_claims of the SAME call) is still rejected:
    same_call_overlap = _exec(
        ctx,
        "test_proto_assembly",
        "p-self-overlap",
        base_hypothesis_id=h1,
        choices=[
            {
                "set_id": smoke_member,
                "proto_segment": "p",
                "confidence": 0.9,
                "rationale": "duplicate in same call",
            }
        ],
        shared_claims=[
            {
                "pattern_id": pf_pattern.set_id,
                "member_set_ids": list(pf_pattern.member_set_ids),
                "proto_segment": "p",
                "confidence": 0.9,
                "rationale": "shared labial claim",
            }
        ],
    )
    assert not same_call_overlap.ok
    assert same_call_overlap.error.code == "invalid-shared-claim"

    # Step 2: Promote smoke_member into full pf_pattern shared_claim + add aa_pattern shared_claim.
    # Inherits residue_policy='retain_from_witness', residue_witness_child_id='A', and ii_local choice!
    p2 = _exec(
        ctx,
        "test_proto_assembly",
        "p2",
        base_hypothesis_id=h1,
        shared_claims=[
            {
                "pattern_id": pf_pattern.set_id,
                "member_set_ids": list(pf_pattern.member_set_ids),
                "proto_segment": "p",
                "confidence": 0.9,
                "rationale": "shared labial retention across all three etyma",
            },
            {
                "pattern_id": aa_pattern.set_id,
                "member_set_ids": list(aa_pattern.member_set_ids),
                "proto_segment": "a",
                "confidence": 0.95,
                "rationale": "low vowel retention",
            },
        ],
    )
    assert p2.ok, p2.error
    h2 = p2.result["hypothesis_id"]
    assert h2 != h1
    assert p2.result["commit_ready"] is True
    assert p2.result["residue_policy"] == "retain_from_witness"
    assert len(p2.result["covered_set_ids"]) == 6
    # Base snapshot remains completely immutable:
    assert ctx.inventory_hypotheses[h1].model_dump_json() == snap1_before

    # Step 3: Carve a 1-set local exception out of pf_pattern (concept 'three' before i -> *t)
    # using a 1-element choices=[...] patch without re-sending pf_pattern.member_set_ids!
    three_pf_set = next(
        s.set_id
        for s in inv.sets
        if s.segments == ("p", "f") and s.scope_id == "three"
    )
    p3 = _exec(
        ctx,
        "test_proto_assembly",
        "p3",
        base_hypothesis_id=h2,
        choices=[
            {
                "set_id": three_pf_set,
                "proto_segment": "t",
                "confidence": 0.7,
                "rationale": "palatalized dental exception before i",
            }
        ],
    )
    assert p3.ok, p3.error
    h3 = p3.result["hypothesis_id"]
    spec3 = ProtoInventorySpec.model_validate_json(ctx.inventory_hypotheses[h3].spec_json)
    pf_shared_after_carve = next(
        sc for sc in spec3.shared_claims if sc.pattern_id == pf_pattern.set_id
    )
    assert set(pf_shared_after_carve.member_set_ids) == set(
        pf_pattern.member_set_ids
    ) - {three_pf_set}
    assert {c.set_id: c.proto_segment for c in spec3.commitments} == {
        ii_local.set_id: "i",
        three_pf_set: "t",
    }

    # Step 4: Test drop_set_ids and drop_pattern_ids, plus policy switch to 'drop' (clearing witness automatically).
    p4 = _exec(
        ctx,
        "test_proto_assembly",
        "p4",
        base_hypothesis_id=h3,
        drop_set_ids=[ii_local.set_id],
        drop_pattern_ids=[aa_pattern.set_id],
        residue_policy="drop",
    )
    assert p4.ok, p4.error
    h4 = p4.result["hypothesis_id"]
    spec4 = ProtoInventorySpec.model_validate_json(ctx.inventory_hypotheses[h4].spec_json)
    assert spec4.residue_policy is ResiduePolicy.DROP
    assert spec4.residue_witness_child_id is None
    assert [sc.pattern_id for sc in spec4.shared_claims] == [pf_pattern.set_id]
    assert [c.set_id for c in spec4.commitments] == [three_pf_set]

    # Step 5: Commit h3 (the complete 6-set carved inventory) and verify persisted structure!
    committed = _exec(
        ctx,
        "commit_reconstruction",
        "commit-h3",
        node_id=ctx.node_id,
        hypothesis_id=h3,
        anomalies=[],
        summary="Incrementally patched inventory with one local exception.",
    )
    assert committed.ok, committed.error
    assert ctx.commit is not None
    assert len(ctx.commit.request.commitments) == 6
    approved_by_pattern = {
        sc.pattern_id: sc.member_set_ids for sc in ctx.commit.approved_shared_claims
    }
    assert set(approved_by_pattern) == {pf_pattern.set_id, aa_pattern.set_id}
    assert set(approved_by_pattern[pf_pattern.set_id]) == set(
        pf_pattern.member_set_ids
    ) - {three_pf_set}


def test_v2_rejects_unknown_and_stale_base_hypotheses() -> None:
    ctx = _three_concept_context()
    unknown = _exec(
        ctx,
        "test_proto_assembly",
        "unknown-base",
        base_hypothesis_id="hyp-does-not-exist",
        choices=[],
    )
    assert not unknown.ok
    assert unknown.error.code == "hypothesis-unknown"

    p1 = _exec(
        ctx,
        "test_proto_assembly",
        "p1",
        choices=[],
        residue_policy="drop",
    )
    assert p1.ok, p1.error
    h1 = p1.result["hypothesis_id"]

    # Cross-session / other context cannot use h1:
    other_ctx = _three_concept_context()
    cross = _exec(
        other_ctx,
        "test_proto_assembly",
        "cross-session",
        base_hypothesis_id=h1,
        choices=[],
    )
    assert not cross.ok
    assert cross.error.code == "hypothesis-unknown"

    # Creating a segmentation overlay changes evidence_revision -> patching h1 under new overlay raises hypothesis-stale:
    first_form = ctx.all_forms[0]
    seg = _exec(
        ctx,
        "segment_morphemes",
        "seg1",
        segmentations=[
            {
                "form_id": first_form.form_id,
                "segments": [first_form.segments[0], "+", *first_form.segments[1:]],
            }
        ],
        rationale="test boundary overlay",
    )
    assert seg.ok, seg.error
    overlay_id = seg.result["segmentation_overlay_id"]

    stale_overlay = _exec(
        ctx,
        "test_proto_assembly",
        "stale-overlay",
        base_hypothesis_id=h1,
        segmentation_overlay_id=overlay_id,
    )
    assert not stale_overlay.ok
    assert stale_overlay.error.code == "hypothesis-stale"
    assert "evidence_revision" in stale_overlay.error.message

    # Underlying form change also invalidates base_hypothesis_id with hypothesis-stale:
    ctx.child_lexicons = (
        lex("A", form("A", ("t", "a"), (("one", (0, 1)),), concept="one")),
        ctx.child_lexicons[1],
    )
    stale_forms = _exec(
        ctx,
        "test_proto_assembly",
        "stale-forms",
        base_hypothesis_id=h1,
        choices=[],
    )
    assert not stale_forms.ok
    assert stale_forms.error.code == "hypothesis-stale"


# ---------------------------------------------------------------------------
# 3. inventory_contrast_reductions: true mergers vs partial attestation
# ---------------------------------------------------------------------------


def test_inventory_contrast_reductions_separates_partial_attestation_from_true_mergers() -> None:
    four = ("A", "B", "C", "D")
    two = ("A", "B")

    # 1. Partial attestation of identical retention: ('j','j','j','j') + (None,None,'j',None) -> *j
    j_sets = (
        _commitment(("j", "j", "j", "j"), "j", children=four),
        _commitment((None, None, "j", None), "j", children=four),
    )
    assert inventory_contrast_reductions(j_sets) == ()

    # 2. Boundary partial attestation: (None,'+',None,None) + ('+',None,None,None) -> *+
    plus_sets = (
        _commitment((None, "+", None, None), "+", children=four),
        _commitment(("+", None, None, None), "+", children=four),
    )
    assert inventory_contrast_reductions(plus_sets) == ()

    # 3. Consistent multi-reflex partial attestation: ('o','a','o','ɔ') + (None,'a','o',None) -> *a
    a_sets = (
        _commitment(("o", "a", "o", "ɔ"), "a", children=four),
        _commitment((None, "a", "o", None), "a", children=four),
    )
    assert inventory_contrast_reductions(a_sets) == ()

    # 4. True within-child merger: ('l','l') + ('l','n') -> *l
    l_sets = (
        _commitment(("l", "l"), "l", children=two),
        _commitment(("l", "n"), "l", children=two),
    )
    l_reds = {r.set_id: r for r in inventory_contrast_reductions(l_sets)}
    assert set(l_reds) == {c.set_id for c in l_sets}
    assert all(r.merges and not r.deletes for r in l_reds.values())

    # 5. Within-child merger with non-conflicting bystander singleton:
    # ('ʔ','ʔ','k','k') + (None,'k',None,None) conflict in slot 1, while (None,None,'k',None) does not!
    k_full = _commitment(("ʔ", "ʔ", "k", "k"), "k", children=four)
    k_slot1 = _commitment((None, "k", None, None), "k", children=four)
    k_bystander = _commitment((None, None, "k", None), "k", children=four)
    k_reds = {
        r.set_id: r
        for r in inventory_contrast_reductions((k_full, k_slot1, k_bystander))
    }
    assert set(k_reds) == {k_full.set_id, k_slot1.set_id}
    assert k_bystander.set_id not in k_reds

    # 6. Disjoint-witness merger: ('p', None) + (None, 't') -> *p (no set co-attests {'p', 't'})
    disjoint_sets = (
        _commitment(("p", None), "p", children=two),
        _commitment((None, "t"), "p", children=two),
    )
    disjoint_reds = {r.set_id: r for r in inventory_contrast_reductions(disjoint_sets)}
    assert set(disjoint_reds) == {c.set_id for c in disjoint_sets}
    assert all(r.merges and not r.deletes for r in disjoint_reds.values())

    # 7. Deletion remains flagged unchanged: ('h', None) -> None
    del_set = _commitment(("h", None), None, children=two)
    del_reds = inventory_contrast_reductions((del_set,))
    assert len(del_reds) == 1
    assert del_reds[0].set_id == del_set.set_id
    assert del_reds[0].deletes is True and del_reds[0].merges is False


# ---------------------------------------------------------------------------
# 4. Replay on B02 Stage 1 maruic Turn 15 -> Turn 21 (394 sets)
# ---------------------------------------------------------------------------


def test_b02_maruic_turn15_to_turn21_replay_supersedes_and_eliminates_false_mergers() -> None:
    if not (B02_PAYLOAD_PATH.exists() and B02_TRAJECTORY_PATH.exists()):
        pytest.skip("B02 Stage 1 maruic artifacts are not present in this checkout")

    payload = WorkbenchPayload.model_validate_json(
        B02_PAYLOAD_PATH.read_text(encoding="utf-8")
    )
    dataset = ingest_payload(payload)
    by_variety = {lexicon.variety_id: lexicon for lexicon in dataset.lexicons}
    traj = json.loads(
        B02_TRAJECTORY_PATH.read_text(encoding="utf-8").splitlines()[0]
    )
    active_ids = tuple(
        child["node_id"] for child in traj["initial_payload"]["active_children"]
    )
    ctx = AgentContext(
        node_id="maruic",
        child_lexicons=tuple(by_variety[cid] for cid in active_ids),
        aligner=LingPyAligner(),
    )

    t15_args = traj["messages"][30]["tool_calls"][0]["arguments"]
    t21_args = traj["messages"][42]["tool_calls"][0]["arguments"]

    # Replay Turn 15 under stored-hypothesis-v2:
    r15 = _exec(ctx, "test_proto_assembly", "turn15", **t15_args)
    assert r15.ok, r15.error
    h15 = r15.result["hypothesis_id"]
    assert len(r15.result["covered_set_ids"]) == 3

    # Replay Turn 21 as an incremental patch on h15 (passing ONLY Turn 21's 55 shared_claims):
    # Two of Turn 15's smoke choices (ŋ and ⁵⁵) are automatically superseded by shared_claims,
    # while the third ('a' in 1209) survives, yielding the exact 394-set deduplicated inventory!
    r21 = _exec(
        ctx,
        "test_proto_assembly",
        "turn21-patched",
        base_hypothesis_id=h15,
        shared_claims=t21_args["shared_claims"],
        detail=t21_args["detail"],
    )
    assert r21.ok, r21.error
    assert len(r21.result["covered_set_ids"]) == 394

    # Inspect exact contrast-reduction and missing-directionality counts on the 394 commitments:
    inv, _ = node_inventory(ctx, segmentation_overlay_id=None, alignment_overlay_id=None)
    patched_spec = ProtoInventorySpec.model_validate_json(
        ctx.inventory_hypotheses[r21.result["hypothesis_id"]].spec_json
    )
    from cognate_reconstruction.agent.tools.inventory_evidence import (
        expand_shared_claims,
    )

    expanded = expand_shared_claims(patched_spec, inv)
    assert len(expanded.commitments) == 394

    reductions = inventory_contrast_reductions(expanded.commitments)
    by_id = {c.set_id: c for c in expanded.commitments}
    flagged_protos = {by_id[r.set_id].proto_segment for r in reductions}
    # Only the 3 genuine within-child segmental/tonal mergers (*k, *²¹, *⁵⁵) are flagged —
    # partial-attestation retentions (*+, *j, *ŋ, *m, *a, *u, *au, *kʰ, *ʔ, *³¹, *³⁵, *⁵¹) are NOT!
    assert flagged_protos == {"k", "²¹", "⁵⁵"}
    assert len(reductions) == 55

    missing_reqs = inventory_commit_requirements(expanded.commitments)
    assert [req.code for req in missing_reqs] == ["missing-directionality-rationale"]
    # Down from 346 false-positive missing-directionality sets to the 35 genuine unexplained merger sets!
    assert "35 committed set(s)" in missing_reqs[0].message
