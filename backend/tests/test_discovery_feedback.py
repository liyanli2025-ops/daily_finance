"""Controller behavior across tasks/dates; mocked transport is not live acceptance."""
import json
import tempfile
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

from app.models.news import News
from app.services.discovery_feedback import build_feedback, body_records, complete_local_reads
from app.services.episode_workspace import EpisodeWorkspace
from app.services.primary_discovery import discover, Limits
from app.services.primary_report import export_discovery, prepare


def tool(*requests):
    return json.dumps(dict(action='tools', requests=list(requests)), ensure_ascii=False)


def query(lane='us_market', text='Latest completed US session close'):
    return dict(tool='search', lane=lane, query=text, reason='查本期实际缺口')


def read(candidate_id='S1', **kwargs):
    return dict(tool='read', candidate_id=candidate_id, relation='market', reason='选择对应来源', **kwargs)


def current_feedback(messages):
    return json.JSONDecoder().raw_decode(messages[0]['content'].rsplit('collection_feedback：', 1)[1])[0]


def finish(feedback, defer=True):
    return dict(action='finish', events=[], omissions=[],
        coverage=[dict(lane=row['lane'], status='body_provided' if row['body_ids'] else 'missing',
            evidence_ids=row['body_ids'], explanation='按实际研究关联，未查方向保留缺口') for row in feedback['lanes']],
        watchlist_checks=[dict(key=row['key'].removeprefix('stock:'),
            status='body_provided' if row['body_ids'] else 'missing', evidence_ids=row['body_ids'],
            explanation='只把当前主体直接阅读计入') for row in feedback['watchlist']],
        deferred_tasks=[dict(task_id=t['task_id'], reason='在本用例范围外，明确保留未解决项')
                        for t in feedback['tasks']] if defer else [])


class FeedbackLoopTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.now=datetime(2026, 10, 31, 16)
        self.workspace=EpisodeWorkspace([], root=self.directory.name, now=self.now)
        self.search=Mock(return_value=dict(status='ok', results=[
            dict(title='Market close and actual drivers', snippet='Completed session',
                 url='https://example.com/markets/close')]))
        self.content='市场事实、归属和不同解释需要保留。'*30

    def reader(self, workspace, url, **kwargs):
        item=News(id='evidence-'+url.rsplit('/',1)[-1], title='当期市场材料', content=self.content,
            source='公开网页可见正文-example', source_url=url, published_at=workspace.now)
        workspace.add([item])
        return dict(status='ok', material=workspace.read(item.id, characters=kwargs['characters']))

    async def collect(self, actions, *, stocks=None, limits=None):
        decisions=iter(actions)
        async def model(task, messages, max_tokens):
            action=next(decisions)
            if callable(action):
                action=action(current_feedback(messages))
            return json.dumps(action,ensure_ascii=False) if isinstance(action,dict) else action
        self.model=AsyncMock(side_effect=model)
        return await discover(self.workspace, stocks or [], limits=limits or Limits(),
            model=self.model, search=self.search, read=self.reader)

    async def test_early_finish_receives_gaps_then_continues_in_original_budget(self):
        state=await self.collect([tool(query()), tool(read()), lambda f:finish(f,False),
            tool(query('global_policy','Latest released central bank statement')), lambda f:finish(f)],
            limits=Limits(model_calls=5))
        self.assertFalse(state['finish_feedback_history'][0]['accepted'])
        self.assertIn('lane:industry:locate_body',state['finish_feedback_history'][0]['actionable_unresolved_tasks'])
        self.assertEqual(self.search.call_count,2)
        self.assertEqual(state['model_calls'],5)
        self.assertEqual(state['status'],'partial_materials_for_human_review')

    async def test_long_body_is_completed_locally_including_tail_counter_evidence(self):
        self.content='逐段经营事实和行业条件。'*650+'末段反证：需求预测存在回落风险。'
        state=await self.collect([tool(query()),tool(read()),lambda f:finish(f)],limits=Limits(model_calls=3))
        row=state['collection_feedback']['bodies']['evidence-close']
        self.assertEqual(row['unread_ranges'],[])
        self.assertEqual(row['ranges'],[[0,len(self.content)]])
        self.assertEqual(state['body_url_calls'],1)
        auto=[r for r in state['receipts'] if r.get('origin')=='controller_local_completion']
        self.assertTrue(auto)
        self.assertIn('末段反证',''.join(r['result']['text'] for r in auto))

    async def test_local_budget_exhaustion_preserves_unread_intervals(self):
        self.content='需核对的长正文及末段信息。'*600
        state=await self.collect([tool(query()),tool(read()),lambda f:finish(f)],
            limits=Limits(model_calls=3,local_read_characters=0))
        self.assertEqual(state['local_read_characters'],0)
        self.assertTrue(state['collection_feedback']['bodies']['evidence-close']['unread_ranges'])
        self.assertEqual(state['status'],'partial_materials_for_human_review')
        value=export_discovery(self.workspace,state)
        self.assertTrue(value['reading_coverage'][0]['unread_ranges'])

    async def test_last_turn_does_not_accept_unrelated_scope_claim(self):
        def wrong_scope(feedback):
            result=finish(feedback)
            result['coverage'][5].update(status='body_provided',evidence_ids=['evidence-close'])
            return result
        state=await self.collect([tool(query()),tool(read()),wrong_scope],limits=Limits(model_calls=3))
        self.assertEqual(state['status'],'finish_not_supported_by_receipts')
        self.assertIn('body_not_read_for_claimed_scope',
            [r['code'] for r in state['finish_feedback']['problems']])

    async def test_repeated_cached_query_stops_without_extra_rounds(self):
        state=await self.collect([tool(query()),tool(query()),tool(query())])
        self.assertEqual(state['status'],'stalled_no_new_evidence')
        self.assertEqual(state['model_calls'],3)
        self.search.assert_called_once()

    async def test_repeating_the_same_early_finish_does_not_buy_all_remaining_rounds(self):
        state=await self.collect([tool(query()),tool(read()),lambda f:finish(f,False),lambda f:finish(f,False)])
        self.assertEqual(state['status'],'stalled_no_new_evidence')
        self.assertEqual(state['model_calls'],4)
        self.assertEqual(state['phase'],'repeated_finish_without_progress')

    async def test_promotional_body_is_retained_but_not_exported_with_alternative(self):
        self.search.return_value['results'].append(dict(title='Alternative source',snippet='Independent account',
            url='https://example.com/markets/alternative'))
        base_reader=self.reader
        def reader(workspace,url,**kwargs):
            old=self.content
            try:
                if url.endswith('/close'):self.content+='立即下单'
                return base_reader(workspace,url,**kwargs)
            finally:self.content=old
        self.reader=reader
        state=await self.collect([tool(query()),tool(read()),tool(read('S2')),lambda f:finish(f)],
            limits=Limits(model_calls=4))
        value=export_discovery(self.workspace,state)
        self.assertEqual([n['id'] for n in value['news']],['evidence-alternative'])
        self.assertEqual(value['unselected_provided_ids'],['evidence-close'])
        self.assertIn('立即下单',self.workspace.documents['evidence-close'].content)
        self.assertFalse(prepare(value,now=self.now)[2]['body_quality_review_required'])

    async def test_dynamic_watchlist_and_date_do_not_reuse_an_old_company(self):
        profiles=[(datetime(2026,11,2,9),[dict(market='A',code='002594',name='比亚迪')]),
                  (datetime(2027,2,4,18),[dict(market='HK',code='00941',name='中国移动')])]
        for now,stocks in profiles:
            with self.subTest(now=now,stocks=stocks):
                self.workspace=EpisodeWorkspace([],root=self.directory.name,now=now)
                stock=stocks[0];scope=stock['market']+':'+stock['code']
                self.search.return_value=dict(status='ok',results=[dict(title=stock['name']+'发布经营信息',
                    snippet=stock['code'],url='https://example.com/companies/release')])
                self.content=(stock['name']+' '+stock['code']+' 本期经营变化与风险。')*30
                request=read();request.update(relation='direct',scope=scope)
                search_request=query('company_event',stock['name']+' '+stock['code']+' 新增经营信息')
                search_request['scope']=scope
                state=await self.collect([tool(search_request),tool(request),lambda f:finish(f)],stocks=stocks,
                    limits=Limits(model_calls=3))
                self.assertEqual(state['watchlist'],stocks)
                self.assertEqual(state['started_at'],now.isoformat())
                self.assertEqual(state['collection_feedback']['watchlist'][0]['body_ids'],['evidence-release'])
                industry=next(r for r in state['collection_feedback']['lanes'] if r['lane']=='industry')
                self.assertEqual(industry['body_ids'],[])

    async def test_no_new_search_is_bought_when_new_body_budget_is_exhausted(self):
        state=await self.collect([tool(query()),tool(read()),
            tool(query('industry','New industry supply data')),lambda f:finish(f)],
            limits=Limits(model_calls=4,body_urls=1))
        self.search.assert_called_once()
        self.assertEqual(state['receipts'][2]['result']['reason'],'no_body_budget_for_new_search')
        self.assertFalse(next(t for t in state['collection_feedback']['tasks']
            if t['task_id']=='lane:industry:locate_body')['executable'])

    async def test_default_search_unavailable_stops_before_buying_a_model_decision(self):
        model=AsyncMock()
        with patch('app.services.web_research.search_availability',return_value=dict(available=False,reason='search_disabled')):
            with self.assertRaisesRegex(RuntimeError,'discovery_search_unavailable_before_model'):
                await discover(self.workspace,[],model=model,read=self.reader)
        model.assert_not_awaited()

    async def test_scoped_search_can_read_ambiguous_title_then_check_the_body(self):
        stocks=[dict(market='HK',code='00941',name='中国移动')]
        search_request=query('company_event','中国移动 00941 最新公告')
        search_request['scope']='HK:00941'
        self.search.return_value['results'][0].update(title='经营情况公告',snippet='本月经营数据')
        self.content='中国移动 00941 经营数据与风险说明。'*30
        request=read();request.update(relation='direct',scope='HK:00941')
        state=await self.collect([tool(search_request),tool(request),lambda f:finish(f)],stocks=stocks,
            limits=Limits(model_calls=3))
        self.assertEqual(state['collection_feedback']['watchlist'][0]['body_ids'],['evidence-close'])

    async def test_wrong_company_body_can_be_reused_for_another_purpose_without_another_url_call(self):
        stocks=[dict(market='HK',code='00941',name='中国移动')]
        search_request=query('company_event','中国移动 00941 最新公告')
        search_request['scope']='HK:00941'
        self.search.return_value['results'][0].update(title='经营情况公告',snippet='报告正文待核')
        self.content='其他公司披露的经营数据与风险。'*30
        request=read();request.update(relation='direct',scope='HK:00941')
        state=await self.collect([tool(search_request),tool(request),tool(read()),lambda f:finish(f)],stocks=stocks,
            limits=Limits(model_calls=4,body_urls=1))
        self.assertEqual(state['receipts'][1]['result']['reason'],'direct_company_not_in_body')
        self.assertTrue(state['receipts'][2]['result']['reused'])
        self.assertEqual(state['body_url_calls'],1)
        self.assertEqual(state['collection_feedback']['watchlist'][0]['body_ids'],[])
        self.assertTrue(next(r for r in state['collection_feedback']['lanes'] if r['lane']=='company_event')['body_ids'])


    async def test_default_planning_and_finish_share_the_existing_model_calls(self):
        actions=iter([tool(query()),tool(read()),None])
        async def model(task,messages,max_tokens):
            action=next(actions)
            return action if action else json.dumps(finish(current_feedback(messages)),ensure_ascii=False)
        model=AsyncMock(side_effect=model)
        from app.config import settings
        with patch.object(settings,'model_max_calls_per_report',8), patch.object(settings,'research_max_model_calls',None):
            state=await discover(self.workspace,[],model=model,search=self.search,read=self.reader)
        self.assertEqual(state['budget_plan']['mode'],'progress_driven_collection')
        self.assertIsNone(state['limits']['model_calls'])
        self.assertEqual(state['model_calls'],3)
        self.assertEqual(model.await_count,3)
        self.assertEqual(state['budget_expansions'],[])

    async def test_default_collection_can_research_beyond_five_model_calls(self):
        from app.config import settings
        number=0
        def search(workspace,query,**kwargs):
            nonlocal number
            number+=1
            return dict(status='ok',results=[dict(title='当期市场新材料',snippet='待核对',
                url='https://example.com/news/new-'+str(number))])
        actions=iter([tool(query(text='Question one')),tool(read('S1')),
            tool(query(text='Question two')),tool(read('S2')),
            tool(query(text='Question three')),tool(read('S3')),None])
        async def reply(task,messages,max_tokens):
            action=next(actions)
            return action if action else json.dumps(finish(current_feedback(messages)),ensure_ascii=False)
        model=AsyncMock(side_effect=reply)
        with patch.object(settings,'research_max_model_calls',None):
            state=await discover(self.workspace,[],model=model,search=search,read=self.reader)
        self.assertEqual(state['model_calls'],7)
        self.assertEqual(model.await_count,7)
        self.assertEqual(state['collection_completion']['status'],'incomplete')
        self.assertTrue(state['collection_completion']['scope_gaps'])

    async def test_cumulative_input_and_output_limits_stop_before_model_requests(self):
        from app.config import settings
        for field,status in [('research_total_input_characters','cumulative_input_budget_exhausted'),
                             ('research_total_output_tokens','cumulative_output_budget_exhausted')]:
            with self.subTest(field=field),patch.object(settings,field,1):
                model=AsyncMock(side_effect=AssertionError('no paid request'))
                state=await discover(self.workspace,[],model=model,search=self.search,read=self.reader)
                self.assertEqual(state['status'],status)
                model.assert_not_awaited()

    async def test_expansion_is_processed_inside_the_existing_tool_reply(self):
        from dataclasses import replace
        initial=Limits(model_calls=5,search_calls=1,body_urls=1)
        ceiling=replace(initial,search_calls=5,body_urls=9)
        count=0
        def search(workspace,query,**kwargs):
            nonlocal count
            count+=1
            return dict(status='ok',results=[dict(title='Market or industry evidence',snippet='新增正文候选',
                url='https://example.com/news/'+('close' if count==1 else 'industry'))])
        proposal=dict(task_ids=['lane:industry:locate_body'],reason='重要行业变化仍缺原始正文，继续定向查找')
        expanded_tool=json.loads(tool(query('industry','Industry actual changes')))
        expanded_tool['budget_extension']=proposal
        actions=iter([tool(query()),tool(read()),json.dumps(expanded_tool),tool(read('S2')),None])
        async def reply(task,messages,max_tokens):
            action=next(actions)
            return action if action else json.dumps(finish(current_feedback(messages)),ensure_ascii=False)
        model=AsyncMock(side_effect=reply)
        plan=dict(mode='task_scaled_with_gap_batches',initial=initial.__dict__,ceiling=ceiling.__dict__)
        with patch('app.services.primary_discovery.plan_budget',return_value=(initial,ceiling,plan)):
            state=await discover(self.workspace,[],model=model,search=search,read=self.reader)
        self.assertEqual(state['model_calls'],5)
        self.assertEqual(model.await_count,5)
        self.assertEqual(state['limits']['body_urls'],9)
        self.assertEqual(state['budget_expansions'][0]['status'],'expanded')
        self.assertEqual(state['search_tool_calls'],2)
        self.assertEqual(state['body_url_calls'],2)
        self.assertEqual(state['provided_ids'],['evidence-close','evidence-industry'])

    async def test_two_empty_search_rounds_stop_even_when_counters_increase(self):
        self.search.return_value=dict(status='ok',results=[])
        state=await self.collect([tool(query()),tool(query(text='Different search without new results'))])
        self.assertEqual(state['status'],'stalled_no_new_evidence')
        self.assertEqual(state['search_tool_calls'],2)
        self.assertEqual(state['model_calls'],2)


