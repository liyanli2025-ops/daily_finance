import json,socket,tempfile,time,unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock,patch
from pydantic import SecretStr
from app.config import settings
from app.models.news import News
from app.services.episode_workspace import EpisodeWorkspace
from app.services.web_research import search,capabilities,public_target,fetch_html_once,parse_visible_article,read_public
from app.services.news_quality import reading_scope
from app.services.evidence import publication_label

NOW=datetime(2026,10,31,8)
URL='https://publisher.example/news/123'
def page(date='2026-10-30T18:00:00+08:00',extra=''):
    return '<html><head><meta property="article:published_time" content="'+date+'"></head><body><h1>行业订单与库存变化</h1>'+extra+'<article>'+('记者核对了公司订单与库存数据，所涉期间需要分开理解。'*20)+'</article></body></html>'

class WebResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.workspace=EpisodeWorkspace([],self.tmp.name,NOW)
        self.hub=patch('app.services.web_research.ResearchHub',return_value=SimpleNamespace(root=self.tmp.name));self.hub.start();self.addCleanup(self.hub.stop)
        self.flags=[patch.object(settings,'research_web_search_enabled',True),patch.object(settings,'research_web_search_api_key',SecretStr('fake-test-key')),
                    patch.object(settings,'research_web_search_max_requests',2)]
        for flag in self.flags:flag.start();self.addCleanup(flag.stop)

    def test_disabled_or_blank_key_never_calls_provider(self):
        with patch('app.services.web_research.requests.post') as post,patch.object(settings,'research_web_search_enabled',False):
            self.assertEqual(search(self.workspace,'行业变化')['status'],'disabled');post.assert_not_called()
        with patch('app.services.web_research.requests.post') as post,patch.object(settings,'research_web_search_api_key',SecretStr('')):
            self.assertFalse(capabilities()['configured']);self.assertEqual(search(self.workspace,'行业变化')['status'],'unavailable');post.assert_not_called()

    def test_existing_fixed_source_body_is_reused_without_new_http(self):
        item=News(id='fixed',title='行业订单与库存变化',content='已取得的记者正文与统计口径。'*50,
            source='证券时报原文',source_url=URL,published_at=NOW)
        self.workspace.add([item])
        with patch('app.services.web_research.fetch_html_once') as fetch:
            result=read_public(self.workspace,URL+'?utm_source=search',characters=120)
        fetch.assert_not_called()
        self.assertEqual(result['material']['id'],'fixed')
        self.assertEqual(len(result['material']['text']),120)
        self.assertEqual(result['http_requests_performed'],0)
        self.assertFalse(result['remote_version_checked'])

    def test_same_url_feed_text_does_not_replace_reading_the_article(self):
        self.workspace.add([News(id='feed',title='行业订单与库存变化',content='这是订阅摘要，并非全文。'*30,
            source='未知RSS摘要',source_url=URL,published_at=NOW)])
        with patch('app.services.web_research.fetch_html_once',return_value=(200,{},page().encode())) as fetch:
            result=read_public(self.workspace,URL)
        fetch.assert_called_once()
        self.assertNotEqual(result['material']['id'],'feed')

    def test_same_title_at_different_url_still_allows_a_counter_report(self):
        self.workspace.add([News(id='first',title='行业订单与库存变化',content='原有报告正文。'*50,
            source='证券时报原文',source_url='https://publisher.example/news/other',published_at=NOW)])
        with patch('app.services.web_research.fetch_html_once',return_value=(200,{},page().encode())) as fetch:
            result=read_public(self.workspace,URL)
        fetch.assert_called_once()
        self.assertEqual(result['status'],'ok')
        self.assertNotEqual(result['material']['id'],'first')

    def test_search_results_remain_directory_and_cache_does_not_spend_again(self):
        response=Mock(status_code=200);response.json.return_value=dict(results=[dict(title='新行业变量',url=URL,content='摘要内容',published_date='2026-10-30')])
        with patch('app.services.web_research.requests.post',return_value=response) as post:
            first=search(self.workspace,'行业变量');second=search(self.workspace,'行业变量')
        self.assertEqual(post.call_count,1);self.assertTrue(second['reused_within_episode'])
        self.assertEqual(first['results'][0]['reading_status'],'search_snippet_not_body')
        self.assertEqual(len(self.workspace.documents),0)
        self.assertEqual(post.call_args.kwargs['json']['search_depth'],'basic')
        self.assertFalse(post.call_args.kwargs['json']['auto_parameters'])
        self.assertNotIn('fake-test-key',json.dumps(first))

    def test_failure_is_not_retried_under_new_query_or_new_episode(self):
        with patch('app.services.web_research.requests.post',side_effect=RuntimeError('private fake-test-key')) as post:
            first=search(self.workspace,'问题甲');second=search(self.workspace,'问题乙')
        self.assertEqual(post.call_count,1);self.assertEqual(second['status'],'unavailable')
        self.assertNotIn('fake-test-key',json.dumps(first))

    def test_attempt_budget_includes_failures_and_cache_stays_readable_after_limit(self):
        response=Mock(status_code=200);response.json.return_value=dict(results=[])
        with patch('app.services.web_research.requests.post',return_value=response) as post:
            search(self.workspace,'问题甲');search(self.workspace,'问题乙')
            self.assertEqual(search(self.workspace,'问题丙')['status'],'budget_exhausted')
            self.assertTrue(search(self.workspace,'问题甲')['reused_within_episode'])
        self.assertEqual(post.call_count,2)

    def test_private_and_mixed_dns_targets_are_rejected(self):
        for addresses in [['127.0.0.1'],['169.254.169.254'],['::1'],['8.8.8.8','10.0.0.1']]:
            with patch('app.services.web_research.socket.getaddrinfo',return_value=[(2,1,6,'',(address,443)) for address in addresses]):
                with self.assertRaises(ValueError):public_target(URL)
        for bad in ['file:///etc/passwd','https://user:password@publisher.example/a','http://localhost/a','https://example.com:8000/a']:
            with self.assertRaises(ValueError):public_target(bad)

    def test_checked_ip_is_pinned_with_original_tls_and_no_credentials(self):
        response=Mock(status=200,headers={'Content-Type':'text/html'});response.stream.return_value=[page().encode()]
        pool=Mock();pool.request.return_value=response
        with patch('app.services.web_research.socket.getaddrinfo',return_value=[(2,1,6,'',('8.8.8.8',443))]),patch('app.services.web_research.urllib3.HTTPSConnectionPool',return_value=pool) as factory:
            status,headers,body=fetch_html_once(URL)
        self.assertEqual(status,200);self.assertIn(b'article',body)
        self.assertEqual(factory.call_args.args[0],'8.8.8.8')
        self.assertEqual(factory.call_args.kwargs['server_hostname'],'publisher.example')
        self.assertEqual(factory.call_args.kwargs['assert_hostname'],'publisher.example')
        self.assertEqual(set(pool.request.call_args.kwargs['headers']),{'Host','User-Agent'})
        self.assertIs(pool.request.call_args.kwargs['retries'],False)

    def test_visible_article_has_source_clock_and_never_claims_full_text(self):
        item=parse_visible_article(page(),URL,NOW)
        self.assertEqual(reading_scope(item),'visible_body')
        self.assertEqual(item.published_at,datetime(2026,10,30,18))
        self.assertEqual(parse_visible_article(page('2026-10-31'),URL,NOW).market_impact.count('精度：day'),1)
        self.assertIn('日精度',publication_label(parse_visible_article(page('2026-10-31'),URL,NOW)))

    def test_missing_body_time_zone_future_and_paywall_fail_closed(self):
        for html in [page().replace('<article>','<div>').replace('</article>','</div>'),page('2026-10-30T18:00:00'),
                     page('2026-11-01T18:00:00+08:00'),page(extra='<script type="application/ld+json">{"isAccessibleForFree":false}</script>')]:
            with self.assertRaises(ValueError):parse_visible_article(html,URL,NOW)

    def test_sina_article_body_excludes_recommendations_and_preserves_minute(self):
        body='记者核对了股指收盘、业绩披露和市场反应；因果仍需要核对。'*15
        html='<h1 class="main-title">美股收盘与科技财报新变化</h1><div class="date-source"><span class="date">2026年10月31日 06:05</span></div><div id="artibody">'+body+'</div><div>不应入正文的推荐新闻</div>'
        item=parse_visible_article(html,'https://cj.sina.com.cn/articles/view/123/abc',NOW)
        self.assertEqual(item.content,body);self.assertIn('分钟精度',publication_label(item))
        with self.assertRaises(ValueError):parse_visible_article(html.replace('2026年10月31日 06:05',''),item.source_url,NOW)

    def test_bea_release_clock_is_not_page_modified_date(self):
        body='Personal income and spending data, period September; monthly changes are not annual rates. '*10
        html='<h1>News Release</h1><h1>Personal Income and Outlays, September 2026</h1><div class="field--name-field-release-date">EMBARGOED UNTIL RELEASE AT 8:30 a.m. EDT, Thursday, October 29, 2026</div><div class="field--name-body">'+body+'</div><div>Page last modified on 10/30/26</div>'
        item=parse_visible_article(html,'https://www.bea.gov/news/2026/personal-income-and-outlays-september-2026',NOW)
        self.assertEqual(item.published_at,datetime(2026,10,29,20,30));self.assertIn('分钟精度',publication_label(item))
        self.assertNotIn('last modified',item.content)

    def test_reviewed_adapter_failure_cannot_fall_back_to_generic_article(self):
        with patch('app.services.public_news_sources.parse_article',side_effect=ValueError('known adapter admission failure')):
            with self.assertRaisesRegex(ValueError,'known adapter'):
                parse_visible_article(page(),'https://www.nbd.com.cn/articles/2026-10-30/123.html',NOW)

    def test_successful_public_read_preserves_ranges_and_reuses_page(self):
        with patch('app.services.web_research.fetch_html_once',return_value=(200,{},page().encode())) as fetch:
            first=read_public(self.workspace,URL,characters=100);second=read_public(self.workspace,URL,characters=200)
        self.assertEqual(fetch.call_count,1);self.assertEqual(first['status'],'ok')
        self.assertEqual(len(second['material']['text']),200)
        self.assertEqual(len(self.workspace.documents),1)
        self.assertFalse(self.workspace.confirmed)

    def test_failed_body_is_not_retried_or_admitted(self):
        with patch('app.services.web_research.fetch_html_once',return_value=(200,{},b'<h1>Not an article</h1>')) as fetch:
            result=read_public(self.workspace,URL)
            self.assertEqual(result['status'],'failed');self.assertEqual(result['reason'],'web_source_body_unavailable')
            self.assertEqual(read_public(self.workspace,URL)['status'],'unavailable')
        self.assertEqual(fetch.call_count,1);self.assertFalse(self.workspace.documents)

    def test_alias_to_a_paused_target_is_not_fetched_again(self):
        target='https://publisher.example/news/paused'
        with patch('app.services.web_research.PAUSED_PUBLIC_ARTICLES',{target:'known_failed'}),patch(
                'app.services.web_research.fetch_html_once',return_value=(302,{'Location':target},b'')) as fetch:
            self.assertEqual(read_public(self.workspace,URL)['status'],'failed')
            self.assertEqual(read_public(self.workspace,URL)['status'],'unavailable')
        self.assertEqual(fetch.call_count,1)

    def test_capabilities_preflight_does_not_call_any_external_service(self):
        from app.research_desk_check import inspect
        with patch('app.services.web_research.requests.post') as post,patch('app.services.web_research.fetch_html_once') as fetch:
            result=inspect()
        self.assertEqual(result['external_model_requests'],0);self.assertEqual(result['search_requests'],0)
        post.assert_not_called();fetch.assert_not_called()

    def test_expired_deadline_has_zero_network(self):
        with patch('app.services.web_research.requests.post') as post:
            self.assertEqual(search(self.workspace,'问题',deadline=time.monotonic()-1)['status'],'budget_exhausted');post.assert_not_called()
