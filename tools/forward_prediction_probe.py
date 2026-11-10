"""Offline forward-prediction feasibility and withheld-data study probe (`r06-forward-v1`).

Executes the R06 withheld-daughter forward-prediction study on
`benchmarks/diagnostic/forward-prediction-v1.json` (plus a cross-check on R05's
`benchmarks/diagnostic/two-level-propagation-v1.json`), testing:
1. Etymon-cluster splitting (`r06-etymon-split-v1`) and shared cognate-unit leakage refusal.
2. Strict withholding of target-daughter test forms across payloads, alignments,
   correspondence inventories, search_forms, polarize, and assembly previews.
3. Native `ProtoInventoryAssembler` ancestor reconstruction from non-masked sisters `(b, c)`
   under intended (`*q`) vs observationally equivalent (`*ɢ`) ancestral labels.
4. Ten forward branch hypotheses (`h1`..`h10`, plus `h2b`, `h4b`, `h7b`, `h8b`, and an
   in-sample circularity control) across `development_in_sample` and `held_out_test`
   (`validated_only` vs `underdetermined_only`).
5. Non-invertibility of forward cascades containing mergers/deletions (`check_forward_cascade_invertibility`)
   and inventory-derived child-to-parent rules (`derive_branch_rules`).
6. DiaSim-inspired residual context autopsy (`build_residual_autopsy`), before/after
   rule-edit/reordering comparison (`compare_forward_hypotheses`), and PBEBench-style
   permutation ordering diagnostics (`evaluate_rule_order_permutations`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.schemas import LLMToolCall
from cognate_reconstruction.agent.tools import default_tool_registry
from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.evaluation.forward import (
    ETYMON_SPLIT_VERSION,
    FORWARD_EVALUATOR_VERSION,
    ForwardBranchHypothesis,
    ForwardLexicalException,
    build_etymon_cluster_split,
    check_forward_cascade_invertibility,
    compare_forward_hypotheses,
    compute_corpus_contrast_equivalence,
    evaluate_forward_split,
    evaluate_rule_order_permutations,
    mask_target_daughter_in_payload,
    verify_no_target_leakage,
)
from cognate_reconstruction.ingestion.service import ingest_payload
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.schemas.inventory import CommittedProtoInventory
from cognate_reconstruction.schemas.lexicon import LanguageLexicon
from cognate_reconstruction.schemas.traversal import (
    EvidenceKind,
    EvidenceRelation,
    NodeEvidence,
)
from cognate_reconstruction.synthesis.diagnostics import build_case, load_suite
from cognate_reconstruction.traversal.assembler import (
    ProtoInventoryAssembler,
    derive_branch_rules,
)
from cognate_reconstruction.traversal.beam import beam_to_lexicon, make_leaf_beam

SUITE_PATH = Path("benchmarks/diagnostic/forward-prediction-v1.json")
R05_SUITE_PATH = Path("benchmarks/diagnostic/two-level-propagation-v1.json")
DEFAULT_OUTPUT_PATH = Path("docs/research/forward_prediction_feasibility_results.json")


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


def _forms_dict(lexicon: LanguageLexicon) -> dict[str, tuple[str, ...]]:
    return {form.concept_id: form.segments for form in lexicon.forms}


def _reconstruct_ancestor_from_sisters(
    full_payload: WorkbenchPayload,
    *,
    dorsal_proto_symbol: str,
    sister_ids: tuple[str, ...] = ("b", "c"),
) -> tuple[dict[str, tuple[str, ...]], dict[str, Any], list[dict[str, Any]]]:
    """Reconstruct `*r` from non-masked sister daughters `(b, c)` using native tools and assembler."""
    sister_lexicons = tuple(
        lex for lex in full_payload.lexicons if lex.variety_id in set(sister_ids)
    )
    sister_payload = WorkbenchPayload(
        lexicons=sister_lexicons,
        concepts=full_payload.concepts,
        newick=f"({','.join(sister_ids)})r;",
        historical_form_bindings=(),
    )
    ingested = ingest_payload(sister_payload)
    aligner = LingPyAligner()
    assembler = ProtoInventoryAssembler(beam_width=3, aligner=aligner)

    child_beams = tuple(
        make_leaf_beam(lex, beam_width=3) for lex in ingested.lexicons
    )
    node_evidence = tuple(
        NodeEvidence(
            node_id=lex.variety_id,
            kind=EvidenceKind.OBSERVED,
            relation=EvidenceRelation.ACTIVE_CHILD,
            lexicon=lex,
            descendant_leaf_ids=(lex.variety_id,),
        )
        for lex in ingested.lexicons
    )
    agent_ctx = AgentContext(
        node_id="r",
        child_beams=child_beams,
        child_lexicons=ingested.lexicons,
        aligner=aligner,
        evidence=node_evidence,
        concepts=ingested.concepts,
    )
    registry = default_tool_registry(inventory_protocol="full-payload")
    exchanges: list[dict[str, Any]] = []

    all_concept_ids = [c.concept_id for c in ingested.concepts]
    align_res = _exec_tool(
        registry,
        agent_ctx,
        "call-r-alignments",
        "get_alignments",
        {"node_ids": list(sister_ids), "concept_ids": all_concept_ids, "detail": "summary"},
    )
    exchanges.append({"tool": "get_alignments", "result": align_res})

    search_res = _exec_tool(
        registry,
        agent_ctx,
        "call-r-search",
        "search_forms",
        {"scope": "available_tree", "limit": 100},
    )
    exchanges.append({"tool": "search_forms", "result": search_res})

    nodes_res = _exec_tool(
        registry,
        agent_ctx,
        "call-r-nodes",
        "list_available_nodes",
        {},
    )
    exchanges.append({"tool": "list_available_nodes", "result": nodes_res})

    all_sets: list[dict[str, Any]] = []
    offset = 0
    while True:
        survey = _exec_tool(
            registry,
            agent_ctx,
            f"call-r-survey-{offset}",
            "summarize_correspondences",
            {"reading": "local", "min_support": 1, "limit": 50, "offset": offset},
        )
        exchanges.append({"tool": "summarize_correspondences", "result": survey})
        all_sets.extend(survey["sets"])
        if survey.get("next_offset") is None:
            break
        offset = survey["next_offset"]

    commitments: list[dict[str, Any]] = []
    for cset in all_sets:
        b_seg, c_seg = cset["segments"]
        if b_seg == c_seg and b_seg is not None:
            proto_seg = b_seg
            conf = 0.95
            rat = f"Unanimous sister retention <b {b_seg} : c {c_seg}> -> *{proto_seg}."
        elif (b_seg, c_seg) == ("f", "p"):
            proto_seg = "p"
            conf = 0.90
            rat = "Sister c retains *p contrast against *f; sister b merged *p > f / #_."
        elif (b_seg, c_seg) == ("i", "e"):
            proto_seg = "i"
            conf = 0.90
            rat = "Sister b retains final *-i vs *-e; sister c merged i > e / _#."
        elif (b_seg, c_seg) == ("t", None):
            proto_seg = "t"
            conf = 0.90
            rat = "Sister b retains final *-t; sister c deleted final *-t > Ø / _#."
        elif (b_seg, c_seg) == ("ɢ", "ʔ"):
            proto_seg = dorsal_proto_symbol
            conf = 0.90
            rat = (
                f"Distinct dorsal correspondence <b ɢ : c ʔ> reconstructed as *{dorsal_proto_symbol} "
                "(observationally equivalent up to symbol relabelling)."
            )
        else:
            raise RuntimeError(f"Unexpected correspondence set in (b, c): {(b_seg, c_seg)}")

        commitments.append(
            {
                "set_id": cset["set_id"],
                "reflexes": [b_seg, c_seg],
                "proto_segment": proto_seg,
                "confidence": conf,
                "support": cset["support"],
                "rationale": rat,
                "directionality_rationale": rat,
            }
        )

    preview = _exec_tool(
        registry,
        agent_ctx,
        "call-r-preview",
        "test_proto_assembly",
        {"commitments": commitments, "residue_policy": "drop"},
    )
    exchanges.append({"tool": "test_proto_assembly", "result": preview})
    if not preview.get("commit_ready"):
        raise RuntimeError(f"Preview at r not commit_ready: {preview}")

    commit_res = _exec_tool(
        registry,
        agent_ctx,
        "call-r-commit",
        "commit_reconstruction",
        {
            "node_id": "r",
            "inventory": {
                "child_node_ids": list(sister_ids),
                "assembly_validation_call_id": "call-r-preview",
                "commitments": commitments,
                "residue_policy": "drop",
            },
            "anomalies": [],
            "summary": f"Comparative ancestor reconstruction from sisters (b, c) using dorsal label *{dorsal_proto_symbol}.",
        },
    )
    exchanges.append({"tool": "commit_reconstruction", "result": commit_res})
    committed = CommittedProtoInventory.model_validate_json(
        json.dumps(commit_res["reconstruction"])
    )

    step = assembler.reconstruct(
        "r",
        child_beams,
        inventory=committed,
    )
    reconstructed_lexicon = beam_to_lexicon(step.output_beam)
    derived = derive_branch_rules(
        committed.request.commitments,
        committed.request.child_node_ids,
    )
    inferred_forms = _forms_dict(reconstructed_lexicon)
    meta = {
        "dorsal_proto_symbol": dorsal_proto_symbol,
        "sister_ids": list(sister_ids),
        "committed_set_count": len(commitments),
        "derived_child_to_parent_rules": [
            {
                "source_child_ids": list(r.source_child_ids),
                "dsl": r.rule.source,
                "confidence": r.confidence,
            }
            for r in derived.rules
        ],
        "derived_non_invertible_child_ids": list(derived.non_invertible_child_ids),
        "concepts_available": step.diagnostics.concepts_available,
    }
    return inferred_forms, meta, exchanges


def _verify_masked_three_child_context(
    masked_payload: WorkbenchPayload,
) -> list[dict[str, Any]]:
    """Run tools on the 3-child masked payload `(a, b, c)r;` where `a` has only dev forms."""
    ingested = ingest_payload(masked_payload)
    aligner = LingPyAligner()
    child_beams = tuple(
        make_leaf_beam(lex, beam_width=3) for lex in ingested.lexicons
    )
    node_evidence = tuple(
        NodeEvidence(
            node_id=lex.variety_id,
            kind=EvidenceKind.OBSERVED,
            relation=EvidenceRelation.ACTIVE_CHILD,
            lexicon=lex,
            descendant_leaf_ids=(lex.variety_id,),
        )
        for lex in ingested.lexicons
    )
    agent_ctx = AgentContext(
        node_id="r",
        child_beams=child_beams,
        child_lexicons=ingested.lexicons,
        aligner=aligner,
        evidence=node_evidence,
        concepts=ingested.concepts,
    )
    registry = default_tool_registry(inventory_protocol="full-payload")
    exchanges: list[dict[str, Any]] = []
    all_concept_ids = [c.concept_id for c in ingested.concepts]
    for tool_name, args in (
        ("get_alignments", {"node_ids": ["a", "b", "c"], "concept_ids": all_concept_ids, "detail": "summary"}),
        ("search_forms", {"scope": "available_tree", "limit": 200}),
        ("list_available_nodes", {}),
        ("summarize_correspondences", {"reading": "local", "min_support": 1, "limit": 100, "offset": 0}),
    ):
        res = _exec_tool(registry, agent_ctx, f"masked-3child-{tool_name}", tool_name, args)
        exchanges.append({"tool": tool_name, "result": res})
    return exchanges


def _run_r05_forward_crosscheck() -> dict[str, Any]:
    """Cross-check forward reflex prediction on R05's `two-level-propagation-v1` branch `x -> a`."""
    suite = load_suite(R05_SUITE_PATH)
    case = suite["cases"][0]
    built = build_case(case)
    answer_key = built.answer_key
    node_lexicons = {lex.variety_id: _forms_dict(lex) for lex in answer_key.node_lexicons}
    branch_a = answer_key.branch("a")
    assert branch_a is not None
    all_cids = [f.concept_id for f in built.payload.concepts]
    etymon_map = {cid: cid for cid in all_cids}

    # In R05:
    # - Under a1 (single-winner absent on tie at x), x loses final -k on R1-R4 (c001-c004) and -t on L2 (c012).
    # - Under c1 (tied-beam retention at x, resolved with sister clade y at r) or d1 (tree rotation y before x),
    #   x retains *p i k, *t e k, *p a k, *t u k on c001-c004.
    x_forms_a1 = dict(node_lexicons["x"])
    for cid in ("c001", "c002", "c003", "c004"):
        x_forms_a1[cid] = x_forms_a1[cid][:-1]  # premature deletion of -k at x
    x_forms_c1_resolved = dict(node_lexicons["x"])

    hyp_x_to_a = ForwardBranchHypothesis(
        hypothesis_id="r05_branch_x_to_a",
        parent_node_id="x",
        child_node_id="a",
        direction="parent_to_child",
        ancestor_regime="inferred_ancestor",
        rule_sources=branch_a.rules,
    )
    eval_from_a1 = evaluate_forward_split(
        hyp_x_to_a,
        split_name="r05_from_a1_collapsed_x",
        concept_ids=all_cids,
        concept_to_etymon_id=etymon_map,
        ancestor_forms=x_forms_a1,
        target_daughter_forms=node_lexicons["a"],
    )
    eval_from_c1 = evaluate_forward_split(
        hyp_x_to_a,
        split_name="r05_from_c1_preserved_x",
        concept_ids=all_cids,
        concept_to_etymon_id=etymon_map,
        ancestor_forms=x_forms_c1_resolved,
        target_daughter_forms=node_lexicons["a"],
    )
    diff = compare_forward_hypotheses(eval_from_a1, eval_from_c1)
    return {
        "fixture_path": str(R05_SUITE_PATH),
        "fixture_sha256": _sha256_file(R05_SUITE_PATH),
        "branch": "x -> a",
        "forward_rules": list(branch_a.rules),
        "from_a1_collapsed_x_exact_count": eval_from_a1["all_planned"]["exact_count"],
        "from_a1_collapsed_x_exact_rate": eval_from_a1["all_planned"]["exact_rate"],
        "from_c1_preserved_x_exact_count": eval_from_c1["all_planned"]["exact_count"],
        "from_c1_preserved_x_exact_rate": eval_from_c1["all_planned"]["exact_rate"],
        "repaired_by_preserving_x_candidates": diff["repaired_concept_ids"],
        "newly_broken_concept_ids": diff["newly_broken_concept_ids"],
    }


