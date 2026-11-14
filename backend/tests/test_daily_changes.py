"""Offline regressions for discovery provenance, scope and dated market evidence."""
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.services import daily_changes as changes
from app.services.edition_market import collect, evidence, allowed_endpoint, COUNT, QUOTE_BASE
from app.services.edition_pipeline import initial_searches, EditionPipeline
from app.services.edition_issuer_desk import PROTOCOL as LISTENER
from app.services.edition_budget import digest
from app.services.edition_context import packet
from app.services.edition_inputs import editorial_forecast
import test_unified_edition as reference

NOW = datetime(2026,11,14,10)
STOCK = dict(market='A',code='002714',name='牧原股份')
FACT = '公司公告确认生产线因事故暂时停产，恢复时间待定。'


def state():
    s = reference.state()
    s.update(research_protocol=LISTENER, change_protocol=changes.PROTOCOL,
        cutoff=NOW.isoformat(), watchlist=[STOCK])
    return s


def screened(s):
    return dict(change_checks=[dict(task_id=t['id'], status='screened_no_material_event',
        reason='仅在这次已完成的检索范围内未选出实质新增事件', evidence=[]) for t in changes.tasks(s)])


def checked_state():
    s=state()
    s['search_receipts']=[dict(job=dict(change_task=t['id'],change_categories=[t['id']]),
        result=dict(status='ok',results=[])) for t in changes.tasks(s)]
    return s


