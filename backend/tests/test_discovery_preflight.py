import asyncio
from datetime import datetime,timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,patch

SPEC=importlib.util.spec_from_file_location('discovery_preflight',Path(__file__).resolve().parents[2]/'tools/prepare_discovery_acceptance_v1.py')
m=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(m)

class PreflightTests(unittest.TestCase):
    def test_binding_checks_normalized_sources_and_rejects_unknown_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'source.py').write_bytes(b'abc\r\n')
            expected={'source.py':hashlib.sha256(b'abc\n').hexdigest()}
            m.verify_sources(root,expected)
            (root/'source.py').write_bytes(b'changed')
            with self.assertRaises(RuntimeError):m.verify_sources(root,expected)

    def test_inputs_are_content_addressed_and_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path,key=m.save_input(Path(folder),{'message':'固定输入'})
            again,other=m.save_input(Path(folder),{'message':'固定输入'})
            self.assertEqual((path,key),(again,other))
            path.write_text('conflict')
            with self.assertRaises(RuntimeError):m.save_input(Path(folder),{'message':'固定输入'})

class ActualInputTests(unittest.IsolatedAsyncioTestCase):
    async def test_preview_includes_research_and_market_without_exporting_key(self):
        from app.models.news import News
        from app.services.ai_analyzer import AIAnalyzerService
        from app.services.watchlist_service import WatchlistStock
        now=datetime(2026,10,30,18)
        stock=WatchlistStock('123456','新公司','A')
        service=SimpleNamespace(get_all_stocks=lambda:[stock])
        row=dict(id='one',title='新公司收入增长',content='新公司披露2026年第三季度收入增长，现金流下降。'*20,
            source='财联社公开原文',url='https://www.cls.cn/detail/12345',published=(now-timedelta(minutes=15)).isoformat(),news_type='finance')
        news=News(id=row['id'],title=row['title'],content=row['content'],source=row['source'],source_url=row['url'],published_at=datetime.fromisoformat(row['published']))
        analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
        with patch('app.services.ai_analyzer.get_watchlist_service',return_value=service),patch('app.services.research_hub.ResearchHub.load',return_value=[]):
            text=analyzer._prepare_news_summary([news])
        selection=analyzer._news_briefing
        snapshot=dict(full_collection=True,collected_at=(now-timedelta(minutes=5)).isoformat(),collection_started_at=(now-timedelta(minutes=10)).isoformat(),hours=72,
            watchlist_signature=[['A','123456','新公司']],raw_articles=[row],selection=selection)
        raw=json.dumps(snapshot,ensure_ascii=False).encode()
        replay=dict(snapshot_sha256=m.digest(raw),selection=selection,news_input=text,
            discovery_catalogue=selection['discovery_catalogue'],initial_budget=selection['initial_budget'])
        route=SimpleNamespace(provider='ofox_anthropic',model='test-model',base_url='https://api.example.com/v1',effort='none',api_key='DO_NOT_EXPORT_THIS_KEY')
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);data=root/'data';radar=data/'radar';radar.mkdir(parents=True)
            (data/'.automation-paused').write_text('paused')
            (radar/'news-acceptance.json').write_bytes(raw)
            (radar/'selection-replay.json').write_text(json.dumps(replay,ensure_ascii=False),encoding='utf-8')
            (radar/'technical.json').write_text(json.dumps(dict(collected_at=(now-timedelta(minutes=7)).isoformat(),watchlist=['A:123456'])),encoding='utf-8')
            hub=SimpleNamespace(root=data/'research',prompt=lambda *a,**k:('当前研究底稿证据。'*40,[]),evidence_pool=lambda *a:[],prompt_reading=[])
            with patch.object(m,'verify_sources'),patch('app.services.time_context.china_now',return_value=now),patch('app.services.watchlist_repository.refresh_app_watchlist',AsyncMock(return_value=service)),patch('app.services.watchlist_repository.assert_watchlist_current',AsyncMock()),patch('app.services.research_hub.ResearchHub',return_value=hub),patch('app.services.technical_radar.prompt',return_value='冻结行情与带日期报价'),patch('app.services.model_gateway.resolve_route',return_value=route):
                result=await m.prepare(root)
            packet=json.loads(Path(result['input_file']).read_text(encoding='utf-8'))
            self.assertIn('当前研究底稿证据',packet['base_prompt'])
            self.assertIn('冻结行情与带日期报价',packet['base_prompt'])
            self.assertEqual(result['http_requests_performed'],0)
            self.assertEqual(result['proposed_max_http_requests'],2)
            self.assertNotIn('DO_NOT_EXPORT_THIS_KEY',json.dumps(packet))
