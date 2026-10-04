"""Offline task04 counterexamples, before and after evidence repairs."""
from pathlib import Path

from cognate_reconstruction.agent.tools.inventory_evidence import node_inventory
from cognate_reconstruction.evaluation.diagnostics import annotated_units
from cognate_reconstruction.schemas.inventory import CorrespondenceCommitment, ProtoInventorySpec, ResiduePolicy
from cognate_reconstruction.schemas.traversal import NodeEvidence, EvidenceKind, EvidenceRelation
from cognate_reconstruction.synthesis.diagnostics import build_case, load_suite
from tests.workbench.test_evidence_contract import form, lex, context, call, preview


def test_unrelated_alternative_does_not_add_independent_core_support():
    a = lex('A', form('A', ('p', 'k'), (('core', (0,)), ('extra', (1,)))))
    b = form('B', ('p', 't'), (('core', (0,)), ('extra', (1,))))
    alternative = form('B', ('p', 's'), (('core', (0,)), ('extra', (1,))), suffix='alt')
    counts = []
    for forms in ((b,), (b, alternative)):
        inventory, _ = node_inventory(context(a, lex('B', *forms)), segmentation_overlay_id=None, alignment_overlay_id=None)
        counts.append(next(s.support for s in inventory.sets if s.scope_id == 'core'))
    assert counts == [1, 1]


def test_repeated_identical_retention_commits_without_merger_story():
    ctx = context(*(lex(child, *(form(child, ('p',), ((concept, (0,)),), concept=concept)
                               for concept in ('one', 'two'))) for child in ('A', 'B')))
    inventory, _ = node_inventory(ctx, segmentation_overlay_id=None, alignment_overlay_id=None)
    spec = ProtoInventorySpec(child_node_ids=ctx.child_ids, commitments=tuple(
        CorrespondenceCommitment(set_id=s.set_id, reflexes=s.segments, proto_segment='p',
            support=s.support, confidence=.9, rationale='retention in independent etyma') for s in inventory.sets), residue_policy=ResiduePolicy.DROP)
    assert preview(ctx, spec).ok
    result = call(ctx, 'commit_reconstruction', 'commit', node_id=ctx.node_id,
                  inventory=spec.model_dump(mode='json'), anomalies=[], summary='Retain p.')
    assert result.ok, result.error


def scoped_outgroup_context():
    ctx = context(*(lex(child, *(form(child, (token,), ((concept, (0,)),), concept=concept)
                               for concept in ('one', 'two'))) for child, token in (('A', 'p'), ('B', 'f'))))
    out = lex('O', form('O', ('p',), (('one', (0,)),), concept='one'),
                   form('O', ('t',), (('two', (0,)),), concept='two'))
    ctx.evidence = (NodeEvidence(node_id='O', lexicon=out, kind=EvidenceKind.OBSERVED,
                                relation=EvidenceRelation.OUTGROUP),)
    return ctx


def test_local_outgroup_profiles_never_mix_etyma():
    ctx = scoped_outgroup_context()
    result = call(ctx, 'summarize_correspondences', 'survey', min_support=1, reading='local')
    assert result.ok, result.error
    scopes = {s['set_id']: s['scope_id'] for s in result.result['sets']}
    found = {scopes[p['set_id']]: {r['segment'] for r in p['reflexes']}
             for p in result.result['outgroup_reflexes']}
    assert found == {'one': {'p'}, 'two': {'t'}}


def test_generated_morphology_targets_have_scorer_only_units():
    suite = load_suite(Path(__file__).resolve().parents[2] / 'benchmarks/diagnostic/task02-v1.json')
    built = build_case(next(c for c in suite['cases'] if c['case_id'] == 'morphology'))
    assert all(annotated_units(f) is not None for b in built.payload.historical_form_bindings for f in b.forms)


