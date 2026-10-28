import asyncio
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch

from app.models.news import News
from app.services.technical_radar import indicators,parse_bars,TechnicalRadar,prompt
from app.services.event_observations import EventObservations,canonical
from app.services.news_collector import NewsCollectorService
from app.services.watchlist_service import WatchlistService
from app.services.ai_analyzer import AIAnalyzerService

NOW=datetime(2026,10,23,18)


def bars(count=70):
    days=[]
    day=NOW.date()
    while len(days)<count:
        if day.weekday()<5:days.append(day)
        day-=timedelta(days=1)
    return [dict(date=day.isoformat(),open=100+i,close=101+i,high=102+i,low=99+i,volume=100)
            for i,day in enumerate(reversed(days))]


def article(identifier='one',url='https://example.com/a',title='政策发生变化',body='正文',published=None):
    return News(id=identifier,title=title,content=body,source='测试',source_url=url,published_at=published or NOW-timedelta(hours=1))


class TechnicalTests(unittest.TestCase):
    def test_warmup_and_known_monotone_series(self):
        self.assertIsNone(indicators(bars(14))['rsi14'])
        result=indicators(bars())
        self.assertEqual(result['rsi14'],100)
        self.assertEqual(result['atr14'],3)
        self.assertEqual(result['volume_vs_prior20'],1)
        self.assertIsNone(indicators(bars(),False)['volume_vs_prior20'])
        self.assertAlmostEqual(result['return_5d_pct'],(170/165-1)*100,places=4)
        self.assertEqual(result['ma20'],160.5)

    def payload(self):
        return {'code':0,'data':{'sh123456':{'qt':{'sh123456':['','测试','123456']},
            'qfqday':[[b['date'],b['open'],b['close'],b['high'],b['low'],b['volume']] for b in bars()]}}}

    def test_intraday_cache_cannot_become_completed_bar_after_close(self):
        rows,_,_=parse_bars(self.payload(),dict(symbol='sh123456',kind='watchlist',market='A'),NOW.replace(hour=13),NOW)
        self.assertEqual(rows[-1]['date'],'2026-10-22')

    def test_reject_identity_nan_and_unadjusted_stock(self):
        instrument=dict(symbol='sh123456',kind='watchlist',market='A')
        for mutation in ['identity','nan','adjustment']:
            data=self.payload();node=data['data']['sh123456']
            if mutation=='identity':node['qt']['sh123456'][2]='999999'
            if mutation=='nan':node['qfqday'][-1][2]='nan'
            if mutation=='adjustment':node['day']=node.pop('qfqday')
            with self.assertRaises(ValueError):parse_bars(data,instrument,NOW,NOW)

    def test_relative_strength_requires_identical_dates(self):
        with tempfile.TemporaryDirectory() as temporary:
            radar=TechnicalRadar(temporary)
            def fetch(item,deadline):
                history=bars()
                if item['symbol']=='sh512480':history.pop(-3)
                return dict(**item,status='ok',bars=history,metrics=indicators(history))
            with patch.object(radar,'fetch',side_effect=fetch):data=radar.collect([])
            proxy=next(row for row in data['instruments'] if row['symbol']=='sh512480')
            self.assertIsNone(proxy['metrics']['excess_5d_percentage_points'])
            self.assertEqual(data['breadth']['status'],'unavailable')

    def test_stale_snapshot_does_not_enter_prompt(self):
        with tempfile.TemporaryDirectory() as temporary:
            Path(temporary,'technical.json').write_text(json.dumps({'collected_at':(NOW-timedelta(hours=3)).isoformat()}))
            self.assertIn('无有效技术快照',prompt([],temporary,NOW))


