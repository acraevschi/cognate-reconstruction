"""Offline recovery lifecycle: rejected requests, partial trees, safe resume and views."""
from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path

import pytest

from cognate_reconstruction import cli
from cognate_reconstruction.agent.events import JsonlEventSink
from cognate_reconstruction.agent.orchestrator import AgentOrchestrator, RunBudgetExceeded, RunCancelled, failed_node_trajectory
from cognate_reconstruction.agent.providers import LiteLLMProvider, ProviderError, ProviderTransientError, ProviderFailureKind, classify_provider_error
from cognate_reconstruction.agent.providers.errors import normalized_provider_error, retry_after_seconds
from cognate_reconstruction.agent.reconstructor import AgenticNodeReconstructor
from cognate_reconstruction.agent.schemas import ProviderResponse, ProviderResponseMetadata, ProviderUsage
from cognate_reconstruction.agent.service import ReconstructionService
from cognate_reconstruction.agent.trajectory import JsonlTrajectorySink, TrajectoryDatasetBuilder
from cognate_reconstruction.benchmarks.sweep import read_seed, aggregate, render_text
from cognate_reconstruction.ingestion import ingest_payload
from cognate_reconstruction.traversal import CheckpointStore, FamilyCheckpoint
from tests.workbench.test_recovery_and_provider import _node_id, _commit_message
from tests.workbench.test_evaluation_contract import plan
from tests.workbench.test_resume_integrity import _infer, _prepare, AutoCommitProvider


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def read(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class HTTPFailure(Exception):
    def __init__(self, status, code=None, retry_after=None):
        super().__init__("untrusted provider prose")
        self.status_code = status
        self.body = {"error": {"code": code}}
        self.headers = {"Retry-After": retry_after} if retry_after is not None else {}


class Fake:
    model = "test-model"

    def __init__(self, *, errors=(), fail_node="INNER", persistent=False, cost=None):
        self.errors = list(errors)
        self.fail_node = fail_node
        self.persistent = persistent
        self.nodes = []
        self.cost = cost

    def complete(self, messages, tools, **kwargs):
        node = _node_id(messages)
        self.nodes.append(node)
        if node == self.fail_node and self.errors:
            error = self.errors[0] if self.persistent else self.errors.pop(0)
            raise error
        message = _commit_message(node)
        if self.cost is not None:
            return ProviderResponse(message=message, metadata=ProviderResponseMetadata(usage=ProviderUsage(cost_usd=self.cost)))
        return message


def service(provider, tmp_path, **controls):
    return ReconstructionService(AgenticNodeReconstructor(AgentOrchestrator(
        provider, instructions="Commit.",
        trajectory_sink=JsonlTrajectorySink(tmp_path / "trajectories.jsonl"),
        event_sink=JsonlEventSink(tmp_path / "events.jsonl"),
        run_id="test", configuration_sha256="hash", **controls,
    )))


@pytest.mark.parametrize("status,code,kind,retryable", [
    (429, "rate_limit_exceeded", ProviderFailureKind.RATE_LIMIT, True),
    (429, "insufficient_quota", ProviderFailureKind.QUOTA, False),
    (429, "RESOURCE_EXHAUSTED", ProviderFailureKind.UNKNOWN, True),
    (429, None, ProviderFailureKind.UNKNOWN, True),
    (503, None, ProviderFailureKind.CAPACITY, True),
    (401, None, ProviderFailureKind.AUTH, False),
    (403, None, ProviderFailureKind.AUTH, False),
    (400, "invalid_argument", ProviderFailureKind.AUTH, False),
    (418, None, ProviderFailureKind.UNKNOWN, False),
])
def test_structured_taxonomy(status, code, kind, retryable):
    meta = classify_provider_error(HTTPFailure(status, code))
    assert (meta.kind, meta.retryable) == (kind, retryable)
    assert "untrusted provider prose" not in meta.model_dump_json()


def test_unknown_prose_and_lost_response_are_never_replayed():
    for error in (TimeoutError("quota billing tier"), ConnectionError("503 unavailable"), RuntimeError("429 quota")):
        meta = classify_provider_error(error)
        assert meta.kind is ProviderFailureKind.UNKNOWN
        assert not meta.retryable
        assert meta.response_state == "unknown"


def test_retry_hints_dates_and_structured_duration():
    now = datetime(2026, 10, 5, 12, tzinfo=UTC)
    assert retry_after_seconds("Mon, 05 Oct 2026 12:01:00 GMT", now=now) == 60
    assert retry_after_seconds("7.5") == 7.5
    assert retry_after_seconds("not a hint") is None
    assert retry_after_seconds("nan") is None
    error = HTTPFailure(429)
    error.body["error"]["details"] = [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "9s"}]
    assert classify_provider_error(error).retry_after_seconds == 9


