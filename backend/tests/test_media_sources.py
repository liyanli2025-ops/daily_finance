from datetime import datetime, timedelta, timezone
import tempfile
import unittest
from unittest.mock import patch,Mock,AsyncMock

from app.services.media_sources import MediaCollector,query_plan,relation,parse_stcn,stcn_links,public_article
from app.services.watchlist_service import WatchlistStock
from app.services.ai_analyzer import AIAnalyzerService
from app.models.news import News
from types import SimpleNamespace
from app.services.news_collector import NewsCollectorService
from app.services.watchlist_service import WatchlistService

NOW=datetime(2026,10,25,12)


def epoch(stamp):
    return stamp.replace(tzinfo=timezone(timedelta(hours=8))).timestamp()


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.collector=MediaCollector(self.folder.name)
        self.stocks=[WatchlistStock('123456','任意新公司','A')]
        self.profiles={'A:123456':dict(industry='电子制造',business='主营环氧塑封料',topics=['半导体','封装'])}

    def test_query_plan_changes_with_app_watchlist_and_actual_business(self):
        queries,terms=query_plan(self.stocks,self.profiles)
        self.assertIn('任意新公司',queries)
        self.assertIn('封装材料',queries)
        self.assertNotIn('牧原股份',queries)
        changed=[WatchlistStock('09999','新港股','HK')]
        next_queries,_=query_plan(changed,{'HK:09999':dict(industry='电力',business='主营燃煤火电')})
        self.assertIn('新港股',next_queries)
        self.assertIn('煤电',next_queries)
        self.assertNotIn('来水',next_queries)
        self.assertNotIn('任意新公司',next_queries)

    def test_public_targeted_read_has_no_twenty_four_article_ceiling(self):
        def get(url,*args,**kwargs):
            if '/search/article' in url:
                return {'items':[dict(id=i,title='特定行业新事件'+str(i),display_time=epoch(NOW),is_paid=False)
                    for i in range(100,135)]}
            return '<html></html>'
        def detail(provider,identifier,deadline):
            return dict(title='特定行业新事件'+identifier,body='本次公开披露行业新变化，仍需核实传导条件。'*30,
                published=NOW.isoformat(),source='华尔街见闻原文',url='https://wallstreetcn.com/articles/'+identifier)
        with patch.object(self.collector,'get',side_effect=get),patch.object(self.collector,'detail',side_effect=detail), \
                patch('app.services.media_sources.china_now',return_value=NOW):
            news,coverage=self.collector.collect([],{},72,50,search_queries=['特定行业'])
        self.assertEqual(len(news),35)
        self.assertIsNone(coverage['detail_budget']['limit'])
        self.assertEqual(coverage['detail_budget']['not_attempted'],0)

    def test_time_budget_records_unread_candidates_instead_of_claiming_read(self):
        original=self.fake_get
        with patch.object(self.collector,'get',side_effect=original), \
                patch.object(self.collector,'detail') as detail, \
                patch('app.services.media_sources.china_now',return_value=NOW):
            news,coverage=self.collector.collect(self.stocks,self.profiles,72,budget=0)
        self.assertEqual(news,[]);detail.assert_not_called()
        self.assertGreater(coverage['detail_budget']['not_attempted'],0)
        self.assertTrue(coverage['unread_candidates'])

    def test_industry_relation_never_becomes_company_or_customer_relation(self):
        direct,industry,macro=relation('三星扩大先进封装投入','报道没有提到该公司',self.stocks,{'123456':['先进封装']})
        self.assertEqual(direct,[])
        self.assertEqual(industry,{'123456':['先进封装']})

    def test_public_access_filters_paid_and_trial_flags(self):
        for key in ['is_paid','is_priced','is_need_pay','is_trial','is_trail']:
            self.assertFalse(public_article({key:True}))
        self.assertTrue(public_article({'is_need_pay':False}))

    def test_stcn_article_uses_own_date_and_body_not_related_articles(self):
        html='<h1>公司新事件</h1><div class="detail-info">来源 2026-10-24 16:13</div>' \
             '<div class="detail-content">'+('已披露的事项。'*30)+'</div><aside>2026-10-25 12:00 其他相关新闻</aside>'
        title,published,body=parse_stcn(html)
        self.assertEqual(published,datetime(2026,10,24,16,13))
        self.assertNotIn('其他相关新闻',body)
        actual_layout=html.replace('<h1>','<div class="detail-title">').replace('</h1>','</div>')
        self.assertEqual(parse_stcn(actual_layout)[0],title)
        with self.assertRaises(ValueError):parse_stcn(html.replace('2026-10-24 16:13','日期未提供'))

    def test_index_does_not_follow_arbitrary_links_or_image_summary_duplicates(self):
        html='<a href="http://127.0.0.1/private">任意新公司最新报道</a>' \
             '<a href="/article/detail/123.html">任意新公司最新报道</a>' \
             '<a href="/article/detail/123.html">这是文章摘要，不能替代标题</a>'
        self.assertEqual(stcn_links(html),[('https://www.stcn.com/article/detail/123.html','任意新公司最新报道')])

    def fake_get(self,url,deadline,params=None,json_response=True):
        if '/information-flow' in url:
            return {'items':[]}
        if '/search/article' in url:
            return {'items':[
                dict(id=11,title='新封装材料事件',display_time=epoch(NOW-timedelta(hours=10)),is_paid=False),
                dict(id=12,title='任意新公司新增订单',display_time=epoch(NOW-timedelta(hours=8)),is_paid=False),
                dict(id=13,title='付费封装材料报道',display_time=epoch(NOW),is_paid=True),
                dict(id=14,title='旧封装材料报道',display_time=epoch(NOW-timedelta(days=20)),is_paid=False),
                dict(id=15,title='未来封装材料报道',display_time=epoch(NOW+timedelta(days=1)),is_paid=False)]}
        if '/content/articles/' in url:
            identifier=int(url.rsplit('/',1)[1])
            return dict(id=identifier,is_need_pay=False,is_priced=False,
                        title='先进封装材料需求变化' if identifier==11 else '任意新公司新增订单',
                        display_time=epoch(NOW-timedelta(hours=8)),
                        content=('<p>先进封装材料需求变化，未提及任何该自选股供货关系。</p>' if identifier==11
                                 else '<p>任意新公司公告新增订单，后续需核实执行情况。</p>')*12)
        return '<html>无匹配文章</html>'

    def test_real_collection_path_reads_bodies_and_excludes_paid_old_future_results(self):
        with patch.object(self.collector,'get',side_effect=self.fake_get) as get, \
                patch('app.services.media_sources.china_now',return_value=NOW):
            news,coverage=self.collector.collect(self.stocks,self.profiles,hours=72)
        self.assertEqual(len(news),2)
        direct=next(item for item in news if item.related_stocks)
        industry=next(item for item in news if not item.related_stocks)
        self.assertEqual(direct.related_stocks,['123456'])
        self.assertIn('不证明该公司受益或供货',industry.market_impact)
        urls=[call.args[0] for call in get.call_args_list]
        self.assertFalse(any(url.endswith(('/13','/14','/15')) for url in urls))
        self.assertEqual(sum('/content/articles/11' in url for url in urls),1)
        self.assertEqual(coverage['sources']['wscn']['status'],'ok')
        self.assertEqual(coverage['per_stock']['A:123456']['company_mentions'],1)
        self.assertEqual(coverage['per_stock']['A:123456']['industry_leads'],1)

    def test_search_excerpt_cannot_replace_missing_or_paid_article_body(self):
        original=self.fake_get
        def get(url,*args,**kwargs):
            data=original(url,*args,**kwargs)
            if '/content/articles/' in url:
                data['is_need_pay']=True
                data['content']='可见摘要'*100
            return data
        with patch.object(self.collector,'get',side_effect=get),patch('app.services.media_sources.china_now',return_value=NOW):
            news,coverage=self.collector.collect(self.stocks,self.profiles,hours=72)
        self.assertEqual(news,[])
        self.assertEqual(coverage['sources']['wscn']['status'],'failed')

    def test_market_wide_event_does_not_require_a_watchlist_or_keyword_match(self):
        def get(url,*args,**kwargs):
            if '/information-flow' in url:
                return {'items':[{'resource_type':'article','resource':dict(id=99,title='交易所发布新制度',
                    display_time=epoch(NOW-timedelta(hours=1)),is_priced=False)}]}
            if '/search/article' in url:
                return {'items':[]}
            if '/content/articles/' in url:
                return dict(id=99,title='交易所发布新制度',display_time=epoch(NOW-timedelta(hours=1)),
                            is_need_pay=False,content='<p>'+('本次制度变化是公开事件，不预设受益股票。'*12)+'</p>')
            return '<html></html>'
        with patch.object(self.collector,'get',side_effect=get),patch('app.services.media_sources.china_now',return_value=NOW):
            articles,coverage=self.collector.collect([],{},hours=24)
        self.assertEqual(len(articles),1)
        self.assertEqual(articles[0].related_stocks,[])
        self.assertEqual(articles[0].category,'全市场事件')
        self.assertEqual(coverage['market_wide_articles'],1)
        self.assertIn('不自动视为短线催化',articles[0].market_impact)

    def test_provider_error_is_reported_as_failed_not_no_news(self):
        with patch.object(self.collector,'get',side_effect=TimeoutError('fixture')):
            news,coverage=self.collector.collect(self.stocks,self.profiles,hours=24)
        self.assertEqual(news,[])
        self.assertEqual(coverage['sources']['wscn']['status'],'failed')
        self.assertEqual(coverage['sources']['stcn']['status'],'failed')

    def test_http_layer_does_not_redirect_to_unknown_hosts(self):
        with patch('app.services.media_sources.requests.get') as get:
            with self.assertRaises(ValueError):
                self.collector.get('https://127.0.0.1/private',float('inf'))
        get.assert_not_called()

    def test_industry_original_survives_generic_news_flood_without_becoming_company_fact(self):
        original=News(id='industry',title='封装基板扩产',content='封装产业报道，不证明该公司供货。',
            source='原始媒体',source_url='https://wallstreetcn.com/articles/3784240',published_at=NOW,
            related_stocks=[],importance_score=.74,
            market_impact='行业关联 A:123456（匹配：封装；不证明该公司受益或供货）')
        pool=[News(id='generic'+str(i),title='不同市场消息'+str(i),content='普通新闻',source='来源',
            source_url='https://example.com/article/'+str(i),published_at=NOW,importance_score=.99) for i in range(45)]
        analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
        with patch('app.services.ai_analyzer.get_watchlist_service',return_value=SimpleNamespace(get_all_stocks=lambda:self.stocks)):
            summary=analyzer._prepare_news_summary(pool+[original])
        self.assertIn('[N:industry]',summary)
        self.assertIn('不证明该公司受益或供货',summary)
        self.assertEqual(original.related_stocks,[])


class CollectionIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_media_original_is_returned_from_production_news_collector(self):
        collector=NewsCollectorService.__new__(NewsCollectorService)
        collector.akshare_available=False
        collector._load_db_watchlist=AsyncMock(return_value=[dict(code='123456',name='新自选股',market='A')])
        item=News(id='new-media',title='新自选股新增事件',content='原文正文',source='证券时报原文',
                  source_url='https://www.stcn.com/article/detail/123.html',published_at=NOW)
        with patch('app.services.news_collector.get_watchlist_service',return_value=WatchlistService()), \
                patch('app.services.watchlist_sources.fetch_company_announcements',return_value=([],{})), \
                patch('app.services.watchlist_sources.fetch_sina_stock_news',return_value=([],{})), \
                patch('app.services.research_hub.ResearchHub.collect',AsyncMock(return_value={'stocks':[]})), \
                patch('app.services.research_hub.ResearchHub.load',return_value=[]), \
                patch('app.services.technical_radar.TechnicalRadar.collect',return_value={'coverage':{}}), \
                patch('app.services.policy_sources.PolicyCollector.collect',return_value=([],{'sources':{}})), \
                patch('app.services.public_news_sources.PublicNewsCollector.collect',return_value=([],{'sources':{}})), \
                patch('app.services.overseas_sources.OverseasCollector.collect',return_value=([],{'sources':{}})), \
                patch('app.services.media_sources.MediaCollector.collect',return_value=([item],{})) as media:
            items=await collector._collect_radar_news(hours=72)
        self.assertIn(item,items)
        self.assertEqual(media.call_args.args[0][0].code,'123456')
        self.assertEqual(media.call_args.args[2],72)
