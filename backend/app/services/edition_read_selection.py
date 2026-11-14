"""Choose bounded article reads from metadata. Never certify news or independence."""
import re
from urllib.parse import urlsplit
from .search_objectives import primary_candidate

INCREMENTS = {'original_source', 'new_update', 'independent_verification',
              'counterevidence', 'missing_context', 'access_failure'}


def validate_increment(request):
    if (request.get('increment') not in INCREMENTS or not isinstance(request.get('reason'), str)
            or not 12 <= len(request['reason'].strip()) <= 400):
        raise ValueError('edition_read_increment_required')


def primary_plan(events):
    jobs, trace = [], []
    for event in events:
        selected = event['read_ids'][:1]
        if selected:
            jobs.append(dict(event_id=event['id'], candidate_id=selected[0], increment='representative',
                reason=event['reason'], fallback_ids=list(event['candidate_ids']), allow_fallback=True))
        trace.append(dict(phase='representative', event_id=event['id'], selected_ids=selected,
            deferred_ids=[cid for cid in event['candidate_ids'] if cid not in selected],
            basis='模型选定的一篇代表稿；其余候选保留，后续按具体缺口补读。'))
    return jobs, trace


def _words(text):
    words = set(re.findall(r'[a-z0-9]{3,}', text.lower()))
    for span in re.findall(r'[\u4e00-\u9fff]+', text):
        words.update(span[i:i+2] for i in range(len(span)-1))
    return words


def _origin(row):
    hint = row.get('original_source') or row.get('publisher') or row.get('source')
    if not isinstance(hint, str) or not hint.strip():
        match = re.search(r'(?:来源|转载自|转自|\bSource)\s*[:：]\s*([^\s，。；|<>]{2,35})',
                          str(row.get('snippet') or ''), re.I)
        hint = match.group(1) if match else ''
    return re.sub(r'\s+', '', hint).casefold()


def _signature(row):
    title = re.sub(r'[\W_]+', '', str(row.get('title') or '')).casefold()
    origin, published = _origin(row), row.get('published_hint')
    return (title, origin, published) if title and origin and isinstance(published, str) and published else None


def _available(state, cid):
    url = state['candidates'][cid]['url']
    return any(source['url'] == url for source in state.get('sources', {}).values())


# A small translation table for commodity nouns, not a list of favored events.
COMMODITY_TERMS = (
    (r'黄金|金价', {'gold'}), (r'白银|银价', {'silver'}),
    (r'铜', {'copper'}), (r'原油|油价|石油', {'oil', 'crude', 'brent'}),
    (r'中东', {'middle', 'east'}), (r'伊朗', {'iran'}))
TOPIC_FILLER = {'一个', '来源', '原文', '当前', '相关', '方面', '报道', '最新', '消息',
                '原始', '核对', '具体', '说明', '影响', '公司', '资料'}


def topic_words(text, lane):
    words = _words(text) - TOPIC_FILLER
    if lane == 'commodities':
        for pattern, aliases in COMMODITY_TERMS:
            if re.search(pattern, text): words.update(aliases)
    return words


def stale_hint(state, event, row):
    """Only a ranking hint; the body parser still verifies publication time."""
    from datetime import datetime, timedelta, timezone
    from email.utils import parsedate_to_datetime
    cutoff, raw = state.get('cutoff'), row.get('published_hint')
    if not isinstance(cutoff, str) or not isinstance(raw, str): return False
    try:
        now = datetime.fromisoformat(cutoff)
        try: stamp = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        except ValueError: stamp = parsedate_to_datetime(raw)
        if stamp.tzinfo: stamp = stamp.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
        if now.tzinfo: now = now.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
        hours = (168 if event['purpose'] == 'commentary' or now.weekday() >= 5
                 and event['purpose'] in {'company_event', 'released_policy'}
                 else 96 if now.weekday() >= 5 else 72)
        return stamp.date() < (now-timedelta(hours=hours)).date() or stamp.date() > now.date()
    except (ValueError, TypeError, OverflowError):
        return False


def candidate_admission(state, event, row, request):
    # A search excerpt can quote recommendations unrelated to the page title.
    # Require the company itself for a direct company research task, and avoid
    # choosing a same-language title solely because its snippet mentions a topic.
    flags = []
    scope = request.get('scope') or event.get('scope')
    stock = next((s for s in state.get('watchlist', [])
                  if s['market'] + ':' + s['code'] == scope), None)
    title = str(row.get('title') or '')
    if stock and not (stock['name'].casefold() in title.casefold()
                      or re.search(r'(?<!\d)' + re.escape(stock['code']) + r'(?!\d)', title)):
        flags.append('company_not_title_subject')
    event_title = event['title'] + ' ' + str(request.get('reason') or '')
    chinese = lambda text: len(re.findall(r'[\u4e00-\u9fff]', text)) >= 4
    lane = event.get('lane')
    known_commodity_aliases = lane == 'commodities' and any(re.search(p, event_title) for p, _ in COMMODITY_TERMS)
    if chinese(event_title) and chinese(title) or known_commodity_aliases:
        if not (topic_words(event_title, lane) & topic_words(title, lane)):
            flags.append('title_topic_not_supported_by_metadata')
    return flags


