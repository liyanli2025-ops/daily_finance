import importlib.util,io,json,tempfile,unittest
from contextlib import redirect_stdout
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock,patch

from app.config import settings
from app.services.primary_discovery import Limits

spec=importlib.util.spec_from_file_location('primary_runner_test',Path(__file__).resolve().parents[2]/'tools/run_primary_collection_once.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
STOCKS=[dict(market='A',code='300750',name='宁德时代')]
ROUTE=SimpleNamespace(provider='ofox_anthropic',model='fixture-model',base_url='https://api.ofox.io/anthropic/v1',
                      effort='none',api_key='private-secret-never-display')


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);flag=self.root/'data/.automation-paused';flag.parent.mkdir();flag.write_text('preserve')
        self.stocks=patch('app.services.watchlist_repository.read_app_watchlist',new=AsyncMock(return_value=STOCKS))
        self.stocks.start();self.addCleanup(self.stocks.stop)
        self.route=patch('app.services.model_gateway.resolve_route',return_value=ROUTE);self.route.start();self.addCleanup(self.route.stop)
        self.caps=patch('app.services.web_research.capabilities',return_value=dict(configured=True));self.caps.start();self.addCleanup(self.caps.stop)
        self.output=io.StringIO();self.redirect=redirect_stdout(self.output);self.redirect.__enter__();self.addCleanup(self.redirect.__exit__,None,None,None)

    async def test_free_preview_stable_and_no_secret_or_network(self):
        with patch('httpx.AsyncClient') as client,patch('app.services.web_research.requests.post') as post:
            first=await runner.prepare(self.root);second=await runner.prepare(self.root)
        self.assertEqual(first['input_sha256'],second['input_sha256']);client.assert_not_called();post.assert_not_called()
        self.assertNotIn(ROUTE.api_key,self.output.getvalue())
        self.assertFalse(runner.paths(self.root)[2].exists())

    async def test_wrong_fingerprint_stops_before_marker_and_model(self):
        await runner.prepare(self.root);factory=Mock()
        with self.assertRaisesRegex(RuntimeError,'指纹'):await runner.execute(self.root,'wrong',model_factory=factory)
        factory.assert_not_called();self.assertFalse(runner.paths(self.root)[2].exists())

    async def test_marker_blocks_repeated_run_before_any_account_checks(self):
        marker=runner.paths(self.root)[2];marker.parent.mkdir(exist_ok=True);marker.write_text('attempted')
        with patch('app.services.watchlist_repository.read_app_watchlist',new=AsyncMock()) as stocks:
            await runner.execute(self.root,'anything')
        stocks.assert_not_called()

    async def test_expired_input_stops_without_charge_marker(self):
        await runner.prepare(self.root);path=runner.paths(self.root)[0];value=json.loads(path.read_text())
        from app.services.time_context import china_now
        value['expires_at']=(china_now()-timedelta(seconds=1)).isoformat();path.write_text(json.dumps(value))
        with self.assertRaisesRegex(RuntimeError,'超过2小时'):await runner.execute(self.root,runner.digest(value))
        self.assertFalse(runner.paths(self.root)[2].exists())

    async def test_failure_keeps_receipt_pause_and_original_search_settings(self):
        info=await runner.prepare(self.root)
        ws=SimpleNamespace(path=self.root/'workspace',web_search_attempts=1)
        async def fail(workspace,stocks,**kwargs):
            self.assertTrue(settings.research_web_search_enabled)
            self.assertEqual(settings.research_web_search_max_requests,8)
            kwargs['checkpoint'](dict(status='running',body_url_calls=0,provided_ids=[]))
            raise RuntimeError('synthetic fault')
        with patch('app.services.episode_workspace.EpisodeWorkspace',return_value=ws),\
             patch('app.services.primary_discovery.discover',side_effect=fail),\
             patch.object(settings,'research_web_search_enabled',False),patch.object(settings,'research_web_search_max_requests',4):
            result=await runner.execute(self.root,info['input_sha256'],model_factory=Mock())
            self.assertFalse(settings.research_web_search_enabled);self.assertEqual(settings.research_web_search_max_requests,4)
        self.assertEqual(result['status'],'failed_no_retry');self.assertTrue(result['pause_preserved'])
        self.assertTrue(runner.paths(self.root)[2].exists());self.assertEqual(result['research']['status'],'running')

    async def test_mutated_watchlist_cannot_run_prepared_input(self):
        info=await runner.prepare(self.root)
        with patch('app.services.watchlist_repository.read_app_watchlist',new=AsyncMock(return_value=[])):
            with self.assertRaisesRegex(RuntimeError,'名单'):await runner.execute(self.root,info['input_sha256'])
        self.assertFalse(runner.paths(self.root)[2].exists())

    async def test_isolated_transport_does_not_retry_after_connection_error(self):
        state=dict(model_http_attempts=0,usage=[]);factory=Mock()
        client=AsyncMock();client.post.side_effect=RuntimeError('synthetic connection failure')
        factory.return_value.__aenter__=AsyncMock(return_value=client)
        factory.return_value.__aexit__=AsyncMock(return_value=False)
        model=runner.IsolatedModel(ROUTE,Limits(),Mock(),state,Mock(),factory)
        with patch('app.services.model_gateway.request_for',return_value=('https://api.ofox.io/endpoint',{},{})),\
             patch('app.services.model_usage.record_usage',return_value={'fixture':True}):
            with self.assertRaises(RuntimeError):await model('analysis',[dict(role='user',content='test')],100)
        self.assertEqual(client.post.await_count,1);self.assertEqual(state['model_http_attempts'],1)
        self.assertEqual(len(state['usage']),1)

    async def test_missing_pause_stops_isolated_transport_before_reserving_post(self):
        state=dict(model_http_attempts=0,usage=[]);factory=Mock()
        guard=Mock(side_effect=RuntimeError('pause changed'))
        model=runner.IsolatedModel(ROUTE,Limits(),guard,state,Mock(),factory)
        with self.assertRaisesRegex(RuntimeError,'pause changed'):await model('analysis',[dict(role='user',content='test')],100)
        factory.assert_not_called();self.assertEqual(state['model_http_attempts'],0)
