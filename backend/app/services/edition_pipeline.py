"""Single production edition path. No maintenance override, paid retry or fallback."""
import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta
import fcntl
import json
import os
from pathlib import Path
import re
import time
import uuid

from ..config import settings
from . import edition_contract as contract
from .edition_context import packet, editorial_source_ids
from .edition_issuer_desk import IssuerDesk, PROTOCOL, company_job
from .listener_research import validate_draft as validate_listener_draft, validate_review as validate_listener_review
from .edition_read_selection import primary_plan, patch_plan, fallback_plan, validate_increment
from .edition_budget import Budget, OUTPUTS, digest, policy, protection, accounted, request_input_pricing, search_batch_plan
from .edition_inputs import messages_for, editorial_forecast, edition_forecast
from .episode_workspace import EpisodeWorkspace, body
from .model_gateway import MODEL_PAUSE_FILE, complete, ensure_models_enabled, resolve_route, request_for
from .research_hub import save_json
from .search_primary_collection import search_agenda
from .time_context import china_now
from .watchlist_repository import read_app_watchlist, watchlist_signature, assert_watchlist_current

ROOT = Path(__file__).resolve().parents[2] / 'data/editions'


def source_signature():
    # Bind acceptance to the whole application, including entry points and
    # indirect readers, rather than a hand-maintained list that can omit changes.
    root = Path(__file__).parent.parent
    files = sorted(root.rglob('*.py'))
    if any(p.is_symlink() for p in files):
        raise ValueError('edition_source_symlink')
    return digest({p.relative_to(root).as_posix(): digest(p.read_text()) for p in files})


def initial_searches(stocks, now, *, direct_issuers=False, daily_changes=False, baselines=None):
    jobs = search_agenda(stocks, now)
    jobs += [dict(lane='global_policy', purpose='discovery',
                  query=now.strftime('%Y-%m-%d') + ' major world political economic breaking developments financial markets'),
             dict(lane='global_policy', purpose='discovery',
                  query=now.strftime('%Y年%m月%d日') + ' 国内 国际 重大事件 最新进展 金融市场')]
    for job in jobs:
        if job['lane'] == 'us_market':
            job['query'] = now.strftime('%Y-%m-%d') + ' US stocks latest completed session closing market report'
    if direct_issuers:
        for job in jobs:
            if company_job(job, stocks):
                job['retrieval'] = 'issuer_catalogue'
    if daily_changes:
        from .daily_changes import decorate_jobs, targeted_jobs
        jobs = decorate_jobs(jobs, now, baselines) + targeted_jobs(stocks, now, baselines)
    return jobs


