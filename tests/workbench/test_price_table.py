"""R02 cost gate: an explicit price table prices responses LiteLLM cannot.

The installed LiteLLM's bundled cost map has no `gemini-3.8-flash` entry, and
`input_cost_per_token` cannot travel through `--provider-config` because the
secret filter refuses every key ending in `_token`. These cases drive the real
`LiteLLMProvider` with a fake completion function, so no request leaves the
process.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest

from cognate_reconstruction import cli
from cognate_reconstruction.agent.provider_config import load_provider_options
from cognate_reconstruction.agent.providers.litellm_provider import LiteLLMProvider
from cognate_reconstruction.agent.providers.pricing import (
    PriceTable, TokenPrice, load_price_table, price_for, priced_cost,
)
from tests.workbench.test_resume_integrity import _prepare

REPO = Path(__file__).resolve().parents[2]
GEMINI_TABLE = REPO / "examples/pricing/gemini-3.8-flash.price-table.json"


def _price(model="test-model", **extra):
    return TokenPrice.model_validate_json(json.dumps({
        "model": model, "input_usd_per_million": 0.75, "output_usd_per_million": 3.75,
        "cached_input_usd_per_million": 0.075, "valid_through": "2026-12-31",
        "tier": "test", "source_url": "https://example.invalid/pricing", "read_on": "2026-10-25",
        **extra}))


def _table(tmp_path, model="test-model", **extra):
    # A far validity end keeps CLI cases independent of the run date.
    extra.setdefault("valid_through", "2099-12-31")
    path = tmp_path / "prices.json"
    path.write_text(json.dumps({"price_table_version": "price-table-v1",
                                "prices": [json.loads(_price(model, **extra).model_dump_json())]}))
    return path


def _completion(*, prompt=1000, output=200, reported=None, usage=True):
    """OpenAI-shaped responses committing identity at whichever node is asked."""
    calls = []

    def complete(*, model, messages, tools, tool_choice, **options):
        calls.append(options)
        node = re.search(r'"node_id":\s*"([^"]+)"', messages[1]["content"]).group(1)
        response = {
            "id": f"r{len(calls)}", "model": model,
            "choices": [{"finish_reason": "tool_calls", "message": {"role": "assistant", "content": None,
                "tool_calls": [{"id": f"c{len(calls)}", "type": "function", "function": {
                    "name": "commit_reconstruction",
                    "arguments": json.dumps({"node_id": node, "rules": [], "anomalies": [],
                                             "summary": "identity"})}}]}}],
        }
        if usage:
            response["usage"] = {"prompt_tokens": prompt, "completion_tokens": output,
                                 "total_tokens": prompt + output,
                                 "prompt_tokens_details": {"cached_tokens": prompt // 2},
                                 "completion_tokens_details": {"reasoning_tokens": output // 2}}
        if reported is not None:
            response["_hidden_params"] = {"response_cost": reported}
        return response

    complete.calls = calls
    return complete


def _commit(provider):
    from cognate_reconstruction.agent.schemas import LLMMessage, MessageRole
    messages = [LLMMessage(role=MessageRole.SYSTEM, content="s"),
                LLMMessage(role=MessageRole.USER, content='{"node_id": "X"}')]
    return provider.complete(messages, ()).metadata.usage


def test_committed_gemini_table_matches_the_official_page_read_for_r02():
    table, sha = load_price_table(GEMINI_TABLE)
    price = price_for(table, "gemini/gemini-3.8-flash", date(2026, 10, 25))
    assert (price.input_usd_per_million, price.output_usd_per_million,
            price.cached_input_usd_per_million) == (0.75, 3.75, 0.075)
    # Prices double on 2027-01-01, so the table refuses to price that day.
    with pytest.raises(ValueError, match="re-read"):
        price_for(table, "gemini/gemini-3.8-flash", date(2027, 1, 1))
    with pytest.raises(ValueError, match="no entry"):
        price_for(table, "gemini/gemini-3.7-flash", date(2026, 10, 25))
    assert len(sha) == 64


def test_table_validation_is_strict():
    with pytest.raises(ValueError):
        PriceTable.model_validate_json(json.dumps({"price_table_version": "price-table-v1",
            "prices": [json.loads(_price().model_dump_json())] * 2}))
    with pytest.raises(ValueError):
        _price(input_usd_per_million=0)
    with pytest.raises(ValueError):
        _price(valid_from="2027-01-01")


def test_cost_is_an_upper_bound_charging_cached_input_at_the_full_rate():
    # 1M prompt tokens of which half cached, 100k output (incl. reasoning).
    assert priced_cost(_price(), 1_000_000, 100_000) == pytest.approx(0.75 + 0.375)
    assert priced_cost(_price(), None, 10) is None
    assert priced_cost(_price(), 10, None) is None


def test_adapter_prices_an_unpriced_response_and_keeps_the_reported_figure_apart():
    unpriced = _commit(LiteLLMProvider("test-model", completion_fn=_completion(), price=_price()))
    assert unpriced.cost_usd == pytest.approx((1000 * 0.75 + 200 * 3.75) / 1e6)
    assert (unpriced.cost_source, unpriced.provider_reported_cost_usd) == ("price_table", None)
    assert (unpriced.cached_input_tokens, unpriced.reasoning_output_tokens) == (500, 100)

    both = _commit(LiteLLMProvider("test-model", completion_fn=_completion(reported=0.0001), price=_price()))
    assert both.cost_source == "price_table" and both.provider_reported_cost_usd == 0.0001

    no_table = _commit(LiteLLMProvider("test-model", completion_fn=_completion(reported=0.0001)))
    assert (no_table.cost_usd, no_table.cost_source) == (0.0001, "provider_reported")

    # Without token counts the table cannot price; cost stays unknown, never zero.
    tokenless = _commit(LiteLLMProvider("test-model", completion_fn=_completion(usage=False), price=_price()))
    assert tokenless is None
    with pytest.raises(ValueError, match="price entry is for"):
        LiteLLMProvider("other-model", price=_price())


def test_pricing_keys_cannot_travel_through_provider_config(tmp_path):
    # Why the table exists: LiteLLM's documented per-call pricing kwargs are
    # refused by the secret filter, which treats every `*_token` key as a secret.
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"input_cost_per_token": 7.5e-7, "output_cost_per_token": 3.75e-6}))
    with pytest.raises(ValueError, match="secret"):
        load_provider_options(path)


def _run(tmp_path, monkeypatch, completion, *extra):
    real = LiteLLMProvider
    monkeypatch.setattr(cli, "LiteLLMProvider",
                        lambda model, **kwargs: real(model, completion_fn=completion, **kwargs))
    cli.main(["infer", "--input", str(tmp_path / "input.json"), "--model", "test-model",
              "--output", str(tmp_path / "result.json"), "--trajectories", str(tmp_path / "t.jsonl"),
              "--checkpoint", str(tmp_path / "checkpoint.json"), "--quiet", "--no-events",
              "--run-id", "price-test", *extra])
    return json.loads((tmp_path / "run_summary.json").read_text())


def test_cli_cost_cap_runs_with_a_table_and_refuses_without_one(tmp_path, monkeypatch):
    _prepare(tmp_path)
    table = _table(tmp_path)
    summary = _run(tmp_path, monkeypatch, _completion(), "--max-total-cost-usd", "1",
                   "--price-table", str(table))
    assert summary["usage"]["responses_without_cost"] == 0
    assert summary["usage"]["reported_cost_usd"] == pytest.approx(2 * (1000 * 0.75 + 200 * 3.75) / 1e6)
    journal = [json.loads(line) for line in (tmp_path / "checkpoint.requests.jsonl").read_text().splitlines()]
    assert [r["cost_usd"] for r in journal if r["event"] == "request_end"] == [pytest.approx(0.0015)] * 2

    unpriced = tmp_path / "unpriced"
    unpriced.mkdir()
    _prepare(unpriced)
    with pytest.raises(SystemExit):
        _run(unpriced, monkeypatch, _completion(), "--max-total-cost-usd", "1")
    usage = json.loads((unpriced / "run_summary.json").read_text())["usage"]
    assert usage["responses_without_cost"] == 1 and usage["turns"] == 1


def test_cost_cap_is_checked_after_each_response_so_one_response_of_headroom_is_needed(tmp_path, monkeypatch):
    _prepare(tmp_path)
    # Each response costs 0.0015; a 0.001 cap is crossed by the first response
    # and only then refused: realized spend is cap + at most one response.
    with pytest.raises(SystemExit):
        _run(tmp_path, monkeypatch, _completion(), "--max-total-cost-usd", "0.001",
             "--price-table", str(_table(tmp_path)))
    usage = json.loads((tmp_path / "run_summary.json").read_text())["usage"]
    assert usage["turns"] == 1
    assert 0.001 < usage["reported_cost_usd"] <= 0.001 + 0.0015


def test_table_joins_the_configuration_digest_only_when_used(tmp_path):
    args = cli._parser().parse_args([
        "infer", "--input", "i.json", "--model", "test-model", "--no-preflight"])
    _, plain, public, _ = cli._provider_and_configuration(args)
    assert "price_table" not in public
    priced_args = cli._parser().parse_args([
        "infer", "--input", "i.json", "--model", "test-model", "--no-preflight",
        "--price-table", str(_table(tmp_path))])
    _, priced, public, _ = cli._provider_and_configuration(priced_args)
    assert priced != plain
    assert public["price_table"]["price"]["model"] == "test-model"
    assert len(public["price_table"]["price_table_sha256"]) == 64
