"""Meaningful acquisition progress and repair actions; no live transports."""
from copy import deepcopy
from datetime import datetime,timedelta
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,AsyncMock,patch

from app.models.news import News
from app.services.discovery_action_plan import reject_finish,action_plan
from app.services.discovery_budget import Limits
from app.services.discovery_feedback import build_feedback,lane_usage_allowed
from app.services.episode_workspace import EpisodeWorkspace
from app.services.collection_time import window
from app.services.primary_discovery import discover


class FinishProgressTests(unittest.TestCase):
    def state(self):
        return dict(candidates={'S1':dict(url='https://example.com/one')},
            collection_feedback=dict(bodies={'B1':dict(eligible=True,ranges=[[0,80]])}))

    def test_changed_problems_and_tasks_cannot_buy_another_finish(self):
        state=self.state();self.assertFalse(reject_finish(state)['stop'])
        state['finish_feedback']=dict(problems=[{'code':'different'}],actionable_unresolved_tasks=['different'])
        self.assertTrue(reject_finish(state)['stop'])

    def test_rewritten_dossier_does_not_reset_progress(self):
        state=self.state();reject_finish(state)
        state['proposed_dossier']=dict(events=[dict(title='重新写标题与顺序')],deferred_tasks=[])
        self.assertTrue(reject_finish(state)['stop'])

    def test_representing_old_context_is_not_new_acquisition(self):
        state=self.state();reject_finish(state)
        state['context_delivery']=dict(body_ranges={'B1':[[0,80]]},candidate_ids=['S1'])
        self.assertTrue(reject_finish(state)['stop'])

    def test_failed_attempt_counts_do_not_reset_progress(self):
        state=self.state();reject_finish(state)
        state.update(search_tool_calls=10,body_url_calls=20)
        self.assertTrue(reject_finish(state)['stop'])

    def test_new_candidate_opens_another_repair_opportunity(self):
        state=self.state();reject_finish(state)
        state['candidates']['S2']=dict(url='https://example.com/two')
        guard=reject_finish(state);self.assertFalse(guard['stop']);self.assertEqual(guard['rejections'],1)

    def test_new_body_range_opens_another_repair_opportunity(self):
        state=self.state();reject_finish(state)
        state['collection_feedback']['bodies']['B1']['ranges']=[[0,160]]
        self.assertFalse(reject_finish(state)['stop'])


class ActionPlanTests(unittest.TestCase):
    def fixture(self,scope=None):
        state=dict(candidates={'S2':dict(title='可供核对的候选',url='https://example.com/two',snippet='目录不是正文')})
        feedback=dict(tasks=[dict(task_id='scope:locate_body',kind='read_candidate',lane='company_event' if scope else 'us_market',
            scope=scope,question='请核对真实主体与范围',candidate_ids=['S2'],executable=True)])
        return state,feedback

    def test_options_preserve_choice_and_do_not_execute_tools(self):
        state,feedback=self.fixture();original=deepcopy(state)
        plan=action_plan(state,feedback)
        self.assertEqual(plan['tasks'][0]['candidate_options'][0]['candidate_id'],'S2')
        self.assertFalse(plan['tool_execution_performed']);self.assertEqual(state,original)
        self.assertNotIn('search_option',plan['tasks'][0])

    def test_direct_company_option_keeps_scope(self):
        state,feedback=self.fixture('A:600900')
        request=action_plan(state,feedback)['tasks'][0]['candidate_options'][0]['request_if_selected']
        self.assertEqual(request['relation'],'direct');self.assertEqual(request['scope'],'A:600900')

    def test_oversized_option_is_omitted_whole_not_truncated_into_evidence(self):
        state,feedback=self.fixture();state['candidates']['S2']['snippet']='原始完整摘要'*5000
        plan=action_plan(state,feedback,max_characters=2400)
        self.assertEqual(plan['tasks'][0]['candidate_options'],[])
        self.assertLessEqual(len(json.dumps(json.dumps(plan,ensure_ascii=False),ensure_ascii=False)),2400)

    def test_non_executable_task_is_not_a_tool_suggestion(self):
        state,feedback=self.fixture();feedback['tasks'][0]['executable']=False
        self.assertEqual(action_plan(state,feedback)['tasks'],[])


