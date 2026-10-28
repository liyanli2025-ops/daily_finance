from datetime import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.models.news import News
from app.services.editorial_value import profile,statistical_event_key
from app.services.news_briefing import diverse_rank,editorial_exclusion
from app.services.ai_analyzer import AIAnalyzerService


def article(key,title,body='记者采访企业，订单减少20%，库存仍在增加。'*20,source='界面新闻公开原文'):
    return News(id=key,title=title,content=body,source=source,source_url='https://example.com/'+key,
        published_at=datetime(2026,10,28,10),importance_score=.7,market_impact='全市场事件入口')


class EditorialValueTests(unittest.TestCase):
    def test_specific_changes_outrank_generic_confidence_without_truth_claim(self):
        change=article('change','产业库存降至九个月新低')
        view=article('view','坚定看好A股中长期投资价值');view.importance_score=.99
        self.assertEqual(diverse_rank([view,change])[0].id,'change')
        self.assertEqual(profile(change)['kind'],'operating_or_market_change')
        self.assertIn('不证明',profile(change)['limitation'])

    def test_expected_growth_is_labeled_prediction(self):
        row=article('forecast','机构预计明年产量增长20%')
        self.assertEqual(profile(row)['kind'],'forecast_or_hypothesis')
        self.assertIn('不是已实现',profile(row)['reasons'][0])

    def test_same_statistical_fact_shares_slot_but_opposing_data_does_not(self):
        first=article('stat1','前9个月工业利润同比增长15.5%',body='国家统计局显示，全国前9个月工业企业利润同比增长15.5%，这是公布值。'*20)
        second=article('stat2','国家统计局：1—9月全国规上工业企业利润增长15.5%',body='全国规模以上工业企业实现利润总额6000亿元，同比增长15.5%，需要核对统计口径。'*20)
        opposite=article('stat3','前9个月工业利润同比下降15.5%',body='国家统计局另一版本，全国前9个月工业企业利润同比下降15.5%，与另一版本存在方向冲突。'*20)
        explanation=article('stat4','解读前9个月工业利润同比增长15.5%的背后',body='分析各行业对增长15.5%的贡献，不把数据变化直接推为股价方向。'*20)
        self.assertEqual(statistical_event_key(first),statistical_event_key(second))
        self.assertNotEqual(statistical_event_key(first),statistical_event_key(opposite))
        self.assertIsNone(statistical_event_key(explanation))
        analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
        with patch('app.services.ai_analyzer.get_watchlist_service',return_value=SimpleNamespace(get_all_stocks=lambda:[])),patch('app.services.research_hub.ResearchHub.load',return_value=[]):
            analyzer._prepare_news_summary([first,second,opposite,explanation])
        ids={row.id for row in analyzer._selected_evidence_news}
        self.assertEqual(len(ids&{'stat1','stat2'}),1)
        self.assertIn('stat3',ids)
        self.assertIn('stat4',ids)
        self.assertEqual(len(analyzer._news_briefing['statistical_event_supplements']),1)

    def test_regional_or_multiple_statistics_do_not_get_merged(self):
        regional=article('regional','某省前9个月工业利润同比增长15.5%',body='省级统计局公布当地工业企业利润同比增长15.5%。'*20)
        mixed=article('mixed','国家统计局：9月全国CPI同比上涨1.1%，PPI同比上涨1.1%')
        self.assertIsNone(statistical_event_key(regional))
        self.assertIsNone(statistical_event_key(mixed))

    def test_live_variant_and_wealth_profile_are_not_operating_events(self):
        for title in ['【直播中】全球铝行业论坛','身家1270亿元！某公司创始人成女首富']:
            self.assertIsNotNone(editorial_exclusion(article('feature',title),[]))
        self.assertIsNone(editorial_exclusion(article('buy','富豪榜创始人增持公司股权'),[]))

    def test_reading_completeness_remains_explicit_and_no_keyword_buys(self):
        full=article('full','行业调查','记者与采购方讨论公司经营与市场现状。'*20)
        feed=article('feed','库存下降20%且订单增长30%',source='36氪快讯');feed.importance_score=1
        self.assertEqual(diverse_rank([feed,full])[0].id,'full')
        self.assertNotIn('buy',profile(feed))

    def test_real_selection_limits_recap_flood_without_model_requests(self):
        recap=[article('recap'+str(i),'行业早报 '+str(i)) for i in range(20)]
        changes=[article('change'+str(i),'不同企业库存降至新低 '+str(i),body=('企业'+str(i)+'库存下降20%，同口径订单仍待验证。')*20) for i in range(4)]
        analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
        with patch('app.services.ai_analyzer.get_watchlist_service',return_value=SimpleNamespace(get_all_stocks=lambda:[])), \
                patch('app.services.research_hub.ResearchHub.load',return_value=[]), \
                patch.object(analyzer,'_call_ai',side_effect=AssertionError('no model requests')):
            analyzer._prepare_news_summary(recap+changes)
        chosen=analyzer._selected_evidence_news
        self.assertLessEqual(sum(profile(row)['kind']=='recap' for row in chosen),1)
        self.assertTrue(all(row in chosen for row in changes))
        self.assertLess(len(chosen),28)
        self.assertEqual(analyzer._news_briefing['selected_editorial_counts']['operating_or_market_change'],4)
