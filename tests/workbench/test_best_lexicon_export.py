"""`FamilyReconstructionResult.internal_nodes[].best_lexicon` keeps analyses.

Review finding 4: the public projection rebuilt each top form from its ID,
concept and segments and dropped the beam candidate's analysis. It must carry
the analysis as-is — never re-derive one from the spelling.
"""
import json
from pathlib import Path

from cognate_reconstruction.agent.orchestrator import AgentOrchestrator
from cognate_reconstruction.agent.reconstructor import AgenticNodeReconstructor
from cognate_reconstruction.agent.schemas import LLMMessage, LLMToolCall, MessageRole
from cognate_reconstruction.agent.service import FamilyReconstructionResult, ReconstructionService
from cognate_reconstruction.ingestion import ingest_payload
from cognate_reconstruction.schemas.evidence import EvidencePiece, FormAnalysis, PieceSource
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm
from cognate_reconstruction.synthesis.diagnostics import build_case, load_suite


def _form(child, concept, segments, pieces):
    fid = f"{child}:{concept}"
    return LexicalForm(form_id=fid, variety_id=child, concept_id=concept, segments=segments,
        analysis=FormAnalysis(claim="source", pieces=tuple(
            EvidencePiece(unit_id=unit, cognate_set_id=None if kind == "unknown" else unit,
                kind=kind, segment_indices=indices,
                sources=(PieceSource(form_id=fid, cognate_set_id=None if kind == "unknown" else unit,
                                     segment_indices=indices),))
            for unit, kind, indices in pieces)))


def _payload():
    # Both concepts surface as identical forms; only the analyses differ, and
    # concept "two" carries a piece the source leaves explicitly unknown.
    return WorkbenchPayload(newick="(A,B)P;", lexicons=tuple(
        LanguageLexicon(variety_id=child, name=child, forms=(
            _form(child, "one", (onset, "a"), (("core", "cognate", (0, 1)),)),
            _form(child, "two", (onset, "a"), (("stem", "cognate", (0,)),
                                               ("unknown:tail", "unknown", (1,)))),
        )) for child, onset in (("A", "p"), ("B", "f"))))


class _RetainingProvider:
    """Survey, preview, commit: every set keeps its first attested reflex."""

    model = "scripted/best-lexicon"

    def complete(self, messages, tools, **kwargs):
        calls = [m for m in messages if m.role is MessageRole.TOOL]
        for message in calls:
            assert json.loads(message.content)["ok"], message.content
        if not calls:
            name, args = "summarize_correspondences", {
                "reading": "local", "min_support": 1, "limit": 200, "include_outgroup": False}
        else:
            survey = json.loads(next(m.content for m in calls
                                     if m.name == "summarize_correspondences"))["result"]
            commitments = [{"set_id": s["set_id"], "reflexes": s["segments"], "support": s["support"],
                "proto_segment": next(x for x in s["segments"] if x is not None), "confidence": .9,
                "rationale": "scripted retention control",
                "directionality_rationale": "scripted control; polarity not identified"}
                for s in survey["sets"]]
            args = {"commitments": commitments, "residue_policy": "drop"}
            if not any(m.name == "test_proto_assembly" for m in calls):
                name = "test_proto_assembly"
            else:
                name = "commit_reconstruction"
                args = {"node_id": "P", "inventory": {"child_node_ids": survey["node_ids"], **args},
                        "anomalies": [], "summary": "Scripted retention control"}
        return LLMMessage(role=MessageRole.ASSISTANT,
                          tool_calls=(LLMToolCall(call_id=name, name=name, arguments=args),))


def _service(provider):
    return ReconstructionService(AgenticNodeReconstructor(
        AgentOrchestrator(provider, instructions="Offline scripted control.")))


def _assert_best_lexicon_matches_beam(result):
    assert result.internal_nodes
    for node in result.internal_nodes:
        by_concept = {form.concept_id: form for form in node.best_lexicon.forms}
        assert len(by_concept) == len(node.beam.distributions)
        for distribution in node.beam.distributions:
            top = distribution.candidates[0]
            exported = by_concept[distribution.concept_id]
            assert top.analysis is not None
            assert exported.form_id == top.candidate_id and exported.segments == top.segments
            assert exported.analysis == top.analysis


def _roundtrip(result):
    readback = FamilyReconstructionResult.model_validate_json(result.model_dump_json())
    assert [n.best_lexicon for n in readback.internal_nodes] == \
        [n.best_lexicon for n in result.internal_nodes]
    return readback


def test_best_lexicon_keeps_distinct_analyses_of_equal_surface_forms_and_unknown_pieces():
    result = _service(_RetainingProvider()).reconstruct_family(ingest_payload(_payload()))
    assert all(t.completed for t in result.trajectories)
    _assert_best_lexicon_matches_beam(result)
    readback = _roundtrip(result)
    forms = {f.concept_id: f for f in readback.internal_nodes[0].best_lexicon.forms}
    assert forms["one"].segments == forms["two"].segments == ("p", "a")
    assert forms["one"].analysis != forms["two"].analysis
    assert [(p.unit_id, p.kind, p.cognate_set_id) for p in forms["one"].analysis.pieces] == [
        ("core", "cognate", "core")]
    assert [(p.unit_id, p.kind, p.cognate_set_id) for p in forms["two"].analysis.pieces] == [
        ("stem", "cognate", "stem"), ("unknown:tail", "unknown", None)]
    # The unknown piece stays unknown: no cognacy is read off its spelling.
    unknown = forms["two"].analysis.pieces[1]
    assert all(source.cognate_set_id is None for source in unknown.sources)
    assert forms["two"].analysis.claim == "approved_assembly"
    assert forms["two"].analysis.order_status == "unresolved"
    assert forms["one"].analysis.order_status == "source"


def test_best_lexicon_keeps_model_order_claims():
    from tools.evidence_repair_controls import MorphologyProvider
    suite = load_suite(Path(__file__).resolve().parents[2] / "benchmarks/diagnostic/task02-v1.json")
    payload = build_case(next(c for c in suite["cases"] if c["case_id"] == "morphology")).payload
    result = _service(MorphologyProvider(payload, "reordered")).reconstruct_family(ingest_payload(payload))
    assert all(t.completed for t in result.trajectories)
    _assert_best_lexicon_matches_beam(result)
    readback = _roundtrip(result)
    for exported in readback.internal_nodes[0].best_lexicon.forms:
        assert exported.analysis.order_status == "model_claim"
        assert exported.analysis.claim == "approved_assembly"
        assert all(piece.sources for piece in exported.analysis.pieces)
