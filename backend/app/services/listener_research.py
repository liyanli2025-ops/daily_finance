"""Listener-facing research obligations, not a claim to certify investment truth."""
from copy import deepcopy

from .edition_issuer_desk import PROTOCOL
from .research_schema import research_fields

QUESTIONS = (
    '发生了什么新增变化？原始来源、公布日、统计期与最近完成交易时段分别是什么？',
    '与什么基线相比？收入、扣非利润、现金流、负债及业务经营指标能否相互印证？',
    '经过哪条经营或估值渠道影响谁？传导是事实、推断还是有期限的情景？',
    '另一种合理解释是什么？什么可观察变化会使本期判断失效？',
    '对当前自选股哪些相关、哪些不相关？接下来观察哪个指标、哪个时间窗口？',
)

WRITE_REQUIREMENTS = '''
本期启用listener_research_v1。先完成分析，再表达，不用播报涨跌代替解释。
新增listener_cards数组，每个core_opinions字符串对应一张卡：
{judgment:"与core_opinions逐字相同",source_id:"已读来源ID",fact_quote:"来源逐字原文2至400字",
report_quote:"本判断在body中的逐字句子2至400字",mechanism:"事实到公司经营或估值的传导，注明推断",
alternative:"另一种合理解释，缺证据只写假设",horizon:"判断适用期间",
invalidation:"未来哪个可观察指标或事件发生何种变化就需撤回判断；这一短句须逐字写入body和script"}。
卡片是研究底稿，关键条件须写入报告和口播，不能只放在卡片里。无法建立有依据的观点可不提该观点；不要为凑卡片编事实。
新增stock_followups数组，覆盖全部当前自选股：{key:"A:代码",status:"supported或insufficient",
reason:"本期能下什么结论、不能下什么结论",report_quote:"body中包含该公司名或代码的逐字句子2至400字",variables:["业务对应的待观察变量"],
next_check:"下一次应核对的披露/数据及其日期或已知未知边界",source_ids:["直接公司证据ID"]}。
insufficient允许source_ids为空，必须说明缺口；supported只能用scope或direct_scopes匹配的公司资料。
每只自选股在报告中用简短一段交代结论边界与下一观察项；口播优先有实质变化者，不机械念完清单。
公司业务归类只用来选问题，不能充今日消息；财务基线标明期间和供应商镜像属性，不能当今日催化或已核原报。
禁止以下跳步：利润增速高于收入就称盈利质量改善；回购计划完成比例就推导股价支撑；
解禁额度就当实际卖出；只有涨跌就认定空头回补、资金意图或市场已定价。分别补现金流/扣非与基数、
实际回购金额与股数/注销和流动性、真实减持披露、仓位或预期基线；缺资料明确无法判断。
同一数字先核单位、期间、分母及计算。自选股不是已知持仓，不猜仓位、成本、承受能力或保证收益。
口播围绕最重要变化讲清事实、机制、分歧和一个具体观察点；无新增公司证据时简短交代研究边界，不硬凑利好利空。
'''
REVIEW_REQUIREMENTS = '''
独立检查listener_cards和stock_followups，对照真实正文，不能因卡片填满就通过。
新增listener_checks数组，逐项提供{criterion,status:"supported或failed",report_quote,script_quote,reason}，
criterion必须覆盖evidence、causality、company_relevance、time_and_units、countercase_and_falsifier五项。
report_quote和script_quote分别逐字摘自文字及口播（2至400字）。
证据是否支持声称的强度、经营指标是否真的变化、现金流/利润是否混淆、回购/解禁是否被误当价格因果、
自选股是否被假当持仓、另一种解释和判断失效条件是否能听到，任一不合格则passed=false。
不要因模型填满表格、引用存在或节目听起来顺就判定事实正确。重要消息先核原始出处，不把转载数量当独立证实。
'''


def brief(state):
    if state.get('research_protocol') != PROTOCOL:
        return {}
    companies = []
    baselines = state.get('company_baselines', {})
    for stock in state.get('watchlist', []):
        key = stock['market'] + ':' + stock['code']
        record = baselines.get(key) or {}
        profile = record.get('profile') or {}
        fields = profile.get('fields') or research_fields('', '')['fields']
        companies.append(dict(key=key, name=stock['name'],
            business_profile_status='provider_classification' if profile else 'missing',
            industry=profile.get('industry'), research_variables=deepcopy(fields),
            source_url=profile.get('source_url'), observed_at=profile.get('collected_at'),
            gaps=deepcopy(record.get('gaps', [])),
            usage='研究问题，不是已验证事实；缺业务归类时使用通用问题，不猜行业。'))
    return dict(research_protocol=PROTOCOL, listener_questions=list(QUESTIONS), company_questions=companies,
        issuer_catalogue_checks=deepcopy(state.get('issuer_catalogue_checks', [])))


def requirements(stage, value):
    if value.get('research_protocol') != PROTOCOL:
        return ''
    if stage == 'writing':
        return WRITE_REQUIREMENTS
    if stage == 'review':
        return REVIEW_REQUIREMENTS
    return ('\n按listener_questions检查价值和缺口；company_questions仅给研究方向，不是事实。'
            '财务基线是背景，不因过往报告日期旧而当今日催化，也不把它当最新公司消息的替代。'
            '公司披露目录只含最近20条，空目录不能声称无重大事件；披露镜像不冒充交易所原件。')


def _text(value):
    return isinstance(value, str) and 2 <= len(value.strip()) <= 800


def _quote(value, text):
    return isinstance(value, str) and 2 <= len(value) <= 400 and value in text


