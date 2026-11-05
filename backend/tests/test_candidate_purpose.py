"""Candidate use is a metadata hint; no reader or provider is invoked."""
from datetime import datetime,timedelta
import tempfile
from types import SimpleNamespace
import unittest

from app.models.news import News
from app.services.search_objectives import primary_candidate,request_profile,social_platform
from app.services.primary_discovery import unsupported_page
from app.services.material_roles import assess_role
from app.services.discovery_feedback import build_feedback
from app.services.discovery_budget import Limits
from app.services.episode_workspace import EpisodeWorkspace

NOW=datetime(2026,11,1,13,56)


class CandidatePurposeTests(unittest.TestCase):
    def candidate(self,title,url='https://publisher.example/article'):
        return dict(title=title,url=url,snippet='来源摘要仅供发现，不是已读正文。')

    def test_ahead_of_decision_is_background_not_a_released_decision(self):
        value=primary_candidate(self.candidate('Bond yields rise ahead of central bank decision'),'global_policy')
        self.assertFalse(value['main_source_option']);self.assertTrue(value['background_only'])

    def test_set_to_hold_is_a_forecast(self):
        value=primary_candidate(self.candidate('Central Bank Set to Hold Rates and Signal More Hikes'),'global_policy')
        self.assertIn('forecast_or_commentary_not_release_confirmation',value['flags'])

    def test_actual_release_can_still_be_selected(self):
        value=primary_candidate(self.candidate('Central bank issues policy statement'),'global_policy')
        self.assertTrue(value['main_source_option']);self.assertTrue(value['body_check_required'])
        self.assertFalse(value['source_identity_verified'])

    def test_released_decision_with_an_outlook_still_requires_body_check(self):
        value=primary_candidate(self.candidate('Central bank holds rates as expected'),'global_policy')
        self.assertTrue(value['main_source_option'])
        self.assertIn('mixed_release_and_outlook_needs_body_check',value['flags'])

    def test_x_is_not_read_by_the_main_html_article_reader(self):
        for host in ('x.com','www.x.com','mobile.twitter.com','threads.net'):
            url='https://'+host+'/account/status/example'
            self.assertTrue(social_platform(url));self.assertIsNotNone(unsupported_page(url))
            self.assertFalse(primary_candidate(self.candidate('Stock closing summary',url),'us_market')['main_source_option'])

    def test_social_domain_matching_does_not_block_similar_hostnames(self):
        self.assertFalse(social_platform('https://notx.com/article'))
        self.assertFalse(social_platform('https://twitter.com.publisher.example/article'))

    def test_main_search_excludes_platforms_without_affecting_discussion_discovery(self):
        _,profile=request_profile('Stock market closing','latest_close',NOW)
        self.assertIn('x.com',profile['exclude_domains'])
        _,profile=request_profile('Public investors views','commentary',NOW)
        self.assertEqual(profile,{})

    def test_completed_session_lead_precedes_a_live_page_without_deleting_it(self):
        close=primary_candidate(self.candidate('How major stock indexes fared Friday'),'us_market')
        live=primary_candidate(self.candidate('Stock market live updates','https://publisher.example/livecoverage/today'),'us_market')
        self.assertLess(close['priority'],live['priority']);self.assertTrue(live['main_source_option'])
        self.assertIn('rolling_article_may_contain_later_completed_session',live['flags'])

    def test_morning_report_is_background_for_settlement(self):
        value=primary_candidate(self.candidate('Gold and currencies - AM Report'),'commodities')
        self.assertFalse(value['main_source_option']);self.assertTrue(value['background_only'])

    def test_forecast_text_cannot_gain_policy_role_by_changing_search_purpose(self):
        item=SimpleNamespace(title='Policy rates are set to stay unchanged',source_url='https://example.com/preview')
        self.assertFalse(assess_role(item)['original_policy_release_allowed'])

    def test_body_role_rejects_social_statement_as_main_news(self):
        item=SimpleNamespace(title='Stock market closing',source_url='https://x.com/author/status/1')
        role=assess_role(item)
        self.assertFalse(role['latest_close_allowed']);self.assertFalse(role['original_policy_release_allowed'])


class CandidateFeedbackTests(unittest.TestCase):
    def state(self,rows,lane):
        return dict(candidates={key:dict(value,discovered_by=[dict(lane=lane,purpose='released_policy'
                if lane=='global_policy' else 'latest_close')]) for key,value in rows.items()},
            receipts=[],effective_search_limit=4,model_calls=1,search_tool_calls=0,body_url_calls=0,local_read_characters=0)

    def workspace(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        return EpisodeWorkspace([],root=directory.name,now=NOW)

    def test_forecasts_leave_raw_catalogue_and_become_background_hints(self):
        rows={'S1':dict(title='Rates ahead of policy decision',url='https://example.com/ahead'),
              'S2':dict(title='Bank set to hold rates',url='https://example.com/set-to')}
        state=self.state(rows,'global_policy');feedback=build_feedback(self.workspace(),state,[],Limits())
        task=next(t for t in feedback['tasks'] if t['task_id']=='lane:global_policy:locate_body')
        self.assertEqual(task['kind'],'search_alternative');self.assertEqual(task['candidate_ids'],[])
        self.assertEqual([x['candidate_id'] for x in task['background_candidate_hints']],['S1','S2'])
        self.assertEqual(set(state['candidates']),{'S1','S2'})

    def test_completed_summary_is_suggested_before_live_coverage_and_social_is_not(self):
        rows={'S1':dict(title='Stock market live updates',url='https://example.com/live-updates'),
              'S2':dict(title='Stock market closing',url='https://x.com/account/status/1'),
              'S3':dict(title='How major stock indexes fared Friday',url='https://example.com/recap')}
        state=self.state(rows,'us_market');feedback=build_feedback(self.workspace(),state,[],Limits())
        task=next(t for t in feedback['tasks'] if t['task_id']=='lane:us_market:locate_body')
        self.assertEqual(task['candidate_ids'],['S3','S1'])
        self.assertIn('S2',state['candidates'])

    def test_reading_a_preview_does_not_turn_it_into_policy_coverage(self):
        workspace=self.workspace()
        item=News(id='B1',title='Bank set to hold rates',content='预测与发布事实需要明确区分。'*30,
            source='公开网页可见正文-example',source_url='https://example.com/preview',published_at=NOW-timedelta(hours=1))
        workspace.add([item]);state=self.state({'S1':dict(title=item.title,url=item.source_url)},'global_policy')
        state['receipts']=[dict(request=dict(tool='read',candidate_id='S1',relation='market'),
            result=dict(status='ok',material=workspace.read(item.id)))]
        feedback=build_feedback(workspace,state,[],Limits())
        self.assertEqual(next(x for x in feedback['lanes'] if x['lane']=='global_policy')['body_ids'],[])
