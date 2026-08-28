"""An interactive view of *how the agent worked* at each node of one run.

`inspect_run.py` answers "what did this run conclude": what each node committed,
what the deterministic step did with it, and which condition the workflow filter
rejected. It never shows the session that produced any of that. This module
answers the other question — turn by turn, what did the model look at, what did
the tools say back, where was it rejected, and what did it finally commit.

Two things are new here. The **timeline** is derived from
`AgentTrajectory.messages`, pairing each assistant tool call with the tool
message that answered it. The **tree** is derived from the traversal steps, so a
reader can see the bottom-up walk and — because a node is reconstructed from its
direct children — which nodes were built on top of an identity fallback.

Everything else is delegated to `inspect_run.build_report`, so this view and the
text report cannot disagree about a rule, a diagnostic, a form, or a gate
reason. This module states no fact of its own about linguistics.

Nothing here scores, filters, or gates. The phase labels grouping the tool calls
are a *display* grouping of tool names with no linguistic content, and a tool
this module does not know renders as "other" rather than being guessed into a
phase.

Live mode serves the same page against a run directory still being written.
`JsonlEventSink` appends and flushes one line per event and `JsonlTrajectorySink`
appends one record per finished node, so a finished node renders from its
trajectory at full fidelity and a node still in flight renders from its events.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cognate_reconstruction.agent.error_codes import classify_tool_error_code
from cognate_reconstruction.inspect_run import (
    DEFAULT_FORM_LIMIT,
    EVENTS_FILE,
    NodeReport,
    RunArtifacts,
    build_report,
    load_run,
)

DEFAULT_OUTPUT_NAME = "trajectory_view.html"
DEFAULT_PORT = 8765
DEFAULT_PAYLOAD_CHARS = 20_000
"""Characters of one tool argument or result embedded before truncation.

The raw payload is there so a reader can check a digest against what the model
actually saw. A handful of `get_alignments` results would otherwise dominate the
page, and the full text is always in `trajectories.jsonl`.
"""

TOOL_PHASES: Mapping[str, str] = {
    # Orienting: what is here, and what corresponds to what.
    "list_available_nodes": "survey",
    "list_concepts": "survey",
    "search_forms": "survey",
    "summarize_correspondences": "survey",
    # Looking at particular evidence.
    "get_alignments": "inspect",
    "get_node_reconstruction": "inspect",
    "polarize": "inspect",
    "realign": "inspect",
    "segment_morphemes": "inspect",
    # Putting a hypothesis in front of the deterministic checker.
    "test_proto_assembly": "test",
    "test_rule_cascade": "test",
    "test_sound_law": "test",
    # Ending the session.
    "commit_reconstruction": "commit",
}
"""Which stage of the session a tool call belongs to, for display only.

This groups tool *names*. It encodes no claim about sound change, and nothing
downstream reads it. A tool absent from this map is shown as "other", which is
the honest rendering of "this view was written before that tool existed".
"""

PHASE_ORDER = ("survey", "inspect", "test", "commit", "other")

RESULT_DIGEST_FIELDS: Mapping[str, tuple[tuple[str, str], ...]] = {
    "summarize_correspondences": (
        ("sets matched", "matched_set_count"),
        ("of", "total_set_count"),
        ("below min support", "suppressed_below_min_support"),
    ),
    "polarize": (
        ("columns", "columns_matched"),
        ("concepts", "matched_concept_count"),
    ),
    "get_alignments": (("alignments", "alignment_map.alignments"),),
    "search_forms": (("hits", "hits"),),
    "list_concepts": (("concepts", "concepts"),),
    "list_available_nodes": (("nodes", "nodes"),),
    "get_node_reconstruction": (("forms", "lexicon.forms"),),
    "segment_morphemes": (("forms", "forms"),),
    "realign": (("alignments", "alignment_map.alignments"),),
    "test_sound_law": (
        ("held-out concepts", "held_out.concept_count"),
        ("convergence", "held_out.convergence.child_convergence_rate"),
    ),
    "test_rule_cascade": (
        ("converged", "convergence.converged_concepts"),
        ("of", "convergence.concepts_evaluated"),
        ("rate", "convergence.child_convergence_rate"),
    ),
    "test_proto_assembly": (
        ("concepts assembled", "assembled_concept_count"),
        ("unaccounted columns", "unaccounted_column_rate"),
        ("cross-branch", "cross_branch_assembly_rate"),
    ),
    "commit_reconstruction": (
        ("status", "status"),
        ("convergence", "convergence.child_convergence_rate"),
    ),
}
"""Fields lifted out of a successful result into the one-line digest.

Retrieval, not interpretation: each entry names a path the tool itself wrote. A
tool with no entry falls back to its top-level scalars, and every call keeps its
full payload one click away.
"""


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _resolve(payload: Any, path: str) -> Any:
    """Follow a dotted path, returning None rather than raising on a miss."""
    current = payload
    for key in path.split("."):
        if not isinstance(current, Mapping) or key not in current:
            return None
        current = current[key]
    return current


def _render_scalar(value: Any) -> str | None:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, str):
        return value if len(value) <= 60 else value[:57] + "…"
    if isinstance(value, list):
        return str(len(value))
    return None


def _truncate_json(payload: Any, limit: int) -> str:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return text[:limit] + f"\n… {omitted} more character(s); see trajectories.jsonl"


def _concept_digest(values: Sequence[str] | None) -> str | None:
    if not values:
        return None
    head = ", ".join(str(value) for value in values[:3])
    return head if len(values) <= 3 else f"{head} (+{len(values) - 3})"


def _short_name(node_id: str) -> str:
    """The part of a node ID a reader scans for, keeping the whole as a title."""
    return node_id.rsplit(":", 1)[-1]


# ---------------------------------------------------------------------------
# the timeline
# ---------------------------------------------------------------------------


def digest_arguments(name: str, arguments: Mapping[str, Any]) -> str:
    """One line naming what this call asked for, in the tool's own terms."""
    parts: list[str] = []
    if name == "polarize":
        correspondence = arguments.get("correspondence")
        if isinstance(correspondence, list):
            parts.append(" ~ ".join(str(token) for token in correspondence))
    elif name in {"test_sound_law"}:
        dsl = arguments.get("dsl")
        if isinstance(dsl, str):
            parts.append(dsl)
    elif name in {"test_rule_cascade"}:
        rules = arguments.get("rules") or []
        laws = [rule.get("dsl") for rule in rules if isinstance(rule, Mapping)]
        laws = [law for law in laws if isinstance(law, str)]
        if laws:
            head = "; ".join(laws[:2])
            parts.append(head if len(laws) <= 2 else f"{head}; +{len(laws) - 2} more")
    elif name == "test_proto_assembly":
        commitments = arguments.get("commitments") or []
        parts.append(f"{len(commitments)} commitment(s)")
    elif name == "commit_reconstruction":
        rules = arguments.get("rules")
        commitments = arguments.get("commitments")
        if isinstance(commitments, list):
            parts.append(f"{len(commitments)} commitment(s)")
        elif isinstance(rules, list):
            parts.append(f"{len(rules)} rule(s)")
        anomalies = arguments.get("anomalies")
        if isinstance(anomalies, list) and anomalies:
            parts.append(f"{len(anomalies)} anomaly/-ies")

    concepts = _concept_digest(arguments.get("concept_ids"))
    if concepts:
        parts.append(f"concepts {concepts}")

    for key in ("node_ids", "child_ids", "source_child_ids", "child_node_ids"):
        values = arguments.get(key)
        if isinstance(values, list) and values:
            names = ", ".join(_short_name(str(value)) for value in values[:3])
            suffix = "" if len(values) <= 3 else f" (+{len(values) - 3})"
            parts.append(f"{names}{suffix}")
            break
    return " · ".join(parts)


