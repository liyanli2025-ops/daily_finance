import json,tempfile,unittest
from datetime import datetime
from unittest.mock import AsyncMock,Mock,patch

from app.config import settings
from app.models.news import News
from app.services.episode_workspace import EpisodeWorkspace
from app.services.primary_discovery import Limits,discover,prompt
from app.services.search_primary_collection import LANES

NOW=datetime(2026,10,31,16)
STOCKS=[dict(market='A',code='002714',name='牧原股份')]
URL='https://example.com/news/us-close'


def tools(*rows):return json.dumps(dict(action='tools',requests=list(rows)),ensure_ascii=False)
def search(query='US market close',lane='us_market'):
    return dict(tool='search',query=query,lane=lane,reason='寻找最近已完成交易日收盘，不自动读首条')
def read(identifier='S1',**kwargs):
    return dict(tool='read',candidate_id=identifier,relation='market',reason='直接解释市场异动',**kwargs)
def finish(ids=(),events=None):
    return json.dumps(dict(action='finish',events=events or [],
        coverage=[dict(lane=x,status='body_provided' if ids and x=='us_market' else 'missing',
                       evidence_ids=list(ids) if x=='us_market' else [],explanation='样本范围；其余未查，不声称无消息') for x in LANES],
        watchlist_checks=[dict(key='A:002714',status='missing',evidence_ids=[],explanation='未查公司消息')],omissions=[]))


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.ws=EpisodeWorkspace([],root=self.tmp.name,now=NOW)
        self.query=Mock(return_value=dict(status='ok',results=[dict(title='美国股票收盘',url=URL,snippet='纳指与大盘分化')]))
        self.reader=Mock(side_effect=self.body)

    def body(self,workspace,url,**kwargs):
        item=News(id='B1',title='市场变化',content='实际可见正文，保留日期和观点归属。'*30,
                  source='公开网页可见正文-示例',source_url=url,published_at=NOW)
        workspace.add([item]);return dict(status='ok',url=url,material=workspace.read('B1',characters=4000))

    async def run_decisions(self,decisions,**kwargs):
        self.model=AsyncMock(side_effect=decisions)
        return await discover(self.ws,STOCKS,model=self.model,search=self.query,read=self.reader,**kwargs)

    async def test_model_selects_second_result_instead_of_first(self):
        self.query.return_value['results'].insert(0,dict(title='台湾股市收盘',url='https://example.com/news/taiwan',snippet='台湾股票'))
        r=await self.run_decisions([tools(search()),tools(read('S2')),finish(['B1'],[
            dict(title='美股收盘',why_it_matters='指数与行业分化',evidence_ids=['B1'],caveats='只读示例正文，未独立核实')])])
        self.assertEqual(self.reader.call_args.args[1],URL)
        self.assertEqual(r['status'],'partial_materials_for_human_review')
        self.assertIn('global_policy',r['coverage_gaps'])
        self.assertEqual(r['model_calls'],3);self.assertEqual(r['provided_ids'],['B1'])
        self.assertTrue((self.ws.path/'primary-discovery.json').exists())

    async def test_irrelevant_company_cannot_be_direct_watchlist_body(self):
        self.query.return_value['results'][0].update(title='山东药玻上市保荐书',snippet='600529')
        r=await self.run_decisions([tools(search('牧原股份 季报','company_event')),
            tools(dict(tool='read',candidate_id='S1',relation='direct',scope='A:002714',reason='公司直接信息')),finish()])
        self.reader.assert_not_called();self.assertEqual(r['receipts'][1]['result']['reason'],'direct_company_not_in_candidate')
        self.assertEqual(r['status'],'insufficient_body_evidence')

    async def test_index_landing_is_not_read_as_news(self):
        self.query.return_value['results'][0]['url']='https://www.hsi.com.hk/chi/indexes/all-indexes/hsi'
        r=await self.run_decisions([tools(search()),tools(read()),finish()])
        self.reader.assert_not_called();self.assertEqual(r['receipts'][1]['result']['reason'],'article_landing_page_not_body')

    async def test_body_failure_allows_different_source_not_failed_url_retry(self):
        self.query.return_value['results'].append(dict(title='另一来源',url='https://example.com/news/other',snippet='独立解释'))
        first=dict(status='failed',reason='ConnectTimeoutError')
        self.reader.side_effect=[first,lambda:None]
        def reader(ws,url,**kwargs):return first if url==URL else self.body(ws,url,**kwargs)
        self.reader.side_effect=reader
        r=await self.run_decisions([tools(search()),tools(read()),tools(read(),read('S2')),finish(['B1'])])
        self.assertEqual(self.reader.call_count,2);self.assertEqual(r['body_url_calls'],2)
        self.assertTrue(r['receipts'][2]['result']['reused'])

    async def test_same_query_does_not_spend_search_twice(self):
        r=await self.run_decisions([tools(search()),tools(search('US   market close')),finish()])
        self.query.assert_called_once();self.assertTrue(r['receipts'][1]['result']['reused'])

    async def test_local_continuation_reads_later_text_without_new_http(self):
        r=await self.run_decisions([tools(search()),tools(read()),
            tools(dict(tool='read_more',id='B1',offset=120,characters=180,reason='补读后部细节')),finish(['B1'])])
        self.reader.assert_called_once();self.assertEqual(r['body_url_calls'],1)
        self.assertEqual(r['receipts'][2]['result']['offset'],120)

    async def test_bad_packet_validated_before_first_paid_search(self):
        with self.assertRaises(ValueError):await self.run_decisions([tools(search(),dict(tool='invented',reason='x'))])
        self.query.assert_not_called()

    async def test_search_account_failure_stops_provider_retests(self):
        self.query.return_value=dict(status='failed',reason='http_401',results=[])
        r=await self.run_decisions([tools(search()),tools(search('美国市场 收盘')),finish()])
        self.query.assert_called_once();self.assertEqual(r['receipts'][1]['result']['reason'],'search_route_failed_no_retest')

    async def test_exhausted_model_never_repairs_or_publishes(self):
        r=await self.run_decisions([tools(search())],limits=Limits(model_calls=1))
        self.assertEqual(r['status'],'model_budget_exhausted');self.assertEqual(self.model.await_count,1)

    async def test_search_budget_not_article_quota(self):
        r=await self.run_decisions([tools(search(),search('Fed rates')),finish()],limits=Limits(search_calls=1))
        self.query.assert_called_once();self.assertEqual(r['receipts'][1]['result']['status'],'budget_exhausted')

    async def test_catalogue_cannot_be_used_as_event_evidence(self):
        with self.assertRaisesRegex(ValueError,'unprovided_evidence'):
            await self.run_decisions([tools(search()),finish(['S1'])])

    async def test_coverage_must_include_every_dynamic_stock_and_lane(self):
        incomplete=json.loads(finish());incomplete['watchlist_checks']=[]
        with self.assertRaisesRegex(ValueError,'coverage_missing'):await self.run_decisions([json.dumps(incomplete)])

    async def test_no_body_means_incomplete_even_when_model_says_finish(self):
        r=await self.run_decisions([finish()]);self.assertEqual(r['status'],'insufficient_body_evidence')
        self.query.assert_not_called();self.reader.assert_not_called()

    async def test_input_guard_stops_before_any_model_call(self):
        r=await self.run_decisions([],limits=Limits(input_characters=10))
        self.model.assert_not_called();self.assertEqual(r['status'],'input_budget_exhausted')

    async def test_maintenance_pause_cannot_be_overridden_by_controller(self):
        marker=self.ws.path/'pause';marker.write_text('paused')
        with patch('app.services.model_gateway.MODEL_PAUSE_FILE',marker),patch('app.services.model_gateway.httpx.AsyncClient') as client:
            with self.assertRaisesRegex(RuntimeError,'维护暂停'):
                await discover(self.ws,STOCKS,search=self.query,read=self.reader)
        client.assert_not_called();self.query.assert_not_called()


class BriefTests(unittest.TestCase):
    def test_shared_brief_keeps_global_and_participant_requirements(self):
        value=prompt([dict(market='HK',code='01234',name='动态公司')],NOW,Limits())
        for phrase in ('美股与重要外盘','知情人士','猜测','原始','动态公司','HK','交易日期','候选'):
            self.assertIn(phrase,value)
        self.assertNotIn('2026年10月31日 A股 最近交易日',value)
        self.assertNotIn('牧原股份',value)

    def test_invalid_cost_limits_rejected(self):
        with self.assertRaises(ValueError):Limits(model_calls=50)
