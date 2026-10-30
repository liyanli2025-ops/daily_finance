from datetime import datetime,timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from app.models.news import News,NewsType
from app.services.market_coverage import market_candidates,coverage_role,cross_category_reason
from app.services.ai_analyzer import AIAnalyzerService
from app.selection_check import candidates

NOW=datetime(2026,10,30,17,9)

def article(key,title,body='',kind=NewsType.FINANCE,minutes=10):
    return News(id=key,title=title,content=title+'。'+body+'公开报道的事实，需要核对日期与来源。'*30,
        news_type=kind,source='财联社公开原文',source_url='https://www.cls.cn/detail/'+key,
        published_at=NOW-timedelta(minutes=minutes),importance_score=.7)

class MarketCoverageTests(unittest.TestCase):
    def test_type_label_does_not_hide_financial_event_or_supply_shock(self):
        earnings=article('1','新公司第三季度净利润增长30%',kind=NewsType.TECH)
        shock=article('2','海峡封锁导致能源运输受阻','原油供应和航运价格受到影响',kind=NewsType.GEOPOLITICAL)
        gadget=article('3','新款手机今天发布',kind=NewsType.TECH)
        self.assertEqual([x.id for x in market_candidates([earnings,shock,gadget])],['1','2'])
        self.assertIsNone(cross_category_reason(gadget))

    def test_market_context_survives_generic_company_quota_and_prefers_daily(self):
        a=article('10','每日收评：创业板指下跌，全市场多数股票收绿',minutes=30)
        monthly=article('11','收评：A股10月收官，指数月跌幅扩大',minutes=80)
        h=article('12','港股收评：恒生指数上涨',minutes=20)
        hm=article('13','港股收盘：科技指数创单月最大跌幅',minutes=10)
        us=article('14','美股收盘：纳指下跌',minutes=400)
        overseas=article('15','海外云厂商财报：现金流与资本开支分化','华尔街和美股关注盈利兑现')
        risk=article('16','海峡运输风险上升','原油供应与天然气价格变动')
        generic=[article(str(i+100),'公司'+str(i)+'净利润同比增长'+str(i)+'%') for i in range(40)]
        service=AIAnalyzerService.__new__(AIAnalyzerService)
        with patch('app.services.ai_analyzer.get_watchlist_service',return_value=SimpleNamespace(get_all_stocks=lambda:[])),patch('app.services.research_hub.ResearchHub.load',return_value=[]):
            service._prepare_news_summary(generic+[a,monthly,h,hm,us,overseas,risk])
        selected={x.id for x in service._selected_evidence_news}
        self.assertTrue({'10','12','14','15','16'}<=selected)
        self.assertEqual(service._news_briefing['market_coverage']['hk_session']['selected_ids'],['12'])

    def test_supply_news_is_not_inferred_from_unrelated_body_references(self):
        self.assertIsNone(coverage_role(article('20','美国季度经济数据发布','文末提及关税、原油和其他文章')))
        self.assertNotEqual(coverage_role(article('21','全球科技股下跌！纳指期货跌2%，英特尔美股盘前下跌，韩股收跌3%')), 'us_session')
        self.assertIsNone(coverage_role(article('22','ETF今日收评：创业板ETF下跌'))) 

    def test_restore_is_explicit_time_bounded_and_preserves_original_type(self):
        rows=[]
        for x in [article('30','科技公司三季度净利润增长',kind=NewsType.TECH),article('31','新款手机发布',kind=NewsType.TECH),article('32','公司三季度净利润增长',kind=NewsType.TECH,minutes=-2)]:
            rows.append(dict(id=x.id,title=x.title,content=x.content,source=x.source,url=x.source_url,published=x.published_at.isoformat(),news_type=x.news_type.value))
        # An existing admitted entry is retained; restoration only adds in-window leads.
        data=dict(full_collection=True,collected_at=NOW.isoformat(),hours=72,selection=dict(articles=[dict(id='31')]),raw_articles=rows)
        self.assertEqual([x.id for x in candidates(data)],['31'])
        self.assertEqual([x.id for x in candidates(data,True)],['30','31'])
        self.assertEqual(candidates(data,True)[0].news_type,NewsType.TECH)

    def test_batch_warning_group_requires_matching_population_and_metric(self):
        from app.services.news_briefing import regulatory_population_key
        a=article('40','香港证监会点名17家公司','股权集中度最高99.53%。')
        b=article('41','17只港股被香港证监会点名','股权高度集中。十八名股东控制股份，合计达到99.53%。')
        c=article('42','香港证监会点名18家公司','股权集中度最高99.53%。')
        changed=article('43','香港证监会点名17家公司','股权集中度最高90.00%。')
        self.assertIsNotNone(regulatory_population_key(a))
        self.assertEqual(regulatory_population_key(a),regulatory_population_key(b))
        self.assertNotEqual(regulatory_population_key(a),regulatory_population_key(c))
        self.assertNotEqual(regulatory_population_key(a),regulatory_population_key(changed))

    def test_country_filter_accepts_financial_event_even_with_tech_label(self):
        from app.services.news_collector import NewsCollectorService
        collector=NewsCollectorService.__new__(NewsCollectorService)
        collector.china_keywords=[]
        event=article('50','海外科技公司季度财报发布','营业收入与现金流变动',kind=NewsType.TECH)
        self.assertEqual(collector.filter_china_related([event]),[event])
