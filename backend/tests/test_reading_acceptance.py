"""Offline acceptance boundaries; no HTTP, model, database or production fixtures."""
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.services.reading_acceptance import replay, local_time, render_review
from app.services.generic_extraction import runtime_status


class ReadingAcceptanceTests(unittest.TestCase):
    def capture(self, root, name='capture', **overrides):
        raw = b'<html>saved-response</html>'
        (root / (name + '.body')).write_bytes(raw)
        meta = dict(url='https://publisher.example/article/123', http_status=200,
                    content_type='text/html', bytes=len(raw), file=name + '.body',
                    body_sha256=hashlib.sha256(raw).hexdigest(),
                    observed_at='2026-10-31T16:01:00', snapshot_cutoff='2026-10-31T16:00:00')
        meta.update(overrides)
        (root / (name + '.json')).write_text(json.dumps(meta), encoding='utf-8')
        return meta

    def article(self):
        return SimpleNamespace(title='经营与风险', content='实际正文与末尾反证' * 30,
                               source='公开网页可见正文-publisher.example')

    def test_damaged_capture_stops_before_production_parser(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.capture(root, body_sha256='0' * 64)
            with patch('app.services.web_research.parse_visible_article') as parser:
                result = replay(root)
            parser.assert_not_called()
            self.assertEqual(result['rows'][0]['reason'], 'capture_integrity_mismatch')

    def test_duplicate_capture_not_counted_as_two_articles_and_clock_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.capture(root, name='first')
            self.capture(root, name='second')
            with patch('app.services.web_research.parse_visible_article', return_value=self.article()) as parser, \
                 patch('app.services.news_quality.excluded_reason', return_value=None), \
                 patch('app.services.evidence.publication_label', return_value='原始发布时间'):
                result = replay(root)
            self.assertEqual(parser.call_count, 1)
            self.assertEqual(result['counts']['duplicate_capture'], 1)
            row = result['rows'][0]
            self.assertTrue(row['observed_after_cutoff'])
            self.assertFalse(row['available_at_cutoff_verified'])
            self.assertEqual(row['text'], self.article().content)
            self.assertIn('末尾反证', render_review(result))
            for key in ('http_requests', 'search_requests', 'model_requests', 'tts_requests'):
                self.assertEqual(result[key], 0)

    def test_body_paths_and_symlinks_are_not_followed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.capture(root, name='path', file='../outside.body')
            self.capture(root, name='link')
            (root / 'link.body').unlink()
            try:
                (root / 'link.body').symlink_to(root / 'path.body')
            except OSError:
                self.skipTest('symlink unavailable')
            with patch('app.services.web_research.parse_visible_article') as parser:
                result = replay(root)
            parser.assert_not_called()
            self.assertEqual(set(result['reasons']), {'capture_file_path_invalid', 'capture_file_missing_or_symlink'})

    def test_byte_budget_and_specialized_material_never_trigger_parser(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.capture(root, url='https://www.jisilu.cn/question/123')
            with patch('app.services.web_research.parse_visible_article') as parser:
                self.assertEqual(replay(root)['counts']['specialized_reader_required'], 1)
                self.assertEqual(replay(root, max_total_bytes=1)['counts']['not_attempted'], 1)
            parser.assert_not_called()

    def test_admission_failure_is_reported_without_network_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.capture(root)
            with patch('app.services.web_research.parse_visible_article',
                       side_effect=ValueError('web_source_time_missing')):
                result = replay(root)
            self.assertEqual(result['rows'][0]['reason'], 'web_source_time_missing')
            self.assertFalse(result['content_accepted'])
            self.assertFalse(result['paid_trial_authorized'])

    def test_empty_is_not_a_pass_and_timezone_normalizes_to_beijing(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(replay(Path(folder))['status'], 'no_captures')
        self.assertEqual(local_time('2026-10-31T08:00:00Z'), local_time('2026-10-31T16:00:00'))

    def test_broken_optional_dependency_is_distinguished_from_missing_library(self):
        with patch.dict('sys.modules', {'trafilatura': None}):
            self.assertEqual(runtime_status()['reason'], 'generic_extractor_not_installed')
        with patch.dict('sys.modules', {'trafilatura': SimpleNamespace(extract=lambda: None)}), \
             patch('app.services.generic_extraction.importlib.metadata.version', side_effect=RuntimeError('private detail')):
            result = runtime_status()
            self.assertFalse(result['ready'])
            self.assertEqual(result['reason'], 'generic_extractor_runtime_unavailable')
            self.assertNotIn('private detail', json.dumps(result))
