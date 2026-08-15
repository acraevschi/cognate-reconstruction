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
