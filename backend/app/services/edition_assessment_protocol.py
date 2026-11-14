"""One assessment output specification and conservative incomplete-reply handling.

Local placeholders only say missing. They are never model conclusions, a repair
of facts, an authorization to fetch, or permission to spend another model call.
"""
from copy import deepcopy
import json

OWNER='finance-assessment-contract-v1'
PURPOSES=('discovery','latest_close','released_policy','company_event','commentary')
INCREMENTS=('original_source','new_update','independent_verification','counterevidence','missing_context','access_failure')
CORE=('events','missed_major_events','additional_searches','additional_reads','watchlist_checks')


def records(value,name):
    rows=value.get(name,[])
    columns=value.get('record_columns',{}).get(name)
    if columns:
        return [dict(zip(columns[:-1],r[:-1]),**r[-1]) for r in rows]
    return rows


def specification(value):
    fields=list(CORE)
    changes=value.get('change_protocol')=='daily_changes_v1'
    if changes:fields.append('change_checks')
    pending=value.get('change_topic_pending',[]) if changes else []
    if pending:fields.append('change_topic_checks')
    stocks=[r['market']+':'+r['code'] for r in value.get('watchlist',[])]
    return dict(owner=OWNER,required_arrays=fields,
        required_event_ids=[r['id'] for r in (value.get('agenda') or {}).get('events',[])],
        required_watchlist_keys=stocks,
        required_change_task_ids=[r['id'] for r in records(value,'change_coverage')] if changes else [],
        required_topic_keys=[dict(candidate_id=r['candidate_id'],topic=r['topic']) for r in pending],
        search_purpose_values=list(PURPOSES),increment_values=list(INCREMENTS))


def instruction(stage,value):
    if stage not in {'assessment','patch_assessment'}:return ''
    spec=specification(value)
    example=dict(events=[dict(id='已有事件ID',status='ready|missing|excluded',reason='根据实际证据填写',
        evidence=[dict(source_id='已送达来源ID',quote='逐字依据')])],
        missed_major_events=[],additional_searches=[dict(event_id='已有事件ID',query='具体查询',
            purpose='discovery',increment='original_source',reason='具体补查问题，至少12字')],
        additional_reads=[dict(event_id='已有事件ID',candidate_id='现有候选ID',increment='missing_context',
            reason='具体缺失事实或背景，至少12字')],
        watchlist_checks=[dict(key='当前自选股key',status='covered|missing|no_material_event',
            reason='实际有限检查结论',evidence=[])],expectation_checks=[])
    if 'change_checks' in spec['required_arrays']:
        example['change_checks']=[dict(task_id='清单中的每个task_id',status='supported|screened_no_material_event|missing',
            reason='实际证据和核查边界，至少8字',evidence=[])]
    if 'change_topic_checks' in spec['required_arrays']:
        example['change_topic_checks']=[dict(candidate_id='待核候选ID',topic='待核议题',
            status='assigned|excluded|missing',event_id='assigned时的已有事件ID',reason='明确该议题的取舍，12至400字')]
    return ('\n【本阶段完整输出协议】仅返回一个JSON对象，全部必填数组必须同时存在；无补查、无预期差时相应数组为[]。'
        '模板中的竖线表示允许选一个值，不得原样输出。各逐项核对数组必须覆盖下面清单，不能仅返回events和watchlist_checks。'
        'purpose只能使用固定英文枚举；中文目的写在reason。字段存在不代表证据成立；缺证据写missing，不编造核对结论。\n'
        +json.dumps(spec,ensure_ascii=False,separators=(',',':'))+'\n完整对象形状：'
        +json.dumps(example,ensure_ascii=False,separators=(',',':')))


