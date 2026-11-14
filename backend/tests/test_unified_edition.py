"""Offline regression suite. All providers are fakes; never run live acceptance."""
import copy
from datetime import timedelta
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from app.services import edition_contract as c
from app.services.edition_budget import Budget, model_estimate, number
from app.services.edition_pipeline import EditionPipeline, run_path, edition_lock
from app.services.episode_workspace import EpisodeWorkspace
from app.services.time_context import china_now
from app.models.news import News

FACT = '政策已公布，后续实施仍有条件。'
EVENT = dict(id='E1', title='重大政策变化', importance='major', reason='影响跨市场定价',
             lane='global_policy', purpose='discovery', candidate_ids=['S1'], read_ids=['S1'])


def fixtures():
    source = dict(id='body-1', title='政策发布与适用条件', url='https://example.com/article/1',
        text=FACT * 8, event_ids=['E1'], direct_scopes=[], source_role={})
    body = FACT + '[N:body-1]'
    written = dict(title='政策变化与条件', summary='关注变化及条件', body=body, core_opinions=['保留条件'],
        source_checks=[dict(source_id='body-1', source_quote=FACT, report_quote=FACT)],
        event_coverage=[dict(event_id='E1', quote=FACT)],
        script_event_coverage=[dict(event_id='E1', quote=FACT)],
        programme=dict(mainline='政策变化仍须关注实施条件', choices=[dict(topic='政策及条件',
            editorial_reason='理解变化的适用边界', report_quotes=[FACT])], omitted=[]), script=FACT)
    assessment = dict(events=[dict(id='E1', status='ready', reason='有明确正文及条件',
        evidence=[dict(source_id='body-1', quote=FACT)])], missed_major_events=[],
        additional_searches=[], additional_reads=[], watchlist_checks=[])
    reviewed = dict(passed=True, issues=[], source_checks=[dict(source_id='body-1',
        source_quote=FACT, report_quote=FACT, status='supported')],
        agenda_checks=[dict(event_id='E1', status='covered', report_quote=FACT, script_quote=FACT)],
        spoken_review=dict(passed=True, issues=[], checks=[dict(facet=f, status='preserved',
            report_quote=FACT, script_quote=FACT, reason='保留变化及实施条件')
            for f in ('facts', 'judgment', 'qualifiers')]))
    return source, written, assessment, reviewed


def state():
    price = dict(input='2', output='10', cache_read='2', cache_write='2')
    return dict(id='edition-' + 'a' * 32, cutoff=china_now().isoformat(), status='prepared',
        report_type='morning', watchlist=[], candidates={}, sources={}, reservations=[], usage=[],
        policy=dict(model_prices=dict(analysis=price, review=price), search_price_usd='.001',
            estimated_limit_usd='50', max_model_reservations=5, max_search_requests=24,
            max_body_urls=64, max_input_characters=65000, total_input_characters=325000,
            total_output_tokens=30000, audio_enabled=False))


