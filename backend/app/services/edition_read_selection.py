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


def select_candidate(state, event, candidate_ids, request):
    tried = {r['candidate_id'] for r in state.get('read_receipts', [])}
    known = [state['candidates'][s['candidate_id']] for s in state.get('sources', {}).values()
             if s.get('candidate_id') in state['candidates'] and event['id'] in s.get('event_ids', [])]
    signatures = {_signature(row) for row in known} - {None}
    origins = {_origin(row) for row in known} - {''}
    query = event['title'] + ' ' + request.get('query', '') + ' ' + request.get('reason', '')
    questions = _words(query)
    ranked, skipped = [], []
    lane = event['lane'] if event['purpose'] in {'released_policy', 'latest_close'} else None
    for cid in dict.fromkeys(candidate_ids):
        row = state['candidates'][cid]
        if cid in tried or _available(state, cid):
            skipped.append(dict(candidate_id=cid, reason='already_attempted_or_stored'))
            continue
        hint = primary_candidate(row, lane)
        if not hint['main_source_option']:
            skipped.append(dict(candidate_id=cid, reason='metadata_purpose_mismatch', flags=hint['flags']))
            continue
        same_origin = bool(_origin(row) and _origin(row) in origins)
        if request.get('increment') == 'independent_verification' and same_origin:
            skipped.append(dict(candidate_id=cid, reason='same_declared_upstream_not_independent'))
            continue
        probable_reprint = _signature(row) in signatures if _signature(row) else False
        similarity = len(questions & _words(str(row.get('title') or '') + ' ' + str(row.get('snippet') or '')))
        # Relevance is a metadata hint. Domain/time/title do not certify truth.
        rank = (probable_reprint, hint['priority'], -similarity,
                urlsplit(row['url']).hostname or '', row['url'], cid)
        ranked.append((rank, cid, dict(candidate_id=cid, likely_reprint=probable_reprint,
            relevance_terms=similarity, purpose_flags=hint['flags'])))
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
    for request in assessment.get('additional_reads', []):
        validate_increment(request)
        event, cid = events[request['event_id']], request['candidate_id']
        key = event['id'], request['increment']
        if key in planned:
            trace.append(dict(phase='increment', event_id=event['id'], selected_ids=[],
                              deferred_ids=[cid], reason='one_article_per_event_increment'))
            continue
        row = state['candidates'][cid]
        known = [state['candidates'][s['candidate_id']] for s in state.get('sources', {}).values()
                 if s.get('candidate_id') in state['candidates'] and event['id'] in s.get('event_ids', [])]
        if (request['increment'] == 'independent_verification' and _origin(row)
                and any(_origin(row) == _origin(other) for other in known)):
            trace.append(dict(phase='increment', event_id=event['id'], selected_ids=[],
                deferred_ids=[cid], reason='same_declared_upstream_not_independent'))
            continue
        planned.add(key)
        jobs.append(dict(request, allow_fallback=False))
        trace.append(dict(phase='increment', event_id=event['id'], selected_ids=[cid],
                          increment=request['increment'], reason=request['reason']))
    extra_jobs, extra_trace = primary_plan(extra_events)
    jobs.extend(extra_jobs); trace.extend(extra_trace)
    planned.update((j['event_id'], j['increment']) for j in jobs)
    grouped = {}
    for request in assessment.get('additional_searches', []):
        validate_increment(request)
        key = request['event_id'], request['increment']
        grouped.setdefault(key, []).append(request)
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
