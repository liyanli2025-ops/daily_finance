"""Free preview by default; --run authorizes ONE isolated speech-writing POST.
Uses v7 production spoken_prompts, a frozen manually corrected report, no paid review/TTS.
"""
import argparse
from dataclasses import replace
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

ID='spoken-report-20261029-v1'
ORIGIN_SHA='0bf1cb2e8646ca392e318385e973ff0987a1085a90733b2f941c2fab240bfeb2'
REPORT_SHA='82b52f5f3dd4a2a1579b4e851d80d123304bf2e2f2f92011fcc2fcc3c24075a9'
SOURCES={'editorial_policy.py':'3453334db42cccba3ed2f1aa53140bef0ea37cade27ec7e7a0b1133736b31ef9',
         'podcast_generator.py':'16a413f0694f4c3d421df9e2123a8b2efd2ae753688802b437fcdca6236b9f30'}
MODEL='anthropic/claude-sonnet-5.5'
MAX_TOKENS=8000


def save(path,data):
    temporary=path.with_suffix('.tmp')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as stream:
        json.dump(data,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)


def prepare(backend,report_path):
    backend=Path(backend).resolve()
    if not (backend/'data/.automation-paused').is_file():raise RuntimeError('维护暂停必须保持，不创建或删除暂停标记')
    for name,expected in SOURCES.items():
        value=(backend/'app/services'/name).read_bytes().replace(b'\r\n',b'\n')
        if hashlib.sha256(value).hexdigest()!=expected:raise RuntimeError('口播源码不是本次核对的v7：'+name+'；不覆盖或修改源码')
    raw=Path(report_path).read_bytes().replace(b'\r\n',b'\n')
    if hashlib.sha256(raw).hexdigest()!=REPORT_SHA:raise RuntimeError('人工修正版报告指纹不匹配，停止')
    origin=backend/'data/diagnostics/staged-report'/(ORIGIN_SHA+'.report.json')
    data=json.loads(origin.read_text(encoding='utf-8'))
    if data.get('status')!='completed_for_human_review' or data.get('input_sha256')!=ORIGIN_SHA:
        raise RuntimeError('未找到本次已完成报告的验收记录，不重新生成报告')
    from app.services.editorial_policy import spoken_prompts
    report=SimpleNamespace(content=raw.decode('utf-8'),title='2026-10-29 A/H短线早报',report_date=date(2026,10,29))
    system,user=spoken_prompts(report,report.report_date,'早报')
    messages=[dict(role='system',content=system),dict(role='user',content=user)]
    text=json.dumps(messages,ensure_ascii=False,separators=(',',':'))
    if len(text)>15000:raise RuntimeError('口播验收输入超过15000字符，停止，不截断')
    return dict(owner=ID,messages=messages,report_sha256=REPORT_SHA,input_sha256=hashlib.sha256(text.encode()).hexdigest(),
        input_characters=len(text),snapshot_collected_at='2026-10-29T07:32:10.979524',
        max_output_tokens=MAX_TOKENS,max_http_requests=1,retries=0)


def preview(packet):
    return dict(mode='free_preview',input_sha256=packet['input_sha256'],report_sha256=REPORT_SHA,
        input_characters=packet['input_characters'],model=MODEL,max_output_tokens=MAX_TOKENS,
        max_http_requests=1,retries=0,http_requests_performed=0,local_reasoning_effort='none',
        pricing_reference='https://ofox.io/models',reference_input_usd_per_million=2,
        reference_output_usd_per_million=10,max_output_reference_usd=.08,
        limitation='使用v7正式口播提示词和人工修正版报告，07:32历史截面，不是新实时节目。'
        '字符不是token，$0.08只含8000输出token的目录参考，输入另计，不是总扣费保证。'
        '默认不调用模型；--run单次写口播，不自动审查、修稿、TTS或发布，不恢复调度。'
        '本次局部低推理配置不改变生产设置，不验收新版报告分析、补查能力或实际音频。')