class StageContextRegression(unittest.TestCase):
    def restore_candidates(self, encoded):
        def decode(value):
            if isinstance(value, dict):
                if set(value) == {'$ref'}:
                    return decode(encoded['candidate_shared'][value['$ref']])
                return {k: decode(v) for k, v in value.items()}
            if isinstance(value, list): return [decode(v) for v in value]
            return value
        if 'candidate_columns' not in encoded:
            return copy.deepcopy(encoded['candidates'])
        return {cid: dict(zip(encoded['candidate_columns'][:-1], row[:-1]), **decode(row[-1]))
                for cid, row in encoded['candidates'].items()}

    def test_real_large_candidate_catalogue_is_lossless_and_smaller(self):
        from app.services.edition_context import candidate_packet
        candidates = json.loads((Path(__file__).parent / 'fixtures/edition_cost_sample.json').read_text())['candidates']
        before = copy.deepcopy(candidates)
        encoded = candidate_packet(candidates)
        restored = self.restore_candidates(encoded)
        self.assertEqual(restored, before)
        self.assertEqual(candidates, before)
        compact = json.dumps(encoded, ensure_ascii=False, separators=(',', ':'))
        self.assertLess(len(compact), len(json.dumps(dict(candidates=candidates), ensure_ascii=False)))
        self.assertEqual(len(encoded['candidates']), 92)

    def test_large_real_agenda_includes_system_brief_inside_request_limit(self):
        from app.services.edition_context import packet
        from app.services.edition_inputs import messages_for
        sample = json.loads((Path(__file__).parent / 'fixtures/edition_cost_sample.json').read_text())
        run = state(); run.update(candidates=sample['candidates'], watchlist=sample['watchlist'])
        messages = messages_for('agenda', c.AGENDA, packet(run, 'agenda'), china_now(), 'morning')
        self.assertLessEqual(sum(len(m['content']) for m in messages), run['policy']['max_input_characters'])
        self.assertIn('candidate_columns', messages[0]['content'])

    def test_shared_context_never_replaces_unique_warning_or_scope(self):
        from app.services.edition_context import candidate_packet
        candidates = {sid: dict(title='同一事件', url='https://example.com/' + sid,
            snippet='各来源摘要', published_hint=None, reading_status='metadata_only',
            discovered_by=[dict(scope=scope)], retrieval_assessments=[dict(flags=[flag])])
            for sid, scope, flag in [('S1', 'A:600900', 'old_session'), ('S2', 'A:002714', 'commentary')]}
        value = candidate_packet(candidates)
        self.assertEqual(self.restore_candidates(value), candidates)

    def test_reserved_codec_key_falls_back_without_overwriting_source(self):
        from app.services.edition_context import candidate_packet
        candidates = dict(S1=dict(title='来源原字段', url='https://example.com/1', snippet='摘要',
                                 published_hint=None, extra={'$ref': 5}))
        self.assertEqual(candidate_packet(candidates), dict(candidates=candidates))

    def test_assessment_keeps_major_and_unread_snippets_and_all_candidate_titles(self):
        from app.services.edition_context import assessment_candidates
        value = self.context()
        value['candidates'] = {cid: dict(title=cid, url='https://example.com/' + cid,
            snippet='完整摘要' + cid) for cid in ('S1', 'S2', 'S3', 'S4', 'S5')}
        value['agenda']['excluded_candidates'] = [dict(candidate_ids=['S2'], reason='无新增背景')]
        value['sources']['body-1']['candidate_id'] = 'S4'
        value['sources']['body-2'] = dict(value['sources']['body-1'], id='body-2', candidate_id='S1')
        before = copy.deepcopy(value)
        result = assessment_candidates(value)
        self.assertEqual(set(result), set(value['candidates']))
        self.assertEqual(result['S1']['snippet'], '完整摘要S1')
        self.assertEqual(result['S3']['snippet'], '完整摘要S3')
        self.assertEqual(result['S5']['snippet'], '完整摘要S5')
        self.assertIsNone(result['S2']['snippet'])
        self.assertIsNone(result['S4']['snippet'])
        self.assertEqual(value, before)
        for cid, row in result.items(): self.assertEqual(row['title'], value['candidates'][cid]['title'])

    def test_forecast_replaces_draft_allowance_with_actual_saved_draft_and_keeps_all_known_bodies(self):
        from app.services.edition_inputs import editorial_forecast
        value = self.context()
        draft = value.pop('draft')
        value['sources']['contrary'] = dict(value['sources']['body-1'], id='contrary', event_ids=['E9'])
        before = copy.deepcopy(value)
        first = editorial_forecast(value, china_now())
        self.assertEqual(first[1]['future_draft_allowance_bytes'], 40000)
        self.assertEqual(set(first[1]['source_ids']), {'body-1', 'contrary'})
        self.assertEqual(value, before)
        value['draft'] = draft
        second = editorial_forecast(value, china_now())
        self.assertEqual(second[1]['future_draft_allowance_bytes'], 0)
        self.assertGreater(second[1]['known_input_bytes'], first[1]['known_input_bytes'])

    def context(self):
        source, written, assessment, _ = fixtures()
        value = state()
        value.update(candidates={'S1': dict(title='政策', snippet='仍有条件'),
                                 'S2': dict(title='其他线索', snippet='不能静默漏掉')},
            agenda=dict(events=[copy.deepcopy(EVENT)], excluded_candidates=[]),
            sources={'body-1': source}, assessment=assessment, draft=written,
            read_receipts=[dict(candidate_id='S1', event_id='E1', status='ok',
                                response_capture='private-snapshot-path')])
        return value

    def test_agenda_keeps_every_candidate_without_body_or_process(self):
        from app.services.edition_context import packet
        value = packet(self.context(), 'agenda')
        self.assertEqual(set(value['candidates']), {'S1', 'S2'})
        self.assertNotIn('sources', value)
        self.assertNotIn('assessment', value)

    def test_writing_and_review_remove_directory_but_keep_major_and_original_body(self):
        from app.services.edition_context import packet
        state = self.context()
        for stage in ('writing', 'review'):
            value = packet(state, stage)
            self.assertNotIn('candidates', value)
            self.assertNotIn('read_receipts', value)
            self.assertEqual(value['agenda'], state['agenda'])
            self.assertEqual(value['sources']['body-1']['text'], state['sources']['body-1']['text'])
        self.assertEqual(packet(state, 'review')['draft'], state['draft'])

    def test_contrary_body_and_separate_watchlist_evidence_are_not_filtered_out(self):
        from app.services.edition_context import packet
        value = self.context()
        value['sources']['contrary'] = dict(value['sources']['body-1'], id='contrary', text='存在相反解释')
        value['sources']['company'] = dict(value['sources']['body-1'], id='company', event_ids=['E2'])
        value['assessment']['watchlist_checks'] = [dict(key='A:600900', status='covered',
            evidence=[dict(source_id='company', quote=FACT)])]
        self.assertEqual(set(packet(value, 'writing')['sources']), {'body-1', 'contrary', 'company'})

    def test_only_exact_duplicate_metadata_removed_and_state_is_unchanged(self):
        from app.services.edition_context import packet
        value = self.context()
        value['sources']['body-1']['metadata'] = dict(id='body-1', title='其他口径标题',
            published='2026-11-13', reading_scope='public_visible_body', body_quality={'warning': True})
        before = copy.deepcopy(value)
        source = packet(value, 'assessment')['sources']['body-1']
        self.assertNotIn('id', source['metadata'])
        self.assertEqual(source['metadata']['title'], '其他口径标题')
        self.assertEqual(source['metadata']['body_quality'], {'warning': True})
        self.assertEqual(source['metadata']['published'], '2026-11-13')
        self.assertEqual(value, before)

    def test_patch_keeps_all_candidates_failure_reasons_and_last_assessment(self):
        from app.services.edition_context import packet
        value = self.context()
        value['read_receipts'].append(dict(candidate_id='S2', event_id='E1', status='failed', reason='timeout'))
        result = packet(value, 'patch_assessment')
        self.assertTrue(result['last_assessment'])
        self.assertEqual(set(result['candidates']), {'S1', 'S2'})
        self.assertEqual(result['read_receipts'][-1]['reason'], 'timeout')
        self.assertNotIn('response_capture', result['read_receipts'][0])

    def test_review_keeps_cited_body_on_resume(self):
        from app.services.edition_context import packet
        value = self.context()
        value['assessment']['events'][0]['status'] = 'excluded'
        self.assertIn('body-1', packet(value, 'review')['sources'])


