"""Check active report-to-speech wiring, not subjective listening quality."""
from datetime import date
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock,patch

from app.models.report import ReportType
from app.services.ai_analyzer import AIAnalyzerService
from app.services.podcast_generator import PodcastGeneratorService
from app.services.editorial_policy import EDITION_BRIEFS,REPORT_POLICY,SPOKEN_POLICY
from app.services import podcast_script_cache as cache


class OriginalProgrammeIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def test_active_report_prompts_receive_the_matching_edition_purpose(self):
        analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
        for period,day,kind in [('早报',date(2026,10,29),ReportType.MORNING),
                                ('晚报',date(2026,10,29),ReportType.EVENING),
                                ('即时更新',date(2026,10,29),ReportType.MORNING),
                                ('周末回顾',date(2026,11,1),ReportType.MORNING)]:
            analyzer._edition_label=period
            prompt=analyzer._build_editorial_report_prompt(today=day,report_type=kind,is_trading_day=True,
                watchlist_text='本期名单',market_data_text='行情截止边界',finance_summary='完整证据',cross_border_summary='海外证据')
            self.assertIn(EDITION_BRIEFS[period],prompt)
            self.assertIn(REPORT_POLICY,prompt)
            for value in ('本期名单','行情截止边界','完整证据','海外证据'):
                self.assertIn(value,prompt)

    async def test_real_speech_path_uses_edition_and_full_report_without_extra_calls(self):
        cases=[('早报',False,'报告',ReportType.MORNING),
               ('晚报',False,'报告',ReportType.EVENING),
               ('周末回顾',True,'报告',ReportType.MORNING),
               ('即时更新',True,'即时更新｜报告',ReportType.MORNING)]
        for period,weekend,title,kind in cases:
            generator=PodcastGeneratorService.__new__(PodcastGeneratorService);generator.ai_client=True
            generator._call_ai_for_podcast=AsyncMock(return_value='已有事实、条件和反证。')
            generator._verify_podcast_script=AsyncMock()
            content='完整正文开始。'+('重要分析及限定。'*400)+'原文结尾反证不能截断。'
            report=SimpleNamespace(title=title,content=content,summary='',core_opinions=[])
            with (patch('app.services.report_diagnostics.save_spoken_case',return_value=Path('fixture.json')),
                  patch('app.services.report_diagnostics.mark_spoken_case')):
                await generator._generate_ai_podcast_script(report,'',date(2026,10,29),kind,weekend)
            generator._call_ai_for_podcast.assert_awaited_once()
            system,user=generator._call_ai_for_podcast.call_args.args
            self.assertIn(SPOKEN_POLICY,system)
            self.assertIn(EDITION_BRIEFS[period],user)
            self.assertIn(content,user)
            generator._verify_podcast_script.assert_awaited_once()

    def test_changing_edition_rules_or_title_invalidates_verified_speech_cache(self):
        report=SimpleNamespace(title='早报',content='原报告事实和条件')
        with tempfile.TemporaryDirectory() as folder:
            cache.save(report,'用户','已有事实和条件。',folder)
            self.assertIsNotNone(cache.load(report,'用户',folder))
            report.title='即时更新｜早报'
            self.assertIsNone(cache.load(report,'用户',folder))
            report.title='早报'
            with patch.dict(cache.EDITION_BRIEFS,{'早报':'新的节目定位'}):
                self.assertIsNone(cache.load(report,'用户',folder))
            self.assertIsNotNone(cache.load(report,'用户',folder))
