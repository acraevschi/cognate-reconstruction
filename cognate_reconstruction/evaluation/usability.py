"""R02 Stage A: supplied-hypothesis usability, `r02-usability-v1`.

The Stage A instruction block hands the model one explicit hypothesis for one
node. Success is exact execution of those supplied choices, one specified
harmless revision with a new preview, and a commit of the revised hypothesis
whose output keeps its source-unit provenance. It is a protocol result, never
reconstruction-quality evidence: the reference forms are only the
deterministic execution of the supplied claims.

Claims are compared after expansion to local sets, so a shared claim and the
equivalent local choices are the same hypothesis; the shape is reported
separately. Rationale prose is required by the harness but never compared.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.tools.inventory_evidence import node_inventory
from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.schemas.rules import RuleEnvironment

USABILITY_VERSION = "r02-usability-v1"


def _conditioning_key(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, RuleEnvironment):
        value = RuleEnvironment.model_validate_json(json.dumps(value))
    # An all-default environment conditions nothing: the same claim as none.
    return None if value == RuleEnvironment() else value.model_dump_json()


def claim_key(set_id: str, proto_segment, confidence: float, conditioning) -> tuple:
    return (set_id, proto_segment, round(float(confidence), 6), _conditioning_key(conditioning))


def node_evidence(case: Mapping, payload, node_id: str):
    """The node's local sets and recurrence patterns, as its session sees them."""
    children = {lexicon.variety_id: lexicon for lexicon in payload.lexicons}
    context = AgentContext(node_id=node_id, child_lexicons=tuple(children.values()),
                           aligner=LingPyAligner())
    inventory, _ = node_inventory(context, segmentation_overlay_id=None, alignment_overlay_id=None)
    return inventory


def expected_hypothesis(case: Mapping, payload, *, revised: bool) -> dict:
    """Expanded claim keys and residue choice of the supplied hypothesis."""
    spec = case["supplied_hypothesis"]
    inventory = node_evidence(case, payload, spec["node_id"])
    revision = spec["revision"]
    claims = set()
    patterns = {}
    for shared in spec["shared_claims"]:
        pattern = next(p for p in inventory.recurrence_patterns
                       if list(p.segments) == shared["reflexes"])
        confidence = shared["confidence"]
        if revised and revision["label"] == shared["label"]:
            confidence = revision["to"]
        patterns[pattern.set_id] = tuple(sorted(pattern.member_set_ids))
        claims |= {claim_key(member, shared["proto_segment"], confidence, shared.get("conditioning"))
                   for member in pattern.member_set_ids}
    for choice in spec["choices"]:
        local = next(s for s in inventory.sets if s.scope_id == f"cog:{choice['unit']}"
                     and list(s.segments) == choice["reflexes"])
        confidence = choice["confidence"]
        if revised and revision["label"] == choice["label"]:
            confidence = revision["to"]
        claims.add(claim_key(local.set_id, choice["proto_segment"], confidence, choice.get("conditioning")))
    return {"claims": frozenset(claims), "residue_policy": spec["residue_policy"],
            "residue_witness_child_id": spec["residue_witness_child_id"], "shared_patterns": patterns}


def expand_arguments(arguments: Mapping, patterns: Mapping[str, Sequence[str]] | None = None) -> dict:
    """Expanded claim keys of preview or commit inventory arguments.

    Shared claims expand over the member IDs they themselves select, so a
    claim over the wrong members is a different hypothesis.
    """
    claims = set()
    for row in tuple(arguments.get("choices") or ()) + tuple(arguments.get("commitments") or ()):
        claims.add(claim_key(row["set_id"], row.get("proto_segment"), row["confidence"], row.get("conditioning")))
    shared_shape = {}
    for shared in arguments.get("shared_claims") or ():
        shared_shape[shared["pattern_id"]] = tuple(sorted(shared["member_set_ids"]))
        claims |= {claim_key(member, shared.get("proto_segment"), shared["confidence"], shared.get("conditioning"))
                   for member in shared["member_set_ids"]}
    return {"claims": frozenset(claims), "residue_policy": arguments.get("residue_policy"),
            "residue_witness_child_id": arguments.get("residue_witness_child_id"),
            "shared_patterns": shared_shape}


def _same(observed: Mapping, expected: Mapping) -> bool:
    return all(observed[key] == expected[key] for key in ("claims", "residue_policy", "residue_witness_child_id"))


def tool_exchanges(trajectory) -> list[dict]:
    """Each tool call with its result, in session order."""
    results = {m.tool_call_id: m for m in trajectory.messages if m.tool_call_id is not None}
    exchanges = []
    for message in trajectory.messages:
        for call in message.tool_calls:
            result = results.get(call.call_id)
            outcome = json.loads(result.content) if result is not None and result.content else {}
            exchanges.append({"call_id": call.call_id, "name": call.name, "arguments": call.arguments,
                              "ok": bool(outcome.get("ok")), "result": outcome.get("result") or {}})
    return exchanges


