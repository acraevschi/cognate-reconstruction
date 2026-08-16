"""Command-line interface for auditable family reconstruction."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from cognate_reconstruction.agent import (
    MAX_PROTOCOL_FAILURE_RATE,
    AgenticNodeReconstructor,
    AgentOrchestrator,
    AgentTrajectory,
    CompositeEventSink,
    ConsoleEventSink,
    JsonlEventSink,
    JsonlTrajectorySink,
    LiteLLMProvider,
    ReconstructionService,
    TrajectoryDatasetBuilder,
    default_tool_registry,
)
from cognate_reconstruction.agent.instructions import load_agent_instructions
from cognate_reconstruction.agent.provider_config import (
    api_key_from_environment,
    load_provider_options,
)
from cognate_reconstruction.ingestion import (
    ingest_payload,
    load_cldf_dataset,
)
from cognate_reconstruction.ingestion.historical import (
    load_historical_lineage_bindings,
    materialize_historical_bindings,
)
from cognate_reconstruction.schemas.anchors import AnchorFile
from cognate_reconstruction.schemas.historical import (
    HistoricalBindingFile,
    HistoricalFormRole,
)
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.schemas.rules import AnchorPolicy
from cognate_reconstruction.traversal import (
    CheckpointStore,
    FamilyCheckpoint,
    RuleBasedReconstructor,
)

DEFAULT_LM_STUDIO_BASE = "http://localhost:1234/v1"


def _api_base(value: str) -> str:
    return value.rstrip("/")


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _hash_json(value: object) -> str:
    return _hash_text(
        json.dumps(value, sort_keys=True, separators=(",", ":"))
    )


def _lm_studio_models(
    api_base: str,
    api_key: str | None,
) -> tuple[str, ...]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(f"{_api_base(api_base)}/models", headers=headers)
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310
            payload = json.load(response)
    except (OSError, URLError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"could not query LM Studio at {_api_base(api_base)!r}: {error}"
        ) from error
    models = payload.get("data", []) if isinstance(payload, dict) else []
    return tuple(
        str(model["id"])
        for model in models
        if isinstance(model, dict) and model.get("id")
    )


def _write_json(path: str | Path, content: str) -> None:
    destination = Path(path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content + "\n", encoding="utf-8")


def _command_models(args: argparse.Namespace) -> None:
    api_key = api_key_from_environment(args.api_key_env)
    for model_id in _lm_studio_models(args.api_base, api_key):
        print(model_id)


def _command_list_lexibank(args: argparse.Namespace) -> None:
    dataset = load_cldf_dataset(args.dataset)
    for lexicon in dataset.lexicons:
        print(
            "\t".join(
                (
                    lexicon.variety_id,
                    lexicon.name,
                    str(len(lexicon.forms)),
                    lexicon.source_glottocode or "",
                    lexicon.tree_glottocode or "",
                )
            )
        )


def _command_prepare_lexibank(args: argparse.Namespace) -> None:
    dataset = load_cldf_dataset(args.dataset)
    if args.historical_role and not args.historical_lineages:
        raise ValueError(
            "--historical-role is valid only with --historical-lineages; "
            "JSON binding files declare each role themselves"
        )
    if args.historical_bindings:
        binding_requests = HistoricalBindingFile.model_validate_json(
            Path(args.historical_bindings)
            .expanduser()
            .read_text(encoding="utf-8")
        )
    elif args.historical_lineages:
        if args.historical_role is None:
            raise ValueError(
                "--historical-lineages requires --historical-role target or anchor"
            )
        binding_requests = load_historical_lineage_bindings(
            args.historical_lineages,
            dataset_id=dataset.dataset_id,
            role=args.historical_role,
        )
    else:
        binding_requests = None
    historical_bindings = (
        materialize_historical_bindings(binding_requests, dataset.lexicons)
        if binding_requests is not None
        else ()
    )
    bound_source_ids = {
        binding.source_variety_id for binding in historical_bindings
    }
    lexicons = dataset.lexicons
    if args.variety_id:
        selected = set(args.variety_id)
        available = {lexicon.variety_id for lexicon in lexicons}
        if unknown := sorted(selected - available):
            raise ValueError(
                f"unknown dataset-scoped variety IDs: {unknown}. Use "
                "`list-lexibank-varieties --dataset ...` and include the "
                f"{dataset.dataset_id!r} dataset prefix"
            )
        lexicons = tuple(
            lexicon for lexicon in lexicons if lexicon.variety_id in selected
        )
    lexicons = tuple(
        lexicon
        for lexicon in lexicons
        if lexicon.variety_id not in bound_source_ids
    )
    concepts = dataset.concepts
    if args.concept_id:
        selected_concepts = set(args.concept_id)
        available_concepts = {
            form.concept_id
            for lexicon in dataset.lexicons
            for form in lexicon.forms
        }
        if unknown := sorted(selected_concepts - available_concepts):
            raise ValueError(
                f"unknown concept IDs: {unknown}. Concept IDs are the exact "
                "Concepticon IDs or dataset-scoped fallback IDs shown in the "
                "prepared evidence"
            )
        lexicons = tuple(
            lexicon.model_copy(
                update={
                    "forms": tuple(
                        form
                        for form in lexicon.forms
                        if form.concept_id in selected_concepts
                    )
                }
            )
            for lexicon in lexicons
        )
        empty_varieties = sorted(
            lexicon.variety_id for lexicon in lexicons if not lexicon.forms
        )
        if empty_varieties:
            raise ValueError(
                "selected concepts leave no tokenized cognate evidence for "
                f"varieties: {empty_varieties}"
            )
        concepts = tuple(
            concept
            for concept in concepts
            if concept.concept_id in selected_concepts
        )
        filtered_bindings = []
        for binding in historical_bindings:
            forms = tuple(
                form
                for form in binding.forms
                if form.concept_id in selected_concepts
            )
            if not forms:
                raise ValueError(
                    f"selected concepts leave historical {binding.role.value} "
                    f"binding {binding.source_variety_id!r} without forms"
                )
            filtered_bindings.append(
                binding.model_copy(update={"forms": forms})
            )
        historical_bindings = tuple(filtered_bindings)
    if len(lexicons) < 2:
        raise ValueError(
            "Lexibank preparation requires at least two selected varieties "
            "with tokenized cognate forms"
        )
    newick = (
        Path(args.newick_file).expanduser().read_text(encoding="utf-8").strip()
        if args.newick_file
        else None
    )
    if historical_bindings and newick is None:
        raise ValueError(
            "historical target/anchor roles require --newick-file with exact "
            "internal node IDs; lineage metadata never induces traversal order"
        )
    payload = WorkbenchPayload(
        lexicons=lexicons,
        concepts=concepts,
        newick=newick,
        historical_form_bindings=historical_bindings,
        tree_method=args.tree_method,
    )
    if newick is not None:
        ingested = ingest_payload(payload)
        payload = payload.model_copy(update={"newick": ingested.tree.newick})
    _write_json(args.output, payload.model_dump_json(indent=2))
    tree_message = (
        f"validated and normalized supplied classification {args.newick_file}"
        if args.newick_file
        else (
            "no classification supplied; inference will use exploratory "
            f"lexical {args.tree_method} induction"
        )
    )
    print(
        f"wrote {args.output}: {len(lexicons)} dataset-scoped varieties, "
        f"{sum(len(item.forms) for item in lexicons)} tokenized evidence forms, "
        f"{len({form.concept_id for item in lexicons for form in item.forms})} concepts, "
        f"{len(historical_bindings)} historical node binding(s); "
        f"{tree_message}",
        file=sys.stderr,
    )


ABSENT_COMPONENT_DIGEST = "absent"
"""Recorded for an optional input that was not supplied at all.

