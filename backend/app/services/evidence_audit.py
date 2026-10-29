"""Offline checks of the text actually supplied; never a rating of trading edge."""
from collections import Counter, defaultdict
import hashlib
import html
import json
import re

from .event_observations import canonical
from .news_quality import reading_scope, company_focus, excluded_reason
from .news_selection import matches_watchlist


def normalized_body(item):
    # Preserve numbers, signs, negation and punctuation: changes can be material.
    text = re.sub(r'<[^>]+>', ' ', html.unescape(item.content or ''))
    return re.sub(r'\s+', '', text).strip()


def title_only(item):
    plain = lambda text: re.sub(r'[^\w\u4e00-\u9fff]', '', text).casefold()
    body, title = plain(normalized_body(item)), plain(item.title)
    return not body or body == title


def copy_reason(left, right):
    """Conservative copy removal. Different full bodies are retained for reasoning."""
    a, b = normalized_body(left), normalized_body(right)
    if len(a) >= 80 and a == b:
        return 'same_body'
    if canonical(left.source_url) == canonical(right.source_url) and a == b:
        return 'same_url_and_text'
    return None


def retain_distinct_full_bodies(left, right):
    # A matching headline alone must not discard an update or contrary account.
    return (reading_scope(left) == reading_scope(right) == 'full_text'
            and len(normalized_body(left)) >= 80 and len(normalized_body(right)) >= 80
            and not copy_reason(left, right))


def audit(candidates, selected, stocks, profiles):
    from .news_briefing import associations, topic
    selected = list(selected)
    rows = []
    bodies, urls = defaultdict(list), defaultdict(list)
    for item in selected:
        body = normalized_body(item)
        digest = hashlib.sha256(body.encode()).hexdigest()
        bodies[digest].append(item.id)
        urls[canonical(item.source_url)].append(item.id)
        rows.append(dict(id=item.id, title=item.title, url=item.source_url,
            reading_scope=reading_scope(item), supplied_characters=len(item.content or ''),
            text_shape='title_only' if title_only(item) else 'short_text' if len(body)<200 else 'body_text',
            body_hash=digest, topic=topic(item)))
    per_stock = []
    for stock in stocks:
        key = str(getattr(stock.market, 'value', stock.market))+':'+stock.code
        company, industry, mentions, excerpts = [], [], [], []
        for item in selected:
            full = reading_scope(item) == 'full_text' and not title_only(item)
            if company_focus(item, stock):
                (company if full else excerpts).append(item.id)
            elif full and any(row['stock']==key and row.get('operating_context')
                              for row in associations(item,[stock],profiles)):
                industry.append(item.id)
            elif matches_watchlist(item, [stock]):
                mentions.append(item.id)
            elif any(row['stock']==key and row['level']=='business_overlap'
                     for row in associations(item, [stock], profiles)) and full:
                industry.append(item.id)
        gaps = []
        if not company:
            gaps.append('本次入模材料无公司专属原文；不是已证明公司无新消息')
        if not industry:
            gaps.append('本次入模材料无已匹配经营环节的行业原文；研究缓存另行核对')
        per_stock.append(dict(stock=key, name=stock.name, company_original_ids=company,
            industry_original_ids=industry, mention_only_ids=mentions,
            company_excerpt_ids=excerpts, gaps=gaps))
    scopes = dict(Counter(row['reading_scope'] for row in rows))
    return dict(status='requires_editorial_assessment', candidate_articles=len(candidates),
        candidate_reading_scopes=dict(Counter(reading_scope(item) for item in candidates)),
        selected_articles=len(selected), reading_scopes=scopes,
        title_only_articles=sum(row['text_shape']=='title_only' for row in rows),
        short_originals=sum(row['text_shape']=='short_text' and row['reading_scope']=='full_text' for row in rows),
        exact_text_versions=len(bodies),
        duplicate_text_groups=[ids for ids in bodies.values() if len(ids)>1],
        same_url_groups=[ids for url,ids in urls.items() if url and len(ids)>1],
        selected_topics=dict(Counter(row['topic'] for row in rows if row['topic'])),
        admission_exclusions=dict(Counter(reason for item in candidates if (reason:=excluded_reason(item)))),
        per_stock=per_stock, articles=rows,
        limitation='正文数量、不同文本版本和不同域名都不等于独立事件、独立核实或交易价值。短原文不自动低质；长RSS不升级成原文。异标题改写转载可能仍未识别。行业统计、财报及技术行情在各自材料另行核对；本检查不据缺失项一票否决分析。')


def prompt(data):
    return '\n'.join(['## 实际入模资料覆盖检查（不是投资价值评分）',data['limitation'],
        '先判断哪些资料支持改变判断，哪些只是转载或背景；不要把记录数量当证据强度。摘要只能支持其实际出现的主张，缺失的上下文不能自行补齐。',
        '正文允许先提出有依据的假设，不必等所有验证完成；说明最强反证和判断期限。没有公司原文不妨碍有据的技术分析或行业推演，但不能假装取得公司订单或成本。',
        json.dumps({key:data[key] for key in ('reading_scopes','title_only_articles','short_originals','duplicate_text_groups','selected_topics','per_stock')},
                   ensure_ascii=False,separators=(',',':'))])
