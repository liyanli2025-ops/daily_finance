import asyncio
from datetime import date, datetime
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.config import settings
from app.models.database import Base, ReportModel
from app.services import model_usage, podcast_script_cache
from app.services.scheduler import SchedulerService
from app.services.model_gateway import Route


class CostControls(unittest.IsolatedAsyncioTestCase):
    async def test_request_limit_is_enforced_before_extra_call_and_resets_per_run(self):
        class Owner:
            @model_usage.budgeted_generation
            async def generate(self):
                model_usage.reserve_call()
                model_usage.reserve_call()
                with self_test.assertRaisesRegex(RuntimeError,'调用次数'):
                    model_usage.reserve_call()
        self_test=self
        owner=Owner()
        with patch.object(settings,'model_max_calls_per_report',2):
            await owner.generate()
            await owner.generate()
        self.assertIsNone(model_usage._run.get())

    async def test_shared_edition_guard_prevents_morning_evening_overlap(self):
        entered=asyncio.Event()
        release=asyncio.Event()
        calls=[]
        class Owner:
            @model_usage.budgeted_generation
            async def generate(self,label):
                calls.append(label)
                entered.set()
                await release.wait()
        owner=Owner()
        first=asyncio.create_task(owner.generate('morning'))
        await entered.wait()
        await owner.generate('evening')
        release.set()
        await first
        self.assertEqual(calls,['morning'])

    async def test_existing_edition_after_restart_is_skipped_before_collection(self):
        owner=SchedulerService.__new__(SchedulerService)
        owner.is_trading_day=Mock(return_value=False)
        owner._has_saved_edition=AsyncMock(return_value=True)
        with patch('app.services.scheduler.get_news_collector') as collect:
            await owner.generate_morning_report()
        collect.assert_not_called()

    async def test_unified_acceptance_never_calls_a_model(self):
        from app import preflight
        local={'ready':True,'watchlist':{'readable':True}}
        market=dict(ready=True,date='2026-10-25',indices=[],global_indices=[],source_status={})
        sources=dict(stocks=[],research={'stocks':[]})
        with patch.object(preflight,'inspect',AsyncMock(return_value=local)), \
                patch.object(preflight,'check_market_sources',AsyncMock(return_value=market)), \
                patch('app.source_check.inspect',AsyncMock(return_value=sources)), \
                patch.object(preflight,'check_model_access',AsyncMock()) as paid:
            result=await preflight.acceptance_without_models()
        paid.assert_not_called()
        self.assertTrue(result['paid_acceptance_pending'])

    async def test_database_guard_distinguishes_date_and_edition(self):
        engine=create_async_engine('sqlite+aiosqlite:///:memory:')
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            maker=async_sessionmaker(engine,expire_on_commit=False)
            async with maker() as session:
                session.add(ReportModel(id='fixture',title='测试',summary='测试',content='已生成内容',
                    report_date=date(2026,10,25),report_type='morning'))
                await session.commit()
            owner=SchedulerService.__new__(SchedulerService)
            owner._session_maker=maker
            self.assertTrue(await owner._has_saved_edition(date(2026,10,25),'morning'))
            self.assertFalse(await owner._has_saved_edition(date(2026,10,25),'evening'))
            self.assertFalse(await owner._has_saved_edition(date(2026,10,24),'morning'))
        finally:
            await engine.dispose()

    def test_usage_records_tokens_and_status_but_never_request_or_credentials(self):
        route=Route('compatible','model','https://example.com','sensitive-key','none')
        response=httpx.Response(200,json={'usage':{'prompt_tokens':123,'completion_tokens':45},
                                        'content':'sensitive-response'})
        with tempfile.TemporaryDirectory() as directory:
            row=model_usage.record_usage('analysis',route,4000,response=response,directory=directory)
            text=next(Path(directory).glob('*.jsonl')).read_text(encoding='utf-8')
            self.assertEqual(row['input_tokens'],123)
            self.assertEqual(row['output_tokens'],45)
            self.assertNotIn('sensitive-key',text)
            self.assertNotIn('sensitive-response',text)
            missing=model_usage.record_usage('analysis',route,4000,response=httpx.Response(402),directory=directory)
            self.assertIsNone(missing['output_tokens'])
            self.assertEqual(missing['http_status'],402)

    def test_verified_script_cache_requires_same_facts_routing_and_intact_script(self):
        report=SimpleNamespace(report_date=date(2026,10,25),report_type='morning',content='事实原文',summary='摘要',core_opinions=[])
        script='已核验的口播稿。'*40
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(podcast_script_cache.load(report,'用户',directory))
            podcast_script_cache.save(report,'用户',script,directory)
            self.assertEqual(podcast_script_cache.load(report,'用户',directory),script)
            with patch.object(settings,'podcast_model','different-model'):
                self.assertIsNone(podcast_script_cache.load(report,'用户',directory))
            report.content='更新后的事实'
            self.assertIsNone(podcast_script_cache.load(report,'用户',directory))
            report.content='事实原文'
            path=next(Path(directory).glob('*.json'))
            cached=json.loads(path.read_text(encoding='utf-8'))
            cached['script']='被误改的口播稿。'*40
            path.write_text(json.dumps(cached),encoding='utf-8')
            self.assertIsNone(podcast_script_cache.load(report,'用户',directory))

    def test_cross_border_selection_needs_business_or_macro_relevance(self):
        from app.models.news import News, NewsType
        from app.services.news_collector import NewsCollectorService
        from app.services.watchlist_service import WatchlistStock
        items=[News(id=str(i),title=title,content='原文内容',source='测试',published_at=datetime(2026,10,25),
                    news_type=NewsType.TECH,importance_score=.9) for i,title in enumerate([
                        '三体剧集官宣概念海报','Wi-Fi手机使用小技巧','美联储公布利率决定','新关注企业公布量产计划'])]
        owner=NewsCollectorService.__new__(NewsCollectorService)
        service=SimpleNamespace(get_all_stocks=lambda:[WatchlistStock('003456','新关注企业','A')])
        with patch('app.services.news_collector.get_watchlist_service',return_value=service):
            selected=owner.filter_cross_border_news(items)
        self.assertEqual([item.id for item in selected],['2','3'])
