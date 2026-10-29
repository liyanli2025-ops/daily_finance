import importlib.util
import json
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

SPEC = importlib.util.spec_from_file_location('prepare_report_acceptance', Path(__file__).resolve().parents[2]/'tools/prepare_report_acceptance.py')
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def fixture():
    snapshot = dict(full_collection=True, collected_at='2026-10-29T07:32:00', selection=dict(articles=[dict(id='fact')]),
        raw_articles=[dict(id='fact', title='经营变化', content='经营数据增长3%，影响仍待验证。', source='公开原文', url='https://example.com/fact', published='2026-10-29T07:00:00')])
    replay = dict(snapshot_sha256='fixture', selection=dict(articles=[dict(id='fact', selected=True)]), news_input='已保存正文片段及[N:fact]')
    return snapshot, replay


class FrozenInputTests(unittest.TestCase):
    def test_actual_editorial_prompt_without_model_or_collection(self):
        snapshot, replay = fixture()
        with patch('httpx.Client.post', side_effect=AssertionError('no HTTP')), patch('requests.get', side_effect=AssertionError('no collection')):
            packet = module.assemble(snapshot, replay, 'fixture', [], '固定历史行情')
        from app.services.editorial_policy import REPORT_POLICY
        self.assertIn(REPORT_POLICY, packet['messages'][0]['content'])
        self.assertIn('固定历史行情', packet['messages'][0]['content'])
        self.assertIn('已保存正文片段', packet['messages'][0]['content'])
        self.assertEqual(packet['max_http_requests'], 1)
        self.assertEqual(packet['retries'], 0)
        self.assertTrue(packet['within_input_guard'])

    def test_mismatched_snapshot_or_duplicate_selection_rejected(self):
        snapshot, replay = fixture()
        with self.assertRaises(RuntimeError):
            module.assemble(snapshot, replay, 'other', [], 'market')
        replay['selection']['articles'] *= 2
        with self.assertRaises(RuntimeError):
            module.assemble(snapshot, replay, 'fixture', [], 'market')

    def test_future_article_rejected(self):
        snapshot, replay = fixture()
        snapshot['raw_articles'][0]['published'] = '2026-10-29T09:00:00'
        with self.assertRaises(RuntimeError):
            module.assemble(snapshot, replay, 'fixture', [], 'market')

    def test_large_input_reports_guard_without_silent_dropping(self):
        snapshot, replay = fixture()
        replay['news_input'] = '正文'*60000
        packet = module.assemble(snapshot, replay, 'fixture', [], 'market')
        self.assertFalse(packet['within_input_guard'])
        self.assertIn(replay['news_input'], packet['messages'][0]['content'])


class PreparationTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeat_preparation_preserves_pause_and_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            radar = root/'data/radar'
            radar.mkdir(parents=True)
            flag = root/'data/.automation-paused'
            flag.write_text('keep', encoding='utf-8')
            snapshot, replay = fixture()
            raw = json.dumps(snapshot).encode()
            replay['snapshot_sha256'] = hashlib.sha256(raw).hexdigest()
            (radar/'news-acceptance.json').write_bytes(raw)
            (radar/'selection-replay.json').write_text(json.dumps(replay), encoding='utf-8')
            (radar/'technical.json').write_text(json.dumps(dict(collected_at='2026-10-29T07:31:00', watchlist=[])), encoding='utf-8')
            with patch('app.services.watchlist_repository.refresh_app_watchlist', AsyncMock(return_value=SimpleNamespace(get_all_stocks=lambda: []))), patch('app.services.technical_radar.prompt', return_value='固定市场证据'), patch('httpx.Client.post', side_effect=AssertionError('no HTTP')):
                first, path = await module.prepare(root)
                again, same = await module.prepare(root)
            self.assertEqual(first, again)
            self.assertEqual(path, same)
            self.assertEqual(len(list(path.parent.iterdir())), 1)
            self.assertEqual(flag.read_text(encoding='utf-8'), 'keep')
            self.assertEqual((radar/'news-acceptance.json').read_bytes(), raw)
