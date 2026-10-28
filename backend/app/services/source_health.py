"""Durable negative results. Never auto-probe a retired adapter to see if it recovered."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import requests

from .time_context import china_now

# A timeout proves this observed route failed, not that the publisher is gone.
# These routes are nevertheless paused under the user's no-repeat instruction.
PAUSED_FEEDS={name:'paused_after_observed_failure_no_automatic_retest' for name in
    ('东方财富研报','格隆汇港股','金十数据')}
PAUSED_DAILY={'sh512660','sh515700'}
DAILY_STRUCTURE_FAILURES=frozenset({'kline_identity_missing','completed_daily_or_adjusted_series_missing',
    'kline_quote_identity_missing','kline_dates_invalid','kline_ohlcv_invalid','kline_response_invalid'})
PAUSED_PUBLIC_ARTICLES={
    'https://www.eeo.com.cn/2026/1027/1076099.shtml':'publisher_source_date_missing',
    'https://news.smm.cn/news/104181722':'publisher_full_body_unavailable',
    'https://news.smm.cn/news/104181778':'publisher_full_body_unavailable',
}
# Reviewed public probe failures travel with the release. Runtime failures still
# live in the private, persistent exact-key ledger; neither expires into a retry.
_public_failures=Path(__file__).resolve().parents[2]/'public_source_failures.json'
if _public_failures.exists():
    PAUSED_PUBLIC_ARTICLES.update(json.loads(_public_failures.read_text(encoding='utf-8')))


class RetiredSourceError(ValueError):pass


def state_path(root,key):
    return Path(root)/'blocked'/(hashlib.sha256(key.encode()).hexdigest()+'.json')


def ensure_active(root,key):
    path=state_path(root,key)
    if path.exists():
        # Never expose a provider response or secrets in exception text.
        raise RetiredSourceError('source_paused_no_automatic_retest')


def permanent_reason(error):
    if isinstance(error,ValueError) and str(error) in DAILY_STRUCTURE_FAILURES:return str(error)
    response=getattr(error,'response',None)
    status=getattr(response,'status_code',None)
    if status in {400,401,403,404,405,410}:return 'http_'+str(status)
    if isinstance(error,requests.exceptions.SSLError):return 'tls_verification_failed'
    # Article-specific admission failures, not a ban on the entire publisher.
    if str(error) in {'media_identity_or_access_rejected','media_access_unknown','media_full_body_unavailable',
        'media_publication_missing','media_article_structure_missing',
        'publisher_identity_or_free_access_rejected','publisher_paid_access_rejected',
        'publisher_full_body_unavailable','publisher_restricted_content','publisher_source_date_missing',
        'publisher_public_page_state_missing','legacy_negative_result_requires_review',
        'overseas_full_body_unavailable','overseas_restricted_content','overseas_source_time_missing',
        'overseas_source_timezone_missing','minute_identity_missing','minute_quote_identity_missing',
        'minute_shape_invalid','minute_sequence_invalid','minute_values_invalid','minute_response_invalid',
        'breadth_catalog_shape_invalid','breadth_catalog_identity_invalid','breadth_response_invalid'}:return str(error)
    return None


def record_failure(root,key,error):
    reason=permanent_reason(error)
    if reason is None:return False
    from .research_hub import save_json
    save_json(state_path(root,key),dict(status='paused',at=china_now().isoformat(),reason=reason,
        automatic_retest=False,scope='exact_adapter_or_article_key',
        resume='Only explicitly revalidate after a URL/parser/config change; no expiry probe'))
    return True
