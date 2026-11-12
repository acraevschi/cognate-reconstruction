"""An explicit, versioned price table for providers LiteLLM cannot price.

LiteLLM prices a response from its model-cost map. The bundled map of the
installed release has no entry for some current hosted models, and the map it
fetches at import time changes without notice, so a response can arrive with
no cost and the run cost cap then refuses after the first request. Missing
cost is never zero. This table makes the price an operator input instead: it
names one exact model, the published per-token prices, where and when they
were read and the last date they apply, and its digest joins the run's
configuration digest.

When both a response's cached prompt token count and the table's
`cached_input_usd_per_million` rate are present, `priced_cost` charges cached
prompt tokens at the discounted cached input rate and the remaining prompt
tokens at `input_usd_per_million` (clamping `cached_input_tokens` defensively
into `[0, input_tokens]`). When either is absent, `priced_cost` falls back
conservatively to `priced_uncached_cost`, which charges every prompt token at
the uncached input rate and also supplies 0%-cache worst-case single-response
headroom and uncached upper-bound ledger reporting. Output tokens include
reasoning tokens, which providers bill at the output rate and LiteLLM already
counts inside `completion_tokens`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from cognate_reconstruction.schemas.common import NonEmptyStr, WorkbenchModel

PRICE_TABLE_VERSION = "price-table-v1"


class TokenPrice(WorkbenchModel):
    model: NonEmptyStr
    """The exact LiteLLM model string the harness sends, e.g. `gemini/gemini-3.8-flash`."""
    input_usd_per_million: float = Field(gt=0)
    output_usd_per_million: float = Field(gt=0)
    cached_input_usd_per_million: float | None = Field(default=None, gt=0)
    """Discounted input rate for cached prompt tokens when reported by the provider."""
    valid_from: date | None = None
    valid_through: date
    tier: NonEmptyStr
    source_url: NonEmptyStr
    read_on: date

    @model_validator(mode="after")
    def dates_in_order(self) -> TokenPrice:
        if self.valid_from is not None and self.valid_from > self.valid_through:
            raise ValueError("valid_from must not follow valid_through")
        return self


class PriceTable(WorkbenchModel):
    price_table_version: Literal["price-table-v1"]
    prices: tuple[TokenPrice, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def one_price_per_model(self) -> PriceTable:
        models = [price.model for price in self.prices]
        if len(models) != len(set(models)):
            raise ValueError("a price table names each model once")
        return self


def load_price_table(path: str | Path) -> tuple[PriceTable, str]:
    """The table and the SHA-256 of its exact bytes."""
    data = Path(path).expanduser().read_bytes()
    return PriceTable.model_validate_json(data), hashlib.sha256(data).hexdigest()


def price_for(table: PriceTable, model: str, today: date) -> TokenPrice:
    """The applicable price, or a refusal to start a run it cannot price."""
    price = next((item for item in table.prices if item.model == model), None)
    if price is None:
        raise ValueError(
            f"price table has no entry for {model!r}; it lists "
            f"{sorted(item.model for item in table.prices)}"
        )
    if today > price.valid_through or (price.valid_from is not None and today < price.valid_from):
        raise ValueError(
            f"price for {model!r} applies {price.valid_from or '…'} to {price.valid_through}, "
            f"not on {today}; re-read {price.source_url} and write a new table"
        )
    return price


def priced_uncached_cost(
    price: TokenPrice,
    input_tokens: int | None,
    output_tokens: int | None,
) -> float | None:
    """0%-cache upper-bound cost of one response, or None when either count is unknown."""
    if input_tokens is None or output_tokens is None:
        return None
    return (
        input_tokens * price.input_usd_per_million
        + output_tokens * price.output_usd_per_million
    ) / 1_000_000


def priced_cost(
    price: TokenPrice,
    input_tokens: int | None,
    output_tokens: int | None,
    cached_input_tokens: int | None = None,
) -> float | None:
    """Cost of one response (cached-adjusted when both cached count and rate exist), or None."""
    if input_tokens is None or output_tokens is None:
        return None
    if cached_input_tokens is not None and price.cached_input_usd_per_million is not None:
        cached = min(max(0, cached_input_tokens), max(0, input_tokens))
        uncached = max(0, input_tokens - cached)
        return (
            uncached * price.input_usd_per_million
            + cached * price.cached_input_usd_per_million
            + output_tokens * price.output_usd_per_million
        ) / 1_000_000
    return priced_uncached_cost(price, input_tokens, output_tokens)


def price_setting(price: TokenPrice, table_sha256: str) -> dict:
    """The configuration-digest entry: which prices this run charged."""
    return {"price_table_version": PRICE_TABLE_VERSION, "price_table_sha256": table_sha256,
            "price": json.loads(price.model_dump_json())}
