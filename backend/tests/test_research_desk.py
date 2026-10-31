import copy,json,tempfile,unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from app.models.news import News
from app.services.episode_workspace import EpisodeWorkspace
from app.services.research_desk import AREAS,decode,validate
from app.services.episode_research import complete_with_research,execute
from app.services.watchlist_service import WatchlistStock

NOW=datetime(2026,10,31,8)
def article(key):
    return News(id=key,title='公司订单与融资条件变化'+key,content='公司披露经营变化，需核对期间、并表范围与原始依据。'*120,
                source='证券时报原文',source_url='https://example.com/news/'+key,published_at=NOW)

def reply(report='报告[N:one]',stocks=()):
    return dict(action='complete_research',report=report,research=dict(
        coverage=[dict(area=area,status='catalogue_checked',evidence_ids=[],explanation='仅检查本期目录，仍须区分正文和全网覆盖。') for area in AREAS],
        watchlist_checks=[dict(key='A:'+stock.code,status='catalogue_checked',evidence_ids=[],explanation='当前名单检查，不强行编造公司新闻。') for stock in stocks],
        questions=[dict(id='Q1',title='订单增长是否伴随融资压力',selected=True,priority='high',status='supported',
            support_ids=['one'],counter_ids=[],what_changed='新披露订单与现金流需要同口径比较。',
            why_it_matters='可能影响未来几日风险判断。',mechanism='现金投入与订单不是同一个变量。',
            alternative='市场预期及其他驱动尚需比较。',what_to_watch='下一份经营披露与之后数日价格是否改变判断。')],omissions=[]))

class DeskTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.workspace=EpisodeWorkspace([article('one'),article('two')],self.tmp.name,NOW)
        self.workspace.prepare_ranges('one',[[0,300]],'initial_news')
        self.workspace.confirm_analysis_response()

    async def test_one_reply_can_contain_dossier_and_report_without_editor_call(self):
        analyzer=SimpleNamespace(_call_ai=AsyncMock(return_value=json.dumps(reply())))
        with patch('app.services.report_diagnostics.save_generation_stage'):
            report,transcript=await complete_with_research(analyzer,'实际输入',4000,self.workspace,[])
        self.assertEqual(report,'报告[N:one]');self.assertEqual(transcript,[])
        self.assertEqual(analyzer._call_ai.await_count,1)
        stored=json.loads((self.workspace.path/'research-dossier.json').read_text(encoding='utf-8'))
        self.assertEqual(stored['status'],'recorded_for_human_review')

    async def test_plain_report_cannot_silently_skip_research_contract(self):
        analyzer=SimpleNamespace(_call_ai=AsyncMock(return_value='直接写了一个简短报告'))
        with patch('app.services.report_diagnostics.save_generation_stage'):
            with self.assertRaisesRegex(RuntimeError,'结构化研究底稿'):
                await complete_with_research(analyzer,'输入',4000,self.workspace,[])
        self.assertEqual(analyzer._call_ai.await_count,1)

    async def test_empty_research_questions_cannot_accompany_a_finished_report(self):
        data=reply();data['research']['questions']=[]
        with self.assertRaisesRegex(RuntimeError,'缺少实际选题'):validate(data,self.workspace,[])

    async def test_known_critical_unread_gap_stops_report_and_preserves_dossier(self):
        data=reply();data['research']['questions'][0].update(status='needs_reading',support_ids=['two'])
        with self.assertRaisesRegex(RuntimeError,'关键问题'):
            validate(data,self.workspace,[])
        self.assertTrue((self.workspace.path/'research-dossier.json').exists())

    async def test_title_in_pool_does_not_count_as_supplied_body(self):
        data=reply();data['research']['questions'][0]['support_ids']=['two']
        with self.assertRaisesRegex(RuntimeError,'未提供正文'):validate(data,self.workspace,[])

    async def test_report_cannot_quote_unread_title_even_if_ledger_looks_valid(self):
        with self.assertRaisesRegex(RuntimeError,'未提供正文'):validate(reply('报告[N:two]'),self.workspace,[])

    async def test_covering_only_a_few_areas_is_not_full_research_record(self):
        data=reply();data['research']['coverage']=data['research']['coverage'][:2]
        with self.assertRaisesRegex(RuntimeError,'覆盖对象'):validate(data,self.workspace,[])

    async def test_current_watchlist_is_checked_and_stale_stock_cannot_replace_it(self):
        stocks=[WatchlistStock('654321','新加入公司','A')]
        data=reply(stocks=stocks);validate(data,self.workspace,stocks)
        data['research']['watchlist_checks'][0]['key']='A:123456'
        with self.assertRaisesRegex(RuntimeError,'覆盖对象'):validate(data,self.workspace,stocks)

    async def test_no_company_news_and_future_monitor_are_allowed(self):
        stocks=[WatchlistStock('654321','新加入公司','A')];data=reply(stocks=stocks)
        data['research']['watchlist_checks'][0].update(status='missing',explanation='本池没有新增公司新闻，不能推定全网没有。')
        data['research']['questions'][0].update(status='monitor',support_ids=[],what_to_watch='下一交易日才可能发生的价格验证。')
        validate(data,self.workspace,stocks)

    async def test_price_only_question_requires_real_price_context(self):
        data=reply();data['research']['questions'][0].update(support_ids=[],basis='price_only')
        with self.assertRaisesRegex(RuntimeError,'缺少实际正文或行情'):validate(data,self.workspace,[])
        self.workspace.price_context_present=True;validate(data,self.workspace,[])

    async def test_search_claim_without_tool_or_disabled_search_is_rejected(self):
        data=reply();data['research']['coverage'][0]['status']='scoped_search_checked'
        with self.assertRaisesRegex(RuntimeError,'没有成功工具'):validate(data,self.workspace,[])
        self.workspace.record(dict(tool='search_web'),dict(status='unavailable'))
        with self.assertRaisesRegex(RuntimeError,'没有成功工具'):validate(data,self.workspace,[])

    async def test_batch_read_exposes_several_sources_and_never_silently_truncates(self):
        with patch('app.services.research_hub.ResearchHub.load',return_value=[]):
            result=await execute(self.workspace,[dict(tool='read_materials',items=[dict(id='one',characters=200),dict(id='two',characters=400)],total_characters=600)],[])
            before=copy.deepcopy(self.workspace.prepared)
            with self.assertRaisesRegex(ValueError,'budget_exceeded'):
                await execute(self.workspace,[dict(tool='read_materials',items=[dict(id='one',characters=500),dict(id='two',characters=500)],total_characters=600)],[])
        self.assertEqual(self.workspace.prepared,before)
        self.assertEqual([len(row['text']) for row in result[0]['result']['results']],[200,400])

    async def test_missing_or_duplicate_question_identifiers_fail(self):
        data=reply();data['research']['questions']*=2
        with self.assertRaisesRegex(RuntimeError,'编号重复'):validate(data,self.workspace,[])