def test_one_rate_limit_recovery_uses_hint_clock_jitter_and_records_cause(tmp_path):
    clock = Clock()
    provider = Fake(errors=(normalized_provider_error(HTTPFailure(429, "rate_limit_exceeded", "5")),))
    result = service(provider, tmp_path, max_retries=1, retry_backoff_seconds=1,
                     sleep_fn=clock.sleep, clock_fn=clock.read, jitter_fn=lambda _: 1).reconstruct_family(ingest_payload(plan()))
    assert provider.nodes == ["INNER", "INNER", "PROTO"]
    assert clock.now == 5
    assert result.trajectories[0].metrics.retry_count == 1
    assert result.trajectories[0].metrics.provider_attempts == 2
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    retry = next(e for e in events if e["kind"] == "provider_retry")
    assert retry["details"]["provider_failure"]["kind"] == "recoverable_rate_limit"
    assert retry["details"]["delay_seconds"] == 5
    assert result.lifecycle_summary["usage"]["responses_without_cost"] == 2


@pytest.mark.parametrize("run_cap,retry_cap", [(20, 300), (None, 20)])
def test_retry_after_longer_than_remaining_budget_suspends_without_wait(tmp_path, run_cap, retry_cap):
    clock = Clock()
    provider = Fake(errors=(normalized_provider_error(HTTPFailure(429, None, "120")),), persistent=True)
    svc = service(provider, tmp_path, max_run_seconds=run_cap, max_retry_seconds=retry_cap,
                  sleep_fn=clock.sleep, clock_fn=clock.read)
    with pytest.raises(ProviderError) as caught:
        svc.reconstruct_family(ingest_payload(plan()))
    assert provider.nodes == ["INNER"]
    assert clock.sleeps == []
    assert caught.value.stop_reason == "retry_after_exceeds_budget"
    assert svc.last_run_summary["unattempted_node_ids"] == ["PROTO"]
    assert svc.last_run_summary["fallback_node_ids"] == []
    assert svc.last_run_summary["missing_evaluation_outputs"] == 6


@pytest.mark.parametrize("attempts,elapsed,expected", [(2, 300, 3), (20, 35, 3)])
def test_persistent_503_bounds_calls_and_time(tmp_path, attempts, elapsed, expected):
    clock = Clock()
    provider = Fake(errors=(normalized_provider_error(HTTPFailure(503)),), persistent=True)
    svc = service(provider, tmp_path, max_retries=attempts, max_retry_seconds=elapsed,
                  sleep_fn=clock.sleep, clock_fn=clock.read)
    with pytest.raises(ProviderError):
        svc.reconstruct_family(ingest_payload(plan()))
    assert len(provider.nodes) == expected
    assert clock.now == 30
    assert svc.last_run_summary["failure_kind"] == "capacity_unavailability"
    assert svc.last_run_summary["completed_node_ids"] == []


@pytest.mark.parametrize("status,code", [(429, "insufficient_quota"), (401, None), (403, None)])
def test_hard_failures_do_not_walk_tree_even_without_fail_fast(tmp_path, status, code):
    provider = Fake(errors=(normalized_provider_error(HTTPFailure(status, code)),), persistent=True)
    svc = service(provider, tmp_path)
    with pytest.raises(ProviderError):
        svc.reconstruct_family(ingest_payload(plan()))
    assert provider.nodes == ["INNER"]
    assert svc.last_run_summary["interruption_reason"] == "not_retryable"
    assert svc.last_run_summary["fallback_node_ids"] == []


def test_ambiguous_429_stays_unknown_after_exhaustion(tmp_path):
    clock = Clock()
    provider = Fake(errors=(normalized_provider_error(HTTPFailure(429)),), persistent=True)
    svc = service(provider, tmp_path, max_retries=1, sleep_fn=clock.sleep, clock_fn=clock.read)
    with pytest.raises(ProviderError):
        svc.reconstruct_family(ingest_payload(plan()))
    assert svc.last_run_summary["failure_kind"] == "unknown_provider_failure"
    target = svc.last_run_summary["evaluation_report"]["targets"][0]
    assert target["failure_kind"] == "unknown_provider_failure"
    assert target["output_kind"] == "missing"


