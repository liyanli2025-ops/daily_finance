"""Search evidence -> report input -> reviewed draft, without publishing/TTS.

Default preparation is offline. Execution uses the production gateway, pause,
watchlist and explicit phase budgets; it has no isolated paid transport or fallback
to legacy collection. Prior failed discovery trials are never accepted.
"""
from datetime import timedelta
import asyncio
import hashlib
import json
import os
from pathlib import Path

from ..models.news import News
from .news_quality import reading_scope, excluded_reason
from .news_selection import within_window
from .search_primary_collection import prepare as prepare_primary, watchlist_rows, local_time
from .watchlist_repository import watchlist_signature
from .time_context import china_now
from .discovery_completion import CONTRACT, completion_review
from .collection_time import policy as time_policy,validate_window,eligible as time_eligible

OWNER = 'finance-primary-report-input-v1'
FINISHED = {'materials_for_human_review', 'partial_materials_for_human_review'}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def body_hash(item):
    return hashlib.sha256(item.content.encode('utf-8')).hexdigest()


def export_discovery(workspace, state):
    """Keep evidence IDs and the complete stored body, not search snippets.

    Returned discovery ranges are retained separately: storing a complete body
    never implies that the discovery model read every character.
    """
    from .primary_discovery import validate_finish
    if state.get('owner') != 'finance-model-led-discovery-v1' or state.get('status') not in FINISHED:
        raise ValueError('primary_report_discovery_incomplete')
    stocks = watchlist_rows(state.get('watchlist'))
    cutoff = local_time(state['started_at'])
    if cutoff != workspace.now:
        raise ValueError('primary_report_workspace_clock_changed')
    if state.get('time_policy') is not None and state['time_policy']!=time_policy(cutoff):
        raise ValueError('primary_report_time_policy_changed')
    provided = state.get('provided_ids')
    if not isinstance(provided, list) or not provided or len(set(provided)) != len(provided):
        raise ValueError('primary_report_provided_ids_invalid')
    validate_finish(state['dossier'], set(provided), stocks, state['candidates'])
    from .discovery_feedback import cited_ids, body_records
    selected = cited_ids(state['dossier'])
    if not selected:
        raise ValueError('primary_report_no_selected_evidence')
    records = body_records(workspace, state['receipts'])
    news, provenance = [], []
    for identifier in selected:
        item = workspace.documents.get(identifier)
        if not isinstance(item, News) or reading_scope(item) not in {'visible_body', 'full_text', 'wire_text'}:
            raise ValueError('primary_report_source_not_body')
        if body_hash(item) != workspace.document_hashes.get(identifier):
            raise ValueError('primary_report_stored_body_changed')
        ranges, observations = [], []
        for receipt in state['receipts']:
            result = receipt.get('result', {})
            material = result.get('material', result)
            if result.get('status') != 'ok' or material.get('id') != identifier:
                continue
            text = material.get('text')
            offset = material.get('offset', 0)
            if not isinstance(text, str) or type(offset) is not int or offset < 0 or not text:
                raise ValueError('primary_report_exposure_invalid')
            if item.content[offset:offset + len(text)] != text:
                raise ValueError('primary_report_exposure_changed')
            ranges.append([offset, offset + len(text)])
            observed = result.get('cache_observed_at') or result.get('observed_at')
            if observed:
                observations.append(observed)
        if not ranges:
            raise ValueError('primary_report_no_body_receipt')
        news.append(item.model_dump(mode='json'))
        provenance.append(dict(id=identifier, text_sha256=body_hash(item),
                               discovery_provided_ranges=workspace.merged_ranges(ranges),
                               discovery_completed_request_ranges=(state['context_delivery']['body_ranges'].get(identifier, [])
                                   if 'context_delivery' in state else None),
                               observation_times=sorted(set(observations)),
                               observation_time_unknown=not observations,
                               available_at_cutoff_verified=False,
                               source_windows=records.get(identifier,{}).get('source_windows',[]),
                               reading_scope=reading_scope(item)))
    if any(not records.get(identifier, {}).get('eligible') for identifier in selected):
        raise ValueError('primary_report_selected_body_not_eligible')
    return dict(owner=OWNER, collected_at=cutoff.isoformat(), hours=72, watchlist=stocks,
                time_policy=state.get('time_policy'),
                news=news, provenance=provenance, research=state['dossier'],
                budget_contract=state.get('budget_contract'),
                collection_completion=(completion_review(state) if state.get('budget_contract')==CONTRACT else None),
                collection_feedback=state.get('collection_feedback'),
                open_tasks=state.get('open_tasks', []),
                reading_coverage=[{key: records[identifier][key] for key in
                    ('id', 'characters', 'text_sha256', 'ranges', 'unread_ranges', 'body_quality', 'eligible')}
                    for identifier in selected],
                unselected_provided_ids=sorted(set(provided)-set(selected)),
                executed_coverage=state.get('executed_coverage', {}),
                search_receipts=[r for r in state['receipts'] if r.get('request', {}).get('tool') == 'search'],
                upstream_usage={key: state.get(key) for key in ('model_calls', 'model_input_characters', 'reserved_output_tokens',
                    'search_tool_calls', 'body_url_calls')},
                source_status=state['status'], quality_acceptance='pending_human_review')


