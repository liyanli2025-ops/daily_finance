import copy,importlib.util,io,tempfile,unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,AsyncMock,patch

SCRIPT=Path(__file__).resolve().parents[2]/'tools/run_tavily_acceptance_once.py'
spec=importlib.util.spec_from_file_location('tavily_once_fixture',SCRIPT)
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)
NOW=datetime(2026,10,31,14)


class SampleTests(unittest.TestCase):
    def workspace(self):return SimpleNamespace(web_search_attempts=0)

    def test_dynamic_watchlist_sample_no_old_stock_fallback(self):
        rows=[dict(code='01234',name='新公司',market='HK')]
        q=probe.queries_for(rows,NOW)
        self.assertIn('新公司',q[3]['query']);self.assertEqual(q[3]['scope'],'HK:01234')
        self.assertEqual(probe.queries_for([],NOW)[3]['lane'],'industry')

    def test_at_most_four_searches_and_four_body_urls_with_checkpoints(self):
        w=self.workspace();saved=[]
        def search(ws,q,**kwargs):
            ws.web_search_attempts+=1
            return dict(status='ok',results=[dict(title='实际结果标题',url='https://example.com/article/'+str(ws.web_search_attempts),published_hint=None)])
        read=Mock(return_value=dict(status='ok',material=dict(text='原文片段',has_more=True)))
        r=probe.sample(w,probe.queries_for([],NOW),search,read,lambda v:saved.append(copy.deepcopy(v)),NOW)
        self.assertEqual(r['search_http_attempts'],4);self.assertEqual(read.call_count,4)
        self.assertEqual(r['readable_body_count'],4);self.assertEqual(r['model_requests'],0)
        self.assertEqual(r['status'],'completed_for_human_review')
        self.assertGreaterEqual(len(saved),9)

    def test_bad_search_stops_without_spending_remaining_attempts(self):
        w=self.workspace()
        def search(ws,q,**kwargs):
            ws.web_search_attempts+=1;return dict(status='failed',reason='http_401',results=[])
        read=Mock();r=probe.sample(w,probe.queries_for([],NOW),search,read,lambda _:None,NOW)
        read.assert_not_called();self.assertEqual(r['search_http_attempts'],1)
        self.assertEqual(r['status'],'partial_or_failed_no_retry')

    def test_empty_results_are_not_bodies_or_proof_of_no_news(self):
        w=self.workspace();read=Mock()
        def search(ws,q,**kwargs):ws.web_search_attempts+=1;return dict(status='ok',results=[])
        r=probe.sample(w,probe.queries_for([],NOW),search,read,lambda _:None,NOW)
        self.assertEqual(r['readable_body_count'],0);read.assert_not_called()
        self.assertIn('不代表',r['limitation'])

    def test_duplicate_and_paused_urls_not_re_requested(self):
        w=self.workspace();read=Mock(return_value=dict(status='failed',reason='web_source_body_unavailable'))
        def search(ws,q,**kwargs):
            ws.web_search_attempts+=1
            return dict(status='ok',results=[dict(title='失败路由',url='https://example.com/paused'),dict(title='同一链接',url='https://example.com/article/1')])
        with patch('app.services.source_health.PAUSED_PUBLIC_ARTICLES',{'https://example.com/paused':'paused'}):
            r=probe.sample(w,probe.queries_for([],NOW),search,read,lambda _:None,NOW)
        self.assertEqual(read.call_count,1);self.assertEqual(r['readable_body_count'],0)

    def test_budget_cannot_be_silently_increased(self):
        with self.assertRaises(ValueError):probe.sample(self.workspace(),[],Mock(),Mock(),Mock(),NOW,20)


class EntryTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_sample_restores_process_settings_and_keeps_stop_marker(self):
        from app.config import settings
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'.env').write_text('preserve-original-settings')
            ws=SimpleNamespace(path=root/'episode',meta={})
            def fail(*args,**kwargs):
                self.assertTrue(settings.research_web_search_enabled)
                ws.web_search_attempts=2
                args[4]({'phase':'saved_before_failure','search_results':[]})
                raise RuntimeError('synthetic failure')
            with patch.object(probe,'setup',return_value=root),\
                 patch('app.services.watchlist_repository.read_app_watchlist',new=AsyncMock(return_value=[])),\
                 patch('app.services.web_research.capabilities',return_value={'configured':True}),\
                 patch('app.services.episode_workspace.EpisodeWorkspace',return_value=ws),\
                 patch.object(settings,'research_web_search_enabled',False),\
                 patch.object(probe,'sample',side_effect=fail),redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError,'保留开始标记'):await probe.main(True)
                self.assertFalse(settings.research_web_search_enabled)
            self.assertTrue((root/'data/diagnostics/tavily-acceptance-v1.started').exists())
            self.assertEqual((root/'.env').read_text(),'preserve-original-settings')
            import json
            result=json.loads((root/'data/radar/cache/tavily-acceptance-v1.json').read_text())
            self.assertEqual(result['phase'],'saved_before_failure')
            self.assertEqual(result['search_http_attempts'],2)

    async def test_preview_never_searches_or_leaks_secret(self):
        from app.config import settings
        from pydantic import SecretStr
        with tempfile.TemporaryDirectory() as folder,patch.object(probe,'setup',return_value=Path(folder)),\
             patch('app.services.watchlist_repository.read_app_watchlist',new=AsyncMock(return_value=[])),\
             patch('app.services.web_research.search') as search,patch('app.services.web_research.read_public') as read,\
             patch.object(settings,'research_web_search_api_key',SecretStr('private-key-never-print')):
            out=io.StringIO()
            with redirect_stdout(out):await probe.main(False)
            search.assert_not_called();read.assert_not_called()
            self.assertNotIn('private-key-never-print',out.getvalue())
            self.assertFalse((Path(folder)/'data/diagnostics/tavily-acceptance-v1.started').exists())

    async def test_existing_marker_blocks_repeat_search_even_if_result_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            marker=Path(folder)/'data/diagnostics/tavily-acceptance-v1.started';marker.parent.mkdir(parents=True);marker.write_text('earlier attempt')
            with patch.object(probe,'setup',return_value=Path(folder)),\
                 patch('app.services.watchlist_repository.read_app_watchlist',new=AsyncMock(return_value=[])),\
                 patch('app.services.web_research.capabilities',return_value={'configured':True}),\
                 patch('app.services.web_research.search') as search,redirect_stdout(io.StringIO()):
                await probe.main(True)
            search.assert_not_called()