def test_absent_cost_with_cap_stops_after_first_response(tmp_path):
    provider = Fake()
    svc = service(provider, tmp_path, max_total_cost_usd=1)
    with pytest.raises(RunBudgetExceeded):
        svc.reconstruct_family(ingest_payload(plan()))
    assert provider.nodes == ["INNER"]
    assert svc.last_run_summary["usage"]["responses_without_cost"] == 1
    assert svc.last_run_summary["missing_evaluation_outputs"] == 6


def test_reported_cost_at_cap_stops_without_replaying_response(tmp_path):
    provider = Fake(cost=1)
    svc = service(provider, tmp_path, max_total_cost_usd=1)
    with pytest.raises(RunBudgetExceeded):
        svc.reconstruct_family(ingest_payload(plan()))
    assert provider.nodes == ["INNER"]
    assert svc.last_run_summary["usage"]["reported_cost_usd"] == 1


def test_cancel_during_backoff_keeps_partial_trajectory_without_another_call(tmp_path):
    clock = Clock()
    provider = Fake(errors=(normalized_provider_error(HTTPFailure(503)),), persistent=True)
    svc = service(provider, tmp_path, sleep_fn=clock.sleep, clock_fn=clock.read,
                  cancelled_fn=lambda: clock.now >= 1)
    with pytest.raises(RunCancelled) as caught:
        svc.reconstruct_family(ingest_payload(plan()))
    assert clock.now == 1
    assert provider.nodes == ["INNER"]
    assert failed_node_trajectory(caught.value).metrics.retry_count == 0
    assert svc.last_run_summary["failure_kind"] == "cancelled"


def test_keyboard_cancel_is_recorded(tmp_path):
    provider = Fake(errors=(KeyboardInterrupt(),))
    svc = service(provider, tmp_path)
    with pytest.raises(RunCancelled):
        svc.reconstruct_family(ingest_payload(plan()))
    assert len(TrajectoryDatasetBuilder.read_jsonl(tmp_path / "trajectories.jsonl")) == 1
    assert svc.last_run_summary["status"] == "interrupted"


def test_lost_transport_response_has_one_call(tmp_path):
    provider = Fake(errors=(TimeoutError(),), persistent=True)
    svc = service(provider, tmp_path)
    with pytest.raises(ProviderError):
        svc.reconstruct_family(ingest_payload(plan()))
    assert provider.nodes == ["INNER"]
    assert svc.last_run_summary["provider_failure"]["response_state"] == "unknown"


def test_adapter_disables_nested_retries_redacts_and_bounds_timeout():
    captured = {}
    def completion(**kwargs):
        captured.update(kwargs)
        raise HTTPFailure(429, "insufficient_quota")
    provider = LiteLLMProvider("fake/model", completion_fn=completion, completion_kwargs={"timeout": 600})
    with pytest.raises(ProviderError) as caught:
        provider.complete((), (), timeout_override=3)
    assert captured["num_retries"] == captured["max_retries"] == 0
    assert captured["timeout"] == 3
    assert provider.completion_kwargs == {"timeout": 600}
    assert "untrusted provider prose" not in str(caught.value)


def test_cli_interrupt_resume_retry_change_idempotence_and_semantic_refusal(tmp_path, monkeypatch, capsys):
    _prepare(tmp_path)
    provider = Fake(errors=(normalized_provider_error(HTTPFailure(503)),), fail_node="ROOT", persistent=True)
    with pytest.raises(SystemExit):
        _infer(tmp_path, monkeypatch, "--run-id", "run-test", "--max-retries", "0", provider=provider)
    assert provider.nodes == ["X", "ROOT"]
    store = CheckpointStore(tmp_path / "checkpoint.json")
    assert list(store.load().steps_by_node) == ["X"]
    summary = json.loads((tmp_path / "run_summary.json").read_text())
    assert summary["complete"] is False
    assert summary["attempted_node_ids"] == ["ROOT", "X"]
    assert summary["completed_node_ids"] == ["X"]
    recovered = Fake(fail_node="ROOT")
    _infer(tmp_path, monkeypatch, "--resume", "--max-retries", "8", "--max-retry-seconds", "600", provider=recovered)
    assert recovered.nodes == ["ROOT"]
    assert "operational retry settings changed" in capsys.readouterr().err
    # Another resume produces no model calls, completed events or new JSONL.
    before = (tmp_path / "trajectories.jsonl").read_bytes()
    _infer(tmp_path, monkeypatch, "--resume", "--max-retries", "8", "--max-retry-seconds", "600", provider=recovered)
    assert recovered.nodes == ["ROOT"]
    assert (tmp_path / "trajectories.jsonl").read_bytes() == before
    assert list(store.load().steps_by_node) == ["X", "ROOT"]
    outcome = read_seed(0, "run-test", tmp_path, 0)
    assert outcome.nodes_attempted == outcome.nodes_completed == outcome.nodes_committed == 2
    with pytest.raises(SystemExit):
        _infer(tmp_path, monkeypatch, "--resume", "--temperature", "0.9", provider=recovered)
    assert "provider and limit settings" in capsys.readouterr().err


