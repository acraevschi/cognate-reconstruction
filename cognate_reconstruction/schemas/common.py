"""Shared strict-model configuration and token conventions."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
MORPHOLOGICAL_BOUNDARY_TOKENS: frozenset[str] = frozenset({"+", "-"})


def sorted_token_set(value: frozenset[str]) -> list[str]:
    """Serialize a token set in one canonical order.

    A `frozenset` dumps in hash-table order, which depends on the process's
    string-hash seed and on insertion order. Digests are taken over these
    dumps (a stored hypothesis is re-digested from its JSON snapshot at
    commit), so an unsorted dump can differ from its own readback.
    """
    return sorted(value)


class WorkbenchModel(BaseModel):
    """Immutable, strict, and closed base class for serialized workbench data."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        frozen=True,
        validate_default=True,
    )
