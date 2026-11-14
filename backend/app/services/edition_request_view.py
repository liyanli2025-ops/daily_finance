"""Bounded assessment catalogue, with whole source bodies kept verbatim.

Original URLs, snippets and executed queries remain in the durable run. The
assessment index is explicitly a headline locator, not another news source.
"""
import json
from copy import deepcopy
from urllib.parse import urlsplit

CODEC_KEYS = ('candidates','candidate_columns','candidate_shared','candidate_codec')


def candidates_from(value):
    if 'candidate_columns' not in value:
        return deepcopy(value.get('candidates',{}))
    def decode(x):
        if isinstance(x,dict):
            if set(x)=={'$ref'}:return decode(value['candidate_shared'][x['$ref']])
            return {k:decode(v) for k,v in x.items()}
        if isinstance(x,list):return [decode(v) for v in x]
        return x
    columns=value['candidate_columns']
    return {cid:dict(zip(columns[:-1],row[:-1]),**decode(row[-1]))
            for cid,row in value['candidates'].items()}


def assessment_index(value):
    from .edition_context import candidate_packet
    result=deepcopy(value);rows=candidates_from(value)
    # All candidates already went through the agenda. Keep every title/time,
    # origin and non-default warning, issuer identity and company association.
    for row in rows.values():
        row['snippet']=None
        row.pop('snippet_note',None)
        links=row.pop('search_links',[])
        scopes=sorted({link['scope'] for link in links if link.get('scope')})
        if scopes:row['associated_scopes']=scopes
        origin=urlsplit(row['url'])
        row['url']=origin.scheme+'://'+origin.netloc
        if row.get('reading_status') in {'metadata_only','search_snippet_not_body'}:
            row.pop('reading_status')
    for key in CODEC_KEYS:result.pop(key,None)
    index=candidate_packet(rows)
    if 'candidate_columns' in index:
        index['candidate_columns'][1]='source_origin'
    else:
        for row in index['candidates'].values():row['source_origin']=row.pop('url')
    if 'candidate_codec' in index:
        index['candidate_codec']='候选数组按candidate_columns列序读取，attributes内单独的{"$ref":n}等于candidate_shared[n]，可嵌套；本阶段仅标题索引，完整资料仍在本地。'
    result.update(index)
    result['candidate_view_note']=('本阶段为已选题后的标题索引：全部候选ID、标题、站点、日期及特殊警示保留。'
        'source_origin仅为站点，不是文章地址；完整URL、旧摘要及执行查询已在选题阶段提供并保存在本地，'
        '此处不重复发送。正文按reading_limit与provided_original_ranges说明阅读范围，完整原文在本地保留；未读候选需按candidate_id提出补读，不得据标题确认事实。')
    tables={}
    for name in ('change_coverage','company_questions','read_receipts'):
        records=result.get(name)
        if not isinstance(records,list) or not records or any(not isinstance(r,dict) or 'attributes' in r for r in records):
            continue
        columns=sorted(set.intersection(*(set(r) for r in records)))
        packed=[[r[k] for k in columns]+[{k:v for k,v in r.items() if k not in columns}] for r in records]
        if len(json.dumps(packed,ensure_ascii=False))+len(json.dumps(columns)) < len(json.dumps(records,ensure_ascii=False)):
            result[name]=packed;tables[name]=columns+['attributes']
    if tables:
        result['record_columns']=tables
        result['record_table_note']='record_columns指定同名数组每行的列顺序；末列attributes合并为额外字段。仅无损去重字段名，所有记录及原值保留。'
    return result
