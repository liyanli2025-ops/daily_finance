"""Whole-pool discovery metadata and bounded initial reading, no model calls."""
from collections import defaultdict
import json

BEGIN='@@NEWS_DISCOVERY_BEGIN'
END='@@NEWS_DISCOVERY_END'


def catalogue(items, stocks):
    from .news_quality import reading_scope
    from .news_briefing import company_reporting_event,regulatory_population_key
    from .editorial_value import statistical_event_key
    from .event_observations import canonical
    references={};groups=defaultdict(list);events={};event_refs={}
    reserved={item.id for item in items};number=0
    for item in sorted(items,key=lambda row:row.id):
        number+=1
        ref='C'+str(number).zfill(4)
        while ref in reserved:
            number+=1;ref='C'+str(number).zfill(4)
        references[ref]=item.id
        event=(company_reporting_event(item,stocks) or regulatory_population_key(item)
               or statistical_event_key(item))
        if event is None:event=('url',canonical(item.source_url)) if item.source_url else ('id',item.id)
        key=json.dumps(event,ensure_ascii=False,sort_keys=True)
        if key not in event_refs:event_refs[key]='E'+str(len(event_refs)+1).zfill(4)
        event_ref=event_refs[key]
        events.setdefault(event_ref,[]).append(ref)
        stamp=item.published_at.isoformat()
        group=(stamp[:10],item.source,reading_scope(item))
        groups[group].append([ref,item.title])
    rows=[dict(date=key[0],source=key[1],stored_scope=key[2],items=value)
          for key,value in sorted(groups.items(),reverse=True)]
    header=(BEGIN+'\n## 全池发现目录（元信息，不是正文证据）\n'
        '先浏览全部目录，发现今天的重要变化、竞争解释和遗漏，再决定哪些问题值得深入。初读数量不代表市场覆盖。\n'
        '每行items为[目录编号,完整标题]；来源日期/来源/存储阅读范围见组头，时分及精度须读原文元数据。相同事件的编号组见末尾clusters，未列组不代表彼此无关。'
        'C编号仅在本期有效，可用read_material(id=C编号)读取，返回完整证据ID后才引用[N:完整ID]；也可按标题关键词search_materials。'
        '标题和事件组只是检索线索，不能把未读文章写成已知事实或用C编号作引用；相同组不等于事实完全重复或独立佐证。\n')
    text=header+json.dumps(dict(sources=rows,clusters=[refs for refs in events.values() if len(refs)>1]),ensure_ascii=False,separators=(',',':'))+'\n'+END
    return dict(text=text,references=references,events=events,entry_count=len(references),
                event_count=len(events),characters=len(text),complete=True)


def reading_budget(item, stocks):
    from .market_coverage import coverage_role
    from .news_quality import company_focus
    from .editorial_value import profile
    if coverage_role(item):return 1800
    if any(company_focus(item,stock) for stock in stocks):return 2200
    return 1200 if profile(item)['priority']>=2 else 700


def render_article(item, reading, number=None):
    from .news_quality import scope_label
    from .evidence import publication_label
    from .evidence_reading import render_initial_news
    heading=(str(number)+'. ') if number is not None else ''
    return (f'\n### {heading}[N:{item.id}] {item.title}\n'
        f'- 来源：{item.source}\n- 阅读范围：{scope_label(item)}\n'
        f'- 原文链接：{item.source_url or "未提供，不可视为已验证"}\n'
        f'- 时间：{publication_label(item)}\n'
        f'- 采集文本（按上述阅读范围使用）：{render_initial_news(item.content,reading)}\n')


def without_catalogue(text):
    """Remove exactly the generated metadata block, never article evidence."""
    import re
    if BEGIN not in text and END not in text:return text
    if text.count(BEGIN)!=1 or text.count(END)!=1:raise ValueError('discovery_marker_collision')
    pattern=r'(?ms)^'+re.escape(BEGIN)+r'\n.*?^'+re.escape(END)+r'(?=\n|$)'
    result,count=re.subn(pattern,'全池目录已在发现阶段提供；当前按既定研究问题与补读证据继续，不将未读标题当事实。',text,count=1)
    if count!=1:raise ValueError('discovery_block_not_found')
    return result
