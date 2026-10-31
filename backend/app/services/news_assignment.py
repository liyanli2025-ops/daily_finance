"""Inspectable reading assignments inspired by event-led news desks.

No LLM or paid search. These cues decide what to READ, never certify market
importance, a price driver, a surprise, or an independent confirmation.
"""
from collections import defaultdict, deque
import re

POLICY = re.compile(r'降准|降息|加息|利率决议|货币政策工具|出口管制|关税|制裁|征求意见|交易规则|FOMC.*statement',re.I)
OPERATING = re.compile(r'订单|供给|供应|需求|产能|库存|交期|售价|电价|猪价|资本开支|现金流|现金牛|烧钱|CapEx|cash flow|supply|demand|capacity',re.I)
CHANGE = re.compile(r'扩大|收缩|下降|增长|上调|下调|减少|增加|紧张|短缺|中断|暂停|停产|加速|变动|变化|走弱|收紧|放缓|烧穿|枯竭|跌|涨|\d[\d.,]*\s*(?:%|元|美元|万吨|亿|天)|cut|rais|fall|surge|shortage|disrupt',re.I)
INDUSTRY = re.compile(r'行业|产业|供应链|全球|厂商|设备商|电网|原料|半导体|芯片|能源|锂|养殖|水电|AI|artificial intelligence',re.I)
VIEW = re.compile(r'可能|预计|暗示|预测|展望|看好|看空|前官员|专访|观点|呼吁|或再|或将|或会')
FINANCIAL_SUBJECT = re.compile(r'公司|股份|控股|上市|债券|银行|证券|交易所|破产|bonds?|bankruptcy|listed company|stock market',re.I)
MACRO_DATA = re.compile(r'\bGDP\b|\bCPI\b|\bPPI\b|\bPMI\b|工业(?:企业)?利润|规上工业企业|非农|社零|社会消费品零售|进出口',re.I)


def assess(item,stocks=(),profiles=None):
    from .news_quality import company_focus
    from .news_briefing import operating_context
    from .company_news_scope import MAJOR,AGGREGATE,REPORT,SYSTEMIC,decision
    from .market_coverage import coverage_role
    title=item.title or ''
    direct_company=any(company_focus(item,stock) for stock in stocks)
    role=coverage_role(item)
    if role in {'a_session','hk_session','us_session'}:
        lane=role;level=3;why='市场时段综述，先核对真实交易时点和市场结构'
    elif MACRO_DATA.search(title):
        lane='macro_data';level=2 if VIEW.search(title) else 3
        why='宏观统计或统计解读，须核对公布值、预期、修订、月份与统计口径'
    elif POLICY.search(title):
        if VIEW.search(title) or '？' in title or '?' in title:
            lane='macro_policy';level=2;why='政策评论或预期线索，不是已经实施的政策变化'
        else:lane='macro_policy';level=3;why='政策或规则变化线索，须核对阶段、执行范围与市场预期'
    elif (MAJOR.search(title) and FINANCIAL_SUBJECT.search(title)) or role=='international_transmission':
        lane='major_risk';level=3;why='重大风险或供应冲击线索，尚未证明事件属实、传播强度或市场传导'
    elif re.search(r'美股|纳指|道指|标普',title) and re.search(r'暴跌|大跌|重挫|大涨|跳水|涨超|跌超',title):
        lane='global_market';level=3;why='海外价格异动线索，须读原文区分盘前、盘后、盘中及收盘'
    elif INDUSTRY.search(title) and OPERATING.search(title) and CHANGE.search(title):
        lane='industry_operating';level=2 if VIEW.search(title) or '？' in title or '?' in title else 3
        why='行业经营变量线索，含观点时不冒充已经发生的变化；须核对主体、口径和增量'
    elif direct_company:
        lane='watchlist';level=3 if REPORT.search(title) or OPERATING.search(title) else 2
        why='当前自选股直接材料，须区分例行披露与实质新增变化'
    elif AGGREGATE.search(title):
        lane='industry_or_institution';level=2;why='多公司或机构持仓对照，历史持仓不能冒充今日资金'
    elif role=='overseas_company_event':
        # A domestic issuer's earnings article may mention US markets. Never
        # protect it as overseas company news on that body mention alone.
        if (re.search(r'海外|美股|美企|华尔街|Nasdaq|NYSE',title,re.I)
                and re.search(r'财报|盈利|业绩|资本开支|营收|利润|现金流|交卷|盘后|earnings|capex',title,re.I)):
            lane='overseas_company';level=2;why='海外公司事件线索，须另证A/H敞口与市场影响'
        else:lane='other';level=1;why='正文涉及海外不证明本文主体是海外公司'
    else:
        lane='other';level=1;why='未识别优先研究问题，保留检索，不视为已判无价值'
    for stock in stocks:
        key=str(getattr(stock.market,'value',stock.market))+':'+stock.code
        context=operating_context(item,(profiles or {}).get(key) or {})
        if context and level<3:
            lane='watchlist' if direct_company else 'industry_operating'
            level=3;why='与当前自选股具体经营变量匹配：'+context+'；不证明公司受益'
    if direct_company and lane=='industry_operating':lane='watchlist'
    scope=decision(item,stocks,profiles)
    if scope['reason']=='industry_scale_operating_lead' and not SYSTEMIC.search(title):
        lane='other';level=1;why='仅正文中的规模措辞，未核定该普通个股的行业代表性，保留编辑复核'
    question=lane
    if lane=='industry_operating':
        if re.search(r'资本开支|现金流|现金牛|烧钱|融资|capex|cash flow',title,re.I):question+=':investment_funding'
        elif re.search(r'价|成本',title):question+=':price_cost'
        else:question+=':supply_demand'
    return dict(lane=lane,question=question,reading_priority=level,reason=why,
                status='reading_lead_not_verified_importance')


