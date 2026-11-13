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
            assessment['additional_reads'] = [dict(event_id='E1', candidate_id='S1')]
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

    async def test_normal_whole_path_four_calls_and_persistent_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            pipeline, stages, written = await self.scenario(Path(temporary))
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


if __name__ == '__main__':
    unittest.main()
