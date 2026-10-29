from spoken_fixtures import reply,review_reply
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace

import httpx
from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings
from app.models.database import Base, StockModel
from app.services import model_gateway as gateway
from app.services.watchlist_repository import read_app_watchlist


class RoutingTests(unittest.TestCase):
    def config(self, **kwargs):
        return Settings(_env_file=None, openai_api_key="test-not-a-real-key",
                        openai_base_url="https://api.deepseek.com",
                        analysis_model="deepseek-v4-pro", review_model="deepseek-v4-pro",
                        extraction_model="deepseek-flash", podcast_model="deepseek-flash",
                        analysis_reasoning_effort="high", **kwargs)

    def test_each_task_uses_its_configured_model(self):
        config = self.config()
        for task, model in [("analysis", "deepseek-v4-pro"), ("review", "deepseek-v4-pro"),
                            ("extraction", "deepseek-flash"), ("podcast", "deepseek-flash")]:
            self.assertEqual(gateway.resolve_route(task, config).model, model)

    def test_review_can_use_explicit_separate_provider(self):
        config = self.config(review_provider="backup", backup_ai_api_key="test-backup",
                             backup_ai_base_url="https://review.example/v1")
        route = gateway.resolve_route("review", config)
        self.assertEqual(route.api_key, "test-backup")
        self.assertEqual(route.base_url, "https://review.example/v1")

    def test_no_credentials_does_not_select_anonymous_provider(self):
        with self.assertRaisesRegex(RuntimeError, "未配置模型凭据"):
            gateway.resolve_route("analysis", Settings(_env_file=None))

    def test_legacy_explicit_model_is_preserved(self):
        config = Settings(_env_file=None, openai_api_key="test", ai_model="my-existing-model")
        self.assertEqual(gateway.resolve_route("analysis", config).model, "my-existing-model")

    def test_ofox_claude_uses_messages_and_existing_ofox_credential(self):
        config = Settings(_env_file=None, openai_api_key="test",
                          openai_base_url="https://api.ofox.io/v1",
                          ai_model="anthropic/claude-sonnet-5.5")
        route = gateway.resolve_route("analysis", config)
        url, headers, body = gateway.request_for(route, [{"role": "user", "content": "test"}], 64)
        self.assertEqual(url, "https://api.ofox.io/anthropic/v1/messages")
        self.assertEqual(body["model"], "anthropic/claude-sonnet-5.5")
        self.assertEqual(headers["x-api-key"], "test")
        self.assertEqual(body["thinking"], {"type": "between_tools"})
        self.assertEqual(body["output_config"], {"effort": "low"})
        self.assertNotIn("reasoning_effort", body)

    def test_ofox_deepseek_keeps_chat_protocol(self):
        config = Settings(_env_file=None, openai_api_key="test",
                          openai_base_url="https://api.ofox.io/v1",
                          ai_model="deepseek/deepseek-v4.1-flash")
        route = gateway.resolve_route("podcast", config)
        url, headers, body = gateway.request_for(route, [{"role": "user", "content": "test"}], 64)
        self.assertEqual(url, "https://api.ofox.io/v1/chat/completions")
        self.assertIn("Authorization", headers)

    def test_deepseek_thinking_has_budget_and_no_temperature(self):
        route = gateway.resolve_route("analysis", self.config())
        _, _, body = gateway.request_for(route, [{"role": "user", "content": "test"}], 16000)
        self.assertEqual(body["max_tokens"], 16000)
        self.assertEqual(body["thinking"], {"type": "enabled"})
        self.assertEqual(body["reasoning_effort"], "high")
        self.assertNotIn("temperature", body)

    def test_truncated_refused_empty_responses_cannot_pass(self):
        route = gateway.resolve_route("analysis", self.config())
        for data in [
            {"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]},
            {"choices": [{"finish_reason": "stop", "message": {"content": ""}}]},
            {"choices": [{"finish_reason": "stop", "message": {"content": "x", "refusal": "no"}}]},
            {"choices": []},
        ]:
            with self.subTest(data=data), self.assertRaises(RuntimeError):
                gateway.completed_text(route, data)


class GatewayIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_and_podcast_call_same_gateway_with_distinct_routes(self):
        from app.services.ai_analyzer import AIAnalyzerService
        from app.services.podcast_generator import PodcastGeneratorService
        config = Settings(_env_file=None, openai_api_key="test",
                          openai_base_url="https://api.deepseek.com",
                          analysis_model="deepseek-v4-pro", review_model="deepseek-v4-pro",
                          podcast_model="deepseek-flash")
        requests = []

        def handler(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200, json={"choices": [
                {"finish_reason": "stop", "message": {"content": "verified response"}}]})

        original_client = httpx.AsyncClient
        with patch.object(gateway, "settings", config), patch.object(
                gateway.httpx, "AsyncClient",
                side_effect=lambda **kw: original_client(transport=httpx.MockTransport(handler), **kw)):
            analyzer = AIAnalyzerService.__new__(AIAnalyzerService)
            podcast = PodcastGeneratorService.__new__(PodcastGeneratorService)
            await analyzer._call_ai("facts", task="analysis")
            await analyzer._call_ai("check facts", task="review")
            await podcast._call_ai_for_podcast("edit", "report")
            await podcast._call_ai_for_podcast("check", "script", task="review")
        self.assertEqual([r["model"] for r in requests], [
            "deepseek-v4-pro", "deepseek-v4-pro", "deepseek-flash", "deepseek-v4-pro"])

    async def test_auth_failure_is_explicit_and_does_not_call_other_provider(self):
        count = 0

        def handler(request):
            nonlocal count
            count += 1
            return httpx.Response(401, json={"error": "do not expose raw provider error"})

        config = Settings(_env_file=None, openai_api_key="test", ai_model="explicit")
        original_client = httpx.AsyncClient
        with patch.object(gateway, "settings", config), patch.object(
                gateway.httpx, "AsyncClient",
                side_effect=lambda **kw: original_client(transport=httpx.MockTransport(handler), **kw)):
            with self.assertRaisesRegex(RuntimeError, "HTTP 401"):
                await gateway.complete("analysis", [{"role": "user", "content": "facts"}])
        self.assertEqual(count, 1)


class AppDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_app_watchlist_flows_into_report_then_podcast_and_review(self):
        from datetime import datetime
        from app.config import settings
        from app.models.news import News
        from app.models.report import ReportType
        from app.services.ai_analyzer import AIAnalyzerService
        from app.services.podcast_generator import PodcastGeneratorService
        from app.services.market_data_service import MarketOverview
        from app.services.time_context import china_today
        from app.services.research_hub import Material

        with tempfile.TemporaryDirectory() as tmp:
            url = "sqlite+aiosqlite:///" + (Path(tmp) / "app.db").as_posix()
            engine = create_async_engine(url)
            try:
                async with engine.begin() as connection:
                    await connection.run_sync(Base.metadata.create_all)
                    await connection.execute(insert(StockModel), {
                        "id": "1", "code": "00700", "name": "腾讯控股", "market": "HK"})
                news = News(id="fixture-news", title="集成测试公告", content="仅为离线测试的证据，不是真实新闻。",
                            source="测试夹具", source_url="https://example.com/announcement/1",
                            published_at=datetime(2026, 10, 23, 5))
                background = Material('fixture-financial','历史财务资料','测试夹具','https://example.com/filing/1',
                                      'financial_baseline','HK:00700','带日期的历史财务证据',None,'2026-10-23T12:00:00')
                body = "## 测试事实\n仅验证数据流[N:fixture-news]，历史资料[N:fixture-financial]。\n## 自选股\n腾讯控股00700，信息不足不新增判断。"
                metadata = {"title": "集成测试报告", "summary": "仅验证数据流", "core_opinions": [],
                            "highlights": [], "cross_border_events": [], "market_analysis": {}}
                responses = iter([
                    body + "\n```json\n" + json.dumps(metadata, ensure_ascii=False) + "\n```",
                    '{"overall_quality":8,"issues":[]}',
                    reply("本段只验证既有报告到口播的代码流程，保留事实边界与限制条件，不是真实财经内容。" * 7, body),
                    review_reply(body, '本段只验证既有报告到口播的代码流程，保留事实边界与限制条件，不是真实财经内容。' * 7),
                ])
                requests = []

                def handler(request):
                    requests.append(json.loads(request.content))
                    return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
                                          "message": {"content": next(responses)}}]})

                config = Settings(_env_file=None, openai_api_key="test",
                                  openai_base_url="https://api.deepseek.com",
                                  analysis_model="deepseek-v4-pro", review_model="deepseek-v4-pro",
                                  podcast_model="deepseek-flash")
                market = SimpleNamespace(get_market_overview=AsyncMock(
                    return_value=MarketOverview(date=china_today().isoformat())))
                original_client = httpx.AsyncClient
                with patch.object(settings, "database_url", url), \
                        patch("app.services.ai_analyzer.china_now", return_value=datetime(2026, 10, 23, 13)), \
                        patch.object(gateway, "settings", config), \
                        patch.object(gateway.httpx, "AsyncClient", side_effect=lambda **kw:
                                     original_client(transport=httpx.MockTransport(handler), **kw)), \
                        patch("app.services.ai_analyzer.get_market_data_service", return_value=market), \
                        patch("app.services.research_hub.ResearchHub.prompt", return_value=(background.prompt(),[background])), \
                        patch("app.services.ai_analyzer.AIAnalyzerService._fetch_watchlist_quotes", return_value={}), \
                        patch("app.services.signal_tracker.get_signal_tracker", return_value=SimpleNamespace(
                            get_signal_summary_text=AsyncMock(return_value=""))), \
                        patch("app.services.backtest_service.get_backtest_service", return_value=SimpleNamespace(
                            get_backtest_summary_text=AsyncMock(return_value=""))):
                    analyzer = AIAnalyzerService()
                    report = await analyzer.generate_daily_report([news])
                    podcast = PodcastGeneratorService.__new__(PodcastGeneratorService)
                    podcast.ai_client = "task_gateway"
                    script = await podcast._generate_ai_podcast_script(
                        report, "", report.report_date, ReportType.MORNING, False)
                self.assertIn("00700", requests[0]["messages"][0]["content"])
                self.assertIn('带日期的历史财务证据', requests[0]['messages'][0]['content'])
                self.assertIn('带日期的历史财务证据', requests[1]['messages'][0]['content'])
                self.assertIn('fixture-financial', report.content)
                self.assertIn('实际生成时点：2026-10-23T13:00:00', requests[0]['messages'][0]['content'])
                self.assertIn('即时更新', report.title)
                self.assertIn("本期引用来源", report.content)
                from app.services.spoken_editing import report_body
                self.assertIn(report_body(report.content), requests[2]["messages"][1]["content"])
                self.assertNotIn('## 本期引用来源',requests[2]["messages"][1]["content"])
                self.assertIn('节目：即时更新', requests[2]['messages'][1]['content'])
                self.assertTrue(script)
                self.assertEqual([r["model"] for r in requests], [
                    "deepseek-v4-pro", "deepseek-v4-pro", "deepseek-flash", "deepseek-v4-pro"])
            finally:
                await engine.dispose()

    async def test_reads_actual_app_schema_and_reflects_user_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "app.db"
            url = "sqlite+aiosqlite:///" + path.as_posix()
            engine = create_async_engine(url)
            try:
                async with engine.begin() as connection:
                    await connection.run_sync(Base.metadata.create_all)
                    await connection.execute(insert(StockModel), [
                        {"id": "1", "code": "00700", "name": "腾讯控股", "market": "HK"},
                        {"id": "2", "code": "300750", "name": "宁德时代", "market": "A"}])
                rows = await read_app_watchlist(url)
                self.assertEqual({r["code"] for r in rows}, {"00700", "300750"})
                async with engine.begin() as connection:
                    await connection.execute(delete(StockModel))
                self.assertEqual(await read_app_watchlist(url), [])
            finally:
                await engine.dispose()

    async def test_missing_database_is_not_created_or_silently_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.db"
            with self.assertRaises(RuntimeError):
                await read_app_watchlist("sqlite:///" + path.as_posix())
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
