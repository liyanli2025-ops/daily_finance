"""Offline regression tests: no API keys, network, or production database."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.models.report import ReportType
from app.services.ai_analyzer import AIAnalyzerService
from app.services.podcast_generator import PodcastGeneratorService
from app.services.news_collector import NewsCollectorService
from app.services.watchlist_service import WatchlistService
from app.services.evidence import article_url, validate_citations
import feedparser


class ReviewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = AIAnalyzerService.__new__(AIAnalyzerService)
        self.report = SimpleNamespace(content="完整事实及限制条件")

    async def review(self, responses):
        self.service._call_ai = AsyncMock(side_effect=responses)
        return await self.service._review_and_fix_report(
            self.report, "raw", "market", "news", "cross", ReportType.MORNING
        )

    async def test_empty_malformed_or_incomplete_review_blocks(self):
        for value in ["", "{}", "[]", '{"issues":[]',
                      '{"issues":[],"overall_quality":true}',
                      '{"issues":[{}],"overall_quality":8}']:
            with self.subTest(value=value):
                with self.assertRaises((RuntimeError, ValueError)):
                    await self.review([value])

    async def test_valid_review_passes(self):
        result = await self.review(['{"issues":[],"overall_quality":8}'])
        self.assertIs(result, self.report)

    async def test_repaired_report_must_be_reviewed_again(self):
        issue = json.dumps({"issues": [{"severity": "high", "type": "数据编造",
                                        "detail": "数字无依据", "check_kind":"unsupported_fact",
                                        "report_quote":"完整事实", "source_quote":"market"}], "overall_quality": 5})
        self.service._ai_fix_report = AsyncMock(return_value=self.report)
        with self.assertRaisesRegex(RuntimeError, "复核"):
            await self.review([issue, issue])
        self.assertEqual(self.service._call_ai.await_count, 2)
        self.service._ai_fix_report.assert_awaited_once()

    async def test_repair_then_clean_review_passes(self):
        self.service._ai_fix_report = AsyncMock(return_value=self.report)
        await self.review([json.dumps(dict(issues=[dict(severity='high',type='逻辑矛盾',detail='事实解释矛盾',
            check_kind='reasoning',report_quote='完整事实')],overall_quality=5)),
                           '{"issues":[],"overall_quality":8}'])
        self.assertEqual(self.service._call_ai.await_count, 2)

    async def test_real_repair_path_uses_its_own_prompt(self):
        self.report.title = "test"
        self.report.summary = "summary"
        self.report.core_opinions = []
        self.service._decision_notes=[dict(claim='已删除的旧判断')]
        metadata = {"title":"修复标题", "summary":"修复摘要", "core_opinions":[],
                    "market_analysis":{"overall_sentiment":"neutral", "trend":"neutral"}}
        self.service._call_ai = AsyncMock(return_value="修复后的完整内容及证据，保留限制条件。\n```json\n" +
                                         json.dumps(metadata, ensure_ascii=False) + "\n```")
        result = await self.service._ai_fix_report(
            self.report, "raw", [{"detail": "待修复"}], "market", ReportType.MORNING,
            finance_summary="完整财经证据末尾", cross_border_summary="完整海外证据末尾")
        self.assertIn("修复后", result.content)
        self.assertIn("用户目标与证据要求", self.service._call_ai.call_args.args[0])
        self.assertIn("完整财经证据末尾", self.service._call_ai.call_args.args[0])
        self.assertIn("完整海外证据末尾", self.service._call_ai.call_args.args[0])
        self.assertEqual(result.summary, "修复摘要")
        self.assertEqual(result.core_opinions, [])
        self.assertEqual(self.service._decision_notes, [])

    async def test_repair_without_metadata_cannot_leave_old_summary(self):
        self.service._call_ai = AsyncMock(return_value='修复正文但缺少完整元数据')
        with self.assertRaisesRegex(RuntimeError, '不能沿用旧摘要'):
            await self.service._ai_fix_report(self.report, 'raw', [], 'market', ReportType.MORNING)

    async def test_review_checks_summary_and_core_opinions_too(self):
        self.report.summary = '摘要中的待核实判断'
        self.report.core_opinions = ['核心观点中的待核实判断']
        await self.review(['{"issues":[],"overall_quality":8}'])
        prompt = self.service._call_ai.call_args.args[0]
        self.assertIn(self.report.summary, prompt)
        self.assertIn(self.report.core_opinions[0], prompt)

    async def test_fake_citation_is_checked_before_paid_review(self):
        self.report.content = '占位错误[N:fake-placeholder]'
        evidence = [SimpleNamespace(id='real', source_url='https://example.com/article/1')]
        fixed = SimpleNamespace(content='修复后的事实[N:real]')
        self.service._ai_fix_report = AsyncMock(return_value=fixed)
        self.service._call_ai = AsyncMock(return_value='{"issues":[],"overall_quality":8}')
        result = await self.service._review_and_fix_report(
            self.report, 'raw', 'market', '完整财经证据', '完整海外证据',
            ReportType.MORNING, evidence_news=evidence)
        self.assertIs(result, fixed)
        self.assertEqual(self.service._call_ai.await_count, 1)
        self.assertEqual(self.service._ai_fix_report.call_args.kwargs['finance_summary'], '完整财经证据')

    async def test_repair_that_keeps_fake_citation_is_not_sent_for_review(self):
        self.report.content = '占位错误[N:fake-placeholder]'
        evidence = [SimpleNamespace(id='real', source_url='https://example.com/article/1')]
        self.service._ai_fix_report = AsyncMock(return_value=self.report)
        self.service._call_ai = AsyncMock()
        with self.assertRaisesRegex(RuntimeError, '复核仍未通过'):
            await self.service._review_and_fix_report(
                self.report, 'raw', 'market', 'news', '', ReportType.MORNING, evidence_news=evidence)
        self.service._call_ai.assert_not_awaited()

    async def test_no_news_blocks_before_data_or_ai_calls(self):
        self.service._call_ai = AsyncMock()
        with self.assertRaisesRegex(RuntimeError, "缺少财经新闻"):
            await self.service.generate_daily_report([])
        self.service._call_ai.assert_not_awaited()

    def test_review_contains_tail_of_all_evidence(self):
        prompt = self.service._build_review_prompt(
            "a" * 13000 + "REPORT_TAIL", "b" * 5000 + "MARKET_TAIL",
            "c" * 5000 + "NEWS_TAIL", "d" * 3000 + "CROSS_TAIL", ReportType.MORNING)
        for marker in ["REPORT_TAIL", "MARKET_TAIL", "NEWS_TAIL", "CROSS_TAIL"]:
            self.assertIn(marker, prompt)


class PodcastTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = PodcastGeneratorService.__new__(PodcastGeneratorService)
        self.service.voice = "test"
        self.service.rate = "+0%"
        self.service.volume = "+0%"

    async def test_script_review_fails_closed(self):
        report = SimpleNamespace(content="report", summary="summary", core_opinions=[])
        for response in [None, "{}", "[]", '{"passed":true}',
                         '{"passed":true,"issues":["新增数字"]}',
                         '{"passed":false,"issues":[]}']:
            self.service._call_ai_for_podcast = AsyncMock(return_value=response)
            with self.subTest(response=response):
                with self.assertRaises((RuntimeError, ValueError)):
                    await self.service._verify_podcast_script("script", report)
        self.service._call_ai_for_podcast = AsyncMock(
            return_value='{"passed":true,"issues":[]}')
        await self.service._verify_podcast_script("script", report)

    async def test_failed_script_does_not_use_unreviewed_template(self):
        self.service._generate_ai_podcast_script = AsyncMock(return_value=None)
        self.service._is_weekend = lambda day: False
        report = SimpleNamespace(report_date=date(2026, 10, 23), report_type=ReportType.MORNING)
        with self.assertRaisesRegex(RuntimeError, "未经核验"):
            await self.service._prepare_podcast_text(report)

    async def test_partial_sentence_recovery_is_not_complete_audio(self):
        class Speech:
            def __init__(self, text, **kwargs):
                self.text = text

            async def save(self, path):
                if "失败" in self.text:
                    raise RuntimeError("simulated synthesis failure")
                Path(path).write_bytes(b"a" * 2048)

        with tempfile.TemporaryDirectory() as tmp, \
                patch("app.services.podcast_generator.edge_tts.Communicate", Speech), \
                patch("app.services.podcast_generator.asyncio.sleep", new=AsyncMock()):
            output = Path(tmp) / "output.mp3"
            ok = await self.service._generate_tts_edge_with_fallback(
                ["成功。", "正常。失败。", "成功。"], str(output))
            self.assertFalse(ok)
            self.assertFalse(output.exists())


class WatchlistTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_app_watchlist_clears_previous_database_snapshot(self):
        watchlist = WatchlistService()
        watchlist.load_from_database([{"code": "00700", "name": "旧股票", "market": "HK"}])
        collector = NewsCollectorService.__new__(NewsCollectorService)
        collector.akshare_available = False
        collector._load_db_watchlist = AsyncMock(return_value=[])
        collector._collect_xueqiu_stock_discussion = AsyncMock(return_value=[])
        with patch("app.services.news_collector.get_watchlist_service", return_value=watchlist), \
                patch("app.services.news_collector.settings", SimpleNamespace(watchlist_stocks="")):
            self.assertEqual(await collector._collect_watchlist_news(), [])
        self.assertEqual(watchlist.get_all_stocks(), [])


class EvidenceTests(unittest.TestCase):
    def test_homepages_and_unsafe_urls_are_not_article_evidence(self):
        for url in [None, "", "https://example.com/", "file:///a", "https://u:p@example.com/a"]:
            self.assertFalse(article_url(url))
        self.assertTrue(article_url("https://example.com/news/123"))

    def test_unknown_missing_or_untraceable_citations_block(self):
        item = SimpleNamespace(id="known", source_url="https://example.com/")
        for content in ["no evidence", "[N:unknown]", "[N:known]"]:
            with self.assertRaises(RuntimeError):
                validate_citations(content, [item])
        item.source_url = "https://example.com/article/1"
        self.assertEqual(validate_citations("事实[N:known]", [item]), [item])

    def test_rss_time_is_converted_from_utc_and_missing_time_is_skipped(self):
        collector = NewsCollectorService.__new__(NewsCollectorService)
        collector._clean_html = lambda text: text
        collector._calculate_importance = lambda *args: 0.5
        collector._extract_keywords = lambda *args: []
        collector._extract_stock_codes = lambda *args: []
        entry = feedparser.FeedParserDict(title="headline", summary="body", link="https://example.com/a")
        self.assertIsNone(collector._parse_rss_entry(entry, {"name": "test"}))
        entry["published_parsed"] = (2026, 10, 22, 22, 0, 0, 3, 295, 0)
        item = collector._parse_rss_entry(entry, {"name": "test"})
        self.assertEqual(item.published_at.isoformat(), "2026-10-23T06:00:00")


if __name__ == "__main__":
    unittest.main()
