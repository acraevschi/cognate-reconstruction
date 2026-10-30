"""One bounded, provenance-aware reading for survey and execution.

No reference forms or inferred cognacy enter this module. Every position is
either in a supplied membership or explicitly unknown/structural.
"""

from __future__ import annotations

import math
from functools import lru_cache
from importlib.metadata import version
from collections import defaultdict
from itertools import product

from cognate_reconstruction.schemas.common import MORPHOLOGICAL_BOUNDARY_TOKENS
from cognate_reconstruction.schemas.evidence import (
    AssemblyWork, EvidenceColumn, EvidencePiece, FormAnalysis, PieceSource,
    UnitOrderClaim, digest, EVIDENCE_CONTRACT_VERSION,
)
from cognate_reconstruction.schemas.alignment import (
    AlignmentMember, AlignmentResult, CorrespondenceDetail, MultipleAlignmentMap,
)
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm

MAX_UNIT_TUPLES = 4096
MAX_NODE_TUPLES = 65536
MAX_PROJECTED_COLUMNS = 250000


@lru_cache(maxsize=1)
def lingpy_version():
    return version("lingpy")


def alignment_identity(aligner):
    return [EVIDENCE_CONTRACT_VERSION, type(aligner).__module__, type(aligner).__qualname__,
            getattr(aligner, "method", "sca"), getattr(aligner, "mode", "global"), lingpy_version()]


def unresolved_source(form, reason):
    """Keep ambiguous annotations as provenance on a usable unknown whole unit."""
    return (FormAnalysis(claim="source", notes=(reason,), pieces=(EvidencePiece(
        unit_id="whole:unknown", kind="whole", segment_indices=tuple(range(len(form.segments))),
        sources=tuple(PieceSource(form_id=form.form_id, membership_id=m.membership_id,
            cognate_set_id=m.cognate_set_id, segment_indices=m.segment_indices or tuple(range(len(form.segments))))
                      for m in form.cognate_memberships),
    ),)),)


def source_analyses(form: LexicalForm) -> tuple[FormAnalysis, ...]:
    if form.analysis is not None:
        return (form.analysis,)
    memberships = form.cognate_memberships
    whole = [item for item in memberships if not item.segment_indices]
    if whole:
        if len(whole) != len(memberships):
            return unresolved_source(form, "mixed whole/slice source annotations; whole-form fallback, cognacy unresolved")
        return tuple(FormAnalysis(pieces=(EvidencePiece(
            unit_id="cog:" + item.cognate_set_id, cognate_set_id=item.cognate_set_id,
            kind="whole", segment_indices=tuple(range(len(form.segments))),
            sources=(PieceSource(form_id=form.form_id, membership_id=item.membership_id,
                                 cognate_set_id=item.cognate_set_id,
                                 segment_indices=tuple(range(len(form.segments)))),),
        ),), claim="source") for item in whole)
    # A single full-span slice has the same geometry as a whole membership.
    # Retain its original membership/source identity; do not infer cognacy.
    if (len(memberships) == 1 and memberships[0].segment_indices == tuple(range(len(form.segments)))
            and not any(t in MORPHOLOGICAL_BOUNDARY_TOKENS for t in form.segments)):
        item = memberships[0]
        return (FormAnalysis(claim="source", pieces=(EvidencePiece(
            unit_id="cog:" + item.cognate_set_id, cognate_set_id=item.cognate_set_id,
            kind="whole", segment_indices=item.segment_indices,
            sources=(PieceSource(form_id=form.form_id, membership_id=item.membership_id,
                cognate_set_id=item.cognate_set_id, segment_indices=item.segment_indices),),
        ),)),)
    if not memberships:
        return (FormAnalysis(pieces=(EvidencePiece(
            unit_id="cog:" + form.cognate_set_id if form.cognate_set_id else "whole:unknown",
            cognate_set_id=form.cognate_set_id, kind="whole",
            segment_indices=tuple(range(len(form.segments))),
            sources=(PieceSource(form_id=form.form_id, cognate_set_id=form.cognate_set_id,
                                 segment_indices=tuple(range(len(form.segments)))),),
        ),), claim="source"),)
    labels = {}
    for item in memberships:
        for index in item.segment_indices:
            if form.segments[index] in MORPHOLOGICAL_BOUNDARY_TOKENS:
                continue
            if index in labels:
                return unresolved_source(form, "overlapping source memberships; whole-form fallback, cognacy unresolved")
            labels[index] = item
    pieces = []
    index = 0
    while index < len(form.segments):
        item = labels.get(index)
        end = index + 1
        if item is not None:
            while end < len(form.segments) and labels.get(end) == item:
                end += 1
            unit_id, kind, cognate = "cog:" + item.cognate_set_id, "cognate", item.cognate_set_id
        else:
            kind = "boundary" if form.segments[index] in MORPHOLOGICAL_BOUNDARY_TOKENS else "unknown"
            # Unknown material cannot acquire cognacy from its spelling.
            unit_id, cognate = f"{kind}:{form.form_id}:{index}", None
            if kind == "boundary":
                left = labels.get(index - 1)
                right = labels.get(index + 1)
                if left is not None and right is not None:
                    unit_id = f"boundary:{left.cognate_set_id}:{right.cognate_set_id}:{form.segments[index]}"
        positions = tuple(range(index, end))
        pieces.append(EvidencePiece(unit_id=unit_id, kind=kind, cognate_set_id=cognate,
            segment_indices=positions, sources=(PieceSource(
                form_id=form.form_id, membership_id=item.membership_id if item else None,
                cognate_set_id=cognate, segment_indices=positions),)))
        index = end
    ids = [piece.unit_id for piece in pieces]
    if len(set(ids)) != len(ids):
        return unresolved_source(form, "discontinuous/repeated source unit; whole-form fallback, supply explicit occurrence analysis")
    return (FormAnalysis(pieces=tuple(pieces), claim="source"),)


