"""Free preparation by default; --run + exact input SHA authorizes one trial.

Isolated model transport only. Never removes the production pause marker,
changes credentials, starts jobs, retries, generates speech or publishes.
"""
import argparse
import asyncio
from datetime import datetime,timedelta
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

TRIAL='model-led-primary-v1'


def setup():
    root=Path.cwd().resolve()
    if not (root/'app/config.py').is_file():raise RuntimeError('先cd /var/www/finance-daily/backend')
    sys.path.insert(0,str(root));return root


def digest(data):return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def route_metadata(route):
    return {k:getattr(route,k) for k in ('provider','model','base_url','effort')}


def paths(backend):
    root=backend/'data'
    return (root/'radar/cache'/(TRIAL+'.input.json'),root/'radar/cache'/(TRIAL+'.result.json'),
            root/'diagnostics'/(TRIAL+'.started'))


async def prepare(backend):
    from app.services.primary_discovery import Limits,prompt
    from app.services.watchlist_repository import read_app_watchlist
    from app.services.model_gateway import resolve_route
    from app.services.web_research import capabilities
    from app.services.time_context import china_now
    from app.services.research_hub import save_json
    from app.config import settings
    if not (backend/'data/.automation-paused').is_file():raise RuntimeError('要求保留维护暂停，不与正式任务并行')
    input_file,result_file,marker=paths(backend)
    if marker.exists():
        print('本试验已有开始标记，不重新准备或重复扣费。结果：'+str(result_file));return
    stocks=await read_app_watchlist();route=resolve_route('analysis');now=china_now()
    # Explicit trial limits, not new production defaults or article quotas.
    limits=Limits(model_calls=4,search_calls=8,body_urls=10,input_characters=80000,output_tokens=3000,seconds=360)
    value=dict(owner='finance-model-led-trial-v1',prepared_at=now.isoformat(),
        expires_at=(now+timedelta(hours=2)).isoformat(),watchlist=stocks,
        route=route_metadata(route),limits=limits.__dict__,prompt=prompt(stocks,now,limits))
    if input_file.exists():
        old=json.loads(input_file.read_text(encoding='utf-8'))
        if (datetime.fromisoformat(old['expires_at'])>now and old['watchlist']==stocks
            and old['route']==value['route'] and old['limits']==value['limits']
            and old['prompt']==prompt(stocks,datetime.fromisoformat(old['prepared_at']),limits)):
            value=old
    save_json(input_file,value)
    info=dict(mode='free_preview_no_requests',trial=TRIAL,input_sha256=digest(value),input_file=str(input_file),
        prepared_at=value['prepared_at'],expires_at=value['expires_at'],watchlist=stocks,route=value['route'],
        search_configured=capabilities()['configured'],production_search_enabled=settings.research_web_search_enabled,
        trial_temporarily_enables_search_only_in_this_process=True,
        max_model_http_requests=4,max_search_http_requests=8,max_basic_search_reference_credits=8,
        max_body_urls=10,max_public_gets_including_redirects=30,max_output_tokens_per_model_request=3000,
        max_input_characters_per_model_request=80000,retries=0,http_requests_performed=0,
        model_requests_performed=0,tts_requests_performed=0,
        limitation='最多4次真实模型POST、8次basic搜索；实际可能更少。字符不是token，未承诺美元账单。'
                    '需另行明确执行；不自动审查/修稿/分析成稿/口播/发布，不恢复调度。')
    print(json.dumps(info,ensure_ascii=False,indent=2));return info


class IsolatedModel:
    """Explicit trial callback; independent of production pause/retry controls."""
    def __init__(self,route,limits,guard,state,save,client_factory=None):
        import httpx
        self.route=route;self.limits=limits;self.guard=guard;self.state=state;self.save=save
        self.client_factory=client_factory or httpx.AsyncClient

    async def __call__(self,task,messages,max_tokens):
        from app.services import model_gateway as gateway
        from app.services.model_usage import record_usage
        if task!='analysis' or max_tokens>self.limits.output_tokens:raise RuntimeError('trial_model_request_invalid')
        if self.state['model_http_attempts']>=self.limits.model_calls:raise RuntimeError('trial_model_budget_exhausted')
        self.guard()
        chars=sum(len(m['content']) for m in messages)
        if chars>self.limits.input_characters:raise RuntimeError('trial_input_guard')
        url,headers,body=gateway.request_for(self.route,messages,max_tokens)
        self.state['model_http_attempts']+=1;self.save()
        started=time.monotonic();response=None
        try:
            # Default HTTPX transport has zero connection retries; explicitly no redirects.
            async with self.client_factory(timeout=80,follow_redirects=False) as client:
                self.guard()
                response=await client.post(url,headers=headers,json=body)
            if response.is_error:raise gateway.service_error(task,response)
            return gateway.completed_text(self.route,response.json())
        finally:
            usage=record_usage(task,self.route,max_tokens,response=response,
                error=RuntimeError('transport_or_response_failure') if response is None else None,
                elapsed=time.monotonic()-started,request_characters=chars)
            self.state['usage'].append(usage);self.save()


