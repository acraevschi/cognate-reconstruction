"""Safe loading of non-secret, provider-specific LiteLLM options."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_RESERVED = {"model", "messages", "tools", "tool_choice", "api_key"}
_SECRET_MARKERS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
}
# Options that hand the model an information source outside the harness. The
# whole design rests on the model reaching the evidence only through the typed
# tools, so that what a trajectory shows is what the reconstruction rested on.
# A grounded model can retrieve a published proto-form instead of deriving one,
# and nothing in the trajectory would look different: the tool calls would read
# as ordinary inspection, and the commit as ordinary work. This repo exists to
# measure models on exactly that task, so the option is refused rather than
# recorded. Provider-agnostic by name because the shape recurs — OpenAI and
# Anthropic spell it `web_search_options`, LiteLLM turns that into Gemini's
# `googleSearch`, xAI uses `search_parameters`, and a later provider will bring
# another spelling to add here.
_GROUNDING_OPTIONS = {
    "web_search_options",
    "search_parameters",
    "google_search",
    "google_search_retrieval",
    "grounding",
    "enable_search",
    "url_context",
    "retrieval",
}


def _find_secret_keys(value: object, path: str = "") -> list[str]:
    found = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            location = f"{path}.{key_text}" if path else key_text
            normalized = key_text.lower().replace("-", "_")
            if normalized in _SECRET_MARKERS or any(
                normalized.endswith(f"_{marker}") for marker in _SECRET_MARKERS
            ):
                found.append(location)
            found.extend(_find_secret_keys(item, location))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_find_secret_keys(item, f"{path}[{index}]"))
    return found


def _find_grounding_keys(value: object, path: str = "") -> list[str]:
    found = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            location = f"{path}.{key_text}" if path else key_text
            if key_text.lower().replace("-", "_") in _GROUNDING_OPTIONS:
                found.append(location)
            found.extend(_find_grounding_keys(item, location))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_find_grounding_keys(item, f"{path}[{index}]"))
    return found


def load_provider_options(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    source = Path(path).expanduser()
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"could not read provider config {source}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("provider config must be one JSON object")
    if overlap := sorted(_RESERVED & value.keys()):
        raise ValueError(
            f"provider config contains reserved option(s): {overlap}"
        )
    if secret_keys := _find_secret_keys(value):
        raise ValueError(
            "provider config must not persist secrets; use --api-key-env. "
            f"Secret-like keys: {sorted(secret_keys)}"
        )
    if grounding_keys := _find_grounding_keys(value):
        raise ValueError(
            "provider config must not give the model a source outside the "
            "harness: a grounded model can retrieve a published "
            "reconstruction instead of deriving one, and the trajectory would "
            "not show the difference. Remove "
            f"{sorted(grounding_keys)}. Every source the model may consult is "
            "a tool, so add one rather than opening a side channel."
        )
    return dict(value)


def api_key_from_environment(variable_name: str | None) -> str | None:
    if variable_name is None:
        return None
    value = os.environ.get(variable_name)
    if value is None or not value.strip():
        raise ValueError(
            f"API-key environment variable {variable_name!r} is unset or empty"
        )
    return value
