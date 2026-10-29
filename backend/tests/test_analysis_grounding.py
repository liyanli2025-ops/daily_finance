import unittest
from app.services.analysis_grounding import rsi_band, research_contrast_index, decision_pairs


class GroundingTests(unittest.TestCase):
    def test_exact_rsi_boundaries_and_invalid_values(self):
        for value in (29.9999,0): self.assertEqual(rsi_band(value),'below_30')
        for value in (30,30.2007,30.2941,30.3028,70): self.assertEqual(rsi_band(value),'within_30_70')
        self.assertEqual(rsi_band(70.0001),'above_70')
        for value in (None,True,'25',float('nan'),float('inf'),-1,101):
            self.assertEqual(rsi_band(value),'unavailable')

    def test_only_exact_provided_source_lines_get_indexed(self):
        quote='第三季度单位盈利能力变化有如下因素：产品结构的变化，以及消费税和出口退税的影响。'
        text='[N:ir-1] 公司交流\n类型：investor_relations\n【原文字符0:80 / 总长800】\n'+quote
        result=research_contrast_index(text)
        self.assertIn('[N:ir-1] '+quote,result)
        self.assertIn('不认定负面',result)
        self.assertNotIn('未提供的缓存',result)
        question='请问第三季度单位盈利能力变化的主要原因及未来趋势展望是什么？'
        self.assertEqual(research_contrast_index(text.split('【')[0]+'【原文字符0:80】'+question),'')
        self.assertEqual(research_contrast_index(text.split('【')[0]),'')

    def test_positive_change_is_not_labeled_negative_and_limit_is_bounded(self):
        text='\n'.join('[N:x'+str(i)+'] 交流\n类型：investor_relations\n【原文字符0:90】\n本季度产品结构持续改善，公司表示相关单位盈利能力有所提升。' for i in range(8))
        result=research_contrast_index(text)
        self.assertEqual(result.count('[N:'),4)
        self.assertNotIn('[N:x4]',result)

    def test_pair_check_never_auto_judges_or_changes_claim(self):
        note=dict(claim='下降结构中的反弹',invalidation='反弹回吐',why_invalidation_matters='单日修复')
        out=decision_pairs([note])[0]
        self.assertEqual(out['claim'],note['claim'])
        self.assertEqual(out['status'],'needs_semantic_review')
        self.assertNotIn('status',note)