def test_legacy_checkpoint_keeps_old_retry_hash_and_no_migration(tmp_path, monkeypatch):
    _prepare(tmp_path)
    monkeypatch.setattr(cli, "LiteLLMProvider", lambda *a, **k: AutoCommitProvider())
    args = cli._parser().parse_args(["infer", "--input", str(tmp_path / "input.json"), "--model", "test-model", "--max-retries", "2", "--retry-backoff-seconds", "1"])
    _, old_hash, _, components = cli._provider_and_configuration(args, compatibility_policy="strict-v1")
    checkpoint = FamilyCheckpoint(run_id="run-test", input_sha256="input", normalized_tree_sha256="tree", configuration_sha256=old_hash, configuration_components=components)
    assert checkpoint.compatibility_policy == "strict-v1"
    args.max_retries = 3
    _, changed, _, current = cli._provider_and_configuration(args, compatibility_policy="strict-v1")
    assert cli._resume_mismatches(checkpoint, input_sha256="input", tree_sha256="tree", configuration_sha256=changed, components=current) == ["the provider and limit settings"]
    args.max_retries = 2
    _, same, _, same_components = cli._provider_and_configuration(args, compatibility_policy="strict-v1")
    assert cli._resume_mismatches(checkpoint, input_sha256="input", tree_sha256="tree", configuration_sha256=same, components=same_components) == []


def test_token_override_budget_is_semantic_even_if_retry_patience_changes(tmp_path, monkeypatch):
    _prepare(tmp_path)
    _infer(tmp_path, monkeypatch, "--run-id", "run-test")
    with pytest.raises(SystemExit):
        _infer(tmp_path, monkeypatch, "--resume", "--allow-truncation-backoff", "--truncation-max-tokens-ceiling", "4096")


def test_aggregate_completed_fallback_interrupted_runs_retains_planned_set(tmp_path):
    payload = plan()
    outcomes = []
    for index, provider in enumerate((Fake(), Fake(errors=(RuntimeError("protocol fake"),)), Fake(errors=(normalized_provider_error(HTTPFailure(503)),)))):
        directory = tmp_path / str(index)
        directory.mkdir()
        svc = service(provider, directory, max_retries=0)
        try:
            result = svc.reconstruct_family(ingest_payload(payload))
        except ProviderError:
            (directory / "run_summary.json").write_text(json.dumps(svc.last_run_summary))
            code = 2
        else:
            (directory / "result.json").write_text(result.model_dump_json())
            code = 0
        outcomes.append(read_seed(index, "test", directory, code, payload=payload))
    summary = aggregate(outcomes, benchmark="fake", model="fake")
    assert [o.nodes_committed for o in outcomes] == [2, 1, 0]
    assert [o.nodes_attempted for o in outcomes] == [2, 2, 1]
    assert outcomes[1].evaluation_report.targets[1].evaluation.descendant_fallback_node_ids == ("INNER",)
    assert summary["interruption_causes"] == {"capacity_unavailability": 1}
    assert summary["evaluation_views"]["raw_targets"]["planned_concepts"] == 18
    assert summary["evaluation_views"]["raw_targets"]["missing_outputs"] == 6
    assert summary["evaluation_views"]["raw_targets"]["fallback_outputs"] == 3
    assert "capacity_unavailability" in render_text(summary)