Distinguishing "no anchors" from "these anchors" is the point: supplying an
anchor file to a resume that had none is exactly as much of a change as editing
one.
"""


def _behavioural_input_digests(args: argparse.Namespace) -> dict[str, str]:
    """Digest the model-visible inputs that are not plain CLI scalars.

    These are the inputs a checkpoint hash kept missing: the instruction text
    the model is given, the tool schemas it is given, and any external anchor
    file. The first two use the same derivation as
    `AgentOrchestrator._trajectory`, so a checkpoint and a trajectory written by
    the same run report identical digests.

    Keys are the human-readable phrases used in the refused-resume message.
    """
    definitions = default_tool_registry().definitions()
    return {
        "the agent instructions": _hash_text(load_agent_instructions()),
        "the tool schemas": _hash_json(
            [definition.model_dump(mode="json") for definition in definitions]
        ),
        "the anchor file": (
            _hash_text(
                Path(args.anchors).expanduser().read_text(encoding="utf-8")
            )
            if args.anchors
            else ABSENT_COMPONENT_DIGEST
        ),
    }


def _provider_and_configuration(
    args: argparse.Namespace,
) -> tuple[LiteLLMProvider, str, dict[str, Any], dict[str, str]]:
    options = load_provider_options(args.provider_config)
    api_key = api_key_from_environment(args.api_key_env)
    preset = "lm-studio" if args.lm_studio else args.preset
    model = args.model
    api_base = _api_base(args.api_base) if args.api_base else None
    if preset == "lm-studio":
        api_base = api_base or DEFAULT_LM_STUDIO_BASE
        raw_model = model.removeprefix("openai/")
        if not args.no_preflight:
            available = _lm_studio_models(api_base, api_key)
            if raw_model not in available:
                rendered = ", ".join(available) if available else "no models reported"
                raise ValueError(
                    f"model {raw_model!r} is not reported by LM Studio; "
                    f"available: {rendered}"
                )
        model = f"openai/{raw_model}"
        options.update(
            {
                "api_base": api_base,
                # OpenAI-compatible clients require a value even when local
                # authentication is disabled. This literal is not a secret.
                "api_key": api_key or "lm-studio",
            }
        )
    else:
        if api_base:
            options["api_base"] = api_base
        if api_key:
            options["api_key"] = api_key
    options["temperature"] = args.temperature
    options["timeout"] = args.timeout
    provider = LiteLLMProvider(model, completion_kwargs=options)
    settings = {
        "model": model,
        "preset": preset,
        "api_base": api_base,
        "provider_options": load_provider_options(args.provider_config),
        "temperature": args.temperature,
        "timeout": args.timeout,
        "beam_width": args.beam_width,
        "anchor_policy": args.anchor_policy,
        "anchor_match_factor": args.anchor_match_factor,
        "max_turns": args.max_turns,
        "max_tool_calls": args.max_tool_calls,
        "max_retries": args.max_retries,
        "retry_backoff_seconds": args.retry_backoff_seconds,
        "max_total_turns": args.max_total_turns,
        "max_total_tool_calls": args.max_total_tool_calls,
        "max_run_seconds": args.max_run_seconds,
        "max_total_cost_usd": args.max_total_cost_usd,
        # Thresholds that decide when a node gives up. A flag nobody hashes is
        # a flag that silently changes a resumed run.
        "max_repeated_tool_failures": args.max_repeated_tool_failures,
        "stall_window_calls": args.stall_window_calls,
        "max_truncated_responses": args.max_truncated_responses,
        "allow_truncation_backoff": args.allow_truncation_backoff,
        "truncation_max_tokens_ceiling": args.truncation_max_tokens_ceiling,
    }
    digests = _behavioural_input_digests(args)
    public = {
        **settings,
        "instruction_sha256": digests["the agent instructions"],
        "tool_schema_sha256": digests["the tool schemas"],
        "anchors_sha256": digests["the anchor file"],
    }
    components = {
        **digests,
        "the provider and limit settings": _hash_json(settings),
    }
    return provider, _hash_json(public), public, components


def _event_sink(args: argparse.Namespace):
    sinks = []
    if not args.quiet:
        sinks.append(ConsoleEventSink(max_json_chars=args.max_event_chars))
    if not args.no_events:
        sinks.append(JsonlEventSink(args.events))
    if not sinks:
        return None
    if len(sinks) == 1:
        return sinks[0]
    return CompositeEventSink(sinks)


def _load_anchors(
    path: str | None,
    dataset,
) -> dict[str, tuple]:
    if path is None:
        return {}
    anchor_path = Path(path).expanduser()
    anchors = AnchorFile.model_validate_json(
        anchor_path.read_text(encoding="utf-8")
    )
    return anchors.validate_for_dataset(dataset)


def _resume_mismatches(
    checkpoint: FamilyCheckpoint,
    *,
    input_sha256: str,
    tree_sha256: str,
    configuration_sha256: str,
    components: dict[str, str],
) -> list[str]:
    """Name what changed in terms an operator can act on.

    `configuration_sha256` stays the decision — it is the value every existing
    checkpoint carries — but a bare "configuration" sends the reader to compare
    a dozen unrelated settings. When the checkpoint recorded component digests,
    the message names the ones that actually moved instead.
    """
    mismatches = []
    if checkpoint.input_sha256 != input_sha256:
        mismatches.append("the input dataset")
    if checkpoint.normalized_tree_sha256 != tree_sha256:
        mismatches.append("the normalized tree")
    if checkpoint.configuration_sha256 != configuration_sha256:
        # An older checkpoint recorded no components; `.get` then compares a
        # digest with itself and the message stays honestly generic.
        changed = [
            name
            for name, digest in components.items()
            if checkpoint.configuration_components.get(name, digest) != digest
        ]
        mismatches.extend(changed or ["the configuration"])
    return mismatches


def _seed_trajectories(
    path: str,
    checkpoint: FamilyCheckpoint,
    configuration_sha256: str,
) -> tuple[AgentTrajectory, ...]:
    """Load committed hypotheses for nodes this run will not re-execute.

    A record qualifies only if it is a completed commit, for a node the
    checkpoint already holds, under this run's configuration hash, and from
    this run. See the filter below for why the last two are not the same test.

    A resumed run without them is degraded, not broken — the reconstructed
    lexicons are in the checkpoint either way — so an absent or unreadable file
    warns and continues. A file that is present but fails schema validation is
    a different matter and is raised: silently seeding nothing from a corrupt
    audit artifact would hide the corruption.

    `read_jsonl` materializes the whole file, as it does for its three other
    callers. That is fine at the scale this harness runs at and is left alone
    on purpose; README "Trajectory and training boundary" records the
    measurements and what should trigger a streaming reader.
    """
    source = Path(path).expanduser()
    if not source.exists():
        print(
            f"warning: {source} does not exist; resuming without the "
            "hypotheses committed at already-completed nodes",
            file=sys.stderr,
        )
        return ()
    try:
        loaded = TrajectoryDatasetBuilder.read_jsonl(source)
    except OSError as error:
        print(
            f"warning: could not read {source} ({error}); resuming without "
            "the hypotheses committed at already-completed nodes",
            file=sys.stderr,
        )
        return ()
    except ValueError as error:
        raise ValueError(
            f"could not load prior hypotheses from {source}: {error}"
        ) from error
    completed_nodes = {
        step.parent_node_id for step in checkpoint.completed_steps
    }
    return tuple(
        trajectory
        for trajectory in loaded
        if trajectory.completed
        and trajectory.committed_reconstruction is not None
        and trajectory.node_id in completed_nodes
        # The same compatibility notion the checkpoint itself uses: a
        # hypothesis produced under a different model or a different
        # instruction set must not leak into this run.
        and trajectory.configuration_sha256 == configuration_sha256
        # And it must be *this* run. The configuration hash cannot tell two
        # invocations apart — same model, same input, same settings produce the
        # same hash — and `--trajectories` defaults to one file in the working
        # directory, so two runs append to it. Without this, a node's lexicon
        # could come from the checkpoint's own step while its rules came from a
        # different invocation that happened to be written last: the model
        # would read rules that did not produce the forms it can see.
        # `--run-id` cannot change during `--resume`, so every legitimate
        # record already carries the checkpoint's run ID.
        and trajectory.run_id == checkpoint.run_id
    )


def _command_infer(args: argparse.Namespace) -> None:
    if args.allow_truncation_backoff and args.truncation_max_tokens_ceiling is None:
        raise ValueError(
            "--allow-truncation-backoff requires "
            "--truncation-max-tokens-ceiling; the harness will not override a "
            "user-supplied provider option without an explicit bound"
        )
    input_path = Path(args.input).expanduser()
    input_text = input_path.read_text(encoding="utf-8")
    payload = WorkbenchPayload.model_validate_json(input_text)
    dataset = ingest_payload(payload)
    anchors_by_node = _load_anchors(args.anchors, dataset)
    provider, configuration_sha256, _, components = _provider_and_configuration(
        args
    )

    checkpoint_store = (
        CheckpointStore(args.checkpoint) if args.checkpoint else None
    )
    checkpoint: FamilyCheckpoint | None = None
    seed_trajectories: tuple[AgentTrajectory, ...] = ()
    input_sha256 = _hash_text(input_text)
    tree_sha256 = _hash_text(dataset.tree.newick)
    if args.resume:
        if args.run_id is not None:
            raise ValueError("--run-id cannot be changed during --resume")
        if checkpoint_store is None:
            raise ValueError("--resume requires --checkpoint")
        checkpoint = checkpoint_store.load()
        mismatches = _resume_mismatches(
            checkpoint,
            input_sha256=input_sha256,
            tree_sha256=tree_sha256,
            configuration_sha256=configuration_sha256,
            components=components,
        )
        if mismatches:
            raise ValueError(
                "checkpoint cannot be resumed because these changed: "
                + ", ".join(mismatches)
            )
        run_id = checkpoint.run_id
        seed_trajectories = _seed_trajectories(
            args.trajectories, checkpoint, configuration_sha256
        )
    else:
        if checkpoint_store is not None and checkpoint_store.path.exists():
            raise ValueError(
                f"checkpoint already exists: {checkpoint_store.path}; use "
                "--resume or choose a new checkpoint path"
            )
        run_id = args.run_id or f"run-{uuid.uuid4()}"
        if checkpoint_store is not None:
            checkpoint = FamilyCheckpoint(
                run_id=run_id,
                input_sha256=input_sha256,
                configuration_sha256=configuration_sha256,
                normalized_tree_sha256=tree_sha256,
                configuration_components=components,
            )
            checkpoint_store.save(checkpoint)

    orchestrator = AgentOrchestrator(
        provider,
        max_turns=args.max_turns,
        max_tool_calls=args.max_tool_calls,
        max_retries=args.max_retries,
        retry_backoff_seconds=args.retry_backoff_seconds,
        max_total_turns=args.max_total_turns,
        max_total_tool_calls=args.max_total_tool_calls,
        max_run_seconds=args.max_run_seconds,
        max_total_cost_usd=args.max_total_cost_usd,
        max_repeated_tool_failures=args.max_repeated_tool_failures,
        stall_window_calls=args.stall_window_calls,
        max_truncated_responses=args.max_truncated_responses,
        allow_truncation_backoff=args.allow_truncation_backoff,
        truncation_max_tokens_ceiling=args.truncation_max_tokens_ceiling,
        trajectory_sink=JsonlTrajectorySink(args.trajectories),
        event_sink=_event_sink(args),
        run_id=run_id,
        configuration_sha256=configuration_sha256,
    )
    deterministic = RuleBasedReconstructor(
        beam_width=args.beam_width,
        anchor_policy=AnchorPolicy(args.anchor_policy),
        anchor_match_factor=args.anchor_match_factor,
    )
    service = ReconstructionService(
        AgenticNodeReconstructor(
            orchestrator,
            deterministic=deterministic,
        )
    )

    def save_step(step) -> None:
        nonlocal checkpoint
        if checkpoint_store is None or checkpoint is None:
            return
        checkpoint = checkpoint.with_step(step)
        checkpoint_store.save(checkpoint)

    if args.resume:
        seeded_nodes = {item.node_id for item in seed_trajectories}
        print(
            f"seeded {len(seeded_nodes)} prior committed hypothes"
            f"{'is' if len(seeded_nodes) == 1 else 'es'} from "
            f"{args.trajectories} for nodes restored from the checkpoint",
            file=sys.stderr,
        )

    result = service.reconstruct_family(
        dataset,
        anchors_by_node=anchors_by_node,
        resume_steps=checkpoint.steps_by_node if checkpoint else None,
        seed_trajectories=seed_trajectories,
        on_step_complete=save_step,
    )
    _write_json(args.output, result.model_dump_json(indent=2))
    print(
        f"wrote {args.output}: {len(result.internal_nodes)} reconstructed "
        f"internal nodes (run {run_id})",
        file=sys.stderr,
    )
    print(
        f"appended {len(result.trajectories)} new trajectories to "
        f"{args.trajectories}",
        file=sys.stderr,
    )
    if checkpoint_store is not None:
        print(
            f"checkpoint contains {len(checkpoint.completed_steps if checkpoint else ())} "
            f"completed nodes at {checkpoint_store.path}",
            file=sys.stderr,
        )


def _trajectory_summary(trajectories) -> dict[str, Any]:
    completed = [item for item in trajectories if item.completed]
    models = Counter(item.model_id or "unknown" for item in trajectories)
    failures = Counter(
        item.failure.split(":", 1)[0]
        for item in trajectories
        if item.failure is not None
    )
    tool_failures: Counter[str] = Counter()
    for item in trajectories:
        tool_failures.update(item.metrics.tool_failures_by_type)
    total_tool_calls = sum(item.metrics.tool_call_count for item in trajectories)
    total_failed_tool_calls = sum(
        item.metrics.failed_tool_call_count for item in trajectories
    )
    # Exploratory rejections are counted in the total but not in the gate: only
    # protocol friction says the session was a poor tool-use example.
    total_protocol_failures = sum(item.metrics.protocol_failures for item in trajectories)
    return {
        "schema_version": "2.0",
        "trajectory_count": len(trajectories),
        "completed": len(completed),
        "failed": len(trajectories) - len(completed),
        "high_quality": sum(item.high_quality for item in trajectories),
        "runs": len({item.run_id for item in trajectories}),
        "models": dict(sorted(models.items())),
        "failure_types": dict(sorted(failures.items())),
        "total_turns": sum(item.metrics.turn_count for item in trajectories),
        "total_tool_calls": total_tool_calls,
        "total_failed_tool_calls": total_failed_tool_calls,
        "total_protocol_failures": total_protocol_failures,
        "total_exploratory_failures": total_failed_tool_calls - total_protocol_failures,
        "protocol_failure_rate": (
            total_protocol_failures / total_tool_calls if total_tool_calls else 0.0
        ),
        "max_protocol_failure_rate": MAX_PROTOCOL_FAILURE_RATE,
        "trajectories_above_protocol_failure_rate": sum(
            item.metrics.protocol_failure_rate > MAX_PROTOCOL_FAILURE_RATE
            for item in trajectories
        ),
        "tool_failures_by_type": dict(sorted(tool_failures.items())),
        "truncated_responses": sum(
            item.metrics.truncated_response_count for item in trajectories
        ),
        "forced_tool_choices": sum(
            item.metrics.forced_tool_choice_count for item in trajectories
        ),
        "truncation_backoffs": sum(
            item.metrics.truncation_backoff_applied for item in trajectories
        ),
        "total_retries": sum(item.metrics.retry_count for item in trajectories),
        "committed_rules": sum(
            item.metrics.committed_rule_count for item in completed
        ),
        "committed_no_op_rules": sum(
            item.committed_no_op_rule_count for item in completed
        ),
        "trajectories_with_no_op_rules": sum(
            item.committed_no_op_rule_count > 0 for item in completed
        ),
        "committed_anomalies": sum(
            item.metrics.committed_anomaly_count for item in completed
        ),
        "identity_without_testing": sum(
            item.metrics.identity_without_testing for item in completed
        ),
        "committed_without_inspection": sum(
            item.metrics.committed_without_inspection for item in completed
        ),
        "reported_cost_usd": sum(
            item.metrics.cost_usd or 0.0 for item in trajectories
        ),
    }


def _command_validate_trajectories(args: argparse.Namespace) -> None:
    trajectories = TrajectoryDatasetBuilder.read_jsonl(args.input)
    print(
        json.dumps(
            {
                "valid": True,
                **_trajectory_summary(trajectories),
            },
            indent=2,
            sort_keys=True,
        )
    )


def _command_summarize_trajectories(args: argparse.Namespace) -> None:
    trajectories = TrajectoryDatasetBuilder.read_jsonl(args.input)
    print(json.dumps(_trajectory_summary(trajectories), indent=2, sort_keys=True))


def _command_export_trajectories(args: argparse.Namespace) -> None:
    trajectories = TrajectoryDatasetBuilder.read_jsonl(args.input)
    examples = TrajectoryDatasetBuilder().build(
        trajectories,
        include_incomplete=args.include_incomplete,
        high_quality_only=args.high_quality_only,
        max_anomaly_rate=args.max_anomaly_rate,
    )
    TrajectoryDatasetBuilder.write_jsonl(examples, args.output)
    print(
        f"wrote {len(examples)} generic tool-use examples to {args.output}",
        file=sys.stderr,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cognate-reconstruct",
        description="Run the deterministic cognate-reconstruction harness.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    models = subparsers.add_parser(
        "lm-studio-models",
        help="List model IDs exposed by an LM Studio local server.",
    )
    models.add_argument("--api-base", default=DEFAULT_LM_STUDIO_BASE)
    models.add_argument(
        "--api-key-env",
        help="Read an optional API key from this environment variable.",
    )
    models.set_defaults(handler=_command_models)

    varieties = subparsers.add_parser(
        "list-lexibank-varieties",
        help="List dataset-scoped variety IDs in local Lexibank CLDF.",
    )
    varieties.add_argument("--dataset", required=True)
    varieties.set_defaults(handler=_command_list_lexibank)

    prepare = subparsers.add_parser(
        "prepare-lexibank",
        help="Convert local Lexibank CLDF to strict workbench JSON.",
    )
    prepare.add_argument("--dataset", required=True)
    prepare.add_argument("--output", required=True)
    prepare.add_argument(
        "--variety-id",
        action="append",
        help="Exact dataset-scoped variety ID; repeat to select a subset.",
    )
    prepare.add_argument(
        "--concept-id",
        action="append",
        help=(
            "Exact Concepticon or dataset-scoped fallback concept ID; repeat "
            "to make a bounded experiment subset."
        ),
    )
    prepare.add_argument(
        "--newick-file",
        help=(
            "Recommended: classification Newick whose leaves use exact "
            "dataset-scoped variety IDs."
        ),
    )
    prepare.add_argument(
        "--tree-method",
        choices=["neighbor", "upgma"],
        default="neighbor",
        help="Exploratory lexical-tree fallback when --newick-file is absent.",
    )
    historical_source = prepare.add_mutually_exclusive_group()
    historical_source.add_argument(
        "--historical-bindings",
        help=(
            "Strict JSON mapping source varieties to explicit internal nodes "
            "with target or anchor roles."
        ),
    )
    historical_source.add_argument(
        "--historical-lineages",
        help=(
            "Curated lineage CSV; target variety IDs must also be exact "
            "internal node IDs in --newick-file."
        ),
    )
    prepare.add_argument(
        "--historical-role",
        choices=[role.value for role in HistoricalFormRole],
        help="Role assigned to targets loaded through --historical-lineages.",
    )
    prepare.set_defaults(handler=_command_prepare_lexibank)

    infer = subparsers.add_parser(
        "infer",
        help="Reconstruct every internal node from strict workbench JSON.",
    )
    infer.add_argument("--input", required=True)
    infer.add_argument("--model", required=True)
    infer.add_argument("--output", default="reconstruction_result.json")
    infer.add_argument("--trajectories", default="trajectories.jsonl")
    infer.add_argument(
        "--events",
        default="reconstruction_events.jsonl",
        help="Append structured operational events to this JSONL file.",
    )
    infer.add_argument("--no-events", action="store_true")
    infer.add_argument("--anchors", help="Strict versioned anchor JSON file.")
    infer.add_argument(
        "--preset",
        choices=["lm-studio"],
        help="Optional provider preset; generic LiteLLM identifiers need none.",
    )
    infer.add_argument(
        "--lm-studio",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    infer.add_argument("--api-base")
    infer.add_argument(
        "--api-key-env",
        help=(
            "Read the API key from this environment variable. Secrets are "
            "never written to configs, events, trajectories, or checkpoints."
        ),
    )
    infer.add_argument(
        "--provider-config",
        help=(
            "JSON object of provider-specific non-secret LiteLLM options; "
            "secret-like keys are rejected."
        ),
    )
    infer.add_argument("--no-preflight", action="store_true")
    infer.add_argument("--beam-width", type=int, default=5)
    infer.add_argument(
        "--anchor-policy",
        choices=[policy.value for policy in AnchorPolicy],
        default=AnchorPolicy.ADVISORY.value,
    )
    infer.add_argument("--anchor-match-factor", type=float, default=100.0)
    infer.add_argument("--temperature", type=float, default=0.1)
    infer.add_argument("--timeout", type=float, default=300.0)
    infer.add_argument("--max-turns", type=int, default=24)
    infer.add_argument("--max-tool-calls", type=int, default=64)
    infer.add_argument("--max-retries", type=int, default=2)
    infer.add_argument("--retry-backoff-seconds", type=float, default=1.0)
    infer.add_argument("--max-total-turns", type=int)
    infer.add_argument("--max-total-tool-calls", type=int)
    infer.add_argument("--max-run-seconds", type=float)
    infer.add_argument("--max-total-cost-usd", type=float)
    infer.add_argument(
        "--max-repeated-tool-failures",
        type=int,
        default=3,
        help=(
            "Rejections sharing one (tool, error code) signature inside the "
            "stall window before the node is corrected once and then stopped."
        ),
    )
    infer.add_argument(
        "--stall-window-calls",
        type=int,
        help=(
            "Trailing tool calls the stall detector remembers, successes "
            "included. Defaults to 3x --max-repeated-tool-failures."
        ),
    )
    infer.add_argument(
        "--max-truncated-responses",
        type=int,
        default=3,
        help=(
            "Truncated responses carrying no tool call before the node ends "
            "in ProtocolStallError."
        ),
    )
    infer.add_argument(
        "--allow-truncation-backoff",
        action="store_true",
        help=(
            "Permit the harness to raise max_tokens above the value in "
            "--provider-config after a truncated response with no tool call. "
            "Off by default: max_tokens is your option, not the harness's."
        ),
    )
    infer.add_argument(
        "--truncation-max-tokens-ceiling",
        type=int,
        help=(
            "Hard upper bound for --allow-truncation-backoff, which is "
            "required whenever that flag is set."
        ),
    )
    infer.add_argument(
        "--checkpoint",
        help="Atomically save completed internal-node boundaries here.",
    )
    infer.add_argument(
        "--resume",
        action="store_true",
        help="Resume a matching --checkpoint without rerunning completed nodes.",
    )
    infer.add_argument("--run-id")
    infer.add_argument("--max-event-chars", type=int, default=4000)
    infer.add_argument(
        "--quiet",
        action="store_true",
        help="Disable the readable trace; structured events remain enabled.",
    )
    infer.set_defaults(handler=_command_infer)

    validate = subparsers.add_parser(
        "validate-trajectories",
        help="Strictly validate every line of a trajectory JSONL file.",
    )
    validate.add_argument("--input", required=True)
    validate.set_defaults(handler=_command_validate_trajectories)

    summary = subparsers.add_parser(
        "summarize-trajectories",
        help="Summarize completion, quality, usage, and failure metadata.",
    )
    summary.add_argument("--input", required=True)
    summary.set_defaults(handler=_command_summarize_trajectories)

    export = subparsers.add_parser(
        "export-trajectories",
        help="Export generic future tool-use training examples.",
    )
    export.add_argument("--input", required=True)
    export.add_argument("--output", required=True)
    export.add_argument("--include-incomplete", action="store_true")
    export.add_argument("--high-quality-only", action="store_true")
    export.add_argument("--max-anomaly-rate", type=float)
    export.set_defaults(handler=_command_export_trajectories)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        args.handler(args)
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(2, f"error: {error}\n")


if __name__ == "__main__":
    main()
