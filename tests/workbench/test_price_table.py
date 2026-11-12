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
    PriceTable, TokenPrice, load_price_table, price_for, priced_cost, priced_uncached_cost,
)
from tests.workbench.test_resume_integrity import _prepare

REPO = Path(__file__).resolve().parents[2]
GEMINI_TABLE = REPO / "examples/pricing/gemini-3.8-flash.price-table.json"
_DEFAULT_CACHED = object()


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


def _completion(*, prompt=1000, output=200, cached=_DEFAULT_CACHED, reported=None, usage=True):
    """OpenAI-shaped responses committing identity at whichever node is asked."""
    calls = []
    cached_value = (prompt // 2) if cached is _DEFAULT_CACHED else cached

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
            usage_payload = {
                "prompt_tokens": prompt,
                "completion_tokens": output,
                "total_tokens": prompt + output,
                "completion_tokens_details": {"reasoning_tokens": output // 2},
            }
            if cached_value is not None:
                usage_payload["prompt_tokens_details"] = {"cached_tokens": cached_value}
            response["usage"] = usage_payload
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


def test_cost_applies_cached_rate_when_reported_and_falls_back_to_uncached_upper_bound():
    # 3-arg call (`cached_input_tokens=None`) and `priced_uncached_cost` charge full input rate:
    assert priced_cost(_price(), 1_000_000, 100_000) == pytest.approx(0.75 + 0.375)
    assert priced_uncached_cost(_price(), 1_000_000, 100_000) == pytest.approx(0.75 + 0.375)
    assert priced_cost(_price(), None, 10) is None
    assert priced_cost(_price(), 10, None) is None
    assert priced_uncached_cost(_price(), None, 10) is None
    assert priced_uncached_cost(_price(), 10, None) is None

    # 4-arg call with 500k cached of 1M prompt + 100k output:
    assert priced_cost(_price(), 1_000_000, 100_000, 500_000) == pytest.approx(
        500_000 * 0.75 / 1e6 + 500_000 * 0.075 / 1e6 + 100_000 * 3.75 / 1e6
    )

    # Without `cached_input_usd_per_million` in the price entry, fall back conservatively to full rate:
    no_cached_rate = _price(cached_input_usd_per_million=None)
    assert priced_cost(no_cached_rate, 1_000_000, 100_000, 500_000) == pytest.approx(0.75 + 0.375)

    # Defensive clamping when `cached_input_tokens > input_tokens` or `< 0`:
    assert priced_cost(_price(), 1_000_000, 100_000, 1_500_000) == pytest.approx(
        1_000_000 * 0.075 / 1e6 + 100_000 * 3.75 / 1e6
    )
    assert priced_cost(_price(), 1_000_000, 100_000, -250) == pytest.approx(0.75 + 0.375)

    # Exact B02 Stage 1 aggregate replay against `GEMINI_TABLE`:
    table, _ = load_price_table(GEMINI_TABLE)
    gemini_price = price_for(table, "gemini/gemini-3.8-flash", date(2026, 11, 11))
    assert priced_cost(gemini_price, 4_434_603, 88_855, 3_588_670) == pytest.approx(1.236806)
    assert priced_uncached_cost(gemini_price, 4_434_603, 88_855) == pytest.approx(3.6591585)


def test_adapter_prices_an_unpriced_response_and_keeps_the_reported_figure_apart():
    # Default `_completion()` reports prompt=1000, cached=500, output=200 -> 0.0011625 USD:
    unpriced = _commit(LiteLLMProvider("test-model", completion_fn=_completion(), price=_price()))
    assert unpriced.cost_usd == pytest.approx((500 * 0.75 + 500 * 0.075 + 200 * 3.75) / 1e6)
    assert unpriced.cost_usd == pytest.approx(0.0011625)
    assert (unpriced.cost_source, unpriced.provider_reported_cost_usd) == ("price_table", None)
    assert (unpriced.cached_input_tokens, unpriced.reasoning_output_tokens) == (500, 100)

    # When `prompt_tokens_details` is absent (`cached_tokens=None`), charges uncached `0.0015`:
    uncached_resp = _commit(
        LiteLLMProvider("test-model", completion_fn=_completion(cached=None), price=_price())
    )
    assert uncached_resp.cached_input_tokens is None
    assert uncached_resp.cost_usd == pytest.approx(0.0015)

    both = _commit(LiteLLMProvider("test-model", completion_fn=_completion(reported=0.0001), price=_price()))
    assert both.cost_source == "price_table" and both.provider_reported_cost_usd == 0.0001
    assert both.cost_usd == pytest.approx(0.0011625)

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
    assert summary["usage"]["reported_cost_usd"] == pytest.approx(2 * 0.0011625)
    journal = [json.loads(line) for line in (tmp_path / "checkpoint.requests.jsonl").read_text().splitlines()]
    assert [r["cost_usd"] for r in journal if r["event"] == "request_end"] == [pytest.approx(0.0011625)] * 2

    unpriced = tmp_path / "unpriced"
    unpriced.mkdir()
    _prepare(unpriced)
    with pytest.raises(SystemExit):
        _run(unpriced, monkeypatch, _completion(), "--max-total-cost-usd", "1")
    usage = json.loads((unpriced / "run_summary.json").read_text())["usage"]
    assert usage["responses_without_cost"] == 1 and usage["turns"] == 1


def test_cost_cap_is_checked_after_each_response_so_one_response_of_headroom_is_needed(tmp_path, monkeypatch):
    _prepare(tmp_path)
    # Each cached-adjusted response costs 0.0011625; a 0.001 cap is crossed by the first
    # response and only then refused: realized spend is cap + at most one response.
    with pytest.raises(SystemExit):
        _run(tmp_path, monkeypatch, _completion(), "--max-total-cost-usd", "0.001",
             "--price-table", str(_table(tmp_path)))
    usage = json.loads((tmp_path / "run_summary.json").read_text())["usage"]
    assert usage["turns"] == 1
    assert 0.001 < usage["reported_cost_usd"] <= 0.001 + 0.0011625


def test_table_joins_the_configuration_digest_only_when_used(tmp_path, monkeypatch):
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

    # Historical `c-gemini-r04` and `b02-burmish-gemini` configuration_sha256 digests stay bit-for-bit invariant:
    monkeypatch.setenv("GEMINI_API_KEY", "offline-dummy-key")
    r04_manifest = REPO / "runs/experiments/r04-stage-c-20261029-v2/manifest.stage-c.json"
    if r04_manifest.exists():
        r04_argv = json.loads(r04_manifest.read_text(encoding="utf-8"))["arm"]["gemini-r04"]["argv"][3:]
        _, r04_sha, _, _ = cli._provider_and_configuration(
            cli._parser().parse_args([*r04_argv, "--no-preflight"])
        )
        assert r04_sha == "339adb1338add17c78a0b5477d9c0b9dd85b64501e2be314951627861adce38a"

    b02_manifest = REPO / "runs/experiments/b02-burmish-gemini-benchmark/manifest.b02-burmish.json"
    if b02_manifest.exists():
        b02_argv = json.loads(b02_manifest.read_text(encoding="utf-8"))["arm"]["burmish-gemini"][
            "stage1_maruic_gate"
        ]["argv"][3:]
        _, b02_sha, _, _ = cli._provider_and_configuration(
            cli._parser().parse_args([*b02_argv, "--no-preflight"])
        )
        assert b02_sha == "89a49065883951bc68bc0943898ae6681be7ee6f9371ef52fe3c417d5e69ed22"


def test_b04_driver_profiles_48k_headroom_polynesian_and_cached_ledger_breakdown(tmp_path):
    from dataclasses import replace
    from cognate_reconstruction.benchmarks.ledger import RunResources, read_run_resources
    from tools import real_family_benchmark_probe as probe

    # 1. Legacy B02 constants & 32k headroom stay intact:
    assert probe.MAX_OUTPUT_TOKENS == 32_768
    assert probe.B04_MAX_OUTPUT_TOKENS == 49_152
    table, _ = load_price_table(GEMINI_TABLE)
    gemini_price = price_for(table, "gemini/gemini-3.8-flash", date(2026, 11, 12))

    b02_bound = probe.resource_bound(
        cost_cap_usd=8.50,
        max_run_seconds=3600.0,
        max_turns_total=108,
        price=gemini_price,
        expected_cached_usd_range=(1.80, 2.80),
    )
    assert b02_bound["one_response_headroom_usd"] == pytest.approx(0.909312)
    assert b02_bound["worst_case_upper_bound_usd"] == pytest.approx(9.409312)

    # 2. 48k (`49,152`) worst-case 0%-cache single-response headroom == $0.970752:
    b04_burmish_s1 = probe.resource_bound(
        cost_cap_usd=2.50,
        max_run_seconds=1500.0,
        max_turns_total=36,
        price=gemini_price,
        expected_cached_usd_range=(0.60, 1.50),
        max_output_tokens=49_152,
    )
    assert b04_burmish_s1["one_response_headroom_usd"] == pytest.approx(0.970752)
    assert b04_burmish_s1["worst_case_upper_bound_usd"] == pytest.approx(3.470752)
    assert b04_burmish_s1["worst_case_upper_bound_usd"] <= 3.48

    b04_burmish_s2 = probe.resource_bound(
        cost_cap_usd=6.50,
        max_run_seconds=3600.0,
        max_turns_total=108,
        price=gemini_price,
        expected_cached_usd_range=(2.00, 4.50),
        max_output_tokens=49_152,
    )
    assert b04_burmish_s2["one_response_headroom_usd"] == pytest.approx(0.970752)
    assert b04_burmish_s2["worst_case_upper_bound_usd"] == pytest.approx(7.470752)
    assert b04_burmish_s2["within_10_usd_hard_ceiling"] is True

    # 3. Auto-detection of B04 defaults (`49,152` + `stored-hypothesis-v2`) from `b04-*` dir and `--stage B04`:
    b04_burmish_dir = tmp_path / "b04-burmish-gemini-rehearsal"
    prof_b04_burm = probe.resolve_benchmark_profile(b04_burmish_dir)
    assert (prof_b04_burm.stage, prof_b04_burm.family) == ("B04", "burmish")
    assert prof_b04_burm.protocol == "stored-hypothesis-v2"
    assert prof_b04_burm.max_output_tokens == 49_152
    assert prof_b04_burm.gate_node_id == "maruic"
    assert prof_b04_burm.stage1_caps["max_total_cost_usd"] == 2.50
    assert prof_b04_burm.stage2_caps["max_total_cost_usd"] == 6.50

    # 4. Polynesian tree verification (`tongic` first post-order node, 7 internal nodes, 252 turns) & manifest auto-detection:
    poly_payload, _, _ = probe.load_benchmark_payload(probe.POLYNESIAN_DEFINITION)
    poly_nodes = probe.postorder_internal_node_ids(poly_payload)
    assert poly_nodes == (
        "tongic",
        "futunic",
        "marquesic",
        "tahitic",
        "central_eastern",
        "nuclear_polynesian",
        "proto_polynesian",
    )
    assert poly_nodes[0] == probe.POLYNESIAN_GATE_NODE_ID == "tongic"
    assert 36 * len(poly_nodes) == probe.POLYNESIAN_MAX_TOTAL_TURNS == 252

    poly_exp_dir = tmp_path / "custom-exp-dir"
    poly_freeze = probe.freeze(
        poly_exp_dir,
        stage="B04",
        family="polynesian",
        include_banked_critic_baselines=False,
    )
    assert (poly_exp_dir / "manifest.b04-polynesian.json").is_file()
    assert json.loads((poly_exp_dir / "inputs/provider-config.json").read_text())["max_tokens"] == 49_152
    assert poly_freeze["budget_ceiling"]["stage1_cost_cap_usd"] == 2.00
    assert poly_freeze["budget_ceiling"]["stage2_cumulative_cost_cap_usd"] == 6.00
    assert poly_freeze["budget_ceiling"]["worst_case_cumulative_upper_bound_usd"] == pytest.approx(6.970752)

    # Subsequent calls with ONLY `experiment_dir` detect `B04` + `polynesian` from `manifest.b04-polynesian.json`:
    s1_dry = probe.run_stage1(poly_exp_dir, dry_run=True)
    assert "--inventory-protocol" in s1_dry["argv"]
    idx_proto = s1_dry["argv"].index("--inventory-protocol")
    assert s1_dry["argv"][idx_proto + 1] == "stored-hypothesis-v2"
    idx_stop = s1_dry["argv"].index("--stop-after-node")
    assert s1_dry["argv"][idx_stop + 1] == "tongic"
    idx_cost = s1_dry["argv"].index("--max-total-cost-usd")
    assert s1_dry["argv"][idx_cost + 1] == "2.00"
    idx_sec = s1_dry["argv"].index("--max-run-seconds")
    assert s1_dry["argv"][idx_sec + 1] == "1200"

    s2_argv = probe.stage2_resume_argv(poly_exp_dir)
    idx_s2_cost = s2_argv.index("--max-total-cost-usd")
    assert s2_argv[idx_s2_cost + 1] == "6.00"

    # 5. `compute_cached_adjusted_cost_usd` derives BOTH uncached upper bound & cached-adjusted cost
    #    from token counts whether `resources.known_cost_usd` was historical uncached (B02) or cached-adjusted (B04+):
    empty_res = read_run_resources(tmp_path / "nonexistent-run")
    b02_style_res = replace(
        empty_res,
        present=True,
        cost_known=True,
        input_tokens=4_434_603,
        output_tokens=88_855,
        total_tokens=4_523_458,
        cached_input_tokens=3_588_670,
        known_cost_usd=3.6591585,
        total_cost_usd=3.6591585,
    )
    b04_style_res = replace(
        b02_style_res,
        known_cost_usd=1.23680625,
        total_cost_usd=1.23680625,
    )
    for res_case in (b02_style_res, b04_style_res):
        bd = probe.compute_cached_adjusted_cost_usd(res_case, GEMINI_TABLE)
        assert bd["uncached_table_known_cost_usd"] == pytest.approx(3.659158, abs=1e-6)
        assert bd["uncached_table_total_cost_usd"] == pytest.approx(3.659158, abs=1e-6)
        assert bd["cached_adjusted_known_cost_usd"] == pytest.approx(1.236806, abs=1e-6)
        assert bd["cached_adjusted_total_cost_usd"] == pytest.approx(1.236806, abs=1e-6)


def test_offline_b04_polynesian_two_stage_rehearsal_with_live_cached_pricing(tmp_path, monkeypatch):
    from cognate_reconstruction.schemas.historical import (
        GoldEvidenceKind,
        HistoricalFormBinding,
        HistoricalFormRole,
        TargetValidity,
    )
    from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
    from cognate_reconstruction.schemas.lexicon import (
        ConceptMetadata,
        LanguageLexicon,
        LexicalForm,
    )
    from tools import real_family_benchmark_probe as probe

    monkeypatch.setenv("GEMINI_API_KEY", "offline-b04-poly-key")
    payload = WorkbenchPayload(
        newick=(
            "(('walworthpolynesian:Tongan','walworthpolynesian:Niuean')tongic,"
            "('walworthpolynesian:Samoan','walworthpolynesian:Maori')nuclear_polynesian)"
            "proto_polynesian;"
        ),
        concepts=(ConceptMetadata(concept_id="c01", gloss="WATER"),),
        lexicons=tuple(
            LanguageLexicon(
                variety_id=vid,
                name=vid.split(":")[1],
                forms=(
                    LexicalForm(
                        form_id=f"{vid}:c01",
                        variety_id=vid,
                        concept_id="c01",
                        segments=("w", "a", "i"),
                        cognate_set_id="cog1",
                    ),
                ),
            )
            for vid in (
                "walworthpolynesian:Tongan",
                "walworthpolynesian:Niuean",
                "walworthpolynesian:Samoan",
                "walworthpolynesian:Maori",
            )
        ),
        historical_form_bindings=(
            HistoricalFormBinding(
                source_variety_id="walworthpolynesian:Polynesian",
                node_id="proto_polynesian",
                role=HistoricalFormRole.TARGET,
                gold_evidence_kind=GoldEvidenceKind.RECONSTRUCTED,
                target_validity=TargetValidity.VALIDATED,
                forms=(
                    LexicalForm(
                        form_id="proto_polynesian:c01",
                        variety_id="proto_polynesian",
                        concept_id="c01",
                        segments=("w", "a", "i"),
                    ),
                ),
            ),
        ),
    )
    def_path = tmp_path / "mini_polynesian.payload.json"
    def_path.write_text(payload.model_dump_json(indent=2) + "\n", encoding="utf-8")

    exp_dir = tmp_path / "b04-polynesian-rehearsal"
    probe.main(
        [
            "freeze",
            "--experiment-dir",
            str(exp_dir),
            "--definition",
            str(def_path),
            "--family",
            "polynesian",
        ]
    )

    def _scripted_completion(*, model, messages, tools, tool_choice, **options):
        assert options.get("max_tokens") == 49_152
        node = re.search(r'"node_id":\s*"([^"]+)"', messages[1]["content"]).group(1)
        tool_msgs = [json.loads(m["content"]) for m in messages if m.get("role") == "tool"]
        if len(tool_msgs) == 0:
            call_name = "summarize_correspondences"
            call_args = {"reading": "local", "min_support": 1, "min_attested_children": 2, "limit": 50}
        elif len(tool_msgs) == 1:
            sets = tool_msgs[0]["result"]["sets"]
            call_name = "test_proto_assembly"
            call_args = {
                "choices": [
                    {
                        "set_id": s["set_id"],
                        "proto_segment": s["segments"][0],
                        "confidence": 1.0,
                        "rationale": "Unanimous retention.",
                    }
                    for s in sets
                ],
                "residue_policy": "drop",
            }
        else:
            call_name = "commit_reconstruction"
            call_args = {
                "node_id": node,
                "hypothesis_id": tool_msgs[1]["result"]["hypothesis_id"],
                "anomalies": [],
                "summary": f"Committed {node}.",
            }
        return {
            "id": f"resp-{node}-{len(tool_msgs)}",
            "model": model,
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": f"call-{node}-{len(tool_msgs)}",
                                "type": "function",
                                "function": {"name": call_name, "arguments": json.dumps(call_args)},
                            }
                        ],
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 10_000,
                "completion_tokens": 500,
                "total_tokens": 10_500,
                "prompt_tokens_details": {"cached_tokens": 8_000},
                "completion_tokens_details": {"reasoning_tokens": 200},
            },
        }

    real_provider = LiteLLMProvider
    monkeypatch.setattr(
        cli,
        "LiteLLMProvider",
        lambda model, **kw: real_provider(model, completion_fn=_scripted_completion, **kw),
    )

    run_dir = probe.default_run_dir(exp_dir)
    assert run_dir.name == "polynesian-gemini"

    # Stage 1 (`tongic` gate) -> `gate-stage1` -> Stage 2 (`--resume`) -> `evaluate` (all auto-detecting family from manifest!):
    cli.main(probe.stage1_argv(exp_dir, run_dir=run_dir, extra_args=("--no-preflight",))[3:])
    probe.main(["gate-stage1", "--experiment-dir", str(exp_dir)])
    gate_doc = json.loads((run_dir / "gate_stage1.json").read_text(encoding="utf-8"))
    assert gate_doc["gate_node_id"] == "tongic"
    assert gate_doc["usable"] is True

    cli.main(probe.stage2_resume_argv(exp_dir, run_dir=run_dir, extra_args=("--no-preflight",))[3:])
    probe.main(["evaluate", "--experiment-dir", str(exp_dir)])

    eval_doc = json.loads((run_dir / "evaluation.json").read_text(encoding="utf-8"))
    assert eval_doc["family"] == "polynesian"
    assert eval_doc["tones_preserved"] is False
    assert eval_doc["stage_gate"]["usable"] is True

    # 9 turns x (2,000 uncached * 0.75 + 8,000 cached * 0.075 + 500 out * 3.75) / 1e6 = 9 * 0.003975 = 0.035775 USD
    # vs uncached 9 * (10,000 * 0.75 + 500 * 3.75) / 1e6 = 9 * 0.009375 = 0.084375 USD:
    assert eval_doc["resources"]["total_cost_usd"] == pytest.approx(0.035775)
    assert eval_doc["cost_breakdown"]["cached_adjusted_total_cost_usd"] == pytest.approx(0.035775)
    assert eval_doc["cost_breakdown"]["uncached_table_total_cost_usd"] == pytest.approx(0.084375)
