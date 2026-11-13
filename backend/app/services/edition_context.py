"""Stage-specific model inputs; the persisted research pool remains untouched."""
from copy import deepcopy


def source_packet(source):
    result = deepcopy(source)
    metadata = result.get('metadata')
    if isinstance(metadata, dict):
        # Remove only exact duplicates, never freshness, role or quality limits.
        for key in ('id', 'title', 'url', 'text', 'source_role', 'direct_scopes'):
            if key in result and metadata.get(key) == result[key]:
                metadata.pop(key, None)
    return result


def editorial_source_ids(state):
    assessment = state.get('assessment') or {}
    ready = {r['id'] for r in assessment.get('events', []) if r.get('status') == 'ready'}
    # Keep ALL bodies attached to a ready event, including contrary evidence
    # which the assessor did not quote. Watchlist evidence may be separate.
    ids = {sid for sid, source in state.get('sources', {}).items()
           if ready.intersection(source.get('event_ids', []))}
    for row in assessment.get('events', []) + assessment.get('watchlist_checks', []):
        if row.get('status') in {'ready', 'covered'}:
            ids.update(e['source_id'] for e in row.get('evidence', []))
    return sorted(ids)


def packet(state, stage):
    if stage not in {'agenda', 'assessment', 'patch_assessment', 'writing', 'review'}:
        raise ValueError('edition_context_stage_invalid')
    result = {k: deepcopy(state.get(k)) for k in ('cutoff', 'watchlist', 'report_type')}
    if stage == 'agenda':
        result['candidates'] = deepcopy(state.get('candidates', {}))
        return result
    result['agenda'] = deepcopy(state.get('agenda'))
    result['missing'] = deepcopy(state.get('missing', []))
    if stage in {'assessment', 'patch_assessment'}:
        result['candidates'] = deepcopy(state.get('candidates', {}))
        result['read_receipts'] = [{k: deepcopy(row[k]) for k in
            ('candidate_id', 'event_id', 'status', 'reason') if k in row}
            for row in state.get('read_receipts', [])]
        ids = state.get('sources', {}).keys()
        if stage == 'patch_assessment':
            result['assessment'] = deepcopy(state.get('assessment'))
            result['last_assessment'] = True
    else:
        # Assessment results and ALL major/excluded event reasons remain visible;
        # provider directories and executed tool plans are no longer useful here.
        assessment = state.get('assessment') or {}
        result['assessment'] = {k: deepcopy(assessment[k]) for k in
            ('events', 'watchlist_checks', 'missed_major_events') if k in assessment}
        ids = editorial_source_ids(state)
        result['prior_report'] = deepcopy(state.get('prior_report'))
        if stage == 'review':
            result['draft'] = deepcopy(state['draft'])
            # Legacy/resumed drafts must never lose an explicitly cited body.
            ids = set(ids) | {r['source_id'] for r in state['draft'].get('source_checks', [])}
    result['sources'] = {sid: source_packet(state['sources'][sid]) for sid in sorted(ids)}
    return result
