"""News horizon and reusable background policy, without paid requests."""
from dataclasses import asdict
from datetime import datetime, timedelta
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.models.news import News
from app.services.news_collector import NewsCollectorService
from app.services.research_hub import ResearchHub, Material
from app.services.watchlist_service import WatchlistStock, WatchlistService

NOW=datetime(2026,10,25,12)


class NewsWindowTests(unittest.IsolatedAsyncioTestCase):
    async def test_weekend_news_window_reaches_both_company_feeds_before_background_work(self):
        collector=NewsCollectorService.__new__(NewsCollectorService)
        collector.akshare_available=True
        collector._load_db_watchlist=AsyncMock(return_value=[dict(code='002714',name='牧原股份',market='A')])
        collector._collect_individual_stock_news=AsyncMock(return_value=[])
        collector._collect_sector_news=AsyncMock(return_value=[])
        order=[]
        news=News(id='weekend',title='周五新增经营消息',content='有原文的事实',source='来源',
                  source_url='https://example.com/1',published_at=NOW-timedelta(hours=45),related_stocks=['002714'])
        def feed(stock,hours):
            self.assertEqual(hours,168)
            order.append('news')
            return [news],{'status':'ok'}
        async def background(*args,**kwargs):
            self.assertEqual(order,['news','news'])
            order.append('background')
            return {'stocks':[]}
        with patch('app.services.news_collector.china_now',return_value=NOW), \
                patch('app.services.news_collector.get_watchlist_service',return_value=WatchlistService()), \
                patch('app.services.watchlist_sources.fetch_company_announcements',side_effect=feed), \
                patch('app.services.watchlist_sources.fetch_sina_stock_news',side_effect=feed), \
                patch('app.services.media_sources.MediaCollector.collect', return_value=([],{})), \
                patch('app.services.research_hub.ResearchHub.collect',side_effect=background):
            result=await collector._collect_watchlist_news(hours=168)
        self.assertEqual(len(result),2)
        collector._collect_individual_stock_news.assert_not_awaited()

    async def test_diagnostic_window_is_explicit_and_passed_to_both_feeds(self):
        from app import source_check
        with patch.object(source_check,'read_app_watchlist',AsyncMock(return_value=[dict(code='002714',name='牧原股份',market='A')])), \
                patch.object(source_check,'fetch_watchlist_quotes',return_value={}), \
                patch.object(source_check,'fetch_company_announcements',return_value=([],{})) as notices, \
                patch.object(source_check,'fetch_sina_stock_news',return_value=([],{})) as news:
            result=await source_check.inspect(hours=72)
        self.assertEqual(result['news_window_hours'],72)
        self.assertEqual(notices.call_args.kwargs['hours'],72)
        self.assertEqual(news.call_args.kwargs['hours'],72)


class BackgroundPriorityTests(unittest.TestCase):
    def test_large_old_reports_do_not_displace_recent_events_and_remain_reusable(self):
        with tempfile.TemporaryDirectory() as folder:
            hub=ResearchHub(folder)
            materials=[]
            for i,kind in enumerate(['financial_baseline','financial_report','investor_relations','industry_observation']):
                old=kind.startswith('financial')
                date=NOW-timedelta(days=60) if old else NOW-timedelta(hours=12)
                item=Material('id'+str(i),kind,'来源','https://example.com/'+str(i),kind,'A:123456',
                              ('背景。' if old else '近期新增。')*5000,date,NOW.isoformat())
                materials.append({**asdict(item),'published_at':date.isoformat()})
            context=dict(key='A:123456',name='任意自选股',profile=None,coverage={},materials=materials)
            with patch.object(hub,'load',return_value=[context]), \
                    patch('app.services.research_hub.china_now',return_value=NOW):
                first,evidence=hub.prompt([WatchlistStock('123456','任意自选股','A')],max_characters=8000)
                second,_=hub.prompt([WatchlistStock('123456','任意自选股','A')],max_characters=8000)
            self.assertEqual(first,second)  # references do not expire by use count
            self.assertIn('financial_baseline',{m.kind for m in evidence})
            self.assertIn('investor_relations',{m.kind for m in evidence})
            self.assertIn('industry_observation',{m.kind for m in evidence})
            self.assertLess(first.index('[N:id2]'),first.index('[N:id0]'))
            self.assertLess(first.count('背景'),800)
