"""Bounded public-original observation; no LLM, TTS, financial PDFs or App DB writes."""
import asyncio
from .media_sources import MediaCollector
from .event_observations import EventObservations
from .policy_sources import PolicyCollector
from .news_archive import NewsArchive
from .public_news_sources import PublicNewsCollector
from .overseas_sources import OverseasCollector


async def sample():
    from .material_lifecycle import prune_material_caches
    await asyncio.to_thread(prune_material_caches)
    # Capture RSS snapshots between editions too. These remain excerpts and
    # never become full text merely because they were archived.
    from .news_collector import NewsCollectorService
    collector=NewsCollectorService(sentiment=False)
    try:
        results=await asyncio.gather(*(collector._collect_rss(feed) for feed in collector.rss_feeds),return_exceptions=True)
    finally:
        await collector.client.aclose()
    rss=[item for result in results if isinstance(result,list) for item in result]
    # Save RSS before the remaining public sources, so a later failure cannot
    # discard an already completed sample.
    try:
        await asyncio.to_thread(NewsArchive().save,rss,dict(rss=collector._rss_coverage),'hourly_rss')
    except Exception as error:
        print('[小时RSS历史] 保存失败：'+type(error).__name__,flush=True)
    # Intentionally independent of watchlists. Limited provider scope is explicit.
    media_result,policy_result,direct_result,overseas_result=await asyncio.gather(
        asyncio.to_thread(MediaCollector().collect,[],{},24,25),
        asyncio.to_thread(PolicyCollector().collect,24,25),
        asyncio.to_thread(PublicNewsCollector().collect,[],{},24,30),
        asyncio.to_thread(OverseasCollector().collect,24,30),return_exceptions=True)
    articles=[];coverage={'sources':{}}
    for name,result in [('media',media_result),('policy',policy_result),('direct_publishers',direct_result),('overseas',overseas_result)]:
        if isinstance(result,Exception):
            coverage['sources'][name]=dict(status='failed',read=0,errors=[dict(error=type(result).__name__)])
        else:
            originals,status=result
            articles.extend(originals)
            coverage['sources'].update({('overseas_'+key if name=='overseas' else key):value for key,value in status.get('sources',{}).items()})
    await asyncio.to_thread(EventObservations().observe,articles,dict(
        scope='小时采样：列明国内直连媒体、交易所/发改委、见闻/时报与央行/证监会栏目；有限正文样本',media=coverage))
    await asyncio.to_thread(NewsArchive().save,articles,coverage,'hourly_originals')
    print(f'[全市场观察采样] 原文={len(articles)}；不调用模型；来源状态={coverage.get("sources",{})}',flush=True)
