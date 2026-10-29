from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from app import programme_acceptance as trial
from app.services.spoken_editing import prepare_script
from spoken_fixtures import reply


@dataclass
class Route:
    provider: str='ofox_anthropic'
    model: str=trial.MODEL
    base_url: str='https://api.ofox.io'
    effort: str='high'


class ProgrammeTrialTests(unittest.TestCase):
    def fixture(self,root):
        backend=Path(root)/'backend'
        (backend/'data/diagnostics/staged-report').mkdir(parents=True)
        (backend/'data/.automation-paused').touch()
        (backend/'app/services').mkdir(parents=True)
        for name in ('editorial_policy.py','spoken_programme.py','spoken_editing.py','podcast_generator.py'):
            (backend/'app/services'/name).write_text('fixture',encoding='utf-8')
        original=backend/'data/diagnostics/staged-report'/(trial.ORIGIN_SHA+'.report.json')
        original.write_text(json.dumps(dict(status='completed_for_human_review',input_sha256=trial.ORIGIN_SHA)))
        report=Path(root)/'report.md';report.write_text('事实已经发生，未来仍有条件。',encoding='utf-8')
        return backend,report

    def packet(self,backend,report):
        with patch.object(trial,'REPORT_SHA',trial.digest(report.read_bytes())):
            return trial.prepare(backend,report)

    def gateway(self,raw):
        gateway=Mock()
        gateway.resolve_route.return_value=Route()
        gateway.request_for.return_value=('https://api.ofox.io/v1/messages',{'secret':'never printed'},dict())
        gateway.completed_text.return_value=raw
        payload=dict(stop_reason='end_turn',content=[dict(type='text',text=raw)])
        response=Mock(status_code=200,is_error=False);response.json.return_value=payload
        factory=Mock();factory.return_value.__enter__=Mock(return_value=Mock(post=Mock(return_value=response)))
        factory.return_value.__exit__=Mock(return_value=False)
        return gateway,factory

    def test_free_preparation_has_no_marker_or_http_and_uses_production_contract(self):
        with tempfile.TemporaryDirectory() as root:
            backend,report=self.fixture(root);packet=self.packet(backend,report)
            self.assertIn('programme',packet['messages'][0]['content'])
            self.assertEqual(trial.preview(packet)['http_requests_performed'],0)
            self.assertFalse((backend/'data/diagnostics/staged-programme').exists())

    def test_pause_and_report_origin_are_required_before_spending(self):
        with tempfile.TemporaryDirectory() as root:
            backend,report=self.fixture(root)
            (backend/'data/.automation-paused').unlink()
            with self.assertRaises(RuntimeError):self.packet(backend,report)
            (backend/'data/.automation-paused').touch()
            with self.assertRaisesRegex(RuntimeError,'指纹'):trial.prepare(backend,report)
            origin=next((backend/'data/diagnostics/staged-report').glob('*.json'));origin.write_text('{}')
            with self.assertRaisesRegex(RuntimeError,'付费完成'):self.packet(backend,report)

    def test_mismatched_preview_and_changed_source_do_not_call_http(self):
        with tempfile.TemporaryDirectory() as root:
            backend,report=self.fixture(root);packet=self.packet(backend,report);gateway,factory=self.gateway('raw')
            with self.assertRaises(RuntimeError):trial.execute(backend,packet,'wrong',gateway,factory,Mock())
            (backend/'app/services/spoken_programme.py').write_text('changed')
            with self.assertRaises(RuntimeError):trial.execute(backend,packet,packet['input_sha256'],gateway,factory,Mock())
            factory.assert_not_called()

    def test_one_call_preserves_plan_script_and_stable_marker_prevents_recharge(self):
        with tempfile.TemporaryDirectory() as root:
            backend,report=self.fixture(root);packet=self.packet(backend,report)
            raw=reply('已有变化，但若条件不满足则暂缓。',report.read_text(encoding='utf-8'))
            gateway,factory=self.gateway(raw);usage=Mock(return_value={'input_tokens':123})
            path=trial.execute(backend,packet,packet['input_sha256'],gateway,factory,usage)
            value=json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(value['status'],'completed_for_human_review')
            self.assertEqual(value['raw_response'],raw)
            self.assertTrue(value['editorial_plan']['choices'])
            self.assertEqual(value['script'],prepare_script('已有变化，但若条件不满足则暂缓。'))
            self.assertEqual(value['http_requests'],1)
            factory.return_value.__enter__.return_value.post.assert_called_once()
            route=gateway.request_for.call_args.args[0];self.assertEqual(route.effort,'none')
            changed=json.loads(json.dumps(packet))
            changed['messages'][1]['content']+=' changed prompt'
            changed['input_sha256']=trial.digest(json.dumps(changed['messages'],ensure_ascii=False,separators=(',',':')).encode())
            self.assertEqual(trial.execute(backend,changed,changed['input_sha256'],gateway,factory,usage),path)
            factory.assert_called_once()

    def test_bad_format_saved_and_never_automatically_repaired(self):
        with tempfile.TemporaryDirectory() as root:
            backend,report=self.fixture(root);packet=self.packet(backend,report)
            gateway,factory=self.gateway('paid plain text without a programme')
            path=trial.execute(backend,packet,packet['input_sha256'],gateway,factory,Mock(return_value={}))
            value=json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(value['status'],'failed_no_retry')
            self.assertIn('paid plain text',value['raw_response'])
            factory.return_value.__enter__.return_value.post.assert_called_once()

    def test_timeout_keeps_marker_without_retry(self):
        with tempfile.TemporaryDirectory() as root:
            backend,report=self.fixture(root);packet=self.packet(backend,report)
            gateway,factory=self.gateway('unused')
            factory.return_value.__enter__.return_value.post.side_effect=TimeoutError('timeout')
            path=trial.execute(backend,packet,packet['input_sha256'],gateway,factory,Mock(return_value={}))
            self.assertEqual(json.loads(path.read_text())['status'],'failed_no_retry')
            trial.execute(backend,packet,packet['input_sha256'],gateway,factory,Mock())
            factory.assert_called_once()

    def test_other_route_refused_before_marker_or_request(self):
        with tempfile.TemporaryDirectory() as root:
            backend,report=self.fixture(root);packet=self.packet(backend,report)
            gateway,factory=self.gateway('unused');gateway.resolve_route.return_value=Route(model='other')
            with self.assertRaisesRegex(RuntimeError,'路由'):trial.execute(backend,packet,packet['input_sha256'],gateway,factory,Mock())
            self.assertFalse(list((backend/'data/diagnostics/staged-programme').glob('*.started')))
            factory.assert_not_called()

    def test_modified_input_after_preview_is_not_sent(self):
        with tempfile.TemporaryDirectory() as root:
            backend,report=self.fixture(root);packet=self.packet(backend,report)
            gateway,factory=self.gateway('unused')
            packet['messages'][1]['content']+=' changed'
            with self.assertRaisesRegex(RuntimeError,'输入已变化'):
                trial.execute(backend,packet,packet['input_sha256'],gateway,factory,Mock())
            factory.assert_not_called()
