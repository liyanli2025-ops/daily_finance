import asyncio
from datetime import datetime,timedelta
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch

from app.services.watchlist_preparation import PreparationService
from app.services.watchlist_repository import watchlist_signature,WatchlistChangedError,assert_watchlist_current
from app.services.episode_workspace import _current
from app.services.ai_analyzer import AIAnalyzerService

RECORD=dict(id='record-a',code='600123',name='动态公司',market='A')
NOW=datetime(2026,10,28,18)


def complete():return dict(history=dict(status='ok',observations=180),profile=dict(status='ok'),
    news=dict(status='ok',company_articles=1),research=dict(coverage={}))


class PreparationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.reader=AsyncMock(return_value=[RECORD]);self.worker=AsyncMock(return_value=complete())
        self.service=PreparationService(self.root,self.reader,self.worker)
        self.clock=patch('app.services.watchlist_preparation.china_now',return_value=NOW)
        self.clock.start();self.addCleanup(self.clock.stop)

    async def test_pause_blocks_queue_and_status_reads_do_not_collect(self):
        (self.root/'.automation-paused').touch()
        status,attempt=self.service.queue(RECORD)
        self.assertEqual(status['status'],'paused');self.assertIsNone(attempt)
        self.assertFalse(self.service.root.exists())
        self.worker.assert_not_awaited();self.reader.assert_not_awaited()

    async def test_real_worker_uses_dynamic_stock_and_public_archive_without_models(self):
        from app.services.watchlist_preparation import prepare_resources
        from app.models.news import News
        article=News(id='public',title='动态公司披露经营变化',content='公开材料。'*40,
            source='证券时报原文',source_url='https://www.stcn.com/article/detail/123.html',published_at=NOW)
        technical=dict(instruments=[dict(symbol='sh600123',status='ok',bars=[{}]*80,metrics=dict(as_of='2026-10-27'))])
        research=dict(key='A:600123',profile=dict(industry='制造业'),materials=[],coverage={})
        checkpoint=AsyncMock(return_value=[RECORD])
        with patch('app.services.technical_radar.TechnicalRadar.collect',return_value=technical) as daily,patch('app.services.research_hub.ResearchHub.collect_stock',return_value=research) as hub,patch('app.services.media_sources.MediaCollector.collect',return_value=([article],{})) as media,patch('app.services.news_archive.NewsArchive.save') as archive,patch('app.services.model_gateway.complete',AsyncMock(side_effect=AssertionError('no models'))) as model:
            result=await prepare_resources(RECORD,checkpoint)
        self.assertEqual(daily.call_args.args[0][0].code,'600123')
        self.assertEqual(hub.call_args.args[0].name,'动态公司')
        self.assertEqual(media.call_args.args[0][0].code,'600123')
        self.assertEqual(result['news']['company_articles'],1)
        self.assertEqual(result['history']['observations'],80)
        archive.assert_called_once();model.assert_not_awaited()

    async def test_duplicate_add_or_click_only_runs_once(self):
        _,attempt=self.service.queue(RECORD)
        _,again=self.service.queue(RECORD);self.assertEqual(again,attempt)
        await asyncio.gather(self.service.run(RECORD,attempt),self.service.run(RECORD,again))
        self.worker.assert_awaited_once()
        self.assertEqual(self.service.status(RECORD)['status'],'complete')
        _,repeat=self.service.queue(RECORD);self.assertIsNone(repeat)

    async def test_os_lock_deduplicates_two_service_instances(self):
        entered=asyncio.Event();release=asyncio.Event()
        async def worker(record,checkpoint):entered.set();await release.wait();return complete()
        self.service.worker=AsyncMock(side_effect=worker)
        _,attempt=self.service.queue(RECORD)
        task=asyncio.create_task(self.service.run(RECORD,attempt));await entered.wait()
        other=PreparationService(self.root,self.reader,self.worker)
        await other.run(RECORD,attempt)
        self.worker.assert_not_awaited();release.set();await task

    async def test_removed_and_readded_stock_does_not_reuse_old_record(self):
        _,attempt=self.service.queue(RECORD)
        replacement=dict(RECORD,id='new-record')
        self.reader.return_value=[replacement]
        await self.service.run(RECORD,attempt)
        self.worker.assert_not_awaited()
        self.assertEqual(self.service.status(RECORD)['status'],'cancelled')
        self.assertNotEqual(self.service.path(RECORD),self.service.path(replacement))

    async def test_deletion_during_collection_stops_later_stages(self):
        async def worker(record,checkpoint):
            self.reader.return_value=[]
            await checkpoint('下一阶段不可运行')
            raise AssertionError('must stop')
        self.service.worker=worker
        _,attempt=self.service.queue(RECORD);await self.service.run(RECORD,attempt)
        self.assertEqual(self.service.status(RECORD)['status'],'cancelled')

    async def test_pause_during_collection_stops_later_stages(self):
        async def worker(record,checkpoint):
            (self.root/'.automation-paused').touch()
            await checkpoint('下一阶段不可运行')
        self.service.worker=worker
        _,attempt=self.service.queue(RECORD);await self.service.run(RECORD,attempt)
        self.assertEqual(self.service.read(RECORD)['status'],'paused')
        (self.root/'.automation-paused').unlink()
        self.assertEqual(self.service.status(RECORD)['status'],'not_prepared')

    async def test_zero_company_news_is_not_complete_or_no_news_claim(self):
        coverage=complete();coverage['news']=dict(status='no_company_material',company_articles=0)
        self.worker.return_value=coverage
        _,attempt=self.service.queue(RECORD);await self.service.run(RECORD,attempt)
        status=self.service.status(RECORD)
        self.assertEqual(status['status'],'partial')
        self.assertIn('未取得公司专属新闻',status['message'])

    async def test_short_history_and_research_failure_remain_partial(self):
        coverage=complete();coverage['history']=dict(status='partial',observations=12)
        coverage['research']['coverage']={'financial':dict(status='failed')}
        self.worker.return_value=coverage
        _,attempt=self.service.queue(RECORD);await self.service.run(RECORD,attempt)
        self.assertEqual(self.service.status(RECORD)['status'],'partial')
        self.assertIn('12期',self.service.status(RECORD)['message'])

    async def test_worker_exception_does_not_leak_error_body_or_auto_retry(self):
        self.worker.side_effect=RuntimeError('private error text')
        _,attempt=self.service.queue(RECORD);await self.service.run(RECORD,attempt)
        self.assertEqual(self.service.status(RECORD)['status'],'failed')
        self.assertNotIn('private',self.service.path(RECORD).read_text(encoding='utf-8'))
        self.assertIsNone(self.service.queue(RECORD)[1])

    async def test_queued_work_can_be_rescheduled_after_process_restart(self):
        _,attempt=self.service.queue(RECORD)
        restarted=PreparationService(self.root,self.reader,self.worker)
        self.assertEqual(restarted.status(RECORD)['status'],'queued')
        _,same=restarted.queue(RECORD);self.assertEqual(same,attempt)
        await restarted.run(RECORD,same)
        self.worker.assert_awaited_once()

    async def test_interrupted_record_is_recoverable_only_on_explicit_queue(self):
        _,old=self.service.queue(RECORD)
        data=self.service.read(RECORD);data['status']='collecting'
        self.service.path(RECORD).write_text(json.dumps(data),encoding='utf-8')
        self.service.status(RECORD);self.worker.assert_not_awaited()
        data['updated_at']=(NOW-timedelta(minutes=4)).isoformat()
        self.service.path(RECORD).write_text(json.dumps(data),encoding='utf-8')
        self.assertEqual(self.service.status(RECORD)['status'],'interrupted')
        _,new=self.service.queue(RECORD);self.assertNotEqual(old,new)
        await self.service.run(RECORD,old);self.worker.assert_not_awaited()
        await self.service.run(RECORD,new);self.worker.assert_awaited_once()

    async def test_status_becomes_stale_without_silent_refresh(self):
        _,attempt=self.service.queue(RECORD);await self.service.run(RECORD,attempt)
        with patch('app.services.watchlist_preparation.china_now',return_value=NOW+timedelta(hours=3)):
            self.assertEqual(self.service.status(RECORD)['status'],'stale')
        self.worker.assert_awaited_once()

    async def test_summary_expires_without_removing_lock_or_other_files(self):
        from app.services.material_lifecycle import prune_material_caches
        self.service.queue(RECORD)
        path=self.service.path(RECORD);data=self.service.read(RECORD)
        data['updated_at']=(NOW-timedelta(hours=25)).isoformat();path.write_text(json.dumps(data),encoding='utf-8')
        result=prune_material_caches(self.root,NOW)
        self.assertIn(str(path.relative_to(self.root)),result['removed'])
        self.assertTrue(path.with_suffix('.lock').exists())


class RevisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_gateway_rechecks_membership_before_its_internal_retry(self):
        import httpx
        from app.services import model_gateway as gateway
        from app.config import Settings
        config=Settings(_env_file=None,openai_api_key='test',openai_base_url='https://api.ofox.io/v1',ai_model='anthropic/claude-sonnet-5.5')
        calls=[]
        def respond(request):calls.append(request);return httpx.Response(503,json={'error':{'message':'temporary'}})
        original=httpx.AsyncClient
        token=_current.set(SimpleNamespace(watchlist_signature=watchlist_signature([RECORD])))
        try:
            with patch.object(gateway,'settings',config),patch.object(gateway.httpx,'AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(respond),**kw)),patch('app.services.watchlist_repository.read_app_watchlist',AsyncMock(side_effect=[[RECORD],[]])),patch.object(gateway.asyncio,'sleep',AsyncMock()),patch('app.services.model_usage.record_usage'):
                with self.assertRaises(WatchlistChangedError):await gateway.complete('analysis',[dict(role='user',content='test')])
            self.assertEqual(len(calls),1)
        finally:_current.reset(token)

    async def test_signature_is_order_independent_and_market_specific(self):
        hk=dict(RECORD,market='HK')
        self.assertEqual(watchlist_signature([RECORD,hk]),watchlist_signature([hk,RECORD]))
        self.assertNotEqual(watchlist_signature([RECORD]),watchlist_signature([hk]))
        with patch('app.services.watchlist_repository.read_app_watchlist',AsyncMock(return_value=[])):
            with self.assertRaises(WatchlistChangedError):await assert_watchlist_current(watchlist_signature([RECORD]))

    async def test_change_before_model_stops_before_billing(self):
        token=_current.set(SimpleNamespace(watchlist_signature=watchlist_signature([RECORD])))
        try:
            with patch('app.services.watchlist_repository.read_app_watchlist',AsyncMock(return_value=[])),patch('app.services.ai_analyzer.complete',AsyncMock()) as call:
                with self.assertRaises(WatchlistChangedError):await AIAnalyzerService()._call_ai('prompt')
                call.assert_not_awaited()
        finally:_current.reset(token)

    async def test_change_during_model_keeps_reply_and_stops_without_retry(self):
        token=_current.set(SimpleNamespace(watchlist_signature=watchlist_signature([RECORD])))
        try:
            with patch('app.services.watchlist_repository.read_app_watchlist',AsyncMock(side_effect=[[RECORD],[]])),patch('app.services.ai_analyzer.complete',AsyncMock(return_value='已完成回复')) as call,patch('app.services.report_diagnostics.save_generation_stage') as save:
                with self.assertRaises(WatchlistChangedError):await AIAnalyzerService()._call_ai('prompt')
                call.assert_awaited_once();save.assert_called_once_with('watchlist_changed_response','已完成回复')
        finally:_current.reset(token)


class PreparationApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from fastapi import FastAPI
        import httpx
        from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
        from app.models.database import Base
        from app.routers import stocks
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.engine=create_async_engine('sqlite+aiosqlite:///:memory:')
        async with self.engine.begin() as connection:await connection.run_sync(Base.metadata.create_all)
        self.maker=async_sessionmaker(self.engine,expire_on_commit=False)
        async def db():
            async with self.maker() as session:yield session
        self.worker=AsyncMock(return_value=complete())
        async def reader():
            from sqlalchemy import select
            from app.models.database import StockModel
            async with self.maker() as session:
                rows=(await session.execute(select(StockModel))).scalars().all()
                return [stocks.preparation_record(row) for row in rows]
        self.service=PreparationService(self.root,reader,self.worker)
        app=FastAPI();app.include_router(stocks.router,prefix='/api/stocks');app.dependency_overrides[stocks.get_db]=db
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test')
        self.mock=patch('app.services.watchlist_preparation.get_preparation_service',return_value=self.service)
        self.mock.start();self.addCleanup(self.mock.stop)

    async def asyncTearDown(self):await self.client.aclose();await self.engine.dispose()

    async def test_add_returns_queued_and_poll_reads_real_job_status(self):
        response=await self.client.post('/api/stocks/watchlist',json={key:RECORD[key] for key in ('code','name','market')})
        self.assertEqual(response.status_code,200)
        data=response.json();self.assertEqual(data['preparation']['status'],'queued')
        status=await self.client.get('/api/stocks/watchlist/preparation')
        self.assertEqual(status.json()[data['id']]['status'],'complete')
        self.worker.assert_awaited_once()
        duplicate=await self.client.post('/api/stocks/watchlist',json={key:RECORD[key] for key in ('code','name','market')})
        self.assertEqual(duplicate.status_code,400);self.worker.assert_awaited_once()

    async def test_add_during_pause_persists_stock_without_collecting(self):
        (self.root/'.automation-paused').touch()
        response=await self.client.post('/api/stocks/watchlist',json={key:RECORD[key] for key in ('code','name','market')})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['preparation']['status'],'paused')
        retry=await self.client.post('/api/stocks/watchlist/'+response.json()['id']+'/prepare')
        self.assertEqual(retry.json()['status'],'paused');self.worker.assert_not_awaited()
