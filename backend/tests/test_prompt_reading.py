import json
import re
import unittest
from unittest.mock import patch

from app.services.prompt_reading import excerpt,input_characters,validate_input


class ReadingWindowTests(unittest.TestCase):
    def test_short_body_is_unchanged_and_long_body_spans_are_verbatim(self):
        self.assertEqual(excerpt('短正文'), '短正文')
        body='开头披露。'*300+'订单增长20%。'*100+'然而需求风险尚未解除。'*200
        rendered=excerpt(body,'订单增长',900)
        self.assertIn('未提供全文',rendered)
        self.assertIn('read_material',rendered)
        matches=list(re.finditer(r'【原文字符(\d+):(\d+) / 总长(\d+)】\n',rendered))
        self.assertGreater(len(matches),1)
        for i,match in enumerate(matches):
            start,end,total=map(int,match.groups())
            end_of_span=matches[i+1].start()-1 if i+1<len(matches) else len(rendered)
            self.assertEqual(rendered[match.end():end_of_span],body[start:end])
            self.assertEqual(total,len(body))
        self.assertLess(len(rendered),1250)

    def test_excerpt_does_not_shrink_full_workspace_document(self):
        from app.services.episode_workspace import EpisodeWorkspace
        from app.models.news import News
        from datetime import datetime
        import tempfile
        body='订单增长20%，仍需留意风险。'*1000
        row=News(id='long',title='企业订单增长',content=body,source='界面新闻公开原文',
            source_url='https://example.com/article',published_at=datetime(2026,10,28))
        with tempfile.TemporaryDirectory() as folder:
            workspace=EpisodeWorkspace([row],root=folder)
            self.assertLess(len(excerpt(row.content,row.title,600)),len(body))
            self.assertEqual(workspace.read('long',5000,500)['text'],body[5000:5500])
            self.assertTrue(workspace.read('long',5000,500)['has_more'])

    def test_character_guard_is_not_claimed_as_token_estimate(self):
        messages=[dict(role='user',content='中文'*100)]
        self.assertEqual(input_characters(messages),len(json.dumps(messages,ensure_ascii=False,separators=(',',':'))))
        self.assertEqual(validate_input(messages),input_characters(messages))
        with self.assertRaisesRegex(RuntimeError,'未发送请求'):validate_input(messages,100)


class GatewayGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_saved_case_preflight_has_no_network_and_preserves_source_snapshot(self):
        from app import prompt_cost_check as check
        from tests.test_selection_check import SelectionReplayTests
        from unittest.mock import AsyncMock
        from types import SimpleNamespace
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);data=SelectionReplayTests().snapshot()
            data['raw_articles'][1]['content']='企业订单增长20%，尚有需求风险。'*10000
            source=root/'news-acceptance.json';source.write_text(json.dumps(data),encoding='utf-8');before=source.read_bytes()
            case=root/'review-case.json';case.write_text(json.dumps(dict(content='测试报告',finance_evidence='旧资料'*60000,
                market_evidence='保留来源时间的行情资料。'*1000)),encoding='utf-8')
            with patch('app.selection_check.refresh_app_watchlist',AsyncMock()), \
                    patch('app.services.ai_analyzer.get_watchlist_service',return_value=SimpleNamespace(get_all_stocks=lambda:[])), \
                    patch('app.services.watchlist_service.get_watchlist_service',return_value=SimpleNamespace(get_all_stocks=lambda:[])), \
                    patch.object(check,'get_watchlist_service',return_value=SimpleNamespace(get_all_stocks=lambda:[])), \
                    patch('app.services.research_hub.ResearchHub.load',return_value=[]), \
                    patch.object(check.EventObservations,'context',return_value='只读观察记录'), \
                    patch('requests.get',side_effect=AssertionError('no network')), \
                    patch('app.services.ai_analyzer.AIAnalyzerService._call_ai',side_effect=AssertionError('no model')):
                result=await check.check(case,root)
            self.assertLess(result['new_finance_characters'],result['old_finance_characters']/4)
            self.assertFalse(any(result['would_stop_before_http'].values()))
            self.assertEqual(source.read_bytes(),before)

    async def test_oversized_input_stops_before_http_client_or_request_reservation(self):
        from app.services.model_gateway import complete
        with patch('app.services.model_gateway.httpx.AsyncClient',side_effect=AssertionError('no HTTP')) as client, \
                patch('app.services.model_usage.reserve_call',side_effect=AssertionError('no reserve')) as reserve:
            with self.assertRaisesRegex(RuntimeError,'未发送请求'):
                await complete('analysis',[dict(role='user',content='长资料'*40000)])
        client.assert_not_called();reserve.assert_not_called()
