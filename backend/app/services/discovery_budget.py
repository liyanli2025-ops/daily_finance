"""Local acquisition planning; no model, network, billing or settings mutation."""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Limits:
    # Explicit callers retain a fixed envelope; defaults use plan_budget.
    model_calls: int | None = 6
    search_calls: int = 4
    body_urls: int = 12
    input_characters: int = 48000
    output_tokens: int = 3000
    seconds: int = 240
    local_read_characters: int = 12000
    tool_requests_per_turn: int = 6

    def __post_init__(self):
        if self.model_calls is not None and (type(self.model_calls) is not int or not 1 <= self.model_calls <= 128):
            raise ValueError('discovery_limit_invalid:model_calls')
        for key, maximum in [('search_calls', 48), ('body_urls', 128),
                ('input_characters', 300000), ('output_tokens', 6000), ('seconds', 1800),
                ('tool_requests_per_turn', 12)]:
            value = getattr(self, key)
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError('discovery_limit_invalid:'+key)
        if type(self.local_read_characters) is not int or not 0 <= self.local_read_characters <= 240000:
            raise ValueError('discovery_limit_invalid:local_read_characters')


def plan_budget(stock_count, lane_count, settings):
    if type(stock_count) is not int or stock_count < 0 or type(lane_count) is not int or lane_count < 1:
        raise ValueError('discovery_budget_task_size_invalid')
    units = lane_count+stock_count
    common = dict(model_calls=settings.research_max_model_calls, output_tokens=min(6000, max(3000, units*300)),
                  tool_requests_per_turn=min(12, max(6, units)))
    ceiling = Limits(**common, search_calls=settings.research_web_search_max_requests,
        body_urls=settings.research_body_max_urls, input_characters=settings.research_input_max_characters,
        local_read_characters=settings.research_local_read_max_characters, seconds=settings.research_max_seconds)
    initial = replace(ceiling, search_calls=min(ceiling.search_calls, max(8, units)),
        body_urls=min(ceiling.body_urls, max(16, units*2)),
        local_read_characters=min(ceiling.local_read_characters, max(24000, units*4000)),
        input_characters=min(ceiling.input_characters, max(80000, units*8000+20000)),
        seconds=min(ceiling.seconds, max(360, units*30)))
    return initial, ceiling, dict(mode='progress_driven_collection', lane_count=lane_count,
        watchlist_count=stock_count, task_units=units, report_model_calls_independent=settings.model_max_calls_per_report,
        total_input_characters=settings.research_total_input_characters,
        total_reserved_output_tokens=settings.research_total_output_tokens,
        model_request_cap=initial.model_calls,
        initial=initial.__dict__, ceiling=ceiling.__dict__,
        billing_note='请求次数和字符是用量边界，不是金额上限；上下文变长可增加token费用。')


def evidence_progress(state):
    """Failed/empty calls and repeated URLs cannot unlock successive batches."""
    feedback = state.get('collection_feedback', {})
    return [sorted({row['url'] for row in state.get('candidates', {}).values()}),
        sorted((key, row['ranges']) for key, row in feedback.get('bodies', {}).items() if row['eligible'])]


def addresses_task(request, task):
    if task['kind']=='read_remaining':
        return request.get('tool')=='read_more' and request.get('id') in task['evidence_ids']
    if request.get('tool')=='read':return request.get('candidate_id') in task.get('candidate_ids',[])
    if request.get('tool')=='search':
        return request.get('scope')==task['scope'] if task.get('scope') else request.get('lane')==task.get('lane')
    return False


def matching_proposal(state, requests, limits):
    """A local capacity proposal for actual model-selected tools, no new tools."""
    needs=set()
    for tool,used,cap in [('search',state.get('search_tool_calls',0),state['effective_search_limit']),
                         ('read',state.get('body_url_calls',0),limits.body_urls),
                         ('read_more',state.get('local_read_characters',0),limits.local_read_characters)]:
        amount=sum((r.get('characters',0) if tool=='read_more' else 1) for r in requests if r.get('tool')==tool)
        if amount and (used>=cap*.75 or used+amount>cap):needs.add(tool)
    ids=[t['task_id'] for t in state['collection_feedback']['tasks']
         if any(request.get('tool') in needs and addresses_task(request,t) for request in requests)]
    if not ids:return None
    return dict(task_ids=list(dict.fromkeys(ids))[:12],reason='已选择解决实际缺口的工具，按真实进展核对同一期资源扩展')


