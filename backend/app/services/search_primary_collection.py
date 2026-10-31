"""Reviewed search-body intake -> incremental public collection, never an LLM.

Chat-assisted exports and a future server search provider use the same explicit
contract. Importing an export does not prove its content true or comprehensive.
"""
from datetime import datetime,timedelta,timezone
import hashlib,re

from ..models.news import News
from .evidence import article_url
from .event_observations import canonical
from .news_archive import identity
from .news_quality import excluded_reason,reading_scope
from .time_context import china_now
from .watchlist_repository import watchlist_signature

OWNER='finance-search-primary-v1'
LANES=('a_market','hk_market','us_market','global_policy','commodities','industry','company_event')


def local_time(value):
    stamp=datetime.fromisoformat(value)
    return stamp.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None) if stamp.tzinfo else stamp


def watchlist_rows(rows):
    if not isinstance(rows,list):raise ValueError('primary_watchlist_missing')
    result=[];seen=set()
    for row in rows:
        if not isinstance(row,dict):raise ValueError('primary_watchlist_invalid')
        code=row.get('code');market=row.get('market');name=row.get('name')
        if (market not in {'A','HK'} or not isinstance(code,str)
            or not re.fullmatch(r'\d{6}' if market=='A' else r'\d{5}',code)
            or not isinstance(name,str) or not name.strip()):raise ValueError('primary_watchlist_invalid')
        key=(market,code)
        if key in seen:raise ValueError('primary_watchlist_duplicate')
        seen.add(key);result.append(dict(code=code,market=market,name=name.strip()))
    return result


def search_agenda(stocks,cutoff):
    """Explicit coverage questions, not a claim that a search has happened."""
    day=cutoff.strftime('%Y年%m月%d日')
    rows=[dict(lane=lane,query=day+' '+query) for lane,query in [
        ('a_market','A股 最新收盘 市场主线 成交额 行业异动'),
        ('hk_market','港股 最新收盘 恒生科技 行业异动'),
        ('us_market','美股 最新收盘 科技巨头 重大公司事件'),
        ('global_policy','国际宏观 央行 财政 贸易 地缘风险 资本市场'),
        ('commodities','原油 黄金 铜 汇率 国债收益率 最新变化'),
        ('industry','产业 供需 价格 库存 订单 重大变化')]]
    for s in stocks:
        rows.append(dict(lane='company_event',scope=s['market']+':'+s['code'],
            query=day+' '+s['name']+' '+s['code']+' 重要消息 行业 同业 客户 供应商 风险'))
    return rows