def digest_result(name: str, result: Any) -> str:
    """One line naming what came back, lifted from fields the tool wrote."""
    if not isinstance(result, Mapping):
        return ""
    parts: list[str] = []
    for label, path in RESULT_DIGEST_FIELDS.get(name, ()):
        rendered = _render_scalar(_resolve(result, path))
        if rendered is not None:
            parts.append(f"{label} {rendered}")
    if parts:
        return " · ".join(parts)
    for key, value in list(result.items())[:6]:
        rendered = _render_scalar(value)
        if rendered is not None and not isinstance(value, list):
            parts.append(f"{key} {rendered}")
    return " · ".join(parts[:4])


def _tool_results_by_call_id(messages: Sequence[Any]) -> dict[str, Any]:
    answers: dict[str, Any] = {}
    for message in messages:
        if message.role != "tool" or not message.tool_call_id:
            continue
        try:
            answers[message.tool_call_id] = json.loads(message.content or "null")
        except json.JSONDecodeError:
            answers[message.tool_call_id] = {"ok": False, "error": {
                "error_type": "UnreadableToolMessage",
                "message": "the recorded tool message is not JSON",
                "code": None,
            }}
    return answers


def build_timeline(
    trajectory: Any,
    *,
    payload_chars: int = DEFAULT_PAYLOAD_CHARS,
) -> list[dict[str, Any]]:
    """Turn-by-turn record of one session, paired call to answer.

    A turn is one assistant message: whatever the model said, plus the calls it
    made and what each call got back. Rejections stay in place rather than being
    collected at the end — a commit refused twice and accepted on the third try
    is the shape a reader is looking for.
    """
    answers = _tool_results_by_call_id(trajectory.messages)
    turns: list[dict[str, Any]] = []
    index = 0
    for message in trajectory.messages:
        if message.role != "assistant":
            continue
        index += 1
        calls: list[dict[str, Any]] = []
        for call in message.tool_calls or ():
            arguments = dict(call.arguments or {})
            payload = answers.get(call.call_id)
            ok = bool(isinstance(payload, Mapping) and payload.get("ok"))
            entry: dict[str, Any] = {
                "call_id": call.call_id,
                "name": call.name,
                "phase": TOOL_PHASES.get(call.name, "other"),
                "ok": ok,
                "arguments_digest": digest_arguments(call.name, arguments),
                "arguments_json": _truncate_json(arguments, payload_chars),
                "answered": payload is not None,
            }
            if payload is None:
                entry["result_digest"] = "no recorded answer"
            elif ok:
                entry["result_digest"] = digest_result(
                    call.name, payload.get("result")
                )
                entry["result_json"] = _truncate_json(
                    payload.get("result"), payload_chars
                )
            else:
                error = (payload or {}).get("error") or {}
                code = error.get("code")
                entry["error_code"] = code or "unclassified"
                entry["error_category"] = classify_tool_error_code(code).value
                entry["error_type"] = error.get("error_type") or "ToolError"
                entry["error_message"] = error.get("message") or ""
                entry["remediation"] = error.get("remediation") or ""
                entry["result_digest"] = entry["error_code"]
                entry["result_json"] = _truncate_json(payload, payload_chars)
            calls.append(entry)
        text = (message.content or "").strip()
        if not text and not calls:
            continue
        turns.append({"index": index, "text": text, "calls": calls})
    return turns


