"""Local next-action guidance and evidence-based finish-loop protection."""
import hashlib
import json

from .discovery_budget import evidence_progress
from .search_objectives import primary_candidate


def reject_finish(state):
    """Wording, task reordering, deferrals and re-presentations aren't evidence.

    Two rejected finishes against the same acquired evidence stop the loop.
    A new candidate or new provided body range opens a new repair opportunity;
    this is a no-progress guard, not a cap on productive research requests.
    """
    signature=hashlib.sha256(json.dumps(evidence_progress(state),ensure_ascii=False,
        sort_keys=True,separators=(',',':')).encode()).hexdigest()
    previous=state.get('finish_loop_guard',{})
    count=previous.get('rejections',0)+1 if previous.get('evidence_sha256')==signature else 1
    guard=dict(owner='finance-finish-progress-v1',evidence_sha256=signature,
        rejections=count,stop=count>=2,counts_draft_changes_as_progress=False)
    state['finish_loop_guard']=guard
    return guard


def action_plan(state,feedback,*,max_characters=6000):
    """Offer inspected candidates, never auto-select a source or execute tools."""
    tasks=[]
    order={'read_remaining':0,'read_candidate':1,'search_alternative':1,'search_drivers':1,'event_research':2}
    for task in sorted(feedback['tasks'],key=lambda row:order.get(row['kind'],2)):
        if not task.get('executable'):continue
        row={key:task[key] for key in ('task_id','kind','lane','scope','question') if key in task}
        if task.get('next_request'):
            row['local_request']=task['next_request']
        options=[]
        for identifier in task.get('candidate_ids',[])[:3]:
            candidate=state['candidates'][identifier]
            relation='direct' if task.get('scope') else 'industry' if task.get('lane')=='industry' else 'market'
            purpose=('company_event' if relation=='direct' else 'released_policy'
                if task.get('lane')=='global_policy' else 'latest_close'
                if task.get('lane') in {'a_market','hk_market','us_market','commodities'} else 'discovery')
            request=dict(tool='read',candidate_id=identifier,relation=relation,purpose=purpose,
                reason='根据标题与摘要判断是否能解决本任务；保留来源与口径限制')
            if task.get('scope'):request['scope']=task['scope']
            options.append(dict(candidate_id=identifier,title=candidate.get('title',''),
                url=candidate['url'],snippet=candidate.get('snippet',''),request_if_selected=request,
                use_assessment=primary_candidate(candidate,task.get('lane')),
                reused_without_http=identifier in task.get('reusable_candidate_ids',[])))
        if options:row['candidate_options']=options
        remaining=feedback.get('remaining',{})
        measured=feedback.get('resource_review',{})
        extended=measured.get('hard_remaining',{}) if measured.get('extension_progress_available') else {}
        search_available=bool((remaining.get('searches') or extended.get('searches'))
            and (remaining.get('body_urls') or extended.get('body_urls')) and not state.get('search_route_failed'))
        if task.get('lane') and search_available:
            row['search_option']=dict(tool='search',lane=task['lane'],scope=task.get('scope'),
                query_required='由你根据问题编写适合来源语言的查询；不要重复已失败路径',
                purpose=('released_policy' if task['lane']=='global_policy' else 'company_event'
                    if task.get('scope') else 'latest_close'
                    if task['lane'] in {'a_market','hk_market','us_market','commodities'} else 'discovery'))
        tasks.append(row)
    plan=dict(owner='finance-research-actions-v1',required_action='tools_or_explicitly_justified_deferral',
        tasks=[],remaining_task_count=len(tasks),
        all_executable_task_ids=[task['task_id'] for task in feedback['tasks'] if task.get('executable')],
        instruction='上次finish未被接受。优先选择有价值的缺口并返回action=tools；候选选项仅供你判断，'
            '不得机械读取首条。若决定暂不补查，finish须逐项deferred_tasks说明理由，'
            '并按实际账本保留searched/missing，不能继续用评论/晨报声称原披露/结算已齐。'
            '改写成稿不会增加资料；连续两次无新增候选或正文区间的无效finish会停止。',
        tool_execution_performed=False,coverage_certified=False,
        limitation='候选菜单限长，仅省略完整条目；全部任务和候选保留在原反馈与分页目录。')
    def size():return len(json.dumps(json.dumps(plan,ensure_ascii=False),ensure_ascii=False))
    for row in tasks:
        if len(plan['tasks'])>=6:break
        plan['tasks'].append(row);plan['remaining_task_count']=len(tasks)-len(plan['tasks'])
        while size()>max_characters and row.get('candidate_options'):
            row['candidate_options'].pop()
        if size()>max_characters:
            plan['tasks'].pop();plan['remaining_task_count']=len(tasks)-len(plan['tasks'])
    return plan
