"""Licensed token diagnostics and explicitly identified cognate-piece comparison.

No phonetic mapping, learned normalizer, substring matching or inferred cognacy.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from collections import Counter

from cognate_reconstruction.evaluation.metrics import compare_to_nearest
from cognate_reconstruction.schemas.historical import TokenEvaluationDiagnostics

SUPERSCRIPTS = frozenset("⁰¹²³⁴⁵⁶⁷⁸⁹")
BOUNDARIES = frozenset({"+", "-"})


def tone_token(token: str) -> bool:
    return bool(token) and set(token) <= SUPERSCRIPTS


def partition(tokens: Sequence[str]):
    return (
        tuple(token for token in tokens if not tone_token(token)),
        tuple(token for token in tokens if tone_token(token)),
    )


def pieces(tokens: Sequence[str]) -> tuple[tuple[str, ...], ...]:
    output: list[list[str]] = [[]]
    for token in tokens:
        if token in BOUNDARIES:
            output.append([])
        else:
            output[-1].append(token)
    return tuple(tuple(part) for part in output)


def token_diagnostics(candidate, alternatives, *, unresolved_scope=False):
    target_pieces = tuple(pieces(target) for target in alternatives)
    target_tones = tuple(partition(target)[1] for target in alternatives)
    status = "superscript_token_partition_only"
    tone_status = "token_comparison_only_no_category_mapping"
    segment_exact = segment_ned = tone_exact = None
    predicted_tones = predicted_pieces = None
    if candidate is None:
        status = tone_status = "missing_output"
    else:
        predicted_pieces = pieces(candidate)
        segment_tokens, predicted_tones = partition(candidate)
        # Keep attached digits and source slash notation visible; never strip them.
        ambiguous = any(
            (set(token) & SUPERSCRIPTS and not tone_token(token))
            or any(ch.isdecimal() for ch in token) and not tone_token(token)
            or "/" in token
            for tokens in (candidate, *alternatives) for token in tokens
        )
        if ambiguous:
            status = tone_status = "ambiguous_notation_unscored"
        elif not segment_tokens or any(not partition(t)[0] for t in alternatives):
            status = "missing_segment_analysis_unscored"
        else:
            comparison = compare_to_nearest(
                segment_tokens, [partition(target)[0] for target in alternatives]
            )
            segment_exact = comparison.exact
            segment_ned = comparison.normalized_edit_distance
            if not predicted_tones and not any(target_tones):
                tone_status = "both_unmarked"
            else:
                tone_exact = predicted_tones in target_tones
                if not predicted_tones or any(not t for t in target_tones):
                    tone_status = "one_side_or_alternative_unmarked"
    morphology_status = (
        "unresolved_lexical_scope" if unresolved_scope else
        "missing_output" if candidate is None else
        "boundary_only_output_memberships_unknown" if
        any(t in BOUNDARIES for tokens in (candidate, *alternatives) for t in tokens)
        else "unanalyzed_output_memberships_unknown"
    )
    return TokenEvaluationDiagnostics(
        analysis_status=status, segment_only_exact=segment_exact,
        segment_only_ned=segment_ned, predicted_tone_tokens=predicted_tones,
        target_tone_alternatives=target_tones, tone_status=tone_status,
        tone_token_exact=tone_exact, morphology_status=morphology_status,
        predicted_pieces=predicted_pieces, target_piece_alternatives=target_pieces,
    )


def compare_cognate_units(
    predicted: Sequence[tuple[str, Sequence[str]]] | None,
    target: Sequence[tuple[str, Sequence[str]]] | None,
) -> Mapping[str, object]:
    """Compare complete explicitly named units, never infer IDs from token equality.

    IDs must be independent analyses. Duplicate IDs are ambiguous (e.g. repeated
    morphemes with unspecified occurrences). Whole-word order stays a separate
    diagnostic; extra predicted units cannot be hidden by high target-unit recall.
    """
    if predicted is None or target is None:
        return {"status": "missing_analysis", "unit_exact_rate": None}
    if (len({key for key, _ in predicted}) != len(predicted)
            or len({key for key, _ in target}) != len(target)
            or not target or any(not tokens for _, tokens in (*predicted, *target))):
        return {"status": "ambiguous_analysis", "unit_exact_rate": None}
    p = {key: tuple(tokens) for key, tokens in predicted}
    t = {key: tuple(tokens) for key, tokens in target}
    hits = sorted(key for key, tokens in t.items() if p.get(key) == tokens)
    shared_order_p = [key for key, _ in predicted if key in t]
    shared_order_t = [key for key, _ in target if key in p]
    return {
        "status": "explicit_units", "target_units": len(t), "exact_unit_ids": hits,
        "unit_exact_rate": len(hits) / len(t), "missing_unit_ids": sorted(t.keys() - p.keys()),
        "extra_unit_ids": sorted(p.keys() - t.keys()),
        "shared_units_reordered": shared_order_p != shared_order_t,
        "whole_analysis_exact": ([(key, tuple(tokens)) for key, tokens in predicted]
                                 == [(key, tuple(tokens)) for key, tokens in target]),
    }


def annotated_units(form):
    """Read complete explicit pieces; refuse incomplete or inferred membership."""
    if form is None:
        return None
    if form.analysis is not None:
        selected = [piece for piece in form.analysis.pieces if piece.kind != "boundary"]
        if not selected or any(piece.cognate_set_id is None for piece in selected):
            return None
        return [(piece.cognate_set_id, tuple(form.segments[i] for i in piece.segment_indices))
                for piece in selected]
    memberships = getattr(form, "cognate_memberships", ())
    if not memberships:
        return None
    positions = [i for m in memberships for i in m.segment_indices]
    if sorted(positions) != [i for i, token in enumerate(form.segments) if token not in BOUNDARIES]:
        return None
    return [(m.cognate_set_id, tuple(form.segments[i] for i in m.segment_indices)) for m in memberships]


def with_unit_diagnostics(diagnostics, top, targets):
    # OLD MAN's scope remains unresolved even if source piece IDs are present.
    if diagnostics.morphology_status == "unresolved_lexical_scope":
        return diagnostics
    predicted = annotated_units(top)
    if predicted is None:
        return diagnostics
    comparisons = tuple(dict(compare_cognate_units(predicted, annotated_units(target))) for target in targets)
    scored = [c for c in comparisons if c["status"] == "explicit_units"]
    return diagnostics.model_copy(update={
        "unit_evaluator_version": "task04-units-v1",
        "morphology_status": "explicit_output_units_target_unknown" if not scored else "explicit_cognate_units",
        "cognate_unit_comparisons": comparisons,
        "cognate_unit_exact": (any(c["unit_exact_rate"] == 1 and not c["extra_unit_ids"] for c in scored)
                               if scored else None),
    })


def diagnostic_text(evaluation) -> str:
    """Compact report with measured denominators and unknown analyses visible."""
    recorded = [c.token_diagnostics for c in evaluation.concepts if c.token_diagnostics]
    if not recorded:
        return "token diagnostics not measured"
    segments = [d for d in recorded if d.segment_only_exact is not None]
    tones = [d for d in recorded if d.tone_token_exact is not None]
    statuses = dict(sorted(Counter(d.analysis_status for d in recorded).items()))
    morphology = dict(sorted(Counter(d.morphology_status for d in recorded).items()))
    return (
        f"task01-v1 token partition: segment-only exact "
        f"{sum(d.segment_only_exact for d in segments)}/{len(segments)} measured; "
        f"tone-token exact {sum(d.tone_token_exact for d in tones)}/{len(tones)} measured "
        f"(no category mapping); analysis {statuses}; morphology {morphology}; "
        f"{len(evaluation.concepts)-len(recorded)} concepts without diagnostics"
    )
