"""Free frozen-input preparation only. No --run, model requests, collection or App writes."""
import argparse
import asyncio
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys


def assemble(snapshot, replay, raw_sha, stocks, market):
    from app.selection_check import candidates
    from app.models.report import ReportType
    from app.services.ai_analyzer import AIAnalyzerService
    from app.services.prompt_reading import input_characters
    if replay.get('snapshot_sha256') != raw_sha:
        raise RuntimeError('重选与原始资料不匹配，停止；不会重新采集')
    pool={item.id:item for item in candidates(snapshot, bool(replay.get("restored_market_events", False)))}
    selected=[row['id'] for row in replay['selection']['articles'] if row.get('selected')]
    if not selected or len(selected)!=len(set(selected)) or set(selected)-set(pool):
        raise RuntimeError('入选清单为空、重复或缺原文')
    finance=replay.get('news_input','')
    if not finance.strip():raise RuntimeError('缺少保存的入模阅读片段')
    at=datetime.fromisoformat(snapshot['collected_at'])
    if any(pool[key].published_at>at for key in selected):raise RuntimeError('入选材料晚于固定截面，不可作当时已知信息')
    service=AIAnalyzerService.__new__(AIAnalyzerService)
    edition='即时更新' if at.hour>=9 else '早报'
    if at.weekday()>=5:edition='周末回顾'
    service._edition_label=edition
    service._generation_context=(f'历史截面文字验收，固定资料时点：{at.isoformat()}（北京时间）。'
        '不是当前实时节目，不发布App。各资料使用自身原始截止时间，不把采集时点当成交时点。'
        '本次单次成稿，不提供补查工具；资料不足就收窄结论，不编消息或催化。')
    prompt=service._build_editorial_report_prompt(today=at.date(),report_type=ReportType.MORNING,
        is_trading_day='本次未独立核验，不猜测A/H开休市',watchlist_text='当前App名单：'+json.dumps(stocks,ensure_ascii=False)+'；报价以固定市场资料自身时点为准。',
        market_data_text=market,finance_summary=finance,cross_border_summary='已选材料中的海外报道见上方，不另行补查。')
    messages=[dict(role='user',content=prompt)]
    size=input_characters(messages)
    return dict(owner='finance-staged-report-input-v1',snapshot_collected_at=at.isoformat(),snapshot_sha256=raw_sha,
        messages=messages,watchlist=stocks,candidate_count=len(pool),selected_count=len(selected),
        input_characters=size,max_output_tokens=8000,max_http_requests=1,retries=0,
        within_input_guard=size<=100000,
        limitation='仅准备实际报告写作提示词与固定阅读片段；不刷新行情、不搜索、不调用LLM/TTS、不自动审查或修稿、不写App。'
        '本次未附加独立ResearchHub缓存或全候选检索工具，不验收这些能力。字符不是token或收费估算。')


async def prepare(backend):
    from app.services.watchlist_repository import refresh_app_watchlist
    from app.services.technical_radar import prompt as technical_prompt
    from app.services.prompt_reading import compact_market
    backend=Path(backend).resolve()
    if not (backend/'data/.automation-paused').is_file():raise RuntimeError('要求维护暂停保持，不改变调度状态')
    root=backend/'data/radar'
    raw=(root/'news-acceptance.json').read_bytes()
    snapshot=json.loads(raw)
    replay=json.loads((root/'selection-replay.json').read_text(encoding='utf-8'))
    technical=json.loads((root/'technical.json').read_text(encoding='utf-8'))
    at=datetime.fromisoformat(snapshot['collected_at'])
    if not timedelta()<=at-datetime.fromisoformat(technical['collected_at'])<timedelta(hours=2):
        raise RuntimeError('技术快照与原资料截面不匹配；不会自动补采')
    watchlist=await refresh_app_watchlist()
    stocks=watchlist.get_all_stocks()
    rows=[dict(market=str(getattr(stock.market,'value',stock.market)),code=stock.code,name=stock.name) for stock in stocks]
    if {row['market']+':'+row['code'] for row in rows}!=set(technical.get('watchlist',[])):
        raise RuntimeError('当前名单与固定技术快照不一致；停止，不自动补采或扣费')
    market=compact_market(technical_prompt(stocks,root,at))
    packet=assemble(snapshot,replay,hashlib.sha256(raw).hexdigest(),rows,market)
    encoded=json.dumps(packet,ensure_ascii=False,sort_keys=True,indent=2).encode('utf-8')
    key=hashlib.sha256(encoded).hexdigest()
    folder=backend/'data/diagnostics/staged-report';folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    target=folder/(key+'.input.json')
    if target.exists():
        if target.read_bytes()!=encoded:raise RuntimeError('固定输入文件冲突，不覆盖')
    else:
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(encoded)
    result={key:value for key,value in packet.items() if key not in {'messages','watchlist'}}
    result.update(status='prepared_no_model_calls',http_requests_performed=0,input_file=str(target),input_sha256=key)
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    return packet,target


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend',type=Path,default=Path('/var/www/finance-daily/backend'))
    args=parser.parse_args()
    sys.path.insert(0,str(args.backend.resolve()))
    asyncio.run(prepare(args.backend))
