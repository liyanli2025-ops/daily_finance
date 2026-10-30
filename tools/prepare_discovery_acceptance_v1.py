"""Freeze the actual discovery-report input. No paid mode or network refresh."""
import argparse
import asyncio
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

EXPECTED_BINDINGS = {'app/config.py': 'b52d1dc65d0136d5f2b31ce1cd5ca77e9a5f81778262e0c2dae16145e0f001d7', 'app/services/ai_analyzer.py': 'f23b751371084e6a6bd3774f29607c370065e389e2d5d1f571217e32200cc25c', 'app/services/editorial_policy.py': '5af6ab939518f388f25a1a5a6aa1c48b28da0ddf050739aa4e7412df1064fdcc', 'app/services/episode_research.py': '962efe58a2b30ad76485636c5cb39635caca9e38cd096b8b82ec9c8c8e4f56b4', 'app/services/episode_workspace.py': '2e962fbf3e0774568618408d76e34d77fcee530cd8086af0307324fef5377141', 'app/services/news_workspace_brief.py': '7ce903633d357522c8029a03fba6b8539af8af04f25aa0129871778275a6ada3', 'app/services/model_gateway.py': '6c331b01f66d7f0cf85f4e23b5193fa647acf5ff7e729cfd564abafdb398597c', 'app/services/research_hub.py': '8a7a38da66c5facbe82617a671213ccfe7891db9f56a1a2e23fd8bc5b561c3b4', 'app/services/technical_radar.py': '143bf26add0cec2922bd3da13ae10d60c8e12e37f5bb46084cd4227d237f17f6', 'app/services/prompt_reading.py': '856f6b94fa7a98ad4c12775a928ff0ea9e2380dac7ffec4caeaa643d8d173edb'}
OWNER='finance-discovery-preflight-20261030-v1'


def digest(raw):return hashlib.sha256(raw).hexdigest()


def verify_sources(backend,expected=None):
    expected=EXPECTED_BINDINGS if expected is None else expected
    for name,key in expected.items():
        if digest((backend/name).read_bytes().replace(b'\r\n',b'\n'))!=key:
            raise RuntimeError('预检源码不匹配：'+name+'；停止，不采集或调用模型')


def save_input(folder,packet):
    raw=json.dumps(packet,ensure_ascii=False,sort_keys=True,indent=2).encode('utf-8')
    key=digest(raw)
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    target=folder/(key+'.input.json')
    if target.exists():
        if target.read_bytes()!=raw:raise RuntimeError('固定输入冲突，不覆盖')
    else:
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(raw)
    return target,key


