from __future__ import annotations

import json
import re
from io import BytesIO
from collections.abc import Sequence
from pathlib import Path

import pytest

from cognate_reconstruction import cli
from cognate_reconstruction.agent.schemas import (
    LLMMessage,
    LLMToolCall,
    LLMToolDefinition,
    MessageRole,
)
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm


class AutoCommitProvider:
    model = "test-model"

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[LLMToolDefinition],
    ) -> LLMMessage:
        match = re.search(r'"node_id":\s*"([^"]+)"', messages[1].content or "")
        assert match is not None and tools
        node_id = match.group(1)
        return LLMMessage(
            role=MessageRole.ASSISTANT,
            tool_calls=(
                LLMToolCall(
                    call_id=f"commit:{node_id}",
                    name="commit_reconstruction",
                    arguments={
                        "node_id": node_id,
                        "rules": [],
                        "anomalies": [],
                        "summary": "Identity reconstruction.",
                    },
                ),
            ),
        )


def _lexicon(variety_id: str) -> LanguageLexicon:
    return LanguageLexicon(
        variety_id=variety_id,
        name=variety_id,
        forms=(
            LexicalForm(
                form_id=f"{variety_id}:water",
                variety_id=variety_id,
                concept_id="water",
                segments=("p",),
            ),
        ),
    )


def test_inference_cli_writes_result_and_trajectory(tmp_path, monkeypatch) -> None:
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "result.json"
    trajectory_path = tmp_path / "trajectory.jsonl"
    payload = WorkbenchPayload(
        lexicons=(_lexicon("A"), _lexicon("B")),
        newick="(A,B)PROTO;",
    )
    input_path.write_text(payload.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(
        cli,
        "LiteLLMProvider",
        lambda *args, **kwargs: AutoCommitProvider(),
    )
    cli.main(
        [
            "infer",
            "--input",
            str(input_path),
            "--model",
            "test-model",
            "--output",
            str(output_path),
            "--trajectories",
            str(trajectory_path),
            "--quiet",
            "--no-events",
        ]
    )
    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["internal_nodes"][0]["node_id"] == "PROTO"
    assert len(trajectory_path.read_text(encoding="utf-8").splitlines()) == 1


def test_documented_example_is_valid_workbench_json() -> None:
    example = Path("examples/reconstruction_input.json")
    payload = WorkbenchPayload.model_validate_json(example.read_text(encoding="utf-8"))
    assert len(payload.lexicons) == 3


def test_prepare_lexibank_filters_exact_concept_ids(tmp_path) -> None:
    output_path = tmp_path / "fixture-water.json"
    cli.main(
        [
            "prepare-lexibank",
            "--dataset",
            "examples/lexibank_fixture",
            "--newick-file",
            "examples/lexibank_fixture/tree.nwk",
            "--concept-id",
            "948",
            "--output",
            str(output_path),
        ]
    )
    payload = WorkbenchPayload.model_validate_json(
        output_path.read_text(encoding="utf-8")
    )
    assert {form.concept_id for lexicon in payload.lexicons for form in lexicon.forms} == {
        "948"
    }
    assert [concept.concept_id for concept in payload.concepts] == ["948"]


def test_prepare_lexibank_rejects_unknown_concept_id(
    tmp_path, capsys
) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(
            [
                "prepare-lexibank",
                "--dataset",
                "examples/lexibank_fixture",
                "--concept-id",
                "unknown",
                "--output",
                str(tmp_path / "unused.json"),
            ]
        )
    assert caught.value.code == 2
    assert "unknown concept IDs" in capsys.readouterr().err


def test_lm_studio_endpoint_discovery_normalizes_model_ids(monkeypatch) -> None:
    captured = {}

    def open_request(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.headers.get("Authorization")
        captured["timeout"] = timeout
        return BytesIO(
            json.dumps(
                {
                    "data": [
                        {"id": "tool-model"},
                        {"id": ""},
                        {"unexpected": "ignored"},
                    ]
                }
            ).encode()
        )

    monkeypatch.setattr(cli, "urlopen", open_request)
    assert cli._lm_studio_models(
        "http://localhost:1234/v1/",
        "local-key",
    ) == ("tool-model",)
    assert captured == {
        "url": "http://localhost:1234/v1/models",
        "authorization": "Bearer local-key",
        "timeout": 10,
    }
