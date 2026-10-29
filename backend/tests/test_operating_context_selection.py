from datetime import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.models.news import News
from app.services.ai_analyzer import AIAnalyzerService
from app.services.news_briefing import associations,operating_context
from app.services.evidence_audit import audit
from app.services.watchlist_service import WatchlistStock


def article(key,title,body,day='2026-10-28T20:00:00'):
    return News(id=key,title=title,content=body,source='界面新闻公开原文',source_url='https://example.com/'+key,
        published_at=datetime.fromisoformat(day),importance_score=.5)


class OperatingContextTests(unittest.TestCase):
    def setUp(self):
        self.battery=WatchlistStock('123456','动态电池公司','A')
        self.hydro=WatchlistStock('234567','动态水电公司','A')
        self.profiles={'A:123456':dict(business='主营动力电池'),
                       'A:234567':dict(business='水力发电')}
        self.price=article('price','碳酸锂期价回落，供需出现什么变化？','碳酸锂价格下跌4%，现货价格回落，供给增加。'*15)
        self.peer=article('peer','另一水电公司三季报，来水与电价如何影响利润？',
            '水电发电量下降2%，流域来水偏少。动态水电公司此前披露发电量下降4%，两流域不可混同。'*12)

    def test_critical_operating_evidence_survives_newer_generic_company_news(self):
        pool=[self.price,self.peer]+[article(str(i),'一般公司'+str(i)+'营收增长20%，净利润变化',
            '营业收入增长20%，利润增长10%，经营变化待核。'*20,'2026-10-29T07:00:00') for i in range(40)]
        analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
        service=SimpleNamespace(get_all_stocks=lambda:[self.battery,self.hydro])
        profiles=[dict(key=key,profile=value) for key,value in self.profiles.items()]
        with patch('app.services.ai_analyzer.get_watchlist_service',return_value=service),patch('app.services.research_hub.ResearchHub.load',return_value=profiles),patch('requests.get',side_effect=AssertionError('no network')):
            analyzer._prepare_news_summary(pool)
        ids={row.id for row in analyzer._selected_evidence_news}
        self.assertTrue({'price','peer'}.issubset(ids))
        self.assertLessEqual(len(ids),28)

    def test_peer_metric_is_operating_context_not_company_owned_new_fact(self):
        row=associations(self.peer,[self.hydro],self.profiles)[0]
        self.assertEqual(row['level'],'company_mention')
        self.assertEqual(row['focus'],'body_mention')
        self.assertEqual(row['operating_context'],'水电经营与同业对照')
        result=audit([self.peer],[self.peer],[self.hydro],self.profiles)['per_stock'][0]
        self.assertEqual(result['company_original_ids'],[])
        self.assertEqual(result['industry_original_ids'],['peer'])

    def test_wide_semiconductor_labels_or_purchasing_power_cannot_fill_company_gaps(self):
        equipment=article('equipment','半导体设备ETF上涨3%','半导体设备行业资本开支增长。'*10)
        self.assertIsNone(operating_context(equipment,dict(business='主营环氧塑封料、封装材料')))
        mine=article('mine','稀土矿融资与水电站购电安排','该矿同某水电站签署购电协议，融资3000万美元。'*10)
        self.assertIsNone(operating_context(mine,self.profiles['A:234567']))

    def test_fund_holdings_and_related_links_cannot_become_physical_operating_context(self):
        fund=article('fund','基金三季报持仓：碳酸锂公司与电池股变化','碳酸锂价格下降4%，属于持仓解释。'*10)
        self.assertIsNone(operating_context(fund,self.profiles['A:123456']))
        footer=article('footer','全行业观察','只介绍宏观背景。\n相关阅读：\n碳酸锂价格下降4%，供给增加。')
        self.assertIsNone(operating_context(footer,self.profiles['A:123456']))