def instruction_block(case: Mapping, protocol: str) -> str:
    """The model-visible Stage A task, appended to the packaged instructions."""
    spec = case["supplied_hypothesis"]
    revision = spec["revision"]
    lines = [
        "## Stage A protocol task: execute a supplied hypothesis",
        "",
        f"This session is a protocol exercise for node {spec['node_id']}. The parent hypothesis is",
        "supplied below. Execute it exactly; do not evaluate or improve it. It is not a",
        "historical claim, and nothing here asks you to discover a reconstruction.",
        "",
        "1. Find the IDs with `summarize_correspondences`: reading=recurrence, min_support=1",
        "   for csp-* patterns and their member_set_ids; reading=local, min_support=1 for",
        "   csu-* local sets and their scope_id.",
        "2. Preview with `test_proto_assembly` exactly this hypothesis and nothing else:",
        f"   - residue_policy `{spec['residue_policy']}`, residue_witness_child_id `{spec['residue_witness_child_id']}`;",
    ]
    for shared in spec["shared_claims"]:
        row = (f"   - shared claim over the recurrence pattern with reflexes {json.dumps(shared['reflexes'])}, "
               f"selecting all of its member_set_ids: proto_segment {json.dumps(shared['proto_segment'])}, "
               f"confidence {shared['confidence']}")
        if shared.get("conditioning"):
            row += f", conditioning {json.dumps(shared['conditioning'])}"
        row += f", rationale {json.dumps(shared['rationale'])}"
        if shared.get("directionality_rationale"):
            row += f", directionality_rationale {json.dumps(shared['directionality_rationale'])}"
        lines.append(row + ";")
    noun = "commitments" if protocol == "full-payload" else "choices"
    for choice in spec["choices"]:
        row = (f"   - one entry in {noun} for the local set with scope_id `cog:{choice['unit']}` and reflexes "
               f"{json.dumps(choice['reflexes'])}: proto_segment {json.dumps(choice['proto_segment'])}, "
               f"confidence {choice['confidence']}, rationale {json.dumps(choice['rationale'])}")
        if choice.get("directionality_rationale"):
            row += f", directionality_rationale {json.dumps(choice['directionality_rationale'])}"
        lines.append(row + ";")
    lines += [
        "   A recurrence pattern can pool these local sets with sets of other units; select the",
        "   named local sets themselves, not such a pattern.",
        "3. Then make exactly one revision: change only the confidence of the claim over",
        f"   {json.dumps(next(s for s in spec['shared_claims'] if s['label'] == revision['label'])['reflexes'])} "
        f"from {revision['from']} to {revision['to']}, and preview again.",
    ]
    if protocol == "full-payload":
        lines.append("4. Commit with `commit_reconstruction`, giving the revised inventory exactly as previewed.")
    else:
        lines.append("4. Commit with `commit_reconstruction` using the hypothesis_id of the revised preview.")
    target = case["targets"][spec["node_id"]]["forms"]
    rendered = "; ".join(f"{concept} `{' + '.join(text for _, text in alternatives[0])}`"
                         for concept, alternatives in target.items())
    lines += ["", f"After the commit the parent forms should be: {rendered}.", ""]
    return "\n".join(lines)


def stage_a_instructions(case: Mapping, protocol: str, base: str) -> str:
    return base.rstrip("\n") + "\n\n" + instruction_block(case, protocol)


