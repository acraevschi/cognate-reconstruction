"""R02 Stage B: unit-scoped retention decisions, `r02-decisions-v1`.

An additive, report-only diagnostic beside task02-v1 and task04-units-v1. One
opportunity is one etymon position (or whole piece) at a scored node where
exactly one active child has material in one supplied cognate unit. The
reading uses the committed top candidate's analysis: a piece is found by its
cognate set, never by spelling. Each opportunity is read as

- `retain` / `absent`: the unit piece shows the material / the edge the
  material-less daughter shows (or, for a whole piece, the piece is present or
  not);
- `other`: the unit piece exists with neither edge (another value);
- `unit_missing`: an edge opportunity whose unit piece is gone or relabelled,
  so the material's unit cannot be read (never credited as `absent`);
- `unscorable`: no analysis, or unknown pieces that could hide the unit;
- `missing`: no output for the concept.

The primary denominator is every planned identified opportunity. Missing,
unscorable and other readings are not correct, so deleting output or analysis
cannot raise the primary rate. Unresolved (no-outgroup) opportunities are read
and reported but never scored as uniquely recoverable.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

DECISIONS_VERSION = "r02-decisions-v1"


def instruction_block(case: Mapping) -> str:
    """The Stage B criterion block appended to the packaged instructions.

    It states the definition's identification criterion, never an item or an
    answer, so a model is not scored against an assumption it was not given.
    """
    return "\n".join(case["task_block"])


def stage_b_instructions(case: Mapping, base: str) -> str:
    return base.rstrip("\n") + "\n\n" + instruction_block(case)


def read_opportunity(opportunity: Mapping, distribution) -> tuple[str, str | None]:
    """The output reading of one opportunity and a short reason."""
    if distribution is None or not distribution.candidates:
        return "missing", "no output for the concept"
    top = distribution.candidates[0]
    analysis = top.analysis
    if analysis is None:
        return "unscorable", "output has no analysis"
    unit = opportunity["unit"]
    matching = [piece for piece in analysis.pieces if piece.cognate_set_id == unit]
    unknown = any(piece.kind == "unknown" for piece in analysis.pieces)
    if opportunity["locus"] == "piece":
        if matching:
            return "retain", None
        return ("unscorable", "unknown piece could hold the unit") if unknown else ("absent", None)
    if len(matching) != 1:
        if unknown:
            return "unscorable", "unknown piece could hold the unit"
        return ("unit_missing", "unit piece absent or relabelled") if not matching else ("unscorable", "unit repeated")
    tokens = [top.segments[index] for index in matching[0].segment_indices]
    edge = tokens[-1] if opportunity["locus"] == "final" else tokens[0]
    if edge == opportunity["token"]:
        return "retain", None
    if edge == opportunity["absent_token"]:
        return "absent", None
    return "other", f"unit edge is {edge!r}"


def _provenance(opportunity: Mapping, step) -> str | None:
    """Whether an explicit claim or the residue policy decided the column(s)."""
    if step is None:
        return None
    report = next((r for r in step.assembly_reports if r.concept_id == opportunity["concept_id"]), None)
    if report is None:
        return None
    columns = [c for c in report.columns if c.unit_id == f"cog:{opportunity['unit']}"]
    if opportunity["locus"] != "piece":
        columns = [c for c in columns if None in c.reflexes and opportunity["token"] in c.reflexes]
    if not columns:
        return None
    explicit = [c for c in columns if c.set_id is not None and c.resolved_by != "residue_policy"]
    return "explicit_claim" if explicit else "residue_policy"


def score_decisions(case: Mapping, steps_by_node: Mapping, *, model_committed: Mapping[str, bool] | None = None) -> dict:
    """Read every opportunity from committed steps; gold is read only here."""
    rows = []
    for opportunity in case["opportunities"]:
        step = steps_by_node.get(opportunity["node_id"])
        distribution = None
        if step is not None:
            distribution = next((d for d in step.output_beam.distributions
                                 if d.concept_id == opportunity["concept_id"]), None)
        reading, reason = read_opportunity(opportunity, distribution)
        fallback = bool(step is not None and step.diagnostics.failure_fallback)
        committed = (model_committed or {}).get(opportunity["node_id"], step is not None and not fallback)
        rows.append({
            "opportunity_id": opportunity["opportunity_id"], "concept_id": opportunity["concept_id"],
            "class": opportunity["class"], "basis": opportunity["basis"], "pair": opportunity["pair"],
            "expected": opportunity["expected"], "reading": reading, "reason": reason,
            "correct": reading == opportunity["expected"] if opportunity["class"] == "primary" else None,
            "decided_by": _provenance(opportunity, step), "node_fallback": fallback,
            "model_committed": bool(committed),
        })
    primary = [row for row in rows if row["class"] == "primary"]
    # Correct model decisions exclude fallback output, as task02-v1 excludes it
    # from model hits; the raw reading keeps every row.
    correct = sum(bool(row["correct"]) for row in primary)
    model_correct = sum(bool(row["correct"]) and row["model_committed"] and not row["node_fallback"]
                        for row in primary)
    pairs = {}
    for pair, members in (case.get("matched_pairs") or {}).items():
        items = [next(row for row in rows if row["opportunity_id"] == member) for member in members]
        pairs[pair] = {"members": members, "readings": [item["reading"] for item in items],
                       "both_correct": all(item["correct"] for item in items),
                       "readings_differ": len({item["reading"] for item in items}) > 1}
    scorable = [row for row in primary if row["reading"] in ("retain", "absent")]
    readings = Counter(row["reading"] for row in primary)
    by_basis = {}
    for row in primary:
        group = by_basis.setdefault(row["basis"], {"planned": 0, "correct": 0})
        group["planned"] += 1
        group["correct"] += bool(row["correct"])
    return {
        "decisions_version": DECISIONS_VERSION,
        "primary": {
            "planned_opportunities": len(primary),
            "correct": correct,
            "rate": correct / len(primary) if primary else None,
            "model_committed_correct": model_correct,
            "model_committed_rate": model_correct / len(primary) if primary else None,
            "scorable": len(scorable),
            "readings": dict(sorted(readings.items())),
            "by_basis": by_basis,
            "uniform_reading": next(iter(readings)) if len(readings) == 1 else None,
        },
        "matched_pairs": {
            "pairs": pairs,
            "both_correct": sum(item["both_correct"] for item in pairs.values()),
            "readings_differ": sum(item["readings_differ"] for item in pairs.values()),
            "planned": len(pairs),
        },
        "unresolved": [row for row in rows if row["class"] != "primary"],
        "decided_by": dict(Counter(str(row["decided_by"]) for row in primary)),
        "opportunities": rows,
        "interpretation": (
            "Correct is conditional on the stated parsimony/outgroup assumptions; unresolved "
            "opportunities are descriptive only. Missing, unscorable, unit_missing and other "
            "readings stay in the denominator. The headline is model_committed_correct."
        ),
    }
