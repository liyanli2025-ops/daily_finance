from datetime import datetime,timedelta,timezone
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,Mock,patch

from app.models.news import News,NewsType
from app.services.news_archive import NewsArchive
from app.services.source_inventory import inventory
from app.services.news_collector import NewsCollectorService
from app.services.media_sources import MediaCollector

NOW=datetime(2026,10,25,13)


def article(key,source='华尔街见闻-全球',published=None,body=None):
    return News(id=key,title='市场变化'+key,content=body or ('公开采集文本'+key+'，实际发布信息及口径。')*12,
        source=source,source_url='https://example.com/articles/'+key,published_at=published or NOW-timedelta(hours=2))


class ArchiveTests(unittest.TestCase):
    def test_previous_list_text_returns_without_turning_excerpt_into_full_or_today(self):
        with tempfile.TemporaryDirectory() as folder:
            archive=NewsArchive(folder);row=article('previous')
            archive.save([row],{},'hourly_rss',NOW-timedelta(hours=1))
            restored,status=archive.load(24,NOW)
            self.assertEqual(restored[0].content,row.content)
            self.assertEqual(restored[0].published_at,row.published_at)
            self.assertTrue(restored[0].id.startswith('history-'))
            self.assertFalse(status['complete_window'])
            self.assertEqual(inventory([],restored,NOW,24)['source_rows'][0]['reading_scopes'],{'feed_excerpt':1})

    def test_latest_observed_body_has_unique_id_and_old_version_remains_diagnostic_only(self):
        with tempfile.TemporaryDirectory() as folder:
            archive=NewsArchive(folder);row=article('same-provider-id')
            archive.save([row],{},'one',NOW-timedelta(hours=1))
            row.content='公司最新更正为收入下降10%，与原披露有差异。'*12
            archive.save([row],{},'two',NOW)
            restored,status=archive.load(24,NOW)
            self.assertEqual(len(restored),1)
            self.assertEqual(restored[0].content,row.content)
            self.assertNotEqual(restored[0].id,row.id)
            self.assertEqual(status['matching_versions'],2)

    def test_future_expired_title_only_and_bad_links_cannot_be_restored(self):
        with tempfile.TemporaryDirectory() as folder:
            archive=NewsArchive(folder)
            bad=article('bad');bad.source_url='https://[invalid'
            title=article('title');title.content=title.title
            archive.save([article('old',published=NOW-timedelta(days=9)),
                article('future',published=NOW+timedelta(days=1)),title,bad],{},'fixture',NOW)
            self.assertEqual(archive.load(24,NOW)[0],[])

    def test_inventory_covers_nonfinance_duplicates_failures_and_unselected_headlines(self):
        one=article('one');copy=article('copy',source='百度国际新闻',body=one.content)
        copy.news_type=NewsType.GEOPOLITICAL
        title=article('title');title.content=title.title
        result=inventory([one,copy,title],[],NOW,24,{'失效源':dict(status='failed')})
        self.assertEqual(result['retrieved'],3)
        self.assertEqual(len(result['exact_copy_groups']),1)
        self.assertEqual(next(row for row in result['source_rows'] if row['source']=='失效源')['feed_status']['status'],'failed')
        self.assertEqual(sum(row['title_only'] for row in result['source_rows']),1)
        self.assertEqual(result['coverage_status'],'sampled_not_complete')


class FlowTests(unittest.TestCase):
    def test_additional_public_body_field_is_read_without_treating_excerpt_as_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            collector=MediaCollector(folder)
            with patch.object(collector,'get',return_value=dict(id='1',is_need_pay=False,
                content='<p>原文前段。</p>',content_more='<p>'+('原文后段及关键反证。'*20)+'</p>',
                title='全文测试',display_time=1792900000)):
                row=collector.detail('wscn','1',float('inf'))
            self.assertIn('原文前段',row['body']);self.assertIn('原文后段及关键反证',row['body'])

    def test_pagination_uses_supplied_cursor_and_does_not_claim_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            collector=MediaCollector(folder)
            calls=[]
            def get(url,deadline,params):
                calls.append(params)
                return dict(items=[dict(resource_type='article',resource=dict(id=1 if len(calls)==1 else 2))],
                    next_cursor='next' if len(calls)==1 else '')
            with patch.object(collector,'get',side_effect=get):
                result=collector.latest('market-flow',float('inf'))
            self.assertEqual(calls[1]['cursor'],'next')
            self.assertEqual(len(result['items']),2)
            self.assertFalse(result['pagination']['complete_window'])

    def test_ignored_cursor_stops_instead_of_refetching_same_page(self):
        with tempfile.TemporaryDirectory() as folder:
            collector=MediaCollector(folder)
            with patch.object(collector,'get',return_value=dict(items=[dict(resource_type='article',resource=dict(id=1))],next_cursor='same')) as get:
                result=collector.latest('market-flow',float('inf'))
            self.assertEqual(get.call_count,2)
            self.assertEqual(result['pagination']['stop'],'repeated_page')


class CollectionHistoryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_feed_cools_down_instead_of_repeating_every_report(self):
        with tempfile.TemporaryDirectory() as folder:
            collector=NewsCollectorService.__new__(NewsCollectorService)
            collector._rss_state_root=Path(folder)
            collector.client=SimpleNamespace(get=AsyncMock(side_effect=TimeoutError()))
            feed=dict(name='测试源',url='https://example.com/rss')
            with patch('app.services.news_collector.china_now',return_value=NOW):
                await collector._collect_rss(feed)
                await collector._collect_rss(feed)
            self.assertEqual(collector.client.get.await_count,1)
            self.assertEqual(collector._rss_coverage['测试源']['status'],'cooldown')

    async def test_real_collection_merges_history_and_records_whole_pool_without_models(self):
        with tempfile.TemporaryDirectory() as folder:
            archive=NewsArchive(folder)
            archive.save([article('previous')],{},'previous',NOW-timedelta(hours=1))
            service=NewsCollectorService.__new__(NewsCollectorService)
            service._archive_enabled=True;service._archive_root=folder
            service._seen_hashes=set();service.rss_feeds=[{}]
            service.akshare_available=False;service.sentiment_analyzer=None
            service._collect_rss=AsyncMock(return_value=[article('current')])
            service._collect_10jqka_news=AsyncMock(return_value=[])
            service._collect_watchlist_news=AsyncMock(return_value=[])
            service._collect_radar_news=AsyncMock(return_value=[])
            with patch('app.services.news_collector.china_now',return_value=NOW), \
                    patch('app.services.news_archive.china_now',return_value=NOW), \
                    patch('app.services.news_collector.get_watchlist_service',return_value=SimpleNamespace(get_all_stocks=lambda:[])), \
                    patch('app.services.research_hub.ResearchHub.load',return_value=[]), \
                    patch('app.services.event_observations.EventObservations.observe'):
                result=await service.collect_all(24)
            self.assertEqual(len(result),2)
            self.assertEqual(service._collection_funnel['retrieved'],1)
            self.assertEqual(service._collection_funnel['history_restored'],1)
            self.assertEqual(service._source_inventory['retrieved'],1)

    async def test_rss_records_parse_loss_and_transport_separately_from_source_name(self):
        service=NewsCollectorService.__new__(NewsCollectorService)
        xml='''<rss version="2.0"><channel><title>feed</title><link>https://example.com</link><description>feed</description>
        <item><title>有效短消息</title><description>实际短内容保留。</description><link>https://example.com/a</link><pubDate>Sun, 25 Oct 2026 00:00:00 GMT</pubDate></item>
        <item><title>缺日期</title><description>不能伪造今天。</description><link>https://example.com/b</link></item></channel></rss>'''
        service.client=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(text=xml,raise_for_status=lambda:None)))
        service._calculate_importance=Mock(return_value=.5);service._extract_keywords=Mock(return_value=[])
        service._extract_stock_codes=Mock(return_value=[])
        news=await service._collect_rss(dict(name='解析测试源',url='https://rss.example.com/feed'))
        status=service._rss_coverage['解析测试源']
        self.assertEqual(status['feed_entries'],2);self.assertEqual(status['invalid_entries'],1)
        self.assertEqual(status['transport_host'],'rss.example.com')
        self.assertFalse(status['history_pagination'])
        self.assertEqual(news[0].content,'实际短内容保留。')
