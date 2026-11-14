"""Non-destructive reading views. Rules limit use; they never certify truth.

Offsets are Python character offsets in the immutable extracted body, not HTML
or PDF coordinates. Unknown layouts fall back to the whole body.
"""
from copy import deepcopy
import hashlib
import re
from urllib.parse import urlsplit

OWNER = 'finance-evidence-view-v1'
SEPARATOR = '\n[页面附带内容已移至本地原文；以下为另一个原文区间]\n'
LIMIT = '原文完整保存在本地；移出项不作引用。未命中规则不代表可靠。评论只作署名观点，待核资料不能作已确认事实；缺原始依据须保留缺口。'


def merge(spans):
    result = []
    for a, b in sorted(spans):
        if a >= b: continue
        if result and a <= result[-1][1]: result[-1][1] = max(b, result[-1][1])
        else: result.append([a, b])
    return result


def complement(text, spans):
    result, start = [], 0
    for a, b in merge(spans):
        if start < a: result.append([start, a])
        start = b
    if start < len(text): result.append([start, len(text)])
    return result


def screen(source):
    text = source['text']; removed = []; findings = []
    kind = source.get('metadata', {}).get('kind')
    # Structured data and disclosures keep every table row, unit and footnote.
    structured = kind in {'primary_notice', 'market_observation', 'financial_baseline'}
    def remove(a, b, code):
        prefix=text[:a]
        if any((prefix.count(left)%2 if left==right else prefix.rfind(left)>prefix.rfind(right))
               for left,right in (('“','”'),('「','」'),('\"','\"'))):
            return  # Quoted page content is reporting evidence, not our UI.
        removed.append([a, b]); findings.append(dict(code=code, start=a, end=b))
    if not structured:
        for m in re.finditer(r'(?m)^Advertisements?[ \t]*\r?\n', text):
            # Standalone page label only, never remove the following paragraph.
            remove(*m.span(), 'standalone_ad_label')
        # A footer needs BOTH a reader-count CTA and platform share controls.
        footer = re.search(r'(?m)^Our community already has [^\n]*readers!\s*\nSubscribe to our Telegram channel\b', text)
        if footer and 'Share on X (Opens in new window)' in text[footer.start():]:
            # A later legal disclaimer is never swallowed by the footer.
            end = re.search(r'(?mi)^Disclaimer[:：]', text[footer.start():])
            remove(footer.start(), footer.start()+end.start() if end else len(text), 'subscription_share_footer')
        # Author platform biography is removed only with an explicit repeated
        # byline, platform sales copy, tags AND a separate disclaimer boundary.
        bio = re.search(r'(?m)^TradingView\s*\nTradingView\s*\n', text)
        if bio:
            tail = text[bio.end():]; end = re.search(r'(?m)^Disclaimer:\s*\n', tail)
            if end and 'Tags:\n' in tail[:end.start()] and 'Look first, then leap.' in tail[:end.start()]:
                remove(bio.start(), bio.end()+end.start(), 'platform_biography_and_tags')
        # Related-link blocks need their exact UI delimiter and a commercial
        # title. Bare "Read also" or genuine contrary reporting stays visible.
        for m in re.finditer(r'(?mi)^Read also[ \t]*\n?:[ \t]*\n([^\n]+)(?:\n|$)', text):
            if re.search(r'Retirement Blueprint|Tax Management strategies for Digital Nomads|Build Your Wealth and Freedom', m[1], re.I):
                remove(*m.span(), 'commercial_related_link')
        # Only a standalone site voice CTA. Quoted/reported promotion is kept.
        for m in re.finditer(r'It is time to seize this price opportunity and invest in gold\.', text):
            left = text[max(0, m.start()-2):m.start()]
            if left in {'', '\n', '. ', '。', '\n\n'} and text[m.end():].startswith(('\n', '\r\n')):
                remove(*m.span(), 'direct_investment_cta')
    ranges = complement(text, removed)
    reasons = []
    # A period discrepancy is a verification question, not a falsehood verdict.
    if not structured and re.search(r'单周|一周', source.get('title', '')) and re.search(r'最近两[个]?日|两日累计', text):
        reasons.append('period_basis_requires_confirmation')
    # High-impact corporate claims require a separate original source before
    # this mixed market overview can be used as factual evidence. These are
    # explicit lead flags, not a general misinformation detector.
    if not structured and re.search(r"\b(?:resignation|interim CEO)\b", text, re.I) and re.search(r'\bIPO\b', text, re.I):
        reasons.append('leadership_and_ipo_claims_require_original_source')
    commentary = (not structured and (re.search(r'/(?:opinion|commentary)/', urlsplit(source.get('url', '')).path, re.I)
        or re.search(r'^\([^\n]{0,60}Commentary\)', text, re.I)))
    use = 'pending_verification' if reasons else ('attributed_commentary' if commentary else 'evidence_candidate')
    return dict(owner=OWNER, original_text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        original_characters=len(text), retained_characters=sum(b-a for a,b in ranges),
        removed_characters=sum(b-a for a,b in merge(removed)), provided_original_ranges=ranges,
        removed=findings, use=use, reasons=reasons, facts_verified=False,
        limitation=LIMIT)


