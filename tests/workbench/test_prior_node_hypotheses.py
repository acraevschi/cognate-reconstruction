"""Read-only cross-node exposure of previously committed hypotheses.

Each node keeps its own independent session; a later node can *retrieve* what an
already-reconstructed descendant committed, and nothing else changes. Prior
rules are hypotheses, not evidence, and they do not touch scoring.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.orchestrator import AgentOrchestrator
from cognate_reconstruction.agent.reconstructor import AgenticNodeReconstructor
from cognate_reconstruction.agent.schemas import (
    LLMMessage,
    LLMToolCall,
    LLMToolDefinition,
    MessageRole,
)
from cognate_reconstruction.agent.service import ReconstructionService
from cognate_reconstruction.agent.tools import default_tool_registry
from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.ingestion import ingest_payload
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm


def _lexicon(variety_id: str, initial: str) -> LanguageLexicon:
    return LanguageLexicon(
        variety_id=variety_id,
        name=variety_id,
        forms=(
            LexicalForm(
                form_id=f"{variety_id}:water",
                variety_id=variety_id,
                concept_id="water",
                segments=(initial, "a"),
            ),
        ),
    )


class _RecordingProvider:
    """Inspect nodes, look up any prior hypothesis, test, then commit."""

    model = "scripted/cross-node"

    def __init__(self) -> None:
        self.turns_by_node: dict[str, int] = {}
        self.available_nodes: dict[str, list[dict]] = {}
        self.retrieved: dict[str, dict] = {}
        self.lookup_errors: dict[str, str] = {}
        self.message_counts: list[int] = []

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[LLMToolDefinition],
        *,
        tool_choice: str = "auto",
        max_tokens_override: int | None = None,
    ) -> LLMMessage:
        assert any(tool.name == "get_node_reconstruction" for tool in tools)
        payload = json.loads((messages[1].content or "").split("\n\n", 1)[1])
        node_id = payload["node_id"]
        turn = self.turns_by_node.get(node_id, 0) + 1
        self.turns_by_node[node_id] = turn
        if turn == 1:
            self.message_counts.append(len(messages))
        for message in messages:
            if message.role is not MessageRole.TOOL or message.content is None:
                continue
            body = json.loads(message.content)
            if message.name == "list_available_nodes" and body["ok"]:
                self.available_nodes[node_id] = body["result"]["nodes"]
            elif message.name == "get_node_reconstruction":
                if body["ok"]:
                    self.retrieved[node_id] = body["result"]["reconstruction"]
                else:
                    self.lookup_errors[node_id] = body["error"]["remediation"]

        children = [item["node_id"] for item in payload["active_children"]]
        if turn == 1:
            return self._call("nodes", "list_available_nodes", {})
        if turn == 2:
            # Ask for the deepest internal node whether or not it exists yet.
            return self._call(
                "prior", "get_node_reconstruction", {"node_id": "X"}
            )
        if turn == 3:
            return self._call(
                "validate",
                "test_sound_law",
                {"dsl": "f > p", "source_child_ids": [children[-1]]},
            )
        return self._call(
            "commit",
            "commit_reconstruction",
            {
                "node_id": node_id,
                "rules": [
                    {
                        "dsl": "f > p",
                        "source_child_ids": [children[-1]],
                        "confidence": 0.8,
                    }
                ],
                "anomalies": [],
                "summary": f"Parent initial p reconstructed at {node_id}.",
            },
        )

    @staticmethod
    def _call(call_id: str, name: str, arguments: dict) -> LLMMessage:
        return LLMMessage(
            role=MessageRole.ASSISTANT,
            tool_calls=(
                LLMToolCall(call_id=call_id, name=name, arguments=arguments),
            ),
        )


def _run_two_internal_nodes() -> _RecordingProvider:
    provider = _RecordingProvider()
    dataset = ingest_payload(
        WorkbenchPayload(
            lexicons=(
                _lexicon("A", "p"),
                _lexicon("B", "f"),
                _lexicon("C", "f"),
            ),
            newick="((A,B)X,C)ROOT;",
        )
    )
    ReconstructionService(
        AgenticNodeReconstructor(
            AgentOrchestrator(provider, instructions="Inspect, then commit.")
        )
    ).reconstruct_family(dataset)
    return provider


def test_a_later_node_can_read_what_an_earlier_node_committed() -> None:
    provider = _run_two_internal_nodes()
    assert set(provider.turns_by_node) == {"X", "ROOT"}

    retrieved = provider.retrieved["ROOT"]
    assert retrieved["node_id"] == "X"
    assert retrieved["rules"] == [
        {"dsl": "f > p", "source_child_ids": ["B"], "confidence": 0.8}
    ]
    assert retrieved["summary"] == "Parent initial p reconstructed at X."
    assert retrieved["identity_reconstruction"] is False
    # Session-local bookkeeping from X's own commit stays out of ROOT's view.
    assert "validation_call_id" not in json.dumps(retrieved)
    assert "supporting_form_ids" not in json.dumps(retrieved)


def test_nothing_leaks_for_a_node_not_yet_reconstructed() -> None:
    provider = _run_two_internal_nodes()
    # X runs first in post-order, so its own lookup of X must fail.
    assert "X" not in provider.retrieved
    assert "none" in provider.lookup_errors["X"]
    assert "ROOT" not in provider.lookup_errors

    at_x = {item["node_id"]: item for item in provider.available_nodes["X"]}
    assert all(not item["has_committed_hypothesis"] for item in at_x.values())
    at_root = {item["node_id"]: item for item in provider.available_nodes["ROOT"]}
    assert at_root["X"]["has_committed_hypothesis"] is True
    assert at_root["C"]["has_committed_hypothesis"] is False


def test_each_node_still_starts_a_fresh_conversation() -> None:
    provider = _run_two_internal_nodes()
    # Both nodes open with exactly system instructions plus the node payload;
    # prior hypotheses are retrieved through a tool, never prepended.
    assert provider.message_counts == [2, 2]


def test_prior_hypotheses_do_not_reach_a_context_that_was_not_given_any() -> None:
    state = AgentContext(
        node_id="PROTO",
        child_lexicons=(_lexicon("A", "p"), _lexicon("B", "f")),
        aligner=LingPyAligner(),
    )
    result = default_tool_registry().execute(
        LLMToolCall(
            call_id="prior",
            name="get_node_reconstruction",
            arguments={"node_id": "X"},
        ),
        state,
    )
    assert not result.ok
    assert result.error is not None
    assert "no committed hypothesis is available" in result.error.message
    assert "none" in (result.error.remediation or "")
