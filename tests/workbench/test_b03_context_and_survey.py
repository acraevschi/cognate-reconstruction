"""Offline unit tests for B03 survey filtering and watermark read-only compaction (`$0`, 0 live calls).

Covers:
  1. Exact `stored-hypothesis` tool-schema SHA-256 invariance (`628f0f32…`) alongside
     `stored-hypothesis-v2` registration of `SummarizeCorrespondencesV2Args`.
  2. `SummarizeCorrespondencesV2Args` & `min_attested_children` filtering across both
     `reading="recurrence"` (`csp-*`) and `reading="local"` (`csu-*`) on synthetic
     multi-daughter lexicons and real `burmish.payload.json` (`maruic`), plus
     `invalid-correspondence-filter` rejection when `min_attested_children > len(node_ids)`.
  3. Watermark-gated read-only page compaction (`_compact_watermark_read_only`) in
     `AgentOrchestrator`: 0 compactions below watermark, newest-2-per-tool verbatim
     retention above watermark, `>= 1024 B` net-savings threshold skipping tiny 0-row
     pages, uncompacted `trajectories.jsonl` (`audit`), `compacted_read_only_results`
     accounting & single-turn `watermark_trigger_count` deduplication when combined with
     preview compaction, `run_summary.json` persistence, and full re-execution (no
     `repeat_guard` block) when re-calling an earlier compacted read-only page.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from cognate_reconstruction import cli
from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.events import AgentEvent, AgentEventKind
from cognate_reconstruction.agent.instructions import load_agent_instructions
from cognate_reconstruction.agent.orchestrator import (
    MIN_READ_ONLY_COMPACTION_SAVINGS_BYTES,
    WATERMARK_COMPACTABLE_READ_ONLY_TOOLS,
    WATERMARK_READ_ONLY_KEEP_LIVE_PER_TOOL,
    AgentOrchestrator,
)
from cognate_reconstruction.agent.reconstructor import AgenticNodeReconstructor
from cognate_reconstruction.agent.schemas import (
    LLMMessage,
    LLMToolCall,
    MessageRole,
    ProviderResponse,
    ProviderResponseMetadata,
    ProviderUsage,
    SummarizeCorrespondencesArgs,
    SummarizeCorrespondencesV2Args,
)
from cognate_reconstruction.agent.service import ReconstructionService
from cognate_reconstruction.agent.tools import default_tool_registry
from cognate_reconstruction.agent.tools.correspondences import summarize_correspondences
from cognate_reconstruction.agent.tools.errors import ToolInputError
from cognate_reconstruction.agent.trajectory import (
    JsonlTrajectorySink,
    TrajectoryDatasetBuilder,
)
from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.ingestion import ingest_payload
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.traversal.beam import make_leaf_beam
from cognate_reconstruction.schemas.lexicon import (
    CognateMembership,
    CognateMembershipInterpretation,
    CognateMembershipProvenance,
    CognateMembershipScope,
    ConceptMetadata,
    LanguageLexicon,
    LexicalForm,
)

ROOT = Path(__file__).resolve().parents[2]
BURMISH_PAYLOAD_PATH = (
    ROOT / "runs/experiments/b02-burmish-gemini-benchmark/inputs/burmish.payload.json"
)
PINNED_STORED_HYPOTHESIS_TOOL_SCHEMA_SHA256 = (
    "628f0f32eca43a872c7fb72c90e67b1ba3e00b9a1f9b4057e1cf702175584a72"
)


def _tool_schema_sha256(inventory_protocol: str) -> str:
    reg = default_tool_registry(inventory_protocol=inventory_protocol)
    serialized = json.dumps(
        [d.model_dump(mode="json") for d in reg.definitions()],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _make_form(
    variety_id: str,
    concept_id: str,
    segments: tuple[str, ...],
    *,
    cog_id: str | None = None,
    memberships: tuple[CognateMembership, ...] = (),
    row: int = 1,
) -> LexicalForm:
    form_id = f"{variety_id}:{concept_id}:{row}"
    if memberships:
        effective_memberships = memberships
    elif cog_id is not None:
        effective_memberships = (
            CognateMembership(
                membership_id=f"{form_id}:m1",
                cognate_set_id=cog_id,
                scope=CognateMembershipScope.WHOLE_FORM,
                interpretation=CognateMembershipInterpretation.ASSERTED,
                segment_indices=(),
                provenance=CognateMembershipProvenance(
                    dataset_id="synth-b03",
                    source_table="CognateTable",
                    source_row=row,
                    source_cognateset_id=cog_id,
                ),
            ),
        )
    else:
        effective_memberships = ()
    return LexicalForm(
        form_id=form_id,
        variety_id=variety_id,
        concept_id=concept_id,
        segments=segments,
        cognate_set_id=cog_id if not memberships else None,
        cognate_memberships=effective_memberships,
    )


def _slice_membership(
    form_prefix: str,
    idx: int,
    cog_id: str,
    segment_indices: tuple[int, ...],
    *,
    row: int,
) -> CognateMembership:
    return CognateMembership(
        membership_id=f"{form_prefix}:m{idx}",
        cognate_set_id=cog_id,
        scope=CognateMembershipScope.SEGMENT_SLICE,
        interpretation=CognateMembershipInterpretation.PARTIAL_COGNATE,
        segment_indices=segment_indices,
        slice_unit="morpheme",
        provenance=CognateMembershipProvenance(
            dataset_id="synth-b03",
            source_table="CognateTable",
            source_row=row,
            source_cognateset_id=cog_id,
        ),
    )


def _build_synthetic_four_daughter_payload(concept_count: int = 18) -> WorkbenchPayload:
    """Build a 4-daughter node with 1-daughter compound prefixes, recurring stems, and multi-daughter singletons."""
    concepts = tuple(
        ConceptMetadata(concept_id=f"c{i:02d}", gloss=f"CONCEPT_{i:02d}")
        for i in range(1, concept_count + 1)
    )
    forms_by_lang: dict[str, list[LexicalForm]] = {
        "d1": [],
        "d2": [],
        "d3": [],
        "d4": [],
    }
    row = 1
    for i in range(1, concept_count + 1):
        cid = f"c{i:02d}"
        stem_cog = f"stem_{i:02d}"
        if i <= 4:
            # Recurring 1-daughter prefix `ʔ a` attested ONLY in `d1` (support >= 2, attested_children == 1),
            # plus 4-daughter stem `p a` (support >= 2, attested_children == 4).
            f_id = f"d1:{cid}:{row}"
            forms_by_lang["d1"].append(
                _make_form(
                    "d1",
                    cid,
                    ("ʔ", "ə", "p", "a"),
                    memberships=(
                        _slice_membership(f_id, 1, "solo_pref_d1", (0, 1), row=row),
                        _slice_membership(f_id, 2, stem_cog, (2, 3), row=row),
                    ),
                    row=row,
                )
            )
            row += 1
            for d in ("d2", "d3", "d4"):
                forms_by_lang[d].append(
                    _make_form(d, cid, ("p", "a"), cog_id=stem_cog, row=row)
                )
                row += 1
        elif i == 5:
            # Singleton 1-daughter compound morpheme ONLY in `d2` (support == 1, attested_children == 1)
            f_id = f"d2:{cid}:{row}"
            forms_by_lang["d2"].append(
                _make_form(
                    "d2",
                    cid,
                    ("k", "u", "t", "i"),
                    memberships=(
                        _slice_membership(f_id, 1, "solo_singleton_d2", (0, 1), row=row),
                        _slice_membership(f_id, 2, stem_cog, (2, 3), row=row),
                    ),
                    row=row,
                )
            )
            row += 1
            for d in ("d1", "d3", "d4"):
                forms_by_lang[d].append(
                    _make_form(d, cid, ("t", "i"), cog_id=stem_cog, row=row)
                )
                row += 1
        elif i == 6:
            # Multi-daughter singleton creaky vowel correspondence across 2 daughters (`d3`, `d4`)
            # with support == 1 and attested_children == 2!
            forms_by_lang["d3"].append(
                _make_form("d3", cid, ("m", "a̱"), cog_id=stem_cog, row=row)
            )
            row += 1
            forms_by_lang["d4"].append(
                _make_form("d4", cid, ("m", "ɔ̱"), cog_id=stem_cog, row=row)
            )
            row += 1
        elif i == 7:
            # 3-daughter singleton correspondence (`d1`, `d2`, `d3`) with support == 1, attested_children == 3
            for d, v in (("d1", "e̱"), ("d2", "e̱"), ("d3", "ɛ̱")):
                forms_by_lang[d].append(
                    _make_form(d, cid, ("n", v), cog_id=stem_cog, row=row)
                )
                row += 1
        else:
            # Distinct stems across remaining concepts so survey/alignment/search pages easily exceed 1024 B!
            cons = ("k", "s", "l", "ŋ", "t", "p")[i % 6]
            vow = ("a", "i", "u", "o", "e")[i % 5]
            tone = ("⁵⁵", "³¹", "³³")[i % 3]
            for d_idx, d in enumerate(("d1", "d2", "d3", "d4")):
                c_seg = "g" if (d_idx == 3 and cons == "k") else cons
                forms_by_lang[d].append(
                    _make_form(d, cid, (c_seg, vow, tone), cog_id=stem_cog, row=row)
                )
                row += 1

    lexicons = tuple(
        LanguageLexicon(
            variety_id=d,
            name=d.upper(),
            forms=tuple(forms_by_lang[d]),
        )
        for d in ("d1", "d2", "d3", "d4")
    )
    return WorkbenchPayload(
        newick="(d1,d2,d3,d4)proto_d;",
        concepts=concepts,
        lexicons=lexicons,
    )


# ===========================================================================
# 1. Registry Digest Invariance & `SummarizeCorrespondencesV2Args` Schema
# ===========================================================================


def test_stored_hypothesis_v1_preserves_pinned_tool_schema_digest() -> None:
    """`stored-hypothesis` v1 tool schemas must remain bit-for-bit identical to `628f0f32…`."""
    assert (
        _tool_schema_sha256("stored-hypothesis")
        == PINNED_STORED_HYPOTHESIS_TOOL_SCHEMA_SHA256
    )

    v1_reg = default_tool_registry(inventory_protocol="stored-hypothesis")
    v1_defs = {d.name: d for d in v1_reg.definitions()}
    assert (
        "min_attested_children"
        not in v1_defs["summarize_correspondences"].parameters["properties"]
    )
    assert "min_attested_children" not in v1_defs["summarize_correspondences"].description

    full_reg = default_tool_registry(inventory_protocol="full-payload")
    full_defs = {d.name: d for d in full_reg.definitions()}
    assert (
        "min_attested_children"
        not in full_defs["summarize_correspondences"].parameters["properties"]
    )

    with pytest.raises(ValueError, match="unknown inventory protocol"):
        default_tool_registry(inventory_protocol="nonexistent-protocol")


def test_stored_hypothesis_v2_exposes_summarize_correspondences_v2_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`stored-hypothesis-v2` wires `SummarizeCorrespondencesV2Args` and `StoredAssemblyV2Args`."""
    import cognate_reconstruction.agent.tools.stored_hypothesis as sh_mod

    # Allow testing `default_tool_registry("stored-hypothesis-v2")` even if `protocol-impl`
    # has not finished editing `stored_hypothesis.py` yet, while exercising the real
    # symbols automatically when present.
    if not hasattr(sh_mod, "StoredAssemblyV2Args"):
        monkeypatch.setattr(
            sh_mod, "StoredAssemblyV2Args", sh_mod.StoredAssemblyArgs, raising=False
        )
        monkeypatch.setattr(
            sh_mod, "test_stored_assembly_v2", sh_mod.test_stored_assembly, raising=False
        )
        monkeypatch.setattr(
            sh_mod,
            "describe_inventory_input_v2",
            sh_mod.describe_inventory_input,
            raising=False,
        )

    v2_reg = default_tool_registry(inventory_protocol="stored-hypothesis-v2")
    v2_defs = {d.name: d for d in v2_reg.definitions()}

    surv_def = v2_defs["summarize_correspondences"]
    props = surv_def.parameters["properties"]
    assert "min_attested_children" in props
    assert props["min_attested_children"]["default"] == 1
    assert props["min_attested_children"]["minimum"] == 1
    assert (
        "Use min_attested_children>=2 with min_support=1 to inspect multi-daughter singleton correspondences without 1-daughter compound noise."
        in surv_def.description
    )

    asm_def = v2_defs["test_proto_assembly"]
    assert (
        "Pass base_hypothesis_id to patch an earlier same-session preview incrementally via choices, shared_claims, drop_set_ids, or drop_pattern_ids."
        in asm_def.description
    )

    # Validate Pydantic bounds on `SummarizeCorrespondencesV2Args`:
    parsed_default = SummarizeCorrespondencesV2Args()
    assert parsed_default.min_attested_children == 1
    with pytest.raises(ValidationError):
        SummarizeCorrespondencesV2Args(min_attested_children=0)


