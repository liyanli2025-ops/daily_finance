"""python -m app.media_check --hours 72: public news only, zero LLM/TTS calls."""
import argparse
import asyncio
import json

from .services.media_sources import MediaCollector
from .services.research_hub import ResearchHub
from .services.watchlist_repository import read_app_watchlist
from .services.watchlist_service import WatchlistStock


async def inspect(hours=24):
    stocks=[WatchlistStock(**row) for row in await read_app_watchlist()]
    profiles={row['key']:row['profile'] for row in ResearchHub().load(stocks) if row.get('profile')}
    articles,coverage=await asyncio.to_thread(MediaCollector().collect,stocks,profiles,hours)
    return dict(scope='读取当前App自选股、公开媒体检索及原文；无模型/TTS请求，无数据库写入，写入私有新闻缓存。',
        watchlist=[dict(code=stock.code,name=stock.name,market=stock.market) for stock in stocks],
        missing_business_profiles=[stock.code for stock in stocks
            if str(getattr(stock.market,'value',stock.market))+':'+stock.code not in profiles],
        coverage=coverage,articles=[dict(title=item.title,published_at=item.published_at.isoformat(),
            source=item.source,url=item.source_url,related_stocks=item.related_stocks,
            association=item.market_impact,body_characters=len(item.content),body_preview=item.content[:600]) for item in articles])


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--hours',type=int,default=24)
    args=parser.parse_args()
    if not 1<=args.hours<=168:
        parser.error('--hours must be between 1 and 168')
    print(json.dumps(asyncio.run(inspect(args.hours)),ensure_ascii=False,indent=2))
