"""Offline regressions for protocol, publication windows and subject admission."""
from copy import deepcopy
from datetime import datetime,timedelta
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch,AsyncMock,Mock

from app.models.news import News
from app.services.primary_discovery import decode,discover,Limits
from app.services.discovery_completion import review_events,FACETS
from app.services.web_research import parse_visible_article,read_public
from app.services.collection_time import policy,window,validate_window
from app.services.discovery_feedback import body_records,build_feedback
from app.services.episode_workspace import EpisodeWorkspace
from app.services.news_quality import company_focus,excluded_reason
from app.services.primary_report import export_discovery,prepare
from app.services.search_primary_collection import LANES

NOW=datetime(2026,11,1,13,56)
TEXT='经营变化、会计口径和风险仍需独立核对。'*30


class ResponseTests(unittest.TestCase):
    def test_identical_repeated_lane_is_audited_without_another_model_request(self):
        notes=[]
        result=decode('{"action":"finish","events":[{"lane":"industry","lane":"industry"}]}',normalizations=notes)
        self.assertEqual(result['events'][0]['lane'],'industry')
        self.assertEqual(notes,[dict(path='$["events"][0]["lane"]',action='identical_duplicate_removed')])

    def test_different_lane_values_still_stop(self):
        with self.assertRaisesRegex(ValueError,'duplicate_json_key'):
            decode('{"action":"finish","lane":"industry","lane":"commodities"}')

    def test_boolean_and_number_are_not_identical(self):
        with self.assertRaisesRegex(ValueError,'duplicate_json_key'):
            decode('{"action":"finish","x":true,"x":1}')

    def test_different_nested_object_keys_stop_without_keyerror(self):
        with self.assertRaisesRegex(ValueError,'duplicate_json_key'):
            decode('{"action":"finish","x":{"a":1},"x":{"b":1}}')

    def test_same_nested_values_are_normalized(self):
        result=decode('{"action":"finish","x":[{"a":1}],"x":[{"a":1}]}')
        self.assertEqual(result['x'],[{'a':1}])

    def test_fragments_and_multiple_objects_remain_rejected(self):
        for raw in ('{"action":"finish",','{"action":"finish"} {"action":"tools"}'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):decode(raw)

    def test_nonfinite_values_are_not_valid_tool_arguments(self):
        for raw in ('NaN','Infinity','1e999'):
            with self.subTest(raw=raw),self.assertRaisesRegex(ValueError,'nonfinite_json_number'):
                decode('{"action":"tools","x":'+raw+'}')

    def test_invalid_lane_reports_the_actual_field(self):
        event=dict(lane='global',evidence_ids=['B1'],research_checks={key:dict(
            status='supported',evidence_ids=['B1'],explanation='原文支持') for key in FACETS})
        result=review_events(dict(events=[event]),dict(watchlist=[]))
        self.assertEqual([row['code'] for row in result['problems']],['event_lane_invalid'])
        self.assertIn('global_policy',result['problems'][0]['allowed'])


class MetadataTests(unittest.TestCase):
    def parse(self,html):
        return parse_visible_article(html,'https://publisher.example/news/item',NOW,hours=168)

    def test_mobile_article_h2_and_explicit_time(self):
        item=self.parse('<article><div class="artiHead"><h2 class="artiTit">某公司基本面的变化与风险</h2>'
            '<span class="artiTime">2026-10-27 14:55:04</span></div><div>'+TEXT+'</div></article>')
        self.assertEqual(item.title,'某公司基本面的变化与风险')
        self.assertIn('2026-10-27 14:55:04',item.market_impact)
        self.assertIn('来源未标时区',item.market_impact)

    def test_header_english_date_is_day_precision(self):
        item=self.parse('<h1>FX daily snapshot and risks</h1><div class="publication-header__details">'
            '<ul><li>By Analyst</li><li>Oct 30, 2026</li></ul></div><article>'+TEXT+'</article>')
        self.assertIn('原始来源时点：Oct 30, 2026',item.market_impact)
        self.assertIn('精度：day',item.market_impact)

    def test_publisher_epoch_has_an_actual_timezone(self):
        item=self.parse('<h1>华能水电资产注入与三季报</h1><div class="info" data-article-publish-time="1793189379"></div>'
                        '<article>'+TEXT+'</article>')
        self.assertEqual(item.published_at,datetime(2026,10,28,20,9,39))

    def test_showtime_keeps_full_year_and_does_not_invent_timezone(self):
        item=self.parse('<h1>公司披露三季度财务数据</h1><span class="time" data-showtime="2026-10-29 16:40:32">10-29 16:40</span>'
                        '<article>'+TEXT+'</article>')
        self.assertIn('原始来源时点：2026-10-29 16:40:32',item.market_impact)
        self.assertIn('精度：day',item.market_impact)

    def test_recommendation_time_cannot_repair_missing_publication(self):
        with self.assertRaisesRegex(ValueError,'time_missing'):
            self.parse('<h1>公司披露三季度财务数据</h1><article>'+TEXT+'</article>'
                       '<aside><time datetime="2026-10-31T10:00:00+08:00">推荐</time></aside>')

    def test_missing_title_is_not_reported_as_short_body(self):
        with self.assertRaisesRegex(ValueError,'article_title_missing'):
            self.parse('<meta itemprop="datePublished" content="2026-10-30"><article>'+TEXT+'</article>')

    def test_missing_timezone_boundary_remains_rejected_for_narrow_window(self):
        html='<h1>公司最新披露与口径变化</h1><meta itemprop="datePublished" content="2026-10-29 23:32"><article>'+TEXT+'</article>'
        with self.assertRaisesRegex(ValueError,'day_window_boundary'):
            parse_visible_article(html,'https://publisher.example/news/item',NOW,72)
        self.assertIn('精度：day',self.parse(html).market_impact)


