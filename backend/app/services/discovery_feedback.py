"""Recompute collection gaps from receipts; never invent searches or evidence.

The controller checks acquisition and exposure, not truth, importance, issuer
identity or whether a source independently corroborates another source.
"""
import hashlib
from collections import deque

from .news_quality import excluded_reason, reading_scope
from .news_selection import within_window
from .primary_material_quality import QUESTIONS, review_body
from .search_primary_collection import LANES
from .collection_time import receipt_windows,eligible as time_eligible,policy


def cited_ids(dossier):
    return sorted({identifier for key in ('events', 'coverage', 'watchlist_checks')
                   for row in dossier.get(key, []) for identifier in row.get('evidence_ids', [])})


def complete_local_reads(workspace, state, limits, *, room_for_text, checkpoint, active=lambda: True):
    """Provide missing stored ranges within the same shared local/input budget.

    The callbacks supply the caller's actual remaining input space and deadline.
    No model, HTTP request, source choice or date refresh happens here.
    """
    provided = set(state.get('provided_ids', []))
    order = []
    for receipt in state['receipts']:
        result = receipt.get('result', {})
        identifier = result.get('material', result).get('id')
        if result.get('status') == 'ok' and identifier in provided and identifier not in order:
            order.append(identifier)
    order.extend(identifier for identifier in state.get('provided_ids', []) if identifier not in order)
    records = body_records(workspace, state['receipts'])
    initial_used = state.get('local_read_characters', 0)
    remaining_turns = (max(1, limits.model_calls-state['model_calls']) if limits.model_calls is not None
                       else 2) if 'model_calls' in state else 1
    allowance = max(1, (limits.local_read_characters-initial_used)//remaining_turns)
    queue = deque(identifier for identifier in order if records.get(identifier, {}).get('eligible')
                  and records[identifier]['unread_ranges'])
    unserved = len(queue)
    while queue and active():
        used = state.get('local_read_characters', 0)
        remaining = min(limits.local_read_characters-used, allowance-(used-initial_used))
        available = max(0, room_for_text())
        if min(remaining, available) <= 0:
            break
        share = max(1, min(remaining, available)//unserved)
        identifier = queue.popleft()
        unserved -= 1
        row = body_records(workspace, state['receipts'])[identifier]
        # Read the unprovided ending first when space is scarce. This exposes
        # late caveats without pretending that the middle has been provided.
        tail = row['unread_ranges'][-1][1] == row['characters']
        start, end = row['unread_ranges'][-1] if tail else row['unread_ranges'][0]
        chars = min(4000, end-start, share)
        offset = end-chars if tail else start
        result = workspace.read(identifier, offset=offset, characters=chars)
        if result.get('status') == 'ok':
            state['local_read_characters'] = state.get('local_read_characters', 0)+len(result['text'])
        state['receipts'].append(dict(request=dict(tool='read_more', id=identifier, offset=offset,
            characters=chars, reason='预算内轮流补读已存正文；先核后段，再补中间缺口，不增加HTTP'),
            result=result, origin='controller_local_completion',
            reading_strategy='tail_first_fair_share' if tail else 'fill_remaining_gap'))
        checkpoint()
        if result.get('status') == 'ok' and body_records(workspace, state['receipts'])[identifier]['unread_ranges']:
            queue.append(identifier)
        if unserved == 0:
            unserved = len(queue)


def body_records(workspace, receipts):
    records = {}
    for receipt in receipts:
        result = receipt.get('result', {})
        material = result.get('material', result)
        if result.get('status') != 'ok' or not isinstance(material.get('text'), str):
            continue
        identifier = material.get('id')
        item = workspace.documents.get(identifier)
        if item is None or not hasattr(item, 'content'):
            continue
        row = records.setdefault(identifier, dict(id=identifier, ranges=[], invalid_receipt=False))
        offset, text = material.get('offset', 0), material['text']
        if (type(offset) is not int or offset < 0 or not text
                or item.content[offset:offset+len(text)] != text):
            row['invalid_receipt'] = True
        else:
            row['ranges'].append([offset, offset+len(text)])
    for identifier, row in records.items():
        item = workspace.documents[identifier]
        digest = hashlib.sha256(item.content.encode()).hexdigest()
        row['ranges'] = workspace.merged_ranges(row['ranges'])
        cursor, gaps = 0, []
        for start, end in row['ranges']:
            if cursor < start:
                gaps.append([cursor, start])
            cursor = max(cursor, end)
        if cursor < len(item.content):
            gaps.append([cursor, len(item.content)])
        row.update(characters=len(item.content), text_sha256=digest, unread_ranges=gaps,
                   body_quality=review_body(item.content), lanes=[], direct_scopes=[],
                   source_windows=receipt_windows(receipts,identifier,workspace.now))
        row['eligible'] = bool(not row['invalid_receipt'] and row['ranges']
            and len(item.content.strip()) >= 80
            and digest == workspace.document_hashes.get(identifier)
            and reading_scope(item) in {'full_text', 'visible_body', 'wire_text'}
            and not excluded_reason(item) and time_eligible(item, workspace.now, row['source_windows'])
            and not row['body_quality']['requires_editorial_review'])
    return records


def build_feedback(workspace, state, stocks, limits):
    from .primary_discovery import landing_page, unsupported_page
    receipts, candidates = state.get('receipts', []), state.get('candidates', {})
    bodies = body_records(workspace, receipts)
    searched_lanes, searched_scopes, outcomes = set(), set(), {}
    for receipt in receipts:
        request, result = receipt['request'], receipt['result']
        if request.get('tool') == 'search' and result.get('status') == 'ok':
            searched_lanes.add(request['lane'])
            if request.get('scope'):
                searched_scopes.add(request['scope'])
        if request.get('tool') != 'read':
            continue
        candidate_id = request.get('candidate_id')
        outcome = outcomes.setdefault(candidate_id, dict(terminal_failure=False, rejected_scopes=[], stored_body_id=None))
        reason = result.get('reason')
        if result.get('status') in {'failed', 'unavailable', 'unsupported', 'needs_local_review'} or (
                result.get('status') == 'rejected' and reason not in
                {'direct_company_not_in_candidate', 'direct_company_not_in_body','direct_company_not_primary_subject'}):
            outcome['terminal_failure'] = True
        if result.get('status') == 'rejected' and reason in {
                'direct_company_not_in_candidate', 'direct_company_not_in_body','direct_company_not_primary_subject'}:
            if request.get('scope') not in outcome['rejected_scopes']:
                outcome['rejected_scopes'].append(request.get('scope'))
        cached_id = (result.get('material', {}).get('id') if result.get('status') == 'ok'
                     else result.get('stored_body_id'))
        if cached_id in workspace.documents:
            outcome['stored_body_id'] = cached_id
        row = bodies.get(result.get('material', {}).get('id'))
        if result.get('status') != 'ok' or row is None:
            continue
        candidate = candidates.get(candidate_id, {})
        lanes = {r['lane'] for r in result.get('research_links', candidate.get('discovered_by', []))}
        source_item=workspace.documents[result['material']['id']]
        # A background window does not qualify as evidence of the latest
        # market session or an actual new policy release.
        market_hours=policy(workspace.now)['hours']['latest_close'] if row['source_windows'] else 72
        if not within_window(source_item,workspace.now,market_hours):
            lanes-={'a_market','hk_market','us_market','global_policy'}
        if result.get('source_window',{}).get('purpose')=='commentary':
            lanes-={'a_market','hk_market','us_market','global_policy'}
        # Industry/direct relations are explicit research uses, not inferred
        # from body keywords. Even these links do NOT verify the subject.
        if request.get('relation') == 'direct':
            lanes &= {'company_event'}
            if request.get('scope'):
                from .news_quality import company_focus
                from types import SimpleNamespace
                company=next((stock for stock in stocks if stock['market']+':'+stock['code']==request['scope']),None)
                if company is not None and company_focus(source_item,SimpleNamespace(**company)):
                    row['direct_scopes'].append(request['scope'])
        elif request.get('relation') == 'industry':
            lanes &= {'industry'}
        row['lanes'] = sorted(set(row['lanes']) | lanes)
        row['direct_scopes'] = sorted(set(row['direct_scopes']))
    remaining = dict(model_calls=(max(0, limits.model_calls-state.get('model_calls', 0))
                                  if limits.model_calls is not None else None),
        searches=max(0, state['effective_search_limit']-state.get('search_tool_calls', 0)),
        body_urls=max(0, limits.body_urls-state.get('body_url_calls', 0)),
        local_characters=max(0, limits.local_read_characters-state.get('local_read_characters', 0)))
    search_available = bool(remaining['searches'] and remaining['body_urls'] and not state.get('search_route_failed'))

    def reusable(identifier):
        if identifier in bodies:
            return bodies[identifier]['eligible']
        item = workspace.documents.get(identifier)
        return bool(item is not None and hasattr(item, 'content') and len(item.content.strip()) >= 80
            and hashlib.sha256(item.content.encode()).hexdigest() == workspace.document_hashes.get(identifier)
            and reading_scope(item) in {'full_text', 'visible_body', 'wire_text'} and not excluded_reason(item)
            and time_eligible(item, workspace.now, receipt_windows(receipts,identifier,workspace.now))
            and not review_body(item.content)['requires_editorial_review'])
    tasks, lanes, watchlist = [], [], []
    for identifier, row in bodies.items():
        if not row['eligible']:
            continue
        if row['unread_ranges']:
            start, end = row['unread_ranges'][0]
            tasks.append(dict(task_id='body:'+identifier+':read_remaining', kind='read_remaining',
                evidence_ids=[identifier], candidate_ids=[], executable=bool(remaining['local_characters']),
                next_request=(dict(tool='read_more', id=identifier, offset=start,
                                  characters=min(4000, end-start, remaining['local_characters']))
                              if remaining['local_characters'] else None),
                question='补读已存正文未提供区间，不重新下载；未提供不等于已读完。'))

    def target(key, lane, scope=None):
        ids = sorted(identifier for identifier, row in bodies.items() if row['eligible']
                     and (scope in row['direct_scopes'] if scope else lane in row['lanes']))
        fresh, cached = [], []
        for identifier, candidate in candidates.items():
            outcome = outcomes.get(identifier, {})
            if (outcome.get('terminal_failure') or scope and scope in outcome.get('rejected_scopes', [])
                    or landing_page(candidate['url']) or unsupported_page(candidate['url'])):
                continue
            links = candidate.get('discovered_by', [])
            if any(r.get('scope') == scope if scope else r.get('lane') == lane for r in links):
                cached_id = outcome.get('stored_body_id')
                if cached_id:
                    if cached_id not in ids and reusable(cached_id):
                        cached.append(identifier)
                else:
                    fresh.append(identifier)
        unread = cached+fresh
        readable = bool(cached or fresh and remaining['body_urls'])
        successful_search = scope in searched_scopes if scope else lane in searched_lanes
        row = dict(key=key, lane=lane, scope=scope, body_ids=ids,
                   successful_search=successful_search, unread_candidate_ids=unread,
                   reusable_candidate_ids=cached, fresh_candidate_ids=fresh,
                   subject_verified=False, coverage_sufficient=False)
        if not ids:
            kind = 'read_candidate' if readable else 'search_alternative'
            tasks.append(dict(task_id=key+':locate_body', kind=kind, lane=lane, scope=scope,
                evidence_ids=[], candidate_ids=unread[:12],
                reusable_candidate_ids=cached[:12], executable=bool(readable or search_available),
                blocked_by=(None if readable or search_available else 'body_url_budget' if not remaining['body_urls']
                            else 'search_route_or_budget'),
                question=('核对当前公司 '+scope+' 的主体及新增事实；同业材料不是公司直接消息。' if scope else QUESTIONS[lane])))
        elif lane in {'a_market', 'hk_market', 'us_market'} and all(bodies[i]['characters'] < 160 for i in ids):
            tasks.append(dict(task_id=key+':explain_drivers', kind='search_drivers', lane=lane, scope=scope,
                evidence_ids=ids, candidate_ids=unread[:12], reusable_candidate_ids=cached[:12],
                executable=bool(readable or search_available),
                question=QUESTIONS[lane]))
        return row

    for task in state.get('event_followup_tasks', []):
        task=dict(task)
        local_available=any(bodies.get(i,{}).get('unread_ranges') for i in task.get('evidence_ids',[]))
        task['executable']=bool(search_available or local_available and remaining['local_characters'])
        tasks.append(task)
    for lane in LANES:
        lanes.append(target('lane:'+lane, lane))
    for stock in stocks:
        scope = stock['market']+':'+stock['code']
        row = target('stock:'+scope, 'company_event', scope)
        row['key'] = scope
        watchlist.append(row)
    duplicates = {}
    for identifier, row in bodies.items():
        duplicates.setdefault(row['text_sha256'], []).append(identifier)
    return dict(owner='finance-discovery-feedback-v1', bodies=bodies, lanes=lanes,
        watchlist=watchlist, tasks=tasks, remaining=remaining, candidate_reads=outcomes,
        duplicate_body_groups=[ids for ids in duplicates.values() if len(ids) > 1],
        limitation='只证实实际工具关联、已提供区间与机械准入；不同域名不是独立核实，范围标签不是主体确认或充分性判断。')


def assess_finish(dossier, feedback, *, last_turn=False):
    """Reject unsupported claims; feed actionable omissions into the next turn."""
    problems = []
    selected = cited_ids(dossier)
    for identifier in selected:
        if not feedback['bodies'].get(identifier, {}).get('eligible'):
            problems.append(dict(code='cited_body_not_eligible', id=identifier))
    for key, ledger, field in [('coverage', feedback['lanes'], 'lane'),
                               ('watchlist_checks', feedback['watchlist'], 'key')]:
        actual = {row[field]: row for row in ledger}
        for row in dossier[key]:
            record = actual[row[field]]
            if row['status'] == 'body_provided' and not set(row['evidence_ids']) <= set(record['body_ids']):
                problems.append(dict(code='body_not_read_for_claimed_scope', scope=row[field]))
            if row['status'] == 'searched' and not record['successful_search']:
                problems.append(dict(code='successful_search_receipt_missing', scope=row[field]))
    known = {task['task_id'] for task in feedback['tasks']}
    deferred = dossier.get('deferred_tasks', [])
    if (not isinstance(deferred, list) or any(not isinstance(row, dict)
            or row.get('task_id') not in known or not isinstance(row.get('reason'), str)
            or not row['reason'].strip() for row in deferred)):
        problems.append(dict(code='deferred_tasks_invalid'))
        deferred = []
    deferred_ids = {row['task_id'] for row in deferred}
    pending = [task['task_id'] for task in feedback['tasks'] if task['executable']
               and task['task_id'] not in deferred_ids
               and (task['kind'] != 'read_remaining' or set(task['evidence_ids']) & set(selected))]
    return dict(accepted=not problems and (not pending or last_turn), problems=problems,
        actionable_unresolved_tasks=pending, deferred_tasks=deferred,
        stopped_at_model_limit=bool(last_turn and pending), selected_ids=selected,
        instruction='依据实际缺口继续选择工具；可显式说明暂不补查的编辑理由。不得自行增加模型轮次或越过硬上限、重试失败URL或把缺口改写成无消息。')
