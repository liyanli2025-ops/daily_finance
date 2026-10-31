"""Replay old evidence to measure new prompt sizes, with no model/network calls."""
import argparse
import asyncio
from datetime import datetime
import json
from pathlib import Path

from .selection_check import inspect,candidates
from .services.ai_analyzer import AIAnalyzerService
from .services.episode_research import initial_prompt
from .services.event_observations import EventObservations
from .services.prompt_reading import input_characters,compact_market
from .services.research_hub import ResearchHub
from .services.technical_radar import ROOT
from .services.watchlist_service import get_watchlist_service
from .models.report import ReportType


async def check(case_path,root=None):
    root=Path(root) if root is not None else ROOT
    case=json.loads(Path(case_path).read_text(encoding='utf-8'))
    await inspect(root)
    replay=json.loads((root/'selection-replay.json').read_text(encoding='utf-8'))
    snapshot=json.loads((root/'news-acceptance.json').read_text(encoding='utf-8'))
    ids={row['id'] for row in replay['selection']['articles'] if row.get('selected')}
    news=[row for row in candidates(snapshot) if row.id in ids]
    stocks=get_watchlist_service().get_all_stocks()
    research,_=ResearchHub().prompt(stocks,max_characters=8000)
    finance=replay['news_input']+'\n\n'+EventObservations().context(news)+'\n\n'+research
    old_market=case.get('market_evidence','')
    market=compact_market(old_market)
    analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
    analyzer._generation_context=case.get('generation_context','')
    analyzer._edition_label='历史即时更新回放（非当前实时）'
    draft=analyzer._build_editorial_report_prompt(today=datetime.fromisoformat(snapshot['collected_at']).date(),
        report_type=ReportType.MORNING,is_trading_day=True,watchlist_text='',market_data_text=market,
        finance_summary=finance,cross_border_summary='')
    draft=initial_prompt(draft,stocks)
    review=analyzer._build_review_prompt(case['content']+'\n元数据：'+json.dumps(case.get('metadata',{}),ensure_ascii=False),
        market,finance,'',ReportType.MORNING)
    sizes={task:input_characters([dict(role='user',content=content)]) for task,content in [('analysis',draft),('review',review)]}
    return dict(mode='历史快照成本回放，无行情刷新、LLM、TTS或App写入；单独更新selection-replay诊断',
        snapshot_collected_at=snapshot['collected_at'],case_file=Path(case_path).name,
        old_finance_characters=len(case.get('finance_evidence','')),new_finance_characters=len(finance),
        reused_old_market_characters=len(old_market),new_market_characters=len(market),initial_articles=len(news),
        request_characters=sizes,per_request_character_guard=100000,
        headroom_characters={task:100000-size for task,size in sizes.items()},
        would_stop_before_http={task:size>100000 for task,size in sizes.items()},
        limitation='这是固定旧市场文本的字符预检，不是token计价或真实模型验收。正式请求还会加入本期时点、取材回复等，网关逐次重新检查；全文仍保留在工作集。')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--case',required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(asyncio.run(check(args.case)),ensure_ascii=False,indent=2))
