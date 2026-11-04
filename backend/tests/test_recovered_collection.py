"""Saved-source recovery and spending boundaries; all transports are mocked."""
from copy import deepcopy
from datetime import datetime,timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch,AsyncMock

from app.models.news import News
from app.services.discovery_budget import Limits
from app.services.discovery_recovery import prepare_saved,fingerprint,validate_prepared
from app.services.discovery_resume import restore_state,tool_caches
from app.services.episode_workspace import EpisodeWorkspace
from app.services.material_roles import assess_role,lane_allowed
from app.services.primary_discovery import discover

NOW=datetime(2026,11,1,13,56)
URL='https://publisher.example/news/company'
TEXT='原始事实、风险及公司归属需要继续核对。'*30


def config():
    return dict(research_web_search_max_requests=22,research_body_max_urls=64,
        research_local_read_max_characters=96000,research_input_max_characters=160000,
        research_max_seconds=882,research_total_input_characters=1964734,
        research_total_output_tokens=113400,research_max_model_calls=None)


def fixture(directory,url=URL):
    seed=News(id='B1',title='市场原有材料与口径',content=TEXT,source='公开网页可见正文-example',
              source_url='https://publisher.example/news/seed',published_at=NOW)
    workspace=EpisodeWorkspace([seed],root=directory,now=NOW)
    stock=dict(market='A',code='600900',name='长江电力')
    limits=Limits(model_calls=None,search_calls=11,body_urls=22,input_characters=108000,
                  local_read_characters=44000,output_tokens=3300,seconds=360)
    raw=b'<article>saved response</article>'
    key=hashlib.sha256(url.encode()).hexdigest()[:24]
    folder=workspace.path/'public-responses';folder.mkdir()
    (folder/(key+'.body')).write_bytes(raw)
    meta=dict(url=url,http_status=200,snapshot_cutoff=NOW.isoformat(),file=key+'.body',
        bytes=len(raw),body_sha256=hashlib.sha256(raw).hexdigest(),observed_at='2026-11-04T15:49:30')
    (folder/(key+'.json')).write_text(json.dumps(meta))
    state=dict(owner='finance-model-led-discovery-v1',status='failed_no_retry',phase='decode_model_response',
        error_code='discovery_duplicate_json_key',error_type='ValueError',started_at=NOW.isoformat(),watchlist=[stock],
        limits=limits.__dict__,budget_plan=dict(mode='progress_driven_collection',initial=limits.__dict__,
            ceiling=dict(limits.__dict__,search_calls=22,body_urls=64,input_characters=160000,
                local_read_characters=96000,seconds=882),total_input_characters=1964734,
            total_reserved_output_tokens=113400,model_request_cap=None),
        model_calls=2,model_input_characters=100672,reserved_output_tokens=6600,search_tool_calls=1,
        body_url_calls=2,local_read_characters=3,no_progress_turns=1,budget_expansions=[],
        event_followup_tasks=[],event_review_problems=[],provided_ids=['B1'],finish_feedback_history=[],
        candidates={'S1':dict(title=seed.title,url=seed.source_url,discovered_by=[dict(lane='us_market',purpose='latest_close')]),
                    'S2':dict(title='长江电力三季报',url=url,discovered_by=[dict(lane='company_event',purpose='company_event',scope='A:600900')])},
        decisions=['{"action":"tools"}','{"action":"finish","events":[{"lane":"company_event","lane":"company_event"}]}'],
        receipts=[dict(request=dict(tool='read',candidate_id='S1',relation='market'),
            result=dict(status='ok',material=workspace.read('B1'))),
            dict(request=dict(tool='read',candidate_id='S2',relation='direct',scope='A:600900',reason='核对主体'),
                result=dict(status='failed',reason='web_source_time_missing',response_capture='public-responses/'+key+'.json'))])
    result=dict(status='failed_no_retry',cutoff=NOW.isoformat(),finished_at='2026-11-04T15:50:44',research=state,
        model_exposures=[dict(completed_response=True,body_ranges={'B1':[[0,20]]}),dict(completed_response=True,body_ranges={})])
    (workspace.path/'primary-discovery.json').write_text(json.dumps(state))
    item=News(id='B2',title='长江电力披露财务变化',content=TEXT+'新增证据。',
        source='公开网页可见正文-example',source_url=url,published_at=NOW-timedelta(hours=110))
    return workspace,result,item


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.workspace,self.result,self.item=fixture(self.directory.name)
        self.parser=Mock(return_value=self.item)

    def prepare(self):return prepare_saved(self.result,self.workspace.path,self.parser)

    def test_recovers_in_memory_preserving_original_files_and_paid_counters(self):
        source=self.workspace.path
        before={str(p.relative_to(source)):p.read_bytes() for p in source.rglob('*') if p.is_file()}
        original=deepcopy(self.result)
        memory,state,digest=self.prepare()
        after={str(p.relative_to(source)):p.read_bytes() for p in source.rglob('*') if p.is_file()}
        self.assertEqual(before,after);self.assertEqual(self.result,original)
        self.assertEqual(state['model_calls'],2);self.assertEqual(state['body_url_calls'],2)
        self.assertEqual(state['search_tool_calls'],1)
        self.assertEqual(state['local_read_characters'],3+len(self.item.content))
        self.assertEqual(state['status'],'recovered_saved_materials')
        self.assertNotIn('dossier',state);self.assertNotIn('error_code',state)
        self.assertEqual(memory.now,NOW)
        validate_prepared(memory,state,digest)

    def test_prepared_recovery_restores_actual_exposure_not_new_body_delivery(self):
        memory,state,digest=self.prepare()
        restored,*_=restore_state(memory,state['watchlist'],dict(research=state,recovery_state_sha256=digest,
            model_exposures=self.result['model_exposures'],active_seconds=160,search_http_attempts=1),SimpleNamespace(**config()))
        self.assertEqual(restored['context_delivery']['body_ranges'],{'B1':[[0,20]]})
        self.assertEqual(restored['no_progress_turns'],0)
        self.assertEqual(restored['recovery']['original_no_progress_turns'],1)

    def test_mutated_prepared_usage_is_rejected(self):
        memory,state,digest=self.prepare();state['model_calls']=0
        with self.assertRaisesRegex(ValueError,'prepared_state_changed'):validate_prepared(memory,state,digest)

    def test_snapshot_recovery_supersedes_parser_cache_without_url_retry(self):
        memory,state,digest=self.prepare()
        cached=tool_caches(state)[1][URL]
        self.assertEqual(cached['status'],'ok');self.assertEqual(cached['material']['id'],'B2')
        self.assertEqual(state['collection_feedback']['watchlist'][0]['body_ids'],['B2'])

    def test_failed_http_path_is_not_reparsed_even_with_an_html_capture(self):
        self.result['research']['receipts'][1]['result']['reason']='public_http_403'
        (self.workspace.path/'primary-discovery.json').write_text(json.dumps(self.result['research']))
        memory,state,_=self.prepare()
        self.parser.assert_not_called();self.assertNotIn('B2',memory.documents)
        self.assertEqual(tool_caches(state)[1][URL]['reason'],'public_http_403')

    def test_peer_body_is_retained_without_direct_scope_or_automatic_industry_claim(self):
        self.item.title='华能水电财务变化与对比';self.item.content=TEXT+'长江电力作为同行对比。'
        memory,state,_=self.prepare()
        self.assertIn('B2',memory.documents)
        self.assertEqual(state['collection_feedback']['watchlist'][0]['body_ids'],[])
        self.assertIn('A:600900',state['collection_feedback']['candidate_reads']['S2']['rejected_scopes'])
        row=state['collection_feedback']['bodies']['B2']
        self.assertEqual(row['lanes'],[]);self.assertEqual(row['direct_scopes'],[])

    def test_disclosed_generated_article_is_not_added(self):
        self.item.content+='免责声明：本文基于AI生产，仅供参考。'
        memory,state,_=self.prepare()
        self.assertNotIn('B2',memory.documents)
        self.assertEqual(state['recovery']['rows'][0]['reason'],'disclosed_ai_generated_article')

    def test_capture_tampering_stops_before_parser(self):
        next((self.workspace.path/'public-responses').glob('*.body')).write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'capture_identity_changed'):self.prepare()
        self.parser.assert_not_called()

    def test_parser_cannot_substitute_a_different_source_url(self):
        self.item.source_url='https://other.example/news/item'
        with self.assertRaisesRegex(ValueError,'parser_url_changed'):self.prepare()

    def test_conflicting_duplicate_key_does_not_get_a_continuation(self):
        self.result['research']['decisions'][-1]='{"action":"finish","lane":"industry","lane":"company_event"}'
        with self.assertRaisesRegex(ValueError,'duplicate_json_key'):self.prepare()

    def test_incomplete_transport_is_not_repaired(self):
        self.result['model_exposures'][-1]['completed_response']=False
        with self.assertRaisesRegex(ValueError,'complete_response_missing'):self.prepare()

    def test_another_failure_cannot_use_recovery(self):
        self.result['research']['error_code']='discovery_action_invalid'
        with self.assertRaisesRegex(ValueError,'stop_not_supported'):self.prepare()

    def test_no_room_for_local_read_does_not_reset_the_budget(self):
        self.result['research']['local_read_characters']=44000
        (self.workspace.path/'primary-discovery.json').write_text(json.dumps(self.result['research']))
        memory,state,_=self.prepare()
        self.assertEqual(state['local_read_characters'],44000)
        self.assertNotIn('B2',memory.documents)
        self.assertEqual(state['no_progress_turns'],1)


