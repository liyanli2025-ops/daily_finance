from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app.services.body_acquisition import failure_class
from app.services.edition_acquisition import recover
from app.services.edition_news_focus import new_window
from app.services.edition_pipeline import EditionPipeline
from app.services.web_research import parse_visible_article
from test_unified_edition import state as make_state


NOW = datetime(2026, 11, 18, 11)


def lead(title, host):
    return dict(title=title, url=f'https://{host}/article', search_links=[])


def event(title, lane, purpose, candidates):
    return dict(id='E1', title=title, lane=lane, purpose=purpose, importance='major',
        reason='核对实际进展及已公布的具体条件', candidate_ids=candidates, read_ids=candidates[:1])


class AcquisitionRecovery(unittest.IsolatedAsyncioTestCase):
    def setup_pipeline(self, entry, candidates, *, saved=None, failures=None, search_rows=()):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        workspace = type('Workspace', (), {'now': NOW, 'public_fetch_attempts': 0,
                                           'web_search_attempts': 0})()
        state = make_state()
        state.update(news_focus=new_window(NOW), cutoff=NOW.isoformat(), candidates=candidates,
                     agenda=dict(events=[entry]), sources=saved or {},
                     read_receipts=[dict(event_id='E1', candidate_id=cid, status='failed',
                                         reason=reason, public_http_requests=1)
                                    for cid, reason in (failures or {}).items()])
        order = []

        def search(ws, query, **options):
            order.append('search')
            ws.web_search_attempts += 1
            return dict(status='ok', results=list(search_rows))

        pipeline = EditionPipeline(state, Path(temporary.name), workspace, check=AsyncMock(), search=search)

        async def read(jobs, events):
            cid = jobs[0]['candidate_id']
            order.append(cid)
            row = state['candidates'][cid]
            state['sources'][cid] = dict(candidate_id=cid, title=row['title'], url=row['url'],
                text='发布者已公布实际结果，以及适用条件和生效日期。', event_ids=[jobs[0]['event_id']])
            workspace.public_fetch_attempts += 1

        pipeline.reads = AsyncMock(side_effect=read)
        return pipeline, state, order

    async def test_preassessment_search_recovers_oversized_report_using_independent_source(self):
        entry = event('贸易理事会实际进展', 'global_policy', 'discovery', ['S1', 'S2'])
        candidates = {'S1': lead('贸易理事会实况', 'first.example'),
                      'S2': lead('贸易理事会投资信号综述', 'preview.example')}
        saved = {'old': dict(candidate_id='S2', title=candidates['S2']['title'], url=candidates['S2']['url'],
                            text='该文讨论会前市场预期。', event_ids=['E1'])}
        replacement = lead('贸易理事会发布实际进展', 'agency.example')
        pipeline, state, order = self.setup_pipeline(entry, candidates, saved=saved,
            failures={'S1': 'web_source_response_too_large'}, search_rows=[replacement])
        original_reads = pipeline.selected_reads

        async def selected(jobs, events, trace):
            if trace[0]['phase'] != 'representative':
                await original_reads(jobs, events, trace)

        async def call(stage, *_):
            order.append(stage)
            self.assertEqual(state['acquisition_recovery'][0]['source_ids'], ['S3'])
            return {}

        pipeline.selected_reads = selected
        pipeline.call = call
        pipeline.validate_assessment = lambda *args: ({}, [])
        pipeline.finish_materials = AsyncMock()
        await pipeline.read_agenda()
        self.assertEqual(order, ['search', 'S3', 'assessment'])
        self.assertEqual(state['agenda']['events'][0]['candidate_ids'], ['S1', 'S2', 'S3'])
        self.assertEqual([r['kind'] for r in state['reservations']], ['search'])

    async def test_denied_site_uses_existing_different_publisher_without_search(self):
        entry = event('港股收盘科技指数下跌', 'hk_market', 'latest_close', ['S1', 'S2'])
        candidates = {'S1': lead('港股收盘科技指数下跌', 'denied.example'),
                      'S2': lead('港股收盘科技指数下跌', 'www.denied.example'),
                      'S3': lead('港股收盘科技指数下跌', 'exchange.example')}
        candidates['S3']['search_links'].append(dict(lane='hk_market'))
        pipeline, state, order = self.setup_pipeline(entry, candidates,
            failures={'S1': 'public_http_403'})
        await recover(pipeline, {'E1': entry})
        await recover(pipeline, {'E1': entry})
        self.assertEqual(order, ['S3'])
        self.assertEqual(state['acquisition_recovery'][0]['source_ids'], ['S3'])
        self.assertFalse(state['reservations'])

    async def test_search_budget_keeps_gap_without_buying_a_request(self):
        entry = event('电池生产设备投产进展', 'industry', 'discovery', ['S1'])
        pipeline, state, order = self.setup_pipeline(entry,
            {'S1': lead(entry['title'], 'initial.example')},
            failures={'S1': 'web_source_article_text_too_short'})
        state['policy']['max_search_requests'] = 0
        await recover(pipeline, {'E1': entry})
        self.assertFalse(order)
        self.assertEqual(state['acquisition_recovery'][0]['status'], 'evidence_gap')
        self.assertEqual(state['acquisition_recovery'][0]['stop_reason'], 'edition_search_budget_exhausted')
        self.assertFalse(state['reservations'])

    async def test_empty_search_does_not_promote_an_unread_snippet(self):
        entry = event('利率决议正式发布', 'global_policy', 'released_policy', ['S1'])
        pipeline, state, order = self.setup_pipeline(entry,
            {'S1': lead(entry['title'], 'initial.example')},
            failures={'S1': 'web_source_time_missing'},
            search_rows=[lead('利率决议发布前瞻', 'preview.example')])
        await recover(pipeline, {'E1': entry})
        self.assertEqual(order, ['search'])
        self.assertEqual(state['acquisition_recovery'][0]['status'], 'evidence_gap')
        self.assertFalse(state['sources'])


