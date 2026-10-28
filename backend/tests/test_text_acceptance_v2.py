from datetime import datetime,timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock,patch

from app.services.model_usage import reserve_call

spec=importlib.util.spec_from_file_location('text_acceptance_v2',Path(__file__).resolve().parents[2]/'tools/run_text_acceptance_v2.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
NOW=datetime(2026,10,28,13,5)


class TextAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self,root):
        folder=root/'data/radar';folder.mkdir(parents=True)
        rows=[dict(id=key,title=key,content=key+' 企业订单增长20%。'*20,source='界面新闻公开原文',
            url='https://example.com/'+key,published='2026-10-28T10:00:00') for key in ['initial','other']]
        articles=[dict(id=row['id'],title=row['title'],selected=row['id']=='initial') for row in rows]
        data=dict(full_collection=True,collected_at='2026-10-28T12:04:17',raw_articles=rows,selection=dict(articles=articles))
        raw=json.dumps(data).encode();(folder/'news-acceptance.json').write_bytes(raw)
        (folder/'selection-replay.json').write_text(json.dumps(dict(snapshot_sha256=hashlib.sha256(raw).hexdigest(),
            selection=dict(articles=articles),news_input='冻结的原文输入[N:initial]')),encoding='utf-8')
        (folder/'technical.json').write_text(json.dumps(dict(collected_at=data['collected_at'],watchlist=[])))

    def test_stale_or_mismatched_snapshot_stops(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.fixture(root)
            with self.assertRaisesRegex(RuntimeError,'超过2小时'):module.load(root,NOW+timedelta(hours=3))
            path=root/'data/radar/selection-replay.json';data=json.loads(path.read_text());data['snapshot_sha256']='wrong';path.write_text(json.dumps(data))
            with self.assertRaisesRegex(RuntimeError,'不匹配'):module.load(root,NOW)

    async def test_preflight_never_calls_model_or_starts_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.fixture(root)
            with patch.object(module,'china_now',return_value=NOW),patch.object(module,'read_app_watchlist',AsyncMock(return_value=[])), \
                    patch.object(module.SnapshotAnalyzer,'once',AsyncMock()) as once:
                await module.main(root)
            once.assert_not_awaited()
            self.assertFalse(list((root/'data/diagnostics').glob('*.started')))

    async def test_run_passes_whole_pool_and_reuses_finished_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.fixture(root)
            with patch.object(module,'china_now',return_value=NOW),patch.object(module,'read_app_watchlist',AsyncMock(return_value=[])), \
                    patch.object(module.SnapshotAnalyzer,'once',AsyncMock(return_value=SimpleNamespace(content='待人工验收[N:initial]'))) as once, \
                    patch.object(module.settings,'model_max_calls_per_report',8):
                await module.main(root,True);await module.main(root,True)
                self.assertEqual(module.settings.model_max_calls_per_report,4)
            once.assert_awaited_once()
            self.assertEqual({row.id for row in once.call_args.args[0]},{'initial','other'})
            state=json.loads((root/'data/diagnostics/text-acceptance-latest.json').read_text())
            self.assertEqual(state['status'],'passed_model_review')

    async def test_failed_run_cannot_repeat_and_watchlist_mismatch_cannot_start(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.fixture(root)
            with patch.object(module,'china_now',return_value=NOW),patch.object(module,'read_app_watchlist',AsyncMock(return_value=[dict(market='A',code='new')])), \
                    patch.object(module.SnapshotAnalyzer,'once',AsyncMock()) as once:
                with self.assertRaisesRegex(RuntimeError,'自选股'):await module.main(root,True)
                once.assert_not_awaited()
            with patch.object(module,'china_now',return_value=NOW),patch.object(module,'read_app_watchlist',AsyncMock(return_value=[])), \
                    patch.object(module.SnapshotAnalyzer,'once',AsyncMock(side_effect=RuntimeError('review failed'))) as once, \
                    patch.object(module.settings,'model_max_calls_per_report',4):
                with self.assertRaisesRegex(RuntimeError,'review failed'):await module.main(root,True)
                await module.main(root,True)
                once.assert_awaited_once()

    async def test_actual_request_reservation_stops_before_fifth(self):
        async def generate(*args,**kwargs):
            for _ in range(5):reserve_call()
        with tempfile.TemporaryDirectory() as folder:
            analyzer=module.SnapshotAnalyzer({},[],Path(folder)/'state.json',{})
            with patch('app.services.watchlist_repository.refresh_app_watchlist',AsyncMock(return_value=SimpleNamespace(get_all_stocks=lambda:[]))), \
                    patch('app.services.microstructure.MicrostructureRadar.collect',return_value={}), \
                    patch('app.services.scheduler.SchedulerService',return_value=SimpleNamespace(is_trading_day=lambda day:True)), \
                    patch.object(module.AIAnalyzerService,'generate_daily_report',generate), \
                    patch.object(module.settings,'model_max_calls_per_report',4):
                with self.assertRaisesRegex(RuntimeError,'上限'):await analyzer.once([])
            self.assertEqual(analyzer.calls,4)