class ChangeTasks(unittest.TestCase):
    def test_four_stocks_have_sixteen_paid_searches_and_four_catalogues(self):
        stocks=[dict(STOCK,code=str(200000+i)) for i in range(4)]
        jobs=initial_searches(stocks,NOW,direct_issuers=True,daily_changes=True)
        self.assertEqual(sum(j.get('retrieval')=='issuer_catalogue' for j in jobs),4)
        self.assertEqual(sum(j.get('retrieval')!='issuer_catalogue' for j in jobs),16)
        self.assertTrue(all(2<=len(j['query'])<=120 for j in jobs))

    def test_company_operations_and_risk_are_separate_non_announcement_jobs(self):
        jobs=changes.targeted_jobs([STOCK],NOW)
        self.assertEqual({j['change_task'] for j in jobs},{'operations:A:002714','governance:A:002714'})
        self.assertTrue(all('retrieval' not in j for j in jobs))
        self.assertIn('停产',jobs[0]['query']);self.assertIn('诉讼',jobs[1]['query'])

    def test_verified_industry_can_guide_search_but_no_guessed_counterparty(self):
        baseline={'A:002714':dict(profile=dict(industry='已披露行业'))}
        jobs=changes.targeted_jobs([STOCK],NOW,baseline)
        self.assertIn('已披露行业',jobs[0]['query'])
        self.assertNotIn('某客户公司',jobs[0]['query'])

    def test_missing_profile_does_not_block_non_financial_incident_search(self):
        self.assertIn('事故',changes.targeted_jobs([STOCK],NOW)[0]['query'])

    def test_industry_and_political_slots_explicitly_include_missing_topics(self):
        jobs=initial_searches([],NOW,daily_changes=True)
        self.assertIn('商业化',next(j['query'] for j in jobs if j['lane']=='industry'))
        self.assertTrue(any('election' in j['query'] for j in jobs))

    def test_business_specific_industry_search_can_find_peer_without_company_name(self):
        jobs=initial_searches([STOCK],NOW,direct_issuers=True,daily_changes=True,
            baselines={'A:002714':{'profile':{'industry':'养殖'}}})
        industry=[j for j in jobs if j['lane']=='industry']
        self.assertTrue(any('养殖' in j['query'] and STOCK['name'] not in j['query'] for j in industry))

    def test_fewer_results_are_requested_upfront_not_silently_dropped_from_existing_pool(self):
        from app.services.web_research import search_request
        p,_=search_request('产业技术最新变化','discovery',NOW,max_results=5)
        self.assertEqual(p['max_results'],5)
        p,_=search_request('产业技术最新变化','discovery',NOW)
        self.assertEqual(p['max_results'],10)

    def test_legacy_jobs_and_historical_states_keep_their_protocol(self):
        self.assertEqual(changes.brief({}),{})
        self.assertEqual(len(initial_searches([],NOW)),8)
        self.assertFalse(any('change_task' in j for j in initial_searches([STOCK],NOW)))

    def test_empty_pool_is_not_checked_no_event(self):
        self.assertTrue(all(r['discovery']=='not_checked' for r in changes.coverage(state())))
        with self.assertRaisesRegex(ValueError,'not_searched'):
            changes.validate_checks(state(),screened(state()),set())

    def test_failed_query_is_visible_and_does_not_certify_absence(self):
        s=checked_state();s['search_receipts'][0]['result']['status']='failed'
        self.assertEqual(changes.coverage(s)[0]['discovery'],'unavailable')
        with self.assertRaisesRegex(ValueError,'not_searched'):
            changes.validate_checks(s,screened(s),set())

    def test_completed_finite_screen_is_allowed_without_inventing_daily_news(self):
        s=checked_state()
        self.assertEqual(changes.validate_checks(s,screened(s),set()),[])

    def test_all_tasks_must_remain_in_assessment(self):
        s=checked_state();v=screened(s);v['change_checks'].pop()
        with self.assertRaisesRegex(ValueError,'checks_missing'):
            changes.validate_checks(s,v,set())

    def test_body_on_disk_is_not_proof_of_delivery(self):
        s=checked_state();j=changes.targeted_jobs([STOCK],NOW)[0]
        s['candidates']={'S1':dict(title='事故停产',search_links=[j])}
        s['sources']={'B1':dict(id='B1',candidate_id='S1',text=FACT,direct_scopes=['A:002714'])}
        v=screened(s);v['change_checks'][-2].update(status='supported',evidence=[dict(source_id='B1',quote=FACT)])
        with self.assertRaisesRegex(ValueError,'evidence_invalid'):
            changes.validate_checks(s,v,set())
        self.assertEqual(changes.validate_checks(s,v,{'B1'}),[])

    def test_company_peer_or_old_financial_baseline_cannot_fill_today_incident(self):
        s=checked_state();j=changes.targeted_jobs([STOCK],NOW)[0]
        s['candidates']={'S1':dict(title='停产',search_links=[j])}
        s['sources']={'B1':dict(id='B1',candidate_id='S1',text=FACT,direct_scopes=['A:600900'])}
        v=screened(s);v['change_checks'][-2].update(status='supported',evidence=[dict(source_id='B1',quote=FACT)])
        with self.assertRaisesRegex(ValueError,'evidence_invalid'):changes.validate_checks(s,v,{'B1'})
        s['sources']['B1'].update(direct_scopes=['A:002714'],metadata={'kind':'financial_baseline'})
        with self.assertRaisesRegex(ValueError,'evidence_invalid'):changes.validate_checks(s,v,{'B1'})

    def test_actual_missing_scope_survives_instead_of_becoming_no_event(self):
        s=checked_state();v=screened(s);v['change_checks'][0]['status']='missing'
        self.assertEqual(changes.validate_checks(s,v,set()),['change:politics'])

    def test_election_is_not_lost_inside_generic_macro_label(self):
        s=state();s['candidates']={'S1':dict(title='Election results announced')}
        a=dict(events=[dict(id='E1',title='国际宏观',reason='总体经济变化',candidate_ids=['S1'])])
        with self.assertRaisesRegex(ValueError,'concrete_event_lost'):changes.audit_agenda(s,a)
        a['events'][0]['title']='Election results';changes.audit_agenda(s,a)
        self.assertEqual(s['change_signal_decisions'][0]['topic'],'选举')

    def test_exclusion_must_say_which_concrete_political_topic_was_not_selected(self):
        s=state();s['candidates']={'S1':dict(title='关税新进展')}
        a=dict(events=[],excluded_candidates=[dict(candidate_ids=['S1'],reason='重复资讯')])
        with self.assertRaisesRegex(ValueError,'concrete_event_lost'):changes.audit_agenda(s,a)
        a['excluded_candidates'][0]['reason']='关税报道同源重复，原稿已归入E1';changes.audit_agenda(s,a)

    def test_writing_and_review_keep_checks_and_cited_evidence(self):
        s=checked_state();s['assessment']=screened(s);s['assessment']['expectation_checks']=[]
        p=packet(s,'writing')
        self.assertIn('change_checks',p['assessment']);self.assertIn('change_coverage',p)
        messages=editorial_forecast(s,NOW)
        self.assertTrue(all(r['known_input_bytes']>0 for r in messages))


