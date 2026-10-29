"""Assemble historical exported news/research/technical input, with network disabled."""
import argparse
import copy
from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch,AsyncMock
import zipfile


def read_member(archive,suffix):
    names=[name for name in archive.namelist() if name.endswith(suffix)]
    if len(names)!=1:raise ValueError('Ambiguous archive member '+suffix)
    return archive.read(names[0])


def prepare(news_archive,research_archive,output):
    repo=Path(__file__).resolve().parents[1];sys.path.insert(0,str(repo/'backend'))
    from app.selection_check import candidates
    from app.models.report import ReportType
    from app.services.ai_analyzer import AIAnalyzerService
    from app.services import research_hub
    from app.services.research_schema import research_fields
    from app.services.watchlist_service import get_watchlist_service
    from app.services.episode_workspace import EpisodeWorkspace,_current
    from app.services.episode_research import INSTRUCTIONS,questions
    from app.services.technical_radar import prompt as technical_prompt
    from app.services.prompt_reading import compact_market,restore_market,_json_line,input_characters
    with zipfile.ZipFile(news_archive) as archive:
        news_data=json.loads(read_member(archive,'news-acceptance.json'))
        technical=read_member(archive,'technical.json');microstructure=read_member(archive,'microstructure.json')
    with zipfile.ZipFile(research_archive) as archive:
        research_data=json.loads(archive.read('research-review.json'))
    contexts=copy.deepcopy(research_data['contexts']);at=datetime.fromisoformat(news_data['collected_at'])
    for context in contexts:
        if context.get('profile'):
            profile=context['profile'];profile.update(research_fields(profile.get('industry'),profile.get('business')))
        for row in context.get('materials',[]):
            published=research_hub.parse_date(row.get('published_at'))
            if published and published>at:raise RuntimeError('Research publication is later than the news cut')
    rows=[dict(code=c['key'].split(':')[1],market=c['key'].split(':')[0],name=c['name']) for c in contexts]
    watchlist=get_watchlist_service();watchlist.load_from_config('');watchlist.load_from_database(rows)
    watchlist.apply_research_profiles({c['key']:c['profile'] for c in contexts if c.get('profile')})
    stocks=watchlist.get_all_stocks();news=candidates(news_data)
    analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
    analyzer._edition_label='早报'
    analyzer._generation_context=(f'离线历史输入审阅：新闻截面{at.isoformat()}，研究缓存于{research_data["created_at"]}导出；'
        '仅组合已提供历史资料，不证明当时系统已掌握全部材料，不是当前实时节目，不发布。各行情只按自身来源日期使用。')
    with tempfile.TemporaryDirectory(prefix='finance-combined-input-') as temporary, \
            patch.object(research_hub.ResearchHub,'load',return_value=contexts), \
            patch.object(research_hub,'china_now',return_value=at), \
            patch('requests.sessions.Session.request',side_effect=AssertionError('offline: no HTTP')), \
            patch('httpx.Client.send',side_effect=AssertionError('offline: no HTTP')), \
            patch('httpx.AsyncClient.send',new=AsyncMock(side_effect=AssertionError('offline: no HTTP'))):
        root=Path(temporary);(root/'technical.json').write_bytes(technical);(root/'microstructure.json').write_bytes(microstructure)
        workspace=EpisodeWorkspace(news,root/'episodes',at);token=_current.set(workspace)
        try:
            finance=analyzer._prepare_news_summary(news)
            hub=research_hub.ResearchHub();research,evidence=hub.prompt(stocks,max_characters=8000)
            workspace.add(evidence);workspace.add(hub.evidence_pool(stocks))
            for key,ranges in hub.prompt_ranges.items():workspace.prepare_ranges(key,ranges,'initial_research')
            raw_market=technical_prompt(stocks,root,at)
            market=compact_market(raw_market)
            def semantic_lines(value):
                return [(_json_line(line)[:2] if _json_line(line) else line) for line in value.splitlines()]
            assert semantic_lines(restore_market(market))==semantic_lines(raw_market),'Market dictionary roundtrip changed values'
            for row in analyzer._news_briefing['initial_reading']:
                body=workspace.documents[row['id']].content
                assert all(body[a:b] in finance for a,b in row['ranges']),'Selected news fragment missing from input'
            report_prompt=analyzer._build_editorial_report_prompt(today=at.date(),report_type=ReportType.MORNING,
                is_trading_day='独立交易日历未核验，不据此推断A/H开休市',watchlist_text=json.dumps(rows,ensure_ascii=False)+'；风格：日内至数日，自选股不等于持仓。',
                market_data_text=market,finance_summary=finance+'\n\n'+research,cross_border_summary='海外资料见新闻正文，不另计独立来源。')
            first_request=report_prompt+INSTRUCTIONS+'\n研究问题：\n'+questions(stocks)
            characters=input_characters([dict(role='user',content=first_request)])
            usage=workspace.usage()
            result=dict(mode='historical_combined_input_prepared_not_sent',news_snapshot=news_data['collected_at'],research_export=research_data['created_at'],
                news_candidates=len(news),selected_news=len(analyzer._selected_evidence_news),research_views=len(evidence),
                research_source_documents=len({item.source_id for item in evidence}),research_characters=len(research),market_characters=len(market),
                market_roundtrip_verified=True,news_ranges_preserved=True,first_request_characters=characters,within_input_guard=characters<=100000,news_characters=len(finance),per_request_guard=100000,model_requests=0,http_requests=0,confirmed_sources=usage['confirmed_sources'],
                prepared_sources=usage['prepared_sources'],prepared_citation_ids=sorted(workspace.prepared),pool_views=usage['pool_count'],initial_research_reading=hub.prompt_reading,
                prompt=first_request,single_report_prompt=report_prompt+'\n本次仅单次完整报告验收，不提供取材工具；只用实际给出的阅读片段，不请求工具，不把未读部分补成事实。',limitation='Free historical assembly, not a generated report or exact reconstruction of original news ranking. No live MarketOverview refresh, independent trading calendar, EventObservations history or new source collection. Full stored pool and actual initial ranges exist; zero model reads, no quality/accuracy verdict.')
            Path(output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        finally:workspace.finish(False);_current.reset(token)
    return {key:value for key,value in result.items() if key not in {'initial_research_reading','prompt','single_report_prompt','prepared_citation_ids'}}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--news',type=Path,required=True);parser.add_argument('--research',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(prepare(args.news,args.research,args.output),ensure_ascii=False,indent=2))
