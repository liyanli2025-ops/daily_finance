"""Bounded daily discovery tasks and receipts tied to executed work, not categories filled by a model."""
from copy import deepcopy
import re

PROTOCOL = 'daily_changes_v1'
CATEGORIES = {
    'politics': ('宏观政治', '选举、关税、央行、财政、贸易限制、冲突；区分拟议、公布、生效和新进展'),
    'industry': ('行业变化', '供需、价格、库存、技术突破、商业化验证、竞争份额；不能用单家股价代替行业'),
    'operations': ('公司经营', '订单、客户、供应商、产品、产能、事故和停产；关系须有证据，不猜客户名单'),
    'governance': ('治理与风险', '管理层、监管调查、诉讼、融资、股东行为；区分计划和实际发生'),
    'market': ('市场变化', '汇率、利率、成交结构、涨跌分布和预期变化；价格反应不等于因果或已定价'),
}
SIGNALS = {
    'politics': r'选举|大选|中期选举|关税|制裁|央行|战争|空袭|election|tariff|sanction|central bank|war\b',
    'industry': r'技术突破|量产|商业化|竞争|市场份额|库存|供需|breakthrough|commercialization|market share|inventory',
    'operations': r'订单|客户|供应商|停产|事故|召回|新产品|扩产|order|customer|supplier|outage|recall',
    'governance': r'董事长|辞职|换帅|调查|诉讼|减持|增持|融资|违约|investigation|lawsuit|resign|default',
    'market': r'汇率|收益率|成交|涨跌家数|预期|共识|turnover|breadth|consensus|expectation|yield',
}


def enabled(state):
    return state.get('change_protocol') == PROTOCOL


def targeted_jobs(stocks, now, baselines=None):
    """Two different company questions, even when an announcement already exists."""
    day = now.strftime('%Y-%m-%d')
    result = []
    if not stocks:
        return [dict(lane='company_event', purpose='discovery', change_task=k,
            change_categories=[k], query=day+' 上市公司 大型企业 '+q) for k,q in (
                ('operations','重大订单 产品 产能 事故 停产 最新进展'),
                ('governance','管理层 调查 诉讼 融资 股东 重大风险 最新进展'))]
    for stock in stocks:
        scope = stock['market'] + ':' + stock['code']
        profile = ((baselines or {}).get(scope) or {}).get('profile') or {}
        industry = profile.get('industry')
        business = (' ' + industry[:18]) if isinstance(industry, str) else ''
        prefix = day + ' ' + stock['name'][:20] + ' ' + stock['code'] + business
        for category, question in (
            ('operations', '订单 客户 供应商 新产品 产能 事故 停产 最新进展'),
            ('governance', '管理层 监管 调查 诉讼 融资 股东 增减持 最新进展')):
            result.append(dict(lane='company_event', scope=scope, purpose='company_event',
                change_task=category + ':' + scope, change_categories=[category],
                query=prefix + ' ' + question))
    return result


def decorate_jobs(jobs, now, baselines=None):
    """Retain market session jobs; specialize the other existing slots, not extra loops."""
    result = deepcopy(jobs)
    for job in result:
        lane, q = job.get('lane'), job['query']
        category = {'a_market':'market', 'hk_market':'market', 'us_market':'market',
                    'commodities':'market', 'industry':'industry', 'global_policy':'politics',
                    'company_event':'operations'}.get(lane)
        job['change_categories'] = [category] if category else []
        if lane == 'industry':
            job['query'] = now.strftime('%Y-%m-%d') + ' 行业 供需 价格 库存 技术突破 商业化 竞争格局 市场份额 新进展'
        elif lane == 'global_policy' and 'major world' in q:
            job['query'] = now.strftime('%Y-%m-%d') + ' election tariff central bank conflict major developments financial markets'
        elif lane == 'global_policy' and '国内 国际' in q:
            industries = sorted({r.get('profile', {}).get('industry') for r in (baselines or {}).values()
                if isinstance(r.get('profile'), dict) and isinstance(r['profile'].get('industry'), str)})
            subjects = ' '.join(s[:12] for s in industries[:4])
            job.update(lane='industry', change_categories=['industry'],
                query=now.strftime('%Y-%m-%d') + ' ' + subjects + ' 产业链 客户 供应商 技术 商业化 竞争格局 最新变化')
    return result


def tasks(state):
    rows = [dict(id=k, name=v[0], question=v[1]) for k,v in CATEGORIES.items()]
    for stock in state.get('watchlist', []):
        scope = stock['market'] + ':' + stock['code']
        rows.extend(dict(id=k + ':' + scope, name=stock['name'] + '·' + CATEGORIES[k][0],
            question=CATEGORIES[k][1], scope=scope) for k in ('operations', 'governance'))
    return rows


def job_matches(job, task):
    return (task['id'] == job.get('change_task') or ':' not in task['id']
        and task['id'] in job.get('change_categories', []))


