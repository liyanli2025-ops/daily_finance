import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch,Mock,AsyncMock

from app.models.report import ReportType
from app.services.ai_analyzer import AIAnalyzerService
from app.services.report_diagnostics import save_review_case,save_generation_stage


class ReviewContextTests(unittest.TestCase):
    def test_unparsed_generation_is_checkpointed_separately_and_marked_unreviewed(self):
        with tempfile.TemporaryDirectory() as folder:
            path=save_generation_stage('repair_response','完整修复正文及未解析元数据',folder)
            data=json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(data['response'],'完整修复正文及未解析元数据')
            self.assertEqual(data['status'],'unreviewed')
            self.assertEqual(data['stage'],'repair_response')

    def test_checkpoint_failure_stops_before_another_paid_stage(self):
        with patch('app.services.research_hub.save_json',side_effect=PermissionError()):
            with self.assertRaisesRegex(RuntimeError,'停止后续模型请求'):
                save_generation_stage('draft_response','已花费生成的完整文本')

    def test_snapshot_retains_complete_draft_evidence_and_review(self):
        with tempfile.TemporaryDirectory() as folder:
            report = SimpleNamespace(content='失败稿原文')
            path = save_review_case(report, {'title':'标题'}, {'issues':[{'detail':'完整问题'*80}]},
                                    '新闻原文及ID', '跨界原文', '市场材料', '生成时点', True, folder)
            saved = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(saved['content'], report.content)
            self.assertEqual(saved['finance_evidence'], '新闻原文及ID')
            self.assertEqual(saved['review']['issues'][0]['detail'], '完整问题'*80)
            self.assertTrue(saved['repaired'])
            self.assertEqual(len(list(Path(folder).iterdir())), 1)

    def test_reviewer_does_not_demand_unverified_market_numbers(self):
        analyzer = AIAnalyzerService.__new__(AIAnalyzerService)
        prompt = analyzer._build_review_prompt('report', 'market', 'finance', 'cross', ReportType.MORNING)
        self.assertIn('不得要求以无来源时间的快照补齐实时盘面', prompt)
        self.assertIn('不能凭审查员记忆裁定真实值', prompt)


class GenerationCheckpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_draft_is_preserved_before_parser_failure(self):
        from app.services.market_data_service import MarketOverview
        service=AIAnalyzerService.__new__(AIAnalyzerService)
        service._prepare_watchlist_analysis=Mock(return_value='当前自选股')
        service._prepare_news_summary_with_sentiment=Mock(return_value='新闻原文')
        service._prepare_cross_border_summary=Mock(return_value='')
        service._selected_evidence_news=[SimpleNamespace(id='real')]
        service._cross_border_evidence_news=[]
        service._call_ai=AsyncMock(return_value='完整回复但元数据有误')
        order=[]
        def parse(*args):
            order.append('parse')
            raise RuntimeError('parse fixture')
        service._parse_enhanced_report_response=Mock(side_effect=parse)
        with patch('app.services.ai_analyzer.refresh_app_watchlist',AsyncMock()), \
                patch('app.services.ai_analyzer.get_watchlist_service',return_value=SimpleNamespace(get_all_stocks=lambda:[])), \
                patch('app.services.ai_analyzer.get_market_data_service',return_value=SimpleNamespace(
                    get_market_overview=AsyncMock(return_value=MarketOverview(date='2026-10-25')))), \
                patch('app.services.event_observations.EventObservations.context',return_value='传播未知'), \
                patch('app.services.research_hub.ResearchHub.prompt',return_value=('研究底稿',[])), \
                patch('app.services.report_diagnostics.save_generation_stage',side_effect=lambda *args:order.append('saved')) as save:
            with self.assertRaisesRegex(RuntimeError,'parse fixture'):
                await service.generate_daily_report([SimpleNamespace(id='real')])
        self.assertEqual(order,['saved','parse'])
        save.assert_called_once_with('draft_response','完整回复但元数据有误')

    async def test_repaired_response_survives_bad_metadata(self):
        service=AIAnalyzerService.__new__(AIAnalyzerService)
        service._call_ai=AsyncMock(return_value='完整修复正文，但没有完整JSON元数据')
        with patch('app.services.report_diagnostics.save_generation_stage') as save:
            with self.assertRaisesRegex(RuntimeError,'完整元数据'):
                await service._ai_fix_report(SimpleNamespace(content='原稿'),'',[], 'market',ReportType.MORNING)
        save.assert_called_once_with('repair_response','完整修复正文，但没有完整JSON元数据')
