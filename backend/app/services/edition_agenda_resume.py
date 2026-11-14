"""One explicit continuation after the saved agenda-topic audit failed.

Old result/marker/captures stay immutable. The child keeps every reservation,
request counter and the original cutoff; it cannot purchase another agenda.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
import os
import shutil
from pathlib import Path
import time

from . import edition_pipeline as core, edition_contract as contract
from .daily_changes import audit_agenda
from .edition_budget import accounted, number, search_batch_plan
from .edition_inputs import edition_forecast
from .episode_workspace import EpisodeWorkspace
from .research_hub import save_json
from .time_context import china_now

CHILD = 'agenda-continuation-v46'


def regular(path):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError('edition_agenda_resume_path_invalid')
    return path


def load_original(directory):
    raw = regular(directory / 'result.json').read_bytes()
    response_raw = regular(directory / 'response-1.json').read_bytes()
    state = json.loads(raw)
    models = [r for r in state.get('reservations', []) if r.get('kind') == 'model']
    if (state.get('status') != 'failed' or state.get('phase') != 'agenda'
            or state.get('error_code') != 'edition_change_concrete_event_lost'
            or len(models) != 1 or models[0].get('stage') != 'agenda'
            or state.get('model_http_attempts') != 1 or len(state.get('usage', [])) != 1
            or state['usage'][0].get('http_status') != 200
            or state.get('read_receipts') or state.get('draft') or state.get('assessment')
            or state.get('tts_attempts') or state.get('app_written')
            or state.get('change_protocol') != 'daily_changes_v1'):
        raise ValueError('edition_agenda_resume_original_not_eligible')
    response = json.loads(response_raw)
    if response.get('stage') != 'agenda':
        raise ValueError('edition_agenda_resume_response_invalid')
    stocks = {r['market']+':'+r['code'] for r in state['watchlist']}
    agenda = contract.agenda(contract.decode(response['text']), state['candidates'], stocks)
    if agenda != state.get('agenda'):
        raise ValueError('edition_agenda_resume_saved_agenda_changed')
    state = deepcopy(state)
    pending = audit_agenda(state, agenda)
    capture_files(directory, state)
    _, pool_proof = background_pool(directory, state)
    proof = dict(original_sha256=hashlib.sha256(raw).hexdigest(),
        response_sha256=hashlib.sha256(response_raw).hexdigest(), **pool_proof)
    return state, pending, proof, raw, response_raw


def capture_files(directory, state):
    """Validate saved HTTP blobs before reusing their receipts in a child workspace."""
    captures = []
    for row in state.get('issuer_http_receipts', []):
        if row.get('status') != 'received':
            continue
        name = row.get('capture')
        if not isinstance(name, str) or Path(name).name != name or name != row['key']+'.json':
            raise ValueError('edition_agenda_resume_capture_invalid')
        matches = list((directory/'evidence').glob('episode-*/issuer-responses/'+name))
        if len(matches) != 1:
            raise ValueError('edition_agenda_resume_capture_missing')
        path = regular(matches[0])
        if hashlib.sha256(path.read_bytes()).hexdigest() != row.get('sha256'):
            raise ValueError('edition_agenda_resume_capture_changed')
        captures.append(path)
    return captures


def background_pool(directory, state):
    """Restore only saved financial background, with original IDs/text/periods."""
    from .research_hub import Material
    wanted = {c['baseline_document']:c for c in state.get('candidates', {}).values()
              if c.get('baseline_document')}
    if not wanted:
        return [], {}
    paths = list((directory/'evidence').glob('episode-*/materials.json'))
    if len(paths) != 1:
        raise ValueError('edition_agenda_resume_background_missing')
    raw = regular(paths[0]).read_bytes()
    rows = json.loads(raw)
    meta_raw = regular(paths[0].parent/'meta.json').read_bytes()
    observed = json.loads(meta_raw)['created_at']
    items = []
    for identifier, candidate in wanted.items():
        matches = [r for r in rows if r.get('id') == identifier]
        if len(matches) != 1:
            raise ValueError('edition_agenda_resume_background_missing')
        row = matches[0]
        if (row.get('kind') != 'financial_baseline' or row.get('scope') != candidate.get('scope')
                or not isinstance(row.get('text'), str)
                or row.get('characters') != len(row['text']) or not row.get('published')
                or datetime.fromisoformat(row['published']) > datetime.fromisoformat(state['cutoff'])):
            raise ValueError('edition_agenda_resume_background_invalid')
        items.append(Material(identifier,row['title'],row['source'],row['url'],row['kind'],row['scope'],
            row['text'],datetime.fromisoformat(row['published']),observed,row.get('period',''),row.get('reading_scope','')))
    return items, dict(background_pool_sha256=hashlib.sha256(raw).hexdigest(),
        background_meta_sha256=hashlib.sha256(meta_raw).hexdigest())


async def preview(config, identifier, *, root):
    from .. import edition_once as entry
    entry.require_pause()
    directory = core.run_path(identifier, root)
    state, pending, proof, _, _ = load_original(directory)
    if state['id'] != identifier:
        raise ValueError('edition_agenda_resume_identifier_changed')
    await entry.assert_watchlist_current(entry.watchlist_signature(state['watchlist']))
    current_policy, _, routes = core.environment(state['watchlist'], state['report_type'], config)
    if current_policy != state['policy']:
        raise ValueError('edition_agenda_resume_policy_changed')
    usage = state['usage'][0]
    if any(usage.get(k) != routes['analysis'][k] for k in ('provider', 'model')):
        raise ValueError('edition_agenda_resume_model_changed')
    from .generic_extraction import runtime_status
    from .web_research import search_availability
    search = search_availability(config=config, manual_proof=entry.reviewed_search_permission(config))
    forecast = search_batch_plan(state['policy'], edition_forecast(state,
        datetime.fromisoformat(state['cutoff'])), 0, state['reservations'])
    blockers = []
    minimum_stages = ('assessment','writing','review')
    from .edition_budget import OUTPUTS
    models = [r for r in state['reservations'] if r['kind']=='model']
    if state['policy']['max_model_reservations']-len(models) < len(minimum_stages):
        blockers.append('edition_model_reservations_insufficient_for_remaining_stages')
    if state['policy']['total_output_tokens']-sum(r['output_tokens'] for r in models) < sum(OUTPUTS[k] for k in minimum_stages):
        blockers.append('edition_output_budget_insufficient_for_remaining_stages')
    from .edition_inputs import messages_for
    from .edition_context import packet
    assessment_messages = messages_for('assessment', contract.ASSESS, packet(state,'assessment'),
        datetime.fromisoformat(state['cutoff']), state['report_type'])
    known_assessment_characters = sum(len(m['content']) for m in assessment_messages)
    remaining_input = state['policy']['total_input_characters']-sum(r.get('input_characters',0) for r in models)
    if (known_assessment_characters > state['policy']['max_input_characters']
            or known_assessment_characters >= remaining_input):
        blockers.append('edition_input_budget_insufficient_for_known_assessment')
    if not runtime_status()['ready']: blockers.append('body_extractor_unavailable')
    if not search['available']: blockers.append(search['reason'])
    if not forecast['fits_money']: blockers.append('edition_estimated_budget_exhausted')
    if state['policy']['max_body_urls']*3 <= state.get('public_fetch_attempts', 0):
        blockers.append('edition_public_http_budget_exhausted')
    if config.research_max_seconds <= state.get('active_seconds', 0): blockers.append('edition_time_exhausted')
    fingerprint = entry.identity(state['watchlist'], state['report_type'], config)
    frozen = dict(proof, identity=fingerprint, policy=state['policy'], original_cutoff=state['cutoff'])
    spent = sum((accounted(r) for r in state['reservations']), number(0))
    now = china_now()
    result = dict(mode='same_edition_saved_agenda_continuation_preview', id=identifier,
        prepared_at=now.isoformat(), expires_at=(now+timedelta(hours=2)).isoformat(),
        ready_to_run=not blockers, blockers=blockers, input_sha256=core.digest(frozen),
        original_cutoff=state['cutoff'], historical_reassessment=True,
        estimated_limit_usd=state['policy']['estimated_limit_usd'],
        spent_or_reserved_usd=str(spent), remaining_estimate_usd=str(number(state['policy']['estimated_limit_usd'])-spent),
        prior_model_http_attempts=state['model_http_attempts'],
        prior_search_http_attempts=state.get('search_http_attempts',0),
        prior_public_fetch_attempts=state.get('public_fetch_attempts',0),
        remaining_public_http_attempts=state['policy']['max_body_urls']*3-state.get('public_fetch_attempts',0),
        remaining_model_reservations=state['policy']['max_model_reservations']-len(models),
        remaining_input_characters=remaining_input, known_assessment_characters=known_assessment_characters,
        selected_read_ids=[r for e in state['agenda']['events'] for r in e['read_ids']],
        pending_topic_leads=pending, budget_forecast=forecast,
        source_counts=entry.summary(state, directory)['source_counts'],
        models_performed=0, search_requests=0, public_fetch_attempts=0, tts_requests=0,
        app_written=False, pause_preserved=True, original_files_unchanged=True,
        limitation='复用原选题，不重搜整批、不重付选题、不扫描全市场；读正文后评估，必要时仅一次补查，再写稿审稿。'
        '沿用原累计$1估算、计数和截止，非硬账单上限；晚取得的页面不证明原截止前已公开。'
        '费用或重大证据不足则保存部分资料；不生成音频、不发布App、不恢复自动化。')
    return result, state, proof, fingerprint


async def continue_once(config, identifier, *, root, run=False, input_sha=None):
    from .. import edition_once as entry
    with core.edition_lock(core.ROOT):
        entry.require_pause()
        original_dir = core.run_path(identifier, root)
        child = original_dir / CHILD
        if child.is_symlink(): raise ValueError('edition_agenda_resume_path_invalid')
        marker = child / 'continuation.started'
        if marker.exists() or marker.is_symlink():
            saved = json.loads(regular(child / 'result.json').read_text())
            lineage = saved['agenda_continuation']
            if (regular(marker).read_text() != lineage['input_sha256']
                    or hashlib.sha256(regular(original_dir / 'result.json').read_bytes()).hexdigest()
                        != lineage['original_sha256']):
                raise ValueError('edition_agenda_resume_history_changed')
            return saved, child, True
        planned, state, proof, fingerprint = await preview(config, identifier, root=root)
        if not run or not planned['ready_to_run']:
            return planned, None, False
        if input_sha != planned['input_sha256']:
            raise ValueError('edition_agenda_resume_preview_changed')
        if child.exists(): raise ValueError('edition_agenda_resume_incomplete_directory')
        # Persist a child initial state BEFORE the one-attempt marker; old directory
        # content is only read. A crash before/after the marker never buys a new trial.
        from .edition_release_gate import require_acceptance
        release_receipt = require_acceptance()
        captures = capture_files(original_dir, state)
        background, _ = background_pool(original_dir, state)
        child.mkdir(mode=0o700)
        state['agenda_continuation'] = dict(proof, input_sha256=input_sha,
            prior_usage=entry.summary(state, original_dir),
            repair_source_signature=core.source_signature(), current_identity=fingerprint, release_acceptance=release_receipt,
            started_at=china_now().isoformat(), automatic_retry_allowed=False,
            original_result_preserved=True)
        state.update(status='reading_saved_agenda', resume_allowed=False, manual_run_finished=False)
        for key in ('error_type','error_code','error_http_status'):
            state.pop(key, None)
        save_json(child / 'result.json', state)
        with os.fdopen(os.open(marker, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600), 'w') as stream:
            stream.write(input_sha); stream.flush(); os.fsync(stream.fileno())
        expiry = china_now()+timedelta(hours=2)
        workspace = EpisodeWorkspace(root=child / 'evidence', now=datetime.fromisoformat(state['cutoff']))
        if captures:
            folder = workspace.path/'issuer-responses'
            folder.mkdir(mode=0o700)
            for capture in captures:
                shutil.copyfile(capture, folder/capture.name)
                (folder/capture.name).chmod(0o600)
        workspace.add(background)
        state['agenda_continuation']['background_records_restored'] = len(background)
        workspace.watchlist_signature = entry.watchlist_signature(state['watchlist'])
        workspace.web_search_attempts = state.get('search_http_attempts',0)
        workspace.public_fetch_attempts = state.get('public_fetch_attempts',0)
        pipeline = None
        async def check():
            entry.require_pause()
            await entry.assert_watchlist_current(workspace.watchlist_signature)
            if entry.identity(state['watchlist'], state['report_type'], config) != fingerprint:
                raise ValueError('edition_agenda_resume_environment_changed')
            if china_now() > expiry or time.monotonic() >= pipeline.deadline:
                raise RuntimeError('edition_time_exhausted')
            if hashlib.sha256(regular(original_dir / 'result.json').read_bytes()).hexdigest() != proof['original_sha256']:
                raise ValueError('edition_agenda_resume_history_changed')
        pipeline = core.EditionPipeline(state, child, workspace, check=check)
        with entry.manual_text_scope(identifier, config, search_proof=entry.reviewed_search_permission(config)):
            try:
                await check()
                pipeline.save()
                await pipeline.read_agenda()
            except (Exception, asyncio.CancelledError) as error:
                state.update(status='interrupted' if isinstance(error, asyncio.CancelledError) else 'failed',
                    error_type=type(error).__name__, error_code=str(error) if isinstance(error, (ValueError, RuntimeError))
                        and str(error).startswith('edition_') else None)
                pipeline.save()
                if isinstance(error, asyncio.CancelledError): raise
        state['manual_run_finished'] = True
        state['agenda_continuation']['finished_at'] = china_now().isoformat()
        pipeline.save()
        return state, child, False
