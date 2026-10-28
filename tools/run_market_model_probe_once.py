"""One authorized historical market-model/editorial probe (2026-10-29). Does not enable production jobs.
Default: free preview. --run: one POST, no retries; keep pause flag intact.
No news collection, DB access, TTS, provider fallback or production source edits.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

MODEL='anthropic/claude-sonnet-5.5'
MAX_TOKENS=1200
PROBE_ID="market-model-editorial-20261029-v1"


def messages():
    return [dict(role='system',content='只使用给定材料完成财经编辑验收。不要调用工具、联网或输出思维过程。'),
            dict(role='user',content=PROMPT)]


def preview():
    text=json.dumps(messages(),ensure_ascii=False,separators=(',',':'))
    return dict(mode='free_preview',model=MODEL,input_characters=len(text),
        max_output_tokens=MAX_TOKENS,max_http_requests=1,retries=0,
        limitation='字符不是token；实际扣费以账户为准。无搜索、缓存写入或TTS；一次POST，零自动重试。')


def save(path,value):
    # All artifacts are under this dedicated probe folder; atomic private writes.
    temporary=path.with_suffix('.tmp')
    descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2)
        stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)


def execute(backend,gateway,client_factory,record_usage):
    """Separate one-shot process only; never unlink/patch the production pause guard."""
    backend=Path(backend).resolve()
    flag=backend/'data/.automation-paused'
    if not flag.is_file():raise RuntimeError('要求财经项目保持维护暂停；本工具不会创建或删除暂停标记')
    route=gateway.resolve_route('analysis')
    if (route.model!=MODEL or route.provider!='ofox_anthropic'
            or urlsplit(route.base_url).hostname!='api.ofox.io'):
        raise RuntimeError('实际分析路由不是已批准的Ofox Sonnet 5.5，停止；不切模型或试旧域名')
    from dataclasses import replace
    route=replace(route,effort='none')  # Probe only; leave production settings untouched.
    request=messages()
    if preview()['input_characters']>5000:raise RuntimeError('小样本输入超出5000字符保护，未请求')
    url,headers,body=gateway.request_for(route,request,MAX_TOKENS)
    key=hashlib.sha256(json.dumps(dict(provider=route.provider,url=url,body=body),
        ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()
    folder=backend/'data/diagnostics/market-model-probe';folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    marker=folder/(PROBE_ID+'.started');state=folder/(PROBE_ID+'.json')
    try:descriptor=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:
        print('该小样本已有请求记录，不重复扣费。结果：'+str(state),flush=True)
        return state
    os.close(descriptor)
    data=dict(owner=PROBE_ID,at=datetime.now(timezone.utc).isoformat(),
        status='started',http_requests=0,request_sha256=key,**preview())
    data['mode']='isolated_paid_probe'
    save(state,data)
    started=time.monotonic()
    try:
        if not flag.is_file():raise RuntimeError('暂停状态已改变，停止本次请求')
        with client_factory(timeout=120.0,follow_redirects=False) as client:
            data.update(http_requests=1,status='request_attempted');save(state,data)
            # Exactly one POST. No use of complete(), which has production retries.
            response=client.post(url,headers=headers,json=body)
        usage=record_usage('analysis',route,MAX_TOKENS,response=response,
            elapsed=time.monotonic()-started,request_characters=data['input_characters'])
        data.update(http_status=response.status_code,usage=usage)
        if response.is_error:raise gateway.service_error('analysis',response)
        payload=response.json()
        data['stop_reason']=payload.get('stop_reason')
        # Keep visible text even if truncated, never save thinking blocks or headers.
        data['response']='\n'.join(block.get('text','') for block in payload.get('content',[])
            if block.get('type')=='text')
        data['response']=gateway.completed_text(route,payload)
        data['status']='completed_for_human_review'
    except Exception as error:
        data.update(status='failed_no_retry',error_type=type(error).__name__,
            note='可能已经计费；开始标记保留，不删除后重跑。部分回复不是通过验收的内容。')
        if 'http_status' not in data and data['http_requests']:
            data['usage']=record_usage('analysis',route,MAX_TOKENS,error=error,
                elapsed=time.monotonic()-started,request_characters=data['input_characters'])
    finally:
        data.update(elapsed_seconds=round(time.monotonic()-started,2),pause_flag_present=flag.is_file())
        save(state,data)
    print('状态：'+data['status']+'；结果：'+str(state),flush=True)
    if data.get('usage'):print('用量：'+json.dumps(data['usage'],ensure_ascii=False),flush=True)
    if data.get('response'):print('\n=== 模型回复，待人工验收 ===\n'+data['response'],flush=True)
    return state


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--backend',type=Path,default=Path('/var/www/finance-daily/backend'))
    args=parser.parse_args()
    details=preview()
    if args.run:details['mode']='isolated_paid_probe'
    print(json.dumps(details,ensure_ascii=False,indent=2),flush=True)
    if not args.run:return
    sys.path.insert(0,str(args.backend.resolve()))
    import httpx
    from app.services import model_gateway
    from app.services.model_usage import record_usage
    execute(args.backend,model_gateway,httpx.Client,record_usage)



PROMPT='你是财经播客编辑。以下是一次有限的历史表达测试，不是实时播报，不要求查询外部资料。不要把历史模型检验当作盈利策略，不编价格、行情、公司新闻或交易胜率。\n\n【真实历史材料A】\n采集时间2026-10-25 11:36，北京时间；已完成日线截至2026-10-23。不是10月28日数据。\n华海诚科（sh688535）相对沪深300的市场模型：个股日收益=截距+beta×指数日收益+残差，收益为百分数、残差为百分点。\n固定120期估计→随后20期留出→再后5期观察，不重复拟合。beta=2.331178；20期留出误差RMSE=3.327680个百分点，简单“个股收益等于指数收益”基线RMSE=3.686735个百分点。仅在这个短留出期内较好，误差仍较大，不保证未来。\n最近5期日残差的算术合计=+0.506970个百分点，不是复利投资收益，也不是未来收益。没有绑定可核实的公司事件，没有提供该5期股票或指数的绝对收益，不能推断股票一定上涨。价格模型与技术指标共享数据，不是独立双重验证。\n\n【合成边界测试B，非真实公司资料】\n测试股甲：样本内R²=0.98，留出期RMSE=1.8个百分点，简单基线RMSE=1.2个百分点，状态diagnostic_only。没有提供最近残差。不得据高R²称预测准确或虚构残差。\n\n【待编辑稿，故意含错误】\n华海诚科过去五期额外赚了0.51%，证明有公司利好没有被市场定价。模型已经跑赢基线，因此预计未来三天会继续跑赢大盘。测试股甲拟合度98%，说明胜率很高。两只股票都有技术指标和市场模型双重验证。\n\n【任务】\n1. 分别指出待编辑稿中必须改的地方；不要把没有现价判成数据矛盾，也不要求编新消息。\n2. 写一段可用于历史样稿的口播，150—250个汉字：说明材料A真正增加了什么认识、尚不能区分什么、如何观察和推翻一个有期限的相对强弱假设。允许有边界的主观倾向，但要区分它与模型直接提供的结论；若材料不足以支持方向，不强编方向。不能一段只读免责声明或连续报系数。\n3. 用一句话处理材料B；不要输出它未提供的系数或残差。\n\n禁止搜索、工具调用、音频、App写入和重新生成整期。回答不超过1200个输出token。\n'

if __name__=='__main__':main()
