"""Run one benchmark several times and aggregate what the seeds disagree about.

The same input fails differently on every run. Three attempts at the Polynesian
benchmark at temperature 0.1 produced three different failure modes at two
different nodes; a fourth committed at four of five node sessions and stalled at
the fifth. Single runs are therefore not comparable, and any number quoted from
one is noise wearing a decimal point.

The aggregate is the artifact a human should read. It is deliberately shaped so
a single number from a single run is hard to quote by accident: every metric
comes with its spread across seeds, and the per-seed table sits beside it.

Two shapes of seed have to be handled and never conflated:

- a run that **finished with losses** — `result.json` exists, some nodes were
  walked over as identity fallbacks, and those nodes are recorded in
  `node_failures`;
- a run that was **abandoned** — `--max-failed-nodes` was exhausted, the run
  raised `TooManyNodeFailuresError`, and no `result.json` was written at all.

A fallback node is never counted as a completion. A run that scores seven nodes
when two of them are fallbacks is exactly the false number this harness exists
to avoid.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from cognate_reconstruction.agent.trajectory import (
    AgentTrajectory,
    TrajectoryDatasetBuilder,
)
from cognate_reconstruction.inspect_run import directionality_evidence
from cognate_reconstruction.schemas.historical import HistoricalTargetEvaluation
from cognate_reconstruction.schemas.metrics import MetricDistribution


@dataclass(frozen=True)
class SeedOutcome:
    """One repetition, whether or not it produced a result."""

    seed: int
    run_id: str
    run_dir: str
    exit_code: int
    result_written: bool
    nodes_attempted: int
    nodes_committed: int
    fallback_nodes: tuple[str, ...]
    node_failures: tuple[dict, ...]
    tool_calls: int
    failed_tool_calls: int
    protocol_failures: int
    error_codes: dict[str, int]
    committed_rules: int
    contrast_reducing_rules: tuple[int, ...]
    held_out_convergence_rates: tuple[float, ...]
    root_node_id: str | None = None
    directionality_claims_without_outgroup: tuple[str, ...] = field(default=())
    """Nodes that committed a direction claim where polarize returned no out-group.

    Structural, never a reading of the rationale's prose: `polarize` tags every
    node it reports with a `relation`, and a call that returned none tagged
    `outgroup` is a fact about the tool result. At most one node per run — the
    root — has this property by construction, since nothing lies outside it, so
    what a sweep makes visible is a seed where it happens *elsewhere*. See
    `direction_claims_below_the_root`.
    """
    directionality_claims_without_polarize: tuple[str, ...] = field(default=())
    target_evaluations: tuple[HistoricalTargetEvaluation, ...] = field(default=())
    stderr_tail: str = ""

    @property
    def direction_claims_below_the_root(self) -> tuple[str, ...]:
        """Flagged nodes that are *not* the root, which is the interesting set.

        The root has no out-group by construction — nothing lies outside it — so
        a claim of out-group support there is inevitable rather than
        informative. Reporting the two together would train a reader to ignore
        the line.

        A run that wrote no `result.json` has no known root, and every flagged
        node in it is genuinely below the root: it never got there.
        """
        return tuple(
            node_id
            for node_id in self.directionality_claims_without_outgroup
            if node_id != self.root_node_id
        )

    @property
    def abandoned(self) -> bool:
        """No `result.json`: the run gave up rather than finishing with losses."""
        return not self.result_written

    def as_dict(self) -> dict:
        return {
            "seed": self.seed,
            "run_id": self.run_id,
            "run_dir": self.run_dir,
            "exit_code": self.exit_code,
            "result_written": self.result_written,
            "abandoned": self.abandoned,
            "nodes_attempted": self.nodes_attempted,
            "nodes_committed": self.nodes_committed,
            "fallback_nodes": list(self.fallback_nodes),
            "node_failures": [dict(failure) for failure in self.node_failures],
            "tool_calls": self.tool_calls,
            "failed_tool_calls": self.failed_tool_calls,
            "protocol_failures": self.protocol_failures,
            "error_codes": dict(sorted(self.error_codes.items())),
            "committed_rules": self.committed_rules,
            "contrast_reducing_rules": list(self.contrast_reducing_rules),
            "held_out_convergence_rates": list(self.held_out_convergence_rates),
            "root_node_id": self.root_node_id,
            "directionality_claims_without_outgroup": list(
                self.directionality_claims_without_outgroup
            ),
            "directionality_claims_without_outgroup_below_the_root": list(
                self.direction_claims_below_the_root
            ),
            "directionality_claims_without_polarize": list(
                self.directionality_claims_without_polarize
            ),
            "target_evaluations": [
                {
                    "node_id": evaluation.node_id,
                    "failure_fallback": evaluation.failure_fallback,
                    "gold_evidence_kind": (
                        evaluation.gold_evidence_kind.value
                        if evaluation.gold_evidence_kind is not None
                        else None
                    ),
                    "evaluated_concepts": evaluation.evaluated_concepts,
                    "top_exact_rate": evaluation.top_exact_rate,
                    "beam_exact_rate": evaluation.beam_exact_rate,
                    "mean_top_normalized_edit_distance": _graded(
                        evaluation, "top_normalized_edit_distance"
                    ),
                    "mean_beam_best_normalized_edit_distance": _graded(
                        evaluation, "beam_best_normalized_edit_distance"
                    ),
                    "mean_top_bcubed_f1": _graded(evaluation, "top_bcubed_f1"),
                }
                for evaluation in self.target_evaluations
            ],
            "stderr_tail": self.stderr_tail,
        }


def _graded(evaluation: HistoricalTargetEvaluation, field_name: str):
    graded = evaluation.graded
    if graded is None:
        return None
    distribution = getattr(graded, field_name)
    return distribution.mean if distribution is not None else None


def _distribution(values: Sequence[float]) -> dict | None:
    summary = MetricDistribution.of(values)
    return summary.model_dump(mode="json") if summary is not None else None


def read_seed(
    seed: int,
    run_id: str,
    run_dir: Path,
    exit_code: int,
    stderr_tail: str = "",
) -> SeedOutcome:
    """Read one repetition's artifacts, tolerating a run that wrote none."""
    result_path = run_dir / "result.json"
    trajectories_path = run_dir / "trajectories.jsonl"
    trajectories: list[AgentTrajectory] = []
    if trajectories_path.exists():
        trajectories = list(
            TrajectoryDatasetBuilder.read_jsonl(trajectories_path)
        )
    result = None
    if result_path.exists():
        result = json.loads(result_path.read_text(encoding="utf-8"))
    node_failures = tuple(result.get("node_failures", ())) if result else ()
    fallback_nodes = tuple(
        str(failure["node_id"]) for failure in node_failures
    )
    evaluations = tuple(
        HistoricalTargetEvaluation.model_validate_json(json.dumps(raw))
        for raw in (result.get("historical_target_evaluations", ()) if result else ())
    )
    codes: Counter[str] = Counter()
    for trajectory in trajectories:
        codes.update(trajectory.metrics.tool_failures_by_code)
    completed = [item for item in trajectories if item.completed]
    steps = [
        item.reconstruction_step
        for item in completed
        if item.reconstruction_step is not None
    ]
    root_node_id = None
    if result is not None:
        root_node_id = (result.get("snapshot") or {}).get("root_node_id")
    return SeedOutcome(
        seed=seed,
        run_id=run_id,
        run_dir=str(run_dir),
        exit_code=exit_code,
        result_written=result is not None,
        root_node_id=root_node_id,
        nodes_attempted=len(trajectories),
        # Completion means a session committed. A fallback node has a beam and
        # is not a reconstruction, so it is never counted here.
        nodes_committed=len(completed),
        fallback_nodes=fallback_nodes,
        node_failures=node_failures,
        tool_calls=sum(item.metrics.tool_call_count for item in trajectories),
        failed_tool_calls=sum(
            item.metrics.failed_tool_call_count for item in trajectories
        ),
        protocol_failures=sum(
            item.metrics.protocol_failures for item in trajectories
        ),
        error_codes=dict(codes),
        committed_rules=sum(
            item.metrics.committed_rule_count for item in completed
        ),
        contrast_reducing_rules=tuple(
            step.diagnostics.contrast_reducing_rule_count
            for step in steps
            if step.diagnostics.contrast_reducing_rule_count is not None
        ),
        held_out_convergence_rates=tuple(
            item.metrics.held_out_convergence_rate
            for item in completed
            if item.metrics.held_out_convergence_rate is not None
        ),
        directionality_claims_without_outgroup=tuple(
            item.node_id
            for item in trajectories
            for evidence in (directionality_evidence(item),)
            if evidence.rules_with_rationale
            and evidence.polarize_calls
            and not evidence.calls_returning_outgroup
        ),
        directionality_claims_without_polarize=tuple(
            item.node_id
            for item in trajectories
            for evidence in (directionality_evidence(item),)
            if evidence.rules_with_rationale and not evidence.polarize_calls
        ),
        target_evaluations=evaluations,
        stderr_tail=stderr_tail,
    )


