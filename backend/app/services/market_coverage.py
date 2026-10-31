"""Reading leads for market-wide coverage; no truth or causality claims."""
import re


def cross_category_reason(item):
    title=item.title
    lead=title+' '+(item.content or '')[:1200]
    if re.search(r'财报|季报|净利润|归母.{0,10}(?:盈利|亏损)|营业收入|营收|每股收益|financial results|quarterly earnings',title,re.I):
        return 'company_financial_event'
    if re.search(r'关税|出口管制|制裁|利率决议|外汇市场|电力.{0,8}(?:交易|零售|价格)|tariff|export control|sanctions',title,re.I):
        return 'policy_or_market_rule'
    if (re.search(r'停产|供应中断|封锁|战争|空袭|冲突|地震|飓风',title)
            and re.search(r'原油|天然气|航运|运价|产能|芯片|供应链|通胀|oil|gas|shipping',lead,re.I)):
        return 'supply_or_geopolitical_transmission_lead'
    if (re.search(r'芯片|半导体|电池|能源|HBM|semiconductor',title,re.I)
            and re.search(r'份额|订单|供应|供给|成本|价格|产量|停产|增产|减产',title)):
        return 'industry_operating_event'
    return None


def market_candidates(items):
    return [item for item in items if getattr(item.news_type,'value',item.news_type)=='finance'
            or cross_category_reason(item)]


def coverage_role(item):
    """Headline scope is a reading lead, never a verified session/date label."""
    if (getattr(item,'source','') or '').startswith('公开参与者讨论-'):return None
    title=item.title
    lead=title+' '+(item.content or '')[:1200]
    us_close=re.search(r'美股收盘|美股.{0,10}(?:收涨|收跌|三连涨|三连跌)|(?:纳指|标普|道指).{0,8}(?:收涨|收跌|三连涨|三连跌)',title)
    if us_close and not re.search(r'盘前|盘后|期货',title):return 'us_session'
    close=bool(re.search(r'收评|收盘|复盘',title) or ('行情收官' in title and re.search(r'收盘|收市',lead)))
    if close and not re.search(r'ETF|基金|可转债|期货',title,re.I):
        if re.search(r'港股|恒生|恒指|恒科',title):return 'hk_session'
        if re.search(r'A股|沪指|上证|创业板|科创|两市|三大指数|全市场',title):return 'a_session'
    geographic=title+' '+(item.content or '')[:200]
    if (re.search(r'财报|现金流|资本开支|盈利指引|earnings|cash flow|capex',lead,re.I)
            and re.search(r'美股|华尔街|纳指|纳斯达克|标普|纽交所|Nasdaq|NYSE',geographic,re.I)):
        return 'overseas_company_event'
    risk=(re.search(r'关税|制裁|出口管制',title)
          or re.search(r'战争|空袭|军事行动|海峡|地缘|中东|对.{1,5}(?:行动|打击)',geographic))
    if risk and re.search(r'原油|天然气|能源|航运|运价|供应|通胀|芯片|半导体',lead):
        return 'international_transmission'
    return None


ROLES=('a_session','hk_session','us_session','overseas_company_event','international_transmission')


def coverage_audit(pool,selected):
    result={}
    for role in ROLES:
        candidates=[item for item in pool if coverage_role(item)==role]
        chosen=[item for item in selected if coverage_role(item)==role]
        result[role]=dict(candidates=len(candidates),selected_ids=[item.id for item in chosen],
            status='prepared_reading_lead' if chosen else 'not_selected' if candidates else 'not_found_in_pool')
    return result


def anchor_rank(item, role):
    from .news_quality import priority
    title=item.title
    monthly=bool(re.search(r'月度|月内|单月|月跌|月涨|月最大|月最小|\d{1,2}月收官',title))
    # Prefer the most recent completed-session account over monthly retrospectives.
    # Selection is a reading lead; actual session and numeric checks remain upstream.
    session=role.endswith('_session')
    direct_risk=bool(re.search(r'战争|空袭|军事行动|海峡|关税|制裁|出口管制|对.{1,5}(?:行动|打击)',title))
    return (not monthly if session else True,direct_risk if role=='international_transmission' else True,
            priority(item)[0],item.published_at,item.importance_score)
