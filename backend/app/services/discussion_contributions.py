"""Bounded, text-free source usage receipts; usage is NOT useful information."""
from collections import Counter
from datetime import datetime,timedelta
from pathlib import Path
import hashlib,json

from .research_hub import save_json
from .time_context import china_now

ROOT=Path(__file__).resolve().parents[2]/'data'/'radar'/'discussion-contributions'
OWNER='finance-discussion-contribution-v1'


def record(workspace,usage,success,root=None,now=None):
    sources=Counter(item.source for item in workspace.documents.values()
        if (item.source or '').startswith('公开参与者讨论-'))
    if not sources:return
    root=(Path(root) if root is not None else ROOT).resolve();now=now or china_now()
    # One file per episode avoids concurrent read/modify/write counters. Keep
    # only counts/statuses, no usernames, quotations, news facts or author ranks.
    prepared=Counter(row['source'] for row in usage['sources']
        if row.get('prepared_ranges') and row.get('source') in sources)
    confirmed=Counter(row['source'] for row in usage['sources']
        if row.get('confirmed_ranges') and row.get('source') in sources)
    cited=Counter(row['source'] for row in usage['sources']
        if row.get('cited') and row.get('source') in sources)
    result=dict(owner=OWNER,collected_at=now.isoformat(),generation_success=success,
        sources=[dict(source=s,pool_documents=sources[s],prepared_documents=prepared[s],
            pool_statement_documents=sum(item.source==s and item.id.startswith('discussion-statement-') for item in workspace.documents.values()),
            confirmed_delivery_documents=confirmed[s],reported_citations=cited[s],
            value_review='not_reviewed') for s in sources],
        limitation='只记录存储、提供范围与报告引用；不证明模型关注、事实准确、增量有用或预测有效。不据抓取量/引用量自动升降频；需多期贡献复核。')
    key=hashlib.sha256(workspace.path.name.encode()).hexdigest()[:24]
    save_json(root/('contribution-'+key+'.json'),result)
    prune(root,now)


def prune(root=None,now=None):
    root=(Path(root) if root is not None else ROOT).resolve();now=now or china_now()
    if not root.is_dir():return
    for p in root.glob('contribution-*.json'):
        if p.is_symlink() or p.resolve().parent!=root:continue
        try:
            row=json.loads(p.read_text(encoding='utf-8'))
            if row.get('owner')==OWNER and datetime.fromisoformat(row['collected_at'])<now-timedelta(days=7):p.unlink()
        except (ValueError,KeyError,TypeError,OSError):continue


def summary(root=None,now=None):
    root=Path(root) if root is not None else ROOT;now=now or china_now();rows=[]
    if root.is_dir():
        for p in root.glob('contribution-*.json'):
            if p.is_symlink():continue
            try:
                r=json.loads(p.read_text(encoding='utf-8'))
                if r.get('owner')==OWNER and now-timedelta(days=7)<=datetime.fromisoformat(r['collected_at'])<=now:rows.append(r)
            except (ValueError,KeyError,TypeError,OSError):continue
    return dict(episodes=len(rows),receipts=rows,automatic_frequency_changes=False,
        limitation='仅近7日无正文使用记录，不是来源有效率或可信度排名；人工复核不足时不自动封源或追捧高产账号。')
