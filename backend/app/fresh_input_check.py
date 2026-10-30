"""Read-only readiness check for a newly collected episode. No model imports."""
import asyncio
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path


def local_time(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is not None:
        result = result.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
    return result


def inspect(snapshot_bytes, replay, technical, current_watchlist, now):
    data = json.loads(snapshot_bytes)
    digest = hashlib.sha256(snapshot_bytes).hexdigest()
    errors = []
    def check_time(value, label):
        try:
            stamp = local_time(value)
            if not timedelta(0) <= now - stamp <= timedelta(hours=2):
                errors.append(label + ': expired_or_future')
            return stamp
        except (ValueError, TypeError):
            errors.append(label + ': missing_or_invalid')
            return None
    started = check_time(data.get('collection_started_at'), 'collection_started_at')
    finished = check_time(data.get('collected_at'), 'collected_at')
    check_time(technical.get('collected_at'), 'technical_collected_at')
    if started and finished and started > finished:
        errors.append('collection_time_reversed')
    if data.get('full_collection') is not True:
        errors.append('full_collection_required')
    if replay.get('snapshot_sha256') != digest:
        errors.append('selection_snapshot_mismatch')
    expected = sorted([list(row) for row in current_watchlist])
    if sorted(data.get('watchlist_signature', [])) != expected:
        errors.append('collection_watchlist_mismatch')
    if sorted(technical.get('watchlist', [])) != sorted(row[0]+':'+row[1] for row in expected):
        errors.append('technical_watchlist_mismatch')
    articles = {row['id']: row for row in data.get('raw_articles', [])}
    selected = [row['id'] for row in replay.get('selection', {}).get('articles', []) if row.get('selected')]
    if not selected or len(selected) != len(set(selected)) or set(selected)-set(articles):
        errors.append('selected_articles_empty_duplicate_or_missing')
    ages = Counter()
    rows = []
    for key in selected:
        item = articles.get(key, {})
        try:
            age = now - local_time(item.get('published'))
            band = ('future' if age < timedelta(0) else 'within_24h' if age <= timedelta(hours=24)
                    else 'within_72h' if age <= timedelta(hours=72) else 'older_background')
        except (TypeError, ValueError):
            band = 'unknown'
        if band in {'future', 'unknown'}:
            errors.append('selected_publication_' + band + ':' + key)
        if not isinstance(item.get('content'), str) or not item['content'].strip():
            errors.append('selected_body_missing:' + key)
        ages[band] += 1
        rows.append(dict(id=key,title=item.get('title'),source=item.get('source'),
                         published=item.get('published'),publication_band=band))
    return dict(mode='read_only_new_collection_check',http_requests_performed=0,model_requests_performed=0,
        status='ready_for_material_review' if not errors else 'blocked',errors=errors,
        snapshot_sha256=digest,collection_started_at=data.get('collection_started_at'),
        collected_at=data.get('collected_at'),watchlist_signature=expected,
        collection_funnel=data.get('collection_funnel',{}),selected_count=len(selected),
        selected_publication_bands=dict(ages),selected_reading_scope=replay.get('selected_reading_scope',{}),
        selected_articles=rows,
        limitation='新采集不等于每篇新闻刚发布；旧背景可保留，不强制每股有新闻。ready只表示采集时间/名单/重选绑定通过，不代表事实、正文完整性或内容质量合格，不授权付费。研究缓存、行情实际交易日及来源失败另查；单期不能证明普适性。')


async def main():
    from .services.time_context import china_now
    from .services.watchlist_repository import read_app_watchlist, watchlist_signature
    root = Path(__file__).resolve().parents[1] / 'data/radar'
    result = inspect((root/'news-acceptance.json').read_bytes(),
        json.loads((root/'selection-replay.json').read_text(encoding='utf-8')),
        json.loads((root/'technical.json').read_text(encoding='utf-8')),
        watchlist_signature(await read_app_watchlist()), china_now())
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result


if __name__ == '__main__':
    result = asyncio.run(main())
    raise SystemExit(0 if result['status']=='ready_for_material_review' else 1)
