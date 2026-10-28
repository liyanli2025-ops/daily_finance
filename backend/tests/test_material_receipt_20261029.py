"""Actual server receipt cases: incidental power purchase and paused adapters."""
from datetime import datetime
import tempfile
import unittest
from unittest.mock import patch

import requests
from app.models.news import News
from app.services.media_sources import relation
from app.services.news_selection import industry_terms
from app.services.news_briefing import associations,weak_industry_only
from app.services.public_news_sources import PublicNewsCollector
from app.services.overseas_sources import OverseasCollector
from app.services.source_health import record_failure
from app.services.watchlist_service import WatchlistStock


class MaterialReceiptTests(unittest.TestCase):
    def test_mine_electricity_purchase_is_not_hydropower_business_news(self):
        stock=WatchlistStock('123456','动态水电公司','A')
        body='安哥拉隆贡若稀土矿讨论股权融资，计划投产。除了同劳卡（Laúca）水电站签署购电协议外，项目采购仍在推进。'
        self.assertEqual(relation('彭萨纳公司继续融资开发隆贡若项目',body,[stock],{'123456':['水电','来水']})[1],{})
        # Old archived labels are not accepted as business overlap on replay.
        row=News(id='old',title='彭萨纳公司继续融资开发隆贡若项目',content=body,source='上海有色网公开原文',
            source_url='https://news.smm.cn/news/104183705',published_at=datetime(2026,10,28,14,9),
            market_impact='行业关联 A:123456（匹配：水电；不证明该公司受益）')
        profiles={'A:123456':dict(business='水力发电')}
        self.assertEqual(associations(row,[stock],profiles)[0]['level'],'keyword_only')
        self.assertTrue(weak_industry_only(row,[stock],profiles))
        self.assertIn('水电站',row.content)  # Do not rewrite or discard source text.

    def test_real_operating_context_and_other_industries_remain(self):
        terms=['水电','来水','水电站','水电发电量']
        self.assertIn('水电站',industry_terms('国内水电站发电量随流域来水变化。',terms))
        self.assertIn('水电站',industry_terms('水电站与工业用户签署长期售电协议。',terms))
        mixed='矿山向某水电站购买电力。国内流域来水偏少，水电发电量下降。'
        self.assertIn('水电发电量',industry_terms(mixed,terms))
        self.assertIn('稀土',industry_terms('稀土矿与某水电站签署购电协议。',['水电','稀土']))
        self.assertEqual(industry_terms('稀土矿向某水电站购买电力。',['水电','水电站']),[])

    def test_direct_company_mention_survives_incidental_clause_mask(self):
        stock=WatchlistStock('123456','动态水电公司','A')
        direct,_,_=relation('动态水电公司披露公告','与某水电站签署购电协议。',[stock],{'123456':['水电']})
        self.assertEqual(direct,['123456'])

    def test_paused_publisher_index_is_not_a_fresh_network_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            collector=PublicNewsCollector(folder)
            record_failure(collector.hub.root,'publisher:index:v1:eeo',ValueError('publisher_source_date_missing'))
            with patch('requests.get',side_effect=AssertionError('no re-probe')) as get:
                articles,result=collector.collect([],{},providers=['eeo'])
            state=result['sources']['eeo'];self.assertEqual(articles,[])
            self.assertEqual(state['status'],'paused');self.assertEqual(state['errors'],[])
            self.assertEqual(len(state['paused_routes']),1);get.assert_not_called()

    def test_paused_publisher_article_is_not_counted_as_read_or_fresh_error(self):
        with tempfile.TemporaryDirectory() as folder:
            collector=PublicNewsCollector(folder);url='https://www.cls.cn/detail/123'
            record_failure(collector.hub.root,'publisher:article:v1:'+url,ValueError('publisher_full_body_unavailable'))
            with patch.object(collector,'index',return_value='<a href="/detail/123">上市公司经营事件变化</a>'),patch('requests.get',side_effect=AssertionError('no re-probe')) as get:
                _,result=collector.collect([],{},providers=['cls'])
            state=result['sources']['cls'];self.assertEqual(state['status'],'paused')
            self.assertEqual(state['read'],0);self.assertEqual(state['errors'],[])
            self.assertEqual(state['paused_routes'][0]['stage'],'article');get.assert_not_called()

    def test_paused_overseas_route_retains_old_reason_without_http(self):
        with tempfile.TemporaryDirectory() as folder:
            collector=OverseasCollector(folder)
            response=requests.Response();response.status_code=403
            record_failure(collector.hub.root,'overseas:index:v1:bbc',requests.HTTPError(response=response))
            with patch('requests.get',side_effect=AssertionError('no re-probe')) as get:
                _,result=collector.collect(providers=['bbc'])
            state=result['sources']['bbc'];self.assertEqual(state['status'],'paused')
            self.assertEqual(state['errors'],[])
            self.assertEqual(state['paused_routes'][0]['reason'],'http_403');get.assert_not_called()
