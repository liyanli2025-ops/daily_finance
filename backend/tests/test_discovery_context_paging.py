"""Offline regressions for context delivery, exact ranges and controller wiring."""
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
import json
import tempfile
import unittest
from unittest.mock import Mock

from app.services.discovery_context import (project, manifest, confirm, encoded, wire_size,
    body_packets, validate_inspection, retain_observations, merged)


def fixture(count=66, text='原始正文与后部风险。'*1000):
    return dict(candidates={f'S{i}': dict(title=f'不同范围原题{i}',
        url=f'https://example.com/news/{i}', snippet='完整目录摘要，不是正文。'*35,
        discovered_by=[dict(lane='a_market',scope=None,purpose='latest_close',query='重复查询'*20)],
        retrieval_assessments=[dict(flags=[],limitation='元数据不是事实核实'*30)]) for i in range(count)},
        receipts=[dict(request=dict(tool='read',candidate_id='S0'),result=dict(status='ok',
            material=dict(id='B',offset=0,text=text,title='原始标题',url='https://example.com/body')))])


class ContextPagingTests(unittest.TestCase):
    def test_bounded_projection_does_not_modify_or_shorten_private_evidence(self):
        state=fixture();before=deepcopy(state)
        view=project(state,16000)
        self.assertLessEqual(wire_size(view),16000)
        self.assertEqual(state,before)
        for candidate in view['candidates']:
            self.assertEqual(candidate['snippet'],state['candidates'][candidate['candidate_id']]['snippet'])
        self.assertLess(len(view['candidates']),66)

    def test_all_candidate_pages_remain_reachable(self):
        state=fixture(text='已存正文。'*50)
        for _ in range(120):
            sent=manifest(project(state,12000));confirm(state,sent)
            if set(state['context_delivery']['candidate_ids'])==set(state['candidates']):break
        self.assertEqual(set(state['context_delivery']['candidate_ids']),set(state['candidates']))

    def test_long_unicode_body_can_be_delivered_without_gaps_or_changed_offsets(self):
        text='甲乙🙂反证和限制\n'*1800
        state=fixture(count=3,text=text)
        for _ in range(80):
            view=project(state,12000)
            for row in view['body_packets']:
                self.assertEqual(row['text'],text[row['offset']:row['offset']+len(row['text'])])
            confirm(state,manifest(view))
            if state['context_delivery']['body_ranges'].get('B')==[[0,len(text)]]:break
        self.assertEqual(state['context_delivery']['body_ranges']['B'],[[0,len(text)]])
        self.assertEqual(body_packets(state)[0]['text'],text)

    def test_building_a_page_does_not_confirm_a_model_response(self):
        state=fixture();sent=manifest(project(state,14000))
        self.assertTrue(sent['body_ranges'])
        self.assertNotIn('context_delivery',state)
        confirm(state,sent)
        self.assertEqual(state['context_delivery']['body_ranges'],sent['body_ranges'])

    def test_long_first_source_does_not_hide_every_other_body(self):
        state=fixture(count=1,text='第一篇很长的正文。'*5000)
        state['receipts'].append(dict(request=dict(tool='read'),result=dict(status='ok',
            material=dict(id='SECOND',offset=0,text='第二篇的限制和反证。'*1000))))
        sent=manifest(project(state,26000))
        self.assertIn('B',sent['body_ranges'])
        self.assertIn('SECOND',sent['body_ranges'])

    def test_original_publication_precision_and_reading_scope_are_preserved(self):
        state=fixture(count=1)
        state['receipts'][0]['result']['material'].update(
            published='2026-10-30（来源无时区；只核日期）',reading_scope='visible_body')
        view=project(state,16000)
        self.assertEqual(view['body_index'][0]['published'],'2026-10-30（来源无时区；只核日期）')
        self.assertEqual(view['body_index'][0]['reading_scope'],'visible_body')

    def test_budget_counts_quotes_backslashes_and_newline_escaping(self):
        state=fixture(count=2,text='"\\\n🙂'*3000)
        view=project(state,9000)
        contribution=len(json.dumps(encoded(view),ensure_ascii=False))-2
        self.assertEqual(wire_size(view),contribution)
        self.assertLessEqual(contribution,9000)

    def test_rereading_returned_ranges_is_local_and_unreturned_ranges_are_rejected(self):
        state=fixture(count=2,text='头部原文'*200)
        focus=validate_inspection(dict(section='body',id='B',offset=20),state)
        confirm(state,manifest(project(state,14000)));state['context_focus']=focus
        view=project(state,14000)
        self.assertEqual(view['body_packets'][0]['offset'],20)
        with self.assertRaises(ValueError):
            validate_inspection(dict(section='body',id='B',offset=999999),state)

    def test_oversized_candidate_is_reported_without_cutting_its_snippet(self):
        state=fixture(count=1);state['candidates']['S0']['snippet']='完整原摘要。'*10000
        view=project(state,10000)
        self.assertFalse(view['candidates'])
        self.assertEqual(view['navigation']['candidates']['oversized_entry'],'S0')
        self.assertEqual(len(state['candidates']['S0']['snippet']),60000)

    def test_observations_require_exact_quotes_from_completed_requests(self):
        state=fixture(count=1,text='事实发生，但尚有反证。'*200)
        ws=SimpleNamespace(documents={'B':SimpleNamespace(content=body_packets(state)[0]['text'])})
        row=dict(id='B',offset=0,quote='事实发生，但尚有反证。',note='保留限制，需要独立核对。')
        with self.assertRaises(ValueError):retain_observations(state,dict(observations=[row]),ws)
        confirm(state,manifest(project(state,16000)))
        retain_observations(state,dict(observations=[row]),ws)
        self.assertEqual(state['observations'][0]['quote'],row['quote'])
        before=deepcopy(state['observations'])
        with self.assertRaises(ValueError):
            retain_observations(state,dict(observations=[row,dict(row,quote='改写成不存在的引文')]),ws)
        self.assertEqual(state['observations'],before)

    def test_history_and_observations_have_explicit_paging(self):
        state=fixture(count=1)
        state['receipts']*=25
        state['observations']=[dict(id='B',offset=0,quote='原文',note=str(i)) for i in range(30)]
        state['context_focus']=validate_inspection(dict(section='receipts',offset=0),state)
        view=project(state,16000)
        self.assertEqual(view['navigation']['receipts']['offset'],0)
        self.assertIsNotNone(view['navigation']['receipts']['next_offset'])
        state['context_focus']=validate_inspection(dict(section='observations',offset=0),state)
        self.assertEqual(project(state,16000)['observations'][0]['note'],'0')

    def test_overlapping_tool_ranges_do_not_become_two_independent_sources(self):
        state=fixture(count=1,text='abcdefghij'*400)
        state['receipts'].append(dict(request=dict(tool='read_more'),result=dict(status='ok',
            id='B',offset=2000,text='abcdefghij'*300)))
        for _ in range(10):confirm(state,manifest(project(state,16000)))
        self.assertEqual(merged(state['context_delivery']['body_ranges']['B']),[[0,5000]])


