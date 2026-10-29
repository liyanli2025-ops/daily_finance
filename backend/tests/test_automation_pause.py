import ast
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock,Mock,patch


class MaintenanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_keeps_app_database_but_never_starts_jobs_when_paused(self):
        # Execute the actual lifecycle functions without Windows stdout wrapping
        # or importing router side effects; all DB/scheduler effects are mocked.
        source=Path(__file__).resolve().parents[1]/'app/main.py'
        tree=ast.parse(source.read_text(encoding='utf-8'))
        nodes=[node for node in tree.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))
               and node.name in {'automation_paused','lifespan','health_check'}]
        for node in nodes:
            if node.name=='health_check':node.decorator_list=[]
        code=compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),str(source),'exec')
        for paused in (False,True):
            with tempfile.TemporaryDirectory() as folder:
                backend=Path(folder)/'backend';(backend/'data').mkdir(parents=True)
                if paused:(backend/'data/.automation-paused').touch()
                engine=SimpleNamespace(dispose=AsyncMock())
                scheduler=SimpleNamespace(is_running=False,set_db=Mock(),stop=AsyncMock())
                async def start():scheduler.is_running=True
                scheduler.start=AsyncMock(side_effect=start)
                init=AsyncMock(return_value=engine)
                ns=dict(Path=Path,__file__=str(backend/'app/main.py'),FastAPI=object,asynccontextmanager=asynccontextmanager,
                    db_engine=None,scheduler_service=None,settings=SimpleNamespace(app_name='finance',database_url='fixture',
                        podcasts_dir=backend/'podcasts',reports_dir=backend/'reports',daily_report_hour=6,daily_report_minute=0),
                    SchedulerService=lambda:scheduler,init_database=init,get_session_maker=lambda engine:object())
                exec(code,ns)
                app=SimpleNamespace(state=SimpleNamespace())
                async with ns['lifespan'](app):
                    health=await ns['health_check']()
                    self.assertEqual(health['status'],'healthy');self.assertEqual(health['database'],'connected')
                    self.assertEqual(health['automation_paused'],paused)
                    self.assertEqual(health['scheduler'],'stopped' if paused else 'running')
                self.assertEqual(scheduler.start.await_count,0 if paused else 1)
                init.assert_awaited_once();engine.dispose.assert_awaited_once()

    async def test_pause_blocks_all_model_tasks_before_client_route_and_budget(self):
        from app.services import model_gateway as gateway
        with tempfile.TemporaryDirectory() as folder:
            flag=Path(folder)/'paused';flag.touch()
            with patch.object(gateway,'MODEL_PAUSE_FILE',flag), \
                    patch.object(gateway,'resolve_route',side_effect=AssertionError('no route')) as route, \
                    patch.object(gateway.httpx,'AsyncClient',side_effect=AssertionError('no client')) as client, \
                    patch('app.services.model_usage.reserve_call',side_effect=AssertionError('no reservation')) as reserve:
                for task in ('analysis','review','extraction','podcast'):
                    with self.assertRaisesRegex(RuntimeError,'维护暂停'):await gateway.complete(task,[])
                route.assert_not_called();client.assert_not_called();reserve.assert_not_called()

    async def test_pause_created_during_retry_wait_prevents_second_request(self):
        from app.services import model_gateway as gateway
        import httpx
        with tempfile.TemporaryDirectory() as folder:
            flag=Path(folder)/'paused'
            client=AsyncMock();client.__aenter__.return_value=client
            async def post(*args,**kwargs):
                flag.touch();return httpx.Response(429,json={'error':'rate limited'})
            client.post.side_effect=post
            with patch.object(gateway,'MODEL_PAUSE_FILE',flag),patch.object(gateway,'resolve_route',return_value=SimpleNamespace(provider='fixture',model='fixture',effort='none')), \
                    patch.object(gateway,'request_for',return_value=('https://fixture.invalid',{},dict(max_tokens=100))), \
                    patch.object(gateway.httpx,'AsyncClient',return_value=client),patch.object(gateway.asyncio,'sleep',AsyncMock()), patch.object(gateway.settings,'model_http_retries',1), \
                    patch('app.services.model_usage.reserve_call') as reserve,patch('app.services.model_usage.record_usage'):
                with self.assertRaisesRegex(RuntimeError,'维护暂停'):await gateway.complete('review',[])
            client.post.assert_awaited_once();self.assertEqual(reserve.call_count,1)
