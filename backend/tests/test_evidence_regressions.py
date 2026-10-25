"""Evidence selection and missing-analysis regressions, with no external services."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from app.models.news import News
from app.routers.stocks import get_stock_prediction, trigger_stock_analysis, generate_watchlist_predictions
from app.services.ai_analyzer import AIAnalyzerService
from app.services.news_collector import NewsCollectorService
from app.services.news_selection import matches_watchlist, within_window
from app.services.watchlist_service import WatchlistStock

NOW = datetime(2026, 10, 23, 6)
STOCKS = [WatchlistStock('002714', '牧原股份', 'A'),
          WatchlistStock('688535', '华海诚科', 'A'),
          WatchlistStock('600900', '长江电力', 'A')]
def news(identifier, title, **kwargs):
    return News(id=identifier, title=title, content=kwargs.pop('content', title+'。原文还披露了相应统计范围和经营变化。'), source='普通新闻源',
                source_url='https://example.com/news/' + identifier,
                published_at=kwargs.pop('published_at', NOW), **kwargs)


class SelectionTests(unittest.TestCase):
    def test_watchlist_matches_name_or_exact_code_without_category(self):
        self.assertTrue(matches_watchlist(news('1', '牧原股份发布公告'), STOCKS))
        self.assertTrue(matches_watchlist(news('2', '代码688535公告'), STOCKS))
        self.assertFalse(matches_watchlist(news('3', '订单编号16885350'), STOCKS))
        self.assertFalse(matches_watchlist(news('4', '普通新闻', category='自选股-已删除股票'), STOCKS))

    def test_old_future_and_timezone_boundaries(self):
        self.assertFalse(within_window(news('1', '旧稿', published_at=NOW-timedelta(days=2)), NOW, 24))
        self.assertFalse(within_window(news('2', '未来', published_at=NOW+timedelta(minutes=1)), NOW, 24))
        utc = datetime(2026, 10, 22, 22, tzinfo=timezone.utc)
        self.assertTrue(within_window(news('3', '当前', published_at=utc), NOW, 24))

    def test_each_company_gets_evidence_even_when_general_news_scores_higher(self):
        pool = [news(str(i), f'不同市场消息{i}', importance_score=0.99) for i in range(45)]
        for stock in STOCKS:
            pool.append(news(stock.code, stock.name+'独立公告', importance_score=0.2))
        analyzer = AIAnalyzerService.__new__(AIAnalyzerService)
        service = SimpleNamespace(get_all_stocks=lambda: STOCKS)
        with patch('app.services.ai_analyzer.get_watchlist_service', return_value=service):
            summary = analyzer._prepare_news_summary_with_sentiment(pool)
        for stock in STOCKS:
            self.assertIn('[N:'+stock.code+']', summary)

    def test_dedup_keeps_watchlist_evidence_over_generic_copy(self):
        collector = NewsCollectorService.__new__(NewsCollectorService)
        generic = news('generic', '重要经营信息公告', importance_score=0.99)
        specific = news('specific', '[牧原股份] 重要经营信息公告',
                        related_stocks=['002714'], importance_score=0.3)
        service = SimpleNamespace(get_all_stocks=lambda: STOCKS)
        with patch('app.services.news_collector.get_watchlist_service', return_value=service):
            result = collector._deduplicate([generic, specific])
        self.assertEqual([n.id for n in result], ['specific'])


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_high_score_copy_cannot_displace_current_news(self):
        collector = NewsCollectorService.__new__(NewsCollectorService)
        collector._seen_hashes = set()
        collector.rss_feeds = [{}]
        collector.akshare_available = False
        collector.sentiment_analyzer = None
        collector._collect_rss = AsyncMock(return_value=[
            news('old', '相同公告', importance_score=0.99, published_at=NOW-timedelta(days=2)),
            news('fresh', '相同公告', importance_score=0.2)])
        collector._collect_10jqka_news = AsyncMock(return_value=[])
        collector._collect_watchlist_news = AsyncMock(return_value=[])
        collector._collect_radar_news = AsyncMock(return_value=[])
        service = SimpleNamespace(get_all_stocks=lambda: STOCKS)
        with patch('app.services.news_collector.china_now', return_value=NOW), patch(
                'app.services.news_collector.get_watchlist_service', return_value=service):
            result = await collector.collect_all(hours=24)
        self.assertEqual([n.id for n in result], ['fresh'])

    async def test_price_only_analysis_does_not_call_model_or_return_neutral(self):
        analyzer = AIAnalyzerService.__new__(AIAnalyzerService)
        analyzer._call_ai = AsyncMock()
        with self.assertRaisesRegex(RuntimeError, '资料不足'):
            await analyzer.analyze_stock_simple('002714', '牧原股份', 'A', 30, 1)
        analyzer._call_ai.assert_not_awaited()

    async def test_missing_prediction_and_analysis_routes_never_fabricate_success(self):
        for function, args, status in [
            (get_stock_prediction, {'stock_code':'002714'}, 404),
            (trigger_stock_analysis, {'stock_code':'002714'}, 422),
            (generate_watchlist_predictions, {'request':None}, 422),
        ]:
            with self.subTest(route=function.__name__), self.assertRaises(HTTPException) as error:
                await function(**args)
            self.assertEqual(error.exception.status_code, status)


class QuoteEvidenceTests(unittest.TestCase):
    def test_quote_without_trade_timestamp_is_not_called_realtime(self):
        analyzer = AIAnalyzerService.__new__(AIAnalyzerService)
        response = SimpleNamespace(json=lambda: {'data':{'diff':[{'f12':'002714', 'f2':30}]}})
        with patch('requests.get', return_value=response):
            self.assertEqual(analyzer._fetch_watchlist_quotes(STOCKS), {})
