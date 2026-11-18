"""Recover usable article inputs before paying for evidence assessment."""
import re

from .body_acquisition import host, read_target
from .edition_evidence_view import screen
from .edition_read_selection import candidate_admission, select_candidate, topic_words


MAX_EXTRA_READS = 8
MAX_EXTRA_READS_PER_EVENT = 2
MAX_TARGETED_SEARCHES = 2
SEARCH_STOPS = {
    'edition_search_budget_exhausted', 'edition_estimated_budget_exhausted',
    'edition_future_input_capacity_exhausted', 'edition_search_unavailable_no_retry',
}


def usable_body_ids(state, event):
    role_key = {
        'released_policy': 'original_policy_release_allowed',
        'latest_close': ('commodity_settlement_allowed' if event['lane'] == 'commodities'
                         else 'latest_close_allowed'),
    }.get(event['purpose'])
    request = dict(increment='access_failure', reason=event['reason'])
    return [
        identifier for identifier, source in state['sources'].items()
        if source.get('candidate_id') and source.get('text') and event['id'] in source['event_ids']
        and source.get('metadata', {}).get('kind') != 'financial_baseline'
        and (not role_key or source.get('source_role', {}).get(role_key) is not False)
        and (not event.get('scope') or event['scope'] in source.get('direct_scopes', []))
        and 'overview_cannot_fill_specific_result_gap' not in candidate_admission(
            state, event, state['candidates'].get(source['candidate_id'], source), request)
        and screen(source)['use'] == 'evidence_candidate'
    ]


def recovery_query(event, now):
    title = re.sub(r'https?://\S+', '', event['title'], flags=re.I)
    title = ' '.join(title.split())[:90].strip()
    if not title:
        return None
    chinese = re.search(r'[\u4e00-\u9fff]', title)
    qualifiers = {
        'released_policy': ('原文 正式发布', 'official release'),
        'latest_close': ('收盘 结算', 'closing report'),
        'company_event': ('公告 最新进展', 'filing update'),
    }
    zh, en = qualifiers.get(event['purpose'], ('原始来源 最新进展', 'source latest development'))
    return f'{now:%Y-%m-%d} {title} {zh if chinese else en}'


async def read_alternatives(pipeline, events, row, candidate_ids, remaining, request):
    state = pipeline.state
    event = events[row['event_id']]
    candidates = state['candidates']
    attempted_sites = {
        host(read_target(attempt.get('read_url') or candidates[attempt['candidate_id']]['url'])).removeprefix('www.')
        for attempt in state.get('read_receipts', []) if attempt['event_id'] == event['id']
    }
    while remaining and len(row['extra_read_ids']) < MAX_EXTRA_READS_PER_EVENT:
        if (len(state.get('read_receipts', [])) >= state['policy']['max_body_urls']
                or getattr(pipeline.workspace, 'public_fetch_attempts', 0) + 3 > state['policy']['max_body_urls'] * 3):
            row['stop_reason'] = 'public_read_budget_exhausted'
            break
        options = [cid for cid in candidate_ids if
                   host(read_target(candidates[cid]['url'])).removeprefix('www.') not in attempted_sites]
        cid, trace = select_candidate(state, event, options, request)
        if not cid:
            break
        attempted_sites.add(host(read_target(candidates[cid]['url'])).removeprefix('www.'))
        trace['phase'] = 'acquisition_recovery'
        row['extra_read_ids'].append(cid)
        if cid not in event['candidate_ids']:
            event['candidate_ids'].append(cid)
        await pipeline.selected_reads([dict(request, candidate_id=cid, allow_fallback=False)], events, [trace])
        remaining -= 1
        if usable_body_ids(state, event):
            break
    return remaining


async def recover(pipeline, events):
    state = pipeline.state
    rows = state.setdefault('acquisition_recovery', [])
    handled = {row['event_id'] for row in rows}
    search_count = sum(bool(row.get('search_query')) for row in rows)
    remaining = MAX_EXTRA_READS - sum(len(row['extra_read_ids']) for row in rows)
    search_stop = next((row['stop_reason'] for row in rows if row.get('stop_reason') in SEARCH_STOPS), None)
    for event in sorted(events.values(), key=lambda event: event['importance'] != 'major'):
        eid = event['id']
        if (eid in handled or (event['importance'] != 'major' and not event.get('scope'))
                or usable_body_ids(state, event)):
            continue
        row = dict(event_id=eid, status='checking', extra_read_ids=[], source_ids=[])
        rows.append(row)
        request = dict(event_id=eid, increment='access_failure', reason=event['reason'])
        terms = topic_words(event['title'], event['lane'])
        # Reuse nearby leads that were already paid for, even if the agenda
        # didn't shortlist them. Scope alone never makes a title relevant.
        nearby = [cid for cid, candidate in state['candidates'].items()
                  if any(link.get('lane') == event['lane'] and link.get('scope') == event.get('scope')
                         for link in candidate.get('search_links', []))
                  and len(terms & topic_words(candidate.get('title') or '', event['lane'])) >= 2]
        remaining = await read_alternatives(pipeline, events, row,
            list(dict.fromkeys(event['candidate_ids'] + nearby)), remaining, request)
        if (not usable_body_ids(state, event) and remaining and not row.get('stop_reason')
                and len(row['extra_read_ids']) < MAX_EXTRA_READS_PER_EVENT):
            query = recovery_query(event, pipeline.workspace.now)
            if search_stop or search_count >= MAX_TARGETED_SEARCHES:
                row['stop_reason'] = search_stop or 'targeted_search_limit'
            elif query and not any(saved['query'] == query for saved in state.get('search_receipts', [])):
                row['search_query'] = query
                search_count += 1
                pipeline.save()
                try:
                    await pipeline.searches([dict(request, query=query, lane=event['lane'],
                        scope=event.get('scope'), purpose=event['purpose'], discovery_scope='acquisition_recovery')])
                except (RuntimeError, ValueError) as error:
                    if str(error) not in SEARCH_STOPS:
                        raise
                    search_stop = row['stop_reason'] = str(error)
                else:
                    options = [cid for cid, candidate in state['candidates'].items()
                               if any(link.get('query') == query and link.get('event_id') == eid
                                      for link in candidate.get('search_links', []))]
                    remaining = await read_alternatives(pipeline, events, row, options, remaining, request)
        row['source_ids'] = usable_body_ids(state, event)
        row['status'] = 'body_candidate' if row['source_ids'] else 'evidence_gap'
        if not row['source_ids']:
            row.setdefault('stop_reason', 'additional_read_limit' if not remaining or
                           len(row['extra_read_ids']) >= MAX_EXTRA_READS_PER_EVENT else 'no_suitable_body')
        pipeline.save()
