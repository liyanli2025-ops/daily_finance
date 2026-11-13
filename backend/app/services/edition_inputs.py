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
