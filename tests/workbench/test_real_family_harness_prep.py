"""Focused & portable offline tests for B01 real-family harness prep (`$0`, 0 live calls).

Covers all four B01 integration requirements:
  1. `--tied-confidence-threshold` propagation to both `proto_assembly.py:assemble_node`
     and `AgenticNodeReconstructor`, verifying preview-commit beam agreement across
     multi-level trees and `configuration_sha256` invariance when `None` vs `0.5`.
  2. `audit_run_directory` & `tools/hypothesis_critic_probe.py audit-run` across both
     completed and `--stop-after-node` checkpointed runs, verifying zero false positives
     on 2-child root nodes (`proto_burmish` / `proto_polynesian`) and shifted/prefixed
     outgroups while catching all 5 scoped defects.
  3. `--compaction-watermark-tokens` in `AgentOrchestrator` and `cli.py`, verifying
     100% prefix-cache preservation below watermark, deterministic stubbing of older
     accepted previews above watermark with preserved `validation_id`/`inventory_id`
     handles, verbatim retention of `ok=false` errors and newest accepted previews,
     repeat-call guard on identical `argument_sha256`, and uncompacted `trajectories.jsonl`.
  4. End-to-end offline rehearsal of the `B02` Stage 1 (`--stop-after-node maruic`) ->
     `gate-stage1` -> Stage 2 (`--resume`) -> `evaluate` pipeline in `tmp_path` with a
     priced fake provider, verifying cumulative `read_run_resources` cost certification
     and tone-preserving `task02-v1` + `R06` `corpus_bcubed_f1` + counterfactual replay.
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from cognate_reconstruction import cli
from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.instructions import load_agent_instructions
from cognate_reconstruction.agent.orchestrator import AgentOrchestrator
from cognate_reconstruction.agent.providers.litellm_provider import LiteLLMProvider
from cognate_reconstruction.agent.providers.pricing import load_price_table, price_for
from cognate_reconstruction.agent.reconstructor import AgenticNodeReconstructor
from cognate_reconstruction.agent.schemas import (
    LLMMessage,
    LLMToolCall,
    MessageRole,
    ProviderResponse,
    ProviderResponseMetadata,
    ProviderUsage,
)
from cognate_reconstruction.agent.service import ReconstructionService
from cognate_reconstruction.agent.tools import default_tool_registry
from cognate_reconstruction.agent.trajectory import (
    JsonlTrajectorySink,
    TrajectoryDatasetBuilder,
)
from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.benchmarks.ledger import read_run_resources
from cognate_reconstruction.evaluation.critic import (
    REAL_RUN_AUDIT_MODE,
    REAL_RUN_DEFECT_CATEGORIES,
    audit_run_directory,
)
from cognate_reconstruction.ingestion import ingest_payload
from cognate_reconstruction.schemas.historical import (
    GoldEvidenceKind,
    HistoricalFormBinding,
    HistoricalFormRole,
    TargetValidity,
)
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.schemas.lexicon import (
    CognateMembership,
    CognateMembershipInterpretation,
    CognateMembershipProvenance,
    CognateMembershipScope,
    ConceptMetadata,
    LanguageLexicon,
    LexicalForm,
)
from cognate_reconstruction.traversal import CheckpointStore, FamilyCheckpoint, PlannedStop
from cognate_reconstruction.traversal.beam import make_leaf_beam
from tools import real_family_benchmark_probe as b02_probe

ROOT = Path(__file__).resolve().parents[2]


def _whole_cog_membership(
    form_id: str,
    cognate_set_id: str,
    segments: tuple[str, ...],
    row: int = 1,
) -> CognateMembership:
    return CognateMembership(
        membership_id=f"{form_id}:m1",
        cognate_set_id=cognate_set_id,
        scope=CognateMembershipScope.WHOLE_FORM,
        interpretation=CognateMembershipInterpretation.ASSERTED,
        segment_indices=(),
        provenance=CognateMembershipProvenance(
            dataset_id="synthetic_test",
            source_table="CognateTable",
            source_row=row,
            source_cognateset_id=cognate_set_id,
        ),
    )


def _slice_cog_membership(
    form_id: str,
    idx: int,
    cognate_set_id: str,
    segment_indices: tuple[int, ...],
    row: int = 1,
) -> CognateMembership:
    return CognateMembership(
        membership_id=f"{form_id}:m{idx}",
        cognate_set_id=cognate_set_id,
        scope=CognateMembershipScope.SEGMENT_SLICE,
        interpretation=CognateMembershipInterpretation.PARTIAL_COGNATE,
        segment_indices=segment_indices,
        slice_unit="morpheme",
        provenance=CognateMembershipProvenance(
            dataset_id="synthetic_test",
            source_table="CognateTable",
            source_row=row,
            source_cognateset_id=cognate_set_id,
        ),
    )


def _form(
    variety_id: str,
    concept_id: str,
    segments: tuple[str, ...],
    *,
    cog_id: str | None = None,
    memberships: tuple[CognateMembership, ...] = (),
    row: int = 1,
) -> LexicalForm:
    fid = f"{variety_id}:{concept_id}"
    if memberships:
        mems = memberships
    elif cog_id is not None:
        mems = (_whole_cog_membership(fid, cog_id, segments, row=row),)
    else:
        mems = ()
    return LexicalForm(
        form_id=fid,
        variety_id=variety_id,
        concept_id=concept_id,
        segments=segments,
        cognate_set_id=cog_id if not memberships else None,
        cognate_memberships=mems,
    )


def _node_from_prompt(prompt: str) -> str:
    match = re.search(r'"node_id":\s*"([^"]+)"', prompt)
    assert match is not None, f"missing node_id in prompt: {prompt[:200]}"
    return match.group(1)


def _build_two_level_tie_payload(
    *,
    root_name: str = "proto_burmish",
    left_name: str = "maruic",
    right_name: str = "burmic",
    leaf_names: tuple[str, str, str, str] = ("a", "b", "c", "d"),
    shifted_outgroup: bool = False,
) -> WorkbenchPayload:
    """Build a 4-leaf 2-level family where `left_name` has a 1-1 `p`/`b` tie on `c01`."""
    la, lb, lc, ld = leaf_names
    c01_c = ("f", "a") if shifted_outgroup else ("p", "a")
    c01_d = ("m", "+", "f", "a") if shifted_outgroup else ("p", "a")

    def _outgroup_c01_form(var: str, segs: tuple[str, ...], row: int) -> LexicalForm:
        if "+" in segs:
            fid = f"{var}:c01"
            return _form(
                var,
                "c01",
                segs,
                memberships=(
                    _slice_cog_membership(fid, 1, "pref_m", (0,), row=row),
                    _slice_cog_membership(fid, 2, "u1", (2, 3), row=row + 1),
                ),
            )
        return _form(var, "c01", segs, cog_id="u1", row=row)

    lexicons = (
        LanguageLexicon(
            variety_id=la,
            name=la,
            forms=(
                _form(la, "c01", ("p", "a"), cog_id="u1", row=1),
                _form(la, "c02", ("k", "i"), cog_id="u2", row=2),
            ),
        ),
        LanguageLexicon(
            variety_id=lb,
            name=lb,
            forms=(
                _form(lb, "c01", ("b", "a"), cog_id="u1", row=3),
                _form(lb, "c02", ("k", "i"), cog_id="u2", row=4),
            ),
        ),
        LanguageLexicon(
            variety_id=lc,
            name=lc,
            forms=(
                _outgroup_c01_form(lc, c01_c, 5),
                _form(lc, "c02", ("k", "i"), cog_id="u2", row=7),
            ),
        ),
        LanguageLexicon(
            variety_id=ld,
            name=ld,
            forms=(
                _outgroup_c01_form(ld, c01_d, 8),
                _form(ld, "c02", ("k", "i"), cog_id="u2", row=10),
            ),
        ),
    )
    return WorkbenchPayload(
        newick=f"(({la},{lb}){left_name},({lc},{ld}){right_name}){root_name};",
        concepts=(
            ConceptMetadata(concept_id="c01", gloss="WATER"),
            ConceptMetadata(concept_id="c02", gloss="FIRE"),
        ),
        lexicons=lexicons,
    )


# ===========================================================================
# 1. `--tied-confidence-threshold` Propagation & Digest Rule
# ===========================================================================


def test_tied_confidence_threshold_propagates_to_preview_and_committed_beams() -> None:
    payload = _build_two_level_tie_payload(
        root_name="r", left_name="x", right_name="y", leaf_names=("a", "b", "c", "d")
    )
    dataset = ingest_payload(payload)

    def _run_with_threshold(threshold: float | None) -> tuple[Any, dict[str, dict[str, Any]]]:
        previews_by_node: dict[str, dict[str, Any]] = {}

        class _TieScriptedProvider:
            model = "scripted/tie-propagation"

            def complete(self, messages, tools, **kwargs):
                node = _node_from_prompt(messages[1].content)
                tool_msgs = [json.loads(m.content) for m in messages if m.role is MessageRole.TOOL]
                assert all(m["ok"] for m in tool_msgs), f"tool failed at {node}: {tool_msgs}"
                results = [m["result"] for m in tool_msgs]
                if not results:
                    return LLMMessage(
                        role=MessageRole.ASSISTANT,
                        tool_calls=(
                            LLMToolCall(
                                call_id=f"{node}-survey",
                                name="summarize_correspondences",
                                arguments={"reading": "local", "min_support": 1, "limit": 100},
                            ),
                        ),
                    )
                if len(results) == 1:
                    choices = []
                    for item in results[0]["sets"]:
                        non_null = [s for s in item["segments"] if s is not None]
                        distinct = sorted(set(non_null))
                        if len(distinct) == 1 and None not in item["segments"]:
                            choices.append(
                                {
                                    "set_id": item["set_id"],
                                    "proto_segment": distinct[0],
                                    "confidence": 1.0,
                                    "rationale": "Unanimous retention across active children.",
                                }
                            )
                        elif set(non_null) == {"p", "b"}:
                            # Deliberately pick *b as primary at 0.50 on x; at r, y has *p!
                            chosen = "b" if node == "x" else "p"
                            conf = 0.50 if node == "x" else 0.85
                            choices.append(
                                {
                                    "set_id": item["set_id"],
                                    "proto_segment": chosen,
                                    "confidence": conf,
                                    "rationale": "Hedged 1-1 labial tie at x; resolved at r.",
                                    "directionality_rationale": "Labial correspondence.",
                                }
                            )
                        else:
                            choices.append(
                                {
                                    "set_id": item["set_id"],
                                    "proto_segment": non_null[0] if non_null else None,
                                    "confidence": 0.75,
                                    "rationale": "Default choice.",
                                    "directionality_rationale": "Default direction.",
                                }
                            )
                    return LLMMessage(
                        role=MessageRole.ASSISTANT,
                        tool_calls=(
                            LLMToolCall(
                                call_id=f"{node}-preview",
                                name="test_proto_assembly",
                                arguments={"choices": choices, "residue_policy": "drop"},
                            ),
                        ),
                    )
                previews_by_node[node] = results[1]
                return LLMMessage(
                    role=MessageRole.ASSISTANT,
                    tool_calls=(
                        LLMToolCall(
                            call_id=f"{node}-commit",
                            name="commit_reconstruction",
                            arguments={
                                "node_id": node,
                                "hypothesis_id": results[1]["hypothesis_id"],
                                "anomalies": [],
                                "summary": f"Committed {node}.",
                            },
                        ),
                    ),
                )

        reconstructor = AgenticNodeReconstructor(
            AgentOrchestrator(
                _TieScriptedProvider(),
                registry=default_tool_registry(inventory_protocol="stored-hypothesis"),
                instructions=load_agent_instructions(),
                run_id="tie-test",
                configuration_sha256="tie-test-sha",
            ),
            tied_confidence_threshold=threshold,
        )
        assert reconstructor.assembler.tied_confidence_threshold == threshold
        result = ReconstructionService(reconstructor).reconstruct_family(dataset)
        return result, previews_by_node

    res_none, prev_none = _run_with_threshold(None)
    res_tied, prev_tied = _run_with_threshold(0.5)

    steps_none = {s.parent_node_id: s for s in res_none.snapshot.steps}
    steps_tied = {s.parent_node_id: s for s in res_tied.snapshot.steps}

    x_c01_none = next(d for d in steps_none["x"].output_beam.distributions if d.concept_id == "c01")
    x_c01_tied = next(d for d in steps_tied["x"].output_beam.distributions if d.concept_id == "c01")
    assert [c.segments for c in x_c01_none.candidates] == [("b", "a")]
    assert [c.segments for c in x_c01_tied.candidates] == [("b", "a"), ("p", "a")]
    assert [round(c.probability, 4) for c in x_c01_tied.candidates] == [0.5, 0.5]

    # Preview (`proto_assembly.py:assemble_node`) and committed step (`AgenticNodeReconstructor`)
    # must agree identically on output beams and assembly work!
    from cognate_reconstruction.agent.tools.proto_assembly import assemble_node
    from cognate_reconstruction.agent.schemas import ProtoInventorySpec

    x_committed_inv = res_tied.trajectories[0].committed_reconstruction
    x_ctx_tied = AgentContext(
        node_id="x",
        child_beams=steps_tied["x"].input_beams,
        child_lexicons=tuple(l for l in dataset.lexicons if l.variety_id in ("a", "b")),
        aligner=LingPyAligner(),
        tied_confidence_threshold=0.5,
    )
    preview_step_x_tied, _ = assemble_node(
        x_ctx_tied,
        ProtoInventorySpec(
            child_node_ids=x_committed_inv.request.child_node_ids,
            commitments=x_committed_inv.request.commitments,
            residue_policy=x_committed_inv.request.residue_policy,
        ),
        node_id="x",
        segmentation_overlay_id=None,
    )
    assert preview_step_x_tied.output_beam.model_dump(mode="json") == steps_tied[
        "x"
    ].output_beam.model_dump(mode="json")
    assert prev_none["r"]["work"]["candidate_tuples"] == 2
    assert prev_tied["r"]["work"]["candidate_tuples"] == 3

    # At root `r`, tied-beam retention at `x` lets `x`'s `("p", "a")` candidate match `y`'s `("p", "a")`
    # via unanimous identity `<p : p> -> *p` at confidence 1.0!
    r_c01_none = next(d for d in steps_none["r"].output_beam.distributions if d.concept_id == "c01")
    r_c01_tied = next(d for d in steps_tied["r"].output_beam.distributions if d.concept_id == "c01")
    assert r_c01_tied.candidates[0].segments == ("p", "a")
    assert r_c01_tied.candidates[0].probability > r_c01_none.candidates[0].probability or (
        len(steps_tied["r"].output_beam.distributions) == 2
    )


def test_tied_confidence_threshold_cli_validation_and_digest_invariance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "offline-dummy-key")
    base_argv = [
        "infer",
        "--input",
        str(tmp_path / "in.json"),
        "--preset",
        "gemini",
        "--model",
        "gemini-3.8-flash",
        "--reasoning-effort",
        "medium",
        "--no-preflight",
    ]
    parser = cli._parser()

    args_default = parser.parse_args(base_argv)
    assert args_default.tied_confidence_threshold is None
    _, sha_default, settings_default, components_default = cli._provider_and_configuration(
        args_default
    )
    assert "tied_confidence_threshold" not in settings_default

    # Removing the attribute altogether produces the exact same SHA-256 (bit-for-bit backward compat)
    delattr(args_default, "tied_confidence_threshold")
    _, sha_legacy, settings_legacy, components_legacy = cli._provider_and_configuration(
        args_default
    )
    assert sha_default == sha_legacy
    assert settings_default == settings_legacy
    assert components_default == components_legacy

    # Setting 0.5 or 0.0 includes the key and changes `configuration_sha256`
    args_half = parser.parse_args([*base_argv, "--tied-confidence-threshold", "0.5"])
    _, sha_half, settings_half, _ = cli._provider_and_configuration(args_half)
    assert settings_half["tied_confidence_threshold"] == 0.5
    assert sha_half != sha_default

    args_zero = parser.parse_args([*base_argv, "--tied-confidence-threshold", "0.0"])
    _, sha_zero, settings_zero, _ = cli._provider_and_configuration(args_zero)
    assert settings_zero["tied_confidence_threshold"] == 0.0
    assert sha_zero != sha_default
    assert sha_zero != sha_half

    # Direct `assemble_node` with `0.0` maps cleanly without tripping `ProtoInventoryAssembler`
    aligner = LingPyAligner()
    payload = _build_two_level_tie_payload()
    ctx_zero = AgentContext(
        node_id="maruic",
        child_lexicons=tuple(l for l in payload.lexicons if l.variety_id in ("a", "b")),
        aligner=aligner,
        tied_confidence_threshold=0.0,
    )
    assert ctx_zero.tied_confidence_threshold == 0.0

    for bad_val in ("-0.1", "1.0", "1.25", "nan", "inf"):
        bad_args = parser.parse_args([*base_argv, "--tied-confidence-threshold", bad_val])
        with pytest.raises(ValueError, match="tied-confidence-threshold"):
            cli._provider_and_configuration(bad_args)


# ===========================================================================
# 2. `audit_run_directory` & `tools/hypothesis_critic_probe.py audit-run`
# ===========================================================================


def _execute_offline_family_run(
    run_dir: Path,
    payload: WorkbenchPayload,
    provider: Any,
    *,
    stop_after_node: str | None = None,
    tied_confidence_threshold: float | None = 0.5,
    max_failed_nodes: int = 0,
    run_id: str = "audit-test-run",
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    input_path = run_dir / "input.payload.json"
    input_text = payload.model_dump_json(indent=2) + "\n"
    input_path.write_text(input_text, encoding="utf-8")

    dataset = ingest_payload(payload)
    checkpoint_store = CheckpointStore(run_dir / "checkpoint.json")
    checkpoint = FamilyCheckpoint(
        run_id=run_id,
        input_sha256=cli._hash_text(input_text),
        configuration_sha256=f"cfg-{run_id}",
        normalized_tree_sha256=cli._hash_text(dataset.tree.newick),
    )
    checkpoint_store.save(checkpoint)

    orchestrator = AgentOrchestrator(
        provider,
        registry=default_tool_registry(inventory_protocol="stored-hypothesis"),
        trajectory_sink=JsonlTrajectorySink(run_dir / "trajectories.jsonl"),
        instructions=load_agent_instructions(),
        run_id=run_id,
        configuration_sha256=f"cfg-{run_id}",
        max_turns=12,
        max_tool_calls=24,
    )
    service = ReconstructionService(
        AgenticNodeReconstructor(
            orchestrator,
            fail_fast=(max_failed_nodes == 0),
            max_failed_nodes=max_failed_nodes,
            tied_confidence_threshold=tied_confidence_threshold,
        )
    )

    def _on_step(step) -> None:
        nonlocal checkpoint
        checkpoint = checkpoint.with_step(step)
        checkpoint_store.save(checkpoint)

    try:
        result = service.reconstruct_family(
            dataset,
            on_step_complete=_on_step,
            stop_after_node=stop_after_node,
        )
    except PlannedStop:
        (run_dir / "run_summary.json").write_text(
            json.dumps(
                {**service.last_run_summary, "stop_after_node": stop_after_node},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return
    except Exception:
        if service.last_run_summary is not None:
            (run_dir / "run_summary.json").write_text(
                json.dumps(service.last_run_summary, indent=2) + "\n",
                encoding="utf-8",
            )
        return

    (run_dir / "result.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8"
    )
    (run_dir / "run_summary.json").write_text(
        json.dumps(service.last_run_summary, indent=2) + "\n", encoding="utf-8"
    )


class _CleanComparativeProvider:
    """Inspects outgroups on non-root nodes, keeps identity at 1.0, and commits cleanly."""

    model = "scripted/clean-comparative"

    def complete(self, messages, tools, **kwargs):
        node = _node_from_prompt(messages[1].content)
        tool_msgs = [json.loads(m.content) for m in messages if m.role is MessageRole.TOOL]
        assert all(m["ok"] for m in tool_msgs), f"tool error at {node}: {tool_msgs}"
        results = [m["result"] for m in tool_msgs]

        if len(results) == 0:
            return LLMMessage(
                role=MessageRole.ASSISTANT,
                tool_calls=(
                    LLMToolCall(
                        call_id=f"{node}-search",
                        name="search_forms",
                        arguments={"scope": "available_tree", "limit": 50},
                    ),
                ),
            )
        if len(results) == 1:
            return LLMMessage(
                role=MessageRole.ASSISTANT,
                tool_calls=(
                    LLMToolCall(
                        call_id=f"{node}-survey",
                        name="summarize_correspondences",
                        arguments={"reading": "local", "min_support": 1, "limit": 100},
                    ),
                ),
            )
        if len(results) == 2:
            choices = []
            for item in results[1]["sets"]:
                segs = item["segments"]
                non_null = [s for s in segs if s is not None]
                if None not in segs and len(set(non_null)) == 1:
                    choices.append(
                        {
                            "set_id": item["set_id"],
                            "proto_segment": non_null[0],
                            "confidence": 1.0,
                            "rationale": "Unanimous retention.",
                        }
                    )
                else:
                    proto = "p" if "p" in non_null or "f" in non_null else non_null[0]
                    choices.append(
                        {
                            "set_id": item["set_id"],
                            "proto_segment": proto,
                            "confidence": 0.85,
                            "rationale": (
                                "Outgroup shifted reflex *p > f inspected in available_tree."
                                if not node.startswith("proto_")
                                else "Root comparative reconstruction across both primary branches."
                            ),
                            "directionality_rationale": "Lenition *p > b / *p > f.",
                        }
                    )
            return LLMMessage(
                role=MessageRole.ASSISTANT,
                tool_calls=(
                    LLMToolCall(
                        call_id=f"{node}-preview",
                        name="test_proto_assembly",
                        arguments={
                            "choices": choices,
                            "residue_policy": "retain_from_witness",
                            "residue_witness_child_id": results[1]["node_ids"][0],
                        },
                    ),
                ),
            )
        return LLMMessage(
            role=MessageRole.ASSISTANT,
            tool_calls=(
                LLMToolCall(
                    call_id=f"{node}-commit",
                    name="commit_reconstruction",
                    arguments={
                        "node_id": node,
                        "hypothesis_id": results[2]["hypothesis_id"],
                        "anomalies": [],
                        "summary": f"Clean reconstruction at {node}.",
                    },
                ),
            ),
        )


@pytest.mark.parametrize(
    ("root_name", "left_name", "right_name", "leaves"),
    [
        ("proto_burmish", "maruic", "burmic", ("atsi", "maru", "achang", "rangoon")),
        (
            "proto_polynesian",
            "tongic",
            "nuclear_polynesian",
            ("tongan", "niuean", "samoan", "maori"),
        ),
    ],
)
def test_audit_run_directory_zero_false_positives_on_two_child_roots_and_shifted_outgroups(
    tmp_path: Path,
    root_name: str,
    left_name: str,
    right_name: str,
    leaves: tuple[str, str, str, str],
) -> None:
    payload = _build_two_level_tie_payload(
        root_name=root_name,
        left_name=left_name,
        right_name=right_name,
        leaf_names=leaves,
        shifted_outgroup=True,
    )

    # 1. Planned-stop checkpoint run (`--stop-after-node <left_name>`)
    stop_dir = tmp_path / f"{root_name}_planned_stop"
    _execute_offline_family_run(
        stop_dir,
        payload,
        _CleanComparativeProvider(),
        stop_after_node=left_name,
    )
    assert not (stop_dir / "result.json").exists()
    stop_audit = audit_run_directory(stop_dir, payload=payload)
    assert stop_audit["audit_mode"] == REAL_RUN_AUDIT_MODE
    assert stop_audit["run_status"] == "planned_stop"
    assert stop_audit["nodes_audited"] == [left_name]
    assert stop_audit["total_defect_count"] == 0

    # 2. Full completed run including 2-child root with 0 external outgroups
    full_dir = tmp_path / f"{root_name}_completed"
    _execute_offline_family_run(full_dir, payload, _CleanComparativeProvider())
    assert (full_dir / "result.json").exists()
    full_audit = audit_run_directory(full_dir, payload=payload)
    assert full_audit["run_status"] == "completed"
    assert set(full_audit["nodes_audited"]) == {left_name, right_name, root_name}
    assert full_audit["nodes"][root_name]["is_root"] is True
    assert full_audit["nodes"][root_name]["defect_count"] == 0
    assert full_audit["total_defect_count"] == 0

    # 3. CLI `tools/hypothesis_critic_probe.py audit-run` round-trip
    out_json = tmp_path / f"{root_name}_audit_cli.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/hypothesis_critic_probe.py"),
            "audit-run",
            "--run-dir",
            str(full_dir),
            "--definition",
            str(full_dir / "input.payload.json"),
            "--output",
            str(out_json),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    cli_report = json.loads(proc.stdout)
    assert out_json.exists()
    assert cli_report["total_defect_count"] == 0
    assert set(cli_report["defect_counts_by_category"]) == set(REAL_RUN_DEFECT_CATEGORIES)


def test_audit_run_directory_catches_all_five_real_family_defects(tmp_path: Path) -> None:
    base_payload = _build_two_level_tie_payload(
        root_name="proto_burmish",
        left_name="maruic",
        right_name="burmic",
        leaf_names=("atsi", "maru", "achang", "rangoon"),
    )

    # --- Defect 1 & 2: `silent_residue_drop_truncation` + `uninspected_outgroup_citation` ---
    class _DropAndUninspectedOutgroupProvider:
        model = "scripted/drop-and-uninspected"

        def complete(self, messages, tools, **kwargs):
            node = _node_from_prompt(messages[1].content)
            results = [
                json.loads(m.content)["result"]
                for m in messages
                if m.role is MessageRole.TOOL
            ]
            if not results:
                return LLMMessage(
                    role=MessageRole.ASSISTANT,
                    tool_calls=(
                        LLMToolCall(
                            call_id=f"{node}-survey",
                            name="summarize_correspondences",
                            arguments={"reading": "local", "min_support": 1, "limit": 100},
                        ),
                    ),
                )
            if len(results) == 1:
                # Cover ONLY the first set, omit the rest under `residue_policy="drop"`,
                # and cite outgroup `achang` without ever inspecting outgroup forms!
                first = results[0]["sets"][0]
                non_null = [s for s in first["segments"] if s is not None]
                return LLMMessage(
                    role=MessageRole.ASSISTANT,
                    tool_calls=(
                        LLMToolCall(
                            call_id=f"{node}-preview",
                            name="test_proto_assembly",
                            arguments={
                                "choices": [
                                    {
                                        "set_id": first["set_id"],
                                        "proto_segment": non_null[0],
                                        "confidence": 0.9,
                                        "rationale": "Outgroup achang corroborates retention.",
                                        "directionality_rationale": "Supported by external outgroup.",
                                    }
                                ],
                                "residue_policy": "drop",
                            },
                        ),
                    ),
                )
            return LLMMessage(
                role=MessageRole.ASSISTANT,
                tool_calls=(
                    LLMToolCall(
                        call_id=f"{node}-commit",
                        name="commit_reconstruction",
                        arguments={
                            "node_id": node,
                            "hypothesis_id": results[1]["hypothesis_id"],
                            "anomalies": [],
                            "summary": "Partial drop commit.",
                        },
                    ),
                ),
            )

    d12_dir = tmp_path / "defects_drop_and_outgroup"
    _execute_offline_family_run(
        d12_dir,
        base_payload,
        _DropAndUninspectedOutgroupProvider(),
        stop_after_node="maruic",
    )
    d12_audit = audit_run_directory(d12_dir, payload=base_payload)
    assert d12_audit["defect_counts_by_category"]["silent_residue_drop_truncation"] >= 1
    assert d12_audit["defect_counts_by_category"]["uninspected_outgroup_citation"] >= 1
    assert d12_audit["nodes"]["maruic"]["unaccounted_column_rate"] > 0.0
    assert d12_audit["nodes"]["maruic"]["uncovered_set_count"] >= 1

    # --- Defect 3: `unit_provenance_loss` (assembled output_beam emits `whole:unknown` / missing `cog:*`) ---
    d3_dir = tmp_path / "defect_unit_provenance_loss"
    _execute_offline_family_run(
        d3_dir,
        base_payload,
        _CleanComparativeProvider(),
        stop_after_node="maruic",
    )
    # Strip `cognate_set_id` to `whole:unknown` on the saved `maruic` output_beam to simulate provenance loss:
    cp_d3 = CheckpointStore(d3_dir / "checkpoint.json").load()
    maruic_step = cp_d3.steps_by_node["maruic"]
    degraded_dists = tuple(
        d.model_copy(
            update={
                "candidates": tuple(
                    c.model_copy(update={"analysis": None}) for c in d.candidates
                )
            }
        )
        for d in maruic_step.output_beam.distributions
    )
    degraded_step = maruic_step.model_copy(
        update={
            "output_beam": maruic_step.output_beam.model_copy(
                update={"distributions": degraded_dists}
            )
        }
    )
    CheckpointStore(d3_dir / "checkpoint.json").save(
        cp_d3.model_copy(update={"completed_steps": (degraded_step,)})
    )
    traj_records = list(TrajectoryDatasetBuilder.read_jsonl(d3_dir / "trajectories.jsonl"))
    (d3_dir / "trajectories.jsonl").write_text(
        "\n".join(
            t.model_copy(update={"reconstruction_step": degraded_step}).model_dump_json()
            for t in traj_records
        )
        + "\n",
        encoding="utf-8",
    )
    d3_audit = audit_run_directory(d3_dir, payload=base_payload)
    assert d3_audit["defect_counts_by_category"]["unit_provenance_loss"] >= 1

    # --- Defect 4: `identity_confidence_length_bias` ---
    # Child `maruic` has a 1-sided coda `t` vs gap tie on `c01` (`("k", "a", "t")` vs `("k", "a")`),
    # retained as 2 unequal-length candidates under `tied_confidence_threshold=0.5`, while `burmic`
    # has unanimous `("k", "a", "t")` on `c01` and all 4 leaves share `("t", "a")` on `c02` (`cog:u1`).
    # At `proto_burmish`, committing unanimous identity `<k:k>`, `<a:a>`, `<t:t>` at confidence 0.90 < 1.0
    # yields unequal-length competing candidates with unequal probabilities!
    len_payload = WorkbenchPayload(
        newick="((atsi,maru)maruic,(achang,rangoon)burmic)proto_burmish;",
        concepts=(
            ConceptMetadata(concept_id="c01", gloss="STONE"),
            ConceptMetadata(concept_id="c02", gloss="TOOTH"),
        ),
        lexicons=(
            LanguageLexicon(
                variety_id="atsi",
                name="atsi",
                forms=(
                    _form("atsi", "c01", ("k", "a", "t"), cog_id="u1", row=1),
                    _form("atsi", "c02", ("t", "a"), cog_id="u1", row=2),
                ),
            ),
            LanguageLexicon(
                variety_id="maru",
                name="maru",
                forms=(
                    _form("maru", "c01", ("k", "a"), cog_id="u1", row=3),
                    _form("maru", "c02", ("t", "a"), cog_id="u1", row=4),
                ),
            ),
            LanguageLexicon(
                variety_id="achang",
                name="achang",
                forms=(
                    _form("achang", "c01", ("k", "a", "t"), cog_id="u1", row=5),
                    _form("achang", "c02", ("t", "a"), cog_id="u1", row=6),
                ),
            ),
            LanguageLexicon(
                variety_id="rangoon",
                name="rangoon",
                forms=(
                    _form("rangoon", "c01", ("k", "a", "t"), cog_id="u1", row=7),
                    _form("rangoon", "c02", ("t", "a"), cog_id="u1", row=8),
                ),
            ),
        ),
    )

    class _IdentityLengthBiasProvider:
        model = "scripted/length-bias"

        def complete(self, messages, tools, **kwargs):
            node = _node_from_prompt(messages[1].content)
            results = [
                json.loads(m.content)["result"]
                for m in messages
                if m.role is MessageRole.TOOL
            ]
            if not results:
                return LLMMessage(
                    role=MessageRole.ASSISTANT,
                    tool_calls=(
                        LLMToolCall(
                            call_id=f"{node}-survey",
                            name="summarize_correspondences",
                            arguments={"reading": "local", "min_support": 1, "limit": 100},
                        ),
                    ),
                )
            if len(results) == 1:
                choices = []
                for item in results[0]["sets"]:
                    segs = item["segments"]
                    non_null = [s for s in segs if s is not None]
                    if None not in segs and len(set(non_null)) == 1:
                        # At root `proto_burmish`, commit unanimous identity at 0.90 (< 1.0)!
                        conf = 0.90 if node == "proto_burmish" else 1.0
                        choices.append(
                            {
                                "set_id": item["set_id"],
                                "proto_segment": non_null[0],
                                "confidence": conf,
                                "rationale": "Identity retention.",
                                "directionality_rationale": "Retained proto-segment across branches.",
                            }
                        )
                    else:
                        proto = None if node == "proto_burmish" else non_null[0]
                        choices.append(
                            {
                                "set_id": item["set_id"],
                                "proto_segment": proto,
                                "confidence": 0.50,
                                "rationale": "One-sided coda tie.",
                                "directionality_rationale": "Coda retention vs loss tie.",
                            }
                        )
                return LLMMessage(
                    role=MessageRole.ASSISTANT,
                    tool_calls=(
                        LLMToolCall(
                            call_id=f"{node}-preview",
                            name="test_proto_assembly",
                            arguments={"choices": choices, "residue_policy": "drop"},
                        ),
                    ),
                )
            return LLMMessage(
                role=MessageRole.ASSISTANT,
                tool_calls=(
                    LLMToolCall(
                        call_id=f"{node}-commit",
                        name="commit_reconstruction",
                        arguments={
                            "node_id": node,
                            "hypothesis_id": results[1]["hypothesis_id"],
                            "anomalies": [],
                            "summary": f"Committed {node}.",
                        },
                    ),
                ),
            )

    d4_dir = tmp_path / "defect_identity_length_bias"
    _execute_offline_family_run(
        d4_dir,
        len_payload,
        _IdentityLengthBiasProvider(),
        tied_confidence_threshold=0.5,
    )
    d4_audit = audit_run_directory(d4_dir, payload=len_payload)
    assert d4_audit["defect_counts_by_category"]["identity_confidence_length_bias"] >= 1, d4_audit
    assert d4_audit["nodes"]["proto_burmish"]["defect_count"] >= 1

    # --- Defect 5: `upstream_tie_collapse_majority` ---
    # Run `base_payload` with `tied_confidence_threshold=None` so `maruic`'s `p`/`b` tie at 0.50
    # collapses to single-winner `*b`, and `proto_burmish` commits `<b : p> -> *b` at confidence 0.85!
    class _UpstreamTieCollapseProvider:
        model = "scripted/tie-collapse"

        def complete(self, messages, tools, **kwargs):
            node = _node_from_prompt(messages[1].content)
            results = [
                json.loads(m.content)["result"]
                for m in messages
                if m.role is MessageRole.TOOL
            ]
            if not results:
                return LLMMessage(
                    role=MessageRole.ASSISTANT,
                    tool_calls=(
                        LLMToolCall(
                            call_id=f"{node}-survey",
                            name="summarize_correspondences",
                            arguments={"reading": "local", "min_support": 1, "limit": 100},
                        ),
                    ),
                )
            if len(results) == 1:
                choices = []
                for item in results[0]["sets"]:
                    segs = item["segments"]
                    non_null = [s for s in segs if s is not None]
                    if None not in segs and len(set(non_null)) == 1:
                        choices.append(
                            {
                                "set_id": item["set_id"],
                                "proto_segment": non_null[0],
                                "confidence": 1.0,
                                "rationale": "Unanimous retention.",
                            }
                        )
                    elif node == "maruic":
                        choices.append(
                            {
                                "set_id": item["set_id"],
                                "proto_segment": "b",
                                "confidence": 0.50,
                                "rationale": "1-1 tie hedged at 0.50.",
                                "directionality_rationale": "Unpolarized labial tie.",
                            }
                        )
                    else:
                        choices.append(
                            {
                                "set_id": item["set_id"],
                                "proto_segment": "b",
                                "confidence": 0.85,
                                "rationale": "Confident root claim built on collapsed child tie.",
                                "directionality_rationale": "Assumed *b > p.",
                            }
                        )
                return LLMMessage(
                    role=MessageRole.ASSISTANT,
                    tool_calls=(
                        LLMToolCall(
                            call_id=f"{node}-preview",
                            name="test_proto_assembly",
                            arguments={"choices": choices, "residue_policy": "drop"},
                        ),
                    ),
                )
            return LLMMessage(
                role=MessageRole.ASSISTANT,
                tool_calls=(
                    LLMToolCall(
                        call_id=f"{node}-commit",
                        name="commit_reconstruction",
                        arguments={
                            "node_id": node,
                            "hypothesis_id": results[1]["hypothesis_id"],
                            "anomalies": [],
                            "summary": f"Committed {node}.",
                        },
                    ),
                ),
            )

    d5_dir = tmp_path / "defect_upstream_tie_collapse"
    _execute_offline_family_run(
        d5_dir,
        base_payload,
        _UpstreamTieCollapseProvider(),
        tied_confidence_threshold=None,
    )
    d5_audit = audit_run_directory(d5_dir, payload=base_payload)
    assert d5_audit["defect_counts_by_category"]["upstream_tie_collapse_majority"] >= 1


# ===========================================================================
# 3. `--compaction-watermark-tokens` (Prefix Cache, Handles, Rejections, Repeat Guard)
# ===========================================================================


def test_watermark_compaction_preserves_prefix_cache_below_watermark_and_digest_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "offline-dummy-key")
    base_argv = [
        "infer",
        "--input",
        str(tmp_path / "in.json"),
        "--preset",
        "gemini",
        "--model",
        "gemini-3.8-flash",
        "--reasoning-effort",
        "medium",
        "--no-preflight",
    ]
    parser = cli._parser()

    args_none = parser.parse_args(base_argv)
    assert args_none.compaction_watermark_tokens is None
    _, sha_none, settings_none, _ = cli._provider_and_configuration(args_none)
    assert "compaction_watermark_tokens" not in settings_none

    for wm in (256_000, 96_000):
        args_wm = parser.parse_args([*base_argv, "--compaction-watermark-tokens", str(wm)])
        _, sha_wm, settings_wm, _ = cli._provider_and_configuration(args_wm)
        assert settings_wm["compaction_watermark_tokens"] == wm
        assert sha_wm != sha_none

    for bad_wm in ("0", "4096", "8191", "-100"):
        args_bad = parser.parse_args([*base_argv, "--compaction-watermark-tokens", bad_wm])
        with pytest.raises(ValueError, match="compaction-watermark-tokens"):
            cli._provider_and_configuration(args_bad)

    # Below watermark (`256000`), earlier `test_proto_assembly` tool results in `messages`
    # must stay 100% byte-identical across turns (zero prefix mutation!).
    payload = _build_two_level_tie_payload()
    ctx = AgentContext(
        node_id="maruic",
        child_lexicons=tuple(l for l in payload.lexicons if l.variety_id in ("a", "b")),
        aligner=LingPyAligner(),
    )
    observed_prompts: list[list[dict[str, Any]]] = []

    class _BelowWatermarkProvider:
        model = "scripted/below-watermark"

        def complete(self, messages, tools, **kwargs):
            observed_prompts.append([m.model_dump(mode="json") for m in messages])
            turn = len(observed_prompts)
            if turn == 1:
                call = LLMToolCall(
                    call_id="survey-1",
                    name="summarize_correspondences",
                    arguments={"reading": "local", "min_support": 1, "limit": 50},
                )
            elif turn in (2, 3):
                survey = json.loads(messages[3].content)["result"]
                conf = 0.60 if turn == 2 else 0.70
                choices = [
                    {
                        "set_id": s["set_id"],
                        "proto_segment": s["segments"][0],
                        "confidence": conf,
                        "rationale": f"Draft {turn}.",
                        "directionality_rationale": "Draft polarity.",
                    }
                    for s in survey["sets"]
                ]
                call = LLMToolCall(
                    call_id=f"prev-{turn}",
                    name="test_proto_assembly",
                    arguments={"choices": choices, "residue_policy": "drop"},
                )
            else:
                latest_prev = json.loads(messages[-1].content)["result"]
                call = LLMToolCall(
                    call_id="commit-final",
                    name="commit_reconstruction",
                    arguments={
                        "node_id": "maruic",
                        "hypothesis_id": latest_prev["hypothesis_id"],
                        "anomalies": [],
                        "summary": "Done.",
                    },
                )
            return ProviderResponse(
                message=LLMMessage(role=MessageRole.ASSISTANT, tool_calls=(call,)),
                metadata=ProviderResponseMetadata(
                    provider_id="fake",
                    model_id=self.model,
                    usage=ProviderUsage(input_tokens=4_000, output_tokens=200, total_tokens=4_200),
                ),
            )

    orch = AgentOrchestrator(
        _BelowWatermarkProvider(),
        registry=default_tool_registry(inventory_protocol="stored-hypothesis"),
        instructions=load_agent_instructions(),
        compaction_watermark_tokens=256_000,
    )
    run_res = orch.run(ctx)
    traj = run_res.trajectory
    assert traj.completed is True
    assert traj.metrics.compacted_tool_results == 0
    assert orch.compaction_summary()["watermark_trigger_count"] == 0
    # Prefix of Turn 3 must match Turn 4's prefix byte-for-byte!
    assert observed_prompts[3][: len(observed_prompts[2])] == observed_prompts[2]


def test_watermark_compaction_stubs_older_previews_preserves_handles_rejections_repeat_guard_and_audit(
    tmp_path: Path,
) -> None:
    payload = _build_two_level_tie_payload()
    ctx = AgentContext(
        node_id="maruic",
        child_lexicons=tuple(l for l in payload.lexicons if l.variety_id in ("a", "b")),
        aligner=LingPyAligner(),
        tied_confidence_threshold=0.5,
    )
    traj_path = tmp_path / "trajectories.jsonl"
    observed_prompts: list[list[LLMMessage]] = []
    saved_prev1_choices: list[dict[str, Any]] = []
    saved_prev1_hyp_id: str | None = None

    class _AboveWatermarkProvider:
        model = "scripted/above-watermark"

        def complete(self, messages, tools, **kwargs):
            nonlocal saved_prev1_hyp_id
            observed_prompts.append(list(messages))
            turn = len(observed_prompts)

            if turn == 1:
                in_tok = 100  # below watermark (300)
                call = LLMToolCall(
                    call_id="survey-1",
                    name="summarize_correspondences",
                    arguments={"reading": "local", "min_support": 1, "limit": 50},
                )
            elif turn == 2:
                in_tok = 200  # still below watermark (300)
                survey = json.loads(messages[-1].content)["result"]
                for s in survey["sets"]:
                    saved_prev1_choices.append(
                        {
                            "set_id": s["set_id"],
                            "proto_segment": s["segments"][0],
                            "confidence": 0.50 if len(set(s["segments"])) > 1 else 1.0,
                            "rationale": "First accepted preview.",
                            "directionality_rationale": "Initial tie reading.",
                        }
                    )
                call = LLMToolCall(
                    call_id="prev-1",
                    name="test_proto_assembly",
                    arguments={"choices": saved_prev1_choices, "residue_policy": "drop"},
                )
            elif turn == 3:
                in_tok = 250  # still below watermark; capture `prev-1` hypothesis_id!
                saved_prev1_hyp_id = json.loads(messages[-1].content)["result"]["hypothesis_id"]
                # Submit an invalid preview (`ok=false`) that MUST NEVER be compacted
                call = LLMToolCall(
                    call_id="prev-bad",
                    name="test_proto_assembly",
                    arguments={
                        "choices": [
                            {
                                "set_id": "csu-nonexistent-id",
                                "proto_segment": "p",
                                "confidence": 0.9,
                                "rationale": "Invalid set_id.",
                            }
                        ],
                        "residue_policy": "drop",
                    },
                )
            elif turn == 4:
                in_tok = 450  # CROSSES WATERMARK (>= 300)!
                # Submit second accepted preview (`prev-2`), superseding `prev-1`
                choices_2 = [
                    {**c, "proto_segment": "b"} if c["confidence"] == 0.50 else dict(c)
                    for c in saved_prev1_choices
                ]
                call = LLMToolCall(
                    call_id="prev-2",
                    name="test_proto_assembly",
                    arguments={"choices": choices_2, "residue_policy": "drop"},
                )
            elif turn == 5:
                in_tok = 380
                # Re-submit IDENTICAL arguments to already-compacted `prev-1` -> triggers repeat guard!
                call = LLMToolCall(
                    call_id="prev-1-repeat",
                    name="test_proto_assembly",
                    arguments={
                        "residue_policy": "drop",
                        "choices": list(saved_prev1_choices),
                    },
                )
            elif turn == 6:
                in_tok = 390
                # Commit by `prev-1`'s handle (`saved_prev1_hyp_id`) even though `prev-1` was compacted!
                assert saved_prev1_hyp_id is not None
                call = LLMToolCall(
                    call_id="commit-by-compacted-handle",
                    name="commit_reconstruction",
                    arguments={
                        "node_id": "maruic",
                        "hypothesis_id": saved_prev1_hyp_id,
                        "anomalies": [],
                        "summary": "Committed using earlier compacted preview handle.",
                    },
                )
            else:
                raise AssertionError(f"unexpected extra turn {turn}")

            return ProviderResponse(
                message=LLMMessage(role=MessageRole.ASSISTANT, tool_calls=(call,)),
                metadata=ProviderResponseMetadata(
                    provider_id="fake",
                    model_id=self.model,
                    usage=ProviderUsage(input_tokens=in_tok, output_tokens=80, total_tokens=in_tok + 80),
                ),
            )

    orch = AgentOrchestrator(
        _AboveWatermarkProvider(),
        registry=default_tool_registry(inventory_protocol="stored-hypothesis"),
        trajectory_sink=JsonlTrajectorySink(traj_path),
        instructions=load_agent_instructions(),
        compaction_watermark_tokens=300,
    )
    reconstructor = AgenticNodeReconstructor(
        orch,
        tied_confidence_threshold=0.5,
    )
    child_beams = tuple(
        make_leaf_beam(l, beam_width=5)
        for l in payload.lexicons
        if l.variety_id in ("a", "b")
    )
    reconstructor.reconstruct("maruic", child_beams)
    traj = reconstructor.trajectories[0]
    assert traj.completed is True

    # Inspect prompt messages seen by the model on Turn 6 (final turn):
    final_prompt_tools = {
        m.tool_call_id: json.loads(m.content)
        for m in observed_prompts[-1]
        if m.role is MessageRole.TOOL
    }
    # 1) `prev-1` was compacted into a deterministic stub with all required fields & handles:
    stub = final_prompt_tools["prev-1"]
    assert stub["compacted"] is True
    assert stub["tool"] == "test_proto_assembly"
    assert stub["call_id"] == "prev-1"
    assert isinstance(stub["argument_sha256"], str) and len(stub["argument_sha256"]) == 64
    assert stub["validation_id"] == "prev-1"
    assert stub["inventory_id"] == saved_prev1_hyp_id
    assert stub["hypothesis_id"] == saved_prev1_hyp_id
    assert stub["executable"] is True
    assert stub["commit_ready"] is True
    assert stub["covered_set_count"] >= 1
    assert stub["unaccounted_column_rate"] == 0.0
    assert stub["superseded_by"] == "prev-2"
    assert "concepts" not in stub

    # 2) Rejected call (`prev-bad`, `ok=false`) remained 100% verbatim!
    prev_bad_prompt = final_prompt_tools["prev-bad"]
    assert prev_bad_prompt["ok"] is False
    assert "compacted" not in prev_bad_prompt
    assert "unknown or nonlocal" in prev_bad_prompt["error"]["message"]

    # 3) Newest accepted preview (`prev-2`) remained 100% verbatim!
    prev2_prompt = final_prompt_tools["prev-2"]
    assert prev2_prompt["ok"] is True
    assert "compacted" not in prev2_prompt["result"]
    assert "concepts" in prev2_prompt["result"]

    # 4) Repeat call (`prev-1-repeat`) returned deterministic repeat-call guard notice!
    repeat_prompt = final_prompt_tools["prev-1-repeat"]
    assert repeat_prompt["ok"] is True
    assert repeat_prompt["result"]["repeat_guard"] is True
    assert repeat_prompt["result"]["identical_to_call_id"] == "prev-1"
    assert repeat_prompt["result"]["argument_sha256"] == stub["argument_sha256"]
    assert repeat_prompt["result"]["inventory_id"] == saved_prev1_hyp_id

    # 5) Orchestrator compaction summary & node metrics recorded exact counts:
    comp_summary = orch.compaction_summary()
    assert comp_summary["compaction_watermark_tokens"] == 300
    assert comp_summary["watermark_trigger_count"] >= 1
    assert comp_summary["compacted_preview_results"] == 1
    assert comp_summary["repeat_guard_hits"] == 1
    assert traj.metrics.compacted_tool_results == 1

    # 6) `_MessageLog.audit` (`trajectories.jsonl`) is 100% UNCOMPACTED!
    saved_trajs = list(TrajectoryDatasetBuilder.read_jsonl(traj_path))
    assert len(saved_trajs) == 1
    audit_tools = {
        m.tool_call_id: json.loads(m.content)
        for m in saved_trajs[0].messages
        if m.role is MessageRole.TOOL
    }
    assert "compacted" not in audit_tools["prev-1"]["result"]
    assert "concepts" in audit_tools["prev-1"]["result"]


def test_watermark_compaction_char_fallback_and_rule_cascade_handles(tmp_path: Path) -> None:
    payload = _build_two_level_tie_payload()
    ctx = AgentContext(
        node_id="maruic",
        child_lexicons=tuple(l for l in payload.lexicons if l.variety_id in ("a", "b")),
        aligner=LingPyAligner(),
    )
    traj_path = tmp_path / "rule_trajectories.jsonl"
    observed_prompts: list[list[LLMMessage]] = []

    class _CharFallbackRuleProvider:
        model = "scripted/char-fallback-rules"

        def complete(self, messages, tools, **kwargs):
            observed_prompts.append(list(messages))
            turn = len(observed_prompts)
            if turn == 1:
                call = LLMToolCall(
                    call_id="search-1",
                    name="search_forms",
                    arguments={"scope": "active_children", "limit": 20},
                )
            elif turn == 2:
                call = LLMToolCall(
                    call_id="law-1",
                    name="test_sound_law",
                    arguments={"source_child_ids": ["b"], "dsl": "b > p"},
                )
            elif turn == 3:
                call = LLMToolCall(
                    call_id="law-2",
                    name="test_sound_law",
                    arguments={"source_child_ids": ["a"], "dsl": "p > b"},
                )
            elif turn == 4:
                call = LLMToolCall(
                    call_id="casc-1",
                    name="test_rule_cascade",
                    arguments={"rules": [{"source_child_ids": ["b"], "dsl": "b > p"}]},
                )
            elif turn == 5:
                call = LLMToolCall(
                    call_id="casc-2",
                    name="test_rule_cascade",
                    arguments={"rules": [{"source_child_ids": ["a"], "dsl": "p > b"}]},
                )
            else:
                # Commit the rule cascade tested in compacted `casc-1`!
                call = LLMToolCall(
                    call_id="commit-rules",
                    name="commit_reconstruction",
                    arguments={
                        "node_id": "maruic",
                        "rules": [
                            {
                                "source_child_ids": ["b"],
                                "dsl": "b > p",
                                "confidence": 0.8,
                                "rationale": "Voicing in b.",
                                "directionality_rationale": "Lenition *p > b.",
                            }
                        ],
                        "anomalies": [],
                        "summary": "Rule commit validated by compacted casc-1.",
                    },
                )
            # `usage=None` forces `len(json_bytes) // 3` conservative token estimate!
            return ProviderResponse(
                message=LLMMessage(role=MessageRole.ASSISTANT, tool_calls=(call,)),
                metadata=ProviderResponseMetadata(provider_id="fake", model_id=self.model, usage=None),
            )

    orch = AgentOrchestrator(
        _CharFallbackRuleProvider(),
        registry=default_tool_registry(inventory_protocol="stored-hypothesis"),
        trajectory_sink=JsonlTrajectorySink(traj_path),
        instructions=load_agent_instructions(),
        compaction_watermark_tokens=200,
    )
    run_res = orch.run(ctx)
    traj = run_res.trajectory
    assert traj.completed is True

    final_tools = {
        m.tool_call_id: json.loads(m.content)
        for m in observed_prompts[-1]
        if m.role is MessageRole.TOOL
    }
    assert final_tools["law-1"]["compacted"] is True
    assert final_tools["law-1"]["superseded_by"] == "law-2"
    assert final_tools["casc-1"]["compacted"] is True
    assert final_tools["casc-1"]["validation_id"] == "casc-1"
    assert final_tools["casc-1"]["superseded_by"] == "casc-2"
    assert "compacted" not in final_tools["casc-2"]


# ===========================================================================
# 4. Offline `B02` Stage 1 (`--stop-after-node`) -> Gate -> Stage 2 (`--resume`) Rehearsal
# ===========================================================================


def _build_tonal_burmish_rehearsal_payload() -> WorkbenchPayload:
    """Compact tone-bearing Burmish-shaped family (`maruic`, `burmic`, `proto_burmish`).

    Daughters carry surface contour tones (`⁵⁵`, `³¹`), while `OldBurmese` (`burmic`
    provisional proxy) and `ProtoBurmish` (`proto_burmish` validated target) carry
    abstract tone-category labels (`¹`, `²`), exercising full-form tone preservation
    and `R06` `compute_corpus_contrast_equivalence` (`corpus_bcubed_f1 = 1.0`,
    `is_bijective_relabelling = True`). Also includes a 1-1 labial tie (`p` vs `b`)
    at `maruic` so counterfactual replay (`None` vs `0.5`) shows a real beam delta!
    """
    concepts = (
        ConceptMetadata(concept_id="c01", gloss="WATER"),
        ConceptMetadata(concept_id="c02", gloss="FIRE"),
        ConceptMetadata(concept_id="c03", gloss="MOON"),
    )
    lexicons = (
        LanguageLexicon(
            variety_id="hillburmish:Atsi",
            name="Atsi",
            forms=(
                _form("hillburmish:Atsi", "c01", ("p", "a", "⁵⁵"), cog_id="cog1", row=1),
                _form("hillburmish:Atsi", "c02", ("m", "i", "³¹"), cog_id="cog2", row=2),
                _form("hillburmish:Atsi", "c03", ("l", "a", "⁵⁵"), cog_id="cog3", row=3),
            ),
        ),
        LanguageLexicon(
            variety_id="hillburmish:Maru",
            name="Maru",
            forms=(
                _form("hillburmish:Maru", "c01", ("b", "a", "⁵⁵"), cog_id="cog1", row=4),
                _form("hillburmish:Maru", "c02", ("m", "i", "³¹"), cog_id="cog2", row=5),
                _form("hillburmish:Maru", "c03", ("l", "a", "⁵⁵"), cog_id="cog3", row=6),
            ),
        ),
        LanguageLexicon(
            variety_id="hillburmish:AchangLongchuan",
            name="Achang",
            forms=(
                _form(
                    "hillburmish:AchangLongchuan", "c01", ("p", "a", "⁵⁵"), cog_id="cog1", row=7
                ),
                _form(
                    "hillburmish:AchangLongchuan", "c02", ("m", "i", "³¹"), cog_id="cog2", row=8
                ),
                _form(
                    "hillburmish:AchangLongchuan", "c03", ("l", "a", "⁵⁵"), cog_id="cog3", row=9
                ),
            ),
        ),
        LanguageLexicon(
            variety_id="hillburmish:Rangoon",
            name="Rangoon",
            forms=(
                _form("hillburmish:Rangoon", "c01", ("p", "a", "⁵⁵"), cog_id="cog1", row=10),
                _form("hillburmish:Rangoon", "c02", ("m", "i", "³¹"), cog_id="cog2", row=11),
                _form("hillburmish:Rangoon", "c03", ("l", "a", "⁵⁵"), cog_id="cog3", row=12),
            ),
        ),
    )
    bindings = (
        HistoricalFormBinding(
            source_variety_id="hillburmish:OldBurmese",
            node_id="burmic",
            role=HistoricalFormRole.TARGET,
            gold_evidence_kind=GoldEvidenceKind.ATTESTED,
            target_validity=TargetValidity.PROVISIONAL_PROXY,
            target_validity_note="Old Burmese proxy target with tones preserved.",
            forms=(
                _form("burmic", "c01", ("p", "a", "¹"), row=13),
                _form("burmic", "c02", ("m", "i", "²"), row=14),
            ),
        ),
        HistoricalFormBinding(
            source_variety_id="hillburmish:ProtoBurmish",
            node_id="proto_burmish",
            role=HistoricalFormRole.TARGET,
            gold_evidence_kind=GoldEvidenceKind.RECONSTRUCTED,
            target_validity=TargetValidity.VALIDATED,
            target_validity_note="Proto-Burmish validated root target with tones preserved.",
            forms=(
                _form("proto_burmish", "c01", ("p", "a", "¹"), row=15),
                _form("proto_burmish", "c02", ("m", "i", "²"), row=16),
                _form("proto_burmish", "c03", ("l", "a", "¹"), row=17),
            ),
        ),
    )
    return WorkbenchPayload(
        newick=(
            "(('hillburmish:Atsi','hillburmish:Maru')maruic,"
            "('hillburmish:AchangLongchuan','hillburmish:Rangoon')burmic)proto_burmish;"
        ),
        concepts=concepts,
        lexicons=lexicons,
        historical_form_bindings=bindings,
    )


def test_offline_b02_two_stage_rehearsal_ledger_and_tone_preserving_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "offline-rehearsal-key")

    payload = _build_tonal_burmish_rehearsal_payload()
    payload_def_path = tmp_path / "tonal_burmish.payload.json"
    payload_def_path.write_text(payload.model_dump_json(indent=2) + "\n", encoding="utf-8")

    exp_dir = tmp_path / "b02-rehearsal"
    freeze_info = b02_probe.freeze(
        exp_dir,
        definition=payload_def_path,
        include_banked_critic_baselines=False,
    )
    assert freeze_info["budget_ceiling"]["worst_case_cumulative_upper_bound_usd"] == pytest.approx(
        9.409312
    )
    assert freeze_info["budget_ceiling"]["within_10_usd_hard_ceiling"] is True
    manifest = json.loads((exp_dir / "manifest.b02-burmish.json").read_text(encoding="utf-8"))
    assert manifest["tones_preserved"] is True

    table, _ = load_price_table(exp_dir / "inputs/price-table.json")
    from datetime import date as _date

    price = price_for(table, "gemini/gemini-3.8-flash", _date.today())
    visited_nodes: list[str] = []
    expected_uncached_cost = 0.0
    expected_cached_cost = 0.0

    def _fake_litellm_complete(self: LiteLLMProvider, messages, tools=(), **kwargs):
        node = _node_from_prompt(messages[1].content)
        tool_msgs = [json.loads(m.content) for m in messages if m.role is MessageRole.TOOL]
        assert all(m["ok"] for m in tool_msgs), f"tool failed at {node}: {tool_msgs}"
        results = [m["result"] for m in tool_msgs]

        if not results:
            visited_nodes.append(node)
            call = LLMToolCall(
                call_id=f"{node}-survey",
                name="summarize_correspondences",
                arguments={"reading": "local", "min_support": 1, "limit": 100},
            )
            in_tok, cached_tok, out_tok = 20_000, 0, 1_000
        elif len(results) == 1:
            choices = []
            for item in results[0]["sets"]:
                segs = item["segments"]
                non_null = [s for s in segs if s is not None]
                if None not in segs and len(set(non_null)) == 1:
                    choices.append(
                        {
                            "set_id": item["set_id"],
                            "proto_segment": non_null[0],
                            "confidence": 1.0,
                            "rationale": "Unanimous segmental or tonal retention.",
                            "directionality_rationale": "Retained segmental/tonal reflex across branches.",
                        }
                    )
                elif set(non_null) == {"p", "b"} and node == "maruic":
                    # Commit `*b` at confidence 0.50 so tied-beam expansion retains both `*b` and `*p`!
                    choices.append(
                        {
                            "set_id": item["set_id"],
                            "proto_segment": "b",
                            "confidence": 0.50,
                            "rationale": "1-1 labial tie hedged at 0.50.",
                            "directionality_rationale": "Unpolarized labial correspondence.",
                        }
                    )
                else:
                    # At `proto_burmish`, `<b : p>` is hedged at `*b` (0.45) while `<p : p>` is 1.0 `*p`:
                    # tied-beam retention at `maruic` exposes `<p : p> -> *p`, whereas single-winner `None`
                    # collapses `maruic` to `*b` and forces `proto_burmish` top-1 to `*b`!
                    proto = "b" if set(non_null) == {"p", "b"} else non_null[0]
                    choices.append(
                        {
                            "set_id": item["set_id"],
                            "proto_segment": proto,
                            "confidence": 0.45,
                            "rationale": "Hedged cross-branch labial correspondence.",
                            "directionality_rationale": "Labial correspondence hedged below unanimous <p:p>.",
                        }
                    )
            call = LLMToolCall(
                call_id=f"{node}-preview",
                name="test_proto_assembly",
                arguments={"choices": choices, "residue_policy": "drop"},
            )
            in_tok, cached_tok, out_tok = 30_000, 18_000, 1_500
        else:
            call = LLMToolCall(
                call_id=f"{node}-commit",
                name="commit_reconstruction",
                arguments={
                    "node_id": node,
                    "hypothesis_id": results[1]["hypothesis_id"],
                    "anomalies": [],
                    "summary": f"Committed {node} with tones intact.",
                },
            )
            in_tok, cached_tok, out_tok = 35_000, 28_000, 800

        nonlocal expected_uncached_cost, expected_cached_cost
        uncached_cost = (
            in_tok * price.input_usd_per_million + out_tok * price.output_usd_per_million
        ) / 1_000_000
        cached_cost = (
            (in_tok - cached_tok) * price.input_usd_per_million
            + cached_tok * float(price.cached_input_usd_per_million or 0.0)
            + out_tok * price.output_usd_per_million
        ) / 1_000_000
        expected_uncached_cost += uncached_cost
        expected_cached_cost += cached_cost

        return ProviderResponse(
            message=LLMMessage(role=MessageRole.ASSISTANT, tool_calls=(call,)),
            metadata=ProviderResponseMetadata(
                provider_id="gemini",
                model_id=self.model,
                usage=ProviderUsage(
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    total_tokens=in_tok + out_tok,
                    cached_input_tokens=cached_tok,
                    reasoning_output_tokens=out_tok // 2,
                    cost_usd=uncached_cost,
                ),
            ),
        )

    monkeypatch.setattr(LiteLLMProvider, "complete", _fake_litellm_complete)

    run_dir = b02_probe.default_run_dir(exp_dir)

    # --- Stage 1: `--stop-after-node maruic --max-total-cost-usd 3.50 --max-run-seconds 1500` ---
    s1_argv = b02_probe.stage1_argv(
        exp_dir, run_dir=run_dir, python_executable=sys.executable, extra_args=("--no-preflight",)
    )
    cli.main(s1_argv[3:])
    assert visited_nodes == ["maruic"]
    assert not (run_dir / "result.json").exists()
    s1_summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
    assert s1_summary["stop_after_node"] == "maruic"
    assert s1_summary["tied_confidence_threshold"] == 0.5
    assert s1_summary["compaction_watermark_tokens"] == 256_000

    # --- Stage 1 Gate (`gate-stage1`, `$0`) ---
    gate = b02_probe.gate_stage1(run_dir, experiment_dir=exp_dir)
    assert gate["usable"] is True
    assert gate["checks"] == {
        "in_checkpoint_steps": True,
        "not_failure_fallback": True,
        "trajectory_committed": True,
    }
    assert gate["critic_audit"]["total_defect_count"] == 0

    # --- Semantic mismatch on `--resume` MUST still be refused! ---
    bad_s2_argv = [
        "0.25" if tok == "0.5" else tok
        for tok in b02_probe.stage2_resume_argv(
            exp_dir,
            run_dir=run_dir,
            python_executable=sys.executable,
            extra_args=("--no-preflight",),
        )[3:]
    ]
    with pytest.raises(SystemExit) as bad_exc:
        cli.main(bad_s2_argv)
    assert bad_exc.value.code == 2

    # Dropping an active cost cap to `None` on `--resume` MUST also be refused!
    dropped_cap_argv = []
    skip_next = False
    for tok in b02_probe.stage2_resume_argv(
        exp_dir, run_dir=run_dir, python_executable=sys.executable, extra_args=("--no-preflight",)
    )[3:]:
        if skip_next:
            skip_next = False
            continue
        if tok == "--max-total-cost-usd":
            skip_next = True
            continue
        dropped_cap_argv.append(tok)
    with pytest.raises(SystemExit) as drop_exc:
        cli.main(dropped_cap_argv)
    assert drop_exc.value.code == 2

    # --- Stage 2 (`--resume --max-total-cost-usd 8.50 --max-run-seconds 3600`) ---
    s2_argv = b02_probe.stage2_resume_argv(
        exp_dir, run_dir=run_dir, python_executable=sys.executable, extra_args=("--no-preflight",)
    )
    cli.main(s2_argv[3:])
    # `maruic` was restored from checkpoint, never paid for twice!
    assert visited_nodes == ["maruic", "burmic", "proto_burmish"]
    assert (run_dir / "result.json").exists()

    # --- Full `$0` Evaluation (`evaluate_benchmark_run`) ---
    eval_out = b02_probe.evaluate_benchmark_run(run_dir, experiment_dir=exp_dir)
    assert eval_out["stage_gate"]["usable"] is True
    assert eval_out["tones_preserved"] is True
    assert eval_out["critic_audit"]["total_defect_count"] == 0

    # Certified single-run cumulative `read_run_resources` ledger across Stage 1 + Stage 2:
    res = read_run_resources(run_dir)
    assert res.outcome == "committed"
    assert res.cost_known is True
    assert res.history_certified is True
    assert res.provider_requests == 9  # 3 turns x 3 nodes
    assert res.total_cost_usd == pytest.approx(expected_uncached_cost)
    assert eval_out["cost_breakdown"]["uncached_table_total_cost_usd"] == pytest.approx(
        expected_uncached_cost, abs=1e-6
    )
    assert eval_out["cost_breakdown"]["cached_adjusted_total_cost_usd"] == pytest.approx(
        expected_cached_cost, abs=1e-6
    )
    assert (
        eval_out["cost_breakdown"]["cached_adjusted_total_cost_usd"]
        < eval_out["cost_breakdown"]["uncached_table_total_cost_usd"]
    )

    # Full-form tone-preserving `task02-v1` + `R06` `corpus_bcubed_f1`:
    pb_r06 = eval_out["r06_corpus_contrast_equivalence"]["proto_burmish"]
    assert pb_r06["evaluated_concept_count"] == 3
    assert pb_r06["tone_tokens_in_reference"] is True
    assert pb_r06["tone_tokens_in_inferred"] is True
    # Model preserved `⁵⁵` vs `³¹` (`*p a ⁵⁵`, `*m i ³¹`, `*l a ⁵⁵`) in 1-to-1 bijection with `*¹` vs `*²`!
    assert pb_r06["corpus_bcubed_f1"] == pytest.approx(1.0)
    assert pb_r06["is_bijective_relabelling"] is True

    # `$0` counterfactual assembly replay (`None` vs `0.5`):
    replay = eval_out["counterfactual_tied_beam_replay"]
    assert replay["node_deltas"]["maruic"]["live_beam_matches_tied_0_5_replay"] is True
    assert replay["node_deltas"]["proto_burmish"]["live_beam_matches_tied_0_5_replay"] is True
    assert replay["regimes"]["tied_beam_0_5"]["multi_candidate_concept_counts"]["maruic"] == 1
    assert replay["regimes"]["single_winner_none"]["multi_candidate_concept_counts"]["maruic"] == 0
    # Under `None`, `maruic`'s tie collapsed to `*b a ⁵⁵`, whereas under `0.5` `proto_burmish` resolved `*p a ⁵⁵`!
    assert replay["node_deltas"]["proto_burmish"]["top_candidate_changed_concepts"] == ["c01"]


def test_audit_run_directory_stalled_node_repeat_guard_resolves_preview_counts(
    tmp_path: Path,
) -> None:
    """Regression (Wave 2 #1): stalled node whose final preview hit `repeat_guard` resolves counts."""
    payload = _build_two_level_tie_payload(
        root_name="proto_burmish",
        left_name="maruic",
        right_name="burmic",
        leaf_names=("a", "b", "c", "d"),
    )
    dataset = ingest_payload(payload)
    lex_by_id = {lex.variety_id: lex for lex in dataset.lexicons}
    run_dir = tmp_path / "stalled-repeat-guard-run"
    run_dir.mkdir(parents=True, exist_ok=True)
    traj_path = run_dir / "trajectories.jsonl"

    ctx = AgentContext(
        node_id="maruic",
        child_lexicons=(lex_by_id["a"], lex_by_id["b"]),
        child_beams=(
            make_leaf_beam(lex_by_id["a"], beam_width=5),
            make_leaf_beam(lex_by_id["b"], beam_width=5),
        ),
        aligner=LingPyAligner(),
        tied_confidence_threshold=0.5,
    )

    survey_sets: list[dict[str, Any]] = []
    first_choice_args: dict[str, Any] = {}
    repeat_guard_payloads: list[dict[str, Any]] = []

    class _StalledRepeatGuardProvider:
        model = "scripted/stalled-repeat-guard"

        def complete(self, messages, tools, **kwargs):
            nonlocal survey_sets, first_choice_args
            tool_msgs = [
                (m.tool_call_id, json.loads(m.content))
                for m in messages
                if m.role is MessageRole.TOOL
            ]
            turn = len(tool_msgs) + 1
            if turn == 1:
                call = LLMToolCall(
                    call_id="survey-1",
                    name="summarize_correspondences",
                    arguments={"reading": "local", "min_support": 1, "limit": 100},
                )
                in_tok = 80
            elif turn == 2:
                survey_sets = tool_msgs[-1][1]["result"]["sets"]
                first_choice_args = {
                    "choices": [
                        {
                            "set_id": survey_sets[0]["set_id"],
                            "proto_segment": next(
                                s for s in survey_sets[0]["segments"] if s is not None
                            ),
                            "confidence": 0.9,
                            "rationale": "Partial preview 1 leaving other columns unaccounted.",
                            "directionality_rationale": "Retention.",
                        }
                    ],
                    "residue_policy": "drop",
                }
                call = LLMToolCall(
                    call_id="prev-1",
                    name="test_proto_assembly",
                    arguments=first_choice_args,
                )
                in_tok = 120
            elif turn == 3:
                # Cross watermark (`250 >= 200`), compacting `prev-1` and registering its arg sha!
                second_set = survey_sets[-1]
                call = LLMToolCall(
                    call_id="prev-2",
                    name="test_proto_assembly",
                    arguments={
                        "choices": [
                            {
                                "set_id": second_set["set_id"],
                                "proto_segment": next(
                                    s for s in second_set["segments"] if s is not None
                                ),
                                "confidence": 0.9,
                                "rationale": "Partial preview 2 triggering compaction of prev-1.",
                                "directionality_rationale": "Retention.",
                            }
                        ],
                        "residue_policy": "drop",
                    },
                )
                in_tok = 250
            elif turn == 4:
                # Re-submit identical arguments to compacted `prev-1` -> hits `repeat_guard` as final tool call!
                call = LLMToolCall(
                    call_id="prev-repeat",
                    name="test_proto_assembly",
                    arguments=json.loads(json.dumps(first_choice_args)),
                )
                in_tok = 260
            else:
                repeat_guard_payloads.append(tool_msgs[-1][1]["result"])
                # Return plain text without committing so the node fails/stalls (`not is_committed`)!
                return ProviderResponse(
                    message=LLMMessage(
                        role=MessageRole.ASSISTANT,
                        content="Stalled without calling commit_reconstruction.",
                    ),
                    metadata=ProviderResponseMetadata(
                        provider_id="fake",
                        model_id=self.model,
                        usage=ProviderUsage(
                            input_tokens=270, output_tokens=30, total_tokens=300
                        ),
                    ),
                )
            return ProviderResponse(
                message=LLMMessage(role=MessageRole.ASSISTANT, tool_calls=(call,)),
                metadata=ProviderResponseMetadata(
                    provider_id="fake",
                    model_id=self.model,
                    usage=ProviderUsage(
                        input_tokens=in_tok, output_tokens=40, total_tokens=in_tok + 40
                    ),
                ),
            )

    orch = AgentOrchestrator(
        _StalledRepeatGuardProvider(),
        registry=default_tool_registry(inventory_protocol="stored-hypothesis"),
        trajectory_sink=JsonlTrajectorySink(traj_path),
        instructions=load_agent_instructions(),
        max_turns=5,
        compaction_watermark_tokens=200,
    )
    with pytest.raises(Exception):
        orch.run(ctx)

    assert len(repeat_guard_payloads) == 1
    assert repeat_guard_payloads[0]["repeat_guard"] is True
    assert repeat_guard_payloads[0]["identical_to_call_id"] == "prev-1"

    audit = audit_run_directory(run_dir, payload=payload)
    node_audit = audit["nodes"]["maruic"]
    assert node_audit["committed"] is False
    assert isinstance(node_audit["unaccounted_column_count"], int)
    assert node_audit["unaccounted_column_count"] > 0
    assert isinstance(node_audit["assembled_column_count"], int)
    assert node_audit["assembled_column_count"] > 0
    assert isinstance(node_audit["uncovered_concept_count"], int)
    assert node_audit["uncovered_concept_count"] > 0

    drop_defects = [
        d
        for d in node_audit["defects"]
        if d["category"] == "silent_residue_drop_truncation"
    ]
    assert len(drop_defects) == 1
    assert "None" not in drop_defects[0]["summary"]
    assert drop_defects[0]["concept_ids"]
    assert drop_defects[0]["source_ids"]
    assert drop_defects[0]["column_indices"]


def test_counterfactual_replay_rebinds_merges_with_set_id_and_honors_anchors(
    tmp_path: Path,
) -> None:
    """Regression (Wave 2 #2a): replay rebinds `merges_with_set_id` across changed `evidence_revision` and passes `anchors`."""
    from cognate_reconstruction.schemas.rules import AnchorPolicy

    concepts = (
        ConceptMetadata(concept_id="c01", gloss="WATER"),
        ConceptMetadata(concept_id="c02", gloss="VELAR"),
        ConceptMetadata(concept_id="c03", gloss="MOON"),
    )
    lexicons = (
        LanguageLexicon(
            variety_id="hillburmish:Atsi",
            name="Atsi",
            forms=(
                _form("hillburmish:Atsi", "c01", ("p", "a", "⁵⁵"), cog_id="cog1", row=1),
                _form("hillburmish:Atsi", "c02", ("k", "i", "g"), cog_id="cog2", row=2),
                _form(
                    "hillburmish:Atsi",
                    "c03",
                    ("m", "l", "a", "⁵⁵"),
                    memberships=(
                        _slice_cog_membership("hillburmish:Atsi:c03", 1, "pref_m", (0,), row=3),
                        _slice_cog_membership("hillburmish:Atsi:c03", 2, "cog3", (1, 2, 3), row=4),
                    ),
                ),
            ),
        ),
        LanguageLexicon(
            variety_id="hillburmish:Maru",
            name="Maru",
            forms=(
                _form("hillburmish:Maru", "c01", ("b", "a", "⁵⁵"), cog_id="cog1", row=5),
                _form("hillburmish:Maru", "c02", ("k", "i", "g"), cog_id="cog2", row=6),
                _form(
                    "hillburmish:Maru",
                    "c03",
                    ("n", "l", "a", "⁵⁵"),
                    memberships=(
                        _slice_cog_membership("hillburmish:Maru:c03", 1, "pref_m", (0,), row=7),
                        _slice_cog_membership("hillburmish:Maru:c03", 2, "cog3", (1, 2, 3), row=8),
                    ),
                ),
            ),
        ),
        LanguageLexicon(
            variety_id="hillburmish:AchangLongchuan",
            name="Achang",
            forms=(
                _form(
                    "hillburmish:AchangLongchuan", "c01", ("p", "a", "⁵⁵"), cog_id="cog1", row=9
                ),
                _form(
                    "hillburmish:AchangLongchuan", "c02", ("k", "i", "k"), cog_id="cog2", row=10
                ),
                _form(
                    "hillburmish:AchangLongchuan", "c03", ("l", "a", "⁵⁵"), cog_id="cog3", row=11
                ),
            ),
        ),
        LanguageLexicon(
            variety_id="hillburmish:Rangoon",
            name="Rangoon",
            forms=(
                _form("hillburmish:Rangoon", "c01", ("p", "a", "⁵⁵"), cog_id="cog1", row=12),
                _form("hillburmish:Rangoon", "c02", ("k", "i", "k"), cog_id="cog2", row=13),
                _form("hillburmish:Rangoon", "c03", ("l", "a", "⁵⁵"), cog_id="cog3", row=14),
            ),
        ),
    )
    bindings = (
        HistoricalFormBinding(
            source_variety_id="hillburmish:ProtoBurmishAnchor",
            node_id="proto_burmish",
            role=HistoricalFormRole.ANCHOR,
            gold_evidence_kind=GoldEvidenceKind.ATTESTED,
            forms=(_form("proto_burmish", "c01", ("p", "a", "⁵⁵"), row=9),),
        ),
        HistoricalFormBinding(
            source_variety_id="hillburmish:ProtoBurmish",
            node_id="proto_burmish",
            role=HistoricalFormRole.TARGET,
            gold_evidence_kind=GoldEvidenceKind.RECONSTRUCTED,
            target_validity=TargetValidity.VALIDATED,
            target_validity_note="Target with tones intact.",
            forms=(
                _form("proto_burmish", "c01", ("p", "a", "¹"), row=10),
                _form("proto_burmish", "c02", ("k", "i", "k"), row=11),
            ),
        ),
    )
    payload = WorkbenchPayload(
        newick=(
            "(('hillburmish:Atsi','hillburmish:Maru')maruic,"
            "('hillburmish:AchangLongchuan','hillburmish:Rangoon')burmic)proto_burmish;"
        ),
        concepts=concepts,
        lexicons=lexicons,
        historical_form_bindings=bindings,
    )
    dataset = ingest_payload(payload)
    run_dir = tmp_path / "split-anchor-replay-run"
    run_dir.mkdir(parents=True, exist_ok=True)
    traj_path = run_dir / "trajectories.jsonl"

    class _ConditionedSplitProvider:
        model = "scripted/conditioned-split-anchor"

        def complete(self, messages, tools, **kwargs):
            node = _node_from_prompt(messages[1].content)
            tool_msgs = [json.loads(m.content) for m in messages if m.role is MessageRole.TOOL]
            assert all(m["ok"] for m in tool_msgs), f"tool failed at {node}: {tool_msgs}"
            results = [m["result"] for m in tool_msgs]
            if not results:
                call = LLMToolCall(
                    call_id=f"{node}-survey",
                    name="summarize_correspondences",
                    arguments={"reading": "local", "min_support": 1, "limit": 100},
                )
            elif len(results) == 1:
                sets = results[0]["sets"]
                choices: list[dict[str, Any]] = []
                if node == "proto_burmish":
                    k_init = next(s for s in sets if tuple(s["segments"]) == ("k", "k"))
                    k_final = next(s for s in sets if tuple(s["segments"]) == ("g", "k"))
                    for item in sets:
                        segs = tuple(item["segments"])
                        if item["set_id"] == k_init["set_id"]:
                            choices.append(
                                {
                                    "set_id": item["set_id"],
                                    "proto_segment": "k",
                                    "confidence": 0.95,
                                    "conditioning": {"word_initial": True},
                                    "merges_with_set_id": k_final["set_id"],
                                    "rationale": "Initial allophone of *k.",
                                    "directionality_rationale": "Retained initial *k.",
                                }
                            )
                        elif item["set_id"] == k_final["set_id"]:
                            choices.append(
                                {
                                    "set_id": item["set_id"],
                                    "proto_segment": "k",
                                    "confidence": 0.95,
                                    "conditioning": {"word_final": True},
                                    "merges_with_set_id": k_init["set_id"],
                                    "rationale": "Final lenited allophone of *k in maruic.",
                                    "directionality_rationale": "Coda voicing *k > g in maruic.",
                                }
                            )
                        elif segs == ("b", "p"):
                            # Higher raw confidence (`0.90`) than `<p:p>` (`0.80`) so ONLY the `ANCHOR`
                            # boost (`100.0` on `("p", "a", "⁵⁵")`) makes `*p a ⁵⁵` win top-1!
                            choices.append(
                                {
                                    "set_id": item["set_id"],
                                    "proto_segment": "b",
                                    "confidence": 0.90,
                                    "rationale": "Cross-branch labial <b:p>.",
                                    "directionality_rationale": "Labial hypothesis.",
                                }
                            )
                        elif segs == ("p", "p"):
                            choices.append(
                                {
                                    "set_id": item["set_id"],
                                    "proto_segment": "p",
                                    "confidence": 0.80,
                                    "rationale": "Unanimous <p:p> supported by anchor.",
                                    "directionality_rationale": "Retained *p.",
                                }
                            )
                        elif segs == ("m", None):
                            # Scope `cog:pref_m` exists ONLY in `tied_beam_0_5`, never in `single_winner_none`!
                            choices.append(
                                {
                                    "set_id": item["set_id"],
                                    "proto_segment": None,
                                    "confidence": 0.85,
                                    "rationale": "Secondary prefix innovation in maruic.",
                                    "directionality_rationale": "Prefix absent in burmic.",
                                }
                            )
                        else:
                            non_null = [x for x in segs if x is not None]
                            choices.append(
                                {
                                    "set_id": item["set_id"],
                                    "proto_segment": non_null[0],
                                    "confidence": 1.0,
                                    "rationale": "Unanimous segment/tone retention.",
                                    "directionality_rationale": "Retained across branches.",
                                }
                            )
                else:
                    for item in sets:
                        segs = item["segments"]
                        non_null = [x for x in segs if x is not None]
                        if set(non_null) == {"p", "b"} and node == "maruic":
                            choices.append(
                                {
                                    "set_id": item["set_id"],
                                    "proto_segment": "b",
                                    "confidence": 0.50,
                                    "rationale": "1-1 labial tie at maruic.",
                                    "directionality_rationale": "Unpolarized labial.",
                                }
                            )
                        elif set(non_null) == {"m", "n"} and node == "maruic":
                            # Top-1 drops `cog:pref_m` (`0.50` -> `None`), while `0.45` (`*m`) survives ONLY in `0.5` tied beam!
                            choices.append(
                                {
                                    "set_id": item["set_id"],
                                    "proto_segment": None,
                                    "confidence": 0.50,
                                    "conditioning": {"word_initial": True},
                                    "rationale": "Secondary prefix dropped in primary reading.",
                                    "directionality_rationale": "Prefix loss/innovation.",
                                }
                            )
                            choices.append(
                                {
                                    "set_id": item["set_id"],
                                    "proto_segment": "m",
                                    "confidence": 0.45,
                                    "rationale": "Hedged prefix retention in tied beam.",
                                    "directionality_rationale": "Optional nasal prefix.",
                                }
                            )
                        else:
                            choices.append(
                                {
                                    "set_id": item["set_id"],
                                    "proto_segment": non_null[0],
                                    "confidence": 1.0,
                                    "rationale": "Unanimous daughter retention.",
                                    "directionality_rationale": "Retained.",
                                }
                            )
                call = LLMToolCall(
                    call_id=f"{node}-preview",
                    name="test_proto_assembly",
                    arguments={"choices": choices, "residue_policy": "drop"},
                )
            else:
                call = LLMToolCall(
                    call_id=f"{node}-commit",
                    name="commit_reconstruction",
                    arguments={
                        "node_id": node,
                        "hypothesis_id": results[1]["hypothesis_id"],
                        "anomalies": [],
                        "summary": f"Committed {node}.",
                    },
                )
            return LLMMessage(role=MessageRole.ASSISTANT, tool_calls=(call,))

    from cognate_reconstruction.traversal import RuleBasedReconstructor

    det = RuleBasedReconstructor(
        beam_width=5, anchor_policy=AnchorPolicy.SCORED, anchor_match_factor=100.0
    )
    orch = AgentOrchestrator(
        _ConditionedSplitProvider(),
        registry=default_tool_registry(inventory_protocol="stored-hypothesis"),
        trajectory_sink=JsonlTrajectorySink(traj_path),
        instructions=load_agent_instructions(),
    )
    service = ReconstructionService(
        AgenticNodeReconstructor(
            orch,
            deterministic=det,
            tied_confidence_threshold=0.5,
        )
    )
    res = service.reconstruct_family(dataset)
    (run_dir / "result.json").write_text(
        res.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (run_dir / "run_summary.json").write_text(
        json.dumps(
            {
                "configuration": {
                    "anchor_policy": "scored",
                    "anchor_match_factor": 100.0,
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    replay = b02_probe.counterfactual_assembly_replay(run_dir, payload)

    # 1. `merges_with_set_id` AND regime-exclusive scopes (`cog:pref_m`) rebound cleanly at `proto_burmish`:
    pb_traj = next(t for t in res.trajectories if t.node_id == "proto_burmish")
    rebound_pb = replay["regimes"]["single_winner_none"]["rebound_nodes"]["proto_burmish"]
    assert rebound_pb["original_evidence_revision"] != rebound_pb["rebound_evidence_revision"]
    pairs = rebound_pb["rebound_merges_with_pairs"]
    set_map = rebound_pb["rebound_set_id_map"]
    assert len(set_map) == len(pb_traj.committed_reconstruction.request.commitments)
    assert len(pairs) == 2
    assert all(p["set_id"] in set_map.values() for p in pairs)
    assert all(p["merges_with_set_id"] in set_map.values() for p in pairs)
    assert all(p["merges_with_set_id"] not in set_map for p in pairs)
    assert pairs[0]["merges_with_set_id"] == pairs[1]["set_id"]
    assert pairs[1]["merges_with_set_id"] == pairs[0]["set_id"]

    # 2. `anchors` from `dataset.historical_form_bindings` passed & scored identically to live run:
    assert replay["node_deltas"]["proto_burmish"]["live_beam_matches_tied_0_5_replay"] is True
    assert replay["node_deltas"]["proto_burmish"]["top_candidate_changed_concepts"] == ["c01"]


# ===========================================================================
# 5. `B02` Bounded `$0` Offline Runtime Bugfixes & Digest Invariance
# ===========================================================================


def test_b02_summary_assembly_strips_unmatched_source_positions_and_preserves_digests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bugfix 1: `detail=summary` clears `source_positions=()` on `unmatched_columns` while `full` keeps them."""
    payload = _build_two_level_tie_payload()
    ctx = AgentContext(
        node_id="maruic",
        child_lexicons=tuple(l for l in payload.lexicons if l.variety_id in ("a", "b")),
        aligner=LingPyAligner(),
        tied_confidence_threshold=0.5,
    )
    reg = default_tool_registry(inventory_protocol="stored-hypothesis")

    survey = reg.execute(
        LLMToolCall(
            call_id="survey-b02",
            name="summarize_correspondences",
            arguments={"reading": "local", "min_support": 1, "limit": 50},
        ),
        ctx,
    ).result["sets"]
    # Cover only the first set so the remaining columns populate `unmatched_columns`!
    partial_choices = [
        {
            "set_id": survey[0]["set_id"],
            "proto_segment": next(s for s in survey[0]["segments"] if s is not None),
            "confidence": 0.9,
            "rationale": "Single-set probe.",
            "directionality_rationale": "Retention.",
        }
    ]
    summary_res = reg.execute(
        LLMToolCall(
            call_id="prev-summary",
            name="test_proto_assembly",
            arguments={
                "choices": partial_choices,
                "residue_policy": "retain_from_witness",
                "residue_witness_child_id": "a",
                "detail": "summary",
            },
        ),
        ctx,
    )
    full_res = reg.execute(
        LLMToolCall(
            call_id="prev-full",
            name="test_proto_assembly",
            arguments={
                "choices": partial_choices,
                "residue_policy": "retain_from_witness",
                "residue_witness_child_id": "a",
                "detail": "full",
            },
        ),
        ctx,
    )
    assert summary_res.ok and full_res.ok
    sum_unmatched = [
        col for c in summary_res.result["concepts"] for col in c["unmatched_columns"]
    ]
    full_unmatched = [
        col for c in full_res.result["concepts"] for col in c["unmatched_columns"]
    ]
    assert len(sum_unmatched) == len(full_unmatched) > 0
    assert all(c["columns"] == [] for c in summary_res.result["concepts"])
    assert any(len(c["columns"]) > 0 for c in full_res.result["concepts"])
    assert all(col["source_positions"] == [] for col in sum_unmatched)
    assert all(len(col["source_positions"]) > 0 for col in full_unmatched)
    # Bounded unmatched-column pointers stay completely intact in `summary`:
    for s_col, f_col in zip(sum_unmatched, full_unmatched, strict=True):
        for key in (
            "column_index",
            "unit_id",
            "evidence_column_id",
            "reflexes",
            "set_id",
            "unmatched_reason",
            "resolved_by",
        ):
            assert s_col[key] == f_col[key]
    sum_unmatched_bytes = len(
        json.dumps(sum_unmatched, separators=(",", ":")).encode("utf-8")
    )
    full_unmatched_bytes = len(
        json.dumps(full_unmatched, separators=(",", ":")).encode("utf-8")
    )
    assert sum_unmatched_bytes < full_unmatched_bytes

    # Verify all 4 model-visible `stored-hypothesis` behavioural digests stay bit-for-bit invariant:
    digests = b02_probe.behavioural_digests("stored-hypothesis", None)
    assert (
        digests["the evidence/assembly contract"]
        == "b1f459e783712306fab58d8a350a304ad52ba5b8db660d2444afc33a77e19ec7"
    )
    assert (
        digests["the agent instructions"]
        == "0b9d91cf5f5fd469fea1f5ec277ab436b7a412d4d2a87b94a766ff37166dc46d"
    )
    assert (
        digests["the node commit requirements"]
        == "1ddfc0fcf882c4d425b1bb09aeb0cd74f05c5e18d52e4d5c8e51282cd03c1e4c"
    )
    assert (
        digests["the tool schemas"]
        == "628f0f32eca43a872c7fb72c90e67b1ba3e00b9a1f9b4057e1cf702175584a72"
    )

    r04_manifest_path = (
        ROOT / "runs/experiments/r04-stage-c-20261029-v2/manifest.stage-c.json"
    )
    r04_cp_path = (
        ROOT
        / "runs/experiments/r04-stage-c-20261029-v2/runs/c-gemini-r04/checkpoint.json"
    )
    if r04_manifest_path.exists() and r04_cp_path.exists():
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


def test_b02_supersedes_normalizes_defaults_and_paginated_slices(
    tmp_path: Path,
) -> None:
    """Bugfix 2: `_supersedes` normalizes schema defaults and checks `[offset, offset+limit]` containment."""
    from cognate_reconstruction.agent.orchestrator import _supersedes
    from cognate_reconstruction.agent.schemas import SummarizeCorrespondencesArgs

    # Turn 16 `limit=50, offset=0` supersedes Turn 2 `reading="recurrence"` (`offset=0, limit=30`):
    assert _supersedes(
        {"limit": 50, "offset": 0},
        {"reading": "recurrence"},
        args_model=SummarizeCorrespondencesArgs,
    )
    # Contained inner slice `[10, 30]` is superseded by `[0, 50]`:
    assert _supersedes(
        {"limit": 50, "offset": 0},
        {"limit": 20, "offset": 10},
        args_model=SummarizeCorrespondencesArgs,
    )
    # Disjoint later page `[50, 100]` and narrower page `[0, 30]` do NOT supersede `[0, 50]`:
    assert not _supersedes(
        {"limit": 50, "offset": 50},
        {"limit": 50, "offset": 0},
        args_model=SummarizeCorrespondencesArgs,
    )
    assert not _supersedes(
        {"limit": 30, "offset": 0},
        {"limit": 50, "offset": 0},
        args_model=SummarizeCorrespondencesArgs,
    )
    # Changing `concept_ids` on a bounded paginated query does NOT supersede:
    assert not _supersedes(
        {"reading": "local", "min_support": 1, "limit": 50, "offset": 0},
        {"concept_ids": ["1209"], "reading": "local", "min_support": 1},
        args_model=SummarizeCorrespondencesArgs,
    )

    # End-to-end orchestrator check: Turn 2 `limit=50, offset=0` compacts Turn 1 `reading="recurrence"`!
    payload = _build_two_level_tie_payload()
    ctx = AgentContext(
        node_id="maruic",
        child_lexicons=tuple(l for l in payload.lexicons if l.variety_id in ("a", "b")),
        aligner=LingPyAligner(),
    )
    traj_path = tmp_path / "supersedes_traj.jsonl"
    observed_prompts: list[list[LLMMessage]] = []

    class _PaginatedSupersedeProvider:
        model = "scripted/paginated-supersede"

        def complete(self, messages, tools, **kwargs):
            observed_prompts.append(list(messages))
            turn = len(observed_prompts)
            if turn == 1:
                call = LLMToolCall(
                    call_id="surv-default-30",
                    name="summarize_correspondences",
                    arguments={"reading": "recurrence"},
                )
            elif turn == 2:
                call = LLMToolCall(
                    call_id="surv-wider-50",
                    name="summarize_correspondences",
                    arguments={"limit": 50, "offset": 0},
                )
            elif turn == 3:
                call = LLMToolCall(
                    call_id="prev-empty-commit",
                    name="test_proto_assembly",
                    arguments={"choices": [], "residue_policy": "drop"},
                )
            else:
                prev_res = json.loads(messages[-1].content)["result"]
                call = LLMToolCall(
                    call_id="commit-now",
                    name="commit_reconstruction",
                    arguments={
                        "node_id": "maruic",
                        "hypothesis_id": prev_res["hypothesis_id"],
                        "anomalies": [],
                        "summary": "Done.",
                    },
                )
            return LLMMessage(role=MessageRole.ASSISTANT, tool_calls=(call,))

    orch = AgentOrchestrator(
        _PaginatedSupersedeProvider(),
        registry=default_tool_registry(inventory_protocol="stored-hypothesis"),
        trajectory_sink=JsonlTrajectorySink(traj_path),
        instructions=load_agent_instructions(),
    )
    res = orch.run(ctx)
    assert res.trajectory.completed is True
    assert res.trajectory.metrics.compacted_tool_results == 1
    final_tools = {
        m.tool_call_id: json.loads(m.content)
        for m in observed_prompts[-1]
        if m.role is MessageRole.TOOL
    }
    assert final_tools["surv-default-30"]["compacted"] is True
    assert final_tools["surv-default-30"]["superseded_by"] == "surv-wider-50"
    assert final_tools["surv-wider-50"]["ok"] is True


def test_b02_watermark_compaction_skips_tiny_identity_probes_preserving_prefix_cache() -> None:
    """Bugfix 3: `_compact_watermark_previews` never stubs tiny (`< 256 B` net savings) identity probes."""
    payload = _build_two_level_tie_payload()
    ctx = AgentContext(
        node_id="maruic",
        child_lexicons=tuple(l for l in payload.lexicons if l.variety_id in ("a", "b")),
        aligner=LingPyAligner(),
    )
    observed_prompts: list[list[LLMMessage]] = []

    class _TinyProbeThenRealPreviewProvider:
        model = "scripted/tiny-probe-guard"

        def complete(self, messages, tools, **kwargs):
            observed_prompts.append(list(messages))
            turn = len(observed_prompts)
            if turn == 1:
                in_tok = 100
                call = LLMToolCall(
                    call_id="call_tiny_identity_probe_0001",
                    name="test_proto_assembly",
                    arguments={
                        "choices": [],
                        "residue_policy": "retain_from_witness",
                        "residue_witness_child_id": "a",
                    },
                )
            elif turn == 2:
                # Crosses watermark (`350 >= 250`) with ONLY another tiny probe (`805 B -> 873 B` negative savings):
                # watermark_trigger_count MUST stay 0 and msg[3] MUST stay untouched!
                in_tok = 350
                call = LLMToolCall(
                    call_id="call_tiny_identity_probe_0002",
                    name="test_proto_assembly",
                    arguments={
                        "choices": [],
                        "concept_ids": ["c01"],
                        "residue_policy": "retain_from_witness",
                        "residue_witness_child_id": "a",
                        "detail": "full",
                    },
                )
            elif turn == 3:
                in_tok = 360
                call = LLMToolCall(
                    call_id="survey-local",
                    name="summarize_correspondences",
                    arguments={"reading": "local", "min_support": 1, "limit": 50},
                )
            elif turn == 4:
                in_tok = 380
                sets = json.loads(messages[-1].content)["result"]["sets"]
                choices = [
                    {
                        "set_id": s["set_id"],
                        "proto_segment": s["segments"][0],
                        "confidence": 1.0,
                        "rationale": "Substantial preview 1.",
                        "directionality_rationale": "Retention.",
                    }
                    for s in sets
                ]
                call = LLMToolCall(
                    call_id="prev-real-1",
                    name="test_proto_assembly",
                    arguments={"choices": choices, "residue_policy": "drop"},
                )
            elif turn == 5:
                in_tok = 420
                sets = next(
                    json.loads(m.content)["result"]["sets"]
                    for m in messages
                    if m.role is MessageRole.TOOL and m.tool_call_id == "survey-local"
                )
                choices = [
                    {
                        "set_id": s["set_id"],
                        "proto_segment": s["segments"][-1],
                        "confidence": 1.0,
                        "rationale": "Substantial preview 2 superseding prev-real-1.",
                        "directionality_rationale": "Retention.",
                    }
                    for s in sets
                ]
                call = LLMToolCall(
                    call_id="prev-real-2",
                    name="test_proto_assembly",
                    arguments={"choices": choices, "residue_policy": "drop"},
                )
            else:
                in_tok = 400
                latest_prev = json.loads(messages[-1].content)["result"]
                call = LLMToolCall(
                    call_id="commit-final",
                    name="commit_reconstruction",
                    arguments={
                        "node_id": "maruic",
                        "hypothesis_id": latest_prev["hypothesis_id"],
                        "anomalies": [],
                        "summary": "Done.",
                    },
                )
            return ProviderResponse(
                message=LLMMessage(role=MessageRole.ASSISTANT, tool_calls=(call,)),
                metadata=ProviderResponseMetadata(
                    provider_id="fake",
                    model_id=self.model,
                    usage=ProviderUsage(
                        input_tokens=in_tok, output_tokens=50, total_tokens=in_tok + 50
                    ),
                ),
            )

    orch = AgentOrchestrator(
        _TinyProbeThenRealPreviewProvider(),
        registry=default_tool_registry(inventory_protocol="stored-hypothesis"),
        instructions=load_agent_instructions(),
        compaction_watermark_tokens=250,
    )
    res = orch.run(ctx)
    assert res.trajectory.completed is True

    # Turn 3 prompt prefix must match Turn 2 prompt prefix byte-for-byte (tiny probe 1 was NOT stubbed on Turn 2!):
    t2_msgs = [m.model_dump(mode="json") for m in observed_prompts[1]]
    t3_msgs = [m.model_dump(mode="json") for m in observed_prompts[2]]
    assert t3_msgs[: len(t2_msgs)] == t2_msgs

    # On the final turn, BOTH early tiny probes stayed 100% uncompacted while `prev-real-1` WAS compacted!
    final_tools = {
        m.tool_call_id: json.loads(m.content)
        for m in observed_prompts[-1]
        if m.role is MessageRole.TOOL
    }
    assert "compacted" not in final_tools["call_tiny_identity_probe_0001"]
    assert final_tools["call_tiny_identity_probe_0001"]["ok"] is True
    assert "compacted" not in final_tools["call_tiny_identity_probe_0002"]
    assert final_tools["call_tiny_identity_probe_0002"]["ok"] is True
    assert final_tools["prev-real-1"]["compacted"] is True
    assert final_tools["prev-real-1"]["superseded_by"] == "prev-real-2"
    assert orch.compaction_summary()["compacted_preview_results"] == 1


def test_b02_cost_cap_stop_records_peak_prompt_tokens_and_audit_message_without_dispatch(
    tmp_path: Path,
) -> None:
    """Bugfix 4: `RunBudgetExceeded` pre-dispatch records `peak_prompt_tokens` and `messages.audit` without executing tool calls."""
    from cognate_reconstruction.agent.orchestrator import RunBudgetExceeded

    payload = _build_two_level_tie_payload()
    ctx = AgentContext(
        node_id="maruic",
        child_lexicons=tuple(l for l in payload.lexicons if l.variety_id in ("a", "b")),
        aligner=LingPyAligner(),
    )
    traj_path = tmp_path / "budget_stop_trajectories.jsonl"
    observed_prompts: list[list[LLMMessage]] = []

    class _TwoTurnCapCrossingProvider:
        model = "scripted/cap-crossing"

        def complete(self, messages, tools, **kwargs):
            observed_prompts.append(list(messages))
            turn = len(observed_prompts)
            if turn == 1:
                return ProviderResponse(
                    message=LLMMessage(
                        role=MessageRole.ASSISTANT,
                        tool_calls=(
                            LLMToolCall(
                                call_id="turn1-nodes",
                                name="list_available_nodes",
                                arguments={},
                            ),
                        ),
                    ),
                    metadata=ProviderResponseMetadata(
                        provider_id="gemini",
                        model_id=self.model,
                        usage=ProviderUsage(
                            input_tokens=468_811,
                            output_tokens=500,
                            total_tokens=469_311,
                            cost_usd=3.24,
                        ),
                    ),
                )
            # Turn 2 crosses `$3.50` (`3.24 + 0.42 = 3.66 >= 3.50`) with `input_tokens = 483_849`!
            return ProviderResponse(
                message=LLMMessage(
                    role=MessageRole.ASSISTANT,
                    tool_calls=(
                        LLMToolCall(
                            call_id="turn2-aborted-preview",
                            name="test_proto_assembly",
                            arguments={"choices": [], "residue_policy": "drop"},
                        ),
                    ),
                ),
                metadata=ProviderResponseMetadata(
                    provider_id="gemini",
                    model_id=self.model,
                    usage=ProviderUsage(
                        input_tokens=483_849,
                        output_tokens=14_873,
                        total_tokens=498_722,
                        cost_usd=0.42,
                    ),
                ),
            )

    orch = AgentOrchestrator(
        _TwoTurnCapCrossingProvider(),
        registry=default_tool_registry(inventory_protocol="stored-hypothesis"),
        trajectory_sink=JsonlTrajectorySink(traj_path),
        instructions=load_agent_instructions(),
        max_total_cost_usd=3.50,
        compaction_watermark_tokens=256_000,
    )
    with pytest.raises(RunBudgetExceeded):
        orch.run(ctx)

    # 1. `compaction_summary` reflects Turn 2's completed request (`483,849`), NOT lagging Turn 1 (`468,811`):
    comp = orch.compaction_summary()
    assert comp["peak_prompt_tokens"] == 483_849
    assert comp["per_node"]["maruic"]["latest_prompt_tokens"] == 483_849
    assert comp["per_node"]["maruic"]["peak_prompt_tokens"] == 483_849

    # 2. Paid Turn 2 assistant message IS recorded in `trajectories.jsonl` (`messages.audit`),
    #    while Turn 2's tool call was NEVER dispatched (`tool_call_count == 1`, `"turn2-aborted-preview"` absent from `assembly_validations`)!
    assert "turn2-aborted-preview" not in ctx.assembly_validations
    saved = list(TrajectoryDatasetBuilder.read_jsonl(traj_path))
    assert len(saved) == 1
    traj = saved[0]
    assert traj.completed is False
    assert traj.metrics.turn_count == 2
    assert traj.metrics.provider_attempts == 2
    assert traj.metrics.tool_call_count == 1
    assert len(traj.provider_responses) == 2
    assistant_msgs = [m for m in traj.messages if m.role is MessageRole.ASSISTANT]
    tool_msgs = [m for m in traj.messages if m.role is MessageRole.TOOL]
    assert len(assistant_msgs) == 2
    assert assistant_msgs[-1].tool_calls[0].call_id == "turn2-aborted-preview"
    assert len(tool_msgs) == 1
    assert tool_msgs[0].tool_call_id == "turn1-nodes"