def order(items,stocks=(),profiles=None):
    """Balance research questions before repeating a busy lane.

    No fixed article count, no minimum number of stories and no invented scores
    of predicted returns. Different events in one company are kept distinct.
    """
    from .news_briefing import diverse_rank
    buckets=defaultdict(list)
    for item in items:
        assignment=assess(item,stocks,profiles)
        buckets[(assignment['reading_priority']>=2,assignment['question'])].append(item)
    result=[]
    for phase in (True,False):
        queues={}
        for key,values in buckets.items():
            if key[0]!=phase:continue
            # Balance research lanes BEFORE one busy lane's best-quality
            # articles consume the input. Priority is ordinal within a lane.
            ranked=diverse_rank(values)
            ranked.sort(key=lambda item:(assess(item,stocks,profiles)['reading_priority'],item.published_at.date()),reverse=True)
            queues[key]=deque(ranked)
        keys=sorted(queues,key=lambda key:(-assess(queues[key][0],stocks,profiles)['reading_priority'],key[1]))
        while any(queues.values()):
            for key in keys:
                if queues[key]:result.append(queues[key].popleft())
    return result


def audit(items,readings,stocks=(),profiles=None):
    provided={row['id']:row for row in readings};rows=[]
    for item in items:
        rows.append(dict(id=item.id,title=item.title,**assess(item,stocks,profiles),
                         body_provided=item.id in provided,
                         provided_characters=provided.get(item.id,{}).get('selected_characters',0)))
    lanes={}
    for row in rows:
        state=lanes.setdefault(row['lane'],dict(candidates=0,provided=0,unread_ids=[]))
        state['candidates']+=1
        if row['body_provided']:state['provided']+=1
        else:state['unread_ids'].append(row['id'])
    return dict(stage='prepared_input_not_model_read_receipt',lanes=lanes,articles=rows,
                limitation='本池线索分工，不是全网重大事件清单；未初读保留完整目录及补读能力，规则命中不证明重要、真实、未定价或已读全文。')