class RoleTests(unittest.TestCase):
    def item(self,title,url='https://publisher.example/news/item'):
        return News(id='X',title=title,content=TEXT,source='公开网页可见正文-example',source_url=url,published_at=NOW)

    def test_morning_report_can_support_background_but_not_close_or_settlement(self):
        item=self.item('Gold prices and risks - Kitco AM Report')
        self.assertFalse(lane_allowed(item,'commodities'))
        self.assertFalse(lane_allowed(item,'us_market'))
        self.assertTrue(lane_allowed(item,'industry'))

    def test_bank_commentary_cannot_be_original_central_bank_release(self):
        item=self.item('FX Daily Snapshot','https://www.mufgresearch.com/fx/snapshot')
        self.assertFalse(assess_role(item)['original_policy_release_allowed'])
        self.assertFalse(lane_allowed(item,'global_policy'))

    def test_a_completed_close_title_is_not_automatically_verified(self):
        role=assess_role(self.item('US stocks close higher as sectors diverge'))
        self.assertTrue(role['latest_close_allowed']);self.assertFalse(role['session_verified'])

    def test_policy_preview_is_not_decision_confirmation(self):
        self.assertFalse(lane_allowed(self.item('Federal Reserve decision preview'),'global_policy'))

    def test_report_import_rechecks_roles_instead_of_trusting_coverage_labels(self):
        from test_primary_report import source,discovery,NOW as cutoff
        from app.services.primary_report import export_discovery,prepare
        item=source();item.title='US stocks morning report'
        with tempfile.TemporaryDirectory() as directory:
            workspace=EpisodeWorkspace([item],root=directory,now=cutoff)
            value=export_discovery(workspace,discovery(workspace))
            with self.assertRaisesRegex(ValueError,'material_role_mismatch'):prepare(value,now=cutoff)


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_resumed_request_contains_recovered_body_without_search_or_fetch(self):
        from app.config import settings
        with tempfile.TemporaryDirectory() as directory:
            workspace,result,item=fixture(directory)
            memory,state,digest=prepare_saved(result,workspace.path,Mock(return_value=item))
            memory.path=Path(directory)/'continued';memory.path.mkdir()
            model=AsyncMock(side_effect=RuntimeError('stop after observing request'))
            search,read=Mock(),Mock()
            with patch.multiple(settings,**config()):
                with self.assertRaisesRegex(RuntimeError,'stop after observing request'):
                    await discover(memory,state['watchlist'],resume=dict(research=state,recovery_state_sha256=digest,
                        model_exposures=result['model_exposures'],active_seconds=160,search_http_attempts=1),
                        model=model,search=search,read=read)
            search.assert_not_called();read.assert_not_called()
            self.assertIn('新增证据。',model.call_args.args[1][0]['content'])


