"""Acquisition boundaries, real saved metadata/HTML and fake publisher transport."""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.services.body_acquisition import read_target, failure_class, availability_penalty, summary
from app.services.edition_read_selection import select_candidate, primary_plan
from app.services.edition_pipeline import EditionPipeline
from app.services.web_research import parse_visible_article
from app.services.episode_workspace import EpisodeWorkspace
from app.models.news import News
import test_unified_edition as reference

FIXTURES = Path(__file__).parent / 'fixtures'
NOW = datetime(2026,11,14,9)


def sample(): return json.loads((FIXTURES / 'body_acquisition_sample.json').read_text())


def event():
    return dict(id='E1', title='政策变化及实施条件', lane='global_policy', purpose='discovery',
        reason='核对这次已公布政策对市场的适用条件和影响',
        read_ids=['S1'], candidate_ids=['S1','S2','S3','S4'])


def run_state():
    value = reference.state(); value['cutoff'] = NOW.isoformat()
    value['candidates'] = {cid:dict(title='政策变化及实施条件',
        url='https://publisher'+cid[-1]+'.example/article', snippet='已披露政策及实施条件',
        published_hint='2026-11-14', search_links=[]) for cid in event()['candidate_ids']}
    return value


class AcquisitionMetadata(unittest.TestCase):
    def test_real_failed_batch_has_four_nonarticle_routes_before_http(self):
        from app.services.search_objectives import metadata_blockers
        blocked = {r['candidate_id'] for r in sample()['rows'] if metadata_blockers(r['candidate'])}
        self.assertEqual(blocked, {'S75','S76','S52','S54'})

    def test_real_failed_batch_distinguishes_network_and_access(self):
        counts = [failure_class(r['receipt']['reason']) for r in sample()['rows']]
        self.assertEqual(counts.count('network'),4)
        self.assertEqual(counts.count('access'),2)

    def test_rthk_own_language_proxy_unwraps_exact_publisher_path(self):
        url='https://gbcode.rthk.hk/TuniS/news.rthk.hk/rthk/en/component/k2/1877774-20261114.htm?spTabChangeable=0'
        self.assertEqual(read_target(url),'https://news.rthk.hk/rthk/en/component/k2/1877774-20261114.htm?spTabChangeable=0')

    def test_other_proxy_embedded_target_and_userinfo_never_unwrap(self):
        for url in ['https://example.com/TuniS/news.rthk.hk/article',
                    'https://gbcode.rthk.hk/TuniS/evil.example/article',
                    'https://x@gbcode.rthk.hk/TuniS/news.rthk.hk/article']:
            self.assertEqual(read_target(url),url)

    def test_outside_window_is_skipped_instead_of_just_ranked_last(self):
        state=run_state(); state['candidates']['S1']['published_hint']='2026-10-30'
        chosen, trace=select_candidate(state,event(),['S1'],dict(reason='核对政策',increment='missing_context'))
        self.assertIsNone(chosen)
        self.assertEqual(trace['skipped'][0]['reason'],'published_hint_outside_event_window')

    def test_unknown_publication_remains_body_check_not_assumed_fresh(self):
        state=run_state(); state['candidates']['S1']['published_hint']=None
        chosen,_=select_candidate(state,event(),['S1'],dict(reason='核对政策',increment='missing_context'))
        self.assertEqual(chosen,'S1')

    def test_same_host_failure_prefers_different_host_in_same_event(self):
        state=run_state(); state['candidates']['S2']['url']='https://publisher1.example/other'
        state['read_receipts']=[dict(candidate_id='S1',reason='ConnectTimeoutError')]
        chosen,_=select_candidate(state,event(),['S2','S3'],dict(reason='核对政策',increment='access_failure'))
        self.assertEqual(chosen,'S3')

    def test_host_failure_is_not_a_permanent_publisher_ban(self):
        state=run_state(); state['read_receipts']=[dict(candidate_id='S1',reason='public_http_403')]
        state['candidates']['S2']['url']='https://publisher1.example/other'
        chosen,_=select_candidate(state,event(),['S2'],dict(reason='核对政策',increment='access_failure'))
        self.assertEqual(chosen,'S2')

    def test_stored_body_restores_host_priority_without_clearing_failure(self):
        state=run_state(); state['read_receipts']=[dict(candidate_id='S1',reason='ConnectTimeoutError')]
        self.assertEqual(availability_penalty(state,state['candidates']['S1']['url']),1)
        state['sources']['B1']=dict(url=state['candidates']['S1']['url'])
        self.assertEqual(availability_penalty(state,state['candidates']['S1']['url']),0)
        self.assertEqual(len(state['read_receipts']),1)

    def test_metadata_rejected_candidate_is_not_chosen_again(self):
        state=run_state(); state['read_metadata_rejections']=[dict(candidate_id='S2',event_id='E1',flags=['paused'])]
        chosen,_=select_candidate(state,event(),['S2','S3'],dict(reason='核对政策',increment='access_failure'))
        self.assertEqual(chosen,'S3')


