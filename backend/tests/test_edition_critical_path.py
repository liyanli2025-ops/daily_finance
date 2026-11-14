"""Network-denied acceptance. Only external transports/DB identity are substituted.

Captured supplier pages are real; model replies below are controlled protocol
fixtures, not independent editorial judgments or a certification of daily news.
"""
import asyncio
from contextlib import ExitStack
import copy
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import zipfile

import httpx
import requests
from pydantic import SecretStr
from app import edition_once as entry
from app.config import settings
from app.services import edition_pipeline as core, edition_contract as contract
from app.services import edition_agenda_resume as resume, edition_release_gate as gate
from app.services import model_gateway as gateway, model_usage, research_hub, podcast_script_cache
from app.services.daily_changes import coverage, audit_agenda
from app.services.edition_issuer_desk import BODY_URL
from app.services.episode_workspace import EpisodeWorkspace
from test_edition_manual import PRICES
from test_unified_edition import fixtures, state as empty_state

FIX = Path(__file__).parent/'fixtures'
EVIDENCE = dict(owner=gate.OWNER, network_connections=0, paid_provider_requests=0, cases={})
RAW_TEXT = ''.join(json.loads((FIX/n).read_text())['data']['notice_content'] for n in
    ('issuer_three_page_first.json','issuer_three_page_2.json','issuer_three_page_3.json')).strip()
QUOTE = '69,964,683'
CONDITION = '若后续披露修正这笔金额，就撤回本期关于该金额的判断。'


