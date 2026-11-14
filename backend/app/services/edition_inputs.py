"""Shared request assembly and explicit forecasts from the material already held."""
from copy import deepcopy
from . import edition_contract as contract
from .edition_context import source_packet
from .edition_budget import OUTPUTS


RESEARCH_BRIEF = """为A/H股日内至数日投资者建立当期资料底稿，研究范围不受自选股或节目长度限制。
全市场检查A股、港股、美股及重要外盘、宏观政策、行业经营、重大公司风险、自选股和价格结构；重大政治经济、突发及跨市场事件单独保留。热度、篇数和搜索排序不代表重要性，重大外盘即使与A/H关联待核仍可独立成项。
围绕新增变化、旧背景、受影响对象、经营/估值/利率/汇率/风险偏好传导、竞争解释、价格反证及后续验证判断价值。区分事实、机制与有期限的假设，不编资金意图、预期差或“未定价”；收入同比增长不代替盈利质量、现金流与基数分析。
标题和摘要仅作线索，未读不能当事实；正文存在不代表真实、完整或独立核验。按主体、事件、期间、指标和原始来源判断证据用途，同公司或同题不代表同一事实，同源转载不当独立佐证。
对齐来源时区、交易日期、盘前盘中收盘盘后与截止时点，核最近已完成交易时段；政策区分拟议/通过/生效/执行，旧财报不当新催化，预测、评论、晨报不当原披露或收盘。
保留更新、公司回应、独立调查、有力反方和正文深处的关键细节。具体未确认说法可作为待核线索，标明说话人、原始出处、时间、上下文、依据和回应；匿名身份不升级为已核身份，热度或多次复述不等于证实，广告和无增量刷屏不当证据。
已有同页复用；补查说明原始依据、缺口及新增价值。工具失败、未搜、未读和缺重要证据如实区分，不解释成没有新闻；自选股不是持仓，缺关联不硬编。研究保留重要事实、不同解释和遗漏；节目取舍不抹掉底稿。
本阶段只按末尾JSON协议完成任务；程序执行搜索和阅读，不输出旧工具名称、循环指令或完整报告。"""


def messages_for(stage, prompt, value, now, report_type):
    import json
    from .editorial_policy import REPORT_POLICY, REVIEW_POLICY, SPOKEN_POLICY, edition_brief, SPOKEN_EDITION_BRIEFS
    edition = '周末回顾' if now.weekday() >= 5 else ('晚报' if report_type == 'evening' else '早报')
    if stage == 'writing':
        brief = REPORT_POLICY + '\n' + edition_brief(edition) + '\n' + SPOKEN_POLICY + '\n' + SPOKEN_EDITION_BRIEFS[edition]
    elif stage == 'review':
        brief = REVIEW_POLICY
    else:
        brief = RESEARCH_BRIEF
    from .listener_research import requirements
    brief += requirements(stage, value)
    if 'candidate_columns' in value:
        brief += '\n输入候选表按candidate_columns列顺序读取；attributes中单独的{"$ref":n}引用candidate_shared[n]，可嵌套。标题/链接/摘要/时点按原列解释，不能遗漏候选。'
    return [dict(role='system', content=contract.SYSTEM + '\n' + brief + '\n' + prompt),
            dict(role='user', content=json.dumps(value, ensure_ascii=False, separators=(',', ':')))]


def editorial_forecast(state, now):
    from .spoken_fidelity import CONTRACT
    value = {k: deepcopy(state.get(k)) for k in
             ('cutoff', 'watchlist', 'report_type', 'agenda', 'missing', 'prior_report')}
    from .listener_research import brief
    value.update(brief(state))
    assessment = state.get('assessment') or {}
    value['assessment'] = {k: deepcopy(assessment[k]) for k in
        ('events', 'watchlist_checks', 'missed_major_events', 'change_checks', 'change_topic_checks', 'expectation_checks') if k in assessment}
    # Forecast all known bodies, including contrary/unselected bodies, without
    # inventing ready evidence. This is only planning, never a research verdict.
    from .edition_context import editorial_source_packet
    value['sources'] = {sid: editorial_source_packet(s, state) for sid, s in state.get('sources', {}).items()}
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