def coverage(state):
    """Search completion, saved bodies and editorial conclusions are different columns."""
    checks = {r.get('task_id'):r for r in (state.get('assessment') or {}).get('change_checks', [])
              if isinstance(r, dict)}
    result = []
    for task in tasks(state):
        receipts = [r for r in state.get('search_receipts', []) if job_matches(r.get('job', {}), task)]
        ids = [cid for cid,c in state.get('candidates', {}).items()
               if any(job_matches(j, task) for j in c.get('search_links', []))]
        bodies = [sid for sid,s in state.get('sources', {}).items() if s.get('candidate_id') in ids
            or task.get('scope') in s.get('direct_scopes', []) and re.search(
                SIGNALS[task['id'].split(':')[0]], s.get('text', ''), re.I)
            or task['id'] == 'market' and s.get('metadata', {}).get('kind') == 'market_observation']
        result.append(dict(task, discovery='checked' if any(r.get('result', {}).get('status') == 'ok'
            for r in receipts) else 'unavailable' if receipts else 'not_checked',
            candidate_ids=ids, stored_source_ids=bodies,
            conclusion=checks.get(task['id'], {}).get('status', 'not_assessed')))
    return result


def brief(state):
    if not enabled(state):
        return {}
    signals = [dict(candidate_id=cid, categories=[k for k,p in SIGNALS.items()
        if re.search(p, str(c.get('title', '')), re.I)]) for cid,c in state.get('candidates', {}).items()]
    market = state.get('market_observations', {})
    market_note = {k:deepcopy(market[k]) for k in ('status','observed_at','gaps','limitation') if k in market}
    market_note['evidence_source_ids'] = [sid for sid,s in state.get('sources', {}).items()
        if s.get('metadata', {}).get('kind') == 'market_observation']
    return dict(change_protocol=PROTOCOL, change_coverage=coverage(state),
        change_signals=[r for r in signals if r['categories']],
        market_observations=market_note,
        change_limit='标题标记仅帮助逐事件查漏，未命中仍可能重要；检索完成不等于覆盖充分、没有新闻或事实已核实。')


def requirements(stage):
    common = '''\n启用daily_changes_v1。五类变化均属于日报，不限业绩；旧事件新进展、回应、修正也可能是新闻。
change_coverage显示实际检索范围，change_signals只是标题线索。选举等具体事件不得用泛泛“宏观已覆盖”代替。
每个有信号的候选仍须在agenda中逐事件归类或明确排除理由；同一政治类别不代表同一事件。
含选举/关税/央行/冲突线索的候选，事件标题或排除理由须明确指出相应议题，不允许只写“国际宏观”。
客户/供应商/竞争关系、技术突破的商业化程度、管理层传闻、监管指控须读正文核实；转载不当独立佐证。
market_observations只支持其中实际得到且标明范围/时点的数据，缺失不是零值；不得将样本扩为全市场。
'''
    if stage in {'assessment', 'patch_assessment'}:
        return common + '''新增change_checks数组：change_coverage中每个id恰好一项
{task_id,status:"supported或screened_no_material_event或missing",reason:"具体结论边界",
evidence:[{source_id,quote:"已提供正文逐字引文"}]}。
supported只能用本任务候选的已读正文，公司项还须匹配直接公司主体；不以财务背景代替今日变化。
screened_no_material_event仅表示本次已执行的有限检索中未选出相关实质变化，不声称全网或公司没有事件。
存在尚待核实的重大事件须missing，并在现有additional_searches/reads提出具体缺口，不要无限改写。
如要下“超预期/低于预期/未定价/空头回补/资金流入驱动”结论，新增expectation_checks数组：
{claim_quote:"拟用于稿件的完整短句",event_id,
actual:{source_id,quote,as_of:"ISO时点含时区",metric,unit,period},
baseline:{source_id,quote,as_of:"ISO事前时点含时区",metric,unit,period},
baseline_before_actual:true,comparable:true,reason:"逐字依据中的时点、口径、基线为何可比"}。
没有事前预期或仓位证据时不得做这种判断，写无法判断；涨跌不是预期基线。
'''
    if stage in {'writing','review'}:
        return common + '''change_checks缺口必须在结论边界中保留，不用五类清单硬凑每天五条新闻。
没有expectation_checks中匹配的双边原文和事前可比基线，禁止肯定“超预期/低于预期/未定价/空头回补/资金流入驱动”；
可以明确说“无法判断是否超预期”。审阅须核事前时点、同单位同期间，不能因程序检查通过就认定可比。
'''
    return common


def audit_agenda(state, agenda):
    if not enabled(state):
        return
    decisions = []
    groups = list(agenda.get('events', [])) + list(agenda.get('excluded_candidates', []))
    for cid,c in state.get('candidates', {}).items():
        for topic, pattern in (('选举',r'选举|大选|election'), ('关税',r'关税|tariff'),
                               ('央行',r'央行|central bank|fed\b|federal reserve'),
                               ('冲突',r'战争|空袭|冲突|war\b|conflict')):
            if not re.search(pattern, str(c.get('title','')), re.I):
                continue
            matches = [r for r in groups if cid in r.get('candidate_ids', [])]
            if not matches or any(not re.search(pattern, r.get('title','')+' '+r.get('reason',''), re.I)
                                  for r in matches):
                raise ValueError('edition_change_concrete_event_lost')
            decisions.append(dict(candidate_id=cid, topic=topic,
                decisions=[dict(event_id=r.get('id'), reason=r.get('reason')) for r in matches]))
    state['change_signal_decisions'] = decisions