def test_descriptive_recurrence_requires_explicit_member_selection_and_keeps_exception():
    from cognate_reconstruction.schemas.inventory import SharedCorrespondenceClaim
    from cognate_reconstruction.agent.tools.proto_assembly import assemble_node
    ctx = context(*(lex(child, *(form(child, ('p',), ((c, (0,)),), concept=c)
                  for c in ('one', 'two', 'three'))) for child in ('A', 'B')))
    inventory, _ = node_inventory(ctx, segmentation_overlay_id=None, alignment_overlay_id=None)
    pattern = inventory.recurrence_patterns[0]
    assert pattern.support == pattern.etymon_count == pattern.concept_count == 3
    assert len(pattern.member_set_ids) == 3 and len(inventory.sets) == 3
    shared = SharedCorrespondenceClaim(pattern_id=pattern.set_id,
        member_set_ids=pattern.member_set_ids[:2], proto_segment='p', confidence=.9,
        rationale='explicit shared retention over selected local occurrences')
    exception = next(s for s in inventory.sets if s.set_id == pattern.member_set_ids[2])
    local = CorrespondenceCommitment(set_id=exception.set_id, reflexes=exception.segments,
        support=exception.support, proto_segment='t', confidence=.7, rationale='local competing hypothesis')
    spec = ProtoInventorySpec(child_node_ids=ctx.child_ids, commitments=(local,), shared_claims=(shared,), residue_policy=ResiduePolicy.DROP)
    assert preview(ctx, spec).ok
    step, committed = assemble_node(ctx, spec, node_id=ctx.node_id, segmentation_overlay_id=None)
    assert {c.segments for d in step.output_beam.distributions for c in d.candidates} == {('p',), ('t',)}
    assert committed.approved_shared_claims == (shared,)
    assert len(committed.request.commitments) == 3 and committed.request.shared_claims == ()
    from cognate_reconstruction.schemas.inventory import CommittedProtoInventory
    assert CommittedProtoInventory.model_validate_json(committed.model_dump_json()) == committed
    assert call(ctx, 'commit_reconstruction', 'shared-commit', node_id=ctx.node_id,
        inventory=spec.model_dump(mode='json'), anomalies=[], summary='explicit group and exception').ok
    changed = spec.model_copy(update={'shared_claims': (shared.model_copy(update={'member_set_ids': pattern.member_set_ids}),)})
    assert not call(ctx, 'commit_reconstruction', 'stale-selection', node_id=ctx.node_id,
        inventory=changed.model_dump(mode='json'), anomalies=[], summary='changed collection').ok
    unrelated = shared.model_copy(update={'member_set_ids': ('nonmember',)})
    assert not preview(ctx, spec.model_copy(update={'shared_claims': (unrelated,)}), cid='nonmember').ok


def test_pattern_id_alone_cannot_be_committed_as_a_local_set():
    ctx = scoped_outgroup_context()
    inventory, _ = node_inventory(ctx, segmentation_overlay_id=None, alignment_overlay_id=None)
    pattern = inventory.recurrence_patterns[0]
    commitment = CorrespondenceCommitment(set_id=pattern.set_id, reflexes=pattern.segments,
        support=pattern.support, proto_segment='p', confidence=.9)
    spec = ProtoInventorySpec(child_node_ids=ctx.child_ids, commitments=(commitment,), residue_policy=ResiduePolicy.DROP)
    rejected = preview(ctx, spec)
    assert not rejected.ok and rejected.error.code == 'unknown-correspondence-set'


def test_scoped_polarize_and_aggregate_are_distinct_readings():
    ctx = scoped_outgroup_context()
    inventory, _ = node_inventory(ctx, segmentation_overlay_id=None, alignment_overlay_id=None)
    for item in inventory.sets:
        result = call(ctx, 'polarize', 'pol-'+item.scope_id, child_ids=list(ctx.child_ids),
            correspondence=list(item.segments), set_id=item.set_id)
        assert result.ok, result.error
        assert result.result['reading'] == 'local'
        assert {w['concept_id'] for w in result.result['witnesses']} == {item.scope_id}
        assert {w['segment'] for w in result.result['witnesses']} == ({'p'} if item.scope_id == 'one' else {'t'})
        assert all(w['evidence_column_id'] and w['source_positions'] for w in result.result['witnesses'])
    survey = call(ctx, 'summarize_correspondences', 'recur', reading='recurrence')
    assert survey.ok, survey.error
    assert survey.result['reading'] == 'recurrence' and survey.result['matched_set_count'] == 1
    profile = survey.result['outgroup_reflexes'][0]
    assert profile['reading'] == 'recurrence' and {r['segment'] for r in profile['reflexes']} == {'p', 't'}


