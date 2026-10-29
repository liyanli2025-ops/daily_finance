from spoken_fixtures import reply
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch, AsyncMock

import httpx
from app.services.model_gateway import Route, request_for, completed_text, service_error

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('spoken_acceptance', REPO/'tools/run_spoken_acceptance_once.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class SpokenAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        services = self.root/'app/services'
        services.mkdir(parents=True)
        for name in runner.SOURCES:
            shutil.copyfile(REPO/'backend/app/services'/name, services/name)
        fixture_sources={name:hashlib.sha256((services/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for name in runner.SOURCES}
        source_patch=patch.object(runner,'SOURCES',fixture_sources)
        source_patch.start();self.addCleanup(source_patch.stop)
        origin = self.root/'data/diagnostics/staged-report'
        origin.mkdir(parents=True)
        (origin/(runner.ORIGIN_SHA+'.report.json')).write_text(json.dumps(dict(status='completed_for_human_review', input_sha256=runner.ORIGIN_SHA)), encoding='utf-8')
        self.flag = self.root/'data/.automation-paused'
        self.flag.write_bytes(b'keep paused')
        self.report = REPO/'docs/report_for_spoken_acceptance_20261029.md'
        self.route = Route('ofox_anthropic', runner.MODEL, 'https://api.ofox.io/anthropic/v1', 'fixture-key', 'high')
        self.gateway = SimpleNamespace(resolve_route=Mock(return_value=self.route), request_for=request_for, completed_text=completed_text, service_error=service_error)
        self.client = Mock()
        self.client.__enter__ = Mock(return_value=self.client)
        self.client.__exit__ = Mock(return_value=False)
        self.factory = Mock(return_value=self.client)
        self.usage = Mock(return_value=dict(input_tokens=100, output_tokens=200))

    def response(self, status=200, stop='end_turn', text='已有依据支持有限判断，同时保留必要反证。'):
        return httpx.Response(status, json=dict(stop_reason=stop, content=[dict(type='thinking', thinking='hidden fixture'), dict(type='text', text=text)], usage=dict(input_tokens=100, output_tokens=200)))

    def packet(self):
        return runner.prepare(self.root, self.report)

    def run_once(self):
        return runner.execute(self.root, self.packet(), self.gateway, self.factory, self.usage)

    def test_free_preview_uses_actual_shared_builder_without_http(self):
        from app.services.editorial_policy import spoken_prompts
        with patch('app.services.editorial_policy.spoken_prompts', wraps=spoken_prompts) as builder:
            packet = self.packet()
        builder.assert_called_once()
        expected = builder.call_args
        system, user = spoken_prompts(*expected.args)
        self.assertEqual(packet['messages'], [dict(role='system', content=system), dict(role='user', content=user)])
        self.assertEqual(runner.preview(packet)['http_requests_performed'], 0)
        self.gateway.resolve_route.assert_not_called()
        self.factory.assert_not_called()
        self.assertLess(packet['input_characters'], 15000)

    def test_wrong_source_report_or_missing_origin_stops_without_request(self):
        target = self.root/'app/services/editorial_policy.py'
        original = target.read_bytes()
        target.write_bytes(b'wrong source')
        with self.assertRaises(RuntimeError):
            self.packet()
        target.write_bytes(original)
        fake = self.root/'modified.md'
        fake.write_text('修改稿', encoding='utf-8')
        with self.assertRaises(RuntimeError):
            runner.prepare(self.root, fake)
        (self.root/'data/diagnostics/staged-report'/(runner.ORIGIN_SHA+'.report.json')).unlink()
        with self.assertRaises(FileNotFoundError):
            self.packet()
        self.factory.assert_not_called()

    def test_success_one_request_and_duplicate_never_spends_again(self):
        self.client.post.return_value = self.response()
        path = self.run_once()
        data = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(data['status'], 'completed_for_human_review')
        self.assertNotIn('hidden fixture', path.read_text(encoding='utf-8'))
        self.assertEqual(self.run_once(), path)
        self.client.post.assert_called_once()
        self.assertEqual(self.route.effort, 'high')
        self.assertEqual(self.flag.read_bytes(), b'keep paused')

    def test_timeout_no_retry_and_usage_has_transport_error(self):
        self.client.post.side_effect = httpx.ReadTimeout('fixture')
        path = self.run_once()
        self.assertEqual(json.loads(path.read_text())['status'], 'failed_no_retry')
        self.assertIsInstance(self.usage.call_args.kwargs['error'], httpx.ReadTimeout)
        self.run_once()
        self.client.post.assert_called_once()

    def test_truncation_preserves_visible_raw_text_without_approval(self):
        self.client.post.return_value = self.response(stop='max_tokens')
        data = json.loads(self.run_once().read_text(encoding='utf-8'))
        self.assertEqual(data['status'], 'failed_no_retry')
        self.assertTrue(data['raw_response'])
        self.assertNotIn('script', data)

    def test_billing_error_no_fallback(self):
        self.client.post.return_value = self.response(status=402)
        data = json.loads(self.run_once().read_text())
        self.assertEqual(data['http_status'], 402)
        self.client.post.assert_called_once()

    def test_oversize_output_is_saved_not_truncated_or_repaired(self):
        self.client.post.return_value = self.response(text='有效正文。'*1000)
        data = json.loads(self.run_once().read_text(encoding='utf-8'))
        self.assertEqual(data['status'], 'format_rejected_no_retry')
        self.assertGreater(len(data['script']), 4000)
        self.client.post.assert_called_once()

    def test_missing_pause_or_wrong_podcast_route_stops_before_post(self):
        packet = self.packet()
        self.flag.unlink()
        with self.assertRaises(RuntimeError):
            runner.execute(self.root, packet, self.gateway, self.factory, self.usage)
        self.flag.write_bytes(b'keep paused')
        self.gateway.resolve_route.return_value = Route('compatible', 'other', 'https://example.com', 'fixture', 'none')
        with self.assertRaises(RuntimeError):
            runner.execute(self.root, packet, self.gateway, self.factory, self.usage)
        self.factory.assert_not_called()


class CanonicalSpeechTests(unittest.IsolatedAsyncioTestCase):
    async def test_normalized_script_matches_the_locked_production_path(self):
        from app.services.podcast_generator import PodcastGeneratorService
        from app.models.report import ReportType
        from datetime import date
        raw = '若未来1—3日保持优势，保留判断。\n\n条件≤30时回查。\n\n反证仍保留。\n\n还有一个相关变化。'
        service = PodcastGeneratorService.__new__(PodcastGeneratorService)
        service.ai_client = True
        service._call_ai_for_podcast = AsyncMock(return_value=reply(raw,'原事实和条件'))
        service._verify_podcast_script = AsyncMock()
        report = SimpleNamespace(title='早报', content='原事实和条件')
        with patch('app.services.report_diagnostics.save_spoken_case', return_value=Path('fixture.json')), patch('app.services.report_diagnostics.mark_spoken_case'):
            actual = await service._generate_ai_podcast_script(report, '', date(2026, 10, 29), ReportType.MORNING, False)
        self.assertEqual(runner.canonical_script(raw), actual)
