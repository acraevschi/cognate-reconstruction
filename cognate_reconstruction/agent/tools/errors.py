"""Tool rejections that can carry deterministic remediation guidance."""

from __future__ import annotations


class ToolInputError(ValueError):
    """A rejected tool call that can also explain how to build a valid one.

    ``remediation`` is deterministic text derived from recorded session state,
    never model prose. It is returned inside the tool result and therefore lands
    in the trajectory, so it must stay stable for identical session state.
    """

    def __init__(
        self,
        message: str,
        *,
        remediation: str | None = None,
        error_type: str | None = None,
    ) -> None:
        super().__init__(message)
        self.remediation = remediation
        self.error_type = error_type or type(self).__name__
