"""Bound the initial reading window; retain exact offsets and the original pool."""
import re


def excerpt(text,query='',budget=1200):
    if len(text)<=budget:
        return text
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
    parts=['【入模节选，未提供全文；字符偏移从0起，缺失部分不得推断。可用read_material按本条ID继续读取。】']
    for start in offsets:
        end=min(len(text),start+width)
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
