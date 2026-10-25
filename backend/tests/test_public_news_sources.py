from datetime import datetime,timedelta
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from app.services.public_news_sources import PublicNewsCollector,parse_article,discover,permitted,SOURCES
from app.services.watchlist_service import WatchlistStock
from app.services.news_quality import reading_scope

NOW=datetime(2026,10,25,17)
BODY='原文披露行业新增产能，须区分计划与实际投产，不代表任何公司已经取得订单。'*12


def cls_html(identifier='123',free=True,body=BODY,stamp=1792896886):
    return '<script id="__NEXT_DATA__" type="application/json">'+json.dumps(dict(props=dict(pageProps=dict(
        articleDetail=dict(id=identifier,isFree=free,title='材料行业新增产能',ctime=stamp,content='<p>'+body+'</p>')))))+'</script>'


class DirectParserTests(unittest.TestCase):
    def test_cls_requires_explicit_free_flag_and_same_identity(self):
        url='https://www.cls.cn/detail/123'
        row=parse_article('cls',cls_html(),url)
        self.assertIn('新增产能',row['body'])
        for html in [cls_html(free=False),cls_html(identifier='456'),cls_html(body='摘要')]:
            with self.assertRaises(ValueError):parse_article('cls',html,url)

    def test_cnstock_reads_public_text_and_preserves_reprint_attribution(self):
        data=dict(contId='123',title='金融政策公开征求意见',pubTime='2026-10-25 11:00',source='原始通讯社',
            textInfo=dict(content='<p>'+BODY+'</p>'))
        html=lambda:'<script id="__NEXT_DATA__">'+json.dumps(dict(props=dict(pageProps=dict(data=data))))+'</script>'
        row=parse_article('cnstock',html(),'https://www.cnstock.com/commonDetail/123')
        self.assertEqual(row['upstream'],'原始通讯社');self.assertEqual(row['date_precision'],'minute')
        data['isPay']=True
        with self.assertRaises(ValueError):parse_article('cnstock',html(),'https://www.cnstock.com/commonDetail/123')

    def test_dom_parsers_keep_body_and_source_date_not_related_articles(self):
        cases={
            'yicai':('https://www.yicai.com/news/123.html','<h1>公司事件</h1><div class="m-text"><p class="f-cb">第一财经 2026-10-25 12:00:00</p><div id="multi-text">'+BODY+'</div></div>'),
            '21jingji':('https://m.21jingji.com/article/20261025/herald/abc.html','<h1>行业事件</h1><div class="newsDate">2026-10-25 12:00</div><div class="main_content">'+BODY+'</div>'),
            'cs':('https://www.cs.com.cn/ssgs/01/2026/10/25/detail_123.html','<article class="cont_article"><header><h1 id="title">公司事件</h1><div class="artc_info"><time>2026-10-25 12:00</time></div></header><p>'+BODY+'</p><aside>其他相关文章</aside></article>'),
            'nbd':('https://www.nbd.com.cn/articles/2026-10-25/123.html','<div class="g-article"><h1>行业事件</h1><p class="u-time"><span class="time">2026-10-25 12:00:00</span></p><div class="g-articl-text">'+BODY+'如需转载请联系报社</div></div>'),
            'ndrc':('https://www.ndrc.gov.cn/xwdt/xwfb/202610/t20261025_123.html','<meta name="ArticleTitle" content="公开政策"><meta name="PubDate" content="2026-10-25 12:00:00"><div class="article_con"><div class="TRS_Editor">'+BODY+'</div></div>'),
            'sse':('https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20261025_123.shtml','<div class="article-infor"><h2>交易规则</h2><div class="article_opt"><i>2026-10-25</i></div><div class="allZoom">'+BODY+'</div></div>')}
        for key,(url,html) in cases.items():
            with self.subTest(key=key):
                row=parse_article(key,html+'<aside>2026-12-30 未来相关文章</aside>',url)
                self.assertTrue(row['published'].startswith('2026-10-25'))
                self.assertNotIn('相关文章',row['body'])
                self.assertNotIn('转载请联系',row['body'])

    def test_missing_date_and_paywall_never_become_collected_text(self):
        base='<h1>事件</h1><div class="newsDate">日期未知</div><div class="main_content">'+BODY+'</div>'
        url='https://m.21jingji.com/article/20261025/herald/abc.html'
        with self.assertRaises(ValueError):parse_article('21jingji',base,url)
        with self.assertRaises(ValueError):parse_article('21jingji',base.replace('日期未知','2026-10-25 12:00').replace(BODY,BODY+'付费阅读全文'),url)

    def test_21_columnist_header_time_is_valid_but_body_dates_cannot_replace_it(self):
        url='https://m.21jingji.com/article/20261025/herald/abc.html'
        html='<h1>机构观点</h1><div class="titleHead"><div class="author-infos"><span>作者 2026-10-25 14:14</span></div></div><div class="main_content">'+BODY+'2026-10-26 明天的观察条件</div>'
        row=parse_article('21jingji',html,url)
        self.assertEqual(row['published'],'2026-10-25T14:14:00')

    def test_newer_url_is_read_first_but_still_requires_source_date(self):
        html='<a href="/articles/2025-01-01/1.html">公司重要新闻事件变化</a><a href="/articles/2026-10-25/2.html">公司重要新闻事件变化</a>'
        rows=discover('nbd',html,[],{})
        self.assertTrue(rows[0]['url'].endswith('/2.html'))

    def test_publisher_interleaving_does_not_demote_full_text_below_feeds(self):
        from app.models.news import News
        from app.services.news_briefing import diverse_rank
        rows=[]
        for i in range(5):
            rows.append(News(id=str(i),title='公开正文'+str(i),content=BODY,source='财联社公开原文',
                source_url='https://www.cls.cn/detail/'+str(i),published_at=NOW,importance_score=.9))
        alternate=rows[0].model_copy(update=dict(id='alt',source='中证网公开原文',source_url='https://www.cs.com.cn/ssgs/alt.html',importance_score=.7))
        feed=rows[0].model_copy(update=dict(id='feed',source='信报财经新闻',source_url='https://www2.hkej.com/article/1',importance_score=1))
        result=diverse_rank(rows+[alternate,feed])
        self.assertEqual(result[1].id,'alt');self.assertEqual(result[-1].id,'feed')

    def test_discovery_is_dynamic_and_does_not_follow_external_or_paid_api(self):
        stocks=[WatchlistStock('123456','新加入公司','A')]
        html='<a href="/detail/1">新加入公司发布重要变化</a><a href="/detail/2">周末体育比赛结果</a>' \
             '<a href="https://127.0.0.1/detail/3">新加入公司发布重要变化</a>'
        rows=discover('cls',html,stocks,{'123456':[]})
        self.assertEqual([row['url'] for row in rows],['https://www.cls.cn/detail/1'])
        for url in ['http://www.cls.cn/detail/1','https://www.cls.cn/detail/1?token=secret','https://user:pass@www.cls.cn/detail/1']:
            self.assertFalse(permitted('cls',url))


