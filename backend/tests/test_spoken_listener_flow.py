"""Check routing and explicit separation, not whether prose sounds human."""
from datetime import date
from types import SimpleNamespace
import unittest
import json
from app.services.spoken_editing import spoken_input
from app.services.spoken_programme import delivery_leaks, parse_response
from app.services.editorial_policy import spoken_prompts

class ListenerFlowTests(unittest.TestCase):
    def test_separates_only_explicit_editor_section_and_preserves_later_analysis(self):
        source='## 判断\n需求未明，不能据此认定需求稳定。\n## 编辑说明（不朗读）\n不要朗读后台规则。\n### 备注子项\n保留来源归属。\n## 应对\n若反弹延续，降低谨慎权重。'
        result=spoken_input(source)
        self.assertIn('需求未明，不能据此认定需求稳定。',result['analysis'])
        self.assertIn('若反弹延续，降低谨慎权重。',result['analysis'])
        self.assertNotIn('后台规则',result['analysis'])
        self.assertIn('保留来源归属。',result['editor_notes'])
        system,user=spoken_prompts(SimpleNamespace(content=source),date(2026,10,29),'早报')
        self.assertIn(result['analysis'],user);self.assertIn(result['editor_notes'],user)
        self.assertIn('不能从中新增投资判断',user)

    def test_does_not_strip_uncertainty_or_similar_headings(self):
        for source in ('材料没有订单信息，无法判断需求变化。','## 编辑观点\n利率可能影响估值。','引用“## 编辑说明（不朗读）”只是正文的一部分。'):
            self.assertEqual(spoken_input(source),dict(analysis=source,editor_notes=''))

    def test_catches_actual_backend_leaks_not_ordinary_source_attribution(self):
        for text in ('这是报道中有归属的说法。','报告没有给出具体仓位和目标价，这里也不编。'):
            self.assertTrue(delivery_leaks(text))
        self.assertFalse(delivery_leaks('据华尔街见闻转述，机构减持了部分债券。需求是否变化仍不清楚。'))

    def test_plan_cannot_use_editor_note_as_its_source_quote(self):
        report='正文只有这项判断。\n## 编辑说明（不朗读）\n这是检查人员留下的备注。'
        reply=dict(programme=dict(mainline='主线',choices=[dict(topic='主题',editorial_reason='解释变化',report_quotes=['这是检查人员留下的备注。'])],omitted=[]),script='口播文本。')
        with self.assertRaisesRegex(RuntimeError,'引用不在报告正文'):
            parse_response(json.dumps(reply,ensure_ascii=False),report)
