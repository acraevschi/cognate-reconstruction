"""Offline task04 count/work measurements; no inference or target witnesses."""
from __future__ import annotations
import argparse
import hashlib
import json
import time
from pathlib import Path
import _bootstrap  # noqa: F401
from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.schemas import LLMToolCall
from cognate_reconstruction.agent.tools import default_tool_registry
from cognate_reconstruction.alignment.units import evidence_map
from cognate_reconstruction.alignment.correspondence_sets import build_correspondence_sets, one_reading_per_node
from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.schemas.inventory import SharedCorrespondenceClaim, CorrespondenceCommitment
from cognate_reconstruction.schemas.traversal import NodeEvidence, EvidenceKind, EvidenceRelation


def measure(path):
    # Load payload through its public schema. Target bindings are never passed to tools.
    from cognate_reconstruction.ingestion import ingest_payload
    from cognate_reconstruction.schemas.evidence import EVIDENCE_CONTRACT_VERSION
    raw = Path(path).read_bytes()
    payload = WorkbenchPayload.model_validate_json(raw)
    family = ingest_payload(payload)
    by_id = {l.variety_id: l for l in payload.lexicons}
    rows = []
    from cognate_reconstruction.tree import parse_newick, postorder_groups, assign_node_ids
    root = parse_newick(family.tree.newick)
    ids = assign_node_ids(root)
    for child_nodes, node in postorder_groups(root):
        children = tuple(ids[id(c)] for c in child_nodes)
        if len(children) < 2 or not all(c in by_id for c in children):
            continue
        lexicons = tuple(by_id[c] for c in children)
        ctx = AgentContext(node_id=ids[id(node)], child_lexicons=lexicons, aligner=LingPyAligner(),
            evidence=tuple(NodeEvidence(node_id=l.variety_id, lexicon=l, kind=EvidenceKind.OBSERVED,
                relation=EvidenceRelation.OUTGROUP) for l in payload.lexicons if l.variety_id not in children))
        old = build_correspondence_sets(ctx.aligner.align_multiple(one_reading_per_node(lexicons)), node_ids=children)
        start = time.perf_counter()
        try:
            reading, work = evidence_map(lexicons, ctx.aligner, cache=ctx.unit_alignment_cache)
            inventory = build_correspondence_sets(reading, node_ids=children)
            result = default_tool_registry().execute(LLMToolCall(call_id='survey', name='summarize_correspondences',
                arguments={'include_outgroup': False}), ctx)
            assert result.ok, result.error
            entry = {'node_id': ids[id(node)], 'legacy_sets': len(old.sets), 'local_sets': len(inventory.sets),
                     'support1': sum(s.support == 1 for s in inventory.sets),
                     'multiconcept': sum(s.concept_count > 1 for s in inventory.sets),
                     'default_matched': result.result['matched_set_count'],
                     'default_page_bytes': len(json.dumps(result.result, ensure_ascii=False).encode()),
                     'full_inventory_bytes': len(inventory.model_dump_json().encode()),
                     'work': work.model_dump(mode='json'), 'seconds': time.perf_counter()-start}
            if hasattr(inventory, 'recurrence_patterns'):
                patterns = inventory.recurrence_patterns
                entry.update(recurrence_patterns=len(patterns), recurrence_support1=sum(s.support == 1 for s in patterns),
                             default_local_matched=sum(s.support >= 2 for s in inventory.sets),
                             recurrence_bytes=len(json.dumps([s.model_dump(mode='json') for s in patterns]).encode()))
                repeated = [s for s in patterns if s.support >= 2]
                members = {sid for p in repeated for sid in p.member_set_ids}
                entry.update(local_sets_bytes=len(json.dumps([s.model_dump(mode='json') for s in inventory.sets],ensure_ascii=False).encode()),
                    default_covered_local_sets=len(members), local_sets_total=len(inventory.sets),
                    default_covered_occurrences=sum(s.occurrence_count for s in inventory.sets if s.set_id in members),
                    total_occurrences=sum(s.occurrence_count for s in inventory.sets),
                    default_concept_count=len({c for s in inventory.sets if s.set_id in members for c in s.example_concept_ids}))
                independent = tuple(CorrespondenceCommitment(set_id=s.set_id, reflexes=s.segments,
                    support=s.support, proto_segment=next(t for t in s.segments if t is not None),
                    confidence=.9,rationale='operator size control') for s in inventory.sets)
                shared = tuple(SharedCorrespondenceClaim(pattern_id=s.set_id, member_set_ids=s.member_set_ids,
                    proto_segment=next(t for t in s.segments if t is not None),confidence=.9,rationale='operator size control') for s in patterns)
                entry.update(individual_claim_bytes=len(json.dumps([c.model_dump(mode='json') for c in independent],ensure_ascii=False).encode()),
                    shared_claim_bytes=len(json.dumps([c.model_dump(mode='json') for c in shared],ensure_ascii=False).encode()),
                    individual_claim_count=len(independent), shared_claim_count=len(shared))
                wide = default_tool_registry().execute(LLMToolCall(call_id='wide',name='summarize_correspondences',arguments={}),ctx)
                entry['outgroup_default'] = ({'page_bytes':len(json.dumps(wide.result,ensure_ascii=False).encode()),
                    'work':wide.result['outgroup_work'], 'profiles':len(wide.result['outgroup_reflexes'])} if wide.ok else {'refused':wide.error.model_dump(mode='json')})
            # Coverage is over every alignment, never the bounded examples.
            from cognate_reconstruction.agent.tools.inventory_evidence import column_bindings
            bindings = {b.column_id:b.set_id for b in column_bindings(reading,children)}
            entry['default_concept_count'] = len({a.concept_id for a in reading.alignments if any(bindings[c.column_id] in members for c in a.evidence_columns)})
            rows.append(entry)
        except ValueError as error:
            rows.append({'node_id': ids[id(node)], 'refused': str(error)})
    return {'version': 'task04-measurement-v1', 'evidence_contract': EVIDENCE_CONTRACT_VERSION,
            'payload': str(path), 'payload_sha256': hashlib.sha256(raw).hexdigest(),
            'concepts': len(payload.concepts), 'live_model_calls': 0, 'nodes': rows,
            'root_note': 'Initial internal child beams do not yet exist; use --banked-inputs for separately labelled retained historical root inputs. This does not estimate an unknown future model beam.'}