def save_discovery_input(workspace, state):
    """Only successful, list-checked callers may create this local handoff."""
    if state.get('status') not in FINISHED:
        return None
    from .research_hub import save_json
    value = export_discovery(workspace, state)
    save_json(workspace.path / 'report-input.json', value)
    return dict(file='report-input.json', input_sha256=fingerprint(value),
                status='report_input_pending_human_review', report_generated=False)


def prepare(value, now=None):
    """Accept an explicit search-primary bundle or a successful discovery export."""
    now = now or china_now()
    if not isinstance(value, dict):
        raise ValueError('primary_report_input_invalid')
    if value.get('owner') == 'finance-search-primary-v1':
        news, intake = prepare_primary(value, now)
        source = dict(cutoff=intake['collected_at'], watchlist=intake['watchlist'],
                      hours=intake['hours'], research=None,
                      executed_coverage={'status': 'external_receipts_not_model_execution_ledger'},
                      search_receipts=intake['search_receipts'], intake=intake,
                      watchlist_origin=value.get('watchlist_origin','provided_not_verified_against_app'),
                      manual_review_notes=value.get('manual_review_notes',[]),
                      upstream_usage=None, source_kind='provided_primary_bundle')
    elif value.get('owner') == OWNER:
        cutoff = local_time(value['collected_at'])
        hours = value.get('hours')
        if type(hours) is not int or not 1 <= hours <= 72 or cutoff > now:
            raise ValueError('primary_report_clock_invalid')
        policy=value.get('time_policy')
        if policy is not None and policy!=time_policy(cutoff):raise ValueError('primary_report_time_policy_changed')
        if value.get('source_status') not in FINISHED:
            raise ValueError('primary_report_discovery_incomplete')
        stocks = watchlist_rows(value.get('watchlist'))
        rows = value.get('news')
        provenance = value.get('provenance')
        if not isinstance(rows, list) or not rows or not isinstance(provenance, list):
            raise ValueError('primary_report_bodies_missing')
        news = [News.model_validate(row) for row in rows]
        identifiers = [n.id for n in news]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError('primary_report_duplicate_id')
        hashes = {row['id']: row['text_sha256'] for row in provenance}
        if len(hashes) != len(provenance) or set(hashes) != set(identifiers):
            raise ValueError('primary_report_provenance_mismatch')
        for item in news:
            windows=next(row for row in provenance if row['id']==item.id).get('source_windows',[])
            if not isinstance(windows,list):raise ValueError('primary_report_source_window_invalid')
            for window in windows:validate_window(window,cutoff)
            if windows and policy is None:raise ValueError('primary_report_time_policy_missing')
            if (len(item.content.strip()) < 80 or reading_scope(item) not in {'full_text', 'visible_body', 'wire_text'}
                    or excluded_reason(item) or not (time_eligible(item,cutoff,windows) if policy else within_window(item, cutoff, hours))):
                raise ValueError('primary_report_source_not_admitted')
            if body_hash(item) != hashes[item.id]:
                raise ValueError('primary_report_body_hash_mismatch')
        # Recheck finish citations even when reading a saved, edited JSON export.
        from .primary_discovery import validate_finish
        validate_finish(dict(value['research'], omissions=[]), set(identifiers), stocks, {})
        if value.get('budget_contract') not in {None,CONTRACT}:
            raise ValueError('primary_report_budget_contract_invalid')
        if value.get('budget_contract')==CONTRACT and not isinstance(value.get('collection_completion'),dict):
            raise ValueError('primary_report_collection_review_missing')
        completion=None
        if value.get('budget_contract')==CONTRACT:
            if not isinstance(value.get('collection_feedback'),dict):
                raise ValueError('primary_report_collection_review_missing')
            completion=completion_review(dict(dossier=value['research'],selected_ids=identifiers,
                collection_feedback=value['collection_feedback'],watchlist=stocks,status=value['source_status'],
                **(value.get('upstream_usage') or {})))
        source = dict(cutoff=cutoff.isoformat(), hours=hours, watchlist=stocks,
                      time_policy=policy,
                      research=value['research'], executed_coverage=value.get('executed_coverage', {}),
                      provenance=provenance, search_receipts=value.get('search_receipts', []),
                      collection_feedback=value.get('collection_feedback'), open_tasks=value.get('open_tasks', []),
                      reading_coverage=value.get('reading_coverage', []),
                      budget_contract=value.get('budget_contract'), collection_completion=completion,
                      upstream_usage=value.get('upstream_usage'), source_kind='model_led_discovery')
    else:
        raise ValueError('primary_report_contract_missing')
    cutoff = local_time(source['cutoff'])
    receipt_times = []
    for receipt in source['search_receipts']:
        if source['source_kind'] == 'provided_primary_bundle':
            if receipt.get('status') in {'searched', 'searched_not_exhaustive', 'completed', 'ok'}:
                receipt_times.append(local_time(receipt['checked_at']))
        elif receipt.get('result', {}).get('status') == 'ok':
            # Discovery's started_at is conservative, never export-time now.
            receipt_times.append(cutoff)
    fresh = bool(receipt_times and cutoff <= now <= cutoff + timedelta(hours=2)
                 and now - min(receipt_times) <= timedelta(hours=2))
    from .primary_material_quality import followup_plan
    followup = followup_plan(news, source)
    context = dict(owner=OWNER, **source, input_sha256=fingerprint(value),
                   allow_external_evidence_tools=False, material_followup=followup)
    preview = dict(mode='offline_report_input', input_sha256=context['input_sha256'],
                   budget_contract=source.get('budget_contract'),collection_completion=source.get('collection_completion'),
                   report_model_budget='independent' if source.get('budget_contract')==CONTRACT else 'legacy_shared',
                   source_kind=source['source_kind'], cutoff=source['cutoff'], watchlist=source['watchlist'],
                   body_count=len(news), sources=[dict(id=n.id, title=n.title, url=n.source_url,
                       characters=len(n.content), reading_scope=reading_scope(n)) for n in news],
                   executed_coverage=source['executed_coverage'], research=source['research'],
                   declared_body_coverage=source.get('intake',{}).get('declared_body_coverage'),
                   missing_declared_lanes=source.get('intake',{}).get('missing_declared_lanes'),
                   source_receipts_present=bool(receipt_times), fresh_for_generation=fresh,
                   material_followup=followup,
                   collection_feedback=source.get('collection_feedback'),
                   open_tasks=source.get('open_tasks', []), reading_coverage=source.get('reading_coverage', []),
                   body_quality_review_required=any(row['requires_editorial_review'] for row in followup['body_quality'].values()),
                   watchlist_checked_against_app=False, quality_acceptance='pending_human_review',
                   model_requests=0, search_requests=0, tts_requests=0, app_written=False,
                   limitation='完整正文已交给报告输入，不代表模型已读完、事实正确或覆盖充分；执行前仍核App名单、暂停及预算。')
    return news, context, preview