def run_study() -> dict[str, Any]:
    suite = load_suite(SUITE_PATH)
    case = suite["cases"][0]
    built = build_case(case)
    full_payload = built.payload
    answer_key = built.answer_key

    concept_etymon_map: dict[str, str] = dict(case["concept_etymon_ids"])
    dev_cids: list[str] = list(case["development_concept_ids"])
    test_cids: list[str] = list(case["held_out_concept_ids"])
    validated_test_cids: list[str] = list(case["validated_held_out_concept_ids"])
    underdetermined_test_cids: list[str] = list(case["underdetermined_held_out_concept_ids"])
    all_cids = dev_cids + test_cids

    # 1. Build and verify etymon-cluster split (and verify that splitting t07/t08 is refused).
    etymon_split = build_etymon_cluster_split(
        concept_etymon_map,
        case["held_out_etymon_ids"],
        payload=full_payload,
    )
    leaky_map = dict(concept_etymon_map)
    leaky_map["t08"] = "etym_leaked_split"
    leaky_split_refused = False
    leaky_split_error = ""
    try:
        build_etymon_cluster_split(
            leaky_map,
            case["held_out_etymon_ids"],
            payload=full_payload,
        )
    except ValueError as exc:
        leaky_split_refused = True
        leaky_split_error = str(exc)

    # 2. Extract ground-truth node lexicons (operator/scorer-side only) and mask payload.
    node_lexicons = {
        lex.variety_id: _forms_dict(lex) for lex in answer_key.node_lexicons
    }
    gold_r_forms = node_lexicons["r"]
    gold_a_forms = node_lexicons["a"]
    sister_b_forms = node_lexicons["b"]
    sister_c_forms = node_lexicons["c"]

    withheld_a_test_forms = {cid: gold_a_forms[cid] for cid in test_cids}
    masked_payload = mask_target_daughter_in_payload(
        full_payload,
        target_daughter_id="a",
        masked_concept_ids=test_cids,
        drop_historical_bindings=True,
    )

    # 3. Reconstruct `*r` from non-masked sisters `(b, c)` under `*q` (intended) and `*ɢ` (equivalent).
    inferred_r_q, recon_meta_q, exchanges_q = _reconstruct_ancestor_from_sisters(
        masked_payload,
        dorsal_proto_symbol="q",
    )
    inferred_r_G, recon_meta_G, exchanges_G = _reconstruct_ancestor_from_sisters(
        masked_payload,
        dorsal_proto_symbol="ɢ",
    )
    masked_3child_exchanges = _verify_masked_three_child_context(masked_payload)

    leakage_audit_sister_payload = verify_no_target_leakage(
        masked_payload,
        target_daughter_id="a",
        withheld_forms=withheld_a_test_forms,
        answer_key=answer_key,
        tool_exchanges=exchanges_q + exchanges_G,
    )
    leakage_audit_3child_payload = verify_no_target_leakage(
        masked_payload,
        target_daughter_id="a",
        withheld_forms=withheld_a_test_forms,
        answer_key=answer_key,
        tool_exchanges=masked_3child_exchanges,
    )

    sister_forms_by_concept = {
        cid: {"b": sister_b_forms[cid], "c": sister_c_forms[cid]}
        for cid in all_cids
    }

    # 4. Non-invertibility analysis on branches a, b, c.
    branch_invertibility = {}
    for branch_ans in answer_key.branches:
        bid = branch_ans.node_id
        branch_invertibility[bid] = check_forward_cascade_invertibility(
            branch_ans.rules,
            gold_r_forms,
            node_lexicons[bid],
            parent_node_id="r",
            child_node_id=bid,
        )

    # 5. Define the hypotheses and controls to evaluate on dev and held-out test.
    hypotheses_spec: list[tuple[ForwardBranchHypothesis, dict[str, tuple[str, ...] | None], str]] = [
        (
            ForwardBranchHypothesis(
                hypothesis_id="h1_intended_cascade",
                parent_node_id="r",
                child_node_id="a",
                direction="parent_to_child",
                ancestor_regime="inferred_ancestor",
                rule_sources=(
                    "k > tʃ / _ i",
                    "i > e / _ #",
                    "t > Ø / _ #",
                    "q > x",
                    "w > v / # _",
                ),
                notes="Intended ordered forward cascade on *r inferred from sisters (b, c) with dorsal symbol *q.",
            ),
            inferred_r_q,
            "inferred_r_q",
        ),
        (
            ForwardBranchHypothesis(
                hypothesis_id="h2_equivalent_ancestral_label",
                parent_node_id="r",
                child_node_id="a",
                direction="parent_to_child",
                ancestor_regime="inferred_ancestor",
                rule_sources=(
                    "k > tʃ / _ i",
                    "i > e / _ #",
                    "t > Ø / _ #",
                    "ɢ > x",
                    "w > v / # _",
                ),
                notes="Observationally equivalent ancestral label *ɢ for <b ɢ : c ʔ> with forward rule ɢ > x.",
            ),
            inferred_r_G,
            "inferred_r_G",
        ),
        (
            ForwardBranchHypothesis(
                hypothesis_id="h2b_equivalent_two_stage_chronology",
                parent_node_id="r",
                child_node_id="a",
                direction="parent_to_child",
                ancestor_regime="inferred_ancestor",
                rule_sources=(
                    "k > tʃ / _ i",
                    "i > e / _ #",
                    "t > Ø / _ #",
                    "q > χ",
                    "χ > x",
                    "w > v / # _",
                ),
                notes="Observationally equivalent 2-stage intermediate chronology (q > χ > x) with unattested stage χ.",
            ),
            inferred_r_q,
            "inferred_r_q",
        ),
        (
            ForwardBranchHypothesis(
                hypothesis_id="h3_wrong_order_bleeding",
                parent_node_id="r",
                child_node_id="a",
                direction="parent_to_child",
                ancestor_regime="inferred_ancestor",
                rule_sources=(
                    "i > e / _ #",
                    "k > tʃ / _ i",
                    "t > Ø / _ #",
                    "q > x",
                    "w > v / # _",
                ),
                notes="Reversed bleeding order: i > e / _# runs before k > tʃ / _i, bleeding palatalization before final *-i.",
            ),
            inferred_r_q,
            "inferred_r_q",
        ),
        (
            ForwardBranchHypothesis(
                hypothesis_id="h4_overfit_dev_lookup",
                parent_node_id="r",
                child_node_id="a",
                direction="parent_to_child",
                ancestor_regime="inferred_ancestor",
                rule_sources=(
                    "i > e / _ #",
                    "k > tʃ / _ i",
                    "t > Ø / s a _ #",
                    "q > x / # _ a l",
                    "q > x / l a _ a",
                ),
                lexical_exceptions=(
                    ForwardLexicalException(
                        concept_id="d01",
                        override_segments=("p", "a", "tʃ", "e"),
                        note="Memorized development lexical override patching bled palatalization on d01.",
                    ),
                    ForwardLexicalException(
                        concept_id="d02",
                        override_segments=("f", "a", "tʃ", "e"),
                        note="Memorized development lexical override patching bled palatalization on d02.",
                    ),
                ),
                max_lexical_exceptions=1,
                notes="Overfit hypothesis: bleeding rule order patched by 2 lexical overrides on d01/d02 and dev-stem rules (8/8 dev fit, 1/8 held-out test).",
            ),
            inferred_r_q,
            "inferred_r_q",
        ),
        (
            ForwardBranchHypothesis(
                hypothesis_id="h4b_overfit_word_specific_zero_exceptions",
                parent_node_id="r",
                child_node_id="a",
                direction="parent_to_child",
                ancestor_regime="inferred_ancestor",
                rule_sources=(
                    "k > tʃ / p a _ i",
                    "k > tʃ / f a _ i",
                    "k > tʃ / # _ i t",
                    "i > e / _ #",
                    "t > Ø / s a _ #",
                    "q > x / # _ a l",
                    "q > x / l a _ a",
                ),
                max_lexical_exceptions=1,
                notes="Overfit rule-memorization control with 0 lexical exceptions: encodes individual dev word stems in rule contexts (8/8 dev fit, 1/8 held-out test).",
            ),
            inferred_r_q,
            "inferred_r_q",
        ),
        (
            ForwardBranchHypothesis(
                hypothesis_id="h5_naive_unscoped_inventory_rules",
                parent_node_id="r",
                child_node_id="a",
                direction="parent_to_child",
                ancestor_regime="inferred_ancestor",
                rule_sources=(
                    "i > e",
                    "k > tʃ",
                    "q > x",
                ),
                notes="Unscoped context-free rules (analogous to dropping conditioning/order in naive rule views): over-applies i > e and k > tʃ.",
            ),
            inferred_r_q,
            "inferred_r_q",
        ),
        (
            ForwardBranchHypothesis(
                hypothesis_id="h6_identity_from_inferred_proto",
                parent_node_id="r",
                child_node_id="a",
                direction="parent_to_child",
                ancestor_regime="inferred_ancestor",
                rule_sources=(),
                notes="Identity baseline from inferred proto-forms *r (empty forward cascade).",
            ),
            inferred_r_q,
            "inferred_r_q",
        ),
        (
            ForwardBranchHypothesis(
                hypothesis_id="h7_direct_sister_b_cascade",
                parent_node_id="b",
                child_node_id="a",
                direction="parent_to_child",
                ancestor_regime="direct_sister_baseline",
                rule_sources=(
                    "k > tʃ / _ i",
                    "i > e / _ #",
                    "t > Ø / _ #",
                    "ɢ > x",
                ),
                notes="Best direct single-sister cascade b -> a (cannot recover *p vs *f merged in b).",
            ),
            sister_b_forms,
            "sister_b",
        ),
        (
            ForwardBranchHypothesis(
                hypothesis_id="h7b_copy_sister_b",
                parent_node_id="b",
                child_node_id="a",
                direction="parent_to_child",
                ancestor_regime="direct_sister_baseline",
                rule_sources=(),
                notes="Raw copying baseline from observed sister b.",
            ),
            sister_b_forms,
            "sister_b",
        ),
        (
            ForwardBranchHypothesis(
                hypothesis_id="h8_direct_sister_c_cascade",
                parent_node_id="c",
                child_node_id="a",
                direction="parent_to_child",
                ancestor_regime="direct_sister_baseline",
                rule_sources=(
                    "k > tʃ / _ i",
                    "ʔ > x",
                ),
                notes="Best direct single-sister cascade c -> a (cannot recover *-i vs *-e merged in c).",
            ),
            sister_c_forms,
            "sister_c",
        ),
        (
            ForwardBranchHypothesis(
                hypothesis_id="h8b_copy_sister_c",
                parent_node_id="c",
                child_node_id="a",
                direction="parent_to_child",
                ancestor_regime="direct_sister_baseline",
                rule_sources=(),
                notes="Raw copying baseline from observed sister c.",
            ),
            sister_c_forms,
            "sister_c",
        ),
        (
            ForwardBranchHypothesis(
                hypothesis_id="h9_missing_output_and_would_empty",
                parent_node_id="r",
                child_node_id="a",
                direction="parent_to_child",
                ancestor_regime="inferred_ancestor",
                rule_sources=(
                    "k > tʃ / _ i",
                    "i > e / _ #",
                    "t > Ø / _ #",
                    "s a > Ø",
                ),
                notes="Partial-coverage and would_empty_form control: omits dorsal rule/outputs on t06-t08 and attempts whole-word deletion s a > Ø on d06.",
            ),
            {
                cid: (None if cid in ("t06", "t07", "t08") else inferred_r_q[cid])
                for cid in all_cids
            },
            "inferred_r_q_partial",
        ),
        (
            ForwardBranchHypothesis(
                hypothesis_id="h10_privileged_given_ancestor_oracle",
                parent_node_id="r",
                child_node_id="a",
                direction="parent_to_child",
                ancestor_regime="given_ancestor_control",
                privileged_operator_control=True,
                deployable_baseline=False,
                rule_sources=(
                    "k > tʃ / _ i",
                    "i > e / _ #",
                    "t > Ø / _ #",
                    "q > x",
                    "w > v / # _",
                ),
                notes="Privileged operator control (deployable_baseline=False): supplies generator-truth *r forms (including *w a l a on u01).",
            ),
            gold_r_forms,
            "gold_r_oracle",
        ),
    ]

    dev_evaluations: dict[str, dict[str, Any]] = {}
    test_evaluations: dict[str, dict[str, Any]] = {}
    summary_rows: list[dict[str, Any]] = []

    dev_anc_q = {cid: inferred_r_q[cid] for cid in dev_cids}
    dev_etymon_map = {cid: concept_etymon_map[cid] for cid in dev_cids}

    for hyp, anc_source, anc_label in hypotheses_spec:
        dev_eval = evaluate_forward_split(
            hyp,
            split_name="development_in_sample",
            concept_ids=dev_cids,
            concept_to_etymon_id=concept_etymon_map,
            ancestor_forms={cid: anc_source.get(cid) for cid in dev_cids},
            target_daughter_forms={cid: gold_a_forms[cid] for cid in dev_cids},
            underdetermined_concept_ids=(),
            sister_forms_by_concept=sister_forms_by_concept,
            reference_ancestor_forms={cid: gold_r_forms[cid] for cid in dev_cids},
            dev_ancestor_forms_for_complexity=dev_anc_q,
            dev_concept_to_etymon_id=dev_etymon_map,
        )
        test_eval = evaluate_forward_split(
            hyp,
            split_name="held_out_test",
            concept_ids=test_cids,
            concept_to_etymon_id=concept_etymon_map,
            ancestor_forms={cid: anc_source.get(cid) for cid in test_cids},
            target_daughter_forms={cid: gold_a_forms[cid] for cid in test_cids},
            underdetermined_concept_ids=underdetermined_test_cids,
            sister_forms_by_concept=sister_forms_by_concept,
            reference_ancestor_forms={cid: gold_r_forms[cid] for cid in test_cids},
            dev_ancestor_forms_for_complexity=dev_anc_q,
            dev_concept_to_etymon_id=dev_etymon_map,
        )
        dev_evaluations[hyp.hypothesis_id] = dev_eval
        test_evaluations[hyp.hypothesis_id] = test_eval

        summary_rows.append(
            {
                "hypothesis_id": hyp.hypothesis_id,
                "ancestor_regime": hyp.ancestor_regime,
                "ancestor_input": anc_label,
                "privileged_operator_control": hyp.privileged_operator_control,
                "deployable_baseline": hyp.deployable_baseline,
                "dev_exact_count": dev_eval["validated_only"]["exact_count"],
                "dev_exact_rate": dev_eval["validated_only"]["exact_rate"],
                "dev_mean_ned": dev_eval["validated_only"]["mean_ned"],
                "test_validated_exact_count": test_eval["validated_only"]["exact_count"],
                "test_validated_exact_rate": test_eval["validated_only"]["exact_rate"],
                "test_validated_conditional_exact_rate": test_eval["validated_only"]["conditional_available_exact_rate"],
                "test_validated_coverage": test_eval["validated_only"]["coverage"],
                "test_validated_mean_ned": test_eval["validated_only"]["mean_ned"],
                "test_underdetermined_u01_exact_count": test_eval["underdetermined_only"]["exact_count"],
                "test_all_planned_exact_count": test_eval["all_planned"]["exact_count"],
                "test_all_planned_exact_rate": test_eval["all_planned"]["exact_rate"],
                "test_proto_raw_exact_rate": test_eval["ancestor_evaluation"]["raw_exact_rate"],
                "test_proto_corpus_bcubed_f1": test_eval["ancestor_evaluation"]["corpus_bcubed_f1"],
                "test_proto_bijective_relabelling": test_eval["ancestor_evaluation"]["is_bijective_relabelling"],
                "rule_count": test_eval["complexity_report"]["rule_count"],
                "lexical_exception_count": test_eval["complexity_report"]["lexical_exception_count"],
                "exception_bound_exceeded": test_eval["complexity_report"]["exception_bound_exceeded"],
                "single_etymon_dev_rule_count": len(test_eval["complexity_report"]["single_etymon_dev_rule_ids"]),
                "description_token_complexity": test_eval["complexity_report"]["description_token_complexity"],
            }
        )

    # 6. In-sample circularity control: what happens if daughter `a` is NOT masked on `u01`
    # when inferring `*r` (using `<a v : b l : c l> -> *w`), and then predicting `a` back?
    circular_r_forms = dict(inferred_r_q)
    circular_r_forms["u01"] = ("w", "a", "l", "a")  # leaked from unmasked `a: v a l a`
    circular_eval = evaluate_forward_split(
        hypotheses_spec[0][0],  # h1_intended_cascade rules
        split_name="in_sample_circular_unmasked_check",
        concept_ids=test_cids,
        concept_to_etymon_id=concept_etymon_map,
        ancestor_forms=circular_r_forms,
        target_daughter_forms={cid: gold_a_forms[cid] for cid in test_cids},
        underdetermined_concept_ids=underdetermined_test_cids,
        sister_forms_by_concept=sister_forms_by_concept,
    )

    # 7. DiaSim-inspired before/after cascade comparisons:
    # (a) Reordering h3_wrong_order_bleeding -> h1_intended_cascade on dev and test
    reordering_diff_dev = compare_forward_hypotheses(
        dev_evaluations["h3_wrong_order_bleeding"],
        dev_evaluations["h1_intended_cascade"],
    )
    reordering_diff_test = compare_forward_hypotheses(
        test_evaluations["h3_wrong_order_bleeding"],
        test_evaluations["h1_intended_cascade"],
    )
    # (b) Adding `f > p / #_` to direct sister b cascade: repairs *p- words (t01, t03, t05)
    # but newly breaks *f- words (d02 on dev, t02 on test)!
    hyp_b_with_fp = ForwardBranchHypothesis(
        hypothesis_id="h7c_direct_sister_b_with_f_to_p",
        parent_node_id="b",
        child_node_id="a",
        direction="parent_to_child",
        ancestor_regime="direct_sister_baseline",
        rule_sources=(
            "f > p / # _",
            "k > tʃ / _ i",
            "i > e / _ #",
            "t > Ø / _ #",
            "ɢ > x",
        ),
        notes="Direct sister b cascade adding f > p / #_: repairs *p- words while breaking *f- words.",
    )
    eval_b_fp_test = evaluate_forward_split(
        hyp_b_with_fp,
        split_name="held_out_test",
        concept_ids=test_cids,
        concept_to_etymon_id=concept_etymon_map,
        ancestor_forms={cid: sister_b_forms[cid] for cid in test_cids},
        target_daughter_forms={cid: gold_a_forms[cid] for cid in test_cids},
        underdetermined_concept_ids=underdetermined_test_cids,
        sister_forms_by_concept=sister_forms_by_concept,
    )
    direct_b_edit_diff_test = compare_forward_hypotheses(
        test_evaluations["h7_direct_sister_b_cascade"],
        eval_b_fp_test,
    )

    # 8. Auxiliary PBEBench-style 4! = 24 rule-ordering check on the 4 core rules of `r -> a`.
    core_four_rules = (
        "k > tʃ / _ i",
        "i > e / _ #",
        "t > Ø / _ #",
        "q > x",
    )
    ordering_dev = evaluate_rule_order_permutations(
        core_four_rules,
        ancestor_forms={cid: inferred_r_q[cid] for cid in dev_cids},
        target_daughter_forms={cid: gold_a_forms[cid] for cid in dev_cids},
        concept_ids=dev_cids,
    )
    ordering_test = evaluate_rule_order_permutations(
        core_four_rules,
        ancestor_forms={cid: inferred_r_q[cid] for cid in validated_test_cids},
        target_daughter_forms={cid: gold_a_forms[cid] for cid in validated_test_cids},
        concept_ids=validated_test_cids,
    )

    # 9. Cross-check with R05's two-level propagation fixture.
    r05_crosscheck = _run_r05_forward_crosscheck()

    return {
        "study_id": "r06-forward-prediction-feasibility",
        "evaluator_version": FORWARD_EVALUATOR_VERSION,
        "etymon_split_version": ETYMON_SPLIT_VERSION,
        "primary_regime": "inferred_ancestor_masked_daughter",
        "fixture_path": str(SUITE_PATH),
        "fixture_sha256": _sha256_file(SUITE_PATH),
        "live_model_calls": 0,
        "paid_api_spend_usd": 0.0,
        "etymon_split": etymon_split.as_dict(),
        "leaky_etymon_split_check": {
            "leaky_split_refused": leaky_split_refused,
            "error_message": leaky_split_error,
        },
        "leakage_audits": {
            "sister_only_ancestor_inference": leakage_audit_sister_payload,
            "masked_three_child_context": leakage_audit_3child_payload,
        },
        "ancestor_reconstructions": {
            "intended_q_label": recon_meta_q,
            "equivalent_G_label": recon_meta_G,
            "q_vs_G_contrast_equivalence_on_all_17_concepts": compute_corpus_contrast_equivalence(
                inferred_r_G,
                inferred_r_q,
                all_cids,
            ),
        },
        "branch_invertibility": branch_invertibility,
        "summary_table": summary_rows,
        "in_sample_circularity_control": {
            "description": (
                "Unmasking daughter a on u01 (*w a l a -> v a l a) during ancestor inference "
                "allows <a v : b l : c l> to recover *w a l a and predict v a l a (1/1), "
                "whereas genuinely withholding a on u01 leaves <b l : c l> underdetermined (0/1)."
            ),
            "withheld_inferred_u01_exact": test_evaluations["h1_intended_cascade"]["underdetermined_only"]["exact_count"],
            "circular_unmasked_u01_exact": circular_eval["underdetermined_only"]["exact_count"],
            "privileged_given_oracle_u01_exact": test_evaluations["h10_privileged_given_ancestor_oracle"]["underdetermined_only"]["exact_count"],
        },
        "diasim_style_diagnostics": {
            "h3_bleeding_dev_residual_autopsy": dev_evaluations["h3_wrong_order_bleeding"]["residual_autopsy"],
            "reordering_h3_to_h1_dev_diff": reordering_diff_dev,
            "reordering_h3_to_h1_test_diff": reordering_diff_test,
            "direct_sister_b_add_f_to_p_test_diff": direct_b_edit_diff_test,
        },
        "pbebench_style_auxiliary_ordering": {
            "dev_permutations": {
                "rule_count": ordering_dev["rule_count"],
                "permutation_count": ordering_dev["permutation_count"],
                "exact_match_permutation_count": ordering_dev["exact_match_permutation_count"],
                "top_order": ordering_dev["permutation_ranking"][0],
                "worst_order": ordering_dev["permutation_ranking"][-1],
            },
            "test_permutations": {
                "rule_count": ordering_test["rule_count"],
                "permutation_count": ordering_test["permutation_count"],
                "exact_match_permutation_count": ordering_test["exact_match_permutation_count"],
                "top_order": ordering_test["permutation_ranking"][0],
                "worst_order": ordering_test["permutation_ranking"][-1],
            },
        },
        "r05_two_level_propagation_crosscheck": r05_crosscheck,
        "dev_evaluations": dev_evaluations,
        "test_evaluations": test_evaluations,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path to write JSON results.",
    )
    args = parser.parse_args()
    results = run_study()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {args.output} ({len(results['summary_table'])} hypothesis rows).")


if __name__ == "__main__":
    main()
