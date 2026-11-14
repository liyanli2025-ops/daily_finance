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

    async def run_fake(self, root, fail_review=False, missing_change_checks=False):
        import test_unified_edition as reference
        sample,stages,written=await reference.PipelineRegression().scenario(root/'fake',fail_review=fail_review)
        condition='若政策未按已披露条件实施就撤回传导判断。'
        written['body'] += condition; written['script'] += condition
        written['listener_cards'] = [dict(judgment='保留条件', source_id='body-1',
            fact_quote=reference.FACT, report_quote=reference.FACT,
            mechanism='政策可能影响经营，需要实际实施印证',
            alternative='也可能只改变短期情绪，尚缺定价数据',
            horizon='下一次正式实施披露', invalidation=condition)]
        written['stock_followups'] = []
        async def model(task,messages,limit):
            raw=await sample.model(task,messages,limit)
            reply=json.loads(raw)
            if len(stages)==2 and not missing_change_checks:
                # These are explicit fake editorial responses to the finite
                # fake searches below. Production validators remain enabled.
                from app.services.daily_changes import tasks
                reply['change_checks'] = [dict(task_id=t['id'],
                    status='supported' if t['id']=='politics' else 'screened_no_material_event',
                    reason=('示例正文仅支持政策已公布及适用条件，不作独立核验'
                        if t['id']=='politics' else '本次有限模拟检索只取得政策样例，未选出该类实质变化'),
                    evidence=[dict(source_id='body-1',quote=reference.FACT)]
                        if t['id']=='politics' else []) for t in tasks(sample.state)]
                reply['expectation_checks'] = []
            if task=='review':
                reply['listener_checks'] = [dict(criterion=c,status='supported',
                    reason='已核对模拟正文和口播中的条件边界',
                    report_quote=reference.FACT,script_quote=reference.FACT) for c in
                    ('evidence','causality','company_relevance','time_and_units','countercase_and_falsifier')]
            return json.dumps(reply,ensure_ascii=False)
        prepared=dict(ready_to_run=True,watchlist=[],policy=copy.deepcopy(sample.state['policy']),
            environment_sha256='env',execution_sha256='frozen')
        prepared['policy'].update(estimated_limit_usd='1',audio_enabled=False,
            edition_forecast='remaining_stages_v1',
            request_input_pricing=dict(analysis='uncached_request_v1',review='uncached_request_v1'))
        real_class=entry.core.EditionPipeline
        def pipeline(state,directory,workspace,check):
            self.assertTrue(state['manual_text_only'])
            self.assertEqual(state['research_protocol'],'listener_research_v1')
            self.assertEqual(state['change_protocol'],'daily_changes_v1')
            return real_class(state,directory,workspace,model=model,
                search=sample.search,read=sample.read,check=check)
        with patch.object(entry,'require_pause'),patch.object(entry,'identity',return_value='frozen'),\
                patch.object(entry,'preview',AsyncMock(return_value=prepared)),\
                patch.object(entry,'assert_watchlist_current',AsyncMock()),\
                patch.object(entry.core,'EditionPipeline',side_effect=pipeline),\
                patch('app.services.edition_market.collect',return_value=dict(status='unavailable',
                    indices=[],breadth={},gaps=['离线测试不提供行情，不作行情结论'])) as market:
            result,path,reused=await entry.run_once(config(),root=root/'editions')
            second,second_path,second_reused=await entry.run_once(config(),root=root/'editions')
        market.assert_called_once()
        self.assertFalse(result.get('issuer_http_receipts'))
        self.assertFalse(reused);self.assertTrue(second_reused)
        self.assertEqual(second['id'],result['id']);self.assertEqual(path,second_path)
        return result,path,stages

    async def test_shared_pipeline_runs_four_stages_and_duplicate_does_not_pay(self):
        with tempfile.TemporaryDirectory() as temporary:
            result,path,stages=await self.run_fake(Path(temporary))
            self.assertEqual(result['status'],'reviewed_text')
            self.assertEqual(len(stages),4)
            self.assertEqual({r['task_id'] for r in result['assessment']['change_checks']},
                {'politics','industry','operations','governance','market'})
            self.assertEqual(len(result['review']['listener_checks']),5)
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

    async def test_missing_change_checks_still_stops_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            result,path,stages=await self.run_fake(Path(temporary),missing_change_checks=True)
            self.assertEqual(result['status'],'failed')
            self.assertEqual(result['error_code'],'edition_change_checks_missing')
            self.assertNotIn('draft',result)
            self.assertEqual(len(stages),2)
            self.assertEqual(len([r for r in result['reservations'] if r['kind']=='model']),2)

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
        request,_=search_request('market closing','latest_close',datetime(2026,11,1,11),topic='news')
        # The actual successful historical probe predates three added exclusions.
        request['exclude_domains'] = request['exclude_domains'][:6]
        owner='finance-search-contract-diagnostic-v1'
        prepared=dict(owner=owner,prepared_at='2026-11-01T11:00:00',credential_fingerprint=credential,
                      revised_request_parameters=request,
                      previous_request_parameters=dict(request,time_range='week'))
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
            self.assertIsNotNone(proof)
            for target in (blocked,folder/'result.json'):
                before=target.read_bytes();target.write_bytes(before+b' ')
                with manual.manual_text_scope(IDENTIFIER,cfg,search_proof=proof):
                    with self.assertRaises(RetiredSourceError):manual.ensure_search_active(root/'data/research',key)
                target.write_bytes(before)

    def test_other_account_or_newer_failure_cannot_use_old_proof(self):
        from pydantic import SecretStr
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);cfg,key,blocked,folder=self.evidence(root)
            self.assertIsNotNone(manual.reviewed_search_permission(cfg,backend=root))
            other=cfg.model_copy(update=dict(research_web_search_api_key=SecretStr('other-offline-key')))
            self.assertIsNone(manual.reviewed_search_permission(other,backend=root))
            value=json.loads(blocked.read_text());value['at']='2026-11-02T10:00:00'
            blocked.write_text(json.dumps(value))
            self.assertIsNone(manual.reviewed_search_permission(cfg,backend=root))

    def update_signed_request(self, folder, mutate):
        prepared=json.loads((folder/'input.json').read_text())
        request=prepared['revised_request_parameters'];mutate(request)
        prepared['previous_request_parameters']=dict(request,time_range='week')
        marker=json.loads((folder/'started.json').read_text())
        marker['input_sha256']=hashlib.sha256(json.dumps(prepared,ensure_ascii=False,
            sort_keys=True,separators=(',',':')).encode()).hexdigest()
        result=json.loads((folder/'result.json').read_text())
        result['diagnostics']['request_parameters']=request
        for name,value in [('input.json',prepared),('started.json',marker),('result.json',result)]:
            (folder/name).write_text(json.dumps(value))

    def test_relative_window_cannot_reuse_the_absolute_window_repair(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);cfg,key,blocked,folder=self.evidence(root)
            def relative(request):
                request.pop('start_date');request.pop('end_date');request['time_range']='week'
            self.update_signed_request(folder,relative)
            self.assertIsNone(manual.reviewed_search_permission(cfg,backend=root))

    def test_other_request_parameters_cannot_be_relaxed_by_a_signed_proof(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);cfg,key,blocked,folder=self.evidence(root)
            self.update_signed_request(folder,lambda request:request.update(search_depth='advanced'))
            self.assertIsNone(manual.reviewed_search_permission(cfg,backend=root))