def resource_review(limits, ceiling, state, *, elapsed, total_input, total_output, shared_search_limit=None):
    """Measured resources, not a monetary allowance or a coverage certificate."""
    def room(cap,key,used):return max(0,getattr(cap,key)-state.get(used,0))
    current=dict(searches=max(0,state['effective_search_limit']-state.get('search_tool_calls',0)),
        body_urls=room(limits,'body_urls','body_url_calls'),
        local_characters=room(limits,'local_read_characters','local_read_characters'))
    maximum=ceiling or limits
    progress=evidence_progress(state)
    can_expand=bool(ceiling is not None and any(progress)
        and progress!=state.get('last_budget_expansion_progress') and state.get('no_progress_turns',0)<2)
    next_input=max(12000,state.get('request_context',{}).get('request_characters',12000))
    turn_room=(limits.model_calls is None or state.get('model_calls',0)<limits.model_calls)
    turn_room=bool(turn_room and total_input-state.get('model_input_characters',0)>=next_input
        and total_output-state.get('reserved_output_tokens',0)>=limits.output_tokens and elapsed<limits.seconds)
    hard=dict(searches=room(maximum,'search_calls','search_tool_calls'),
        body_urls=room(maximum,'body_urls','body_url_calls'),
        local_characters=room(maximum,'local_read_characters','local_read_characters'))
    if shared_search_limit is not None:
        hard['searches']=min(hard['searches'],max(0,shared_search_limit-state.get('search_tool_calls',0)))
    return dict(owner='finance-measured-resource-review-v1',current=current,hard_remaining=hard,
        next_turn_resources_available=turn_room,extension_progress_available=can_expand,
        search_route_available=not state.get('search_route_failed',False),
        remaining_seconds=max(0,limits.seconds-elapsed),
        remaining_input_characters=max(0,total_input-state.get('model_input_characters',0)),
        remaining_reserved_output_tokens=max(0,total_output-state.get('reserved_output_tokens',0)),
        limitation='当前资源和扩展空间不是金额、新闻价值或完成度判定；工具仍由模型选择，失败台账和总上限不变。')


def task_has_capacity(task, review):
    if not review or not review['next_turn_resources_available']:return False
    remaining=review['current'];maximum=review['hard_remaining']
    def available(key):return remaining[key]>0 or review['extension_progress_available'] and maximum[key]>0
    if task['kind']=='read_remaining':return available('local_characters')
    if task.get('reusable_candidate_ids') and available('local_characters'):return True
    if task.get('candidate_ids') and available('body_urls'):return True
    return bool(review['search_route_available'] and available('searches') and available('body_urls'))


def expand_budget(limits, ceiling, state, proposal, *, requests, elapsed, input_characters):
    """Validate an in-reply editorial choice against actual open tasks.

    A larger local envelope performs no tool/model request. Model call limits,
    output size and the independent report budget never expand here.
    """
    if (not isinstance(proposal, dict) or not isinstance(proposal.get('reason'), str)
            or not 1 <= len(proposal['reason'].strip()) <= 1000
            or not isinstance(proposal.get('task_ids'), list) or not 1 <= len(proposal['task_ids']) <= 12
            or any(not isinstance(key, str) for key in proposal['task_ids'])):
        raise ValueError('discovery_budget_extension_invalid')
    tasks = {task['task_id']: task for task in state['collection_feedback']['tasks']}
    if any(key not in tasks for key in proposal['task_ids']):
        raise ValueError('discovery_budget_extension_unknown_task')
    record = dict(task_ids=list(dict.fromkeys(proposal['task_ids'])), reason=proposal['reason'].strip(),
                  before=limits.__dict__, model_calls=state['model_calls'])
    def denied(reason):
        return limits, dict(record, status='declined', decision_reason=reason)
    if ceiling is None:
        return denied('explicit_fixed_limits')
    if limits.model_calls is not None and state['model_calls'] >= limits.model_calls:
        return denied('final_model_turn_reserved_for_finish')
    if elapsed >= limits.seconds or elapsed >= ceiling.seconds:
        return denied('deadline_already_reached')
    progress = evidence_progress(state)
    if (not any(progress) or progress == state.get('last_budget_expansion_progress')
            or state.get('no_progress_turns', 0) >= 2):
        return denied('no_new_candidates_or_body_ranges')
    selected = [tasks[key] for key in record['task_ids']]
    if any(not any(addresses_task(request, task) for request in requests) for task in selected):
        return denied('selected_gap_has_no_matching_tool_request')
    network = any(task['kind'] != 'read_remaining' for task in selected)
    local = any(task['kind'] == 'read_remaining' for task in selected)
    changes = {}
    def grow(key, used, step):
        current, maximum = getattr(limits, key), getattr(ceiling, key)
        demand=sum((r.get('characters',0) if key=='local_read_characters' else 1) for r in requests
            if r.get('tool')=={'body_urls':'read','search_calls':'search','local_read_characters':'read_more'}.get(key))
        if (used >= current*.75 or demand and used+demand>current) and current < maximum:
            changes[key] = min(maximum, current+step)
    if network:
        grow('body_urls', state['body_url_calls'], 8)
        if not state.get('search_route_failed') and state['body_url_calls'] < changes.get('body_urls',limits.body_urls):
            grow('search_calls', state['search_tool_calls'], 4)
    if local:
        grow('local_read_characters', state['local_read_characters'], 16000)
    grow('input_characters', input_characters, 32000)
    grow('seconds', elapsed, 120)
    # More source/body capacity needs room for packets in the same batch.
    if any(key in changes for key in ('body_urls','search_calls','local_read_characters')):
        if limits.input_characters < ceiling.input_characters:
            changes['input_characters']=min(ceiling.input_characters,limits.input_characters+32000)
    if any(key in changes for key in ('body_urls','search_calls')) and limits.seconds < ceiling.seconds:
        changes['seconds']=min(ceiling.seconds,limits.seconds+120)
    if not changes:
        return denied('no_near_limit_resource_can_expand')
    expanded = replace(limits, **changes)
    return expanded, dict(record, status='expanded', after=expanded.__dict__,
        changed_resources=sorted(changes), progress=progress,
        decision_reason='existing_gap_selected_and_resource_near_limit')
