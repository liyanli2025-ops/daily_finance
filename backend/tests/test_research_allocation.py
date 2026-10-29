from dataclasses import asdict
from datetime import datetime,timedelta
import unittest
from unittest.mock import patch

from app.services.research_hub import Material,ResearchHub
from app.services.watchlist_service import WatchlistStock


class ResearchAllocationTests(unittest.TestCase):
    def fixture(self):
        now=datetime(2026,10,29,14)
        contexts=[];stocks=[]
        kinds=['primary_notice','investor_relations','company_research','industry_research','industry_observation','financial_baseline','financial_report','investor_relations','operating_release']
        for index,count in enumerate([9,9,9,6]):
            name='动态企业'+str(index);code=str(120000+index);key='A:'+code
            materials=[]
            for number,kind in enumerate(kinds[:count]):
                old=kind in {'financial_baseline','financial_report'}
                stamp=now-timedelta(days=60) if old else now-timedelta(hours=2)
                body=('期间：2026上半年；币种：CNY\n- 营业收入（REVENUE）：123456.78 元\n'+'- 毛利率（MARGIN）：31.25 %\n'*60) if kind=='financial_baseline' else (name+'披露订单增长20%，但成本和库存仍有风险。')*120
                item=Material(str(index)+'-'+str(number),name+' '+kind,'公开来源','https://example.com/report/'+str(number),kind,key,body,stamp,now.isoformat(),'2026年原报告期间','存储文本节选')
                materials.append(dict(asdict(item),published_at=stamp.isoformat()))
            profile=dict(industry='行业归类',business=(name+'从事相关业务，实际敞口需原文核对。')*100,fields=['候选字段'+str(i) for i in range(40)],source_url='https://example.com/profile?'+('longparam=abc&'*100),collected_at=now.isoformat())
            contexts.append(dict(key=key,name=name,profile=profile,collected_at=now.isoformat(),materials=materials,coverage={'internal':{'status':'partial','details':'内部失败说明'*500}}))
            stocks.append(WatchlistStock(code,name,'A'))
        return now,contexts,stocks

    def test_33_cached_materials_do_not_starve_recent_evidence_in_four_stocks(self):
        now,contexts,stocks=self.fixture();hub=ResearchHub()
        with patch.object(hub,'load',return_value=contexts),patch('app.services.research_hub.china_now',return_value=now):
            text,evidence=hub.prompt(stocks,max_characters=8000)
        self.assertEqual(sum(len(c['materials']) for c in contexts),33)
        self.assertLessEqual(len(text),8000)
        self.assertEqual({item.scope for item in evidence if item.kind!='financial_baseline'},{c['key'] for c in contexts})
        self.assertTrue(any(item.kind in {'primary_notice','investor_relations','company_research','industry_research'} for item in evidence))
        self.assertGreater(sum(row['selected_characters'] for row in hub.prompt_reading),1600)
        self.assertEqual(len(hub.prompt_reading),33)
        self.assertNotIn('内部失败说明',text)
        self.assertNotIn('longparam=',text)
        self.assertTrue(all('longparam=' in c['profile']['source_url'] for c in contexts))
        self.assertIn('订单增长20%',text)

    def test_adding_many_candidates_does_not_recreate_equal_slice_starvation(self):
        now,contexts,stocks=self.fixture();context=contexts[0]
        for index in range(50):
            row=dict(context['materials'][1],id='extra-'+str(index))
            context['materials'].append(row)
        hub=ResearchHub()
        with patch.object(hub,'load',return_value=[context]),patch('app.services.research_hub.china_now',return_value=now):
            text,evidence=hub.prompt(stocks[:1],max_characters=2400)
        self.assertTrue(evidence)
        self.assertTrue(any(item.kind!='financial_baseline' for item in evidence))
        self.assertLessEqual(len(text),2400)
        self.assertEqual(len(hub.prompt_reading),59)
        self.assertEqual(hub.prompt_ranges.keys(),{item.id for item in evidence})
