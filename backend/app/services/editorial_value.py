"""Explainable reading priorities, not truth scores or estimated trading returns."""
import re

VARIABLE=re.compile(r'订单|库存|交期|排产|产能|产量|销量|售价|报价|利润|收入|营收|成本|毛利|开工|运价|出口|进口|赎回|资本开支|算力|供应|需求|成交|利率|汇率|收益率|溢价|折价|价差')
CHANGE=re.compile(r'增长|下降|下滑|减少|增加|回落|降至|升至|跌至|涨至|扩产|提价|降价|上调|下调|取消|短缺|收缩|修复|亏损|新低|新高|突破|瓶颈|砍单|扩大|收窄|骤降')
NUMBER=re.compile(r'\d+(?:\.\d+)?\s*(?:%|亿|万|倍|吨|元|个月|周|天)')


def promotion_reason(title):
    """Narrow headline-level commercial calls to action, not a publisher ban."""
    if (re.search(r'展会|展览|电机展|博览会|峰会|论坛',title)
            and re.search(r'即将开幕|锁定.{0,12}展|集中洽谈|采购订单|报名|诚邀|展位|招展',title)):
        return 'event_call_to_action'
    if (re.search(r'指数|ETF|基金',title,re.I)
            and re.search(r'怎么选|优势明显|投资利器|布局利器|一键布局|掘金利器',title)):
        return 'investment_product_recommendation'
    if (re.search(r'ETF.{0,12}[（(]\d{6}[)）]',title,re.I)
            and re.search(r'标的指数|半日涨|盘中涨|涨超',title)
            and not re.search(r'净申购|净赎回|资金流|份额|清盘|折溢价|跟踪误差|费率',title)):
        return 'named_fund_price_promotion'
    return None


def profile(item):
    """Classify visible textual cues only; facts and mechanisms need review."""
    title=item.title
    body=item.content or ''
    result=dict(kind='unclassified',priority=1,reasons=['尚未识别具体经营/政策/交易增量'],
        limitation='词项线索只用于阅读排序，不证明事实正确、原创、未定价或投资价值')
    if re.search(r'翌日披露[报報]表',title):
        result.update(kind='routine_disclosure',priority=0,reasons=['例行股份变动披露，须另核本期新增事实；不因公告标题就占重要催化位'])
        return result
    if re.search(r'\bFOMC\b.*\bstatement\b',title,re.I):
        result.update(kind='policy_or_calendar',priority=3,reasons=['议息声明线索；须核对原文、时点和政策阶段，不代表超预期'])
        return result
    promotion=promotion_reason(title)
    if promotion:
        result.update(kind='commercial_promotion',priority=-1,reasons=[promotion])
        return result
    benchmarks=re.findall(r'创业板|科创50|恒科|恒指|沪指|上证|深成指|纳指|标普',title)
    if (len(set(benchmarks))>=2 and re.search(r'涨|跌',title) and '%' in title
            and not re.search(r'为何|为什么|背后|解读|财报|业绩|政策|关税|降息|降准',title)):
        result.update(kind='recap',priority=0,reasons=['多指数涨跌综述，仅作带时点的市场背景'])
        return result
    if (re.search(r'午评|午盘|半日|收评|收盘|全市场.{0,8}(?:股|个股).{0,8}(?:飘红|上涨|下跌)',title)
            and re.search(r'指数|创业板|恒指|恒科|科创|全市场|金属|沪指|A股',title)
            and not re.search(r'财报|订单|产能|库存|净利润|收入|营收|政策|关税|降息|降准',title)):
        result.update(kind='recap',priority=0,reasons=['市场时段综述，仅作行情背景；不能从正文附带词升级为经营事件'])
        return result
    if re.search(r'早报|晚报|早知道|晨报|隔夜行情|收盘综述|盘前必读',title):
        result.update(kind='recap',priority=0,reasons=['综合综述，优先找对应事件原文；避免重复占位'])
        return result
    if re.search(r'人民币.*中间价|公开市场业务交易公告',title):
        result.update(kind='routine_quote',priority=1,reasons=['常规公布值，需比较预期/前值；不能仅凭发布认定重大变化'])
        return result
    if re.search(r'坚定看好|长期向好|中长期投资价值',title):
        result.update(kind='general_opinion',priority=0,reasons=['方向性表态；尚未从标题识别可验证的新依据'])
        return result
    if re.search(r'货币政策工具|交易规则|征求意见|出口管制|关税|利率决议|降准|降息|制裁',title):
        result.update(kind='policy_or_calendar',priority=3,reasons=['政策、规则或重要日历线索；阶段、影响范围与意外程度仍须核对'])
        return result
    cue=next((sentence.strip() for sentence in re.split(r'[。！？\n]',title+'。'+body)
        if VARIABLE.search(sentence) and (CHANGE.search(sentence) or NUMBER.search(sentence))),None)
    if cue:
        forecast=bool(re.search(r'预计|预测|预期|有望|或将',cue))
        result.update(kind='forecast_or_hypothesis' if forecast else 'operating_or_market_change',
            priority=2 if forecast else 3,reasons=['经营或量价变量与变化/数量同句出现；需核对口径'],cue=cue[:160])
        if forecast:result['reasons']=['预测或假设，必须保留机构/作者归属；不是已实现经营结果']
        return result
    if VARIABLE.search(title+' '+body) and re.search(r'专访|记者.{0,12}(?:调查|采访|了解到)|受访|财说',title+' '+body):
        result.update(kind='reported_investigation',priority=2,reasons=['有采访/调查及经营变量线索；样本与利益立场仍需核对'])
    elif re.search(r'分析师|研究员|基金经理|机构观点|研究发布',title+' '+body[:1000]+' '+(item.source or '')):
        result.update(kind='attributed_view',priority=1,reasons=['可归属的研究/观点线索，具体假设与反方证据待阅读'])
    return result


