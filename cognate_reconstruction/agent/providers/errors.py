"""Conservative structured provider failures. No provider prose is classified or saved."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum
import math
from typing import Literal

from pydantic import Field

from cognate_reconstruction.schemas.common import WorkbenchModel


class ProviderFailureKind(StrEnum):
    RATE_LIMIT = "recoverable_rate_limit"
    QUOTA = "exhausted_quota_billing"
    CAPACITY = "capacity_unavailability"
    AUTH = "authentication_configuration"
    UNKNOWN = "unknown_provider_failure"


class ProviderFailureMetadata(WorkbenchModel):
    kind: ProviderFailureKind = ProviderFailureKind.UNKNOWN
    retryable: bool = False
    http_status: int | None = None
    structured_code: str | None = None
    exception_type: str | None = None
    evidence_source: Literal["adapter", "http_status", "structured_code", "legacy_unspecified"] = "adapter"
    retry_after_seconds: float | None = Field(default=None, ge=0)
    response_state: Literal["rejected", "unknown"] = "unknown"
    # Raw messages, URLs, headers, bodies, request IDs and credentials are omitted.


class ProviderError(RuntimeError):
    def __init__(self, message: str = "provider request failed", *, metadata: ProviderFailureMetadata | None = None) -> None:
        self.metadata = metadata or ProviderFailureMetadata()
        self.stop_reason: str | None = None
        super().__init__(message)


class ProviderTransientError(ProviderError):
    """Compatibility name for an adapter-asserted retryable rejection.

    Old callers provide no cause metadata; the cause remains unknown. Transport
    failures with a possibly lost response must use non-retryable ProviderError.
    """
    def __init__(self, message: str = "provider request failed", *, metadata: ProviderFailureMetadata | None = None) -> None:
        super().__init__(message, metadata=metadata or ProviderFailureMetadata(
            retryable=True, evidence_source="legacy_unspecified",
        ))


def _get(value, key, default=None):
    return value.get(key, default) if isinstance(value, Mapping) else getattr(value, key, default)


_CODES = {
    "rate_limit_exceeded": ProviderFailureKind.RATE_LIMIT,
    "too_many_requests": ProviderFailureKind.RATE_LIMIT,
    "insufficient_quota": ProviderFailureKind.QUOTA,
    "billing_hard_limit_reached": ProviderFailureKind.QUOTA,
    "billing_not_active": ProviderFailureKind.QUOTA,
    "invalid_api_key": ProviderFailureKind.AUTH,
    "authentication_error": ProviderFailureKind.AUTH,
    "permission_denied": ProviderFailureKind.AUTH,
    "unauthenticated": ProviderFailureKind.AUTH,
    "invalid_argument": ProviderFailureKind.AUTH,
    "model_not_found": ProviderFailureKind.AUTH,
    "overloaded_error": ProviderFailureKind.CAPACITY,
    "unavailable": ProviderFailureKind.CAPACITY,
}
# RESOURCE_EXHAUSTED does not distinguish request/token rate from hard quota.
_AMBIGUOUS_CODES = {"resource_exhausted", "quota_exhausted"}


def retry_after_seconds(value, *, now: datetime | None = None) -> float | None:
    """Accept delay seconds or an HTTP date; ignore malformed/nonfinite hints."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            stamp = parsedate_to_datetime(value)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=UTC)
            seconds = (stamp - (now or datetime.now(UTC))).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    return max(0.0, seconds) if math.isfinite(seconds) else None


def classify_provider_error(error: Exception, *, now: datetime | None = None) -> ProviderFailureMetadata:
    """Only status, explicit error codes and retry hints are evidence.

    Exception class names are retained for provenance, never matched against
    prose. A generic 429 is unknown but can retry the rejected request; a 503
    establishes transient unavailability, never tier/model availability.
    """
    if isinstance(error, ProviderError):
        return error.metadata
    response = _get(error, "response")
    status = _get(error, "status_code") or _get(error, "http_status") or _get(error, "status") or _get(response, "status_code")
    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        status = None
    body = _get(error, "body")
    if not isinstance(body, Mapping) and response is not None:
        try:
            body = response.json()
        except Exception:
            body = None
    structured = _get(body, "error", body) if isinstance(body, Mapping) else {}
    if not isinstance(structured, Mapping):
        structured = {}
    raw_codes = [structured.get(key) for key in ("code", "type", "status", "reason")]
    raw_codes.extend([_get(error, "code"), _get(error, "type")])
    # ErrorInfo may provide a code, but no quota metric, message or consumer ID
    # is interpreted. RetryInfo has a structured duration.
    retry_hint = None
    for detail in structured.get("details", ()) or ():
        if not isinstance(detail, Mapping):
            continue
        raw_codes.append(detail.get("reason"))
        if detail.get("@type") == "type.googleapis.com/google.rpc.RetryInfo":
            value = detail.get("retryDelay")
            if isinstance(value, str) and value.endswith("s"):
                retry_hint = retry_after_seconds(value[:-1], now=now)
            elif isinstance(value, Mapping):
                try:
                    delay = float(value.get("seconds", 0)) + float(value.get("nanos", 0)) / 1_000_000_000
                    retry_hint = retry_after_seconds(delay, now=now)
                except (TypeError, ValueError):
                    pass
    codes = [v.lower() for v in raw_codes if isinstance(v, str)]
    code = next((v for v in codes if v in _CODES), None)
    kind = _CODES[code] if code else ProviderFailureKind.UNKNOWN
    source = "structured_code" if code else "adapter"
    if code is None:
        code = next((v for v in codes if v in _AMBIGUOUS_CODES), None)
        if status in {401, 403, 400, 404, 422}:
            kind, source = ProviderFailureKind.AUTH, "http_status"
        elif status in {500, 502, 503, 504}:
            kind, source = ProviderFailureKind.CAPACITY, "http_status"
        elif status is not None:
            source = "http_status"
    rejected = status is not None or code is not None
    retryable = kind in {ProviderFailureKind.RATE_LIMIT, ProviderFailureKind.CAPACITY} or (
        kind is ProviderFailureKind.UNKNOWN and status in {408, 409, 425, 429}
    )
    # No automatic replay of timeouts/connections without an explicit rejection:
    # the server may already have generated and billed a lost response.
    headers = _get(response, "headers", {}) or _get(error, "headers", {}) or {}
    if isinstance(headers, Mapping):
        header = next((v for k, v in headers.items() if str(k).lower() == "retry-after"), None)
        retry_hint = retry_after_seconds(header, now=now) if header is not None else retry_hint
    return ProviderFailureMetadata(
        kind=kind, retryable=retryable, http_status=status,
        structured_code=code, exception_type=type(error).__name__,
        evidence_source=source, retry_after_seconds=retry_hint,
        response_state="rejected" if rejected else "unknown",
    )


def normalized_provider_error(error: Exception) -> ProviderError:
    if isinstance(error, ProviderError):
        return error
    metadata = classify_provider_error(error)
    cls = ProviderTransientError if metadata.retryable else ProviderError
    return cls(f"provider request failed: {metadata.kind.value}", metadata=metadata)
