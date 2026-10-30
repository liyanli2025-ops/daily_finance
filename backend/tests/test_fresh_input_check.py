import hashlib
import json
import unittest
from datetime import datetime
from app.fresh_input_check import inspect

NOW=datetime(2026,10,30,16)
WATCH=[('A','300750','宁德时代')]

class FreshInputTests(unittest.TestCase):
    def case(self, **changes):
        data=dict(full_collection=True,collection_started_at='2026-10-30T15:40:00',
                  collected_at='2026-10-30T15:50:00',watchlist_signature=WATCH,
                  raw_articles=[dict(id='new',title='当期新闻',source='公开源',content='已保存的文章内容',published='2026-10-30T15:00:00'),
                                dict(id='old',title='旧背景',source='公开源',content='已保存的文章内容',published='2026-10-01T15:00:00')])
        data.update(changes)
        raw=json.dumps(data).encode()
        replay=dict(snapshot_sha256=hashlib.sha256(raw).hexdigest(),selection=dict(articles=[
            dict(id='new',selected=True),dict(id='old',selected=True)]))
        technical=dict(collected_at='2026-10-30T15:45:00',watchlist=['A:300750'])
        return raw,replay,technical

    def test_new_collection_does_not_relabel_old_articles(self):
        result=inspect(*self.case(),WATCH,NOW)
        self.assertEqual(result['status'],'ready_for_material_review')
        self.assertEqual(result['selected_publication_bands'],{'within_24h':1,'older_background':1})
        self.assertEqual(result['model_requests_performed'],0)

    def test_missing_start_cannot_become_fresh_by_touching_completion(self):
        result=inspect(*self.case(collection_started_at=None),WATCH,NOW)
        self.assertIn('collection_started_at: missing_or_invalid',result['errors'])
        result=inspect(*self.case(collection_started_at='2026-10-29T15:40:00'),WATCH,NOW)
        self.assertEqual(result['status'],'blocked')

    def test_changed_watchlist_or_replay_is_blocked(self):
        raw,replay,technical=self.case()
        replay['snapshot_sha256']='other'
        result=inspect(raw,replay,technical,[('A','600900','长江电力')],NOW)
        self.assertIn('selection_snapshot_mismatch',result['errors'])
        self.assertIn('collection_watchlist_mismatch',result['errors'])
        self.assertIn('technical_watchlist_mismatch',result['errors'])

    def test_timezone_normalization_and_future_clock(self):
        result=inspect(*self.case(collection_started_at='2026-10-30T07:40:00+00:00'),WATCH,NOW)
        self.assertEqual(result['status'],'ready_for_material_review')
        result=inspect(*self.case(collected_at='2026-10-30T17:00:00'),WATCH,NOW)
        self.assertEqual(result['status'],'blocked')

    def test_invalid_article_cannot_pass_even_when_collection_is_new(self):
        raw,replay,technical=self.case()
        data=json.loads(raw)
        data['raw_articles'][0]['published']='2026-11-01T15:00:00'
        data['raw_articles'][1]['content']=' '
        raw=json.dumps(data).encode()
        replay['snapshot_sha256']=hashlib.sha256(raw).hexdigest()
        result=inspect(raw,replay,technical,WATCH,NOW)
        self.assertEqual(result['status'],'blocked')
        self.assertIn('selected_publication_future:new',result['errors'])
        self.assertIn('selected_body_missing:old',result['errors'])