class CandidateUseTests(unittest.TestCase):
    def fixture(self,title,url,lane,*,scope=None,relation='market',purpose='latest_close'):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        now=datetime(2026,11,1,13,56)
        item=News(id='B1',title=title,content='公开正文中的原始事实、归属和限制需要核对。'*30,
            source='公开网页可见正文-example',source_url=url,published_at=now-timedelta(hours=30))
        workspace=EpisodeWorkspace([item],root=directory.name,now=now)
        stock=dict(market='A',code='600900',name='长江电力')
        link=dict(lane=lane,purpose=purpose,scope=scope)
        request=dict(tool='read',candidate_id='S1',relation=relation)
        if scope:request['scope']=scope
        state=dict(candidates={'S1':dict(url=url,title=title,discovered_by=[link])},
            receipts=[dict(request=request,result=dict(status='ok',material=workspace.read('B1'),source_window=window(now,purpose)))],
            effective_search_limit=4,model_calls=1,search_tool_calls=1,body_url_calls=1,local_read_characters=0)
        return workspace,state,[stock] if scope else []

    def test_bank_commentary_is_not_recommended_to_close_policy_gap(self):
        workspace,state,stocks=self.fixture('FX Daily Snapshot','https://www.mufgresearch.com/fx/snapshot',
            'global_policy',purpose='commentary')
        feedback=build_feedback(workspace,state,stocks,Limits())
        task=next(t for t in feedback['tasks'] if t['task_id']=='lane:global_policy:locate_body')
        self.assertNotIn('S1',task['candidate_ids'])

    def test_morning_report_is_not_recommended_to_close_settlement_gap(self):
        workspace,state,stocks=self.fixture('Gold - Kitco AM Report','https://www.kitco.com/news/morning','commodities')
        feedback=build_feedback(workspace,state,stocks,Limits())
        task=next(t for t in feedback['tasks'] if t['task_id']=='lane:commodities:locate_body')
        self.assertNotIn('S1',task['candidate_ids'])

    def test_other_company_cache_does_not_become_direct_company_option(self):
        workspace,state,stocks=self.fixture('华能水电业绩与同行对比','https://example.com/peer',
            'company_event',scope='A:600900',purpose='company_event')
        feedback=build_feedback(workspace,state,stocks,Limits())
        task=next(t for t in feedback['tasks'] if t['task_id']=='stock:A:600900:locate_body')
        self.assertNotIn('S1',task['candidate_ids'])

    def test_matching_cached_company_can_be_read_explicitly_as_direct(self):
        workspace,state,stocks=self.fixture('长江电力披露经营变化','https://example.com/company',
            'company_event',scope='A:600900',purpose='company_event')
        feedback=build_feedback(workspace,state,stocks,Limits())
        task=next(t for t in feedback['tasks'] if t['task_id']=='stock:A:600900:locate_body')
        self.assertIn('S1',task['reusable_candidate_ids'])

    def test_weekend_policy_uses_its_own_window_instead_of_market_window(self):
        workspace,state,_=self.fixture('Policy decision statement','https://centralbank.example/release',
            'global_policy',purpose='released_policy')
        item=workspace.documents['B1'];item.published_at=workspace.now-timedelta(hours=110)
        windows=[window(workspace.now,'released_policy')]
        self.assertTrue(lane_usage_allowed(item,'global_policy',windows,workspace.now))
        self.assertFalse(lane_usage_allowed(item,'us_market',windows,workspace.now))

    def test_background_window_does_not_certify_commodity_settlement(self):
        workspace,state,_=self.fixture('Commodity views','https://example.com/views','commodities',purpose='commentary')
        self.assertFalse(lane_usage_allowed(workspace.documents['B1'],'commodities',
            [window(workspace.now,'commentary')],workspace.now))


class FinishControllerTests(unittest.IsolatedAsyncioTestCase):
    # Reuse the existing injected transports without inheriting its test cases.
    def setUp(self):
        from test_discovery_feedback import FeedbackLoopTests
        FeedbackLoopTests.setUp(self)

    def reader(self,*args,**kwargs):
        from test_discovery_feedback import FeedbackLoopTests
        return FeedbackLoopTests.reader(self,*args,**kwargs)

    async def collect(self,*args,**kwargs):
        from test_discovery_feedback import FeedbackLoopTests
        return await FeedbackLoopTests.collect(self,*args,**kwargs)

    async def test_changing_scope_errors_stops_after_two_rejected_finishes(self):
        from test_discovery_feedback import tool,query,read,finish
        def wrong(lane):
            def response(feedback):
                value=finish(feedback,False)
                row=next(r for r in value['coverage'] if r['lane']==lane)
                row.update(status='body_provided',evidence_ids=['evidence-close'])
                return value
            return response
        state=await self.collect([tool(query()),tool(read()),wrong('global_policy'),wrong('commodities')])
        self.assertEqual(state['status'],'stalled_no_new_evidence')
        self.assertEqual(state['model_calls'],4);self.assertEqual(self.search.call_count,1)
        self.assertEqual(state['finish_loop_guard']['rejections'],2)
        self.assertIn('finish_repair',self.model.call_args.args[1][0]['content'])

    async def test_a_tool_response_can_resolve_or_defer_after_the_repair_hint(self):
        from test_discovery_feedback import tool,query,read,finish
        state=await self.collect([tool(query()),tool(read()),lambda f:finish(f,False),
            tool(query('global_policy','New central bank statement')),lambda f:finish(f)])
        self.assertEqual(state['status'],'partial_materials_for_human_review')
        self.assertEqual(self.search.call_count,2)

    async def test_resumed_stored_tail_is_provided_before_the_first_paid_request(self):
        from test_recovered_collection import fixture,config
        from app.config import settings
        from app.services.discovery_recovery import prepare_saved
        with tempfile.TemporaryDirectory() as directory:
            workspace,result,item=fixture(directory)
            item.content='经营事实与限制。'*650+'末段关键反证。'
            memory,state,digest=prepare_saved(result,workspace.path,Mock(return_value=item))
            memory.path=Path(directory)/'continued';memory.path.mkdir()
            model=AsyncMock(side_effect=RuntimeError('observe only'))
            with patch.multiple(settings,**config()):
                with self.assertRaisesRegex(RuntimeError,'observe only'):
                    await discover(memory,state['watchlist'],model=model,search=Mock(),read=Mock(),
                        resume=dict(research=state,recovery_state_sha256=digest,model_exposures=result['model_exposures'],
                            active_seconds=160,search_http_attempts=1))
            self.assertIn('末段关键反证。',model.call_args.args[1][0]['content'])
            checkpoint=json.loads((memory.path/'primary-discovery.json').read_text())
            self.assertGreater(checkpoint['local_read_characters'],state['local_read_characters'])