class ContractRegression(unittest.TestCase):
    def test_real_failed_election_sources_remain_a_major_gap(self):
        frozen = json.loads((Path(__file__).parent / 'fixtures/unified_major_omission.json').read_text())
        source = frozen['other_macro_source']
        source.update(event_ids=['E2'], direct_scopes=[], source_role={})
        events = {'E1': dict(EVENT, title='中期选举', candidate_ids=list(frozen['candidates']), read_ids=[]),
                  'E2': dict(EVENT, id='E2', title='美债收益率', importance='context', purpose='commentary')}
        value = dict(events=[dict(id='E1', status='excluded', reason='两篇选举来源超时，已有其他国际材料'),
            dict(id='E2', status='ready', reason='有另一篇收益率全文', evidence=[
                dict(source_id=source['id'], quote=source['text'][:100])])], watchlist_checks=[])
        self.assertEqual(c.assess(value, events, {source['id']: source}, set()), ['E1'])

    def test_major_candidate_cannot_disappear_in_selection(self):
        with self.assertRaisesRegex(ValueError, 'unaccounted'):
            c.agenda(dict(events=[copy.deepcopy(EVENT)]), {'S1': {}, 'S2': {}}, set())

    def test_macro_category_cannot_replace_missing_major_event(self):
        source, _, assessment, _ = fixtures()
        assessment['events'][0].update(status='excluded', reason='已有另一篇利率报道')
        self.assertEqual(c.assess(assessment, {'E1': EVENT}, {'body-1': source}, set()), ['E1'])

    def test_unread_or_wrong_event_body_is_not_evidence(self):
        source, _, assessment, _ = fixtures(); source['event_ids'] = ['E2']
        with self.assertRaisesRegex(ValueError, 'scope_invalid'):
            c.assess(assessment, {'E1': EVENT}, {'body-1': source}, set())

    def test_company_peer_is_not_direct_evidence(self):
        source, _, assessment, _ = fixtures()
        assessment['watchlist_checks'] = [dict(key='A:600900', status='covered', reason='正文涉及水电',
            evidence=[dict(source_id='body-1', quote=FACT)])]
        with self.assertRaisesRegex(ValueError, 'subject_mismatch'):
            c.assess(assessment, {'E1': EVENT}, {'body-1': source}, {'A:600900'})

    def test_bank_commentary_does_not_become_original_release(self):
        source, _, assessment, _ = fixtures()
        event = dict(EVENT, purpose='released_policy')
        source['source_role']['original_policy_release_allowed'] = False
        with self.assertRaisesRegex(ValueError, 'role_invalid'):
            c.assess(assessment, {'E1': event}, {'body-1': source}, set())

    def test_review_cannot_pass_when_audio_loses_major_event(self):
        source, written, _, reviewed = fixtures(); reviewed['agenda_checks'] = []
        with self.assertRaisesRegex(ValueError, 'major_event_omitted'):
            c.review(reviewed, {'E1': EVENT}, {'body-1': source}, written)

    def test_fabricated_quote_rejected(self):
        source, written, _, _ = fixtures(); written['source_checks'][0]['source_quote'] = '原文不存在的结论'
        with self.assertRaisesRegex(ValueError, 'quote_not_found'):
            c.draft(written, {'E1': EVENT}, {'body-1': source})

    def test_conflicting_duplicate_key_not_repaired_by_model(self):
        with self.assertRaisesRegex(ValueError, 'duplicate_json_key'):
            c.decode('{"passed":true,"passed":false}')