@contextmanager
def edition_lock(root):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(root / '.lock', os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('edition_already_running') from None
        yield
    finally:
        os.close(fd)


def run_path(identifier, root=ROOT):
    if not re.fullmatch(r'edition-[0-9a-f]{32}', identifier):
        raise ValueError('edition_id_invalid')
    path = Path(root) / identifier
    if path.is_symlink():
        raise ValueError('edition_path_symlink')
    return path


def environment(stocks, report_type, config=settings):
    routes = {task: resolve_route(task, config=config) for task in ('analysis', 'review')}
    pricing = {task: request_input_pricing(request_for(route,
        [dict(role='user', content='pricing-shape')], 1)[2]) for task, route in routes.items()}
    p = policy(config, routes, request_pricing=pricing)
    key = config.research_web_search_api_key
    private = dict(policy=p, stocks=stocks, report_type=report_type,
        source_signature=source_signature(),
        routes={k: dict(provider=r.provider, model=r.model, base_url=r.base_url,
                       key_digest=digest(r.api_key), effort=r.effort) for k, r in routes.items()},
        search_key_digest=digest(key.get_secret_value() if key else None),
        search_enabled=config.research_web_search_enabled, retries=config.model_http_retries,
        accepted=config.edition_estimate_accepted, nickname=config.user_nickname,
        voice=config.tts_voice, rate=config.tts_rate, volume=config.tts_volume,
        max_seconds=config.research_max_seconds)
    return p, digest(private), {k: dict(provider=r.provider, model=r.model) for k, r in routes.items()}


async def preflight(report_type='morning', config=settings):
    if report_type not in {'morning', 'evening'}:
        raise ValueError('edition_type_invalid')
    stocks = await read_app_watchlist()
    now = china_now()
    blockers = []
    if MODEL_PAUSE_FILE.exists(): blockers.append('maintenance_paused')
    if not config.edition_estimate_accepted: blockers.append('cost_estimate_not_accepted')
    if not config.research_web_search_enabled: blockers.append('production_search_disabled')
    if not config.research_web_search_api_key: blockers.append('search_account_missing')
    if config.model_http_retries: blockers.append('model_retries_must_be_zero')
    if config.report_auto_repair_enabled: blockers.append('auto_repair_must_be_disabled')
    from .generic_extraction import runtime_status
    extractor = runtime_status()
    if not extractor['ready']: blockers.append('body_extractor_unavailable')
    plan = None
    try:
        p, fingerprint, routes = environment(stocks, report_type, config)
        plan = search_batch_plan(p, edition_forecast(dict(cutoff=now.isoformat(),
            watchlist=stocks, report_type=report_type, sources={}, research_protocol=PROTOCOL, change_protocol='daily_changes_v1'), now),
            sum(j.get('retrieval') != 'issuer_catalogue' for j in initial_searches(stocks, now, direct_issuers=True, daily_changes=True)))
        if not plan['fits_money']:
            blockers.append('estimated_limit_below_initial_batch_and_model_plan')
        if not plan['fits_search_count']:
            blockers.append('search_budget_cannot_cover_base_agenda')
    except (ValueError, RuntimeError, KeyError, TypeError) as error:
        p, fingerprint, routes = None, None, None
        blockers.append(str(error) if isinstance(error, ValueError) else 'model_route_or_price_unavailable')
    return dict(owner='finance-unified-edition-v1', mode='free_preflight', report_type=report_type,
        prepared_at=now.isoformat(), watchlist=stocks, policy=p, environment_sha256=fingerprint,
        budget_forecast=plan,
        routes=routes, extractor=extractor, ready_to_run=not blockers, blockers=blockers,
        base_search_jobs=initial_searches(stocks, now, direct_issuers=True, daily_changes=True),
        source_plan=dict(company_disclosures="A股先读公司披露列表，选题后读公告；空目录不代表没有事件",
            company_baseline="首次建立基线；财务遇新披露或每7天核对，业务遇相关变动或每30天核对，平日复用；仅事件需要时比较",
            daily_changes="五类逐项核对；每只自选股另查经营和治理风险，非只查业绩；标题后选一篇读",
            market_structure="先用1次批量请求取得带日期指数；日报不自动遍历全市场，宽度缺口明示，不推断资金意图",
            expectation="有事前可比基线及实际值原文才允许预期差判断；无一致预期接口则留缺口",
            public_http_limit=config.research_body_max_urls * 3, paid_search_fallback="不自动回退；仅一次条件补查按缺口决定"),
        normal_model_requests=4, conditional_extra_requests=1, model_requests=0,
        search_requests=0, public_fetch_attempts=0, tts_requests=0,
        limitation='免费本地预检；价格由配置提供，本地金额为已接受估算，不是服务商硬账单上限。尚未联网或证明覆盖充分。')


class EditionPipeline:
    def __init__(self, state, directory, workspace, *, model=None, search=None, read=None, check=None):
        self.state, self.path, self.workspace = state, Path(directory), workspace
        self.model = model or complete
        from .web_research import search as public_search, read_public
        self.search = search or public_search
        self.read = read or read_public
        self.uses_public_reader = read is None or read is read_public
        self.check = check or self._check_environment
        self.budget = Budget(state, self.save, lambda: (edition_forecast(self.state, self.workspace.now)
            if self.state['policy'].get('edition_forecast') == 'remaining_stages_v1'
            else editorial_forecast(self.state, self.workspace.now)))
        self.started = time.monotonic()
        self.prior_seconds = state.get('active_seconds', 0)
        self.deadline = self.started + settings.research_max_seconds - self.prior_seconds
        self.issuer_desk = (IssuerDesk(state, workspace, self.save, self.deadline)
            if state.get('research_protocol') == PROTOCOL else None)

    def save(self):
        self.state['active_seconds'] = self.prior_seconds + time.monotonic() - self.started
        self.state['updated_at'] = china_now().isoformat()
        from .body_acquisition import summary as acquisition_summary
        self.state['body_acquisition'] = acquisition_summary(self.state)
        save_json(self.path / 'result.json', self.state)
        # A human-readable receipt is updated before/after every stage, even failure.
        lines = [self.state['id'], '状态：' + self.state['status'], '截止：' + self.state['cutoff'],
                 '模型请求预留：' + str(sum(r['kind'] == 'model' for r in self.state.get('reservations', []))),
                 '实际HTTP回执：' + str(len(self.state.get('usage', []))),
                 '搜索HTTP：' + str(self.state.get('search_http_attempts', 0)),
                 '网页HTTP：' + str(self.state.get('public_fetch_attempts', 0)),
                 '语音合成尝试：' + str(len(self.state.get('tts_attempts', []))),
                 '事件缺口：' + json.dumps(self.state.get('missing', []), ensure_ascii=False)]
        from .edition_budget import number
        estimated = sum((number(r['estimated_usd']) for r in self.state.get('reservations', [])), number(0))
        lines.append('已预留估算美元：' + str(estimated) + '；不是实际账单，失败或未知用量不清零')
        lines.append('按完整用量回执更新后的核算美元：' + str(sum(
            (accounted(r) for r in self.state.get('reservations', [])), number(0))) + '；非账户账单，原预留记录保留')
        if self.state.get('budget_forecast'):
            lines.append('后续阶段费用规划：' + json.dumps(self.state['budget_forecast'], ensure_ascii=False))
        if self.state.get('patch_progress'):
            lines.append('补查进展：' + json.dumps(self.state['patch_progress'], ensure_ascii=False))
        for row in self.state.get('read_selection', []):
            selection = {k: v for k, v in row.items() if k not in {'ranked', 'skipped'}}
            selection['selected_articles'] = [dict(id=cid,
                title=self.state['candidates'][cid]['title'], url=self.state['candidates'][cid]['url'])
                for cid in row.get('selected_ids', [])]
            lines.append('文章选择：' + json.dumps(selection, ensure_ascii=False))
        for row in self.state.get('input_audit', []):
            lines.append('阶段输入：' + json.dumps(row, ensure_ascii=False))
        for row in self.state.get('usage', []):
            lines.append('调用回执：' + json.dumps({k: row.get(k) for k in
                ('phase', 'provider', 'model', 'http_status', 'input_tokens', 'output_tokens',
                 'cache_read_tokens', 'cache_write_tokens', 'transport_error')}, ensure_ascii=False))
        for event in self.state.get('agenda', {}).get('events', []):
            lines.append(event['id'] + ' ' + event['importance'] + ' ' + event['title'])
        for source in self.state.get('sources', {}).values():
            lines.append('\n来源：' + source['title'] + '\n' + source['url'] + '\n' + source['text'])
        if self.state.get('company_baselines'):
            lines.append('公司研究基线：' + json.dumps(self.state['company_baselines'], ensure_ascii=False))
        if self.state.get('issuer_catalogue_checks'):
            lines.append('公司披露目录核对：' + json.dumps(self.state['issuer_catalogue_checks'], ensure_ascii=False))
        if self.state.get('draft'):
            if self.state['draft'].get('stock_followups'):
                lines.append('自选股后续观察：' + json.dumps(self.state['draft']['stock_followups'], ensure_ascii=False))
            lines.append('\n文字稿（是否已审以本期状态为准）：\n' + self.state['draft'].get('body', ''))
            lines.append('\n口播稿（未通过联合审阅不得合成）：\n' + self.state['draft'].get('script', ''))
        if self.state.get('review'):
            lines.append('\n联合审阅：\n' + json.dumps(self.state['review'], ensure_ascii=False))
        target = self.path / 'receipt.txt'
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as stream: stream.write('\n'.join(lines))
        from .listener_research import listening_receipt
        fd = os.open(self.path / 'listener-receipt.txt', os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as stream: stream.write(listening_receipt(self.state))

    async def _check_environment(self):
        ensure_models_enabled()
        await assert_watchlist_current(watchlist_signature(self.state['watchlist']))
        _, signature, _ = environment(self.state['watchlist'], self.state['report_type'])
        if signature != self.state['environment_sha256']:
            raise RuntimeError('edition_environment_changed')
        if china_now() > datetime.fromisoformat(self.state['cutoff']) + timedelta(hours=2):
            raise RuntimeError('edition_expired')
        if time.monotonic() >= self.deadline:
            raise RuntimeError('edition_time_exhausted')

    async def call(self, stage, prompt, value):
        await self.check()
        self.state.update(status=stage, phase=stage)
        self.state.setdefault('flow_trace', []).append(stage)
        messages = messages_for(stage, prompt, value, self.workspace.now, self.state['report_type'])
        task = 'review' if stage == 'review' else 'analysis'
        expected = self.state['policy'].get('request_input_pricing', {}).get(task, 'unknown')
        if self.model is complete and expected != 'unknown':
            actual = request_input_pricing(request_for(resolve_route(task), messages, OUTPUTS[stage])[2])
            if actual != expected:
                raise ValueError('edition_request_pricing_changed')
        self.budget.reserve('model', stage=stage, messages=messages, output=OUTPUTS[stage])
        self.state.setdefault('input_audit', []).append(dict(stage=stage,
            data_characters=len(messages[1]['content']),
            total_message_characters=sum(len(m['content']) for m in messages),
            fields=sorted(value), source_ids=sorted(value.get('sources', {})),
            body_characters=sum(len(s['text']) for s in value.get('sources', {}).values()),
            limitation='请求组装记录，不表示模型理解或事实核验；实际费用以服务商用量为准'))
        self.save()
        def receipt(row):
            self.state.setdefault('usage', []).append(row)
            reservation = next(r for r in reversed(self.state['reservations'])
                               if r['kind'] == 'model' and r['stage'] == stage)
            self.budget.record_usage(reservation, row)
            self.save()
        def before_attempt():
            self.state['model_http_attempts'] = self.state.get('model_http_attempts', 0) + 1
            self.save()
        from .model_usage import edition_model_scope
        with edition_model_scope(self.state['id'], stage, receipt, before_attempt):
            raw = await asyncio.wait_for(
                self.model('review' if stage == 'review' else 'analysis', messages, OUTPUTS[stage]),
                timeout=max(.1, self.deadline - time.monotonic()))
        # Persist the paid visible response BEFORE parsing or content validation.
        number = sum(r['kind'] == 'model' for r in self.state['reservations'])
        save_json(self.path / ('response-' + str(number) + '.json'), dict(stage=stage, text=raw))
        self.state.setdefault('delivered_sources', {})[stage] = {
            i: digest(s['text']) for i, s in value.get('sources', {}).items()}
        self.save()
        return contract.decode(raw)

    async def searches(self, jobs):
        candidates = self.state.setdefault('candidates', {})
        for job in jobs:
            if (not isinstance(job, dict) or not isinstance(job.get('query'), str)
                    or not 2 <= len(job['query']) <= 120
                    or job.get('purpose', 'discovery') not in {'discovery', 'latest_close', 'released_policy', 'company_event', 'commentary'}):
                raise ValueError('edition_search_packet_invalid')
        seen = {r['query'] for r in self.state.get('search_receipts', [])}
        pending = []
        for job in jobs:
            if job['query'] not in seen:
                pending.append(job); seen.add(job['query'])
        if not pending:
            return
        await self.check()
        direct = lambda j: (self.state.get('research_protocol') == PROTOCOL
            and j.get('retrieval') == 'issuer_catalogue' and company_job(j, self.state['watchlist']))
        self.budget.check_search_batch(sum(not direct(j) for j in pending))
        for job in pending:
            await self.check()
            if any(r['query'] == job['query'] for r in self.state.get('search_receipts', [])):
                continue
            stock = direct(job)
            if stock:
                try:
                    result = await asyncio.to_thread(self.issuer_desk.catalogue, stock)
                except Exception as error:
                    result = dict(status='source_gap', results=[], error_type=type(error).__name__,
                        limitation='披露通道未取得有效列表；不是公司没有事件，不自动切换付费搜索。')
                self.state.setdefault('issuer_catalogue_checks', []).append(dict(
                    key=stock['market'] + ':' + stock['code'], status=result['status'],
                    results=len(result['results']), complete_history=False))
                baseline, rows = await asyncio.to_thread(self.issuer_desk.baseline, stock, disclosures=result['results'])
                result['results'].extend(rows)
                self.state.setdefault('company_baselines', {})[baseline['key']] = baseline
            else:
                self.budget.reserve('search')
                options = dict(max_results=5) if self.state.get('change_protocol') == 'daily_changes_v1' else {}
                result = await asyncio.to_thread(self.search, self.workspace, job['query'],
                    deadline=self.deadline, hours=168 if self.workspace.now.weekday() >= 5 else 72,
                    topic='news', purpose=job.get('purpose', 'discovery'), **options)
            self.state.setdefault('search_receipts', []).append(dict(query=job['query'], job=job, result=result))
            self.state['search_http_attempts'] = getattr(self.workspace, 'web_search_attempts', 0)
            for row in result.get('results', []):
                from .event_observations import canonical
                url = canonical(row['url'])
                old = next((i for i, r in candidates.items() if r['url'] == url), None)
                if old is None:
                    old = 'S' + str(len(candidates) + 1)
                    candidates[old] = dict(row, url=url, search_links=[])
                candidates[old].setdefault('search_links', []).append(job)
            self.save()
            if result.get('status') in {'failed', 'unavailable', 'disabled'}:
                raise RuntimeError('edition_search_unavailable_no_retry')

    async def reads(self, jobs, events):
        sources = self.state.setdefault('sources', {})
        for job in jobs:
            await self.check()
            eid, cid = job['event_id'], job['candidate_id']
            event = events[eid]
            url = self.state['candidates'][cid]['url']
            from .search_objectives import metadata_blockers
            candidate = self.state['candidates'][cid]
            blocked = metadata_blockers(candidate)
            from .edition_read_selection import stale_hint
            from .body_acquisition import paused_public
            if not candidate.get('baseline_document') and stale_hint(self.state, event, candidate):
                blocked.append('published_hint_outside_event_window')
            if (self.uses_public_reader and not candidate.get('issuer_document')
                    and not candidate.get('baseline_document') and paused_public(url)):
                blocked.append('article_paused_no_auto_retest')
            if blocked:
                self.state.setdefault('read_metadata_rejections', []).append(
                    dict(candidate_id=cid, event_id=eid, flags=blocked, http_requests=0))
                self.save(); continue
            candidate = self.state['candidates'][cid]
            question = event.get('baseline_question')
            if (self.state.get('research_protocol') == PROTOCOL and candidate.get('baseline_document')
                    and (not isinstance(question, str) or not 12 <= len(question.strip()) <= 200)):
                self.state.setdefault('read_metadata_rejections', []).append(dict(
                    candidate_id=cid, event_id=eid, flags=['baseline_requires_event_question'], http_requests=0))
                self.save(); continue
            old = next((s for s in sources.values() if s['url'] == url), None)
            if old:
                if eid not in old['event_ids']: old['event_ids'].append(eid)
                self.attach_baselines(eid, old, event)
                self.save(); continue
            if any(r['candidate_id'] == cid for r in self.state.get('read_receipts', [])): continue
            if len(self.state.get('read_receipts', [])) >= self.state['policy']['max_body_urls']:
                raise RuntimeError('edition_body_budget_exhausted')
            receipt = dict(candidate_id=cid, event_id=eid, status='started',
                increment=job.get('increment'), selection_reason=job.get('reason'))
            self.state.setdefault('read_receipts', []).append(receipt); self.save()
            from .collection_time import window
            hours = window(self.workspace.now, event['purpose'])['hours']
            candidate = self.state['candidates'][cid]
            before_http = getattr(self.workspace, 'public_fetch_attempts', 0)
            if (self.state.get('research_protocol') == PROTOCOL
                    and (candidate.get('issuer_document') or candidate.get('baseline_document'))):
                try:
                    result = await asyncio.to_thread(self.issuer_desk.read, candidate)
                except Exception as error:
                    result = dict(status='failed', reason='issuer_body_unavailable:' + type(error).__name__)
            else:
                if getattr(self.workspace, 'public_fetch_attempts', 0) + 3 > self.state['policy']['max_body_urls'] * 3:
                    raise ValueError('edition_public_http_budget_exhausted')
                result = await asyncio.to_thread(self.read, self.workspace, url,
                    hours=hours, deadline=self.deadline, characters=6000)
            receipt.update(status=result.get('status'), reason=result.get('reason'),
                           read_url=result.get('url', url),
                           public_http_requests=getattr(self.workspace, 'public_fetch_attempts', 0) - before_http,
                           response_capture=result.get('response_capture'))
            self.state['public_fetch_attempts'] = getattr(self.workspace, 'public_fetch_attempts', 0)
            material = result.get('material', {})
            identifier = material.get('id')
            if result.get('status') == 'ok' and identifier in self.workspace.documents:
                item = self.workspace.documents[identifier]
                metadata = self.workspace.metadata(item)
                if metadata['body_quality']['requires_editorial_review']:
                    receipt.update(status='excluded', reason='body_quality_requires_review')
                else:
                    from .material_roles import assess_role
                    from .news_quality import company_focus
                    from types import SimpleNamespace
                    role = assess_role(item)
                    subject = SimpleNamespace(title=item.title, content=body(item), source=item.source,
                        related_stocks=getattr(item, 'related_stocks', []))
                    if candidate.get('issuer_document'):
                        role.update(latest_close_allowed=False, commodity_settlement_allowed=False,
                            original_policy_release_allowed=False, flags=['issuer_disclosure_mirror_not_market_close_or_government_policy'])
                    if candidate.get('baseline_document'):
                        role.update(latest_close_allowed=False, commodity_settlement_allowed=False,
                            original_policy_release_allowed=False, flags=['financial_baseline_not_current_event'])
                    sources[identifier] = dict(id=identifier, event_ids=[eid], candidate_id=cid,
                        title=item.title, url=url, text=body(item), metadata=metadata,
                        purpose=event['purpose'], scope=event.get('scope'),
                        source_role=role,
                        direct_scopes=[s['market'] + ':' + s['code'] for s in self.state['watchlist']
                                       if company_focus(subject, SimpleNamespace(**s))],
                        limitation='正文存在不代表独立核实、完整稿或最新交易时段；原文由后续证据评估和审稿核对。')
                    self.attach_baselines(eid, sources[identifier], event)
            elif result.get('status') == 'ok':
                receipt.update(status='failed', reason='web_source_material_not_in_workspace')
            self.save()

    def attach_baselines(self, event_id, current, event=None):
        """Provide baseline numbers only for an explicit event research question."""
        question = (event or {}).get("baseline_question")
        if not isinstance(question, str) or not 12 <= len(question.strip()) <= 200:
            return
        if self.state.get('research_protocol') != PROTOCOL or current.get('metadata', {}).get('kind') == 'financial_baseline':
            return
        scopes = set(current.get('direct_scopes', []))
        for cid, candidate in self.state['candidates'].items():
            identifier = candidate.get('baseline_document')
            if not identifier or candidate.get('scope') not in scopes:
                continue
            if identifier in self.state['sources']:
                old = self.state['sources'][identifier]
                if event_id not in old['event_ids']:
                    old['event_ids'].append(event_id)
                continue
            item = self.workspace.documents.get(identifier)
            if item is None:
                continue
            metadata = self.workspace.metadata(item)
            if metadata['body_quality']['requires_editorial_review']:
                continue
            self.state['sources'][identifier] = dict(id=identifier, event_ids=[event_id], candidate_id=cid,
                title=item.title, url=item.source_url, text=body(item), metadata=metadata,
                purpose='commentary', scope=item.scope, direct_scopes=[item.scope],
                source_role=dict(latest_close_allowed=False, commodity_settlement_allowed=False,
                    original_policy_release_allowed=False, flags=['financial_baseline_not_current_event']),
                limitation='带期间的经营比较背景；供应商结构化指标，未核原财报，不是本期新事件或独立佐证。')
            self.state.setdefault('baseline_links', []).append(dict(source_id=identifier,
                event_id=event_id, scope=item.scope, question=question, new_http_requests=0))

    async def selected_reads(self, jobs, events, trace):
        self.state.setdefault('read_selection', []).extend(trace); self.save()
        for original in jobs:
            job, charged, considered = dict(original), 0, set()
            while job and job['candidate_id'] not in considered:
                considered.add(job['candidate_id'])
                before_http = getattr(self.workspace, 'public_fetch_attempts', 0)
                before_receipts = len(self.state.get('read_receipts', []))
                await self.reads([job], events)
                # Metadata/paused/cache failures must not consume the second
                # live-source opportunity. Still consider each candidate once.
                if (getattr(self.workspace, 'public_fetch_attempts', 0) > before_http
                        or not self.uses_public_reader and len(self.state.get('read_receipts', [])) > before_receipts):
                    charged += 1
                if charged >= 2 or not original.get('allow_fallback'):
                    break
                job['fallback_ids'] = [cid for cid in original.get('fallback_ids', []) if cid not in considered]
                job['allow_fallback'] = True
                alternate, record = fallback_plan(self.state, events, job)
                if record:
                    record['live_source_attempts'] = charged
                    self.state['read_selection'].append(record); self.save()
                job = alternate

    def packet(self, stage):
        return packet(self.state, stage)

    def validate_assessment(self, assessment, events, stocks):
        stage = self.state['phase']
        delivered = self.state.get('delivered_sources', {}).get(stage, {})
        provided = {sid for sid, source in self.state['sources'].items()
                    if delivered.get(sid) == digest(source['text'])}
        if self.state.get('research_protocol') == PROTOCOL:
            from .listener_research import restrict_baselines
            assessment = restrict_baselines(assessment, events, self.state['sources'])
        accepted, sources, validation = contract.prepare_assessment(
            assessment, events, self.state['sources'], stocks, provided)
        self.state['sources'] = sources
        from .daily_changes import enabled, validate_checks, validate_expectations, validate_topics
        if enabled(self.state):
            self.state['change_missing'] = (validate_checks(self.state, accepted, provided)
                + validate_topics(self.state, accepted, events))
            validate_expectations(self.state, accepted, provided)
            validation['missing'].extend(self.state['change_missing'])
        self.state.setdefault('flow_trace', []).append('assessment_validated')
        self.state.setdefault('assessment_validation', []).append(dict(stage=stage, **validation))
        self.save()
        return accepted, validation['missing']

    async def execute(self):
        stocks = {r['market'] + ':' + r['code'] for r in self.state['watchlist']}
        try:
            jobs = initial_searches(self.state['watchlist'], self.workspace.now,
                direct_issuers=self.state.get('research_protocol') == PROTOCOL,
                daily_changes=self.state.get('change_protocol') == 'daily_changes_v1')
            if self.state.get('research_protocol') == PROTOCOL:
                # Obtain free issuer context before reserving the paid batch.
                await self.searches([j for j in jobs if j.get('retrieval') == 'issuer_catalogue'])
                if self.state.get('change_protocol') == 'daily_changes_v1':
                    jobs = initial_searches(self.state['watchlist'], self.workspace.now,
                        direct_issuers=True, daily_changes=True, baselines=self.state.get('company_baselines'))
                # Reserve the COMPLETE paid batch before spending on any search.
                await self.searches([j for j in jobs if j.get('retrieval') != 'issuer_catalogue'])
                if self.state.get('change_protocol') == 'daily_changes_v1':
                    from .edition_market import collect, evidence
                    await self.check()
                    self.state['market_observations'] = await asyncio.to_thread(collect, self.state, self.issuer_desk)
                    source = evidence(self.state['market_observations'])
                    if source:
                        self.state['sources'][source['id']] = source
                    self.save()
            else:
                await self.searches(jobs)
            a = await self.call('agenda', contract.AGENDA, self.packet('agenda'))
            self.state['agenda'] = contract.agenda(a, self.state['candidates'], stocks)
            from .daily_changes import audit_agenda
            audit_agenda(self.state, self.state['agenda'])
            self.save()
            return await self.read_agenda()
        except asyncio.CancelledError:
            self.state.update(status='interrupted', resume_allowed=False)
            self.save(); raise
        except Exception as error:
            self.state.update(status='failed', error_type=type(error).__name__,
                error_code=str(error) if isinstance(error, ValueError) and re.fullmatch(r'edition_[a-z_]+', str(error)) else None,
                resume_allowed=self.state.get('phase') == 'review')
            if self.state.get('usage'):
                self.state['error_http_status'] = self.state['usage'][-1].get('http_status')
            self.save()
            raise

    async def read_agenda(self):
        """Read a validated saved agenda; also used by same-budget repair continuation."""
        self.state.update(status='reading', phase='reading')
        self.state.setdefault('flow_trace', []).append('reading')
        self.save()
        events = {r['id']: r for r in self.state['agenda']['events']}
        stocks = {r['market'] + ':' + r['code'] for r in self.state['watchlist']}
        selected, trace = primary_plan(self.state['agenda']['events'])
        await self.selected_reads(selected, events, trace)
        if not self.state['sources'] or (self.state.get('research_protocol') == PROTOCOL
                and not any(s.get('candidate_id') for s in self.state['sources'].values())):
            self.state.update(status='partial_materials', missing=list(events), stop_reason='no_readable_article_body')
            self.save(); return None
        assessment = await self.call('assessment', contract.ASSESS, self.packet('assessment'))
        assessment, missing = self.validate_assessment(assessment, events, stocks)
        return await self.finish_materials(assessment, events, stocks)

    async def finish_materials(self, assessment, events, stocks, *, research_tasks=None, recovered_ids=()):
        """One patch assessment, writing and review; reused by same-ledger continuation."""
        self.state.setdefault('flow_trace', []).append('materials_decision')
        missing = contract.assess(assessment, events, self.state['sources'], stocks)
        missing.extend(self.state.get('change_missing', []))
        extra = assessment.get('missed_major_events', [])
        for event in extra:
            contract.event(event, self.state['candidates'], stocks)
            if event['importance'] != 'major' or event['id'] in events: raise ValueError('edition_new_event_invalid')
            events[event['id']] = event; self.state['agenda']['events'].append(event); missing.append(event['id'])
        self.state.update(assessment=assessment, missing=missing); self.save()
        research_events = dict(events, **(research_tasks or {}))
        jobs = assessment.get('additional_searches', [])
        reads = assessment.get('additional_reads', [])
        for job in jobs:
            if job.get('event_id') not in research_events or not isinstance(job.get('query'), str) or not 2 <= len(job['query']) <= 120:
                raise ValueError('edition_patch_search_invalid')
            validate_increment(job)
        for job in reads:
            if job.get('event_id') not in research_events or job.get('candidate_id') not in self.state['candidates']:
                raise ValueError('edition_patch_read_invalid')
            validate_increment(job)
        if jobs or reads or extra or recovered_ids:
            before = {i: dict(text=digest(s['text']), event_ids=set(s['event_ids']))
                      for i, s in self.state['sources'].items()}
            if not jobs:
                await self.check()
                self.budget.check_search_batch(0)
            await self.searches(jobs)
            selected, trace = patch_plan(self.state, research_events, assessment, extra)
            await self.selected_reads(selected, research_events, trace)
            changed = [i for i, source in self.state['sources'].items()
                       if i not in before or digest(source['text']) != before[i]['text'] or i in recovered_ids]
            links = [dict(source_id=i, event_id=eid)
                     for i, source in self.state['sources'].items() for eid in source['event_ids']
                     if i in before and eid in events and eid not in before[i]['event_ids']]
            self.state['patch_progress'] = dict(new_or_changed_body_ids=changed,
                reused_body_event_links=links,
                limitation='新增关联不是新增事实或独立来源；仍须逐事件评估证据，不能直接判定已覆盖。')
            if not changed and not links:
                self.state.update(status='partial_materials', stop_reason='patch_no_new_body')
                self.save(); return None
            assessment = await self.call('patch_assessment', contract.ASSESS,
                self.packet('patch_assessment'))
            assessment, missing = self.validate_assessment(assessment, events, stocks)
            if (assessment.get('additional_searches') or assessment.get('additional_reads')
                    or assessment.get('missed_major_events')):
                missing.append('unresolved_additional_research')
            self.state.update(assessment=assessment, missing=missing); self.save()
        if missing or not self.state['sources']:
            self.state['status'] = 'partial_materials'; self.save(); return None
        self.state['editorial_source_ids'] = editorial_source_ids(self.state)
        editorial = self.packet('writing')
        written = await self.call('writing', contract.WRITE, editorial)
        self.state['draft'] = written; self.save()
        contract.draft(written, events, editorial['sources'])
        validate_listener_draft(self.state, written, editorial['sources'])
        from .daily_changes import validate_language
        validate_language(self.state, written); self.save()
        return await self.review_and_finish(events)

    async def review_and_finish(self, events):
        from .spoken_fidelity import CONTRACT
        value = await self.call('review', contract.REVIEW + CONTRACT,
            self.packet('review'))
        self.state['review'] = value; self.save()
        contract.review(value, events, self.state['sources'], self.state['draft'])
        validate_listener_review(self.state, value)
        self.state.setdefault('flow_trace', []).append('review_validated')
        await self.check()
        from ..models.report import Report, ReportType
        written = self.state['draft']
        sources = '\n\n## 本期引用来源\n以下为采集来源，来源存在不等于内容已被独立证实。\n'
        cited = set(re.findall(r'\[N:([^\]\s]+)\]', written['body']))
        sources += '\n'.join('- [N:' + sid + '] ' + self.state['sources'][sid]['title'] + ' ' + self.state['sources'][sid]['url'] for sid in sorted(cited))
        report = Report(id=self.state['id'], title=written['title'], summary=written['summary'],
            content=written['body'] + sources, report_date=self.workspace.now.date(),
            report_type=ReportType(self.state['report_type']), core_opinions=written.get('core_opinions', []),
            word_count=len(written['body']), reading_time=max(1, len(written['body']) // 400),
            news_count=len(cited), podcast_status='pending')
        from .podcast_script_cache import save, load
        nickname = settings.user_nickname or '朋友'
        save(report, nickname, written['script'])
        if load(report, nickname) != written['script']: raise RuntimeError('edition_verified_script_not_saved')
        self.state.update(status='reviewed_text', report=report.model_dump(mode='json'), resume_allowed=False)
        self.save()
        return report


async def generate_edition(report_type='morning', root=ROOT, prior_report=None):
    preview = await preflight(report_type)
    if not preview['ready_to_run']:
        raise RuntimeError('统一生成尚未具备执行条件：' + ','.join(preview['blockers']))
    with edition_lock(Path(root)):
        # Cross-process, persistent edition guard; force never clears it.
        day = china_now().date().isoformat()
        marker = Path(root) / (day + '-' + report_type + '.started')
        identifier = 'edition-' + uuid.uuid4().hex
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream: stream.write(identifier)
        path = run_path(identifier, root); path.mkdir(mode=0o700)
        now = china_now()
        state = dict(id=identifier, owner='finance-unified-edition-v1', status='prepared',
            cutoff=now.isoformat(), report_type=report_type, watchlist=preview['watchlist'],
            policy=preview['policy'], environment_sha256=preview['environment_sha256'],
            reservations=[], usage=[], candidates={}, sources={}, app_written=False, research_protocol=PROTOCOL, change_protocol='daily_changes_v1')
        if prior_report is not None:
            state['prior_report'] = dict(id=prior_report.id, title=prior_report.title,
                report_date=prior_report.report_date.isoformat(), content=prior_report.content,
                usage='旧报告仅供复盘原判断，不充作本期新事实证据')
        workspace = EpisodeWorkspace(root=path / 'evidence', now=now)
        pipeline = EditionPipeline(state, path, workspace); pipeline.save()
        report = await pipeline.execute()
        if report is None: return None
        if state['policy']['audio_enabled']:
            await pipeline.check()
            from .podcast_generator import get_podcast_generator
            state['status'] = 'audio_started'; pipeline.save()
            try:
                _, duration = await synthesize_reviewed(pipeline, report)
                report.podcast_url = '/podcasts/' + report.id + '.mp3'
                report.podcast_duration = duration; report.podcast_status = 'ready'
                state['status'] = 'audio_ready'
            except Exception as error:
                report.podcast_status = 'failed'
                state.update(status='audio_failed', error_type=type(error).__name__)
        state['report'] = report.model_dump(mode='json'); pipeline.save()
        return report


async def synthesize_reviewed(pipeline, report):
    from .podcast_generator import get_podcast_generator
    async def before_attempt(characters):
        await pipeline.check()
        pipeline.state.setdefault('tts_attempts', []).append(dict(
            provider='edge', characters=characters, at=china_now().isoformat(),
            billing='未使用收费TTS凭据，不允许自动切换收费引擎'))
        pipeline.save()
    return await get_podcast_generator().generate_podcast(report, require_verified_cache=True,
        allow_paid_fallback=False, before_tts_attempt=before_attempt)


def load_state(identifier, root=ROOT):
    path = run_path(identifier, root) / 'result.json'
    if path.is_symlink(): raise ValueError('edition_path_symlink')
    state = json.loads(path.read_text())
    if state.get('id') != identifier or state.get('owner') != 'finance-unified-edition-v1':
        raise ValueError('edition_state_invalid')
    return state


async def check_publication(report, root=ROOT):
    state = load_state(report.id, root)
    if state.get('status') not in {'reviewed_text', 'audio_ready', 'audio_failed'} or not state.get('review'):
        raise RuntimeError('edition_not_reviewed_for_publication')
    if any(state['report'].get(k) != report.model_dump(mode='json').get(k)
           for k in ('title', 'summary', 'content', 'report_date', 'report_type', 'core_opinions')):
        raise RuntimeError('edition_reviewed_report_changed')
    ensure_models_enabled()
    await assert_watchlist_current(watchlist_signature(state['watchlist']))
    _, signature, _ = environment(state['watchlist'], state['report_type'])
    if signature != state['environment_sha256']:
        raise RuntimeError('edition_environment_changed')
    if china_now() > datetime.fromisoformat(state['cutoff']) + timedelta(hours=2):
        raise RuntimeError('edition_expired')


async def resume_review(identifier, root=ROOT):
    """Explicit same-run retry only for a review without a complete response."""
    with edition_lock(Path(root)):
        state = load_state(identifier, root)
        if (state.get('status') != 'failed' or not state.get('resume_allowed')
                or state.get('review') is not None):
            raise RuntimeError('edition_review_not_resumable')
        # A malformed complete response is not a transport failure to repurchase.
        for file in run_path(identifier, root).glob('response-*.json'):
            if json.loads(file.read_text()).get('stage') == 'review':
                raise RuntimeError('edition_complete_review_already_saved')
        workspace = EpisodeWorkspace(root=run_path(identifier, root) / 'resume-evidence',
            now=datetime.fromisoformat(state['cutoff']))
        pipeline = EditionPipeline(state, run_path(identifier, root), workspace)
        events = {r['id']: r for r in state['agenda']['events']}
        contract.draft(state['draft'], events, state['sources'])
        try:
            return await pipeline.review_and_finish(events)
        except Exception as error:
            state.update(status='failed', error_type=type(error).__name__, resume_allowed=True)
            pipeline.save(); raise


async def regenerate_reviewed_audio(report, root=ROOT):
    """No analysis, writing or review model can be invoked from audio retry."""
    with edition_lock(Path(root)):
        state = load_state(report.id, root)
        if state.get('status') not in {'audio_failed', 'reviewed_text'} or not state['policy']['audio_enabled']:
            raise RuntimeError('edition_audio_not_resumable')
        frozen = state['report']
        if any(frozen.get(key) != report.model_dump(mode='json').get(key)
               for key in ('title', 'summary', 'content', 'report_date', 'report_type', 'core_opinions')):
            raise RuntimeError('edition_report_changed')
        workspace = EpisodeWorkspace(root=run_path(report.id, root) / 'resume-evidence',
            now=datetime.fromisoformat(state['cutoff']))
        pipeline = EditionPipeline(state, run_path(report.id, root), workspace)
        await pipeline.check()
        state['status'] = 'audio_started'; pipeline.save()
        try:
            output, duration = await synthesize_reviewed(pipeline, report)
            report.podcast_duration = duration; report.podcast_status = 'ready'
            report.podcast_url = '/podcasts/' + report.id + '.mp3'
            state.update(status='audio_ready', report=report.model_dump(mode='json'))
            pipeline.save(); return output, duration
        except Exception as error:
            state.update(status='audio_failed', error_type=type(error).__name__)
            pipeline.save(); raise
