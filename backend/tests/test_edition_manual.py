"""Offline boundaries for the one-shot entry; all provider calls are fakes."""
import asyncio
import copy
import json
import hashlib
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app import edition_once as entry
from app.config import settings
from app.services import edition_manual as manual, model_gateway as gateway
from app.services.model_usage import edition_model_scope, reserve_call

PRICES = dict(model_prices={'ofox_anthropic/anthropic/claude-sonnet-5.5':
    dict(input='2', output='10', cache_read='.2', cache_write='4')},
    search_price_usd='.008', estimated_limit_usd='.50')
IDENTIFIER = 'edition-' + 'b' * 32


def config():
    original = settings.model_copy(update=dict(model_http_retries=0,
        report_auto_repair_enabled=False, edition_estimate_accepted=False,
        edition_audio_enabled=True, research_web_search_enabled=False))
    return entry.accepted_config(PRICES, '1', original)


class ManualPermissionTests(unittest.IsolatedAsyncioTestCase):
    def test_acceptance_is_only_on_a_copy_and_audio_is_disabled(self):
        original = settings.model_copy(update=dict(model_http_retries=0,
            report_auto_repair_enabled=False, edition_estimate_accepted=False,
            edition_audio_enabled=True, research_web_search_enabled=False))
        before = original.model_dump()
        accepted = entry.accepted_config(PRICES, '1', original)
        self.assertEqual(original.model_dump(), before)
        self.assertEqual(accepted.edition_estimated_limit_usd, '1')
        self.assertTrue(accepted.edition_estimate_accepted)
        self.assertTrue(accepted.research_web_search_enabled)
        self.assertFalse(accepted.edition_audio_enabled)

    def test_invalid_money_and_retry_settings_cannot_start(self):
        for amount in ('0', '-1', 'NaN'):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                entry.accepted_config(PRICES, amount, settings)
        for overrides in (dict(model_http_retries=1), dict(report_auto_repair_enabled=True)):
            with self.assertRaisesRegex(ValueError, 'budget_or_retry_invalid'):
                entry.accepted_config(PRICES, '1', config().model_copy(update=overrides))

    def test_unreserved_and_other_run_model_requests_remain_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            flag=Path(temporary)/'pause';flag.touch()
            with patch.object(gateway,'MODEL_PAUSE_FILE',flag), manual.manual_text_scope(IDENTIFIER,config()):
                with self.assertRaises(RuntimeError):gateway.ensure_models_enabled()
                with edition_model_scope('edition-'+'c'*32,'writing',lambda row:None,lambda:None):
                    with self.assertRaises(RuntimeError):gateway.ensure_models_enabled()

    def test_only_the_reserved_stage_can_send_one_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            flag=Path(temporary)/'pause';flag.touch()
            starts=[]
            with patch.object(gateway,'MODEL_PAUSE_FILE',flag), manual.manual_text_scope(IDENTIFIER,config()):
                with edition_model_scope(IDENTIFIER,'writing',lambda row:None,lambda:starts.append(True)):
                    gateway.ensure_models_enabled();reserve_call()
                    with self.assertRaises(RuntimeError):gateway.ensure_models_enabled()
                    with self.assertRaises(RuntimeError):reserve_call()
                with edition_model_scope(IDENTIFIER,'podcast',lambda row:None,lambda:None):
                    with self.assertRaises(RuntimeError):gateway.ensure_models_enabled()
            self.assertEqual(starts,[True])

    def test_scope_reset_keeps_the_global_pause(self):
        with tempfile.TemporaryDirectory() as temporary:
            flag=Path(temporary)/'pause';flag.touch()
            with patch.object(gateway,'MODEL_PAUSE_FILE',flag):
                with self.assertRaisesRegex(ValueError,'intentional'):
                    with manual.manual_text_scope(IDENTIFIER,config()):raise ValueError('intentional')
                self.assertFalse(manual.active())
                self.assertIs(manual.current_config(settings),settings)
                with self.assertRaises(RuntimeError):gateway.ensure_models_enabled()
                self.assertTrue(flag.is_file())

    def test_pause_removal_does_not_resume_a_manual_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            flag=Path(temporary)/'not-created'
            with patch.object(gateway,'MODEL_PAUSE_FILE',flag), manual.manual_text_scope(IDENTIFIER,config()):
                with edition_model_scope(IDENTIFIER,'review',lambda row:None,lambda:None):
                    with self.assertRaises(RuntimeError):gateway.ensure_models_enabled()

    async def test_search_thread_receives_only_the_process_local_copy(self):
        accepted=config()
        with manual.manual_text_scope(IDENTIFIER,accepted):
            self.assertIs(await asyncio.to_thread(manual.current_config,settings),accepted)
        self.assertIs(manual.current_config(settings),settings)

    async def test_preview_removes_only_pause_and_keeps_money_and_source_blockers(self):
        prepared=dict(watchlist=[],blockers=['maintenance_paused','estimated_limit_below_initial_batch_and_model_plan'],
            ready_to_run=False,model_requests=0,search_requests=0)
        with patch.object(entry,'require_pause'),patch.object(entry.core,'preflight',AsyncMock(return_value=prepared)),\
                patch.object(entry,'identity',return_value='frozen'),\
                patch.object(entry,'search_availability',return_value=dict(available=False,reason='search_route_paused_no_auto_retest')):
            result=await entry.preview(config())
        self.assertFalse(result['ready_to_run'])
        self.assertEqual(result['blockers'],['estimated_limit_below_initial_batch_and_model_plan','search_route_paused_no_auto_retest'])
        self.assertFalse(result['live_settings_changed'])


class ManualExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_preview_blocker_stops_before_marker_or_paid_pipeline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            with patch.object(entry,'require_pause'),\
                    patch.object(entry,'preview',AsyncMock(return_value=dict(ready_to_run=False,blockers=['money']))),\
                    patch.object(entry.core,'EditionPipeline') as pipeline:
                result,path,reused=await entry.run_once(config(),root=root)
            pipeline.assert_not_called()
            self.assertIsNone(path)
            self.assertFalse(reused)
            self.assertEqual(list(root.glob('*.started')),[])

    async def run_fake(self, root, fail_review=False):
        import test_unified_edition as reference
        sample,stages,_=await reference.PipelineRegression().scenario(root/'fake',fail_review=fail_review)
        prepared=dict(ready_to_run=True,watchlist=[],policy=copy.deepcopy(sample.state['policy']),
            environment_sha256='env',execution_sha256='frozen')
        prepared['policy'].update(estimated_limit_usd='1',audio_enabled=False,
            edition_forecast='remaining_stages_v1',
            request_input_pricing=dict(analysis='uncached_request_v1',review='uncached_request_v1'))
        real_class=entry.core.EditionPipeline
        def pipeline(state,directory,workspace,check):
            self.assertTrue(state['manual_text_only'])
            return real_class(state,directory,workspace,model=sample.model,
                search=sample.search,read=sample.read,check=check)
        with patch.object(entry,'require_pause'),patch.object(entry,'identity',return_value='frozen'),\
                patch.object(entry,'preview',AsyncMock(return_value=prepared)),\
                patch.object(entry,'assert_watchlist_current',AsyncMock()),\
                patch.object(entry.core,'EditionPipeline',side_effect=pipeline):
            result,path,reused=await entry.run_once(config(),root=root/'editions')
            second,second_path,second_reused=await entry.run_once(config(),root=root/'editions')
        self.assertFalse(reused);self.assertTrue(second_reused)
        self.assertEqual(second['id'],result['id']);self.assertEqual(path,second_path)
        return result,path,stages

    async def test_shared_pipeline_runs_four_stages_and_duplicate_does_not_pay(self):
        with tempfile.TemporaryDirectory() as temporary:
            result,path,stages=await self.run_fake(Path(temporary))
            self.assertEqual(result['status'],'reviewed_text')
            self.assertEqual(len(stages),4)
            self.assertEqual(len(result['sources']),1)
            self.assertFalse(result['app_written'])
            self.assertNotIn('tts_attempts',result)

    async def test_failed_review_keeps_draft_and_cannot_auto_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            result,path,stages=await self.run_fake(Path(temporary),fail_review=True)
            self.assertEqual(result['status'],'failed')
            self.assertIn('draft',result)
            self.assertEqual(len(stages),4)
            self.assertEqual(len([r for r in result['reservations'] if r['kind']=='model']),4)

    def test_export_is_offline_idempotent_and_contains_the_material(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);folder=root/'edition';folder.mkdir()
            (folder/'result.json').write_text(json.dumps(dict(id=IDENTIFIER)))
            (folder/'receipt.txt').write_text('正文、缺口、用量')
            target=root/'review.zip'
            entry.export_review(folder,target);before=target.read_bytes()
            entry.export_review(folder,target)
            self.assertEqual(target.read_bytes(),before)
            (folder/'result.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'other_result'):entry.export_review(folder,target)


class ReviewedSearchProofTests(unittest.TestCase):
    def evidence(self, root):
        from pydantic import SecretStr
        from app.services.web_research import search_request
        from app.services.source_health import state_path
        cfg=config().model_copy(update=dict(research_web_search_api_key=SecretStr('offline-fake-key')))
        credential=hashlib.sha256(b'offline-fake-key').hexdigest()
        route='research-web-search:tavily:v1:'+credential[:12]
        request,_=search_request('market policy','discovery',datetime(2026,11,1,11),topic='news')
        owner='finance-search-contract-diagnostic-v1'
        prepared=dict(owner=owner,prepared_at='2026-11-01T11:00:00',credential_fingerprint=credential,
                      revised_request_parameters=request)
        fingerprint=hashlib.sha256(json.dumps(prepared,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        result=dict(owner=owner,status='search_http_accepted_pending_review',
            diagnostics=dict(http_status=200,request_parameters=request),search_http_attempts=1,
            model_requests=0,public_fetch_attempts=0,tts_requests=0,pause_preserved=True)
        marker=dict(owner=owner,input_sha256=fingerprint,started_at='2026-11-01T11:01:00')
        folder=root/'data/diagnostics/search-contract-diagnostic-v1';folder.mkdir(parents=True)
        for name,value in [('input.json',prepared),('result.json',result),('started.json',marker)]:
            (folder/name).write_text(json.dumps(value))
        blocked=state_path(root/'data/research',route);blocked.parent.mkdir(parents=True)
        blocked.write_text(json.dumps(dict(status='paused',automatic_retest=False,
            detail_code='http_400',at='2026-11-01T10:00:00')))
        return cfg,route,blocked,folder

    def test_valid_proof_is_same_account_and_does_not_remove_block(self):
        from app.services.source_health import RetiredSourceError
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);cfg,key,blocked,_=self.evidence(root)
            proof=manual.reviewed_search_permission(cfg,backend=root)
            self.assertIsNotNone(proof)
            with self.assertRaises(RetiredSourceError):manual.ensure_search_active(root/'data/research',key)
            with manual.manual_text_scope(IDENTIFIER,cfg,search_proof=proof):
                manual.ensure_search_active(root/'data/research',key)
            self.assertTrue(blocked.is_file())

    def test_changed_failure_or_diagnostic_revokes_permission(self):
        from app.services.source_health import RetiredSourceError
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);cfg,key,blocked,folder=self.evidence(root)
            proof=manual.reviewed_search_permission(cfg,backend=root)
            for target in (blocked,folder/'result.json'):
                before=target.read_bytes();target.write_bytes(before+b' ')
                with manual.manual_text_scope(IDENTIFIER,cfg,search_proof=proof):
                    with self.assertRaises(RetiredSourceError):manual.ensure_search_active(root/'data/research',key)
                target.write_bytes(before)

    def test_other_account_or_newer_failure_cannot_use_old_proof(self):
        from pydantic import SecretStr
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);cfg,key,blocked,folder=self.evidence(root)
            other=cfg.model_copy(update=dict(research_web_search_api_key=SecretStr('other-offline-key')))
            self.assertIsNone(manual.reviewed_search_permission(other,backend=root))
            value=json.loads(blocked.read_text());value['at']='2026-11-02T10:00:00'
            blocked.write_text(json.dumps(value))
            self.assertIsNone(manual.reviewed_search_permission(cfg,backend=root))
