"""Local acquisition decisions and receipts, separate from evidence assessment."""
from collections import Counter
from urllib.parse import urlsplit
import re


def host(url):
    return (urlsplit(url or '').hostname or '').lower()


def read_target(url):
    """Unwrap only RTHK's explicit own-site language proxy, never arbitrary URLs."""
    parts = urlsplit(url)
    prefix = '/TuniS/news.rthk.hk/'
    if (parts.scheme == 'https' and parts.hostname == 'gbcode.rthk.hk'
            and parts.port is None and not parts.username and not parts.password
            and parts.path.startswith(prefix)):
        return 'https://news.rthk.hk/' + parts.path[len(prefix):] + (
            '?' + parts.query if parts.query else '')
    return url


def failure_class(reason):
    value = str(reason or '')
    if value == 'article_paused_no_auto_retest': return 'paused'
    if re.search(r'timeout|connection|tls|ssl|dns|gaierror|NewConnectionError|MaxRetryError', value, re.I):
        return 'network'
    if value in {'public_http_401','public_http_403','http_401','http_403',
                 'web_source_access_restricted'}: return 'access'
    if value in {'public_http_404','public_http_410','http_404','http_410'}: return 'missing_url'
    if value in {'published_hint_outside_event_window','web_source_time_outside_window',
                 'web_source_day_window_boundary_requires_review'}: return 'time_window'
    if value.startswith('body_quality') or value == 'web_source_disclosed_ai_generated_article': return 'quality'
    if value.startswith('web_source_'): return 'parse_or_identity'
    return 'other'


def availability_penalty(state, url):
    """Prefer another host after observed failures; never ban a whole publisher."""
    target = host(read_target(url))
    for source in state.get('sources', {}).values():
        if host(read_target(source.get('url'))) == target:
            return 0  # This episode has a usable body, not a permanent endorsement.
    return int(any(host(read_target(state.get('candidates', {}).get(
        row.get('candidate_id'), {}).get('url'))) == target
        and failure_class(row.get('reason')) in {'network', 'access'}
        for row in state.get('read_receipts', [])))


def paused_public(url):
    """Inspect exact existing stop records only; never expire or clear them."""
    from .source_health import PAUSED_PUBLIC_ARTICLES, ensure_active, RetiredSourceError
    from .research_hub import ResearchHub
    for target in dict.fromkeys([url, read_target(url)]):
        if target in PAUSED_PUBLIC_ARTICLES: return True
        try: ensure_active(ResearchHub().root, 'research-public-url:' + target.split('#', 1)[0])
        except RetiredSourceError: return True
    return False


def summary(state):
    receipts = state.get('read_receipts', [])
    sources = state.get('sources', {})
    rows = []
    for row in receipts:
        cid = row.get('candidate_id')
        candidate = state.get('candidates', {}).get(cid, {})
        stored = [s for s in sources.values() if s.get('candidate_id') == cid
                  or s.get('url') == candidate.get('url')]
        rows.append(dict(candidate_id=cid, event_id=row.get('event_id'),
            title=candidate.get('title'), url=candidate.get('url'),
            read_url=row.get('read_url') or candidate.get('url'),
            status='stored_pending_assessment' if stored else row.get('status'),
            reason=row.get('reason'), failure_class=None if stored else failure_class(row.get('reason')),
            public_http_requests=row.get('public_http_requests'),
            stored_source_ids=[s['id'] for s in stored],
            body_characters=sum(len(s.get('text', '')) for s in stored)))
    skipped = state.get('read_metadata_rejections', [])
    # Only count delivered article evidence if it is actually in the accepted
    # assessment. Parsed/stored text is not automatically useful evidence.
    assessment = state.get('assessment') or {}
    accepted = {e.get('source_id') for r in assessment.get('events', []) + assessment.get('watchlist_checks', [])
                if r.get('status') in {'ready', 'covered'} for e in r.get('evidence', [])}
    linked = {sid for r in rows for sid in r['stored_source_ids']}
    counters_known = all(type(r['public_http_requests']) is int for r in rows)
    return dict(owner='finance-body-acquisition-v1', attempted_urls=len(rows),
        metadata_skipped=len(skipped), stored_article_bodies=len(linked),
        assessment_cited_bodies=len(linked & accepted),
        article_http_requests=sum(r['public_http_requests'] for r in rows) if counters_known else None,
        failure_counts=dict(Counter(r['failure_class'] for r in rows if not r['stored_source_ids'])),
        rows=rows, skips=skipped,
        limitation='已存正文、评估引用和最终事实正确是不同层次；旧回执缺HTTP计数时不猜测。请求数不含搜索/行情，评估引用仍待审稿和人工内容验收。')


def receipt_lines(state):
    result = summary(state)
    labels = dict(network='连接或超时', access='访问受限', missing_url='链接失效',
        paused='已停用且未重试', time_window='不在本次时窗', quality='正文质量不合格',
        parse_or_identity='正文结构、时间或身份未通过', other='其他未完成')
    lines = ['', '从标题到正文的实际转化：',
        '尝试链接=' + str(result['attempted_urls']) + '；读取前拦截=' + str(result['metadata_skipped'])
        + '；已存文章正文=' + str(result['stored_article_bodies']) + '；被评估引用=' + str(result['assessment_cited_bodies']),
        '文章公开HTTP请求=' + (str(result['article_http_requests']) if result['article_http_requests'] is not None else '旧回执未完整记录')]
    for row in result['rows']:
        lines += ['- ' + str(row['title'] or row['candidate_id']) + '：' + (
            '已存正文，仍须评估和审稿' if row['stored_source_ids'] else labels[row['failure_class']])
            + '；' + str(row['reason'] or ''), '  ' + str(row['url'])]
    for row in result['skips']:
        candidate = state.get('candidates', {}).get(row['candidate_id'], {})
        flags = dict(spam_or_adult_promotion_metadata='推广或色情垃圾线索',
            directory_or_quote_page_not_article='公司目录或行情页，非报道',
            generated_document_app_not_original_news='生成文档页，非原始新闻',
            attachment_or_chart_not_article='截图或图表，非文章',
            published_hint_outside_event_window='搜索给出的日期已明显超窗',
            article_paused_no_auto_retest='这个链接已有停用记录，不重试',
            baseline_requires_event_question='背景资料缺具体研究问题')
        lines.append('- 未联网跳过 ' + str(candidate.get('title') or row['candidate_id'])
            + '：' + '、'.join(flags.get(f, f) for f in row['flags']))
    return lines
