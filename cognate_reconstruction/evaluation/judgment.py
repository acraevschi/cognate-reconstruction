"""R04 Stage C: multi-outgroup judgment and warranted uncertainty, `r04-judgment-v1`.

An additive, report-only reading beside `r02-decisions-v1` (whose value
readings it reuses unchanged), task02-v1 and task04-units-v1. Stage C asks for
the decision the stated criterion gives where the survey's per-column outgroup
witness — R02's deployable rule — does not: three outgroups, other-unit forms,
missing forms and tied items. It adds:

- the confidence and rationale of the committed claim that decided each
  opportunity's column (none when the residue policy decided it);
- warranted uncertainty: tied items are marked when that claim's confidence is
  at most 0.5, the convention the criterion block states; a decided item at or
  below 0.5 is hedged, and an incorrect decided item or a tied item above 0.5
  is a false confident claim;
- the model's score on each shallow rule's error set, so a partial reading of
  the criterion shows as the component it misses;
- what outgroup evidence the session actually read (navigation), so a wrong
  decision on evidence the model never saw is not read as a judgment.

Missing, unscorable and fallback outputs stay in every denominator.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

from cognate_reconstruction.evaluation.decisions import score_decisions, stage_b_instructions
from cognate_reconstruction.evaluation.usability import tool_exchanges

JUDGMENT_VERSION = "r04-judgment-v1"
UNRESOLVED_CONFIDENCE = 0.5
"""Tied items at or below this, decided items above it: the block's convention."""

# Pre-registered descriptive labels (one trial; a next-step reading, not a ranking).
CRITERION_PRIMARY = 17       # of 19 decided opportunities
WITNESS_RULE_FLOOR = 5       # of the outgroup-witness rule's 6 errors
PAIRS_FLOOR = 4              # of 5 matched pairs
SURVEY_LABEL_CEILING = 2     # at most this many of the witness rule's errors right
BASELINE_PRIMARY = 15        # the best shallow rule's score
BASELINE_PAIRS = 1           # the witness rule's pair count


def stage_c_instructions(case: Mapping, base: str) -> str:
    return stage_b_instructions(case, base)


def _deciding_columns(opportunity: Mapping, step):
    """The assembly columns of the opportunity's unit position (as `r02-decisions-v1`)."""
    if step is None:
        return []
    report = next((r for r in step.assembly_reports if r.concept_id == opportunity["concept_id"]), None)
    if report is None:
        return []
    columns = [c for c in report.columns if c.unit_id == f"cog:{opportunity['unit']}"]
    if opportunity["locus"] != "piece":
        columns = [c for c in columns if None in c.reflexes and opportunity["token"] in c.reflexes]
    return columns


def committed_claims(trajectory) -> dict[str, dict]:
    """Committed claims by local set ID, shared claims already expanded."""
    committed = getattr(trajectory, "committed_reconstruction", None) if trajectory is not None else None
    request = getattr(committed, "request", None)
    return {c.set_id: {"confidence": c.confidence, "rationale": c.rationale, "proto_segment": c.proto_segment}
            for c in (getattr(request, "commitments", None) or ())}


def _form_sightings(value, outgroups: frozenset[str], seen: set) -> None:
    """(node, concept) of every outgroup form or unit state a tool result showed."""
    if isinstance(value, Mapping):
        node = value.get("node_id") or value.get("variety_id")
        # `search_forms` hits carry `segments`; `get_alignments` members `aligned_segments`.
        if node in outgroups and value.get("concept_id") and ("segments" in value or "aligned_segments" in value):
            seen.add((node, value["concept_id"]))
        # `polarize` node reports carry per-unit `observations` with `example_concept_ids`.
        if node in outgroups and "observations" in value:
            for obs in value.get("observations") or ():
                for cid in obs.get("example_concept_ids") or ():
                    seen.add((node, cid))
        # A single-concept `polarize` call also reports `columns_covered: 0` when an
        # outgroup has no form in that cognate unit, resolving its same-unit state.
        if (value.get("matched_concept_count") == 1
                and len(value.get("matched_concept_ids") or ()) == 1
                and isinstance(value.get("nodes"), (list, tuple))):
            cid = value["matched_concept_ids"][0]
            for report in value["nodes"]:
                if isinstance(report, Mapping) and report.get("node_id") in outgroups:
                    seen.add((report["node_id"], cid))
        for item in value.values():
            _form_sightings(item, outgroups, seen)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _form_sightings(item, outgroups, seen)


