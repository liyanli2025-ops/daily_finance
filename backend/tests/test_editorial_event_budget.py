from datetime import datetime,timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from app.models.news import News
from app.services.news_quality import excluded_reason
from app.services.news_briefing import company_reporting_event,editorial_exclusion
from app.services.watchlist_service import WatchlistStock
from app.services.ai_analyzer import AIAnalyzerService

NOW=datetime(2026,10,30,17)
STOCK=WatchlistStock('123456','新农股份','A')

def article(key,title,body='',source='财联社公开原文'):
    return News(id=key,title=title,content=title+'。'+body+'可供阅读的原始文本。'*25,
                source=source,source_url='https://www.cls.cn/detail/'+key,
                published_at=NOW-timedelta(minutes=int(key)),importance_score=.8)

class EditorialEventBudgetTests(unittest.TestCase):
    def test_ai_disclosure_is_not_confused_with_reporting_about_ai(self):
        generated=article('1','某公司三季报',body='收入增长。')
        generated.content+='\n本文由AI生成，不构成投资建议。'
        self.assertEqual(excluded_reason(generated),'disclosed_ai_generated_article')
        normal=article('2','公司AI业务变化','公司介绍AI生成产品。记者采访了客户。')
        self.assertIsNone(excluded_reason(normal))
        assisted=article('3','公司财报','记者核验。')
        assisted.content+='\n本文由AI辅助编辑，记者核实。'
        self.assertIsNone(excluded_reason(assisted))

    def test_group_requires_explicit_period_and_checks_company_alias(self):
        formal=article('4','新农股份：2026年第三季度报告')
        shortened=article('5','新农前三季度亏损','新农股份披露2026年第三季度报告。')
        unknown=article('6','新农股份三季度报告')
        other=article('7','新农股份：2025年第三季度报告')
        self.assertEqual(company_reporting_event(formal,[STOCK]),company_reporting_event(shortened,[STOCK]))
        self.assertIsNone(company_reporting_event(unknown,[STOCK]))
        correction=article('13','新农股份2026年第三季度报告更正')
        self.assertIsNone(company_reporting_event(correction,[STOCK]))
        self.assertNotEqual(company_reporting_event(formal,[STOCK]),company_reporting_event(other,[STOCK]))

    def test_financial_event_has_two_initial_sources_and_retains_other_ids(self):
        rows=[article('8','新农股份：2026年第三季度报告'),
              article('9','新农前三季度亏损','新农股份披露2026年第三季度报告，补充经营信息。'),
              article('10','新农股份前三季度亏损','2026年第三季度报告。')]
        analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
        with patch('app.services.ai_analyzer.get_watchlist_service',return_value=SimpleNamespace(get_all_stocks=lambda:[STOCK])),patch('app.services.research_hub.ResearchHub.load',return_value=[]):
            text=analyzer._prepare_news_summary(rows)
        self.assertEqual(len(analyzer._selected_evidence_news),2)
        group=analyzer._news_briefing['company_reporting_events'][0]
        self.assertEqual(set(group['related_ids']),{'8','9','10'})
        self.assertIn('共用一个分析问题',text)

    def test_private_consumer_funding_stays_searchable_but_not_initial_story(self):
        row=article('11','消费品牌在降温期拿到热钱','冰淇淋连锁品牌宣布首轮融资。')
        self.assertEqual(editorial_exclusion(row,[]),'private_consumer_funding_without_watchlist_link')
        watched=WatchlistStock('654321','消费品牌','A')
        self.assertIsNone(editorial_exclusion(row,[watched]))
        deal=article('12','上市公司收购消费品牌获得融资','餐饮行业。')
        self.assertIsNone(editorial_exclusion(deal,[]))
