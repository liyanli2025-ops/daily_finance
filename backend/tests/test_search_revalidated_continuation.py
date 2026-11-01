"""Offline accounting and evidence binding; no provider or DB calls."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

PATH = Path(__file__).resolve().parents[2] / 'tools/continue_progress_collection.py'
SPEC = importlib.util.spec_from_file_location('search_revalidated_continuation', PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':')).encode()).hexdigest()


def fixture():
    config = SimpleNamespace(research_total_input_characters=2000000,
        research_total_output_tokens=120000, research_web_search_max_requests=24,
        research_body_max_urls=64, research_local_read_max_characters=96000,
        research_max_seconds=900, research_max_model_calls=None)
    owner = 'finance-progress-collection-acceptance-v1'
    old_input = dict(owner=owner, task='original')
    original = dict(owner=owner, status='failed_no_retry', error_type='JSONDecodeError',
        input_sha256=fingerprint(old_input), started_at='2026-11-01T12:42:57',
        finished_at='2026-11-01T12:43:11', model_http_attempts=2,
        model_input_characters=35266, reserved_output_tokens=6600,
        search_http_attempts=1, public_fetch_attempts=0,
        research=dict(candidates={}, provided_ids=[], body_url_calls=0, local_read_characters=0,
            receipts=[dict(request=dict(tool='search', query='收盘 2026'), result=dict(reason='http_400'))]),
        budget_plan=dict(total_input_characters=2000000, total_reserved_output_tokens=120000,
            model_request_cap=None, initial=dict(output_tokens=3300),
            ceiling=dict(search_calls=24, body_urls=64, local_read_characters=96000, seconds=900)))
    marker = dict(owner=owner, input_sha256=original['input_sha256'])
    probe_owner = 'finance-search-contract-diagnostic-v1'
    payload = dict(query='收盘 2026', start_date='2026-10-29', end_date='2026-11-02')
    probe_input = dict(owner=probe_owner, credential_fingerprint='account-a', revised_request_parameters=payload)
    probe_marker = dict(owner=probe_owner, input_sha256=fingerprint(probe_input), started_at='2026-11-01T13:11:51')
    probe = dict(owner=probe_owner, status='search_http_accepted_pending_review',
        diagnostics=dict(http_status=200, request_parameters=payload), search_http_attempts=1,
        model_requests=0, public_fetch_attempts=0, tts_requests=0,
        pause_preserved=True, finished_at='2026-11-01T13:11:55')
    return config, original, old_input, marker, probe, probe_input, probe_marker


class ContinuationTests(unittest.TestCase):
    def test_prior_model_and_both_search_attempts_are_subtracted(self):
        config, old, _, _, probe, _, marker = fixture()
        policy, spent = module.remaining_policy(config, old, probe, marker)
        self.assertEqual(policy['research_total_input_characters'], 1964734)
        self.assertEqual(policy['research_total_output_tokens'], 113400)
        self.assertEqual(policy['research_web_search_max_requests'], 22)
        self.assertEqual(policy['research_max_seconds'], 882)
        self.assertIsNone(policy['research_max_model_calls'])
        self.assertEqual(spent['model_requests'], 2)

    def test_emergency_call_cap_also_subtracts_prior_calls(self):
        config, old, _, _, probe, _, marker = fixture()
        config.research_max_model_calls = 3
        policy, _ = module.remaining_policy(config, old, probe, marker)
        self.assertEqual(policy['research_max_model_calls'], 1)

    def test_depleted_output_envelope_is_not_reset(self):
        config, old, _, _, probe, _, marker = fixture()
        config.research_total_output_tokens = 7000
        with self.assertRaises(ValueError):
            module.remaining_policy(config, old, probe, marker)

    def test_success_requires_same_input_marker_account_and_http_status(self):
        _, old, old_input, old_marker, probe, probe_input, probe_marker = fixture()
        module.verify_receipts(old, old_input, old_marker, probe, probe_input, probe_marker,
                               fingerprint, 'account-a')
        with self.assertRaises(ValueError):
            module.verify_receipts(old, old_input, old_marker, probe, probe_input, probe_marker,
                                   fingerprint, 'account-b')
        failed = deepcopy(probe)
        failed['diagnostics']['http_status'] = 400
        with self.assertRaises(ValueError):
            module.verify_receipts(old, old_input, old_marker, failed, probe_input, probe_marker,
                                   fingerprint, 'account-a')

    def test_tampered_original_input_is_rejected(self):
        _, old, old_input, old_marker, probe, probe_input, probe_marker = fixture()
        old_input['task'] = 'changed'
        with self.assertRaises(ValueError):
            module.verify_receipts(old, old_input, old_marker, probe, probe_input, probe_marker,
                                   fingerprint, 'account-a')

    def test_changed_failure_ledger_revokes_scoped_permission(self):
        with tempfile.TemporaryDirectory() as directory:
            from app.services.source_health import state_path
            key = 'research-web-search:tavily:v1:test'
            path = state_path(directory, key)
            path.parent.mkdir()
            path.write_text('old failure')
            proof = dict(route_key=key, blocked_path=path, frozen={str(path): module.sha(path)})
            original = Mock()
            allowed = module.permit_reviewed_route(original, proof)
            allowed(directory, key)
            original.assert_not_called()
            path.write_text('new failure')
            with self.assertRaises(ValueError):
                allowed(directory, key)

    def test_other_routes_still_use_original_failure_guard(self):
        original = Mock(side_effect=ValueError('still paused'))
        proof = dict(route_key='reviewed-key')
        with self.assertRaises(ValueError):
            module.permit_reviewed_route(original, proof)('unused-root', 'other-route')
        original.assert_called_once_with('unused-root', 'other-route')


if __name__ == '__main__':
    unittest.main()