# ===========================================================================
# 2. `min_attested_children` on Synthetic & Real Burmish (`maruic`) Evidence
# ===========================================================================


def test_min_attested_children_synthetic_recurrence_local_and_bounds_error() -> None:
    payload = _build_synthetic_four_daughter_payload(concept_count=10)
    ds = ingest_payload(payload)
    ctx = AgentContext(
        node_id="proto_d",
        child_lexicons=ds.lexicons,
        aligner=LingPyAligner(),
        concepts=ds.concepts,
    )

    for reading in ("recurrence", "local"):
        base = summarize_correspondences(
            SummarizeCorrespondencesArgs(reading=reading, min_support=1, limit=200),
            ctx,
            f"base-{reading}",
        )
        v2_att1 = summarize_correspondences(
            SummarizeCorrespondencesV2Args(
                reading=reading, min_support=1, min_attested_children=1, limit=200
            ),
            ctx,
            f"v2-att1-{reading}",
        )
        assert v2_att1.model_dump(exclude={"work", "outgroup_work"}) == base.model_dump(
            exclude={"work", "outgroup_work"}
        )

        # Synthetic data contains 1-daughter compound slices (`solo_pref_d1`, `solo_singleton_d2`):
        solo_rows = [
            s for s in base.sets if sum(1 for seg in s.segments if seg is not None) == 1
        ]
        assert len(solo_rows) >= 4

        v2_att2_sup2 = summarize_correspondences(
            SummarizeCorrespondencesV2Args(
                reading=reading, min_support=2, min_attested_children=2, limit=200
            ),
            ctx,
            f"v2-att2-sup2-{reading}",
        )
        v2_att2_sup1 = summarize_correspondences(
            SummarizeCorrespondencesV2Args(
                reading=reading, min_support=1, min_attested_children=2, limit=200
            ),
            ctx,
            f"v2-att2-sup1-{reading}",
        )
        assert all(
            sum(1 for seg in s.segments if seg is not None) >= 2
            for s in v2_att2_sup1.sets
        )
        assert v2_att2_sup1.matched_set_count == len(base.sets) - len(solo_rows)
        assert v2_att2_sup1.suppressed_below_min_support == 0
        # Accounting identity across min_support under fixed min_attested_children=2:
        assert (
            v2_att2_sup2.matched_set_count + v2_att2_sup2.suppressed_below_min_support
            == v2_att2_sup1.matched_set_count
        )

        # Multi-daughter creaky singleton (`m a̱` / `m ɔ̱` on `d3`/`d4`) survives `min_attested_children=2`!
        assert any(
            tuple(s.segments) == (None, None, "a̱", "ɔ̱") and s.support == 1
            for s in v2_att2_sup1.sets
        )

        # `min_attested_children=3` drops 2-daughter rows and keeps 3+ daughter rows:
        v2_att3 = summarize_correspondences(
            SummarizeCorrespondencesV2Args(
                reading=reading, min_support=1, min_attested_children=3, limit=200
            ),
            ctx,
            f"v2-att3-{reading}",
        )
        assert all(
            sum(1 for seg in s.segments if seg is not None) >= 3 for s in v2_att3.sets
        )
        assert not any(
            tuple(s.segments) == (None, None, "a̱", "ɔ̱") for s in v2_att3.sets
        )
        assert any(
            tuple(s.segments) == ("e̱", "e̱", "ɛ̱", None) for s in v2_att3.sets
        )

    # Exceeding selected node count raises `ToolInputError` with `code="invalid-correspondence-filter"`:
    with pytest.raises(ToolInputError) as exc_info:
        summarize_correspondences(
            SummarizeCorrespondencesV2Args(min_attested_children=5),
            ctx,
            "too-many-children",
        )
    assert exc_info.value.code == "invalid-correspondence-filter"
    assert "min_attested_children=5 exceeds selected node count (4)" in str(
        exc_info.value
    )
    assert exc_info.value.remediation is not None

    # Narrowing `node_ids` to 2 nodes makes `min_attested_children=3` fail with count `(2)`:
    with pytest.raises(ToolInputError) as exc_narrow:
        summarize_correspondences(
            SummarizeCorrespondencesV2Args(
                node_ids=("d1", "d2"), min_attested_children=3
            ),
            ctx,
            "too-many-for-subset",
        )
    assert exc_narrow.value.code == "invalid-correspondence-filter"
    assert "min_attested_children=3 exceeds selected node count (2)" in str(
        exc_narrow.value
    )


