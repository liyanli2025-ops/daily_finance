from datetime import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from unittest.mock import AsyncMock
import json
from pathlib import Path
import tempfile

from app.models.news import News, NewsType
from app.services.ai_analyzer import AIAnalyzerService
from app.services.news_collector import NewsCollectorService
from app.services.news_quality import excluded_reason
from app.services.evidence_audit import audit, copy_reason
from app.services.watchlist_service import WatchlistStock


def article(key,title='公开经营信息',body=None,source='证券时报原文',url=None):
    return News(id=key,title=title,content=body or (title+'：公开披露了本期业务数据及统计范围。')*12,
        source=source,source_url=url or 'https://example.com/articles/'+key,
        published_at=datetime(2026,10,25,12))


class EvidenceAuditTests(unittest.TestCase):
    def test_title_only_is_not_a_short_original_and_long_rss_is_not_full_text(self):
        headline=article('title',body='公开经营信息')
        self.assertEqual(excluded_reason(headline),'title_only')
        notice=article('notice',body='央行公告：今日七天期逆回购操作量为零。')
        long_feed=article('feed',body='RSS提供的采集文本，不代表读取原始页面。'*200,source='华尔街见闻-全球')
        self.assertIsNone(excluded_reason(notice))
        result=audit([headline,notice,long_feed],[notice,long_feed],[],{})
        self.assertEqual(result['reading_scopes'],{'full_text':1,'feed_excerpt':1})
        self.assertEqual(result['short_originals'],1)
        self.assertEqual(result['admission_exclusions'],{'title_only':1})
        self.assertEqual(result['status'],'requires_editorial_assessment')

    def test_changed_headline_copies_removed_but_changed_numbers_and_negation_retained(self):
        first=article('first','经营情况更新',body='公司公告收入上升10%，口径为本季度。'*12)
        copy=article('copy','某媒体解读经营情况',body=first.content)
        update=article('update','经营情况更新',body='公司公告收入下降10%，口径为本季度。'*12)
        self.assertEqual(copy_reason(first,copy),'same_body')
        self.assertIsNone(copy_reason(first,update))
        collector=NewsCollectorService.__new__(NewsCollectorService)
        with patch('app.services.news_collector.get_watchlist_service',return_value=SimpleNamespace(get_all_stocks=lambda:[])):
            selected=collector._deduplicate([first,copy,update])
        self.assertEqual({item.id for item in selected},{'first','update'})

    def test_current_company_coverage_separates_mentions_from_specific_originals(self):
        stocks=[WatchlistStock('123456','动态新增公司','A'),WatchlistStock('234567','另一公司','HK')]
        recap=article('recap','市场综述',body=('市场综述正文，动态新增公司也被顺带提及。')*15)
        company=article('company','动态新增公司披露经营变动')
        result=audit([recap,company],[recap,company],stocks,{})
        row=result['per_stock'][0]
        self.assertEqual(row['company_original_ids'],['company'])
        self.assertEqual(row['mention_only_ids'],['recap'])
        self.assertTrue(result['per_stock'][1]['gaps'])
        self.assertEqual(result['per_stock'][1]['stock'],'HK:234567')

    def test_selected_material_checks_and_cross_border_path_share_reading_boundaries(self):
        first=article('first','海外事件最新变化')
        copy=article('copy','改标题转载',body=first.content)
        update=article('update','海外事件最新变化',body='新披露明确否认订单取消，观察范围为本季度。'*12)
        title=article('title',body='公开经营信息')
        analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
        with patch('app.services.ai_analyzer.get_watchlist_service',return_value=SimpleNamespace(get_all_stocks=lambda:[])), \
                patch('app.services.research_hub.ResearchHub.load',return_value=[]):
            text=analyzer._prepare_news_summary([first,copy,update,title])
        self.assertEqual({row.id for row in analyzer._selected_evidence_news},{'first','update'})
        self.assertIn('实际入模资料覆盖检查',text)
        self.assertEqual(analyzer._evidence_audit['admission_exclusions'],{'title_only':1})
        self.assertNotIn('情感判断',text)
        copy.news_type=NewsType.GEOPOLITICAL
        feed=article('feed','另一海外事件',source='百度国际新闻');feed.news_type=NewsType.GEOPOLITICAL
        cross=analyzer._prepare_cross_border_summary([copy,feed,title])
        self.assertNotIn('[N:copy]',cross)
        self.assertNotIn('[N:title]',cross)
        self.assertIn('未核验完整正文',cross)

    def test_short_real_rss_text_is_preserved_instead_of_replaced_by_headline(self):
        collector=NewsCollectorService.__new__(NewsCollectorService)
        collector._calculate_importance=lambda *args:.5
        collector._extract_keywords=lambda *args:[]
        collector._extract_stock_codes=lambda *args:[]
        entry=SimpleNamespace(content=[SimpleNamespace(value='操作量为零，另有隔夜操作。')])
        fields=dict(title='央行公开市场操作',link='https://example.com/notice',
                    published_parsed=(2026,10,25,1,0,0,0,0,0))
        entry.get=lambda key,default=None:fields.get(key,default)
        row=collector._parse_rss_entry(entry,dict(name='金十数据',news_type='finance'))
        self.assertEqual(row.content,'操作量为零，另有隔夜操作。')


class SavedSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def test_saved_snapshot_uses_complete_text_and_current_app_without_collection(self):
        from app.evidence_check import inspect
        original=article('one','动态新增公司披露经营变化')
        snapshot=dict(full_collection=True,collected_at='2026-10-25T12:00:00',
            raw_articles=[dict(id=original.id,title=original.title,content=original.content,
                source=original.source,url=original.source_url,published=original.published_at.isoformat())],
            selection=dict(articles=[dict(id='one',selected=True)]))
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'snapshot.json'
            path.write_text(json.dumps(snapshot),encoding='utf-8')
            with patch('app.evidence_check.read_app_watchlist',AsyncMock(return_value=[
                    dict(code='123456',name='动态新增公司',market='A')])), \
                    patch('app.evidence_check.ResearchHub.load',return_value=[]):
                result=await inspect(path)
            self.assertEqual(result['per_stock'][0]['company_original_ids'],['one'])
            self.assertEqual(result['articles'][0]['supplied_characters'],len(original.content))
            snapshot['full_collection']=False
            path.write_text(json.dumps(snapshot),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'正文预览'):
                await inspect(path)
