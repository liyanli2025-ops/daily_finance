"""Public commercial research/reporting, independent of a fixed watchlist."""
from datetime import datetime
import json
import tempfile
import unittest
from unittest.mock import patch

from app.services.public_news_sources import PublicNewsCollector,parse_article,discover
from app.services.news_quality import reading_scope
from app.services.news_briefing import editorial_exclusion

BODY='记者调查发现订单、库存与利润率存在变化，但不证明相关股票会涨。'*20


class NonofficialSourceTests(unittest.TestCase):
    def test_reporters_body_and_header_date_without_related_items(self):
        cases=[('eeo','https://www.eeo.com.cn/2026/1027/123.shtml',
            '<h1>企业订单与库存调查</h1><p id="showFocus">2026-10-27 17:50</p><div class="xx_boxsing">'+BODY+'</div>'),
            ('jiemian','https://www.jiemian.com/article/123.html',
            '<h1>消费公司盈利调查</h1><p class="info-s">记者 2026/10/27 14:50</p><div class="article-content">'+BODY+'</div>')]
        for key,url,html in cases:
            row=parse_article(key,html+'<aside>2027-01-01 推荐文章</aside>',url)
            self.assertTrue(row['published'].startswith('2026-10-27'))
            self.assertNotIn('推荐文章',row['body'])
            with self.assertRaises(ValueError):parse_article(key,html.replace('2026-10-27','未知').replace('2026/10/27','未知'),url)

    def test_empty_watchlist_can_discover_multiple_market_industries(self):
        rows=discover('jiemian',''.join('<a href="/article/'+str(i)+'.html">'+title+'</a>' for i,title in enumerate(
            ['珠江啤酒旺季失守','汽车产业增长难题','航运企业订单变化','机器人产业库存调查'])),[],{})
        self.assertEqual(len(rows),4)
        eeo=discover('eeo','<a href="http://www.eeo.com.cn/2026/1027/123.shtml">产业公司增长与订单变化</a>',[],{})
        self.assertEqual(eeo[0]['url'],'https://www.eeo.com.cn/2026/1027/123.shtml')

    def test_trendforce_publication_is_not_subscription_report_or_fake_clock(self):
        html='<article class="presscenter"><h1>Server CPU Shipments Research</h1><div class="tag-row"><span>22 October 2026</span></div><p>'+BODY+'</p></article><footer>订阅报告</footer>'
        row=parse_article('trendforce',html,'https://www.trendforce.com/presscenter/news/20261022-123.html')
        self.assertEqual(row['date_precision'],'day')
        self.assertIn('不等于完整订阅报告',row['reading'])
        self.assertEqual(row['publication_start'],'2026-10-21T18:00:00')
        self.assertEqual(row['publication_end'],'2026-10-23T20:00:00')
        self.assertNotIn('订阅报告',row['body'])

    def test_smm_requires_public_access_and_real_text_not_image_charts(self):
        row=dict(newsId=123,isVip=False,isLoginVisible=False,hasPerm=True,remainWords='',disable=0,
            title='金属现货市场调查',content='<p>'+BODY+'</p>',source='SMM')
        def html():return '<time>2026-10-27 18:33</time><script id="__NEXT_DATA__">'+json.dumps(dict(props=dict(pageProps=dict(newsDetail=row))))+'</script>'
        url='https://news.smm.cn/news/123'
        self.assertEqual(parse_article('smm',html(),url)['upstream'],'SMM')
        for field,value in [('isVip',True),('hasPerm',False),('isLoginVisible',True),('remainWords','剩余正文')]:
            original=row[field];row[field]=value
            with self.assertRaises(ValueError):parse_article('smm',html(),url)
            row[field]=original
        row['content']='<p>数据如图</p><img src="chart.png">'
        with self.assertRaisesRegex(ValueError,'publisher_full_body_unavailable'):parse_article('smm',html(),url)

    def test_known_failed_sample_never_reprobed(self):
        with tempfile.TemporaryDirectory() as root:
            collector=PublicNewsCollector(root)
            with patch.object(collector,'get',side_effect=AssertionError('must not retry')):
                with self.assertRaisesRegex(ValueError,'source_paused_no_automatic_retest'):
                    collector.detail('smm','https://news.smm.cn/news/104181778',float('inf'))

    def test_new_sources_conference_promotion_does_not_become_main_story(self):
        from types import SimpleNamespace
        self.assertEqual(editorial_exclusion(SimpleNamespace(title='产业论坛成功举办',source='上海有色网公开原文'),[]),
            'conference_promotion_not_primary_story')
        self.assertIsNone(editorial_exclusion(SimpleNamespace(title='产业订单与库存发生变化',source='上海有色网公开原文'),[]))

    def test_enters_real_collect_path_without_watchlist_or_model(self):
        with tempfile.TemporaryDirectory() as root:
            collector=PublicNewsCollector(root)
            html='<a href="/article/123.html">汽车产业增长难题与公司订单</a>'
            row=dict(title='汽车产业增长难题',body=BODY,published='2026-10-27T14:50:00',date_precision='minute',
                url='https://www.jiemian.com/article/123.html',source='界面新闻公开原文',reading='公开主体',upstream='')
            with patch.object(collector,'index',return_value=html),patch.object(collector,'detail',return_value=row), \
                    patch('app.services.public_news_sources.china_now',return_value=datetime(2026,10,28,12)):
                items,coverage=collector.collect([],{},72,1,providers=['jiemian'])
            self.assertEqual(len(items),1)
            self.assertEqual(reading_scope(items[0]),'full_text')
            self.assertEqual(items[0].related_stocks,[])
            self.assertIn('全市场事件入口',items[0].market_impact)
            self.assertIn('商业报道或评论',items[0].market_impact)
            self.assertEqual(coverage['sources']['jiemian']['read'],1)


if __name__=='__main__':unittest.main()