@pytest.mark.skipif(
    not BURMISH_PAYLOAD_PATH.exists(),
    reason="Real Burmish benchmark payload not present in checkout",
)
def test_burmish_maruic_min_attested_children_excludes_compound_singletons_and_surfaces_creaky_vowels() -> None:
    """Verify exact `maruic` recurrence & local counts on `burmish.payload.json`."""
    payload = WorkbenchPayload.model_validate_json(
        BURMISH_PAYLOAD_PATH.read_text(encoding="utf-8")
    )
    ds = ingest_payload(payload)
    maruic_children = (
        "hillburmish:Atsi",
        "hillburmish:Bola",
        "hillburmish:Lashi",
        "hillburmish:Maru",
    )
    lex_by_id = {lex.variety_id: lex for lex in ds.lexicons}
    ctx = AgentContext(
        node_id="maruic",
        child_lexicons=tuple(lex_by_id[cid] for cid in maruic_children),
        aligner=LingPyAligner(),
        concepts=ds.concepts,
    )

    # 1) Default `min_support=2` (`min_attested_children=1` vs `2`):
    rec_sup2_att1 = summarize_correspondences(
        SummarizeCorrespondencesV2Args(
            reading="recurrence",
            min_support=2,
            min_attested_children=1,
            include_outgroup=False,
            limit=200,
        ),
        ctx,
        "maruic-sup2-att1",
    )
    rec_sup2_att2 = summarize_correspondences(
        SummarizeCorrespondencesV2Args(
            reading="recurrence",
            min_support=2,
            min_attested_children=2,
            include_outgroup=False,
            limit=200,
        ),
        ctx,
        "maruic-sup2-att2",
    )
    assert rec_sup2_att1.total_set_count == 320
    assert rec_sup2_att1.matched_set_count == 113
    # Excludes all 67 1-daughter compound/affix patterns (`113 -> 46`)!
    assert rec_sup2_att2.matched_set_count == 46
    assert rec_sup2_att1.matched_set_count - rec_sup2_att2.matched_set_count == 67
    assert rec_sup2_att2.suppressed_below_min_support == 150

    # 2) `reading="recurrence", min_support=1, min_attested_children=2` across all pages:
    all_att2_sup1 = []
    offset = 0
    while True:
        page = summarize_correspondences(
            SummarizeCorrespondencesV2Args(
                reading="recurrence",
                min_support=1,
                min_attested_children=2,
                include_outgroup=False,
                limit=200,
                offset=offset,
            ),
            ctx,
            f"maruic-sup1-att2-{offset}",
        )
        all_att2_sup1.extend(page.sets)
        if page.next_offset is None:
            break
        offset = page.next_offset

    assert len(all_att2_sup1) == 196  # 46 (support>=2) + 150 (support==1)
    assert all(
        sum(1 for seg in item.segments if seg is not None) >= 2
        for item in all_att2_sup1
    )
    # Surfaces multi-daughter `support == 1` creaky-vowel (`V̱`, U+0331) correspondences!
    creaky_singletons = [
        item
        for item in all_att2_sup1
        if item.support == 1
        and any(seg is not None and "\u0331" in seg for seg in item.segments)
    ]
    assert len(creaky_singletons) == 24

    # 3) `reading="local", min_support=1, min_attested_children=2` also filters `csu-*` sets cleanly:
    loc_att1 = summarize_correspondences(
        SummarizeCorrespondencesV2Args(
            reading="local",
            min_support=1,
            min_attested_children=1,
            include_outgroup=False,
            limit=200,
        ),
        ctx,
        "maruic-loc-att1",
    )
    loc_att2 = summarize_correspondences(
        SummarizeCorrespondencesV2Args(
            reading="local",
            min_support=1,
            min_attested_children=2,
            include_outgroup=False,
            limit=200,
        ),
        ctx,
        "maruic-loc-att2",
    )
    assert loc_att2.matched_set_count < loc_att1.matched_set_count
    assert all(
        sum(1 for seg in item.segments if seg is not None) >= 2
        for item in loc_att2.sets
    )