def prepare(bundle,now=None):
    now=now or china_now()
    if not isinstance(bundle,dict) or bundle.get('owner')!=OWNER:raise ValueError('primary_bundle_contract_missing')
    cutoff=local_time(bundle['collected_at']);hours=bundle.get('hours',72)
    if type(hours) is not int or not 1<=hours<=72:raise ValueError('primary_window_invalid')
    if cutoff>now:raise ValueError('primary_snapshot_in_future')
    stocks=watchlist_rows(bundle.get('watchlist'));articles=bundle.get('articles')
    if not isinstance(articles,list):raise ValueError('primary_articles_missing')
    receipts=bundle.get('search_receipts',[])
    if not isinstance(receipts,list):raise ValueError('primary_search_receipts_invalid')
    checked=[]
    for receipt in receipts:
        if (not isinstance(receipt,dict) or not isinstance(receipt.get('query'),str)
            or not receipt['query'].strip()):raise ValueError('primary_search_receipts_invalid')
        try:date=local_time(receipt['checked_at'])
        except (ValueError,TypeError,KeyError):raise ValueError('primary_search_receipt_time_invalid') from None
        if date>cutoff:raise ValueError('primary_search_receipt_after_cutoff')
        if receipt.get('status') in {'searched','searched_not_exhaustive','completed','ok'}:checked.append(date)
    # Re-exporting old search results must not refresh their discovery clock.
    discovery_start=min(checked) if checked else None
    news=[];seen={};accepted=[];rejected=[]
    for index,row in enumerate(articles):
        try:
            if not isinstance(row,dict):raise ValueError('article_shape_invalid')
            if row.get('body_scope') not in {'visible_body','full_text'}:raise ValueError('not_report_body')
            title=row.get('title');body=row.get('body');url=row.get('url');source=row.get('source_name')
            if not all(isinstance(x,str) and x.strip() for x in (title,body,url,source)):raise ValueError('article_fields_missing')
            if len(body.strip())<80 or re.search(r'<(?:html|script|body)\b',body,re.I):raise ValueError('article_body_unusable')
            if not article_url(url):raise ValueError('article_url_invalid')
            observed=local_time(row['observed_at']);published=local_time(row['published_at'])
            if observed>cutoff:raise ValueError('body_observed_after_cutoff')
            if published>observed:raise ValueError('publication_after_observation')
            precision=row.get('publication_precision')
            if precision not in {'day','minute','second'}:raise ValueError('publication_precision_missing')
            if precision=='day' and not re.fullmatch(r'\d{4}-\d{2}-\d{2}',row['published_at']):raise ValueError('day_precision_has_clock')
            publication_end=published+timedelta(days=1) if precision=='day' else published
            if publication_end<cutoff-timedelta(hours=hours):raise ValueError('article_outside_window')
            if published<cutoff-timedelta(hours=hours):raise ValueError('day_window_boundary_requires_review')
            lanes=row.get('lanes',[])
            if not isinstance(lanes,list) or any(lane not in LANES for lane in lanes):raise ValueError('article_lane_invalid')
            identifier='primary-'+hashlib.sha256((canonical(url)+'\0'+source+'\0'+row['published_at']+'\0'+body).encode()).hexdigest()[:24]
            n=News(id=identifier,title=title.strip(),content=body,source='公开网页可见正文-'+source.strip(),source_url=url,
                published_at=published,category='主动搜索主资料',importance_score=.5,
                market_impact='原始来源时点：'+row['published_at']+'；精度：'+precision+'；正文由显式资料包提供，未独立核实。')
            reason=excluded_reason(n)
            if reason:raise ValueError(reason)
            key=identity(n)
            if key in seen:
                accepted[seen[key]]['declared_lanes']=sorted(set(accepted[seen[key]]['declared_lanes'])|set(lanes))
                rejected.append(dict(index=index,reason='exact_body_version_already_present'));continue
            seen[key]=len(accepted);news.append(n)
            accepted.append(dict(id=n.id,url=url,title=n.title,characters=len(body),declared_lanes=lanes,
                observed_at=observed.isoformat(),remote_version_checked=False,
                producer_acquisition=row.get('acquisition','provided_external_body'),
                upstream=row.get('upstream'),input_scope=row['body_scope'],
                admission='provided_body_not_independent_verification'))
        except (ValueError,TypeError,KeyError) as error:
            reason=str(error) if isinstance(error,ValueError) and re.fullmatch(r'[a-z][a-z0-9_]+',str(error)) else 'article_fields_invalid'
            rejected.append(dict(index=index,reason=reason))
    if not news:raise RuntimeError('主动搜索主资料没有可接纳的报道正文；不回退为论坛或固定媒体扫库')
    lane_ids={lane:[r['id'] for r in accepted if lane in r['declared_lanes']] for lane in LANES}
    from .news_selection import matches_watchlist
    from .watchlist_service import WatchlistStock
    stock_coverage=[]
    for s in stocks:
        stock=WatchlistStock(s['code'],s['name'],s['market'])
        stock_coverage.append(dict(key=s['market']+':'+s['code'],name=s['name'],
            lexical_mentions=[n.id for n in news if matches_watchlist(n,[stock])],
            status='lexical_coverage_only_not_company_catalyst'))
    return news,dict(owner='finance-primary-collection-check-v1',collected_at=cutoff.isoformat(),
        expires_at=(cutoff+timedelta(hours=24)).isoformat(),hours=hours,watchlist=stocks,
        accepted=accepted,rejected=rejected,declared_body_coverage=lane_ids,
        missing_declared_lanes=[lane for lane in LANES if not lane_ids[lane]],watchlist_coverage=stock_coverage,
        planned_searches=search_agenda(stocks,cutoff),search_receipts=receipts,
        search_discovery_receipts_present=bool(checked),
        earliest_search_checked_at=discovery_start.isoformat() if discovery_start else None,
        snapshot_age_seconds=round((now-cutoff).total_seconds()),
        ready_for_public_collection=bool(discovery_start is not None and now-cutoff<=timedelta(hours=2)
            and now-discovery_start<=timedelta(hours=2)),
        http_requests_performed=0,model_requests_performed=0,tts_requests_performed=0,
        quality_acceptance='pending_human_review',
        limitation='主题覆盖来自导入声明，需逐项人工检查。正文准入、词项提及、目录数量均不是事实验证、主编选材或信息充分性的通过标记。导入不刷新远端版本。')


async def collect(bundle,now=None):
    """One explicit public run. No legacy fallback, account search or publishing."""
    news,report=prepare(bundle,now)
    if not report['ready_for_public_collection']:raise RuntimeError('主资料/检索截面超过2小时或缺少检索收据，停止新联合采集；可继续离线复核')
    from .watchlist_repository import read_app_watchlist
    live=await read_app_watchlist()
    signature=watchlist_signature(live)
    if signature!=watchlist_signature(report['watchlist']):raise RuntimeError('App自选股已改变，先更新主资料检索范围')
    from .news_collector import NewsCollectorService
    collector=NewsCollectorService(sentiment=False)
    try:
        combined=await collector.collect_all(hours=report['hours'],primary_news=news)
        if signature!=watchlist_signature(await read_app_watchlist()):raise RuntimeError('采集中App自选股改变，停止保存不一致资料包')
        report.update(mode='search_primary_public_supplements',watchlist_checked_against_app=True,
            primary_cutoff=report['collected_at'],public_collection_started_at=(now or china_now()).isoformat(),
            public_collection_finished_at=china_now().isoformat(),
            time_alignment='mixed_source_timestamps_require_review_not_synchronous_snapshot',
            news=[n.model_dump(mode='json') for n in combined],
            participant_documents=sum(reading_scope(n)=='public_statement' for n in combined),
            technical=getattr(collector,'_technical_snapshot',{}),microstructure=getattr(collector,'_microstructure_snapshot',{}),
            coverage=getattr(collector,'_radar_coverage',{}),
            public_collection_executed=True,http_requests_performed=None,
            http_count_note='具体公开HTTP尝试见各适配器诊断；不是零网络，未合并成精确请求总数。')
        return report
    finally:await collector.close()