def navigation(case: Mapping, trajectory) -> dict:
    """What the session read: calls by tool, rejections, and outgroup forms seen per concept."""
    outgroups = frozenset(v for v in case["observed"] if v not in ("a", "b"))
    exchanges = tool_exchanges(trajectory) if trajectory is not None else []
    seen: set = set()
    for exchange in exchanges:
        if exchange["ok"] and exchange["name"] != "summarize_correspondences":
            _form_sightings(exchange["result"], outgroups, seen)
    with_forms = {concept: {o for o in outgroups if concept in case["observed"][o]}
                  for concept in case["observed"]["a"]}
    complete = {concept: forms <= {o for o, c in seen if c == concept} for concept, forms in with_forms.items()}
    return {
        "calls": dict(Counter(e["name"] for e in exchanges)),
        "rejected_calls": sum(not e["ok"] for e in exchanges),
        "survey_outgroup_profiles": sum(bool(e["result"].get("outgroup_reflexes")) for e in exchanges
                                        if e["ok"] and e["name"] == "summarize_correspondences"),
        "outgroup_forms_seen": sorted(f"{o}:{c}" for o, c in seen),
        "concepts_with_every_outgroup_form_seen": sum(complete.values()),
        "concepts": len(complete),
        "concept_outgroup_forms_seen": complete,
        "note": ("A form counts as seen when a non-survey tool result showed that outgroup's form "
                 "or unit state for the concept (search_forms, get_alignments, or polarize); "
                 "survey witnesses show presence only."),
    }