class ExpectationEvidence(unittest.TestCase):
    def prepared(self):
        s=state();s['agenda']={'events':[dict(id='E1')]}
        s['sources']={'B1':dict(id='B1',text='此前一致预期为五。实际结果为六。',event_ids=['E1'])}
        row=dict(event_id='E1',claim_quote='本次结果高于预期，但持续性待核',baseline_before_actual=True,
            comparable=True,reason='同一统计期间和单位，事前预测与随后实际公布值分别保留',
            actual=dict(source_id='B1',quote='实际结果为六',as_of='2026-11-14T09:00:00+08:00',metric='指标',unit='个',period='本期'),
            baseline=dict(source_id='B1',quote='此前一致预期为五',as_of='2026-11-13T09:00:00+08:00',metric='指标',unit='个',period='本期'))
        return s,row

    def test_two_dated_verbatim_sides_required(self):
        s,row=self.prepared();changes.validate_expectations(s,dict(expectation_checks=[row]),{'B1'})
        row['baseline']['quote']='没有这段预期'
        with self.assertRaisesRegex(ValueError,'evidence_invalid'):
            changes.validate_expectations(s,dict(expectation_checks=[row]),{'B1'})

    def test_post_release_forecast_and_wrong_unit_rejected(self):
        s,row=self.prepared();row['baseline']['as_of']='2026-11-14T09:30:00+08:00'
        with self.assertRaisesRegex(ValueError,'time_or_metric_invalid'):
            changes.validate_expectations(s,dict(expectation_checks=[row]),{'B1'})
        row['baseline']['as_of']='2026-11-13T09:00:00+08:00';row['baseline']['unit']='万元'
        with self.assertRaisesRegex(ValueError,'time_or_metric_invalid'):
            changes.validate_expectations(s,dict(expectation_checks=[row]),{'B1'})

    def test_price_rise_alone_cannot_become_positive_expectation_claim(self):
        with self.assertRaisesRegex(ValueError,'without_baseline'):
            changes.validate_language(state(),dict(body='股价上涨，说明业绩超预期。',script=''))
        changes.validate_language(state(),dict(body='缺乏事前共识数据，无法判断是否超预期。',script=''))

    def test_a_different_approved_claim_does_not_authorize_another_assertion(self):
        s=state();s['assessment']={'expectation_checks':[dict(claim_quote='订单超预期但仍需观察') ]}
        with self.assertRaisesRegex(ValueError,'without_baseline'):
            changes.validate_language(s,dict(body='资金流入驱动股价上涨。',script=''))

    def test_approved_phrase_does_not_authorize_second_assertion_in_same_sentence(self):
        s=state();s['assessment']={'expectation_checks':[dict(claim_quote='订单超预期')]}
        with self.assertRaisesRegex(ValueError,'without_baseline'):
            changes.validate_language(s,dict(body='订单超预期，资金流入驱动股价上涨。',script=''))


