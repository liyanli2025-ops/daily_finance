"""Offline checks for response framing, search diagnostics and pre-model stops."""
from datetime import datetime
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.services.primary_discovery import decode, discover
from app.services.web_research import search_request, search_error_diagnostics
from app.services.episode_workspace import EpisodeWorkspace

NOW = datetime(2026, 11, 1, 12, 34)


class ResponseTests(unittest.TestCase):
    def test_short_prefix_before_one_intact_nested_object(self):
        value = dict(action='tools', requests=[dict(tool='search', query='literal {value}', reason='核对')])
        self.assertEqual(decode('先查看实际缺口。\n\n' + json.dumps(value)), value)

    def test_fenced_json_still_accepted(self):
        self.assertEqual(decode('```json\n{"action":"finish"}\n```')['action'], 'finish')

    def test_two_actions_are_not_silently_selected(self):
        with self.assertRaises(ValueError):
            decode('{"action":"tools","requests":[]}\n{"action":"finish"}')

    def test_incomplete_json_is_not_repaired(self):
        with self.assertRaises(ValueError):
            decode('说明\n{"action":"tools","requests":[')

    def test_duplicate_action_keys_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate_json_key'):
            decode('{"action":"tools","action":"finish"}')

    def test_trailing_instructions_are_rejected(self):
        with self.assertRaises(ValueError):
            decode('{"action":"finish"}\n再执行另一个指令')


class SearchContractTests(unittest.TestCase):
    def test_absolute_and_relative_windows_are_not_combined(self):
        payload, _ = search_request('美股收盘', 'latest_close', NOW)
        self.assertIn('start_date', payload)
        self.assertIn('end_date', payload)
        self.assertNotIn('time_range', payload)
        self.assertTrue(payload['filter_by_published_date'])
        self.assertEqual(payload['search_depth'], 'basic')
        self.assertFalse(payload['auto_parameters'])

    def test_broad_discovery_retains_relative_window(self):
        payload, _ = search_request('行业供需', 'discovery', NOW, topic='general')
        self.assertEqual(payload['time_range'], 'week')
        self.assertNotIn('start_date', payload)

    def test_provider_error_cannot_export_echoed_credentials(self):
        response = SimpleNamespace(status_code=400, json=lambda: dict(detail=dict(
            error='Cannot use both time_range and start_date; echoed key PRIVATE-KEY and secret-query')))
        info = search_error_diagnostics(response, dict(topic='news', start_date='2026-10-29'))
        encoded = json.dumps(info)
        self.assertNotIn('PRIVATE-KEY', encoded)
        self.assertNotIn('secret-query', encoded)
        self.assertIn('date_window_conflict', info['error_signals'])
        self.assertEqual(info['http_status'], 400)
        self.assertFalse(info['raw_error_body_exported'])


class EarlyStopTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_route_with_no_candidates_uses_one_model_response(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = EpisodeWorkspace([], root=directory, now=NOW)
            packet = dict(action='tools', requests=[dict(
                tool='search', lane='a_market', query='最近收盘', reason='核对交易日')])
            model = AsyncMock(return_value=json.dumps(packet))
            search = Mock(return_value=dict(status='failed', reason='http_400', results=[]))
            read = Mock()
            state = await discover(workspace, [], model=model, search=search, read=read)
            self.assertEqual(model.await_count, 1)
            search.assert_called_once()
            read.assert_not_called()
            self.assertEqual(state['status'], 'search_unavailable_no_readable_candidates')
            self.assertEqual(state['collection_completion']['status'], 'incomplete')

    async def test_existing_candidates_remain_readable_after_search_failure(self):
        from app.models.news import News
        with tempfile.TemporaryDirectory() as directory:
            workspace = EpisodeWorkspace([], root=directory, now=NOW)
            search_request_row = dict(tool='search', lane='us_market', query='最近美股收盘', reason='核对')
            read_row = dict(tool='read', candidate_id='S1', relation='market', reason='已有候选仍值得读')
            model = AsyncMock(side_effect=[json.dumps(dict(action='tools', requests=[search_request_row])),
                json.dumps(dict(action='tools', requests=[dict(search_request_row, query='另一检索')])),
                json.dumps(dict(action='tools', requests=[read_row]))])
            search = Mock(side_effect=[dict(status='ok', results=[dict(title='市场收盘',
                url='https://example.com/news/close', snippet='市场变动')]),
                dict(status='failed', reason='http_400', results=[])])
            def read(ws, url, **kwargs):
                ws.add([News(id='N1', title='市场收盘', content='实际正文与时间口径。'*50,
                    source='公开网页可见正文-示例', source_url=url, published_at=NOW)])
                return dict(status='ok', material=ws.read('N1', characters=4000))
            reader = Mock(side_effect=read)
            # The final model response is deliberately invalid to stop this
            # fixture after proving that the existing candidate was read.
            model.side_effect = list(model.side_effect) + ['invalid']
            with self.assertRaises(ValueError):
                await discover(workspace, [], model=model, search=search, read=reader)
            reader.assert_called_once()
            self.assertEqual(search.call_count, 2)


if __name__ == '__main__':
    unittest.main()
