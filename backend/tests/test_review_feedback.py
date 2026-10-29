import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock,patch

from app.services.review_feedback import assess,decision_notes,ReviewNeedsHuman
from app.services.ai_analyzer import AIAnalyzerService
from app.models.report import ReportType


def issue(**changes):
    row=dict(type='数据不一致',severity='high',detail='报价数值与来源不符',check_kind='numeric_mismatch',
        report_quote='现价20元',source_quote='现价10元',comparison=dict(reported=20,source=10,same_basis=True))
    row.update(changes);return row


class FeedbackTests(unittest.TestCase):
    def test_valid_literal_comparison_is_grounded_not_declared_true(self):
        row=issue();before=json.dumps(row)
        result=assess([row],'现价20元，来源待核。','腾讯报价现价10元。')
        self.assertTrue(result['all_anchors_valid'])
        self.assertEqual(json.dumps(row),before)
        self.assertIn('不能证明',result['limitation'])

    def test_equal_numbers_nonfinite_booleans_and_mixed_basis_cannot_trigger_repair(self):
        for comparison in [dict(reported=-2.94,source=-2.94,same_basis=True),
                           dict(reported=True,source=10,same_basis=True),
                           dict(reported=float('inf'),source=10,same_basis=True),
                           dict(reported=20,source=10,same_basis=False)]:
            result=assess([issue(comparison=comparison)],'现价20元','现价10元')
            self.assertFalse(result['all_anchors_valid'])

    def test_quoted_sentence_and_source_must_exist_not_just_source_id(self):
        for changes in [dict(report_quote='不存在的断言'),dict(source_quote='不存在的来源'),dict(check_kind='unknown'),dict(report_quote=None)]:
            self.assertFalse(assess([issue(**changes)],'现价20元','现价10元')['all_anchors_valid'])
        row=issue(report_quote='现价\n20元',source_quote='现价\n10元')
        self.assertTrue(assess([row],'现价 20元','现价 10元')['all_anchors_valid'])

    def test_missing_material_is_not_proof_of_fabrication(self):
        row=issue(check_kind='missing_evidence',source_quote='',comparison=None)
        self.assertFalse(assess([row],'现价20元','缺少报价')['all_anchors_valid'])
        row['type']='内容缺失'
        self.assertTrue(assess([row],'现价20元','缺少报价')['all_anchors_valid'])

    def test_legacy_review_is_unverified_not_automatically_rejected_as_false(self):
        result=assess([dict(type='逻辑矛盾',detail='旧审查意见')],'报告正文','材料')
        self.assertFalse(result['all_anchors_valid'])
        self.assertEqual(result['issues'][0]['reasons'],['report_quote_missing_or_not_found','check_kind_missing_or_unknown'])

    def note(self):
        return dict(claim='当前表现可能同时受多种因素影响',horizon='未来1—3个交易日',price_structure='下降结构中的反弹',
            possible_drivers='盈利消息与风险偏好可共同作用',main_alternative='反弹缺乏持续性',watch='相对表现是否延续',
            invalidation='同口径相对表现转弱',why_invalidation_matters='这会削弱相对强势判断',support_ids=['source'],counterevidence_ids=[])

    def test_deliverable_notes_are_bounded_and_cannot_add_unknown_ids(self):
        self.assertEqual(decision_notes([self.note()],{'source'})[0]['possible_drivers'],'盈利消息与风险偏好可共同作用')
        self.assertEqual(decision_notes(None,set()),[])
        for value in [[self.note()]*4,[dict(self.note(),support_ids=['invented'])],[dict(self.note(),claim=True)],{}]:
            with self.assertRaises(RuntimeError):decision_notes(value,{'source'})

    def test_display_prefix_normalizes_only_exact_known_ids(self):
        note=dict(self.note(),support_ids=['N:source'])
        self.assertEqual(decision_notes([note],{'source'})[0]['support_ids'],['source'])
        self.assertEqual(note['support_ids'],['N:source'])
        self.assertEqual(decision_notes([note],{'N:source','source'})[0]['support_ids'],['N:source'])
        for bad in ['N:unknown','N:N:source',' source','SOURCE']:
            with self.assertRaises(RuntimeError):
                decision_notes([dict(note,support_ids=[bad])],{'source'})

    def test_report_parser_retains_decision_notes_for_review_not_app_schema(self):
        from datetime import date
        from app.models.news import News
        analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
        metadata=dict(title='条件判断',summary='这是摘要',core_opinions=[],decision_notes=[self.note()],
            market_analysis=dict(overall_sentiment='neutral',trend='neutral'))
        response='报告正文[N:source]\n```json\n'+json.dumps(metadata,ensure_ascii=False)+'\n```'
        news=News(id='source',title='来源事实',content='来源正文',source='公开原文',source_url='https://example.com/fact',published_at=__import__('datetime').datetime(2026,10,28))
        report=analyzer._parse_enhanced_report_response(response,date(2026,10,28),[news],[])
        self.assertEqual(analyzer._decision_notes[0]['price_structure'],'下降结构中的反弹')
        self.assertNotIn('decision_notes',report.content)


class ReviewFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_unanchored_or_self_conflicting_review_stops_without_repair_or_second_call(self):
        for row in [dict(type='数据不一致',severity='medium',detail='旧审查没有原句'),
                    issue(comparison=dict(reported=20,source=20,same_basis=True))]:
            analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
            report=SimpleNamespace(content='现价20元')
            analyzer._call_ai=AsyncMock(return_value=json.dumps(dict(overall_quality=6,issues=[row])))
            analyzer._ai_fix_report=AsyncMock()
            with patch('app.services.ai_analyzer.save_review_case',return_value=Path('private-review.json')) as save:
                with self.assertRaises(ReviewNeedsHuman):
                    await analyzer._review_and_fix_report(report,'','现价10元','','',ReportType.MORNING)
            analyzer._call_ai.assert_awaited_once();analyzer._ai_fix_report.assert_not_awaited()
            self.assertFalse(save.call_args.args[2]['feedback_checks']['all_anchors_valid'])
            self.assertIs(analyzer._last_reviewed_report,report)

    async def test_low_score_without_actionable_issue_does_not_pay_for_rewrite(self):
        analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
        analyzer._call_ai=AsyncMock(return_value='{"overall_quality":6,"issues":[]}')
        analyzer._ai_fix_report=AsyncMock()
        with patch('app.services.ai_analyzer.save_review_case'):
            with self.assertRaises(ReviewNeedsHuman):await analyzer._review_and_fix_report(SimpleNamespace(content='正文'),'','','','',ReportType.MORNING)
        analyzer._ai_fix_report.assert_not_awaited();analyzer._call_ai.assert_awaited_once()

    async def test_grounded_small_edit_is_not_replaced_out_of_context(self):
        analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
        report=SimpleNamespace(content='原句表达欠清晰')
        row=dict(type='表述模糊',severity='low',detail='需编辑核对',check_kind='clarity',report_quote=report.content)
        analyzer._call_ai=AsyncMock(return_value=json.dumps(dict(overall_quality=8,issues=[row])))
        analyzer._lightweight_fix_report=AsyncMock()
        with patch('app.services.ai_analyzer.save_review_case'):
            with self.assertRaises(ReviewNeedsHuman):await analyzer._review_and_fix_report(report,'','','','',ReportType.MORNING)
        analyzer._lightweight_fix_report.assert_not_awaited();self.assertEqual(report.content,'原句表达欠清晰')


class SavedReviewToolTests(unittest.TestCase):
    def test_export_is_explicitly_unapproved_and_original_review_is_unchanged(self):
        from app.review_check import inspect
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'review.json'
            path.write_text(json.dumps(dict(content='已付费保存的修稿',metadata={},review=dict(overall_quality=6,issues=[]))),encoding='utf-8')
            original=path.read_bytes()
            with patch('requests.get',side_effect=AssertionError('no network')):
                result=inspect(path,True);again=inspect(path,True)
            self.assertEqual(result,again)
            self.assertEqual(path.read_bytes(),original)
            self.assertIn('未通过发布审核',Path(result['candidate_output']).read_text(encoding='utf-8'))
            self.assertEqual(result['status'],'saved_case_for_human_review')
