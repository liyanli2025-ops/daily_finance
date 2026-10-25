from datetime import datetime, timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch, AsyncMock

import requests

from app.services.watchlist_service import WatchlistStock
from app.services.watchlist_sources import parse_tencent_quotes, fetch_company_announcements, fetch_sina_stock_news
from app.services import market_data_service as market


NOW = datetime(2026, 10, 23, 14)
STOCK = WatchlistStock('002714', '牧原股份', 'A')


def quote(stamp='20261023135959', code='002714'):
    fields = [''] * 34
    fields[1], fields[2], fields[3], fields[30], fields[32] = '牧原股份', code, '40', stamp, '-0.6'
    return 'v_sz002714="' + '~'.join(fields) + '";'


def response(data):
    return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'data':data})


class WatchlistSourcesTests(unittest.TestCase):
    def test_quote_identity_timestamp_and_missing_rows(self):
        self.assertEqual(parse_tencent_quotes(quote(), [STOCK], NOW)[STOCK.code]['as_of'], '2026-10-23T13:59:59')
        self.assertEqual(parse_tencent_quotes(quote(code='600900'), [STOCK], NOW), {})
        self.assertEqual(parse_tencent_quotes(quote(stamp=''), [STOCK], NOW), {})
        self.assertEqual(parse_tencent_quotes(quote(stamp='20261023150000'), [STOCK], NOW), {})
        old = parse_tencent_quotes(quote(stamp='20261022150000'), [STOCK], NOW)
        self.assertEqual(old[STOCK.code]['as_of'], '2026-10-22T15:00:00')

    def test_hong_kong_timestamp_and_currency_use_the_provider_format(self):
        stock = WatchlistStock('00700', '腾讯控股', 'HK')
        text = quote(stamp='2026/10/23 13:59:59', code='00700').replace('v_sz002714', 'v_hk00700')
        value = parse_tencent_quotes(text, [stock], NOW)['00700']
        self.assertEqual(value['currency'], 'HKD')
        self.assertEqual(value['as_of'], '2026-10-23T13:59:59')

    def test_recent_disclosure_uses_publication_time_not_next_day_document_date(self):
        row = dict(art_code='AN202610221234', title='牧原股份公告',
                   display_time='2026-10-22 18:07:39:741', notice_date='2026-10-23 00:00:00',
                   codes=[{'stock_code':STOCK.code}])
        detail = dict(art_code=row['art_code'], page_size='1', notice_content='可核对的完整公司公告正文')
        with patch('app.services.watchlist_sources.requests.get', side_effect=[response({'list':[row]}), response(detail)]):
            items, status = fetch_company_announcements(STOCK, now=NOW)
        self.assertEqual(status['full_text'], 1)
        self.assertEqual(items[0].published_at, datetime(2026, 10, 22, 18, 7, 39, 741000))
        self.assertIn('2026-10-23', items[0].content)
        self.assertEqual(items[0].related_stocks, ['002714'])

    def test_old_or_other_company_announcements_are_not_fetched_as_new(self):
        rows = [dict(display_time='2026-10-12 15:31:55:557', codes=[{'stock_code':STOCK.code}]),
                dict(display_time='2026-10-23 12:00:00', codes=[{'stock_code':'600900'}])]
        with patch('app.services.watchlist_sources.requests.get', return_value=response({'list':rows})) as get:
            items, status = fetch_company_announcements(STOCK, now=NOW)
        self.assertEqual(items, [])
        self.assertEqual(status['latest_publication'], '2026-10-12T15:31:55.557000')
        self.assertEqual(get.call_count, 1)

    def test_title_only_or_wrong_body_never_becomes_evidence(self):
        row = dict(art_code='AN1234', display_time='2026-10-23 12:00:00', codes=[{'stock_code':STOCK.code}])
        for detail in [dict(art_code='AN1234', page_size='1', notice_content=''),
                       dict(art_code='AN9999', page_size='1', notice_content='错误正文'),
                       dict(art_code='AN1234', page_size='6', notice_content='不完整正文')]:
            with self.subTest(detail=detail), patch('app.services.watchlist_sources.requests.get',
                    side_effect=[response({'list':[row]}), response(detail)]):
                items, status = fetch_company_announcements(STOCK, now=NOW)
            self.assertEqual(items, [])
            self.assertEqual(status['status'], 'partial')

    def test_intraday_cache_expires_instead_of_lasting_until_tomorrow(self):
        cache = market._MarketDataCache()
        with patch('app.services.market_data_service.time.monotonic', return_value=100):
            cache.set('quote', {'price':40})
            self.assertTrue(cache.has('quote'))
        with patch('app.services.market_data_service.time.monotonic', return_value=221):
            self.assertIsNone(cache.get('quote'))
            self.assertFalse(cache.has('quote'))

    def test_sina_reads_full_article_and_labels_automated_secondary_news(self):
        url = 'https://finance.sina.com.cn/stock/aiassist/lr/2026-10-23/doc-test.shtml'
        listing = SimpleNamespace(status_code=200, raise_for_status=lambda:None,
            text='<div class="datelist">2026-10-23&nbsp;09:59 <a href="'+url+'">牧原股份融资数据</a></div>')
        body = SimpleNamespace(status_code=200, raise_for_status=lambda:None,
            text='<span class="date">2026年10月23日 09:59</span><div id="artibody"><p>'
                 +'牧原股份上一交易日融资情况。'*10+'</p></div>')
        with patch('app.services.watchlist_sources.requests.get', side_effect=[listing, body]):
            items, status = fetch_sina_stock_news(STOCK, now=NOW)
        self.assertEqual(status['full_text'], 1)
        self.assertIn('自动生成快讯', items[0].source)
        self.assertIn('不是独立人工调查', items[0].content)
        self.assertEqual(items[0].published_at, datetime(2026, 10, 23, 9, 59))

    def test_sina_rejects_mismatched_dates_and_external_links(self):
        listing = SimpleNamespace(status_code=200, raise_for_status=lambda:None,
            text='<div class="datelist">2026-10-23 09:59 <a href="https://finance.sina.com.cn/doc-test.shtml">新闻</a>'
                 '<br>2026-10-23 10:00 <a href="https://example.com/unsafe.shtml">外链</a></div>')
        body = SimpleNamespace(status_code=200, raise_for_status=lambda:None,
            text='<span class="date">2026年10月22日 09:59</span><div id="artibody"><p>'+'牧原股份新闻'*30+'</p></div>')
        with patch('app.services.watchlist_sources.requests.get', side_effect=[listing, body]) as get:
            items, status = fetch_sina_stock_news(STOCK, now=NOW)
        self.assertEqual(items, [])
        self.assertEqual(status['status'], 'partial')
        self.assertEqual(get.call_count, 2)


