from datetime import datetime
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from app.models.news import News
from app.services.episode_workspace import EpisodeWorkspace
from app.services.news_workspace_brief import catalogue,BEGIN
from app.services import model_gateway
from app.services.prompt_reading import input_characters

SPEC=importlib.util.spec_from_file_location('discovery_runner',Path(__file__).resolve().parents[2]/'tools/run_discovery_acceptance_v1.py')
m=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(m)

class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'data').mkdir();(self.root/'data/.automation-paused').write_text('paused')
        self.news=News(id='canonical-one',title='新事实',content='公司收入增长，成本也上升。'*100,
            source='财联社公开原文',source_url='https://www.cls.cn/detail/12345',published_at=datetime(2026,10,30,16))
        self.ws=EpisodeWorkspace([self.news],root=self.root/'data/episodes',now=datetime(2026,10,30,18))
        directory=catalogue([self.news],[]);self.ws.bind_catalogue(directory['references'])
        self.ref=next(iter(directory['references']))
        text=directory['text']+'\n[N:canonical-one]'+self.news.content
        self.ws.prepare_ranges(self.news.id,[(0,len(self.news.content))],'initial_news')
        self.route=SimpleNamespace(provider='ofox_anthropic',model='anthropic/claude-sonnet-5.5',base_url='https://api.ofox.io/v1',effort='none',api_key='PRIVATE_HEADER_KEY')
        self.gateway=SimpleNamespace(resolve_route=lambda task:self.route,request_for=model_gateway.request_for,
            completed_text=model_gateway.completed_text,service_error=model_gateway.service_error)
        self.packet=dict(messages=[dict(role='user',content=text)],input_characters=input_characters([dict(role='user',content=text)]),snapshot_collected_at='2026-10-30T17:09:16',
            route=dict(provider=self.route.provider,model=self.route.model,host='api.ofox.io',effort='none'))
        self.report='## 结论\n当前判断及依据[N:canonical-one]。\n```json\n{"title":"测试稿","decision_notes":[]}\n```'
        self.record=Mock(return_value={'input_tokens':10,'output_tokens':20})
        self.guard=Mock();self.posts=[]

    def tearDown(self):self.tmp.cleanup()

    def factory(self,replies):
        parent=self
        class Client:
            def __init__(self,**kwargs):self.kwargs=kwargs
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def post(self,url,**kwargs):
                parent.posts.append(kwargs)
                value=replies[len(parent.posts)-1]
                if isinstance(value,Exception):raise value
                if isinstance(value,str):value=dict(stop_reason='end_turn',content=[dict(type='text',text=value)])
                return SimpleNamespace(status_code=200,json=lambda:value)
        return Client

    def run_trial(self,replies):
        state=m.execute(self.root,self.packet,self.ws,self.gateway,self.factory(replies),self.record,self.guard)
        return json.loads(state.read_text()),state

    def test_single_report_and_repeat_marker_never_charge_again(self):
        result,state=self.run_trial([self.report])
        self.assertEqual(result['status'],'completed_for_human_review')
        self.assertEqual(result['http_requests'],1)
        self.assertEqual(result['offline_checks']['problems'],[])
        self.run_trial([RuntimeError('must not call')])
        self.assertEqual(len(self.posts),1)
        self.assertTrue(state.with_suffix('.started').exists())

    def test_catalogue_read_then_report_uses_two_requests_and_drops_directory(self):
        request=json.dumps(dict(action='request_evidence',requests=[dict(tool='read_material',id=self.ref,characters=100)]))
        result,state=self.run_trial([request,self.report])
        self.assertEqual(result['http_requests'],2)
        second=self.posts[1]['json']['messages'][0]['content']
        self.assertNotIn(BEGIN,second)
        self.assertIn('canonical-one',second)
        self.assertEqual(result['status'],'completed_for_human_review')
        self.assertEqual(len(self.ws.journal),1)

    def test_second_tool_request_stops_without_third_post(self):
        request=json.dumps(dict(action='request_evidence',requests=[dict(tool='search_materials',query='收入增长')]))
        result,state=self.run_trial([request,request,RuntimeError('must not call')])
        self.assertEqual(len(self.posts),2)
        self.assertEqual(result['status'],'failed_preserved')
        self.assertTrue((state.parent/(m.TRIAL+'.round2.response.json')).is_file())

    def test_transport_error_has_no_retry_and_does_not_record_sensitive_message(self):
        result,state=self.run_trial([ValueError('PRIVATE_HEADER_KEY')])
        self.assertEqual(result['status'],'failed_preserved')
        self.assertEqual(len(self.posts),1)
        self.assertNotIn('PRIVATE_HEADER_KEY',state.read_text())

    def test_truncation_preserves_visible_text_without_thinking_or_report(self):
        reply=dict(stop_reason='max_tokens',content=[dict(type='thinking',thinking='HIDDEN_THOUGHT'),dict(type='text',text='不完整的可见正文')])
        result,state=self.run_trial([reply])
        response=state.parent/(m.TRIAL+'.round1.response.json')
        saved=response.read_text(encoding='utf-8')
        self.assertIn('不完整的可见正文',saved)
        self.assertNotIn('HIDDEN_THOUGHT',saved)
        self.assertEqual(result['status'],'failed_preserved')
        self.assertEqual(len(self.posts),1)
        self.assertFalse((state.parent/(m.TRIAL+'.report.md')).exists())

    def test_tool_result_too_large_is_not_counted_as_delivered(self):
        self.ws.prepared={};self.ws.accessed={}
        self.news.content='收入增加。'*1500
        # Use a fresh workspace so its original-text fingerprint remains valid.
        ws=EpisodeWorkspace([self.news],root=self.root/'budget',now=datetime(2026,10,30,18))
        initial='固定正文。'*19000
        result=m.dispatch(ws,[dict(tool='read_material',id=self.news.id,characters=6000)],initial)
        self.assertEqual(result[0]['result']['status'],'not_provided_input_budget')
        self.assertEqual(ws.usage()['prepared_sources'],0)
        self.assertEqual(ws.accessed,{})

    def test_changed_route_stops_before_marker_or_post(self):
        self.route.model='different-model'
        with self.assertRaisesRegex(RuntimeError,'路由'):
            self.run_trial([self.report])
        self.assertEqual(self.posts,[])
        self.assertFalse((self.root/'data/diagnostics/discovery-acceptance'/(m.TRIAL+'.started')).exists())

    def test_workspace_rebuild_marks_only_exact_frozen_news_and_research_ranges(self):
        from app.services.research_hub import Material
        material=Material(id='research-one',title='研究材料',source='原始研究',source_url='https://www.cls.cn/detail/54321',
            kind='financial_baseline',scope='A:123456',body='公司盈利与现金流的研究正文。'*20,
            published_at=datetime(2026,10,29),collected_at='2026-10-30T17:00:00',period='2026Q3')
        folder=self.root/'data/radar';folder.mkdir()
        row=dict(id=self.news.id,title=self.news.title,content=self.news.content,source=self.news.source,
            url=self.news.source_url,published=self.news.published_at.isoformat())
        snapshot=dict(full_collection=True,selection=dict(articles=[dict(id=self.news.id)]),raw_articles=[row])
        replay=dict(selection=dict(initial_reading=[dict(id=self.news.id,ranges=[[0,30]])]))
        (folder/'news-acceptance.json').write_text(json.dumps(snapshot),encoding='utf-8')
        (folder/'selection-replay.json').write_text(json.dumps(replay),encoding='utf-8')
        self.packet.update(watchlist=[dict(code='123456',name='新公司',market='A')],research_pool=1,
            catalogue_refs={self.ref:self.news.id},research_reading=[dict(id=material.id,ranges=[[0,40]])])
        self.packet['messages'][0]['content']+='\n'+material.body[:40]
        with patch('app.services.research_hub.ResearchHub.evidence_pool',return_value=[material]):
            ws=m.workspace_for(self.root,self.packet)
        self.assertEqual(ws.usage()['prepared_sources'],2)
        self.assertEqual(ws.usage()['confirmed_sources'],0)
        self.assertEqual(ws.read(self.ref,characters=80)['id'],self.news.id)