class PurposeAndSubjectTests(unittest.TestCase):
    def item(self,**changes):
        values=dict(id='B1',title='华能水电资产注入与三季报',content=TEXT+'长江电力作为同行对比。',
            source='公开网页可见正文-example',source_url='https://publisher.example/news/item',
            published_at=NOW-timedelta(hours=110))
        values.update(changes)
        return News(**values)

    def test_weekend_is_wider_but_workday_markets_keep_72_hours(self):
        self.assertEqual(policy(NOW)['hours']['latest_close'],96)
        self.assertEqual(policy(NOW)['hours']['company_event'],168)
        self.assertEqual(policy(datetime(2026,11,4,16))['hours']['latest_close'],72)

    def test_arbitrary_widening_is_rejected(self):
        value=window(NOW,'commentary');value['hours']=1000
        with self.assertRaisesRegex(ValueError,'source_window_invalid'):validate_window(value,NOW)

    def test_peer_mention_is_not_direct_company_subject(self):
        stock=SimpleNamespace(name='长江电力',code='600900')
        self.assertFalse(company_focus(self.item(),stock))
        self.assertTrue(company_focus(self.item(title='长江电力三季度财务变化'),stock))

    def test_ambiguous_title_can_use_an_explicit_issuer_lead(self):
        self.assertTrue(company_focus(self.item(title='本月经营数据与风险说明',content='长江电力 公告经营数据。'+TEXT),
                                      SimpleNamespace(name='长江电力',code='600900')))

    def test_explicit_ai_production_disclaimer_is_excluded(self):
        self.assertEqual(excluded_reason(self.item(content=TEXT+'免责声明：本文基于AI生产，仅供参考。')),
                         'disclosed_ai_generated_article')
        self.assertIsNone(excluded_reason(self.item(content=TEXT+'本文讨论AI产业链的生产能力。')))

    def test_background_window_survives_local_reads_but_not_market_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            item=self.item()
            workspace=EpisodeWorkspace([item],root=directory,now=NOW)
            receipts=[dict(request=dict(tool='read',candidate_id='S1',relation='industry'),result=dict(status='ok',
                material=workspace.read(item.id,characters=100),source_window=window(NOW,'commentary'),
                research_links=[dict(lane='us_market'),dict(lane='industry')])),
                dict(request=dict(tool='read_more'),result=workspace.read(item.id,offset=100,characters=200))]
            state=dict(receipts=receipts,candidates={},effective_search_limit=0)
            record=body_records(workspace,receipts)[item.id]
            self.assertTrue(record['eligible'])
            feedback=build_feedback(workspace,state,[],Limits())
            self.assertEqual(next(row for row in feedback['lanes'] if row['lane']=='us_market')['body_ids'],[])
            self.assertEqual(next(row for row in feedback['lanes'] if row['lane']=='industry')['body_ids'],[item.id])

    def test_background_window_survives_report_export_and_import(self):
        with tempfile.TemporaryDirectory() as directory:
            item=self.item()
            workspace=EpisodeWorkspace([item],root=directory,now=NOW)
            receipts=[dict(request=dict(tool='read',candidate_id='S1',relation='industry'),result=dict(status='ok',
                material=workspace.read(item.id,characters=6000),source_window=window(NOW,'commentary')))]
            state=dict(owner='finance-model-led-discovery-v1',status='partial_materials_for_human_review',
                started_at=NOW.isoformat(),time_policy=policy(NOW),watchlist=[],provided_ids=[item.id],candidates={},
                receipts=receipts,model_calls=3,search_tool_calls=0,body_url_calls=1,
                dossier=dict(action='finish',events=[dict(title='行业背景',why_it_matters='需要历史对照',
                    caveats='背景不是今日消息',evidence_ids=[item.id])],
                    coverage=[dict(lane=lane,status='missing',evidence_ids=[],explanation='仍缺主资料') for lane in LANES],
                    watchlist_checks=[],omissions=[]))
            value=export_discovery(workspace,state)
            news,context,preview=prepare(value,now=NOW)
            self.assertEqual(news[0].content,item.content)
            self.assertEqual(context['provenance'][0]['source_windows'],[window(NOW,'commentary')])
            self.assertFalse(preview['fresh_for_generation'])
            forged=deepcopy(value);forged['provenance'][0]['source_windows'][0]['hours']=999
            with self.assertRaisesRegex(ValueError,'source_window_invalid'):prepare(forged,now=NOW)
            legacy=deepcopy(value);legacy['time_policy']=None
            with self.assertRaisesRegex(ValueError,'time_policy_missing'):prepare(legacy,now=NOW)

    def test_old_receipt_without_a_window_keeps_original_72_hour_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            item=self.item();workspace=EpisodeWorkspace([item],root=directory,now=NOW)
            receipts=[dict(request=dict(tool='read'),result=dict(status='ok',material=workspace.read(item.id)))]
            self.assertFalse(body_records(workspace,receipts)[item.id]['eligible'])


