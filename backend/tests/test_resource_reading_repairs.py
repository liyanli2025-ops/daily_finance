"""Cross-date resource, title and financial-product boundaries; no live APIs."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from bs4 import BeautifulSoup

from app.services.article_metadata import extracted_article_title,visible_publication_fields
from app.services.discovery_budget import (Limits,matching_proposal,expand_budget,resource_review,task_has_capacity)
from app.services.discovery_feedback import assess_finish
from app.services.primary_material_quality import review_body
from app.services.material_roles import assess_role
from app.services.web_research import parse_visible_article


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.limits=Limits(model_calls=None,search_calls=3,body_urls=4,seconds=360)
        self.ceiling=replace(self.limits,search_calls=7,body_urls=12,seconds=900)
        self.task=dict(task_id='lane:industry:locate_body',kind='read_candidate',lane='industry',scope=None,
            executable=True,candidate_ids=['S2'],evidence_ids=[])
        self.state=dict(effective_search_limit=3,model_calls=4,model_input_characters=100000,
            reserved_output_tokens=12000,search_tool_calls=3,body_url_calls=3,local_read_characters=0,
            candidates={'S2':dict(url='https://example.com/event')},
            collection_feedback=dict(bodies={},tasks=[self.task]))

    def review(self,**kwargs):
        return resource_review(self.limits,self.ceiling,self.state,elapsed=100,
            total_input=2000000,total_output=120000,**kwargs)

    def feedback(self):
        return dict(bodies={},lanes=[dict(lane='industry',body_ids=[],successful_search=True)],watchlist=[],
            tasks=[self.task],resource_review=self.review())

    def dossier(self,reason='预算紧张'):
        return dict(events=[],coverage=[dict(lane='industry',status='searched',evidence_ids=[])],
            watchlist_checks=[],deferred_tasks=[dict(task_id=self.task['task_id'],reason=reason)])

    def test_unused_body_capacity_rejects_blanket_budget_deferral(self):
        review=assess_finish(self.dossier(),self.feedback())
        self.assertFalse(review['accepted'])
        self.assertEqual(review['invalid_budget_deferrals'],[self.task['task_id']])

    def test_initial_search_exhaustion_is_not_hard_exhaustion(self):
        review=self.review();self.assertEqual(review['current']['searches'],0)
        self.assertEqual(review['hard_remaining']['searches'],4)
        self.assertTrue(task_has_capacity(dict(kind='search_alternative'),review))

    def test_real_editorial_choice_remains_possible(self):
        self.assertTrue(assess_finish(self.dossier('仅有重复转载，本期不将这一事件作为主线'),self.feedback())['accepted'])

    def test_last_model_turn_can_preserve_budget_gaps(self):
        self.assertTrue(assess_finish(self.dossier(),self.feedback(),last_turn=True)['accepted'])

    def test_actual_cumulative_exhaustion_does_not_force_more_paid_turns(self):
        self.state['model_input_characters']=2000000
        self.assertFalse(task_has_capacity(self.task,self.review()))
        self.assertTrue(assess_finish(self.dossier(),self.feedback())['accepted'])

    def test_shared_search_allowance_is_never_invented(self):
        review=self.review(shared_search_limit=3)
        self.assertEqual(review['hard_remaining']['searches'],0)
        self.assertFalse(task_has_capacity(dict(kind='search_alternative'),review))

    def test_closed_search_route_does_not_block_stored_candidates(self):
        self.state['search_route_failed']=True
        self.assertTrue(task_has_capacity(self.task,self.review()))
        self.assertFalse(task_has_capacity(dict(kind='search_alternative'),self.review()))

    def test_only_actual_selected_gap_tools_propose_capacity(self):
        before=deepcopy(self.state)
        proposal=matching_proposal(self.state,[dict(tool='read',candidate_id='S2')],self.limits)
        self.assertEqual(proposal['task_ids'],[self.task['task_id']]);self.assertEqual(self.state,before)
        self.assertIsNone(matching_proposal(self.state,[dict(tool='read',candidate_id='unknown')],self.limits))

    def test_reading_with_room_does_not_spend_search_extension_progress(self):
        self.state['body_url_calls']=0
        self.assertIsNone(matching_proposal(self.state,[dict(tool='read',candidate_id='S2')],self.limits))

    def test_selected_tool_packet_can_request_room_before_overflow(self):
        self.state['body_url_calls']=1
        requests=[dict(tool='read',candidate_id='S2')]*4
        proposal=matching_proposal(self.state,requests,self.limits)
        expanded,record=expand_budget(self.limits,self.ceiling,self.state,proposal,
            requests=requests,elapsed=100,input_characters=10000)
        self.assertGreater(expanded.body_urls,4);self.assertEqual(record['status'],'expanded')
        self.assertEqual(expanded.model_calls,self.limits.model_calls)

    def test_failed_empty_calls_do_not_unlock_growth(self):
        self.state['candidates']={}
        self.assertFalse(self.review()['extension_progress_available'])

    def test_expired_active_window_cannot_be_renewed(self):
        review=resource_review(self.limits,self.ceiling,self.state,elapsed=360,
            total_input=2000000,total_output=120000)
        self.assertFalse(task_has_capacity(self.task,review))


class ExtractedTitleTests(unittest.TestCase):
    def title(self,html,text='公开经营事实与风险，原文需要核实。'*20):
        return extracted_article_title(BeautifulSoup(html,'html.parser'),text)

    def test_non_h1_visible_headline_matches_document_title(self):
        title='企业发布最新经营报告与风险提示'
        self.assertEqual(self.title('<title>'+title+' - 新闻网站</title><h3>'+title+'</h3>'),title)

    def test_article_opening_can_match_short_news_document_title(self):
        title='原油收盘价格有所回落，合约和交易日均需分别核对，这是已保存的公开短讯'
        self.assertEqual(self.title('<title>'+title+'_新闻网站</title>',title+'。更多细节。'),title)

    def test_unrelated_document_title_is_not_assigned_to_body(self):
        self.assertEqual(self.title('<title>网站首页欢迎访问更多财经资讯</title><h2>推荐文章与热门榜单</h2>'),'')

    def test_hidden_heading_cannot_validate_document_title(self):
        title='企业发布最新经营报告与风险提示'
        for wrapper in ('<aside>{}</aside>','<div hidden>{}</div>','<div style="display:none">{}</div>'):
            self.assertEqual(self.title('<title>'+title+'</title>'+wrapper.format('<h3>'+title+'</h3>')),'')

    def test_title_in_script_does_not_become_visible_headline(self):
        self.assertEqual(self.title('<title>企业发布最新经营报告与风险提示</title><script>headline="企业发布最新经营报告与风险提示"</script>'),'')

    def test_generic_title_match_still_requires_publication(self):
        title='企业经营报告与风险提示详情';body=title+'。'+('现金流及经营风险需要核对。'*25)
        html='<title>'+title+'</title><h3>'+title+'</h3><div>'+body+'</div>'
        with patch('app.services.generic_extraction.extract_main_text',return_value=dict(status='text_candidate',
                text=body,method='example',version='1',warnings=[])):
            with self.assertRaisesRegex(ValueError,'time_missing'):
                parse_visible_article(html,'https://publisher.example/news',datetime(2026,11,5,8))

    def test_bounded_publication_widget_ignores_recommendation_dates(self):
        html='<div class="artMain"><div class="artDes"><span>2026-11-04 15:30:00</span><span>来源：示例</span></div></div>'
        html+='<aside><span>2026-11-05 07:00:00</span></aside>'
        self.assertEqual(visible_publication_fields(BeautifulSoup(html,'html.parser')),['2026-11-04 15:30:00'])


class ProductAndPurposeTests(unittest.TestCase):
    def test_product_call_to_action_is_flagged_with_unchanged_text(self):
        text='供给仍偏高，现金流承压。关注养殖ETF（159999），含猪量更高更纯，生猪权重全市场领先！'
        review=review_body(text)
        self.assertIn('financial_product_promotion',{x['code'] for x in review['findings']})
        self.assertFalse(review['text_modified'])
        self.assertIn('现金流',text)

    def test_etf_market_news_is_not_automatically_promotion(self):
        self.assertFalse(review_body('市场ETF资金净流出，跟踪指数下跌。机构维持买入评级，但提示现金流风险。')['requires_editorial_review'])

    def test_product_risk_disclaimer_alone_is_not_promotion(self):
        self.assertFalse(review_body('示例ETF（159999）风险等级R3；基金有风险，投资需谨慎。')['requires_editorial_review'])

    def test_subscription_fee_disclosure_alone_is_not_a_product_invitation(self):
        self.assertFalse(review_body('示例ETF（159999）公告说明申购赎回费率与风险等级，供持有人核对。')['requires_editorial_review'])

    def test_bond_quote_is_not_original_policy_evidence(self):
        item=SimpleNamespace(title='国债收益率小幅上升',source_url='https://example.com/news',content='市场行情转述。')
        role=assess_role(item)
        self.assertFalse(role['original_policy_release_allowed']);self.assertTrue(role['latest_close_allowed'])

    def test_policy_statement_is_not_removed_by_a_yield_mention(self):
        item=SimpleNamespace(title='央行发布声明并解释国债收益率变化',source_url='https://example.com/news')
        self.assertTrue(assess_role(item)['original_policy_release_allowed'])

    def test_reported_session_is_preserved_without_certifying_the_latest(self):
        item=SimpleNamespace(title='市场收盘',source_url='https://example.com/news',content='美东时间周二(11月3日)，股指收盘。')
        role=assess_role(item)
        self.assertIn('11月3日',role['reported_session_labels'][0]);self.assertFalse(role['session_verified'])


class SelectedToolIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_first_source_can_use_selected_alternative_within_existing_turns(self):
        from app.config import settings
        from app.models.news import News
        from app.services.discovery_budget import plan_budget
        from app.services.episode_workspace import EpisodeWorkspace
        from app.services.primary_discovery import discover
        initial,ceiling,plan=plan_budget(0,7,settings)
        initial=replace(initial,search_calls=1,body_urls=1)
        ceiling=replace(ceiling,search_calls=4,body_urls=4)
        plan.update(initial=initial.__dict__,ceiling=ceiling.__dict__)
        queries=[dict(tool='search',lane='us_market',query='Latest completed market session',reason='核对本期市场')]
        reads=[dict(tool='read',candidate_id='S'+str(i),relation='market',reason='选择解决市场缺口的正文') for i in (1,2)]
        packets=iter([queries,[reads[0]],[reads[1]]]);calls=[]
        async def model(task,messages,max_tokens):
            calls.append(messages)
            if len(calls)<=3:return json.dumps(dict(action='tools',requests=next(packets)))
            feedback=json.JSONDecoder().raw_decode(messages[0]['content'].rsplit('collection_feedback：',1)[1])[0]
            return json.dumps(dict(action='finish',events=[],omissions=[],watchlist_checks=[],
                coverage=[dict(lane=row['lane'],status='body_provided' if row['body_ids'] else 'missing',
                    evidence_ids=row['body_ids'],explanation='按真实回执保留缺口') for row in feedback['lanes']],
                deferred_tasks=[dict(task_id=t['task_id'],reason='在本回归用例的研究范围外') for t in feedback['tasks']]))
        def search(workspace,query,**kwargs):
            return dict(status='ok',results=[dict(title='Market session report',url='https://example.com/news/'+str(i)) for i in (1,2)])
        def reader(workspace,url,**kwargs):
            if url.endswith('/1'):return dict(status='failed',reason='public_http_403')
            item=News(id='B2',title='本期市场事实和风险',content='市场事实与风险需要独立核对。'*30,
                source='公开网页可见正文-example',source_url=url,published_at=workspace.now)
            workspace.add([item]);return dict(status='ok',material=workspace.read(item.id))
        with tempfile.TemporaryDirectory() as directory:
            workspace=EpisodeWorkspace([],root=directory,now=datetime(2026,11,5,8))
            with patch('app.services.primary_discovery.plan_budget',return_value=(initial,ceiling,plan)):
                state=await discover(workspace,[],model=model,search=search,read=reader)
        self.assertEqual(state['model_calls'],4);self.assertEqual(state['body_url_calls'],2)
        self.assertEqual(state['search_tool_calls'],1);self.assertEqual(state['provided_ids'],['B2'])
        self.assertEqual(state['budget_expansions'][0]['origin'],'selected_tools_local_review')
        self.assertLessEqual(state['limits']['body_urls'],ceiling.body_urls)
