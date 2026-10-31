"""Offline acceptance of captured public responses, never a network fallback.

Consumes capture_public_response's existing metadata contract. All publication
and access admission remains with the production parser. Reports contain private
article text and belong inside the original, expiring episode directory.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_METADATA_BYTES = 64 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
CHINA = timezone(timedelta(hours=8))


def local_time(value):
    if not isinstance(value, str) or not re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}', value):
        raise ValueError('capture_clock_invalid')
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('capture_clock_invalid') from None
    # Existing capture metadata uses naive Beijing clocks. Never change them
    # to the cloud host's local timezone.
    return stamp.astimezone(CHINA).replace(tzinfo=None) if stamp.tzinfo else stamp


def capture_file(root, name):
    """Only a direct, regular child; do not follow a capture's path or symlink."""
    if not isinstance(name, str) or not name or name in {'.', '..'} or '/' in name or '\\' in name:
        raise ValueError('capture_file_path_invalid')
    target = root / name
    if target.is_symlink() or not target.is_file():
        raise ValueError('capture_file_missing_or_symlink')
    return target


def check_directory(path):
    path = Path(path).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)) or not path.is_dir():
        raise ValueError('capture_directory_missing_or_symlink')
    return path


def validate_metadata(meta):
    if not isinstance(meta, dict):
        raise ValueError('capture_metadata_invalid')
    url = meta.get('url')
    if not isinstance(url, str) or len(url) > 2048:
        raise ValueError('capture_url_invalid')
    parts = urlsplit(url)
    if parts.scheme not in {'http', 'https'} or not parts.hostname or parts.username or parts.password:
        raise ValueError('capture_url_invalid')
    if type(meta.get('http_status')) is not int or meta['http_status'] != 200:
        raise ValueError('capture_http_not_ok')
    if 'html' not in str(meta.get('content_type', '')).lower():
        raise ValueError('capture_not_html')
    if type(meta.get('bytes')) is not int or not 0 < meta['bytes'] <= MAX_BODY_BYTES:
        raise ValueError('capture_size_invalid')
    if not isinstance(meta.get('body_sha256'), str) or not re.fullmatch(r'[0-9a-f]{64}', meta['body_sha256']):
        raise ValueError('capture_digest_invalid')
    cutoff = local_time(meta.get('snapshot_cutoff'))
    observed = local_time(meta.get('observed_at'))
    return cutoff, observed