class Harness:
    def __init__(self, root, fault=None):
        self.root=Path(root);self.fault=fault;self.stack=ExitStack();self.model_calls=[];self.get_calls=[]
        self.saved_zip=zipfile.ZipFile(FIX/'v45_trial_replay.zip')
        self.original=json.loads(self.saved_zip.read('result.json'))
        self.now=datetime.fromisoformat(self.original['cutoff'])
        self.captures={}
        for r in self.original['issuer_http_receipts']:
            if r.get('status')=='received':
                names=[n for n in self.saved_zip.namelist() if n.endswith('/issuer-responses/'+r['capture'])]
                self.captures[json.dumps([r['url'],r['parameters']],sort_keys=True)] = self.saved_zip.read(names[0])
        original=settings.model_copy(update=dict(ai_provider='compatible',openai_api_key='offline-placeholder',
            openai_base_url='https://api.ofox.io/v1',ai_model='anthropic/claude-sonnet-5.5',
            analysis_provider=None,analysis_model=None,review_provider=None,review_model=None,
            research_web_search_api_key=SecretStr('offline-placeholder'),model_http_retries=0,
            report_auto_repair_enabled=False,research_max_seconds=900))
        self.config=entry.accepted_config(PRICES,'1',original)
        self.pause=self.root/'pause';self.pause.touch()

    def __enter__(self):
        self.stack.enter_context(patch.object(gateway,'MODEL_PAUSE_FILE',self.pause))
        self.stack.enter_context(patch.object(entry,'MODEL_PAUSE_FILE',self.pause))
        self.stack.enter_context(patch.object(core,'MODEL_PAUSE_FILE',self.pause))
        self.stack.enter_context(patch.object(core,'ROOT',self.root/'locks'))
        self.stack.enter_context(patch.object(research_hub,'ROOT',self.root/'research'))
        self.stack.enter_context(patch.object(model_usage,'ROOT',self.root/'usage'))
        self.stack.enter_context(patch.object(podcast_script_cache,'ROOT',self.root/'scripts'))
        for module in (entry,core):self.stack.enter_context(patch.object(module,'china_now',return_value=self.now))
        self.stack.enter_context(patch('app.services.edition_market.china_now',return_value=self.now))
        self.stack.enter_context(patch.object(entry,'assert_watchlist_current',AsyncMock()))
        self.stack.enter_context(patch('app.services.watchlist_repository.assert_watchlist_current',AsyncMock()))
        self.stack.enter_context(patch('requests.get',side_effect=self.get))
        self.stack.enter_context(patch('app.services.web_research.fetch_html_once',side_effect=ValueError('public_http_403')))
        owner=self
        class Client:
            def __init__(self,**kwargs):pass
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def post(self,url,headers,json):return owner.post(url,json)
        self.stack.enter_context(patch.object(gateway.httpx,'AsyncClient',Client))
        return self

    def __exit__(self,*args):
        self.stack.close();self.saved_zip.close()

    def get(self,url,params=None,**kwargs):
        self.get_calls.append((url,copy.deepcopy(params)))
        raw=self.captures.get(json.dumps([url,params],sort_keys=True))
        if url==BODY_URL and self.fault=='interrupted_read':raise asyncio.CancelledError()
        if url==BODY_URL and params['art_code']=='AN202611121831664865' and self.fault!='no_body':
            name={1:'issuer_three_page_first.json',2:'issuer_three_page_2.json',3:'issuer_three_page_3.json'}[params['page_index']]
            raw=(FIX/name).read_bytes()
        # Other selected articles are deliberately unavailable in this fault
        # scenario. An absence is never manufactured into a successful source.
        if url==BODY_URL and (self.fault=='no_body' or params['art_code']!='AN202611121831664865'):raw=None
        response=requests.Response();response.status_code=200 if raw is not None else 404
        response.url=url;response.raw=io.BytesIO(raw or b'');return response

    def post(self,url,body):
        stage=model_usage._run.get()['phase'];self.model_calls.append(stage)
        if self.fault=='model_402' and stage=='assessment':
            return httpx.Response(402,json={'error':{'message':'offline insufficient balance'}},request=httpx.Request('POST',url))
        if stage=='agenda':value=self.agenda()
        elif stage in {'assessment','patch_assessment'}:value=self.assessment()
        elif stage=='writing':value=self.writing()
        elif stage=='review':value=self.review()
        else:raise AssertionError(stage)
        if stage in {'assessment','writing','review'}:
            # Verify real gateway input contains the actual supplier amount.
            assert QUOTE in json.dumps(body,ensure_ascii=False)
        return httpx.Response(200,json=dict(content=[dict(type='text',text=json.dumps(value,ensure_ascii=False))],
            stop_reason='end_turn',usage=dict(input_tokens=1000,output_tokens=800,
                cache_read_input_tokens=0,cache_creation_input_tokens=0)),request=httpx.Request('POST',url))

    def agenda(self):
        cid=next(cid for cid,c in self.s['candidates'].items()
            if c.get('issuer_document',{}).get('art_code')=='AN202611121831664865')
        return dict(events=[dict(id='E1',title='宁德时代已披露的股份变动记录',importance='major',
            lane='company_event',purpose='company_event',scope='A:300750',reason='离线流程样本，仅验证披露金额与限制',
            candidate_ids=[cid],read_ids=[cid])],excluded_candidates=[dict(candidate_ids=[i],
            reason='本控制样本仅验证一个公告的处理，不作其他事件重要性判断') for i in self.s['candidates'] if i!=cid])

    def assessment(self):
        s=self.s;events=s['agenda']['events'];rows=[]
        for e in events:
            source=next((v for v in s['sources'].values() if e['id'] in v['event_ids']
                and v.get('candidate_id') and QUOTE in v['text']),None)
            if source and not self.fault=='invalid_quote':
                rows.append(dict(id=e['id'],status='ready',reason='实际已提供供应商公告文本，镜像尚未独立核原件',
                    evidence=[dict(source_id=source['id'],quote=QUOTE)]))
            elif source:
                rows.append(dict(id=e['id'],status='ready',reason='本测试故意提供错误引文',
                    evidence=[dict(source_id=source['id'],quote='原文里没有的金额999999999999')]))
            else:rows.append(dict(id=e['id'],status='missing' if e['importance']=='major' else 'excluded',
                reason='当前离线情景没有取得适用正文，不能认定该线索成立'))
        value=dict(events=rows,missed_major_events=[],additional_searches=[],additional_reads=[],
            watchlist_checks=[dict(key=r['market']+':'+r['code'],status='no_material_event',
                reason='仅记录本次有限检索，不代表公司没有事件') for r in s['watchlist']],
            change_checks=[dict(task_id=r['id'],status='screened_no_material_event' if r['discovery']=='checked' else 'missing',
                reason='控制样本的有限检索边界，不作全网无事件判断') for r in coverage(s)])
        value['change_topic_checks']=[dict(candidate_id=r['candidate_id'],topic=r['topic'],status='missing',
            reason='该'+r['topic']+'线索尚无适用正文证实，保留具体缺口') for r in s.get('change_topic_pending',[])]
        return value

    def writing(self):
        source=next(v for v in self.s['sources'].values() if QUOTE in v['text']);sid=source['id']
        _,written,_,_=fixtures()
        fact='宁德时代披露镜像中列有金额69,964,683；单位和表格口径仍须对照原件。'
        opinion='披露金额不能直接证明股价获得支撑。'
        company_lines=[r['name']+'：本样本不足以形成今日经营结论，待核后续原始披露。' for r in self.s['watchlist']]
        written.update(title='公告处理离线样本',summary='用于软件流程验收，不能当真实日报',
            body=fact+'[N:'+sid+']'+opinion+CONDITION+'\n'+'\n'.join(company_lines),
            script=fact+opinion+CONDITION,core_opinions=[opinion],
            source_checks=[dict(source_id=sid,source_quote=QUOTE,report_quote=fact)],
            event_coverage=[dict(event_id='E1',quote=fact)],script_event_coverage=[dict(event_id='E1',quote=fact)],
            programme=dict(mainline=opinion,choices=[dict(topic='披露与结论边界',editorial_reason='避免金额到价格的跳步',
                report_quotes=[fact])],omitted=[]),
            listener_cards=[dict(judgment=opinion,source_id=sid,fact_quote=QUOTE,report_quote=opinion,
                mechanism='金额到股价的影响尚无证据，不作因果判断',alternative='股价也可能受市场因素影响，未核实',
                horizon='本期公告核对期间',invalidation=CONDITION)],
            stock_followups=[dict(key=r['market']+':'+r['code'],status='insufficient',source_ids=[],
                reason='本控制样本不认证完整公司研究',report_quote=company_lines[n],variables=['后续原始披露'],
                next_check='下一次披露时间未确定，不推定日期') for n,r in enumerate(self.s['watchlist'])])
        return written

    def review(self):
        written=self.s['draft'];fact=written['source_checks'][0]['report_quote'];sid=written['source_checks'][0]['source_id']
        _,_,_,reviewed=fixtures()
        reviewed.update(source_checks=[dict(source_id=sid,source_quote=QUOTE,report_quote=fact,status='supported')],
            agenda_checks=[dict(event_id='E1',status='covered',report_quote=fact,script_quote=fact)],
            spoken_review=dict(passed=True,issues=[],checks=[dict(facet=f,status='preserved',report_quote=fact,
                script_quote=fact,reason='控制样本保留来源及限制') for f in ('facts','judgment','qualifiers')]),
            listener_checks=[dict(criterion=f,status='supported',report_quote=CONDITION,script_quote=CONDITION,
                reason='离线协议样本，不是真实独立研究结论') for f in
                ('evidence','causality','company_relevance','time_and_units','countercase_and_falsifier')])
        return reviewed

    def fresh(self):
        s=empty_state();s.update(id='edition-'+'d'*32,cutoff=self.now.isoformat(),watchlist=self.original['watchlist'],
            research_protocol='listener_research_v1',change_protocol='daily_changes_v1',app_written=False)
        s['policy']=core.environment(s['watchlist'],'morning',self.config)[0]
        folder=self.root/'fresh';folder.mkdir();ws=EpisodeWorkspace(root=folder/'evidence',now=self.now)
        def search(workspace,*args,**kwargs):
            workspace.web_search_attempts=getattr(workspace,'web_search_attempts',0)+1
            return dict(status='ok',results=[],limitation='控制样本空检索响应，不认证覆盖')
        self.s=s;self.pipeline=core.EditionPipeline(s,folder,ws,search=search,check=AsyncMock())
        return s,self.pipeline

    def export_case(self,name,**extra):
        EVIDENCE['cases'][name]=dict(outcome=gate.CASES[name],assertions_passed=True,**extra)


