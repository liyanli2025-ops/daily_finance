"""Metadata selection regressions: no model, HTTP or application dependencies."""
import copy
import unittest
from app.services.edition_read_selection import (primary_plan, patch_plan, fallback_plan,
    select_candidate, validate_increment)


def event(**changes):
    value = dict(id='E1', title='政策已公布', lane='global_policy', purpose='discovery',
        reason='影响后续市场定价和适用条件', candidate_ids=['S1', 'S2', 'S3'], read_ids=['S2', 'S1'])
    value.update(changes); return value


def state():
    return dict(candidates={cid: dict(title='政策最新消息' + cid,
        url='https://example.com/' + cid, snippet='政策实施细则和条件',
        published_hint='2026-11-13', search_links=[dict(event_id='E1', query='政策细则')])
        for cid in ('S1', 'S2', 'S3')}, sources={}, read_receipts=[])


def request(**changes):
    value = dict(event_id='E1', query='政策细则', increment='missing_context',
                 reason='核对政策实施条件是否覆盖此前未解释的行业影响')
    value.update(changes); return value


class ReadSelectionTests(unittest.TestCase):
    def test_model_choice_precedes_search_order_and_reads_only_one(self):
        jobs, trace = primary_plan([event()])
        self.assertEqual([j['candidate_id'] for j in jobs], ['S2'])
        self.assertEqual(trace[0]['deferred_ids'], ['S1', 'S3'])

    def test_no_model_choice_does_not_force_first_search_result(self):
        self.assertEqual(primary_plan([event(read_ids=[])])[0], [])

    def test_first_plan_does_not_mutate_agenda(self):
        value = event(); before = copy.deepcopy(value)
        primary_plan([value]); self.assertEqual(value, before)

    def test_increment_requires_known_kind_and_concrete_length(self):
        for invalid in (dict(increment='more'), dict(reason='补资料'), dict(reason=None), dict(reason='x' * 401)):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'increment_required'):
                validate_increment(request(**invalid))

    def test_patch_search_selects_one_and_preserves_all_candidates(self):
        value = state(); before = copy.deepcopy(value)
        jobs, trace = patch_plan(value, {'E1': event()}, dict(additional_searches=[request()]), [])
        self.assertEqual(len(jobs), 1)
        self.assertEqual(len(trace[0]['deferred_ids']), 2)
        self.assertEqual(value, before)

    def test_close_candidate_outranks_first_morning_report(self):
        value = state()
        value['candidates']['S1']['title'] = 'Gold AM Report'
        value['candidates']['S2']['title'] = 'Gold closed lower'
        cid, _ = select_candidate(value, event(lane='commodities', purpose='latest_close'),
                                  ['S1', 'S2'], request())
        self.assertEqual(cid, 'S2')

    def test_multiple_queries_share_one_selection_without_losing_second_query(self):
        value = state()
        value['candidates']['S1'].update(title='政策决定前瞻', search_links=[dict(event_id='E1', query='第一查询')])
        value['candidates']['S2'].update(title='宣布政策决定', search_links=[dict(event_id='E1', query='第二查询')])
        jobs, _ = patch_plan(value, {'E1': event(purpose='released_policy')},
            dict(additional_searches=[request(query='第一查询'), request(query='第二查询')]), [])
        self.assertEqual([j['candidate_id'] for j in jobs], ['S2'])

    def known(self, value, eid='E1'):
        value['sources']['body-1'] = dict(candidate_id='S1', event_ids=[eid], url=value['candidates']['S1']['url'])
        value['candidates']['S1']['original_source'] = '原始通讯社'
        value['candidates']['S2']['original_source'] = '原始通讯社'
        return value

    def test_same_declared_upstream_cannot_be_independent_confirmation(self):
        value = self.known(state())
        cid, trace = select_candidate(value, event(), ['S2'], request(increment='independent_verification'))
        self.assertIsNone(cid)
        self.assertEqual(trace['skipped'][0]['reason'], 'same_declared_upstream_not_independent')

    def test_other_event_source_does_not_block_same_publisher(self):
        value = self.known(state(), 'E9')
        cid, _ = select_candidate(value, event(), ['S2'], request(increment='independent_verification'))
        self.assertEqual(cid, 'S2')

    def test_probable_reprint_deprioritized_without_deleting_lead(self):
        value = self.known(state())
        value['candidates']['S2']['title'] = value['candidates']['S1']['title']
        cid, trace = select_candidate(value, event(), ['S2', 'S3'], request())
        self.assertEqual(cid, 'S3')
        self.assertIn('S2', trace['deferred_ids'])

    def test_updated_same_headline_kept_as_possible_new_information(self):
        value = self.known(state())
        value['candidates']['S2'].update(title=value['candidates']['S1']['title'], published_hint='2026-11-13 17:00')
        cid, trace = select_candidate(value, event(), ['S2'], request(increment='new_update'))
        self.assertEqual(cid, 'S2')
        self.assertFalse(trace['ranked'][0]['likely_reprint'])

    def test_explicit_read_retains_reason_and_bounds_same_gap(self):
        value = state(); first = request(candidate_id='S3')
        jobs, _ = patch_plan(value, {'E1': event()},
            dict(additional_reads=[first, request(candidate_id='S2')], additional_searches=[request()]), [])
        self.assertEqual([j['candidate_id'] for j in jobs], ['S3'])
        self.assertEqual(jobs[0]['reason'], first['reason'])

    def test_explicit_same_upstream_read_is_not_independent(self):
        value = self.known(state())
        jobs, _ = patch_plan(value, {'E1': event()}, dict(additional_reads=[
            request(candidate_id='S2', increment='independent_verification')]), [])
        self.assertEqual(jobs, [])

    def test_no_fallback_when_representative_body_is_available(self):
        value = state(); jobs, _ = primary_plan([event()])
        value['sources']['B2'] = dict(url=value['candidates']['S2']['url'])
        self.assertEqual(fallback_plan(value, {'E1': event()}, jobs[0]), (None, None))

    def test_failed_first_url_has_only_one_fallback(self):
        value = state(); jobs, _ = primary_plan([event()])
        alternate, _ = fallback_plan(value, {'E1': event()}, jobs[0])
        self.assertNotEqual(alternate['candidate_id'], 'S2')
        self.assertFalse(alternate['allow_fallback'])
        self.assertEqual(fallback_plan(value, {'E1': event()}, alternate), (None, None))

    def test_fallback_preserves_independent_verification_constraint(self):
        value = self.known(state())
        job = request(candidate_id='S3', increment='independent_verification',
                      fallback_ids=['S2'], allow_fallback=True)
        alternate, trace = fallback_plan(value, {'E1': event()}, job)
        self.assertIsNone(alternate)
        self.assertEqual(trace['increment'], 'independent_verification')

    def test_failed_candidate_is_not_retried(self):
        value = state(); value['read_receipts'] = [dict(candidate_id='S1', status='failed')]
        cid, _ = select_candidate(value, event(), ['S1', 'S2'], request())
        self.assertEqual(cid, 'S2')

    def test_unknown_origin_does_not_claim_independence(self):
        cid, trace = select_candidate(state(), event(), ['S3'], request(increment='independent_verification'))
        self.assertEqual(cid, 'S3')
        self.assertIn('不认证独立性', trace['basis'])