def prepare(state,value,events=None,stocks=None):
    """Keep valid rows, record EVERY shape/enum issue, fill only explicit gaps."""
    from .daily_changes import brief
    packet=dict(brief(state),agenda=state.get('agenda'),watchlist=state.get('watchlist',[]))
    spec=specification(packet)
    if events is not None:spec['required_event_ids']=list(events)
    if stocks is not None:spec['required_watchlist_keys']=sorted(stocks)
    result=deepcopy(value);issues=[]
    if not isinstance(result,dict):
        result={};issues.append(dict(code='reply_not_object',path='$'))
    def issue(code,path):issues.append(dict(code=code,path=path))
    for name in spec['required_arrays']:
        if not isinstance(result.get(name),list):
            issue('required_array_missing_or_invalid',name);result[name]=[]
    if 'expectation_checks' in result and not isinstance(result['expectation_checks'],list):
        issue('optional_array_invalid','expectation_checks');result['expectation_checks']=[]
    def complete_rows(name,key,expected,allowed):
        rows=result[name];out=[]
        for i,row in enumerate(rows):
            if not isinstance(row,dict) or row.get(key) not in expected:
                issue('unknown_or_invalid_row',name+'['+str(i)+']')
        for identifier in expected:
            matches=[r for r in rows if isinstance(r,dict) and r.get(key)==identifier]
            valid=(len(matches)==1 and isinstance(matches[0].get('status'),str) and matches[0]['status'] in allowed
                and isinstance(matches[0].get('reason'),str) and bool(matches[0]['reason'].strip()))
            if not valid:
                issue('required_row_missing_duplicate_or_invalid',name+':'+identifier)
                out.append({key:identifier,'status':'missing',
                    'reason':'模型未完整交付本项核对，程序仅保留未完成标记，不作已检查或无事件结论。',
                    'evidence':[],'origin':'local_missing_marker_not_model_conclusion'})
            else:
                row=matches[0]
                evidence=row.get('evidence')
                if row['status'] in ('ready','covered','supported') and (not isinstance(evidence,list) or any(
                        not isinstance(e,dict) or not isinstance(e.get('source_id'),str)
                        or not isinstance(e.get('quote'),str) for e in evidence)):
                    issue('evidence_shape_invalid',name+':'+identifier)
                    row.update(status='missing',evidence=[],origin='local_missing_marker_not_model_conclusion')
                out.append(row)
        result[name]=out
    complete_rows('events','id',spec['required_event_ids'],{'ready','missing','excluded'})
    complete_rows('watchlist_checks','key',spec['required_watchlist_keys'],{'covered','missing','no_material_event'})
    if 'change_checks' in spec['required_arrays']:
        complete_rows('change_checks','task_id',spec['required_change_task_ids'],{'supported','screened_no_material_event','missing'})
    if 'change_topic_checks' in spec['required_arrays']:
        rows=result['change_topic_checks'];out=[]
        expected={(r['candidate_id'],r['topic']) for r in spec['required_topic_keys']}
        for row in rows:
            if not isinstance(row,dict) or not any(row.get('candidate_id')==a and row.get('topic')==b for a,b in expected):
                issue('unknown_or_invalid_row','change_topic_checks')
        for task in spec['required_topic_keys']:
            matches=[r for r in rows if isinstance(r,dict) and all(r.get(k)==v for k,v in task.items())]
            if len(matches)!=1 or matches[0].get('status') not in ('assigned','excluded','missing'):
                issue('required_topic_missing_duplicate_or_invalid','change_topic_checks:'+task['candidate_id']+':'+task['topic'])
                out.append(dict(task,status='missing',reason='模型未完整核对该'+task['topic']+'线索，保留具体证据缺口。',
                    origin='local_missing_marker_not_model_conclusion'))
            else:out.append(matches[0])
        result['change_topic_checks']=out
    from .edition_contract import event as check_event
    known_events=dict(events or {r['id']:r for r in (state.get('agenda') or {}).get('events',[])})
    extras=[]
    for index,row in enumerate(result['missed_major_events']):
        try:
            if not isinstance(row,dict) or not isinstance(row.get('id'),str):raise ValueError('edition_new_event_invalid')
            check_event(row,state.get('candidates',{}),set(spec['required_watchlist_keys']))
            if row['importance']!='major' or row['id'] in known_events:raise ValueError('edition_new_event_invalid')
            known_events[row['id']]=row;extras.append(row)
        except (ValueError,TypeError,KeyError,AttributeError):
            issue('new_major_event_invalid','missed_major_events['+str(index)+']')
    result['missed_major_events']=extras
    rejected=[]
    for name in ('additional_searches','additional_reads'):
        valid=[]
        for index,row in enumerate(result[name]):
            path=name+'['+str(index)+']'
            okay=(isinstance(row,dict) and isinstance(row.get('event_id'),str) and row['event_id'] in known_events
                and row.get('increment') in INCREMENTS and isinstance(row.get('reason'),str)
                and 12<=len(row['reason'].strip())<=400)
            if name=='additional_searches':
                okay=okay and isinstance(row.get('query'),str) and 2<=len(row['query'])<=120 and row.get('purpose') in PURPOSES
            else:
                okay=okay and isinstance(row.get('candidate_id'),str) and row['candidate_id'] in state.get('candidates',{})
            if not okay:
                issue('research_action_invalid',path);rejected.append(dict(path=path,received=deepcopy(row)))
            else:valid.append(row)
        result[name]=valid
    protocol=dict(owner=OWNER,complete=not issues,issues=issues,rejected_research_actions=rejected,
        specification=spec,model_repair_requests=0,
        limitation='本地补出的条目全部为未完成，不是模型核对结论；原回复另存。协议不完整禁止补查、写稿、审稿或TTS。')
    return result,protocol