class AssessmentEvidenceTests(unittest.TestCase):
    """Reuse delivered text without bypassing quotes, roles or company checks."""
    def sample(self):
        from app.services import edition_contract as contract
        source = dict(id='B1', event_ids=['E1'], text='政策已公布，\n实施仍有条件。\n行业价格回落。',
                      direct_scopes=[], source_role={})
        events = {eid: dict(purpose='discovery', importance='major') for eid in ('E1', 'E2')}
        value = dict(events=[dict(id=eid, status='ready', reason='以对应正文及边界为准',
            evidence=[dict(source_id='B1', quote='政策已公布，实施仍有条件。' if eid == 'E1' else '行业价格回落。')])
            for eid in events], watchlist_checks=[], additional_reads=[], additional_searches=[],
            missed_major_events=[])
        return contract, value, events, {'B1': source}

    def prepare(self, value=None, events=None, sources=None, provided=None, stocks=None):
        c, v, e, s = self.sample()
        return c.prepare_assessment(value if value is not None else v,
            events if events is not None else e, sources if sources is not None else s,
            stocks or set(), {'B1'} if provided is None else provided)

    def test_explicit_other_event_quote_reuses_delivered_body_without_new_source(self):
        accepted, sources, validation = self.prepare()
        self.assertEqual(validation['missing'], [])
        self.assertEqual(sources['B1']['event_ids'], ['E1', 'E2'])
        self.assertEqual(len(sources), 1)
        self.assertFalse(validation['reused_body_event_links'][0]['independent_verification'])

    def test_layout_linebreak_restored_to_exact_original_substring(self):
        c, _, _, _ = self.sample()
        accepted, sources, validation = self.prepare()
        evidence = accepted['events'][0]['evidence'][0]['quote']
        self.assertEqual(evidence, '政策已公布，\n实施仍有条件。')
        c.quote(evidence, sources['B1']['text'])
        self.assertEqual(len(validation['restored_source_quotes']), 1)

    def test_invalid_quote_is_missing_not_rewritten_or_silently_dropped(self):
        _, value, _, _ = self.sample()
        value['events'][1]['evidence'][0]['quote'] = '行业价格大涨。'
        accepted, sources, validation = self.prepare(value=value)
        self.assertEqual(validation['missing'], ['E2'])
        self.assertEqual(accepted['events'][1]['status'], 'missing')
        self.assertEqual(accepted['events'][1]['evidence'], [])
        self.assertEqual(sources['B1']['event_ids'], ['E1'])
        self.assertEqual(validation['issues'][0]['problems'][0]['code'], 'edition_quote_not_found')

    def test_valid_part_of_invalid_event_does_not_attach_other_event(self):
        _, value, _, _ = self.sample()
        value['events'][1]['evidence'].append(dict(source_id='B1', quote='不存在的句子。'))
        _, sources, validation = self.prepare(value=value)
        self.assertEqual(sources['B1']['event_ids'], ['E1'])
        self.assertEqual(validation['missing'], ['E2'])

    def test_undelivered_body_cannot_be_evidence_even_with_exact_quote(self):
        accepted, _, validation = self.prepare(provided=set())
        self.assertEqual(validation['missing'], ['E1', 'E2'])
        self.assertTrue(all(r['status'] == 'missing' for r in accepted['events']))

    def test_unknown_source_is_a_material_gap(self):
        _, value, _, _ = self.sample()
        value['events'][1]['evidence'][0]['source_id'] = 'invented'
        _, _, validation = self.prepare(value=value)
        self.assertEqual(validation['missing'], ['E2'])
        self.assertEqual(validation['issues'][0]['problems'][0]['code'], 'edition_evidence_not_delivered')

    def test_commentary_reuse_does_not_become_original_policy(self):
        _, _, events, sources = self.sample()
        events['E2']['purpose'] = 'released_policy'
        sources['B1']['source_role']['original_policy_release_allowed'] = False
        _, sources, validation = self.prepare(events=events, sources=sources)
        self.assertEqual(validation['missing'], ['E2'])
        self.assertEqual(sources['B1']['event_ids'], ['E1'])

    def test_peer_or_market_summary_cannot_become_direct_company_evidence(self):
        _, value, _, _ = self.sample()
        value['watchlist_checks'] = [dict(key='A:600900', status='covered', reason='标题仅为行业综述',
            evidence=[dict(source_id='B1', quote='行业价格回落。')])]
        accepted, sources, validation = self.prepare(value=value, stocks={'A:600900'})
        self.assertEqual(accepted['watchlist_checks'][0]['status'], 'missing')
        self.assertEqual(validation['missing'], ['A:600900'])
        self.assertEqual(sources['B1']['direct_scopes'], [])

    def test_split_number_and_english_word_are_not_joined(self):
        c, _, _, _ = self.sample()
        for candidate, raw in [('100', '1\n00'), ('interest', 'inter\nest'),
                               ('10元', '10\n元')]:
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, 'quote_not_found'):
                c._source_quote(candidate, raw)

    def test_changed_negation_cannot_pass_layout_matching(self):
        c, _, _, _ = self.sample()
        with self.assertRaisesRegex(ValueError, 'quote_not_found'):
            c._source_quote('政策已公布，实施没有条件。', '政策已公布，\n实施仍有条件。')

    def test_original_response_and_sources_are_unchanged(self):
        c, value, events, sources = self.sample()
        before = copy.deepcopy((value, sources))
        c.prepare_assessment(value, events, sources, set(), {'B1'})
        self.assertEqual((value, sources), before)

    def test_missing_event_is_still_a_hard_protocol_error(self):
        _, value, _, sources = self.sample()
        before = copy.deepcopy(sources)
        value['events'].pop()
        with self.assertRaisesRegex(ValueError, 'event_disappeared'):
            self.prepare(value=value, sources=sources)
        self.assertEqual(sources, before)

    def test_second_validation_does_not_invent_more_links(self):
        c, _, events, _ = self.sample()
        accepted, sources, _ = self.prepare()
        again, reused, validation = c.prepare_assessment(accepted, events, sources, set(), {'B1'})
        self.assertEqual(again, accepted)
        self.assertEqual(reused, sources)
        self.assertEqual(validation['reused_body_event_links'], [])

    def test_pipeline_rejects_changed_body_after_saved_delivery(self):
        from app.services.edition_budget import digest
        _, value, events, sources = self.sample()
        pipeline = entry.core.EditionPipeline.__new__(entry.core.EditionPipeline)
        pipeline.state = dict(phase='assessment', sources=sources,
            delivered_sources={'assessment': {'B1': digest('other body')}})
        pipeline.save = lambda: None
        accepted, missing = pipeline.validate_assessment(value, events, set())
        self.assertEqual(missing, ['E1', 'E2'])
        self.assertEqual(pipeline.state['sources']['B1']['event_ids'], ['E1'])
        self.assertEqual(accepted['events'][0]['status'], 'missing')

    def test_summary_does_not_present_unfinished_missing_check_as_complete(self):
        with patch.object(entry, 'MODEL_PAUSE_FILE', Path(__file__)):
            result = entry.summary(dict(id=IDENTIFIER, status='failed', cutoff='2026-11-14',
                policy={'estimated_limit_usd': '1'}, agenda={'events': [dict(id='E1', title='待核线索', importance='major')]}),
                Path('unused'))
        self.assertIsNone(result['missing'])
        self.assertFalse(result['missing_assessed'])
        self.assertEqual(result['events'][0]['evidence_status'], 'not_assessed')
        self.assertFalse(result['events'][0]['fact_verified'])
