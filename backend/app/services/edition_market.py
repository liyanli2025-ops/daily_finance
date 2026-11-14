"""Connect the existing dated index/breadth adapters to the edition's HTTP ledger.

No money-flow inference, live quote in historical replay, or new paid data feed.
"""
from datetime import datetime
import math
import json
import re
import time
from types import SimpleNamespace

from .time_context import china_now

QUOTE_BASE = 'https://qt.gtimg.cn/q='
CATALOG_BASE = 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/'
COUNT = CATALOG_BASE + 'Market_Center.getHQNodeStockCount'
CATALOG = CATALOG_BASE + 'Market_Center.getHQNodeData'
SYMBOL = re.compile(r'(?:sh\d{6}|sz\d{6}|bj\d{6}|hkHSI|hkHSCEI|hkHSTECH|usDJI|usIXIC|usINX)')


def allowed_endpoint(url):
    if url in {COUNT, CATALOG}:
        return True
    return (url.startswith(QUOTE_BASE) and 0 < len(url) < 2500
            and all(SYMBOL.fullmatch(s) for s in url[len(QUOTE_BASE):].split(',')))


def collect(state, desk, *, observed=None, include_breadth=False):
    from .timed_market import INDICES, parse_quotes
    from .market_breadth import BreadthRadar
    observed = observed or china_now()
    cutoff = datetime.fromisoformat(state['cutoff'])
    result = dict(status='partial', observed_at=observed.isoformat(), indices=[], breadth={},
        expectation_baseline='not_supplied_requires_dated_original_evidence',
        gaps=['外汇和利率仍由当期正文核对；未接入专门结构化序列',
              '未接入期权仓位/资金流/一致预期接口，不推断空头回补、未定价或共识预期'],
        limitation='指数和A股样本宽度分开验时；不作跨市场同步快照，不保证最近完成交易日。')
    # Current endpoints cannot reconstruct history. Refuse before the first request.
    if observed.date() != cutoff.date() or abs((observed-cutoff).total_seconds()) > 7200:
        result.update(status='historical_live_read_refused')
        return result
    before = getattr(desk.workspace, 'public_fetch_attempts', 0)
    try:
        url = QUOTE_BASE + ','.join(INDICES)
        text = desk.request(url, None, response_kind='gbk')
        result['indices'] = parse_quotes(text, observed)
        result['indices'] = [r for r in result['indices'] if r['region'] == '美股'
            or datetime.fromisoformat(r['as_of']) <= cutoff]
        result['index_status'] = 'dated_quotes_pending_session_review' if result['indices'] else 'no_valid_quotes'
    except Exception as error:
        result['index_status'] = 'unavailable'
        result['index_error_type'] = type(error).__name__
    if not include_breadth:
        result['breadth'] = dict(status='not_requested',
            reason='daily_flow_prioritizes_article_evidence_no_unconditional_universe_scan')
        result['gaps'].append('本期未自动抓取全市场涨跌分布；指数涨跌不能替代市场宽度或资金流')
        result['public_fetch_attempts'] = getattr(desk.workspace, 'public_fetch_attempts', 0)-before
        result['status'] = 'observations_pending_review' if result['indices'] else 'unavailable'
        return result
    try:
        radar = BreadthRadar(mapper=lambda items, callback:[callback(item) for item in items])
        count_checked = False
        def request(url, params, deadline):
            nonlocal count_checked
            if time.monotonic() >= deadline:
                raise TimeoutError('breadth_budget_exhausted')
            # Leave at least 24 URL attempts for reading stories; never overrun the
            # same edition cap by launching an independent collector.
            used = getattr(desk.workspace, 'public_fetch_attempts', 0) - before
            remaining = state['policy']['max_body_urls'] * 3 - getattr(desk.workspace, 'public_fetch_attempts', 0)
            if used >= 128 or remaining <= 24:
                raise ValueError('breadth_edition_request_allocation_exhausted')
            if url == COUNT:
                options = dict(request_tag='breadth-final-count') if count_checked else {}
                value = desk.request(url, params, deadline=deadline, **options)
                expected = int(value)
                # Cold catalogue needs all pages and two count checks. Do not
                # download a partial universe which cannot pass the coverage gate.
                needed = math.ceil(expected/80) + math.ceil(expected/200) + 2
                if not 1000 <= expected <= 10000 or not count_checked and needed > min(128-used, remaining-24):
                    raise ValueError('breadth_complete_sample_exceeds_remaining_budget')
                count_checked = True
            elif url.startswith(QUOTE_BASE):
                text = desk.request(url, params, response_kind='gbk', deadline=deadline)
                return SimpleNamespace(text=text)
            else:
                value = desk.request(url, params, deadline=deadline)
            return SimpleNamespace(json=lambda:value)
        # The legacy adapter normally parallelizes pages; serialize this instance
        # so every network request is durably reserved before the next begins.
        radar.get = request
        result['breadth'] = radar.collect(budget=min(90, max(0, desk.deadline-time.monotonic())), cutoff=cutoff)
    except Exception as error:
        result['breadth'] = dict(status='unavailable', error_type=type(error).__name__)
    result['public_fetch_attempts'] = getattr(desk.workspace, 'public_fetch_attempts', 0)-before
    result['status'] = 'observations_pending_review' if result['indices'] or result['breadth'].get('status') == 'ok_sampled' else 'unavailable'
    return result


def evidence(result):
    """A small explicit derived document; API captures stay in the same episode."""
    from .edition_budget import digest
    if not result.get('indices') and result.get('breadth', {}).get('status') != 'ok_sampled':
        return None
    text = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2)
    sid = 'market-' + digest(result)[:24]
    return dict(id=sid, title='本期带日期行情观察（实际取得范围见正文）',
        url=QUOTE_BASE + 'sh000001', text=text, event_ids=[], candidate_id=None,
        metadata=dict(kind='market_observation', observed_at=result['observed_at'],
            derivation='既有指数及宽度适配器；原始API响应另存issuer-responses；并非媒体原文'),
        direct_scopes=[], source_role=dict(latest_close_allowed=False,
            original_policy_release_allowed=False, commodity_settlement_allowed=False,
            flags=['dated_observation_not_certified_latest_close']),
        limitation='仅支持明示样本、报价时点和算法的描述；不充最新收盘证明、资金流或预期基线。')
