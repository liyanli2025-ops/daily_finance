from datetime import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.models.news import News
from app.services.ai_analyzer import AIAnalyzerService
from app.services.news_collector import NewsCollectorService
from app.services.news_quality import excluded_reason,reading_scope,company_focus
from app.services.watchlist_service import WatchlistStock

NOW=datetime(2026,10,25,12)


def article(identifier,title='同一事件的新变化',source='原始媒体',url=None,score=.8):
    return News(id=identifier,title=title,source=source,content=title+'。'+'带来源的正文材料。'*50,
        source_url=url or 'https://example.com/articles/'+identifier,published_at=NOW,importance_score=score)


class EvidenceQualityTests(unittest.TestCase):
    def test_full_body_displaces_same_title_higher_scoring_rss(self):
        rss=article('rss',source='华尔街见闻-全球',score=1)
        full=article('media-original',source='华尔街见闻原文',score=.74)
        collector=NewsCollectorService.__new__(NewsCollectorService)
        with patch('app.services.news_collector.get_watchlist_service',return_value=SimpleNamespace(get_all_stocks=lambda:[])):
            result=collector._deduplicate([rss,full])
        self.assertEqual([row.id for row in result],['media-original'])

    def test_member_paths_and_automated_market_articles_are_not_admitted(self):
        for row in [article('paid',url='https://wallstreetcn.com/member/articles/3784228'),
                    article('bot',source='新浪财经-自动生成快讯'),
                    article('botpath',url='https://finance.sina.com.cn/stock/aiassist/lr/2026-10-24/a.shtml')]:
            self.assertIsNotNone(excluded_reason(row))

    def test_mentions_in_market_recap_do_not_get_company_focus(self):
        stock=WatchlistStock('123456','任意新公司','A')
        recap=article('recap','全市场发生变化');recap.content+='任意新公司也在综述中出现。'
        self.assertFalse(company_focus(recap,stock))
        self.assertTrue(company_focus(article('issuer','任意新公司公告订单变更'),stock))

    def test_substantive_financing_analysis_is_not_filtered_just_for_the_topic(self):
        row=article('analysis','融资余额变化如何影响市场结构',source='证券时报原文')
        self.assertIsNone(excluded_reason(row))

    def test_actual_selection_bounds_research_and_excerpts_and_rejects_bots_even_for_watchlist(self):
        stock=WatchlistStock('123456','任意新公司','A')
        research=[article('research'+str(i),title='策略研究'+chr(0x4e00+i)*4,source='东方财富研报',score=1) for i in range(12)]
        research[0].title='任意新公司经营研究'
        feeds=[article('feed'+str(i),title='市场变化'+chr(0x4e60+i)*4,source='百度财经焦点',score=1) for i in range(12)]
        bot=article('bot','任意新公司获融资买入1000万元',source='新浪财经-自动生成快讯',score=1)
        paid=article('paid','新政策变化',url='https://wallstreetcn.com/member/articles/3784228',score=1)
        full=article('full','任意新公司发布原始公告',source='新浪财经-逐股新闻',score=.7)
        analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
        with patch('app.services.ai_analyzer.get_watchlist_service',return_value=SimpleNamespace(get_all_stocks=lambda:[stock])), \
                patch('app.services.research_hub.ResearchHub.load',return_value=[]):
            summary=analyzer._prepare_news_summary(research+feeds+[bot,paid,full])
        selected=analyzer._selected_evidence_news;ids={row.id for row in selected}
        self.assertIn('full',ids);self.assertNotIn('bot',ids);self.assertNotIn('paid',ids)
        self.assertLessEqual(sum(reading_scope(row)=='research_excerpt' for row in selected),2)
        self.assertLessEqual(sum(reading_scope(row)=='feed_excerpt' for row in selected),6)
        self.assertEqual(selected[0].id,'full')
        self.assertIn('未核验完整PDF',summary)
        self.assertNotIn('research1',ids)
        self.assertEqual(analyzer._news_quality_exclusions['restricted_article'],1)

    def test_cross_border_path_cannot_reintroduce_a_restricted_article(self):
        analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
        self.assertEqual(analyzer._prepare_cross_border_summary([
            article('paid',url='https://wallstreetcn.com/member/articles/3784228')]),'')
