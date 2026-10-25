import json
import tempfile
import unittest
from datetime import datetime,timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch

from app.models.news import News
from app.services.episode_workspace import EpisodeWorkspace
from app.services.episode_research import complete_with_research,execute
from app.services.research_hub import Material,ResearchHub
from app.services.material_lifecycle import prune_material_caches

NOW=datetime(2026,10,25,12)


def article(identifier='new'):
    return News(id=identifier,title='封装材料供需变化',content='公开报道说明行业供需变化，须区分行业与公司。'*100,
        source='证券时报原文',source_url='https://www.stcn.com/article/detail/123.html',published_at=NOW)


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.workspace=EpisodeWorkspace([article()],self.tmp.name,NOW)

    def test_material_keeps_original_period_scope_and_unknown_publication(self):
        material=Material('baseline','财报封装业务','披露文件','https://static.cninfo.com.cn/finalpage/2026-09-01/123.PDF',
            'financial_baseline','A:123456','封装业务收入的历史对照。'*100,None,NOW.isoformat(),'2026半年','节选')
        self.workspace.add([material])
        match=self.workspace.search('财报封装')['results'][0]
        self.assertEqual(match['id'],'baseline');self.assertIsNone(match['published'])
        self.assertEqual(match['period'],'2026半年');self.assertEqual(match['reading_scope'],'节选')
        self.assertTrue(self.workspace.read('baseline',characters=80)['has_more'])

    def test_stale_opinion_and_future_material_are_not_admitted(self):
        for identifier,stamp in [('stale',NOW-timedelta(days=60)),('future',NOW+timedelta(days=1))]:
            self.workspace.add([Material(identifier,'研报','机构','https://example.com/report.pdf','company_research',
                'A:123456','观点背景。'*50,stamp,NOW.isoformat())])
            self.assertEqual(self.workspace.read(identifier)['status'],'not_found')

    def test_success_erases_bodies_and_failure_expires_only_owned_folder(self):
        self.workspace.search('封装');self.workspace.record({'tool':'search'},dict(text='正文'))
        self.workspace.finish(True)
        self.assertFalse((self.workspace.path/'materials.json').exists())
        self.assertFalse((self.workspace.path/'retrieval.json').exists())
        self.assertTrue((self.workspace.path/'sources.json').exists())
        failed=EpisodeWorkspace([article()],self.tmp.name,NOW);failed.finish(False)
        foreign=Path(self.tmp.name)/'episode-other';foreign.mkdir();(foreign/'keep').write_text('other')
        self.assertTrue((failed.path/'materials.json').exists())
        self.assertEqual(EpisodeWorkspace.prune(self.tmp.name,NOW+timedelta(hours=25)),2)
        self.assertTrue((foreign/'keep').exists())

    def test_id_collision_is_not_silently_replaced(self):
        other=article();other.content='另一版本正文。'*100
        with self.assertRaises(ValueError):self.workspace.add([other])

    def test_cached_pool_does_not_depend_on_initial_prompt_selection(self):
        material=Material('unselected','未预选财报','披露','https://example.com/report.pdf',
            'financial_baseline','A:123456','正文'*100,NOW,NOW.isoformat())
        row=dict(material.__dict__,published_at=NOW.isoformat())
        with patch.object(ResearchHub,'load',return_value=[dict(materials=[row])]):
            result=ResearchHub().evidence_pool([])
        self.assertEqual(result[0].id,'unselected')

    def test_context_expiry_is_enforced_even_before_housekeeping(self):
        from app.services.watchlist_service import WatchlistStock
        root=Path(self.tmp.name)/'research';(root/'stocks').mkdir(parents=True)
        (root/'stocks/A-123456.json').write_text(json.dumps(dict(key='A:123456',
            collected_at=(NOW-timedelta(hours=25)).isoformat(),profile={'industry':'old'},materials=[])))
        with patch('app.services.research_hub.china_now',return_value=NOW):
            context=ResearchHub(root).load([WatchlistStock('123456','动态公司','A')])[0]
        self.assertIsNone(context['profile'])


class RetrievalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.workspace=EpisodeWorkspace([article()],self.tmp.name,NOW)

    async def test_ready_response_has_no_extra_model_call(self):
        analyzer=SimpleNamespace(_call_ai=AsyncMock(return_value='完整报告'))
        with patch('app.services.report_diagnostics.save_generation_stage') as save:
            result,transcript=await complete_with_research(analyzer,'初始材料',100,self.workspace,[])
        self.assertEqual(result,'完整报告');self.assertEqual(transcript,[])
        self.assertEqual(analyzer._call_ai.await_count,1);save.assert_called_once()

    async def test_search_then_read_unselected_body_and_finish(self):
        request=lambda rows:json.dumps(dict(action='request_evidence',requests=rows))
        analyzer=SimpleNamespace(_call_ai=AsyncMock(side_effect=[
            request([dict(tool='search_materials',query='封装材料')]),
            request([dict(tool='read_material',id='new',offset=800,characters=100)]),'最终报告[N:new]']))
        with patch('app.services.report_diagnostics.save_generation_stage'),patch.object(ResearchHub,'load',return_value=[]):
            result,transcript=await complete_with_research(analyzer,'初始只给标题',100,self.workspace,[])
        self.assertEqual(len(transcript),2);self.assertIn('new',self.workspace.accessed)
        self.assertIn('工具返回资料',analyzer._call_ai.call_args.args[0])
        self.assertEqual(result,'最终报告[N:new]')

    async def test_tool_round_limit_cannot_be_published_as_report(self):
        request=json.dumps(dict(action='request_evidence',requests=[dict(tool='search_materials',query='封装')]))
        analyzer=SimpleNamespace(_call_ai=AsyncMock(return_value=request))
        with patch('app.services.report_diagnostics.save_generation_stage'),patch.object(ResearchHub,'load',return_value=[]):
            with self.assertRaisesRegex(RuntimeError,'仍请求工具'):
                await complete_with_research(analyzer,'初始材料',100,self.workspace,[])
        self.assertEqual(analyzer._call_ai.await_count,3)

    async def test_unknown_tool_and_invalid_range_fail_without_network(self):
        with patch.object(ResearchHub,'load',return_value=[]):
            with self.assertRaises(ValueError):await execute(self.workspace,[dict(tool='private_api')],[])
        with self.assertRaises(ValueError):self.workspace.read('new',offset=-1)


class LifecycleTests(unittest.TestCase):
    def test_only_expired_transient_paths_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            paths=['research/cache/old.json','research/stocks/old.json','diagnostics/review-old.json',
                'reports/old.json','podcasts/old.json','model-usage/old.json','backups/old.json']
            for relative in paths:
                target=root/relative;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_text(json.dumps(dict(collected_at=(NOW-timedelta(days=2)).isoformat())))
            (root/'.env').write_text('KEEP=1')
            result=prune_material_caches(root,NOW)
            self.assertEqual(len(result['removed']),3)
            for relative in paths[3:]:self.assertTrue((root/relative).exists())
            self.assertEqual((root/'.env').read_text(),'KEEP=1')