class FairLocalReadingTests(unittest.TestCase):
    def test_early_round_leaves_automatic_budget_for_later_selected_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            now=datetime(2026,11,1,10)
            item=News(id='first',title='当期完整原始材料',content='保留经营资料与反方信息。'*900,
                source='公开网页可见正文-example',source_url='https://example.com/first',published_at=now)
            workspace=EpisodeWorkspace([item],root=directory,now=now)
            state=dict(provided_ids=['first'],model_calls=2,local_read_characters=0,
                receipts=[dict(request={'tool':'read'},result=dict(status='ok',material=workspace.read('first',characters=4000)))])
            complete_local_reads(workspace,state,Limits(model_calls=6,local_read_characters=1200),
                room_for_text=lambda:10000,checkpoint=lambda:None)
            self.assertEqual(state['local_read_characters'],300)
            self.assertTrue(body_records(workspace,state['receipts'])['first']['unread_ranges'])

    def test_small_budget_checks_each_source_ending_in_receipt_order(self):
        with tempfile.TemporaryDirectory() as directory:
            now=datetime(2026,11,1,10)
            items=[News(id=identifier,title='原始资料与反方信息',content='原文信息与不同解释。'*800+'后段风险提示',
                source='公开网页可见正文-example',source_url='https://example.com/'+identifier,published_at=now)
                for identifier in ['z-first','a-second']]
            workspace=EpisodeWorkspace(items,root=directory,now=now)
            state=dict(provided_ids=sorted(n.id for n in items),local_read_characters=0,receipts=[])
            for item in items:
                state['receipts'].append(dict(request={'tool':'read'},
                    result=dict(status='ok',material=workspace.read(item.id,characters=4000))))
            complete_local_reads(workspace,state,Limits(local_read_characters=1000),
                room_for_text=lambda:10000,checkpoint=lambda:None)
            auto=[r for r in state['receipts'] if r.get('origin')=='controller_local_completion']
            self.assertEqual([r['result']['id'] for r in auto],['z-first','a-second'])
            self.assertEqual([len(r['result']['text']) for r in auto],[500,500])
            self.assertTrue(all('后段风险提示' in r['result']['text'] for r in auto))
            self.assertTrue(all(row['unread_ranges'] for row in body_records(workspace,state['receipts']).values()))
