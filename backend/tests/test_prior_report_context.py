"""Evening comparisons must use the same genuine pre-open report at each stage."""
from datetime import date, datetime, timezone
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.models.database import Base, ReportModel
from app.models.report import Report, ReportType
from app.services.ai_analyzer import AIAnalyzerService
from app.services.prior_report_context import eligibility, comparison_context
from app.services.scheduler import SchedulerService

DAY = date(2026, 10, 29)


def morning(**values):
    fields = dict(id='advance-report', title='早报：反弹的条件', content='若上涨面扩大才考虑反弹延续，未来三个交易日观察。',
                  report_date=DAY, report_type=ReportType.MORNING, created_at=datetime(2026, 10, 29, 6))
    fields.update(values)
    return SimpleNamespace(**fields)


class PriorReportTests(unittest.TestCase):
    def test_requires_same_day_preopen_record_not_just_morning_db_type(self):
        self.assertEqual(eligibility(morning(), DAY), 'eligible')
        for record in [None, morning(report_date=date(2026, 10, 28)), morning(created_at=datetime(2026, 10, 29, 13)),
                       morning(title='即时更新｜反弹'), morning(report_type=ReportType.EVENING),
                       morning(created_at=None), morning(content=''), morning(title='周末回顾')]:
            self.assertNotEqual(eligibility(record, DAY), 'eligible')
            self.assertIn('不编造早报原话', comparison_context(record, DAY))

    def test_aware_time_converted_to_china_before_cutoff(self):
        self.assertEqual(eligibility(morning(created_at=datetime(2026, 10, 28, 22, tzinfo=timezone.utc)), DAY), 'eligible')
        self.assertNotEqual(eligibility(morning(created_at=datetime(2026, 10, 29, 1, tzinfo=timezone.utc)), DAY), 'eligible')

    def test_exact_conditions_preserved_without_terminal_source_catalogue(self):
        record = morning(content='若上涨面扩大才考虑延续，不触发不行动。\n\n## 本期引用来源\n以下为采集来源，来源存在不等于内容已被独立证实。\n- [N:old] 旧来源')
        text = comparison_context(record, DAY)
        self.assertIn('若上涨面扩大才考虑延续，不触发不行动。', text)
        self.assertIn('advance-report', text)
        self.assertNotIn('- [N:old]', text)
        self.assertIn('观察期未结束不能算命中', text)


class SameComparisonPromptTests(unittest.IsolatedAsyncioTestCase):
    def writer(self, service, record, kind=ReportType.EVENING):
        return service._build_editorial_report_prompt(today=DAY, report_type=kind, is_trading_day=True,
            watchlist_text='', market_data_text='当前行情', finance_summary='当前新闻', cross_border_summary='', morning_report=record)

    async def test_writer_reviewer_repair_share_frozen_original(self):
        service = AIAnalyzerService.__new__(AIAnalyzerService)
        original = morning()
        writer = self.writer(service, original)
        frozen = service._prior_report_context
        original.content = '后改成必涨，伪造早报原话'
        reviewer = service._build_review_prompt('晚报正文', '当前行情', '当前新闻', '', ReportType.EVENING)
        service._call_ai = AsyncMock(return_value='修稿正文\n```json\n'+json.dumps(dict(title='晚报', summary='摘要', core_opinions=[], market_analysis=dict(overall_sentiment='neutral', trend='neutral')))+'\n```')
        report = Report(id='evening', title='晚报', summary='摘要', content='晚报正文', report_date=DAY, report_type=ReportType.EVENING)
        with patch('app.services.report_diagnostics.save_generation_stage'):
            await service._ai_fix_report(report, '', [], '当前行情', ReportType.EVENING, finance_summary='当前新闻')
        repair = service._call_ai.call_args.args[0]
        for text in (writer, reviewer, repair):
            self.assertIn(frozen, text)
            self.assertNotIn('后改成必涨', text)
        self.assertEqual(service._call_ai.await_count, 1)

    def test_service_reuse_cannot_leak_previous_context(self):
        service = AIAnalyzerService.__new__(AIAnalyzerService)
        self.writer(service, morning())
        self.assertNotIn('advance-report', self.writer(service, None))
        self.assertNotIn('advance-report', service._build_review_prompt('晚报', '', '', '', ReportType.EVENING))
        self.writer(service, morning())
        self.assertNotIn('advance-report', self.writer(service, None, ReportType.MORNING))
        self.assertEqual(service._prior_report_context, '不适用')


class SchedulerMorningSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_latest_intraday_cannot_hide_real_preopen_report(self):
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            maker = async_sessionmaker(engine, expire_on_commit=False)
            def row(key, title, hour, day=DAY):
                return ReportModel(id=key, title=title, summary='摘要', content='判断与条件', report_date=day,
                    report_type='morning', created_at=datetime.combine(day, datetime.min.time()).replace(hour=hour))
            async with maker() as session:
                session.add_all([row('old', '早报旧版', 5), row('correct', '早报已更新', 7), row('intraday', '盘中观察', 13),
                                 row('mislabel', '即时更新｜市场变化', 8), row('yesterday', '早报', 6, date(2026, 10, 28))])
                await session.commit()
            service = SchedulerService.__new__(SchedulerService)
            service._session_maker = maker
            with patch('app.services.scheduler.china_today', return_value=DAY):
                self.assertEqual((await service._get_today_morning_report()).id, 'correct')
            async with maker() as session:
                from sqlalchemy import delete
                await session.execute(delete(ReportModel).where(ReportModel.id.in_(['old', 'correct'])))
                await session.commit()
            with patch('app.services.scheduler.china_today', return_value=DAY):
                self.assertIsNone(await service._get_today_morning_report())
        finally:
            await engine.dispose()
