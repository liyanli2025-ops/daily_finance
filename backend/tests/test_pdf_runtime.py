"""No network/models: bounded parser concurrency and failure recovery."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.services import research_documents as documents
from app.services import primary_sources as primary
from app.services.research_hub import ResearchHub
from app.services.watchlist_service import WatchlistStock


class PdfRuntimeTests(unittest.TestCase):
    def test_disclosure_outer_deadline_allows_full_pdf_budget_and_respects_stock_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            hub=ResearchHub(folder)
            stock=WatchlistStock('600900','长江电力','A')
            for remaining in (95,20):
                deadline=time.monotonic()+remaining
                def original(_hub,_stock,outer_deadline):
                    available=outer_deadline-time.monotonic()
                    self.assertLessEqual(outer_deadline,deadline)
                    self.assertGreater(available,60 if remaining==95 else 18)
                    self.assertLessEqual(available,65)
                    return ['original'],{'status':'ok'}
                with patch.object(primary,'cninfo_financial',side_effect=original):
                    items,status=hub.disclosures(stock,deadline)
                self.assertEqual(items,['original'])

    def test_new_attempt_policy_reuses_success_and_ignores_only_old_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            hub=ResearchHub(folder)
            key='cninfo:financial-pdf:serial-v2:12345'
            hub.cache(key,86400,lambda:{'read_pages':196})
            hub.cache('primary:attempt:'+key,600,lambda:dict(ok=False,error='RuntimeError'))
            fetch=Mock(side_effect=AssertionError('successful PDF must not be downloaded again'))
            result=primary.cached(hub,key,86400,fetch,attempt_version='outer-budget-v3')
            self.assertEqual(result['read_pages'],196)
            fetch.assert_not_called()

    def test_exit_signal_diagnostic_is_retained_without_child_stderr(self):
        with patch.object(documents,'pdf_ready',return_value=True), \
                patch.object(documents.requests,'get',return_value=self.response()), \
                patch.object(documents.subprocess,'run',return_value=SimpleNamespace(returncode=-9,stderr='PRIVATE')):
            with self.assertRaisesRegex(RuntimeError,'pdf_parser_exit:-9') as error:
                documents.read_pdf('https://static.cninfo.com.cn/test.pdf')
        self.assertNotIn('PRIVATE',str(error.exception))
        with tempfile.TemporaryDirectory() as folder:
            hub=ResearchHub(folder)
            with self.assertRaisesRegex(ValueError,'cached_primary_failure:RuntimeError:pdf_parser_exit:-9'):
                primary.cached(hub,'failure',600,lambda:(_ for _ in ()).throw(RuntimeError('pdf_parser_exit:-9')))

    def response(self):
        result = Mock(status_code=200)
        result.__enter__ = Mock(return_value=result)
        result.__exit__ = Mock(return_value=False)
        result.iter_content.return_value = [b'%PDF-test']
        return result

    def test_concurrent_collection_runs_one_parser_at_a_time(self):
        state = {'active': 0, 'peak': 0}
        guard = threading.Lock()
        def parse(*args, **kwargs):
            with guard:
                state['active'] += 1
                state['peak'] = max(state['peak'], state['active'])
            try:
                time.sleep(0.03)
                return SimpleNamespace(returncode=0, stdout=json.dumps({'read_pages': 196}))
            finally:
                with guard:
                    state['active'] -= 1
        with patch.object(documents, 'pdf_ready', return_value=True), \
                patch.object(documents.requests, 'get', side_effect=lambda *a, **k: self.response()), \
                patch.object(documents.subprocess, 'run', side_effect=parse) as run:
            with ThreadPoolExecutor(max_workers=3) as workers:
                results = list(workers.map(documents.read_pdf, ['https://static.cninfo.com.cn/test.pdf']*3))
        self.assertEqual(state['peak'], 1)
        self.assertEqual([r['read_pages'] for r in results], [196]*3)
        self.assertEqual(run.call_count, 3)

    def test_timeout_releases_parser_slot_for_next_document(self):
        good = SimpleNamespace(returncode=0, stdout='{"read_pages":214}')
        with patch.object(documents, 'pdf_ready', return_value=True), \
                patch.object(documents.requests, 'get', side_effect=lambda *a, **k: self.response()), \
                patch.object(documents.subprocess, 'run', side_effect=[subprocess.TimeoutExpired('parser', 1), good]):
            with self.assertRaisesRegex(TimeoutError, 'pdf_parse_budget_exhausted'):
                documents.read_pdf('https://static.cninfo.com.cn/first.pdf')
            self.assertEqual(documents.read_pdf('https://static.cninfo.com.cn/second.pdf')['read_pages'], 214)

    def test_queue_deadline_does_not_launch_another_parser(self):
        slot = Mock()
        slot.acquire.return_value = False
        with patch.object(documents, 'pdf_ready', return_value=True), \
                patch.object(documents.requests, 'get', return_value=self.response()), \
                patch.object(documents, '_parser_slot', slot), \
                patch.object(documents.subprocess, 'run') as run:
            with self.assertRaisesRegex(TimeoutError, 'pdf_queue_budget_exhausted'):
                documents.read_pdf('https://static.cninfo.com.cn/test.pdf')
        run.assert_not_called()
        slot.release.assert_not_called()
