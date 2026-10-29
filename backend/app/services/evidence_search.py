"""Lexical relevance and verbatim search windows, not semantic or financial analysis."""
import math
import re

from .evidence_reading import _spans,PRONOUN


def token_weights(tokens,documents):
    """Downweight terms occurring throughout this episode's pool. No external model."""
    documents=[value.casefold() for value in documents]
    return {token:1+math.log((len(documents)+1)/(1+sum(token in value for value in documents)))
        for token in sorted(tokens)}


def query_phrases(query):
    return sorted(set(re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z0-9]+',query.casefold())))


def score(text,weights):
    text=text.casefold()
    return sum(weight for token,weight in weights.items() if token in text)


def search_window(text,weights,budget=800):
    if type(budget) is not int or budget<1:raise ValueError('invalid_search_budget')
    footer=re.search(r'(?m)^\s*相关阅读[：:]?\s*$',text)
    end=footer.start() if footer else len(text)
    spans=list(_spans(text[:end]))
    if not spans:
        return dict(offset=0,end=0,excerpt='',ranges=[],has_more=bool(text),unread_before=False,
            next_offset=0 if text else None,body_term_matches=[],model_input_scope='no_body_provided')
    index=max(range(len(spans)),key=lambda i:(score(text[spans[i][0]:spans[i][1]],weights),-i))
    first=index
    # A statement beginning 公司/他/她 must carry its immediate subject, even
    # when that subject is a peer and not the queried company.
    while first and PRONOUN.search(text[spans[first][0]:spans[first][1]]):first-=1
    start=spans[first][0];stop=spans[index][1]
    matches=[token for token in sorted(weights) if token in text[spans[index][0]:stop].casefold()]
    if stop-start>budget:
        # Do not turn a partial table, numeric value or attribution into a fact.
        return dict(offset=start,end=start,excerpt='',ranges=[],has_more=True,unread_before=start>0,
            next_offset=start,body_term_matches=matches,model_input_scope='no_body_provided',
            limitation='命中句及主语上下文超出搜索预算；未提供正文，请用read_material明确分段读取，不能据标题补写')
    for _,candidate_end in spans[index+1:]:
        if candidate_end-start>budget:break
        stop=candidate_end
    return dict(offset=start,end=stop,excerpt=text[start:stop],ranges=[[start,stop]],
        has_more=start>0 or stop<len(text),unread_before=start>0,
        next_offset=stop if stop<len(text) else None,body_term_matches=matches,
        model_input_scope='all_stored_text' if start==0 and stop==len(text) else 'tool_return_fragment',
        limitation='搜索片段保留完整句和紧邻主语，未提供部分不能冒充已读；表格列关系和事实仍须另行核对')
