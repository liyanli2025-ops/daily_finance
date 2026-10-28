"""Regressions observed during the first production acceptance run."""
import asyncio
from datetime import date
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from app.config import Settings
from app.services import model_gateway as gateway
from app.services.ai_analyzer import AIAnalyzerService
from app.services.scheduler import SchedulerService


class ProductionResponseTests(unittest.IsolatedAsyncioTestCase):
    def test_sonnet_analysis_can_explicitly_keep_adaptive_thinking(self):
        config = Settings(_env_file=None, openai_api_key="test", ai_model="anthropic/claude-sonnet-5.5",
                          openai_base_url="https://api.ofox.io/v1", analysis_reasoning_effort="high")
        route = gateway.resolve_route("analysis", config)
        _, _, body = gateway.request_for(route, [{"role": "user", "content": "facts"}], 16000)
        self.assertEqual(body["thinking"], {"type": "adaptive"})
        self.assertEqual(body["output_config"], {"effort": "high"})

    async def run_review(self, reasons):
        calls = []
        config = Settings(_env_file=None, openai_api_key="test-not-real",
                          openai_base_url="https://api.ofox.io/v1",
                          ai_model="anthropic/claude-sonnet-5.5")
        reasons = iter(reasons)

        def respond(request):
            calls.append(json.loads(request.content))
            reason = next(reasons)
            return httpx.Response(200, json={"stop_reason": reason,
                "content": [{"type": "text", "text": '{"overall_quality":8,"issues":[]}'}],
                "usage": {"output_tokens": 4000}})

        original = httpx.AsyncClient
        with patch.object(gateway, "settings", config), patch.object(
                gateway.httpx, "AsyncClient", side_effect=lambda **kw:
                original(transport=httpx.MockTransport(respond), **kw)):
            try:
                return await gateway.complete("review", [{"role": "user", "content": "full evidence"}], 4000)
            finally:
                self.calls = calls

    async def test_explicit_output_limit_retries_full_evidence_with_bounded_budget(self):
        result = await self.run_review(["max_tokens", "end_turn"])
        self.assertEqual(json.loads(result)["issues"], [])
        self.assertEqual([c["max_tokens"] for c in self.calls], [4000, 8000])
        self.assertEqual(self.calls[0]["messages"], self.calls[1]["messages"])

    async def test_second_truncated_review_still_blocks(self):
        with self.assertRaisesRegex(RuntimeError, "reason=max_tokens"):
            await self.run_review(["max_tokens", "max_tokens"])
        self.assertEqual(len(self.calls), 2)

    async def test_refusal_and_unknown_reason_do_not_retry(self):
        for reason in ["refusal", None, "untrusted text possibly containing credentials"]:
            with self.subTest(reason=reason), self.assertRaises(RuntimeError) as error:
                await self.run_review([reason])
            self.assertEqual(len(self.calls), 1)
            self.assertNotIn("credentials", str(error.exception))

    async def test_generation_error_propagates_instead_of_reporting_completion(self):
        service = SchedulerService.__new__(SchedulerService)
        service._last_morning_date = None
        service._generating_lock = asyncio.Lock()
        service.is_trading_day = lambda _: True
        collector = SimpleNamespace(collect_all=AsyncMock(side_effect=RuntimeError("source failed")))
        with patch("app.services.scheduler.get_news_collector", return_value=collector), \
                patch('app.services.watchlist_repository.read_app_watchlist',AsyncMock(return_value=[])):
            with self.assertRaisesRegex(RuntimeError, "source failed"):
                await service.generate_morning_report()


class MarketMetadataTests(unittest.TestCase):
    def parse(self, sentiment):
        service = AIAnalyzerService.__new__(AIAnalyzerService)
        metadata = {"title": "test", "summary": "test",
                    "market_analysis": {"overall_sentiment": sentiment, "trend": "bearish"}}
        return service._parse_report_response(
            "正文\n```json\n" + json.dumps(metadata) + "\n```", date(2026, 10, 23), [])

    def test_bearish_keeps_negative_direction(self):
        report = self.parse("bearish")
        self.assertEqual(report.analysis.overall_sentiment.value, "negative")
        self.assertEqual(report.analysis.trend.value, "bearish")

    def test_unknown_sentiment_blocks_instead_of_becoming_neutral(self):
        with self.assertRaisesRegex(ValueError, "禁止以中性"):
            self.parse("invalid-direction")
