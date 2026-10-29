"""Budgeted verbatim sentence selection, not financial scoring or a generated summary."""
import re

OPERATING=re.compile(r'\b(?:rates?|inflation|revenue|profits?|orders?|demand|capacity|forecast|target|vot\w*)\b|营收|营业收入|业绩|净利|收入|利润|毛利|订单|产能|销量|出货|需求|库存|成本|价格|电价|来水|发电|供给|供应|现金流|指引|投票|利率|政策|交付',re.I)
CHANGE=re.compile(r'\b(?:increase\w*|rise|fell|maintain\w*|unchanged|raise\w*|lower\w*|expand\w*|robust|strong|gain\w*)\b|增长|上升|下跌|下降|下滑|改善|回升|上调|下调|增加|减少|订满|售罄|满负荷|扩大|收窄|亏损|加息|降息|维持|释放|饱和|缓解|紧张|旺盛|投产|提升|优化|[0-9]+(?:\.[0-9]+)?[%％]',re.I)
ATTRIBUTED=re.compile(r'\b(?:said|stated|preferred|decided|expects?|approved)\b|表示|披露|称|指出|预计|预期|测算|分析称|显示',re.I)
DIRECT_SOURCE=re.compile(r'\b(?:committee|company|management|officials|analysts|chair)\b[^.!?\n]{0,80}\b(?:said|stated|preferred|decided|expects?|maintain\w*)\b|(?:公司|管理层|负责人|分析师|工作人员|他|她)[^。！？]{0,35}(?:表示|指出|称)|(?:业绩说明会|投资者关系|三季报|公告)[^。！？]{0,15}(?:表示|称|提到)',re.I)
QUALIFIER=re.compile(r'\b(?:while|however|although|uncertainty|but|not necessarily|rather than)\b|并未|并非|不代表|不意味着|不等于|未必|不过|但是|然而|尚未|仍需|不及预期|低基数|一次性|受到.{0,12}支撑',re.I)
EXPLICIT_QUALIFIER=re.compile(r'并未|并非|不代表|不意味着|不等于|未必|低基数|一次性')
PRONOUN=re.compile(r'^[\s“”]*(?:公司|该公司|他(?:指出|表示|称)|她(?:指出|表示|称)|其(?!中|他|余))')


def _spans(text):
    start=0
    for boundary in re.finditer(r'[。！？!?]+|(?<![A-Z])\.(?=\s+[A-Z]|\s*$)',text):
        end=boundary.end()
        if text[start:end].strip():yield start,end
        start=end
    if text[start:].strip():yield start,len(text)


def _merge(ranges):
    merged=[]
    for start,end in sorted(ranges):
        if merged and start<=merged[-1][1]:merged[-1][1]=max(end,merged[-1][1])
        else:merged.append([start,end])
    return merged


def read_news(text,title='',budget=1200,focus_terms=()):
    if type(budget) is not int or budget<1:raise ValueError('invalid_reading_budget')
    footer=re.search(r'(?m)^\s*相关阅读[：:]?\s*$',text)
    end=footer.start() if footer else len(text)
    body=text[:end]
    if len(body)<=budget:
        ranges=[[0,end]] if end else []
    else:
        units=list(_spans(body));terms=[str(value).casefold() for value in focus_terms if value]
        title_terms=set(re.findall(r'[A-Za-z0-9]{2,}|[\u4e00-\u9fff]{2}',title))
        candidates=[]
        for i,(start,stop) in enumerate(units):
            sentence=body[start:stop];context=sentence
            # Retain the immediate subject context when a statement uses 公司/他/她.
            if i and PRONOUN.search(sentence):
                context_index=i-1
                while context_index>0 and PRONOUN.search(body[units[context_index][0]:units[context_index][1]]):
                    context_index-=1
                previous=body[units[context_index][0]:start]
                # Never attach a pronoun statement to an earlier watchlist
                # company across an intervening peer. Keep the immediate
                # predecessor even when it names a different company.
                if len(previous)+len(sentence)>budget:continue
                start=units[context_index][0];context=body[start:stop]
            focus=sum(term in context.casefold() for term in terms)
            overlap=sum(term.casefold() in context.casefold() for term in title_terms)
            observation=bool(OPERATING.search(context) and CHANGE.search(context))
            attributed=bool(ATTRIBUTED.search(sentence) and observation)
            qualifier=bool(QUALIFIER.search(sentence) and (OPERATING.search(context) or CHANGE.search(context) or EXPLICIT_QUALIFIER.search(sentence)))
            candidates.append(dict(start=start,end=stop,focus=focus,overlap=overlap,observation=observation,
                attributed=attributed,direct=bool(attributed and DIRECT_SOURCE.search(sentence)),qualifier=qualifier,explicit=bool(EXPLICIT_QUALIFIER.search(sentence))))
        ranges=[]
        def take(candidate):
            trial=_merge(ranges+[[candidate['start'],candidate['end']]])
            if len(trial)>4 or sum(b-a for a,b in trial)>budget:return False
            if trial==ranges:return False
            ranges[:]=trial;return True
        # Preserve a short opening/source caveat without spending most of the
        # window on the opening industry summary.
        if units and units[0][1]<=max(120,budget//4):take(dict(start=0,end=units[0][1]))
        # These lanes are linguistic roles, not bullish/bearish classifications.
        lanes=[lambda row:row['direct'],
               lambda row:row['qualifier'],lambda row:row['observation']]
        for role,lane in enumerate(lanes):
            ranked=sorted((row for row in candidates if lane(row)),
                key=lambda row:(-int(row['explicit']) if role==1 else 0,-row['focus'],-row['overlap'],row['start']))
            for candidate in ranked:
                if take(candidate):break
        for candidate in sorted(candidates,key=lambda row:(-row['focus'],-row['overlap'],row['start'])):
            if sum(b-a for a,b in ranges)>=budget:break
            take(candidate)
    full=bool(ranges==[[0,len(text)]])
    if full:rendered=text
    else:
        rendered='【入模完整句摘录，未提供全文；原文字符偏移从0起。选句是阅读辅助，不是财务结论或独立核实。未读部分可用read_material继续读取。】'
        if not ranges:rendered+='\n本预算内没有可完整提供的句子，需继续读取原文，不从标题补写事实。'
        for start,stop in ranges:rendered+=f'\n【原文字符{start}:{stop} / 总长{len(text)}】\n'+text[start:stop]
    return dict(text=rendered,ranges=ranges,selected_characters=sum(b-a for a,b in ranges),budget=budget,
        collected_text_fully_provided=full,limitation='完整句不等于完整上下文或独立核实；未读取的材料不能冒充已读。')
