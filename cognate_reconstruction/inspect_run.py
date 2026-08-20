"""A readable report over one run directory's artifacts.

This is the artifact-facing view: it reads `result.json` and
`trajectories.jsonl` (and `events.jsonl` when present) and states what each node
committed, what the deterministic step did with it, and — when the workflow
filter rejected a session — exactly which condition it failed. The run-triage
skill's `driver.py triage` remains the event-facing view, reconstructing the
turn-by-turn timeline from `events.jsonl`; it shells out to this report for the
artifact sections rather than reimplementing them.

Nothing here judges historical correctness, including the cross-node section:
observations there are mechanical comparisons of committed rule text for a human
to adjudicate. They carry no score, do not reach `high_quality`, and have no
effect on the beam.
"""

from __future__ import annotations

import html
import json
import textwrap
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cognate_reconstruction.agent.error_codes import classify_tool_error_code
from cognate_reconstruction.agent.trajectory import (
    AgentTrajectory,
    TrajectoryDatasetBuilder,
)
from cognate_reconstruction.schemas.historical import HistoricalTargetEvaluation
from cognate_reconstruction.schemas.lexicon import LanguageLexicon

RESULT_FILE = "result.json"
TRAJECTORIES_FILE = "trajectories.jsonl"
EVENTS_FILE = "events.jsonl"

DEFAULT_FORM_LIMIT = 40
"""Reconstructed forms printed per node before the listing is summarised.

A 170-concept family would otherwise bury the diagnostics under thousands of
lines. `--all-forms` prints everything; `result.json` always has all of them.
"""

MATERIAL_CONFIDENCE_GAP = 0.25
"""Confidence difference at which one DSL committed twice is worth remarking on.

An observation threshold, not a score: nothing consumes this number except the
decision to print a line for a human to read.
"""

MAX_OBSERVATIONS_PER_KIND = 20

CROSS_NODE_HEADER = (
    "Mechanical observations only. The harness compares committed rule text "
    "across nodes; it does not judge historical correctness, and nothing here "
    "affects high_quality, the beam, or any score."
)


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunArtifacts:
    """Everything readable in a run directory, and what was not there."""

    run_dir: Path
    trajectories: tuple[AgentTrajectory, ...]
    result: Mapping[str, Any] | None
    events: tuple[Mapping[str, Any], ...]
    notes: tuple[str, ...]


def _load_events(path: Path) -> tuple[tuple[Mapping[str, Any], ...], tuple[str, ...]]:
    """Read the operational event log leniently, but say what was skipped.

    Events are an append-only operational stream, and a run killed mid-write can
    leave a partial final line. Refusing the whole report over that would be
    worse than reading the rest — but skipping lines silently would hide real
    corruption, so unreadable lines are counted and reported.
    """
    events: list[Mapping[str, Any]] = []
    unreadable = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            unreadable += 1
            continue
        if isinstance(record, dict):
            events.append(record)
        else:
            unreadable += 1
    notes = (
        (f"{unreadable} unreadable line(s) in {EVENTS_FILE} were skipped",)
        if unreadable
        else ()
    )
    return tuple(events), notes


