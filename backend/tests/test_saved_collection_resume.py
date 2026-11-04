"""Offline resume contracts. Models, search and HTTP are mocked throughout."""
from copy import deepcopy
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from app.services.discovery_budget import Limits
from app.services.discovery_resume import restore_state, tool_caches, stored_news, clone_workspace


def config():
    return SimpleNamespace(research_web_search_max_requests=22, research_body_max_urls=64,
        research_local_read_max_characters=96000, research_input_max_characters=160000,
        research_max_seconds=882, research_total_input_characters=1964734,
        research_total_output_tokens=113400, research_max_model_calls=None)


def fixture(workspace):
    limits = Limits(model_calls=None, search_calls=11, body_urls=22, input_characters=108000,
                    output_tokens=3300, seconds=360, local_read_characters=44000)
    ceiling = dict(limits.__dict__, search_calls=22, body_urls=64, input_characters=160000,
                   seconds=882, local_read_characters=96000)
    state = dict(owner='finance-model-led-discovery-v1', status='input_budget_exhausted',
        started_at=workspace.now.isoformat(), watchlist=[], limits=limits.__dict__,
        budget_plan=dict(mode='progress_driven_collection', initial=limits.__dict__, ceiling=ceiling,
            total_input_characters=1964734, total_reserved_output_tokens=113400, model_request_cap=None),
        model_calls=2, model_input_characters=100672, reserved_output_tokens=6600,
        search_tool_calls=9, body_url_calls=6, local_read_characters=2407, no_progress_turns=0,
        budget_expansions=[], event_followup_tasks=[], event_review_problems=[], decisions=[],
        quality='pending_human_review', provided_ids=['B'], finish_feedback_history=[],
        candidates={'S1':dict(title='正文', url='https://example.com/a', snippet='',discovered_by=[])},
        receipts=[dict(request=dict(tool='read',candidate_id='S1',relation='market'),
            result=dict(status='ok', material=dict(id='B',offset=0,text=workspace.documents['B'].content)))])
    return dict(research=state, active_seconds=73, search_http_attempts=9,
        model_exposures=[dict(completed_response=True,body_ranges={}) for _ in range(2)])


def workspace():
    return SimpleNamespace(now=datetime(2026,11,1,13,56), web_search_attempts=9,
                           documents={'B':SimpleNamespace(content='已保存原文与限制。'*100)})