# ===========================================================================
# 3. Watermark-Gated Read-Only Page Compaction in `AgentOrchestrator`
# ===========================================================================


def test_watermark_read_only_compaction_zero_below_watermark() -> None:
    """Below `compaction_watermark_tokens`, 3+ read-only pages stay 100% uncompacted."""
    payload = _build_synthetic_four_daughter_payload(concept_count=18)
    ds = ingest_payload(payload)
    ctx = AgentContext(
        node_id="proto_d",
        child_lexicons=ds.lexicons,
        aligner=LingPyAligner(),
        concepts=ds.concepts,
    )
    observed_prompts: list[list[dict[str, Any]]] = []

    class _BelowWatermarkSurveyProvider:
        model = "scripted/below-wm-survey"

        def complete(self, messages, tools, **kwargs):
            observed_prompts.append([m.model_dump(mode="json") for m in messages])
            turn = len(observed_prompts)
            if turn in (1, 2, 3, 4):
                call = LLMToolCall(
                    call_id=f"surv-page-{turn}",
                    name="summarize_correspondences",
                    arguments={
                        "reading": "local",
                        "min_support": 1,
                        "offset": (turn - 1) * 8,
                        "limit": 8,
                    },
                )
            elif turn == 5:
                call = LLMToolCall(
                    call_id="prev-empty",
                    name="test_proto_assembly",
                    arguments={"choices": [], "residue_policy": "drop"},
                )
            else:
                hyp_id = json.loads(messages[-1].content)["result"]["hypothesis_id"]
                call = LLMToolCall(
                    call_id="commit-done",
                    name="commit_reconstruction",
                    arguments={
                        "node_id": "proto_d",
                        "hypothesis_id": hyp_id,
                        "anomalies": [],
                        "summary": "Below-watermark commit.",
                    },
                )
            return ProviderResponse(
                message=LLMMessage(role=MessageRole.ASSISTANT, tool_calls=(call,)),
                metadata=ProviderResponseMetadata(
                    provider_id="fake",
                    model_id=self.model,
                    usage=ProviderUsage(
                        input_tokens=5_000, output_tokens=50, total_tokens=5_050
                    ),
                ),
            )

    orch = AgentOrchestrator(
        _BelowWatermarkSurveyProvider(),
        registry=default_tool_registry(inventory_protocol="stored-hypothesis"),
        instructions=load_agent_instructions(),
        compaction_watermark_tokens=256_000,
    )
    res = orch.run(ctx)
    assert res.trajectory.completed is True
    comp = orch.compaction_summary()
    assert comp["watermark_trigger_count"] == 0
    assert comp["compacted_read_only_results"] == 0
    assert comp["compacted_preview_results"] == 0
    assert comp["compacted_tool_results"] == 0
    # Every prompt prefix matches the next turn's prompt prefix byte-for-byte:
    for idx in range(len(observed_prompts) - 1):
        prev_msgs = observed_prompts[idx]
        assert observed_prompts[idx + 1][: len(prev_msgs)] == prev_msgs


