from dataclasses import asdict
from datetime import datetime
import unittest
from unittest.mock import patch

from app.services.research_hub import Material,ResearchHub
from app.services.research_reading import read_research
from app.services.watchlist_service import WatchlistStock


class ResearchReadingTests(unittest.TestCase):
    def test_later_operating_statement_and_risk_keep_pdf_page(self):
        body='报告抽取节选，表格列关系可能丢失。\n【原PDF第2页】\n'+('一般背景内容。'*140)
        body+='\n【原PDF第14页】\n动态公司披露储能销量增长30%。公司表示，产能仍紧张。'
        body+='不过，这不代表未来需求必然增长，库存风险仍需关注。'+('背景信息。'*120)
        result=read_research(body,'company_research','经营变化',420,['动态公司','储能'])
        self.assertIn('储能销量增长30%',result['text'])
        self.assertIn('未来需求必然增长',result['text'])
        self.assertIn('【原PDF第14页】',result['text'])
        self.assertLessEqual(result['selected_characters'],420)
        for a,b in result['ranges']:self.assertIn(body[a:b],result['text'])

    def test_mirror_chunk_is_not_relabelled_as_pdf_page(self):
        body='材料仅为镜像前部，不是原PDF全文。'+('一般说明。'*150)
        body+='\n【镜像文本分片3，不是PDF页码】\n动态企业披露订单增长20%。公司表示，预测仍有风险。'
        result=read_research(body,'financial_report','经营情况',350,['动态企业','订单'])
        self.assertIn('【镜像文本分片3，不是PDF页码】',result['text'])
        self.assertNotIn('原PDF第3页',result['text'])

    def test_structured_baseline_preserves_currency_period_complete_metric_rows(self):
        first='供应商指标，尚未逐项核对。\n期间截止：2026-06-30；币种：CNY\n'
        line='- 营业收入（REVENUE）：1234567890.123 元\n'
        body=first+line+'- 毛利率（MARGIN）：31.25 %\n'
        result=read_research(body,'financial_baseline',budget=len(first+line)+8)
        self.assertEqual(result['ranges'],[[0,len(first+line)]])
        self.assertIn('1234567890.123 元',result['text'])
        self.assertNotIn('毛利率（MARGIN）',result['text'])
        self.assertIn('币种：CNY',result['text'])

    def test_oversized_metric_is_not_sliced_or_marked_full(self):
        result=read_research('- 长指标：1234567890 元\n','financial_baseline',budget=8)
        self.assertFalse(result['ranges'])
        self.assertFalse(result['collected_text_fully_provided'])
        self.assertIn('须用read_material',result['text'])

    def test_short_research_remains_verbatim(self):
        body='某机构预计需求可能改善，不代表实现结果。'
        result=read_research(body,'industry_research',budget=300)
        self.assertEqual(result['text'],body)
        self.assertTrue(result['collected_text_fully_provided'])

    def test_initial_research_render_and_ledger_are_budgeted_without_changing_pool_body(self):
        now=datetime(2026,10,29,7,32)
        body='报告简介。'+('一般背景。'*160)+'\n【原PDF第9页】\n新关注企业披露订单增长20%。公司表示，成本仍承压。'+('一般说明。'*100)
        material=Material('r','经营资料','机构观点','https://example.com/report.pdf','company_research','A:123456',body,now,now.isoformat(),'2026三季度','带页码节选')
        context=dict(key='A:123456',name='新关注企业',profile=None,coverage={},materials=[dict(asdict(material),published_at=now.isoformat())])
        hub=ResearchHub()
        with patch.object(hub,'load',return_value=[context]),patch('app.services.research_hub.china_now',return_value=now):
            text,evidence=hub.prompt([WatchlistStock('123456','新关注企业','A')],max_characters=4500)
        self.assertIn('订单增长20%',text)
        self.assertIn('原PDF第9页',text)
        self.assertLessEqual(len(text),4500)
        self.assertEqual(evidence[0].body,body)
        self.assertTrue(hub.prompt_ranges['r'])
        self.assertEqual(hub.prompt_reading[0]['status'],'provided')
        self.assertEqual(hub.prompt_reading[0]['selected_characters'],sum(b-a for a,b in hub.prompt_ranges['r']))

    def test_four_dynamic_stocks_keep_small_background_metric_without_promoting_it_to_catalyst(self):
        now=datetime(2026,10,29,7,32)
        old=datetime(2026,8,1)
        contexts=[];stocks=[]
        for index in range(4):
            code=str(123450+index);name='动态企业'+str(index);key='A:'+code
            body='供应商指标，尚未与原财报核对。\n期间截止：2026-06-30；币种：CNY\n- 营业收入（REVENUE）：1234567890.12 元\n- 毛利率（MARGIN）：31.25 %\n'+('- 其他指标（OTHER）：12.34 元\n'*30)
            item=Material('r'+str(index),name+'历史指标','公开镜像','https://example.com/verylong?'+('param=x&'*50),'financial_baseline',key,body,old,now.isoformat(),'2026上半年','结构化指标，非财报全文')
            contexts.append(dict(key=key,name=name,profile=None,coverage={},materials=[dict(asdict(item),published_at=old.isoformat())]))
            stocks.append(WatchlistStock(code,name,'A'))
        hub=ResearchHub()
        with patch.object(hub,'load',return_value=contexts),patch('app.services.research_hub.china_now',return_value=now):
            text,evidence=hub.prompt(stocks,max_characters=8000)
        self.assertLessEqual(len(text),8000)
        self.assertEqual(len(evidence),4)
        self.assertEqual(text.count('营业收入（REVENUE）：1234567890.12 元'),4)
        self.assertNotIn('param=x',text)
        self.assertTrue(all('param=x' in item.source_url for item in evidence))
        self.assertIn('不等于今日催化',text)
        self.assertTrue(all(row['selected_characters']<row['stored_characters'] for row in hub.prompt_reading))

    def test_skipped_research_is_visible_in_reading_ledger(self):
        now=datetime(2026,10,29,7,32)
        item=Material('unread','研究资料','来源','https://example.com/r','company_research','A:123456','未分句长表格1234567890'*300,now,now.isoformat())
        context=dict(key='A:123456',name='动态企业',profile=None,coverage={},materials=[dict(asdict(item),published_at=now.isoformat())])
        hub=ResearchHub()
        with patch.object(hub,'load',return_value=[context]),patch('app.services.research_hub.china_now',return_value=now):
            text,evidence=hub.prompt([WatchlistStock('123456','动态企业','A')],max_characters=1800)
        self.assertEqual(evidence,[])
        self.assertNotIn('unread',hub.prompt_ranges)
        self.assertEqual(hub.prompt_reading[0]['status'],'not_provided_within_budget')

    def test_free_inspection_uses_cached_research_without_fetch_or_generation(self):
        from app.research_input_check import inspect
        now=datetime(2026,10,29,7,32)
        item=Material('cached','经营资料','机构','https://example.com/a','company_research','A:123456','该企业披露订单增长20%，仍需关注库存风险。',now,now.isoformat())
        context=dict(key='A:123456',name='动态企业',profile=None,coverage={'collection':{'status':'ok'}},materials=[dict(asdict(item),published_at=now.isoformat())])
        hub=ResearchHub()
        with patch.object(hub,'load',return_value=[context]),patch.object(hub,'get_json',side_effect=AssertionError('must not fetch')),patch.object(hub,'collect_stock',side_effect=AssertionError('must not collect')),patch('app.services.research_hub.china_now',return_value=now):
            result=inspect([WatchlistStock('123456','动态企业','A')],hub,True)
        self.assertEqual(result['model_requests_performed'],0)
        self.assertEqual(result['prepared_materials'],1)
        self.assertIn('订单增长20%',result['range_previews'][0]['text'])
        self.assertEqual(result['reading_status_counts'],{'provided':1})
