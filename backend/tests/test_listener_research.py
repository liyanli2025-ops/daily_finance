"""Research usefulness and direct-source boundaries, with no provider requests."""
import copy
from datetime import datetime
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch
from types import SimpleNamespace

from app.services.edition_issuer_desk import IssuerDesk, LIST_URL, BODY_URL, PROTOCOL
from app.services.listener_research import brief, requirements, validate_draft, validate_review, restrict_baselines
from app.services.edition_context import packet
from app.services.edition_inputs import editorial_forecast, messages_for
from app.services.edition_pipeline import EditionPipeline, initial_searches
import test_unified_edition as reference

STOCK = dict(market='A', code='002714', name='牧原股份')
NOW = datetime(2026, 11, 14, 9)
FACT = '公司披露每公斤养殖成本下降。'
CONDITION = '若下月单位成本回升就撤回成本改善判断。'


def listener_state():
    state = reference.state()
    state.update(research_protocol=PROTOCOL, watchlist=[STOCK], cutoff=NOW.isoformat())
    state['policy']['max_body_urls'] = 20
    return state


def draft():
    return dict(core_opinions=['成本改善需要持续观察'], body='牧原股份：' + FACT + CONDITION, script='牧原股份：' + FACT + CONDITION,
        listener_cards=[dict(judgment='成本改善需要持续观察', source_id='B1', fact_quote=FACT,
            report_quote=FACT, mechanism='单位成本变化可能影响养殖毛利，仍需售价和销量印证',
            alternative='也可能是短期饲料价格变化而非效率提升', horizon='下月经营披露', invalidation=CONDITION)],
        stock_followups=[dict(key='A:002714', status='supported', reason='本期只判断单位成本，不能据此断定盈利质量',report_quote='牧原股份：' + FACT,
            variables=['单位成本', '销售价格', '经营现金流'], next_check='下月经营数据披露后与售价同步核对', source_ids=['B1'])])


def sources():
    return {'B1': dict(id='B1', text=FACT, scope='A:002714', direct_scopes=['A:002714'],
        metadata={'kind': 'primary_notice'})}


class ListenerContracts(unittest.TestCase):
    def test_business_questions_follow_profile_instead_of_stock_code(self):
        state = listener_state()
        state['company_baselines'] = {'A:002714': dict(profile={'industry':'测试行业', 'fields':['合同负债变化']})}
        self.assertEqual(brief(state)['company_questions'][0]['research_variables'], ['合同负债变化'])

    def test_missing_profile_does_not_guess_company_industry(self):
        item = brief(listener_state())['company_questions'][0]
        self.assertIsNone(item['industry'])
        self.assertEqual(item['business_profile_status'], 'missing')
        self.assertNotIn('单位成本', item['research_variables'])

    def test_legacy_state_does_not_change_contract(self):
        validate_draft({}, {}, {})
        validate_review({}, {})
        self.assertEqual(brief({}), {})
        self.assertEqual(requirements('writing', {}), '')

    def test_one_anchored_judgment_and_all_stock_followups_are_accepted(self):
        validate_draft(listener_state(), draft(), sources())

    def test_wrong_fact_quote_is_rejected(self):
        value = draft(); value['listener_cards'][0]['fact_quote'] = '经营现金流显著增长'
        with self.assertRaisesRegex(ValueError, 'analysis_incomplete'):
            validate_draft(listener_state(), value, sources())

    def test_falsifier_must_be_heard_not_only_in_internal_card(self):
        value = draft(); value['script'] = FACT
        with self.assertRaisesRegex(ValueError, 'analysis_incomplete'):
            validate_draft(listener_state(), value, sources())

    def test_cannot_drop_a_stock_or_replace_its_evidence_with_peer(self):
        value = draft(); value['stock_followups'] = []
        with self.assertRaisesRegex(ValueError, 'followup_missing'):
            validate_draft(listener_state(), value, sources())
        value = draft(); pool = sources(); pool['B1']['scope'] = 'A:600900'; pool['B1']['direct_scopes'] = []
        with self.assertRaisesRegex(ValueError, 'followup_invalid'):
            validate_draft(listener_state(), value, pool)

    def test_missing_company_material_can_be_honestly_labeled(self):
        value = draft(); row = value['stock_followups'][0]
        row.update(status='insufficient', source_ids=[], reason='只读到行业报道，缺公司直接披露，暂不判断公司变化')
        validate_draft(listener_state(), value, sources())

    def test_review_cannot_pass_without_five_checks_or_spoken_anchors(self):
        state = listener_state(); state['draft'] = draft()
        with self.assertRaisesRegex(ValueError, 'review_missing'):
            validate_review(state, dict(passed=True))
        rows = [dict(criterion=c, status='supported', reason='已核对原文及适用范围', report_quote=FACT, script_quote=FACT)
            for c in ('evidence','causality','company_relevance','time_and_units','countercase_and_falsifier')]
        validate_review(state, dict(listener_checks=rows))
        rows[0]['script_quote'] = '口播没有这句话'
        with self.assertRaisesRegex(ValueError, 'review_not_passed'):
            validate_review(state, dict(listener_checks=rows))

    def test_financial_baseline_cannot_fill_current_event_or_stock_gap(self):
        value = dict(events=[dict(id='E1',status='ready',evidence=[dict(source_id='B1')])],
            watchlist_checks=[dict(key='A:002714',status='covered',evidence=[dict(source_id='B1')])])
        pool = sources(); pool['B1']['metadata']['kind'] = 'financial_baseline'
        before = copy.deepcopy(value)
        result = restrict_baselines(value, {'E1':dict(purpose='company_event',importance='major')}, pool)
        self.assertEqual(result['events'][0]['status'], 'missing')
        self.assertEqual(result['watchlist_checks'][0]['status'], 'missing')
        self.assertEqual(value, before)
        result = restrict_baselines(value, {'E1':dict(purpose='commentary',importance='context')}, pool)
        self.assertEqual(result['events'][0]['status'], 'ready')

    def test_protocol_and_business_context_enter_real_inputs_and_cost_forecast(self):
        state = listener_state(); state['sources'] = {}
        value = packet(state, 'agenda')
        self.assertEqual(value['research_protocol'], PROTOCOL)
        self.assertEqual(len(value['company_questions']), 1)
        old = editorial_forecast(reference.state(), NOW)
        new = editorial_forecast(state, NOW)
        self.assertGreater(new[0]['known_input_bytes'], old[0]['known_input_bytes'])
        messages = messages_for('writing', 'original contract', value, NOW, 'morning')
        self.assertIn('listener_cards', messages[0]['content'])
        self.assertIn('回购', messages[0]['content'])


