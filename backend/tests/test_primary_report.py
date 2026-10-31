"""Evidence integrity and spending boundaries of the explicit report path."""
from datetime import datetime, timedelta
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app.models.news import News
from app.services.episode_workspace import EpisodeWorkspace
from app.services.primary_report import export_discovery, prepare, save_discovery_input, PrimaryReportService, fingerprint
from app.services.search_primary_collection import LANES

NOW=datetime(2026,10,31,16)


def source():
    return News(id='web-evidence-stable-id',title='市场经营变化及反方信息',
        content='经营数据变化及原始口径需要核对。'*40+'末尾反证不能省略。',
        source='公开网页可见正文-publisher.example',source_url='https://publisher.example/articles/123',
        published_at=NOW-timedelta(hours=1))


def discovery(workspace):
    item=source()
    return dict(owner='finance-model-led-discovery-v1',status='partial_materials_for_human_review',
        started_at=NOW.isoformat(),watchlist=[],provided_ids=[item.id],model_calls=3,
        search_tool_calls=1,body_url_calls=1,candidates={},executed_coverage={'missing_search_lanes':['industry']},
        receipts=[dict(request={'tool':'search','lane':'a_market','query':'具体市场问题'},
                       result={'status':'ok','results':[]}),
                  dict(request={'tool':'read','candidate_id':'S1'},result=dict(status='ok',
                       observed_at=NOW.isoformat(),material=workspace.read(item.id,characters=100)))],
        dossier=dict(action='finish',events=[dict(title='变化',why_it_matters='有新增经营事实',
                     caveats='只读前段，须补读末尾',evidence_ids=[item.id])],
                     coverage=[dict(lane=lane,status='body_provided' if lane=='a_market' else 'missing',
                         evidence_ids=[item.id] if lane=='a_market' else [],explanation='实际范围及缺口') for lane in LANES],
                     watchlist_checks=[],omissions=[]))


