from datetime import datetime,timedelta,timezone
import tempfile
import unittest
from unittest.mock import patch

from app.services.wechat_sources import WeChatCollector,parse_article,search_links,permitted,literal_redirect
from app.services.watchlist_service import WatchlistStock

NOW=datetime(2026,10,25,13)


def page():
    stamp=int((NOW-timedelta(hours=2)).replace(tzinfo=timezone(timedelta(hours=8))).timestamp())
    return '<h1 id="activity-name">新自选公司业务变化</h1><a id="js_name">行业观察作者</a>'+\
        '<script>var ct = "'+str(stamp)+'";</script><div id="js_content">'+('新自选公司业务变化，作者提出判断，仍需披露核实。'*20)+'</div>'


class WeChatTests(unittest.TestCase):
    def test_disabled_channel_never_contacts_public_or_paid_apis(self):
        with tempfile.TemporaryDirectory() as folder,patch('app.services.wechat_sources.requests.get') as get:
            articles,status=WeChatCollector(folder,dict(public_search_enabled=False,article_urls=[])).collect([],{},24)
        self.assertEqual(status['status'],'disabled');self.assertEqual(articles,[]);get.assert_not_called()

    def test_real_article_elements_and_original_time_required(self):
        row=parse_article(page())
        self.assertEqual(row['account'],'行业观察作者')
        self.assertEqual(row['published'],'2026-10-25T11:00:00')
        with self.assertRaises(ValueError):parse_article('<div>仅有搜索摘要</div>')
        with self.assertRaises(ValueError):parse_article(page().replace('var ct','var unrelated'))

    def test_captcha_unknown_layout_and_arbitrary_hosts_are_not_read(self):
        for html in ('<html>请输入验证码</html>','<html>未知页面</html>'):
            with self.assertRaises(ValueError):search_links(html)
        for url in ('http://mp.weixin.qq.com/s/a','https://mp.weixin.qq.com.evil.test/s/a',
                    'https://127.0.0.1/s/a','https://mp.weixin.qq.com:8080/s/a'):
            self.assertFalse(permitted(url))

    def test_public_literal_redirect_is_read_without_executing_page_code(self):
        html="<script>var url = '';url += 'https://mp.';url += 'weixin.qq.com/s/example';window.location.replace(url)</script>"
        self.assertEqual(literal_redirect(html),'https://mp.weixin.qq.com/s/example')
        for page in (html.replace('https://mp.','https://127.0.0.1/'),
                     "<script>var url = '';url += secretFunction();window.location.replace(url)</script>"):
            with self.assertRaises(ValueError):literal_redirect(page)

    def test_unavailable_public_search_cools_down_and_does_not_repeat_next_report(self):
        with tempfile.TemporaryDirectory() as folder:
            collector=WeChatCollector(folder,dict(public_search_enabled=True,article_urls=[]))
            with patch.object(collector,'get',return_value=('<html>请输入验证码</html>','https://weixin.sogou.com/weixin')) as get, \
                    patch('app.services.wechat_sources.china_now',return_value=NOW):
                first,status=collector.collect([],{},24)
                again,next_status=collector.collect([],{},24)
            self.assertEqual(get.call_count,1)
            self.assertEqual(next_status['search_status'],'cooldown')
            self.assertEqual(first+again,[])

    def test_explicit_public_article_uses_current_watchlist_and_remains_attributed(self):
        with tempfile.TemporaryDirectory() as folder:
            collector=WeChatCollector(folder,dict(public_search_enabled=False,article_urls=['https://mp.weixin.qq.com/s/example']))
            stock=WatchlistStock('123456','新自选公司','A')
            with patch.object(collector,'get',return_value=(page(),'https://mp.weixin.qq.com/s/example')), \
                    patch('app.services.wechat_sources.china_now',return_value=NOW):
                news,status=collector.collect([stock],{},24)
            self.assertEqual(len(news),1);self.assertEqual(news[0].related_stocks,['123456'])
            self.assertEqual(news[0].source,'微信公众号原文-行业观察作者')
            self.assertIn('非自动认定为公司一手披露',news[0].market_impact)