class DirectIssuerBoundaries(unittest.TestCase):
    def desk(self, root, getter=None):
        state = listener_state()
        workspace = SimpleNamespace(path=Path(root), now=NOW, public_fetch_attempts=0, documents={})
        desk = IssuerDesk(state, workspace, Mock(), time.monotonic() + 60, request_get=getter)
        return desk

    def test_initial_company_jobs_use_direct_catalogue_but_legacy_jobs_do_not(self):
        old = initial_searches([STOCK], NOW)
        new = initial_searches([STOCK], NOW, direct_issuers=True)
        self.assertEqual(sum(j.get('retrieval') == 'issuer_catalogue' for j in new), 1)
        self.assertFalse(any(j.get('retrieval') for j in old))
        self.assertEqual(len(old), len(new))

    def test_catalogue_filters_identity_future_and_old_records_without_reading_body(self):
        with tempfile.TemporaryDirectory() as root:
            desk = self.desk(root)
            row = dict(art_code='AN202611140001',display_time='2026-11-14 08:00:00',
                codes=[dict(stock_code=STOCK['code'])],title='经营数据公告')
            wrong = dict(row, codes=[dict(stock_code='600900')])
            future = dict(row, display_time='2026-11-14 10:00:00')
            old = dict(row, display_time='2026-10-01 08:00:00')
            desk.request = Mock(return_value={'data':{'list':[row,wrong,future,old]}})
            result = desk.catalogue(STOCK)
            self.assertEqual(len(result['results']), 1)
            self.assertIn(STOCK['name'], result['results'][0]['title'])
            self.assertNotIn('text', result['results'][0])
            desk.request.assert_called_once()
            self.assertEqual(desk.request.call_args.args[0], LIST_URL)
            self.assertFalse(result['complete_history'])

    def test_failed_connection_still_counted_and_is_not_retried(self):
        with tempfile.TemporaryDirectory() as root:
            getter = Mock(side_effect=RuntimeError('offline fake failure'))
            desk = self.desk(root, getter)
            with patch('app.services.source_health.ensure_active'), patch('app.services.source_health.record_failure'):
                with self.assertRaises(RuntimeError):desk.request(LIST_URL, {'stock_list':STOCK['code']})
                with self.assertRaisesRegex(ValueError, 'not_retried'):
                    desk.request(LIST_URL, {'stock_list':STOCK['code']})
            self.assertEqual(getter.call_count, 1)
            self.assertEqual(desk.state['public_fetch_attempts'], 1)
            self.assertEqual(desk.state['issuer_http_receipts'][0]['status'], 'failed')

    def test_public_cap_rejects_before_connection(self):
        with tempfile.TemporaryDirectory() as root:
            getter = Mock();desk = self.desk(root, getter)
            desk.workspace.public_fetch_attempts = desk.state['policy']['max_body_urls'] * 3
            with self.assertRaisesRegex(ValueError, 'public_http_budget'):
                desk.request(LIST_URL, {})
            getter.assert_not_called()

    def test_unknown_endpoint_is_not_a_request(self):
        with tempfile.TemporaryDirectory() as root:
            getter = Mock();desk = self.desk(root, getter)
            with self.assertRaisesRegex(ValueError, 'endpoint_invalid'):
                desk.request('https://example.com/anything', {})
            getter.assert_not_called()

    def test_overlong_and_duplicate_announcement_pages_are_not_admitted(self):
        candidate = dict(title='公司公告',url='https://data.eastmoney.com/notices/detail/002714/AN1.html',
            issuer_document=dict(code='002714',art_code='AN1',published_at='2026-11-14T08:00:00'))
        with tempfile.TemporaryDirectory() as root:
            desk = self.desk(root)
            desk.request = Mock(return_value=dict(data=dict(art_code='AN1',page_size=3,notice_content=FACT*10)))
            with self.assertRaisesRegex(ValueError, 'full_document_unavailable'):desk.read(candidate)
            desk.request = Mock(return_value=dict(data=dict(art_code='AN1',page_size=2,notice_content=FACT*10)))
            with self.assertRaisesRegex(ValueError, 'pages_incomplete'):desk.read(candidate)
            self.assertFalse(desk.workspace.documents)


class SharedPipelineIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_direct_company_request_creates_no_paid_search_reservation(self):
        with tempfile.TemporaryDirectory() as root:
            state = listener_state()
            workspace = SimpleNamespace(now=NOW, path=Path(root), web_search_attempts=0)
            search = Mock(side_effect=AssertionError('must not buy keyword search'))
            pipeline = EditionPipeline(state, root, workspace, search=search, check=AsyncMock())
            pipeline.save = Mock();pipeline.budget = Mock()
            pipeline.issuer_desk.catalogue = Mock(return_value=dict(status='ok',results=[]))
            pipeline.issuer_desk.baseline = Mock(return_value=(dict(key='A:002714',profile=None,gaps=[]),[]))
            job = next(j for j in initial_searches([STOCK],NOW,direct_issuers=True) if j.get('retrieval'))
            await pipeline.searches([job])
            pipeline.budget.check_search_batch.assert_called_once_with(0)
            pipeline.budget.reserve.assert_not_called()
            search.assert_not_called()
            self.assertIn('A:002714',state['company_baselines'])
            self.assertEqual(state['issuer_catalogue_checks'][0]['results'],0)

    async def test_failed_direct_catalogue_stays_a_gap_without_hidden_paid_fallback(self):
        with tempfile.TemporaryDirectory() as root:
            state = listener_state();workspace = SimpleNamespace(now=NOW,path=Path(root))
            search = Mock();pipeline = EditionPipeline(state,root,workspace,search=search,check=AsyncMock())
            pipeline.save = Mock();pipeline.budget = Mock()
            pipeline.issuer_desk.catalogue = Mock(side_effect=ValueError('bad provider structure'))
            pipeline.issuer_desk.baseline = Mock(return_value=(dict(key='A:002714',profile=None,gaps=[]),[]))
            job = next(j for j in initial_searches([STOCK],NOW,direct_issuers=True) if j.get('retrieval'))
            await pipeline.searches([job])
            self.assertEqual(state['issuer_catalogue_checks'][0]['status'],'source_gap')
            search.assert_not_called()

