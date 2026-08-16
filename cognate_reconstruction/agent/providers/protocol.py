"""Provider abstraction used by the agent loop."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from cognate_reconstruction.agent.schemas import (
    LLMMessage,
    LLMToolDefinition,
    ProviderResponse,
)


class LLMProvider(Protocol):
    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[LLMToolDefinition],
        *,
        tool_choice: str = "auto",
        max_tokens_override: int | None = None,
    ) -> ProviderResponse | LLMMessage:
        """Request one assistant turn.

        Both keyword arguments exist so the orchestrator can recover from a
        truncated response without reaching into an adapter's stored options.

        ``tool_choice`` is the harness's own request-building concern; the
        orchestrator raises it to ``"required"`` for exactly one retry after a
        truncated response that carried no tool call. Backends that do not
        honour ``"required"`` may raise, and the orchestrator falls back.

        ``max_tokens_override`` applies to that one call only. An adapter must
        merge it over its configured options without mutating them, since those
        options belong to the user.
        """
        ...