class CandidateAdmissionTests(unittest.TestCase):
    def test_adult_spam_title_cannot_be_main_evidence(self):
        from app.services.search_objectives import primary_candidate
        row=dict(title='调教av，精选免费播放路径分享全过程资源- 财经',url='https://example.com/article')
        self.assertFalse(primary_candidate(row,None)['main_source_option'])

    def test_directory_quotes_generated_app_and_attachment_need_other_reader(self):
        from app.services.search_objectives import metadata_blockers
        for url in ['https://example.com/knowledge/company/ABC',
                    'https://example.com/quotes/index.html?code=1',
                    'https://kuku.baidu.com/landing/tscp_doc/abc',
                    'https://example.com/news/topic/screenshot-166/']:
            with self.subTest(url=url):self.assertTrue(metadata_blockers(dict(title='公司新闻',url=url)))

    def test_real_article_path_is_not_a_directory(self):
        from app.services.search_objectives import metadata_blockers
        self.assertEqual(metadata_blockers(dict(title='公司发布季度业绩',
            url='https://example.com/news/2026/11/13/company-results.html')),[])

    def test_company_mention_in_unrelated_snippet_is_not_direct_subject(self):
        from app.services.edition_read_selection import candidate_admission
        value=state();value['watchlist']=[dict(market='A',code='300750',name='宁德时代')]
        row=dict(title='关于周六系统测试的公告',snippet='推荐宁德时代新闻',url='https://example.com/article')
        blocked=candidate_admission(value,event(title='宁德时代公司事项'),row,request(scope='A:300750'))
        self.assertIn('company_not_title_subject',blocked)

    def test_company_code_can_identify_a_direct_article(self):
        from app.services.edition_read_selection import candidate_admission
        value=state();value['watchlist']=[dict(market='A',code='300750',name='宁德时代')]
        row=dict(title='300750 业绩公告',url='https://example.com/article')
        self.assertNotIn('company_not_title_subject',candidate_admission(value,
            event(title='公司业绩公告'),row,request(scope='A:300750')))

    def test_unrelated_title_is_not_chosen_from_recommendation_snippet(self):
        value=state();value['candidates']['S1'].update(title='新模型智商指数登顶',snippet='美国中期选举结果分析')
        cid,trace=select_candidate(value,event(title='美国中期选举结果'),['S1'],request())
        self.assertIsNone(cid);self.assertIn('title_topic_not_supported_by_metadata',trace['skipped'][0]['flags'])

    def test_specific_model_reason_can_explain_a_different_subtopic_title(self):
        from app.services.edition_read_selection import candidate_admission
        row=dict(title='美军否认伊朗袭击巴林雷达设施',url='https://example.com/article')
        flags=candidate_admission(state(),event(title='商品与中东地缘风险'),row,
            request(reason='核对伊朗袭击巴林设施与原油风险的关联和时间'))
        self.assertNotIn('title_topic_not_supported_by_metadata',flags)

    def test_other_language_title_is_not_blocked_by_chinese_word_matching(self):
        from app.services.edition_read_selection import candidate_admission
        self.assertEqual(candidate_admission(state(),event(title='美国最新政策决定'),
            dict(title='US policy statement',url='https://example.com/article'),request()),[])

    def test_failed_explicit_read_can_use_one_alternate_from_same_gap_search(self):
        value=state();first=request(candidate_id='S3')
        jobs,_=patch_plan(value,{'E1':event()},dict(additional_reads=[first],additional_searches=[request()]),[])
        self.assertEqual(len(jobs),1);self.assertEqual(jobs[0]['candidate_id'],'S3')
        self.assertTrue(jobs[0]['allow_fallback'])
        value['read_receipts'].append(dict(candidate_id='S3',status='failed'))
        alternate,_=fallback_plan(value,{'E1':event()},jobs[0])
        self.assertIn(alternate['candidate_id'],['S1','S2']);self.assertFalse(alternate['allow_fallback'])
        self.assertEqual(fallback_plan(value,{'E1':event()},alternate),(None,None))

    def test_explicit_read_without_search_does_not_gain_extra_network_attempts(self):
        jobs,_=patch_plan(state(),{'E1':event()},dict(additional_reads=[request(candidate_id='S3')]),[])
        self.assertFalse(jobs[0]['allow_fallback'])

    def test_successful_explicit_read_does_not_read_the_search_batch(self):
        value=state();jobs,_=patch_plan(value,{'E1':event()},dict(
            additional_reads=[request(candidate_id='S3')],additional_searches=[request()]),[])
        value['sources']['known']=dict(url=value['candidates']['S3']['url'])
        self.assertEqual(fallback_plan(value,{'E1':event()},jobs[0]),(None,None))

    def test_metadata_rejections_preserve_original_candidates(self):
        value=state();value['candidates']['S1'].update(title='行情目录',url='https://example.com/quotes/index.html')
        before=copy.deepcopy(value)
        cid,_=select_candidate(value,event(),['S1'],request())
        self.assertIsNone(cid);self.assertEqual(value,before)


class CandidateReadBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_selected_spam_cannot_cross_actual_http_read_boundary(self):
        from pathlib import Path
        import tempfile
        from unittest.mock import AsyncMock, Mock
        from app.services.edition_pipeline import EditionPipeline
        from app.services.episode_workspace import EpisodeWorkspace
        import test_unified_edition as reference
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);run=reference.state()
            run['candidates']={'S1':dict(title='调教av，精选免费播放资源分享',url='https://example.com/spam')}
            reader=Mock()
            workspace=EpisodeWorkspace(root=root/'evidence')
            pipeline=EditionPipeline(run,root,workspace,read=reader,check=AsyncMock())
            await pipeline.reads([dict(event_id='E1',candidate_id='S1')],{'E1':reference.EVENT})
            reader.assert_not_called()
            self.assertEqual(run['read_metadata_rejections'][0]['http_requests'],0)
            self.assertFalse(run.get('read_receipts'))


class CandidateReplayFindingsTests(unittest.TestCase):
    def test_generic_one_item_word_does_not_make_an_unrelated_election_title_relevant(self):
        value=state();value['candidates']['S1'].update(title='AI生态不围绕单一个人运转',snippet='选举结果')
        cid,_=select_candidate(value,event(title='美国中期选举结果'),['S1'],
            request(reason='针对底稿中这一个未覆盖事件补查，核对实际发布日期'))
        self.assertIsNone(cid)

    def test_english_mining_technology_is_not_an_oil_and_gold_price_source(self):
        value=state();value['candidates']['S1'].update(
            title='AI vs experience: Is technology changing mineral exploration forever?',snippet='mining research')
        cid,_=select_candidate(value,event(title='黄金和原油价格波动',lane='commodities'),['S1'],request())
        self.assertIsNone(cid)

    def test_stale_search_hint_is_ranked_later_without_certifying_fresh_hint(self):
        value=state();value['cutoff']='2026-11-14T09:00:00'
        value['candidates']['S1'].update(title='Oil and gold prices',published_hint='2026-11-01T08:00:00+08:00')
        value['candidates']['S2'].update(title='Oil and gold prices',published_hint='2026-11-13T08:00:00+08:00')
        cid,trace=select_candidate(value,event(title='黄金和原油价格波动',lane='commodities'),['S1','S2'],request())
        self.assertEqual(cid,'S2')
        self.assertIn('S1',trace['deferred_ids'])
        self.assertTrue(next(r for r in trace['ranked'] if r['candidate_id']=='S1')['published_hint_outside_window'])
