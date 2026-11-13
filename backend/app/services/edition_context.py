"""Stage-specific model inputs; the persisted research pool remains untouched."""
from copy import deepcopy
import json


def candidate_packet(candidates):
    """Losslessly intern repeated context; never truncate candidates or snippets."""
    core = ('title', 'url', 'snippet', 'published_hint')
    def reserved(value):
        if isinstance(value, dict):
            return '$ref' in value or any(reserved(v) for v in value.values())
        return isinstance(value, list) and any(reserved(v) for v in value)
    if (not candidates or any(not all(k in row for k in core) for row in candidates.values())
            or reserved(candidates)):
        return dict(candidates=deepcopy(candidates))
    counts = {}
    def token(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    def count(value):
        key = token(value)
        if len(key) > 32:
            counts[key] = counts.get(key, 0) + 1
        if isinstance(value, dict):
            for v in value.values(): count(v)
        elif isinstance(value, list):
            for v in value: count(v)
    extras = {cid: {k: deepcopy(v) for k, v in row.items() if k not in core}
              for cid, row in candidates.items()}
    for row in extras.values(): count(row)
    bank, indices = [], {}
    def children(value):
        if isinstance(value, dict): return {k: encode(v) for k, v in value.items()}
        if isinstance(value, list): return [encode(v) for v in value]
        return value
    def encode(value):
        key = token(value)
        if counts.get(key, 0) > 1:
            if key not in indices:
                indices[key] = len(bank)
                bank.append(None)
                bank[indices[key]] = children(value)
            return {'$ref': indices[key]}
        return children(value)
    rows = {cid: [deepcopy(row[k]) for k in core] + [encode(extras[cid])]
            for cid, row in candidates.items()}
    result = dict(candidates=rows, candidate_columns=list(core) + ['attributes'], candidate_shared=bank,
        candidate_codec='每个候选数组按candidate_columns列顺序读取；attributes内单独的{"$ref":n}等于candidate_shared[n]原值，可嵌套。仅无损去重，候选ID和标题/链接/完整摘要/时点均保留，仍须逐个判断。')
    if len(token(result)) >= len(token(dict(candidates=candidates))):
        return dict(candidates=deepcopy(candidates))
    return result


def source_packet(source):
    result = deepcopy(source)
    metadata = result.get('metadata')
    if isinstance(metadata, dict):
        # Remove only exact duplicates, never freshness, role or quality limits.
        for key in ('id', 'title', 'url', 'text', 'source_role', 'direct_scopes'):
            if key in result and metadata.get(key) == result[key]:
                metadata.pop(key, None)
    return result


def assessment_candidates(state):
    rows = deepcopy(state.get('candidates', {}))
    agenda = state.get('agenda') or {}
    major = {cid for event in agenda.get('events', []) if event.get('importance') == 'major'
             for cid in event.get('candidate_ids', [])}
    excluded = {cid for item in agenda.get('excluded_candidates', []) for cid in item['candidate_ids']}
    read_ids = {s.get('candidate_id') for s in state.get('sources', {}).values()}
    read_urls = {s.get('url') for s in state.get('sources', {}).values()}
    for cid, row in rows.items():
        if cid in major or 'snippet' not in row:
            continue
        if cid in read_ids or row.get('url') in read_urls:
            row['snippet'] = None
            row['snippet_note'] = '本次同时提供了对应正文；搜索摘要不重复发送，原摘要仍在本地。'
        elif cid in excluded:
            row['snippet'] = None
            row['snippet_note'] = '摘要已提供给选题阶段；本阶段依据标题、时点和选题单排除理由复核遗漏。原摘要仍在本地，值得补查可提出读取。'
    return rows


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
        result.update(candidate_packet(state.get('candidates', {})))
        return result
    result['agenda'] = deepcopy(state.get('agenda'))
    result['missing'] = deepcopy(state.get('missing', []))
    if stage in {'assessment', 'patch_assessment'}:
        result.update(candidate_packet(assessment_candidates(state)))
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