def validate(state,value,stage,events=None,stocks=None):
    """Shared by live pipeline and free replay of already-paid replies."""
    from . import edition_contract as contract
    from .edition_budget import digest
    from .daily_changes import enabled,validate_checks,validate_topics,validate_expectations
    from .edition_issuer_desk import PROTOCOL
    received=deepcopy(value)
    assessment,protocol=prepare(state,value,events,stocks)
    events=events if events is not None else {r['id']:r for r in state['agenda']['events']}
    stocks=stocks if stocks is not None else {r['market']+':'+r['code'] for r in state.get('watchlist',[])}
    delivered=state.get('delivered_sources',{}).get(stage,{})
    provided={sid for sid,s in state['sources'].items() if delivered.get(sid)==digest(s['text'])}
    if state.get('research_protocol')==PROTOCOL:
        from .listener_research import restrict_baselines
        assessment=restrict_baselines(assessment,events,state['sources'])
    accepted,sources,validation=contract.prepare_assessment(assessment,events,state['sources'],stocks,provided,
        state.get('delivered_source_ranges',{}).get(stage))
    state['sources']=sources
    if enabled(state):
        try:
            change_missing=validate_checks(state,accepted,provided)
        except (ValueError,TypeError,KeyError) as error:
            protocol['issues'].append(dict(code=str(error),path='change_checks'))
            for row in accepted['change_checks']:
                row.update(status='missing',reason='本地证据校验未通过，保留未完成；原始模型判断另存。',evidence=[],
                    origin='local_missing_marker_not_model_conclusion')
            change_missing=validate_checks(state,accepted,provided)
        state['change_missing']=change_missing+validate_topics(state,accepted,events)
        try:validate_expectations(state,accepted,provided)
        except (ValueError,TypeError,KeyError) as error:
            protocol['issues'].append(dict(code=str(error),path='expectation_checks'))
            accepted['expectation_checks']=[]
            state['change_missing'].append('protocol:expectation_checks')
        validation['missing'].extend(state['change_missing'])
    protocol['complete']=not protocol['issues']
    if not protocol['complete']:validation['missing'].append('protocol:assessment_incomplete')
    state.update(assessment_received=received,assessment_protocol=protocol,assessment=accepted,
        missing=list(dict.fromkeys(validation['missing'])))
    validation['missing']=state['missing']
    return accepted,validation