def _phase_ribbon(turns: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The session's shape as an ordered run of phases, one cell per call."""
    ribbon: list[dict[str, Any]] = []
    for turn in turns:
        for call in turn["calls"]:
            ribbon.append(
                {
                    "phase": call["phase"],
                    "ok": call["ok"],
                    "name": call["name"],
                    "turn": turn["index"],
                }
            )
    return ribbon


# ---------------------------------------------------------------------------
# the tree the traversal walked
# ---------------------------------------------------------------------------


def traversal_tree(artifacts: RunArtifacts) -> dict[str, Any]:
    """Full adjacency and visiting order, leaves included.

    `inspect_run.internal_node_children` deliberately keeps only internal nodes,
    because its cross-node observations are about reconstructions. A picture of
    the walk needs the leaves too: they are the evidence the model read.

    Sources are tried in the order a run writes them, so a directory holding
    only a partial event log still yields a tree.
    """
    children: dict[str, tuple[str, ...]] = {}
    order: list[str] = []

    def record(parent: str | None, kids: Sequence[str]) -> None:
        if not parent or parent in children:
            return
        children[parent] = tuple(str(kid) for kid in kids)
        order.append(parent)

    if artifacts.result is not None:
        for step in (artifacts.result.get("snapshot") or {}).get("steps", []):
            record(step.get("parent_node_id"), step.get("child_node_ids") or ())
    for trajectory in artifacts.trajectories:
        step = trajectory.reconstruction_step
        if step is not None:
            record(step.parent_node_id, step.child_node_ids)
    if artifacts.result is not None:
        for failure in artifacts.result.get("node_failures", []):
            record(failure.get("node_id"), failure.get("child_node_ids") or ())
    for event in artifacts.events:
        if event.get("kind") == "node_start":
            record(
                event.get("node_id"),
                (event.get("details") or {}).get("active_child_ids") or (),
            )

    internal = set(children)
    has_parent = {kid for kids in children.values() for kid in kids}
    roots = sorted(node for node in internal if node not in has_parent)
    return {"children": children, "order": order, "internal": internal, "roots": roots}


def _fallback_node_ids(artifacts: RunArtifacts) -> set[str]:
    """Nodes the traversal walked over on an identity fallback.

    Read from `result.json:node_failures` when it exists, and from the event log
    otherwise, so a run still in flight reports the fallback it already took.
    """
    fallbacks: set[str] = set()
    if artifacts.result is not None:
        for failure in artifacts.result.get("node_failures", []):
            node_id = failure.get("node_id")
            if node_id:
                fallbacks.add(str(node_id))
    for event in artifacts.events:
        if event.get("kind") in {"node_fallback", "node_failed"}:
            fallbacks.add(str(event.get("node_id")))
    return fallbacks


def _built_on_fallback(
    tree: Mapping[str, Any],
    fallbacks: set[str],
) -> dict[str, tuple[str, ...]]:
    """For each node, which failed nodes sit anywhere beneath it.

    A mechanical fact, and the one the tree is worth drawing for: a node is
    reconstructed from its direct children, so a session below that never
    committed leaves an identity fallback in the evidence every node above it
    reads. It carries no verdict — the ancestor's own session may be impeccable.
    """
    children: Mapping[str, tuple[str, ...]] = tree["children"]
    beneath: dict[str, tuple[str, ...]] = {}

    def walk(node: str, seen: frozenset[str]) -> tuple[str, ...]:
        if node in beneath:
            return beneath[node]
        if node in seen:
            return ()
        found: list[str] = []
        for child in children.get(node, ()):
            if child in fallbacks:
                found.append(child)
            found.extend(walk(child, seen | {node}))
        result = tuple(dict.fromkeys(found))
        beneath[node] = result
        return result

    for node in children:
        walk(node, frozenset())
    return beneath


# ---------------------------------------------------------------------------
# per-node state
# ---------------------------------------------------------------------------


def _events_by_node(artifacts: RunArtifacts) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for event in artifacts.events:
        node_id = event.get("node_id")
        if node_id:
            grouped.setdefault(str(node_id), []).append(event)
    return grouped


def _node_from_trajectory(
    trajectory: Any,
    report: NodeReport | None,
    *,
    payload_chars: int,
) -> dict[str, Any]:
    turns = build_timeline(trajectory, payload_chars=payload_chars)
    metrics = trajectory.metrics
    entry: dict[str, Any] = {
        "node_id": trajectory.node_id,
        "source": "trajectory",
        "status": "committed" if trajectory.completed else "failed",
        "failure": trajectory.failure,
        "model_id": trajectory.model_id,
        "schema_version": trajectory.schema_version,
        "high_quality": trajectory.high_quality,
        "quality_reasons": list(trajectory.high_quality_failure_reasons),
        "turns": turns,
        "ribbon": _phase_ribbon(turns),
        "counters": {
            "turns": metrics.turn_count,
            "tool calls": metrics.tool_call_count,
            "rejected": metrics.failed_tool_call_count,
            "protocol rejections": metrics.protocol_failures,
            "inspections": metrics.inspection_tool_calls,
            "sound-law tests": metrics.sound_law_tests,
            "cascade previews": metrics.cascade_tests,
            "assembly previews": metrics.assembly_tests,
            "committed": metrics.committed_rule_count,
            "anomalies": metrics.committed_anomaly_count,
            "duration (s)": round(metrics.duration_seconds, 1),
            "tokens in": metrics.input_tokens,
            "tokens cached": metrics.cached_input_tokens,
            "tokens out": metrics.output_tokens,
        },
        "flags": [],
    }
    if metrics.committed_without_inspection:
        entry["flags"].append("committed without inspecting evidence first")
    if metrics.identity_without_testing:
        entry["flags"].append("committed an identity reconstruction without testing")
    if metrics.truncated_response_count:
        entry["flags"].append(
            f"{metrics.truncated_response_count} truncated response(s); "
            f"{metrics.forced_tool_choice_count} forced tool choice(s)"
        )
    if metrics.compacted_tool_results:
        entry["flags"].append(
            f"{metrics.compacted_tool_results} superseded tool result(s) dropped "
            "from the live prompt"
        )
    if report is not None:
        entry["failure_fallback"] = report.failure_fallback
        entry["summary"] = report.summary
        entry["rules"] = [asdict(rule) for rule in report.rules]
        entry["anomalies"] = list(report.anomalies)
        entry["diagnostics"] = [list(row) for row in report.diagnostics]
        entry["forms"] = [list(row) for row in report.forms]
        entry["omitted_forms"] = report.omitted_forms
        entry["session"] = [list(row) for row in report.session]
    return entry


def _node_from_events(
    node_id: str,
    events: Sequence[Mapping[str, Any]],
    *,
    payload_chars: int,
) -> dict[str, Any]:
    """A node still in flight, rendered from the event log alone.

    Coarser than a trajectory — the event stream carries each call's arguments
    and result but not the model's prose — and labelled as such, so a reader is
    never shown an in-flight session as though it were a finished record.
    """
    turns: list[dict[str, Any]] = []
    pending: dict[str, dict[str, Any]] = {}
    counters = {"turns": 0, "tool calls": 0, "rejected": 0}
    status = "running"
    failure = None
    for event in events:
        kind = event.get("kind")
        details = event.get("details") or {}
        if kind == "model_turn":
            counters["turns"] += 1
        elif kind == "tool_call":
            name = str(event.get("message", "")).removeprefix("calling tool ")
            arguments = details.get("arguments") or {}
            entry = {
                "call_id": details.get("call_id") or f"call-{counters['tool calls']}",
                "name": name,
                "phase": TOOL_PHASES.get(name, "other"),
                "ok": False,
                "answered": False,
                "arguments_digest": digest_arguments(name, arguments),
                "arguments_json": _truncate_json(arguments, payload_chars),
                "result_digest": "waiting",
            }
            counters["tool calls"] += 1
            pending[str(entry["call_id"])] = entry
            turns.append(
                {"index": counters["turns"], "text": "", "calls": [entry]}
            )
        elif kind == "tool_result":
            entry = pending.get(str(details.get("call_id")))
            if entry is None:
                continue
            payload = details.get("result") or {}
            entry["answered"] = True
            if payload.get("ok"):
                entry["ok"] = True
                entry["result_digest"] = digest_result(
                    entry["name"], payload.get("result")
                )
                entry["result_json"] = _truncate_json(
                    payload.get("result"), payload_chars
                )
            else:
                code = details.get("error_code")
                error = payload.get("error") or {}
                entry["error_code"] = code or error.get("code") or "unclassified"
                entry["error_category"] = classify_tool_error_code(
                    code or error.get("code")
                ).value
                entry["error_type"] = error.get("error_type") or "ToolError"
                entry["error_message"] = error.get("message") or ""
                entry["remediation"] = error.get("remediation") or ""
                entry["result_digest"] = entry["error_code"]
                entry["result_json"] = _truncate_json(payload, payload_chars)
                counters["rejected"] += 1
        elif kind == "node_complete":
            status = "committed"
        elif kind == "node_failed":
            status = "failed"
            failure = details.get("error") or details.get("error_type")
    return {
        "node_id": node_id,
        "source": "events",
        "status": status,
        "failure": failure,
        "model_id": None,
        "high_quality": None,
        "quality_reasons": [],
        "turns": turns,
        "ribbon": _phase_ribbon(turns),
        "counters": counters,
        "flags": [],
        "note": (
            "still in flight — rendered from events.jsonl; the full record is "
            "written when the node finishes"
        ),
    }


# ---------------------------------------------------------------------------
# whole-run state
# ---------------------------------------------------------------------------


def _node_without_record(node_id: str, *, failed: bool) -> dict[str, Any]:
    """An internal node the walk visited that left no session behind.

    A resumed run reads earlier nodes from its checkpoint, and a run that died
    mid-walk never wrote records for the nodes above it. Neither is a leaf, and
    drawing one as a leaf would tell a reader that a reconstructed node was an
    input language.
    """
    return {
        "node_id": node_id,
        "source": "none",
        "status": "failed" if failed else "unrecorded",
        "failure": None,
        "model_id": None,
        "high_quality": None,
        "quality_reasons": [],
        "turns": [],
        "ribbon": [],
        "counters": {},
        "flags": [],
        "note": (
            "no session record in this directory — the traversal reached this "
            "node, but no trajectory and no events were written for it here"
        ),
    }


def build_state(
    artifacts: RunArtifacts,
    *,
    form_limit: int | None = DEFAULT_FORM_LIMIT,
    payload_chars: int = DEFAULT_PAYLOAD_CHARS,
) -> dict[str, Any]:
    """Everything the page draws, as one JSON-serializable object.

    The same builder feeds the standalone file and the live server, so the two
    cannot drift. Facts that `inspect_run` already states are taken from its
    report rather than recomputed.
    """
    report = build_report(artifacts, form_limit=form_limit)
    reports = {node.node_id: node for node in report.nodes}
    tree = traversal_tree(artifacts)
    fallbacks = _fallback_node_ids(artifacts)
    beneath = _built_on_fallback(tree, fallbacks)
    grouped_events = _events_by_node(artifacts)

    nodes: dict[str, dict[str, Any]] = {}
    for trajectory in artifacts.trajectories:
        nodes[trajectory.node_id] = _node_from_trajectory(
            trajectory,
            reports.get(trajectory.node_id),
            payload_chars=payload_chars,
        )
    for node_id, events in grouped_events.items():
        if node_id in nodes:
            continue
        nodes[node_id] = _node_from_events(
            node_id, events, payload_chars=payload_chars
        )

    for node_id in tree["internal"]:
        if node_id not in nodes:
            nodes[node_id] = _node_without_record(
                node_id, failed=node_id in fallbacks
            )

    ordering = {node_id: index for index, node_id in enumerate(tree["order"])}
    for node_id, entry in nodes.items():
        entry.setdefault("failure_fallback", node_id in fallbacks)
        entry["children"] = list(tree["children"].get(node_id, ()))
        entry["visit_order"] = ordering.get(node_id)
        entry["fallbacks_beneath"] = list(beneath.get(node_id, ()))

    active = [
        node_id for node_id, entry in nodes.items() if entry["status"] == "running"
    ]
    return {
        "run_dir": str(artifacts.run_dir),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "header": [list(row) for row in report.header],
        "family": [list(row) for row in report.family],
        "historical": list(report.historical),
        "observations": [asdict(item) for item in report.observations],
        "notes": list(report.notes),
        "fallback_nodes": list(report.fallback_nodes),
        "tree": {
            "children": {key: list(value) for key, value in tree["children"].items()},
            "roots": tree["roots"],
            "order": tree["order"],
            "internal": sorted(tree["internal"]),
        },
        "nodes": nodes,
        "active_nodes": sorted(active),
        "phase_order": list(PHASE_ORDER),
    }


def build_live_state(
    run_dir: str | Path,
    *,
    payload_chars: int = DEFAULT_PAYLOAD_CHARS,
) -> dict[str, Any]:
    """State for a directory that may hold nothing but a partial event log.

    `load_run` refuses a directory with neither a result nor a trajectory, which
    is exactly the first seconds of a live run. Rather than weaken that contract,
    this falls back to an event-only state until the first node finishes.
    """
    directory = Path(run_dir).expanduser()
    try:
        artifacts = load_run(directory)
    except ValueError:
        events_path = directory / EVENTS_FILE
        if not events_path.exists():
            return {
                "run_dir": str(directory),
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "header": [["waiting", f"no artifacts in {directory} yet"]],
                "family": [],
                "historical": [],
                "observations": [],
                "notes": [f"nothing written to {directory} yet"],
                "fallback_nodes": [],
                "tree": {"children": {}, "roots": [], "order": [], "internal": []},
                "nodes": {},
                "active_nodes": [],
                "phase_order": list(PHASE_ORDER),
            }
        artifacts = RunArtifacts(
            run_dir=directory,
            trajectories=(),
            result=None,
            events=_read_events_leniently(events_path),
            notes=("the run has not written a trajectory yet",),
        )
        return _events_only_state(artifacts, payload_chars=payload_chars)
    return build_state(artifacts, payload_chars=payload_chars)


def _read_events_leniently(path: Path) -> tuple[Mapping[str, Any], ...]:
    events: list[Mapping[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            events.append(record)
    return tuple(events)


def _events_only_state(
    artifacts: RunArtifacts,
    *,
    payload_chars: int,
) -> dict[str, Any]:
    tree = traversal_tree(artifacts)
    fallbacks = _fallback_node_ids(artifacts)
    beneath = _built_on_fallback(tree, fallbacks)
    ordering = {node_id: index for index, node_id in enumerate(tree["order"])}
    nodes = {
        node_id: _node_from_events(node_id, events, payload_chars=payload_chars)
        for node_id, events in _events_by_node(artifacts).items()
    }
    for node_id, entry in nodes.items():
        entry["failure_fallback"] = node_id in fallbacks
        entry["children"] = list(tree["children"].get(node_id, ()))
        entry["visit_order"] = ordering.get(node_id)
        entry["fallbacks_beneath"] = list(beneath.get(node_id, ()))
    models = sorted(
        {
            str((event.get("details") or {}).get("model_id"))
            for event in artifacts.events
            if (event.get("details") or {}).get("model_id")
        }
    )
    run_ids = sorted(
        {str(event["run_id"]) for event in artifacts.events if event.get("run_id")}
    )
    return {
        "run_dir": str(artifacts.run_dir),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "header": [
            ["run id", ", ".join(run_ids) or "unknown"],
            ["model", ", ".join(models) or "unknown"],
            ["artifacts", f"{len(artifacts.events)} event(s), no trajectory yet"],
        ],
        "family": [],
        "historical": [],
        "observations": [],
        "notes": list(artifacts.notes),
        "fallback_nodes": sorted(fallbacks),
        "tree": {
            "children": {key: list(value) for key, value in tree["children"].items()},
            "roots": tree["roots"],
            "order": tree["order"],
            "internal": sorted(tree["internal"]),
        },
        "nodes": nodes,
        "active_nodes": sorted(
            node_id for node_id, entry in nodes.items() if entry["status"] == "running"
        ),
        "phase_order": list(PHASE_ORDER),
    }


# ---------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------

_STYLE = """
:root {
  color-scheme: light dark;
  --bg: #fbfbfa; --panel: #ffffff; --ink: #1b1b1a; --muted: #5d5d58;
  --line: #dcdcd6; --accent: #7a4b12; --bad: #8a2f22; --good: #245c3a;
  --survey: #4a6b86; --inspect: #2f6f66; --test: #8a6114; --commit: #245c3a;
  --other: #6b6b64; --sel: rgba(122,75,18,.10);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14140f; --panel: #1c1c18; --ink: #eceae1; --muted: #a3a196;
    --line: #33332c; --accent: #e0b071; --bad: #e79284; --good: #86c8a1;
    --survey: #8fb4d0; --inspect: #6fc0b3; --test: #e0b071; --commit: #86c8a1;
    --other: #9a9a90; --sel: rgba(224,176,113,.14);
  }
}
* { box-sizing: border-box; }
html, body { height: 100%; }
body {
  margin: 0; background: var(--bg); color: var(--ink);
  font: 14px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
}
.mono, code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
#app { display: grid; grid-template-columns: 21rem 1fr; height: 100vh; }
#side {
  border-right: 1px solid var(--line); background: var(--panel);
  overflow: auto; padding: 1rem .9rem 3rem;
}
#main { overflow: auto; padding: 1.1rem 1.4rem 4rem; }
h1 { font-size: 1.05rem; margin: 0 0 .1rem; }
h2 { font-size: 1.25rem; margin: 0; }
h3 {
  font-size: .74rem; text-transform: uppercase; letter-spacing: .09em;
  color: var(--muted); margin: 1.5rem 0 .5rem;
}
.sub { color: var(--muted); font-size: .8rem; word-break: break-all; }
.badge {
  display: inline-block; padding: .08rem .5rem; border-radius: 999px;
  font-size: .72rem; border: 1px solid var(--line); color: var(--muted);
  white-space: nowrap; vertical-align: middle;
}
.badge.good { color: var(--good); border-color: currentColor; }
.badge.bad  { color: var(--bad);  border-color: currentColor; }
.badge.warn { color: var(--accent); border-color: currentColor; }
.badge.live { color: var(--bad); border-color: currentColor; }
.badge.live::before {
  content: ""; display: inline-block; width: .45rem; height: .45rem;
  border-radius: 50%; background: currentColor; margin-right: .35rem;
  animation: pulse 1.4s ease-in-out infinite;
}
@keyframes pulse { 50% { opacity: .25; } }

/* the tree */
ul.tree, ul.tree ul { list-style: none; margin: 0; padding: 0; }
ul.tree ul { margin-left: .55rem; padding-left: .7rem; border-left: 1px solid var(--line); }
ul.tree li { margin: .12rem 0; }
.tnode {
  display: flex; gap: .4rem; align-items: baseline; width: 100%;
  background: none; border: 1px solid transparent; border-radius: 6px;
  padding: .25rem .4rem; cursor: pointer; color: inherit;
  font: inherit; text-align: left;
}
.tnode:hover { background: var(--sel); }
.tnode[aria-current="true"] { background: var(--sel); border-color: var(--accent); }
.tnode .ord {
  font-size: .66rem; color: var(--muted); min-width: 1.1rem;
  font-variant-numeric: tabular-nums;
}
.tnode .nm { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tnode .dot { width: .5rem; height: .5rem; border-radius: 50%; flex: none; }
.dot.committed { background: var(--good); }
.dot.failed { background: var(--bad); }
.dot.running { background: var(--accent); animation: pulse 1.4s ease-in-out infinite; }
.dot.unrecorded { background: none; box-shadow: inset 0 0 0 1px var(--muted); }
.leaf { color: var(--muted); padding: .25rem .4rem; font-size: .82rem;
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* the ribbon */
.ribbon { display: flex; flex-wrap: wrap; gap: 2px; margin: .1rem 0 .3rem; }
.cell {
  width: 1.15rem; height: 1.15rem; border-radius: 3px; border: none;
  cursor: pointer; padding: 0; position: relative;
}
.cell.survey { background: var(--survey); }
.cell.inspect { background: var(--inspect); }
.cell.test { background: var(--test); }
.cell.commit { background: var(--commit); }
.cell.other { background: var(--other); }
/* A rejected call keeps its phase colour: dimming it made an amber `test`
   cell read as the grey `other` swatch, which is the one confusion the ribbon
   cannot afford. The ring alone marks the rejection. */
.cell.rej { box-shadow: inset 0 0 0 2px var(--bad), inset 0 0 0 3px var(--panel); }
.legend { display: flex; gap: .8rem; flex-wrap: wrap; color: var(--muted);
          font-size: .74rem; margin-top: .25rem; }
.legend i { width: .6rem; height: .6rem; border-radius: 2px; display: inline-block;
            margin-right: .3rem; }

/* facts */
dl.facts { display: grid; grid-template-columns: minmax(8rem,max-content) 1fr;
           gap: .15rem .9rem; margin: .3rem 0; }
dl.facts dt { color: var(--muted); }
dl.facts dd { margin: 0; }
.counters { display: flex; flex-wrap: wrap; gap: .45rem; margin: .4rem 0; }
.counter {
  border: 1px solid var(--line); border-radius: 6px; padding: .3rem .55rem;
  background: var(--panel); min-width: 4.4rem;
}
.counter b { display: block; font-size: 1rem; font-variant-numeric: tabular-nums; }
.counter span { color: var(--muted); font-size: .68rem; text-transform: uppercase;
                letter-spacing: .05em; }

/* the timeline */
.turn { margin: 0 0 .15rem; }
.turn-text {
  border-left: 2px solid var(--line); padding: .3rem 0 .3rem .7rem;
  margin: .35rem 0; color: var(--muted); white-space: pre-wrap;
}
.call {
  border: 1px solid var(--line); border-left-width: 3px; border-radius: 6px;
  background: var(--panel); margin: .3rem 0;
}
.call.survey { border-left-color: var(--survey); }
.call.inspect { border-left-color: var(--inspect); }
.call.test { border-left-color: var(--test); }
.call.commit { border-left-color: var(--commit); }
.call.other { border-left-color: var(--other); }
.call.rej { border-left-color: var(--bad); }
.call > summary {
  cursor: pointer; padding: .45rem .6rem; display: flex; gap: .55rem;
  align-items: baseline; flex-wrap: wrap; list-style: none; min-width: 0;
}
.call > summary::-webkit-details-marker { display: none; }
.call > summary::before { content: "▸"; color: var(--muted); font-size: .7rem; }
.call[open] > summary::before { content: "▾"; }
.call .tn { font-weight: 600; }
.call .turnno {
  color: var(--muted); font-size: .72rem; font-variant-numeric: tabular-nums;
  min-width: 2.2rem;
}
.call .args { color: var(--ink); min-width: 0; overflow-wrap: anywhere; }
.call .res { color: var(--muted); margin-left: auto; text-align: right; }
.call.rej .res { color: var(--bad); }
.body { padding: 0 .6rem .6rem; }
pre {
  background: var(--bg); border: 1px solid var(--line); border-radius: 5px;
  padding: .5rem .6rem; overflow: auto; max-height: 26rem; font-size: .78rem;
  margin: .25rem 0;
}
.err { color: var(--bad); margin: .3rem 0; }
.rem { color: var(--muted); white-space: pre-wrap; font-size: .82rem; }
/* `minmax(0, 1fr)` rather than `1fr`: a grid item's automatic minimum size is
   its content, so a <pre> holding one long unwrapped JSON line widens its own
   track instead of scrolling inside it, and the whole page ends up scrolling
   sideways. */
.grid2 { display: grid; grid-template-columns: minmax(0,1fr) minmax(0,1fr);
         gap: .6rem; }
.grid2 > * { min-width: 0; }
@media (max-width: 60rem) {
  #app { grid-template-columns: 1fr; height: auto; }
  #side { border-right: none; border-bottom: 1px solid var(--line); }
  .grid2 { grid-template-columns: minmax(0,1fr); }
}

table { border-collapse: collapse; width: 100%; font-size: .84rem; }
th, td { text-align: left; padding: .3rem .55rem; border-bottom: 1px solid var(--line);
         vertical-align: top; }
th { color: var(--muted); font-weight: 600; white-space: nowrap; }
.scroll { overflow-x: auto; }
.controls { display: flex; gap: .5rem; align-items: center; flex-wrap: wrap;
            margin: .5rem 0; }
.controls input[type=search] {
  flex: 1; min-width: 10rem; padding: .32rem .5rem; border-radius: 6px;
  border: 1px solid var(--line); background: var(--panel); color: var(--ink);
  font: inherit;
}
.controls label { color: var(--muted); font-size: .8rem; display: flex;
                  gap: .25rem; align-items: center; cursor: pointer; }
.note { color: var(--muted); font-size: .82rem; margin: .35rem 0; }
.warnbox {
  border: 1px solid var(--bad); border-radius: 6px; padding: .55rem .7rem;
  margin: .6rem 0; color: var(--ink);
}
.warnbox h4 { margin: 0 0 .25rem; font-size: .85rem; color: var(--bad); }
ul.plain { margin: .3rem 0; padding-left: 1.1rem; }
ul.plain li { margin: .15rem 0; }
"""

_SCRIPT = """
const PHASE_LABEL = {
  survey: "survey", inspect: "inspect", test: "test",
  commit: "commit", other: "other"
};
let STATE = window.__STATE__;
let selected = null;
const filters = { text: "", rejectionsOnly: false };

const esc = (value) => String(value === null || value === undefined ? "" : value)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;");

const el = (id) => document.getElementById(id);

function facts(rows) {
  if (!rows || !rows.length) return "";
  return "<dl class=facts>" + rows.map(
    ([k, v]) => "<dt>" + esc(k) + "</dt><dd>" + esc(v) + "</dd>"
  ).join("") + "</dl>";
}

function nodeIds() { return Object.keys(STATE.nodes); }

function renderTree() {
  const tree = STATE.tree;
  const seen = new Set();
  const draw = (id) => {
    const node = STATE.nodes[id];
    const kids = tree.children[id] || [];
    if (seen.has(id)) return "";
    seen.add(id);
    let html = "<li>";
    if (node) {
      const order = node.visit_order === null || node.visit_order === undefined
        ? "" : (node.visit_order + 1);
      html += "<button class=tnode data-node='" + esc(id) + "'" +
        (id === selected ? " aria-current=true" : "") +
        " title='" + esc(id) + "'>" +
        "<span class=ord>" + esc(order) + "</span>" +
        "<span class='dot " + esc(node.status) + "'></span>" +
        "<span class=nm>" + esc(id) + "</span>" +
        (node.failure_fallback ? "<span class='badge bad'>fallback</span>" : "") +
        (node.high_quality === false && node.status === "committed"
          ? "<span class='badge warn'>gate</span>" : "") +
        "</button>";
    } else {
      html += "<div class=leaf title='" + esc(id) + "'>" + esc(id) + "</div>";
    }
    if (kids.length) html += "<ul>" + kids.map(draw).join("") + "</ul>";
    return html + "</li>";
  };
  const roots = tree.roots.length ? tree.roots
    : nodeIds().filter((id) => !Object.values(tree.children).flat().includes(id));
  const orphans = nodeIds().filter((id) => !seen.has(id) && !roots.includes(id));
  const body = "<ul class=tree>" + roots.map(draw).join("") +
    orphans.map(draw).join("") + "</ul>";
  el("tree").innerHTML = body;
  el("tree").querySelectorAll(".tnode").forEach((button) => {
    button.onclick = () => select(button.dataset.node);
  });
}

function renderSide() {
  const live = STATE.active_nodes && STATE.active_nodes.length;
  // Only the two rows a reader checks at a glance stay expanded; the rest of
  // the run header is long prose and would push the tree below the fold.
  const brief = (STATE.header || []).filter(
    ([key]) => key === "run id" || key === "model");
  const rest = (STATE.header || []).filter(
    ([key]) => key !== "run id" && key !== "model");
  const notes = (STATE.notes || []).concat(STATE.family || []);
  el("runhead").innerHTML =
    "<h1>Trajectory view</h1>" +
    "<div class=sub>" + esc(STATE.run_dir) + "</div>" +
    (live ? "<p><span class='badge live'>running: " +
      esc(STATE.active_nodes.join(", ")) + "</span></p>" : "") +
    facts(brief) +
    ((rest.length || notes.length)
      ? "<details><summary class=note>run facts and notes</summary>" +
        facts(rest) + facts(notes.map(
          (n) => Array.isArray(n) ? n : ["note", n])) + "</details>"
      : "");
  el("notes").innerHTML = "";
}

function ribbon(node) {
  if (!node.ribbon || !node.ribbon.length) return "";
  const cells = node.ribbon.map((cell, index) =>
    "<button class='cell " + esc(cell.phase) + (cell.ok ? "" : " rej") +
    "' data-jump='" + index + "' title='turn " + esc(cell.turn) + " · " +
    esc(cell.name) + (cell.ok ? "" : " · rejected") + "'></button>"
  ).join("");
  const legend = STATE.phase_order.map((phase) =>
    "<span><i class='cell " + esc(phase) +
    "' style='width:.6rem;height:.6rem'></i>" + esc(PHASE_LABEL[phase]) +
    "</span>").join("") +
    "<span><i style='box-shadow:inset 0 0 0 2px var(--bad);width:.6rem;" +
    "height:.6rem;border-radius:2px;display:inline-block;margin-right:.3rem'>" +
    "</i>rejected</span>";
  return "<h3>session shape · one cell per tool call, in order</h3>" +
    "<div class=ribbon>" + cells + "</div>" +
    "<div class=legend>" + legend + "</div>";
}

function counters(node) {
  const entries = Object.entries(node.counters || {}).filter(
    ([, value]) => value !== null && value !== undefined
  );
  if (!entries.length) return "";
  return "<div class=counters>" + entries.map(
    ([k, v]) => "<div class=counter><b>" + esc(v) + "</b><span>" + esc(k) +
      "</span></div>"
  ).join("") + "</div>";
}

function callView(call, turnIndex, position) {
  const rejected = call.answered && !call.ok;
  const classes = "call " + call.phase + (rejected ? " rej" : "");
  let head =
    "<summary><span class=turnno>t" + esc(turnIndex) + "</span>" +
    "<span class='badge'>" + esc(PHASE_LABEL[call.phase] || call.phase) +
    "</span><span class='tn mono'>" + esc(call.name) + "</span>" +
    "<span class=args>" + esc(call.arguments_digest) + "</span>" +
    "<span class=res>" + esc(call.result_digest || "") +
    (rejected ? " <span class='badge bad'>" + esc(call.error_category || "") +
      "</span>" : "") + "</span></summary>";
  let body = "<div class=body>";
  if (rejected) {
    body += "<p class=err><b>" + esc(call.error_type) + "</b> · " +
      esc(call.error_code) + "<br>" + esc(call.error_message) + "</p>";
    if (call.remediation) {
      body += "<p class=rem><b>remediation sent back:</b>\\n" +
        esc(call.remediation) + "</p>";
    }
  }
  body += "<div class=grid2><div><h3>arguments</h3><pre>" +
    esc(call.arguments_json) + "</pre></div><div><h3>" +
    (rejected ? "rejection" : "result") + "</h3><pre>" +
    esc(call.result_json || "(no recorded answer)") + "</pre></div></div></div>";
  return "<details class='" + classes + "' id='call-" + position +
    "' data-callid='" + esc(call.call_id) + "'>" + head + body + "</details>";
}

function matches(call) {
  if (filters.rejectionsOnly && !(call.answered && !call.ok)) return false;
  if (!filters.text) return true;
  const hay = [call.name, call.arguments_digest, call.result_digest,
    call.error_code, call.error_message, call.arguments_json, call.result_json]
    .join(" ").toLowerCase();
  return hay.includes(filters.text);
}

function timeline(node) {
  let position = 0;
  let shown = 0;
  const blocks = (node.turns || []).map((turn) => {
    let html = "";
    if (turn.text && !filters.rejectionsOnly && !filters.text) {
      html += "<div class=turn-text>" + esc(turn.text) + "</div>";
    }
    turn.calls.forEach((call) => {
      const here = position++;
      if (!matches(call)) return;
      shown++;
      html += callView(call, turn.index, here);
    });
    return html ? "<div class=turn>" + html + "</div>" : "";
  }).join("");
  if (!shown) {
    return "<p class=note>no tool call matches the current filter.</p>";
  }
  return blocks;
}

function rulesTable(node) {
  if (!node.rules || !node.rules.length) return "";
  const rows = node.rules.map((rule) =>
    "<tr><td class=mono>" + esc(rule.dsl) + "</td><td>" + esc(rule.scope) +
    "</td><td>" + esc(rule.confidence) + "</td><td>" + esc(rule.validation) +
    "</td><td>" + esc(rule.rationale) + "</td></tr>").join("");
  return "<h3>what it committed</h3><div class=scroll><table><tr><th>rule</th>" +
    "<th>scope</th><th>confidence</th><th>validation</th><th>rationale</th></tr>" +
    rows + "</table></div>";
}

function formsTable(node) {
  if (!node.forms || !node.forms.length) return "";
  const rows = node.forms.map(
    ([concept, segments]) => "<tr><td class=mono>" + esc(concept) +
      "</td><td class=mono>" + esc(segments) + "</td></tr>").join("");
  const omitted = node.omitted_forms
    ? "<p class=note>" + esc(node.omitted_forms) +
      " more form(s) in result.json</p>" : "";
  return "<details><summary><h3 style='display:inline'>reconstructed forms (" +
    esc(node.forms.length) + ")</h3></summary><div class=scroll><table><tr>" +
    "<th>concept</th><th>segments</th></tr>" + rows + "</table></div>" +
    omitted + "</details>";
}

function renderMain() {
  const node = STATE.nodes[selected];
  if (!node) {
    el("main").innerHTML = "<p class=note>Select a node.</p>";
    return;
  }
  const badges =
    "<span class='badge " + (node.status === "committed" ? "good" :
      node.status === "failed" ? "bad" :
      node.status === "running" ? "warn" : "") + "'>" + esc(node.status) +
    "</span>" +
    (node.high_quality === true ? "<span class='badge good'>high_quality</span>" :
     node.high_quality === false ? "<span class='badge warn'>gate rejected</span>" :
     "") +
    (node.failure_fallback ? "<span class='badge bad'>identity fallback</span>" : "") +
    (node.source === "events" ? "<span class='badge live'>in flight</span>" : "");

  let warn = "";
  if (node.failure) {
    warn += "<div class=warnbox><h4>the session did not commit</h4>" +
      esc(node.failure) + "</div>";
  }
  if (node.fallbacks_beneath && node.fallbacks_beneath.length) {
    warn += "<div class=warnbox><h4>built on an identity fallback</h4>" +
      "This node reads reconstructions from below it, and " +
      esc(node.fallbacks_beneath.join(", ")) +
      " never committed. What those sessions would have found is not in the " +
      "evidence this node saw. A mechanical fact about the walk, not a " +
      "judgement on this session.</div>";
  }
  if (node.quality_reasons && node.quality_reasons.length) {
    warn += "<div class=warnbox><h4>the workflow filter rejected this session" +
      "</h4><ul class=plain>" + node.quality_reasons.map(
        (reason) => "<li>" + esc(reason) + "</li>").join("") + "</ul></div>";
  }
  if (node.flags && node.flags.length) {
    warn += "<div class=warnbox><h4>worth a look</h4><ul class=plain>" +
      node.flags.map((flag) => "<li>" + esc(flag) + "</li>").join("") +
      "</ul></div>";
  }
  if (node.note) warn += "<p class=note>" + esc(node.note) + "</p>";

  el("main").innerHTML =
    "<h2>" + esc(node.node_id) + " " + badges + "</h2>" +
    "<div class=sub>" + esc((node.children || []).join("  ·  ")) + "</div>" +
    warn + ribbon(node) + counters(node) +
    (node.summary ? "<h3>the session's own summary</h3><p>" +
      esc(node.summary) + "</p>" : "") +
    rulesTable(node) +
    ((node.anomalies && node.anomalies.length)
      ? "<h3>anomalies it recorded</h3><ul class=plain>" + node.anomalies.map(
          (a) => "<li>" + esc(a) + "</li>").join("") + "</ul>" : "") +
    "<h3>timeline</h3>" +
    "<div class=controls>" +
    "<input type=search id=q placeholder='filter calls: tool, segment, error…' " +
    "value='" + esc(filters.text) + "'>" +
    "<label><input type=checkbox id=onlyrej" +
    (filters.rejectionsOnly ? " checked" : "") + "> rejections only</label>" +
    "</div><div id=tl>" + timeline(node) + "</div>" +
    (node.diagnostics && node.diagnostics.length
      ? "<details><summary><h3 style='display:inline'>deterministic step" +
        "</h3></summary>" + facts(node.diagnostics) + "</details>" : "") +
    formsTable(node);

  const q = el("q");
  if (q) {
    q.oninput = () => {
      filters.text = q.value.trim().toLowerCase();
      el("tl").innerHTML = timeline(node);
      q.focus();
    };
  }
  const only = el("onlyrej");
  if (only) {
    only.onchange = () => {
      filters.rejectionsOnly = only.checked;
      el("tl").innerHTML = timeline(node);
    };
  }
  document.querySelectorAll("[data-jump]").forEach((cell) => {
    cell.onclick = () => {
      const target = el("call-" + cell.dataset.jump);
      if (!target) return;
      target.open = true;
      target.scrollIntoView({ behavior: "smooth", block: "center" });
    };
  });
}

function select(id) {
  selected = id;
  renderTree();
  renderMain();
  el("main").scrollTop = 0;
}

function renderAll() {
  renderSide();
  if (!selected || !STATE.nodes[selected]) {
    const active = (STATE.active_nodes || [])[0];
    const order = STATE.tree.order || [];
    selected = active || order[order.length - 1] || nodeIds()[0] || null;
  }
  renderTree();
  renderMain();
}

renderAll();

// `generated_at` moves on every rebuild, so comparing whole states would
// re-render — and collapse whatever the reader had open — twice a second on a
// run that is not doing anything. Compare everything else.
function signature(state) {
  const rest = Object.assign({}, state);
  delete rest.generated_at;
  return JSON.stringify(rest);
}

if (window.__LIVE__) {
  let last = signature(STATE);
  const tick = async () => {
    try {
      const response = await fetch("state.json", { cache: "no-store" });
      if (response.ok) {
        const next = await response.json();
        const now = signature(next);
        if (now !== last) {
          last = now;
          const keep = selected;
          const scroll = el("main").scrollTop;
          const open = new Set(
            [...document.querySelectorAll(".call[open]")]
              .map((node) => node.dataset.callid));
          STATE = next;
          if (keep && STATE.nodes[keep]) selected = keep;
          renderAll();
          document.querySelectorAll(".call").forEach((node) => {
            if (open.has(node.dataset.callid)) node.open = true;
          });
          el("main").scrollTop = scroll;
        }
      }
    } catch (error) { /* the run may be between writes; try again */ }
    setTimeout(tick, window.__POLL_MS__ || 2000);
  };
  setTimeout(tick, window.__POLL_MS__ || 2000);
}
"""


_SHELL = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%%TITLE%%</title>
<style>%%STYLE%%</style></head>
<body><div id="app">
<aside id="side"><div id="runhead"></div>
<h3>the walk, root first</h3>
<p class="note">The number is the order the traversal reconstructed it: a node
is built from its direct children, so it is reconstructed after them.</p>
<div id="tree"></div><div id="notes"></div></aside>
<main id="main"></main></div>
<script>window.__STATE__ = %%STATE%%;
window.__LIVE__ = %%LIVE%%; window.__POLL_MS__ = %%POLL%%;</script>
<script>%%SCRIPT%%</script>
</body></html>
"""


def render_page(
    state: Mapping[str, Any],
    *,
    live: bool = False,
    poll_ms: int = 2000,
) -> str:
    """One self-contained page. The live server serves the same one."""
    payload = json.dumps(state, ensure_ascii=False).replace("</", "<\\/")
    return (
        _SHELL.replace("%%TITLE%%", f"Trajectory view {state.get('run_dir', '')}")
        .replace("%%STYLE%%", _STYLE)
        .replace("%%STATE%%", payload)
        .replace("%%LIVE%%", "true" if live else "false")
        .replace("%%POLL%%", str(int(poll_ms)))
        .replace("%%SCRIPT%%", _SCRIPT)
    )


def visualize_run(
    run_dir: str | Path,
    *,
    html_path: str | Path | None = None,
    form_limit: int | None = DEFAULT_FORM_LIMIT,
    payload_chars: int = DEFAULT_PAYLOAD_CHARS,
) -> Path:
    """Write the standalone page for a finished run and return its path."""
    artifacts = load_run(run_dir)
    state = build_state(
        artifacts, form_limit=form_limit, payload_chars=payload_chars
    )
    destination = (
        Path(html_path).expanduser()
        if html_path is not None
        else artifacts.run_dir / DEFAULT_OUTPUT_NAME
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_page(state), encoding="utf-8")
    return destination


# ---------------------------------------------------------------------------
# live mode
# ---------------------------------------------------------------------------


def serve(
    run_dir: str | Path,
    *,
    port: int = DEFAULT_PORT,
    host: str = "127.0.0.1",
    payload_chars: int = DEFAULT_PAYLOAD_CHARS,
    poll_ms: int = 2000,
) -> None:
    """Serve the same page against a directory that is still being written.

    State is rebuilt per request rather than cached, because the point is to
    read a run in progress. It binds the loopback interface: a run directory
    holds prompts and model output, and nothing here is authenticated.
    """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    directory = Path(run_dir).expanduser()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - the stdlib's spelling
            path = self.path.split("?", 1)[0]
            try:
                if path in {"/", "/index.html"}:
                    state = build_live_state(directory, payload_chars=payload_chars)
                    page = render_page(state, live=True, poll_ms=poll_ms)
                    self._send(page.encode("utf-8"), "text/html; charset=utf-8")
                    return
                if path == "/state.json":
                    state = build_live_state(directory, payload_chars=payload_chars)
                    body = json.dumps(state, ensure_ascii=False).encode("utf-8")
                    self._send(body, "application/json; charset=utf-8")
                    return
            except Exception as error:  # a partial write should not kill the server
                self.send_error(503, f"run not readable yet: {error}")
                return
            self.send_error(404)

        def log_message(self, *_args: Any) -> None:
            return

    with ThreadingHTTPServer((host, port), Handler) as server:
        print(f"serving {directory} at http://{host}:{port}/  (ctrl-c to stop)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
