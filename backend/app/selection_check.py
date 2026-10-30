"""Replay the saved admitted article pool: no network, LLM, TTS or App writes."""
import argparse
import asyncio
from datetime import datetime
import hashlib
import json
from pathlib import Path

from .models.news import News
from .services.ai_analyzer import AIAnalyzerService
from .services.research_hub import save_json
from .services.technical_radar import ROOT
from .services.time_context import china_now
from .services.watchlist_repository import refresh_app_watchlist


def candidates(data, restore_market_events=False):
    if data.get('full_collection') is not True:
        raise ValueError('需要已有完整采集快照；本工具不会启动采集')
    admitted={row['id'] for row in data['selection']['articles']}
    originals={row['id']:row for row in data['raw_articles']}
    if not admitted or admitted-set(originals):
        raise ValueError('原采集候选缺少正文，停止重选')
    result=[]
    keys=set(admitted)
    if restore_market_events:
        keys.update(originals)
    for key in sorted(keys):
        row=originals[key]
        item=News(id=key,title=row['title'],content=row['content'],source=row['source'],
            source_url=row['url'],published_at=datetime.fromisoformat(row['published']),
            market_impact=row.get('association') or '',category=row.get('category'),
            related_stocks=row.get('related_stocks') or [],importance_score=row.get('importance_score',.5),news_type=row.get('news_type','finance'))
        if key not in admitted:
            from .services.market_coverage import cross_category_reason
            from .services.time_context import CHINA_TIME
            from datetime import timedelta
            at=datetime.fromisoformat(data['collected_at'])
            published=item.published_at
            if at.tzinfo is not None:at=at.astimezone(CHINA_TIME).replace(tzinfo=None)
            if published.tzinfo is not None:published=published.astimezone(CHINA_TIME).replace(tzinfo=None)
            if not cross_category_reason(item) or not timedelta()<=at-published<=timedelta(hours=data.get('hours',24)):
                continue
        result.append(item)
    return result


async def inspect(root=None,restore_market_events=False):
    root=Path(root) if root is not None else ROOT
    raw=(root/'news-acceptance.json').read_bytes()
    data=json.loads(raw)
    news=candidates(data,restore_market_events)
    await refresh_app_watchlist()  # App read plus process-local configuration only.
    analyzer=AIAnalyzerService.__new__(AIAnalyzerService)
    report_input=analyzer._prepare_news_summary(news)
    selection=analyzer._news_briefing
    old={row['id']:row for row in data['selection']['articles'] if row.get('selected')}
    new={row.id:row for row in analyzer._selected_evidence_news}
    from .services.news_briefing import editorial_exclusion
    from .services.watchlist_service import get_watchlist_service
    stocks=get_watchlist_service().get_all_stocks()
    result=dict(checked_at=china_now().isoformat(),snapshot_collected_at=data['collected_at'],
        snapshot_sha256=hashlib.sha256(raw).hexdigest(),candidate_count=len(news),
        previous_selected=len(old),selected_count=len(new),
        removed=[dict(id=key,title=row['title'],reason=editorial_exclusion(next(n for n in news if n.id==key),stocks)
            or '排序、背景配额或去重后未入选') for key,row in old.items() if key not in new],
        added=[dict(id=key,title=row.title) for key,row in new.items() if key not in old],
        selected_titles=[row.title for row in new.values()],
        restored_market_events=restore_market_events,market_coverage=selection.get('market_coverage',{}),
        selected_editorial_counts=selection['selected_editorial_counts'],
        selected_reading_scope=selection['selected_reading_scope'],excluded_by_reason=selection['excluded_by_reason'],
        per_stock=selection.get('evidence_audit',{}).get('per_stock',[]),
        limitation='默认重选已准入候选；显式restore时仅补回原始池中有金融/经营/传导线索且在原窗口内的材料，仍走正文准入；不重新抓取；旧快照未保存分类/重要性时使用明确默认值，不能宣称完全还原原排序。不改变原快照或行情时效，不代表正文事实已核实。')
    # Save a separate diagnostic, never silently replace the accepted source snapshot.
    save_json(root/'selection-replay.json',dict(result,selection=selection,news_input=report_input,
        selection_context=getattr(analyzer,'_selection_context',{})))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--snapshot-root',type=Path,default=ROOT)
    parser.add_argument('--restore-market-events',action='store_true',help='从当前快照原始池恢复被类型/地区筛选遗漏的市场事件；不联网')
    args=parser.parse_args()
    print(json.dumps(asyncio.run(inspect(args.snapshot_root,args.restore_market_events)),ensure_ascii=False,indent=2))