def validate_checks(state, value, provided):
    if not enabled(state):
        return []
    expected = {r['id']:r for r in coverage(state)}
    rows = value.get('change_checks')
    if (not isinstance(rows, list) or len(rows) != len(expected)
            or any(not isinstance(r, dict) for r in rows)
            or {r.get('task_id') for r in rows} != set(expected)):
        raise ValueError('edition_change_checks_missing')
    missing = []
    for row in rows:
        task = expected[row['task_id']]
        if (row.get('status') not in {'supported','screened_no_material_event','missing'}
                or not isinstance(row.get('reason'), str) or len(row['reason'].strip()) < 8):
            raise ValueError('edition_change_check_invalid')
        if row['status'] == 'screened_no_material_event' and task['discovery'] != 'checked':
            raise ValueError('edition_change_not_searched')
        if row['status'] == 'supported':
            evidence = row.get('evidence')
            if not isinstance(evidence, list) or not evidence:
                raise ValueError('edition_change_evidence_missing')
            for e in evidence:
                s = state.get('sources', {}).get(e.get('source_id')) if isinstance(e, dict) else None
                if (not s or s['id'] not in provided or s['id'] not in task['stored_source_ids']
                        or not isinstance(e.get('quote'), str) or not 2 <= len(e['quote']) <= 400
                        or e['quote'] not in s['text']
                        or s.get('metadata', {}).get('kind') == 'financial_baseline'
                        or task.get('scope') and task['scope'] not in s.get('direct_scopes', [])):
                    raise ValueError('edition_change_evidence_invalid')
        if row['status'] == 'missing':
            missing.append('change:' + row['task_id'])
    return missing


def validate_expectations(state, value, provided):
    """Verbatim two-sided evidence is a prerequisite; reviewer still checks semantics/dates."""
    rows = value.get('expectation_checks', [])
    if not isinstance(rows, list):
        raise ValueError('edition_expectation_invalid')
    for row in rows:
        if (not isinstance(row, dict) or row.get('event_id') not in
                {r['id'] for r in state.get('agenda', {}).get('events', [])}
                or not isinstance(row.get('claim_quote'), str) or not 4 <= len(row['claim_quote']) <= 200
                or row.get('baseline_before_actual') is not True or row.get('comparable') is not True
                or not isinstance(row.get('reason'), str) or len(row['reason'].strip()) < 12):
            raise ValueError('edition_expectation_invalid')
        for key in ('actual','baseline'):
            e = row.get(key) or {}
            s = state.get('sources', {}).get(e.get('source_id'))
            if (not s or s['id'] not in provided or row['event_id'] not in s.get('event_ids', [])
                    or not isinstance(e.get('quote'), str) or not 2 <= len(e['quote']) <= 400
                    or e['quote'] not in s['text']):
                raise ValueError('edition_expectation_evidence_invalid')
        from datetime import datetime, timezone, timedelta
        try:
            actual, baseline = row['actual'], row['baseline']
            a, b = (datetime.fromisoformat(v['as_of']) for v in (actual, baseline))
            cutoff = datetime.fromisoformat(state['cutoff'])
            if cutoff.tzinfo is None:
                cutoff = cutoff.replace(tzinfo=timezone(timedelta(hours=8)))
            if a.tzinfo is None or b.tzinfo is None or not b < a <= cutoff:
                raise ValueError()
            if any(not isinstance(actual.get(k), str) or not actual[k].strip()
                   or actual[k] != baseline.get(k) for k in ('metric','unit','period')):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ValueError('edition_expectation_time_or_metric_invalid') from None
        if row['actual'] == row['baseline']:
            raise ValueError('edition_expectation_same_evidence')


def validate_language(state, written):
    if not enabled(state):
        return
    approved = [r['claim_quote'] for r in (state.get('assessment') or {}).get('expectation_checks', [])]
    for field in ('body','script'):
        for sentence in re.split(r'[。！？\n]', written.get(field, '')):
            for match in re.finditer(r'超预期|低于预期|未定价|空头回补|资金流入驱动', sentence):
                prefix = sentence[max(0,match.start()-16):match.start()]
                if re.search(r'(?:无法|不能|尚不能|不足以|未能|不宜|不代表|不等于|是否|未证实|缺乏)[^，；]{0,12}$', prefix):
                    continue
                covered = False
                for claim in approved:
                    start = 0
                    while True:
                        left = sentence.find(claim, start)
                        if left < 0:
                            break
                        if left <= match.start() and match.end() <= left+len(claim):
                            covered = True
                        start = left+1
                if not covered:
                    raise ValueError('edition_expectation_claim_without_baseline')
