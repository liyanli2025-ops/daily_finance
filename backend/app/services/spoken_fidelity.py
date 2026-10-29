"""Require auditable anchors in a speech review; never infer semantic truth locally."""
import re

VERSION='spoken-review-anchors-v1'
FACETS=('facts','judgment','qualifiers')
CONTRACT="""逐项对照报告与口播，检查新增事实、数字/日期偏差、推断变事实、无依据交易建议、关键反证与期限/条件遗漏。允许舍弃非选题的整段，不能保留结论却删去改变含义的理由或限制。
重点核对：历史相对弱势是否被改成持续卖压，公司经营解释是否被改成市场定价原因；短线反弹是否被替换成趋势反转，正文可选条件是否在口播变为必需条件。纠正这种含义变化，不因作者有方向性倾向就否决。
只输出严格JSON：{"passed":true,"issues":[],"checks":[{"facet":"facts","status":"preserved","report_quote":"报告逐字原句","script_quote":"口播逐字原句","reason":"两句的事实及口径为何一致"},{"facet":"judgment","status":"preserved","report_quote":"原判断","script_quote":"口播判断","reason":"对象、期限和确定性是否一致"},{"facet":"qualifiers","status":"preserved","report_quote":"关键反方或条件","script_quote":"口播保留的限制","reason":"为什么未删改关键限制"}]}。
checks每类1—3项，必须覆盖facts/judgment/qualifiers三类。每条原句2—240字且逐字存在，report_quote只能摘自完整分析正文，不摘摘要或核心观点；reason为2—240字。有问题则passed=false、issues列出具体问题，status用changed或missing，缺失侧原句可为null。
若选题确实无判断或限制，该类可用not_applicable，但仍引用双方原句并说明为什么不适用，不能以“没有找到”为由省略报告已有的关键条件。facts不能not_applicable。引用存在不代表含义相同，必须核对否定、条件、时间和主体，不能靠同一数字或关键词判通过。无需为每项材料凑朗读或要求所有公司都出现。"""


def _contains(quote,text):
    if not isinstance(quote,str) or not 2<=len(quote)<=240: return False
    normalized=re.sub(r'\s+',' ',quote).strip()
    return len(normalized)>=2 and normalized in re.sub(r'\s+',' ',text)


def assess(value,report,script):
    errors=[]
    if not isinstance(value,dict): return dict(anchors_valid=False,errors=['review_not_object'])
    rows=value.get('checks')
    if not isinstance(rows,list) or not 3<=len(rows)<=9:
        return dict(anchors_valid=False,errors=['missing_or_unbounded_checks'])
    counts={facet:0 for facet in FACETS}
    for i,row in enumerate(rows):
        if not isinstance(row,dict): errors.append(f'{i}:not_object');continue
        facet=row.get('facet');status=row.get('status')
        if facet not in counts: errors.append(f'{i}:unknown_facet')
        else: counts[facet]+=1
        if status not in {'preserved','not_applicable','changed','missing'}: errors.append(f'{i}:unknown_status')
        if status=='not_applicable' and facet=='facts': errors.append(f'{i}:facts_required')
        reason=row.get('reason')
        if not isinstance(reason,str) or not 2<=len(reason.strip())<=240: errors.append(f'{i}:reason_missing')
        for key,text in [('report_quote',report),('script_quote',script)]:
            quote=row.get(key)
            if quote is None and status=='missing' and value.get('passed') is False: continue
            if not _contains(quote,text): errors.append(f'{i}:{key}_not_found')
        if value.get('passed') is True and status not in {'preserved','not_applicable'}: errors.append(f'{i}:pass_conflicts_with_issue')
    if any(not 1<=count<=3 for count in counts.values()): errors.append('facet_coverage_incomplete')
    return dict(version=VERSION,anchors_valid=not errors,errors=errors,
        limitation='只验证双方原句存在和审查结构；不证明含义相同、事实正确或选题覆盖完整，不自动推翻审查问题')