def test_restoration_cannot_use_another_unit_of_the_same_word_as_witness():
    from cognate_reconstruction.schemas.inventory import SegmentRestoration
    from cognate_reconstruction.agent.tools.inventory_evidence import verify_restorations
    from cognate_reconstruction.agent.tools.errors import ToolInputError
    import pytest
    ctx = context(*(lex(c, form(c, ('p', 'k'), (('core', (0,)), ('extra', (1,))))) for c in ('A','B')))
    ctx.evidence = (NodeEvidence(node_id='O', kind=EvidenceKind.OBSERVED, relation=EvidenceRelation.OUTGROUP,
        lexicon=lex('O', form('O', ('p', 't'), (('core', (0,)), ('extra', (1,)))))),)
    _, reading = node_inventory(ctx, segmentation_overlay_id=None, alignment_overlay_id=None)
    wrong = SegmentRestoration(concept_id='word', unit_id='core', before_column_index=0,
        proto_segment='t', restored_from_node_ids=('O',), directionality_rationale='claim of lost core token')
    with pytest.raises(ToolInputError, match='none of'):
        verify_restorations(ctx, (wrong,), reading)
    verify_restorations(ctx, (wrong.model_copy(update={'unit_id':'extra'}),), reading)
    with pytest.raises(ToolInputError, match='must name unit_id'):
        verify_restorations(ctx, (wrong.model_copy(update={'unit_id':None}),), reading)


def test_distinct_reflexes_and_true_deletions_still_require_explanations():
    ctx = context(lex('A', form('A', ('p',), (('one',(0,)),), concept='one'),
                           form('A', ('t',), (('two',(0,)),), concept='two')),
                  lex('B', form('B', ('p',), (('one',(0,)),), concept='one'),
                           form('B', ('t',), (('two',(0,)),), concept='two')))
    inventory, _ = node_inventory(ctx, segmentation_overlay_id=None, alignment_overlay_id=None)
    for value, label in (('p', 'merger'), (None,'deletion')):
        ctx.commit = None
        spec = ProtoInventorySpec(child_node_ids=ctx.child_ids, commitments=tuple(
            CorrespondenceCommitment(set_id=s.set_id, reflexes=s.segments, support=s.support,
                proto_segment=value, confidence=.9, rationale='scripted '+label) for s in inventory.sets), residue_policy=ResiduePolicy.DROP)
        assert preview(ctx, spec, cid=label).ok
        result = call(ctx, 'commit_reconstruction', label+'-commit', node_id=ctx.node_id,
            inventory=spec.model_dump(mode='json'), anomalies=[], summary=label)
        assert not result.ok and result.error.code == 'missing-directionality-rationale'
        spec = spec.model_copy(update={'commitments':tuple(c.model_copy(update={'directionality_rationale':'recorded claim, truth not adjudicated'}) for c in spec.commitments)})
        assert preview(ctx, spec, cid=label+'-explained').ok
        assert call(ctx, 'commit_reconstruction', label+'-explained-commit', node_id=ctx.node_id,
            inventory=spec.model_dump(mode='json'), anomalies=[], summary=label).ok


def test_count_denominators_distinguish_repeated_etyma_columns_and_alternatives():
    from cognate_reconstruction.alignment.correspondence_sets import build_correspondence_sets
    a = lex('A', form('A', ('p','p'), (('shared',(0,1)),), concept='one'),
                 form('A', ('p',), (('shared',(0,)),), concept='two'))
    b = lex('B', form('B', ('p','p'), (('shared',(0,1)),), concept='one'),
                 form('B', ('p',), (('shared',(0,)),), concept='two'))
    inventory, _ = node_inventory(context(a,b), segmentation_overlay_id=None, alignment_overlay_id=None)
    local = inventory.sets[0]
    assert local.support == local.etymon_count == 1
    assert local.concept_count == 2 and local.source_column_count == local.occurrence_count == 3
    assert inventory.recurrence_patterns[0].support == 1
    # Same unchanged core, more source/candidate occurrences, no recurrence gain.
    a = lex('A', form('A', ('p','k'), (('core',(0,)),('extra',(1,)))))
    b = lex('B', form('B', ('p','t'), (('core',(0,)),('extra',(1,)))),
                 form('B', ('p','s'), (('core',(0,)),('extra',(1,))),suffix='alt'))
    inventory, _ = node_inventory(context(a,b), segmentation_overlay_id=None, alignment_overlay_id=None)
    core = next(s for s in inventory.sets if s.scope_id=='core')
    assert core.support == 1 and core.occurrence_count == core.source_column_count == 2
    assert next(s for s in inventory.recurrence_patterns if s.segments==('p','p')).support == 1