class PrimaryReportService:
    """An explicit report-only path. No scheduler entry, publishing or pause override."""
    async def generate(self, value, expected_sha, report_type='morning'):
        # Check maintenance before DB reads, quote requests or workspace creation.
        from .model_gateway import ensure_models_enabled
        ensure_models_enabled()
        from ..config import settings
        if settings.model_http_retries != 0 or settings.report_auto_repair_enabled:
            raise RuntimeError('primary_report_requires_zero_retries_and_no_auto_repair')
        if report_type not in {'morning', 'evening'}:
            raise ValueError('primary_report_type_invalid')
        news, context, preview = prepare(value)
        if expected_sha != preview['input_sha256']:
            raise ValueError('primary_report_input_fingerprint_changed')
        if not preview['fresh_for_generation']:
            raise RuntimeError('primary_report_input_stale_or_no_search_receipts')
        if preview['body_quality_review_required']:
            raise RuntimeError('primary_report_body_quality_review_required')
        prior = (context.get('upstream_usage') or {}).get('model_calls', 0)
        if type(prior) is not int or prior < 0:
            raise RuntimeError('primary_report_upstream_usage_invalid')
        if context.get('budget_contract')==CONTRACT:
            completion=context['collection_completion']
            if (completion.get('status')!='ready_for_editorial_review' or completion.get('scope_gaps')
                    or completion.get('unresolved_tasks') or completion.get('event_review_problems')
                    or not completion.get('valid_dossier_present') or not completion.get('scope_ledger_valid')):
                raise RuntimeError('primary_report_collection_incomplete')
        elif prior >= settings.model_max_calls_per_report:
            raise RuntimeError('primary_report_shared_model_budget_exhausted')
        from .watchlist_repository import assert_watchlist_current
        signature = watchlist_signature(context['watchlist'])
        await assert_watchlist_current(signature)
        return await self._generate_once(news, context, signature, report_type)

    async def _generate_once(self, news, context, signature, report_type):
        from .model_usage import budgeted_generation
        from .research_hub import save_json
        from .episode_workspace import EpisodeWorkspace
        from .watchlist_repository import assert_watchlist_current
        from .ai_analyzer import AIAnalyzerService
        from ..models.report import ReportType

        root = Path(__file__).resolve().parents[2] / 'data'
        marker = root / 'diagnostics' / ('primary-report-' + context['input_sha256'] + '.started')
        marker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise RuntimeError('primary_report_already_attempted_no_automatic_retry') from None
        os.close(descriptor)
        workspace = EpisodeWorkspace(news, now=local_time(context['cutoff']))
        workspace.primary_input_expires_at=local_time(context['cutoff'])+timedelta(hours=2)
        state = dict(status='report_started', input_sha256=context['input_sha256'],
                     started_at=china_now().isoformat(), upstream_usage=context.get('upstream_usage'),
                     report_generated=False, app_written=False, tts_requests=0)
        save_json(workspace.path / 'primary-context.json', context)
        save_json(workspace.path / 'report-state.json', state)

        @budgeted_generation
        async def run(owner):
            from .model_usage import reserve_call
            if context.get('budget_contract')!=CONTRACT:
                for _ in range((context.get('upstream_usage') or {}).get('model_calls', 0)):
                    reserve_call()
            analyzer = AIAnalyzerService()
            return await asyncio.wait_for(analyzer.generate_daily_report(news, report_type=ReportType(report_type),
                is_trading_day=china_now().weekday() < 5, expected_watchlist=signature,
                primary_context=context, evidence_workspace=workspace), timeout=900)

        try:
            report = await run(self)
            if report is None:
                raise RuntimeError('primary_report_concurrent_generation_not_started')
            await assert_watchlist_current(signature)
            save_json(workspace.path / 'report.json', report.model_dump(mode='json'))
            state.update(status='report_generated_pending_human_review', report_generated=True,
                         report_file='report.json')
        except BaseException as error:
            state.update(status='failed_no_retry', error_type=type(error).__name__)
            raise
        finally:
            state['finished_at'] = china_now().isoformat()
            save_json(workspace.path / 'report-state.json', state)
        return dict(state, workspace=str(workspace.path))
