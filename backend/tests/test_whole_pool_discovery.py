from datetime import datetime,timedelta
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from app.models.news import News
from app.services.ai_analyzer import AIAnalyzerService
from app.services.episode_workspace import EpisodeWorkspace
from app.services.news_workspace_brief import catalogue,without_catalogue,BEGIN,END
from app.config import settings

NOW=datetime(2026,10,30,17)

def item(i,large=False):
    name='独立企业'+str(i)
    # Directory budget tests use admissible industry leads. Routine unrelated
    # individual earnings are now intentionally outside the episode scope.
    title='产业链观察'+str(i)+'订单增长'+str(i+1)+'%'
    text=(name+'披露收入增长'+str(i+3)+'%，现金流变化需核对。')*(120 if large else 4)
    return News(id='id-'+str(i),title=title,content=text,source='财联社公开原文',
        source_url='https://www.cls.cn/detail/'+str(i+1000),published_at=NOW-timedelta(minutes=i),importance_score=.8)

def prepare(rows,budget=34000):
    analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
    with patch('app.services.ai_analyzer.get_watchlist_service',return_value=SimpleNamespace(get_all_stocks=lambda:[])),patch('app.services.research_hub.ResearchHub.load',return_value=[]),patch.object(settings,'news_initial_prompt_characters',budget):
        text=analyzer._prepare_news_summary(rows)
    return analyzer,text

class WholePoolTests(unittest.TestCase):
    def test_complete_directory_includes_unread_and_does_not_claim_body_exposure(self):
        rows=[item(i,True) for i in range(80)]
        analyzer,text=prepare(rows)
        data=analyzer._news_briefing
        self.assertEqual(data['discovery_catalogue']['entries'],80)
        self.assertTrue(data['discovery_catalogue']['complete'])
        self.assertLess(len(analyzer._selected_evidence_news),80)
        for row in rows:self.assertIn(row.title,text)
        self.assertLessEqual(len(text),34000)
        self.assertIsNone(data['initial_budget']['article_count_limit'])
        self.assertIn('不是正文证据',text)

    def test_short_material_can_exceed_28_without_exceeding_character_budget(self):
        analyzer,text=prepare([item(i) for i in range(50)],50000)
        self.assertGreater(len(analyzer._selected_evidence_news),28)
        self.assertLessEqual(len(text),50000)

    def test_budget_overflow_fails_instead_of_hiding_tail(self):
        with self.assertRaisesRegex(RuntimeError,'目录超出新闻预算'):
            prepare([item(i,True) for i in range(700)],12000)

    def test_catalogue_reference_resolves_to_canonical_id_without_fake_read(self):
        rows=[item(1),item(2)]
        rows[0].id='C0001'
        directory=catalogue(rows,[])
        self.assertNotIn('C0001',directory['references'])
        with tempfile.TemporaryDirectory() as folder:
            ws=EpisodeWorkspace(rows,root=folder,now=NOW)
            ws.bind_catalogue(directory['references'])
            self.assertEqual(ws.usage()['prepared_sources'],0)
            ref=next(iter(directory['references']))
            reply=ws.read(ref,characters=80)
            self.assertEqual(reply['id'],directory['references'][ref])
            self.assertIn(reply['id'],ws.accessed)
            self.assertEqual(ws.usage()['prepared_sources'],1)
            with self.assertRaisesRegex(ValueError,'changed'):
                ws.bind_catalogue({ref:next(x.id for x in rows if x.id!=reply['id'])})

    def test_followup_drops_only_generated_metadata_and_keeps_evidence(self):
        directory=catalogue([item(1)],[])['text']
        prompt='规则\n'+directory+'\n[N:id-1]完整原句与来源。'
        stripped=without_catalogue(prompt)
        self.assertNotIn(BEGIN,stripped)
        self.assertIn('[N:id-1]完整原句与来源。',stripped)
        with self.assertRaisesRegex(ValueError,'collision'):
            without_catalogue(prompt+'\n'+BEGIN)


class DiscoveryLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_sent_once_then_exact_source_read_is_preserved(self):
        from app.services.episode_research import complete_with_research
        import json
        rows=[item(1)]
        directory=catalogue(rows,[])
        with tempfile.TemporaryDirectory() as folder:
            ws=EpisodeWorkspace(rows,root=folder,now=NOW)
            ws.bind_catalogue(directory['references'])
            ref=next(iter(directory['references']))
            calls=[]
            class Analyzer:
                async def _call_ai(self,prompt,max_tokens):
                    calls.append(prompt)
                    if len(calls)==1:
                        return json.dumps(dict(action='request_evidence',requests=[dict(tool='read_material',id=ref,characters=80)]))
                    return '完整报告'
            with patch('app.services.research_hub.ResearchHub.load',return_value=[]),patch('app.services.report_diagnostics.save_generation_stage'):
                response,transcript=await complete_with_research(Analyzer(),directory['text']+'\n已经提供的原句。',300,ws,[])
            self.assertEqual(response,'完整报告')
            self.assertEqual(len(calls),2)
            self.assertIn(BEGIN,calls[0]);self.assertNotIn(BEGIN,calls[1])
            self.assertIn('已经提供的原句。',calls[1])
            self.assertIn('id-1',calls[1])
            self.assertEqual(ws.usage()['confirmed_sources'],1)

    async def test_reviewer_receives_provided_evidence_without_unread_directory(self):
        from app.models.report import ReportType
        analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
        text=analyzer._build_review_prompt('报告正文','行情',catalogue([item(1)],[])['text']+'\n[N:id-1]实际提供的正文。','跨市场',ReportType.MORNING)
        self.assertNotIn(BEGIN,text)
        self.assertIn('[N:id-1]实际提供的正文。',text)
