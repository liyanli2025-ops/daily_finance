"""Non-destructive editorial warnings and evidence-based follow-up questions.

Heuristics can flag quoted advertising in a legitimate report. They never
rewrite evidence or certify clean text; use a reviewed alternative source.
"""
import re


def review_body(content):
    findings = []
    # Require paired commercial signals, not generic words such as 'price',
    # 'buy' or 'subscription', which are ordinary financial reporting terms.
    merchandise = re.compile(r'冰箱贴|文创周边|周边商品|限量周边|福利礼包')
    action = re.compile(r'扫码|下单|抢购|领券|带回家|购买链接')
    for match in merchandise.finditer(content):
        start, end = max(0, match.start()-100), min(len(content), match.end()+100)
        if action.search(content[start:end]):
            findings.append(dict(code='merchandise_call_to_action', start=start, end=end))
    for match in re.finditer(r'扫码(?:购买|下单|领券)|点击(?:购买|下单)|立即(?:购买|下单|抢购)', content):
        findings.append(dict(code='purchase_call_to_action', start=match.start(), end=match.end()))
    # Multiple lettered poll choices are an interaction block, not price data.
    choices = list(re.finditer(r'(?m)^\s*[A-D]\s*级\s*[｜|：:]', content))
    if len(choices) >= 3:
        findings.append(dict(code='reader_poll_choices', start=choices[0].start(),
                             end=content.find('\n', choices[-1].end()) if '\n' in content[choices[-1].end():] else len(content)))
    return dict(status='editorial_review_required' if findings else 'no_obvious_promotion_signal',
                requires_editorial_review=bool(findings), findings=findings,
                text_modified=False,
                limitation='启发式提示可能命中报道引用；未命中不保证无推广，不裁决事实或重要性。位置为原始正文字符区间。')


QUESTIONS = {
    'a_market': '核对最近已完成A股交易日、指数/成交口径、主要行业变化；短讯不足以解释主线。',
    'hk_market': '核对最近已完成港股交易日、恒指/恒科和主要驱动；不以盘中稿代替收盘。',
    'us_market': '以当地语言核对美股最新已完成交易日及盘后消息；分清日涨跌和月收益。',
    'global_policy': '先找实际已公布的央行、财政或贸易原披露，区别会议声明、预测和评论。',
    'commodities': '分别核对合约/现货、币种、单位与交易日；分析师晨报不等于当天收盘。',
    'industry': '找独立的供需、订单、库存或价格资料；单家财报和股价异动不代表全行业。',
    'company_event': '找具体主体的原披露、回应与反证；全市场重要公司不等于用户持仓公司。',
}


def followup_plan(news, source):
    """A plan, never search execution or an automatic coverage pass."""
    from .search_primary_collection import LANES
    quality = {n.id: review_body(n.content) for n in news}
    lengths = {n.id: len(n.content.strip()) for n in news}
    declared = source.get('intake', {}).get('declared_body_coverage', {})
    if not declared:
        declared = {r['lane']: r.get('evidence_ids', []) for r in
                    (source.get('research') or {}).get('coverage', []) if r.get('status') == 'body_provided'}
    lane_rows, tasks = [], []
    for lane in LANES:
        ids = [identifier for identifier in declared.get(lane, []) if identifier in quality]
        flagged = [identifier for identifier in ids if quality[identifier]['requires_editorial_review']]
        usable = [identifier for identifier in ids if identifier not in flagged]
        short_ids = [identifier for identifier in usable if lengths[identifier] < 160]
        lane_rows.append(dict(lane=lane, declared_body_ids=ids, flagged_body_ids=flagged,
                              unflagged_body_ids=usable, short_text_ids=short_ids, coverage_verified=False))
        if flagged:
            tasks.append(dict(lane=lane, action='replace_or_editorially_review_body',
                              evidence_ids=flagged, question=QUESTIONS[lane], executed=False))
        if not usable:
            tasks.append(dict(lane=lane, action='locate_independent_body',
                              evidence_ids=[], question=QUESTIONS[lane], executed=False))
        elif lane in {'a_market', 'hk_market', 'us_market'} and len(short_ids) == len(usable):
            tasks.append(dict(lane=lane, action='check_drivers_beyond_short_bulletin',
                              evidence_ids=short_ids, question=QUESTIONS[lane], executed=False))
    return dict(owner='finance-primary-followup-v1', body_quality=quality,
                lanes=lane_rows, tasks=tasks, requests_performed=0,
                watchlist_action='verify_current_app_list_before_scoped_search',
                limitation='范围来自输入声明或模型底稿，需人工核对；未标推广不代表已独立核实。补查建议不发请求、不证明已检索；缺口不等于没有消息。')
