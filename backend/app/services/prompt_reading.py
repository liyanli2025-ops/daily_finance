"""Bound the initial reading window; retain exact offsets and the original pool."""
import re


def reading_ranges(text,query='',budget=1200):
    if len(text)<=budget:
        return [(0,len(text))] if text else []
    # Head, query-relevant context and a counterstatement if present. These are
    # verbatim slices, not generated summaries or a claim of exhaustive reading.
    width=max(80,budget//3)
    tokens=set(re.findall(r'[A-Za-z0-9]{2,}|[\u4e00-\u9fff]{2}',query))
    candidates=[]
    for match in re.finditer(r'[^。！？\n]+[。！？\n]?',text):
        sentence=match.group()
        score=sum(token in sentence for token in tokens)
        counter=bool(re.search(r'但是|然而|风险|不代表|不意味着|否认|尚未|未披露|不能',sentence))
        if score or counter:candidates.append((score+counter,match.start()))
    offsets=[0]
    for _,offset in sorted(candidates,key=lambda row:(-row[0],row[1])):
        start=max(0,offset-80)
        if all(abs(start-used)>=width for used in offsets):offsets.append(start)
        if len(offsets)==3:break
    if len(offsets)<3:
        offsets.append(max(0,len(text)-width))
    offsets=sorted(set(offsets))[:3]
    return [(start,min(len(text),start+width)) for start in offsets]


def excerpt(text,query='',budget=1200):
    if len(text)<=budget:return text
    ranges=reading_ranges(text,query,budget)
    parts=['【入模节选，未提供全文；字符偏移从0起，缺失部分不得推断。可用read_material按本条ID继续读取。】']
    for start,end in ranges:
        parts.append(f'【原文字符{start}:{end} / 总长{len(text)}】\n'+text[start:end])
    return '\n'.join(parts)


def input_characters(messages):
    """Conservative serialized character count, not a token or currency estimate."""
    import json
    return len(json.dumps(messages,ensure_ascii=False,separators=(',',':')))


def validate_input(messages,limit=100000):
    size=input_characters(messages)
    if size>limit:
        raise RuntimeError(f'模型输入字符数{size}超过{limit}的单次保护上限；未发送请求，请先缩减初始阅读材料，不删除资料池')
    return size


MARKET_MAP='@@MARKET_KEY_MAP '


def _json_line(line):
    import json
    start=line.find('{')
    if start<0:return None
    try:
        value,end=json.JSONDecoder().raw_decode(line[start:])
        if not isinstance(value,dict) or line[start+end:].strip():return None
        return line[:start],value,line[start+end:]
    except (ValueError,TypeError):return None


def _map_keys(value,mapping):
    if isinstance(value,dict):return {mapping.get(key,key):_map_keys(item,mapping) for key,item in value.items()}
    if isinstance(value,list):return [_map_keys(item,mapping) for item in value]
    return value


def compact_market(text):
    """Lossless dictionary encoding of repeated long JSON keys, never values.

    All metrics, timestamps, units, missingness and provenance remain present.
    No character slicing or model-generated market summary is involved.
    """
    import json
    from collections import Counter
    if any(line.startswith(MARKET_MAP) for line in text.splitlines()[:2]):return text
    lines=text.splitlines(keepends=True)
    parsed=[_json_line(line) for line in lines]
    counts=Counter()
    def visit(value):
        if isinstance(value,dict):
            counts.update(value.keys())
            for item in value.values():visit(item)
        elif isinstance(value,list):
            for item in value:visit(item)
    for row in parsed:
        if row:visit(row[1])
    # Keep identity, time, units and source keys immediately legible.
    keep={'source_quote_time','timestamp_span_seconds','source_url','time_basis','adjustment',
          'collected_at','observed_at','as_of','calendar_status','source_clock_usable'}
    mapping={};legend={};reserved=set(counts)
    for key,count in sorted(counts.items()):
        if key in keep or len(key)<12 or count<3:continue
        number=len(mapping)
        alias='f'+str(number)
        while alias in reserved:
            number+=1;alias='f'+str(number)
        # Include the mapping entry's cost; rare keys are not worth encoding.
        if (len(key)-len(alias))*count <= len(key)+len(alias)+12:continue
        mapping[key]=alias;legend[alias]=key;reserved.add(alias)
    if not mapping:return text
    output=[]
    for line,row in zip(lines,parsed):
        if row:
            prefix,value,suffix=row
            line=prefix+json.dumps(_map_keys(value,mapping),ensure_ascii=False,separators=(',',':'))+suffix
        output.append(line)
    encoded=''.join(output)
    header='行情JSON字段简写：下表只替换重复键名，值、来源时点和单位不变；按表还原含义，不把简写当新指标。\n'
    result=header+MARKET_MAP+json.dumps(legend,ensure_ascii=False,separators=(',',':'))+'\n'+encoded
    return result if len(result)<len(text) else text


def restore_market(text):
    """Audit decoder: restores every original JSON key, not market freshness."""
    import json
    lines=text.splitlines(keepends=True)
    if len(lines)<2 or not lines[1].startswith(MARKET_MAP):return text
    legend=json.loads(lines[1][len(MARKET_MAP):])
    result=[]
    for line in lines[2:]:
        row=_json_line(line)
        if row:
            prefix,value,suffix=row
            line=prefix+json.dumps(_map_keys(value,legend),ensure_ascii=False,separators=(',',':'))+suffix
        result.append(line)
    return ''.join(result)
