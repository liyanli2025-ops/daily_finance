"""Check review anchors before paying for a rewrite; not a truth adjudicator."""
import math
import re

DECISION_NOTES_INSTRUCTION='''decision_notes为最多3项简短可核查判断摘要，不是思维过程。每项包含claim、horizon、price_structure、possible_drivers、main_alternative、watch、invalidation、why_invalidation_matters字符串（每项不超过120字），support_ids和counterevidence_ids为材料ID数组（无反方材料可为空）。价格结构与可能驱动分别填写，可同时成立；why_invalidation_matters解释条件出现为何削弱claim，不重复条件本身。条件必须削弱同一个claim，不能悄悄换成另一项预测：例如claim为“下降结构中的反弹、尚非反转”，回吐支持而非推翻它；持续形成更高高低点等结构改善才可能削弱它。若claim为“反弹将延续”，回吐才可能是反证。历史事实本身不因未来表现失效。不新增事实或未经校准概率；这份清单不在播客中逐项朗读。'''


class ReviewNeedsHuman(RuntimeError):
    def __init__(self,message,reason='review_feedback_unverified'):
        super().__init__(message)
        self.reason=reason


def normalized(text):
    return re.sub(r'\s+',' ',text).strip()


def assess(issues,report,evidence):
    checks=[]
    factual={'数据不一致','信息编造','交易日错误','数据编造'}
    kinds={'numeric_mismatch','time_or_basis','unsupported_fact','missing_evidence','reasoning','clarity'}
    for index,issue in enumerate(issues):
        reasons=[]
        quote=issue.get('report_quote')
        source=issue.get('source_quote')
        kind=issue.get('check_kind')
        if not isinstance(quote,str) or not 2<=len(quote)<=240 or normalized(quote) not in normalized(report):
            reasons.append('report_quote_missing_or_not_found')
        if kind not in kinds:reasons.append('check_kind_missing_or_unknown')
        if issue.get('type') in factual and kind=='missing_evidence':
            reasons.append('missing_evidence_does_not_establish_fabrication')
        required=issue.get('type') in factual or kind in {'numeric_mismatch','time_or_basis','unsupported_fact'}
        if required or source:
            if not isinstance(source,str) or not 2<=len(source)<=500 or normalized(source) not in normalized(evidence):
                reasons.append('source_quote_missing_or_not_found')
        if kind=='numeric_mismatch':
            comparison=issue.get('comparison')
            if not isinstance(comparison,dict):
                reasons.append('numeric_comparison_missing')
            else:
                a,b=comparison.get('reported'),comparison.get('source')
                def numeric(value):
                    try:return type(value) in {int,float} and math.isfinite(value)
                    except OverflowError:return False
                if not numeric(a) or not numeric(b) or comparison.get('same_basis') is not True:
                    reasons.append('numeric_values_or_basis_unverified')
                elif math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-12):
                    reasons.append('numeric_values_agree_not_a_numeric_mismatch')
        checks.append(dict(issue_index=index,anchors_valid=not reasons,reasons=reasons))
    return dict(issues=checks,all_anchors_valid=all(row['anchors_valid'] for row in checks),
        limitation='仅核对原句锚点与显式数字比较，不能证明审查结论正确，也不自动丢弃或放行任何问题')


def decision_notes(value,allowed_ids):
    """Bounded, deliverable claim summaries, not hidden reasoning or new facts."""
    if value is None:return []
    if not isinstance(value,list) or len(value)>3:raise RuntimeError('判断清单格式错误')
    fields=('claim','horizon','price_structure','possible_drivers','main_alternative',
            'watch','invalidation','why_invalidation_matters')
    result=[]
    for row in value:
        if not isinstance(row,dict) or any(not isinstance(row.get(key),str) or not 1<=len(row[key])<=120 for key in fields):
            raise RuntimeError('判断清单字段不完整或超长')
        output={key:row[key] for key in fields}
        for key in ('support_ids','counterevidence_ids'):
            ids=row.get(key)
            if not isinstance(ids,list) or len(ids)>8 or any(not isinstance(item,str) or item not in allowed_ids for item in ids):
                raise RuntimeError('判断清单引用未知证据ID')
            output[key]=ids
        result.append(output)
    return result