class ControllerPagingTests(unittest.IsolatedAsyncioTestCase):
    async def collect(self, fail=False):
        from app.models.news import News
        from app.services.episode_workspace import EpisodeWorkspace
        from app.services.primary_discovery import discover,Limits
        from app.services.search_primary_collection import LANES
        saved=[];calls=[]
        with tempfile.TemporaryDirectory() as directory:
            ws=EpisodeWorkspace([],root=directory,now=datetime(2026,11,1,14))
            search=Mock(side_effect=lambda workspace,query,**kwargs:dict(status='ok',results=[
                dict(title=f'{query} 当期材料{i}',url=f'https://example.com/{query}/{i}',
                     snippet='完整目录信息不是正文。'*45) for i in range(10)]))
            def read(workspace,url,**kwargs):
                item=News(id='BODY',title='当期正文',content='事实、范围与限制需要保留。'*120,
                    source='公开网页可见正文-example',source_url=url,published_at=workspace.now)
                workspace.add([item]);return dict(status='ok',material=workspace.read('BODY',characters=4000))
            async def model(task,messages,max_tokens):
                calls.append(messages)
                if len(calls)==1:
                    return json.dumps(dict(action='tools',requests=[dict(tool='search',lane=lane,
                        query=lane+' actual facts',reason='核对实际范围') for lane in LANES]))
                if len(calls)==2:
                    return json.dumps(dict(action='tools',requests=[dict(tool='read',candidate_id='S1',
                        relation='market',reason='读已展示候选正文')]))
                if fail:raise RuntimeError('simulated incomplete model response')
                feedback=json.JSONDecoder().raw_decode(messages[0]['content'].rsplit('collection_feedback：',1)[1])[0]
                return json.dumps(dict(action='finish',events=[],omissions=[],watchlist_checks=[],
                    deferred_tasks=[dict(task_id=row['task_id'],reason='本用例保留未解决缺口') for row in feedback['tasks']],
                    coverage=[dict(lane=row['lane'],status='body_provided' if row['body_ids'] else 'missing',
                        evidence_ids=row['body_ids'],explanation='其余范围仍有缺口') for row in feedback['lanes']]))
            limits=Limits(model_calls=4,search_calls=11,body_urls=22,input_characters=48000,
                          local_read_characters=44000,tool_requests_per_turn=11)
            try:
                result=await discover(ws,[],limits=limits,model=model,search=search,read=read,
                    checkpoint=lambda state:saved.append(deepcopy(state)))
            except RuntimeError:
                if not fail:raise
                result=saved[-1]
        return result,calls

    async def test_large_directory_does_not_prevent_next_body_request(self):
        result,calls=await self.collect()
        self.assertEqual(len(calls),3)
        self.assertNotEqual(result['status'],'input_budget_exhausted')
        self.assertTrue(result['context_delivery']['body_ranges']['BODY'])
        self.assertIn('事实、范围与限制',calls[2][0]['content'])

    async def test_failed_model_response_does_not_confirm_body_delivery(self):
        result,calls=await self.collect(fail=True)
        self.assertEqual(len(calls),3)
        self.assertTrue(result['request_context']['body_ranges']['BODY'])
        self.assertNotIn('BODY',result['context_delivery']['body_ranges'])


if __name__=='__main__':unittest.main()
