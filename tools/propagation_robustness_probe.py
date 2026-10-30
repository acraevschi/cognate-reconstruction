"""Offline two-level propagation and robustness probe (`two-level-propagation-v1`).

Runs the two-level synthetic diagnostic arms and replays the banked live-model
intermediate commits at `x` from `b-gemini`, `c-gemini-r04`, and
`c-local-qwen38-27b-r04` under single-winner assembly (`tied_confidence_threshold=None`)
versus tied-alternative beam retention (`tied_confidence_threshold=0.5`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.schemas import LLMToolCall
from cognate_reconstruction.agent.tools import default_tool_registry, summarize_commit
from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.alignment.units import evidence_map, source_analyses
from cognate_reconstruction.evaluation.decisions import score_decisions
from cognate_reconstruction.evaluation.run import evaluate_run
from cognate_reconstruction.ingestion.service import ingest_payload
from cognate_reconstruction.schemas.beam import (
    CandidateDerivation,
    ConceptCandidateDistribution,
    NodeBeamState,
    ReconstructionCandidate,
)
from cognate_reconstruction.schemas.evidence import EvidencePiece, FormAnalysis, PieceSource
from cognate_reconstruction.schemas.historical import TargetValidity
from cognate_reconstruction.schemas.inventory import (
    CommittedProtoInventory,
    CorrespondenceCommitment,
    ResiduePolicy,
    SegmentRestoration,
)
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm
from cognate_reconstruction.schemas.traversal import (
    ReconstructionDiagnostics,
    ReconstructionStep,
)
from cognate_reconstruction.synthesis.diagnostics import (
    build_case,
    build_explicit_case,
    load_explicit_case,
    load_suite,
)
from cognate_reconstruction.traversal.assembler import ProtoInventoryAssembler
from cognate_reconstruction.traversal.beam import (
    beam_to_lexicon,
    decided_by_tie_break,
    make_leaf_beam,
)
from cognate_reconstruction.traversal.traverser import TreeTraverser

SUITE_PATH = Path("benchmarks/diagnostic/two-level-propagation-v1.json")
STAGE_B_PATH = Path("benchmarks/diagnostic/stage-b-retention-v1.json")
STAGE_C_PATH = Path("benchmarks/diagnostic/stage-c-multi-outgroup-v1.json")

BANKED_RUNS = {
    "b-gemini": {
        "stage": "r02-stage-b-v1",
        "definition_path": str(STAGE_B_PATH),
        "run_dir": "runs/experiments/r03-model-diagnostic-20261025-v2/runs/b-gemini",
        "tied_concepts": ["w13", "w08"],
    },
    "c-gemini-r04": {
        "stage": "r04-stage-c-v1",
        "definition_path": str(STAGE_C_PATH),
        "run_dir": "runs/experiments/r04-stage-c-20261029-v2/runs/c-gemini-r04",
        "tied_concepts": ["y05", "y03", "y09", "y08"],
    },
    "c-local-qwen38-27b-r04": {
        "stage": "r04-stage-c-v1",
        "definition_path": str(STAGE_C_PATH),
        "run_dir": "runs/experiments/r04b-local-qwen38-27b-20261030/runs/c-local-qwen38-27b-r04",
        "tied_concepts": ["y05", "y03", "y09", "y08"],
    },
}


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _exec_tool(
    registry, context: AgentContext, call_id: str, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    res = registry.execute(
        LLMToolCall(call_id=call_id, name=name, arguments=arguments),
        context,
    )
    if not res.ok:
        raise RuntimeError(
            f"Tool {name} ({call_id}) failed: {res.error.code}: {res.error.message}"
        )
    return res.result


def _build_node_commit(
    context: AgentContext,
    decide_set,
    *,
    inspect_leaves: bool = False,
    check_prior_node: str | None = None,
    reverse_commitments: bool = False,
) -> tuple[CommittedProtoInventory, list[dict[str, Any]]]:
    """Run the real survey -> preview -> commit tool sequence on `context`."""
    registry = default_tool_registry(inventory_protocol="full-payload")
    exchanges: list[dict[str, Any]] = []

    if check_prior_node is not None:
        prior_res = _exec_tool(
            registry,
            context,
            f"call-{context.node_id}-prior",
            "get_node_reconstruction",
            {"node_id": check_prior_node},
        )
        exchanges.append({"tool": "get_node_reconstruction", "result": prior_res})

    if inspect_leaves:
        search_res = _exec_tool(
            registry,
            context,
            f"call-{context.node_id}-search",
            "search_forms",
            {"scope": "available_tree", "limit": 100},
        )
        exchanges.append({"tool": "search_forms", "result": search_res})

    all_sets: list[dict[str, Any]] = []
    offset = 0
    node_ids: list[str] = []
    while True:
        survey = _exec_tool(
            registry,
            context,
            f"call-{context.node_id}-survey-{offset}",
            "summarize_correspondences",
            {"reading": "local", "min_support": 1, "limit": 50, "offset": offset},
        )
        exchanges.append({"tool": "summarize_correspondences", "result": survey})
        node_ids = list(survey["node_ids"])
        all_sets.extend(survey["sets"])
        if survey.get("next_offset") is None:
            break
        offset = survey["next_offset"]

    commitments: list[dict[str, Any]] = []
    for cset in all_sets:
        proto_segment, confidence, rationale = decide_set(cset, context, exchanges)
        commitments.append(
            {
                "set_id": cset["set_id"],
                "reflexes": list(cset["segments"]),
                "proto_segment": proto_segment,
                "confidence": confidence,
                "support": cset["support"],
                "rationale": rationale,
                "directionality_rationale": rationale,
            }
        )
    if reverse_commitments:
        commitments = list(reversed(commitments))

    preview_call_id = f"call-{context.node_id}-preview"
    preview_args = {
        "commitments": commitments,
        "residue_policy": "drop",
    }
    preview = _exec_tool(
        registry,
        context,
        preview_call_id,
        "test_proto_assembly",
        preview_args,
    )
    exchanges.append({"tool": "test_proto_assembly", "result": preview})

    commit_args = {
        "node_id": context.node_id,
        "inventory": {
            "child_node_ids": node_ids,
            "assembly_validation_call_id": preview_call_id,
            "commitments": commitments,
            "residue_policy": "drop",
        },
        "anomalies": [],
        "summary": f"Scripted two-level propagation commit for node {context.node_id}",
    }
    commit_res = _exec_tool(
        registry,
        context,
        f"call-{context.node_id}-commit",
        "commit_reconstruction",
        commit_args,
    )
    exchanges.append({"tool": "commit_reconstruction", "result": commit_res})
    return (
        CommittedProtoInventory.model_validate_json(
            json.dumps(commit_res["reconstruction"])
        ),
        exchanges,
    )


def _decide_y_comparative(cset: dict[str, Any], _context: AgentContext, _exchanges: list) -> tuple[str | None, float, str]:
    reflexes = tuple(cset["segments"])
    non_null = [r for r in reflexes if r is not None]
    if len(set(reflexes)) == 1 and reflexes[0] is not None:
        return reflexes[0], 0.95, f"Unanimous identity correspondence {reflexes[0]} across c and d."
    if set(non_null) == {"g"}:
        return (
            "g",
            0.85,
            "Complementary retention of *-g in clade y corroborated by outgroup a -k.",
        )
    if set(non_null) == {"t"}:
        return (
            None,
            0.50,
            "Genuine 2-vs-2 parsimony tie across tree (a,c have t; b,d have Ø).",
        )
    return non_null[0] if non_null else None, 0.50, "Fallback tie."


def _decide_x_leaf_outgroup_parsimony(
    cset: dict[str, Any],
    context: AgentContext,
    exchanges: list,
    *,
    tie_choice: str = "absent",
    over_retain_innovations: bool = False,
) -> tuple[str | None, float, str]:
    """Decision rule at `x` based on available outgroup evidence."""
    reflexes = tuple(cset["segments"])
    if len(set(reflexes)) == 1 and reflexes[0] is not None:
        return reflexes[0], 0.95, f"Unanimous identity correspondence {reflexes[0]} across a and b."
    if set(reflexes) == {"f", "p"}:
        return "p", 0.85, "Outgroups c and d both attest initial p; a innovated p > f / #_."
    non_null = [r for r in reflexes if r is not None]
    token = non_null[0]
    unit_id = cset["scope_id"]
    concept_id = cset["example_concept_ids"][0]

    # Check if reconstructed sister node y is available in context.evidence
    y_ev = next((ev for ev in context.evidence if ev.node_id == "y"), None)
    if y_ev is not None:
        y_form = next((f for f in y_ev.lexicon.forms if f.concept_id == concept_id), None)
        if y_form is not None and len(y_form.segments) >= 3:
            return (
                token,
                0.85,
                f"Reconstructed sister clade y ({' '.join(y_form.segments)}) attests final consonant on {unit_id}.",
            )

    # Otherwise only raw leaf outgroups c and d are available
    c_ev = next(ev for ev in context.evidence if ev.node_id == "c")
    d_ev = next(ev for ev in context.evidence if ev.node_id == "d")
    c_form = next((f for f in c_ev.lexicon.forms if f.concept_id == concept_id), None)
    d_form = next((f for f in d_ev.lexicon.forms if f.concept_id == concept_id), None)
    outgroup_coda_count = sum(
        1 for f in (c_form, d_form) if f is not None and len(f.segments) >= 3
    )
    if outgroup_coda_count == 2:
        return token, 0.85, f"Both leaf outgroups c and d attest final coda on {unit_id}."
    if outgroup_coda_count == 0:
        if over_retain_innovations:
            return (
                token,
                0.60,
                f"Over-retaining daughter a coda {token} on {unit_id} despite 0/2 outgroups.",
            )
        return (
            None,
            0.85,
            f"Neither outgroup c nor d attests final coda on {unit_id}; daughter innovation.",
        )
    # outgroup_coda_count == 1 -> 1-1 split in raw leaf outgroups (c, d)
    chosen = token if tie_choice == "retain" else None
    return (
        chosen,
        0.50,
        f"1-1 leaf outgroup split across (c, d) on {unit_id}; local tie at confidence 0.50.",
    )


def _decide_r_active_child_parsimony(
    cset: dict[str, Any],
    context: AgentContext,
    exchanges: list,
    *,
    use_leaf_witnesses: bool = False,
    identity_confidence: float = 0.95,
) -> tuple[str | None, float, str]:
    """Decision rule at root `r` comparing active children `x` and `y`."""
    reflexes = tuple(cset["segments"])
    if len(set(reflexes)) == 1 and reflexes[0] is not None:
        return reflexes[0], identity_confidence, f"Unanimous identity correspondence {reflexes[0]} across x and y."
    if set(reflexes) == {"k", "g"}:
        return (
            "k",
            0.90,
            "Regular across-clade velar correspondence <x k : y g> -> *k (y voiced *-k > *-g).",
        )
    non_null = [r for r in reflexes if r is not None]
    token = non_null[0]
    concept_id = cset["example_concept_ids"][0]
    if use_leaf_witnesses and reflexes == (None, "g"):
        a_ev = next(ev for ev in context.evidence if ev.node_id == "a")
        a_form = next((f for f in a_ev.lexicon.forms if f.concept_id == concept_id), None)
        if a_form is not None and a_form.segments[-1] == "k":
            return (
                "k",
                0.85,
                f"Leaf descendant a ({' '.join(a_form.segments)}) attests -k matching y's -g on {concept_id}.",
            )
    if reflexes == ("k", None):
        return (
            None,
            0.85,
            f"One-sided -k in x against open syllable in y on {concept_id}; clade/daughter-a innovation.",
        )
    return (
        None,
        0.50,
        f"One-sided {reflexes} at root r with no outgroup; 1-1 clade tie.",
    )


def _privileged_oracle_step_x(
    dataset,
    built,
    *,
    segments_only: bool = False,
) -> tuple[ReconstructionStep, dict[str, Any]]:
    """Build an explicitly labelled operator-control step at `x` from generator truth."""
    x_lexicon = next(l for l in built.answer_key.node_lexicons if l.variety_id == "x")
    a_lex = next(l for l in dataset.lexicons if l.variety_id == "a")
    b_lex = next(l for l in dataset.lexicons if l.variety_id == "b")
    input_beams = (make_leaf_beam(a_lex, beam_width=5), make_leaf_beam(b_lex, beam_width=5))

    distributions = []
    for form in sorted(x_lexicon.forms, key=lambda f: f.concept_id):
        if segments_only:
            analysis = FormAnalysis(
                claim="source",
                notes=("operator_privileged_synthetic_truth_segments_only",),
                pieces=(
                    EvidencePiece(
                        unit_id="whole:unknown",
                        cognate_set_id=None,
                        kind="whole",
                        segment_indices=tuple(range(len(form.segments))),
                        sources=(
                            PieceSource(
                                form_id=f"oracle:x:{form.concept_id}",
                                cognate_set_id=None,
                                segment_indices=tuple(range(len(form.segments))),
                            ),
                        ),
                    ),
                ),
            )
        else:
            cog_id = form.cognate_set_id or f"two_level_propagation_v1:{form.concept_id}"
            analysis = FormAnalysis(
                claim="source",
                notes=("operator_privileged_synthetic_truth_full",),
                pieces=(
                    EvidencePiece(
                        unit_id=f"cog:{cog_id}",
                        cognate_set_id=cog_id,
                        kind="whole",
                        segment_indices=tuple(range(len(form.segments))),
                        sources=(
                            PieceSource(
                                form_id=f"oracle:x:{form.concept_id}",
                                membership_id=f"oracle:x:{form.concept_id}:0",
                                cognate_set_id=cog_id,
                                segment_indices=tuple(range(len(form.segments))),
                            ),
                        ),
                    ),
                ),
            )
        candidate = ReconstructionCandidate(
            candidate_id=f"x:{form.concept_id}:0",
            segments=form.segments,
            log_score=0.0,
            probability=1.0,
            analysis=analysis,
            derivations=(
                CandidateDerivation(
                    derivation_id=f"oracle:x:{form.concept_id}:0",
                    child_candidate_ids=(
                        f"a:{form.concept_id}:0",
                        f"b:{form.concept_id}:0",
                    ),
                    supporting_child_ids=("a", "b"),
                    analysis=analysis,
                    note="Privileged operator control at x (synthetic generator truth).",
                ),
            ),
        )
        distributions.append(
            ConceptCandidateDistribution(
                concept_id=form.concept_id,
                candidates=(candidate,),
            )
        )
    output_beam = NodeBeamState(
        node_id="x",
        distributions=tuple(distributions),
        beam_width=5,
        source_child_ids=("a", "b"),
    )
    diagnostics = ReconstructionDiagnostics(
        rule_count=0,
        rule_complexity_cost=0,
        rule_results_evaluated=0,
        successful_applications=0,
        target_absent=0,
        context_mismatches=0,
        anchor_mismatches=0,
        applicable_rule_results=0,
        rule_coverage=0.0,
        anomaly_count=0,
        anomaly_rate=0.0,
        identity_reconstruction=False,
        concepts_available=len(distributions),
    )
    step = ReconstructionStep(
        parent_node_id="x",
        child_node_ids=("a", "b"),
        input_beams=input_beams,
        correspondence_maps=(),
        output_beam=output_beam,
        assembly_reports=(),
        anomaly_reports=(),
        diagnostics=diagnostics,
    )
    origin_meta = {
        "node_id": "x",
        "privileged_operator_control": True,
        "deployable_baseline": False,
        "origin": (
            "operator_privileged_synthetic_truth_segments_only"
            if segments_only
            else "operator_privileged_synthetic_truth_full"
        ),
        "preserves_unit_analysis": not segments_only,
    }
    return step, origin_meta


class _ScriptedNodeReconstructor:
    """Deterministic `NodeReconstructor` executing scripted tool sequences via `ProtoInventoryAssembler`."""

    def __init__(
        self,
        *,
        tied_confidence_threshold: float | None = None,
        x_tie_choice: str = "absent",
        x_over_retain_innovations: bool = False,
        r_use_leaf_witnesses: bool = False,
        r_identity_confidence: float = 0.95,
        x_privileged_step: ReconstructionStep | None = None,
        reverse_commitments: bool = False,
    ) -> None:
        self.aligner = LingPyAligner()
        self.assembler = ProtoInventoryAssembler(
            beam_width=5,
            aligner=self.aligner,
            tied_confidence_threshold=tied_confidence_threshold,
        )
        self.x_tie_choice = x_tie_choice
        self.x_over_retain_innovations = x_over_retain_innovations
        self.r_use_leaf_witnesses = r_use_leaf_witnesses
        self.r_identity_confidence = r_identity_confidence
        self.x_privileged_step = x_privileged_step
        self.reverse_commitments = reverse_commitments
        self.committed_by_node: dict[str, CommittedProtoInventory] = {}
        self.exchanges_by_node: dict[str, list[dict[str, Any]]] = {}
        self.context_by_node: dict[str, AgentContext] = {}
        self.prior_inventories: dict[str, Any] = {}

    def reconstruct(
        self,
        parent_node_id: str,
        children,
        *,
        rules=(),
        anomalies=(),
        anchors=(),
        evidence_context=None,
    ) -> ReconstructionStep:
        if parent_node_id == "x" and self.x_privileged_step is not None:
            return self.x_privileged_step
        child_beams = tuple(children)

        visible_priors = tuple(
            self.prior_inventories[item.node_id]
            for item in (evidence_context.available_nodes if evidence_context else ())
            if item.node_id in self.prior_inventories
        )
        context = AgentContext(
            node_id=parent_node_id,
            child_beams=child_beams,
            child_lexicons=tuple(beam_to_lexicon(c) for c in child_beams),
            aligner=self.aligner,
            anchors=tuple(anchors),
            evidence=evidence_context.available_nodes if evidence_context else (),
            concepts=evidence_context.concepts if evidence_context else (),
            prior_inventories=visible_priors,
        )
        self.context_by_node[parent_node_id] = context

        if parent_node_id == "y":
            inv, ex = _build_node_commit(
                context,
                _decide_y_comparative,
                reverse_commitments=self.reverse_commitments,
            )
        elif parent_node_id == "x":
            check_prior = "y" if any(ev.node_id == "y" for ev in context.evidence) else None
            inv, ex = _build_node_commit(
                context,
                lambda cset, ctx, exs: _decide_x_leaf_outgroup_parsimony(
                    cset,
                    ctx,
                    exs,
                    tie_choice=self.x_tie_choice,
                    over_retain_innovations=self.x_over_retain_innovations,
                ),
                check_prior_node=check_prior,
                reverse_commitments=self.reverse_commitments,
            )
        elif parent_node_id == "r":
            inv, ex = _build_node_commit(
                context,
                lambda cset, ctx, exs: _decide_r_active_child_parsimony(
                    cset,
                    ctx,
                    exs,
                    use_leaf_witnesses=self.r_use_leaf_witnesses,
                    identity_confidence=self.r_identity_confidence,
                ),
                inspect_leaves=self.r_use_leaf_witnesses,
                reverse_commitments=self.reverse_commitments,
            )
        else:
            raise ValueError(f"unexpected node {parent_node_id!r}")

        self.committed_by_node[parent_node_id] = inv
        self.exchanges_by_node[parent_node_id] = ex
        self.prior_inventories[parent_node_id] = summarize_commit(parent_node_id, inv)
        return self.assembler.reconstruct(
            parent_node_id,
            child_beams,
            inventory=inv,
            evidence_context=evidence_context,
        )


def _summarize_node_outcome(report, node_id: str, validity: TargetValidity) -> dict[str, Any]:
    target = next(
        t
        for t in report.targets
        if t.node_id == node_id and t.evaluation.target_validity is validity
    )
    ev = target.evaluation
    by_concept = {
        c.concept_id: {
            "top_segments": list(c.top_candidate_segments or ()),
            "target_segments": [list(s) for s in c.target_segment_alternatives],
            "top_exact": c.top_exact_match,
            "beam_exact": c.beam_exact_match,
            "cognate_unit_exact": (
                c.token_diagnostics.cognate_unit_exact
                if c.token_diagnostics is not None
                else None
            ),
            "morphology_status": (
                c.token_diagnostics.morphology_status
                if c.token_diagnostics is not None
                else None
            ),
            "ned": round(c.top_normalized_edit_distance or 0.0, 4),
        }
        for c in ev.concepts
    }
    mean_ned = (
        ev.graded.top_normalized_edit_distance.mean
        if ev.graded and ev.graded.top_normalized_edit_distance
        else 0.0
    )
    return {
        "node_id": node_id,
        "validity": validity.value,
        "evaluated_concepts": ev.evaluated_concepts,
        "top_exact_matches": ev.top_exact_matches,
        "beam_exact_matches": ev.beam_exact_matches,
        "mean_ned": round(mean_ned or 0.0, 4),
        "cognate_unit_exact_matches": sum(
            bool(c.token_diagnostics and c.token_diagnostics.cognate_unit_exact)
            for c in ev.concepts
        ),
        "concepts": by_concept,
    }


def _check_l2_root_restoration_rejection(r_context: AgentContext) -> dict[str, Any]:
    """Verify that attempting to restore `t` on `c012` at root `r` is refused when both children lack `t`."""
    registry = default_tool_registry(inventory_protocol="full-payload")
    survey = _exec_tool(
        registry,
        r_context,
        "call-r-l2-survey",
        "summarize_correspondences",
        {"reading": "local", "min_support": 1, "limit": 50},
    )
    commitments = [
        {
            "set_id": cset["set_id"],
            "reflexes": list(cset["segments"]),
            "proto_segment": cset["segments"][0] if cset["segments"][0] == cset["segments"][1] else None,
            "confidence": 0.9,
            "support": cset["support"],
            "directionality_rationale": "Identity column.",
        }
        for cset in survey["sets"]
    ]
    res = registry.execute(
        LLMToolCall(
            call_id="call-r-l2-restoration-check",
            name="test_proto_assembly",
            arguments={
                "commitments": commitments,
                "residue_policy": "drop",
                "restorations": [
                    {
                        "concept_id": "c012",
                        "before_column_index": 2,
                        "proto_segment": "t",
                        "unit_id": "cog:two_level_propagation_v1:c012",
                        "restored_from_node_ids": ["a", "c"],
                        "directionality_rationale": "Attempt to restore final -t on c012 from raw leaves a and c.",
                    }
                ],
            },
        ),
        r_context,
    )
    return {
        "ok": res.ok,
        "error_code": res.error.code if res.error else None,
        "error_message": res.error.message if res.error else None,
    }


def run_two_level_study() -> dict[str, Any]:
    suite = load_suite(SUITE_PATH)
    case = suite["cases"][0]
    built = build_case(case)

    arm_specs = [
        {
            "arm_id": "a1_single_winner_absent_on_tie",
            "description": "Ordinary single-winner assembly at x (1-1 leaf-outgroup ties on R1-R4 and L2 committed as null at 0.50); r uses active-child parsimony.",
            "privileged_operator_control": False,
            "tied_confidence_threshold": None,
            "x_tie_choice": "absent",
            "x_over_retain_innovations": False,
            "r_use_leaf_witnesses": False,
            "oracle_mode": None,
            "newick_override": None,
        },
        {
            "arm_id": "a2_single_winner_over_retain",
            "description": "Ordinary single-winner assembly where x over-retains -k on all <a k : b Ø> columns (including A1-A4); r discounts <x k : y Ø> -> null while retaining <x k : y g> -> *k.",
            "privileged_operator_control": False,
            "tied_confidence_threshold": None,
            "x_tie_choice": "retain",
            "x_over_retain_innovations": True,
            "r_use_leaf_witnesses": False,
            "oracle_mode": None,
            "newick_override": None,
        },
        {
            "arm_id": "b1_privileged_oracle_x_full",
            "description": "Option 1 operator control: x replaced by generator-truth forms + source FormAnalysis (cog:two_level_propagation_v1:c001..c012).",
            "privileged_operator_control": True,
            "tied_confidence_threshold": None,
            "x_tie_choice": "absent",
            "x_over_retain_innovations": False,
            "r_use_leaf_witnesses": False,
            "oracle_mode": "full",
            "newick_override": None,
        },
        {
            "arm_id": "b2_privileged_oracle_x_segments_only",
            "description": "Option 1 operator control: x replaced by generator-truth segment strings with whole:unknown analysis (no cognate_set_id).",
            "privileged_operator_control": True,
            "tied_confidence_threshold": None,
            "x_tie_choice": "absent",
            "x_over_retain_innovations": False,
            "r_use_leaf_witnesses": False,
            "oracle_mode": "segments_only",
            "newick_override": None,
        },
        {
            "arm_id": "c1_tied_beam_retention",
            "description": "Option 2a: exact same x and y commitments as a1, with tied_confidence_threshold=0.5 retaining competing proto-segments on <=0.50 commitments.",
            "privileged_operator_control": False,
            "tied_confidence_threshold": 0.5,
            "x_tie_choice": "absent",
            "x_over_retain_innovations": False,
            "r_use_leaf_witnesses": False,
            "oracle_mode": None,
            "newick_override": None,
        },
        {
            "arm_id": "c2_leaf_witness_at_r",
            "description": "Option 2b: single-winner assembly a1 at x and y, with r querying raw leaf witnesses (search_forms) and committing non-invertible <x Ø : y g> -> *k.",
            "privileged_operator_control": False,
            "tied_confidence_threshold": None,
            "x_tie_choice": "absent",
            "x_over_retain_innovations": False,
            "r_use_leaf_witnesses": True,
            "oracle_mode": None,
            "newick_override": None,
        },
        {
            "arm_id": "d1_tree_rotation_y_before_x",
            "description": "Option 3 tree rotation ((c,d)y,(a,b)x)r;: y reconstructs first and becomes a visible reconstructed outgroup for x.",
            "privileged_operator_control": False,
            "tied_confidence_threshold": None,
            "x_tie_choice": "absent",
            "x_over_retain_innovations": False,
            "r_use_leaf_witnesses": False,
            "oracle_mode": None,
            "newick_override": "((c,d)y,(a,b)x)r;",
        },
    ]

    arms_out: dict[str, Any] = {}
    for spec in arm_specs:
        payload = built.payload
        if spec["newick_override"] is not None:
            payload = payload.model_copy(update={"newick": spec["newick_override"]})
        dataset = ingest_payload(payload)

        oracle_step = None
        origin_meta = {
            "node_id": "x",
            "privileged_operator_control": False,
            "deployable_baseline": True,
            "origin": "committed_proto_inventory",
            "preserves_unit_analysis": True,
        }
        if spec["oracle_mode"] is not None:
            oracle_step, origin_meta = _privileged_oracle_step_x(
                dataset,
                built,
                segments_only=(spec["oracle_mode"] == "segments_only"),
            )

        reconstructor = _ScriptedNodeReconstructor(
            tied_confidence_threshold=spec["tied_confidence_threshold"],
            x_tie_choice=spec["x_tie_choice"],
            x_over_retain_innovations=spec["x_over_retain_innovations"],
            r_use_leaf_witnesses=spec["r_use_leaf_witnesses"],
            x_privileged_step=oracle_step,
        )
        traverser = TreeTraverser(beam_width=5, reconstructor=reconstructor)
        snapshot = traverser.traverse(dataset)
        steps_by_node = {step.parent_node_id: step for step in snapshot.steps}

        eval_report = evaluate_run(
            payload,
            result={"snapshot": {"steps": [s.model_dump(mode="json") for s in snapshot.steps]}},
            trajectories=(),
            selection_provenance={"arm_id": spec["arm_id"]},
        )
        r_decisions = score_decisions(
            {**case, "opportunities": case["opportunities_by_node"]["r"]},
            steps_by_node,
            model_committed={"r": True, "x": not spec["privileged_operator_control"], "y": True},
        )
        x_decisions = score_decisions(
            {**case, "opportunities": case["opportunities_by_node"]["x"]},
            steps_by_node,
            model_committed={"r": True, "x": not spec["privileged_operator_control"], "y": True},
        )

        r_step = steps_by_node["r"]
        x_step = steps_by_node["x"]
        y_step = steps_by_node["y"]
        r_l2_dist = next(d for d in r_step.output_beam.distributions if d.concept_id == "c012")
        x_l2_dist = next(d for d in x_step.output_beam.distributions if d.concept_id == "c012")

        restoration_check = None
        if spec["arm_id"] == "c2_leaf_witness_at_r":
            restoration_check = _check_l2_root_restoration_rejection(
                reconstructor.context_by_node["r"]
            )

        arms_out[spec["arm_id"]] = {
            "arm_id": spec["arm_id"],
            "description": spec["description"],
            "traversal_order": [s.parent_node_id for s in snapshot.steps],
            "origin_metadata": origin_meta,
            "tied_confidence_threshold": spec["tied_confidence_threshold"],
            "x_outgroup_node_ids": (
                sorted(
                    ev.node_id
                    for ev in reconstructor.context_by_node["x"].evidence
                    if ev.node_id not in ("a", "b")
                )
                if "x" in reconstructor.context_by_node
                else []
            ),
            "r_validated": _summarize_node_outcome(eval_report, "r", TargetValidity.VALIDATED),
            "r_underdetermined": _summarize_node_outcome(eval_report, "r", TargetValidity.UNDERDETERMINED),
            "x_validated": _summarize_node_outcome(eval_report, "x", TargetValidity.VALIDATED),
            "x_underdetermined": _summarize_node_outcome(eval_report, "x", TargetValidity.UNDERDETERMINED),
            "y_validated": _summarize_node_outcome(eval_report, "y", TargetValidity.VALIDATED),
            "r_decisions": {
                "primary_correct": r_decisions["primary"]["correct"],
                "primary_total": r_decisions["primary"]["planned_opportunities"],
                "matched_pairs_correct": r_decisions["matched_pairs"]["both_correct"],
                "matched_pairs_total": r_decisions["matched_pairs"]["planned"],
                "counts_by_reading": r_decisions["primary"]["readings"],
                "opportunities": r_decisions["opportunities"],
            },
            "x_decisions": {
                "primary_correct": x_decisions["primary"]["correct"],
                "primary_total": x_decisions["primary"]["planned_opportunities"],
                "matched_pairs_correct": x_decisions["matched_pairs"]["both_correct"],
                "matched_pairs_total": x_decisions["matched_pairs"]["planned"],
                "counts_by_reading": x_decisions["primary"]["readings"],
            },
            "beam_widths": {
                "x_multi_candidate_concepts": [
                    d.concept_id for d in x_step.output_beam.distributions if len(d.candidates) > 1
                ],
                "y_multi_candidate_concepts": [
                    d.concept_id for d in y_step.output_beam.distributions if len(d.candidates) > 1
                ],
                "r_multi_candidate_concepts": [
                    d.concept_id for d in r_step.output_beam.distributions if len(d.candidates) > 1
                ],
                "x_l2_candidates": [
                    {"segments": list(c.segments), "probability": round(c.probability, 4)}
                    for c in x_l2_dist.candidates
                ],
                "r_l2_candidates": [
                    {"segments": list(c.segments), "probability": round(c.probability, 4)}
                    for c in r_l2_dist.candidates
                ],
            },
            "work_metrics": {
                "x": x_step.diagnostics.assembly_work.model_dump(mode="json")
                if x_step.diagnostics.assembly_work
                else None,
                "y": y_step.diagnostics.assembly_work.model_dump(mode="json")
                if y_step.diagnostics.assembly_work
                else None,
                "r": r_step.diagnostics.assembly_work.model_dump(mode="json")
                if r_step.diagnostics.assembly_work
                else None,
            },
            "r_non_invertible_child_ids": list(
                reconstructor.committed_by_node["r"].non_invertible_child_ids
            ),
            "l2_root_restoration_check": restoration_check,
        }

    return arms_out


def run_presentation_invariance_checks() -> dict[str, Any]:
    """Option 3 equivalent-presentation vs real information-availability checks."""
    suite = load_suite(SUITE_PATH)
    case = suite["cases"][0]
    built = build_case(case)
    base_payload = built.payload

    rec_base = _ScriptedNodeReconstructor()
    snap_base = TreeTraverser(beam_width=5, reconstructor=rec_base).traverse(
        ingest_payload(base_payload)
    )
    steps_base = {s.parent_node_id: s for s in snap_base.steps}

    rec_rev_comm = _ScriptedNodeReconstructor(reverse_commitments=True)
    snap_rev_comm = TreeTraverser(beam_width=5, reconstructor=rec_rev_comm).traverse(
        ingest_payload(base_payload)
    )
    steps_rev_comm = {s.parent_node_id: s for s in snap_rev_comm.steps}

    swapped_payload = base_payload.model_copy(update={"newick": "((b,a)x,(c,d)y)r;"})
    rec_swap_child = _ScriptedNodeReconstructor()
    snap_swap_child = TreeTraverser(beam_width=5, reconstructor=rec_swap_child).traverse(
        ingest_payload(swapped_payload)
    )
    steps_swap_child = {s.parent_node_id: s for s in snap_swap_child.steps}

    a_lex = next(l for l in base_payload.lexicons if l.variety_id == "a")
    c001_form = next(f for f in a_lex.forms if f.concept_id == "c001")
    dup_single = a_lex.model_copy(
        update={
            "forms": (
                *a_lex.forms,
                c001_form.model_copy(update={"form_id": f"{c001_form.form_id}:dup"}),
            )
        }
    )
    beam_single_orig = make_leaf_beam(a_lex, beam_width=5)
    beam_single_dup = make_leaf_beam(dup_single, beam_width=5)
    c001_orig_cand = next(
        d for d in beam_single_orig.distributions if d.concept_id == "c001"
    ).candidates
    c001_dup_cand = next(
        d for d in beam_single_dup.distributions if d.concept_id == "c001"
    ).candidates

    alt_form = c001_form.model_copy(
        update={"form_id": f"{c001_form.form_id}:alt", "segments": ("f", "i")}
    )
    two_var_equal = LanguageLexicon(
        variety_id="a",
        name="a",
        forms=(c001_form, alt_form),
    )
    two_var_dup = LanguageLexicon(
        variety_id="a",
        name="a",
        forms=(
            c001_form,
            c001_form.model_copy(update={"form_id": f"{c001_form.form_id}:dup"}),
            alt_form,
        ),
    )
    beam_two_equal = make_leaf_beam(two_var_equal, beam_width=5)
    beam_two_dup = make_leaf_beam(two_var_dup, beam_width=5)

    def _top_forms(step: ReconstructionStep) -> dict[str, list[str]]:
        return {
            d.concept_id: list(d.candidates[0].segments)
            for d in step.output_beam.distributions
        }

    rec_tied_095 = _ScriptedNodeReconstructor(
        tied_confidence_threshold=0.5, r_identity_confidence=0.95
    )
    snap_tied_095 = TreeTraverser(beam_width=5, reconstructor=rec_tied_095).traverse(
        ingest_payload(base_payload)
    )
    r_step_095 = next(s for s in snap_tied_095.steps if s.parent_node_id == "r")
    l2_095 = next(d for d in r_step_095.output_beam.distributions if d.concept_id == "c012")

    rec_tied_100 = _ScriptedNodeReconstructor(
        tied_confidence_threshold=0.5, r_identity_confidence=1.0
    )
    snap_tied_100 = TreeTraverser(beam_width=5, reconstructor=rec_tied_100).traverse(
        ingest_payload(base_payload)
    )
    r_step_100 = next(s for s in snap_tied_100.steps if s.parent_node_id == "r")
    l2_100 = next(d for d in r_step_100.output_beam.distributions if d.concept_id == "c012")

    return {
        "commitment_order_reversal": {
            "declared_expectation": "strictly_invariant",
            "x_top_forms_identical": _top_forms(steps_base["x"]) == _top_forms(steps_rev_comm["x"]),
            "r_top_forms_identical": _top_forms(steps_base["r"]) == _top_forms(steps_rev_comm["r"]),
            "x_evidence_revision_identical": (
                rec_base.committed_by_node["x"].evidence_revision
                == rec_rev_comm.committed_by_node["x"].evidence_revision
            ),
        },
        "child_order_swap_ba_vs_ab": {
            "declared_expectation": "forms_and_probabilities_invariant_revision_hash_changes",
            "x_child_node_ids_base": list(steps_base["x"].child_node_ids),
            "x_child_node_ids_swapped": list(steps_swap_child["x"].child_node_ids),
            "x_evidence_revision_changed": (
                rec_base.committed_by_node["x"].evidence_revision
                != rec_swap_child.committed_by_node["x"].evidence_revision
            ),
            "x_top_forms_identical": _top_forms(steps_base["x"]) == _top_forms(steps_swap_child["x"]),
            "r_top_forms_identical": _top_forms(steps_base["r"]) == _top_forms(steps_swap_child["r"]),
        },
        "source_duplication": {
            "single_form_duplicate_expectation": "candidate_segments_and_probability_invariant_provenance_sources_lengthened",
            "single_form_candidate_count_orig": len(c001_orig_cand),
            "single_form_candidate_count_dup": len(c001_dup_cand),
            "single_form_probability_orig": round(c001_orig_cand[0].probability, 4),
            "single_form_probability_dup": round(c001_dup_cand[0].probability, 4),
            "single_form_source_count_orig": len(c001_orig_cand[0].analysis.pieces[0].sources),
            "single_form_source_count_dup": len(c001_dup_cand[0].analysis.pieces[0].sources),
            "two_variant_duplicate_expectation": "legitimate_prior_shift",
            "two_variant_equal_probs": {
                " ".join(c.segments): round(c.probability, 4)
                for c in beam_two_equal.distributions[0].candidates
            },
            "two_variant_duplicated_probs": {
                " ".join(c.segments): round(c.probability, 4)
                for c in beam_two_dup.distributions[0].candidates
            },
        },
        "operational_weight_sensitivity": {
            "description": "When unanimous identity columns carry confidence < 1.0 (e.g. 0.95), a 3-column tuple (k o t, k o t) pays an extra log(0.95) length penalty relative to a 2-column tuple (k o, k o); at identity_confidence=1.0 both candidates tie at exact 0.5 / 0.5.",
            "l2_r_candidates_at_identity_095": [
                {"segments": list(c.segments), "probability": round(c.probability, 4)}
                for c in l2_095.candidates
            ],
            "l2_r_decided_by_tie_break_at_095": decided_by_tie_break(l2_095),
            "l2_r_candidates_at_identity_100": [
                {"segments": list(c.segments), "probability": round(c.probability, 4)}
                for c in l2_100.candidates
            ],
            "l2_r_decided_by_tie_break_at_100": decided_by_tie_break(l2_100),
            "validated_r_top_forms_identical_095_vs_100": (
                {k: v for k, v in _top_forms(r_step_095).items() if k != "c012"}
                == {k: v for k, v in _top_forms(r_step_100).items() if k != "c012"}
            ),
        },
    }


def replay_banked_runs() -> dict[str, Any]:
    """Replay the 3 banked live-model commits at `x` under `threshold=None` vs `0.5` and propagate to `r`."""
    aligner = LingPyAligner()
    results: dict[str, Any] = {}

    for label, meta in BANKED_RUNS.items():
        case = load_explicit_case(meta["definition_path"])
        payload = build_explicit_case(case)
        dataset = ingest_payload(payload)
        lex_by_id = {l.variety_id: l for l in dataset.lexicons}
        child_beams_x = (
            make_leaf_beam(lex_by_id["a"], beam_width=5),
            make_leaf_beam(lex_by_id["b"], beam_width=5),
        )

        run_dir = Path(meta["run_dir"])
        cp = json.loads((run_dir / "checkpoint.json").read_text())
        banked_x_step = ReconstructionStep.model_validate_json(
            json.dumps(next(s for s in cp["completed_steps"] if s["parent_node_id"] == "x"))
        )
        traj_lines = [
            json.loads(line)
            for line in (run_dir / "trajectories.jsonl").read_text().splitlines()
            if line.strip()
        ]
        x_traj = next(t for t in traj_lines if t["node_id"] == "x")
        committed_x = CommittedProtoInventory.model_validate_json(
            json.dumps(x_traj["committed_reconstruction"])
        )

        asm_single = ProtoInventoryAssembler(
            beam_width=5, aligner=aligner, tied_confidence_threshold=None
        )
        asm_tied = ProtoInventoryAssembler(
            beam_width=5, aligner=aligner, tied_confidence_threshold=0.5
        )
        step_single = asm_single.reconstruct("x", child_beams_x, inventory=committed_x)
        step_tied = asm_tied.reconstruct("x", child_beams_x, inventory=committed_x)

        banked_beam_dump = banked_x_step.output_beam.model_dump(mode="json")
        single_beam_dump = step_single.output_beam.model_dump(mode="json")
        assert banked_beam_dump == single_beam_dump, f"single-winner replay mismatch on {label}"

        outgroup_ids = [v for v in sorted(lex_by_id) if v not in ("a", "b")]
        outgroup_beams = tuple(make_leaf_beam(lex_by_id[v], beam_width=5) for v in outgroup_ids)

        r_beams_single = (step_single.output_beam, *outgroup_beams)
        r_beams_tied = (step_tied.output_beam, *outgroup_beams)
        r_map_single, r_work_single = evidence_map(
            tuple(beam_to_lexicon(b) for b in r_beams_single), aligner
        )
        r_map_tied, r_work_tied = evidence_map(
            tuple(beam_to_lexicon(b) for b in r_beams_tied), aligner
        )

        tied_concept_details: dict[str, Any] = {}
        for cid in meta["tied_concepts"]:
            dist_s = next(d for d in step_single.output_beam.distributions if d.concept_id == cid)
            dist_t = next(d for d in step_tied.output_beam.distributions if d.concept_id == cid)
            r_alns_s = [a for a in r_map_single.alignments if a.concept_id == cid]
            r_alns_t = [a for a in r_map_tied.alignments if a.concept_id == cid]
            tied_concept_details[cid] = {
                "x_single_candidates": [
                    {"segments": list(c.segments), "probability": round(c.probability, 4)}
                    for c in dist_s.candidates
                ],
                "x_tied_candidates": [
                    {"segments": list(c.segments), "probability": round(c.probability, 4)}
                    for c in dist_t.candidates
                ],
                "x_single_decided_by_tie_break": decided_by_tie_break(dist_s),
                "x_tied_decided_by_tie_break": decided_by_tie_break(dist_t),
                "r_tuple_alignments_single": [
                    {m.variety_id: list(m.aligned_segments) for m in aln.members}
                    for aln in r_alns_s
                ],
                "r_tuple_alignments_tied": [
                    {m.variety_id: list(m.aligned_segments) for m in aln.members}
                    for aln in r_alns_t
                ],
            }

        non_tied_changed = [
            d_s.concept_id
            for d_s, d_t in zip(
                step_single.output_beam.distributions,
                step_tied.output_beam.distributions,
                strict=True,
            )
            if d_s.concept_id not in meta["tied_concepts"]
            and [c.segments for c in d_s.candidates] != [c.segments for c in d_t.candidates]
        ]

        results[label] = {
            "stage": meta["stage"],
            "run_dir": meta["run_dir"],
            "checkpoint_sha256": _sha256_file(run_dir / "checkpoint.json"),
            "trajectories_sha256": _sha256_file(run_dir / "trajectories.jsonl"),
            "single_winner_reproduces_banked_beam_exactly": banked_beam_dump == single_beam_dump,
            "low_confidence_commitments_count": sum(
                1 for c in committed_x.request.commitments if c.confidence <= 0.5
            ),
            "non_tied_concepts_changed_count": len(non_tied_changed),
            "r_evidence_work_single": r_work_single.model_dump(mode="json"),
            "r_evidence_work_tied": r_work_tied.model_dump(mode="json"),
            "tied_concepts": tied_concept_details,
        }

    return results


def build_study_payload() -> dict[str, Any]:
    return {
        "study_id": "two-level-propagation-and-robustness-v1",
        "fixture_path": str(SUITE_PATH),
        "fixture_sha256": _sha256_file(SUITE_PATH),
        "stage_b_sha256": _sha256_file(STAGE_B_PATH),
        "stage_c_sha256": _sha256_file(STAGE_C_PATH),
        "two_level_arms": run_two_level_study(),
        "presentation_invariance": run_presentation_invariance_checks(),
        "banked_live_replays": replay_banked_runs(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/research/propagation_robustness_study_results.json"),
        help="Path to write JSON study results.",
    )
    args = parser.parse_args()
    payload = build_study_payload()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Wrote {args.output} ({args.output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