def load_run(run_dir: str | Path) -> RunArtifacts:
    """Load one run directory, tolerating the artifacts a run may not have left."""
    directory = Path(run_dir).expanduser()
    if not directory.is_dir():
        raise ValueError(f"not a run directory: {directory}")

    notes: list[str] = []
    trajectory_path = directory / TRAJECTORIES_FILE
    trajectories: tuple[AgentTrajectory, ...] = ()
    if trajectory_path.exists():
        trajectories = TrajectoryDatasetBuilder.read_jsonl(trajectory_path)
    else:
        notes.append(f"no {TRAJECTORIES_FILE}: session shape is unavailable")

    result_path = directory / RESULT_FILE
    result: Mapping[str, Any] | None = None
    if result_path.exists():
        # Read as plain JSON rather than through `FamilyReconstructionResult`.
        # The file is written with computed fields included, which the model's
        # own `extra="forbid"` then refuses on read-back, so validating it here
        # would reject every real run. The parts this report needs are validated
        # individually below, where the models do round-trip.
        loaded = json.loads(result_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError(f"{result_path} is not a JSON object")
        result = loaded
    else:
        notes.append(
            f"no {RESULT_FILE}: reconstructed forms come from the trajectories"
        )

    if not trajectories and result is None:
        raise ValueError(
            f"{directory} contains neither {RESULT_FILE} nor {TRAJECTORIES_FILE}"
        )

    events_path = directory / EVENTS_FILE
    events: tuple[Mapping[str, Any], ...] = ()
    if events_path.exists():
        events, event_notes = _load_events(events_path)
        notes.extend(event_notes)
    else:
        notes.append(f"no {EVENTS_FILE}: the operational event counts are omitted")

    return RunArtifacts(
        run_dir=directory,
        trajectories=trajectories,
        result=result,
        events=events,
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# cross-node consistency: observations, never verdicts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommittedRuleView:
    """One committed rule, flattened to what a cross-node comparison needs."""

    node_id: str
    rule_id: str
    source: str
    target: tuple[str, ...]
    replacement: tuple[str, ...]
    environment: str
    confidence: float

    @property
    def correspondence(self) -> str:
        return f"{' '.join(self.target)} > {' '.join(self.replacement)}"


@dataclass(frozen=True)
class CrossNodeObservation:
    kind: str
    nodes: tuple[str, ...]
    detail: str


def _environment_text(environment) -> str:
    left = " ".join(environment.left.tokens) if environment.left else ""
    right = " ".join(environment.right.tokens) if environment.right else ""
    if environment.word_initial:
        left = f"# {left}".strip()
    if environment.word_final:
        right = f"{right} #".strip()
    rendered = f"{left}_{right}".strip()
    return rendered or "_"


def committed_rule_views(
    trajectories: Iterable[AgentTrajectory],
) -> tuple[CommittedRuleView, ...]:
    views: list[CommittedRuleView] = []
    for trajectory in trajectories:
        commit = trajectory.committed_reconstruction
        if commit is None:
            continue
        for parsed in commit.parsed_rules:
            views.append(
                CommittedRuleView(
                    node_id=trajectory.node_id,
                    rule_id=parsed.rule.rule_id,
                    source=parsed.rule.source,
                    target=tuple(parsed.rule.target.tokens),
                    replacement=tuple(parsed.rule.replacement.tokens),
                    environment=_environment_text(parsed.rule.environment),
                    confidence=parsed.confidence,
                )
            )
    return tuple(views)


def internal_node_children(
    trajectories: Sequence[AgentTrajectory],
    result: Mapping[str, Any] | None,
) -> dict[str, tuple[str, ...]]:
    """Map each internal node to the internal nodes directly below it.

    Steps come from `result.json` when it is there and from the trajectories'
    own reconstruction steps otherwise, so a run that failed before writing a
    result still gets its adjacency.
    """
    steps: list[tuple[str, tuple[str, ...]]] = []
    if result is not None:
        for step in (result.get("snapshot") or {}).get("steps", []):
            parent = step.get("parent_node_id")
            children = tuple(step.get("child_node_ids") or ())
            if parent:
                steps.append((parent, children))
    seen = {parent for parent, _ in steps}
    for trajectory in trajectories:
        step = trajectory.reconstruction_step
        if step is not None and step.parent_node_id not in seen:
            steps.append((step.parent_node_id, tuple(step.child_node_ids)))
            seen.add(step.parent_node_id)
    internal = {parent for parent, _ in steps}
    return {
        parent: tuple(child for child in children if child in internal)
        for parent, children in steps
    }


def _descendants(
    node_id: str,
    children: Mapping[str, tuple[str, ...]],
) -> tuple[str, ...]:
    found: list[str] = []
    stack = list(children.get(node_id, ()))
    while stack:
        current = stack.pop()
        if current in found:
            continue
        found.append(current)
        stack.extend(children.get(current, ()))
    return tuple(found)


def _confidence_spread_observations(
    views: Sequence[CommittedRuleView],
) -> list[CrossNodeObservation]:
    by_source: dict[str, list[CommittedRuleView]] = defaultdict(list)
    for view in views:
        by_source[view.source].append(view)
    observations: list[CrossNodeObservation] = []
    for source, group in sorted(by_source.items()):
        nodes = {view.node_id for view in group}
        if len(nodes) < 2:
            continue
        confidences = [view.confidence for view in group]
        if max(confidences) - min(confidences) < MATERIAL_CONFIDENCE_GAP:
            continue
        rendered = ", ".join(
            f"{view.node_id} {view.confidence:.2f}"
            for view in sorted(group, key=lambda item: item.node_id)
        )
        observations.append(
            CrossNodeObservation(
                kind="confidence_spread",
                nodes=tuple(sorted(nodes)),
                detail=(
                    f"{len(nodes)} nodes commit `{source}` with different "
                    f"confidence: {rendered}."
                ),
            )
        )
    return observations


def _contradiction_observations(
    views: Sequence[CommittedRuleView],
    children: Mapping[str, tuple[str, ...]],
) -> list[CrossNodeObservation]:
    by_node: dict[str, list[CommittedRuleView]] = defaultdict(list)
    for view in views:
        by_node[view.node_id].append(view)
    observations: list[CrossNodeObservation] = []
    for parent, direct_children in sorted(children.items()):
        for child in direct_children:
            for above in by_node.get(parent, ()):
                for below in by_node.get(child, ()):
                    if above.target != below.target:
                        continue
                    if above.environment != below.environment:
                        continue
                    if above.replacement == below.replacement:
                        continue
                    observations.append(
                        CrossNodeObservation(
                            kind="contradictory_mapping",
                            nodes=(parent, child),
                            detail=(
                                f"{parent} commits `{above.source}` while its "
                                f"child {child} commits `{below.source}`: the "
                                f"same target in the same environment is mapped "
                                f"to `{' '.join(above.replacement)}` above and "
                                f"`{' '.join(below.replacement)}` below."
                            ),
                        )
                    )
    return observations


def _unmentioned_correspondence_observations(
    views: Sequence[CommittedRuleView],
    children: Mapping[str, tuple[str, ...]],
) -> list[CrossNodeObservation]:
    by_node: dict[str, list[CommittedRuleView]] = defaultdict(list)
    for view in views:
        by_node[view.node_id].append(view)
    observations: list[CrossNodeObservation] = []
    for node_id in sorted(children):
        descendants = _descendants(node_id, children)
        if not descendants:
            continue
        own = {view.correspondence for view in by_node.get(node_id, ())}
        established: dict[str, set[str]] = defaultdict(set)
        for descendant in descendants:
            for view in by_node.get(descendant, ()):
                established[view.correspondence].add(descendant)
        for correspondence, sources in sorted(established.items()):
            if correspondence in own:
                continue
            observations.append(
                CrossNodeObservation(
                    kind="unmentioned_correspondence",
                    nodes=(node_id, *sorted(sources)),
                    detail=(
                        f"{node_id} commits no rule mentioning "
                        f"`{correspondence}`, established below it at "
                        f"{', '.join(sorted(sources))}. Expected when the change "
                        "was already complete lower in the tree; worth a look "
                        "when it was not."
                    ),
                )
            )
    return observations


def cross_node_observations(
    trajectories: Sequence[AgentTrajectory],
    result: Mapping[str, Any] | None = None,
) -> tuple[CrossNodeObservation, ...]:
    """Compare committed rule inventories across nodes, and only report.

    Three mechanical comparisons: one DSL committed at several nodes with
    materially different confidence, adjacent nodes mapping the same target in
    the same environment to different things, and a correspondence established
    below a node that the node itself never mentions. Each is something a human
    reading the trajectories would want pointed out; none of them is evidence
    that anything is wrong.
    """
    views = committed_rule_views(trajectories)
    children = internal_node_children(trajectories, result)
    observations: list[CrossNodeObservation] = []
    for group in (
        _confidence_spread_observations(views),
        _contradiction_observations(views, children),
        _unmentioned_correspondence_observations(views, children),
    ):
        observations.extend(group[:MAX_OBSERVATIONS_PER_KIND])
        if len(group) > MAX_OBSERVATIONS_PER_KIND:
            observations.append(
                CrossNodeObservation(
                    kind=group[0].kind,
                    nodes=(),
                    detail=(
                        f"{len(group) - MAX_OBSERVATIONS_PER_KIND} further "
                        f"{group[0].kind} observation(s) not shown."
                    ),
                )
            )
    return tuple(observations)


# ---------------------------------------------------------------------------
# report model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleRow:
    rule_id: str
    dsl: str
    scope: str
    confidence: str
    validation: str
    supporting_forms: str
    rationale: str


@dataclass(frozen=True)
class NodeReport:
    node_id: str
    status: str
    model_id: str
    failure: str | None
    failure_fallback: bool
    session: tuple[tuple[str, str], ...]
    summary: str | None
    rules: tuple[RuleRow, ...]
    anomalies: tuple[str, ...]
    diagnostics: tuple[tuple[str, str], ...]
    forms: tuple[tuple[str, str], ...]
    omitted_forms: int
    high_quality: bool
    quality_reasons: tuple[str, ...]


@dataclass(frozen=True)
class RunReport:
    run_dir: str
    header: tuple[tuple[str, str], ...]
    nodes: tuple[NodeReport, ...]
    family: tuple[tuple[str, str], ...]
    historical: tuple[str, ...]
    observations: tuple[CrossNodeObservation, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)
    fallback_nodes: tuple[str, ...] = field(default_factory=tuple)
    """Nodes the traversal walked over on an identity fallback.

    Surfaced at the top of the report, not only per node: a reader who takes
    "7 internal nodes" at face value has been told something false, and the
    per-node status is too far down the page to prevent that.
    """


def _segments(tokens: Iterable[str]) -> str:
    return " ".join(tokens)


def _validated(model, raw: Mapping[str, Any]):
    """Validate one fragment of `result.json` through its own strict model.

    The workbench models are `strict=True`, which rejects a JSON list where a
    tuple is declared — so a fragment already parsed by `json.loads` has to be
    re-serialized to be validated. The round-trip is cheap and keeps the report
    honest: what it prints has passed the same schema the harness wrote it with.
    """
    return model.model_validate_json(json.dumps(raw))


def _best_forms(
    trajectory: AgentTrajectory,
    result: Mapping[str, Any] | None,
) -> list[tuple[str, str]]:
    """Best reconstructed lexicon for one node, preferring the result artifact."""
    if result is not None:
        for node in result.get("internal_nodes", []):
            if node.get("node_id") != trajectory.node_id:
                continue
            lexicon = _validated(LanguageLexicon, node["best_lexicon"])
            return [
                (form.concept_id, _segments(form.segments))
                for form in sorted(lexicon.forms, key=lambda item: item.concept_id)
            ]
    step = trajectory.reconstruction_step
    if step is None:
        return []
    return [
        (
            distribution.concept_id,
            _segments(distribution.candidates[0].segments),
        )
        for distribution in sorted(
            step.output_beam.distributions, key=lambda item: item.concept_id
        )
    ]


def _failure_fallback_node_ids(result: Mapping[str, Any] | None) -> set[str]:
    """Nodes recorded as failure fallbacks by the run that wrote result.json.

    Read from the artifact rather than inferred from an incomplete trajectory:
    a trajectory says the session failed, and only the result says whether the
    traversal continued over it. A run that aborted has neither.
    """
    if result is None:
        return set()
    return {
        str(failure["node_id"])
        for failure in result.get("node_failures", [])
        if failure.get("node_id")
    }


def _event_counts(
    events: Sequence[Mapping[str, Any]],
) -> dict[str, Counter[str]]:
    per_node: dict[str, Counter[str]] = defaultdict(Counter)
    for event in events:
        node_id = str(event.get("node_id", "?"))
        per_node[node_id][str(event.get("kind", "?"))] += 1
    return per_node


NOTABLE_EVENT_KINDS = (
    "provider_retry",
    "response_truncated",
    "truncation_recovery",
    "protocol_correction",
    "node_failed",
    "node_fallback",
)


def _reported(value: object | None) -> str:
    """A counter that was never recorded said nothing, which is not zero."""
    return "not reported" if value is None else str(value)


def _session_rows(
    trajectory: AgentTrajectory,
    events: Counter[str] | None,
) -> tuple[tuple[str, str], ...]:
    metrics = trajectory.metrics
    exploratory = metrics.failed_tool_call_count - metrics.protocol_failures
    # An absent protocol counter is not zero: the record predates the split, so
    # the total stands in and calling any of it exploratory would be invented.
    # Older records still predate failure accounting itself, where a recorded 0
    # means "nothing counted this" rather than "nothing failed" — the event log
    # is the only authority for those, and `driver.py triage` reads it.
    failure_split = (
        f"{metrics.protocol_failure_count} protocol, {exploratory} exploratory"
        if metrics.protocol_failure_count is not None
        else (
            f"{metrics.failed_tool_call_count} recorded, unsplit: this record "
            "predates the exploratory/protocol split. A record older than "
            "failure accounting reports 0 whatever happened, so read "
            "events.jsonl (driver.py triage) before trusting a 0 here"
        )
    )
    rows = [
        ("turns", str(metrics.turn_count)),
        (
            "tool calls",
            f"{metrics.tool_call_count} ({metrics.failed_tool_call_count} rejected)",
        ),
        ("rejections", failure_split),
    ]
    if metrics.tool_failures_by_code:
        rows.append(
            (
                "by error code",
                "; ".join(
                    f"{code} x{count} [{classify_tool_error_code(code).value}]"
                    for code, count in sorted(metrics.tool_failures_by_code.items())
                ),
            )
        )
    rows.append(
        (
            "evidence work",
            f"{metrics.inspection_tool_calls} inspections, "
            f"{metrics.sound_law_tests} sound-law tests, "
            f"{metrics.cascade_tests} cascade previews, "
            f"{metrics.compacted_tool_results} superseded result(s) dropped "
            "from the prompt",
        )
    )
    truncation = (
        f"{metrics.truncated_response_count} truncated response(s), "
        f"{metrics.forced_tool_choice_count} forced tool choice(s), "
        f"{metrics.truncation_backoff_applied} max_tokens backoff(s)"
    )
    rows.append(("truncation", truncation))
    rows.append(("retries", str(metrics.retry_count)))
    rows.append(("duration", f"{metrics.duration_seconds:.1f}s"))
    rows.append(
        (
            "tokens",
            f"in {_reported(metrics.input_tokens)} / "
            f"out {_reported(metrics.output_tokens)} / "
            f"total {_reported(metrics.total_tokens)}"
            + (f" / ${metrics.cost_usd:.4f}" if metrics.cost_usd else ""),
        )
    )
    if events:
        notable = [
            f"{kind} x{events[kind]}"
            for kind in NOTABLE_EVENT_KINDS
            if events.get(kind)
        ]
        rows.append(
            (
                "events",
                f"{sum(events.values())} recorded"
                + (f" ({', '.join(notable)})" if notable else ""),
            )
        )
    return tuple(rows)


def _diagnostic_rows(trajectory: AgentTrajectory) -> tuple[tuple[str, str], ...]:
    step = trajectory.reconstruction_step
    if step is None:
        return ()
    diagnostics = step.diagnostics
    # `applicable_rule_results` was added with the coverage-denominator fix and
    # defaults to 0, so an older step reports "0 applicable" alongside real
    # applications. Say that rather than printing the contradiction.
    applications = (
        f"{diagnostics.successful_applications} applied, "
        f"{diagnostics.rule_results_evaluated} evaluated "
        "(applicable denominator not recorded)"
        if diagnostics.applicable_rule_results == 0
        and diagnostics.successful_applications > 0
        else (
            f"{diagnostics.successful_applications} applied of "
            f"{diagnostics.applicable_rule_results} applicable, "
            f"{diagnostics.rule_results_evaluated} evaluated"
        )
    )
    # The one diagnostic that measures the reconstruction instead of the rules,
    # printed beside the rule numbers so the contrast is visible. It is a report:
    # a hypothesis under which some children disagree may be perfectly good.
    if diagnostics.child_convergence_rate is None:
        convergence = "not recorded (step predates the measure)"
    else:
        convergence = f"{diagnostics.child_convergence_rate:.2f}"
        if diagnostics.divergent_concept_count:
            convergence += (
                f" — {diagnostics.divergent_concept_count} concept(s) diverge"
            )
            if diagnostics.divergent_concept_ids:
                shown = ", ".join(diagnostics.divergent_concept_ids)
                more = diagnostics.divergent_concept_count - len(
                    diagnostics.divergent_concept_ids
                )
                convergence += f": {shown}" + (f", +{more} more" if more else "")
        else:
            convergence += " — every active child agreed"
    return (
        (
            "rules",
            f"{diagnostics.rule_count} (complexity cost "
            f"{diagnostics.rule_complexity_cost})",
        ),
        ("applications", applications),
        # applied / applicable: a child that never showed the target is vacuous
        # for the rule, not a counterexample to it.
        ("rule coverage", f"{diagnostics.rule_coverage:.2f}"),
        ("child convergence", convergence),
        (
            "branch support",
            "not recorded"
            if diagnostics.mean_branch_support is None
            else (
                f"{diagnostics.mean_branch_support:.2f} of the active children "
                "stood behind the winning form"
            ),
        ),
        (
            "evidence coverage",
            "not recorded"
            if diagnostics.concepts_available is None
            else (
                f"{_reported(diagnostics.concepts_inspected)} of "
                f"{diagnostics.concepts_available} concepts inspected"
            ),
        ),
        # How much of this node's output was arbitrary. A tie is not a defect,
        # but a reader should not have to assume every reported form was chosen
        # on evidence.
        (
            "tie-broken forms",
            "not recorded"
            if diagnostics.tie_broken_concept_count is None
            else (
                f"{diagnostics.tie_broken_concept_count}"
                + (
                    f" of {diagnostics.concepts_available}"
                    if diagnostics.concepts_available is not None
                    else ""
                )
                + " chosen by segment order, not mass"
            ),
        ),
        (
            "misses",
            f"target absent {diagnostics.target_absent}, context mismatches "
            f"{diagnostics.context_mismatches}, anchor mismatches "
            f"{diagnostics.anchor_mismatches}",
        ),
        (
            "anomalies",
            f"{diagnostics.anomaly_count} (rate {diagnostics.anomaly_rate:.2f})",
        ),
        (
            "identity",
            "yes" if diagnostics.identity_reconstruction else "no",
        ),
    )


def _rule_rows(trajectory: AgentTrajectory) -> tuple[RuleRow, ...]:
    commit = trajectory.committed_reconstruction
    if commit is None:
        return ()
    return tuple(
        RuleRow(
            rule_id=rule.rule_id or "?",
            dsl=rule.dsl,
            scope=", ".join(rule.source_child_ids),
            confidence=f"{rule.confidence:.2f}",
            validation=rule.validation_call_id or "-",
            supporting_forms=str(len(rule.supporting_form_ids)),
            rationale=rule.rationale or "-",
        )
        for rule in commit.request.rules
    )


def _node_report(
    trajectory: AgentTrajectory,
    result: Mapping[str, Any] | None,
    events: Counter[str] | None,
    *,
    form_limit: int | None,
    failure_fallback: bool = False,
) -> NodeReport:
    commit = trajectory.committed_reconstruction
    forms = _best_forms(trajectory, result)
    omitted = 0
    if form_limit is not None and len(forms) > form_limit:
        omitted = len(forms) - form_limit
        forms = forms[:form_limit]
    anomalies = ()
    if commit is not None:
        anomalies = tuple(
            f"{anomaly.anomaly_type.value} "
            f"({anomaly.form_id or anomaly.concept_id}): {anomaly.explanation}"
            for anomaly in commit.request.anomalies
        )
    if trajectory.completed:
        status = "completed"
    elif failure_fallback:
        status = "FAILED - IDENTITY FALLBACK"
    else:
        status = "FAILED"
    return NodeReport(
        node_id=trajectory.node_id,
        status=status,
        model_id=trajectory.model_id or "unknown",
        failure=trajectory.failure,
        failure_fallback=failure_fallback,
        session=_session_rows(trajectory, events),
        summary=commit.request.summary if commit is not None else None,
        rules=_rule_rows(trajectory),
        anomalies=anomalies,
        diagnostics=_diagnostic_rows(trajectory),
        forms=tuple(forms),
        omitted_forms=omitted,
        high_quality=trajectory.high_quality,
        quality_reasons=trajectory.high_quality_failure_reasons,
    )


def _historical_lines(result: Mapping[str, Any] | None) -> tuple[str, ...]:
    if result is None:
        return ()
    lines = []
    for raw in result.get("historical_target_evaluations", []):
        evaluation = _validated(HistoricalTargetEvaluation, raw)
        lines.append(
            f"{evaluation.node_id} vs {evaluation.source_variety_id}: "
            f"{evaluation.top_exact_matches}/{evaluation.evaluated_concepts} exact "
            f"top matches ({evaluation.top_exact_rate:.2f}), "
            f"{evaluation.beam_exact_matches} in beam "
            f"({evaluation.beam_exact_rate:.2f}), "
            f"{evaluation.missing_reconstruction_concepts} concept(s) missing"
        )
    return tuple(lines)


def build_report(
    artifacts: RunArtifacts,
    *,
    form_limit: int | None = DEFAULT_FORM_LIMIT,
) -> RunReport:
    trajectories = artifacts.trajectories
    events = _event_counts(artifacts.events)
    fallbacks = _failure_fallback_node_ids(artifacts.result)
    nodes = tuple(
        _node_report(
            trajectory,
            artifacts.result,
            events.get(trajectory.node_id),
            form_limit=form_limit,
            failure_fallback=trajectory.node_id in fallbacks,
        )
        for trajectory in trajectories
    )
    fallback_nodes = tuple(
        sorted(fallbacks & {trajectory.node_id for trajectory in trajectories})
        or sorted(fallbacks)
    )
    run_ids = sorted({trajectory.run_id for trajectory in trajectories})
    models = sorted({trajectory.model_id or "unknown" for trajectory in trajectories})
    configurations = sorted(
        {trajectory.configuration_sha256 for trajectory in trajectories}
    )
    header = (
        ("run id", ", ".join(run_ids) or "unknown"),
        ("model", ", ".join(models) or "unknown"),
        (
            "configuration",
            ", ".join(digest[:12] for digest in configurations) or "unknown",
        ),
        (
            "artifacts",
            f"{len(trajectories)} trajectory record(s), "
            f"{(len(artifacts.result.get('internal_nodes', [])) if artifacts.result else 0) - len(fallback_nodes)} "
            f"reconstructed internal node(s), {len(artifacts.events)} event(s)",
        ),
    )
    if fallback_nodes:
        header += (
            (
                "FAILURE FALLBACKS",
                f"{len(fallback_nodes)} node(s) were NOT reconstructed: "
                + ", ".join(fallback_nodes)
                + ". Their parent beams are identity fallbacks committed by "
                "the harness after the session failed, not linguistic claims. "
                "They are excluded from the counts above and from trajectory "
                "export.",
            ),
        )
    completed = [item for item in trajectories if item.completed]
    total_calls = sum(item.metrics.tool_call_count for item in trajectories)
    total_failed = sum(item.metrics.failed_tool_call_count for item in trajectories)
    total_protocol = sum(item.metrics.protocol_failures for item in trajectories)
    codes: Counter[str] = Counter()
    for trajectory in trajectories:
        codes.update(trajectory.metrics.tool_failures_by_code)
    family = (
        (
            "nodes",
            f"{len(trajectories)} attempted, {len(completed)} completed, "
            f"{len(trajectories) - len(completed)} failed"
            + (
                f" ({len(fallback_nodes)} of them walked over as identity "
                "fallbacks)"
                if fallback_nodes
                else ""
            ),
        ),
        (
            "high quality",
            f"{sum(item.high_quality for item in trajectories)} of "
            f"{len(trajectories)} (workflow filter, not a linguistic grade)",
        ),
        (
            "tool calls",
            f"{total_calls} total, {total_failed} rejected "
            f"({total_protocol} protocol, {total_failed - total_protocol} "
            "exploratory)",
        ),
        (
            "error codes",
            ", ".join(f"{code} x{count}" for code, count in sorted(codes.items()))
            or "none",
        ),
        (
            "committed rules",
            str(sum(item.metrics.committed_rule_count for item in completed)),
        ),
        (
            "duration",
            f"{sum(item.metrics.duration_seconds for item in trajectories):.1f}s "
            "of model-loop time",
        ),
    )
    return RunReport(
        run_dir=str(artifacts.run_dir),
        header=header,
        nodes=nodes,
        family=family,
        historical=_historical_lines(artifacts.result),
        observations=cross_node_observations(trajectories, artifacts.result),
        notes=artifacts.notes,
        fallback_nodes=fallback_nodes,
    )


# ---------------------------------------------------------------------------
# plain-text rendering
# ---------------------------------------------------------------------------


TEXT_WIDTH = 78


def _wrapped(prefix: str, value: str) -> list[str]:
    """One labelled line, hanging-indented so long values stay readable."""
    body = textwrap.wrap(value, width=max(TEXT_WIDTH - len(prefix), 24)) or [""]
    return [prefix + body[0]] + [" " * len(prefix) + line for line in body[1:]]


def _fact_lines(
    rows: Iterable[tuple[str, str]],
    *,
    indent: str,
    label_width: int,
) -> list[str]:
    lines: list[str] = []
    for label, value in rows:
        lines.extend(_wrapped(f"{indent}{label:<{label_width}}", value))
    return lines


def _rule_text_block(rule: RuleRow, indent: str) -> list[str]:
    lines = [f"{indent}{rule.dsl}   [{rule.rule_id}]"]
    lines.extend(
        _wrapped(
            f"{indent}  ",
            f"scope {rule.scope} | confidence {rule.confidence} | validation "
            f"{rule.validation} | {rule.supporting_forms} supporting form(s)",
        )
    )
    if rule.rationale != "-":
        lines.extend(_wrapped(f"{indent}  rationale: ", rule.rationale))
    return lines


def render_text(report: RunReport) -> str:
    lines: list[str] = [
        "=" * TEXT_WIDTH,
        f"RUN REPORT  {report.run_dir}",
        "=" * TEXT_WIDTH,
    ]
    if report.fallback_nodes:
        lines.extend(
            [
                "!" * TEXT_WIDTH,
                f"{len(report.fallback_nodes)} NODE(S) WERE NOT RECONSTRUCTED: "
                + ", ".join(report.fallback_nodes),
                "The traversal continued over an identity fallback at each of "
                "them.",
                "!" * TEXT_WIDTH,
            ]
        )
    lines.extend(_fact_lines(report.header, indent="  ", label_width=16))
    for note in report.notes:
        lines.extend(_wrapped("  note            ", note))

    for node in report.nodes:
        lines.extend(
            [
                "",
                "-" * TEXT_WIDTH,
                f"NODE {node.node_id}  [{node.status}]  model {node.model_id}",
                "-" * TEXT_WIDTH,
            ]
        )
        if node.failure:
            lines.extend(_wrapped("  failure: ", node.failure))
        if node.failure_fallback:
            lines.extend(
                _wrapped(
                    "  fallback: ",
                    "this node has no reconstruction. The harness committed an "
                    "identity parent so the walk could continue, and left the "
                    "node out of the checkpoint so --resume re-runs it.",
                )
            )
        lines.append("  SESSION SHAPE")
        lines.extend(_fact_lines(node.session, indent="    ", label_width=18))
        lines.append("  COMMITTED HYPOTHESIS")
        if node.summary is None:
            lines.append("    nothing was committed")
        else:
            lines.extend(_wrapped("    summary: ", node.summary))
            if node.rules:
                lines.append(f"    rules ({len(node.rules)}):")
                for rule in node.rules:
                    lines.extend(_rule_text_block(rule, "      "))
            else:
                lines.append("    rules: none (identity reconstruction)")
            if node.anomalies:
                lines.append(f"    anomalies ({len(node.anomalies)}):")
                for anomaly in node.anomalies:
                    lines.extend(_wrapped("      - ", anomaly))
            else:
                lines.append("    anomalies: none")
        if node.diagnostics:
            lines.append("  DETERMINISTIC OUTCOME")
            lines.extend(
                _fact_lines(node.diagnostics, indent="    ", label_width=18)
            )
        lines.append("  QUALITY")
        lines.append(
            f"    {'high_quality':<18}{'yes' if node.high_quality else 'no'}"
        )
        for reason in node.quality_reasons:
            lines.extend(_wrapped("      failed because: ", reason))
        if node.high_quality:
            lines.append(
                "      workflow filter only; it does not grade the linguistics"
            )
        if node.forms:
            lines.append(
                f"  RECONSTRUCTED FORMS ({len(node.forms) + node.omitted_forms})"
            )
            concept_width = max(len(concept) for concept, _ in node.forms) + 2
            for concept, segments in node.forms:
                lines.append(f"    {concept:<{concept_width}}{segments}")
            if node.omitted_forms:
                lines.append(
                    f"    ... {node.omitted_forms} more (use --all-forms, or "
                    "read result.json)"
                )

    lines.extend(["", "-" * TEXT_WIDTH, "FAMILY SUMMARY", "-" * TEXT_WIDTH])
    lines.extend(_fact_lines(report.family, indent="  ", label_width=16))
    if report.historical:
        lines.append("  historical targets (exact token equality):")
        for line in report.historical:
            lines.extend(_wrapped("    - ", line))

    lines.extend(
        ["", "-" * TEXT_WIDTH, "CROSS-NODE CONSISTENCY", "-" * TEXT_WIDTH]
    )
    lines.extend(_wrapped("  ", CROSS_NODE_HEADER))
    if report.observations:
        for observation in report.observations:
            lines.extend(_wrapped("  - ", observation.detail))
    else:
        lines.append("  No cross-node observations.")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# HTML rendering: one self-contained file, no external anything
# ---------------------------------------------------------------------------


_HTML_STYLE = """
:root {
  color-scheme: light dark;
  --bg: #fbfbfa;
  --panel: #ffffff;
  --ink: #1b1b1a;
  --muted: #5d5d58;
  --line: #dcdcd6;
  --accent: #7a4b12;
  --bad: #8a2f22;
  --good: #245c3a;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14140f;
    --panel: #1c1c18;
    --ink: #eceae1;
    --muted: #a3a196;
    --line: #33332c;
    --accent: #e0b071;
    --bad: #e79284;
    --good: #86c8a1;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 2rem 1.25rem 4rem;
  background: var(--bg);
  color: var(--ink);
  font: 15px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
}
main { max-width: 60rem; margin: 0 auto; }
h1 { font-size: 1.5rem; margin: 0 0 .25rem; }
h2 { font-size: 1.15rem; margin: 2rem 0 .5rem; }
h3 { font-size: .85rem; text-transform: uppercase; letter-spacing: .08em;
     color: var(--muted); margin: 1.1rem 0 .35rem; }
code, .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
section.node, section.panel {
  background: var(--panel); border: 1px solid var(--line);
  border-radius: 8px; padding: 1rem 1.15rem; margin: 1rem 0;
}
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; min-width: 34rem; font-size: .9rem; }
th, td { text-align: left; padding: .35rem .6rem; border-bottom: 1px solid var(--line);
         vertical-align: top; }
th { color: var(--muted); font-weight: 600; white-space: nowrap; }
dl.facts { display: grid; grid-template-columns: minmax(9rem, max-content) 1fr;
           gap: .2rem .9rem; margin: .25rem 0; }
dl.facts dt { color: var(--muted); }
dl.facts dd { margin: 0; }
.badge { display: inline-block; padding: .1rem .5rem; border-radius: 999px;
         font-size: .78rem; border: 1px solid var(--line); }
.badge.good { color: var(--good); }
.badge.bad { color: var(--bad); }
ul { margin: .3rem 0; padding-left: 1.2rem; }
li { margin: .2rem 0; }
p.note { color: var(--muted); font-size: .88rem; margin: .3rem 0; }
"""


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _facts(rows: Iterable[tuple[str, str]]) -> str:
    body = "".join(
        f"<dt>{_e(label)}</dt><dd>{_e(value)}</dd>" for label, value in rows
    )
    return f"<dl class='facts'>{body}</dl>"


def _rule_table(rules: Sequence[RuleRow]) -> str:
    head = (
        "<tr><th>rule</th><th>DSL</th><th>child scope</th><th>conf.</th>"
        "<th>validation</th><th>forms</th><th>rationale</th></tr>"
    )
    body = "".join(
        "<tr>"
        f"<td class='mono'>{_e(rule.rule_id)}</td>"
        f"<td class='mono'>{_e(rule.dsl)}</td>"
        f"<td>{_e(rule.scope)}</td>"
        f"<td>{_e(rule.confidence)}</td>"
        f"<td class='mono'>{_e(rule.validation)}</td>"
        f"<td>{_e(rule.supporting_forms)}</td>"
        f"<td>{_e(rule.rationale)}</td>"
        "</tr>"
        for rule in rules
    )
    return f"<div class='scroll'><table>{head}{body}</table></div>"


def _form_table(node: NodeReport) -> str:
    head = "<tr><th>concept</th><th>reconstructed form</th></tr>"
    body = "".join(
        f"<tr><td>{_e(concept)}</td><td class='mono'>{_e(segments)}</td></tr>"
        for concept, segments in node.forms
    )
    more = (
        f"<p class='note'>{node.omitted_forms} more not shown; "
        "use --all-forms or read result.json.</p>"
        if node.omitted_forms
        else ""
    )
    return f"<div class='scroll'><table>{head}{body}</table></div>{more}"


def render_html(report: RunReport) -> str:
    parts: list[str] = [
        "<!DOCTYPE html>",
        "<html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>Run report {_e(report.run_dir)}</title>",
        f"<style>{_HTML_STYLE}</style></head><body><main>",
        f"<h1>Run report</h1><p class='mono note'>{_e(report.run_dir)}</p>",
    ]
    if report.fallback_nodes:
        parts.append(
            "<section class='panel'><h2 class='bad'>"
            f"{len(report.fallback_nodes)} node(s) were not reconstructed</h2>"
            f"<p>{_e(', '.join(report.fallback_nodes))} — the traversal "
            "continued over an identity fallback at each of them.</p></section>"
        )
    parts.extend(
        [
            "<section class='panel'>",
            _facts(report.header),
        ]
    )
    if report.notes:
        parts.append(
            "<ul>" + "".join(f"<li>{_e(note)}</li>" for note in report.notes) + "</ul>"
        )
    parts.append("</section>")

    for node in report.nodes:
        badge = (
            "<span class='badge good'>high_quality</span>"
            if node.high_quality
            else "<span class='badge bad'>not high_quality</span>"
        )
        parts.append("<section class='node'>")
        parts.append(
            f"<h2>{_e(node.node_id)} "
            f"<span class='badge'>{_e(node.status)}</span> {badge}</h2>"
        )
        if node.failure:
            parts.append(f"<p class='note'>failure: {_e(node.failure)}</p>")
        if node.failure_fallback:
            parts.append(
                "<p class='note'>This node has no reconstruction. The harness "
                "committed an identity parent so the walk could continue, and "
                "left the node out of the checkpoint so <code>--resume</code> "
                "re-runs it.</p>"
            )
        parts.append("<h3>Session shape</h3>")
        parts.append(_facts(node.session))
        parts.append("<h3>Committed hypothesis</h3>")
        if node.summary is None:
            parts.append("<p class='note'>Nothing was committed.</p>")
        else:
            parts.append(f"<p>{_e(node.summary)}</p>")
            if node.rules:
                parts.append(_rule_table(node.rules))
            else:
                parts.append(
                    "<p class='note'>No rules: identity reconstruction.</p>"
                )
            if node.anomalies:
                parts.append(
                    "<ul>"
                    + "".join(f"<li>{_e(item)}</li>" for item in node.anomalies)
                    + "</ul>"
                )
            else:
                parts.append("<p class='note'>No anomalies reported.</p>")
        if node.diagnostics:
            parts.append("<h3>Deterministic outcome</h3>")
            parts.append(_facts(node.diagnostics))
        parts.append("<h3>Quality</h3>")
        if node.quality_reasons:
            parts.append(
                "<ul>"
                + "".join(
                    f"<li>failed because: {_e(reason)}</li>"
                    for reason in node.quality_reasons
                )
                + "</ul>"
            )
        else:
            parts.append(
                "<p class='note'>Passed the workflow filter. That is not a "
                "judgement about the linguistics.</p>"
            )
        if node.forms:
            parts.append(
                f"<h3>Reconstructed forms ({node.omitted_forms + len(node.forms)})</h3>"
            )
            parts.append(_form_table(node))
        parts.append("</section>")

    parts.append("<section class='panel'><h2>Family summary</h2>")
    parts.append(_facts(report.family))
    if report.historical:
        parts.append("<h3>Historical targets (exact token equality)</h3><ul>")
        parts.extend(f"<li>{_e(line)}</li>" for line in report.historical)
        parts.append("</ul>")
    parts.append("</section>")

    parts.append("<section class='panel'><h2>Cross-node consistency</h2>")
    parts.append(f"<p class='note'>{_e(CROSS_NODE_HEADER)}</p>")
    if report.observations:
        parts.append("<ul>")
        parts.extend(
            f"<li>{_e(observation.detail)}</li>" for observation in report.observations
        )
        parts.append("</ul>")
    else:
        parts.append("<p class='note'>No cross-node observations.</p>")
    parts.append("</section></main></body></html>")
    return "\n".join(parts) + "\n"


def inspect_run(
    run_dir: str | Path,
    *,
    html_path: str | Path | None = None,
    form_limit: int | None = DEFAULT_FORM_LIMIT,
) -> tuple[str, str | None]:
    """Build the report, returning its text and any HTML that was written."""
    artifacts = load_run(run_dir)
    report = build_report(artifacts, form_limit=form_limit)
    document = render_html(report) if html_path is not None else None
    if html_path is not None and document is not None:
        destination = Path(html_path).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(document, encoding="utf-8")
    return render_text(report), document