class BudgetRegression(unittest.TestCase):
    def test_forecast_uses_known_stage_input_instead_of_maximum_character_cap(self):
        from app.services.edition_budget import protection
        run = state()
        forecasts = [dict(stage=s, known_input_bytes=1000, future_draft_allowance_bytes=2000,
            output_tokens=1000) for s in ('writing', 'review')]
        amount, rows = protection(run['policy'], forecasts)
        self.assertEqual(str(amount), '0.032')
        run['policy'].update(editorial_forecast='known_payload_v1', estimated_limit_usd='.05')
        Budget(run, lambda: None, lambda: forecasts).reserve('search')
        self.assertEqual(len(run['reservations']), 1)
        self.assertEqual(run['budget_forecast']['editorial'], rows)

    def test_growing_material_forecast_stops_before_another_fee(self):
        run = state()
        run['policy'].update(editorial_forecast='known_payload_v1', estimated_limit_usd='.05')
        forecast = [dict(stage=s, known_input_bytes=1000, future_draft_allowance_bytes=0,
            output_tokens=1000) for s in ('writing', 'review')]
        budget = Budget(run, lambda: None, lambda: forecast)
        budget.reserve('search')
        forecast[0]['known_input_bytes'] = 100000
        with self.assertRaisesRegex(ValueError, 'estimated_budget_exhausted'):
            budget.reserve('search')
        self.assertEqual(len(run['reservations']), 1)

    def test_missing_or_invalid_dynamic_forecast_is_not_free(self):
        from app.services.edition_budget import protection
        run = state(); run['policy']['editorial_forecast'] = 'known_payload_v1'
        with self.assertRaisesRegex(ValueError, 'forecast_missing'):
            Budget(run, lambda: None).reserve('search')
        with self.assertRaisesRegex(ValueError, 'forecast_invalid'):
            protection(run['policy'], [])

    def test_complete_known_usage_updates_accounting_but_preserves_attempt_and_original_reserve(self):
        from app.services.edition_budget import accounted
        run = state(); budget = Budget(run, lambda: None)
        reservation = budget.reserve('model', stage='writing', messages=[dict(content='资料')], output=1000)
        original = reservation['estimated_usd']
        budget.record_usage(reservation, dict(http_status=200, provider='ofox_anthropic',
            input_tokens=100, output_tokens=20, cache_read_tokens=0, cache_write_tokens=0))
        self.assertEqual(str(accounted(reservation)), '0.0004')
        self.assertEqual(reservation['estimated_usd'], original)
        self.assertEqual(len(run['reservations']), 1)

    def test_unknown_cache_failure_or_compatible_usage_retains_full_reservation(self):
        from app.services.edition_budget import accounted
        for overrides in [dict(cache_write_tokens=None), dict(http_status=402), dict(provider='compatible'),
                          dict(transport_error='timeout'), dict(input_tokens=True)]:
            run = state(); budget = Budget(run, lambda: None)
            reservation = budget.reserve('model', stage='writing', messages=[dict(content='资料')], output=1000)
            usage = dict(http_status=200, provider='ofox_anthropic', input_tokens=100,
                output_tokens=20, cache_read_tokens=0, cache_write_tokens=0)
            usage.update(overrides); budget.record_usage(reservation, usage)
            self.assertEqual(str(accounted(reservation)), reservation['estimated_usd'])

    def test_receipt_cost_above_reservation_still_blocks_next_paid_action(self):
        run = state(); run['policy']['estimated_limit_usd'] = '2'
        budget = Budget(run, lambda: None)
        reservation = budget.reserve('model', stage='writing', messages=[dict(content='资料')], output=1000)
        budget.record_usage(reservation, dict(http_status=200, provider='ofox_anthropic',
            input_tokens=2000000, output_tokens=20, cache_read_tokens=0, cache_write_tokens=0))
        with self.assertRaisesRegex(ValueError, 'estimated_budget_exhausted'):
            budget.reserve('search')
        self.assertEqual(len(run['reservations']), 1)

    def test_unknown_or_nan_price_is_not_free(self):
        for value in (None, 'NaN', 'Infinity', '-1'):
            with self.subTest(value=value), self.assertRaises(ValueError): number(value)

    def test_money_reserved_for_editorial_before_any_search(self):
        run = state(); run['policy']['estimated_limit_usd'] = '.01'
        with self.assertRaisesRegex(ValueError, 'estimated_budget_exhausted'):
            Budget(run, lambda: None).reserve('search')
        self.assertEqual(run['reservations'], [])

    def test_failed_attempt_still_uses_same_run_budget(self):
        run = state(); budget = Budget(run, lambda: None)
        for _ in range(5): budget.reserve('model', stage='assessment', messages=[dict(content='正文')], output=100)
        with self.assertRaisesRegex(ValueError, 'model_budget_exhausted'):
            Budget(run, lambda: None).reserve('model', stage='review', messages=[dict(content='审稿')], output=100)
        self.assertEqual(len(run['reservations']), 5)

    def test_unknown_transport_usage_keeps_reservation(self):
        run = state(); Budget(run, lambda: None).reserve('model', stage='agenda', messages=[dict(content='正文')], output=100)
        self.assertEqual(run['reservations'][0]['actual_usage'], 'unknown_until_receipt')

    def test_no_save_no_request_reservation(self):
        def broken(): raise OSError('disk unavailable')
        with self.assertRaises(OSError):
            Budget(state(), broken).reserve('search')


