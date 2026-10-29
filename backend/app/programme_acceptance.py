"""Free preparation of one historical programme trial; --run is an explicit paid action."""
import argparse
from dataclasses import replace
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

TRIAL='programme-report-20261029-v1'
REPORT_SHA='82b52f5f3dd4a2a1579b4e851d80d123304bf2e2f2f92011fcc2fcc3c24075a9'
ORIGIN_SHA='0bf1cb2e8646ca392e318385e973ff0987a1085a90733b2f941c2fab240bfeb2'
MODEL='anthropic/claude-sonnet-5.5'
MAX_TOKENS=8000


def digest(value):
    return hashlib.sha256(value).hexdigest()


def save(path,value):
    from .services.research_hub import save_json
    save_json(path,value)


def prepare(backend,report_path):
    backend=Path(backend)
    if not (backend/'data/.automation-paused').is_file():raise RuntimeError('必须保持维护暂停')
    raw=Path(report_path).read_bytes().replace(b'\r\n',b'\n')
    if digest(raw)!=REPORT_SHA:raise RuntimeError('固定人工修正版报告指纹不匹配')
    origin=backend/'data/diagnostics/staged-report'/(ORIGIN_SHA+'.report.json')
    original=json.loads(origin.read_text(encoding='utf-8'))
    if original.get('status')!='completed_for_human_review' or original.get('input_sha256')!=ORIGIN_SHA:
        raise RuntimeError('缺少已经付费完成的报告记录；禁止重新生成报告')
    from .services.editorial_policy import spoken_prompts
    report=SimpleNamespace(content=raw.decode('utf-8'),title='2026-10-29 A/H短线早报',report_date=date(2026,10,29))
    system,user=spoken_prompts(report,report.report_date,'早报')
    messages=[dict(role='system',content=system),dict(role='user',content=user)]
    encoded=json.dumps(messages,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    if len(encoded.decode())>15000:raise RuntimeError('输入超过15000字符，停止，不截断')
    return dict(owner=TRIAL,input_sha256=digest(encoded),report_sha256=REPORT_SHA,
        report=report.content,messages=messages,input_characters=len(encoded.decode()),
        max_output_tokens=MAX_TOKENS,max_http_requests=1,retries=0,
        source_sha256={name:digest((backend/'app/services'/name).read_bytes().replace(b'\r\n',b'\n'))
            for name in ('editorial_policy.py','spoken_programme.py','spoken_editing.py','podcast_generator.py')})


def preview(packet):
    return dict(mode='free_preview',trial=TRIAL,input_sha256=packet['input_sha256'],
        report_sha256=REPORT_SHA,input_characters=packet['input_characters'],model=MODEL,
        max_output_tokens=MAX_TOKENS,max_http_requests=1,retries=0,http_requests_performed=0,
        limitation='使用07:32历史人工修正报告和当前正式编排提示词；不是新实时节目。'
        '默认免费，--run且提供本次输入指纹才执行一次写稿。无自动审查、修稿、TTS或发布；不恢复调度。'
        '编排与正文供人工判断，不验收上游采集、完整分析、预测效果或实际音频。字符不是token，未承诺扣费金额。')


def execute(backend,packet,expected_sha,gateway,client_factory,record_usage):
    backend=Path(backend)
    if expected_sha!=packet['input_sha256']:raise RuntimeError('请先核对免费预览的输入指纹，未执行请求')
    actual=digest(json.dumps(packet['messages'],ensure_ascii=False,separators=(',',':')).encode('utf-8'))
    if actual!=packet['input_sha256'] or digest(packet['report'].encode('utf-8'))!=packet['report_sha256']:
        raise RuntimeError('预检后输入已变化，未执行请求')
    if not (backend/'data/.automation-paused').is_file():raise RuntimeError('暂停状态已变化')
    for name,expected in packet['source_sha256'].items():
        if digest((backend/'app/services'/name).read_bytes().replace(b'\r\n',b'\n'))!=expected:
            raise RuntimeError('预检后源码已变化，未执行请求')
    folder=backend/'data/diagnostics/staged-programme'
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    state=folder/(TRIAL+'.json');marker=folder/(TRIAL+'.started')
    # A stable trial ID, independent of changed prompts, prevents casual recharging.
    if marker.exists():
        print('该试验已有开始记录，禁止重复扣费。结果：'+str(state),flush=True)
        return state
    route=gateway.resolve_route('podcast')
    if route.provider!='ofox_anthropic' or route.model!=MODEL or urlsplit(route.base_url).hostname!='api.ofox.io':
        raise RuntimeError('路由与预览不一致；不切换模型')
    route=replace(route,effort='none')
    url,headers,body=gateway.request_for(route,packet['messages'],MAX_TOKENS)
    fd=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
    result=dict(preview(packet),owner=TRIAL,status='started',http_requests=0)
    save(folder/(TRIAL+'.input.json'),packet);save(state,result)
    response=None;failure=None;started=time.monotonic()
    try:
        if not (backend/'data/.automation-paused').is_file():raise RuntimeError('暂停状态已变化')
        with client_factory(timeout=240.0,follow_redirects=False) as client:
            result.update(status='request_attempted',mode='isolated_paid_programme_trial',http_requests=1,http_requests_performed=1)
            save(state,result)
            response=client.post(url,headers=headers,json=body)
        result['http_status']=response.status_code
        if response.is_error:raise gateway.service_error('podcast',response)
        payload=response.json();result['stop_reason']=payload.get('stop_reason')
        result['raw_response']='\n'.join(row.get('text','') for row in payload.get('content',[]) if row.get('type')=='text')
        save(state,result)  # Preserve even a malformed or truncated paid response.
        raw=gateway.completed_text(route,payload)
        from .services.spoken_programme import parse_response,delivery_leaks
        from .services.spoken_editing import prepare_script,audit
        plan,script=parse_response(raw,packet['report'])
        result.update(editorial_plan=plan,script=prepare_script(script))
        result['reading_load']=audit(result['script'])
        result['format_issues']=delivery_leaks(result['script'])
        if len(result['script'])>4000:result['format_issues'].append('超过4000字符')
        if not result['script'].replace('[SECTION_BREAK]','').strip():result['format_issues'].append('清理后正文为空')
        result['status']='format_rejected_no_retry' if result['format_issues'] else 'completed_for_human_review'
    except Exception as error:
        failure=error
        result.update(status='failed_no_retry',error_type=type(error).__name__,note='可能已计费，保留开始标记与回复，不自动重试')
    finally:
        # First persist text/status, even if usage bookkeeping itself fails.
        result['elapsed_seconds']=round(time.monotonic()-started,2);save(state,result)
        if result['http_requests']:
            result['usage']=record_usage('podcast',route,MAX_TOKENS,response=response,error=failure,
                elapsed=time.monotonic()-started,request_characters=packet['input_characters'])
            save(state,result)
    print('状态：'+result['status']+'；结果：'+str(state),flush=True)
    if result.get('usage'):print('用量：'+json.dumps(result['usage'],ensure_ascii=False),flush=True)
    if result.get('editorial_plan'):print('=== 编排摘要（不朗读）===\n'+json.dumps(result['editorial_plan'],ensure_ascii=False,indent=2),flush=True)
    if result.get('script'):print('=== 待人工验收口播，未合成音频 ===\n'+result['script'],flush=True)
    return state


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--input-sha256')
    args=parser.parse_args()
    backend=Path(__file__).resolve().parent.parent
    packet=prepare(backend,backend.parent/'docs/report_for_spoken_acceptance_20261029.md')
    print(json.dumps(preview(packet),ensure_ascii=False,indent=2),flush=True)
    if not args.run:return
    if not args.input_sha256:parser.error('--run需要提供免费预览的--input-sha256')
    import httpx
    from .services import model_gateway
    from .services.model_usage import record_usage
    execute(backend,packet,args.input_sha256,model_gateway,httpx.Client,record_usage)


if __name__=='__main__':main()