def check_stage_a(case: Mapping, payload, trajectory, step, *, protocol: str,
                  readback: Mapping[str, bool] | None = None) -> dict:
    """Score one Stage A node session; `step` is the committed step, if any."""
    node = case["supplied_hypothesis"]["node_id"]
    original = expected_hypothesis(case, payload, revised=False)
    revised = expected_hypothesis(case, payload, revised=True)
    report = {"usability_version": USABILITY_VERSION, "node_id": node, "protocol": protocol,
              "trajectory_present": trajectory is not None}
    exchanges = tool_exchanges(trajectory) if trajectory is not None else []
    previews = [e for e in exchanges if e["name"] == "test_proto_assembly" and e["ok"]]
    expanded = [expand_arguments(e["arguments"]) for e in previews]
    original_index = next((i for i, item in enumerate(expanded) if _same(item, original)), None)
    # Any later preview of the revised claims counts: prose edits and a
    # not-yet-commit-ready preview fixed in a new one are the documented path.
    revised_indices = [i for i, item in enumerate(expanded) if _same(item, revised)
                       and original_index is not None and i > original_index]
    committed = getattr(trajectory, "committed_reconstruction", None) if trajectory is not None else None
    fallback = bool(step is not None and step.diagnostics.failure_fallback)
    model_committed = bool(trajectory is not None and trajectory.completed and committed is not None and not fallback)
    request = getattr(committed, "request", None)
    commit_view = None
    if request is not None and getattr(request, "commitments", None) is not None:
        commit_view = {
            "claims": frozenset(claim_key(c.set_id, c.proto_segment, c.confidence, c.conditioning)
                                for c in request.commitments),
            "residue_policy": request.residue_policy.value if request.residue_policy is not None else None,
            "residue_witness_child_id": request.residue_witness_child_id,
        }
    commit_calls = [e for e in exchanges if e["name"] == "commit_reconstruction" and e["ok"]]
    handle = commit_calls[-1]["arguments"].get("hypothesis_id") if commit_calls else None
    revised_handles = {previews[i]["result"].get("hypothesis_id") for i in revised_indices}
    inventory_commit = (commit_calls[-1]["arguments"].get("inventory") or {}) if commit_calls else {}
    approved = {c.pattern_id: tuple(sorted(c.member_set_ids))
                for c in getattr(committed, "approved_shared_claims", ())} if committed is not None else {}
    output = {}
    provenance_intact = step is not None
    targets = {concept: [tuple(" ".join(text for _, text in alt).split()) for alt in alternatives]
               for concept, alternatives in case["targets"][node]["forms"].items()}
    expected_units = {concept: [[unit for unit, _ in alt] for alt in alternatives]
                      for concept, alternatives in case["targets"][node]["forms"].items()}
    for distribution in (step.output_beam.distributions if step is not None else ()):
        top = distribution.candidates[0] if distribution.candidates else None
        analysis = top.analysis if top is not None else None
        units = [p.cognate_set_id for p in analysis.pieces] if analysis is not None else None
        output[distribution.concept_id] = {"segments": list(top.segments) if top else None, "units": units}
        if analysis is None or any(not p.sources or not p.column_ids or p.kind == "unknown"
                                   for p in analysis.pieces):
            provenance_intact = False
    output_exact = bool(step is not None) and all(
        concept in output and tuple(output[concept]["segments"] or ()) in alternatives
        for concept, alternatives in targets.items())
    units_exact = bool(step is not None) and all(
        concept in output and output[concept]["units"] in expected_units[concept] for concept in targets)
    criteria = {
        "model_committed": model_committed,
        "committed_supplied_hypothesis": commit_view is not None and _same(commit_view, revised),
        "residue_as_supplied": commit_view is not None and (
            commit_view["residue_policy"], commit_view["residue_witness_child_id"]) == (
            revised["residue_policy"], revised["residue_witness_child_id"]),
        "previewed_original": original_index is not None,
        "previewed_revision_after_original": bool(revised_indices),
        # A handle from a revised preview, or (both profiles allow it) the
        # revised inventory itself after such a preview.
        "committed_revised_preview": bool(revised_indices) and (
            (handle is not None and handle in revised_handles)
            or (handle is None and bool(inventory_commit) and _same(expand_arguments(inventory_commit), revised))),
        "output_matches_reference": output_exact,
        "output_units_match": units_exact,
        "provenance_intact": provenance_intact,
    }
    if readback is not None:
        criteria["artifact_readback"] = all(readback.values())
    gate = ("model_committed", "committed_supplied_hypothesis", "residue_as_supplied",
            "output_matches_reference", "output_units_match", "provenance_intact")
    gate = gate + (("artifact_readback",) if readback is not None else ())
    usable = all(criteria[key] for key in gate)
    success = usable and all(criteria[key] for key in (
        "previewed_original", "previewed_revision_after_original", "committed_revised_preview"))
    if not report["trajectory_present"]:
        outcome = "no_session"
    elif fallback:
        outcome = "fallback"
    elif not model_committed:
        outcome = "no_commit"
    elif success:
        outcome = "success"
    elif usable:
        outcome = "usable_revision_protocol_deviation"
    elif criteria["committed_supplied_hypothesis"]:
        outcome = "committed_supplied_hypothesis_output_defect"
    else:
        outcome = "committed_other_hypothesis"
    report.update({
        "outcome": outcome, "success": success, "criteria": criteria, "gate_criteria": list(gate),
        "readback": dict(readback or {}),
        "preview_count": len(previews), "rejected_tool_calls": sum(not e["ok"] for e in exchanges),
        "tool_calls": len(exchanges),
        "shape_matches_supplied": approved == original["shared_patterns"],
        "commit_extra_claims": sorted(map(list, (commit_view or {"claims": frozenset()})["claims"] - revised["claims"]), key=repr),
        "commit_missing_claims": sorted(map(list, revised["claims"] - (commit_view or {"claims": frozenset()})["claims"]), key=repr),
        "output": output,
        "stage_gate": {"usable": usable, "reason": (
            "committed the supplied revised hypothesis with intact output provenance" if usable else
            f"Stage A outcome {outcome}; failed: " + ", ".join(k for k in gate if not criteria[k]))},
        "interpretation": "protocol usability only; reference forms execute supplied claims and carry no quality claim",
    })
    return report