class PipelineRegression(unittest.IsolatedAsyncioTestCase):
    async def test_preflight_never_opens_provider_connection(self):
        from app.config import settings
        from app.services.edition_pipeline import preflight
        config = settings.model_copy(update=dict(edition_estimate_accepted=False, edition_price_table={}))
        with patch('app.services.edition_pipeline.read_app_watchlist', AsyncMock(return_value=[])), \
             patch('app.services.generic_extraction.runtime_status', return_value=dict(ready=True)), \
             patch('app.services.edition_pipeline.complete', AsyncMock()) as model:
            result = await preflight(config=config)
        self.assertFalse(result['ready_to_run'])
        self.assertIn('cost_estimate_not_accepted', result['blockers'])
        self.assertEqual(result['model_requests'], 0)
        model.assert_not_awaited()

    async def test_scheduler_morning_and_evening_share_same_entry(self):
        from app.services.scheduler import SchedulerService
        scheduler = SchedulerService.__new__(SchedulerService)
        scheduler._generate_unified_edition = AsyncMock(return_value=None)
        await scheduler.generate_morning_report()
        await scheduler.generate_evening_report()
        self.assertEqual([call.args[0] for call in scheduler._generate_unified_edition.await_args_list], ['morning', 'evening'])

    async def scenario(self, directory, *, missing=False, fail_review=False, empty_patch=False):
        source, written, assessment, reviewed = fixtures()
        if missing: assessment['events'][0]['status'] = 'missing'
        if empty_patch:
            assessment['additional_reads'] = [dict(event_id='E1', candidate_id='S1',
                increment='missing_context', reason='检查这篇已读政策正文是否还有未核对的适用条件')]
        run = state(); now = china_now()
        workspace = EpisodeWorkspace(root=directory / 'evidence', now=now)
        def search(ws, query, **kwargs):
            ws.web_search_attempts = getattr(ws, 'web_search_attempts', 0) + 1
            return dict(status='ok', results=[dict(title=source['title'], url=source['url'], snippet=FACT)])
        def read(ws, url, **kwargs):
            item = News(id='body-1', title=source['title'], content=source['text'],
                source='公开网页可见正文-离线替身', source_url=url, published_at=now - timedelta(hours=1))
            ws.add([item]); return dict(status='ok', material=dict(id='body-1'))
        replies = [dict(events=[copy.deepcopy(EVENT)], excluded_candidates=[]), assessment, written, reviewed]
        stages = []
        async def model(task, messages, limit):
            stages.append(task)
            if fail_review and task == 'review': raise RuntimeError('review HTTP 402')
            return json.dumps(replies[len(stages) - 1], ensure_ascii=False)
        pipeline = EditionPipeline(run, directory, workspace, model=model, search=search, read=read, check=AsyncMock())
        return pipeline, stages, written

    async def selection_scenario(self, directory, *, patch_search=False, invalid=False, failed_first=False):
        pipeline, _, _ = await self.scenario(directory)
        candidates = {cid: dict(title='政策最新变化' + cid, url='https://example.com/' + cid,
            snippet=FACT, search_links=[]) for cid in ('S1', 'S2', 'S3')}
        agenda = dict(events=[dict(EVENT, candidate_ids=list(candidates), read_ids=['S2', 'S1'])], excluded_candidates=[])
        assessment = fixtures()[2]
        assessment['events'][0]['status'] = 'missing'
        if patch_search:
            assessment['additional_searches'] = [dict(event_id='E1', query='政策条件', purpose='discovery',
                increment='missing_context', reason='核对这次公布政策的实施条件和适用范围')]
            if invalid: assessment['additional_searches'][0].pop('reason')
        calls, read_ids, searches = [], [], []
        async def search(jobs):
            searches.append(jobs)
            pipeline.state['candidates'] = candidates
            if len(searches) > 1:
                for row in candidates.values():
                    row['search_links'] = jobs
        async def read(jobs, events):
            for job in jobs:
                cid = job['candidate_id']; read_ids.append(cid)
                if failed_first and len(read_ids) == 1: continue
                source = dict(fixtures()[0], id='B' + cid, candidate_id=cid, url=candidates[cid]['url'])
                pipeline.state['sources'][source['id']] = source
        async def call(stage, brief, payload):
            calls.append(stage)
            # Match the real call boundary: record phase and delivered text.
            from app.services.edition_budget import digest
            pipeline.state['phase'] = stage
            pipeline.state.setdefault('delivered_sources', {})[stage] = {
                sid: digest(source['text']) for sid, source in payload.get('sources', {}).items()}
            result = copy.deepcopy(agenda if stage == 'agenda' else assessment)
            if stage == 'patch_assessment': result['additional_searches'] = []
            return result
        pipeline.searches, pipeline.reads, pipeline.call = search, read, call
        return pipeline, calls, read_ids, searches

    async def test_actual_execution_uses_one_model_selected_representative(self):
        with tempfile.TemporaryDirectory() as temporary:
            pipeline, calls, reads, _ = await self.selection_scenario(Path(temporary))
            self.assertIsNone(await pipeline.execute())
            self.assertEqual(reads, ['S2'])
            self.assertEqual(calls, ['agenda', 'assessment'])
            self.assertEqual(pipeline.state['read_selection'][0]['deferred_ids'], ['S1', 'S3'])

    async def test_patch_search_results_are_screened_before_downloading(self):
        with tempfile.TemporaryDirectory() as temporary:
            pipeline, calls, reads, _ = await self.selection_scenario(Path(temporary), patch_search=True)
            self.assertIsNone(await pipeline.execute())
            self.assertEqual(len(reads), 2)
            self.assertEqual(reads[0], 'S2')
            self.assertEqual(len(set(reads)), 2)
            self.assertEqual(calls, ['agenda', 'assessment', 'patch_assessment'])
            self.assertEqual(len(pipeline.state['candidates']), 3)

    async def test_invalid_increment_stops_before_patch_search(self):
        with tempfile.TemporaryDirectory() as temporary:
            pipeline, calls, reads, searches = await self.selection_scenario(Path(temporary), patch_search=True, invalid=True)
            with self.assertRaisesRegex(ValueError, 'increment_required'): await pipeline.execute()
            self.assertEqual(len(searches), 1)
            self.assertEqual(calls, ['agenda', 'assessment'])

    async def test_failed_representative_selects_one_alternate_without_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            pipeline, calls, reads, _ = await self.selection_scenario(Path(temporary), failed_first=True)
            self.assertIsNone(await pipeline.execute())
            self.assertEqual(len(reads), 2)
            self.assertNotEqual(reads[1], reads[0])
            self.assertEqual(calls, ['agenda', 'assessment'])

    async def test_normal_whole_path_four_calls_and_persistent_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            pipeline, stages, written = await self.scenario(Path(temporary))
            pipeline.state['policy']['editorial_forecast'] = 'known_payload_v1'
            with patch('app.services.podcast_script_cache.save'), patch('app.services.podcast_script_cache.load', return_value=written['script']):
                report = await pipeline.execute()
            self.assertEqual(stages, ['analysis', 'analysis', 'analysis', 'review'])
            self.assertEqual(report.id, pipeline.state['id'])
            self.assertEqual(pipeline.state['status'], 'reviewed_text')
            self.assertEqual(len(pipeline.state['sources']), 1)
            self.assertTrue((Path(temporary) / 'receipt.txt').is_file())
            self.assertEqual(set(pipeline.state['delivered_sources']['writing']), {'body-1'})

    async def test_missing_major_stops_before_writing_and_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            pipeline, stages, _ = await self.scenario(Path(temporary), missing=True)
            self.assertIsNone(await pipeline.execute())
            self.assertEqual(len(stages), 2)
            self.assertEqual(pipeline.state['missing'], ['E1'])

    async def test_402_keeps_draft_and_stops_without_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            pipeline, stages, _ = await self.scenario(Path(temporary), fail_review=True)
            with self.assertRaisesRegex(RuntimeError, '402'): await pipeline.execute()
            self.assertEqual(stages.count('review'), 1)
            self.assertIn('draft', pipeline.state)
            self.assertEqual(pipeline.state['status'], 'failed')
            self.assertTrue(pipeline.state['resume_allowed'])
            self.assertFalse(pipeline.state.get('app_written', False))

    async def test_patch_without_new_body_does_not_buy_more_assessment(self):
        with tempfile.TemporaryDirectory() as temporary:
            pipeline, stages, _ = await self.scenario(Path(temporary), missing=True, empty_patch=True)
            self.assertIsNone(await pipeline.execute())
            self.assertEqual(stages, ['analysis', 'analysis'])
            self.assertEqual(pipeline.state['stop_reason'], 'patch_no_new_body')

    async def test_single_stage_scope_blocks_hidden_retry(self):
        from app.services.model_usage import edition_model_scope, reserve_call
        with edition_model_scope('same-edition', 'review', lambda row: None):
            reserve_call()
            with self.assertRaises(RuntimeError): reserve_call()

    async def test_empty_cache_does_not_buy_new_audio_script(self):
        from app.services.podcast_generator import PodcastGeneratorService
        generator = PodcastGeneratorService.__new__(PodcastGeneratorService)
        generator.user_nickname = '测试'
        generator._prepare_podcast_text = AsyncMock()
        with patch('app.services.podcast_script_cache.load', return_value=None):
            with self.assertRaisesRegex(RuntimeError, '已审口播'):
                await generator.generate_podcast(SimpleNamespace(id='example'), require_verified_cache=True)
        generator._prepare_podcast_text.assert_not_awaited()

    async def test_reviewed_audio_failure_has_one_attempt_and_no_paid_fallback(self):
        from app.services.podcast_generator import PodcastGeneratorService
        generator = PodcastGeneratorService.__new__(PodcastGeneratorService)
        generator.voice, generator.rate, generator.volume = 'fake', '+0%', '+0%'
        communicate = SimpleNamespace(save=AsyncMock(side_effect=RuntimeError('edge unavailable')))
        before = AsyncMock()
        with tempfile.TemporaryDirectory() as temporary:
            generator.output_dir = Path(temporary)
            with patch('app.services.podcast_generator.edge_tts.Communicate', return_value=communicate) as engine:
                with self.assertRaisesRegex(RuntimeError, 'edge unavailable'):
                    await generator._generate_reviewed_tts_once(FACT, str(Path(temporary) / 'out.mp3'), before)
            self.assertEqual(engine.call_count, 1)
            communicate.save.assert_awaited_once()
            before.assert_awaited_once_with(len(FACT))
            self.assertEqual(list(Path(temporary).iterdir()), [])

    async def test_duplicate_process_cannot_start_second_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            with edition_lock(Path(temporary)):
                with self.assertRaisesRegex(RuntimeError, 'already_running'):
                    with edition_lock(Path(temporary)): pass

    async def test_operator_cannot_read_arbitrary_path(self):
        for identifier in ('../config', '/etc/passwd', 'edition-invalid'):
            with self.assertRaises(ValueError): run_path(identifier)


