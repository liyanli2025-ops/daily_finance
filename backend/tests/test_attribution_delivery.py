"""Prompt routing and cache boundaries, not a semantic accuracy score."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from app.models.report import ReportType
from app.services.ai_analyzer import AIAnalyzerService
from app.services.editorial_policy import ATTRIBUTION_AND_HORIZON_POLICY, spoken_prompts
from app.services import podcast_script_cache as cache

class AttributionDeliveryTests(unittest.TestCase):
    def test_shared_boundary_reaches_real_analysis_review_and_speech_prompts(self):
        analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
        analyzer._get_writing_philosophy=lambda: ''
        report=SimpleNamespace(content='历史样稿：未来数日反弹候选；均线改善只作趋势确认。')
        analysis=analyzer._build_editorial_report_prompt(today=date(2026,10,29),
            report_type=ReportType.MORNING,is_trading_day=True,watchlist_text='',
            market_data_text='',finance_summary='',cross_border_summary='')
        review=analyzer._build_review_prompt(report.content,'','','',ReportType.MORNING)
        speech,_=spoken_prompts(report,date(2026,10,29),'早报')
        for prompt in (analysis,review,speech):
            self.assertEqual(prompt.count(ATTRIBUTION_AND_HORIZON_POLICY),1)

    def test_changed_delivery_rules_do_not_reuse_old_verified_script_key(self):
        report=SimpleNamespace(content='历史相对弱势，未来仍可能反弹。')
        current=cache.signature(report,'')
        with patch.object(cache,'SPOKEN_POLICY',cache.SPOKEN_POLICY.replace(ATTRIBUTION_AND_HORIZON_POLICY,'')):
            self.assertNotEqual(cache.signature(report,''),current)
        with patch.object(cache,'REVIEW_CONTRACT', 'older review contract'):
            self.assertNotEqual(cache.signature(report,''),current)