class ObservationTests(unittest.TestCase):
    def test_standalone_and_wrapped_source_history_keep_partial_failures_visible(self):
        for wrapped in (False,True):
            with self.subTest(wrapped=wrapped),tempfile.TemporaryDirectory() as temporary:
                media=dict(sources=dict(wscn=dict(status='partial',read=7,errors=[{'error':'ValueError'}]),
                                        stcn=dict(status='ok',read=2,errors=[])))
                ledger=EventObservations(temporary)
                ledger.observe([article()],dict(media=media) if wrapped else media,NOW)
                context=ledger.context([article()],NOW)
                self.assertIn('"wscn": {"status": "partial", "read": 7, "errors": 1}',context)
                self.assertIn('"stcn": {"status": "ok", "read": 2, "errors": 0}',context)

    def test_canonical_preserves_article_identity_queries(self):
        self.assertEqual(canonical('https://example.com/view?id=23&utm_source=x#page'),'https://example.com/view?id=23')
        self.assertNotEqual(canonical('https://example.com/view?id=23'),canonical('https://example.com/view?id=24'))

    def test_history_survives_restart_and_reposts_do_not_become_independent_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            old=article(published=NOW-timedelta(days=1))
            ledger=EventObservations(temporary)
            ledger.observe([old],{'status':'partial'},NOW)
            updated=article(body='改过的正文',published=NOW-timedelta(days=1))
            repost=article('two','https://another.test/repost',body='改过的正文',published=NOW-timedelta(days=1))
            EventObservations(temporary).observe([updated,repost],{'status':'failed'},NOW+timedelta(hours=1))
            context=EventObservations(temporary).context([updated],NOW+timedelta(hours=1))
            self.assertIn('"content_versions": 2',context)
            self.assertIn('"same_title_urls_72h": 2',context)
            self.assertIn('"independent_corroboration": "unknown"',context)
            self.assertIn(NOW.isoformat(),context)
            self.assertIn('failed',context)
            self.assertIn('"same_body_urls": 2',context)

    def test_missing_history_does_not_create_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertIn('历史尚未建立',EventObservations(temporary).context([]))
            self.assertFalse(Path(temporary,'observations.db').exists())


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_global_article_is_not_lost_at_china_filter(self):
        collector=NewsCollectorService.__new__(NewsCollectorService)
        collector.china_keywords=[];collector.global_market_keywords=[]
        item=article();item.market_impact='全市场事件入口';item.importance_score=.74
        self.assertEqual(collector.filter_china_related([item]),[item])

    async def test_empty_watchlist_still_collects_market_and_technicals(self):
        collector=NewsCollectorService.__new__(NewsCollectorService)
        collector._load_db_watchlist=AsyncMock(return_value=[])
        item=article()
        with patch('app.services.news_collector.get_watchlist_service',return_value=WatchlistService()), \
                patch('app.services.research_hub.ResearchHub.load',return_value=[]), \
                patch('app.services.media_sources.MediaCollector.collect',return_value=([item],{})) as media, \
                patch('app.services.policy_sources.PolicyCollector.collect',return_value=([],{'sources':{}})), \
                patch('app.services.public_news_sources.PublicNewsCollector.collect',return_value=([],{'sources':{}})), \
                patch('app.services.overseas_sources.OverseasCollector.collect',return_value=([],{'sources':{}})), \
                patch('app.services.technical_radar.TechnicalRadar.collect',return_value={'coverage':{}}) as technical, \
                patch('app.services.microstructure.MicrostructureRadar.collect',return_value={}) as microstructure:
            self.assertEqual(await collector._collect_radar_news(24),[item])
            self.assertEqual(media.call_args.args[0],[])
            technical.assert_called_once_with([])
            microstructure.assert_called_once_with([])

    async def test_market_event_survives_high_score_generic_flood(self):
        event=article('market');event.market_impact='全市场事件入口';event.importance_score=.1
        pool=[article(str(i),'https://example.com/'+str(i),title='普通市场新闻'+str(i)) for i in range(45)]
        for item in pool:item.importance_score=.99
        analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
        with patch('app.services.ai_analyzer.get_watchlist_service',return_value=SimpleNamespace(get_all_stocks=lambda:[])):
            text=analyzer._prepare_news_summary(pool+[event])
        self.assertIn('[N:market]',text)