class AllStageBudgetRegression(unittest.IsolatedAsyncioTestCase):
    async def test_initial_batch_stops_before_first_search(self):
        with tempfile.TemporaryDirectory() as temporary:
            pipeline, _, _ = await PipelineRegression().scenario(Path(temporary))
            from app.services.edition_budget import search_batch_plan
            from app.services.edition_inputs import edition_forecast
            p = pipeline.state['policy']
            p.update(edition_forecast='remaining_stages_v1',
                request_input_pricing=dict(analysis='uncached_request_v1', review='uncached_request_v1'))
            self_rows = lambda: edition_forecast(pipeline.state, pipeline.workspace.now)
            pipeline.budget.forecast = self_rows
            one = search_batch_plan(p, self_rows(), 1)
            p['estimated_limit_usd'] = one['required_estimated_usd']
            search = unittest.mock.Mock(side_effect=AssertionError('must not connect'))
            pipeline.search = search
            with self.assertRaisesRegex(ValueError, 'estimated_budget_exhausted'):
                await pipeline.searches([dict(lane='global_policy', query='policy news '+str(i)) for i in range(12)])
            search.assert_not_called()
            self.assertEqual(pipeline.state['reservations'], [])

    async def test_normal_four_call_path_with_new_ledger(self):
        with tempfile.TemporaryDirectory() as temporary:
            pipeline, stages, _ = await PipelineRegression().scenario(Path(temporary))
            pipeline.state['policy'].update(edition_forecast='remaining_stages_v1',
                request_input_pricing=dict(analysis='uncached_request_v1', review='uncached_request_v1'))
            self.assertIsNotNone(await pipeline.execute())
            self.assertEqual(len(stages), 4)
            self.assertTrue(pipeline.state['search_batch_checks'])

    async def test_same_query_in_batch_is_not_bought_twice(self):
        with tempfile.TemporaryDirectory() as temporary:
            pipeline, _, _ = await PipelineRegression().scenario(Path(temporary))
            pipeline.state['policy']['edition_forecast'] = 'remaining_stages_v1'
            await pipeline.searches([dict(lane='global_policy', query='same policy')] * 2)
            self.assertEqual(len(pipeline.state['search_receipts']), 1)
            self.assertEqual(pipeline.state['search_batch_checks'][0]['search_batch_count'], 1)

    async def test_future_context_replaced_by_actual_results_without_losing_sources(self):
        from app.services.edition_inputs import edition_forecast
        source, draft, assessment, _ = fixtures()
        run = state(); run['sources'] = {'body-1': source, 'contrary': dict(source, text='相反观点')}
        first = edition_forecast(run, china_now())
        self.assertGreater(next(r for r in first if r['stage']=='review')['future_input_tokens'], 0)
        run.update(agenda=dict(events=[EVENT]), assessment=assessment, draft=draft)
        before = copy.deepcopy(run)
        rows = edition_forecast(run, china_now())
        for row in rows:
            if row['stage'] in {'writing', 'review'}:
                self.assertEqual(row['future_input_tokens'], 0)
                self.assertEqual(set(row['source_ids']), {'body-1', 'contrary'})
        self.assertEqual(run, before)

    async def test_patch_forecast_only_when_research_requested(self):
        from app.services.edition_inputs import edition_forecast
        run = state(); run.update(agenda=dict(events=[EVENT]), assessment=fixtures()[2])
        self.assertNotIn('patch_assessment', [r['stage'] for r in edition_forecast(run, china_now())])
        run['assessment']['additional_searches'] = [dict(query='new policy')]
        self.assertIn('patch_assessment', [r['stage'] for r in edition_forecast(run, china_now())])
        run['reservations'].append(dict(kind='model', stage='patch_assessment'))
        self.assertNotIn('patch_assessment', [r['stage'] for r in edition_forecast(run, china_now())])


