"""Shared request assembly and explicit forecasts from the material already held."""
from copy import deepcopy
from . import edition_contract as contract
from .edition_context import source_packet
from .edition_budget import OUTPUTS


def messages_for(stage, prompt, value, now, report_type):
    import json
    from .editorial_policy import REPORT_POLICY, REVIEW_POLICY, SPOKEN_POLICY, edition_brief, SPOKEN_EDITION_BRIEFS
    edition = '周末回顾' if now.weekday() >= 5 else ('晚报' if report_type == 'evening' else '早报')
    if stage == 'writing':
        brief = REPORT_POLICY + '\n' + edition_brief(edition) + '\n' + SPOKEN_POLICY + '\n' + SPOKEN_EDITION_BRIEFS[edition]
    elif stage == 'review':
        brief = REVIEW_POLICY
    else:
        from .research_desk import INSTRUCTIONS
        marker = '每轮回复用一个JSON对象'
        if marker not in INSTRUCTIONS:
            raise RuntimeError('edition_shared_research_brief_changed')
        brief = INSTRUCTIONS.split(marker, 1)[0]
    if 'candidate_columns' in value:
        brief += '\n输入候选表按candidate_columns列顺序读取；attributes中单独的{"$ref":n}引用candidate_shared[n]，可嵌套。标题/链接/摘要/时点按原列解释，不能遗漏候选。'
    return [dict(role='system', content=contract.SYSTEM + '\n' + brief + '\n' + prompt),
            dict(role='user', content=json.dumps(value, ensure_ascii=False, separators=(',', ':')))]


def editorial_forecast(state, now):
    from .spoken_fidelity import CONTRACT
    value = {k: deepcopy(state.get(k)) for k in
             ('cutoff', 'watchlist', 'report_type', 'agenda', 'missing', 'prior_report')}
    assessment = state.get('assessment') or {}
    value['assessment'] = {k: deepcopy(assessment[k]) for k in
        ('events', 'watchlist_checks', 'missed_major_events') if k in assessment}
    # Forecast all known bodies, including contrary/unselected bodies, without
    # inventing ready evidence. This is only planning, never a research verdict.
    value['sources'] = {sid: source_packet(s) for sid, s in state.get('sources', {}).items()}
    result = []
    for stage, prompt in [('writing', contract.WRITE), ('review', contract.REVIEW + CONTRACT)]:
        payload = deepcopy(value)
        allowance = 0
        if stage == 'review':
            if state.get('draft') is not None:
                payload['draft'] = deepcopy(state['draft'])
            else:
                payload['draft_pending'] = True
                # Explicit forecast for the not-yet-generated draft. Not a
                # tokenizer or a promise about unknown future response size.
                allowance = OUTPUTS['writing'] * 4
        messages = messages_for(stage, prompt, payload, now, state['report_type'])
        result.append(dict(stage=stage,
            known_input_bytes=sum(len(m['content'].encode()) for m in messages),
            future_draft_allowance_bytes=allowance, output_tokens=OUTPUTS[stage],
            source_ids=sorted(value['sources']),
            basis='已保存资料及完整系统提示词；待生成稿按写稿输出额度每token四字节另作预留。'))
    return result


def edition_forecast(state, now):
    """All four normal stages; future response context has explicit token units.

    New search result/body sizes are unknown, so the plan is recomputed as they
    arrive. It never certifies sufficient money for an unknown future episode.
    """
    from .edition_context import packet
    result = editorial_forecast(state, now)
    assessment = state.get('assessment') or {}
    patch_pending = any(assessment.get(k) for k in
        ('additional_searches', 'additional_reads', 'missed_major_events')) and not any(
            r.get('stage') == 'patch_assessment' for r in state.get('reservations', []))
    for row in result:
        future = {}
        if state.get('agenda') is None:
            future['agenda'] = OUTPUTS['agenda']
        if state.get('assessment') is None:
            future['assessment'] = OUTPUTS['assessment']
        if patch_pending:
            future['patch_assessment'] = OUTPUTS['patch_assessment']
        if row['stage'] == 'review' and state.get('draft') is None:
            future['writing'] = OUTPUTS['writing']
        row.update(future_draft_allowance_bytes=0,
            future_input_tokens=(sum(future.values()) * 5 + 3) // 4,
            future_context_output_allowances=future,
            basis='已知系统/正文按UTF8字节保守规划；未来JSON结果按输出token额度加25%输入余量，非精确token计数。')
    stages = [('agenda', contract.AGENDA), ('assessment', contract.ASSESS)]
    if patch_pending:
        stages.append(('patch_assessment', contract.ASSESS))
    for stage, prompt in stages:
        messages = messages_for(stage, prompt, packet(state, stage), now, state['report_type'])
        future = {'agenda': OUTPUTS['agenda']} if stage == 'assessment' and state.get('agenda') is None else {}
        result.append(dict(stage=stage,
            known_input_bytes=sum(len(m['content'].encode()) for m in messages),
            future_draft_allowance_bytes=0, future_input_tokens=(sum(future.values()) * 5 + 3) // 4,
            future_context_output_allowances=future, output_tokens=OUTPUTS[stage],
            source_ids=[] if stage == 'agenda' else sorted(state.get('sources', {})),
            basis='当前实际请求提示词与资料；未来目录/正文未计入，取得后再次核算。'))
    return result
