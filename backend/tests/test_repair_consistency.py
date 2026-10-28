from datetime import date
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch

from app.models.report import Report,ReportType
from app.services.ai_analyzer import AIAnalyzerService
from app.services.editorial_policy import REPORT_POLICY


class RepairConsistencyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
        self.report=Report(id='kept-id',title='原始标题',summary='原始摘要',content='原始正文和条件',report_date=date(2026,10,28))
        self.analyzer._last_reviewed_report=self.report
        self.analyzer._decision_notes=[dict(claim='原稿判断')]
        self.analyzer._cross_border_evidence_news=[SimpleNamespace(id='overseas')]
        self.metadata=dict(title='修稿标题',summary='修稿摘要',core_opinions=['修稿观点'],
            market_analysis=dict(overall_sentiment='neutral',trend='neutral'))

    async def repair(self,body='修稿正文和条件',metadata=None):
        value=self.metadata if metadata is None else metadata
        self.analyzer._call_ai=AsyncMock(return_value=body+'\n```json\n'+json.dumps(value,ensure_ascii=False)+'\n```')
        with patch('app.services.report_diagnostics.save_generation_stage') as save:
            result=await self.analyzer._ai_fix_report(self.report,'unused',[], 'market',ReportType.MORNING,
                finance_summary='已提供的财经片段',cross_border_summary='已提供的海外片段')
        save.assert_called_once()
        self.analyzer._call_ai.assert_awaited_once()
        return result

    async def test_repair_reuses_full_editorial_policy_and_keeps_original_version(self):
        result=await self.repair()
        prompt=self.analyzer._call_ai.call_args.args[0]
        self.assertIn(REPORT_POLICY,prompt)
        self.assertIn('不机械保持原文风格',prompt)
        self.assertIn('已提供的海外片段',prompt)
        self.assertIsNot(result,self.report)
        self.assertEqual(result.id,self.report.id)
        self.assertEqual(result.content,'修稿正文和条件')
        self.assertEqual(result.summary,'修稿摘要')
        self.assertEqual(self.report.title,'原始标题')
        self.assertEqual(self.report.content,'原始正文和条件')
        self.assertIs(self.analyzer._last_reviewed_report,self.report)

    async def test_valid_cross_market_note_is_not_rejected_as_unknown(self):
        note=dict(claim='海外盈利消息可作为催化',horizon='未来数日',price_structure='下降结构尚未改变',
            possible_drivers='海外盈利消息',main_alternative='上涨缺乏持续性',watch='完成后的价格结构',
            invalidation='原下降结构改变',why_invalidation_matters='下降结构解释需要修正',
            support_ids=['overseas'],counterevidence_ids=[])
        result=await self.repair(metadata=dict(self.metadata,decision_notes=[note]))
        self.assertEqual(self.analyzer._decision_notes[0]['support_ids'],['overseas'])
        self.assertEqual(result.title,'修稿标题')

    async def test_invalid_note_cannot_partly_replace_the_original_or_notes(self):
        before=self.report.model_dump()
        with self.assertRaises(RuntimeError):
            await self.repair(metadata=dict(self.metadata,decision_notes=[dict(claim='不完整')]))
        self.assertEqual(self.report.model_dump(),before)
        self.assertEqual(self.analyzer._decision_notes,[dict(claim='原稿判断')])

    async def test_empty_body_is_rejected_before_any_followup(self):
        before=self.report.model_dump()
        with self.assertRaisesRegex(RuntimeError,'缺少正文'):await self.repair(body='')
        self.assertEqual(self.report.model_dump(),before)
        self.assertEqual(self.analyzer._call_ai.await_count,1)
