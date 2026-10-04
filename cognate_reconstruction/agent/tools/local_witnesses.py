"""Retrieve outgroup tokens for exact approved child columns, without gold.

Outgroups are compared separately; their alternatives are never multiplied into
one joint Cartesian product. A combined alignment must preserve the child token
positions of the approved local column before it can provide a witness.
"""
from collections import defaultdict

from cognate_reconstruction.agent.schemas import LocalOutgroupWitness
from cognate_reconstruction.agent.tools.errors import ToolInputError
from cognate_reconstruction.alignment.units import source_analyses, MAX_NODE_TUPLES, MAX_PROJECTED_COLUMNS
from cognate_reconstruction.schemas.alignment import CorrespondenceDetail
from cognate_reconstruction.schemas.evidence import PieceSource
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm


def local_witnesses(context, reading, outside, *, segmentation_overlay_id=None, column_ids=None, absence_observations=None):
    jobs = []
    projected = 0
    outside_forms = {
        item.node_id: [(form, analysis) for form in context.evidence_lexicon(item.node_id, segmentation_overlay_id).forms
                       for analysis in source_analyses(form)] for item in outside
    }
    for alignment in reading.alignments:
        rows = {m.variety_id: m.aligned_segments for m in alignment.members}
        units = defaultdict(list)
        for index, col in enumerate(alignment.evidence_columns):
            units[col.unit_id].append(index)
        for unit, indices in units.items():
            if column_ids is not None and not any(alignment.evidence_columns[i].column_id in column_ids for i in indices):
                continue
            local = alignment.evidence_columns[indices[0]]
            tokens = {node: tuple(rows[node][i] for i in indices if rows[node][i] is not None) for node in reading.variety_ids}
            active = tuple(LanguageLexicon(variety_id=node, name=node, forms=(LexicalForm(
                form_id=next(m.form_id for m in alignment.members if m.variety_id == node),
                variety_id=node, concept_id=alignment.concept_id, segments=values),))
                for node, values in tokens.items() if values)
            # A single unknown whole unit may be compared with an unknown whole
            # outgroup form. Known or partial units require a supplied matching ID.
            unknown_whole = len(units) == 1 and local.kind == 'whole' and local.etymon_id is None
            for item in outside:
                for form, analysis in outside_forms[item.node_id]:
                    if form.concept_id != alignment.concept_id:
                        continue
                    pieces = [p for p in analysis.pieces if p.unit_id == unit]
                    if not pieces and unknown_whole and len(analysis.pieces) == 1 and analysis.pieces[0].kind == 'whole':
                        pieces = list(analysis.pieces)
                    if not pieces:
                        continue
                    piece = pieces[0]
                    if local.etymon_id is not None and piece.cognate_set_id != local.etymon_id:
                        continue
                    out_tokens = tuple(form.segments[i] for i in piece.segment_indices)
                    projected += sum(len(v) for v in tokens.values()) + len(out_tokens)
                    jobs.append((alignment, indices, tokens, active, item.node_id, form, piece, out_tokens))
                    if len(jobs) > MAX_NODE_TUPLES or projected > MAX_PROJECTED_COLUMNS:
                        raise ToolInputError(f"outgroup comparison requires at least {len(jobs)} unit/form pairs and {projected} projected columns; limits {MAX_NODE_TUPLES}/{MAX_PROJECTED_COLUMNS}; no alignment run or alternatives discarded", code='alignment-failed')
    if len(jobs) > MAX_NODE_TUPLES or projected > MAX_PROJECTED_COLUMNS:
        raise ToolInputError(f"outgroup comparison requires {len(jobs)} unit/form pairs and at most {projected} columns; limits {MAX_NODE_TUPLES}/{MAX_PROJECTED_COLUMNS}; no witness alternatives discarded",
            code='alignment-failed')
    found = {}
    cache = {}
    for alignment, indices, tokens, active, outside_id, form, piece, out_tokens in jobs:
        # No operation changes the child evidence reading or column IDs.
        key = (tuple(tokens.items()), outside_id, out_tokens)
        if key not in cache:
            out = LanguageLexicon(variety_id=outside_id, name=outside_id, forms=(LexicalForm(
                form_id=form.form_id, variety_id=outside_id, concept_id=alignment.concept_id, segments=out_tokens),))
            combined = context.aligner.align_multiple((*active, out), respect_cognate_sets=False,
                correspondence_detail=CorrespondenceDetail.SUMMARY)
            cache[key] = tuple({m.variety_id: m.aligned_segments for m in a.members} for a in combined.alignments)
        # Position signatures include gaps: token equality without positions is
        # insufficient when one piece contains a repeated segment.
        old_rows = {m.variety_id: m.aligned_segments for m in alignment.members}
        wanted = {}
        counters = {node: 0 for node in reading.variety_ids}
        for index in indices:
            sig = []
            for node in reading.variety_ids:
                token = old_rows[node][index]
                sig.append((token, counters[node] if token is not None else None))
                counters[node] += token is not None
            wanted[tuple(sig)] = alignment.evidence_columns[index]
        for rows in cache[key]:
            counters = {node: 0 for node in reading.variety_ids}
            out_offset = 0
            for column in range(len(rows[outside_id])):
                sig = []
                for node in reading.variety_ids:
                    token = rows.get(node, (None,) * len(rows[outside_id]))[column]
                    sig.append((token, counters[node] if token is not None else None))
                    counters[node] += token is not None
                out_token = rows[outside_id][column]
                out_position = piece.segment_indices[out_offset] if out_token is not None else None
                out_offset += out_token is not None
                local = wanted.get(tuple(sig))
                if local is None or (column_ids is not None and local.column_id not in column_ids):
                    continue
                if out_token is None:
                    if absence_observations is not None:
                        absence_observations[(local.column_id, outside_id, form.form_id, piece.unit_id)] = (alignment.concept_id, outside_id)
                    continue
                source = PieceSource(form_id=form.form_id, membership_id=next((s.membership_id for s in piece.sources if s.form_id == form.form_id), None),
                    cognate_set_id=piece.cognate_set_id, segment_indices=(out_position,))
                witness = LocalOutgroupWitness(concept_id=alignment.concept_id, unit_id=local.unit_id,
                    evidence_column_id=local.column_id, node_id=outside_id, segment=out_token,
                    source_positions=(*local.sources, source))
                found[(local.column_id, outside_id, source)] = witness
    return tuple(found.values()), {'unit_form_pairs': len(jobs), 'projected_columns': projected, 'alignment_calls': len(cache)}
