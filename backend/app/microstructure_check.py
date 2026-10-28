"""No-model acceptance of intraday observations and dated catalogue breadth."""
import argparse,asyncio,json
from .services.microstructure import MicrostructureRadar
from .services.technical_radar import ROOT
from .services.watchlist_repository import read_app_watchlist
from .services.watchlist_service import WatchlistStock


async def inspect(market_only=False):
    stocks=[]
    if not market_only:
        rows=await read_app_watchlist()
        stocks=[WatchlistStock(row['code'],row['name'],row.get('market','A')) for row in rows]
    return await asyncio.to_thread(MicrostructureRadar().collect,stocks,110)


def summary(data):
    return dict(collected_at=data.get('collected_at'),watchlist=data.get('watchlist'),
        intraday_coverage=data.get('intraday',{}).get('coverage'),
        intraday=[{key:row[key] for key in ('symbol','status','as_of','session','observations','excluded_unconfirmed_points','volume','reason') if key in row}
            for row in data.get('intraday',{}).get('instruments',[])],
        breadth=data.get('breadth'),time_alignment=data.get('a_index_breadth_time_alignment'),
        limitation=data.get('limitation'),mode='公开数据；不生成报告、不调用LLM/TTS、不写App数据库')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--saved-summary',action='store_true',help='只读已有快照，缺文件不自动重采')
    parser.add_argument('--market-only',action='store_true',help='只测指数和覆盖样本宽度，不读App自选股数据库')
    args=parser.parse_args()
    data=json.loads((ROOT/'microstructure.json').read_text(encoding='utf-8')) if args.saved_summary else asyncio.run(inspect(args.market_only))
    print(json.dumps(summary(data),ensure_ascii=False,indent=2))
