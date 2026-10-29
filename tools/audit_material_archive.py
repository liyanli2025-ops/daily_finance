"""Read an exported material ZIP offline; no extraction, APIs, DB or models."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import zipfile


def inspect_archive(path):
    path=Path(path)
    with zipfile.ZipFile(path) as archive:
        entries=archive.infolist();names=[item.filename for item in entries]
        if len(names)!=len(set(names)):raise ValueError('duplicate_archive_entry')
        if sum(item.file_size for item in entries)>50*1024*1024:raise ValueError('archive_too_large')
        allowed=('news-acceptance.json','technical.json','microstructure.json')
        data={name:json.loads(archive.read(name)) if name in names else {} for name in allowed}
    news=data['news-acceptance.json']
    if not isinstance(news.get('raw_articles'),list):raise ValueError('raw_articles_missing')
    raw=news['raw_articles'];selection=news.get('selection',{});rows=selection.get('articles',[])
    selected=[row for row in rows if row.get('selected')];by_id={row['id']:row for row in raw}
    inventory=news.get('source_inventory',{});scopes=Counter()
    for row in inventory.get('source_rows',[]):scopes.update(row.get('reading_scopes',{}))
    companies={}
    for row in rows:
        for association in row.get('associations',[]):
            stock=association['stock'];record=companies.setdefault(stock,dict(company_specific_candidates=0,company_specific_selected=0,body_mentions=0))
            if association.get('focus')=='company_specific':
                record['company_specific_candidates']+=1
                record['company_specific_selected']+=bool(row.get('selected'))
            elif association.get('level')=='company_mention':record['body_mentions']+=1
    # Include a requested stock even if no association row was found.
    for stock in news.get('coverage',{}).get('per_stock',{}):
        companies.setdefault(stock,dict(company_specific_candidates=0,company_specific_selected=0,body_mentions=0))
    errors=Counter()
    for source in news.get('coverage',{}).get('sources',{}).values():
        for error in source.get('errors',[]):
            category=('explicit_paused' if error.get('error')=='RetiredSourceError' else
                'cached_wrapper_diagnostic' if str(error.get('reason','')).startswith('cached_primary_failure:') else
                'cause_not_retained' if error.get('reason')=='cause_not_retained_no_retest' else 'other')
            errors[category]+=1
    technical=data['technical.json'];micro=data['microstructure.json']
    return dict(archive_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        collected_at={name:value.get('collected_at') for name,value in data.items()},
        funnel=news.get('collection_funnel'),raw_records=len(raw),distinct_urls=len({r.get('url') for r in raw}),
        raw_scope_labels=dict(scopes),admitted_finance_candidates=len(rows),
        selected_count=len(selected),initial_news_input_characters=len(news.get('news_input','')),
        article_copy_groups=len(inventory.get('exact_copy_groups',[])),same_url_groups=len(inventory.get('same_article_url_groups',[])),
        source_diagnostic_entries=dict(errors),company_focus=companies,
        source_inventory=inventory.get('source_rows',[]),
        selected=[dict(id=row['id'],title=row['title'],source=row.get('source'),url=row.get('url'),
            reading_scope=row.get('reading_scope'),captured_characters=len(by_id.get(row['id'],{}).get('content','')),
            associations=row.get('associations')) for row in selected],
        technical_coverage=technical.get('coverage'),
        technical_gaps=[dict(symbol=r.get('symbol'),reason=r.get('reason')) for r in technical.get('instruments',[]) if r.get('status')!='ok'],
        breadth=micro.get('breadth'),
        limitations=['阅读范围、关联等级及漏斗来自快照记录，不等于独立事实核验或投资价值评分。',
            '文章去重不是事件去重，历史补回不等于超出本期发布时间窗口。',
            '缓存层错误名称不能证明本次是否发了HTTP；明确暂停项才可确认该路由未重探。',
            '这是采集快照，不能证明模型已经收到或读完所有正文；研究缓存不在此包中。'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('archive',type=Path)
    print(json.dumps(inspect_archive(parser.parse_args().archive),ensure_ascii=False,indent=2))
