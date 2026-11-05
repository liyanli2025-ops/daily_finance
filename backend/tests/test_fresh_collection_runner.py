"""Free/new episode identity and immutable historical accounting."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

PATH=Path(__file__).resolve().parents[2]/'tools/run_fresh_collection.py'
SPEC=importlib.util.spec_from_file_location('fresh_collection_test_runner',PATH)
runner=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(runner)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def fixture():
    resume=dict(source_cutoff='2026-11-01T13:56:44')
    value=dict(environment=dict(resume=resume))
    result=dict(owner='finance-progress-collection-acceptance-v1',status='stalled_no_new_evidence',
        cutoff=resume['source_cutoff'],finished_at='2026-11-05T07:33:43',pause_preserved=True,
        input_sha256=fingerprint(value),started_at='2026-11-05T07:30:28',resume=resume,
        model_http_attempts=17,public_fetch_attempts=17,
        combined_usage=dict(model_http_attempts=19,model_input_characters=1368376,
            reserved_output_tokens=62700,search_http_attempts=12))
    marker=dict(owner=result['owner'],input_sha256=result['input_sha256'],started_at=result['started_at'])
    return result,value,marker


class FreshIdentityTests(unittest.TestCase):
    def test_new_locations_do_not_reuse_old_trial_or_resume_markers(self):
        paths=runner.locations(Path('/example/backend'))
        self.assertIn('fresh-collection-v28',str(paths[0]))
        self.assertNotIn('progress-collection-v1',str(paths[3]))

    def test_finished_history_is_checked_without_changing_usage(self):
        args=fixture();before=deepcopy(args)
        runner.verify_history(*args,fingerprint)
        self.assertEqual(args,before)

    def test_changed_history_marker_is_rejected(self):
        args=fixture();args[2]['input_sha256']='changed'
        with self.assertRaises(ValueError):runner.verify_history(*args,fingerprint)

    def test_changed_private_input_is_rejected(self):
        args=fixture();args[1]['extra']='changed'
        with self.assertRaises(ValueError):runner.verify_history(*args,fingerprint)

    def test_ongoing_history_is_not_used_as_new_trial_proof(self):
        args=fixture();args[0]['finished_at']=None
        with self.assertRaises(ValueError):runner.verify_history(*args,fingerprint)

    def test_historical_usage_is_not_reset_to_the_last_segment(self):
        args=fixture();args[0]['combined_usage']['model_http_attempts']=9
        with self.assertRaises(ValueError):runner.verify_history(*args,fingerprint)

    def test_history_proof_keeps_usage_separate_from_new_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            backend=Path(directory)/'backend'
            root=backend/'data/diagnostics/progress-collection-v1/continue-recovered-materials';root.mkdir(parents=True)
            args=fixture()
            for name,value in zip(('result.json','input.json','started.json'),args):
                (root/name).write_text(json.dumps(value))
            sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
            prior=SimpleNamespace(sha=sha,evidence=Mock(return_value=dict(frozen={},policy={'old_remaining_only':1})))
            base=SimpleNamespace(fingerprint=fingerprint,REVIEWED_RUNTIME={'app/services/'+key:'reviewed-new'
                for key in runner.PROBED_SOURCE})
            with patch.object(runner,'HISTORY_SHA',sha(root/'result.json')):
                proof=runner.proof_for(backend,base,prior)
            self.assertEqual(proof['fresh_public']['historical_usage']['model_http_attempts'],19)
            self.assertEqual(proof['fresh_public']['mode'],'fresh_dated_episode_not_historical_resume')
            self.assertNotIn('resume',proof['fresh_public'])
            self.assertFalse(proof['fresh_public']['production_search_route_resumed'])