def aggregate(
    seeds: Sequence[SeedOutcome],
    *,
    benchmark: str,
    model: str,
    oracle: dict | None = None,
) -> dict:
    """Fold the seeds into one object, always with spread beside every mean."""
    scored = [
        evaluation
        for seed in seeds
        for evaluation in seed.target_evaluations
        # A fallback node's beam is the harness's identity commit, so scoring
        # it measures the fallback. Excluded here and counted separately.
        if not evaluation.failure_fallback
    ]
    fallback_scored = [
        evaluation
        for seed in seeds
        for evaluation in seed.target_evaluations
        if evaluation.failure_fallback
    ]
    by_node: dict[str, list[HistoricalTargetEvaluation]] = {}
    for evaluation in scored:
        by_node.setdefault(evaluation.node_id, []).append(evaluation)
    failure_taxonomy: Counter[str] = Counter()
    for seed in seeds:
        for failure in seed.node_failures:
            failure_taxonomy[str(failure.get("error_type", "unknown"))] += 1
        if seed.abandoned:
            # A run that exhausted --max-failed-nodes wrote no result.json, so
            # its losses are not in node_failures at all. Counting it here is
            # the only way the taxonomy adds up.
            failure_taxonomy["run-abandoned-no-result"] += 1
    error_codes: Counter[str] = Counter()
    for seed in seeds:
        error_codes.update(seed.error_codes)
    return {
        "benchmark": benchmark,
        "model": model,
        "seeds": len(seeds),
        "seeds_with_result": sum(seed.result_written for seed in seeds),
        "seeds_abandoned": sum(seed.abandoned for seed in seeds),
        "nodes_attempted": _distribution(
            [seed.nodes_attempted for seed in seeds]
        ),
        "nodes_committed": _distribution(
            [seed.nodes_committed for seed in seeds]
        ),
        "fallback_nodes_per_seed": _distribution(
            [len(seed.fallback_nodes) for seed in seeds]
        ),
        "failure_taxonomy": dict(sorted(failure_taxonomy.items())),
        "error_codes": dict(sorted(error_codes.items())),
        "tool_calls": _distribution([seed.tool_calls for seed in seeds]),
        "protocol_failures": _distribution(
            [seed.protocol_failures for seed in seeds]
        ),
        "committed_rules": _distribution(
            [seed.committed_rules for seed in seeds]
        ),
        # How a node reached its coverage, not only how much it reached. A seed
        # that scored well by discarding distinctions is visible across seeds
        # rather than only inside one report.
        "contrast_reducing_rules_per_node": _distribution(
            [
                float(count)
                for seed in seeds
                for count in seed.contrast_reducing_rules
            ]
        ),
        "held_out_convergence_rate_per_node": _distribution(
            [
                rate
                for seed in seeds
                for rate in seed.held_out_convergence_rates
            ]
        ),
        # Directionality, reported and never scored. The harness cannot grade
        # what a rationale says; it can say whether the evidence behind the
        # claim was retrieved and what the tool returned.
        "directionality_claims_without_outgroup": sorted(
            node_id
            for seed in seeds
            for node_id in seed.directionality_claims_without_outgroup
        ),
        "directionality_claims_without_outgroup_below_the_root": sorted(
            node_id
            for seed in seeds
            for node_id in seed.direction_claims_below_the_root
        ),
        "directionality_claims_without_polarize": sorted(
            node_id
            for seed in seeds
            for node_id in seed.directionality_claims_without_polarize
        ),
        "gold_targets": {
            "scored_evaluations": len(scored),
            "excluded_fallback_evaluations": len(fallback_scored),
            "top_exact_rate": _distribution(
                [evaluation.top_exact_rate for evaluation in scored]
            ),
            "beam_exact_rate": _distribution(
                [evaluation.beam_exact_rate for evaluation in scored]
            ),
            "mean_top_normalized_edit_distance": _distribution(
                [
                    value
                    for evaluation in scored
                    if (
                        value := _graded(
                            evaluation, "top_normalized_edit_distance"
                        )
                    )
                    is not None
                ]
            ),
            "mean_beam_best_normalized_edit_distance": _distribution(
                [
                    value
                    for evaluation in scored
                    if (
                        value := _graded(
                            evaluation, "beam_best_normalized_edit_distance"
                        )
                    )
                    is not None
                ]
            ),
            "mean_top_bcubed_f1": _distribution(
                [
                    value
                    for evaluation in scored
                    if (value := _graded(evaluation, "top_bcubed_f1"))
                    is not None
                ]
            ),
            "by_node": {
                node_id: {
                    "seeds": len(evaluations),
                    "top_exact_rate": _distribution(
                        [item.top_exact_rate for item in evaluations]
                    ),
                    "beam_exact_rate": _distribution(
                        [item.beam_exact_rate for item in evaluations]
                    ),
                    "mean_top_normalized_edit_distance": _distribution(
                        [
                            value
                            for item in evaluations
                            if (
                                value := _graded(
                                    item, "top_normalized_edit_distance"
                                )
                            )
                            is not None
                        ]
                    ),
                }
                for node_id, evaluations in sorted(by_node.items())
            },
        },
        # The architecture's bound, measured by tools/oracle_ceiling.py on the
        # same payload. An oracle number bounds the architecture; a live number
        # measures a model, and quoting one for the other is the mistake this
        # field exists to make impossible.
        "oracle_ceiling": oracle,
        "seed_outcomes": [seed.as_dict() for seed in seeds],
        "note": (
            "Every rate here is a distribution across seeds, not a single "
            "run's number. Fallback nodes are excluded from nodes_committed "
            "and from the gold-target scores, and counted in "
            "failure_taxonomy."
        ),
    }


