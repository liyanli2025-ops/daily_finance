"""Budget regression specifications. Mocked states are not live quality acceptance."""
from dataclasses import replace
from types import SimpleNamespace
import unittest

from app.services.discovery_budget import Limits, plan_budget, expand_budget


def configuration(**overrides):
    values = dict(model_max_calls_per_report=8, research_max_model_calls=None,
        research_total_input_characters=2000000,research_total_output_tokens=120000,
        research_web_search_max_requests=24, research_body_max_urls=64,
        research_input_max_characters=160000, research_local_read_max_characters=96000,
        research_max_seconds=900)
    return SimpleNamespace(**(values | overrides))


class AdaptiveBudgetTests(unittest.TestCase):
    def setUp(self):
        self.initial, self.ceiling, self.plan = plan_budget(0, 7, configuration())
        self.task = dict(task_id='lane:industry:locate_body', kind='search_alternative',
                         lane='industry', scope=None, candidate_ids=['S1'])
        self.state = dict(model_calls=2, body_url_calls=16, search_tool_calls=8,
            local_read_characters=0, candidates={'S1':dict(url='https://example.com/news/source')},
            collection_feedback=dict(tasks=[self.task], bodies={}))
        self.proposal = dict(task_ids=[self.task['task_id']], reason='重要行业变化仍缺可核对正文，已有新候选')
        self.requests = [dict(tool='read', candidate_id='S1')]

    def expand(self, **kwargs):
        return expand_budget(self.initial, self.ceiling, self.state, self.proposal,
            requests=self.requests, elapsed=100, input_characters=10000, **kwargs)

    def test_scales_resources_with_independent_report_budget(self):
        larger, ceiling, plan = plan_budget(4, 7, configuration())
        self.assertEqual((larger.search_calls, larger.body_urls, larger.local_read_characters), (11,22,44000))
        self.assertEqual(larger.input_characters, 108000)
        self.assertIsNone(larger.model_calls)
        self.assertEqual(larger.tool_requests_per_turn, 11)
        self.assertEqual(plan['report_model_calls_independent'],8)
        self.assertEqual(plan['total_input_characters'],2000000)
        self.assertEqual(ceiling.body_urls, 64)

    def test_existing_lower_configuration_remains_binding(self):
        initial, ceiling, _ = plan_budget(100, 7, configuration(research_web_search_max_requests=4,
            research_body_max_urls=10, research_local_read_max_characters=0))
        self.assertEqual((initial.search_calls,initial.body_urls,initial.local_read_characters),(4,10,0))
        self.assertEqual(initial.search_calls,ceiling.search_calls)

    def test_report_cap_does_not_limit_collection_but_explicit_emergency_cap_does(self):
        initial,_,_=plan_budget(0,7,configuration(model_max_calls_per_report=1))
        self.assertIsNone(initial.model_calls)
        initial,_,_=plan_budget(0,7,configuration(research_max_model_calls=9))
        self.assertEqual(initial.model_calls,9)

    def test_gap_batch_expands_search_and_read_together_but_not_models(self):
        expanded, record = self.expand()
        self.assertEqual((expanded.search_calls,expanded.body_urls),(12,24))
        self.assertEqual(expanded.model_calls,self.initial.model_calls)
        self.assertEqual(record['status'],'expanded')
        self.state['last_budget_expansion_progress']=record['progress']
        unchanged, record=self.expand()
        self.assertEqual(unchanged,self.initial)
        self.assertEqual(record['decision_reason'],'no_new_candidates_or_body_ranges')

    def test_empty_or_failed_attempts_do_not_unlock_expansion(self):
        self.state['candidates']={}
        self.state['search_tool_calls']=100
        unchanged,record=self.expand()
        self.assertEqual(unchanged,self.initial)
        self.assertEqual(record['status'],'declined')

    def test_task_must_match_actual_planned_tools(self):
        self.requests=[dict(tool='search',lane='commodities')]
        _,record=self.expand()
        self.assertEqual(record['decision_reason'],'selected_gap_has_no_matching_tool_request')

    def test_ceiling_never_increases_and_last_turn_cannot_expand(self):
        self.ceiling=self.initial
        _,record=self.expand()
        self.assertEqual(record['decision_reason'],'no_near_limit_resource_can_expand')
        self.initial=replace(self.initial,model_calls=5)
        self.ceiling=replace(self.ceiling,model_calls=5)
        self.state['model_calls']=5
        _,record=self.expand()
        self.assertEqual(record['decision_reason'],'final_model_turn_reserved_for_finish')

    def test_fixed_reviewed_trial_envelope_is_not_adaptive(self):
        self.ceiling=None
        _,record=self.expand()
        self.assertEqual(record['decision_reason'],'explicit_fixed_limits')

    def test_closed_search_route_cannot_gain_search_requests(self):
        self.state['search_route_failed']=True
        expanded,_=self.expand()
        self.assertEqual(expanded.search_calls,self.initial.search_calls)
        self.assertGreater(expanded.body_urls,self.initial.body_urls)

    def test_no_extra_search_when_reading_is_at_hard_ceiling(self):
        self.ceiling=replace(self.ceiling,body_urls=self.initial.body_urls)
        expanded,_=self.expand()
        self.assertEqual(expanded.search_calls,self.initial.search_calls)

    def test_local_input_and_time_budgets_can_grow_together(self):
        task=dict(task_id='body:B1:read_remaining',kind='read_remaining',evidence_ids=['B1'])
        self.state['collection_feedback']['tasks']=[task]
        self.state['local_read_characters']=self.initial.local_read_characters
        proposal=dict(task_ids=[task['task_id']],reason='已选重要长文尚有未读细节')
        expanded,record=expand_budget(self.initial,self.ceiling,self.state,proposal,
            requests=[dict(tool='read_more',id='B1')],elapsed=300,input_characters=70000)
        self.assertEqual(expanded.local_read_characters,self.initial.local_read_characters+16000)
        self.assertEqual(expanded.input_characters,self.initial.input_characters+32000)
        self.assertEqual(expanded.seconds,self.initial.seconds+120)
        self.assertEqual(record['status'],'expanded')

    def test_unknown_task_and_expired_deadline_cannot_extend(self):
        _,record=expand_budget(self.initial,self.ceiling,self.state,self.proposal,
            requests=self.requests,elapsed=360,input_characters=70000)
        self.assertEqual(record['decision_reason'],'deadline_already_reached')
        self.proposal['task_ids']=['made-up-task']
        with self.assertRaisesRegex(ValueError,'extension_unknown_task'):
            self.expand()