class SavedAnnouncement(unittest.TestCase):
    def row(self): return next(r for r in sample()['rows'] if r['candidate_id']=='S80')
    def raw(self): return (FIXTURES / 'sina_announcement_identity.body').read_bytes()

    def test_real_announcement_without_security_code_is_identified_then_rejected_as_old(self):
        with self.assertRaisesRegex(ValueError,'web_source_time_outside_window'):
            parse_visible_article(self.raw(),self.row()['candidate']['url'],NOW,hours=168)

    def test_same_saved_announcement_can_be_parsed_at_its_original_date(self):
        item=parse_visible_article(self.raw(),self.row()['candidate']['url'],datetime(2026,10,31,9),hours=72)
        self.assertIn('计提资产减值准备',item.content)
        self.assertEqual(item.published_at.date(),datetime(2026,10,30).date())
        self.assertIn('镜像',item.source)

    def test_wrong_requested_company_does_not_borrow_title_identity(self):
        with self.assertRaisesRegex(ValueError,'web_source_not_admitted'):
            parse_visible_article(self.raw(),self.row()['candidate']['url'].replace('stockid=688535','stockid=600900'),NOW,hours=168)

    def test_wrong_announcement_pdf_id_does_not_prove_body_identity(self):
        with self.assertRaisesRegex(ValueError,'web_source_not_admitted'):
            parse_visible_article(self.raw(),self.row()['candidate']['url'].replace('id=12676264','id=99999'),NOW,hours=168)


class AcquisitionReceipt(unittest.TestCase):
    def test_stored_body_is_not_automatically_assessed_evidence(self):
        state=run_state(); state['read_receipts']=[dict(candidate_id='S1',event_id='E1',status='ok',public_http_requests=2)]
        state['sources']['B1']=dict(id='B1',candidate_id='S1',url=state['candidates']['S1']['url'],text='实际文字')
        result=summary(state)
        self.assertEqual(result['stored_article_bodies'],1)
        self.assertEqual(result['assessment_cited_bodies'],0)
        self.assertEqual(result['article_http_requests'],2)

    def test_legacy_http_count_stays_unknown_and_state_unchanged(self):
        state=run_state(); state['read_receipts']=[dict(candidate_id='S1',status='failed',reason='ConnectTimeoutError')]
        old=copy.deepcopy(state); result=summary(state)
        self.assertIsNone(result['article_http_requests']); self.assertEqual(old,state)

    def test_assessment_cites_only_sources_actually_stored_for_attempts(self):
        state=run_state(); state['read_receipts']=[dict(candidate_id='S1',status='ok',public_http_requests=1)]
        state['sources']['B1']=dict(id='B1',candidate_id='S1',url=state['candidates']['S1']['url'],text='原文')
        state['assessment']=dict(events=[dict(status='ready',evidence=[dict(source_id='B1'),dict(source_id='invented')])])
        self.assertEqual(summary(state)['assessment_cited_bodies'],1)


class LiveOpportunityBounds(unittest.IsolatedAsyncioTestCase):
    def pipeline(self, folder, failing=()):
        state=run_state(); ws=EpisodeWorkspace(root=folder / 'evidence',now=NOW)
        calls=[]
        def read(workspace,url,**options):
            calls.append(url); workspace.public_fetch_attempts=getattr(workspace,'public_fetch_attempts',0)+1
            if url in failing: return dict(status='failed',reason='ConnectTimeoutError')
            item=News(id='B1',title='政策变化及实施条件',content='公开政策及实施条件需要独立核对。'*20,
                source='公开网页可见正文-测试',source_url=url,published_at=NOW-timedelta(hours=1))
            workspace.add([item]); return dict(status='ok',url=url,material=dict(id='B1'))
        pipeline=EditionPipeline(state,folder,ws,read=read,check=AsyncMock())
        pipeline.uses_public_reader=True
        return pipeline,calls

    async def test_two_paused_candidates_do_not_exhaust_first_live_opportunity(self):
        with tempfile.TemporaryDirectory() as root:
            pipeline,calls=self.pipeline(Path(root))
            paused={pipeline.state['candidates'][cid]['url'] for cid in ['S1','S2']}
            with patch('app.services.body_acquisition.paused_public',side_effect=lambda url:url in paused):
                jobs,trace=primary_plan([event()]); await pipeline.selected_reads(jobs,{'E1':event()},trace)
            self.assertEqual(calls,[pipeline.state['candidates']['S3']['url']])
            self.assertEqual(len(pipeline.state['sources']),1)
            self.assertEqual(len(pipeline.state['read_metadata_rejections']),2)

    async def test_two_actual_network_failures_stop_even_with_more_candidates(self):
        with tempfile.TemporaryDirectory() as root:
            pipeline,calls=self.pipeline(Path(root),failing=[r['url'] for r in run_state()['candidates'].values()])
            with patch('app.services.body_acquisition.paused_public',return_value=False):
                jobs,trace=primary_plan([event()]); await pipeline.selected_reads(jobs,{'E1':event()},trace)
            self.assertEqual(len(calls),2)
            self.assertEqual(pipeline.workspace.public_fetch_attempts,2)
            self.assertEqual(pipeline.state['sources'],{})

    async def test_metadata_spam_is_skipped_before_reader_and_second_body_is_stored(self):
        with tempfile.TemporaryDirectory() as root:
            pipeline,calls=self.pipeline(Path(root)); pipeline.state['candidates']['S1']['url']='https://example.com/quotes/index.html'
            with patch('app.services.body_acquisition.paused_public',return_value=False):
                jobs,trace=primary_plan([event()]); await pipeline.selected_reads(jobs,{'E1':event()},trace)
            self.assertEqual(len(calls),1)
            self.assertNotIn('/quotes/',calls[0])
            self.assertEqual(pipeline.state['body_acquisition']['stored_article_bodies'],1)

    async def test_one_stored_body_stops_without_download_of_duplicates(self):
        with tempfile.TemporaryDirectory() as root:
            pipeline,calls=self.pipeline(Path(root))
            with patch('app.services.body_acquisition.paused_public',return_value=False):
                jobs,trace=primary_plan([event()]); await pipeline.selected_reads(jobs,{'E1':event()},trace)
            self.assertEqual(len(calls),1)
            self.assertEqual(pipeline.state['read_receipts'][0]['public_http_requests'],1)
            self.assertEqual(pipeline.state['reservations'],[])