def banked_inputs(path):
    from cognate_reconstruction.evaluation.run import trajectory_from_artifact
    from cognate_reconstruction.traversal.beam import beam_to_lexicon
    from cognate_reconstruction.agent.tools.errors import ToolInputError
    rows=[]
    for line in Path(path).read_text().splitlines():
        trajectory=trajectory_from_artifact(json.loads(line))
        if not trajectory.reconstruction_step:
            continue
        lexicons=tuple(beam_to_lexicon(b) for b in trajectory.reconstruction_step.input_beams)
        try:
            reading,work=evidence_map(lexicons,LingPyAligner())
            inventory=build_correspondence_sets(reading)
            rows.append({'node_id':trajectory.node_id, 'concepts':len({a.concept_id for a in reading.alignments}),
                'local_sets':len(inventory.sets),'recurrence_patterns':len(inventory.recurrence_patterns),
                'work':work.model_dump(mode='json')})
        except (ValueError,ToolInputError) as error:
            rows.append({'node_id':trajectory.node_id,'refused':str(error)})
    return {'reading':'historical retained beams under current mechanics; legacy analyses stay unknown, not a prospective candidate arm',
        'path':str(path),'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),'nodes':rows}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payload', type=Path, default=Path('runs/benchmarks/burmish.json'))
    parser.add_argument('--flat-control',action='store_true',help='Explicitly labelled all-leaf cap check, not the native tree')
    parser.add_argument('--banked-inputs',type=Path,help='Measure every retained stored input beam, with no branch narrowing')
    args = parser.parse_args()
    result = measure(args.payload)
    if args.flat_control:
        payload=WorkbenchPayload.model_validate_json(args.payload.read_bytes())
        try:
            reading,work=evidence_map(payload.lexicons,LingPyAligner())
            result['all_leaf_flat_control']={'work':work.model_dump(mode='json'),'concepts':len({a.concept_id for a in reading.alignments})}
        except ValueError as error:
            result['all_leaf_flat_control']={'refused':str(error)}
    if args.banked_inputs:
        result['banked_input_reading'] = banked_inputs(args.banked_inputs)
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
