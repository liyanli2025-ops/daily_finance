from datetime import datetime
from types import SimpleNamespace
import unittest
from app.models.news import News
from app.services.news_assignment import assess,order,audit
from app.services.watchlist_service import WatchlistStock

def article(key,title,body='记者采访供应链并核对披露口径。'):
    return News(id=key,title=title,content=body*25,source='财联社公开原文',
                source_url='https://www.cls.cn/detail/'+key,published_at=datetime(2026,10,31,9),importance_score=.8)

class NewsAssignmentTests(unittest.TestCase):
    def test_market_questions_outrank_ordinary_watched_company(self):
        stock=WatchlistStock('123456','测试股份','A')
        ordinary=article('company','测试股份发布股东大会通知')
        industry=article('industry','全球芯片厂商下调资本开支，订单交期缩短')
        policy=article('policy','出口管制新规扩大先进计算芯片范围')
        ranked=order([ordinary,industry,policy],[stock])
        self.assertEqual(ranked[-1].id,'company')
        self.assertEqual({row.id for row in ranked},{'company','industry','policy'})

    def test_one_industry_does_not_consume_other_research_lanes(self):
        industry=[article(str(i),'全球芯片厂商下调资本开支，订单减少'+str(i)) for i in range(10)]
        policy=article('policy','出口管制新规扩大范围')
        self.assertIn(policy,order(industry+[policy])[:2])

    def test_negative_news_is_a_lead_not_a_verified_public_controversy(self):
        result=assess(article('risk','某非自选公司涉嫌财务造假被立案调查'))
        self.assertEqual(result['lane'],'major_risk')
        self.assertEqual(result['status'],'reading_lead_not_verified_importance')
        self.assertIn('尚未证明',result['reason'])

    def test_us_mention_in_domestic_earnings_does_not_certify_overseas_subject(self):
        row=article('mixed','某公司发布三季报','美股市场回暖。公司披露财报利润增长。')
        self.assertEqual(assess(row)['lane'],'other')

    def test_new_watchlist_changes_assignments_without_a_ticker_table(self):
        row=article('new','新公司宣布重要业务调整')
        self.assertEqual(assess(row)['lane'],'other')
        self.assertEqual(assess(row,[WatchlistStock('654321','新公司','A')])['lane'],'watchlist')

    def test_headline_only_can_be_scheduled_without_becoming_read(self):
        row=SimpleNamespace(id='headline',title='全球芯片供应中断，订单交期拉长',content='',source='',category='',related_stocks=[])
        result=audit([row],[])
        self.assertFalse(result['articles'][0]['body_provided'])
        self.assertEqual(result['lanes']['industry_operating']['unread_ids'],['headline'])
        self.assertIn('不是全网',result['limitation'])

    def test_receipt_counts_only_actual_ranges_not_headlines(self):
        rows=[article('a','出口管制新规扩大范围'),article('b','央行发布利率决议')]
        result=audit(rows,[dict(id='a',selected_characters=120)])
        self.assertEqual(result['lanes']['macro_policy']['provided'],1)
        self.assertEqual(result['lanes']['macro_policy']['unread_ids'],['b'])
        self.assertEqual(result['articles'][0]['provided_characters'],120)

    def test_a_year_is_not_an_operating_change(self):
        row=article('date','全球芯片产能布局专题','2026年10月31日。记者介绍这一专题。')
        self.assertEqual(assess(row)['reading_priority'],1)

    def test_future_industry_view_is_not_a_confirmed_current_change(self):
        row=article('view','机构看好全球芯片需求增长10%')
        self.assertEqual(assess(row)['reading_priority'],2)
        self.assertIn('观点',assess(row)['reason'])

    def test_vague_industrial_plan_is_not_promoted_by_body_growth_rhetoric(self):
        row=article('plan','强化源头技术供给，构筑产业发展新优势','规划提出未来增长目标，积极增加产业投入。')
        self.assertEqual(assess(row)['reading_priority'],1)

    def test_company_earnings_wording_does_not_escape_scope_screen(self):
        from app.services.company_news_scope import decision
        row=article('routine','工业AI时代来了？某公司利润增近三倍，新签AI订单增两倍')
        row.content='记者采访当事公司，未提供该股行业地位证据。'
        self.assertFalse(decision(row)['keep'])
        row.content='该公司自称深耕全球供应链。'
        self.assertTrue(decision(row)['keep'])  # Still inspectable, not verified leadership.
        self.assertEqual(assess(row)['reading_priority'],1)

    def test_discovery_download_priority_does_not_default_to_watched_ticker(self):
        from app.services.public_news_sources import discover_html
        stock=WatchlistStock('123456','测试股份','A')
        html='<a href="https://www.yicai.com/news/102000001.html">测试股份发布股东大会通知</a>'
        html+='<a href="https://www.yicai.com/news/102000002.html">A股收评：创业板放量下跌，行业表现分化</a>'
        rows=discover_html('yicai',html,[stock],{})
        self.assertEqual(len(rows),2)
        self.assertIn('A股收评',rows[0]['title'])
        self.assertEqual(rows[0]['assignment']['status'],'reading_lead_not_verified_importance')

    def test_short_name_needs_body_confirmation_and_cannot_match_a_different_company(self):
        from app.services.news_quality import company_focus
        from app.services.company_news_scope import decision
        stock=WatchlistStock('123456','新农股份','A')
        probe=article('alias','新农前三季度亏损','')
        probe.content=''
        self.assertTrue(decision(probe,[stock])['keep'])
        self.assertFalse(company_focus(probe,stock))
        probe.content='新农股份公布三季度经营情况。'
        self.assertTrue(company_focus(probe,stock))
        other=article('other','新农控股前三季度亏损','新农股份是其同业公司。')
        self.assertFalse(company_focus(other,stock))

    def test_editorially_excluded_catalogue_entry_keeps_its_individual_reason(self):
        from unittest.mock import patch
        from app.services.ai_analyzer import AIAnalyzerService
        feature=article('fund','消费品牌在降温期拿到热钱','冰淇淋连锁品牌宣布首轮融资。')
        market=article('close','A股收评：交易表现分化')
        analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
        with patch('app.services.ai_analyzer.get_watchlist_service',return_value=SimpleNamespace(get_all_stocks=lambda:[])),patch(
                'app.services.research_hub.ResearchHub.load',return_value=[]):
            analyzer._prepare_news_summary([feature,market])
        decisions={row['id']:row for row in analyzer._news_briefing['initial_reading_decisions']}
        self.assertEqual(len(decisions),2)
        self.assertFalse(decisions['fund']['provided'])
        self.assertIn('editorial_exclusion:private_consumer_funding',decisions['fund']['reason'])
        self.assertTrue(decisions['close']['provided'])
