import unittest

from app.services.evidence_reading import read_news


class EvidenceReadingTests(unittest.TestCase):
    def test_short_body_is_verbatim_and_footer_is_not_new_evidence(self):
        self.assertEqual(read_news('完整短正文。')['text'], '完整短正文。')
        text='经营事实仍待核对。\n相关阅读：\n另一公司宣布订单增长50%。'
        result=read_news(text, budget=1000)
        self.assertFalse(result['collected_text_fully_provided'])
        self.assertNotIn('另一公司宣布', result['text'])
        for start,end in result['ranges']:
            self.assertIn(text[start:end], result['text'])

    def test_dynamic_company_statement_keeps_subject_and_qualitative_change(self):
        body='行业已有变化。'+('其他背景介绍，没有具体数据。'*80)
        evidence='动态公司披露销量增长10%。公司表示，产能利用率饱和，新产线投产后紧张程度有所缓解。'
        body+=evidence+'不过，这并不代表未来利润一定增长。'+('一般背景。'*100)
        result=read_news(body, '行业经营变化', 320, ['动态公司'])
        self.assertIn(evidence, result['text'])
        self.assertIn('并不代表未来利润一定增长', result['text'])
        self.assertLessEqual(result['selected_characters'], 320)

    def test_peer_switch_cannot_detach_company_statement_from_immediate_subject(self):
        body='关注公司甲今天受到讨论。'+('无关背景介绍。'*100)
        context='公司乙披露出货量增长20%。公司表示，四季度产能已订满。'
        body+=context+('尾部一般介绍。'*80)
        result=read_news(body, '公司乙的产能变化', 240)
        self.assertIn(context, result['text'])
        self.assertTrue(any(context in body[start:end] for start,end in result['ranges']))

    def test_retains_actual_demand_qualification_not_only_weak_demand(self):
        body='行业披露经营情况。'+('其他资料介绍。'*100)
        body+='分析师表示，需求不及预期导致价格下降。'
        qualifier='不过，分析师对短期行情并不悲观。他指出，需求并未大幅崩塌；未来备货可能释放。'
        body+=qualifier+('其他资料介绍。'*100)
        result=read_news(body, '原料价格下降与需求', 240)
        self.assertIn('需求不及预期导致价格下降', result['text'])
        self.assertIn('需求并未大幅崩塌', result['text'])

    def test_english_initials_and_decimal_values_are_not_cut_into_facts(self):
        body='The Committee decided to maintain the rate at 3.75 percent. '
        body+='Economic growth remains strong. '+('Background context is available. '*30)
        names='Lisa D. Cook and Beth M. Hammack preferred to raise the rate by 0.25 percentage point.'
        body+=names
        result=read_news(body, 'Federal Reserve rate statement', 240)
        self.assertIn('3.75 percent.', result['text'])
        self.assertIn(names, result['text'])

    def test_never_cuts_an_oversized_unpunctuated_statement_into_partial_numbers(self):
        body='尚未完成的长句与数字12345'*100
        result=read_news(body, '长句', 100)
        self.assertEqual(result['ranges'], [])
        self.assertIn('需继续读取原文', result['text'])

    def test_ranges_are_verbatim_budgeted_and_bounded_under_different_limits(self):
        body='来源及日期需核对。'+('某公司表示，订单增长20%，但需求仍有不确定性。'*80)
        for budget in (50,100,300,642,1200):
            result=read_news(body, '订单和需求', budget, ['某公司'])
            self.assertLessEqual(result['selected_characters'], budget)
            self.assertLessEqual(len(result['ranges']), 4)
            self.assertEqual(result['selected_characters'], sum(end-start for start,end in result['ranges']))
            for start,end in result['ranges']:
                self.assertTrue(0<=start<end<=len(body))
                self.assertIn(body[start:end], result['text'])

    def test_full_original_is_not_modified_or_relabelled_as_verified(self):
        body='公司表示，新产线可能改善供给。'+('其他背景资料。'*100)
        before=body
        result=read_news(body, '新产线与供给', 200)
        self.assertEqual(body, before)
        self.assertIn('可能改善', result['text'])
        self.assertIn('不是财务结论或独立核实', result['text'])

    def test_invalid_budget_is_rejected(self):
        for value in (0,-1,True,3.5):
            with self.assertRaises(ValueError):
                read_news('正文', budget=value)

    def test_old_earnings_caveat_cannot_crowd_out_later_demand_qualification(self):
        early='利润同比增长80%，但主要受低基数影响。'
        body='行业财报。'+early+('利润增长与营业收入改善，季度盈利仍在恢复。'*30)
        claim='分析师表示，十月需求不及预期，价格下跌，供应宽松。'
        counter='不过，分析师对短期行情并不悲观。他指出，需求并未崩塌，年末备货可能释放。'
        body+=claim+'旺季排产在调整，局部库存仍高。'+counter+('一般介绍。'*40)
        result=read_news(body, '利润增长和需求变化', 280)
        self.assertIn(claim, result['text'])
        self.assertIn('需求并未崩塌', result['text'])
        self.assertLessEqual(result['selected_characters'], 280)

    def test_nearby_unread_qualification_is_explicit_when_budget_cannot_fit_it(self):
        claim='分析师表示，需求下降，价格回落。'
        counter='不过，需求并未消失，'+('局部市场需要进一步核实，'*15)+'仍需按时间和区域区分。'
        body=claim+counter+('一般背景介绍。'*50)
        result=read_news(body, '需求和价格回落', 90)
        self.assertIn(claim, result['text'])
        self.assertTrue(result['followup_ranges'])
        self.assertIn('邻近限定候选尚未提供', result['text'])
        self.assertNotIn(counter, result['text'])
        self.assertLessEqual(result['selected_characters'], 90)

    def test_full_short_text_has_no_false_followup(self):
        result=read_news('公司表示，需求下降，但订单尚未取消。', budget=300)
        self.assertEqual(result['followup_ranges'], [])
        self.assertTrue(result['collected_text_fully_provided'])