def validate_draft(state, written, sources):
    if state.get('research_protocol') != PROTOCOL:
        return
    opinions = written.get('core_opinions', [])
    cards = written.get('listener_cards')
    if (not isinstance(cards, list) or not cards or len(cards) != len(opinions)
            or any(not isinstance(c, dict) for c in cards)
            or [c.get('judgment') for c in cards] != opinions):
        raise ValueError('edition_listener_judgments_missing')
    for card in cards:
        source = sources.get(card.get('source_id'))
        if (not source or not _quote(card.get('fact_quote'), source['text'])
                or not _quote(card.get('report_quote'), written['body'])
                or any(not _text(card.get(field)) for field in ('mechanism', 'alternative', 'horizon', 'invalidation'))
                or not _quote(card.get('invalidation'), written['body'])
                or not _quote(card.get('invalidation'), written['script'])):
            raise ValueError('edition_listener_analysis_incomplete')
    stocks = {s['market'] + ':' + s['code'] for s in state.get('watchlist', [])}
    rows = written.get('stock_followups')
    if (not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows)
            or len(rows) != len(stocks) or {r.get('key') for r in rows} != stocks):
        raise ValueError('edition_listener_stock_followup_missing')
    names = {s['market'] + ':' + s['code']: (s['name'], s['code']) for s in state.get('watchlist', [])}
    for row in rows:
        ids = row.get('source_ids')
        if (row.get('status') not in {'supported', 'insufficient'}
                or not _text(row.get('reason')) or not _text(row.get('next_check'))
                or not _quote(row.get('report_quote'), written['body'])
                or not any(name in row['report_quote'] for name in names[row['key']])
                or not isinstance(row.get('variables'), list) or not row['variables']
                or any(not _text(v) for v in row['variables']) or not isinstance(ids, list)
                or any(sid not in sources for sid in ids)
                or row['status'] == 'supported' and (not ids or any(
                    row['key'] != sources[sid].get('scope')
                    and row['key'] not in sources[sid].get('direct_scopes', []) for sid in ids))):
            raise ValueError('edition_listener_stock_followup_invalid')


def validate_review(state, reviewed):
    if state.get('research_protocol') != PROTOCOL:
        return
    rows = reviewed.get('listener_checks')
    criteria = {'evidence', 'causality', 'company_relevance', 'time_and_units', 'countercase_and_falsifier'}
    written = state['draft']
    if (not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows)
            or len(rows) != len(criteria) or {r.get('criterion') for r in rows} != criteria):
        raise ValueError('edition_listener_review_missing')
    if any(r.get('status') != 'supported' or not _text(r.get('reason'))
           or not _quote(r.get('report_quote'), written['body'])
           or not _quote(r.get('script_quote'), written['script']) for r in rows):
        raise ValueError('edition_listener_review_not_passed')


def restrict_baselines(value, events, sources):
    """A financial background row cannot silently fill a current-news gap."""
    result = deepcopy(value)
    def background_only(row):
        evidence = row.get('evidence') or []
        return bool(evidence) and all(sources.get(e.get('source_id'), {}).get('metadata', {}).get('kind')
            == 'financial_baseline' for e in evidence)
    for row in result.get('events', []):
        event = events.get(row.get('id'), {})
        if (row.get('status') == 'ready' and background_only(row)
                and (event.get('purpose') != 'commentary' or event.get('importance') != 'context')):
            row.update(status='missing', reason='只有往期财务基线，不能支持本期新增事件；需当前事件正文或保留缺口。')
    for row in result.get('watchlist_checks', []):
        if row.get('status') == 'covered' and background_only(row):
            row.update(status='missing', reason='只有财务背景，尚未完成本期公司事件核对。')
    return result


def listening_receipt(state):
    """A listener can see what was actually obtained without reading JSON."""
    lines = ['本期听众核对单', '状态：' + str(state.get('status')),
        '资料截止：' + str(state.get('cutoff')), '', '实际保留的正文（标题不代表事实已核实）：']
    for source in state.get('sources', {}).values():
        lines += ['- ' + source['title'], '  ' + source['url']]
    if not state.get('sources'):
        lines.append('- 目前没有可用正文。')
    lines += ['', '自选股核对：']
    checks = {c['key']: c for c in (state.get('assessment') or {}).get('watchlist_checks', [])}
    for stock in state.get('watchlist', []):
        key = stock['market'] + ':' + stock['code']
        row = checks.get(key, {})
        lines.append('- ' + stock['name'] + '（' + key + '）：' +
            {'covered':'有直接资料', 'missing':'证据不足', 'no_material_event':'已检查但未认定实质事件'}.get(row.get('status'),'尚未评估'))
        if row.get('reason'):
            lines.append('  ' + row['reason'])
    written = state.get('draft') or {}
    if written.get('stock_followups'):
        lines += ['', '针对公司的后续观察：']
        for row in written['stock_followups']:
            lines += ['- ' + row['key'] + '：' + row['reason'],
                '  观察：' + '、'.join(row['variables']), '  下次核对：' + row['next_check']]
    if written.get('listener_cards'):
        lines += ['', '本期判断及撤回条件：']
        for row in written['listener_cards']:
            lines += ['- ' + row['judgment'], '  传导：' + row['mechanism'],
                '  另一种解释：' + row['alternative'], '  适用期间：' + row['horizon'],
                '  撤回条件：' + row['invalidation']]
    lines += ['', '文字与口播审阅：' + ('已通过程序和模型联合检查，仍不等于事实绝对正确'
        if state.get('status') in {'reviewed_text','audio_ready'} else '尚未取得本期通过回执'),
        '音频：' + ('本期已生成' if state.get('status') == 'audio_ready' else '本期尚未生成'),
        '未取得、未读、未核实均不能解释成没有事件。']
    return '\n'.join(lines) + '\n'
