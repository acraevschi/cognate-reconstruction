"""Command-line interface for auditable family reconstruction."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import uuid
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from cognate_reconstruction.agent import (
    DEFAULT_MAX_FAILED_NODES,
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
from cognate_reconstruction.benchmarks import (
    answer_key_path,
    available_definitions,
    available_synthetic_families,
    build_benchmark,
    definition_path,
    load_definition,
    payload_path,
    synthetic_definition_path,
)
from cognate_reconstruction.benchmarks.sweep import (
    aggregate as aggregate_seeds,
    oracle_ceiling as measure_oracle_ceiling,
    read_seed,
    render_text as render_sweep,
)
from cognate_reconstruction.benchmarks.registry import resolve_payload
from cognate_reconstruction.schemas.synthetic import (
    SyntheticAnswerKey,
    SyntheticFamilyDefinition,
)
from cognate_reconstruction.synthesis import generate_family, score_run
from cognate_reconstruction.agent.provider_config import (
    api_key_from_environment,
    load_provider_options,
)
from cognate_reconstruction.ingestion import (
    ingest_payload,
    load_cldf_dataset,
)
from cognate_reconstruction.inspect_run import DEFAULT_FORM_LIMIT, inspect_run
from cognate_reconstruction.ingestion.historical import (
    load_historical_lineage_bindings,
)
from cognate_reconstruction.ingestion.preparation import prepare_payload
from cognate_reconstruction.schemas.anchors import AnchorFile
from cognate_reconstruction.schemas.historical import (
    HistoricalBindingFile,
    HistoricalFormRole,
    HistoricalTargetEvaluation,
)
from cognate_reconstruction.schemas.metrics import MetricDistribution
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
    newick = (
        Path(args.newick_file).expanduser().read_text(encoding="utf-8").strip()
        if args.newick_file
        else None
    )
    payload = prepare_payload(
        dataset,
        variety_ids=args.variety_id,
        concept_ids=args.concept_id,
        binding_requests=binding_requests,
        newick=newick,
        tree_method=args.tree_method,
    )
    _write_json(args.output, payload.model_dump_json(indent=2))
    tree_message = (
        f"validated and normalized supplied classification {args.newick_file}"
        if args.newick_file
        else (
            "no classification supplied; inference will use exploratory "
            f"lexical {args.tree_method} induction"
        )
    )
    lexicons = payload.lexicons
    print(
        f"wrote {args.output}: {len(lexicons)} dataset-scoped varieties, "
        f"{sum(len(item.forms) for item in lexicons)} tokenized evidence forms, "
        f"{len({form.concept_id for item in lexicons for form in item.forms})} concepts, "
        f"{len(payload.historical_form_bindings)} historical node binding(s); "
        f"{tree_message}",
        file=sys.stderr,
    )


def _command_build_benchmark(args: argparse.Namespace) -> None:
    if (args.name is None) == (args.definition is None):
        raise ValueError(
            "build-benchmark takes exactly one of --name or --definition; "
            f"defined benchmarks: {', '.join(available_definitions()) or 'none'}"
        )
    if args.name is not None:
        source = definition_path(args.name)
        if not source.exists():
            raise ValueError(
                f"no benchmark definition named {args.name!r}. Defined: "
                f"{', '.join(available_definitions()) or 'none'}"
            )
        default_output = payload_path(args.name)
    else:
        source = Path(args.definition).expanduser()
        default_output = None
    definition = load_definition(source)
    payload, report = build_benchmark(definition, base_path=source.parent)
    output = Path(args.output) if args.output else default_output
    if output is None:
        raise ValueError(
            "--output is required when a definition is given by path"
        )
    _write_json(output, payload.model_dump_json(indent=2))
    print(f"wrote {output}: {report.summary()}", file=sys.stderr)
    print(
        f"  dataset {report.dataset_path}",
        file=sys.stderr,
    )
    # The gold's nature is printed at build time, not only at scoring time. A
    # reconstruction benchmark whose answer key is itself a reconstruction
    # measures agreement with an analysis; saying so once the number exists is
    # already too late.
    for node_id, kind in zip(
        report.target_node_ids, report.gold_evidence_kinds, strict=True
    ):
        if kind == "reconstructed":
            print(
                f"  NOTE: gold at {node_id} is a published reconstruction, "
                "not an observation. Scores against it measure agreement with "
                "that analysis.",
                file=sys.stderr,
            )
    if definition.provenance.leakage_note:
        print(f"  leakage: {definition.provenance.leakage_note}", file=sys.stderr)


def _command_build_synthetic(args: argparse.Namespace) -> None:
    if (args.name is None) == (args.definition is None):
        raise ValueError(
            "build-synthetic takes exactly one of --name or --definition; "
            "defined families: "
            f"{', '.join(available_synthetic_families()) or 'none'}"
        )
    if args.name is not None:
        source = synthetic_definition_path(args.name)
        if not source.exists():
            raise ValueError(
                f"no synthetic family named {args.name!r}. Defined: "
                f"{', '.join(available_synthetic_families()) or 'none'}"
            )
        default_output = payload_path(args.name)
        default_key = answer_key_path(args.name)
    else:
        source = Path(args.definition).expanduser()
        default_output = default_key = None
    definition = SyntheticFamilyDefinition.model_validate_json(
        source.read_text(encoding="utf-8")
    )
    result = generate_family(definition)
    output = Path(args.output) if args.output else default_output
    key_output = Path(args.answer_key) if args.answer_key else default_key
    if output is None or key_output is None:
        raise ValueError(
            "--output and --answer-key are both required when a definition is "
            "given by path"
        )
    if output.resolve() == key_output.resolve():
        raise ValueError(
            "the answer key must not be written over the payload: it is the "
            "one artifact the model must never see"
        )
    _write_json(output, result.payload.model_dump_json(indent=2))
    _write_json(key_output, result.answer_key.model_dump_json(indent=2))
    print(f"wrote {output}: {result.summary()}", file=sys.stderr)
    print(
        f"wrote {key_output}: the answer key, which is NOT part of the "
        "benchmark input and must not be given to a model",
        file=sys.stderr,
    )


def _command_score_synthetic(args: argparse.Namespace) -> None:
    answer_key = SyntheticAnswerKey.model_validate_json(
        Path(args.answer_key).expanduser().read_text(encoding="utf-8")
    )
    trajectories = TrajectoryDatasetBuilder.read_jsonl(
        Path(args.run_dir).expanduser() / "trajectories.jsonl"
    )
    score = score_run(answer_key, trajectories)
    print(json.dumps(score.as_dict(), indent=2, sort_keys=True))


def _seed_provider_config(
    base: str | None,
    seed_value: int,
    destination: Path,
) -> str | None:
    """Write a per-repetition provider config carrying an explicit `seed`.

    Only used when `--provider-seed-base` is given. Without it, repetitions
    differ by whatever nondeterminism the provider has, which is the honest
    default: a "seed" here is a repetition index and the runner never pretends
    it controls the sampler unless the provider is told a seed.
    """
    options = load_provider_options(base) if base else {}
    options["seed"] = seed_value
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(options, indent=2) + "\n", encoding="utf-8")
    return str(destination)


def _command_run_benchmark(args: argparse.Namespace) -> None:
    if args.seeds < 1:
        raise ValueError("--seeds must be at least 1")
    payload_path = resolve_payload(args.benchmark)
    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    outcomes = []
    for index in range(args.seeds):
        run_dir = out_dir / f"seed-{index:02d}"
        run_dir.mkdir(parents=True, exist_ok=True)
        run_id = f"{args.run_id_prefix}-seed{index:02d}"
        provider_config = args.provider_config
        if args.provider_seed_base is not None:
            provider_config = _seed_provider_config(
                args.provider_config,
                args.provider_seed_base + index,
                run_dir / "provider-config.json",
            )
        command = [
            sys.executable,
            "-m",
            "cognate_reconstruction.cli",
            "infer",
            "--input",
            str(payload_path),
            "--model",
            args.model,
            "--output",
            str(run_dir / "result.json"),
            "--trajectories",
            str(run_dir / "trajectories.jsonl"),
            "--events",
            str(run_dir / "events.jsonl"),
            "--checkpoint",
            str(run_dir / "checkpoint.json"),
            "--run-id",
            run_id,
            "--beam-width",
            str(args.beam_width),
            "--temperature",
            str(args.temperature),
            "--max-turns",
            str(args.max_turns),
            "--max-tool-calls",
            str(args.max_tool_calls),
            "--max-failed-nodes",
            str(args.max_failed_nodes),
        ]
        if args.preset:
            command += ["--preset", args.preset]
        if args.api_base:
            command += ["--api-base", args.api_base]
        if provider_config:
            command += ["--provider-config", provider_config]
        if args.quiet:
            command.append("--quiet")
        command += list(args.infer_arg or ())
        print(
            f"seed {index}: {' '.join(command[3:])}",
            file=sys.stderr,
        )
        # One subprocess per repetition, so a seed that crashes the interpreter
        # costs one seed rather than the sweep. That is the whole reason this
        # is not an in-process loop.
        #
        # Both streams go straight to files rather than through a pipe: a node
        # session can take minutes, and a sweep that buffers its child's output
        # shows a human nothing until the seed is over. `tail -f` on
        # stderr.log is the live view.
        stderr_path = run_dir / "stderr.log"
        with (run_dir / "console.log").open(
            "w", encoding="utf-8"
        ) as console, stderr_path.open("w", encoding="utf-8") as errors:
            completed = subprocess.run(
                command,
                stdout=console,
                stderr=errors,
                text=True,
                check=False,
            )
        stderr_tail = stderr_path.read_text(encoding="utf-8").strip()[-800:]
        outcomes.append(
            read_seed(
                index,
                run_id,
                run_dir,
                completed.returncode,
                stderr_tail=stderr_tail,
            )
        )
        status = "wrote result.json" if outcomes[-1].result_written else (
            "ABANDONED, no result.json"
        )
        print(
            f"seed {index}: exit {completed.returncode}, {status}, "
            f"{outcomes[-1].nodes_committed} of "
            f"{outcomes[-1].nodes_attempted} nodes committed",
            file=sys.stderr,
        )
    summary = aggregate_seeds(
        outcomes,
        benchmark=str(payload_path),
        model=args.model,
        oracle=(
            None
            if args.no_oracle
            else measure_oracle_ceiling(payload_path, args.beam_width)
        ),
    )
    _write_json(out_dir / "aggregate.json", json.dumps(summary, indent=2))
    report = render_sweep(summary)
    (out_dir / "aggregate.txt").write_text(report, encoding="utf-8")
    print(report, end="")
    print(
        f"wrote {out_dir / 'aggregate.json'} and {out_dir / 'aggregate.txt'}",
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


GIVE_UP_COMPONENT = "the give-up thresholds"
"""Name under which the give-up thresholds are recorded in a checkpoint."""

ADVISORY_CONFIGURATION_COMPONENTS = frozenset({GIVE_UP_COMPONENT})
"""Configuration components recorded in a checkpoint but *not* hashed into it.