class CriticalPath(unittest.IsolatedAsyncioTestCase):
    async def normal(self,fault=None):
        root=tempfile.TemporaryDirectory();self.addCleanup(root.cleanup)
        h=Harness(root.name,fault);h.__enter__();self.addCleanup(h.__exit__,None,None,None)
        s,p=h.fresh()
        with entry.manual_text_scope(s['id'],h.config):
            try:await p.execute()
            except (Exception,asyncio.CancelledError) as error:self.error=error
        return h,s,p

    async def test_complete_actual_selection_parsing_gateway_and_editorial_path(self):
        h,s,p=await self.normal()
        self.assertEqual(s['status'],'reviewed_text',str(getattr(self,'error',None)))
        self.assertEqual(h.model_calls,['agenda','assessment','writing','review'])
        source=next(v for v in s['sources'].values() if QUOTE in v['text'])
        self.assertEqual(source['text'],RAW_TEXT);self.assertEqual(len(source['text']),10318)
        self.assertEqual([r[1]['page_index'] for r in h.get_calls if r[0]==BODY_URL],[1,2,3])
        self.assertEqual(s['flow_trace'],['agenda']+gate.REQUIRED_FLOW)
        self.assertTrue((p.path/'response-4.json').is_file());self.assertTrue(s['report']['content'])
        self.assertFalse(s['app_written']);self.assertFalse(s.get('tts_attempts'))
        self.assertEqual(s['model_http_attempts'],4)
        h.export_case('issuer_full_path',flow=s['flow_trace'][1:],model_http_attempts=4,issuer_text_pages=3,
            body_characters=len(source['text']),original_text_sha256=hashlib.sha256(source['text'].encode()).hexdigest(),
            app_written=False,tts_requests=0)

    async def test_no_body_stops_before_assessment(self):
        h,s,p=await self.normal('no_body')
        self.assertEqual(s['status'],'partial_materials');self.assertEqual(h.model_calls,['agenda'])
        self.assertNotIn('draft',s);h.export_case('no_body')

    async def test_402_preserves_body_and_reservation_without_retry(self):
        h,s,p=await self.normal('model_402')
        self.assertEqual(s['status'],'failed');self.assertEqual(s['error_http_status'],402)
        self.assertEqual(h.model_calls,['agenda','assessment']);self.assertIn(QUOTE,json.dumps(s['sources']))
        self.assertEqual(len([r for r in s['reservations'] if r['kind']=='model']),2)
        self.assertNotIn('draft',s);h.export_case('model_402')

    async def test_invalid_quote_does_not_reach_writing(self):
        h,s,p=await self.normal('invalid_quote')
        self.assertEqual(s['status'],'partial_materials',str(getattr(self,'error',None)))
        self.assertEqual(h.model_calls,['agenda','assessment']);self.assertTrue(s['missing']);h.export_case('invalid_quote')

    async def test_interrupted_read_is_saved_and_not_published(self):
        h,s,p=await self.normal('interrupted_read')
        self.assertEqual(s['status'],'interrupted');self.assertEqual(s['phase'],'reading')
        self.assertEqual(h.model_calls,['agenda']);self.assertNotIn('draft',s);h.export_case('interrupted_read')

    async def test_input_limit_checked_before_model_http(self):
        with tempfile.TemporaryDirectory() as root,Harness(root) as h:
            s,p=h.fresh();s['policy']['max_input_characters']=10
            with entry.manual_text_scope(s['id'],h.config),self.assertRaises(Exception):
                await p.execute()
            self.assertEqual(s['status'],'failed');self.assertEqual(h.model_calls,[])
            self.assertNotIn('draft',s);h.export_case('oversized_input')

    async def test_disk_failure_prevents_provider_request(self):
        with tempfile.TemporaryDirectory() as root,Harness(root) as h:
            s,p=h.fresh();p.save()
            with entry.manual_text_scope(s['id'],h.config),patch.object(core,'save_json',side_effect=OSError('disk full')):
                with self.assertRaises(OSError):await p.call('agenda',contract.AGENDA,p.packet('agenda'))
            self.assertEqual(h.model_calls,[]);self.assertEqual(s.get('model_http_attempts',0),0)
            h.export_case('persistence_failure')

    async def test_real_failed_trial_continues_same_budget_and_stops_at_real_gaps(self):
        with tempfile.TemporaryDirectory() as root,Harness(root) as h:
            trial=Path(root)/'old';trial.mkdir();h.saved_zip.extractall(trial)
            identifier=h.original['id'];original_dir=trial/identifier;original_dir.mkdir()
            # Recreate exact server-relative layout; no original result alteration.
            for name in ('result.json','response-1.json','evidence'):(trial/name).rename(original_dir/name)
            before=(original_dir/'result.json').read_bytes()
            pstate,pending,proof,*_=resume.load_original(original_dir)
            self.assertIn(('S30','选举'),[(r['candidate_id'],r['topic']) for r in pending])
            items,_=resume.background_pool(original_dir,pstate)
            self.assertEqual(len(items),4)
            # Watchlist/model identity are local configuration boundaries; the
            # ledger, saved HTML, article readers and model gateway are real.
            h.s=pstate
            planned,prepared,_,_=await resume.preview(h.config,identifier,root=trial)
            self.assertTrue(planned['ready_to_run'],planned['blockers'])
            h.s=prepared
            # Transport replies need the actual child state, not a separate copy.
            original_post=h.post
            def child_post(url,body):
                h.s=json.loads((original_dir/resume.CHILD/'result.json').read_text())
                return original_post(url,body)
            with patch.object(h,'post',side_effect=child_post),patch.object(gate,'require_acceptance',return_value={'offline_test':True}):
                result,path,reused=await resume.continue_once(h.config,identifier,root=trial,run=True,input_sha=planned['input_sha256'])
            self.assertFalse(reused);self.assertEqual(result['status'],'partial_materials',result.get('error_code'))
            self.assertEqual(result['search_http_attempts'],16);self.assertEqual(result['model_http_attempts'],2)
            self.assertEqual(h.model_calls,['assessment']);self.assertNotIn('draft',result)
            self.assertIn('topic:S30:选举',result['missing']);self.assertEqual(result['cutoff'],h.original['cutoff'])
            self.assertEqual(result['reservations'][:len(h.original['reservations'])],h.original['reservations'])
            self.assertEqual((original_dir/'result.json').read_bytes(),before)
            self.assertEqual(result['agenda_continuation']['background_records_restored'],4)
            self.assertIn(QUOTE,json.dumps(result['sources']))
            calls=(len(h.model_calls),len(h.get_calls))
            again,again_path,reused=await resume.continue_once(h.config,identifier,root=trial,run=True,input_sha='ignored')
            self.assertTrue(reused);self.assertEqual(again,result);self.assertEqual(calls,(len(h.model_calls),len(h.get_calls)))
            h.export_case('real_v45_partial',old_public_requests=113,old_search_requests=16,
                old_model_requests=1,original_files_unchanged=True,background_records_restored=4)
            h.export_case('missing_concrete_topic',missing='topic:S30:选举',writing_started=False)

    async def test_failed_actual_continuation_cannot_be_purchased_again(self):
        with tempfile.TemporaryDirectory() as root,Harness(root,'model_402') as h:
            trial=Path(root)/'trials';trial.mkdir()
            original_dir=trial/h.original['id'];original_dir.mkdir()
            h.saved_zip.extractall(original_dir)
            planned,prepared,_,_=await resume.preview(h.config,h.original['id'],root=trial)
            self.assertTrue(planned['ready_to_run'],planned['blockers'])
            h.s=prepared
            with patch.object(gate,'require_acceptance',return_value={'offline_test':True}):
                result,path,reused=await resume.continue_once(h.config,h.original['id'],root=trial,
                    run=True,input_sha=planned['input_sha256'])
            self.assertEqual(result['status'],'failed');self.assertEqual(h.model_calls,['assessment'])
            self.assertEqual(result['usage'][-1]['http_status'],402)
            calls=(len(h.model_calls),len(h.get_calls))
            again,_,reused=await resume.continue_once(h.config,h.original['id'],root=trial,run=True,input_sha='unused')
            self.assertTrue(reused);self.assertEqual(again,result)
            self.assertEqual(calls,(len(h.model_calls),len(h.get_calls)))
            h.export_case('repeat_failed_run',no_new_requests=True,failure_http_status=402)

    def test_gate_rejects_missing_case_wrong_code_and_missing_receipt(self):
        with self.assertRaises(ValueError):gate.validate_evidence(None)
        with self.assertRaises(ValueError):gate.validate_evidence(dict(owner=gate.OWNER,cases={}))
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'receipt.json'
            with self.assertRaisesRegex(ValueError,'missing'):gate.require_acceptance(p)
            p.write_text(json.dumps(dict(source_signature='wrong')))
            with self.assertRaisesRegex(ValueError,'stale'):gate.require_acceptance(p)


