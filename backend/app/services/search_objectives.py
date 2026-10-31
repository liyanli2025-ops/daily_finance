"""Retrieval purpose != story importance. Preserve leads and label their limits."""
from datetime import timedelta
import re
from urllib.parse import urlsplit

PURPOSES={'discovery','latest_close','released_policy','company_event','commentary'}
SOCIAL=('instagram.com','facebook.com','youtube.com','youtu.be','tiktok.com','pinterest.com')


def infer_purpose(query,lane):
    """Compatibility hint when a model omits purpose; explicit purpose wins."""
    if re.search(r'预测|预判|观点|分歧|forecast|preview',query,re.I):return 'commentary'
    if lane in {'a_market','hk_market','us_market'} and re.search(r'收盘|收评|market.*close|closing',query,re.I):return 'latest_close'
    if lane=='global_policy' and re.search(r'决议|声明|decision|statement',query,re.I):return 'released_policy'
    if lane=='company_event' or re.search(r'财报|earnings',query,re.I):return 'company_event'
    return 'discovery'


def request_profile(query,purpose,now,hours=72):
    if purpose not in PURPOSES:raise ValueError('search_purpose_invalid')
    if type(hours) is not int or not 1<=hours<=72:raise ValueError('search_window_invalid')
    if purpose not in {'latest_close','released_policy'}:
        return query,{}
    # Date filtering is only an engine hint. Publication/update date does not
    # verify trading date, event time, or whether an announcement has happened.
    if not re.search(r'(?<!\d)20\d{2}(?!\d)',query):query=query+' '+str(now.year)
    return query,dict(start_date=(now-timedelta(hours=hours)).date().isoformat(),
        end_date=(now+timedelta(days=1)).date().isoformat(),filter_by_published_date=True,
        exclude_domains=list(SOCIAL))


def assess(row,purpose='discovery',lane=None):
    """Headline/URL checks only. A rolling article may contain later updates."""
    title=str(row.get('title') or '');host=(urlsplit(row.get('url') or '').hostname or '').lower()
    flags=[]
    social=any(host==domain or host.endswith('.'+domain) for domain in SOCIAL)
    if social:flags.append('social_or_video_needs_platform_reader')
    if purpose=='latest_close':
        if re.search(r'盘前|开盘前|午评|早盘|盘中|集体低开|pre.market|before.*open',title,re.I):
            flags.append('session_or_rolling_update_needs_body_check')
        if (lane=='us_market' and re.search(r'台股|台湾股市|韓股|韩股|韩国股市|日股|日本股市',title)
            and not re.search(r'美股|华尔街|纳指|标普|道指|Wall Street|Nasdaq|S&P',title,re.I)):
            flags.append('different_market_primary_subject_hint')
        if re.search(r'单月|月内|月度|monthly',title,re.I):flags.append('monthly_period_not_daily_return_needs_body_check')
    if purpose=='released_policy':
        forecast=re.search(r'预测|预期|将风平|只差官宣|盘前|决议前|preview|expected|forecast',title,re.I)
        released=re.search(r'决议全文|声明全文|宣布|已公布|正式发布|发布声明|announces|issues.*statement',title,re.I)
        if forecast and not released:flags.append('forecast_or_commentary_not_release_confirmation')
    return dict(purpose=purpose,flags=flags,
        role='lead_needs_body_check' if flags else 'candidate_needs_body_check',
        reading_scope='metadata_only',event_or_session_verified=False,
        limitation='标题/域名启发式，不是重要性或真假裁决；滚动稿可能有后续更新，正文未核前不作结论。')


def executed_coverage(receipts,stocks):
    from .search_primary_collection import LANES
    lanes=set();scopes=set();queries=[]
    for receipt in receipts:
        req=receipt['request'];res=receipt['result']
        if req.get('tool')!='search' or res.get('status')!='ok':continue
        lanes.add(req['lane'])
        if req.get('scope'):scopes.add(req['scope'])
        queries.append(dict(lane=req['lane'],scope=req.get('scope'),purpose=res.get('purpose',req.get('purpose','discovery')),
                            requested_query=req['query'],effective_query=res.get('effective_query',req['query']),
                            metadata_results=len(res.get('results',[]))))
    return dict(actual_searches=queries,lanes_without_search_receipts=[lane for lane in LANES if lane not in lanes],
        stocks_without_scoped_search_receipts=[s['market']+':'+s['code'] for s in stocks if s['market']+':'+s['code'] not in scopes],
        limitation='仅记录实际成功的检索回执；有检索不等于覆盖充分，无定向回执不等于没有公司新闻。')