class FailureCooldownTests(unittest.IsolatedAsyncioTestCase):
    async def test_issuer_and_sina_sources_feed_the_actual_watchlist_news_path(self):
        from app.services.news_collector import NewsCollectorService
        from app.services.watchlist_service import WatchlistService
        from app.models.news import News
        collector = NewsCollectorService.__new__(NewsCollectorService)
        collector.akshare_available = True
        collector._collect_individual_stock_news = AsyncMock(return_value=[])
        collector._collect_sector_news = AsyncMock(return_value=[])
        collector._load_db_watchlist = AsyncMock(return_value=[dict(code='002714', name='牧原股份', market='A')])
        notice = News(id='notice', title='牧原股份公告', content='完整公告', source='公司公告',
                      source_url='https://example.com/notice/1', published_at=NOW, related_stocks=['002714'])
        article = notice.model_copy(update={'id':'article', 'title':'牧原股份新闻'})
        with patch('app.services.news_collector.china_now', return_value=NOW), \
                patch('app.services.media_sources.MediaCollector.collect', return_value=([],{})), \
                patch('app.services.research_hub.ResearchHub.collect', AsyncMock(return_value={'stocks':[]})), \
                patch('app.services.news_collector.get_watchlist_service', return_value=WatchlistService()), \
                patch('app.services.watchlist_sources.fetch_company_announcements', return_value=([notice], {'status':'ok'})), \
                patch('app.services.watchlist_sources.fetch_sina_stock_news', return_value=([article], {'status':'ok'})):
            items = await collector._collect_watchlist_news()
        self.assertEqual([item.id for item in items], ['notice', 'article'])
        collector._collect_individual_stock_news.assert_not_awaited()

    async def test_same_failed_full_market_request_is_not_repeated_under_another_cache_label(self):
        provider = Mock(side_effect=requests.ConnectionError('test'))
        provider.__name__ = 'stock_zh_a_spot_em'
        service = market.MarketDataService.__new__(market.MarketDataService)
        with patch.object(market, '_akshare_failures', {}), patch.object(market, '_market_data_cache', market._MarketDataCache()), \
                patch.object(market._akshare_rate_limiter, 'acquire', AsyncMock()):
            with self.assertRaises(requests.ConnectionError):
                await service._call_akshare_with_retry(provider, cache_key='market-stats')
            with self.assertRaisesRegex(RuntimeError, '冷却'):
                await service._call_akshare_with_retry(provider, cache_key='technical-scan')
        self.assertEqual(provider.call_count, 1)
