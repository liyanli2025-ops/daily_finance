"""Deterministic input labels and evidence navigation, never a financial verdict."""
import math
import re


def rsi_band(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
        return 'unavailable'
    if value < 30:
        return 'below_30'
    if value > 70:
        return 'above_70'
    return 'within_30_70'


def research_contrast_index(text, limit=4):
    """Point to already-provided exact lines; do not inspect unprovided cache text."""
    rows=[]
    for block in re.split(r'(?=^\[N:)', text, flags=re.M):
        match=re.match(r'\[N:([^\]\s]+)\] ([^\n]+)', block)
        if not match or '类型：' not in block:
            continue
        # Titles/metadata are not source evidence. Read only explicit source spans.
        spans=re.split(r'【原文字符[^】]*】', block)[1:]
        for span in spans:
            for line in span.splitlines():
                line=line.strip()
                if not 20 <= len(line) <= 280 or line.endswith(('?', '？')):
                    continue
                if not re.search(r'单位盈利|毛利率|净利率|利润率|成本转嫁|产品结构|现金流', line):
                    continue
                if not re.search(r'变化|下降|下滑|承压|影响|减少|降低|改善|提升|增长', line):
                    continue
                row=(match.group(1), line)
                if row not in rows: rows.append(row)
    if not rows: return ''
    return ('经营变化阅读索引（只定位已提供原句，不认定负面、因果或新增催化；未命中不代表没有风险）：\n'
        + '\n'.join('[N:'+identifier+'] '+quote for identifier,quote in rows[:limit]))


def decision_pairs(notes):
    """Expose claim/defeater side-by-side without guessing Chinese entailment."""
    return [dict(claim=n.get('claim',''),invalidation=n.get('invalidation',''),
        explanation=n.get('why_invalidation_matters',''),status='needs_semantic_review')
        for n in notes if isinstance(n,dict)]