class HandoffTests(unittest.TestCase):
    def test_full_stored_body_and_original_id_survive_partial_discovery_exposure(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace=EpisodeWorkspace([source()],root=directory,now=NOW)
            value=export_discovery(workspace,discovery(workspace))
            news,context,preview=prepare(value,now=NOW)
        self.assertEqual(news[0].id,source().id)
        self.assertEqual(news[0].content,source().content)
        self.assertEqual(context['provenance'][0]['discovery_provided_ranges'],[[0,100]])
        self.assertEqual(context['cutoff'],NOW.isoformat())
        self.assertEqual(preview['executed_coverage']['missing_search_lanes'],['industry'])
        self.assertFalse(preview['watchlist_checked_against_app'])

    def test_failed_discovery_never_becomes_report_input(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace=EpisodeWorkspace([source()],root=directory,now=NOW)
            state=discovery(workspace);state['status']='failed_no_retry'
            self.assertIsNone(save_discovery_input(workspace,state))
            self.assertFalse((workspace.path/'report-input.json').exists())

    def test_changed_body_or_exposed_range_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace=EpisodeWorkspace([source()],root=directory,now=NOW)
            state=discovery(workspace)
            state['receipts'][1]['result']['material']['text']='not the stored body'
            with self.assertRaisesRegex(ValueError,'exposure_changed'):export_discovery(workspace,state)
            state=discovery(workspace)
            value=export_discovery(workspace,state)
            value['news'][0]['content']+='新增未经审阅内容'
            with self.assertRaisesRegex(ValueError,'body_hash_mismatch'):prepare(value,now=NOW)

    def test_reexport_does_not_refresh_the_original_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace=EpisodeWorkspace([source()],root=directory,now=NOW)
            value=export_discovery(workspace,discovery(workspace))
            _,context,preview=prepare(value,now=NOW+timedelta(hours=3))
        self.assertEqual(context['cutoff'],NOW.isoformat())
        self.assertFalse(preview['fresh_for_generation'])

    def test_publisher_body_container_excludes_recommendations_and_does_not_guess_timezone(self):
        from app.services.web_research import parse_visible_article
        html='<h1>港股市场变化与观察</h1><span id="pubtime_baidu">2026-10-30 21:33:33</span>'
        html+='<div class="left_zw"><p>'+source().content+'</p></div>'
        html+='<div class="selected_news_wrapper">推荐新闻2026年10月31日23:00</div>'
        item=parse_visible_article(html,'https://www.chinanews.com/cj/2026/10-30/123.shtml',NOW)
        self.assertNotIn('推荐新闻',item.content)
        self.assertIn('来源未标时区',item.market_impact)
        self.assertIn('精度：day',item.market_impact)


class ExecutionBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_pause_checked_before_app_read_or_network(self):
        with patch('app.services.model_gateway.ensure_models_enabled',side_effect=RuntimeError('paused')), \
             patch('app.services.watchlist_repository.assert_watchlist_current',new_callable=AsyncMock) as live:
            with self.assertRaisesRegex(RuntimeError,'paused'):
                await PrimaryReportService().generate({},'unused')
            live.assert_not_awaited()

    async def test_upstream_calls_cannot_get_a_fresh_report_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace=EpisodeWorkspace([source()],root=directory,now=NOW)
            state=discovery(workspace);state['model_calls']=8
            value=export_discovery(workspace,state)
            with patch('app.services.model_gateway.ensure_models_enabled'), \
                 patch('app.services.primary_report.china_now',return_value=NOW), \
                 patch('app.config.settings.model_max_calls_per_report',8), \
                 patch('app.config.settings.model_http_retries',0), \
                 patch('app.config.settings.report_auto_repair_enabled',False), \
                 patch('app.services.watchlist_repository.assert_watchlist_current',new_callable=AsyncMock) as live:
                with self.assertRaisesRegex(RuntimeError,'shared_model_budget_exhausted'):
                    await PrimaryReportService().generate(value,fingerprint(value))
                live.assert_not_awaited()

    async def test_new_contract_does_not_deduct_collection_calls_from_report(self):
        from app.services.discovery_completion import CONTRACT
        context=dict(watchlist=[],upstream_usage={'model_calls':50},budget_contract=CONTRACT,
            collection_completion=dict(status='ready_for_editorial_review',valid_dossier_present=True,scope_ledger_valid=True))
        preview=dict(input_sha256='approved',fresh_for_generation=True,body_quality_review_required=False)
        service=PrimaryReportService()
        with patch('app.services.model_gateway.ensure_models_enabled'), \
             patch('app.services.primary_report.prepare',return_value=([],context,preview)), \
             patch('app.config.settings.model_http_retries',0), \
             patch('app.config.settings.report_auto_repair_enabled',False), \
             patch('app.services.watchlist_repository.assert_watchlist_current',new_callable=AsyncMock), \
             patch.object(service,'_generate_once',new_callable=AsyncMock,return_value={'status':'stub'}) as run:
            await service.generate({},'approved')
            run.assert_awaited_once()
            context['collection_completion']['status']='incomplete'
            with self.assertRaisesRegex(RuntimeError,'collection_incomplete'):
                await service.generate({},'approved')
            self.assertEqual(run.await_count,1)

    async def test_frozen_evidence_tools_allow_local_tail_read_but_no_paid_search(self):
        from app.services.episode_research import execute
        with tempfile.TemporaryDirectory() as directory:
            workspace=EpisodeWorkspace([source()],root=directory,now=NOW)
            workspace.allow_external_evidence_tools=False
            with patch('app.services.episode_research.ResearchHub',side_effect=AssertionError('no extra corpus')), \
                 patch('app.services.web_research.search',side_effect=AssertionError('no paid search')):
                rows=await execute(workspace,[dict(tool='search_web',queries=['新搜索']),
                    dict(tool='read_material',id=source().id,offset=len(source().content)-9,characters=9)],[])
        self.assertEqual(rows[0]['result']['reason'],'frozen_primary_report_no_external_collection')
        self.assertIn('末尾反证',rows[1]['result']['text'])
