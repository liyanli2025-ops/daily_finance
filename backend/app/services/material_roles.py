"""Conservative use restrictions, not fact or market-session certification."""
import re
from urllib.parse import urlsplit


def assess_role(item):
    title=item.title or ''
    host=(urlsplit(item.source_url or '').hostname or '').lower()
    flags=[]
    morning=bool(re.search(r'\bAM Report\b|\bmorning (?:report|brief|update)\b|盘前|早盘|晨报|早报',title,re.I))
    commentary=bool(re.search(r'\b(?:snapshot|outlook|preview|commentary)\b|观点|评论|解读|展望',title,re.I))
    bank_commentary=host=='mufgresearch.com' or host.endswith('.mufgresearch.com')
    if morning:flags.append('morning_or_intraday_not_settlement')
    if commentary or bank_commentary:flags.append('commentary_not_original_policy_release')
    return dict(owner='finance-material-role-v1',flags=flags,
        latest_close_allowed=not morning,
        commodity_settlement_allowed=not morning,
        original_policy_release_allowed=not (commentary or bank_commentary),
        session_verified=False,source_identity_verified=False,
        limitation='仅限制明显不匹配用途；未被限制不表示收盘、政策发布或作者身份已核实。')


def lane_allowed(item,lane):
    role=assess_role(item)
    if lane in {'a_market','hk_market','us_market'}:return role['latest_close_allowed']
    if lane=='commodities':return role['commodity_settlement_allowed']
    if lane=='global_policy':return role['original_policy_release_allowed']
    return True
