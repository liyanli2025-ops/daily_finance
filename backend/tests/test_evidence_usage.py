import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch

from app.services.episode_workspace import EpisodeWorkspace,_current
from app.services.episode_research import complete_with_research
from app.services.prompt_reading import excerpt,reading_ranges
from app.evidence_usage_check import check
from tests.test_episode_research import article,NOW


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.item=article()
        self.workspace=EpisodeWorkspace([self.item],self.tmp.name,NOW)

    def test_overlapping_reads_merge_and_pending_read_is_not_confirmed(self):
        w=self.workspace
        w.read('new',0,300);w.read('new',200,300);w.read('new',0,300)
        self.assertEqual(w.usage()['confirmed_sources'],0)
        w.confirm_analysis_response()
        w.read('new',450,300)
        row=w.usage()['sources'][0]
        self.assertEqual(row['confirmed_ranges'],[[0,500]])
        self.assertEqual(row['prepared_ranges'],[[0,750]])
        self.assertEqual(row['confirmed_stored_characters'],500)
        self.assertEqual(row['model_input_scope'],'stored_fragment')

    def test_out_of_range_does_not_authorize_or_record_empty_read(self):
        w=self.workspace
        self.assertEqual(w.read('new',len(self.item.content))['status'],'out_of_range')
        self.assertFalse(w.accessed);self.assertFalse(w.prepared)

    def test_initial_sources_survive_cleanup_without_bodies(self):
        w=self.workspace
        ranges=reading_ranges(self.item.content,self.item.title,600)
        w.prepare_ranges('new',ranges,'initial_news');w.confirm_analysis_response()
        notes=[dict(claim='待验证判断',horizon='数日',support_ids=['new'],counterevidence_ids=['missing'])]
        audit=w.usage('正文[N:new]及[N:missing]',notes)
        self.assertEqual(audit['cited_without_confirmed_text'],['missing'])
        self.assertEqual(audit['decision_sources_without_confirmed_text'],['missing'])
        w.finish(True)
        saved=json.loads((w.path/'sources.json').read_text(encoding='utf-8'))
        self.assertEqual(len(saved),2)
        self.assertNotIn('text',saved[0]);self.assertFalse((w.path/'materials.json').exists())
        self.assertEqual(check(w.path/'usage.json')['status'],'recorded')

    def test_full_stored_summary_does_not_claim_full_original_article(self):
        w=self.workspace
        with patch.object(w,'metadata',return_value=dict(reading_scope='rss_text')):
            w.read('new');w.confirm_analysis_response()
            row=w.usage()['sources'][0]
        self.assertEqual(row['reading_scope'],'rss_text')
        self.assertEqual(row['model_input_scope'],'all_stored_text')
        self.assertIn('摘要/节选100%也不是读完原文',w.usage()['limitation'])

    def test_mutating_same_object_cannot_silently_change_evidence(self):
        self.item.content+=' changed'
        with self.assertRaisesRegex(ValueError,'collision'):self.workspace.add([self.item])
        with self.assertRaisesRegex(ValueError,'source_changed'):
            self.workspace.read('new')

    def test_invalid_ranges_rejected(self):
        for span in [(-1,10),(0,99999),(True,10),(10,10)]:
            with self.assertRaises(ValueError):self.workspace.prepare_ranges('new',[span],'initial_news')

    def test_frozen_input_only_records_verbatim_matching_excerpt(self):
        from tests.test_text_acceptance_v2 import module
        token=_current.set(self.workspace)
        try:
            analyzer=module.SnapshotAnalyzer(dict(news_input='旧格式标题摘要'),[self.item],None,{})
            analyzer._prepare_news_summary_with_sentiment([self.item])
            self.assertFalse(self.workspace.prepared)
            analyzer.replay['news_input']=excerpt(self.item.content,self.item.title,1200)
            analyzer._prepare_news_summary_with_sentiment([self.item])
            self.assertIn('new',self.workspace.prepared)
        finally:_current.reset(token)

    def test_research_records_only_selected_body_prefix(self):
        from dataclasses import asdict
        from app.services.research_hub import ResearchHub,Material
        from app.services.watchlist_service import WatchlistStock
        material=Material('research','测试研究','披露','https://example.com/report.pdf',
            'financial_baseline','A:123456','唯一研究原文。'*3000,NOW,NOW.isoformat())
        row=dict(asdict(material),published_at=NOW.isoformat())
        hub=ResearchHub()
        context=dict(key='A:123456',name='动态公司',profile=None,coverage={},materials=[row])
        with patch.object(hub,'load',return_value=[context]):
            text,evidence=hub.prompt([WatchlistStock('123456','动态公司','A')],max_characters=8000)
        self.assertEqual([item.id for item in evidence],['research'])
        start,end=hub.prompt_ranges['research'][0]
        self.assertEqual(start,0);self.assertLess(end,len(material.body))
        self.assertIn(material.prompt(end),text)

    def test_historical_scope_is_unknown_and_read_only(self):
        path=Path(self.tmp.name)/'old.json'
        path.write_text(json.dumps(dict(content='旧稿',finance_evidence='全文')),encoding='utf-8')
        before=path.read_bytes()
        self.assertEqual(check(path)['status'],'unknown_historical_scope')
        self.assertEqual(before,path.read_bytes())

    def test_free_news_selection_registers_exact_initial_ranges(self):
        from app.services.ai_analyzer import AIAnalyzerService
        from app.services.research_hub import ResearchHub
        token=_current.set(self.workspace)
        try:
            with patch('app.services.ai_analyzer.get_watchlist_service',return_value=SimpleNamespace(get_all_stocks=lambda:[])),patch.object(ResearchHub,'load',return_value=[]):
                text=AIAnalyzerService()._prepare_news_summary_with_sentiment([self.item])
        finally:_current.reset(token)
        from app.services.evidence_reading import read_news
        reading=read_news(self.item.content,self.item.title,1200)
        expected=reading['ranges']
        self.assertIn(reading['text'],text)
        self.assertEqual(self.workspace.merged_ranges(self.workspace.prepared['new']),[list(span) for span in expected])
        self.assertEqual(self.workspace.usage()['confirmed_sources'],0)


class ResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_failure_never_confirms_prepared_text(self):
        with tempfile.TemporaryDirectory() as folder:
            w=EpisodeWorkspace([article()],folder,NOW)
            w.read('new',characters=100)
            analyzer=SimpleNamespace(_call_ai=AsyncMock(side_effect=RuntimeError('blocked')))
            with self.assertRaises(RuntimeError):await complete_with_research(analyzer,'input',100,w,[])
            self.assertEqual(w.usage()['confirmed_sources'],0)

    async def test_search_result_only_confirmed_in_following_successful_reply(self):
        with tempfile.TemporaryDirectory() as folder:
            w=EpisodeWorkspace([article()],folder,NOW)
            request=json.dumps(dict(action='request_evidence',requests=[dict(tool='search_materials',query='封装')]))
            analyzer=SimpleNamespace(_call_ai=AsyncMock(side_effect=[request,RuntimeError('failed')]))
            with patch('app.services.report_diagnostics.save_generation_stage'),patch('app.services.research_hub.ResearchHub.load',return_value=[]):
                with self.assertRaises(RuntimeError):await complete_with_research(analyzer,'input',100,w,[])
            self.assertEqual(w.usage()['prepared_sources'],1)
            self.assertEqual(w.usage()['confirmed_sources'],0)
            self.assertEqual(w.completed_rounds,1)