class StateTests(unittest.TestCase):
    def test_restores_counters_and_unconfirmed_body_without_mutating_original(self):
        ws=workspace();value=fixture(ws);before=deepcopy(value)
        state,limits,ceiling,plan,spent=restore_state(ws,[],value,config())
        self.assertEqual(value,before)
        self.assertEqual(state['model_calls'],2)
        self.assertEqual(state['search_tool_calls'],9)
        self.assertEqual(state['local_read_characters'],2407)
        self.assertEqual(state['context_delivery']['body_ranges'],{})
        self.assertEqual(spent,73)
        self.assertEqual(limits.input_characters,108000)
        self.assertEqual(plan['total_input_characters']-state['model_input_characters'],1864062)

    def test_only_actual_completed_exposures_confirm_ranges(self):
        ws=workspace();value=fixture(ws)
        value['model_exposures'][0]['body_ranges']={'B':[[0,30]]}
        value['model_exposures'][1]=dict(completed_response=False,body_ranges={'B':[[30,60]]})
        state,*_=restore_state(ws,[],value,config())
        self.assertEqual(state['context_delivery']['body_ranges'],{'B':[[0,30]]})

    def test_rejects_a_failed_run_other_than_context_size(self):
        ws=workspace();value=fixture(ws);value['research']['status']='failed_no_retry'
        with self.assertRaises(ValueError):restore_state(ws,[],value,config())

    def test_changed_cutoff_or_watchlist_rejected(self):
        ws=workspace();value=fixture(ws)
        with self.assertRaises(ValueError):restore_state(ws,[dict(code='1')],value,config())
        ws.now=datetime(2026,11,2)
        with self.assertRaises(ValueError):restore_state(ws,[],value,config())

    def test_envelope_cannot_expand_during_resume(self):
        ws=workspace();value=fixture(ws);value['research']['budget_plan']['ceiling']['body_urls']=65
        with self.assertRaises(ValueError):restore_state(ws,[],value,config())

    def test_elapsed_time_and_stall_are_not_reset(self):
        ws=workspace();value=fixture(ws);value['active_seconds']=360
        with self.assertRaises(ValueError):restore_state(ws,[],value,config())
        value['active_seconds']=73;value['research']['no_progress_turns']=2
        with self.assertRaises(ValueError):restore_state(ws,[],value,config())

    def test_changed_source_and_fabricated_delivery_rejected(self):
        ws=workspace();value=fixture(ws);value['research']['receipts'][0]['result']['material']['text']='改写'
        with self.assertRaises(ValueError):restore_state(ws,[],value,config())
        value=fixture(ws);value['model_exposures'][0]['body_ranges']={'B':[[0,99999]]}
        with self.assertRaises(ValueError):restore_state(ws,[],value,config())

    def test_restores_failed_url_and_query_caches_without_fetching(self):
        ws=workspace();value=fixture(ws);state=value['research']
        state['candidates']['S2']=dict(url='https://example.com/failed')
        state['receipts'] += [dict(request=dict(tool='read',candidate_id='S2'),
            result=dict(status='failed',reason='public_http_429')),
            dict(request=dict(tool='search',query=' 查询  内容 ',lane='a_market',purpose='discovery'),
                 result=dict(status='ok',results=[dict(candidate_id='S1')]))]
        searches,reads=tool_caches(state)
        self.assertIn(('查询 内容','general','discovery'),searches)
        self.assertEqual(reads['https://example.com/failed']['reason'],'public_http_429')
        self.assertEqual(reads['https://example.com/a']['material']['id'],'B')

    def test_day_precision_survives_snapshot_restore(self):
        label='2026-10-30 16:34:00（来源未标时区，仅按日期，不用于盘前盘后或消息先后判断）（日精度；内部日期区间起点不是实际发布时分）'
        row=dict(id='B',title='正文',source='公开网页可见正文-example.com',url='https://example.com/a',
                 text='原文'*100,characters=200,published=label,reading_scope='visible_body')
        from app.services.evidence import publication_label
        item=stored_news(row)
        self.assertEqual(publication_label(item),label)
        self.assertEqual(item.published_at,datetime(2026,10,30))

    def test_local_fork_preserves_original_material_bytes(self):
        from app.services.episode_workspace import EpisodeWorkspace
        from app.models.news import News
        with tempfile.TemporaryDirectory() as directory:
            old=EpisodeWorkspace([],root=directory,now=datetime(2026,11,1))
            old.add([News(id='B',title='正文',source='公开网页可见正文-example.com',
                source_url='https://example.com/a',content='正文'*100,published_at=datetime(2026,10,30))])
            before=(old.path/'materials.json').read_bytes()
            new=clone_workspace(old.path,datetime(2026,11,4))
            self.assertNotEqual(old.path,new.path)
            self.assertEqual(new.now,old.now)
            self.assertEqual((old.path/'materials.json').read_bytes(),before)
            self.assertEqual((new.path/'materials.json').read_bytes(),before)
            new.read('B',characters=100)
            self.assertFalse(old.prepared)


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    async def test_resume_uses_failed_url_cache_and_original_counters(self):
        from app.services.episode_workspace import EpisodeWorkspace
        from app.services.primary_discovery import discover
        from app.models.news import News
        from app.config import settings
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            ws=EpisodeWorkspace([],root=directory,now=datetime(2026,11,1,13,56))
            ws.add([News(id='B',title='正文',content='原文与限制。'*200,
                source='公开网页可见正文-example.com',source_url='https://example.com/a',published_at=ws.now)])
            ws.web_search_attempts=9;value=fixture(ws)
            value['research']['candidates']['S2']=dict(title='失败来源',url='https://example.com/failed',
                snippet='',discovered_by=[])
            value['research']['receipts'].append(dict(request=dict(tool='read',candidate_id='S2'),
                result=dict(status='failed',reason='public_http_429')))
            saved=[]
            model=AsyncMock(side_effect=[json.dumps(dict(action='tools',requests=[dict(tool='read',
                candidate_id='S2',relation='market',reason='缓存应保留失败')],)),RuntimeError('injected stop')])
            read,search=Mock(),Mock()
            cfg=config()
            with patch.multiple(settings,**vars(cfg)):
                with self.assertRaises(RuntimeError):
                    await discover(ws,[],resume=value,model=model,read=read,search=search,
                                   checkpoint=lambda s:saved.append(deepcopy(s)))
            read.assert_not_called();search.assert_not_called()
            self.assertEqual(saved[-1]['body_url_calls'],6)
            self.assertEqual(saved[-1]['search_tool_calls'],9)
            self.assertEqual(saved[-1]['model_calls'],4)
            self.assertEqual(saved[-1]['receipts'][-1]['result']['reason'],'public_http_429')
            self.assertTrue(saved[-1]['receipts'][-1]['result']['reused'])
            self.assertIn('B',saved[-1]['context_delivery']['body_ranges'])


