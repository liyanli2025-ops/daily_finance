"""Offline regressions for one same-ledger material continuation."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app import edition_once as entry
from app.services import edition_continuation as cont
from app.services.edition_budget import digest, number
from app.services.edition_context import packet
from app.services.research_hub import save_json
import test_unified_edition as reference
from test_edition_manual import config, IDENTIFIER


def sample():
    source, _, assessment, _ = reference.fixtures()
    state = reference.state()
    state.update(id=IDENTIFIER, owner='finance-unified-edition-v1', status='failed',
        phase='assessment', error_code='edition_evidence_scope_invalid', manual_text_only=True,
        model_http_attempts=2, search_http_attempts=12, public_fetch_attempts=18,
        active_seconds=110, app_written=False,
        agenda=dict(events=[copy.deepcopy(reference.EVENT)], excluded_candidates=[]),
        sources={'body-1': source}, candidates={'S1':dict(title=source['title'],url=source['url'],snippet=reference.FACT)},
        delivered_sources={'assessment':{'body-1':digest(source['text'])}},
        read_receipts=[dict(candidate_id='S1',event_id='E1',status='ok')])
    state['policy'].update(edition_forecast='remaining_stages_v1',estimated_limit_usd='1',
        request_input_pricing=dict(analysis='uncached_request_v1',review='uncached_request_v1'))
    state['reservations']=[dict(kind='model',stage=stage,estimated_usd='.3',
        usage_priced_usd=cost,input_characters=100,output_tokens=5000,
        actual_usage={'http_status':200}) for stage,cost in [('agenda','.076382'),('assessment','.12303')]]
    state['reservations'] += [dict(kind='search',stage=None,estimated_usd='.008') for _ in range(12)]
    return state,assessment


def saved(root):
    state,assessment=sample();directory=root/IDENTIFIER;directory.mkdir()
    save_json(directory/'result.json',state)
    save_json(directory/'response-2.json',dict(stage='assessment',text=json.dumps(assessment,ensure_ascii=False)))
    return state,directory


class PreparationTests(unittest.TestCase):
    def test_original_http_or_unknown_usage_is_not_eligible(self):
        for change in ('usage','stage','draft','error'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as temporary:
                state,directory=saved(Path(temporary))
                if change=='usage':state['reservations'][0].pop('usage_priced_usd')
                if change=='stage':state['phase']='writing'
                if change=='draft':state['draft']={'body':'paid draft'}
                if change=='error':state['error_code']='edition_http_failed'
                save_json(directory/'result.json',state)
                with self.assertRaises(ValueError):cont.original_input(directory,IDENTIFIER)

    def test_prepare_keeps_original_fees_cutoff_and_input_unchanged(self):
        state,value=sample();before=copy.deepcopy(state)
        with patch.object(cont,'recover_sources',return_value=({},[])):
            prepared,_=cont.prepare(state,value,Path('unused'))
        self.assertEqual(state,before)
        for key in ('id','cutoff','reservations','model_http_attempts','search_http_attempts','public_fetch_attempts'):
            self.assertEqual(prepared[key],before[key])
        total=sum((cont.accounted(r) for r in prepared['reservations']),number(0))
        self.assertEqual(total,number('.295412'))

    def test_four_company_gaps_and_missing_event_are_separate_search_targets(self):
        state,value=sample()
        state['watchlist']=[dict(market='A',code=code,name=name) for code,name in
            [('1','甲公司'),('2','乙公司'),('3','丙公司'),('4','丁公司')]]
        value['watchlist_checks']=[dict(key='A:'+s['code'],status='missing',reason='尚无直接资料')
                                   for s in state['watchlist']]
        state['agenda']['events'].append(dict(reference.EVENT,id='E2',importance='context',title='重要选举后续进展'))
        value['events'].append(dict(id='E2',status='missing',reason='只有候选没有正文'))
        jobs,tasks=cont.gap_plan(state,value)
        self.assertEqual(len(jobs),5);self.assertEqual(len(tasks),4)
        self.assertEqual({j['scope'] for j in jobs if j.get('scope')},{'A:1','A:2','A:3','A:4'})
        self.assertTrue(any(j['event_id']=='E2' and '选举' in j['query'] for j in jobs))

    def test_named_company_event_does_not_trigger_duplicate_company_search(self):
        state,value=sample();state['watchlist']=[dict(market='A',code='1',name='甲公司')]
        state['agenda']['events'][0]['title']='甲公司财报线索'
        value['events'][0].update(status='missing',evidence=[])
        value['watchlist_checks']=[dict(key='A:1',status='missing',reason='待核')]
        jobs,tasks=cont.gap_plan(state,value)
        self.assertEqual(len(jobs),1);self.assertEqual(tasks,{})
        self.assertEqual(jobs[0]['event_id'],'E1')

    def test_new_recovery_was_not_available_to_the_original_assessment(self):
        state,value=sample();recovered=copy.deepcopy(state['sources']['body-1']);recovered['id']='recovered';recovered['candidate_id']='S1'
        value['events'][0]['evidence']=[dict(source_id='recovered',quote=reference.FACT)]
        with patch.object(cont,'recover_sources',return_value=({'recovered':recovered},[])):
            prepared,_=cont.prepare(state,value,Path('unused'))
        self.assertEqual(prepared['assessment']['events'][0]['status'],'missing')
        self.assertNotIn('recovered',prepared['delivered_sources']['assessment'])

    def test_patch_packet_identifies_company_tasks_without_changing_agenda(self):
        state,value=sample();state.update(assessment=value,research_tasks={'T1':{'title':'公司核对'}},
            recovered_source_ids=['recovered'])
        payload=packet(state,'patch_assessment')
        self.assertEqual(payload['agenda'],state['agenda'])
        self.assertEqual(payload['company_research_tasks'],state['research_tasks'])
        self.assertIn('不是新增新闻事件',payload['company_task_note'])

    def test_source_response_symlink_cannot_be_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            _,directory=saved(Path(temporary));p=directory/'response-2.json'
            p.rename(directory/'original.json');p.symlink_to('original.json')
            with self.assertRaisesRegex(ValueError,'file_invalid'):cont.original_input(directory,IDENTIFIER)


    def test_continuation_omits_old_snippets_but_keeps_new_and_every_title(self):
        state,value=sample();state.update(assessment=value,continuation_catalogue_ids=['S1'])
        state['candidates']['S2']=dict(title='新搜索的反面资料',url='https://example.com/new',snippet='新的完整摘要')
        payload=packet(state,'patch_assessment')
        # Missing core fields deliberately use the transparent dict encoding.
        self.assertIsNone(payload['candidates']['S1']['snippet'])
        self.assertEqual(payload['candidates']['S1']['title'],state['candidates']['S1']['title'])
        self.assertEqual(payload['candidates']['S1']['url'],state['candidates']['S1']['url'])
        self.assertEqual(payload['candidates']['S2']['snippet'],'新的完整摘要')
        self.assertEqual(state['candidates']['S1']['snippet'],reference.FACT)

    def test_writing_excerpts_preserve_quoted_conditions_and_raw_source(self):
        from app.services.edition_context import editorial_source_packet
        state,value=sample();state.update(assessment=value,continuation_catalogue_ids=['S1'])
        original=('前段背景。\n'*250)+reference.FACT+'附带限制：尚未生效，不保证收益。\n'+('其他消息。\n'*300)
        state['sources']['body-1']['text']=original
        result=editorial_source_packet(state['sources']['body-1'],state)
        self.assertIn(reference.FACT,result['text']);self.assertIn('尚未生效，不保证收益',result['text'])
        self.assertLess(len(result['text']),len(original))
        self.assertEqual(state['sources']['body-1']['text'],original)
        for start,end in result['provided_original_ranges']:
            self.assertIn(original[start:end],result['text'])
        self.assertIn('非全文',result['reading_limit'])

    def test_unquoted_contrary_body_is_not_removed_or_excerpted(self):
        from app.services.edition_context import editorial_source_packet
        state,value=sample();state.update(assessment=value,continuation_catalogue_ids=['S1'])
        contrary=dict(state['sources']['body-1'],id='contrary',text='反方全文，不应过滤。'*300)
        self.assertEqual(editorial_source_packet(contrary,state)['text'],contrary['text'])

    def test_review_includes_new_written_source_quote_context(self):
        from app.services.edition_context import editorial_source_packet
        state,value=sample();state.update(assessment=value,continuation_catalogue_ids=['S1'])
        text=reference.FACT+('不相关段落。\n'*300)+'另一处明确条件和风险。'+('结尾背景。\n'*300)
        state['sources']['body-1']['text']=text
        state['draft']={'source_checks':[dict(source_id='body-1',source_quote='另一处明确条件和风险。')]}
        result=editorial_source_packet(state['sources']['body-1'],state)
        self.assertIn('另一处明确条件和风险。',result['text']);self.assertIn(reference.FACT,result['text'])

    def test_unrequested_recovered_body_stays_local_instead_of_growing_every_input(self):
        state,value=sample();source=dict(state['sources']['body-1'],id='recovered',candidate_id='S1')
        audit=[dict(status='recovered_pending_assessment',source_id='recovered')]
        with patch.object(cont,'recover_sources',return_value=({'recovered':source},audit)):
            prepared,record=cont.prepare(state,value,Path('unused'))
        self.assertNotIn('recovered',prepared['sources']);self.assertEqual(prepared['recovered_source_ids'],[])
        self.assertEqual(record[0]['status'],'available_locally_not_selected')


class ContinuationExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def execute_fake(self,root,*,fail=False,block=False):
        state,directory=saved(root);original=(directory/'result.json').read_bytes()
        state['assessment']=reference.fixtures()[2]
        state.update(research_tasks={},recovered_source_ids=[])
        preview=dict(ready_to_run=not block,input_sha256='frozen',recovery=[],blockers=['money'] if block else [])
        factory=cont.core.EditionPipeline
        captured=[]
        def pipeline(s,d,w,check):
            captured.append(w)
            p=factory(s,d,w,check=check)
            async def finish(*args,**kwargs):
                self.assertEqual(w.web_search_attempts,12)
                self.assertEqual(w.public_fetch_attempts,18)
                s['draft']={'body':'已保存稿件'};p.save()
                if fail:raise RuntimeError('edition_failed_no_retry')
                s['status']='reviewed_text';p.save()
            p.finish_materials=finish
            return p
        with patch.object(entry,'require_pause'),patch.object(entry,'identity',return_value='environment'),\
             patch.object(entry,'assert_watchlist_current',AsyncMock()),\
             patch.object(cont,'continuation_preview',AsyncMock(return_value=(preview,state,original,'environment'))) as planned,\
             patch.object(cont.core,'EditionPipeline',side_effect=pipeline) as made:
            result,path,reused=await cont.continue_once(config(),IDENTIFIER,run=True,root=root)
            if not block:
                second,_,second_reused=await cont.continue_once(config(),IDENTIFIER,run=True,root=root)
                self.assertTrue(second_reused);self.assertEqual(planned.await_count,1);self.assertEqual(made.call_count,1)
                self.assertEqual(second['id'],IDENTIFIER)
        return result,path,captured,original

    async def test_same_run_and_counters_backup_and_duplicate_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            result,directory,workspaces,original=await self.execute_fake(Path(temporary))
            self.assertEqual(result['id'],IDENTIFIER);self.assertEqual(result['status'],'reviewed_text')
            self.assertEqual((directory/'before-material-continuation.json').read_bytes(),original)
            self.assertEqual(len(result['reservations']),14)
            self.assertTrue((directory/'material-continuation.started').is_file())
            self.assertEqual(len(workspaces),1);self.assertFalse(result['resume_allowed'])

    async def test_failed_continuation_preserves_draft_and_never_retries(self):
        with tempfile.TemporaryDirectory() as temporary:
            result,directory,_,_=await self.execute_fake(Path(temporary),fail=True)
            self.assertEqual(result['status'],'failed');self.assertIn('draft',result)
            self.assertEqual(result['error_code'],'edition_failed_no_retry')
            self.assertEqual(result['material_continuation']['prior_error']['error_code'],'edition_evidence_scope_invalid')

    async def test_budget_blocker_creates_no_backup_marker_or_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            result,directory,workspaces,_=await self.execute_fake(Path(temporary),block=True)
            self.assertIsNone(directory);self.assertFalse(result['ready_to_run']);self.assertEqual(workspaces,[])
            self.assertFalse((Path(temporary)/IDENTIFIER/'material-continuation.started').exists())

    async def test_shared_pipeline_uses_only_patch_writing_review_and_never_new_agenda(self):
        with tempfile.TemporaryDirectory() as temporary:
            state,value=sample();directory=Path(temporary);ws=cont.EpisodeWorkspace(root=directory/'evidence')
            source,written,value,reviewed=reference.fixtures()
            value['additional_reads']=[dict(event_id='E1',candidate_id='S1',increment='missing_context',
                reason='已有恢复正文需要重新核对逐字依据和适用条件')]
            state['assessment']=value
            answers=[copy.deepcopy(value),written,reviewed]
            answers[0]['additional_reads']=[]
            stages=[]
            async def model(task,messages,limit):
                stages.append(task);return json.dumps(answers[len(stages)-1],ensure_ascii=False)
            p=cont.core.EditionPipeline(state,directory,ws,model=model,check=AsyncMock())
            with patch('app.services.podcast_script_cache.save'),\
                 patch('app.services.podcast_script_cache.load',return_value=written['script']):
                await p.finish_materials(value,{'E1':reference.EVENT},set(),recovered_ids=['body-1'])
            self.assertEqual([r['stage'] for r in state['reservations'] if r['kind']=='model'],
                ['agenda','assessment','patch_assessment','writing','review'])
            self.assertEqual(stages,['analysis','analysis','review'])
            self.assertEqual(state['status'],'reviewed_text')
            self.assertEqual(state['search_http_attempts'],12);self.assertEqual(state['public_fetch_attempts'],18)
            self.assertFalse(state['app_written']);self.assertNotIn('tts_attempts',state)