def canonical_script(raw):
    from app.services.spoken_editing import clean,tts_text
    script=clean(raw)
    if '[SECTION_BREAK]' not in script:
        paragraphs=script.split('\n\n')
        if len(paragraphs)>3:
            result=[]
            for i,paragraph in enumerate(paragraphs):
                result.append(paragraph)
                if (i+1)%3==0 and i<len(paragraphs)-1:result.append('[SECTION_BREAK]')
            script='\n\n'.join(result)
    return tts_text(script)


def execute(backend,packet,gateway,client_factory,record_usage):
    backend=Path(backend).resolve();flag=backend/'data/.automation-paused'
    if not flag.is_file():raise RuntimeError('暂停状态已变化，停止')
    route=gateway.resolve_route('podcast')
    if route.provider!='ofox_anthropic' or route.model!=MODEL or urlsplit(route.base_url).hostname!='api.ofox.io':
        raise RuntimeError('实际口播路由不是展示的Ofox Sonnet5.5，不自动切换')
    route=replace(route,effort='none')
    url,headers,body=gateway.request_for(route,packet['messages'],MAX_TOKENS)
    folder=backend/'data/diagnostics/staged-spoken';folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    state=folder/(ID+'.json');marker=folder/(ID+'.started')
    if marker.exists():
        print('本次口播验收已有请求记录，禁止重复扣费。结果：'+str(state),flush=True)
        return state
    fd=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
    data=dict(preview(packet),owner=ID,mode='isolated_paid_spoken_trial',status='started',http_requests=0)
    save(folder/(ID+'.input.json'),packet);save(state,data)
    started=time.monotonic();response=None;failure=None
    try:
        if not flag.is_file():raise RuntimeError('暂停状态已变化，停止')
        with client_factory(timeout=240.0,follow_redirects=False) as client:
            data.update(status='request_attempted',http_requests=1,http_requests_performed=1);save(state,data)
            response=client.post(url,headers=headers,json=body)
        data['http_status']=response.status_code
        if response.is_error:raise gateway.service_error('podcast',response)
        payload=response.json()
        data['stop_reason']=payload.get('stop_reason')
        data['raw_response']='\n'.join(row.get('text','') for row in payload.get('content',[]) if row.get('type')=='text')
        save(state,data)
        raw=gateway.completed_text(route,payload)
        data['script']=canonical_script(raw)
        from app.services.spoken_editing import audit
        data['reading_load']=audit(data['script'])
        if not data['script'].replace('[SECTION_BREAK]','').strip() or len(data['script'])>4000:
            data['status']='format_rejected_no_retry'
        else:data['status']='completed_for_human_review'
    except Exception as error:
        failure=error
        data.update(status='failed_no_retry',error_type=type(error).__name__,note='可能已计费；保留标记和已有回复，不删除标记重跑')
    finally:
        if data['http_requests']:
            data['usage']=record_usage('podcast',route,MAX_TOKENS,response=response,error=failure,
                elapsed=time.monotonic()-started,request_characters=packet['input_characters'])
        data.update(elapsed_seconds=round(time.monotonic()-started,2),pause_flag_present=flag.is_file())
        save(state,data)
    print('状态：'+data['status']+'；结果：'+str(state),flush=True)
    if data.get('usage'):print('用量：'+json.dumps(data['usage'],ensure_ascii=False),flush=True)
    if data.get('script'):print('\n=== 待人工验收口播稿，未生成音频 ===\n'+data['script'],flush=True)
    return state


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend',type=Path,default=Path('/var/www/finance-daily/backend'))
    parser.add_argument('--run',action='store_true',help='明确执行一次收费口播生成；不自动审查或重试')
    args=parser.parse_args();sys.path.insert(0,str(args.backend.resolve()))
    report_path=Path(__file__).with_name('report_for_spoken_acceptance_20261029.md')
    packet=prepare(args.backend,report_path)
    print(json.dumps(preview(packet),ensure_ascii=False,indent=2),flush=True)
    if not args.run:return
    import httpx
    from app.services import model_gateway
    from app.services.model_usage import record_usage
    execute(args.backend,packet,model_gateway,httpx.Client,record_usage)


if __name__=='__main__':main()
