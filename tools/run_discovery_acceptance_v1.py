"""One guarded new-snapshot analysis trial. --run is a paid action; no retries."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit

TRIAL='discovery-report-20261030-v1'
INPUT_SHA='79aab53f71b65ea00e04bb75ab239fbe812278ebc17478c03248cf14538bcbbc'
SNAPSHOT_SHA='7037cc9d1d89a04d4757a3f3fc959ab9c8d625896eacac8698fde6c212c4fe82'
MAX_CALLS=2
MAX_TOKENS=6000


def digest(raw):return hashlib.sha256(raw).hexdigest()


def encode(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'))


def save(path,value):
    from app.services.research_hub import save_json
    save_json(path,value)


def load(backend):
    raw=(backend/'data/diagnostics/discovery-preflight'/(INPUT_SHA+'.input.json')).read_bytes()
    if digest(raw)!=INPUT_SHA:raise RuntimeError('固定完整输入指纹不匹配')
    packet=json.loads(raw)
    if (packet.get('owner')!='finance-discovery-preflight-20261030-v1'
        or packet.get('snapshot_sha256')!=SNAPSHOT_SHA
        or packet.get('proposed_max_http_requests')!=MAX_CALLS
        or packet.get('proposed_max_output_tokens_per_request')!=MAX_TOKENS or packet.get('retries')!=0):
        raise RuntimeError('固定试验范围或预算不匹配')
    from app.services.prompt_reading import input_characters,validate_input
    if input_characters(packet['messages'])!=packet['input_characters']:raise RuntimeError('输入字符量已变化')
    validate_input(packet['messages'])
    return packet


def verify(backend,packet):
    if not (backend/'data/.automation-paused').is_file():raise RuntimeError('维护暂停状态已改变')
    for name,key in packet['source_bindings'].items():
        if digest((backend/name).read_bytes().replace(b'\r\n',b'\n'))!=key:raise RuntimeError('预检后源码改变：'+name)
    for name,key in packet['source_files'].items():
        if digest((backend/name).read_bytes())!=key:raise RuntimeError('预检后资料改变：'+name)
    from app.services.watchlist_repository import read_app_watchlist,watchlist_signature
    from app.services.time_context import china_now
    from app.fresh_input_check import local_time
    from datetime import timedelta
    if watchlist_signature(asyncio.run(read_app_watchlist()))!=watchlist_signature(packet['watchlist']):
        raise RuntimeError('自选股改变，不使用旧输入')
    age=china_now()-local_time(packet['snapshot_collected_at'])
    if not timedelta()<=age<=timedelta(hours=2):raise RuntimeError('资料已超两小时；未发请求，不自动重采')


def workspace_for(backend,packet):
    from app.selection_check import candidates
    from app.services.episode_workspace import EpisodeWorkspace,body
    from app.services.research_hub import ResearchHub
    from app.services.watchlist_service import WatchlistStock
    folder=backend/'data/radar'
    snapshot=json.loads((folder/'news-acceptance.json').read_text(encoding='utf-8'))
    replay=json.loads((folder/'selection-replay.json').read_text(encoding='utf-8'))
    pool=candidates(snapshot,bool(replay.get('restored_market_events',False)))
    ws=EpisodeWorkspace(pool,root=backend/'data/episodes')
    stocks=[WatchlistStock(row['code'],row['name'],row['market']) for row in packet['watchlist']]
    research=ResearchHub().evidence_pool(stocks)
    if len(research)!=packet['research_pool']:raise RuntimeError('研究池与固定输入不一致')
    ws.add(research);ws.bind_catalogue(packet['catalogue_refs'])
    text='\n'.join(row['content'] for row in packet['messages'])
    for channel,records in [('initial_news',replay['selection'].get('initial_reading',[])),('initial_research',packet.get('research_reading',[]))]:
        for row in records:
            if not row.get('ranges'):continue
            identifier=row['id']
            if identifier not in ws.documents:raise RuntimeError('已准备正文不在冻结资料池')
            original=body(ws.documents[identifier])
            for start,end in row['ranges']:
                if not 0<=start<end<=len(original) or original[start:end] not in text:
                    raise RuntimeError('初始阅读范围与实际输入不一致')
            ws.prepare_ranges(identifier,row['ranges'],channel)
    return ws


FINAL='本试验只允许一轮固定池补读，现已结束。请按已有证据完成完整报告，保留无法解决的缺口，不再请求工具。'


def followup(base,requests,results):
    from app.services.news_workspace_brief import without_catalogue
    return without_catalogue(base)+'\n本轮取材请求：'+encode(requests)+'\n工具返回资料：'+encode(results)+'\n'+FINAL


def dispatch(ws,requests,initial):
    from app.services.prompt_reading import input_characters
    results=[]
    for request in requests:
        if not isinstance(request,dict):raise ValueError('invalid_evidence_request')
        before_prepared={key:set(value) for key,value in ws.prepared.items()}
        before_accessed=dict(ws.accessed)
        tool=request.get('tool')
        if tool=='read_material':
            result=ws.read(request.get('id'),request.get('offset',0),request.get('characters',6000))
        elif tool=='search_materials':
            query=request.get('query')
            if not isinstance(query,str) or not 2<=len(query.strip())<=120:raise ValueError('invalid_research_query')
            result=ws.search(query)
        elif tool=='search_public':
            result=dict(status='not_enabled_in_frozen_trial',reason='本试验只使用冻结候选及研究池，无公开补采')
        else:raise ValueError('unknown_evidence_tool')
        candidate=results+[dict(tool=tool,result=result)]
        if input_characters([dict(role='user',content=followup(initial,requests,candidate))])>100000:
            ws.prepared=before_prepared;ws.accessed=before_accessed
            result=dict(status='not_provided_input_budget',reason='本次结果超过剩余输入预算，未向模型提供正文；不将其视为已读')
        ws.record(request,result)
        results.append(dict(tool=tool,result=result))
    return results


def visible_checkpoint(response):
    try:data=response.json()
    except (ValueError,TypeError):data={}
    if not isinstance(data,dict):data={}
    blocks=(data.get('content') or []) if response.status_code<400 else []
    visible='\n'.join(row['text'] for row in blocks if isinstance(row,dict) and row.get('type')=='text' and isinstance(row.get('text'),str))
    return dict(http_status=response.status_code,stop_reason=data.get('stop_reason'),visible_text=visible),data


def checks(text,ws):
    from app.services.evidence import validate_citations
    problems=[]
    blocks=list(re.finditer(r'```json\s*(.*?)\s*```',text,re.S))
    metadata={};body_text=text
    if blocks:
        try:metadata=json.loads(blocks[-1].group(1));body_text=text[:blocks[-1].start()].strip()
        except ValueError:problems.append('metadata_json_invalid')
    else:problems.append('metadata_block_missing')
    if not isinstance(metadata,dict):metadata={};problems.append('metadata_not_object')
    try:validate_citations(body_text,ws.documents.values())
    except RuntimeError as error:problems.append(str(error))
    usage=ws.usage(body_text,metadata.get('decision_notes') if isinstance(metadata.get('decision_notes'),list) else [])
    if usage['cited_without_confirmed_text']:problems.append('cited_without_provided_body')
    return dict(problems=problems,metadata=metadata,evidence_usage=usage,
                limitation='免费格式/引用范围检查，不是事实、推理或投资价值核验。')


def preview(packet):
    return dict(mode='free_preview',trial=TRIAL,input_sha256=INPUT_SHA,snapshot_collected_at=packet['snapshot_collected_at'],
        input_characters=packet['input_characters'],route=packet['route'],max_http_requests=MAX_CALLS,
        max_output_tokens_per_request=MAX_TOKENS,retries=0,http_requests_performed=0,
        limitation='--run且输入指纹匹配才收费；一次冻结资料分析试验，必要时最多一轮补读。无公开补采、自动审查、修稿、口播、TTS或发布；不恢复调度。')


def execute(backend,packet,ws,gateway,client_factory,record_usage,guard):
    folder=backend/'data/diagnostics/discovery-acceptance';folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    state=folder/(TRIAL+'.json');marker=folder/(TRIAL+'.started')
    if marker.exists():
        print('该试验已有开始记录，禁止重复扣费。结果：'+str(state),flush=True)
        return state
    guard()
    route=gateway.resolve_route('analysis')
    actual=dict(provider=route.provider,model=route.model,host=urlsplit(route.base_url).hostname,effort=route.effort)
    if actual!=packet['route'] or actual['provider']!='ofox_anthropic' or actual['host']!='api.ofox.io':
        raise RuntimeError('模型路由与预检不同，不切换或降级')
    from app.services.prompt_reading import validate_input
    from app.services.episode_research import requests_from_response
    initial='\n'.join(row['content'] for row in packet['messages'])
    messages=packet['messages'];validate_input(messages)
    fd=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
    result=dict(owner=TRIAL,status='started',input_sha256=INPUT_SHA,snapshot_collected_at=packet['snapshot_collected_at'],
        http_requests=0,max_http_requests=MAX_CALLS,max_output_tokens_per_request=MAX_TOKENS,retries=0,usage=[],
        workspace=str(ws.path),limitation='未通过人工验收，不是已发布报告；无音频，不恢复调度。')
    save(state,result)
    started=time.monotonic()
    try:
        for index in range(MAX_CALLS):
            guard();size=validate_input(messages)
            save(folder/(TRIAL+f'.round{index+1}.input.json'),dict(messages=messages,input_characters=size))
            url,headers,payload=gateway.request_for(route,messages,MAX_TOKENS)
            print(f'开始分析请求{index+1}/{MAX_CALLS}，输入{size}字符；无自动重试。',flush=True)
            result.update(status='running',phase='analysis',round_number=index+1);save(state,result)
            call_started=time.monotonic()
            attempted=False
            try:
                with client_factory(timeout=300,follow_redirects=False) as client:
                    attempted=True;result['http_requests']+=1;save(state,result)
                    response=client.post(url,headers=headers,json=payload)
            except Exception as error:
                if attempted:result['usage'].append(record_usage('analysis',route,MAX_TOKENS,error=error,elapsed=time.monotonic()-call_started,request_characters=size))
                raise
            result['usage'].append(record_usage('analysis',route,MAX_TOKENS,response=response,elapsed=time.monotonic()-call_started,request_characters=size))
            visible,data=visible_checkpoint(response)
            save(folder/(TRIAL+f'.round{index+1}.response.json'),visible)
            result['last_http_status']=response.status_code
            result['last_stop_reason']=visible.get('stop_reason')
            save(state,result)
            if response.status_code>=400:raise gateway.service_error('analysis',response)
            text=gateway.completed_text(route,data)
            ws.confirm_analysis_response()
            requests=requests_from_response(text)
            if requests is None:
                report=folder/(TRIAL+'.report.md')
                fd=os.open(report,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'w',encoding='utf-8') as stream:stream.write(text)
                result.update(status='completed_for_human_review',report_file=str(report),offline_checks=checks(text,ws))
                break
            if index+1>=MAX_CALLS:
                result['failure_reason']='tool_request_after_final_round'
                raise RuntimeError('补读后仍请求工具；预算结束，不发第三次请求')
            result['phase']='local_evidence_read';save(state,result)
            results=dispatch(ws,requests,initial)
            save(folder/(TRIAL+'.tools.json'),dict(requests=requests,results=results))
            messages=[dict(role='user',content=followup(initial,requests,results))]
        else:raise RuntimeError('分析未生成正文')
    except Exception as error:
        result.update(status='failed_preserved',error_type=type(error).__name__,reason='stopped_with_saved_checkpoints_no_retry')
    finally:
        result.update(elapsed_seconds=round(time.monotonic()-started,2),pause_flag_present=(backend/'data/.automation-paused').is_file())
        save(state,result)
        save(ws.path/'usage.json',ws.usage())
        ws.meta['status']=result['status'];save(ws.path/'meta.json',ws.meta)
    print('状态：'+result['status']+'；结果：'+str(state),flush=True)
    print('实际HTTP请求数：'+str(result['http_requests']),flush=True)
    if result.get('report_file'):print('报告：'+result['report_file'],flush=True)
    return state


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend',type=Path,default=Path('/var/www/finance-daily/backend'))
    parser.add_argument('--run',action='store_true',help='授权本次最多两次付费分析HTTP请求，无自动重试')
    parser.add_argument('--input-sha256')
    args=parser.parse_args();backend=args.backend.resolve()
    sys.path.insert(0,str(backend))
    marker=backend/'data/diagnostics/discovery-acceptance'/(TRIAL+'.started')
    if marker.exists():print('该试验已有开始记录，不重跑：'+str(marker.with_suffix('.json')),flush=True);return
    packet=load(backend)
    print(json.dumps(preview(packet),ensure_ascii=False,indent=2),flush=True)
    verify(backend,packet)
    if not args.run:return
    if args.input_sha256!=INPUT_SHA:raise RuntimeError('先核对完整输入指纹，未执行请求')
    ws=workspace_for(backend,packet)
    import httpx
    from app.services import model_gateway
    from app.services.model_usage import record_usage
    execute(backend,packet,ws,model_gateway,httpx.Client,record_usage,lambda:verify(backend,packet))


if __name__=='__main__':main()
