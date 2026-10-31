import asyncio,json,tempfile,time,unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch,Mock,AsyncMock

from app.models.news import News
from app.services.community_sources import CommunityCollector,parse_thread,discover,provider_for,stamp
from app.services.news_quality import reading_scope,scope_label
from app.services.company_news_scope import decision
from app.services.watchlist_service import WatchlistStock

NOW=datetime(2026,10,31,11)
JSL='https://www.jisilu.cn/question/123'
GUBA='https://guba.eastmoney.com/news,123456,555.html'
TGB='https://www.tgb.cn/a/TestPost1'
TV='https://www.tradingview.com/chart/MRVL/Test-Idea/'

def jsl(date='2026-10-30 15:46',reply='2026-10-31 10:11',question='据报某渠道调整交易条件，尚未确认。'):
    return f'''<div class="aw-question-detail-title"><h1>投资者讨论交易条件变化</h1>
      <div class="aw-question-detail-txt">{question}</div>
      <div class="aw-question-detail-meta">发表时间 {date}</div></div>
      <div class="aw-dynamic-topic-content"><p class="publisher"><a class="aw-user-name">回答用户</a></p>
      <div class="markitup-box"><blockquote>他人猜测，仅供上下文。</blockquote>我的观察不同，尚无公告支持。</div>
      <div class="aw-dynamic-topic-meta">{reply}<a data-id="999">引用</a></div></div>'''

def news(source='公开参与者讨论-集思录'):
    return News(id='existing',title='投资者讨论交易条件变化',content='公开账号的原始说法，尚未核实。'*15,
        source=source,source_url=JSL,published_at=NOW)

class ParserTests(unittest.TestCase):
    def test_quoted_claim_is_not_assigned_to_reply_author(self):
        row=parse_thread(jsl(),JSL);reply=row['statements'][1]
        self.assertEqual(reply['author'],'回答用户')
        self.assertNotIn('他人猜测',reply['text'])
        self.assertEqual(reply['quoted_context'],['他人猜测，仅供上下文。'])
        self.assertEqual(reply['verification'],'unverified_statement')
        self.assertIsNone(row['statements'][0]['author'])
        self.assertFalse(row['complete_thread'])

    def test_undated_reply_does_not_borrow_thread_date(self):
        self.assertEqual(len(parse_thread(jsl(reply='刚刚'),JSL)['statements']),1)

    def test_guba_reads_json_literal_and_checks_both_ids(self):
        data=dict(post_id=555,post_guba=dict(stockbar_code='123456'),post_title='个人观点',
            post_content='这是用户的猜测，不是确认事实。',post_publish_time='2026-10-31 09:11:14',
            post_user=dict(user_nickname='公开账号'))
        raw='var post_article='+json.dumps(data,ensure_ascii=False)+';not_executed();'
        self.assertEqual(parse_thread(raw,GUBA)['statements'][0]['text'],'这是用户的猜测，不是确认事实。')
        data['post_guba']['stockbar_code']='654321'
        with self.assertRaisesRegex(ValueError,'identity'):parse_thread('var post_article='+json.dumps(data),GUBA)
        with self.assertRaises(ValueError):parse_thread('var post_article=executeSomething();',GUBA)

    def test_guba_directory_excludes_agency_and_other_board_entries(self):
        data=dict(bar_code='123456',re=[dict(post_id=1,post_type=0,stockbar_code='123456',post_title='用户发言'),
            dict(post_id=2,post_type=1,stockbar_code='123456',post_title='媒体转述'),
            dict(post_id=3,post_type=0,stockbar_code='654321',post_title='另一家公司')])
        rows=discover('guba','var article_list='+json.dumps(data),'https://guba.eastmoney.com/list,123456.html')
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['status'],'directory_not_body')

    def test_tgb_keeps_comment_identity_without_ads(self):
        raw='''<div id="stockTitle">个人复盘</div><div class="article-data"><span class="data-userid">作者甲</span>2026-10-30 16:20</div>
        <div id="first" class="article-text">市场观察，仅为个人判断。</div><aside>开户广告</aside>
        <div class="comment-data"><div class="comment-data-user"><a class="user-name">乙</a><span class="pcyclspan">2026-10-30 17:31</span></div>
        <div class="comment-data-text" id="reply7">我不同意这个判断。</div></div>'''
        result=parse_thread(raw,TGB)
        self.assertEqual(result['statements'][1]['position'],'reply7')
        self.assertEqual(result['statements'][0]['author'],'作者甲')
        self.assertNotIn('开户广告',str(result))

    def test_tradingview_has_explicit_timezone_and_no_fabricated_chart_data(self):
        raw='''<div class="js-publication-view"><h1>投资者观点</h1><a href="/u/Analyst/">Analyst</a>
        <time datetime="Thu, 29 Oct 2026 17:43:37 GMT"></time><div class="description-example">A personal hypothesis, not verified.</div></div>'''
        result=parse_thread(raw,TV)
        self.assertEqual(result['statements'][0]['published_at'],'2026-10-30T01:43:37')
        self.assertIn('图表图像未转',result['replies_scope'])

    def test_no_credentials_queries_challenges_or_arbitrary_hosts(self):
        for url in ['https://user:secret@www.jisilu.cn/question/123',JSL+'?token=x',JSL+'#reply1',
                    'http://www.jisilu.cn/question/123','https://127.0.0.1/question/123']:
            with self.subTest(url=url),self.assertRaises(ValueError):provider_for(url)
        with self.assertRaises(ValueError):parse_thread('<script>challenge()</script>',JSL)

    def test_global_dates_require_timezone_and_iso_offset_is_converted(self):
        self.assertEqual(stamp('2026-10-30T21:43:37Z',True),'2026-10-31T05:43:37')
        with self.assertRaises(ValueError):stamp('2026-10-30 21:43:37',True)

    def test_unconfirmed_discussion_is_not_filtered_as_ordinary_earnings(self):
        item=news();item.title='某公司三季报引发的讨论'
        self.assertTrue(decision(item)['keep'])
        self.assertEqual(reading_scope(item),'public_statement')
        self.assertIn('不是已确认',scope_label(item))


