"""Prepare one historical analysis topic using exact previously supplied evidence."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from unittest.mock import patch, AsyncMock
import zipfile

SOURCE_SHA='8c0808dfd5769b9eac1b95e7d3c7fdd6fe07b92344d4c593a9ac65dee5f2e1e1'
NEWS_SHA='7af5ddca2ae003eb5c16529f985fa9f8860cfe4ec1265557111f619564648a03'
IDS=('9f0c5d394f627fcf205cd289','direct-476b56ccff4073de72311223','direct-3af3512b7bcb07c949094932')
IR='4ad37d214f9c07206ce9f25f'


def prepare(source,news,output):
    raw=Path(source).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SOURCE_SHA: raise ValueError('Not the actual completed report input')
    if hashlib.sha256(Path(news).read_bytes()).hexdigest()!=NEWS_SHA: raise ValueError('Unknown historical technical archive')
    packet=json.loads(raw);original=packet['messages'][0]['content'];blocks=[]
    for identifier in IDS:
        match=re.search(r'^### \d+\. \[N:'+re.escape(identifier)+r'\] ',original,re.M)
        if not match: raise ValueError('Required supplied article missing')
        end=re.search(r'^### \d+\. ',original[match.end():],re.M)
        if not end: raise ValueError('Article boundary unknown')
        blocks.append(original[match.start():match.end()+end.start()].rstrip())
    match=re.search(r'^\[N:'+IR+r'\] ',original,re.M)
    if not match: raise ValueError('Supplied IR missing')
    end=re.search(r'^\[N:',original[match.end():],re.M)
    if not end: raise ValueError('Research boundary unknown')
    blocks.append(original[match.start():match.end()+end.start()].rstrip())
    with zipfile.ZipFile(news) as archive:
        names=[n for n in archive.namelist() if n.endswith('technical.json')]
        if len(names)!=1:raise ValueError('Ambiguous technical archive')
        technical=json.loads(archive.read(names[0]))
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
    from app.services.ai_analyzer import AIAnalyzerService
    from app.models.report import ReportType
    from app.services.analysis_grounding import rsi_band
    metrics=[]
    for row in technical['instruments']:
        if row['symbol'] not in ('sz300750','sh000300'):continue
        if row['status']!='ok':raise ValueError('Unverified technical instrument')
        metrics.append(dict(symbol=row['symbol'],name=row['provider_name'],source_url=row['source_url'],
            adjustment=row['adjustment'],observed_at=row['observed_at'],
            metrics=row['metrics'],rsi14_band=rsi_band(row['metrics']['rsi14']),
            price_structure=row['analysis']['regime']))
    if len(metrics)!=2:raise ValueError('Missing stock or benchmark')
    analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
    analyzer._edition_label='早报'
    analyzer._generation_context='历史分析验收，资料截面2026-10-29 07:32；只写宁德时代与锂价相关的一个研究问题，不扩写整期早报或其他自选股。不是实时建议。'
    market='已完成日线，截至2026-10-28；个股前复权，指数未复权，不拼接其他时点报价。return_1d_pct为单日，return_5d/20d_pct为相应期累计收益，excess为同期收益之差（百分点）。RSI严格小于30才属传统超卖，不代表反弹；未知资金流、估值和一致预期不补造。\n'+json.dumps(metrics,ensure_ascii=False)
    with patch('requests.sessions.Session.request',side_effect=AssertionError('No network')),patch('httpx.AsyncClient.send',new=AsyncMock(side_effect=AssertionError('No network'))):
        prompt=analyzer._build_editorial_report_prompt(today=datetime(2026,10,29).date(),report_type=ReportType.MORNING,
            is_trading_day='独立日历未核验',watchlist_text='本次只讨论App自选股宁德时代（A:300750），不是用户持仓。',
            market_data_text=market,finance_summary='\n\n'.join(blocks),cross_border_summary='本次单主题未附海外资料，不编全市场判断。')
    prompt+='\n单主题任务：宁德时代的经营变化、锂价下行和近期价格表现，对未来数日的判断意味着什么？用当前正式分析要求，输出一篇紧凑的研究短稿及原格式元数据；不写口播、不评论旧稿、不讲模型课程、不列检查清单。不强制方向，不凑其他公司，无补查工具。最多展开一个主判断，约700—1200字，不以篇幅删除关键证据。'
    assert all(block in prompt for block in blocks)
    size=len(json.dumps([dict(role='user',content=prompt)],ensure_ascii=False,separators=(',',':')))
    if size>18000:raise ValueError('Focus input exceeds 18000-character cap')
    result=dict(model_requests=0,confirmed_sources=0,news_snapshot=packet['snapshot_collected_at'],research_export=packet['research_exported_at'],
        single_report_prompt=prompt,prepared_citation_ids=[*IDS,IR],news_candidates=3,selected_news=3,research_views=1,research_source_documents=1,
        source_input_sha256=SOURCE_SHA,input_characters=size,exact_supplied_blocks_preserved=True,
        limitation='Manual topic selection tests writing with known relevant evidence, not autonomous retrieval/ranking, full report, speech, audio or investment accuracy.')
    output=Path(output)
    if output.exists():raise ValueError('Immutable prepared input exists')
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return {k:v for k,v in result.items() if k!='single_report_prompt'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('source','news','output'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args();print(json.dumps(prepare(args.source,args.news,args.output),ensure_ascii=False,indent=2))