class _ListEventSink:
    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    def emit(self, event: AgentEvent) -> None:
        self.events.append(event)


def test_watermark_read_only_compaction_keeps_newest_two_skips_tiny_allows_recall_and_preserves_audit(
    tmp_path: Path,
) -> None:
    """Above watermark:
    - Keeps newest `2` accepted (`ok=True`) live pages per tool (`summarize_correspondences`,
      `get_alignments`, `search_forms`) verbatim.
    - Compacts `3rd+` older pages when `live_bytes - stub_bytes >= 1024`.
    - Skips `< 1024 B` tiny 0-row pages (preserving early prefix cache).
    - Keeps `ok=False` errors untouched and excluded from live counts.
    - Deduplicates `watermark_trigger_count` (`+1`, not `+2`) when preview + read-only
      compaction fire on the same watermark check.
    - Allows re-calling an earlier compacted read-only page without triggering `repeat_guard`,
      returning full uncompacted rows.
    - Leaves `trajectories.jsonl` (`audit`) 100% uncompacted and writes `compacted_read_only_results`
      into `run_summary.json` shape (`orch.compaction_summary()`).
    """
    assert WATERMARK_READ_ONLY_KEEP_LIVE_PER_TOOL == 2
    assert MIN_READ_ONLY_COMPACTION_SAVINGS_BYTES == 1024
    assert WATERMARK_COMPACTABLE_READ_ONLY_TOOLS == frozenset(
        {"summarize_correspondences", "get_alignments", "search_forms"}
    )

    payload = _build_synthetic_four_daughter_payload(concept_count=18)
    ds = ingest_payload(payload)
    ctx = AgentContext(
        node_id="proto_d",
        child_lexicons=ds.lexicons,
        aligner=LingPyAligner(),
        concepts=ds.concepts,
    )
    traj_path = tmp_path / "trajectories.jsonl"
    events = _ListEventSink()
    observed_prompts: list[list[LLMMessage]] = []
    first_survey_sets: list[dict[str, Any]] = []

    class _ReadOnlyCompactionProvider:
        model = "scripted/read-only-watermark"

        def complete(self, messages, tools, **kwargs):
            nonlocal first_survey_sets
            observed_prompts.append(list(messages))
            turn = len(observed_prompts)

            if turn == 1:
                # Tiny 0-row survey page (`< 1024 B`, e.g., ~950 B) -> MUST NEVER be compacted!
                in_tok = 100
                calls = (
                    LLMToolCall(
                        call_id="surv-tiny-0row",
                        name="summarize_correspondences",
                        arguments={
                            "reading": "local",
                            "segment": "NONEXISTENT_SEG",
                            "include_outgroup": False,
                            "limit": 5,
                        },
                    ),
                )
            elif turn == 2:
                # 3 substantial disjoint `summarize_correspondences` pages (`> 1024 B` savings each)
                # + 1 rejected `summarize_correspondences` call (`ok=false`), still below watermark (200 < 500):
                in_tok = 200
                calls = (
                    LLMToolCall(
                        call_id="surv-page-1",
                        name="summarize_correspondences",
                        arguments={
                            "reading": "local",
                            "min_support": 1,
                            "offset": 0,
                            "limit": 12,
                        },
                    ),
                    LLMToolCall(
                        call_id="surv-bad",
                        name="summarize_correspondences",
                        arguments={
                            "reading": "local",
                            "segment": "p",
                            "segment_node_id": "unknown_child",
                        },
                    ),
                    LLMToolCall(
                        call_id="surv-page-2",
                        name="summarize_correspondences",
                        arguments={
                            "reading": "local",
                            "min_support": 1,
                            "offset": 12,
                            "limit": 12,
                        },
                    ),
                    LLMToolCall(
                        call_id="surv-page-3",
                        name="summarize_correspondences",
                        arguments={
                            "reading": "local",
                            "min_support": 1,
                            "offset": 24,
                            "limit": 12,
                        },
                    ),
                )
            elif turn == 3:
                # Capture `surv-page-1` sets while still uncompacted below watermark!
                for m in messages:
                    if m.role is MessageRole.TOOL and m.tool_call_id == "surv-page-1":
                        first_survey_sets = json.loads(m.content)["result"]["sets"]
                assert len(first_survey_sets) == 12
                # Add 3 `get_alignments` pages + 3 `search_forms` pages + 1st substantial preview (`prev-1`),
                # STILL below watermark (`350 < 500`):
                in_tok = 350
                prev1_choices = [
                    {
                        "set_id": s["set_id"],
                        "proto_segment": next(
                            seg for seg in s["segments"] if seg is not None
                        ),
                        "confidence": 0.8,
                        "rationale": "Draft 1.",
                        "directionality_rationale": "Retention.",
                    }
                    for s in first_survey_sets
                ]
                calls = (
                    LLMToolCall(
                        call_id="align-1",
                        name="get_alignments",
                        arguments={
                            "node_ids": ["d1", "d2", "d3", "d4"],
                            "concept_ids": ["c01", "c02", "c03", "c04"],
                            "detail": "full",
                        },
                    ),
                    LLMToolCall(
                        call_id="align-2",
                        name="get_alignments",
                        arguments={
                            "node_ids": ["d1", "d2", "d3", "d4"],
                            "concept_ids": ["c08", "c09", "c10", "c11"],
                            "detail": "full",
                        },
                    ),
                    LLMToolCall(
                        call_id="align-3",
                        name="get_alignments",
                        arguments={
                            "node_ids": ["d1", "d2", "d3", "d4"],
                            "concept_ids": ["c12", "c13", "c14", "c15"],
                            "detail": "full",
                        },
                    ),
                    LLMToolCall(
                        call_id="search-1",
                        name="search_forms",
                        arguments={"offset": 0, "limit": 16},
                    ),
                    LLMToolCall(
                        call_id="search-2",
                        name="search_forms",
                        arguments={"offset": 16, "limit": 16},
                    ),
                    LLMToolCall(
                        call_id="search-3",
                        name="search_forms",
                        arguments={"offset": 32, "limit": 16},
                    ),
                    LLMToolCall(
                        call_id="prev-1",
                        name="test_proto_assembly",
                        arguments={"choices": prev1_choices, "residue_policy": "drop"},
                    ),
                )
            elif turn == 4:
                # CROSSES WATERMARK (`900 >= 500`)!
                # Submit `prev-2` so BOTH `_compact_watermark_previews` (compacting `prev-1`)
                # AND `_compact_watermark_read_only` (compacting `surv-page-1`, `align-1`, `search-1`,
                # while skipping `surv-tiny-0row` and keeping newest 2 of each tool!) run on the SAME turn!
                in_tok = 900
                prev2_choices = [
                    {
                        "set_id": s["set_id"],
                        "proto_segment": next(
                            seg for seg in s["segments"] if seg is not None
                        ),
                        "confidence": 0.95,
                        "rationale": "Draft 2 superseding Draft 1.",
                        "directionality_rationale": "Retention.",
                    }
                    for s in first_survey_sets
                ]
                calls = (
                    LLMToolCall(
                        call_id="prev-2",
                        name="test_proto_assembly",
                        arguments={"choices": prev2_choices, "residue_policy": "drop"},
                    ),
                )
            elif turn == 5:
                # Re-call the EXACT same arguments as compacted `surv-page-1`!
                # Crucial: must NOT hit `repeat_guard` — must execute normally and return fresh rows!
                in_tok = 650
                calls = (
                    LLMToolCall(
                        call_id="surv-page-1-recall",
                        name="summarize_correspondences",
                        arguments={
                            "reading": "local",
                            "min_support": 1,
                            "offset": 0,
                            "limit": 12,
                        },
                    ),
                )
            elif turn == 6:
                # Verify `surv-page-1-recall` came back with full uncompacted sets (NOT `repeat_guard`),
                # while `surv-page-2` became 3rd-newest on Turn 5 and got compacted!
                in_tok = 620
                recalled_msg = next(
                    json.loads(m.content)
                    for m in messages
                    if m.role is MessageRole.TOOL
                    and m.tool_call_id == "surv-page-1-recall"
                )
                assert recalled_msg["ok"] is True
                assert "repeat_guard" not in recalled_msg["result"]
                assert "compacted" not in recalled_msg
                assert recalled_msg["result"]["sets"] == first_survey_sets

                prev2_hyp = next(
                    json.loads(m.content)["result"]["hypothesis_id"]
                    for m in messages
                    if m.role is MessageRole.TOOL and m.tool_call_id == "prev-2"
                )
                calls = (
                    LLMToolCall(
                        call_id="commit-final",
                        name="commit_reconstruction",
                        arguments={
                            "node_id": "proto_d",
                            "hypothesis_id": prev2_hyp,
                            "anomalies": [],
                            "summary": "Committed after watermark read-only compaction and page recall.",
                        },
                    ),
                )
            else:
                raise AssertionError(f"unexpected turn {turn}")

            return ProviderResponse(
                message=LLMMessage(role=MessageRole.ASSISTANT, tool_calls=calls),
                metadata=ProviderResponseMetadata(
                    provider_id="fake",
                    model_id=self.model,
                    usage=ProviderUsage(
                        input_tokens=in_tok, output_tokens=60, total_tokens=in_tok + 60
                    ),
                ),
            )

    orch = AgentOrchestrator(
        _ReadOnlyCompactionProvider(),
        registry=default_tool_registry(inventory_protocol="stored-hypothesis"),
        trajectory_sink=JsonlTrajectorySink(traj_path),
        event_sink=events,
        instructions=load_agent_instructions(),
        compaction_watermark_tokens=500,
    )
    reconstructor = AgenticNodeReconstructor(orch)
    child_beams = tuple(make_leaf_beam(lex, beam_width=5) for lex in ds.lexicons)
    reconstructor.reconstruct("proto_d", child_beams)
    traj = reconstructor.trajectories[0]
    assert traj.completed is True

    # Inspect Turn 5 prompt (immediately after Turn 4 crossed watermark):
    t5_tools = {
        m.tool_call_id: json.loads(m.content)
        for m in observed_prompts[4]
        if m.role is MessageRole.TOOL
    }
    # 1) Tiny `< 1024 B` 0-row survey page was SKIPPED (uncompacted):
    assert t5_tools["surv-tiny-0row"]["ok"] is True
    assert "compacted" not in t5_tools["surv-tiny-0row"]
    assert t5_tools["surv-tiny-0row"]["result"]["sets"] == []

    # 2) Rejected `ok=False` call stayed verbatim:
    assert t5_tools["surv-bad"]["ok"] is False
    assert "compacted" not in t5_tools["surv-bad"]

    # 3) On Turn 4, `surv-page-1`, `align-1`, and `search-1` were compacted into
    #    `watermark_read_only_page` stubs, while newest 2 of each (`-2`, `-3`) stayed verbatim!
    for cid, tool_name in (
        ("surv-page-1", "summarize_correspondences"),
        ("align-1", "get_alignments"),
        ("search-1", "search_forms"),
    ):
        stub = t5_tools[cid]
        assert stub["ok"] is True
        assert stub["compacted"] is True
        assert stub["compaction_kind"] == "watermark_read_only_page"
        assert stub["tool"] == tool_name
        assert stub["call_id"] == cid
        assert len(stub["argument_sha256"]) == 64
        assert (
            stub["note"]
            == "Earlier read-only inspection page compacted above context watermark; re-issue the tool call if exact rows are needed again."
        )

    assert t5_tools["surv-page-1"]["summary"]["reading"] == "local"
    assert t5_tools["surv-page-1"]["summary"]["offset"] == 0
    assert t5_tools["surv-page-1"]["summary"]["limit"] == 12
    assert t5_tools["surv-page-1"]["summary"]["returned_set_count"] == 12
    assert len(t5_tools["surv-page-1"]["summary"]["first_set_ids"]) == 5

    assert t5_tools["align-1"]["summary"]["detail"] == "full"
    assert t5_tools["align-1"]["summary"]["alignment_count"] == 4
    assert t5_tools["align-1"]["summary"]["concept_ids"] == ["c01", "c02", "c03", "c04"]

    assert t5_tools["search-1"]["summary"]["offset"] == 0
    assert t5_tools["search-1"]["summary"]["hit_count"] == 16

    for kept_id in ("surv-page-2", "surv-page-3", "align-2", "align-3", "search-2", "search-3"):
        assert "compacted" not in t5_tools[kept_id], f"{kept_id} should be kept verbatim on Turn 5"
        assert "result" in t5_tools[kept_id]

    # 4) Inspect Turn 6 prompt (after Turn 5 recalled `surv-page-1-recall`):
    #    Newest 2 for `summarize_correspondences` are now `surv-page-3` and `surv-page-1-recall`,
    #    so `surv-page-2` (`3rd`-newest) was compacted on Turn 5!
    t6_tools = {
        m.tool_call_id: json.loads(m.content)
        for m in observed_prompts[5]
        if m.role is MessageRole.TOOL
    }
    assert t6_tools["surv-page-2"]["compacted"] is True
    assert t6_tools["surv-page-2"]["compaction_kind"] == "watermark_read_only_page"
    assert "compacted" not in t6_tools["surv-page-3"]
    assert "compacted" not in t6_tools["surv-page-1-recall"]

    # 5) Check `compaction_summary()` & `watermark_trigger_count` deduplication:
    #    Turn 4 triggered watermark once (compacting `prev-1` + `surv-page-1` + `align-1` + `search-1`),
    #    Turn 5 triggered watermark once (compacting `surv-page-2`).
    #    Total triggers == 2 (NOT 3!), `compacted_preview_results == 1`, `compacted_read_only_results == 4`,
    #    `compacted_tool_results == 5`, `repeat_guard_hits == 0`!
    comp = orch.compaction_summary()
    assert comp["watermark_trigger_count"] == 2
    assert comp["compacted_preview_results"] == 1
    assert comp["compacted_read_only_results"] == 4
    assert comp["compacted_tool_results"] == 5
    assert comp["repeat_guard_hits"] == 0
    assert comp["per_node"]["proto_d"]["compacted_read_only_results"] == 4
    assert traj.metrics.compacted_tool_results == 5

    ro_events = [
        e
        for e in events.events
        if e.kind is AgentEventKind.CONTEXT_COMPACTION
        and e.details.get("action") == "watermark_read_only_compaction"
    ]
    assert [e.details["call_id"] for e in ro_events] == [
        "surv-page-1",
        "align-1",
        "search-1",
        "surv-page-2",
    ]

    # 6) `_MessageLog.audit` (`trajectories.jsonl`) is 100% UNCOMPACTED!
    saved = list(TrajectoryDatasetBuilder.read_jsonl(traj_path))
    assert len(saved) == 1
    audit_tools = {
        m.tool_call_id: json.loads(m.content)
        for m in saved[0].messages
        if m.role is MessageRole.TOOL
    }
    for cid in ("surv-page-1", "surv-page-2", "align-1", "search-1", "prev-1"):
        assert "compacted" not in audit_tools[cid]
        assert audit_tools[cid]["ok"] is True
        assert "result" in audit_tools[cid]