class DirectCollectionTests(unittest.TestCase):
    def test_all_candidates_can_be_read_and_old_future_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            collector=PublicNewsCollector(folder)
            html=''.join('<a href="/detail/'+str(i)+'">材料行业新增产能变化'+str(i)+'</a>' for i in range(32))
            def detail(key,url,deadline):
                i=int(url.rsplit('/',1)[-1]);stamp=NOW-timedelta(hours=2)
                if i==30:stamp=NOW-timedelta(days=8)
                if i==31:stamp=NOW+timedelta(days=1)
                return dict(title='材料行业新增产能',body=BODY,published=stamp.isoformat(),date_precision='minute',
                    url=url,source=SOURCES[key]['name'],reading='公开正文',upstream='其他通讯社')
            with patch.object(collector,'index',return_value=html),patch.object(collector,'detail',side_effect=detail), \
                    patch('app.services.public_news_sources.china_now',return_value=NOW):
                articles,status=collector.collect([],{},72,10,providers=['cls'])
            self.assertEqual(len(articles),30);self.assertEqual(status['sources']['cls']['attempted'],32)
            self.assertEqual(status['sources']['cls']['excluded_old_or_future'],2)
            self.assertEqual(reading_scope(articles[0]),'full_text')
            self.assertFalse(status['complete_window'])

    def test_index_failure_is_not_reported_as_no_news(self):
        with tempfile.TemporaryDirectory() as folder:
            collector=PublicNewsCollector(folder)
            with patch.object(collector,'index',side_effect=TimeoutError()):
                articles,status=collector.collect([],{},providers=['cls'])
            self.assertEqual(articles,[]);self.assertEqual(status['sources']['cls']['status'],'failed')

    def test_deadline_discloses_unread_candidates(self):
        with tempfile.TemporaryDirectory() as folder:
            collector=PublicNewsCollector(folder)
            with patch.object(collector,'index',return_value='<a href="/detail/1">公司重要经营事件变化</a>'), \
                    patch.object(collector,'detail') as detail:
                articles,status=collector.collect([],{},budget=0,providers=['cls'])
            detail.assert_not_called()
            self.assertEqual(status['sources']['cls']['not_attempted'],1)
            self.assertEqual(status['sources']['cls']['status'],'partial')