def rank(item):
    from .news_quality import priority
    scope,importance,published=priority(item)
    return scope,profile(item)['priority'],importance,published


def statistical_event_key(item):
    """One initial slot for an exactly matching headline statistic.

    This is deliberately narrow: same metric, period text, direction, percentage
    and publication day; changes and opposing numbers stay separate. No event
    year is inferred from publication time. All bodies stay in the workspace.
    """
    title=item.title
    if re.search(r'为何|为什么|背后|调查|专访|解读|财说|如何',title):return None
    matches=[(name,pattern) for name,pattern in [
        ('industrial_profit',r'(?:规模以上|规上)?工业(?:企业)?(?:实现)?利润(?:总额)?'),
        ('retail_sales',r'社会消费品零售总额'),
        ('cpi',r'居民消费价格|\bCPI\b'),('ppi',r'工业生产者出厂价格|\bPPI\b')]
        if re.search(pattern,title,re.I)]
    if len(matches)!=1:return None
    metric,metric_pattern=matches[0]
    scope=title+' '+(item.content or '')[:800]
    if '国家统计局' not in scope or '全国' not in scope:return None
    period=re.search(r'(?:1[—\-－至~～](\d{1,2})月|前(\d{1,2})个月|(\d{1,2})月份?)',title)
    value=re.search(r'(同比)?\s*(增长|下降|上涨|下跌)\s*(\d+(?:\.\d+)?)\s*%',title)
    if not period or not value:return None
    yoy=bool(value.group(1))
    if not yoy:
        # A shortened headline may omit 同比. Only its corresponding metric's
        # sentence in the supplied lead can supply this qualifier, not guessing.
        for sentence in re.split(r'[。！？\n]',(item.content or '')[:800]):
            body_value=re.search(r'同比\s*(增长|下降|上涨|下跌)\s*(\d+(?:\.\d+)?)\s*%',sentence)
            if (re.search(metric_pattern,sentence,re.I) and body_value and body_value.group(1)==value.group(2)
                    and float(body_value.group(2))==float(value.group(3))):
                yoy=True;break
    number=period.group(1) or period.group(2) or period.group(3)
    span='ytd' if period.group(1) or period.group(2) else 'month'
    year=re.search(r'(20\d{2})年',title)
    # Explicitly unknown year differs from an explicitly stated year.
    return (item.published_at.date().isoformat(),metric,year.group(1) if year else 'year_unspecified',
        span,int(number),yoy,value.group(2),float(value.group(3)))