class VisibleArticleRecovery(unittest.TestCase):
    def test_comments_article_outside_main_does_not_replace_headline_and_body(self):
        title = '某市场成交结构发生变化'
        text = '主要板块成交量上升，成交最活跃的标的与前一交易日明显不同。' * 10
        html = (f'<title>{title}</title><main><h1>{title}</h1>'
                '<meta property="article:published_time" content="2026-11-18T07:32:00+08:00">'
                f'<p>{text}</p></main><article><p>全部评论，暂无评论。</p></article>')
        extraction = dict(status='text_candidate', method='trafilatura', version='2.3.1',
                          text=text, warnings=[])
        with patch('app.services.generic_extraction.extract_main_text', return_value=extraction) as read:
            item = parse_visible_article(html, 'https://news.example/article', now=NOW)
        read.assert_called_once()
        self.assertEqual(item.content, text)

    def test_recovers_from_same_page_when_main_text_matches_visible_teaser(self):
        teaser = '本次公告介绍下一阶段安排以及哪些产品适用。'
        html = ('<h1>公司发布新计划实施细节</h1>'
                '<meta property="article:published_time" content="2026-11-18T07:32:00+08:00">'
                f'<article><p>{teaser}</p></article>')
        raw_text = teaser + '公告列出了措施的详细适用条件以及各阶段时间。' * 10
        extraction = dict(status='text_candidate', method='trafilatura', version='2.3.1',
                          text=raw_text, warnings=[])
        url = 'https://news.example/article'
        with patch('app.services.generic_extraction.extract_main_text', return_value=extraction) as read:
            item = parse_visible_article(html, url, now=NOW)
            self.assertEqual(item.content, raw_text)
            read.assert_called_once_with(html, url)
        extraction['text'] = raw_text[len(teaser):]
        with patch('app.services.generic_extraction.extract_main_text', return_value=extraction):
            with self.assertRaisesRegex(ValueError, 'web_source_article_text_too_short'):
                parse_visible_article(html, url, now=NOW)

    def test_access_challenge_never_enters_local_recovery(self):
        html = '<title>Verify you are human</title><form id="challenge-form">subscribe to continue</form>'
        with patch('app.services.generic_extraction.extract_main_text') as read:
            with self.assertRaisesRegex(ValueError, 'web_source_access_restricted'):
                parse_visible_article(html, 'https://news.example/article', now=NOW)
            read.assert_not_called()
        self.assertEqual(failure_class('public_http_403'), 'access')
        self.assertEqual(failure_class('web_source_response_too_large'), 'response_size')
