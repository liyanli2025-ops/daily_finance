"""python -m app.source_check: real App watchlist feeds, no model/audio/DB writes."""
import asyncio
import json

from .services.watchlist_repository import read_app_watchlist
from .services.watchlist_service import WatchlistStock
from .services.watchlist_sources import fetch_watchlist_quotes, fetch_company_announcements, fetch_sina_stock_news


async def inspect(research=False, hours=24):
    if type(hours) is not int or not 1<=hours<=168:
        raise ValueError('新闻检查窗口必须为1至168小时')
    stocks = [WatchlistStock(**row) for row in await read_app_watchlist()]
    quotes = await asyncio.to_thread(fetch_watchlist_quotes, stocks)
    semaphore = asyncio.Semaphore(3)
    async def check(stock):
        async with semaphore:
            try:
                try:
                    items, status = await asyncio.to_thread(fetch_company_announcements, stock, hours=hours)
                except Exception as error:
                    items, status = [], dict(status='failed', error=type(error).__name__)
                try:
                    news, news_status = await asyncio.to_thread(fetch_sina_stock_news, stock, hours=hours)
                except Exception as error:
                    news, news_status = [], dict(status='failed', error=type(error).__name__)
                return dict(code=stock.code, name=stock.name, market=stock.market,
                            quote=quotes.get(stock.code), announcements=status,
                            news=news_status,
                            articles=[dict(id=item.id, title=item.title, published_at=item.published_at.isoformat(),
                                           url=item.source_url, body_characters=len(item.content)) for item in items+news])
            except Exception as error:
                return dict(code=stock.code, name=stock.name, quote=quotes.get(stock.code),
                            announcements=dict(status='failed', error=type(error).__name__))
    result = dict(scope='实时接口检查：读取App自选股，不调用模型、不合成音频、不写数据库。'
                      '本地/服务器网络可能不同；没有近期公告不等于没有其他新闻。',
                news_window_hours=hours,
                stocks=await asyncio.gather(*(check(stock) for stock in stocks)))
    if research:
        from .services.research_hub import ResearchHub
        inventory = await ResearchHub().collect(stocks)
        # Keep bodies in the private local research cache; diagnostics show titles,
        # dates, URLs and reading status rather than dumping long PDF text to logs.
        for context in inventory['stocks']:
            for material in context.get('materials', []):
                if material.get('kind') in {'primary_notice','operating_release','industry_observation'}:
                    material['body_preview'] = material.get('body','')[:900]
                material['body_characters'] = len(material.pop('body', ''))
        result['research'] = inventory
    return result


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--research',action='store_true')
    parser.add_argument('--hours',type=int,default=24)
    args=parser.parse_args()
    if not 1<=args.hours<=168:
        parser.error('--hours must be between 1 and 168')
    print(json.dumps(asyncio.run(inspect(research=args.research,hours=args.hours)), ensure_ascii=False, indent=2))