class SavedFailureTests(unittest.TestCase):
    def test_parse_failure_keeps_capture_and_does_not_pause_or_refetch_url(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace=EpisodeWorkspace([],root=directory,now=NOW)
            url='https://publisher.example/news/item'
            with patch('app.services.web_research.ResearchHub',return_value=SimpleNamespace(root=Path(directory))), \
                 patch('app.services.web_research.ensure_active'), \
                 patch('app.services.web_research.record_failure') as failure, \
                 patch('app.services.web_research.fetch_html_once',return_value=(200,{'Content-Type':'text/html'},b'<article/>')) as fetch, \
                 patch('app.services.web_research.parse_visible_article',side_effect=ValueError('web_source_time_missing')):
                first=read_public(workspace,url)
                again=read_public(workspace,url)
            self.assertEqual(first['status'],'needs_local_review')
            self.assertTrue(first['response_capture'])
            self.assertTrue(again['reused_within_episode'])
            fetch.assert_called_once();failure.assert_not_called()

    def test_http_failure_still_pauses_and_is_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace=EpisodeWorkspace([],root=directory,now=NOW)
            with patch('app.services.web_research.ResearchHub',return_value=SimpleNamespace(root=Path(directory))), \
                 patch('app.services.web_research.ensure_active'), \
                 patch('app.services.web_research.record_failure') as failure, \
                 patch('app.services.web_research.fetch_html_once',side_effect=ValueError('public_http_403')) as fetch:
                first=read_public(workspace,'https://publisher.example/news/item')
                again=read_public(workspace,'https://publisher.example/news/item')
            self.assertEqual(first['reason'],'public_http_403')
            self.assertTrue(again['reused_within_episode'])
            failure.assert_called_once();fetch.assert_called_once()


class ControllerTests(unittest.IsolatedAsyncioTestCase):
    async def test_weekend_company_window_reaches_search_reader_and_feedback(self):
        stock=dict(market='A',code='600900',name='长江电力')
        scope='A:600900'
        search_request=dict(tool='search',lane='company_event',scope=scope,purpose='company_event',
                            query='长江电力 三季报与风险',reason='核对公司主体')
        read_request=dict(tool='read',candidate_id='S1',relation='direct',scope=scope,reason='阅读公司公告')
        finish=dict(action='finish',events=[],omissions=[],watchlist_checks=[dict(key=scope,
            status='body_provided',evidence_ids=['B1'],explanation='已读本公司旧公告，不是今日消息')],
            coverage=[dict(lane=lane,status='missing',evidence_ids=[],explanation='仍有缺口') for lane in LANES])
        with tempfile.TemporaryDirectory() as directory:
            workspace=EpisodeWorkspace([],root=directory,now=NOW)
            def body(ws,url,**kwargs):
                ws.add([News(id='B1',title='长江电力三季度财务变化',content=TEXT,
                    source='公开网页可见正文-example',source_url=url,published_at=NOW-timedelta(hours=110))])
                return dict(status='ok',material=ws.read('B1',characters=kwargs['characters']))
            reader=Mock(side_effect=body)
            search=Mock(return_value=dict(status='ok',results=[dict(title='长江电力三季度财务变化',
                snippet='经营风险',url='https://publisher.example/news/company')]))
            model=AsyncMock(side_effect=[json.dumps(dict(action='tools',requests=[search_request])),
                json.dumps(dict(action='tools',requests=[read_request])),json.dumps(finish)])
            state=await discover(workspace,[stock],limits=Limits(model_calls=3),model=model,search=search,read=reader)
        self.assertEqual(search.call_args.kwargs['hours'],168)
        self.assertEqual(reader.call_args.kwargs['hours'],168)
        self.assertTrue(state['collection_feedback']['bodies']['B1']['eligible'])
        self.assertEqual(state['collection_feedback']['watchlist'][0]['body_ids'],['B1'])
        self.assertEqual(state['receipts'][1]['result']['source_window'],window(NOW,'company_event'))
