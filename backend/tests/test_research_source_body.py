from datetime import datetime
from dataclasses import asdict
import unittest
from unittest.mock import patch

from app.services.research_reading import read_research
from app.services.research_relevance import conditional_plan_reminder
from app.services.research_hub import ResearchHub,Material


class ResearchSourceBodyTests(unittest.TestCase):
    def test_generated_broker_preamble_is_not_counted_as_research_body(self):
        prefix='以下是PDF原文节选；券商评级和盈利预测是该机构当时的观点，不得作为本节目买卖指令。'
        body=prefix+'\n【原PDF第1页】\n'+('多栏长表格1234567890'*200)
        result=read_research(body,'company_research',budget=220)
        self.assertEqual(result['source_body_characters'],0)
        self.assertGreater(result['selected_characters'],0)

    def test_real_source_uncertainty_is_not_stripped_as_generated_caveat(self):
        body='公司表示，需求并未崩塌，但客户订单和库存仍有风险。'
        result=read_research(body,'investor_relations',budget=300)
        self.assertEqual(result['source_body_characters'],len(body))
        self.assertIn('仍有风险',result['text'])

    def test_baseline_period_and_currency_without_metric_row_are_not_financial_data(self):
        head='供应商指标，未与原报告核对。\n期间：2026-06-30；币种：CNY\n'
        body=head+'- 营业收入（REV）：12345678901234567890.12 元\n'
        result=read_research(body,'financial_baseline',budget=len(head)+5)
        self.assertEqual(result['source_body_characters'],0)
        self.assertGreater(result['selected_characters'],0)

    def test_preamble_only_material_does_not_enter_citable_initial_evidence(self):
        now=datetime(2026,10,29,14)
        body='以下是PDF原文节选；券商评级和盈利预测是该机构当时的观点，不得作为本节目买卖指令。\n【原PDF第1页】\n'+('长表格字段1234567890'*500)
        m=Material('r','研究报告','机构','https://example.com/a.pdf','company_research','A:123456',body,now,now.isoformat())
        c=dict(key='A:123456',name='动态企业',profile=None,coverage={},materials=[dict(asdict(m),published_at=now.isoformat())])
        h=ResearchHub()
        with patch.object(h,'load',return_value=[c]),patch('app.services.research_hub.china_now',return_value=now):
            text,evidence=h.prompt([],max_characters=1600)
        self.assertEqual(evidence,[])
        self.assertEqual(h.prompt_reading[0]['status'],'not_provided_source_preamble_only')
        self.assertNotIn('[N:r]',text)

    def test_six_month_conditional_reminder_is_background_but_executed_sale_is_not(self):
        title='某公司：关于员工持股计划存续期届满前六个月的提示性公告'
        body='届满前将根据市场情况决定是否卖出股票或其他处置安排。'
        self.assertTrue(conditional_plan_reminder(title,body))
        self.assertFalse(conditional_plan_reminder(title,body+'本计划已全部出售所持股票。'))
        self.assertFalse(conditional_plan_reminder(title,body+'已决定延长存续期。'))
        self.assertFalse(conditional_plan_reminder('重大风险提示性公告',body))