PATH=Path(__file__).resolve().parents[2]/'tools/continue_recovered_collection.py'
SPEC=importlib.util.spec_from_file_location('recovered_collection_test_runner',PATH)
runner=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(runner)


class AccountingTests(unittest.TestCase):
    def fixture(self):
        base=SimpleNamespace(OWNER='owner',fingerprint=fingerprint)
        prior=dict(watchlist=[],budget_plan={'same':'plan'},continuation={'proof':'original'},
            model_http_attempts=2,model_input_characters=100672,reserved_output_tokens=6600,search_http_attempts=9,
            public_fetch_attempts=6,cutoff=NOW.isoformat(),started_at='2026-11-01T13:56:44',
            finished_at='2026-11-01T13:57:57',research=dict(body_url_calls=6,local_read_characters=2407))
        resume=dict(source_result_sha256='old-result',source_cutoff=NOW.isoformat(),prior_segment_active_seconds=73,
            prior_segment_model_calls=2,prior_segment_public_fetch_attempts=6)
        value=dict(watchlist=[],budget_plan=prior['budget_plan'],environment=dict(resume=resume))
        result=dict(owner='owner',status='failed_no_retry',finished_at='2026-11-04T15:50:44.332700',
            pause_preserved=True,input_sha256=fingerprint(value),started_at='2026-11-04T15:49:18.145077',
            watchlist=[],budget_plan=prior['budget_plan'],continuation=prior['continuation'],resume=resume,
            model_http_attempts=8,model_input_characters=504776,reserved_output_tokens=26400,search_http_attempts=10,
            public_fetch_attempts=17,cutoff=NOW.isoformat(),
            research=dict(model_calls=8,model_input_characters=504776,reserved_output_tokens=26400,search_tool_calls=10,
                body_url_calls=17,local_read_characters=5508))
        marker=dict(owner='owner',input_sha256=result['input_sha256'],started_at=result['started_at'])
        return result,value,marker,prior,base

    def test_deducts_both_active_segments_without_counting_days_waiting(self):
        args=self.fixture();self.assertEqual(runner.verify_latest(*args),160)

    def test_usage_cannot_move_backwards(self):
        args=self.fixture();args[0]['model_http_attempts']=1;args[0]['research']['model_calls']=1
        with self.assertRaises(ValueError):runner.verify_latest(*args)

    def test_changed_marker_blocks_continuation(self):
        args=self.fixture();args[2]['input_sha256']='wrong'
        with self.assertRaises(ValueError):runner.verify_latest(*args)

    def test_changed_budget_plan_does_not_reissue_usage(self):
        args=self.fixture();args[0]['budget_plan']={'bigger':'plan'}
        with self.assertRaises(ValueError):runner.verify_latest(*args)