def test_finalized_jsonl_before_checkpoint_is_recovered_without_duplicate_output(tmp_path, monkeypatch):
    _prepare(tmp_path)
    original = CheckpointStore.save
    def interrupted_save(store, checkpoint):
        if checkpoint.completed_steps:
            raise OSError("fake checkpoint write interruption")
        original(store, checkpoint)
    monkeypatch.setattr(CheckpointStore, "save", interrupted_save)
    with pytest.raises(SystemExit):
        _infer(tmp_path, monkeypatch, "--run-id", "run-test")
    assert CheckpointStore(tmp_path / "checkpoint.json").load().completed_steps == ()
    assert [t.node_id for t in TrajectoryDatasetBuilder.read_jsonl(tmp_path / "trajectories.jsonl")] == ["X"]
    monkeypatch.setattr(CheckpointStore, "save", original)
    provider = Fake(fail_node="ROOT")
    _infer(tmp_path, monkeypatch, "--resume", provider=provider)
    assert provider.nodes == ["ROOT"]
    records = TrajectoryDatasetBuilder.read_jsonl(tmp_path / "trajectories.jsonl")
    assert [(t.node_id, t.completed) for t in records] == [("X", True), ("ROOT", True)]


def test_run_usage_caps_survive_resume(tmp_path, monkeypatch):
    _prepare(tmp_path)
    provider = Fake(errors=(normalized_provider_error(HTTPFailure(503)),), fail_node="ROOT")
    with pytest.raises(SystemExit):
        _infer(tmp_path, monkeypatch, "--run-id", "run-test", "--max-retries", "0", "--max-total-turns", "2", provider=provider)
    resumed = Fake(fail_node="ROOT")
    with pytest.raises(SystemExit):
        _infer(tmp_path, monkeypatch, "--resume", "--max-total-turns", "2", provider=resumed)
    assert resumed.nodes == []
    assert json.loads((tmp_path / "run_summary.json").read_text())["failure_kind"] == "resource_interruption"


def test_benchmark_cli_forwards_retry_time_and_cost_limits_per_seed(tmp_path, monkeypatch):
    from types import SimpleNamespace
    _prepare(tmp_path)
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=2)
    monkeypatch.setattr(cli.subprocess, "run", run)
    controls = ["--max-retries=4", "--retry-backoff-seconds=7", "--max-retry-seconds=25",
                "--retry-max-delay-seconds=15", "--max-run-seconds=99", "--max-total-cost-usd=0.5", "--timeout=10"]
    cli.main(["run-benchmark", "--benchmark", str(tmp_path / "input.json"), "--model", "fake", "--seeds", "2",
              "--out-dir", str(tmp_path / "sweep"), "--no-oracle", *["--infer-arg=" + c for c in controls]])
    assert len(commands) == 2
    for command in commands:
        args = cli._parser().parse_args(command[3:])
        assert (args.max_retries, args.retry_backoff_seconds, args.max_retry_seconds, args.retry_max_delay_seconds) == (4, 7, 25, 15)
        assert (args.max_run_seconds, args.max_total_cost_usd, args.timeout) == (99, 0.5, 10)
    summary = json.loads((tmp_path / "sweep" / "aggregate.json").read_text())
    assert summary["seeds_abandoned"] == 2
    assert summary["evaluation_views"]["seeds_with_plan"] == 2


def test_provider_config_cannot_enable_nested_retry_or_fallback():
    for key in ("num_retries", "max_retries", "retry_policy", "fallbacks", "context_window_fallback_dict"):
        with pytest.raises(ValueError, match="harness retry"):
            LiteLLMProvider("fake/model", completion_kwargs={key: 1})


def test_global_litellm_retry_is_refused_before_any_completion(monkeypatch):
    import sys
    from types import SimpleNamespace
    litellm = SimpleNamespace(num_retries=2, completion=lambda **kwargs: pytest.fail("no request allowed"))
    monkeypatch.setitem(sys.modules, "litellm", litellm)
    with pytest.raises(ProviderError, match="global LiteLLM retries"):
        LiteLLMProvider("fake/model").complete((), ())


