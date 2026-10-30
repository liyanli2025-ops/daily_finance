from datetime import datetime
import json
import unittest
from app.services.domestic_discovery import entries
from app.services.public_news_sources import parse_article,permitted,discover


class DomesticDiscoveryTests(unittest.TestCase):
    def test_thepaper_no_summary_fallback_and_id_check(self):
        url='https://m.thepaper.cn/newsDetail_forward_123'
        body='行业经营数据和保险主业分析。'*25
        row=dict(contId=123,name='五大险企经营数据',content='<p>'+body+'</p>',publishTime=1793370528806,source='记者原稿',author='记者甲')
        def page(row,visible=True):
            return '<h1>五大险企经营数据</h1><script id="__NEXT_DATA__">'+json.dumps(dict(props=dict(pageProps=dict(detailData=dict(contentDetail=row)))))+'</script>'+('<article>'+body+'</article>' if visible else '')
        result=parse_article('thepaper',page(row),url)
        self.assertEqual(result['author'],'记者甲')
        self.assertEqual(result['published'],'2026-10-30T22:28:48')
        with self.assertRaises(ValueError):parse_article('thepaper',page(row,False),url)
        row['content']='';row['summary']=body
        with self.assertRaises(ValueError):parse_article('thepaper',page(row),url)
        row['content']=body;row['contId']=124
        with self.assertRaises(ValueError):parse_article('thepaper',page(row),url)

    def test_tmtpost_visible_body_author_and_minute_date(self):
        html='<div class="_content_mode"><h2 class="tit">电网设备行业变化</h2><div class="post_author_infor"><span class="time">2026.10.30 17:34</span></div><div class="post_author"><span class="name">投稿作者</span></div><div class="_bottom">'+'供需行业观察。'*40+'</div></div>'
        row=parse_article('tmtpost',html,'https://www.tmtpost.com/123.html')
        self.assertEqual(row['author'],'投稿作者')
        self.assertEqual(row['date_precision'],'minute')
        with self.assertRaises(ValueError):parse_article('tmtpost',html.replace('供需行业观察。','解锁全文'),'https://www.tmtpost.com/123.html')

    def test_caijing_day_is_interval_and_reprint_source_retained(self):
        html='<div class="article"><h2>半导体设备产业变化</h2><span class="news_time">2026/10/30</span><span class="news_frome">另一媒体</span></div><div class="article-content">'+'行业原文。'*50+'</div>'
        row=parse_article('caijing',html,'https://stock.caijing.com.cn/20261030/123.shtml')
        self.assertEqual(row['date_precision'],'day')
        self.assertEqual(row['publication_end'],'2026-10-31T00:00:00')
        self.assertEqual(row['upstream'],'另一媒体')

    def test_strict_hosts_and_paid_list_rejection(self):
        self.assertFalse(permitted('caijing','https://stock.caijing.com.cn.evil.test/20261030/123.shtml'))
        self.assertFalse(permitted('caijing','https://life.caijing.com.cn/20261030/123.shtml'))
        self.assertEqual(entries('thepaper',json.dumps(dict(data=dict(list=[dict(contId=1,name='市场事件',paywalled=True)])))),[])
        self.assertEqual(entries('tmtpost',json.dumps(dict(data=[dict(title='文章',share_link='https://www.tmtpost.com/1.html',is_paid_special_column_post=True)]))),[])

    def test_domestic_list_does_not_restore_routine_unrelated_earnings(self):
        data=[dict(title='普通公司：第三季度净利润增长4%',url='https://stock.caijing.com.cn/20261030/123.shtml'),
              dict(title='半导体产业链订单变化影响行业供需',url='https://stock.caijing.com.cn/20261030/124.shtml')]
        result=discover('caijing',json.dumps(data),[],{})
        self.assertEqual(len(result),1)
        self.assertTrue(result[0]['url'].endswith('/124.shtml'))