def semantic_form(form: LexicalForm) -> object:
    return [form.segments, form.analysis.model_dump(mode="json") if form.analysis else None]


def expanded_lexicons(lexicons):
    return tuple(lexicon.model_copy(update={"forms": tuple(
        form.model_copy(update={"analysis": analysis})
        for form in lexicon.forms for analysis in source_analyses(form)
    )}) for lexicon in lexicons)


def _unit_order(forms, explicit: UnitOrderClaim | None):
    units = {piece.unit_id for form in forms for piece in form.analysis.pieces}
    if explicit:
        if not units <= set(explicit.unit_ids):
            raise ValueError(f"unit order for {explicit.concept_id} must include {sorted(units)}")
        # One claim may order the union of alternative analyses. Projection
        # retains every unit present in this tuple, without selecting an analysis.
        return tuple(unit for unit in explicit.unit_ids if unit in units)
    edges = {unit: set() for unit in units}
    first_seen = {}
    for form in forms:
        ids = [piece.unit_id for piece in form.analysis.pieces]
        for unit in ids:
            first_seen.setdefault(unit, len(first_seen))
        for left, right in zip(ids, ids[1:]):
            edges[right].add(left)
    order = []
    while edges:
        ready = [unit for unit, predecessors in edges.items() if not predecessors]
        if not ready:
            raise ValueError(f"conflicting unit orders in concept {forms[0].concept_id}; "
                             f"supply unit_orders with these unit_ids and rationale: {sorted(units)}")
        # Disconnected material is kept in child/source order; this is an
        # unresolved serialization order, never evidence of ancestral order.
        unit = min(ready, key=first_seen.get)
        order.append(unit)
        del edges[unit]
        for predecessors in edges.values():
            predecessors.discard(unit)
    return tuple(order)