def test_stale_fallback_ancestor_does_not_supply_output_after_resume_interrupt(tmp_path, monkeypatch):
    from tests.workbench.test_node_failure_fallback import _infer as fallback_infer, CommitProvider
    from cognate_reconstruction.inspect_run import load_run, build_report, render_text as inspect_text
    from tests.workbench.test_resume_integrity import _payload
    fallback_infer(tmp_path, monkeypatch, provider=CommitProvider(fail_at=("X",)))
    assert (tmp_path / "result.json").exists()
    with pytest.raises(SystemExit):
        fallback_infer(tmp_path, monkeypatch, "--resume", "--max-retries", "0",
                       provider=Fake(errors=(normalized_provider_error(HTTPFailure(503)),), fail_node="X"))
    # The old result/ancestor remain banked, but the current interrupted attempt
    # cannot salvage the ancestor based on that old direct fallback.
    outcome = read_seed(0, "run-test", tmp_path, 2, payload=_payload())
    assert not outcome.result_written
    assert outcome.nodes_completed == outcome.nodes_committed == 0
    assert all(n.status != "committed" for n in outcome.evaluation_report.operational_nodes)
    assert "INCOMPLETE RUN" in inspect_text(build_report(load_run(tmp_path)))


def test_old_fallback_ancestor_with_equal_beams_is_not_reused_as_new_commit(tmp_path, monkeypatch):
    from tests.workbench.test_node_failure_fallback import _infer as fallback_infer, CommitProvider
    fallback_infer(tmp_path, monkeypatch, provider=CommitProvider(fail_at=("X",)))
    # Simulate a completed X receipt followed by interruption before checkpoint:
    # identity X can have exactly the old fallback beam. Receipt chronology must
    # still force a fresh ancestor rather than laundering its old fallback use.
    path = tmp_path / "trajectories.jsonl"
    saved = path.read_text()
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    fallback_infer(shadow, monkeypatch, provider=CommitProvider())
    x = TrajectoryDatasetBuilder.read_jsonl(shadow / "trajectories.jsonl")[0]
    old = TrajectoryDatasetBuilder.read_jsonl(path)[0]
    x = x.model_copy(update={"configuration_sha256": old.configuration_sha256, "run_id": old.run_id})
    path.write_text(saved + x.model_dump_json(exclude_computed_fields=True) + "\n")
    recovered = CommitProvider()
    fallback_infer(tmp_path, monkeypatch, "--resume", provider=recovered)
    assert recovered.nodes == ["ROOT"]


def test_adapter_timeout_is_shortened_to_remaining_run_budget(tmp_path):
    clock = Clock()
    captured = []
    def completion(**kwargs):
        captured.append(kwargs)
        raise HTTPFailure(503)
    svc = service(LiteLLMProvider("fake/model", completion_fn=completion, completion_kwargs={"timeout": 600}),
                  tmp_path, max_retries=0, max_run_seconds=20, clock_fn=clock.read, sleep_fn=clock.sleep)
    with pytest.raises(ProviderError):
        svc.reconstruct_family(ingest_payload(plan()))
    assert captured[0]["timeout"] == 20


def test_backoff_oversleep_does_not_make_a_late_request(tmp_path):
    clock = Clock()
    def late_sleep(seconds):
        clock.now += 5
    provider = Fake(errors=(normalized_provider_error(HTTPFailure(503)),), persistent=True)
    svc = service(provider, tmp_path, max_retry_seconds=4, retry_backoff_seconds=1,
                  clock_fn=clock.read, sleep_fn=late_sleep)
    with pytest.raises(ProviderError) as caught:
        svc.reconstruct_family(ingest_payload(plan()))
    assert provider.nodes == ["INNER"]
    assert caught.value.stop_reason == "retry_elapsed_limit"


def test_banked_redacted_failures_keep_unknown_causes_without_prose_parsing():
    examples = json.loads(Path("tests/fixtures/provider_recovery/banked_events.json").read_text())["events"]
    assert len(examples) == 4
    for example in examples:
        details = example["details"]
        assert "error" not in details
        # Banked events retained exception classes, not structured quota/TPM
        # bodies/status metadata. Construct only that saved class evidence.
        error = type(details["error_type"], (Exception,), {})("redacted")
        meta = classify_provider_error(error)
        assert meta.kind is ProviderFailureKind.UNKNOWN
        assert meta.http_status is None
    assert {e["details"]["error_type"] for e in examples} >= {"RateLimitError", "ServiceUnavailableError", "Timeout"}