def test_equivalent_whole_and_full_span_source_annotations_have_same_mechanics():
    from cognate_reconstruction.schemas.lexicon import (
        CognateMembership, CognateMembershipScope, CognateMembershipInterpretation,
        CognateMembershipProvenance, LexicalForm)
    from cognate_reconstruction.alignment.units import source_analyses
    inventories=[]
    for sliced in (False, True):
        lexicons=[]
        for child in ('A','B'):
            membership=CognateMembership(membership_id=child+'-source', cognate_set_id='etymon',
                scope=CognateMembershipScope.SEGMENT_SLICE if sliced else CognateMembershipScope.WHOLE_FORM,
                interpretation=CognateMembershipInterpretation.PARTIAL_COGNATE if sliced else CognateMembershipInterpretation.ASSERTED,
                segment_indices=(0,1) if sliced else (), slice_unit='segment' if sliced else None,
                provenance=CognateMembershipProvenance(source_table='CognateTable',source_row=1,source_cognateset_id='etymon'))
            source=LexicalForm(form_id=child, variety_id=child, concept_id='one', segments=('p','a'), cognate_memberships=(membership,))
            analysis=source_analyses(source)[0]
            assert analysis.pieces[0].kind=='whole' and analysis.pieces[0].sources[0].membership_id==child+'-source'
            lexicons.append(lex(child,source))
        inventory,_=node_inventory(context(*lexicons), segmentation_overlay_id=None,alignment_overlay_id=None)
        inventories.append(inventory)
    assert [(s.scope_id,s.segments,s.support) for s in inventories[0].sets] == [(s.scope_id,s.segments,s.support) for s in inventories[1].sets]
    assert [(s.segments,s.support) for s in inventories[0].recurrence_patterns] == [(s.segments,s.support) for s in inventories[1].recurrence_patterns]


def test_scripted_parent_serialization_and_ordinary_morphology_evaluator(tmp_path):
    from tools.evidence_repair_controls import run_controls
    result=run_controls(tmp_path)
    by_mode={c['mode']:c for c in result['controls']}
    for mode,row in by_mode.items():
        assert row['completed_nodes']==['x','p'] and row['validated_planned']==0
        assert all(units for units in row['intermediate_units'])
        for concept in row['concepts']:
            diagnostic=concept['diagnostics']
            assert diagnostic['unit_evaluator_version']=='task04-units-v1'
            comparison=diagnostic['cognate_unit_comparisons'][0]
            assert comparison['unit_exact_rate']==(0.5 if mode in {'wrong','missing'} else 1)
            assert diagnostic['cognate_unit_exact']==(mode in {'correct','reordered'})
            assert bool(comparison['extra_unit_ids'])==(mode=='extra')
            assert bool(comparison['missing_unit_ids'])==(mode=='missing')
            assert comparison['shared_units_reordered']==(mode=='reordered')
        assert row['raw_exact']==(4 if mode=='correct' else 0)


def test_old_semantic_checkpoint_and_unit_inventory_execution_are_refused():
    import pytest
    from cognate_reconstruction import cli
    from cognate_reconstruction.traversal.checkpoint import FamilyCheckpoint
    from cognate_reconstruction.agent.tools.proto_assembly import assemble_node
    from cognate_reconstruction.traversal.assembler import ProtoInventoryAssembler
    from cognate_reconstruction.traversal.beam import make_leaf_beam
    old=FamilyCheckpoint(schema_version='2.0',run_id='old',input_sha256='i',configuration_sha256='c',normalized_tree_sha256='t')
    reasons=cli._resume_mismatches(old,input_sha256='i',tree_sha256='t',configuration_sha256='c',components={})
    assert any('units-v1 count/scope' in r for r in reasons)
    ctx=scoped_outgroup_context()
    spec=ProtoInventorySpec(child_node_ids=ctx.child_ids,commitments=(),residue_policy=ResiduePolicy.DROP)
    _,committed=assemble_node(ctx,spec,node_id=ctx.node_id,segmentation_overlay_id=None)
    old_inventory=committed.model_copy(update={'evidence_contract_version':'units-v1'})
    with pytest.raises(ValueError,match='original checkout'):
        ProtoInventoryAssembler().reconstruct(ctx.node_id,tuple(make_leaf_beam(l,beam_width=5) for l in ctx.child_lexicons),inventory=old_inventory)