class MarketBoundary(unittest.TestCase):
    def fake_collection(self, s, desk, callback):
        radar=Mock();radar.collect.side_effect=lambda **kwargs:callback(radar)
        with patch('app.services.timed_market.parse_quotes',return_value=[]), \
                patch('app.services.market_breadth.BreadthRadar',return_value=radar):
            return collect(s,desk,observed=NOW)

    def test_market_allowlist_is_fixed_and_does_not_accept_arbitrary_hosts(self):
        self.assertTrue(allowed_endpoint(COUNT));self.assertTrue(allowed_endpoint(QUOTE_BASE+'sh000001,sz399001'))
        for url in ['https://example.com/q=sh000001',QUOTE_BASE+'sh000001&url=x',QUOTE_BASE+'']:
            self.assertFalse(allowed_endpoint(url))

    def test_historical_resume_does_not_fetch_current_quotes(self):
        desk=Mock();s=state()
        result=collect(s,desk,observed=NOW+timedelta(days=1))
        self.assertEqual(result['status'],'historical_live_read_refused');desk.request.assert_not_called()

    def test_no_numeric_data_does_not_create_a_fake_evidence_document(self):
        self.assertIsNone(evidence(dict(indices=[],breadth={'status':'unavailable'})))

    def test_saved_observation_does_not_claim_latest_close_or_original_policy(self):
        s=evidence(dict(indices=[dict(code='000001',as_of=NOW.isoformat(),current=1)],
            breadth={'status':'unavailable'},observed_at=NOW.isoformat()))
        self.assertFalse(s['source_role']['latest_close_allowed'])
        self.assertFalse(s['source_role']['original_policy_release_allowed'])

    def test_observation_numbers_not_duplicated_in_stage_brief(self):
        s=state();s['market_observations']=dict(indices=[dict(current=12345)],status='pending')
        doc=evidence(dict(s['market_observations'],observed_at=NOW.isoformat()))
        s['sources']={doc['id']:doc}
        b=changes.brief(s)
        self.assertNotIn('indices',b['market_observations'])
        self.assertEqual(b['market_observations']['evidence_source_ids'],[doc['id']])

    def test_keep_twenty_four_attempts_for_article_reads(self):
        s=state();s['policy']['max_body_urls']=20
        desk=SimpleNamespace(workspace=SimpleNamespace(public_fetch_attempts=36),
            request=Mock(return_value=''),deadline=time.monotonic()+90)
        r=self.fake_collection(s,desk,lambda radar:radar.get(COUNT,{},desk.deadline))
        self.assertEqual(r['breadth']['status'],'unavailable')
        self.assertEqual(desk.request.call_count,1) # Index only; breadth refuses before transport.

    def test_cold_sample_too_large_stops_after_count_without_page_download(self):
        s=state();s['policy']['max_body_urls']=30
        desk=SimpleNamespace(workspace=SimpleNamespace(public_fetch_attempts=0),
            request=Mock(side_effect=['',6000]),deadline=time.monotonic()+90)
        r=self.fake_collection(s,desk,lambda radar:radar.get(COUNT,{},desk.deadline))
        self.assertEqual(r['breadth']['status'],'unavailable')
        self.assertEqual(desk.request.call_count,2)

    def test_final_count_check_does_not_repeat_the_cold_allocation_check(self):
        s=state();workspace=SimpleNamespace(public_fetch_attempts=0)
        def request(url,params,**kwargs):
            if url==COUNT:
                workspace.public_fetch_attempts+=1
                return 5000
            return ''
        desk=SimpleNamespace(workspace=workspace,request=Mock(side_effect=request),deadline=time.monotonic()+90)
        def callback(radar):
            radar.get(COUNT,{},desk.deadline)
            workspace.public_fetch_attempts=80
            radar.get(COUNT,{},desk.deadline)
            return {'status':'test_count_checks_only'}
        r=self.fake_collection(s,desk,callback)
        self.assertEqual(r['breadth']['status'],'test_count_checks_only')
        self.assertEqual(desk.request.call_args.kwargs['request_tag'],'breadth-final-count')

    def test_breadth_deadline_rejected_before_next_transport(self):
        s=state();desk=SimpleNamespace(workspace=SimpleNamespace(public_fetch_attempts=0),
            request=Mock(return_value=''),deadline=time.monotonic()+90)
        r=self.fake_collection(s,desk,lambda radar:radar.get(COUNT,{},time.monotonic()-1))
        self.assertEqual(r['breadth']['status'],'unavailable')
        self.assertEqual(desk.request.call_count,1)

    def test_catalogue_bookend_is_fresh_while_repeating_it_is_not_a_third_request(self):
        from app.services.edition_issuer_desk import IssuerDesk
        with tempfile.TemporaryDirectory() as root:
            workspace=SimpleNamespace(path=Path(root),now=NOW,public_fetch_attempts=0)
            response=Mock(status_code=200)
            response.iter_content.side_effect=lambda size:iter([b'5000'])
            getter=Mock(return_value=response)
            desk=IssuerDesk(state(),workspace,Mock(),time.monotonic()+90,request_get=getter)
            with patch('app.services.source_health.ensure_active'):
                self.assertEqual(desk.request(COUNT,{}),5000)
                self.assertEqual(desk.request(COUNT,{},request_tag='breadth-final-count'),5000)
                self.assertEqual(desk.request(COUNT,{},request_tag='breadth-final-count'),5000)
            self.assertEqual(getter.call_count,2)
            self.assertEqual(workspace.public_fetch_attempts,2)

    def test_source_quote_after_cutoff_not_admitted_to_breadth(self):
        from app.services.market_breadth import parse_dated_quotes
        fields=['']*35
        for key,value in {2:'000001',3:'11',4:'10',6:'1',30:'20261114100001',32:'10'}.items():fields[key]=value
        quotes,bad=parse_dated_quotes('v_sz000001="'+'~'.join(fields)+'";',{'sz000001'},NOW)
        self.assertEqual(quotes,{})
        self.assertTrue(bad)


class PipelineWiring(unittest.IsolatedAsyncioTestCase):
    async def test_new_pipeline_uses_targeted_jobs_after_baselines_without_extra_model_loop(self):
        with tempfile.TemporaryDirectory() as root:
            s=state();workspace=SimpleNamespace(path=Path(root),now=NOW)
            p=EditionPipeline(s,root,workspace,check=AsyncMock())
            p.searches=AsyncMock();p.save=Mock();p.call=AsyncMock(side_effect=ValueError('edition_stop_here'))
            with patch('app.services.edition_market.collect',return_value={'indices':[],'breadth':{}}):
                with self.assertRaisesRegex(ValueError,'stop_here'):await p.execute()
            self.assertEqual(p.searches.await_count,2)
            paid=p.searches.await_args_list[1].args[0]
            self.assertEqual(len(paid),10)
            self.assertEqual(sum('change_task' in j for j in paid),2)
            self.assertEqual(p.call.await_count,1)

    async def test_missing_change_checks_cannot_reach_writing(self):
        with tempfile.TemporaryDirectory() as root:
            s=state();p=EditionPipeline(s,root,SimpleNamespace(path=Path(root),now=NOW),check=AsyncMock())
            s.update(phase='assessment',delivered_sources={'assessment':{}})
            with patch('app.services.edition_contract.prepare_assessment',return_value=({}, {}, {'missing':[]})):
                with self.assertRaisesRegex(ValueError,'checks_missing'):
                    p.validate_assessment({}, {}, set())
