"""No-network regressions for the two published DOM layouts and the edition path."""
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app.services.edition_pipeline import EditionPipeline
from app.services.edition_read_selection import fallback_plan
from app.services.episode_workspace import EpisodeWorkspace
from app.services.publisher_releases import PUBLISHERS, catalogue
from app.services.web_research import parse_visible_article
from test_unified_edition import state as edition_state


CUTOFF = datetime(2026, 11, 18, 11)
MFA_PATH = '202611/t20261116_12059654.shtml'
MFA_URL = PUBLISHERS['mfa']['directory'] + MFA_PATH
MFA_TITLE = '三国代表将于深圳举行会晤'
MFA_DIRECTORY = f'<ul><li><a href="./{MFA_PATH}">{MFA_TITLE}（2026-11-16）</a></li></ul>'
MOFCOM_PATH = '/xwfb/rcxwfb/art/2026/art_c564995ff6054093a1ed039e10c89aad.html'
MOFCOM_TITLE = '贸易理事会就商品清单举行首次会议'
MOFCOM_TEXT = '双方就产品清单交换意见。本次通报仅公布会议进展，相关措施的具体实施日期仍待单独公布。'


class PublisherReleasesTests(unittest.IsolatedAsyncioTestCase):
    def test_catalogue_keeps_date_and_url_but_cannot_supply_body(self):
        publisher = PUBLISHERS['mfa']
        future = MFA_DIRECTORY.replace('12059654', '12059655').replace('2026-11-16', '2026-11-19')
        mirror = MFA_DIRECTORY.replace('./202611/', 'https://other.example/202611/')
        rows = catalogue(MFA_DIRECTORY + future + mirror, publisher, CUTOFF)
        self.assertEqual([(r['url'], r['title'], r['published_hint'], r['snippet']) for r in rows],
                         [(MFA_URL, MFA_TITLE, '2026-11-16', None)])

    def test_short_timed_notice_from_original_publisher_is_readable(self):
        html = (f'<h1>{MFA_TITLE}</h1><p class="time"><span>2026-11-16 09:00</span></p>'
                '<div id="News_Body_Txt_A"><p>有关部门宣布：</p><p>代表团将于十一月十九日在深圳会面，具体议程和会谈结果以其后发布的公告为准。</p></div>')
        item = parse_visible_article(html, MFA_URL, now=CUTOFF)
        self.assertLess(len(item.content), 80)
        self.assertEqual(item.source, '公开网页可见正文-外交部')
        self.assertIn('精度：day', item.market_impact)
        with self.assertRaisesRegex(ValueError, 'web_source_time_missing'):
            parse_visible_article(html.replace('2026-11-16 09:00', '更新'), MFA_URL, now=CUTOFF)

    def test_trade_directory_ignores_other_sections_and_reads_matching_release(self):
        raw = f'<li><a href="{MOFCOM_PATH}">{MOFCOM_TITLE}</a><span>[2026-11-14]</span></li>'
        rows = catalogue(raw + raw.replace('/rcxwfb/', '/ldrhd/'), PUBLISHERS['mofcom'], CUTOFF)
        self.assertEqual(len(rows), 1)
        html = (f'<div class="art-title">{MOFCOM_TITLE}</div><div class="article-tool"><div class="at-left">'
                '<p>发布部门<span>类别</span><span>2026-11-14 14:33</span></p></div></div>'
                f'<div class="art-con" ergodic="article"><p>{MOFCOM_TEXT}</p><nav>无关导航</nav></div>')
        item = parse_visible_article(html, rows[0]['url'], now=CUTOFF, hours=120)
        self.assertEqual(item.content, MOFCOM_TEXT)
        self.assertIn('2026-11-14 14:33', item.market_impact)

    async def test_catalogue_failure_stays_visible_without_paid_fallback_or_duplicate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = edition_state()
            workspace = EpisodeWorkspace(root=root / 'evidence', now=CUTOFF)
            pipeline = EditionPipeline(state, root, workspace, check=AsyncMock())
            with patch('app.services.web_research.fetch_html_once',
                       side_effect=[(200, {}, MFA_DIRECTORY), ValueError('public_http_403')]) as fetch:
                await pipeline.publisher_catalogues()
                await pipeline.publisher_catalogues()
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(state['public_fetch_attempts'], 2)
            self.assertEqual([r['status'] for r in state['publisher_catalogue_checks']], ['ok', 'unavailable'])
            self.assertFalse(state.get('search_receipts'))
            self.assertTrue(any(r['url'] == MFA_URL for r in state['candidates'].values()))

    def test_result_gap_does_not_fallback_to_background_but_keeps_it_in_directory(self):
        event = dict(id='E6', title='贸易会谈实际结果', reason='核对会谈已经宣布的实际成果和生效边界',
                     lane='global_policy', purpose='discovery')
        rows = {'S43': dict(title='Trade talks live updates', url='https://cnn.com/live'),
                'S28': dict(title='重要会议的投资信号', url='https://news.example/overview', snippet=event['reason']),
                'S70': dict(title='贸易会谈结果公告', url='https://gov.example/statement', original_publisher='发布机构')}
        plan = dict(event_id='E6', candidate_id='S43', increment='representative', reason=event['reason'],
                    allow_fallback=True, fallback_ids=list(rows))
        job, receipt = fallback_plan(dict(candidates=rows, news_focus={'cutoff': CUTOFF.isoformat()}), {'E6': event}, plan)
        self.assertEqual(job['candidate_id'], 'S70')
        self.assertIn('overview_cannot_fill_specific_result_gap', receipt['skipped'][0]['flags'])
        self.assertIn('S28', rows)
