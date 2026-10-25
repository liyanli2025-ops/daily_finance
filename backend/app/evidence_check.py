"""Inspect a saved full collection, without collection, model or audio requests."""
import argparse
import asyncio
from datetime import datetime
import json
from pathlib import Path

from .models.news import News
from .services.evidence_audit import audit
from .services.research_hub import ResearchHub, save_json
from .services.technical_radar import ROOT
from .services.watchlist_repository import read_app_watchlist
from .services.watchlist_service import WatchlistStock


async def inspect(path):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('full_collection') is not True:
        raise ValueError('需要完整采集快照，不能用正文预览冒充原文验收')
    news=[News(id=row['id'],title=row['title'],content=row['content'],source=row['source'],
        source_url=row['url'],published_at=datetime.fromisoformat(row['published']),
        market_impact=row.get('association') or '') for row in data['raw_articles']]
    ids={row['id'] for row in data['selection']['articles'] if row.get('selected')}
    by_id={row.id:row for row in news}
    if ids-set(by_id):
        raise ValueError('已选文章缺少采集文本，无法验收')
    records=await read_app_watchlist()
    stocks=[WatchlistStock(row['code'],row['name'],row['market']) for row in records]
    profiles={row['key']:row['profile'] for row in ResearchHub().load(stocks) if row.get('profile')}
    result=audit(news,[by_id[key] for key in sorted(ids)],stocks,profiles)
    source_inventory=data.get('source_inventory')
    if not source_inventory:
        from .services.source_inventory import inventory
        source_inventory=inventory(news,[],datetime.fromisoformat(data['collected_at']),data.get('hours',72))
        source_inventory.update(measurement_scope='retained_old_snapshot_only',original_retrieved_count='unknown',
            limitation='旧快照只保留当时返回的文本，可能已经去重；不能还原原始抓取总数、去重损失和HTTP状态。以下仅统计旧快照留存池，不代表今天重新抓取。')
    result.update(snapshot_collected_at=data.get('collected_at'),
        collection_funnel=data.get('collection_funnel',{}),
        source_inventory=source_inventory,
        scope='只回放已保存的完整采集文本；按当前App自选股和缓存画像检查，未刷新新闻/行情/研报，无模型或音频请求')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--snapshot',default=str(ROOT/'news-acceptance.json'))
    args=parser.parse_args()
    result=asyncio.run(inspect(args.snapshot))
    target=ROOT/'evidence-audit.json'
    save_json(target,result)
    print(json.dumps(dict(result,saved_to=str(target)),ensure_ascii=False,indent=2))