def align_tuple(forms, child_ids, aligner, *, unit_order=None, overrides=(),
                overlay_ids=(None, None), cache=None, counters=None):
    """All columns of a tuple, preserving each unit and each source position."""
    cache = {} if cache is None else cache
    key = digest([alignment_identity(aligner), forms[0].concept_id, child_ids, [semantic_form(form) for form in forms],
                  unit_order.model_dump(mode="json") if unit_order else None,
                  [item.model_dump(mode="json") for item in overrides], overlay_ids])
    if key in cache:
        if counters is not None: counters["cache_hits"] += 1
        return cache[key]
    # Conservative whole-form fallback for unknown annotations; it makes no
    # cognacy assertion, even if one of the other whole forms is annotated.
    mixed_whole = all(len(form.analysis.pieces) == 1 and form.analysis.pieces[0].kind == "whole"
                      for form in forms)
    unknown_whole = mixed_whole and any(form.analysis.pieces[0].cognate_set_id is None for form in forms)
    entries = defaultdict(dict)
    for form in forms:
        for piece in form.analysis.pieces:
            unit = "whole:unknown" if unknown_whole else piece.unit_id
            entries[unit][form.variety_id] = (form, piece)
    order = ("whole:unknown",) if unknown_whole else _unit_order(forms, unit_order)
    flat = {child: [] for child in child_ids}
    columns = []
    for unit in order:
        present = entries[unit]
        if len({piece.cognate_set_id for _, piece in present.values()}) > 1 and unit != "whole:unknown":
            raise ValueError(f"unit {unit!r} carries conflicting cognate claims in concept {forms[0].concept_id}; "
                             "supply a consistent explicit analysis_claim or keep separate unknown units")
        scope = unit  # Occurrence/cognacy scope never stands for phonological recurrence.
        selected_override = next((item for item in overrides if item.concept_id == forms[0].concept_id
                                  and (item.unit_id == unit or (item.unit_id is None and len(order) == 1))
                                  and (not item.analysis_ids or all(
                                      item.analysis_ids[child_ids.index(child)] == digest(form.analysis.model_dump(mode="json"))
                                      for child, (form, _) in present.items()))
                                  and all(tuple(t for t in item.rows[child_ids.index(child)] if t is not None)
                                          == tuple(form.segments[i] for i in piece.segment_indices)
                                          for child, (form, piece) in present.items())), None)
        tokens = {child: tuple(form.segments[i] for i in piece.segment_indices)
                  for child, (form, piece) in present.items()}
        if selected_override:
            rows = dict(zip(child_ids, selected_override.rows, strict=True))
            if any(tuple(t for t in rows[child] if t is not None) != tokens.get(child, ()) for child in child_ids):
                raise ValueError("realignment no longer matches this candidate analysis; realign the exact unit again")
        elif len(present) == 1:
            rows = tokens
        else:
            lexicons = tuple(LanguageLexicon(variety_id=child, name=child, forms=(LexicalForm(
                form_id=form.form_id, variety_id=child, concept_id=form.concept_id, segments=tokens[child],
            ),)) for child, (form, _) in present.items())
            result = aligner.align_multiple(lexicons, (), respect_cognate_sets=False,
                                           correspondence_detail=CorrespondenceDetail.SUMMARY)
            if counters is not None: counters["alignment_calls"] += 1
            rows = {member.variety_id: member.aligned_segments for alignment in result.alignments
                    for member in alignment.members if not member.is_anchor}
        width = max(map(len, rows.values()), default=0)
        indices = {child: iter(piece.segment_indices) for child, (_, piece) in present.items()}
        for column in range(width):
            sources = []
            for child in child_ids:
                token = rows.get(child, (None,) * width)[column]
                flat[child].append(token)
                if token is not None:
                    form, piece = present[child]
                    position = next(indices[child])
                    sources.append(PieceSource(form_id=form.form_id, cognate_set_id=piece.cognate_set_id,
                                               membership_id=next((source.membership_id for source in piece.sources if source.form_id == form.form_id), None),
                                               segment_indices=(position,)))
            columns.append(EvidenceColumn(column_id="col-" + digest([key, unit, column]),
                                          unit_id=unit, scope_id=scope,
                                          etymon_id=next((p.cognate_set_id for _, p in present.values()), None) if not unknown_whole else None,
                                          kind=next(iter(present.values()))[1].kind, sources=tuple(sources)))
    # A whole-word override on several units cannot silently erase their labels.
    if any(item.unit_id is None for item in overrides) and len(order) > 1:
        raise ValueError("partial evidence requires realign.unit_id; survey/preview names each unit")
    result = AlignmentResult(alignment_id="unit-" + key, concept_id=forms[0].concept_id,
        members=tuple(AlignmentMember(form_id=next((f.form_id for f in forms if f.variety_id == child),
                                                   "missing:" + child), variety_id=child,
                     concept_id=forms[0].concept_id, analysis_id=next((digest(f.analysis.model_dump(mode="json")) for f in forms if f.variety_id == child), None), aligned_segments=tuple(flat[child])) for child in child_ids),
        evidence_columns=tuple(columns), method=getattr(aligner, "method", "sca"), mode=getattr(aligner, "mode", "global"))
    cache[key] = result
    return result


