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

from .research_hub import ResearchHub, Material, DATA_API
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

    def request(self, url, params):
        if url not in {LIST_URL, BODY_URL, PROFILE_URL, DATA_API}:
            raise ValueError('edition_issuer_endpoint_invalid')
        key = hashlib.sha256(json.dumps([url, params], sort_keys=True).encode()).hexdigest()
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
            return json.loads(raw)
        if url in self.state.get('issuer_endpoint_gaps', {}):
            raise ValueError('edition_issuer_endpoint_unavailable_this_run')
        remaining = self.deadline - time.monotonic()
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
                if size > MAX_BYTES or time.monotonic() >= self.deadline:
                    raise ValueError('edition_issuer_response_limit')
                chunks.append(chunk)
            raw = b''.join(chunks)
            data = json.loads(raw)
            if not isinstance(data, dict):
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

    def baseline(self, stock):
        """Reuse business/metric adapters through the same counted transport.

        The small structured baseline is separate from current news. Missing
        announcement dates cannot silently turn a financial row into evidence.
        """
        obj = SimpleNamespace(**stock)
        hub = ResearchHub(self.workspace.path / 'issuer-baseline')
        hub.cache = lambda key, ttl, fetch: fetch()
        hub.get_json = lambda url, params, deadline: self.request(url, params)
        result = dict(key='A:' + stock['code'], name=stock['name'], profile=None,
            gaps=[])
        try:
            profile = hub.profile(obj, self.deadline)
            result['profile'] = {k: profile[k] for k in
                ('company', 'industry', 'families', 'fields', 'topics', 'source', 'source_url', 'collected_at')}
            result['profile']['usage'] = '供应商业务归类，用于提出经营问题；不是最新事件或已核实上下游关系。'
        except Exception as error:
            result['gaps'].append(dict(kind='business_profile', error_type=type(error).__name__))
        candidates = []
        try:
            items = [item for item in hub.financial(obj, self.deadline)
                     if item.published_at is not None and item.published_at <= self.workspace.now]
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
