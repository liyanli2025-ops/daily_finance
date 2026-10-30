"""Public-data acceptance; never generates a report or audio or calls a model."""
import argparse
import asyncio
import json
from pathlib import Path
from .services.news_collector import NewsCollectorService
from .services.event_observations import EventObservations
from .services.ai_analyzer import AIAnalyzerService
from .services.research_hub import save_json
from .services.technical_radar import ROOT
from .services.news_briefing import briefing
from .services.time_context import china_now


def snapshot_article(item):
    """Preserve ranking/association inputs, not just title/body, for replay."""
    return dict(id=item.id,title=item.title,source=item.source,url=item.source_url,
        published=item.published_at.isoformat(),content=item.content,association=item.market_impact,
        importance_score=item.importance_score,related_stocks=item.related_stocks,
        category=item.category,news_type=getattr(item.news_type,'value',item.news_type))


def summarize_saved(root=None):
    """Compact read-only inspection; never re-fetches or generates anything."""
    root=Path(root) if root is not None else ROOT
    data=json.loads((root/'news-acceptance.json').read_text(encoding='utf-8'))
    inventory=data.get('source_inventory',{})
    coverage=data.get('coverage',{})
    selection=data.get('selection',{})
    selected=[row for row in selection.get('articles',[]) if row.get('selected')]
    try:technical=json.loads((root/'technical.json').read_text(encoding='utf-8'))
    except FileNotFoundError:technical={}
    try:microstructure=json.loads((root/'microstructure.json').read_text(encoding='utf-8'))
    except FileNotFoundError:microstructure={}
    sources=[]
    for row in inventory.get('source_rows',[]):
        state=row.get('feed_status') or {}
        sources.append(dict(source=row['source'],window=row.get('window_texts'),
            title_only=row.get('title_only'),median_characters=row.get('median_characters'),
            reading_scopes=row.get('reading_scopes'),status=state.get('status'),
            error=state.get('error'),reason=state.get('reason')))
    return dict(mode='只读已保存快照，不重新采集、不调用模型；快照时间决定本次结果的时效',
        collected_at=data.get('collected_at'),funnel=data.get('collection_funnel'),sources=sources,
        copy_groups=len(inventory.get('exact_copy_groups',[])),
        same_url_groups=len(inventory.get('same_article_url_groups',[])),
        media={name:coverage.get(name) for name in ('article_candidates','article_read','detail_budget','per_stock')},
        source_errors={name:dict(status=row.get('status'),read=row.get('read'),errors=row.get('errors',[])[:2])
            for name,row in coverage.get('sources',{}).items()},
        source_pauses={name:dict(count=len(row.get('paused_routes',[])),details=row.get('paused_routes',[])[:2])
            for name,row in coverage.get('sources',{}).items() if row.get('paused_routes')},
        selected_count=len(selected),selected_titles=[row['title'] for row in selected],
        selected_reading_scope=selection.get('selected_reading_scope'),
        selected_editorial_counts=selection.get('selected_editorial_counts'),
        microstructure=dict(collected_at=microstructure.get('collected_at'),
            intraday_coverage=microstructure.get('intraday',{}).get('coverage'),
            breadth=microstructure.get('breadth'),time_alignment=microstructure.get('a_index_breadth_time_alignment')),
        technical=dict(collected_at=technical.get('collected_at'),coverage=technical.get('coverage'),
            weekly_coverage=technical.get('weekly_coverage'),
            breadth=technical.get('breadth'),
            gaps=[dict(symbol=row.get('symbol'),reason=row.get('reason',row.get('error')))
                for row in technical.get('instruments',[]) if row.get('status')!='ok']))


async def inspect(hours,full_news=False):
    from .services.watchlist_repository import refresh_app_watchlist, watchlist_signature, assert_watchlist_current
    started = china_now()
    service = await refresh_app_watchlist()
    watchlist = watchlist_signature(service.get_all_stocks())
    # Avoid NewsCollector initialization (sentiment/model loading not needed).
    if full_news:
        collector=NewsCollectorService(sentiment=False)
        try:
            articles=await asyncio.wait_for(collector.collect_all(hours),300)
            from .services.market_coverage import market_candidates
            finance=market_candidates(articles)
            eligible=collector.filter_china_related(finance)
            relaxed=len(eligible)<20 and len(finance)>len(eligible)
            if relaxed:eligible=finance
        finally:
            await collector.client.aclose()
    else:
        collector=NewsCollectorService.__new__(NewsCollectorService)
        articles=await collector._collect_radar_news(hours)
        eligible=articles;relaxed=False
        EventObservations().observe(articles,dict(scope='独立公开雷达验收',media=collector._radar_coverage))
    analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
    analyzer._news_briefing=briefing([],[],{})
    analyzer._selected_evidence_news=[]
    report_input=analyzer._prepare_news_summary(eligible)
    selection=analyzer._news_briefing
    raw=getattr(collector,'_raw_news_snapshot',None)
    if not isinstance(raw,list):raw=articles
    source_inventory=getattr(collector,'_source_inventory',{})
    if not isinstance(source_inventory,dict):source_inventory={}
    await assert_watchlist_current(watchlist)
    snapshot=ROOT/'news-acceptance.json'
    save_json(snapshot,dict(collection_started_at=started.isoformat(),watchlist_signature=watchlist,
        collected_at=china_now().isoformat(),hours=hours,full_collection=full_news,china_filter_relaxed=relaxed,
        raw_articles=[snapshot_article(item) for item in raw],
        selection_context=getattr(analyzer,'_selection_context',{}),
        selection=selection,news_input=report_input,
        collection_funnel=getattr(collector,'_collection_funnel',{}) if isinstance(getattr(collector,'_collection_funnel',{}),dict) else {},
        source_inventory=source_inventory,
        coverage=getattr(collector,'_radar_coverage',{})))
    technical=getattr(collector,'_technical_snapshot',{})
    for row in technical.get('instruments',[]):
        row.pop('bars',None)
    return dict(scope='当前App自选股+全市场公开原文+已完成日线；仅写私有缓存及观察历史，无模型/TTS费用',
        full_collection=full_news,raw_articles=len(articles),eligible_finance=len(eligible),china_filter_relaxed=relaxed,
        selection_summary={key:value for key,value in selection.items() if key!='articles'},
        source_inventory=source_inventory,
        selected_articles=[row for row in selection['articles'] if row['selected']],snapshot_path=str(snapshot),
        media=getattr(collector,'_radar_coverage',{}),technical=technical,
        articles=[dict(id=item.id,title=item.title,url=item.source_url,published=item.published_at.isoformat(),
                       association=item.market_impact,body_preview=item.content[:400])
                  for item in (analyzer._selected_evidence_news if full_news else articles)],
        observations=EventObservations().context(articles))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--hours',type=int,default=24,choices=range(1,169),metavar='1..168')
    parser.add_argument('--full-news',action='store_true',help='完整生产新闻采集与财经选题路径，跳过情感模型、分析模型和音频')
    parser.add_argument('--saved-summary',action='store_true',help='只读已有快照并输出精简摘要，不触发任何采集或模型请求')
    args=parser.parse_args()
    print(json.dumps(summarize_saved() if args.saved_summary else asyncio.run(inspect(args.hours,args.full_news)),ensure_ascii=False,indent=2))
