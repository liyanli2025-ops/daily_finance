import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpx
from app.services.model_gateway import Route, request_for, completed_text, service_error

spec = importlib.util.spec_from_file_location('frozen_report', Path(__file__).resolve().parents[2]/'tools/run_frozen_report_once.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class FrozenReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.folder = self.root/'data/diagnostics/staged-report'
        self.folder.mkdir(parents=True)
        self.flag = self.root/'data/.automation-paused'
        self.flag.write_bytes(b'keep paused')
        self.messages = [dict(role='user', content='固定历史完整写稿输入')]
        self.packet = dict(owner='finance-staged-report-input-v1', messages=self.messages,
            max_http_requests=1, retries=0, max_output_tokens=8000, watchlist=[],
            input_characters=len(json.dumps(self.messages, ensure_ascii=False, separators=(',', ':'))),
            snapshot_collected_at='2026-10-29T07:32:10')
        raw = json.dumps(self.packet, ensure_ascii=False).encode()
        self.sha = hashlib.sha256(raw).hexdigest()
        self.patch = patch.object(runner, 'INPUT_SHA', self.sha)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.input = self.folder/(self.sha+'.input.json')
        self.input.write_bytes(raw)
        self.route = Route('ofox_anthropic', runner.MODEL, 'https://api.ofox.io/anthropic/v1', 'fixture-key', 'high')
        self.gateway = SimpleNamespace(resolve_route=Mock(return_value=self.route), request_for=request_for,
            completed_text=completed_text, service_error=service_error)
        self.client = Mock()
        self.client.__enter__ = Mock(return_value=self.client)
        self.client.__exit__ = Mock(return_value=False)
        self.factory = Mock(return_value=self.client)
        self.usage = Mock(return_value=dict(input_tokens=40, output_tokens=60))
        self.verify = Mock()

    def response(self, status=200, stop='end_turn'):
        return httpx.Response(status, json=dict(stop_reason=stop,
            content=[dict(type='thinking', thinking='hidden fixture'), dict(type='text', text='完整待验收报告')],
            usage=dict(input_tokens=40, output_tokens=60)))

    def run_once(self):
        return runner.execute(self.root, runner.load(self.root), self.gateway, self.factory, self.usage, self.verify)

    def test_default_preview_never_resolves_route_or_requests(self):
        details = runner.preview(runner.load(self.root))
        self.assertEqual(details['http_requests_performed'], 0)
        self.assertEqual(details['max_http_requests'], 1)
        self.gateway.resolve_route.assert_not_called()
        self.factory.assert_not_called()

    def test_success_has_one_post_and_repeat_cannot_spend_again(self):
        self.client.post.return_value = self.response()
        state = self.run_once()
        data = json.loads(state.read_text(encoding='utf-8'))
        self.assertEqual(data['status'], 'completed_for_human_review')
        self.assertEqual(data['response'], '完整待验收报告')
        self.assertNotIn('hidden fixture', state.read_text(encoding='utf-8'))
        self.assertEqual(self.run_once(), state)
        self.client.post.assert_called_once()
        self.assertEqual(self.client.post.call_args.kwargs['json']['messages'], self.messages)
        self.assertEqual(self.client.post.call_args.kwargs['json']['max_tokens'], 8000)
        self.assertEqual(self.flag.read_bytes(), b'keep paused')
        self.assertEqual(self.route.effort, 'high')

    def test_network_failure_never_retries(self):
        self.client.post.side_effect = httpx.ReadTimeout('fixture')
        state = self.run_once()
        self.assertEqual(json.loads(state.read_text())['status'], 'failed_no_retry')
        self.run_once()
        self.client.post.assert_called_once()

    def test_truncation_keeps_visible_text_without_approval(self):
        self.client.post.return_value = self.response(stop='max_tokens')
        data = json.loads(self.run_once().read_text(encoding='utf-8'))
        self.assertEqual(data['response'], '完整待验收报告')
        self.assertEqual(data['status'], 'failed_no_retry')

    def test_billing_failure_does_not_fall_back(self):
        self.client.post.return_value = self.response(status=402)
        data = json.loads(self.run_once().read_text())
        self.assertEqual(data['http_status'], 402)
        self.assertEqual(data['status'], 'failed_no_retry')
        self.client.post.assert_called_once()

    def test_modified_input_stops_before_route_resolution(self):
        self.input.write_bytes(self.input.read_bytes()+b' ')
        with self.assertRaises(RuntimeError):
            self.run_once()
        self.gateway.resolve_route.assert_not_called()
        self.factory.assert_not_called()

    def test_pause_or_watchlist_change_stops_before_post(self):
        self.flag.unlink()
        with self.assertRaises(RuntimeError):
            self.run_once()
        self.flag.write_bytes(b'keep paused')
        self.verify.side_effect = RuntimeError('watchlist changed')
        with self.assertRaises(RuntimeError):
            self.run_once()
        self.factory.assert_not_called()
        self.assertFalse((self.folder/(self.sha+'.report.started')).exists())

    def test_unexpected_model_route_stops_without_post(self):
        self.gateway.resolve_route.return_value = Route('compatible', 'other', 'https://example.com', 'fixture', 'none')
        with self.assertRaises(RuntimeError):
            self.run_once()
        self.factory.assert_not_called()
