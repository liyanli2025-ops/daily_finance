from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch,AsyncMock
import importlib.util
import json
import warnings
import zipfile

from app.models.news import News
from app.services.ai_analyzer import AIAnalyzerService
from app.services.editorial_value import profile
from app.services.media_sources import relation
from app.services.news_briefing import primary_rate_decision,topic,editorial_exclusion,associations
from app.services.news_selection import matches_watchlist
from app.services.watchlist_service import WatchlistStock

spec=importlib.util.spec_from_file_location('material_archive_audit',Path(__file__).resolve().parents[2]/'tools/audit_material_archive.py')
archive_audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(archive_audit)


def item(key,title,body='公开报道提供的经营变化和限定。'*30,source='界面新闻公开原文',url=None):
    return News(id=key,title=title,content=body,source=source,source_url=url or 'https://example.com/'+key,
        published_at=datetime(2026,10,29,6),importance_score=.9)


class ShortlistRegressions(unittest.TestCase):
    def test_primary_statement_is_promoted_through_real_selection_path(self):
        official=item('official','Federal Reserve issues FOMC statement',source='美联储公开原文',
            url='https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm')
        pool=[item(str(i),'企业'+str(i)+'收入增长'+str(i)+'亿元') for i in range(40)]+[official]
        analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
        with patch('app.services.ai_analyzer.get_watchlist_service',return_value=SimpleNamespace(get_all_stocks=lambda:[])),patch('app.services.research_hub.ResearchHub.load',return_value=[]),patch('requests.get',side_effect=AssertionError('no network')):
            analyzer._prepare_news_summary(pool)
        self.assertTrue(primary_rate_decision(official))
        self.assertIn('official',{row.id for row in analyzer._selected_evidence_news})
        self.assertLessEqual(len(analyzer._selected_evidence_news),28)
        spoof=official.model_copy(update=dict(source_url='https://example.com/monetary20261028a.htm'))
        self.assertFalse(primary_rate_decision(spoof))
        self.assertFalse(primary_rate_decision(official.model_copy(update=dict(title='FOMC meeting minutes'))))

    def test_routine_disclosure_and_real_price_change_are_not_same_priority(self):
        routine=item('routine','动态公司：H股公告（翌日披露报表）','期初期末结存及历史回购记录。'*50)
        price=item('price','AH股溢价率扩大至33%，动态公司溢价骤降过半')
        self.assertEqual(profile(routine)['kind'],'routine_disclosure')
        self.assertGreater(profile(price)['priority'],profile(routine)['priority'])

    def test_conference_publicity_is_excluded_but_industry_research_is_kept(self):
        promo=item('promo','AIAC 2026SMM铝产业年会圆满落幕！','铝产能增长20%，需求增加。'*50)
        self.assertEqual(editorial_exclusion(promo,[]),'conference_promotion_not_primary_story')
        research=item('research','硒、碲、铼供需格局及后市趋势展望【铜业年会】')
        self.assertIsNone(editorial_exclusion(research,[]))

    def test_related_link_footer_does_not_create_company_or_industry_match(self):
        stock=WatchlistStock('123456','动态养殖公司','A')
        body='铝行业供应变化及统计口径。\n相关阅读：\n动态养殖公司123456猪价与生猪供给\n其他报道'
        article=item('footer','铝行业研究',body);article.related_stocks=['123456']
        self.assertFalse(matches_watchlist(article,[stock]))
        self.assertEqual(relation(article.title,body,[stock],{'123456':['生猪','猪价']})[:2],([],{}))
        article.market_impact='行业关联 A:123456（匹配：猪价）'
        self.assertEqual(associations(article,[stock],{'A:123456':dict(business='生猪养殖')})[0]['level'],'keyword_only')
        self.assertIn('相关阅读',article.content)
        article.title='动态养殖公司披露新进展'
        self.assertTrue(matches_watchlist(article,[stock]))

    def test_quarterly_positioning_titles_share_topic_without_deleting_views(self):
        for title in ['明星基金经理三季报观察：调仓路径','基金季报2026Q3：科技降温','公募季度持仓变化']:
            self.assertEqual(topic(item('fund',title)),'公募季度持仓')


class RetiredUnusableAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_homepage_only_ths_adapter_cannot_fetch_or_fabricate_publication(self):
        from app.services.news_collector import NewsCollectorService
        collector=NewsCollectorService.__new__(NewsCollectorService)
        collector.client=SimpleNamespace(get=AsyncMock(side_effect=AssertionError('retired adapter')))
        self.assertEqual(await collector._collect_10jqka_news(),[])
        collector.client.get.assert_not_awaited()


class ArchiveAuditTests(unittest.TestCase):
    def test_future_snapshot_retains_real_ranking_and_association_fields(self):
        from app.radar_check import snapshot_article
        original=item('source','公开事实').model_copy(update=dict(importance_score=.93,related_stocks=['123456'],category='公司报道'))
        saved=snapshot_article(original)
        self.assertEqual(saved['importance_score'],.93)
        self.assertEqual(saved['related_stocks'],['123456'])
        self.assertEqual(saved['category'],'公司报道')
        self.assertEqual(saved['news_type'],original.news_type.value)
        self.assertEqual(saved['content'],original.content)

    def test_inspection_preserves_archive_and_does_not_extract_untrusted_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'sample.zip'
            data=dict(raw_articles=[dict(id='one',content='原文',url='https://example.com/a')],
                source_inventory=dict(source_rows=[dict(reading_scopes=dict(full_text=1))]),
                coverage=dict(per_stock={'A:123456':{}},sources={'x':dict(errors=[dict(error='RetiredSourceError')])}),
                selection=dict(articles=[dict(id='one',title='公开正文',selected=True,associations=[])]))
            with zipfile.ZipFile(path,'w') as archive:
                archive.writestr('news-acceptance.json',json.dumps(data))
                archive.writestr('../should-not-exist','untrusted')
            original=path.read_bytes()
            result=archive_audit.inspect_archive(path)
            self.assertEqual(path.read_bytes(),original)
            self.assertEqual(list(Path(folder).iterdir()),[path])
            self.assertEqual(result['selected_count'],1)
            self.assertEqual(result['source_diagnostic_entries'],{'explicit_paused':1})
            self.assertEqual(result['company_focus']['A:123456']['company_specific_candidates'],0)

    def test_ambiguous_duplicate_or_oversized_archives_are_rejected_before_reading(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'sample.zip'
            with warnings.catch_warnings():
                warnings.simplefilter('ignore',UserWarning)
                with zipfile.ZipFile(path,'w') as archive:
                    archive.writestr('news-acceptance.json','{}')
                    archive.writestr('news-acceptance.json','{}')
            with self.assertRaisesRegex(ValueError,'duplicate'):archive_audit.inspect_archive(path)
            with patch.object(archive_audit.zipfile.ZipFile,'infolist',return_value=[SimpleNamespace(filename='news-acceptance.json',file_size=51*1024*1024)]):
                with self.assertRaisesRegex(ValueError,'too_large'):archive_audit.inspect_archive(path)