def score_judgment(case: Mapping, steps_by_node: Mapping, *, model_committed: Mapping[str, bool] | None = None,
                   trajectories_by_node: Mapping | None = None) -> dict:
    """`r02-decisions-v1` readings plus confidence, defeat sets and navigation."""
    base = score_decisions(case, steps_by_node, model_committed=model_committed)
    node = case["opportunities"][0]["node_id"]
    step = steps_by_node.get(node)
    trajectory = (trajectories_by_node or {}).get(node)
    claims = committed_claims(trajectory)
    by_id = {o["opportunity_id"]: o for o in case["opportunities"]}
    rows = []
    for row in base["opportunities"]:
        opportunity = by_id[row["opportunity_id"]]
        set_ids = sorted({c.set_id for c in _deciding_columns(opportunity, step)
                          if c.set_id is not None and c.resolved_by != "residue_policy"})
        deciding = [claims[s] for s in set_ids if s in claims]
        confidences = sorted({d["confidence"] for d in deciding})
        confidence = confidences[0] if len(confidences) == 1 else None
        counted = row["model_committed"] and not row["node_fallback"]
        rows.append({**row, "design_id": opportunity["design_id"],
                     "outgroup_states": opportunity["outgroup_states"],
                     "shallow_rule_errors": opportunity["shallow_rule_errors"],
                     "deciding_set_ids": set_ids, "confidence": confidence,
                     "confidences": confidences if len(confidences) > 1 else None,
                     "rationale": deciding[0]["rationale"] if len(deciding) == 1 else None,
                     "marked_unresolved": counted and confidence is not None and confidence <= UNRESOLVED_CONFIDENCE})
    primary = [r for r in rows if r["class"] == "primary"]
    ties = [r for r in rows if r["class"] != "primary"]
    counted = lambda r: r["model_committed"] and not r["node_fallback"]
    model_correct = lambda r: bool(r["correct"]) and counted(r)
    confident = lambda r: counted(r) and r["confidence"] is not None and r["confidence"] > UNRESOLVED_CONFIDENCE
    defeat = {}
    for rule in case["shallow_rules"]:
        items = [r for r in primary if rule in r["shallow_rule_errors"]]
        defeat[rule] = {"rule_errors": len(items), "model_correct": sum(map(model_correct, items)),
                        "rule_correct": len(primary) - len(items),
                        "items": {r["opportunity_id"]: r["reading"] for r in items}}
    pairs = {}
    for pair, members in (case.get("matched_pairs") or {}).items():
        items = [next(r for r in rows if r["opportunity_id"] == m) for m in members]
        pairs[pair] = all(map(model_correct, items))
    uncertainty = {
        "threshold": UNRESOLVED_CONFIDENCE,
        "ties": len(ties),
        "ties_marked": sum(r["marked_unresolved"] for r in ties),
        "ties_confident": sum(map(confident, ties)),
        "ties_without_single_claim": sum(counted(r) and r["confidence"] is None for r in ties),
        "decided_hedged": sum(counted(r) and r["confidence"] is not None
                              and r["confidence"] <= UNRESOLVED_CONFIDENCE for r in primary),
        "decided_incorrect_confident": sum(confident(r) and not r["correct"] for r in primary),
        "decided_without_single_claim": sum(counted(r) and r["confidence"] is None for r in primary),
    }
    uncertainty["false_confident_claims"] = uncertainty["ties_confident"] + uncertainty["decided_incorrect_confident"]
    model_primary = base["primary"]["model_committed_correct"]
    witness = defeat.get("outgroup-witness", {"model_correct": 0, "rule_errors": 0})
    others_pass = all(d["model_correct"] >= d["rule_errors"] - 1 for r, d in defeat.items() if r != "outgroup-witness")
    pair_count = sum(pairs.values())
    has_commit = any(counted(r) for r in rows)
    uniform = base["primary"]["uniform_reading"]
    if not has_commit:
        value_label = "no commit"
    elif uniform in ("retain", "absent"):
        value_label = "uniform (regularity) reading"
    elif witness["rule_errors"] and witness["model_correct"] <= SURVEY_LABEL_CEILING:
        value_label = "witness-rule level"
    elif (model_primary >= CRITERION_PRIMARY and witness["model_correct"] >= WITNESS_RULE_FLOOR
          and others_pass and pair_count >= PAIRS_FLOOR):
        value_label = "criterion-sensitive on this panel"
    elif model_primary <= BASELINE_PRIMARY or pair_count <= BASELINE_PAIRS:
        value_label = "baseline-level"
    else:
        value_label = "mixed"
    if not has_commit:
        uncertainty_label = "no commit"
    elif uncertainty["ties_marked"] >= len(ties) - 1 and uncertainty["decided_hedged"] <= 1:
        uncertainty_label = "warranted uncertainty"
    elif uncertainty["ties_marked"] == 0:
        uncertainty_label = "no uncertainty marking"
    else:
        uncertainty_label = "partial"
    return {
        "judgment_version": JUDGMENT_VERSION,
        "decisions_version": base["decisions_version"],
        "primary": base["primary"],
        "matched_pairs": {"model_both_correct": pair_count, "planned": len(pairs), "pairs": pairs,
                          "readings": base["matched_pairs"]["pairs"]},
        "shallow_rule_error_sets": defeat,
        "uncertainty": uncertainty,
        "decided_by": base["decided_by"],
        "navigation": navigation(case, trajectory),
        "labels": {"value": value_label, "uncertainty": uncertainty_label,
                   "rule": ("value: no commit if the scored node has no non-fallback model commitment; "
                            "uniform (regularity) reading if every primary opportunity has the same "
                            "retain or absent reading; witness-rule level if at most 2 of the witness "
                            "rule's 6 errors are right; criterion-sensitive if >=17/19, >=5/6 of those "
                            "errors, every other shallow rule's error set at most one short, and >=4/5 "
                            "pairs; baseline-level if <=15/19 or <=1/5 pairs; otherwise mixed. "
                            "uncertainty: no commit if no non-fallback model commitment; warranted if "
                            ">=3/4 ties marked and at most one decided item hedged; none if 0 ties "
                            "marked; otherwise partial.")},
        "opportunities": rows,
        "interpretation": (
            "Correct is conditional on the stated multi-outgroup parsimony criterion and the supplied "
            "cognate units. Tied items accept either value; their reading is the confidence convention. "
            "Labels are descriptive for one trial. The headline is primary.model_committed_correct."
        ),
    }
