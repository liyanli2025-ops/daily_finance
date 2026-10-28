import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import httpx
from app.services.model_gateway import Route,request_for,completed_text,service_error

spec=importlib.util.spec_from_file_location('market_model_probe',Path(__file__).resolve().parents[2]/'tools/run_market_model_probe_once.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)


class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'data').mkdir()
        self.flag=self.root/'data/.automation-paused';self.flag.write_bytes(b'keep paused')
        self.route=Route('ofox_anthropic',probe.MODEL,'https://api.ofox.io/anthropic/v1','test-key','high')
        self.gateway=SimpleNamespace(resolve_route=Mock(return_value=self.route),request_for=request_for,
            completed_text=completed_text,service_error=service_error)
        self.client=Mock();self.client.__enter__=Mock(return_value=self.client);self.client.__exit__=Mock(return_value=False)
        self.factory=Mock(return_value=self.client);self.record=Mock(return_value=dict(input_tokens=100,output_tokens=100))

    def response(self,status=200,stop='end_turn'):
        return httpx.Response(status,json=dict(stop_reason=stop,content=[dict(type='thinking',thinking='private'),
            dict(type='text',text='模型可见回复')],usage=dict(input_tokens=100,output_tokens=100)))

    def run_probe(self):return probe.execute(self.root,self.gateway,self.factory,self.record)

    def test_preview_is_small_and_frozen_to_authorized_input(self):
        # This is a frozen authorized request, not a template to silently
        # regenerate after policy edits (which could defeat duplicate billing protection).
        digest=hashlib.sha256(json.dumps(probe.messages(),ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        self.assertEqual(digest,'736c85cad99a677f194cd9e874b1b4b096c36c214d5775a6d7eec88d680707fa')
        self.assertLess(probe.preview()['input_characters'],5000)
        self.assertEqual(probe.preview()['max_http_requests'],1)
        self.assertEqual(probe.preview()['max_output_tokens'],1200)
        self.gateway.resolve_route.assert_not_called()

    def test_success_one_post_preserves_pause_and_duplicate_never_posts(self):
        self.client.post.return_value=self.response()
        path=self.run_probe();data=json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(data['status'],'completed_for_human_review')
        self.assertEqual(self.flag.read_bytes(),b'keep paused')
        self.assertEqual(data['response'],'模型可见回复');self.assertNotIn('private',path.read_text(encoding='utf-8'))
        self.assertEqual(self.run_probe(),path);self.client.post.assert_called_once()
        self.assertEqual(self.client.post.call_args.kwargs['json']['max_tokens'],1200)
        self.assertEqual(self.route.effort,'high')

    def test_transport_error_retains_marker_no_retry_or_new_request(self):
        self.client.post.side_effect=httpx.ConnectError('network')
        path=self.run_probe();self.assertEqual(json.loads(path.read_text())['status'],'failed_no_retry')
        self.run_probe();self.client.post.assert_called_once();self.record.assert_called_once()

    def test_truncation_preserves_text_but_not_approved(self):
        self.client.post.return_value=self.response(stop='max_tokens')
        path=self.run_probe();data=json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(data['status'],'failed_no_retry');self.assertEqual(data['response'],'模型可见回复')
        self.client.post.assert_called_once();self.record.assert_called_once()

    def test_402_has_no_fallback_or_retry(self):
        self.client.post.return_value=self.response(status=402)
        path=self.run_probe();self.assertEqual(json.loads(path.read_text())['http_status'],402)
        self.client.post.assert_called_once();self.record.assert_called_once()

    def test_no_pause_or_unapproved_route_cannot_post(self):
        self.flag.unlink()
        with self.assertRaises(RuntimeError):self.run_probe()
        self.factory.assert_not_called()
        self.flag.write_bytes(b'keep paused')
        self.gateway.resolve_route.return_value=Route('compatible','different','https://example.com','test-key','none')
        with self.assertRaises(RuntimeError):self.run_probe()
        self.factory.assert_not_called()

    def test_reviewed_input_is_identical_to_frozen_document(self):
        document=Path(__file__).resolve().parents[2]/'docs/market_model_probe_input_20261028.md'
        self.assertEqual(probe.messages()[1]['content'],document.read_text(encoding='utf-8'))

    def test_changed_wire_request_does_not_enable_second_charge(self):
        self.client.post.return_value=self.response()
        first=self.run_probe()
        def changed_request(*args):
            url,headers,body=request_for(*args)
            return url,headers,dict(body,temperature=.1)
        self.gateway.request_for=changed_request
        self.assertEqual(first,self.run_probe())
        self.client.post.assert_called_once()

    def test_no_tools_stream_or_production_reasoning_changes(self):
        self.client.post.return_value=self.response()
        self.run_probe();body=self.client.post.call_args.kwargs['json']
        self.assertNotIn('tools',body);self.assertNotIn('stream',body)
        self.assertNotIn('cache_control',body)
        self.assertEqual(body['output_config']['effort'],'low')
        self.assertEqual(self.route.effort,'high')