class SavedInputCapacity(unittest.IsolatedAsyncioTestCase):
    def source(self, root):
        directory=Path(root)/'v47';directory.mkdir()
        with zipfile.ZipFile(FIX/'v47_input_failure.zip') as z:z.extractall(directory)
        return directory,json.loads((directory/'result.json').read_text())

    def test_real_multiple_whole_bodies_and_every_headline_fit_existing_limit(self):
        from app.services.edition_inputs import assemble_request,messages_for,edition_forecast
        from app.services.edition_request_view import candidates_from
        from app.services.edition_budget import search_batch_plan
        with tempfile.TemporaryDirectory() as root:
            directory,s=self.source(root);before=copy.deepcopy(s)
            now=datetime.fromisoformat(s['cutoff']);value=core.packet(s,'assessment')
            selected,messages,capacity=assemble_request('assessment',contract.ASSESS,value,now,'morning',65000)
            self.assertGreater(capacity['original_characters'],85002)
            self.assertLessEqual(capacity['request_characters'],65000)
            self.assertTrue(capacity['candidate_index_used'])
            from app.services.edition_evidence_view import view
            self.assertEqual(selected['sources'],{sid:view(s) for sid,s in value['sources'].items()})
            original=candidates_from(value);indexed=candidates_from(selected)
            self.assertEqual(len(original),65);self.assertEqual(set(original),set(indexed))
            for cid,row in original.items():
                for key in ('title','published','scope','issuer_document','baseline_document','warning'):
                    if key in row:self.assertEqual(indexed[cid][key],row[key],(cid,key))
                self.assertNotIn('snippet',indexed[cid]) if 'snippet' not in row else self.assertIsNone(indexed[cid]['snippet'])
            for name,columns in selected.get('record_columns',{}).items():
                unpacked=[dict(zip(columns[:-1],r[:-1]),**r[-1]) for r in selected[name]]
                self.assertEqual(unpacked,value[name])
            self.assertEqual(s,before)
            plan=search_batch_plan(s['policy'],edition_forecast(s,now),0,s['reservations'])
            self.assertTrue(plan['fits_money'],plan);self.assertEqual(plan['limit_usd'],'1')
            self.assertTrue(all(r.get('fits_known_input',True) for r in plan['model_stages']))

    async def test_real_saved_bodies_pass_gateway_without_rebuying_selection_or_pages(self):
        from app.services import edition_input_resume as stored
        with tempfile.TemporaryDirectory() as root,Harness(root) as h:
            directory,old=self.source(root);before={str(p.relative_to(directory)):p.read_bytes() for p in directory.rglob('*') if p.is_file()}
            plan,_,_,_=await stored.preview(h.config,directory)
            self.assertTrue(plan['ready_to_run'],plan['blockers'])
            self.assertEqual(plan['retained_article_bodies'],5)
            original_post=h.post
            def child_post(url,body):
                h.s=json.loads((directory/stored.CHILD/'result.json').read_text())
                content=body['messages'][-1]['content']
                if isinstance(content,list):content=next(r['text'] for r in content if r['type']=='text')
                actual=json.loads(content)
                from app.services.edition_evidence_view import view
                for sid,source in old['sources'].items():self.assertEqual(actual['sources'][sid]['text'],view(source)['text'])
                return original_post(url,body)
            with patch.object(h,'post',side_effect=child_post),patch.object(gate,'require_acceptance',return_value={'offline_test':True}):
                result,path,reused=await stored.continue_once(h.config,directory,run=True,input_sha=plan['input_sha256'])
            self.assertFalse(reused);self.assertEqual(result['status'],'partial_materials',result.get('error_code'))
            self.assertEqual(h.model_calls,['assessment']);self.assertEqual(h.get_calls,[])
            self.assertEqual(result['model_http_attempts'],2);self.assertEqual(result['search_http_attempts'],16)
            self.assertEqual(result['public_fetch_attempts'],127);self.assertEqual(result['cutoff'],old['cutoff'])
            self.assertEqual(result['sources'],old['sources']);self.assertEqual(result['reservations'][:-1],old['reservations'])
            self.assertEqual(result['policy'],old['policy']);self.assertIn('topic:S30:选举',result['missing'])
            self.assertNotIn('draft',result);self.assertFalse(result.get('app_written'));self.assertFalse(result.get('tts_attempts'))
            for name,data in before.items():self.assertEqual((directory/name).read_bytes(),data)
            again,_,reused=await stored.continue_once(h.config,directory,run=True,input_sha='ignored')
            self.assertTrue(reused);self.assertEqual(again,result);self.assertEqual(h.model_calls,['assessment']);self.assertEqual(h.get_calls,[])
            h.export_case('real_v47_input',original_characters=plan['capacity']['original_characters'],
                request_characters=result['request_capacity'][-1]['request_characters'],input_limit=65000,
                article_bodies=5,candidate_titles=65,original_sources_unchanged=True,
                new_model_requests=1,new_search_requests=0,new_public_requests=0,old_public_requests=127,
                estimated_limit_usd='1',missing_election_preserved=True)

    async def test_changed_body_or_capture_stops_before_marker_or_request(self):
        from app.services import edition_input_resume as stored
        with tempfile.TemporaryDirectory() as root,Harness(root) as h:
            directory,s=self.source(root)
            pool=next(directory.glob('evidence/episode-*/materials.json'));raw=pool.read_text();rows=json.loads(raw)
            article=next(r for r in rows if r['id'] in s['sources']);article['text']+='改'
            pool.write_text(json.dumps(rows,ensure_ascii=False))
            with self.assertRaisesRegex(ValueError,'body_changed'):await stored.preview(h.config,directory)
            pool.write_text(raw)
            body=next(directory.glob('evidence/episode-*/public-responses/*.body'));body.write_bytes(body.read_bytes()+b'changed')
            with self.assertRaisesRegex(ValueError,'capture_changed'):await stored.preview(h.config,directory)
            self.assertFalse((directory/stored.CHILD).exists());self.assertEqual(h.model_calls,[]);self.assertEqual(h.get_calls,[])

    async def test_free_preview_uses_actual_capacity_without_marking_or_modifying_history(self):
        from app.services import edition_input_resume as stored
        with tempfile.TemporaryDirectory() as root,Harness(root) as h:
            directory,s=self.source(root);raw=(directory/'result.json').read_bytes()
            plan,path,reused=await stored.continue_once(h.config,directory)
            self.assertTrue(plan['ready_to_run']);self.assertIsNone(path)
            self.assertEqual(plan['prior_public_fetch_attempts'],127)
            self.assertEqual((directory/'result.json').read_bytes(),raw)
            self.assertFalse((directory/stored.CHILD).exists());self.assertEqual(h.model_calls,[]);self.assertEqual(h.get_calls,[])

    async def test_capacity_error_names_violated_dimension_before_http(self):
        with tempfile.TemporaryDirectory() as root,Harness(root) as h:
            s,p=h.fresh();s['policy']['max_input_characters']=10
            with entry.manual_text_scope(s['id'],h.config),self.assertRaisesRegex(ValueError,'edition_model_budget_exhausted'):
                await p.call('agenda',contract.AGENDA,p.packet('agenda'))
            self.assertIn('request_input_characters',s['budget_block']['dimensions'])
            self.assertFalse(s['budget_block']['model_http_started']);self.assertEqual(h.model_calls,[])

    async def test_impossible_whole_body_is_blocked_in_free_preview(self):
        from app.services import edition_input_resume as stored
        with tempfile.TemporaryDirectory() as root,Harness(root) as h:
            directory,s=self.source(root);pool=next(directory.glob('evidence/episode-*/materials.json'))
            rows=json.loads(pool.read_text());source=next(v for v in s['sources'].values() if v.get('metadata',{}).get('kind')=='primary_notice')
            source['text']+='\n不得静默截取的正文'*12000
            for row in rows:
                if row['id']==source['id']:row.update(text=source['text'],characters=len(source['text']))
            pool.write_text(json.dumps(rows,ensure_ascii=False));(directory/'result.json').write_text(json.dumps(s,ensure_ascii=False))
            plan,path,_=await stored.continue_once(h.config,directory)
            self.assertFalse(plan['ready_to_run']);self.assertIn('edition_input_capacity_exhausted',plan['blockers'])
            self.assertIsNone(path);self.assertFalse((directory/stored.CHILD).exists())
            self.assertEqual(h.model_calls,[]);self.assertEqual(h.get_calls,[])

    async def test_known_future_input_stop_precedes_current_paid_request(self):
        from app.services.edition_inputs import edition_forecast
        with tempfile.TemporaryDirectory() as root,Harness(root) as h:
            s,p=h.fresh();rows=edition_forecast(s,h.now)
            writing=next(r for r in rows if r['stage']=='writing')
            writing.update(known_input_characters=65001,fits_known_input=False)
            p.budget.forecast=lambda:rows
            with entry.manual_text_scope(s['id'],h.config),self.assertRaisesRegex(ValueError,'edition_future_input_capacity_exhausted'):
                await p.call('agenda',contract.AGENDA,p.packet('agenda'))
            self.assertEqual(s['budget_block']['stage'],'writing');self.assertEqual(h.model_calls,[])