def view(source):
    # Existing editorial excerpts already refer to the original full body.
    if 'provided_original_ranges' in source: return deepcopy(source)
    review = screen(source)
    if not review['removed'] and review['use'] == 'evidence_candidate': return deepcopy(source)
    result = deepcopy(source)
    result['text'] = SEPARATOR.join(source['text'][a:b] for a,b in review['provided_original_ranges'])
    result['evidence_view'] = {k: review[k] for k in
        ('owner', 'original_text_sha256', 'original_characters', 'removed_characters', 'use', 'reasons', 'facts_verified')}
    result['provided_original_ranges'] = review['provided_original_ranges']
    if review['use'] == 'pending_verification':
        # Send identity and verification tasks, never pay to repeat this entire
        # mixed article as if it were usable evidence. The cleaned local copy
        # remains available in the free inspection report.
        result['text']=''
        result['provided_original_ranges']=[]
    result['reading_limit'] = LIMIT + (' 本篇仅提供身份和待核问题，正文未送达；须找其他原始依据。' if review['use']=='pending_verification' else '')
    return result


def assert_quote(source, quote, purpose=None, delivered_ranges=None):
    """A verbatim quote is necessary, not sufficient, for a supported claim."""
    review = source.get('evidence_view') or screen(source)
    if review['use'] == 'pending_verification':
        raise ValueError('edition_source_requires_confirmation')
    if review['use'] == 'attributed_commentary' and purpose not in {None, 'commentary'}:
        raise ValueError('edition_commentary_not_factual_evidence')
    if SEPARATOR in quote or '[中间原文未提供]' in quote:
        raise ValueError('edition_quote_crosses_omission')
    if 'evidence_view' in source:
        # View quotes may not cross synthetic omission boundaries.
        if not any(quote in part for part in source['text'].split(SEPARATOR)):
            raise ValueError('edition_quote_outside_evidence_view')
    else:
        ranges = review['provided_original_ranges']
        if delivered_ranges is not None:
            ranges = [[max(a,c),min(b,d)] for a,b in ranges for c,d in delivered_ranges if max(a,c)<min(b,d)]
        if not any(quote in source['text'][a:b] for a,b in ranges):
            raise ValueError('edition_quote_outside_evidence_view')


def audit(sources):
    rows = {sid: screen(s) for sid,s in sources.items()}
    return dict(owner=OWNER, sources=rows,
        original_article_characters=sum(len(s['text']) for s in sources.values() if s.get('candidate_id')),
        removed_characters=sum(r['removed_characters'] for r in rows.values()),
        pending_verification=[sid for sid,r in rows.items() if r['use']=='pending_verification'],
        commentary=[sid for sid,r in rows.items() if r['use']=='attributed_commentary'],
        original_sources_unchanged=True, limitation=LIMIT)


def report(sources):
    lines = ['已存材料自动筛选对照（非事实核验通过）', LIMIT,
             '没有模型、搜索、网页或语音请求；原文、费用和失败标记不变。', '']
    labels = {'evidence_candidate':'待评估证据候选（不是已核实）',
              'attributed_commentary':'仅作署名观点，不证明其中事实',
              'pending_verification':'待核线索，禁止直接支持ready或成稿引用'}
    for sid, source in sources.items():
        review=screen(source);clean=view(source)
        lines += ['='*60, sid+' '+source['title'],source.get('url',''),
            '用途：'+labels[review['use']], '触发问题：'+', '.join(review['reasons']),
            '原文字符：'+str(review['original_characters'])+'；移出页面杂项：'+str(review['removed_characters']),
            '原文SHA256：'+review['original_text_sha256'],
            '【模型阅读视图；不能因可读就当成事实】', clean['text'] or '待核文章正文不送给模型，只保留身份及核查问题。',
            '【本地清理后正文，供人工核查；不等于已送达模型】',
            SEPARATOR.join(source['text'][a:b] for a,b in review['provided_original_ranges']),
            '【移出的页面附带内容；原文中仍保存】']
        for row in review['removed']:
            lines += [f"{row['code']} 原文[{row['start']},{row['end']})",source['text'][row['start']:row['end']]]
        lines.append('')
    return '\n'.join(lines)
