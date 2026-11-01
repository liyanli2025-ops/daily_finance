"""Offline billing-boundary checks. All transport/DB/usage calls are mocked."""
import asyncio
from datetime import timedelta
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

try:
    import fcntl
except ImportError:
    raise unittest.SkipTest('Linux服务器验收入口需要fcntl进程锁')

PATH = Path(__file__).resolve().parents[2] / 'tools/run_progress_collection_once.py'
SPEC = importlib.util.spec_from_file_location('progress_collection_runner', PATH)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class ModelBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.value = dict(watchlist=[], budget_plan=dict(model_request_cap=None,
            total_input_characters=10000, total_reserved_output_tokens=6600))
        self.state = dict(research=dict(limits=dict(input_characters=10000, output_tokens=3300)),
            model_http_attempts=0, model_input_characters=0, reserved_output_tokens=0,
            model_exposures=[], usage=[])
        self.messages = [dict(role='user', content='本期研究任务')]
        self.save = MagicMock()
        self.model = runner.AcceptanceModel(Path('unused'), self.value, self.state,
                                             None, MagicMock(), self.save)
        self.response = SimpleNamespace(is_error=False, json=lambda: {})
        self.client = MagicMock()
        self.client.post = AsyncMock(return_value=self.response)
        self.client.__aenter__ = AsyncMock(return_value=self.client)
        self.client.__aexit__ = AsyncMock(return_value=False)
        self.http = self.enterContext(patch('httpx.AsyncClient', return_value=self.client))
        self.enterContext(patch('app.services.watchlist_repository.assert_watchlist_current',
                                new=AsyncMock()))
        self.enterContext(patch('app.services.model_gateway.resolve_route', return_value=object()))
        self.enterContext(patch('app.services.model_gateway.request_for',
            return_value=('https://example.invalid/messages', {}, {'max_tokens': 3300})))
        self.completed = self.enterContext(patch('app.services.model_gateway.completed_text', return_value='{}'))
        self.usage = self.enterContext(patch('app.services.model_usage.record_usage', return_value={}))
        self.enterContext(patch.object(runner, 'body_exposure', return_value={'N1': [[0, 4000]]}))

    async def test_no_fixed_call_cap_but_cumulative_output_stops_before_post(self):
        await self.model('analysis', self.messages, 3300)
        await self.model('analysis', self.messages, 3300)
        with self.assertRaises(runner.CheckError):
            await self.model('analysis', self.messages, 3300)
        self.assertEqual(self.client.post.await_count, 2)
        self.assertEqual(self.state['reserved_output_tokens'], 6600)
        self.assertTrue(all(row['completed_response'] for row in self.state['model_exposures']))

    async def test_cumulative_input_exhaustion_makes_no_post(self):
        self.state['model_input_characters'] = 10000
        with self.assertRaises(runner.CheckError):
            await self.model('analysis', self.messages, 3300)
        self.client.post.assert_not_awaited()
        self.assertEqual(self.state['model_http_attempts'], 0)

    async def test_explicit_emergency_cap_remains_effective(self):
        self.value['budget_plan']['model_request_cap'] = 1
        await self.model('analysis', self.messages, 3300)
        with self.assertRaises(runner.CheckError):
            await self.model('analysis', self.messages, 3300)
        self.assertEqual(self.client.post.await_count, 1)

    async def test_incomplete_response_is_counted_without_confirming_read(self):
        from app.services.model_gateway import IncompleteOutputError
        self.completed.side_effect = IncompleteOutputError('max_tokens', {})
        with self.assertRaises(IncompleteOutputError):
            await self.model('analysis', self.messages, 3300)
        self.assertEqual(self.state['model_http_attempts'], 1)
        self.assertFalse(self.state['model_exposures'][0]['completed_response'])
        self.assertIsInstance(self.usage.call_args.kwargs['error'], IncompleteOutputError)
        self.assertEqual(self.client.post.await_count, 1)

    async def test_cancelled_request_keeps_reservation_and_usage_without_retry(self):
        self.client.post.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.model('analysis', self.messages, 3300)
        self.assertEqual(self.state['reserved_output_tokens'], 3300)
        self.assertEqual(self.client.post.await_count, 1)
        self.assertFalse(self.state['model_exposures'][0]['completed_response'])
        self.usage.assert_called_once()


class ExecutionBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_changed_preview_is_rejected_before_attempt_marker(self):
        from app.services.time_context import china_now
        with tempfile.TemporaryDirectory() as directory:
            backend = Path(directory)
            root, input_file, _, marker = runner.locations(backend)
            root.mkdir(parents=True)
            now = china_now()
            value = dict(owner=runner.OWNER, prepared_at=now.isoformat(),
                         expires_at=(now+timedelta(hours=2)).isoformat())
            input_file.write_text(json.dumps(value))
            with patch.object(runner, 'inputs', new=AsyncMock(return_value=dict(value, changed=True))):
                with self.assertRaises(runner.CheckError):
                    await runner.execute(backend, runner.fingerprint(value))
            self.assertFalse(marker.exists())

    async def test_existing_attempt_is_never_restarted(self):
        with tempfile.TemporaryDirectory() as directory:
            backend = Path(directory)
            root, _, _, marker = runner.locations(backend)
            root.mkdir(parents=True)
            marker.write_text('{}')
            with patch.object(runner, 'inputs', new=AsyncMock()) as inputs:
                with self.assertRaises(runner.CheckError):
                    await runner.execute(backend, 'unused')
                inputs.assert_not_awaited()
            self.assertEqual(marker.read_text(), '{}')


if __name__ == '__main__':
    unittest.main()
