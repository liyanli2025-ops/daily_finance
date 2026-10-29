from spoken_fixtures import reply
"""Actual speech requests share the delivery contract and invalidate old caches."""
from datetime import date
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app.models.report import ReportType
from app.services.editorial_policy import spoken_prompts, SPOKEN_EDITION_BRIEFS
from app.services.podcast_generator import PodcastGeneratorService
from app.services import podcast_script_cache as cache


class ProgrammeDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_production_request_is_identical_to_shared_prompt_builder(self):
        report = SimpleNamespace(title='2026-10-29早报', content='关键新增事实。'+('传导、比较和有条件应对。'*400)+'最后一段反证不可遗漏。')
        generator = PodcastGeneratorService.__new__(PodcastGeneratorService)
        generator.ai_client = True
        generator._call_ai_for_podcast = AsyncMock(return_value=reply('这次变化影响短线选择，依据和条件来自原报告。',report.content))
        generator._verify_podcast_script = AsyncMock()
        expected = spoken_prompts(report, date(2026, 10, 29), '早报')
        with patch('app.services.podcast_generator.spoken_prompts', wraps=spoken_prompts) as builder, \
             patch('app.services.report_diagnostics.save_spoken_case', return_value=Path('fixture.json')), \
             patch('app.services.report_diagnostics.mark_spoken_case'):
            script = await generator._generate_ai_podcast_script(report, '', date(2026, 10, 29), ReportType.MORNING, False)
        builder.assert_called_once_with(report, date(2026, 10, 29), '早报')
        generator._call_ai_for_podcast.assert_awaited_once_with(*expected, max_tokens=8000)
        generator._verify_podcast_script.assert_awaited_once_with(script, report)
        self.assertIn(report.content, expected[1])
        self.assertIn('2500—3000字', expected[1])
        self.assertIn('不是最低字数', expected[1])

    def test_edition_briefs_cannot_apply_morning_length_to_intraday_update(self):
        report = SimpleNamespace(content='本期完整正文')
        _, evening = spoken_prompts(report, date(2026, 10, 29), '晚报')
        _, intraday = spoken_prompts(report, date(2026, 10, 29), '即时更新')
        self.assertIn('3000—4000字', evening)
        self.assertNotIn('2500—3000字', intraday)
        self.assertIn('不套早晚报时长', intraday)

    def test_edition_delivery_change_invalidates_verified_script_cache(self):
        report = SimpleNamespace(title='早报', content='有效事实与条件')
        with tempfile.TemporaryDirectory() as folder:
            cache.save(report, '用户', '原事实和条件，保持原含义。', folder)
            self.assertIsNotNone(cache.load(report, '用户', folder))
            with patch.dict(SPOKEN_EDITION_BRIEFS, {'早报': '调整后的早报交付要求'}):
                self.assertIsNone(cache.load(report, '用户', folder))
            self.assertIsNotNone(cache.load(report, '用户', folder))

    def test_content_selection_does_not_repeat_summary_or_force_unsupported_actions(self):
        report = SimpleNamespace(content='报告只支持需求改善，但尚无股价方向依据。', summary='不要重复摘要', core_opinions=['不要重复核心观点'])
        system, user = spoken_prompts(report, date(2026, 10, 29), '早报')
        self.assertIn(report.content, user)
        self.assertNotIn(report.summary, user)
        self.assertNotIn(report.core_opinions[0], user)
        self.assertIn('不添加报告外的新闻', system)
        self.assertIn('不把有据的主观判断一律削弱为观望', system)
        self.assertIn('不把“我的判断—理由—最强反方—失效条件”当每段固定顺序', system)
