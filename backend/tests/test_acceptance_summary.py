import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock,patch

from app.radar_check import summarize_saved
from app.services.news_collector import NewsCollectorService


class SavedSummaryTests(unittest.TestCase):
    def test_summary_omits_bodies_and_does_not_fetch(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'news-acceptance.json').write_text(json.dumps(dict(collected_at='2026-10-25T16:01:59',
                raw_articles=[dict(content='not printed '*10000)],news_input='not printed '*10000,
                source_inventory=dict(source_rows=[dict(source='test',window_texts=30,title_only=30,
                    median_characters=0,feed_status=dict(status='disabled',reason='no_body'))]),
                selection=dict(articles=[dict(selected=True,title='实际标题')]),coverage=dict(sources={}),
                collection_funnel=dict(retrieved=189,after_dedup=137))))
            (root/'technical.json').write_text(json.dumps(dict(coverage=dict(requested=2,verified=1),instruments=[
                dict(symbol='good',status='ok',bars=['not printed']*10000),
                dict(symbol='missing',status='failed',reason='series_missing')])))
            with patch.object(NewsCollectorService,'collect_all',side_effect=AssertionError('no fetch')):
                result=summarize_saved(root)
            text=json.dumps(result)
            self.assertNotIn('not printed',text)
            self.assertEqual(result['selected_count'],1)
            self.assertEqual(result['technical']['gaps'][0]['symbol'],'missing')
            self.assertLess(len(text),2500)


class RetiredSupplementTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_empty_untraceable_adapters_never_call_provider(self):
        em=Mock(side_effect=AssertionError('retired'));cctv=Mock(side_effect=AssertionError('retired'))
        collector=NewsCollectorService.__new__(NewsCollectorService)
        with patch.dict('sys.modules',{'akshare':SimpleNamespace(stock_info_global_em=em,news_cctv=cctv)}):
            self.assertEqual(await collector._collect_akshare_news(),[])
        em.assert_not_called();cctv.assert_not_called()
        self.assertEqual(collector._supplement_coverage['东方财富']['status'],'disabled')
