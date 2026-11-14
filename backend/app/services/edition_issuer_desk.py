"""Direct issuer catalogue + business baseline, shared with the edition ledger.

Only exact, fixed provider endpoints are allowed. Metadata comes before an
announcement body. Provider mirrors never become exchange-original evidence.
"""
from datetime import datetime, timedelta
import hashlib
import json
import re
import time
from types import SimpleNamespace

import requests

from .research_hub import ResearchHub, Material, DATA_API, save_json
from .time_context import china_now
from .watchlist_sources import publication_time

LIST_URL = 'https://np-anotice-stock.eastmoney.com/api/security/ann'
BODY_URL = 'https://np-cnotice-stock.eastmoney.com/api/content/ann'
PROFILE_URL = 'https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax'
MAX_BYTES = 2 * 1024 * 1024
PROTOCOL = 'listener_research_v1'


def company_job(job, stocks):
    """Only an initial A-share company job, not arbitrary follow-up keywords."""
    return next((s for s in stocks if s['market'] == 'A'
        and job.get('lane') == 'company_event' and job.get('scope') == 'A:' + s['code']), None)


class IssuerDesk:
    def __init__(self, state, workspace, save, deadline, request_get=None):
        self.state, self.workspace, self.save, self.deadline = state, workspace, save, deadline
        self.get = request_get or requests.get
        self.folder = workspace.path / 'issuer-responses'
        self.stocks = {s['code']: s for s in state['watchlist'] if s['market'] == 'A'}

    def request(self, url, params, *, response_kind='json', deadline=None, request_tag=None):
        from .edition_market import allowed_endpoint, COUNT
        market = allowed_endpoint(url)
        if (url not in {LIST_URL, BODY_URL, PROFILE_URL, DATA_API} and not market
                or response_kind not in {'json', 'gbk'} or response_kind == 'gbk' and not market
                or request_tag is not None and (url != COUNT or request_tag != 'breadth-final-count')):
            raise ValueError('edition_issuer_endpoint_invalid')
        key = hashlib.sha256(json.dumps([url, params], sort_keys=True).encode()).hexdigest()
        if response_kind != 'json':
            key = hashlib.sha256((key + ':' + response_kind).encode()).hexdigest()
        if request_tag:
            key = hashlib.sha256((key + ':' + request_tag).encode()).hexdigest()
        receipts = self.state.setdefault('issuer_http_receipts', [])
        previous = next((r for r in receipts if r['key'] == key), None)
        if previous:
            if previous.get('status') != 'received':
                raise ValueError('edition_issuer_failed_request_not_retried')
            capture = self.folder / (key + '.json')
            if previous.get('capture') != capture.name or capture.is_symlink():
                raise ValueError('edition_issuer_capture_invalid')
            raw = capture.read_bytes()
            if hashlib.sha256(raw).hexdigest() != previous['sha256']:
                raise ValueError('edition_issuer_capture_changed')
            return raw.decode('gbk') if response_kind == 'gbk' else json.loads(raw)
        if url in self.state.get('issuer_endpoint_gaps', {}):
            raise ValueError('edition_issuer_endpoint_unavailable_this_run')
        deadline = min(self.deadline, deadline) if deadline is not None else self.deadline
        remaining = deadline - time.monotonic()
        if remaining <= 0 or getattr(self.workspace, 'public_fetch_attempts', 0) >= self.state['policy']['max_body_urls'] * 3:
            raise ValueError('edition_public_http_budget_exhausted')
        from .source_health import ensure_active, record_failure
        root = ResearchHub().root
        route = 'edition-issuer:' + key
        ensure_active(root, route)
        receipt = dict(key=key, url=url, parameters=params, status='started')
        receipts.append(receipt)
        self.workspace.public_fetch_attempts = getattr(self.workspace, 'public_fetch_attempts', 0) + 1
        self.state['public_fetch_attempts'] = self.workspace.public_fetch_attempts
        self.save()  # A failed connection still consumes the public request.
        response = None
        try:
            response = self.get(url, params=params, timeout=min(8, remaining),
                headers={'User-Agent': 'Mozilla/5.0'}, allow_redirects=False, stream=True)
            receipt['http_status'] = response.status_code
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError('edition_issuer_redirect_not_followed')
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > MAX_BYTES or time.monotonic() >= deadline:
                    raise ValueError('edition_issuer_response_limit')
                chunks.append(chunk)
            raw = b''.join(chunks)
            data = raw.decode('gbk') if response_kind == 'gbk' else json.loads(raw)
            if not isinstance(data, dict) and not market:
                raise ValueError('edition_issuer_structure_invalid')
            self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            name = key + '.json'
            with (self.folder / name).open('xb') as stream:
                stream.write(raw)
            (self.folder / name).chmod(0o600)
            receipt.update(status='received', capture=name, sha256=hashlib.sha256(raw).hexdigest(),
                observed_at=datetime.now().astimezone().isoformat())
            return data
        except Exception as error:
            receipt.update(status='failed', error_type=type(error).__name__)
            if (getattr(response, 'status_code', None) in {401, 403}
                    or isinstance(error, (requests.Timeout, requests.ConnectionError))):
                self.state.setdefault('issuer_endpoint_gaps', {})[url] = dict(
                    reason='endpoint_failed_this_run_no_repeated_company_requests',
                    http_status=getattr(response, 'status_code', None), error_type=type(error).__name__)
            record_failure(root, route, error)
            raise
        finally:
            if response is not None:
                response.close()
            self.save()

    def catalogue(self, stock):
        code = stock['code']
        if code not in self.stocks or not re.fullmatch(r'\d{6}', code):
            raise ValueError('edition_issuer_company_invalid')
        from .collection_time import window
        now = self.workspace.now
        hours = window(now, 'company_event')['hours']
        data = self.request(LIST_URL, dict(sr=-1, page_size=20, page_index=1,
            ann_type='A', client_source='web', stock_list=code))
        listing = (data.get('data') or {}).get('list')
        if not isinstance(listing, list):
            raise ValueError('edition_issuer_catalogue_invalid')
        rows = []
        for item in listing:
            published = publication_time(item.get('display_time'))
            art = str(item.get('art_code') or '')
            if (not any(str(c.get('stock_code')) == code for c in item.get('codes', []))
                    or not re.fullmatch(r'AN\d+', art) or published is None
                    or not now - timedelta(hours=hours) <= published <= now):
                continue
            title = str(item.get('title') or '公告')
            if code not in title and stock['name'] not in title:
                title = stock['name'] + '：' + title
            rows.append(dict(title=title,
                url=f'https://data.eastmoney.com/notices/detail/{code}/{art}.html',
                snippet='公司披露目录，尚未读取正文；公告文件日期：' + str(item.get('notice_date') or '未提供'),
                published_hint=published.isoformat(), source='东方财富上市公司披露镜像',
                issuer_document=dict(code=code, art_code=art, published_at=published.isoformat()),
                source_identity='provider_mirror_not_exchange_original'))
        return dict(status='ok', results=rows, catalogue_size=len(listing),
            recent_results=len(rows), complete_history=False,
            limitation='只核最近20条披露目录；空目录不等于公司没有事件。未读取公告正文，不是交易所原件核验。')

    def periodic_cache(self, key, fetch, disclosures=()):
        """Reuse cross-edition baselines; new disclosures invalidate by identity.

        Weekly financial checking is a fallback, not daily reanalysis. Business
        classification is refreshed monthly or after a relevant business notice.
        The original collection time survives reuse.
        """
        kind, scope = key.split(':', 1)
        if kind not in {'profile', 'financial'} or scope not in {'A:' + code for code in self.stocks}:
            raise ValueError('edition_baseline_cache_identity_invalid')
        root = getattr(self, 'baseline_root', ResearchHub().root / 'edition-baselines-v1')
        path = root / (hashlib.sha256(key.encode()).hexdigest() + '.json')
        pattern = (r'季度报告|年度报告|半年度报告|财务报表|业绩快报|业绩预告|审计报告|财务.*更正|更正.*财务|报告.*修订'
            if kind == 'financial' else r'主营业务.*变更|重大资产重组|重大资产[购出买卖]|收购|并购|吸收合并')
        relevant = sorted({r['issuer_document']['art_code'] for r in disclosures
            if r.get('issuer_document', {}).get('code') == scope.split(':')[1]
            and re.search(pattern, r.get('title', ''))})
        ttl = timedelta(days=7 if kind == 'financial' else 30)
        def checksum(value):
            return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        old, stamp = None, None
        if path.is_symlink():
            raise ValueError('edition_baseline_cache_symlink')
        try:
            if path.stat().st_size > MAX_BYTES * 3:
                raise ValueError('edition_baseline_cache_too_large')
            saved = json.loads(path.read_text())
            stamp = datetime.fromisoformat(saved['collected_at'])
            if (saved.get('owner') != 'edition-periodic-baseline-v1' or saved.get('key') != key
                    or saved.get('value_sha256') != checksum(saved['value'])
                    or stamp > self.workspace.now):
                raise ValueError('edition_baseline_cache_invalid')
            old = saved
        except (OSError, ValueError, TypeError, KeyError):
            pass
        refresh = ('first_collection' if old is None else
            'new_relevant_disclosure' if set(relevant) - set(old.get('disclosures', [])) else
            'periodic_check_due' if self.workspace.now - stamp >= ttl else None)
        if refresh is None:
            value = old['value']; observed = old['collected_at']; status = 'reused'
        else:
            value = fetch()
            # Invalid provider structures must not become a valid baseline.
            if kind == 'financial' and (not isinstance(value, dict)
                    or not isinstance(value.get('result'), dict)
                    or not isinstance(value['result'].get('data'), list)):
                raise ValueError('edition_baseline_financial_structure_invalid')
            observed = china_now().isoformat()
            status = 'checked_unchanged' if old and old['value_sha256'] == checksum(value) else 'refreshed'
            save_json(path, dict(owner='edition-periodic-baseline-v1', key=key,
                collected_at=observed, value_sha256=checksum(value), value=value, disclosures=relevant))
        row = dict(key=key, status=status, refresh_reason=refresh,
            collected_at=observed, value_sha256=checksum(value),
            fallback_check_days=ttl.days, triggered_disclosures=relevant,
            limitation='复用旧基线不代表今日重发业绩；检查后未变不等于公告或财报已经独立核实。')
        self.state.setdefault('baseline_cache_receipts', []).append(row)
        self._baseline_observed = getattr(self, '_baseline_observed', {})
        self._baseline_observed[kind] = observed
        # Include the exact cached supplier value in this edition's export too.
        save_json(self.workspace.path / 'baseline-captures' / (hashlib.sha256(key.encode()).hexdigest() + '.json'),
            dict(**row, value=value))
        self.save()
        return value

    def baseline(self, stock, *, disclosures=()):
        """Reuse business/metric adapters through the same counted transport.

        The small structured baseline is separate from current news. Missing
        announcement dates cannot silently turn a financial row into evidence.
        """
        obj = SimpleNamespace(**stock)
        hub = ResearchHub(self.workspace.path / 'issuer-baseline')
        hub.cache = lambda key, ttl, fetch: self.periodic_cache(key, fetch, disclosures)
        hub.get_json = lambda url, params, deadline: self.request(url, params)
        result = dict(key='A:' + stock['code'], name=stock['name'], profile=None,
            gaps=[])
        try:
            profile = hub.profile(obj, self.deadline)
            profile['collected_at'] = self._baseline_observed['profile']
            result['profile'] = {k: profile[k] for k in
                ('company', 'industry', 'families', 'fields', 'topics', 'source', 'source_url', 'collected_at')}
            result['profile']['usage'] = '供应商业务归类，用于提出经营问题；不是最新事件或已核实上下游关系。'
        except Exception as error:
            result['gaps'].append(dict(kind='business_profile', error_type=type(error).__name__))
        candidates = []
        try:
            items = [item for item in hub.financial(obj, self.deadline)
                     if item.published_at is not None and item.published_at <= self.workspace.now]
            for item in items:
                item.collected_at = self._baseline_observed['financial']
            if not items:
                result['gaps'].append(dict(kind='financial_baseline_or_publication_unavailable'))
            else:
                first = items[0]
                text = '\n\n'.join(item.title + '\n' + item.body for item in items)
                identifier = hashlib.sha256(('baseline:' + first.scope + ':' + text).encode()).hexdigest()[:24]
                item = Material(identifier, first.title + ('及去年同期' if len(items) > 1 else ''),
                    first.source, first.source_url, first.kind, first.scope, text,
                    max(item.published_at for item in items), first.collected_at,
                    '；'.join(item.period for item in items), first.reading_status)
                self.workspace.add([item])
                if item.id in self.workspace.documents:
                    candidates.append(dict(title=item.title, url=item.source_url,
                        snippet='财务基线，统计期间：' + item.period + '；结构化指标尚未与原始财报核对，不是今日催化。',
                        published_hint=item.published_at.isoformat(), source=item.source,
                        baseline_document=item.id, background_only=True, scope=item.scope))
        except Exception as error:
            result['gaps'].append(dict(kind='financial_baseline', error_type=type(error).__name__))
        return result, candidates

    def read(self, candidate):
        if candidate.get('baseline_document'):
            identifier = candidate['baseline_document']
            item = self.workspace.documents.get(identifier)
            if (item is None or not isinstance(item, Material) or item.kind != 'financial_baseline'
                    or item.scope != candidate.get('scope')):
                raise ValueError('edition_issuer_baseline_invalid')
            return dict(status='ok', material=dict(id=identifier), http_requests_performed=0)
        document = candidate.get('issuer_document') or {}
        code, art = document.get('code'), document.get('art_code')
        if code not in self.stocks or not re.fullmatch(r'AN\d+', str(art or '')):
            raise ValueError('edition_issuer_document_invalid')
        pages, total = [], 1
        for page in (1, 2):
            data = self.request(BODY_URL, dict(art_code=art, client_source='web', page_index=page))
            detail = data.get('data') or {}
            text = detail.get('notice_content')
            count = detail.get('page_size')
            if (detail.get('art_code') != art or str(count) not in {'1', '2'}
                    or not isinstance(text, str) or len(text.strip()) < 40):
                raise ValueError('edition_issuer_full_document_unavailable')
            if pages and int(count) != total:
                raise ValueError('edition_issuer_page_count_changed')
            total = int(count)
            pages.append(text.strip())
            if page == total:
                break
        if len(pages) != total or len(set(pages)) != total:
            raise ValueError('edition_issuer_pages_incomplete')
        identifier = hashlib.sha256(('issuer:' + code + ':' + art).encode()).hexdigest()[:24]
        item = Material(identifier, candidate['title'], '东方财富上市公司披露镜像', candidate['url'],
            'primary_notice', 'A:' + code, '\n'.join(pages),
            datetime.fromisoformat(document['published_at']), datetime.now().astimezone().isoformat(),
            reading_status='完整供应商文本分页；未与交易所原始PDF独立核验')
        self.workspace.add([item])
        if identifier not in self.workspace.documents:
            raise ValueError('edition_issuer_body_not_admitted')
        return dict(status='ok', material=dict(id=identifier))
