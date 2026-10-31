"""Company news reading scope, not investment significance or factual verification.

Routine unrelated company releases remain in raw collection diagnostics. They do
not automatically enter the episode merely because a publisher supplied a body.
"""
from datetime import datetime
import re

REPORT = re.compile(r'财报|季度报告|年度报告|季报|年报|业绩|净利|利润|亏损|净赚|营收|营业收入|归母|earnings|quarterly results', re.I)
COMPANY = re.compile(r'^.{2,35}?[：:]|公司公告|公司报道|个股|上市公司')
MARKET = re.compile(r'收评|复盘|全市场|三大指数|A股|港股|美股|恒指|恒生|创业板|科创50|沪指|标普|纳指|行业|产业链|板块|多家|巨头|全线')
MAJOR = re.compile(r'财务造假|财务舞弊|欺诈|立案调查|立案告知|强制退市|债务违约|破产重整|破产清算|重大安全事故|大规模召回|重大数据泄露|停产.{0,8}(?:全球|供应|产能)|全球.{0,12}(?:断供|停产)|fraud|bankruptcy|default on|mass recall', re.I)
OPERATING = re.compile(r'订单|供给|供应|需求|产能|价格|成本|毛利|库存|出货|销量|资本开支|cash flow|capex|capacity|supply|demand', re.I)
SYSTEMIC = re.compile(r'全球|全行业|产业链|供应链|行业龙头|行业第一|市场份额|全球最大|全球主要|world.s largest|industry leader', re.I)
AGGREGATE = re.compile(r'(?:私募|公募|基金).{0,24}(?:重仓|持仓|配置)|(?:多家|[一二三四五六七八九十两\d]+[家大]).{0,12}(?:公司|企业|险企|银行)|(?:厂商|设备商|车企|险企).{0,15}(?:业绩|订单|供需|利润)')
MACRO_AGGREGATE = re.compile(r'工业(?:企业)?利润|规上工业企业')


def decision(item, stocks=(), profiles=None):
    """Return an inspectable decision. No hardcoded company names or stock codes.

    Optional related_companies records must bind an explicit company alias to
    the current stock and a dated, linked relationship/sector-role source. A
    shared sector word alone cannot create a supplier or industry leader.
    """
    from .news_quality import company_focus,company_alias_headline
    profiles = profiles or {}
    title = item.title or ''
    body = item.content or ''
    if (item.source or '').startswith('公开参与者讨论-'):
        return dict(keep=True,reason='participant_statement_pending_editorial_assessment')
    for stock in stocks:
        if company_focus(item, stock):
            return dict(keep=True, reason='watchlist_company', stock=stock.code)
        if not body and company_alias_headline(title,stock):
            return dict(keep=True,reason='watchlist_alias_discovery_lead_not_confirmed_company',stock=stock.code)
    if AGGREGATE.search(title) or MACRO_AGGREGATE.search(title):
        return dict(keep=True, reason='multi_company_or_institutional_position_lead')
    company = bool(COMPANY.search(title) or REPORT.search(title)
                   or re.search(r'公司报道|个股|公司公告', item.category or ''))
    if not company:
        return dict(keep=True, reason='not_identified_as_individual_company')
    if MAJOR.search(title):
        return dict(keep=True, reason='major_company_risk_lead_not_confirmed_public_opinion')
    for stock in stocks:
        key = str(getattr(stock.market, 'value', stock.market)) + ':' + stock.code
        profile = profiles.get(key) or {}
        from .news_briefing import operating_context
        context = operating_context(item, profile)
        if context:
            return dict(keep=True, reason='watchlist_operating_variable_lead', stock=key,
                        operating_context=context)
        for related in profile.get('related_companies', []):
            if not isinstance(related, dict):continue
            aliases = related.get('aliases') or []
            if not isinstance(aliases, list):continue
            if not any(isinstance(alias, str) and len(alias) >= 2 and alias.casefold() in title.casefold() for alias in aliases):continue
            if related.get('role') not in {'supplier', 'customer', 'competitor', 'industry_representative'}:continue
            from .evidence import article_url
            if not article_url(related.get('source_url')):continue
            try:
                valid = datetime.fromisoformat(related['valid_until']).date()
                observed = datetime.fromisoformat(related['as_of']).date()
                if not observed <= item.published_at.date() <= valid:continue
            except (KeyError, ValueError, TypeError):continue
            return dict(keep=True, reason='sourced_related_company', stock=key,
                        relationship_role=related['role'], relationship_source=related['source_url'])
    # Broad market recaps and multi-company industry developments are not
    # routine individual-company reports. They remain subject to editorial review.
    if MARKET.search(title) or (re.search(r'海外|跨国|全球',title) and OPERATING.search(title)):
        return dict(keep=True, reason='market_or_industry_event_lead')
    if SYSTEMIC.search(title + ' ' + body[:1200]) and OPERATING.search(title):
        return dict(keep=True, reason='industry_scale_operating_lead')
    if REPORT.search(title) or re.search(r'公司公告|公司报道|个股', item.category or ''):
        return dict(keep=False, reason='unrelated_company_without_documented_market_relevance')
    return dict(keep=True, reason='company_scope_uncertain_requires_editorial_assessment')


def partition(items, stocks=(), profiles=None):
    kept, excluded = [], []
    for item in items:
        row = decision(item, stocks, profiles)
        if row['keep']:kept.append(item)
        else:excluded.append(dict(id=item.id, title=item.title, **row))
    return kept, excluded
