"""Recovery checkpoints prevent repeat spending after a failed review."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.models.report import ReportType
from app.services.ai_analyzer import AIAnalyzerService
from app.services.report_diagnostics import save_generation_stage, save_review_case


class ReviewRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def service(self, response):
        service = AIAnalyzerService.__new__(AIAnalyzerService)
        service._call_ai = AsyncMock(return_value=response)
        service._ai_fix_report = AsyncMock()
        return service

    async def test_malformed_review_preserved_before_parser_failure(self):
        raw = '```json\n{"overall_quality":6,"issues":['
        service = self.service(raw)
        with tempfile.TemporaryDirectory() as folder:
            def checkpoint(stage, response):
                return save_generation_stage(stage, response, folder)
            with patch('app.services.report_diagnostics.save_generation_stage', side_effect=checkpoint):
                with self.assertRaises(json.JSONDecodeError):
                    await service._review_and_fix_report(SimpleNamespace(content='原稿'), '', '', '', '', ReportType.MORNING)
            saved = json.loads(service._last_review_response_path.read_text(encoding='utf-8'))
            self.assertEqual(saved['response'], raw)
            self.assertEqual(saved['stage'], 'review_response')
            self.assertEqual(saved['status'], 'unreviewed')
        service._call_ai.assert_awaited_once()
        service._ai_fix_report.assert_not_awaited()

    async def test_raw_checkpoint_failure_stops_before_review_pass(self):
        service = self.service('{"overall_quality":9,"issues":[]}')
        with patch('app.services.report_diagnostics.save_generation_stage', side_effect=RuntimeError('保存失败')), patch('app.services.ai_analyzer.save_review_case') as save:
            with self.assertRaisesRegex(RuntimeError, '保存失败'):
                await service._review_and_fix_report(SimpleNamespace(content='原稿'), '', '', '', '', ReportType.MORNING)
        save.assert_not_called()
        service._call_ai.assert_awaited_once()
        service._ai_fix_report.assert_not_awaited()

    async def test_missing_snapshot_never_triggers_paid_repair(self):
        row = dict(type='逻辑矛盾', severity='high', detail='条件未削弱原判断',
                   check_kind='reasoning', report_quote='跟跌将推翻随板块波动')
        service = self.service(json.dumps(dict(overall_quality=5, issues=[row])))
        with patch('app.services.report_diagnostics.save_generation_stage'), patch('app.services.ai_analyzer.save_review_case', return_value=None):
            with self.assertRaisesRegex(RuntimeError, '停止后续模型请求'):
                await service._review_and_fix_report(SimpleNamespace(content=row['report_quote']), '', '', '', '', ReportType.MORNING)
        service._call_ai.assert_awaited_once()
        service._ai_fix_report.assert_not_awaited()


class ReviewPersistenceTests(unittest.TestCase):
    def test_write_failure_leaves_no_partial_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('app.services.report_diagnostics.os.replace', side_effect=PermissionError('fixture')):
                with self.assertRaisesRegex(RuntimeError, '审查材料保存失败'):
                    save_review_case(SimpleNamespace(content='已付费原稿'), {}, dict(issues=[]), '原文', '', '', '', False, folder)
            self.assertEqual(list(Path(folder).iterdir()), [])


class SpokenReviewRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_malformed_spoken_review_is_saved_without_regenerating_script(self):
        from app.services.podcast_generator import PodcastGeneratorService
        service=PodcastGeneratorService.__new__(PodcastGeneratorService)
        raw='{"passed": false, "issues": ['
        service._call_ai_for_podcast=AsyncMock(return_value=raw)
        report=SimpleNamespace(content='原报告有限判断',summary='摘要',core_opinions=[])
        with tempfile.TemporaryDirectory() as folder:
            with patch('app.services.report_diagnostics.save_generation_stage',side_effect=lambda stage,response,**kwargs:save_generation_stage(stage,response,folder,**kwargs)):
                with self.assertRaises(json.JSONDecodeError):
                    await service._verify_podcast_script('有限判断的口播',report)
            saved=json.loads(service._last_spoken_review_response_path.read_text(encoding='utf-8'))
            self.assertEqual(saved['response'],raw)
            self.assertEqual(saved['stage'],'spoken_review_response')
            self.assertEqual(saved['context']['script'],'有限判断的口播')
            self.assertEqual(saved['context']['report_body'],report.content)
            self.assertEqual(saved['status'],'unreviewed')
        service._call_ai_for_podcast.assert_awaited_once()

    async def test_spoken_checkpoint_failure_cannot_be_reported_as_pass(self):
        from app.services.podcast_generator import PodcastGeneratorService
        service=PodcastGeneratorService.__new__(PodcastGeneratorService)
        service._call_ai_for_podcast=AsyncMock(return_value='{"passed":true,"issues":[]}')
        report=SimpleNamespace(content='原报告',summary='摘要',core_opinions=[])
        with patch('app.services.report_diagnostics.save_generation_stage',side_effect=RuntimeError('保存失败')):
            with self.assertRaisesRegex(RuntimeError,'保存失败'):
                await service._verify_podcast_script('口播',report)
        service._call_ai_for_podcast.assert_awaited_once()