async def prepare(backend):
    backend=Path(backend).resolve()
    if not (backend/'data/.automation-paused').is_file():raise RuntimeError('要求维护暂停保持')
    verify_sources(backend)
    from app.fresh_input_check import inspect as fresh_check
    from app.services.time_context import china_now
    from app.services.watchlist_repository import refresh_app_watchlist,watchlist_signature,assert_watchlist_current
    from app.services.technical_radar import prompt as technical_prompt
    from app.services.prompt_reading import compact_market,input_characters,validate_input
    from app.services.ai_analyzer import AIAnalyzerService
    from app.services.research_hub import ResearchHub
    from app.services.episode_research import INSTRUCTIONS,questions
    from app.services.model_gateway import resolve_route
    from app.models.report import ReportType
    service=await refresh_app_watchlist()
    stocks=service.get_all_stocks();signature=watchlist_signature(stocks)
    folder=backend/'data/radar'
    source_files={str(p.relative_to(backend)):digest(p.read_bytes()) for p in
        [folder/name for name in ('news-acceptance.json','selection-replay.json','technical.json','microstructure.json')] if p.is_file()}
    raw=(folder/'news-acceptance.json').read_bytes()
    snapshot=json.loads(raw)
    replay=json.loads((folder/'selection-replay.json').read_text(encoding='utf-8'))
    technical=json.loads((folder/'technical.json').read_text(encoding='utf-8'))
    now=china_now();at=datetime.fromisoformat(snapshot['collected_at'])
    freshness=fresh_check(raw,replay,technical,signature,now)
    if freshness['errors']:raise RuntimeError('资料准备不通过：'+json.dumps(freshness['errors'],ensure_ascii=False))
    discovery=replay.get('discovery_catalogue',{})
    if discovery.get('complete') is not True or not replay.get('initial_budget'):
        raise RuntimeError('缺少全池目录及预算记录，停止')
    references=replay.get('selection',{}).get('catalogue_refs',{})
    if len(references)!=discovery.get('entries') or not replay.get('news_input'):
        raise RuntimeError('目录编号或新闻输入缺失')
    from app.selection_check import candidates
    from app.services.news_quality import excluded_reason
    pool=candidates(snapshot,bool(replay.get('restored_market_events',False)))
    if set(references.values())!={item.id for item in pool if not excluded_reason(item)}:
        raise RuntimeError('目录覆盖与当前完整候选池不一致')
    market=compact_market(technical_prompt(stocks,folder,at))
    hub=ResearchHub()
    for stock in stocks:
        p=hub.root/'stocks'/((str(getattr(stock.market,'value',stock.market))+':'+stock.code).replace(':','-')+'.json')
        if p.is_file():source_files[str(p.relative_to(backend))]=digest(p.read_bytes())
    research,evidence=hub.prompt(stocks,max_characters=8000)
    research_pool=hub.evidence_pool(stocks)
    rows=[dict(market=str(getattr(stock.market,'value',stock.market)),code=stock.code,name=stock.name) for stock in stocks]
    analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
    analyzer._edition_label='晚报'
    analyzer._generation_context=(f'本次为新资料截面的分析验收；新闻采集截至{at.isoformat()}，准备于{now.isoformat()}（北京时间）。'
        '行情和研究资料各有自己的原始截止/发布时间；不刷新新闻或报价，不当作06:00早报或全网实时覆盖。'
        '没有当日早报原文，不编早报观点或预测准确率。')
    base_prompt=analyzer._build_editorial_report_prompt(today=at.date(),report_type=ReportType.EVENING,
        is_trading_day='未独立核验各市场日历，行情仅按来源交易日解释',
        watchlist_text='当前App自选股：'+json.dumps(rows,ensure_ascii=False)+'；不等于持仓，行情见带来源日期资料。',
        market_data_text=market,finance_summary=replay['news_input']+'\n\n'+research,
        cross_border_summary='国际及海外事件见全池目录和已提供片段；有重要缺口先读取，不编传导或受益公司。')
    messages=[dict(role='user',content=base_prompt+INSTRUCTIONS+'\n研究问题：\n'+questions(stocks))]
    size=validate_input(messages)
    route=resolve_route('analysis')
    await assert_watchlist_current(signature)
    for name,key in source_files.items():
        if digest((backend/name).read_bytes())!=key:raise RuntimeError('预检期间源文件改变，停止')
    packet=dict(owner=OWNER,snapshot_collected_at=snapshot['collected_at'],snapshot_sha256=digest(raw),
        messages=messages,base_prompt=base_prompt,source_files=source_files,source_bindings=EXPECTED_BINDINGS,
        catalogue_refs=references,watchlist=rows,research_reading=getattr(hub,'prompt_reading',[]),
        market_scope='已保存日线/分时/宽度；无实时刷新、无晨报对照或公开补采',
        input_characters=size,news_characters=len(replay['news_input']),market_characters=len(market),research_characters=len(research),
        research_views=len(evidence),research_pool=len(research_pool),
        route=dict(provider=route.provider,model=route.model,host=urlsplit(route.base_url).hostname,effort=route.effort),
        proposed_max_http_requests=2,proposed_max_output_tokens_per_request=6000,retries=0,
        scope='正式写作提示词+新资料目录+可补读完整池；拟定一次发现/写稿，必要时最多一次补读后成稿；不自动审查、修稿、TTS或发布。实际执行工具另行提供。')
    target,key=save_input(backend/'data/diagnostics/discovery-preflight',packet)
    result={k:v for k,v in packet.items() if k not in {'messages','base_prompt','source_files','source_bindings','catalogue_refs','watchlist','research_reading','scope'}}
    result.update(mode='free_full_input_preflight',http_requests_performed=0,model_requests_performed=0,
        input_sha256=key,input_file=str(target),scope=packet['scope'],
        limitation='字符不是token或费用；这次只准备输入。后续补读正文会改变请求长度并逐次预检。拟定预算不是生产全流程上限，也不代表已授权付费。')
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend',type=Path,default=Path('/var/www/finance-daily/backend'))
    args=parser.parse_args()
    sys.path.insert(0,str(args.backend.resolve()))
    asyncio.run(prepare(args.backend))


if __name__=='__main__':main()