class RunnerProofTests(unittest.TestCase):
    def load(self):
        path=Path(__file__).resolve().parents[2]/'tools/resume_saved_collection.py'
        spec=importlib.util.spec_from_file_location('saved_resume_tests',path)
        runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
        return runner

    def receipt(self):
        owner='finance-progress-collection-acceptance-v1'
        value=dict(watchlist=[],budget_plan={})
        fingerprint=lambda v:hashlib.sha256(json.dumps(v,sort_keys=True).encode()).hexdigest()
        result=dict(owner=owner,status='input_budget_exhausted',finished_at='2026-11-01T14:38:04.238864',
            pause_preserved=True,input_sha256=fingerprint(value),started_at='2026-11-01T14:36:51.773885',
            cutoff='2026-11-01T13:56:44',watchlist=[],budget_plan={},model_http_attempts=2,
            model_input_characters=100672,reserved_output_tokens=6600,search_http_attempts=9,
            research=dict(started_at='2026-11-01T13:56:44',model_calls=2,model_input_characters=100672,
                reserved_output_tokens=6600,search_tool_calls=9))
        marker=dict(owner=owner,input_sha256=fingerprint(value),started_at=result['started_at'])
        base=SimpleNamespace(OWNER=owner,fingerprint=fingerprint)
        return result,value,marker,base

    def test_time_counts_only_active_run_not_human_wait(self):
        self.assertEqual(self.load().verify_saved(*self.receipt()),73)

    def test_transport_usage_must_match_controller(self):
        result,value,marker,base=self.receipt();result['research']['model_calls']=1
        with self.assertRaises(ValueError):self.load().verify_saved(result,value,marker,base)

    def test_changed_input_marker_rejected(self):
        result,value,marker,base=self.receipt();marker['input_sha256']='changed'
        with self.assertRaises(ValueError):self.load().verify_saved(result,value,marker,base)

    def test_transport_reservations_and_exposures_continue_without_aliasing(self):
        old=dict(model_http_attempts=2,model_input_characters=100672,reserved_output_tokens=6600,
            search_http_attempts=9,public_fetch_attempts=6,usage=[dict(output_tokens=100)],
            model_exposures=[dict(completed_response=True,body_ranges={})],cutoff='2026-11-01T13:56:44')
        state=dict(model_http_attempts=0,model_exposures=[])
        self.load().restore_transport(state,old,dict(mode='resume'))
        self.assertEqual(state['reserved_output_tokens'],6600)
        self.assertEqual(state['model_input_characters'],100672)
        self.assertEqual(state['public_fetch_attempts'],6)
        state['usage'].append({});state['model_exposures'].clear()
        self.assertEqual(len(old['usage']),1)
        self.assertEqual(len(old['model_exposures']),1)


if __name__=='__main__':unittest.main()
