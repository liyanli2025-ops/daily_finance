import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import nonofficial_check as check


class NonofficialCheckTests(unittest.TestCase):
    def test_only_new_four_sources_without_watchlist(self):
        with patch.object(check,'PublicNewsCollector') as factory:
            factory.return_value.collect.return_value=([],{'sources':{}})
            result=check.inspect()
        factory.return_value.collect.assert_called_once_with([],{},hours=72,budget=40,providers=['eeo','jiemian','smm','trendforce'])
        self.assertEqual(result['read'],0)

    def test_saved_summary_does_not_recollect_or_implicitly_recover_missing_file(self):
        with tempfile.TemporaryDirectory() as root,patch.object(check,'SNAPSHOT',Path(root)/'sample.json'), \
                patch.object(check,'inspect',side_effect=AssertionError('must not collect')):
            with self.assertRaises(FileNotFoundError):check.run(saved=True)
            check.SNAPSHOT.write_text(json.dumps(dict(read=2,articles=[dict(title='公开报道')],coverage={})),encoding='utf-8')
            self.assertEqual(check.run(saved=True)['titles'],['公开报道'])

    def test_write_once_then_summary_uses_same_snapshot(self):
        with tempfile.TemporaryDirectory() as root,patch.object(check,'SNAPSHOT',Path(root)/'sample.json'), \
                patch.object(check,'inspect',return_value=dict(read=0,articles=[],coverage={'sources':{'eeo':dict(status='failed',errors=[dict(reason='source_paused_no_automatic_retest')])}})) as collect:
            first=check.run();saved=check.run(saved=True)
            self.assertEqual(first,saved)
            self.assertEqual(saved['sources']['eeo']['error_count'],1)
            collect.assert_called_once_with(72)
