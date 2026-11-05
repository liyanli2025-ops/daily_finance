"""Conservative use restrictions, not fact or market-session certification."""
import re
from urllib.parse import urlsplit
from .search_objectives import assess,social_platform


def assess_role(item):
    title=item.title or ''
    host=(urlsplit(item.source_url or '').hostname or '').lower()
    flags=[]
    morning=bool(re.search(r'\bAM Report\b|\bmorning (?:report|brief|update)\b|盘前|早盘|晨报|早报',title,re.I))
    commentary=bool(re.search(r'\b(?:snapshot|outlook|preview|commentary)\b|观点|评论|解读|展望',title,re.I))
    bank_commentary=host=='mufgresearch.com' or host.endswith('.mufgresearch.com')
    preview='forecast_or_commentary_not_release_confirmation' in assess(
        dict(title=title,url=item.source_url),'released_policy','global_policy')['flags']
    social=social_platform(item.source_url)
    market_commentary=bool(re.search(r'国债收益率|债市|\b(?:treasury|bond) yields?\b',title,re.I)
        and not re.search(r'发布|宣布|决议|声明|借款计划|\b(?:announces?|statement|borrowing plan)\b',title,re.I))
    if morning:flags.append('morning_or_intraday_not_settlement')
    if commentary or bank_commentary:flags.append('commentary_not_original_policy_release')
    if preview:flags.append('forecast_not_released_policy')
    if social:flags.append('social_statement_not_main_news_body')
    if market_commentary:flags.append('market_quote_not_original_policy_release')
    labels=re.findall(r'美东时间[^，。\n]{0,55}|\d{1,2}月\d{1,2}日(?:收盘|结算)',(getattr(item,'content','') or '')[:5000])
    return dict(owner='finance-material-role-v1',flags=flags,
        latest_close_allowed=not (morning or social),
        commodity_settlement_allowed=not (morning or social),
        original_policy_release_allowed=not (commentary or bank_commentary or preview or social or market_commentary),
        reported_session_labels=list(dict.fromkeys(labels))[:8],
        session_verified=False,source_identity_verified=False,
        limitation='仅限制明显不匹配用途；未被限制不表示收盘、政策发布或作者身份已核实。')


def lane_allowed(item,lane):
    role=assess_role(item)
    if lane in {'a_market','hk_market','us_market'}:return role['latest_close_allowed']
    if lane=='commodities':return role['commodity_settlement_allowed']
    if lane=='global_policy':return role['original_policy_release_allowed']
    return True