def test_operator_driver_forwards_recovery_controls_without_starting_provider(tmp_path, monkeypatch):
    import runpy
    from argparse import Namespace
    from types import SimpleNamespace
    driver = runpy.run_path("skills/run-cognate-reconstruction/driver.py")
    run = driver["cmd_run"]
    captured = []
    monkeypatch.setitem(run.__globals__, "find_python", lambda: "fake-python")
    monkeypatch.setitem(run.__globals__, "triage", lambda _: None)
    def popen(command, **kwargs):
        captured.append(command)
        return SimpleNamespace(stdout=iter(()), wait=lambda: 2)
    monkeypatch.setattr(run.__globals__["subprocess"], "Popen", popen)
    args = Namespace(preset="", api_base=None, no_autostart=True, model="fake", input="fake.json", run_dir=str(tmp_path),
                     max_turns=3, max_tool_calls=4, max_run_seconds=50, timeout=8, max_retries=2,
                     retry_backoff_seconds=3, max_retry_seconds=15, retry_max_delay_seconds=7,
                     inventory_protocol="stored-hypothesis", provider_config=None, agent_instructions=None,
                     max_total_cost_usd=.2, api_key_env=None, reasoning_effort=None, temperature=None, quiet=True)
    assert run(args) == 2
    parsed = cli._parser().parse_args(captured[0][3:])
    assert (parsed.max_retries, parsed.retry_backoff_seconds, parsed.max_retry_seconds, parsed.retry_max_delay_seconds) == (2, 3, 15, 7)
    assert (parsed.max_run_seconds, parsed.timeout, parsed.max_total_cost_usd) == (50, 8, .2)


def test_missing_resume_usage_under_caps_does_not_spend_again(tmp_path, monkeypatch):
    _prepare(tmp_path)
    _infer(tmp_path, monkeypatch, "--run-id", "run-test", "--max-total-turns", "2")
    (tmp_path / "trajectories.jsonl").unlink()
    (tmp_path / "run_summary.json").unlink()
    # All completed nodes require no calls; introducing an unfinished node with
    # missing effort cannot make a cumulative cap start at zero.
    store = CheckpointStore(tmp_path / "checkpoint.json")
    store.save(store.load().model_copy(update={"completed_steps": store.load().completed_steps[:1]}))
    provider = Fake(fail_node="ROOT")
    with pytest.raises(SystemExit):
        _infer(tmp_path, monkeypatch, "--resume", "--max-total-turns", "2", provider=provider)
    assert provider.nodes == []
    assert "usage history unavailable" in json.loads((tmp_path / "run_summary.json").read_text())["interruption_reason"]


def test_void_marker_excludes_even_completed_root_hits_but_retains_coverage(tmp_path):
    payload = plan()
    result = service(Fake(), tmp_path).reconstruct_family(ingest_payload(payload))
    (tmp_path / "result.json").write_text(result.model_dump_json())
    (tmp_path / "VOID.txt").write_text("operator exclusion; no cause is inferred from this text")
    outcome = read_seed(0, "test", tmp_path, 0, payload=payload)
    summary = aggregate([outcome], benchmark="fake", model="fake")
    assert outcome.linguistic_exclusion_reason == "operator_marked_void"
    assert outcome.evaluation_report.raw_target_summary.available_outputs == 6
    assert summary["gold_targets"]["scored_evaluations"] == 0
    assert summary["evaluation_views"]["raw_targets"] is None
    assert summary["all_run_coverage"] == {"planned_concepts": 6, "available_outputs": 6, "missing_outputs": 0}
    assert len(summary["excluded_linguistic_seeds"]) == 1


def test_resume_emits_each_node_commit_and_completion_once(tmp_path, monkeypatch):
    from tests.workbench.test_node_failure_fallback import _infer as with_events
    provider = Fake(errors=(normalized_provider_error(HTTPFailure(503)),), fail_node="ROOT")
    with pytest.raises(SystemExit):
        with_events(tmp_path, monkeypatch, "--max-retries", "0", provider=provider)
    with_events(tmp_path, monkeypatch, "--resume", "--max-retries", "2", provider=Fake())
    before = (tmp_path / "trajectories.jsonl").read_bytes()
    with_events(tmp_path, monkeypatch, "--resume", "--max-retries", "2", provider=Fake())
    assert (tmp_path / "trajectories.jsonl").read_bytes() == before
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    for node in ("X", "ROOT"):
        for kind in ("node_commit", "node_complete"):
            assert sum(e["node_id"] == node and e["kind"] == kind for e in events) == 1
    changes = [e for e in events if e["kind"] == "resume_settings_changed"]
    assert changes[0]["details"]["original_retry_settings"]["max_retries"] == 0
    assert changes[0]["details"]["current_retry_settings"]["max_retries"] == 2
