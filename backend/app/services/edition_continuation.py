"""Explicit one-attempt continuation of an already paid material assessment.

All remaining work shares EditionPipeline, its original ledger and its original
cutoff. The old result/response files and started marker remain auditable.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace

from . import edition_contract as contract, edition_pipeline as core
from .edition_budget import accounted, digest, number, search_batch_plan
from .edition_inputs import edition_forecast
from .episode_workspace import EpisodeWorkspace
from .research_hub import save_json
from .time_context import china_now


def regular(path):
    """Validate every visible path component before reading saved private input."""
    path = Path(path)
    if any(part.is_symlink() for part in (path, *path.parents)) or not path.is_file():
        raise ValueError('edition_continuation_file_invalid')
    return path


def original_input(directory, identifier):
    raw = regular(directory / 'result.json').read_bytes()
    state = json.loads(raw)
    stages = [r.get('stage') for r in state.get('reservations', []) if r['kind'] == 'model']
    if (state.get('id') != identifier or not state.get('manual_text_only')
            or state.get('status') != 'failed' or state.get('phase') != 'assessment'
            or state.get('error_code') not in {'edition_evidence_scope_invalid',
                'edition_quote_not_found', 'edition_company_subject_mismatch'}
            or stages != ['agenda', 'assessment'] or state.get('draft')
            or state.get('app_written') or state.get('tts_attempts')
            or state.get('material_continuation')):
        raise ValueError('edition_continuation_not_eligible')
    # Unknown billing and HTTP failures are not semantic failures to retry.
    rows = [r for r in state['reservations'] if r['kind'] == 'model']
    if any('usage_priced_usd' not in r or r.get('actual_usage', {}).get('http_status') != 200 for r in rows):
        raise ValueError('edition_continuation_usage_unknown')
    response_raw = regular(directory / 'response-2.json').read_bytes()
    response = json.loads(response_raw)
    if response.get('stage') != 'assessment':
        raise ValueError('edition_continuation_response_invalid')
    return state, raw, response_raw, contract.decode(response['text'])


def recover_sources(state, directory):
    """Only admit integrity-checked saved captures; never request their URL again."""
    from .collection_time import window
    from .reading_acceptance import replay, local_time, capture_file
    from .web_research import parse_visible_article
    from .primary_material_quality import review_body
    from .material_roles import assess_role
    from .news_quality import company_focus
    cutoff = local_time(state['cutoff'])
    previous = {Path(r['response_capture']).name: r for r in state.get('read_receipts', [])
                if r.get('response_capture') and r.get('status') != 'ok'}
    sources, audit = {}, []
    for folder in sorted((directory / 'evidence').glob('*/public-responses')):
        for row in replay(folder, hours=window(cutoff, 'discovery')['hours'])['rows']:
            prior = previous.get(row['capture'])
            if not prior:
                continue
            cid = prior['candidate_id']
            if row.get('integrity') == 'matched' and (row.get('snapshot_cutoff') != state['cutoff']
                    or row.get('url') != state['candidates'][cid]['url']):
                raise ValueError('edition_continuation_capture_changed')
            record = dict(candidate_id=cid, capture=row['capture'], capture_sha256=row.get('body_sha256'),
                          status='not_admitted', reason=row.get('reason'))
            audit.append(record)
            if not row.get('text'):
                continue
            quality = review_body(row['text'])
            if quality['requires_editorial_review']:
                record.update(reason='body_quality_requires_review', body_quality=quality)
                continue
            metadata_raw = capture_file(folder, row['capture']).read_bytes()
            meta = json.loads(metadata_raw)
            raw = capture_file(folder, meta['file']).read_bytes()
            if hashlib.sha256(raw).hexdigest() != row['body_sha256']:
                raise ValueError('edition_continuation_capture_changed')
            item = parse_visible_article(raw, row['url'], now=cutoff,
                hours=window(cutoff, 'discovery')['hours'])
            if item.content != row['text']:
                raise ValueError('edition_continuation_parser_changed')
            role = assess_role(item)
            # Recovery is background pending reassessment, never verification of
            # a latest closing session or of an original policy publication.
            role.update(latest_close_allowed=False, commodity_settlement_allowed=False,
                        original_policy_release_allowed=False)
            record.update(status='recovered_pending_assessment', source_id=item.id,
                          text_sha256=row['text_sha256'], characters=len(item.content),
                          metadata_sha256=hashlib.sha256(metadata_raw).hexdigest())
            sources[item.id] = dict(id=item.id, title=item.title, url=row['url'], text=item.content,
                event_ids=[prior['event_id']], candidate_id=cid, purpose='commentary',
                metadata=EpisodeWorkspace.metadata(None, item), source_role=role,
                direct_scopes=[s['market'] + ':' + s['code'] for s in state['watchlist']
                    if company_focus(item, SimpleNamespace(**s))],
                recovered_capture=dict(**record, available_at_cutoff_verified=False,
                    delivered_to_model=False, latest_session_verified=False),
                limitation='已存HTML离线恢复，仅作待评估背景；不能替代最新收盘、原政策披露或独立核验。')
    return sources, audit


def gap_plan(state, assessment):
    """Target specific gaps, including company checks; no new whole-edition search."""
    events = {r['id']: r for r in state['agenda']['events']}
    jobs = deepcopy(assessment.get('additional_searches', []))
    tasks = {}
    targeted = {r['event_id'] for r in jobs}
    day = datetime.fromisoformat(state['cutoff']).strftime('%Y-%m-%d')
    for check in assessment['watchlist_checks']:
        if check['status'] != 'missing':
            continue
        stock = next(s for s in state['watchlist'] if s['market'] + ':' + s['code'] == check['key'])
        event = next((e for e in events.values() if e.get('scope') == check['key']), None)
        if event is None:
            named = [e for e in events.values() if stock['name'] in e['title']
                and sum(s['name'] in e['title'] for s in state['watchlist']) == 1]
            event = named[0] if len(named) == 1 else None
        if event is None:
            eid = 'company-check-' + stock['market'] + '-' + stock['code']
            event = dict(id=eid, title=stock['name'] + '直接公司资料核对', scope=check['key'],
                lane='company_event', purpose='company_event', importance='context')
            tasks[eid] = event
        if event['id'] not in targeted:
            jobs.append(dict(event_id=event['id'], lane='company_event', scope=check['key'],
                purpose='company_event', query=day + ' ' + stock['name'] + ' ' + stock['code']
                    + ' 公告 财报 重大事项 最新已披露', increment='original_source',
                reason='自选股仍缺直接资料，核对本公司原始披露；同业或市场综述不能代替本公司证据。'))
            targeted.add(event['id'])
    for row in assessment['events']:
        event = events[row['id']]
        if row['status'] != 'missing' or event['id'] in targeted:
            continue
        jobs.append(dict(event_id=event['id'], lane=event['lane'], scope=event.get('scope'),
            purpose=event['purpose'], query=(day + ' ' + event['title'][:65]
                + (' 最新已完成交易日 收盘 结算' if event['purpose']=='latest_close' else ' 最新进展 原始来源'))[:120],
            increment='original_source', reason='针对底稿中这一个未覆盖事件补查；保留原截止，核对实际发布日期与消息口径。'))
        targeted.add(event['id'])
    return jobs, tasks


def prepare(state, assessment, directory):
    state = deepcopy(state)
    events = {r['id']: r for r in state['agenda']['events']}
    stocks = {s['market'] + ':' + s['code'] for s in state['watchlist']}
    delivered = state.get('delivered_sources', {}).get('assessment', {})
    provided = {sid for sid, source in state['sources'].items()
                if delivered.get(sid) == digest(source['text'])}
    accepted, sources, validation = contract.prepare_assessment(
        assessment, events, state['sources'], stocks, provided)
    state['sources'] = sources
    recovered, audit = recover_sources(state, directory)
    # A recovered page is not automatically useful. Only send it if the paid
    # assessment explicitly asked for that candidate; background alternatives
    # remain replayable locally and do not inflate every remaining request.
    requested = {r['candidate_id'] for r in accepted.get('additional_reads', [])}
    recovered = {sid: source for sid, source in recovered.items()
                 if source['candidate_id'] in requested}
    for record in audit:
        if record.get('status') == 'recovered_pending_assessment' and record.get('source_id') not in recovered:
            record['status'] = 'available_locally_not_selected'
            record['reason'] = 'not_requested_by_saved_assessment_background_not_automatically_loaded'
    for sid, source in recovered.items():
        if sid in sources and sources[sid]['text'] != source['text']:
            raise ValueError('edition_continuation_source_collision')
        if sid not in sources:
            sources[sid] = source
    jobs, tasks = gap_plan(state, accepted)
    accepted['additional_searches'] = jobs
    state.update(assessment=accepted, missing=validation['missing'])
    state.setdefault('assessment_validation', []).append(dict(stage='saved_assessment_replay', **validation))
    state['research_tasks'] = tasks
    state['recovered_source_ids'] = list(recovered)
    state['continuation_catalogue_ids'] = sorted(state['candidates'])
    return state, audit


async def continuation_preview(config, identifier, root=core.ROOT):
    from .. import edition_once as entry
    entry.require_pause()
    directory = core.run_path(identifier, root)
    state, raw, response, assessment = original_input(directory, identifier)
    await entry.assert_watchlist_current(entry.watchlist_signature(state['watchlist']))
    current_policy, _, _ = core.environment(state['watchlist'], state['report_type'], config)
    if current_policy != state['policy']:
        raise ValueError('edition_continuation_policy_changed')
    fingerprint = entry.identity(state['watchlist'], state['report_type'], config)
    state, recovery = prepare(state, assessment, directory)
    jobs = state['assessment']['additional_searches']
    seen = {r['query'] for r in state.get('search_receipts', [])}
    pending = {j['query'] for j in jobs} - seen
    forecast = search_batch_plan(state['policy'], edition_forecast(state,
        datetime.fromisoformat(state['cutoff'])), len(pending), state['reservations'])
    from .generic_extraction import runtime_status
    from .edition_context import packet
    from .edition_inputs import messages_for
    from .web_research import search_availability
    proof = entry.reviewed_search_permission(config)
    available = search_availability(config=config, manual_proof=proof)
    blockers = []
    request_messages = messages_for('patch_assessment', contract.ASSESS, packet(state, 'patch_assessment'),
        datetime.fromisoformat(state['cutoff']), state['report_type'])
    request_characters = sum(len(m['content']) for m in request_messages)
    if request_characters > state['policy']['max_input_characters']:
        blockers.append('edition_model_budget_exhausted')
    if not available['available']: blockers.append(available['reason'])
    if not runtime_status()['ready']: blockers.append('body_extractor_unavailable')
    if not forecast['fits_money']: blockers.append('edition_estimated_budget_exhausted')
    if not forecast['fits_search_count']: blockers.append('edition_search_budget_exhausted')
    if state.get('active_seconds', 0) >= config.research_max_seconds:
        blockers.append('edition_time_exhausted')
    frozen = dict(original_sha256=hashlib.sha256(raw).hexdigest(),
        response_sha256=hashlib.sha256(response).hexdigest(), environment=fingerprint,
        recovery=recovery, plan=jobs, policy=state['policy'])
    public = dict(mode='same_edition_material_continuation_preview', id=identifier,
        ready_to_run=not blockers, blockers=blockers, original_cutoff=state['cutoff'],
        historical_cutoff_preserved=True, estimated_limit_usd=state['policy']['estimated_limit_usd'],
        spent_or_reserved_usd=forecast['spent_or_reserved_usd'], budget_forecast=forecast,
        recovered_bodies_selected=len(state['recovered_source_ids']), recovery=recovery,
        patch_request_characters=request_characters,
        targeted_searches=jobs, remaining_model_stages=['patch_assessment','writing','review'],
        cumulative_model_reservations_max=state['policy']['max_model_reservations'],
        input_sha256=digest(frozen), model_requests=0, search_requests=0, public_fetch_attempts=0,
        tts_requests=0, app_written=False, pause_preserved=True,
        limitation='原一期、原截止、原价格与累计预算，仅补具体缺口。新正文大小未知，预算不足保留资料停止；'
            '截止后取得的页面不证明截止时已公开。--run最多再评估一次、写稿一次、审稿一次，不重付前两阶段。')
    return public, state, raw, fingerprint


async def continue_once(config, identifier, *, run=False, root=core.ROOT):
    from .. import edition_once as entry
    root = Path(root)
    with core.edition_lock(root):
        entry.require_pause()
        directory = core.run_path(identifier, root)
        marker = directory / 'material-continuation.started'
        if marker.is_symlink():
            raise ValueError('edition_continuation_marker_invalid')
        if marker.exists():
            regular(marker)
            # A saved attempt (including an interrupted one) can only be read.
            return core.load_state(identifier, root), directory, True
        preview, state, original, fingerprint = await continuation_preview(config, identifier, root)
        if not run or not preview['ready_to_run']:
            return preview, None, False
        expiry = china_now() + timedelta(hours=2)
        if entry.identity(state['watchlist'], state['report_type'], config) != fingerprint:
            raise ValueError('edition_continuation_environment_changed')
        # Backup must be durably created before marking or changing the old run.
        backup = directory / 'before-material-continuation.json'
        if backup.exists():
            if regular(backup).read_bytes() != original:
                raise ValueError('edition_continuation_backup_changed')
        else:
            with os.fdopen(os.open(backup, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600), 'wb') as stream:
                stream.write(original); stream.flush(); os.fsync(stream.fileno())
        with os.fdopen(os.open(marker, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600), 'w') as stream:
            stream.write(preview['input_sha256']); stream.flush(); os.fsync(stream.fileno())
        state['material_continuation'] = dict(input_sha256=preview['input_sha256'],
            original_sha256=hashlib.sha256(original).hexdigest(), recovery=preview['recovery'],
            prior_error={k: state.get(k) for k in ('status','phase','error_type','error_code','error_http_status')},
            prior_model_http_attempts=state.get('model_http_attempts',0),
            prior_search_http_attempts=state.get('search_http_attempts',0),
            prior_public_fetch_attempts=state.get('public_fetch_attempts',0),
            started_at=china_now().isoformat(), automatic_retry_allowed=False)
        state.update(status='continuing_materials', resume_allowed=False)
        for key in ('error_code','error_type','error_http_status'):
            state.pop(key, None)
        save_json(directory / 'result.json', state)
        workspace = EpisodeWorkspace(root=directory / 'evidence', now=datetime.fromisoformat(state['cutoff']))
        workspace.watchlist_signature = entry.watchlist_signature(state['watchlist'])
        workspace.web_search_attempts = state.get('search_http_attempts',0)
        workspace.public_fetch_attempts = state.get('public_fetch_attempts',0)
        pipeline = None
        async def check():
            entry.require_pause()
            await entry.assert_watchlist_current(workspace.watchlist_signature)
            if entry.identity(state['watchlist'], state['report_type'], config) != fingerprint:
                raise ValueError('edition_continuation_environment_changed')
            if china_now() > expiry or time.monotonic() >= pipeline.deadline:
                raise RuntimeError('edition_time_exhausted')
        pipeline = core.EditionPipeline(state, directory, workspace, check=check)
        pipeline.save()
        with entry.manual_text_scope(identifier, config, search_proof=entry.reviewed_search_permission(config)):
            try:
                events = {r['id']: r for r in state['agenda']['events']}
                stocks = {r['market'] + ':' + r['code'] for r in state['watchlist']}
                await pipeline.finish_materials(state['assessment'], events, stocks,
                    research_tasks=state['research_tasks'], recovered_ids=state['recovered_source_ids'])
            except (Exception, asyncio.CancelledError) as error:
                state.update(status='interrupted' if isinstance(error, asyncio.CancelledError) else 'failed',
                    error_type=type(error).__name__,
                    error_code=str(error) if isinstance(error, (ValueError, RuntimeError))
                        and str(error).startswith('edition_') else None)
                pipeline.save()
                if isinstance(error, asyncio.CancelledError): raise
        state['manual_run_finished'] = True
        state['material_continuation']['finished_at'] = china_now().isoformat()
        state['resume_allowed'] = False
        pipeline.save()
        return state, directory, False