These decide when the harness stops trying, and nothing else: they cannot
change a committed rule, a validated cascade, or a beam. Hashing them meant
that the one configuration change a stall invites — loosen the thresholds and
resume — was the change that invalidated the checkpoint, so recovering from a
protocol stall required re-running the whole family. They stay recorded so a
resume can *report* that they moved; they are simply not grounds to refuse one.
"""


def _give_up_thresholds(args: argparse.Namespace) -> dict[str, Any]:
    """The settings that decide when the harness gives up on a call or a node."""
    return {
        "max_repeated_tool_failures": args.max_repeated_tool_failures,
        "stall_window_calls": args.stall_window_calls,
        "max_truncated_responses": args.max_truncated_responses,
        "allow_truncation_backoff": args.allow_truncation_backoff,
        "truncation_max_tokens_ceiling": args.truncation_max_tokens_ceiling,
        "fail_fast": args.fail_fast,
        "max_failed_nodes": args.max_failed_nodes,
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
    }
    give_up_settings = _give_up_thresholds(args)
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
        GIVE_UP_COMPONENT: _hash_json(give_up_settings),
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
            if name not in ADVISORY_CONFIGURATION_COMPONENTS
            and checkpoint.configuration_components.get(name, digest) != digest
        ]
        mismatches.extend(changed or ["the configuration"])
    return mismatches


def _changed_advisory_components(
    checkpoint: FamilyCheckpoint,
    components: dict[str, str],
) -> list[str]:
    """Components that moved since the checkpoint but do not refuse a resume.

    Reported rather than enforced. A resumed run that gives up sooner or later
    than the one that wrote the checkpoint is still reconstructing the same
    thing from the same evidence, but an operator should not have to remember
    that they changed a flag.
    """
    return [
        name
        for name in sorted(ADVISORY_CONFIGURATION_COMPONENTS)
        if name in components
        and checkpoint.configuration_components.get(name, components[name])
        != components[name]
    ]


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
        for name in _changed_advisory_components(checkpoint, components):
            print(
                f"note: {name} changed since this checkpoint was written. They "
                "decide when the harness gives up, not what it reconstructs, "
                "so the resume proceeds; the checkpoint keeps the values the "
                "original run used.",
                file=sys.stderr,
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
            fail_fast=args.fail_fast,
            max_failed_nodes=args.max_failed_nodes,
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
    reconstructed = len(result.internal_nodes) - len(result.node_failures)
    print(
        f"wrote {args.output}: {reconstructed} reconstructed "
        f"internal nodes (run {run_id})",
        file=sys.stderr,
    )
    # A run with fallback nodes is not a run with that many reconstructions,
    # and the count above is the number people quote.
    for failure in result.node_failures:
        print(
            f"FAILED NODE {failure.node_id}: {failure.error_type}. Its parent "
            "is an identity fallback, not a reconstruction, and it is not in "
            "the checkpoint; --resume re-runs it.",
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


def _current_trajectory_schema_sha256() -> str:
    """The digest every record written by this build carries.

    Derived exactly as `AgentOrchestrator._trajectory` derives it, so the two
    agree without either importing the other's helper.
    """
    return _hash_json(AgentTrajectory.model_json_schema())


def _schema_variants(trajectories) -> list[dict[str, Any]]:
    """Group records by the exact trajectory schema they were written against.

    `schema_version` stays `2.0` while fields are added with defaults, because a
    reader does not have to behave differently — see the README on when the
    literal is bumped. That leaves a real question a curator cannot otherwise
    answer without hashing things themselves: which 2.0 records carry the new
    counters and which predate them. Every record already records the answer in
    `trajectory_schema_sha256`; this only counts them.
    """
    current = _current_trajectory_schema_sha256()
    counts = Counter(item.trajectory_schema_sha256 for item in trajectories)
    return [
        {
            "trajectory_schema_sha256": digest,
            "records": count,
            "current": digest == current,
        }
        for digest, count in sorted(
            counts.items(), key=lambda item: (item[0] != current, item[0])
        )
    ]


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
        "current_trajectory_schema_sha256": _current_trajectory_schema_sha256(),
        "schema_variants": _schema_variants(trajectories),
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
        "compacted_tool_results": sum(
            item.metrics.compacted_tool_results for item in trajectories
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
        # Reported, not gated. `high_quality` stays a protocol-hygiene filter;
        # whether the branches agreed is closer to a linguistic claim, so it is
        # printed for a reader and changes nothing downstream. See
        # docs/report_reject_or_score.md.
        **_convergence_summary(completed),
        # Distributions, not only pooled means. A corpus whose root nodes are
        # good and whose leaf-adjacent nodes are bad averages to the same
        # numbers as a uniformly mediocre one, and a threshold cannot be
        # calibrated against a number that has already been averaged.
        **_distribution_summary(trajectories, completed),
        "per_node": _per_node_rows(trajectories),
    }


def _distribution(values: Sequence[float]) -> dict[str, Any] | None:
    summary = MetricDistribution.of(values)
    return summary.model_dump(mode="json") if summary is not None else None


def _distribution_summary(trajectories, completed) -> dict[str, Any]:
    steps = [
        item.reconstruction_step
        for item in completed
        if item.reconstruction_step is not None
    ]
    return {
        "protocol_failure_rate_distribution": _distribution(
            [item.metrics.protocol_failure_rate for item in trajectories]
        ),
        "child_convergence_rate_distribution": _distribution(
            [
                step.diagnostics.child_convergence_rate
                for step in steps
                if step.diagnostics.child_convergence_rate is not None
            ]
        ),
        # The concepts a *session* did not select. Nothing to do with the gold
        # proto-forms below, which are the answer key.
        "held_out_convergence_rate_distribution": _distribution(
            [
                item.metrics.held_out_convergence_rate
                for item in completed
                if item.metrics.held_out_convergence_rate is not None
            ]
        ),
        "contrast_reducing_rule_count_distribution": _distribution(
            [
                float(step.diagnostics.contrast_reducing_rule_count)
                for step in steps
                if step.diagnostics.contrast_reducing_rule_count is not None
            ]
        ),
        "rule_coverage_distribution": _distribution(
            [step.diagnostics.rule_coverage for step in steps]
        ),
    }


def _per_node_rows(trajectories) -> list[dict[str, Any]]:
    """One row per node session, so a reader can see the shape, not the mean."""
    rows = []
    for item in trajectories:
        step = item.reconstruction_step
        diagnostics = step.diagnostics if step is not None else None
        rows.append(
            {
                "run_id": item.run_id,
                "node_id": item.node_id,
                "completed": item.completed,
                "high_quality": item.high_quality,
                "tool_calls": item.metrics.tool_call_count,
                "protocol_failures": item.metrics.protocol_failures,
                "protocol_failure_rate": item.metrics.protocol_failure_rate,
                "committed_rules": item.metrics.committed_rule_count,
                "rule_coverage": (
                    diagnostics.rule_coverage if diagnostics else None
                ),
                "contrast_reducing_rule_count": (
                    diagnostics.contrast_reducing_rule_count
                    if diagnostics
                    else None
                ),
                "child_convergence_rate": (
                    diagnostics.child_convergence_rate if diagnostics else None
                ),
                "held_out_convergence_rate": (
                    item.metrics.held_out_convergence_rate
                ),
                "tie_broken_concept_count": (
                    diagnostics.tie_broken_concept_count if diagnostics else None
                ),
            }
        )
    return rows


def _gold_target_summary(paths: Sequence[str]) -> dict[str, Any]:
    """Graded held-out gold accuracy, folded in from one or more `result.json`.

    **These are gold proto-forms — the answer key — and not the same thing as
    `held_out_convergence_rate` above**, which measures agreement among a
    node's children on concepts the session did not select and never leaves the
    node. The two are named apart on purpose; conflating them would report a
    convergence measure as an accuracy.
    """
    evaluations: list[HistoricalTargetEvaluation] = []
    fallback = 0
    for path in paths:
        result = json.loads(
            Path(path).expanduser().read_text(encoding="utf-8")
        )
        for raw in result.get("historical_target_evaluations", ()):
            evaluation = HistoricalTargetEvaluation.model_validate_json(
                json.dumps(raw)
            )
            # A fallback node's beam is the harness's identity commit. Scoring
            # it measures the fallback, so it is counted and excluded.
            if evaluation.failure_fallback:
                fallback += 1
                continue
            evaluations.append(evaluation)

    def graded(field_name: str) -> list[float]:
        values = []
        for evaluation in evaluations:
            if evaluation.graded is None:
                continue
            distribution = getattr(evaluation.graded, field_name)
            if distribution is not None:
                values.append(distribution.mean)
        return values

    return {
        "results_read": len(paths),
        "scored_node_evaluations": len(evaluations),
        "excluded_failure_fallback_evaluations": fallback,
        "gold_evidence_kinds": sorted(
            {
                evaluation.gold_evidence_kind.value
                for evaluation in evaluations
                if evaluation.gold_evidence_kind is not None
            }
        ),
        "top_exact_rate_distribution": _distribution(
            [evaluation.top_exact_rate for evaluation in evaluations]
        ),
        "beam_exact_rate_distribution": _distribution(
            [evaluation.beam_exact_rate for evaluation in evaluations]
        ),
        "top_normalized_edit_distance_distribution": _distribution(
            graded("top_normalized_edit_distance")
        ),
        "beam_best_normalized_edit_distance_distribution": _distribution(
            graded("beam_best_normalized_edit_distance")
        ),
        "top_bcubed_f1_distribution": _distribution(graded("top_bcubed_f1")),
        "by_node": {
            evaluation.node_id: {
                "source_variety_id": evaluation.source_variety_id,
                "gold_evidence_kind": (
                    evaluation.gold_evidence_kind.value
                    if evaluation.gold_evidence_kind is not None
                    else None
                ),
                "evaluated_concepts": evaluation.evaluated_concepts,
                "top_exact_rate": evaluation.top_exact_rate,
                "beam_exact_rate": evaluation.beam_exact_rate,
                "graded": (
                    evaluation.graded.model_dump(mode="json")
                    if evaluation.graded is not None
                    else None
                ),
            }
            for evaluation in evaluations
        },
        "note": (
            "Gold proto-forms withheld from the model. Distinct from "
            "held_out_convergence_rate, which is a per-node split of the "
            "session's own concepts and makes no claim about correctness. "
            "Normalized edit distance is better when lower; B-Cubed F1 is "
            "better when higher."
        ),
    }


def _convergence_summary(
    completed: Sequence[AgentTrajectory],
) -> dict[str, object]:
    """Aggregate what the deterministic steps recorded about child agreement.

    Only steps that actually carry the measure are averaged. Steps written before
    it existed are counted separately rather than folded in as zeroes, which
    would report a corpus of old records as maximally divergent.
    """
    rates = [
        step.diagnostics.child_convergence_rate
        for step in (item.reconstruction_step for item in completed)
        if step is not None and step.diagnostics.child_convergence_rate is not None
    ]
    supports = [
        step.diagnostics.mean_branch_support
        for step in (item.reconstruction_step for item in completed)
        if step is not None and step.diagnostics.mean_branch_support is not None
    ]
    divergent = sum(
        step.diagnostics.divergent_concept_count or 0
        for step in (item.reconstruction_step for item in completed)
        if step is not None
    )
    inspected = [
        (
            step.diagnostics.concepts_inspected,
            step.diagnostics.concepts_available,
        )
        for step in (item.reconstruction_step for item in completed)
        if step is not None
        and step.diagnostics.concepts_inspected is not None
        and step.diagnostics.concepts_available is not None
    ]
    tie_broken = sum(
        step.diagnostics.tie_broken_concept_count or 0
        for step in (item.reconstruction_step for item in completed)
        if step is not None
    )
    return {
        "nodes_with_convergence_recorded": len(rates),
        "tie_broken_concepts": tie_broken,
        "mean_child_convergence_rate": (
            sum(rates) / len(rates) if rates else None
        ),
        "divergent_concepts": divergent,
        "mean_branch_support": (
            sum(supports) / len(supports) if supports else None
        ),
        "concepts_inspected": sum(count for count, _ in inspected),
        "concepts_available": sum(total for _, total in inspected),
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
    summary = _trajectory_summary(trajectories)
    if args.result:
        summary["gold_target_evaluation"] = _gold_target_summary(args.result)
    print(json.dumps(summary, indent=2, sort_keys=True))


def _command_inspect_run(args: argparse.Namespace) -> None:
    text, _ = inspect_run(
        args.run_dir,
        html_path=args.html,
        form_limit=None if args.all_forms else DEFAULT_FORM_LIMIT,
    )
    print(text, end="")
    if args.html:
        print(f"wrote {args.html}", file=sys.stderr)


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
        "--fail-fast",
        action="store_true",
        help=(
            "End the whole run at the first node whose session fails, instead "
            "of recording the failure, committing an identity fallback for "
            "that node, and continuing the traversal."
        ),
    )
    infer.add_argument(
        "--max-failed-nodes",
        type=int,
        default=DEFAULT_MAX_FAILED_NODES,
        help=(
            "Node failures to fall back over before the run stops. 0 is "
            f"equivalent to --fail-fast. Default {DEFAULT_MAX_FAILED_NODES}."
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

    build = subparsers.add_parser(
        "build-benchmark",
        help=(
            "Build a runnable benchmark payload from a declarative definition "
            "and local CLDF."
        ),
    )
    build.add_argument(
        "--name",
        help=(
            "A checked-in definition under benchmarks/. Available: "
            f"{', '.join(available_definitions()) or 'none'}."
        ),
    )
    build.add_argument(
        "--definition",
        help="Path to a benchmark definition JSON file.",
    )
    build.add_argument(
        "--output",
        help=(
            "Where to write the payload. Defaults to "
            "runs/benchmarks/<name>.json for --name."
        ),
    )
    build.set_defaults(handler=_command_build_benchmark)

    sweep = subparsers.add_parser(
        "run-benchmark",
        help=(
            "Run one benchmark N times, tolerate failures, and aggregate the "
            "seeds with spread."
        ),
    )
    sweep.add_argument(
        "--benchmark",
        required=True,
        help="A built payload path, or the name of a defined benchmark.",
    )
    sweep.add_argument("--model", required=True)
    sweep.add_argument("--seeds", type=int, default=3)
    sweep.add_argument("--out-dir", required=True)
    sweep.add_argument("--run-id-prefix", default="sweep")
    sweep.add_argument("--preset", choices=("lm-studio",))
    sweep.add_argument("--api-base")
    sweep.add_argument("--provider-config")
    sweep.add_argument(
        "--provider-seed-base",
        type=int,
        help=(
            "Write a per-repetition provider config setting 'seed' to this "
            "value plus the repetition index. Without it, repetitions differ "
            "only by provider nondeterminism, which the aggregate says."
        ),
    )
    sweep.add_argument("--beam-width", type=int, default=5)
    sweep.add_argument("--temperature", type=float, default=0.1)
    sweep.add_argument("--max-turns", type=int, default=24)
    sweep.add_argument("--max-tool-calls", type=int, default=64)
    sweep.add_argument(
        "--max-failed-nodes",
        type=int,
        default=DEFAULT_MAX_FAILED_NODES,
        help=(
            "Passed to each run. A seed that exhausts this writes no "
            "result.json and is aggregated as abandoned, never as a "
            "completion."
        ),
    )
    sweep.add_argument("--quiet", action="store_true")
    sweep.add_argument(
        "--no-oracle",
        action="store_true",
        help="Skip the oracle-ceiling measurement of the same payload.",
    )
    sweep.add_argument(
        "--infer-arg",
        action="append",
        help=(
            "Extra argument passed through to every `infer` invocation. "
            "Repeatable."
        ),
    )
    sweep.set_defaults(handler=_command_run_benchmark)

    synthetic = subparsers.add_parser(
        "build-synthetic",
        help=(
            "Generate a family from a proto-lexicon and a known cascade, with "
            "a separate answer key."
        ),
    )
    synthetic.add_argument(
        "--name",
        help=(
            "A checked-in family under benchmarks/synthetic/. Available: "
            f"{', '.join(available_synthetic_families()) or 'none'}."
        ),
    )
    synthetic.add_argument(
        "--definition", help="Path to a synthetic family definition JSON file."
    )
    synthetic.add_argument("--output", help="Where to write the benchmark payload.")
    synthetic.add_argument(
        "--answer-key",
        help=(
            "Where to write the true cascade per branch. Never written into "
            "the payload."
        ),
    )
    synthetic.set_defaults(handler=_command_build_synthetic)

    score = subparsers.add_parser(
        "score-synthetic",
        help=(
            "Score a run's committed changes and their direction against a "
            "synthetic answer key."
        ),
    )
    score.add_argument("--answer-key", required=True)
    score.add_argument(
        "--run-dir",
        required=True,
        help="A run directory holding trajectories.jsonl.",
    )
    score.set_defaults(handler=_command_score_synthetic)

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
    summary.add_argument(
        "--result",
        action="append",
        help=(
            "A run's result.json, folded in as graded held-out gold accuracy "
            "with distributions. Repeatable."
        ),
    )
    summary.set_defaults(handler=_command_summarize_trajectories)

    inspect = subparsers.add_parser(
        "inspect-run",
        help="Report one run directory's artifacts in readable form.",
    )
    inspect.add_argument(
        "--run-dir",
        required=True,
        help=(
            "Directory holding result.json and trajectories.jsonl; "
            "events.jsonl is used when present."
        ),
    )
    inspect.add_argument(
        "--html",
        help="Also write a single self-contained HTML file to this path.",
    )
    inspect.add_argument(
        "--all-forms",
        action="store_true",
        help=(
            f"List every reconstructed form instead of the first "
            f"{DEFAULT_FORM_LIMIT} per node."
        ),
    )
    inspect.set_defaults(handler=_command_inspect_run)

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
