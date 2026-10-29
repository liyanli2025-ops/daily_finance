"""Budgeted research excerpts; preserve metrics as lines and PDF/chunk provenance."""
import re

from .evidence_reading import read_news,_merge

MARKER=re.compile(r'(?m)^【(?:原PDF第[^\n】]+|镜像文本分片[^\n】]+)】[^\n]*(?:\n|$)')


GENERATED_PREFIXES=(
    '以下是PDF原文节选；券商评级和盈利预测是该机构当时的观点，不得作为本节目买卖指令。',
    '公司交流口径；经营计划不是已实现结果。',
)


def source_body_characters(text,ranges,structured=False):
    """Exclude our generated preambles/page markers, not real source caveats."""
    if structured:
        rows=list(re.finditer(r'(?m)^\s*-\s+[^\n]+[：:][^\n]*(?:\n|$)',text))
        return sum(len(row.group().strip()) for row in rows
            if any(a<=row.start() and b>=row.end() for a,b in ranges))
    markers=list(MARKER.finditer(text))
    start=markers[0].end() if markers else 0
    if not markers:
        for prefix in GENERATED_PREFIXES:
            if text.startswith(prefix):start=max(start,len(prefix))
        if text.startswith('政府行业统计/政策原文节选；'):
            lines=text.splitlines(keepends=True)
            if len(lines)>=3:start=sum(len(line) for line in lines[:2])
    count=0
    for a,b in ranges:
        a=max(a,start)
        if b<=a:continue
        fragment=text[a:b]
        for marker in reversed(markers):
            left=max(a,marker.start());right=min(b,marker.end())
            if right>left:fragment=fragment[:left-a]+fragment[right-a:]
        count+=len(fragment.strip())
    return count


def read_research(text,kind,title='',budget=1200,focus_terms=()):
    if type(budget) is not int or budget<1:raise ValueError('invalid_research_budget')
    omitted=[]
    structured=kind=='financial_baseline' and bool(re.search(r'(?m)^\s*-\s+[^\n]+[：:]',text))
    if len(text)<=budget:
        ranges=[[0,len(text)]] if text else []
    elif structured:
        # Supplier baselines have a currency/period preamble and one labelled
        # metric per line. Never split a number, unit or field label.
        end=0
        for line in text.splitlines(keepends=True):
            if end+len(line)>budget:break
            end+=len(line)
        ranges=[[0,end]] if end else []
        omitted.append('结构化指标仅提供完整前部行；未提供字段须按ID继续读取，不推断缺失数字')
    else:
        result=read_news(text,title,budget=max(1,budget-min(120,budget//4)),focus_terms=focus_terms)
        ranges=result['ranges']
        markers=list(MARKER.finditer(text))
        # Selecting a later paragraph must not detach it from its PDF page or
        # mirror chunk. Marker ranges are counted in the same raw-text budget.
        retained=[]
        for start,end in ranges:
            own_marker=any(start<=m.start()<end and not text[start:m.start()].strip() for m in markers)
            previous=[] if own_marker else [m for m in markers if m.start()<start]
            context=[]
            if previous:
                marker=previous[-1]
                if marker.end()>start:
                    context=[[marker.start(),max(end,marker.end())]]
                else:context=[[marker.start(),marker.end()],[start,end]]
            else:context=[[start,end]]
            trial=_merge(retained+context)
            if sum(b-a for a,b in trial)<=budget:retained=trial
            else:omitted.append('相关段落连同页码/分片超出预算，未提供，需按ID继续读取')
        ranges=retained
    full=ranges==[[0,len(text)]] and bool(text)
    if full:rendered=text
    elif structured:
        rendered='【仅提供存储文本的部分完整指标行，非财报全文。】'
        for start,end in ranges:rendered+=f'\n【原文字符{start}:{end}/{len(text)}】\n'+text[start:end]
        if not ranges:rendered+='本预算未提供完整指标行，须用read_material继续读取。'
    else:
        rendered='【研究材料入模节选，字符偏移从0起；不是财报/研报全文。页码只标原PDF，镜像分片不等于页码。表格列关系未经核验，不自行拼接单位、期间和数值；机构预测不等于实现结果。】'
        for start,end in ranges:rendered+=f'\n【原文字符{start}:{end} / 总长{len(text)}】\n'+text[start:end]
        if not ranges:rendered+='\n本预算未提供完整正文单位，须用read_material继续读取，不据标题形成事实。'
    return dict(text=rendered,ranges=ranges,selected_characters=sum(b-a for a,b in ranges),
        budget=budget,source_body_characters=source_body_characters(text,ranges,structured),collected_text_fully_provided=full,omitted=omitted,
        limitation='完整句/指标行不证明全文上下文、表格列关系或事实已核验；所有统计期和来源以材料元数据及原文为准')
