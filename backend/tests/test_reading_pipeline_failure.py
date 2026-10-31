import importlib.util,json,tempfile,unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock,Mock,patch

from app.services.episode_workspace import EpisodeWorkspace
from app.services.primary_discovery import discover,Limits,unsupported_page
from app.services.web_research import parse_visible_article,capture_public_response,failure_reason,archived_public_body,read_public

spec=importlib.util.spec_from_file_location('saved_body_probe',Path(__file__).resolve().parents[2]/'tools/check_saved_search_bodies.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)
NOW=datetime(2026,10,31,16)
BODY='公开正文中的具体经营信息与反方解释，发布日期不能用链接日期代替。'*15


class TemplatesTests(unittest.TestCase):
    def test_recent_same_url_archive_reused_without_http_or_version_claim(self):
        from app.models.news import News
        from app.services.news_archive import NewsArchive
        with tempfile.TemporaryDirectory() as root:
            item=News(id='old',title='市场分化与行业变化',content=BODY,source='公开网页可见正文-示例',
                      source_url='https://example.com/news/1',published_at=NOW)
            NewsArchive(root).save([item],{},'fixture',now=NOW)
            ws=EpisodeWorkspace([],root=Path(root)/'episodes',now=NOW)
            with patch('app.services.news_archive.ROOT',Path(root)),patch('app.services.web_research.fetch_html_once') as fetch:
                result=read_public(ws,item.source_url)
                self.assertIsNone(archived_public_body('https://example.com/news/other',NOW))
            fetch.assert_not_called();self.assertEqual(result['status'],'ok')
            self.assertFalse(result['remote_version_checked']);self.assertEqual(result['http_requests_performed'],0)

    def test_archive_summary_is_not_promoted_to_body(self):
        from app.models.news import News
        from app.services.news_archive import NewsArchive
        with tempfile.TemporaryDirectory() as root:
            item=News(id='rss',title='市场目录摘要与变化',content=BODY,source='RSS摘要',
                      source_url='https://example.com/news/1',published_at=NOW)
            NewsArchive(root).save([item],{},'fixture',now=NOW)
            self.assertIsNone(archived_public_body(item.source_url,NOW,root=root))

    def test_eastmoney_uses_article_info_not_url_or_recommendations(self):
        html='<div class="title">市场分化与成交变化</div><div class="infos">2026年10月30日 19:57 来源：记者</div><div id="ContentBody">'+BODY+'<aside>无关推荐</aside></div>'
        item=parse_visible_article(html,'https://finance.eastmoney.com/a/202610303916423915.html',NOW)
        self.assertEqual(item.published_at,datetime(2026,10,30,19,57));self.assertIn('具体经营',item.content)
        self.assertNotIn('无关推荐',item.content)
        with self.assertRaisesRegex(ValueError,'time_missing'):
            parse_visible_article(html.replace('2026年10月30日 19:57','无时间'),'https://finance.eastmoney.com/a/202610303916423915.html',NOW)

    def test_alias_declared_canonical_keeps_actual_host_and_uncertainty(self):
        path='/articles/2026-10-30/4631070.html'
        html='<link rel="canonical" href="https://www.nbd.com.cn'+path+'"><div class="g-article"><h1>港股收盘市场分化</h1><p class="u-time"><span class="time">2026-10-30 17:10:45</span></p><div class="g-articl-text">'+BODY+'</div></div>'
        item=parse_visible_article(html,'https://www.mrjjxw.com'+path,NOW)
        self.assertEqual(item.source_url,'https://www.mrjjxw.com'+path)
        self.assertIn('未独立核实',item.market_impact)
        with self.assertRaisesRegex(ValueError,'alias_identity_unverified'):
            parse_visible_article(html.replace('/4631070.html','/1.html'),'https://www.mrjjxw.com'+path,NOW)

    def test_document_and_social_pages_are_classified_before_fetching(self):
        self.assertEqual(unsupported_page('https://example.com/report.PDF?q=1'),'document_requires_document_reader_not_html')
        self.assertEqual(unsupported_page('https://www.instagram.com/p/example'),'social_page_requires_platform_reader')

    def test_capture_retains_bytes_for_offline_reparse_without_credentials(self):
        with tempfile.TemporaryDirectory() as root:
            ws=EpisodeWorkspace([],root=root,now=NOW)
            name=capture_public_response(ws,'https://example.com/news/1',200,{'Content-Type':'text/html','Set-Cookie':'never-save'},BODY.encode())
            meta=json.loads((ws.path/name).read_text())
            self.assertEqual((ws.path/name).with_name(meta['file']).read_bytes(),BODY.encode())
            self.assertNotIn('never-save',json.dumps(meta))
            self.assertEqual(meta['snapshot_cutoff'],NOW.isoformat())

    def test_distinct_safe_failure_codes_remain_actionable(self):
        self.assertEqual(failure_reason(ValueError('web_source_non_html')),'web_source_non_html')
        self.assertEqual(failure_reason(ValueError('secret-provider-body')),'ValueError')

    def test_saved_plan_never_retries_attempted_urls_or_unsupported_targets(self):
        source=dict(research=dict(started_at=NOW.isoformat(),candidates={
            'S1':dict(title='已失败',url='https://example.com/news/1'),
            'S2':dict(title='PDF',url='https://example.com/report.pdf'),
            'S3':dict(title='未尝试',url='https://example.com/news/3')},
            receipts=[dict(request=dict(tool='read',candidate_id='S1'),result=dict(status='failed'))]))
        value=probe.plan(source)
        self.assertEqual([r['candidate_id'] for r in value['targets']],['S3'])
        self.assertEqual(value['model_requests'],0);self.assertEqual(value['search_requests'],0)

    def test_saved_finish_diagnosis_does_not_call_a_model_or_conflate_missing_fields(self):
        from app.services.search_primary_collection import LANES
        final=dict(action='finish',events=[],omissions=[],watchlist_checks=[],
            coverage=[dict(lane=x,status='missing',explanation='尚未取得正文') for x in LANES])
        source=dict(research=dict(started_at=NOW.isoformat(),watchlist=[],candidates={},receipts=[],decisions=[json.dumps(final)]))
        value=probe.plan(source)
        self.assertEqual(value['previous_finish_check']['validation'],'discovery_evidence_list_missing')


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_three_failed_bodies_stop_before_next_paid_model_round(self):
        with tempfile.TemporaryDirectory() as root:
            ws=EpisodeWorkspace([],root=root,now=NOW)
            model=AsyncMock(side_effect=[json.dumps(dict(action='tools',requests=[dict(tool='search',lane='a_market',query='市场变化',reason='查收盘')])),
                json.dumps(dict(action='tools',requests=[dict(tool='read',candidate_id='S'+str(i),relation='market',reason='查正文') for i in range(1,4)]))])
            search=Mock(return_value=dict(status='ok',results=[dict(url='https://example.com/news/'+str(i),title='市场变化',snippet='目录') for i in range(3)]))
            read=Mock(return_value=dict(status='failed',reason='web_source_article_structure_missing'))
            result=await discover(ws,[],model=model,search=search,read=read)
            self.assertEqual(result['status'],'reading_pipeline_unverified');self.assertEqual(model.await_count,2)

    async def test_last_model_turn_cannot_spend_more_tool_requests(self):
        with tempfile.TemporaryDirectory() as root:
            ws=EpisodeWorkspace([],root=root,now=NOW);search=Mock()
            model=AsyncMock(return_value=json.dumps(dict(action='tools',requests=[dict(tool='search',lane='a_market',query='市场',reason='读取') ])))
            result=await discover(ws,[],model=model,search=search,limits=Limits(model_calls=1))
            self.assertEqual(result['status'],'model_budget_exhausted');search.assert_not_called()
