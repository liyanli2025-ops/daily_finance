"""Free held-topic preparation from immutable historical exports; no HTTP or model calls."""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sys
from unittest.mock import patch, AsyncMock
import zipfile
from prepare_analysis_focus import SOURCE_SHA, NEWS_SHA

IDS=('overseas-a0c3e1be77e8b5a27f797ac2','media-4c1a6c01d2672d5d10bad344','media-b4afd4dd5dded7eac0f39dc0')
SYMBOLS=('hkHSTECH','sh000688','sh000300')
METRICS=('as_of','close','return_1d_pct','return_5d_pct','return_20d_pct','ma20','ma60','rsi14','prior20_high','prior20_low')


def prepare(source,news,output):
    raw=Path(source).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SOURCE_SHA: raise ValueError('Unknown historical input')
    if hashlib.sha256(Path(news).read_bytes()).hexdigest()!=NEWS_SHA: raise ValueError('Unknown historical archive')
    packet=json.loads(raw); original=packet['messages'][0]['content']; blocks=[]
    for identifier in IDS:
        match=re.search(r'^### \d+\. \[N:'+re.escape(identifier)+r'\] ',original,re.M)
        if not match:raise ValueError('Missing supplied article')
        end=re.search(r'^### \d+\. ',original[match.end():],re.M)
        if not end:raise ValueError('Unknown article boundary')
        blocks.append(original[match.start():match.end()+end.start()].rstrip())
    with zipfile.ZipFile(news) as archive:
        names=[n for n in archive.namelist() if n.endswith('technical.json')]
        if len(names)!=1:raise ValueError('Ambiguous technical source')
        technical=json.loads(archive.read(names[0]))
    rows=[]
    for row in technical['instruments']:
        if row['symbol'] not in SYMBOLS:continue
        if row['status']!='ok' or row['metrics']['as_of']!='2026-10-28':raise ValueError('Unverified date or instrument')
        rows.append(dict(symbol=row['symbol'],name=row['provider_name'],source_url=row['source_url'],
            adjustment=row['adjustment'],observed_at=row['observed_at'],
            metrics={key:row['metrics'][key] for key in METRICS},price_structure=row['analysis']['regime']))
    if {r['symbol'] for r in rows}!=set(SYMBOLS):raise ValueError('Incomplete instruments')
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
    from app.services.ai_analyzer import AIAnalyzerService
    from app.models.report import ReportType
    analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
    analyzer._edition_label='早报'
    analyzer._generation_context='历史资料验收，固定截面2026-10-29 07:32北京时间，不是实时节目；本次只讨论海外利率、AI融资与A/H科技板块这一个问题。'
    market='已完成指数日线，截至2026-10-28，指数未复权；不含消息之后的行情。return_1d_pct为当日涨跌，5d/20d为对应窗口累计涨跌；prior20_high/low为不含当期的前20期盘中高低点。没有债券收益率曲线、汇率、资金流、市场一致预期或市场宽度快照。\n'+json.dumps(rows,ensure_ascii=False)
    with patch('requests.sessions.Session.request',side_effect=AssertionError('No HTTP')),patch('httpx.AsyncClient.send',new=AsyncMock(side_effect=AssertionError('No HTTP'))):
        prompt=analyzer._build_editorial_report_prompt(today=date(2026,10,29),report_type=ReportType.MORNING,
            is_trading_day='独立日历未核验',watchlist_text='本次是市场主题，不要求关联任何自选股，不假定用户持仓。',
            market_data_text=market,finance_summary='\n\n'.join(blocks),cross_border_summary='海外材料已完整按提供范围并入上述新闻，不重复计数。')
    prompt+='\n单主题任务：上述海外利率和AI融资信息，对A股、港股科技板块未来数日的判断有什么意义？写一篇约700—1200字的研究短稿及正式元数据，最多一个主判断。不要点评旧稿，不写口播或检查清单，不强制方向，不展开其他个股。只用提供资料，无补查工具。'
    assert all(block in prompt for block in blocks)
    messages=[dict(role='user',content=prompt)]
    chars=len(json.dumps(messages,ensure_ascii=False,separators=(',',':')))
    if chars>16000:raise ValueError('Exceeds 16000-character cap')
    result=dict(model_requests=0,confirmed_sources=0,news_snapshot=packet['snapshot_collected_at'],research_export=packet['research_exported_at'],
        single_report_prompt=prompt,prepared_citation_ids=list(IDS),news_candidates=3,selected_news=3,research_views=0,research_source_documents=0,
        source_input_sha256=SOURCE_SHA,input_characters=chars,exact_supplied_blocks_preserved=True,
        source_block_sha256={identifier:hashlib.sha256(block.encode('utf-8')).hexdigest() for identifier,block in zip(IDS,blocks)},
        technical_symbols=list(SYMBOLS),
        limitation='Manually selected historical market topic tests analysis transfer only; no live collection, retrieval, independent source verification, audio or publishing. Not a fresh-news acceptance.')
    output=Path(output)
    if output.exists():raise ValueError('Immutable input already exists')
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return {k:v for k,v in result.items() if k!='single_report_prompt'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('source','news','output'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args();print(json.dumps(prepare(args.source,args.news,args.output),ensure_ascii=False,indent=2))
