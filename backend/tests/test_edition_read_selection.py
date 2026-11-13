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