class EmbeddedEventRegression(unittest.IsolatedAsyncioTestCase):
    OTHER = '媒体报道另一项重大事项，结论仍有待进一步核实。'

    def events(self):
        return [copy.deepcopy(EVENT), dict(EVENT, id='E2', title='综述中的另一项重大事项')]

    def test_one_candidate_can_belong_to_two_distinct_events(self):
        value = dict(events=self.events(), excluded_candidates=[])
        self.assertEqual(c.agenda(value, {'S1': {}}, set()), value)

    def test_assigned_candidate_cannot_also_be_excluded(self):
        with self.assertRaisesRegex(ValueError, 'unaccounted'):
            c.agenda(dict(events=self.events(), excluded_candidates=[
                dict(candidate_ids=['S1'], reason='不能一边使用一边排除')]), {'S1': {}}, set())

    def test_duplicate_and_unknown_candidates_remain_rejected(self):
        duplicate = copy.deepcopy(EVENT); duplicate['candidate_ids'] = ['S1', 'S1']
        with self.assertRaisesRegex(ValueError, 'candidates_invalid'):
            c.agenda(dict(events=[duplicate]), {'S1': {}}, set())
        for excluded in ([dict(candidate_ids=['S2'], reason='不相关')] * 2,
                         [dict(candidate_ids=['S3'], reason='未知候选')]):
            with self.subTest(excluded=excluded), self.assertRaisesRegex(ValueError, 'unaccounted'):
                c.agenda(dict(events=[copy.deepcopy(EVENT)], excluded_candidates=excluded), {'S1': {}, 'S2': {}}, set())

    def test_real_saved_overview_has_separate_market_and_election_passages(self):
        sample = json.loads((Path(__file__).parent / 'fixtures/edition_cost_sample.json').read_text())
        source = next(s for s in sample['sources'] if s['id']=='sample-4a6547aff764077f2bb4f0a6')
        text = source['text']
        market = '科创50指数飙升近10%'
        election = '美国媒体预测，民主党夺回美国国会参议院控制权。'
        self.assertIn(market, text); self.assertIn(election, text)
        events = self.events(); events[0].update(title='市场行情', lane='a_market')
        events[1]['title'] = '媒体对中期选举作出的预测，待核实'
        c.agenda(dict(events=events), {'S1': {}}, set())
        sid=source['id']; material=dict(source, event_ids=['E1', 'E2'])
        assessment=dict(events=[dict(id=eid,status='ready',reason='只核对这一段来源归属，非独立事实验证',
            evidence=[dict(source_id=sid,quote=q)]) for eid,q in [('E1',market),('E2',election)]], watchlist_checks=[])
        self.assertEqual(c.assess(assessment, {e['id']:e for e in events}, {sid:material}, set()), [])
        self.assertEqual(len({sid:material}), 1)  # Two events never mean two independent sources.

    async def shared_scenario(self, directory, *, discovered=False, remains_missing=False):
        pipeline, _, _ = await PipelineRegression().scenario(directory)
        source, written, assessment, reviewed = fixtures()
        events=self.events(); source['text'] += self.OTHER
        second=dict(id='E2',status='ready',reason='综述中另一段可核对的独立事项',
                    evidence=[dict(source_id='body-1',quote=self.OTHER)])
        first=copy.deepcopy(assessment)
        if discovered:
            first['missed_major_events']=[copy.deepcopy(events[1])]
        else:
            first['events'].append(copy.deepcopy(second))
        patch_assessment=copy.deepcopy(assessment); patch_assessment['events'].append(second)
        if remains_missing:
            patch_assessment['events'][1]=dict(id='E2',status='missing',reason='只有媒体预测，关键依据仍未核实')
        written['body'] += self.OTHER; written['script'] += self.OTHER
        written['event_coverage'].append(dict(event_id='E2',quote=self.OTHER))
        written['script_event_coverage'].append(dict(event_id='E2',quote=self.OTHER))
        reviewed['agenda_checks'].append(dict(event_id='E2',status='covered',
                                             report_quote=self.OTHER,script_quote=self.OTHER))
        replies=[dict(events=events[:1] if discovered else events,excluded_candidates=[]),first]
        if discovered:replies.append(patch_assessment)
        replies.extend([written,reviewed])
        phases=[]; reads=[]
        async def model(task,messages,limit):
            phases.append(pipeline.state['phase'])
            return json.dumps(replies.pop(0),ensure_ascii=False)
        def read(ws,url,**kwargs):
            reads.append(url)
            item=News(id='body-1',title=source['title'],content=source['text'],
                source='公开网页可见正文-离线替身',source_url=url,published_at=pipeline.workspace.now-timedelta(hours=1))
            ws.add([item]);return dict(status='ok',material=dict(id='body-1'))
        pipeline.model,pipeline.read=model,read
        return pipeline,phases,reads

    async def test_initial_two_events_share_one_download_and_four_model_stages(self):
        with tempfile.TemporaryDirectory() as temporary:
            pipeline,phases,reads=await self.shared_scenario(Path(temporary))
            self.assertIsNotNone(await pipeline.execute())
            self.assertEqual(phases,['agenda','assessment','writing','review'])
            self.assertEqual(len(reads),1)
            self.assertEqual(set(pipeline.state['sources']['body-1']['event_ids']),{'E1','E2'})

    async def test_new_event_in_cached_body_can_reach_conditional_assessment(self):
        with tempfile.TemporaryDirectory() as temporary:
            pipeline,phases,reads=await self.shared_scenario(Path(temporary),discovered=True)
            self.assertIsNotNone(await pipeline.execute())
            self.assertEqual(phases,['agenda','assessment','patch_assessment','writing','review'])
            self.assertEqual(len(reads),1)
            self.assertEqual(pipeline.state['patch_progress']['new_or_changed_body_ids'],[])
            self.assertEqual(pipeline.state['patch_progress']['reused_body_event_links'],[
                dict(source_id='body-1',event_id='E2')])
            self.assertEqual(len(pipeline.state['sources']),1)

    async def test_new_link_does_not_certify_coverage_or_bypass_missing_major(self):
        with tempfile.TemporaryDirectory() as temporary:
            pipeline,phases,reads=await self.shared_scenario(Path(temporary),discovered=True,remains_missing=True)
            self.assertIsNone(await pipeline.execute())
            self.assertEqual(phases,['agenda','assessment','patch_assessment'])
            self.assertEqual(len(reads),1)
            self.assertEqual(pipeline.state['missing'],['E2'])
            self.assertNotIn('draft',pipeline.state)


if __name__ == '__main__':
    unittest.main()