def test_shared_conditioned_values_and_scope_overlap_are_strict():
    from cognate_reconstruction.schemas.inventory import SharedCorrespondenceClaim
    from cognate_reconstruction.schemas.rules import RuleEnvironment, SegmentExpression
    from cognate_reconstruction.agent.tools.proto_assembly import assemble_node
    ctx=context(lex('A',form('A',('p','a'),(('one',(0,1)),),concept='one'),
                        form('A',('p','i'),(('two',(0,1)),),concept='two')),
                lex('B',form('B',('f','a'),(('one',(0,1)),),concept='one'),
                        form('B',('f','i'),(('two',(0,1)),),concept='two')))
    inventory,_=node_inventory(ctx,segmentation_overlay_id=None,alignment_overlay_id=None)
    pattern=next(s for s in inventory.recurrence_patterns if s.segments==('p','f'))
    shared=SharedCorrespondenceClaim(pattern_id=pattern.set_id,member_set_ids=pattern.member_set_ids,
        proto_segment='p',confidence=.9,rationale='general shared claim')
    conditioned=shared.model_copy(update={'proto_segment':'t', 'conditioning':RuleEnvironment(right=SegmentExpression(tokens=('i',)))})
    vowels=tuple(CorrespondenceCommitment(set_id=s.set_id,reflexes=s.segments,support=s.support,
        proto_segment=s.segments[0],confidence=.9,rationale='vowel retained') for s in inventory.sets if s.segments[0]!='p')
    spec=ProtoInventorySpec(child_node_ids=ctx.child_ids,commitments=vowels,shared_claims=(shared,conditioned),residue_policy=ResiduePolicy.DROP)
    assert preview(ctx,spec).ok
    step,_=assemble_node(ctx,spec,node_id=ctx.node_id,segmentation_overlay_id=None)
    assert {d.concept_id:d.candidates[0].segments for d in step.output_beam.distributions}=={'one':('p','a'),'two':('t','i')}
    overlap=spec.model_copy(update={'shared_claims':(shared,shared.model_copy(update={'proto_segment':'t'}))})
    rejected=preview(ctx,overlap,cid='overlap')
    assert not rejected.ok and rejected.error.code=='invalid-shared-claim'


def test_outgroup_cap_refuses_all_alternatives_explicitly(monkeypatch):
    import cognate_reconstruction.agent.tools.local_witnesses as witnesses
    monkeypatch.setattr(witnesses,'MAX_NODE_TUPLES',1)
    result=call(scoped_outgroup_context(),'summarize_correspondences','cap',min_support=1,reading='local')
    assert result.ok and result.result['outgroup_reflexes']==[]
    assert 'Local outgroup reading refused' in result.result['outgroup_note']
    assert 'no alignment run or alternatives discarded' in result.result['outgroup_note']


def test_scorer_layouts_do_not_enter_scripted_model_requests(tmp_path):
    import copy
    from tools.evidence_repair_controls import MorphologyProvider
    from cognate_reconstruction.agent.orchestrator import AgentOrchestrator
    from cognate_reconstruction.agent.reconstructor import AgenticNodeReconstructor
    from cognate_reconstruction.agent.service import ReconstructionService
    from cognate_reconstruction.ingestion import ingest_payload
    suite=load_suite(Path(__file__).resolve().parents[2]/'benchmarks/diagnostic/task02-v1.json')
    case=next(c for c in suite['cases'] if c['case_id']=='morphology')
    changed=copy.deepcopy(case)
    changed['target_unit_layouts']={k:['SCORER_SENTINEL',*v[1:]] for k,v in changed['target_unit_layouts'].items()}
    captured=[]
    class RecordingProvider(MorphologyProvider):
        def complete(self,messages,tools,**kwargs):
            # Tool arguments/results and prompt/schema are model-visible.
            self.requests.append(([m.model_dump(mode='json') for m in messages],
                                  [t.model_dump(mode='json') for t in tools]))
            return super().complete(messages,tools,**kwargs)
    for definition in (case,changed):
        payload=build_case(definition).payload
        provider=RecordingProvider(payload,'correct');provider.requests=[]
        result=ReconstructionService(AgenticNodeReconstructor(AgentOrchestrator(provider,
            instructions='scripted isolation test'))).reconstruct_family(ingest_payload(payload))
        assert all(t.completed for t in result.trajectories)
        # Tool validation IDs are deterministic; no target/version notes differ.
        text=str(provider.requests)
        assert 'SCORER_SENTINEL' not in text and 'target_unit_layouts' not in text
        captured.append(provider.requests)
    assert captured[0]==captured[1]
