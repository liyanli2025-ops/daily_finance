from datetime import date
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app.models.report import ReportType
from app.services.podcast_generator import PodcastGeneratorService
from app.services.report_diagnostics import save_spoken_case
from app.services.spoken_programme import parse_response, delivery_leaks
from app.services import podcast_script_cache as cache
from spoken_fixtures import reply


class ProgrammeParserTests(unittest.TestCase):
    def test_plan_and_script_are_separate_and_quotes_grounded(self):
        raw = reply('反弹仍受原结构约束，条件出现再调整。', '昨日上涨2%，中期结构尚未改善。')
        plan, script = parse_response(raw, '昨日上涨2%，中期结构尚未改善。')
        self.assertEqual(plan['choices'][0]['report_quotes'], ['昨日上涨2%，中期结构尚未改善。'])
        self.assertNotIn('editorial_reason', script)

    def test_plain_report_readout_or_malformed_envelope_cannot_silently_pass(self):
        for raw in ('照着报告逐股朗读。', '{"programme":', '{"script":"正文"}'):
            with self.assertRaises(RuntimeError):
                parse_response(raw, '原报告事实')

    def test_invented_report_quote_rejected(self):
        with self.assertRaisesRegex(RuntimeError, '引用不在报告正文'):
            parse_response(reply('正文', '新订单增长80%'), '报告没有订单数据')

    def test_bounds_reject_unbounded_topic_inventory(self):
        value = json.loads(reply('正文', '原报告事实'))
        value['programme']['choices'] *= 4
        with self.assertRaisesRegex(RuntimeError, '1至3项'):
            parse_response(json.dumps(value), '原报告事实')

    def test_actual_editor_notes_leak_but_valid_limits_remain_valid(self):
        self.assertTrue(delivery_leaks('其他几只自选，只讲结构，不编消息。'))
        self.assertTrue(delivery_leaks('下面是本期口播稿：'))
        self.assertFalse(delivery_leaks('没有公司订单证据，不能把行业增长直接当成该公司受益。'))
        self.assertFalse(delivery_leaks('若反弹回吐，则当前判断的依据减弱。'))

    def test_programme_contract_change_invalidates_cached_script(self):
        report = SimpleNamespace(content='有效事实', title='早报')
        with tempfile.TemporaryDirectory() as folder:
            cache.save(report, '用户', '既有事实和有效限制。', folder)
            self.assertIsNotNone(cache.load(report, '用户', folder))
            with patch.object(cache, 'FORMAT_VERSION', 'different-contract'):
                self.assertIsNone(cache.load(report, '用户', folder))


class ProgrammeFlowTests(unittest.IsolatedAsyncioTestCase):
    def service(self, response):
        service = PodcastGeneratorService.__new__(PodcastGeneratorService)
        service.ai_client = True
        service._call_ai_for_podcast = AsyncMock(return_value=response)
        service._verify_podcast_script = AsyncMock()
        return service

    async def test_paid_malformed_reply_saved_without_second_call(self):
        service = self.service('完整但不符合新交付格式的旧式口播')
        report = SimpleNamespace(title='早报', content='原报告事实')
        with patch('app.services.report_diagnostics.save_generation_stage') as checkpoint:
            with self.assertRaisesRegex(RuntimeError, '保留回复'):
                await service._generate_ai_podcast_script(report, '', date(2026, 10, 29), ReportType.MORNING, False)
        checkpoint.assert_called_once_with('spoken_response', '完整但不符合新交付格式的旧式口播')
        service._call_ai_for_podcast.assert_awaited_once()
        service._verify_podcast_script.assert_not_awaited()

    async def test_real_returned_editor_note_stops_before_paid_review(self):
        report = SimpleNamespace(title='早报', content='原报告事实')
        service = self.service(reply('其他几只自选，只讲结构，不编消息。', report.content))
        with patch('app.services.report_diagnostics.save_generation_stage'), patch('app.services.report_diagnostics.save_spoken_case', return_value=Path('fixture.json')), patch('app.services.report_diagnostics.mark_spoken_case') as mark:
            with self.assertRaisesRegex(RuntimeError, '编辑说明'):
                await service._generate_ai_podcast_script(report, '', date(2026, 10, 29), ReportType.MORNING, False)
        service._call_ai_for_podcast.assert_awaited_once()
        service._verify_podcast_script.assert_not_awaited()
        mark.assert_called_once_with(Path('fixture.json'), 'format_rejected', 'editorial_notes_in_script')

    async def test_plan_saved_for_human_but_only_script_sent_to_review(self):
        report = SimpleNamespace(title='早报', id='fixture', content='原报告事实与条件')
        raw = reply('市场已有修复，仍需保留原反证。', report.content)
        service = self.service(raw)
        with tempfile.TemporaryDirectory() as folder:
            def save(*args, **kwargs):
                return save_spoken_case(*args, directory=folder, **kwargs)
            with patch('app.services.report_diagnostics.save_generation_stage'), patch('app.services.report_diagnostics.save_spoken_case', side_effect=save):
                script = await service._generate_ai_podcast_script(report, '', date(2026, 10, 29), ReportType.MORNING, False)
            data = json.loads(next(Path(folder).glob('spoken-*.json')).read_text(encoding='utf-8'))
        self.assertEqual(data['raw_script'], raw)
        self.assertTrue(data['editorial_plan']['choices'])
        self.assertNotIn('editorial_reason', script)
        service._verify_podcast_script.assert_awaited_once_with(script, report)
        service._call_ai_for_podcast.assert_awaited_once()
