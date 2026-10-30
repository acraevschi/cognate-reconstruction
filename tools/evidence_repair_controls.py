"""Scripted two-level morphology controls through tools, JSONL and normal evaluator.

All hypotheses below are operator controls based on supplied observed units.
They are not model decisions or estimates of reconstruction quality.
"""
from __future__ import annotations
import json
from pathlib import Path
try:
    import _bootstrap  # noqa: F401
except ModuleNotFoundError:
    from tools import _bootstrap  # noqa: F401
from cognate_reconstruction.agent.orchestrator import AgentOrchestrator
from cognate_reconstruction.agent.reconstructor import AgenticNodeReconstructor
from cognate_reconstruction.agent.schemas import LLMMessage, LLMToolCall, MessageRole
from cognate_reconstruction.agent.service import ReconstructionService
from cognate_reconstruction.agent.trajectory import JsonlTrajectorySink
from cognate_reconstruction.alignment.units import source_analyses
from cognate_reconstruction.evaluation.run import evaluate_run, trajectory_from_artifact
from cognate_reconstruction.ingestion import ingest_payload
from cognate_reconstruction.synthesis.diagnostics import build_case, load_suite


def observed_plan(payload, mode):
    orders = []
    selected = {}
    for first in next(l for l in payload.lexicons if l.variety_id == 'a').forms:
        concept = first.concept_id
        source = source_analyses(first)[0].pieces
        core, boundary, second = [p.unit_id for p in source[:3]]
        units = {p.unit_id for l in payload.lexicons for f in l.forms if f.concept_id == concept
                 for a in source_analyses(f) for p in a.pieces}
        prefix = [second, boundary, core] if mode == 'reordered' else [core, boundary, second]
        orders.append({'concept_id':concept, 'unit_ids':prefix+sorted(units-set(prefix)),
                       'rationale':'scripted source-A ordering claim; ancestral order is underdetermined'})
        selected[concept] = (core, second, boundary, source[3].unit_id, source[4].unit_id)
    return orders, selected


class MorphologyProvider:
    model = 'scripted/task04-morphology'

    def __init__(self, payload, mode):
        self.orders, self.selected = observed_plan(payload, mode)
        self.mode = mode

    def complete(self, messages, tools, **kwargs):
        prompt = messages[1].content
        node = json.loads(prompt[prompt.index('{'):])['node_id']
        calls = [m for m in messages if m.role is MessageRole.TOOL]
        if not calls:
            name = 'summarize_correspondences'
            args = {'reading':'local', 'min_support':1, 'limit':200, 'include_outgroup':False,
                    'unit_orders':self.orders}
        else:
            for msg in calls:
                outcome = json.loads(msg.content)
                if not outcome['ok']:
                    raise AssertionError(outcome)
            survey = json.loads(next(m.content for m in calls if m.name == 'summarize_correspondences'))['result']
            commitments = []
            # Values are chosen from observed pieces, not from target forms.
            for item in survey['sets']:
                concept = item['example_concept_ids'][0]
                core, second, boundary, extra_boundary, extra = self.selected[concept]
                keep = item['scope_id'] in {core, second, boundary}
                if self.mode == 'missing' and item['scope_id'] == second:
                    keep = False
                if self.mode == 'extra' and item['scope_id'] in {extra, extra_boundary}:
                    keep = True
                value = next((s for s in item['segments'] if s is not None), None) if keep else None
                if self.mode == 'wrong' and item['scope_id'] == core:
                    value = 's'
                commitments.append({'set_id':item['set_id'], 'reflexes':item['segments'],
                    'support':item['support'], 'proto_segment':value, 'confidence':.9,
                    'rationale':'scripted source-unit control',
                    'directionality_rationale':'explicit control hypothesis; historical polarity not identified'})
            args = {'commitments':commitments, 'residue_policy':'drop', 'unit_orders':self.orders}
            if not any(m.name == 'test_proto_assembly' for m in calls):
                name = 'test_proto_assembly'
            else:
                name = 'commit_reconstruction'
                args = {'node_id':node, 'inventory':{'child_node_ids':survey['node_ids'], **args},
                        'anomalies':[], 'summary':'Scripted morphology control, '+self.mode}
        return LLMMessage(role=MessageRole.ASSISTANT, tool_calls=(LLMToolCall(call_id=node+':'+name, name=name, arguments=args),))


def run_controls(output_dir):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    suite = load_suite(Path(__file__).resolve().parents[1] / 'benchmarks/diagnostic/synthetic-diagnostic-suite-v1.json')
    built = build_case(next(c for c in suite['cases'] if c['case_id']=='morphology'))
    # Additional two-level traversal is an explicitly labelled scripted fixture.
    payload = built.payload.model_copy(update={'newick':'((a,b)x,c)p;'})
    rows = []
    for mode in ('correct', 'wrong', 'extra', 'missing', 'reordered'):
        sink = out / (mode+'.jsonl')
        service = ReconstructionService(AgenticNodeReconstructor(AgentOrchestrator(
            MorphologyProvider(payload, mode), trajectory_sink=JsonlTrajectorySink(sink),
            instructions='Offline scripted control; approve explicitly observed units.',
            run_id='task04-'+mode, configuration_sha256='scripted-'+mode)))
        result = service.reconstruct_family(ingest_payload(payload))
        raw = json.loads(result.model_dump_json(exclude_computed_fields=True))
        trajectories = tuple(trajectory_from_artifact(json.loads(line)) for line in sink.read_text().splitlines())
        report = evaluate_run(payload, raw, trajectories)
        assert all(t.completed for t in trajectories)
        root = report.targets[0].evaluation
        intermediate = next(s for s in result.snapshot.steps if s.parent_node_id == 'x')
        rows.append({'mode':mode, 'raw_exact':root.top_exact_matches,
            'raw_ned':root.graded.top_normalized_edit_distance.mean,
            'validated_planned':report.validated_target_summary.planned_concepts,
            'completed_nodes':[t.node_id for t in trajectories],
            'intermediate_units':[[p.unit_id for p in d.candidates[0].analysis.pieces] for d in intermediate.output_beam.distributions],
            'concepts':[{'concept_id':c.concept_id, 'top':c.top_candidate_segments,
                         'diagnostics':c.token_diagnostics.model_dump(mode='json')} for c in root.concepts]})
    return {'version':'task04-controls-v1', 'evidence_contract':'units-v2', 'evaluator':'task02-v1',
            'unit_evaluator':'task04-units-v1', 'live_model_calls':0,
            'interpretation':'operator-selected scripted controls; no historical/model-quality claim', 'controls':rows}

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run_controls(args.output_dir), indent=2))
