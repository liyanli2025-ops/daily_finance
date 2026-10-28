from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock,patch
from types import SimpleNamespace

from app.selection_check import candidates,inspect


class SelectionReplayTests(unittest.IsolatedAsyncioTestCase):
    def snapshot(self):
        raw=[dict(id='promo',title='即将开幕，苏州电机展集中洽谈采购订单',source='界面新闻公开原文',
                  url='https://example.com/promo',content='企业订单增长20%，相关合作伙伴报名参展。'*30,published='2026-10-28T10:00:00'),
             dict(id='real',title='企业库存下降20%',source='界面新闻公开原文',url='https://example.com/real',
                  content='记者调查，企业库存下降20%，需求仍待核对。'*30,published='2026-10-28T10:00:00')]
        return dict(full_collection=True,collected_at='2026-10-28T12:04:17',raw_articles=raw,
                    selection=dict(articles=[dict(id=r['id'],title=r['title'],selected=True) for r in raw]))

    def test_missing_body_or_non_full_snapshot_stops_before_replay(self):
        data=self.snapshot();data['raw_articles']=[]
        with self.assertRaises(ValueError):candidates(data)
        data=self.snapshot();data['full_collection']=False
        with self.assertRaises(ValueError):candidates(data)

    async def test_replay_preserves_source_snapshot_and_makes_no_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'news-acceptance.json'
            source.write_text(json.dumps(self.snapshot()),encoding='utf-8');before=source.read_bytes()
            with patch('app.selection_check.refresh_app_watchlist',AsyncMock()), \
                    patch('app.services.ai_analyzer.get_watchlist_service',return_value=SimpleNamespace(get_all_stocks=lambda:[])), \
                    patch('app.services.watchlist_service.get_watchlist_service',return_value=SimpleNamespace(get_all_stocks=lambda:[])), \
                    patch('app.services.research_hub.ResearchHub.load',return_value=[]), \
                    patch('requests.get',side_effect=AssertionError('no network')), \
                    patch('app.services.ai_analyzer.AIAnalyzerService._call_ai',side_effect=AssertionError('no model')):
                result=await inspect(root)
            self.assertEqual(result['selected_count'],1)
            self.assertEqual(result['removed'][0]['id'],'promo')
            self.assertEqual(source.read_bytes(),before)
            self.assertTrue((root/'selection-replay.json').is_file())

    async def test_app_read_failure_cannot_use_cached_watchlist(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'news-acceptance.json').write_text(json.dumps(self.snapshot()),encoding='utf-8')
            with patch('app.selection_check.refresh_app_watchlist',AsyncMock(side_effect=RuntimeError('App unavailable'))):
                with self.assertRaises(RuntimeError):await inspect(root)
            self.assertFalse((root/'selection-replay.json').exists())
