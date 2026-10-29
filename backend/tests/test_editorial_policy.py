from spoken_fixtures import reply
"""Offline safety regressions, not evidence of prediction or listening quality."""
import json
from datetime import date
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.models.report import ReportType
from app.services.ai_analyzer import AIAnalyzerService
from app.services.backtest_service import BacktestService
from app.services.lessons_memory_service import LessonsMemoryService
from app.services.podcast_generator import PodcastGeneratorService
from app.services.editorial_policy import SPOKEN_POLICY


class InvalidAccuracyTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_watch_recommendations_cannot_generate_accuracy(self):
        service = BacktestService()
        service.set_db(Mock(side_effect=AssertionError('must not read/write legacy scores')))
        report = SimpleNamespace(content='建议观望，关注半导体板块', core_opinions=['关注机会'])
        self.assertIsNone(await service.evaluate_morning_predictions(report))
        self.assertEqual(await service.get_recent_accuracy(), {})
        self.assertEqual(await service.get_backtest_summary_text(), '')
        service._session_maker.assert_not_called()

    async def test_historical_scores_do_not_become_model_lessons(self):
        service = LessonsMemoryService()
        service.set_db(Mock(side_effect=AssertionError('legacy scores are not evidence')))
        service._get_accuracy_stats = AsyncMock(return_value={'total': 99, 'avg_overall': 1.0})
        self.assertEqual(await service.get_lessons_memory_text(), '')
        service._get_accuracy_stats.assert_not_awaited()
        service._session_maker.assert_not_called()


class EditorialGatesTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_with_sources_but_rejected_reasoning_cannot_publish(self):
        analyzer = AIAnalyzerService.__new__(AIAnalyzerService)
        report = SimpleNamespace(content='材料属实，但“经营改善所以明天必涨”的推断无依据')
        rejected = json.dumps({'overall_quality': 8, 'issues': [
            {'severity': 'high', 'type': '逻辑错误', 'detail': '经营改善不能直接推出明天上涨',
             'check_kind':'reasoning','report_quote':'经营改善'}]})
        analyzer._call_ai = AsyncMock(return_value=rejected)
        analyzer._ai_fix_report = AsyncMock(return_value=report)
        with patch('app.services.ai_analyzer.save_review_case'):
            with self.assertRaisesRegex(RuntimeError, '复核'):
                await analyzer._review_and_fix_report(report, '', '', '原始材料', '', ReportType.MORNING)
        # A high numerical editing score must not overrule unresolved issues.
        self.assertEqual(analyzer._call_ai.await_count, 2)

    async def test_audio_cannot_omit_conditions_even_if_other_facts_match(self):
        generator = PodcastGeneratorService.__new__(PodcastGeneratorService)
        generator._call_ai_for_podcast = AsyncMock(return_value=json.dumps({
            'passed': False, 'issues': ['口播删除关键条件，将经营改善升级成股价上涨']}))
        report = SimpleNamespace(content='仅经营改善；股价影响尚待验证', summary='', core_opinions=[])
        with self.assertRaisesRegex(RuntimeError, '核验未通过'):
            await generator._verify_podcast_script('股价将上涨', report)

    async def test_spoken_editing_uses_existing_generation_and_review_calls(self):
        generator = PodcastGeneratorService.__new__(PodcastGeneratorService)
        generator.ai_client = True
        generator._call_ai_for_podcast = AsyncMock(return_value=reply('有来源的新增变化。' * 30,'事实与条件'))
        generator._verify_podcast_script = AsyncMock()
        report = SimpleNamespace(title='测试', content='事实与条件', summary='', core_opinions=[])
        await generator._generate_ai_podcast_script(report, '', date(2026, 10, 25), ReportType.MORNING, True)
        generator._call_ai_for_podcast.assert_awaited_once()
        system = generator._call_ai_for_podcast.call_args.args[0]
        self.assertIn(SPOKEN_POLICY, system)
        generator._verify_podcast_script.assert_awaited_once()