async def execute(backend,input_sha,*,model_factory=IsolatedModel):
    from app.config import settings
    from app.services.primary_discovery import Limits,prompt,discover
    from app.services.episode_workspace import EpisodeWorkspace
    from app.services.model_gateway import resolve_route
    from app.services.watchlist_repository import read_app_watchlist,watchlist_signature
    from app.services.time_context import china_now
    from app.services.research_hub import save_json
    from app.services.web_research import capabilities
    input_file,result_file,marker=paths(backend)
    if marker.exists():
        print('本试验已尝试，不重复扣费。结果：'+str(result_file));return
    value=json.loads(input_file.read_text(encoding='utf-8'))
    if value.get('owner')!='finance-model-led-trial-v1' or digest(value)!=input_sha:raise RuntimeError('试验输入指纹不匹配')
    now=china_now();prepared=datetime.fromisoformat(value['prepared_at'])
    if not prepared<=now<datetime.fromisoformat(value['expires_at']):raise RuntimeError('输入超过2小时或来自未来，先免费重新准备')
    stocks=await read_app_watchlist();route=resolve_route('analysis');limits=Limits(**value['limits'])
    if value['limits']!=Limits(model_calls=4,search_calls=8,body_urls=10,input_characters=80000,output_tokens=3000,seconds=360).__dict__:
        raise RuntimeError('试验预算已被改动，拒绝运行')
    if (watchlist_signature(stocks)!=watchlist_signature(value['watchlist'])
        or value['route']!=route_metadata(route) or value['prompt']!=prompt(stocks,prepared,limits)):
        raise RuntimeError('名单、模型路由或研究任务已变化，先免费重新准备')
    if not capabilities()['configured']:raise RuntimeError('搜索密钥未配置，不执行模型试验')
    flag=backend/'data/.automation-paused'
    def guard():
        if not flag.is_file():raise RuntimeError('维护暂停标记已变化，停止隔离试验')
    guard();marker.parent.mkdir(parents=True,exist_ok=True)
    try:fd=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:
        print('其他进程已经开始本试验，不重复扣费。');return
    os.close(fd)
    state=dict(owner='finance-model-led-trial-v1',trial=TRIAL,status='started',input_sha256=input_sha,
        collected_at=now.isoformat(),expires_at=(now+timedelta(hours=24)).isoformat(),model_http_attempts=0,usage=[])
    def save():save_json(result_file,state)
    save()
    try:
        workspace=EpisodeWorkspace([],now=prepared);state['workspace']=str(workspace.path)
        def checkpoint(research):
            state['research']=research;save()
        model=model_factory(route,limits,guard,state,save)
        with patch.object(settings,'research_web_search_enabled',True),patch.object(settings,'research_web_search_max_requests',limits.search_calls):
            research=await discover(workspace,stocks,limits=limits,model=model,checkpoint=checkpoint)
        if watchlist_signature(stocks)!=watchlist_signature(await read_app_watchlist()):
            research['status']='watchlist_changed_not_accepted'
        state.update(status=research['status'],research=research)
    except Exception as error:
        state.update(status='failed_no_retry',error_type=type(error).__name__)
    finally:
        state['finished_at']=china_now().isoformat();state['pause_preserved']=flag.is_file();save()
    research=state.get('research',{})
    summary={k:state[k] for k in ('status','model_http_attempts','error_type','pause_preserved') if k in state}
    summary.update(search_http_attempts=getattr(locals().get('workspace'),'web_search_attempts',0),
        phase=research.get('phase'),error_code=research.get('error_code'),
        body_url_calls=research.get('body_url_calls',0),provided_body_documents=len(research.get('provided_ids',[])),
        coverage_gaps=research.get('coverage_gaps'),watchlist_gaps=research.get('watchlist_gaps'),
        dossier=research.get('dossier'),result_file=str(result_file),tts_requests=0,
        limitation='待人工验收的资料底稿；不证明覆盖充分、判断正确或可直接生成播客。失败可能已计费，不删除开始标记重跑。')
    print(json.dumps(summary,ensure_ascii=False,indent=2));return state


async def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true');parser.add_argument('--input-sha')
    args=parser.parse_args();backend=setup()
    if args.run:
        if not args.input_sha:parser.error('--run必须同时提供免费预检的--input-sha')
        await execute(backend,args.input_sha)
    else:await prepare(backend)


if __name__=='__main__':asyncio.run(main())
