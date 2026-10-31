import copy,unittest
from datetime import datetime,timedelta
from unittest.mock import patch,AsyncMock,Mock

from app.services.search_primary_collection import prepare,collect,OWNER

NOW=datetime(2026,10,31,12)


def bundle():
    return dict(owner=OWNER,collected_at=NOW.isoformat(),hours=72,
        search_receipts=[dict(query='今天全市场重要变化',checked_at=NOW.isoformat(),status='searched_not_exhaustive')],
        watchlist=[dict(code='01234',name='新港股公司',market='HK')],
        articles=[dict(title='全市场重大变化',body='报道正文，保留具体事件、原始口径、时间和可核查的上下文。'*8,
            url='https://example.com/article/1',source_name='测试公开媒体',published_at='2026-10-31T10:00:00+08:00',
            observed_at='2026-10-31T11:00:00+08:00',publication_precision='second',body_scope='visible_body',
            lanes=['hk_market','global_policy'])])


class IntakeTests(unittest.TestCase):
    def test_issuer_article_heading_and_explicit_edt_clock_override_empty_site_header(self):
        from app.services.web_research import parse_visible_article
        raw='<h1></h1><article class="full-news-article"><h1>Issuer Quarterly Financial Results</h1><time class="date">Oct 29, 2026 • 4:01 PM EDT</time><p>'+('Revenue and outlook with clearly separated reporting periods. '*8)+'</p></article>'
        n=parse_visible_article(raw,'https://www.intc.com/news-events/press-releases/detail/123/results',NOW,72)
        self.assertEqual(n.title,'Issuer Quarterly Financial Results')
        self.assertEqual(n.published_at,datetime(2026,10,30,4,1))
        with self.assertRaisesRegex(ValueError,'time_missing'):parse_visible_article(raw.replace(' EDT',''),'https://www.intc.com/news-events/press-releases/detail/123/results',NOW,72)

    def test_reexport_does_not_refresh_old_discovery_or_imply_search_occurred(self):
        d=bundle();d['search_receipts'][0]['checked_at']=(NOW-timedelta(hours=3)).isoformat()
        _,r=prepare(d,NOW);self.assertFalse(r['ready_for_public_collection'])
        d['search_receipts']=[];_,r=prepare(d,NOW)
        self.assertFalse(r['search_discovery_receipts_present']);self.assertFalse(r['ready_for_public_collection'])

    def test_forum_policy_words_do_not_outrank_actual_macro_or_market_reporting(self):
        from app.services.news_assignment import assess,order
        from app.services.market_coverage import coverage_role
        docs,_=prepare(bundle(),NOW);base=docs[0]
        comment=base.model_copy(update={'id':'comment','title':'要加息了？港股收盘复盘',
            'source':'公开参与者讨论-集思录','content':'[发言位置：a；公开账号：用户；发言时间：2026-10-31]\n要加息了吗？\n\n[原帖背景片段]订单库存同比下降20%。'})
        pmi=base.model_copy(update={'id':'macro','title':'统计师解读中国采购经理指数'})
        hk=base.model_copy(update={'id':'market','title':'10月行情收官：港股迎来反弹',
            'content':'恒生指数收盘上涨，恒生科技收盘表现分化。'})
        self.assertEqual(assess(comment)['lane'],'participant_discussion')
        self.assertEqual(assess(comment)['reading_priority'],1)
        self.assertIsNone(coverage_role(comment))
        self.assertEqual(coverage_role(hk),'hk_session')
        self.assertEqual(assess(pmi)['lane'],'macro_data')
        self.assertEqual([n.id for n in order([comment,pmi,hk])][-1],'comment')
        us=base.model_copy(update={'title':'美股收盘：三大指数全线收跌'})
        self.assertEqual(coverage_role(us),'us_session')
        self.assertEqual(coverage_role(base.model_copy(update={'title':'美股盘后：三大指数期货上涨'})),None)

    def test_industry_shipments_and_credit_costs_are_reading_leads_not_routine_reports(self):
        from app.services.news_assignment import assess
        docs,_=prepare(bundle(),NOW);n=docs[0]
        for title in ['全球智能手机出货量大跌22%，存储芯片报价上涨','AI融资潮：债券违约保护成本飙升']:
            self.assertEqual(assess(n.model_copy(update={'title':title}))['lane'],'industry_operating')
        self.assertEqual(assess(n.model_copy(update={'title':'AI行业计划增加资本开支'}))['reading_priority'],2)
        from app.services.company_news_scope import decision
        for title in ['光通信多家公司集体就业绩预期作出回应','白酒季报收官，多股涨停，业绩尚未改善']:
            self.assertTrue(decision(n.model_copy(update={'title':title}))['keep'])

    def test_saved_sina_notice_has_day_precision_and_checks_company_identity(self):
        from app.services.web_research import parse_visible_article
        url='https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=123&stockid=654321'
        raw='<title>新公司季度公告</title>公告日期:2026-10-31<div id="content">证券代码：654321'+('经营数据及表格，未逐项核实。'*12)+'</div>'
        n=parse_visible_article(raw,url,NOW,72)
        self.assertEqual(n.published_at,datetime(2026,10,31))
        self.assertIn('精度：day',n.market_impact)
        self.assertNotIn('公告日期',n.content)
        with self.assertRaisesRegex(ValueError,'not_admitted'):parse_visible_article(raw.replace('证券代码：654321','证券代码：123456'),url,NOW,72)

    def test_metadata_is_not_claimed_as_complete_or_independently_verified(self):
        docs,r=prepare(bundle(),NOW)
        self.assertEqual(len(docs),1);self.assertEqual(r['model_requests_performed'],0)
        self.assertEqual(r['quality_acceptance'],'pending_human_review')
        self.assertIn('a_market',r['missing_declared_lanes'])
        self.assertFalse(r['accepted'][0]['remote_version_checked'])
        self.assertEqual(r['watchlist_coverage'][0]['lexical_mentions'],[])

    def test_discussion_snippets_cannot_replace_primary_bodies(self):
        for scope in ('search_snippet','public_statement','feed_excerpt'):
            d=bundle();d['articles'][0]['body_scope']=scope
            with self.assertRaisesRegex(RuntimeError,'报道正文'):prepare(d,NOW)

    def test_exact_version_deduplicated_but_updated_body_and_other_url_retained(self):
        d=bundle();a=d['articles'][0];d['articles']+=[copy.deepcopy(a),dict(a,body=a['body']+'新增原文回应。'),dict(a,url='https://example.com/article/2')]
        docs,r=prepare(d,NOW)
        self.assertEqual(len(docs),3);self.assertEqual(len(r['rejected']),1)
        self.assertEqual(len({x.id for x in docs}),3)

    def test_observation_after_cutoff_is_rejected_without_dumping_raw_values(self):
        d=bundle();d['articles'].append(dict(d['articles'][0],observed_at='2026-10-31T13:00:00'))
        _,r=prepare(d,NOW)
        self.assertEqual(r['rejected'][0]['reason'],'body_observed_after_cutoff')
        d['articles'][1]['observed_at']='DO_NOT_PRINT_RAW_INPUT'
        _,r=prepare(d,NOW)
        self.assertNotIn('DO_NOT_PRINT_RAW_INPUT',str(r))

    def test_day_precision_remains_day_precision_and_boundary_is_quarantined(self):
        d=bundle();d['articles'][0].update(published_at='2026-10-31',publication_precision='day')
        docs,_=prepare(d,NOW)
        from app.services.evidence import publication_label
        self.assertIn('日精度',publication_label(docs[0]))
        d['articles'].append(dict(d['articles'][0],published_at='2026-10-28'))
        _,r=prepare(d,NOW)
        self.assertEqual(r['rejected'][0]['reason'],'day_window_boundary_requires_review')

    def test_future_publication_and_stale_body_not_silently_dated_today(self):
        d=bundle();d['articles']+=[dict(d['articles'][0],published_at='2026-10-31T13:00:00'),dict(d['articles'][0],published_at='2026-10-01T10:00:00')]
        _,r=prepare(d,NOW)
        self.assertEqual([x['reason'] for x in r['rejected']],['publication_after_observation','article_outside_window'])

    def test_agenda_tracks_changed_watchlist_without_hardcoded_stocks(self):
        d=bundle();d['watchlist']=[dict(code='654321',market='A',name='另一新公司')]
        _,r=prepare(d,NOW)
        self.assertTrue(any('另一新公司' in x['query'] for x in r['planned_searches']))
        self.assertFalse(any('牧原' in x['query'] for x in r['planned_searches']))


class FlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_capability_preview_reads_live_database_without_search_or_cached_watchlist(self):
        from app.primary_collection_check import preview
        with patch('app.services.watchlist_repository.read_app_watchlist',new=AsyncMock(return_value=bundle()['watchlist'])),\
             patch('app.services.web_research.search') as search:
            r=await preview()
        search.assert_not_called();self.assertEqual(r['http_requests_performed'],0)
        self.assertEqual(r['watchlist'][0]['code'],'01234')
        self.assertEqual(r['watchlist_status'],'read_from_app_database')

    async def test_stale_intake_does_not_start_collection_or_read_database(self):
        with patch('app.services.watchlist_repository.read_app_watchlist',new=AsyncMock()) as db:
            with self.assertRaisesRegex(RuntimeError,'超过2小时'):await collect(bundle(),NOW+timedelta(hours=3))
            db.assert_not_called()

    async def test_watchlist_changes_stop_before_public_collection(self):
        with patch('app.services.watchlist_repository.read_app_watchlist',new=AsyncMock(return_value=[])),\
             patch('app.services.news_collector.NewsCollectorService') as factory:
            with self.assertRaisesRegex(RuntimeError,'自选股已改变'):await collect(bundle(),NOW)
            factory.assert_not_called()

    async def test_public_flow_passes_primary_and_rechecks_watchlist_without_llm(self):
        n,_=prepare(bundle(),NOW);fake=Mock(_technical_snapshot={},_microstructure_snapshot={},_radar_coverage={})
        fake.collect_all=AsyncMock(return_value=n);fake.close=AsyncMock()
        with patch('app.services.watchlist_repository.read_app_watchlist',new=AsyncMock(return_value=bundle()['watchlist'])) as db,\
             patch('app.services.news_collector.NewsCollectorService',return_value=fake) as factory:
            r=await collect(bundle(),NOW)
        factory.assert_called_once_with(sentiment=False);self.assertEqual(db.await_count,2)
        self.assertIn('primary_news',fake.collect_all.call_args.kwargs)
        self.assertEqual(r['model_requests_performed'],0);self.assertTrue(r['watchlist_checked_against_app'])
        self.assertIsNone(r['http_requests_performed']);fake.close.assert_awaited_once()

    async def test_mid_collection_watchlist_change_does_not_return_publishable_snapshot(self):
        fake=Mock();fake.collect_all=AsyncMock(return_value=[]);fake.close=AsyncMock()
        with patch('app.services.watchlist_repository.read_app_watchlist',new=AsyncMock(side_effect=[bundle()['watchlist'],[]])),\
             patch('app.services.news_collector.NewsCollectorService',return_value=fake):
            with self.assertRaisesRegex(RuntimeError,'采集中'):await collect(bundle(),NOW)
        fake.close.assert_awaited_once()