def select_candidate(state, event, candidate_ids, request):
    tried = {r['candidate_id'] for r in state.get('read_receipts', [])}
    known = [state['candidates'][s['candidate_id']] for s in state.get('sources', {}).values()
             if s.get('candidate_id') in state['candidates'] and event['id'] in s.get('event_ids', [])]
    signatures = {_signature(row) for row in known} - {None}
    origins = {_origin(row) for row in known} - {''}
    query = event['title'] + ' ' + request.get('query', '') + ' ' + request.get('reason', '')
    questions = topic_words(query, event.get('lane'))
    ranked, skipped = [], []
    lane = event['lane'] if event['purpose'] in {'released_policy', 'latest_close'} else None
    for cid in dict.fromkeys(candidate_ids):
        row = state['candidates'][cid]
        if cid in tried or _available(state, cid):
            skipped.append(dict(candidate_id=cid, reason='already_attempted_or_stored'))
            continue
        hint = primary_candidate(row, lane)
        blocked = candidate_admission(state, event, row, request)
        if not hint['main_source_option'] or blocked:
            skipped.append(dict(candidate_id=cid, reason='metadata_purpose_mismatch', flags=hint['flags'] + blocked))
            continue
        same_origin = bool(_origin(row) and _origin(row) in origins)
        if request.get('increment') == 'independent_verification' and same_origin:
            skipped.append(dict(candidate_id=cid, reason='same_declared_upstream_not_independent'))
            continue
        probable_reprint = _signature(row) in signatures if _signature(row) else False
        similarity = len(questions & topic_words(str(row.get('title') or '') + ' ' + str(row.get('snippet') or ''), event.get('lane')))
        # Relevance is a metadata hint. Domain/time/title do not certify truth.
        old_hint = stale_hint(state, event, row)
        rank = (old_hint, probable_reprint, hint['priority'], -similarity,
                urlsplit(row['url']).hostname or '', row['url'], cid)
        ranked.append((rank, cid, dict(candidate_id=cid, likely_reprint=probable_reprint,
            relevance_terms=similarity, published_hint_outside_window=old_hint, purpose_flags=hint['flags'])))
    ranked.sort(key=lambda item: item[0])
    chosen = ranked[0][1] if ranked else None
    return chosen, dict(event_id=event['id'], increment=request.get('increment'), reason=request.get('reason'),
        selected_ids=[chosen] if chosen else [],
        ranked=[item[2] for item in ranked], skipped=skipped,
        deferred_ids=[item[1] for item in ranked[1:]],
        basis='按转载线索、来源用途、缺口词匹配排序；同分按URL稳定排序。只读一篇，不认证独立性、事实或覆盖。')


def patch_plan(state, events, assessment, extra_events):
    jobs, trace = [], []
    planned = set()
    grouped = {}
    for request in assessment.get('additional_searches', []):
        validate_increment(request)
        grouped.setdefault((request['event_id'], request['increment']), []).append(request)
    def search_options(key):
        queries = {r['query'] for r in grouped.get(key, [])}
        return [cid for cid, row in state['candidates'].items()
            if any(link.get('event_id') == key[0] and link.get('query') in queries
                   for link in row.get('search_links', []))]
    for request in assessment.get('additional_reads', []):
        validate_increment(request)
        event, cid = events[request['event_id']], request['candidate_id']
        key = event['id'], request['increment']
        if key in planned:
            trace.append(dict(phase='increment', event_id=event['id'], selected_ids=[],
                              deferred_ids=[cid], reason='one_article_per_event_increment'))
            continue
        row = state['candidates'][cid]
        hint = primary_candidate(row, None)
        blocked = candidate_admission(state, event, row, request)
        if not hint['main_source_option'] or blocked:
            trace.append(dict(phase='increment', event_id=event['id'], selected_ids=[],
                deferred_ids=[cid], reason='metadata_not_admitted', flags=hint['flags'] + blocked))
            continue
        known = [state['candidates'][s['candidate_id']] for s in state.get('sources', {}).values()
                 if s.get('candidate_id') in state['candidates'] and event['id'] in s.get('event_ids', [])]
        if (request['increment'] == 'independent_verification' and _origin(row)
                and any(_origin(row) == _origin(other) for other in known)):
            trace.append(dict(phase='increment', event_id=event['id'], selected_ids=[],
                deferred_ids=[cid], reason='same_declared_upstream_not_independent'))
            continue
        planned.add(key)
        alternatives = search_options(key)
        jobs.append(dict(request, allow_fallback=bool(alternatives), fallback_ids=alternatives))
        trace.append(dict(phase='increment', event_id=event['id'], selected_ids=[cid],
                          increment=request['increment'], reason=request['reason']))
    extra_jobs, extra_trace = primary_plan(extra_events)
    jobs.extend(extra_jobs); trace.extend(extra_trace)
    planned.update((j['event_id'], j['increment']) for j in jobs)
    for key, requests in grouped.items():
        if key in planned:
            continue
        request = dict(requests[0])
        queries = {r['query'] for r in requests}
        request['query'] = ' '.join(sorted(queries))
        event = events[request['event_id']]
        options = [cid for cid, row in state['candidates'].items()
            if any(link.get('event_id') == event['id'] and link.get('query') in queries
                   for link in row.get('search_links', []))]
        cid, record = select_candidate(state, event, options, request)
        record['phase'] = 'patch_search'; trace.append(record)
        if cid:
            jobs.append(dict(request, candidate_id=cid, allow_fallback=True, fallback_ids=options))
    return jobs, trace


def fallback_plan(state, events, job):
    if not job.get('allow_fallback') or _available(state, job['candidate_id']):
        return None, None
    request = dict(job, increment=('access_failure' if job['increment'] == 'representative'
                                  else job['increment']),
                   reason='前一篇未取得合格正文，换一个来源；原问题：' + job['reason'])
    # The first attempt may be supplied by an injected offline reader with no
    # receipt; still never select the failed URL a second time.
    failed_url = state['candidates'][job['candidate_id']]['url']
    options = [cid for cid in job.get('fallback_ids', [])
               if state['candidates'][cid]['url'] != failed_url]
    cid, trace = select_candidate(state, events[job['event_id']], options, request)
    trace['phase'] = 'fallback'
    return (dict(request, candidate_id=cid, allow_fallback=False) if cid else None), trace