def oracle_ceiling(payload_path: Path, beam_width: int) -> dict | None:
    """Ask `tools/oracle_ceiling.py` for the same benchmark's ceiling.

    Run as a subprocess rather than imported: `tools/` is deliberately not part
    of the package, and the script's `--json` mode already carries the
    `measuring:` path that says which checkout produced the number.
    """
    script = Path(__file__).resolve().parents[2] / "tools" / "oracle_ceiling.py"
    if not script.exists():
        return None
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            str(payload_path),
            "--beam-width",
            str(beam_width),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return {"error": completed.stderr.strip()[-500:]}
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"error": "oracle_ceiling.py did not emit JSON"}


def render_text(summary: dict) -> str:
    """The readable form, which is the one a human is meant to quote."""
    lines = [
        "=" * 78,
        f"BENCHMARK SWEEP  {summary['benchmark']}  model {summary['model']}",
        "=" * 78,
        f"  seeds              {summary['seeds']} "
        f"({summary['seeds_with_result']} produced a result, "
        f"{summary['seeds_abandoned']} abandoned)",
    ]

    def line(label: str, key: str, source: dict | None = None) -> None:
        holder = summary if source is None else source
        distribution = holder.get(key)
        if distribution is None:
            lines.append(f"  {label:<18} not recorded")
            return
        lines.append(
            f"  {label:<18} mean {distribution['mean']:.3f} "
            f"(sd {distribution['standard_deviation']:.3f}, "
            f"range {distribution['minimum']:.3f}-{distribution['maximum']:.3f}, "
            f"n={distribution['count']})"
        )

    line("nodes attempted", "nodes_attempted")
    line("nodes committed", "nodes_committed")
    line("fallback nodes", "fallback_nodes_per_seed")
    line("tool calls", "tool_calls")
    line("protocol failures", "protocol_failures")
    line("committed rules", "committed_rules")
    line("contrast loss/node", "contrast_reducing_rules_per_node")
    line("held-out converge", "held_out_convergence_rate_per_node")
    lines.append(
        "  failure taxonomy   "
        + (
            ", ".join(
                f"{name} x{count}"
                for name, count in summary["failure_taxonomy"].items()
            )
            or "none"
        )
    )
    lines.append(
        "  direction claims   "
        + (
            f"{len(summary['directionality_claims_without_outgroup'])} made "
            "where polarize returned no out-group ("
            + ", ".join(summary["directionality_claims_without_outgroup"])
            + "), of which "
            f"{len(summary['directionality_claims_without_outgroup_below_the_root'])} "
            "below the root, where it is not inevitable ("
            + (
                ", ".join(
                    summary[
                        "directionality_claims_without_outgroup_below_the_root"
                    ]
                )
                or "none"
            )
            + "); "
            f"{len(summary['directionality_claims_without_polarize'])} made "
            "with no polarize call at all"
        )
    )
    lines.append(
        "  error codes        "
        + (
            ", ".join(
                f"{name} x{count}"
                for name, count in summary["error_codes"].items()
            )
            or "none"
        )
    )
    gold = summary["gold_targets"]
    lines.extend(
        [
            "",
            "-" * 78,
            "GOLD TARGETS  (proto-forms withheld from the model)",
            "-" * 78,
            f"  scored {gold['scored_evaluations']} node evaluation(s); "
            f"{gold['excluded_fallback_evaluations']} excluded as identity "
            "fallbacks, which are not reconstructions",
        ]
    )
    line("top exact", "top_exact_rate", gold)
    line("beam exact", "beam_exact_rate", gold)
    line("top NED", "mean_top_normalized_edit_distance", gold)
    line("beam best NED", "mean_beam_best_normalized_edit_distance", gold)
    line("B-Cubed F1", "mean_top_bcubed_f1", gold)
    lines.append("  (NED: lower is better. B-Cubed F1: higher is better.)")
    for node_id, per_node in gold["by_node"].items():
        lines.append(f"  node {node_id}")
        line("  top exact", "top_exact_rate", per_node)
        line("  beam exact", "beam_exact_rate", per_node)
        line("  top NED", "mean_top_normalized_edit_distance", per_node)
    oracle = summary.get("oracle_ceiling")
    if oracle and "error" not in oracle:
        lines.extend(
            [
                "",
                "-" * 78,
                "ORACLE CEILING  (perfect rules on every branch: bounds the "
                "architecture, not the model)",
                "-" * 78,
                f"  measuring          {oracle.get('measuring')}",
                f"  top exact          {oracle['top_exact']}/"
                f"{oracle['evaluated_concepts']} "
                f"({oracle['top_exact_rate']:.3f})",
                f"  beam exact         {oracle['beam_exact']}/"
                f"{oracle['evaluated_concepts']} "
                f"({oracle['beam_exact_rate']:.3f})",
                f"  top NED            "
                f"{oracle['mean_top_normalized_edit_distance']:.3f}",
            ]
        )
    lines.extend(["", "-" * 78, "PER-SEED", "-" * 78])
    for seed in summary["seed_outcomes"]:
        status = "abandoned (no result.json)" if seed["abandoned"] else "finished"
        lines.append(
            f"  seed {seed['seed']:<3} {status:<26} "
            f"{seed['nodes_committed']}/{seed['nodes_attempted']} committed, "
            f"{len(seed['fallback_nodes'])} fallback"
            + (
                f" ({', '.join(seed['fallback_nodes'])})"
                if seed["fallback_nodes"]
                else ""
            )
        )
        lines.append(f"           {seed['run_dir']}")
    return "\n".join(lines) + "\n"
