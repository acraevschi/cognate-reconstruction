from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.schemas import LLMToolCall
from cognate_reconstruction.agent.tools import default_tool_registry
from cognate_reconstruction.alignment import LingPyAligner
from cognate_reconstruction.ingestion import ingest_payload, load_cldf_dataset
from cognate_reconstruction.schemas.anchors import AnchorFile
from cognate_reconstruction.schemas.rules import AnchorPolicy


FIXTURE = Path("examples/lexibank_fixture")


def _dataset():
    loaded = load_cldf_dataset(FIXTURE)
    return ingest_payload(
        loaded.to_payload(
            newick=(FIXTURE / "tree.nwk").read_text(encoding="utf-8")
        )
    )


def test_checked_in_anchor_file_resolves_explicit_node_and_concept() -> None:
    anchors = AnchorFile.model_validate_json(
        Path("examples/anchors.json").read_text(encoding="utf-8")
    )
    resolved = anchors.validate_for_dataset(_dataset())
    assert resolved["PROTO"][0].segments == ("p", "a")
    assert resolved["PROTO"][0].provenance.source_reference


def test_anchor_file_rejects_unknown_targets_and_concepts() -> None:
    value = json.loads(Path("examples/anchors.json").read_text(encoding="utf-8"))
    value["anchors"]["UNKNOWN"] = value["anchors"].pop("PROTO")
    value["anchors"]["UNKNOWN"][0]["variety_id"] = "UNKNOWN"
    anchors = AnchorFile.model_validate_json(json.dumps(value))
    with pytest.raises(ValueError, match="not internal nodes"):
        anchors.validate_for_dataset(_dataset())

    value["anchors"]["PROTO"] = value["anchors"].pop("UNKNOWN")
    value["anchors"]["PROTO"][0]["variety_id"] = "PROTO"
    value["anchors"]["PROTO"][0]["concept_id"] = "not-a-concept"
    anchors = AnchorFile.model_validate_json(json.dumps(value))
    with pytest.raises(ValueError, match="absent from"):
        anchors.validate_for_dataset(_dataset())


def test_anchor_file_requires_token_arrays_and_provenance() -> None:
    value = json.loads(Path("examples/anchors.json").read_text(encoding="utf-8"))
    value["anchors"]["PROTO"][0]["segments"] = "pa"
    with pytest.raises(ValidationError):
        AnchorFile.model_validate_json(json.dumps(value))

    value = json.loads(Path("examples/anchors.json").read_text(encoding="utf-8"))
    value["anchors"]["PROTO"][0]["provenance"] = {}
    with pytest.raises(ValidationError, match="needs source provenance"):
        AnchorFile.model_validate_json(json.dumps(value))


def test_ignore_policy_retains_prompt_provenance_but_disables_tool_matching() -> None:
    resolved = AnchorFile.model_validate_json(
        Path("examples/anchors.json").read_text(encoding="utf-8")
    ).validate_for_dataset(_dataset())
    dataset = _dataset()
    context = AgentContext(
        node_id="PROTO",
        child_lexicons=dataset.lexicons,
        aligner=LingPyAligner(),
        anchors=resolved["PROTO"],
        anchor_policy=AnchorPolicy.IGNORE,
    )
    assert context.anchors
    assert context.active_anchors == ()
    result = default_tool_registry().execute(
        LLMToolCall(
            call_id="ignored-anchor-test",
            name="test_sound_law",
            arguments={
                "dsl": "p > b",
                "source_child_ids": ["lexibank_fixture:A"],
            },
        ),
        context,
    )
    assert result.ok and result.result is not None
    assert result.result["report"]["anchors_matched"] == 0