def test_watermark_read_only_compaction_persists_in_cli_run_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end offline `cli.main(['infer', ...])` writes `compacted_read_only_results` into `run_summary.json`."""
    payload = _build_synthetic_four_daughter_payload(concept_count=14)
    in_path = tmp_path / "input.payload.json"
    in_path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")
    out_dir = tmp_path / "run_out"

    class _CliSurveyProvider:
        model = "scripted/cli-ro-compaction"

        def __init__(self) -> None:
            self.turn = 0

        def complete(self, messages, tools, **kwargs):
            self.turn += 1
            if self.turn in (1, 2, 3):
                call = LLMToolCall(
                    call_id=f"cli-surv-{self.turn}",
                    name="summarize_correspondences",
                    arguments={
                        "reading": "local",
                        "min_support": 1,
                        "offset": (self.turn - 1) * 10,
                        "limit": 10,
                    },
                )
            elif self.turn == 4:
                call = LLMToolCall(
                    call_id="cli-prev",
                    name="test_proto_assembly",
                    arguments={"choices": [], "residue_policy": "drop"},
                )
            else:
                hyp_id = json.loads(messages[-1].content)["result"]["hypothesis_id"]
                call = LLMToolCall(
                    call_id="cli-commit",
                    name="commit_reconstruction",
                    arguments={
                        "node_id": "proto_d",
                        "hypothesis_id": hyp_id,
                        "anomalies": [],
                        "summary": "CLI commit.",
                    },
                )
            return ProviderResponse(
                message=LLMMessage(role=MessageRole.ASSISTANT, tool_calls=(call,)),
                metadata=ProviderResponseMetadata(
                    provider_id="fake",
                    model_id=self.model,
                    usage=ProviderUsage(
                        input_tokens=12_000, output_tokens=50, total_tokens=12_050
                    ),
                ),
            )

    fake_provider = _CliSurveyProvider()
    orig_pc = cli._provider_and_configuration

    def _patched_pc(args, **kwargs):
        _, sha, settings, price = orig_pc(args, **kwargs)
        return fake_provider, sha, settings, price

    monkeypatch.setenv("GEMINI_API_KEY", "offline-dummy-key")
    monkeypatch.setattr(cli, "_provider_and_configuration", _patched_pc)

    out_dir.mkdir(parents=True, exist_ok=True)
    rc = cli.main(
        [
            "infer",
            "--input",
            str(in_path),
            "--output",
            str(out_dir / "result.json"),
            "--trajectories",
            str(out_dir / "trajectories.jsonl"),
            "--checkpoint",
            str(out_dir / "checkpoint.json"),
            "--preset",
            "gemini",
            "--model",
            "gemini-3.8-flash",
            "--compaction-watermark-tokens",
            "8192",
            "--no-preflight",
            "--no-events",
            "--quiet",
        ]
    )
    assert rc is None
    summary = json.loads((out_dir / "run_summary.json").read_text(encoding="utf-8"))
    comp = summary["compaction"]
    assert comp["compaction_watermark_tokens"] == 8192
    assert comp["compacted_read_only_results"] == 1
    assert comp["compacted_preview_results"] == 0
    assert comp["compacted_tool_results"] == 1
    assert comp["watermark_trigger_count"] == 1
    assert comp["per_node"]["proto_d"]["compacted_read_only_results"] == 1
