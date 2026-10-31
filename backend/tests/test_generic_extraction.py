from datetime import datetime
import importlib.util
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from app.services.generic_extraction import extract_main_text,reader_kind
from app.services.web_research import parse_visible_article
from app.services.evidence import publication_label
from app.services.news_quality import reading_scope

NOW=datetime(2026,10,31,16)
URL='https://publisher.example/news/123'
TEXT='经营变化、现金流与风险解释需要分开核查，正文后部也有重要反方信息。'*12


class GenericTests(unittest.TestCase):
    def fake_library(self):return patch.dict('sys.modules',{'trafilatura':SimpleNamespace(extract=Mock(return_value=TEXT))})

    def test_hidden_scripts_and_comments_not_sent_as_article_body(self):
        with self.fake_library() as modules,patch('app.services.generic_extraction.importlib.metadata.version',return_value='2.3.1'):
            html='<div hidden>hidden-secret</div><script>script-secret</script><div style="display:none"><span style="color:red">nested-secret</span></div><p>'+TEXT+'</p>'
            result=extract_main_text(html,URL)
            from trafilatura import extract
            sent=extract.call_args.args[0]
            for value in ('hidden-secret','script-secret','nested-secret'):self.assertNotIn(value,sent)
            self.assertFalse(extract.call_args.kwargs['with_metadata'])
            self.assertFalse(extract.call_args.kwargs['include_comments'])
            self.assertTrue(extract.call_args.kwargs['include_tables'])
            self.assertFalse(result['publication_date_inferred'])

    def test_paywall_and_verification_page_rejected_before_extraction(self):
        with self.fake_library():
            from trafilatura import extract
            for html in ('<script type="application/ld+json">{"isAccessibleForFree":false}</script><p>'+TEXT+'</p>',
                         '<title>Verify you are human</title><p>'+TEXT+'</p>'):
                self.assertEqual(extract_main_text(html,URL)['status'],'rejected')
            extract.assert_not_called()

    def test_missing_optional_library_is_explicit(self):
        with patch.dict('sys.modules',{'trafilatura':None}):
            self.assertEqual(extract_main_text('<p>text</p>',URL)['reason'],'generic_extractor_not_installed')
            with self.assertRaisesRegex(ValueError,'web_source_generic_extractor_unavailable'):
                parse_visible_article('<h1>具体经营变化与风险</h1><div>'+TEXT+'</div>',URL,NOW)

    def test_generic_text_still_requires_explicit_publication_metadata(self):
        with patch('app.services.generic_extraction.extract_main_text',return_value=dict(status='text_candidate',text=TEXT,method='fixture',version='1',warnings=[])):
            with self.assertRaisesRegex(ValueError,'time_missing'):
                parse_visible_article('<h1>具体经营变化与风险</h1><div>'+TEXT+'</div>',URL,NOW)
            html='<meta property="article:published_time" content="2026-10-30T08:00:00+08:00"><h1>具体经营变化与风险</h1><div>'+TEXT+'</div>'
            item=parse_visible_article(html,URL,NOW)
            self.assertEqual(item.content,TEXT);self.assertIn('正文算法：fixture',item.market_impact)

    def test_publisher_free_access_guard_not_bypassed_by_generic_library(self):
        state=dict(props=dict(pageProps=dict(articleDetail=dict(id=123,isFree=False,title='受限文章',content=TEXT,ctime=1793400000))))
        with patch('app.services.generic_extraction.extract_main_text') as extract:
            with self.assertRaisesRegex(ValueError,'free_access_rejected'):
                parse_visible_article('<script id="__NEXT_DATA__" type="application/json">'+json.dumps(state)+'</script>',
                                      'https://www.cls.cn/detail/123',NOW)
        extract.assert_not_called()

    def test_naive_clock_only_retains_day_and_boundary_is_not_silently_admitted(self):
        def html(date):return '<meta property="article:published_time" content="'+date+'"><h1>日期范围与经营观察</h1><article>'+TEXT+'</article>'
        item=parse_visible_article(html('2026-10-30T09:30'),URL,NOW)
        self.assertIn('来源未标时区',publication_label(item));self.assertIn('日精度',publication_label(item))
        with self.assertRaisesRegex(ValueError,'day_window_boundary'):
            parse_visible_article(html('2026-10-28T09:30'),URL,NOW)

    def test_modified_date_not_relabelled_as_published(self):
        html='<h1>日期范围与经营观察</h1><article>'+TEXT+'</article><script type="application/ld+json">'+json.dumps(dict(
            **{'@type':'NewsArticle'},headline='日期范围与经营观察',dateModified='2026-10-31T09:30:00+08:00'))+'</script>'
        with self.assertRaisesRegex(ValueError,'time_missing'):parse_visible_article(html,URL,NOW)

    def test_short_real_item_keeps_wire_scope_without_padding(self):
        body='消息人士称，双方正讨论一项交易，交易尚未确认，条款和时点仍可能变化。'*3
        html='<meta property="article:published_time" content="2026-10-31T09:30:00+08:00"><h1>公司交易讨论仍待确认</h1><article>'+body+'<p>海量资讯、精准解读，尽在新浪财经APP</p></article>'
        item=parse_visible_article(html,URL,NOW)
        self.assertEqual(reading_scope(item),'wire_text');self.assertNotIn('海量资讯',item.content)

    def test_discussion_and_research_keep_specialized_reader_boundary(self):
        self.assertEqual(reader_kind('https://www.jisilu.cn/question/123'),'discussion')
        self.assertEqual(reader_kind('https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/rptid/123/index.phtml'),'research_summary')


@unittest.skipUnless(importlib.util.find_spec('trafilatura') is not None,'optional extractor corpus environment only')
class RealExtractorTests(unittest.TestCase):
    def test_unknown_container_main_text_and_final_paragraph_survive(self):
        html='<title>行业经营变化与风险</title><nav>'+''.join('<a href="/x">导航菜单</a>' for _ in range(100))+'</nav><div><h1>行业经营变化与风险</h1>'
        html+=''.join('<p>'+TEXT+str(i)+'</p>' for i in range(3))+'<p>最后一段的重要反证：数据口径变化，不能直接外推需求。</p></div><div hidden>hidden-secret</div>'
        result=extract_main_text(html,URL)
        self.assertEqual(result['status'],'text_candidate')
        self.assertIn('最后一段的重要反证',result['text']);self.assertNotIn('hidden-secret',result['text'])
        self.assertNotIn('导航菜单',result['text'])
