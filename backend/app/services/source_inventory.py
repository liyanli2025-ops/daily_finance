"""Inventory the complete retrieved pool; counts do not establish news value."""
from collections import Counter,defaultdict
from statistics import median
from urllib.parse import urlsplit

from .evidence_audit import normalized_body,title_only
from .news_archive import identity
from .news_quality import reading_scope,excluded_reason
from .news_selection import within_window
from .event_observations import canonical


def domain(url):
    try:return urlsplit(url or '').hostname
    except ValueError:return None


def inventory(retrieved,history,now,hours,rss=None,history_status=None):
    rows=[]
    sources=sorted({item.source for item in retrieved+history}|set(rss or {}))
    for source in sources:
        fresh=[item for item in retrieved if item.source==source]
        restored=[item for item in history if item.source==source]
        current=[item for item in fresh if within_window(item,now,hours)]
        text=[item for item in current+restored]
        lengths=[len(normalized_body(item)) for item in text]
        hashes={identity(item)[2] for item in text}
        rows.append(dict(source=source,retrieved=len(fresh),retrieved_in_window=len(current),
            history_restored=len(restored),window_texts=len(text),
            reading_scopes=dict(Counter(reading_scope(item) for item in text)),
            news_types=dict(Counter(str(getattr(item.news_type,'value',item.news_type)) for item in text)),
            title_only=sum(title_only(item) for item in text),
            admission_exclusions=dict(Counter(reason for item in text if (reason:=excluded_reason(item)))),
            median_characters=median(lengths) if lengths else None,
            distinct_texts=len(hashes),
            article_domains=sorted({domain(item.source_url) for item in text if domain(item.source_url)}),
            feed_status=(rss or {}).get(source),
            publication_min=min((item.published_at.isoformat() for item in text),default=None),
            publication_max=max((item.published_at.isoformat() for item in text),default=None)))
    bodies=defaultdict(list);urls=defaultdict(list)
    for item in retrieved+history:
        if within_window(item,now,hours):
            entry=dict(id=item.id,source=item.source,url=item.source_url)
            try:url=canonical(item.source_url)
            except ValueError:url=None
            if url:urls[url].append(entry)
            if len(normalized_body(item))>=80:bodies[normalized_body(item)].append(entry)
    return dict(retrieved=len(retrieved),history_restored=len(history),requested_hours=hours,
        source_rows=rows,history=history_status or {},
        exact_copy_groups=[items for items in bodies.values() if len(items)>1],
        same_article_url_groups=[items for items in urls.values() if len(items)>1],
        coverage_status='sampled_not_complete',
        limitation='检查整个采集池，包含非财经材料；来源名称/文章域名不是独立一手来源数量。相同文本仅供保守去重，不同文本仍可能转载同一事件。RSS长度不证明全文；样本数量不证明重要信息已覆盖。')