class IntegrationCoverage(unittest.IsolatedAsyncioTestCase):
    async def test_new_research_protocol_completes_the_same_four_model_stages(self):
        case = reference.PipelineRegression()
        with tempfile.TemporaryDirectory() as root:
            pipeline, stages, written = await case.scenario(Path(root))
            pipeline.state['research_protocol'] = PROTOCOL
            # Existing scenario has no watchlist; this exercises writing/review,
            # not the separately bounded issuer catalogue.
            policy_condition = '若政策未按已披露条件实施就撤回传导判断。'
            written['body'] += policy_condition;written['script'] += policy_condition
            written['listener_cards'] = [dict(judgment='保留条件',source_id='body-1',fact_quote=reference.FACT,
                report_quote=reference.FACT,mechanism='政策可能影响经营，需要实际实施印证',
                alternative='也可能只改变短期情绪，尚缺定价数据',horizon='下一次正式实施披露',invalidation=policy_condition)]
            written['stock_followups'] = []
            original_model = pipeline.model
            async def model(task, messages, output):
                raw = await original_model(task, messages, output)
                value = json.loads(raw)
                if task == 'review':
                    value['listener_checks'] = [dict(criterion=c,status='supported',reason='逐字核对资料和口播条件',
                        report_quote=reference.FACT,script_quote=reference.FACT) for c in
                        ('evidence','causality','company_relevance','time_and_units','countercase_and_falsifier')]
                return json.dumps(value,ensure_ascii=False)
            pipeline.model = model
            with patch('app.services.podcast_script_cache.save'), patch('app.services.podcast_script_cache.load',return_value=written['script']):
                report = await pipeline.execute()
            self.assertIsNotNone(report)
            self.assertEqual(stages,['analysis','analysis','analysis','review'])
            self.assertEqual(pipeline.state['status'],'reviewed_text')

    def test_business_comparison_attaches_only_matching_baseline_without_http(self):
        from app.services.research_hub import Material
        with tempfile.TemporaryDirectory() as root:
            state=listener_state();state['candidates']={
                'S1':dict(scope='A:002714',baseline_document='F1'),
                'S2':dict(scope='A:600900',baseline_document='F2')}
            item=Material('F1','财务背景','供应商镜像','https://example.com/data','financial_baseline',
                'A:002714','明确注明期间及单位的财务基线。'*10,NOW,NOW.isoformat(),period='2026年三季度')
            workspace=SimpleNamespace(now=NOW,path=Path(root),documents={'F1':item},
                metadata=lambda obj:dict(kind='financial_baseline',body_quality={'requires_editorial_review':False}))
            pipeline=EditionPipeline(state,root,workspace,check=AsyncMock())
            pipeline.attach_baselines('E1',dict(direct_scopes=['A:002714'],metadata={'kind':'primary_notice'}))
            self.assertEqual(set(state['sources']),{'F1'})
            self.assertFalse(state['sources']['F1']['source_role']['latest_close_allowed'])
            self.assertEqual(state['baseline_links'][0]['new_http_requests'],0)
            self.assertEqual(state['sources']['F1']['purpose'],'commentary')

    def test_successful_raw_capture_is_reused_without_second_connection(self):
        with tempfile.TemporaryDirectory() as root:
            raw=json.dumps({'data':{'list':[]}}).encode()
            response=SimpleNamespace(status_code=200,raise_for_status=lambda:None,
                iter_content=lambda size:[raw],close=Mock())
            getter=Mock(return_value=response)
            state=listener_state();workspace=SimpleNamespace(now=NOW,path=Path(root),public_fetch_attempts=0)
            desk=IssuerDesk(state,workspace,Mock(),time.monotonic()+60,getter)
            with patch('app.services.source_health.ensure_active'):
                self.assertEqual(desk.request(LIST_URL,{'stock_list':STOCK['code']}),{'data':{'list':[]}})
                desk.request(LIST_URL,{'stock_list':STOCK['code']})
            self.assertEqual(getter.call_count,1)
            self.assertEqual(state['public_fetch_attempts'],1)
            self.assertTrue((Path(root)/'issuer-responses'/state['issuer_http_receipts'][0]['capture']).is_file())
            response.close.assert_called_once()

    def test_redirect_is_not_followed_and_preserves_attempt(self):
        with tempfile.TemporaryDirectory() as root:
            response=SimpleNamespace(status_code=302,raise_for_status=lambda:None,close=Mock())
            getter=Mock(return_value=response)
            state=listener_state();workspace=SimpleNamespace(now=NOW,path=Path(root),public_fetch_attempts=0)
            desk=IssuerDesk(state,workspace,Mock(),time.monotonic()+60,getter)
            with patch('app.services.source_health.ensure_active'),patch('app.services.source_health.record_failure'):
                with self.assertRaisesRegex(ValueError,'redirect_not_followed'):
                    desk.request(LIST_URL,{'stock_list':STOCK['code']})
            self.assertFalse(getter.call_args.kwargs['allow_redirects'])
            self.assertEqual(state['public_fetch_attempts'],1)
            self.assertEqual(getter.call_count,1)


class EndpointEfficiency(unittest.TestCase):
    def test_timeout_does_not_buy_four_repeats_of_same_source_endpoint(self):
        import requests
        with tempfile.TemporaryDirectory() as root:
            getter=Mock(side_effect=requests.Timeout('offline fake timeout'))
            state=listener_state();workspace=SimpleNamespace(now=NOW,path=Path(root),public_fetch_attempts=0)
            desk=IssuerDesk(state,workspace,Mock(),time.monotonic()+60,getter)
            with patch('app.services.source_health.ensure_active'),patch('app.services.source_health.record_failure'):
                with self.assertRaises(requests.Timeout):desk.request(LIST_URL,{'stock_list':'002714'})
                with self.assertRaisesRegex(ValueError,'endpoint_unavailable_this_run'):
                    desk.request(LIST_URL,{'stock_list':'300750'})
            self.assertEqual(getter.call_count,1)
            self.assertEqual(state['public_fetch_attempts'],1)