class EvidenceScreening(unittest.TestCase):
    def source(self, text, **kw):
        return dict(id='news',text=text,title='公司新闻',url='https://example.org/news',
                    event_ids=['E1'],metadata={'kind':'news'},**kw)

    def real(self):
        with zipfile.ZipFile(FIX/'v47_input_failure.zip') as z:
            return json.loads(z.read('result.json'))

    def test_real_five_bodies_noise_roles_quotes_and_disclosures(self):
        from app.services.edition_evidence_view import audit,view,assert_quote
        s=self.real();before=copy.deepcopy(s);summary=audit(s['sources'])
        self.assertEqual(summary['original_article_characters'],27760)
        self.assertEqual(len(summary['pending_verification']),2)
        self.assertEqual(len(summary['commentary']),1)
        self.assertGreater(summary['removed_characters'],1500)
        for sid in ('4dc80ed6482b30c70c799d3b','4acc823141b6262043010e36'):
            self.assertEqual(view(s['sources'][sid]),s['sources'][sid])
        kitco=s['sources']['web-13cc240830ffa2ac810b4bc9'];clean=view(kitco)
        self.assertNotIn('Look first, then leap.',clean['text']);self.assertIn('Disclaimer:',clean['text'])
        self.assertIn('Peter Schiff',clean['text']);self.assertIn('If',clean['text'])
        for sid in summary['pending_verification']:
            source=s['sources'][sid]
            with self.assertRaisesRegex(ValueError,'requires_confirmation'):
                assert_quote(source,source['text'][:50],'discovery')
        with self.assertRaisesRegex(ValueError,'commentary_not_factual'):
            assert_quote(kitco,'A Democratic majority in Congress','discovery')
        assert_quote(kitco,'A Democratic majority in Congress','commentary')
        self.assertEqual(s,before)
        EVIDENCE['cases']['real_evidence_screening']=dict(outcome='cleaned_with_verification_gaps',assertions_passed=True,
            article_bodies=5,removed_characters=summary['removed_characters'],pending_verification=2,commentary=1,
            issuer_bodies_unchanged=True,unsafe_quotes_blocked=True)

    def test_quoted_promotion_and_advertising_reporting_are_kept(self):
        from app.services.edition_evidence_view import view
        t='监管调查广告投放。\n“Advertisements”是页面中的广告标签。\n报道称：“It is time to seize this price opportunity and invest in gold.”\n公司否认宣传，客户要求退款。'
        s=self.source(t);self.assertEqual(view(s),s)

    def test_generic_english_news_and_ipo_reporting_are_not_blacklisted(self):
        from app.services.edition_evidence_view import screen,view
        s=self.source('The company filed an IPO prospectus on Friday. Revenue fell 5%.\nIts rival disputed the forecast. If demand falls, margins may decline.')
        self.assertEqual(screen(s)['use'],'evidence_candidate');self.assertEqual(view(s),s)

    def test_no_hardcoded_domains_ids_dates_or_company_names(self):
        from app.services.edition_evidence_view import screen
        s=self.source('A founder resignation was reported. An interim CEO is in place. An IPO may follow.')
        self.assertEqual(screen(s)['use'],'pending_verification')
        s['text']='法院裁定融资案不成立。管理层否认遭调查。'
        self.assertEqual(screen(s)['use'],'evidence_candidate')

    def test_unknown_layout_falls_back_to_whole_body_and_capacity_guard(self):
        from app.services.edition_evidence_view import view
        s=self.source('Read also\n:\nA contrary view of company pricing\nDisclaimer:\nNot investment advice.\nTradingView is named in the report.')
        self.assertEqual(view(s),s)

    def test_disclosure_table_units_negations_restrictions_and_footnotes_are_whole(self):
        from app.services.edition_evidence_view import view
        s=self.source('单周\n最近两日\n币种 CNY\nA股 290900 69964683\nAdvertisements\n注：未注销；拟于30日后行动，受监管许可条件限制。')
        s['metadata']['kind']='primary_notice'
        self.assertEqual(view(s),s)

    def test_standalone_ad_label_never_deletes_following_news(self):
        from app.services.edition_evidence_view import view,screen
        s=self.source('事实一。\nAdvertisements\n反方：需求可能下降，不能据此推断订单改善。')
        t=view(s)['text'];self.assertIn('事实一。',t);self.assertIn('反方：需求可能下降',t)
        self.assertEqual(screen(s)['removed_characters'],15)

    def test_cta_like_statement_in_denial_or_quotation_is_not_removed(self):
        from app.services.edition_evidence_view import view
        for prefix in ('The company denied saying: ','“','Analysts criticised the wording: '):
            s=self.source(prefix+'It is time to seize this price opportunity and invest in gold.\n')
            self.assertEqual(view(s),s)

    def test_same_words_across_a_removed_interval_are_not_a_quote(self):
        from app.services.edition_evidence_view import assert_quote
        s=self.source('前段证据\nAdvertisements\n后段条件')
        with self.assertRaisesRegex(ValueError,'outside_evidence_view'):
            assert_quote(s,'前段证据\nAdvertisements\n后段条件')
        with self.assertRaisesRegex(ValueError,'outside_evidence_view'):
            assert_quote(s,'后段条件',delivered_ranges=[[0,4]])

    def test_view_is_idempotent_and_cannot_be_quoted_as_full_raw_text(self):
        from app.services.edition_evidence_view import view,assert_quote,SEPARATOR
        s=self.source('前段证据\nAdvertisements\n后段条件');v=view(s)
        self.assertEqual(view(v),v)
        with self.assertRaisesRegex(ValueError,'crosses_omission'):assert_quote(v,'证据\n'+SEPARATOR.strip()+'\n后段')

    def test_pending_source_cannot_pass_assessment_by_quoting_an_unrelated_sentence(self):
        from app.services.edition_evidence_view import view
        s=self.real();sid='web-398b81bfdf7f4b0afec3f21e';source=s['sources'][sid]
        events={e['id']:e for e in s['agenda']['events']};eid=source['event_ids'][0]
        rows=[dict(id=e,status='missing',reason='待核',evidence=[]) for e in events]
        next(r for r in rows if r['id']==eid).update(status='ready',evidence=[dict(source_id=sid,quote='U.S. stocks finished mixed Friday')])
        checks=[dict(key=r['market']+':'+r['code'],status='missing',reason='无直接证据') for r in s['watchlist']]
        accepted,_,validation=contract.prepare_assessment(dict(events=rows,watchlist_checks=checks),events,s['sources'],
            {r['key'] for r in checks},{sid})
        self.assertEqual(next(r for r in accepted['events'] if r['id']==eid)['status'],'missing')
        self.assertIn('edition_source_requires_confirmation',str(validation))

    def test_clear_source_can_replace_quarantined_lead_without_deleting_event(self):
        s=self.real();events={e['id']:e for e in s['agenda']['events']};eid='E2'
        source=self.source('公司已发布正式声明，董事会批准人员变更。');source['event_ids']=[eid]
        source['metadata']['kind']='primary_notice'
        rows=[dict(id=e,status='missing',reason='待核',evidence=[]) for e in events]
        next(r for r in rows if r['id']==eid).update(status='ready',evidence=[dict(source_id='news',quote='董事会批准人员变更')])
        checks=[dict(key=r['market']+':'+r['code'],status='missing',reason='无直接证据') for r in s['watchlist']]
        accepted,_,_=contract.prepare_assessment(dict(events=rows,watchlist_checks=checks),events,{'news':source},
            {r['key'] for r in checks},{'news'})
        self.assertEqual(next(r for r in accepted['events'] if r['id']==eid)['status'],'ready')

    def test_multiline_quoted_page_labels_are_not_removed(self):
        from app.services.edition_evidence_view import view
        s=self.source('记者引用该页：“\nAdvertisements\n某某产品广告\n”\n报道指出该宣传存在误导风险。')
        self.assertEqual(view(s),s)

    def test_quarantined_body_is_local_only_not_sent_to_any_model_stage(self):
        from app.services.edition_evidence_view import view,report
        s=self.real();source=s['sources']['web-398b81bfdf7f4b0afec3f21e']
        v=view(source);self.assertEqual(v['text'],'');self.assertEqual(v['provided_original_ranges'],[])
        self.assertIn('Jensen Huang',report({'source':source}))
        self.assertEqual(v['title'],source['title']);self.assertTrue(v['evidence_view']['reasons'])
