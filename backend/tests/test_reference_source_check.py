import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from app.reference_source_check import inspect_one,ENDPOINTS


class ReferenceSourceCheckTests(unittest.TestCase):
    def test_failure_is_saved_and_never_automatically_retried(self):
        with tempfile.TemporaryDirectory() as temp,patch('app.reference_source_check.get',side_effect=TimeoutError) as call:
            root=Path(temp)
            first=inspect_one('google_news',root)
            self.assertEqual(first['status'],'failed_this_environment_no_retest')
            self.assertEqual(first,inspect_one('google_news',root))
            self.assertEqual(call.call_count,1)

    def test_interrupted_marker_does_not_trigger_network(self):
        with tempfile.TemporaryDirectory() as temp,patch('app.reference_source_check.get') as call:
            root=Path(temp);(root/'techcrunch.started').write_text('started')
            self.assertEqual(inspect_one('techcrunch',root)['status'],'interrupted_or_running_no_retest')
            call.assert_not_called()

    def test_wire_cannot_be_counted_as_article_fulltext(self):
        response=SimpleNamespace(status_code=200,json=lambda:dict(data=[dict(time='2026-10-31T00:00:00Z',data=dict(content='reported event'))]))
        with tempfile.TemporaryDirectory() as temp,patch('app.reference_source_check.get',return_value=response):
            row=inspect_one('mktnews',Path(temp))
            self.assertEqual(row['status'],'wire_only_not_article_body')
            self.assertEqual(row['bodies'],[])

    def test_legacy_failed_sources_are_not_endpoints(self):
        self.assertFalse({'rest_of_world','bbc','guardian','reuters','bloomberg','wsj'} & set(ENDPOINTS))