class CollectorTests(unittest.TestCase):
    def test_new_default_path_uses_owned_expiry_and_custom_root_does_not(self):
        with patch('app.services.material_lifecycle.prune_material_caches') as prune:
            CommunityCollector().collect(urls=[],budget=0)
            prune.assert_called_once()
        with tempfile.TemporaryDirectory() as folder,patch('app.services.material_lifecycle.prune_material_caches') as prune:
            CommunityCollector(folder).collect(urls=[],budget=0)
            prune.assert_not_called()

    def test_expired_budget_keeps_unchecked_new_stock_directory_visible(self):
        with tempfile.TemporaryDirectory() as folder:
            collector=CommunityCollector(folder)
            with patch.object(collector,'get') as get:
                _,coverage=collector.collect([WatchlistStock('654321','新公司','A')],budget=0)
            get.assert_not_called()
            self.assertIn('https://guba.eastmoney.com/list,654321.html',coverage['unread_directories'])
            self.assertEqual(coverage['status'],'partial')

    def test_old_parent_is_context_new_reply_is_dated_separately(self):
        with tempfile.TemporaryDirectory() as folder,patch('app.services.community_sources.china_now',return_value=NOW):
            collector=CommunityCollector(folder)
            with patch.object(collector,'get',return_value=jsl(date='2026-01-01 10:00')):
                items,coverage=collector.collect(urls=[JSL])
            self.assertEqual(len(items),1)
            self.assertEqual(items[0].published_at,datetime(2026,10,31,10,11))
            self.assertIn('2026-01-01T10:00',items[0].content)
            self.assertIn('每条原帖/回复时间分别保留',items[0].market_impact)

    def test_future_reply_never_leaks_into_report_body(self):
        with tempfile.TemporaryDirectory() as folder,patch('app.services.community_sources.china_now',return_value=NOW):
            collector=CommunityCollector(folder)
            with patch.object(collector,'get',return_value=jsl(reply='2026-11-01 10:00')):
                items,_=collector.collect(urls=[JSL])
            self.assertEqual(len(items),1)
            self.assertNotIn('我的观察不同',items[0].content)

    def test_already_available_body_does_not_request_page_again(self):
        with tempfile.TemporaryDirectory() as folder,patch('app.services.community_sources.china_now',return_value=NOW):
            collector=CommunityCollector(folder)
            with patch.object(collector,'get') as get:
                items,coverage=collector.collect(urls=[JSL],existing=[news()])
            get.assert_not_called();self.assertFalse(items)
            self.assertFalse(coverage['reused'][0]['remote_version_checked'])

    def test_structure_failure_is_paused_and_not_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            collector=CommunityCollector(folder);response=Mock(status_code=200,content=b'challenge',text='<script>challenge()</script>',apparent_encoding='utf-8')
            with patch('app.services.community_sources.requests.get',return_value=response) as get:
                with self.assertRaises(ValueError):collector.get(JSL,time.monotonic()+5)
                with self.assertRaises(ValueError):collector.get(JSL,time.monotonic()+5)
            self.assertEqual(get.call_count,1)


class PrimaryPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_on_demand_tool_prepares_attributed_statement_ranges(self):
        from app.services.episode_research import execute
        from app.services.episode_workspace import EpisodeWorkspace
        with tempfile.TemporaryDirectory() as folder:
            workspace=EpisodeWorkspace([],folder,NOW)
            coverage=dict(status='sampled',reused=[],errors=[],scope='public_sample',limitation='未核实')
            with patch('app.services.episode_research.ResearchHub.load',return_value=[]),\
                 patch('app.services.community_sources.CommunityCollector.collect',return_value=([news()],coverage)):
                result=await execute(workspace,[dict(tool='collect_discussions',urls=[JSL],reason='补充主资料之外的参与者观察')],[])
            self.assertEqual(result[0]['result']['materials'][0]['source'],'公开参与者讨论-集思录')
            self.assertTrue(workspace.prepared['existing'])
            self.assertFalse(workspace.confirmed)

    async def test_supplied_search_input_does_not_trigger_legacy_media_scan(self):
        from app.services.news_collector import NewsCollectorService
        collector=NewsCollectorService.__new__(NewsCollectorService)
        collector._load_db_watchlist=AsyncMock(return_value=[dict(code='654321',name='新公司',market='A')])
        primary=news('证券时报原文')
        with patch('app.services.news_collector.china_now',return_value=NOW),\
             patch('app.services.community_sources.CommunityCollector.collect',return_value=([],dict(status='sampled',read=0))) as collect,\
             patch('app.services.technical_radar.TechnicalRadar.collect',return_value={}),\
             patch('app.services.microstructure.MicrostructureRadar.collect',return_value={}),\
             patch.object(collector,'_collect_rss',new=AsyncMock()) as rss,\
             patch.object(collector,'_collect_radar_news',new=AsyncMock()) as media:
            result=await collector.collect_all(primary_news=[primary])
        self.assertEqual(result,[primary]);rss.assert_not_called();media.assert_not_called()
        self.assertEqual(collect.call_args.args[0][0].code,'654321')
        self.assertFalse(collector._radar_coverage['broad_media_scan'])

    async def test_empty_primary_pool_cannot_silently_become_forum_only_report(self):
        from app.services.news_collector import NewsCollectorService
        collector=NewsCollectorService.__new__(NewsCollectorService)
        with self.assertRaisesRegex(RuntimeError,'主资料'):await collector.collect_all(primary_news=[])
        with self.assertRaisesRegex(RuntimeError,'主资料'):await collector.collect_all(primary_news=[news()])
