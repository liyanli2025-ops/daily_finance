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
    names = ('edition_manual.py', 'edition_continuation.py', 'edition_read_selection.py', 'edition_pipeline.py', 'edition_context.py', 'edition_inputs.py', 'edition_contract.py', 'edition_budget.py', 'model_gateway.py',
             'model_usage.py', 'web_research.py', 'article_metadata.py', 'primary_material_quality.py', 'reading_acceptance.py', 'search_objectives.py', 'material_roles.py', 'spoken_fidelity.py',
             'podcast_generator.py', 'podcast_script_cache.py', 'editorial_policy.py', 'research_desk.py')
    return digest({name: digest((Path(__file__).parent / name).read_text()) for name in names})


def initial_searches(stocks, now):
    jobs = search_agenda(stocks, now)
    jobs += [dict(lane='global_policy', purpose='discovery',
                  query=now.strftime('%Y-%m-%d') + ' major world political economic breaking developments financial markets'),
             dict(lane='global_policy', purpose='discovery',
                  query=now.strftime('%Y年%m月%d日') + ' 国内 国际 重大事件 最新进展 金融市场')]
    for job in jobs:
        if job['lane'] == 'us_market':
            job['query'] = now.strftime('%Y-%m-%d') + ' US stocks latest completed session closing market report'
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
            watchlist=stocks, report_type=report_type, sources={}), now),
            len(initial_searches(stocks, now)))
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
        base_search_jobs=initial_searches(stocks, now),
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
        self.check = check or self._check_environment
        self.budget = Budget(state, self.save, lambda: (edition_forecast(self.state, self.workspace.now)
            if self.state['policy'].get('edition_forecast') == 'remaining_stages_v1'
            else editorial_forecast(self.state, self.workspace.now)))
        self.started = time.monotonic()
        self.prior_seconds = state.get('active_seconds', 0)
        self.deadline = self.started + settings.research_max_seconds - self.prior_seconds

    def save(self):
        self.state['active_seconds'] = self.prior_seconds + time.monotonic() - self.started
        self.state['updated_at'] = china_now().isoformat()
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
        if self.state.get('draft'):
            lines.append('\n文字稿（是否已审以本期状态为准）：\n' + self.state['draft'].get('body', ''))
            lines.append('\n口播稿（未通过联合审阅不得合成）：\n' + self.state['draft'].get('script', ''))
        if self.state.get('review'):
            lines.append('\n联合审阅：\n' + json.dumps(self.state['review'], ensure_ascii=False))
        target = self.path / 'receipt.txt'
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as stream: stream.write('\n'.join(lines))

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
        self.budget.check_search_batch(len(pending))
        for job in pending:
            await self.check()
            if any(r['query'] == job['query'] for r in self.state.get('search_receipts', [])):
                continue
            self.budget.reserve('search')
            result = await asyncio.to_thread(self.search, self.workspace, job['query'],
                deadline=self.deadline, hours=168 if self.workspace.now.weekday() >= 5 else 72,
                topic='news', purpose=job.get('purpose', 'discovery'))
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
            blocked = metadata_blockers(self.state['candidates'][cid])
            if blocked:
                self.state.setdefault('read_metadata_rejections', []).append(
                    dict(candidate_id=cid, event_id=eid, flags=blocked, http_requests=0))
                self.save(); continue
            old = next((s for s in sources.values() if s['url'] == url), None)
            if old:
                if eid not in old['event_ids']: old['event_ids'].append(eid)
                self.save(); continue
            if any(r['candidate_id'] == cid for r in self.state.get('read_receipts', [])): continue
            if len(self.state.get('read_receipts', [])) >= self.state['policy']['max_body_urls']:
                raise RuntimeError('edition_body_budget_exhausted')
            receipt = dict(candidate_id=cid, event_id=eid, status='started',
                increment=job.get('increment'), selection_reason=job.get('reason'))
            self.state.setdefault('read_receipts', []).append(receipt); self.save()
            from .collection_time import window
            hours = window(self.workspace.now, event['purpose'])['hours']
            result = await asyncio.to_thread(self.read, self.workspace, url,
                hours=hours, deadline=self.deadline, characters=6000)
            receipt.update(status=result.get('status'), reason=result.get('reason'),
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
                    sources[identifier] = dict(id=identifier, event_ids=[eid], candidate_id=cid,
                        title=item.title, url=url, text=body(item), metadata=metadata,
                        purpose=event['purpose'], scope=event.get('scope'),
                        source_role=role,
                        direct_scopes=[s['market'] + ':' + s['code'] for s in self.state['watchlist']
                                       if company_focus(item, SimpleNamespace(**s))],
                        limitation='正文存在不代表独立核实、完整稿或最新交易时段；原文由后续证据评估和审稿核对。')
            self.save()

    async def selected_reads(self, jobs, events, trace):
        self.state.setdefault('read_selection', []).extend(trace); self.save()
        for job in jobs:
            await self.reads([job], events)
            alternate, record = fallback_plan(self.state, events, job)
            if record:
                self.state['read_selection'].append(record); self.save()
            if alternate:
                await self.reads([alternate], events)

    def packet(self, stage):
        return packet(self.state, stage)

    def validate_assessment(self, assessment, events, stocks):
        stage = self.state['phase']
        delivered = self.state.get('delivered_sources', {}).get(stage, {})
        provided = {sid for sid, source in self.state['sources'].items()
                    if delivered.get(sid) == digest(source['text'])}
        accepted, sources, validation = contract.prepare_assessment(
            assessment, events, self.state['sources'], stocks, provided)
        self.state['sources'] = sources
        self.state.setdefault('assessment_validation', []).append(dict(stage=stage, **validation))
        self.save()
        return accepted, validation['missing']

    async def execute(self):
        stocks = {r['market'] + ':' + r['code'] for r in self.state['watchlist']}
        try:
            jobs = initial_searches(self.state['watchlist'], self.workspace.now)
            await self.searches(jobs)
            a = await self.call('agenda', contract.AGENDA, self.packet('agenda'))
            self.state['agenda'] = contract.agenda(a, self.state['candidates'], stocks)
            events = {r['id']: r for r in a['events']}; self.save()
            selected, trace = primary_plan(a['events'])
            await self.selected_reads(selected, events, trace)
            if not self.state['sources']:
                self.state.update(status='partial_materials', missing=list(events), stop_reason='no_readable_body')
                self.save(); return None
            assessment = await self.call('assessment', contract.ASSESS, self.packet('assessment'))
            assessment, missing = self.validate_assessment(assessment, events, stocks)
            return await self.finish_materials(assessment, events, stocks)
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

    async def finish_materials(self, assessment, events, stocks, *, research_tasks=None, recovered_ids=()):
        """One patch assessment, writing and review; reused by same-ledger continuation."""
        missing = contract.assess(assessment, events, self.state['sources'], stocks)
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
        contract.draft(written, events, editorial['sources']); self.save()
        return await self.review_and_finish(events)

    async def review_and_finish(self, events):
        from .spoken_fidelity import CONTRACT
        value = await self.call('review', contract.REVIEW + CONTRACT,
            self.packet('review'))
        self.state['review'] = value; self.save()
        contract.review(value, events, self.state['sources'], self.state['draft'])
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
            reservations=[], usage=[], candidates={}, sources={}, app_written=False)
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