def evidence_map(lexicons, aligner, *, unit_orders=(), overrides=(), overlay_ids=(None, None),
                 max_tuples=MAX_UNIT_TUPLES, cache=None):
    # Source histories with the same unit claims merge in beams. Apply that
    # same canonicalization before surveying, retaining their merged sources.
    from cognate_reconstruction.traversal.beam import make_leaf_beam, beam_to_lexicon
    lexicons = tuple(beam_to_lexicon(make_leaf_beam(lexicon,
        beam_width=max(1, sum(len(source_analyses(form)) for form in lexicon.forms)))) for lexicon in lexicons)
    lexicons = expanded_lexicons(lexicons)
    child_ids = tuple(lexicon.variety_id for lexicon in lexicons)
    by_concept = defaultdict(lambda: defaultdict(list))
    for lexicon in lexicons:
        for form in lexicon.forms:
            by_concept[form.concept_id][lexicon.variety_id].append(form)
    total = 0
    projected = 0
    for concept, children in by_concept.items():
        if len(children) < 2:
            continue
        count = math.prod(len(forms) for forms in children.values())
        if count > max_tuples:
            raise ValueError(f"concept {concept} requires {count} candidate-analysis tuples; limit {max_tuples}. Reduce the input beam explicitly or select forms with get_alignments; no analysis was discarded")
        total += count
        projected += count * sum(max(len(form.segments) for form in forms) for forms in children.values())
    if total > MAX_NODE_TUPLES or projected > MAX_PROJECTED_COLUMNS:
        raise ValueError(f"node requires {total} tuples and at most {projected} columns; limits {MAX_NODE_TUPLES}/{MAX_PROJECTED_COLUMNS}; no analysis was discarded")
    if len({claim.concept_id for claim in unit_orders}) != len(unit_orders):
        raise ValueError("unit_orders may name each concept only once")
    orders = {claim.concept_id: claim for claim in unit_orders}
    # Every claim enters the evidence revision, so one naming no concept here
    # would change every set identifier without changing any column. A claim
    # for a present concept must already list all its units (_unit_order).
    if unknown := sorted({claim.concept_id for claim in unit_orders} - set(by_concept)):
        raise ValueError(f"unit_orders names {unknown}, which have no form here; concept_ids are "
                         f"{sorted(by_concept)}. Omit unit_orders unless a concept's units conflict in order")
    counters = {"projected_columns": projected, "candidate_tuples": 0, "alignment_calls": 0, "cache_hits": 0}
    alignments = []
    cache = {} if cache is None else cache
    for concept, children in sorted(by_concept.items()):
        if len(children) < 2:
            continue
        choices = [children[child] for child in child_ids if child in children]
        count = math.prod(map(len, choices))
        if count > max_tuples:
            raise ValueError(f"concept {concept} requires {count} candidate-analysis tuples; limit {max_tuples}. "
                             "Reduce the input beam explicitly or raise the offline limit; no analysis was discarded")
        for forms in product(*choices):
            counters["candidate_tuples"] += 1
            alignments.append(align_tuple(forms, child_ids, aligner, unit_order=orders.get(concept),
                overrides=tuple(item for item in overrides if item.concept_id == concept),
                overlay_ids=overlay_ids, cache=cache, counters=counters))
    revision = digest([alignment_identity(aligner), child_ids, [(l.variety_id, sorted([(f.concept_id, semantic_form(f)) for f in l.forms], key=digest)) for l in lexicons],
                       overlay_ids, [c.model_dump(mode="json") for c in unit_orders],
                       [o.model_dump(mode="json") for o in overrides]])
    return MultipleAlignmentMap(variety_ids=child_ids, alignments=tuple(alignments),
                                pairwise_correspondences=(), detail=CorrespondenceDetail.SUMMARY,
                                evidence_revision=revision), AssemblyWork(**counters)