def replay(folder, hours=72, max_total_bytes=MAX_TOTAL_BYTES):
    """Replay every capture within an explicit byte budget, with no HTTP client.

    Counts describe response/parser states, not independent events, coverage,
    importance, factual truth or an authorization to start a paid trial.
    """
    from .generic_extraction import reader_kind, runtime_status
    from .web_research import parse_visible_article, failure_reason
    from .news_quality import reading_scope, excluded_reason
    from .evidence import publication_label

    if type(hours) is not int or not 1 <= hours <= 168:
        raise ValueError('capture_window_invalid')
    if type(max_total_bytes) is not int or not 1 <= max_total_bytes <= MAX_TOTAL_BYTES:
        raise ValueError('capture_total_budget_invalid')
    folder = check_directory(folder)
    rows, identities = [], {}
    consumed = 0
    for metadata in sorted(folder.glob('*.json')):
        row = dict(capture=metadata.name, status='rejected')
        try:
            metadata = capture_file(folder, metadata.name)
            size = metadata.stat().st_size
            if size > MAX_METADATA_BYTES:
                raise ValueError('capture_metadata_too_large')
            if consumed + size > max_total_bytes:
                row.update(status='not_attempted', reason='capture_total_byte_budget')
                rows.append(row)
                continue
            with metadata.open('rb') as stream:
                raw_metadata = stream.read(MAX_METADATA_BYTES + 1)
            consumed += len(raw_metadata)
            if len(raw_metadata) != size:
                raise ValueError('capture_metadata_changed')
            meta = json.loads(raw_metadata)
            cutoff, observed = validate_metadata(meta)
            raw_file = capture_file(folder, meta.get('file'))
            size = raw_file.stat().st_size
            if size != meta['bytes'] or size > MAX_BODY_BYTES:
                raise ValueError('capture_size_mismatch')
            if consumed + size > max_total_bytes:
                row.update(status='not_attempted', reason='capture_total_byte_budget')
                rows.append(row)
                continue
            consumed += size
            # Bounded read also detects replacement/growth after stat.
            with raw_file.open('rb') as stream:
                raw = stream.read(MAX_BODY_BYTES + 1)
            if len(raw) != meta['bytes'] or hashlib.sha256(raw).hexdigest() != meta['body_sha256']:
                raise ValueError('capture_integrity_mismatch')
            row.update(url=meta['url'], body_sha256=meta['body_sha256'],
                       snapshot_cutoff=meta['snapshot_cutoff'], observed_at=meta['observed_at'],
                       integrity='matched', remote_version_checked=False,
                       observed_after_cutoff=observed > cutoff,
                       available_at_cutoff_verified=False,
                       reader_kind=reader_kind(meta['url']))
            identity = (meta['url'], meta['body_sha256'], cutoff.isoformat())
            if identity in identities:
                row.update(status='duplicate_capture', duplicate_of=identities[identity])
            elif row['reader_kind'] != 'article_candidate':
                row.update(status='specialized_reader_required', reason='web_source_specialized_reader_required')
            else:
                item = parse_visible_article(raw, meta['url'], now=cutoff, hours=hours)
                reason = excluded_reason(item)
                if reason:
                    row.update(reason=reason)
                else:
                    row.update(status='parser_admitted_pending_human_review',
                               title=item.title, source=item.source, published=publication_label(item),
                               reading_scope=reading_scope(item), characters=len(item.content),
                               text_sha256=hashlib.sha256(item.content.encode('utf-8')).hexdigest(),
                               text=item.content, complete_document_verified=False,
                               fact_verified=False)
            identities.setdefault(identity, metadata.name)
        except Exception as error:
            code = str(error)
            row.update(reason=code if re.fullmatch(r'capture_[a-z_]+', code) else failure_reason(error),
                       error_type=type(error).__name__)
        rows.append(row)
    counts = dict(Counter(row['status'] for row in rows))
    return dict(schema='finance-reading-acceptance-v1',
                status='no_captures' if not rows else 'offline_replay_completed',
                extractor=runtime_status(), window_hours=hours,
                bytes_read=consumed, max_total_bytes=max_total_bytes,
                counts=counts, reasons=dict(Counter(row['reason'] for row in rows if row.get('reason'))),
                rows=rows, http_requests=0, model_requests=0, search_requests=0, tts_requests=0,
                automation_changed=False, app_database_changed=False,
                paid_trial_authorized=False, content_accepted=False,
                limitation='仅回放已存响应；准入计数不是独立事件数、重要性或事实验证。保留原观察/截止时间，不刷新资料；截止后取得的页面不能证明截止时已可见。需要人工核对全文、日期、反方、价值及新鲜服务器网络。')


def render_review(result):
    lines = ['# 正文读取离线验收', '', result['limitation'], '',
             'HTTP / 模型 / 搜索 / TTS 请求：均为 0。自动化及 App 数据库未改变。', '',
             '状态：' + result['status'], '',
             '解析状态计数：`' + json.dumps(result['counts'], ensure_ascii=False) + '`', '',
             '以下保留全部提取文字，供人工检查，不代表模型已读取或成品已通过。', '']
    for index, row in enumerate(result['rows'], 1):
        lines.extend([f"## {index}. {row.get('title', row['capture'])}", '',
                      '状态：' + row['status'], '',
                      '来源：' + row.get('url', '元数据未通过校验'), '',
                      '说明：' + row.get('reason', row.get('published', '')), ''])
        if row.get('observed_after_cutoff'):
            lines.extend(['注意：原始响应取得于本期截止之后，不是截止时可见性证明。', ''])
        if row.get('text'):
            # Quote source text so article markup cannot become review headings.
            lines.extend('> ' + line for line in row['text'].splitlines())
            lines.append('')
    return '\n'.join(lines) + '\n'
