"""Inspectable acquisition review. Mechanical checks never certify news truth."""
from .search_primary_collection import LANES

FACETS = {
    'primary_facts': '核对原始事实、说法归属、发布时点与新增内容',
    'background': '补查理解本事件所需的背景和对比口径',
    'disagreements': '核对回应、不同解释、反证或尚未确认的部分',
    'transmission': '检查影响对象、传导依据及适用边界，不硬套公司受益',
}
CONTRACT = 'separate_collection_report_v1'


def review_events(dossier, feedback):
    problems, tasks = [], []
    stocks = {row['key'] for row in feedback['watchlist']}
    for index, event in enumerate(dossier['events']):
        checks = event.get('research_checks')
        if event.get('lane') not in LANES:
            problems.append(dict(code='event_lane_invalid', event=index, field='lane',
                received=event.get('lane'), allowed=list(LANES)))
        if event.get('scope') is not None and event['scope'] not in stocks:
            problems.append(dict(code='event_scope_invalid', event=index, field='scope',allowed=sorted(stocks)))
        if not isinstance(checks, dict) or set(checks) != set(FACETS):
            problems.append(dict(code='event_research_checks_missing', event=index, field='research_checks',
                required=list(FACETS)))
            continue
        for facet, question in FACETS.items():
            check = checks[facet]
            if (not isinstance(check, dict) or check.get('status') not in {'supported','unresolved','not_applicable'}
                    or not isinstance(check.get('explanation'), str) or not check['explanation'].strip()
                    or not isinstance(check.get('evidence_ids'), list)
                    or any(not isinstance(i,str) or i not in event['evidence_ids'] for i in check['evidence_ids'])
                    or check['status'] == 'supported' and not check['evidence_ids']
                    or facet == 'primary_facts' and check['status'] == 'not_applicable'):
                problems.append(dict(code='event_research_check_invalid', event=index, facet=facet))
                continue
            if check['status'] == 'unresolved' and event.get('lane') in LANES:
                tasks.append(dict(task_id='event:'+str(index)+':'+facet, kind='event_research',
                    lane=event['lane'], scope=event.get('scope'), candidate_ids=[],
                    evidence_ids=event['evidence_ids'], event_title=event['title'],
                    question=question+'；当前缺口：'+check['explanation']))
    return dict(problems=problems, tasks=tasks)


def completion_review(state):
    """Keep stopped/partial collections explicit even without a valid finish."""
    dossier = state.get('dossier')
    feedback = state.get('collection_feedback', {})
    selected = set(state.get('selected_ids', []))
    ledger_valid=bool({row['lane'] for row in feedback.get('lanes',[])}==set(LANES)
        and {row['key'] for row in feedback.get('watchlist',[])}==
            {row['market']+':'+row['code'] for row in state.get('watchlist',[])})
    gaps = [dict(key=row['key'], searched=row['successful_search'], body_ids=row['body_ids'])
            for row in feedback.get('lanes', [])+feedback.get('watchlist', [])
            if not set(row['body_ids']) & selected]
    tasks = [task for task in feedback.get('tasks', [])
             if task['kind'] != 'read_remaining' or selected & set(task['evidence_ids'])]
    deferred = dossier.get('deferred_tasks', []) if dossier else []
    event_review=review_events(dossier,feedback) if dossier and ledger_valid else dict(problems=[],tasks=[])
    problems=event_review['problems'] or state.get('event_review_problems',[])
    tasks=[task for task in tasks if task['kind']!='event_research']+event_review['tasks']
    ready = bool(dossier and selected and ledger_valid and not gaps and not tasks and not deferred and not problems)
    return dict(owner='finance-collection-review-v1',
        status='ready_for_editorial_review' if ready else 'incomplete',
        valid_dossier_present=bool(dossier),scope_ledger_valid=ledger_valid, stop_status=state['status'],
        scope_gaps=gaps, unresolved_tasks=tasks, deferred_tasks=deferred,
        event_review_problems=problems,
        selected_ids=sorted(selected), model_calls=state['model_calls'],
        model_input_characters=state.get('model_input_characters',0),
        reserved_output_tokens=state.get('reserved_output_tokens',0),
        search_attempts=state['search_tool_calls'], url_read_attempts=state['body_url_calls'],
        quality_acceptance='pending_human_review',
        limitation='有正文和模型给出的研究检查不代表全网无遗漏或事实已核实；deferred仍计入未完成。')
