"""Private saved-source writing rehearsal. Default free; two POSTs at most.

Production completion/pause guards stay intact. This isolated process creates
an unpublished candidate and review, never an App report or audio. No retries.
"""
import argparse
import asyncio
from datetime import datetime, timedelta
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import zipfile

from saved_editorial import (OWNER, LIMITS, sha, fingerprint, prepare_bundle,
                            writer_messages, review_messages, validate_draft, validate_review, citation_audit)


def read(path, root, maximum=16 * 1024 * 1024):
    if (not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > maximum
            or any(part.is_symlink() for part in (path, *path.parents))):
        raise ValueError('editorial_file_missing_or_changed')
    return path.read_bytes()


def write(path, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
    os.replace(temporary, path)


def create_once(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)


def module(filename):
    spec = importlib.util.spec_from_file_location('editorial_bound_collection', filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def load_case(backend, case, review_archive):
    result_path = backend / 'data/diagnostics' / case['trial'] / 'result.json'
    result_raw = read(result_path, backend)
    if sha(result_raw) != case['source_result_sha256']:
        raise ValueError('editorial_case_result_changed')
    result = json.loads(result_raw)
    source = Path(result['workspace'])
    if source.parent != backend / 'data/episodes':
        raise ValueError('editorial_episode_location_changed')
    archive_raw = read(review_archive, review_archive.parent)
    import io
    with zipfile.ZipFile(io.BytesIO(archive_raw)) as archive:
        if archive.namelist() != ['offline-review.json'] or archive.getinfo('offline-review.json').file_size > 16 * 1024 * 1024:
            raise ValueError('editorial_review_archive_invalid')
        review_raw = archive.read('offline-review.json')
    if sha(review_raw) != case['offline_review_sha256']:
        raise ValueError('editorial_offline_review_changed')
    review = json.loads(review_raw)
    if (review['source_result_sha256'] != case['source_result_sha256']
            or result['trial'] != case['trial']
            or json.loads(read(source / 'primary-discovery.json', source)) != result['research']):
        raise ValueError('editorial_source_identity_changed')
    frozen = {str(result_path): sha(result_raw), str(review_archive): sha(archive_raw)}
    for path in sorted(source.rglob('*')):
        if path.is_symlink():
            raise ValueError('editorial_source_symlink')
        if path.is_file():
            frozen[str(path)] = sha(read(path, source))
    for row in review['captures']:
        stem = sha(row['url'].encode())[:24]
        metadata = json.loads(read(source / 'public-responses' / (stem + '.json'), source))
        body = read(source / 'public-responses' / (stem + '.body'), source, 2 * 1024 * 1024)
        if (metadata['url'] != row['url'] or metadata['body_sha256'] != sha(body)
                or row['snapshot_sha256'] != sha(body) or metadata['bytes'] != len(body)
                or metadata['snapshot_cutoff'] != result['cutoff'] or metadata['http_status'] != 200):
            raise ValueError('editorial_saved_capture_changed')
    materials = json.loads(read(source / 'materials.json', source))
    from app.services.primary_material_quality import review_body
    bundle = prepare_bundle(result, review, materials, review_body)
    return bundle, frozen


def assert_frozen(frozen):
    for name, digest in frozen.items():
        path = Path(name)
        if sha(read(path, path.parent)) != digest:
            raise ValueError('editorial_original_files_changed')


def environment(backend, base):
    from app.services.model_gateway import resolve_route
    from app.services.editorial_policy import REPORT_POLICY, REVIEW_POLICY
    from app.config import settings
    routes = {task: resolve_route(task) for task in ('analysis', 'review')}
    if settings.model_http_retries != 0:
        raise ValueError('editorial_requires_zero_retry_settings')
    if settings.model_max_calls_per_report is not None and settings.model_max_calls_per_report < 2:
        raise ValueError('editorial_report_budget_below_two_calls')
    paths = [Path(__file__).absolute(), Path(__file__).with_name('saved_editorial.py').absolute(),
             Path(__file__).with_name('run_progress_collection_once.py').absolute()]
    continuation = Path(__file__).with_name('resume_saved_editorial_review.py').absolute()
    if continuation.exists():
        paths.append(continuation)
    return dict(runtime=fingerprint(base.source_snapshot(backend)),
        tools={p.name: sha(read(p, p.parent)) for p in paths},
        routes={task: base.route_metadata(route) for task, route in routes.items()},
        connection=fingerprint([route.api_key for route in routes.values()]),
        env_file=sha(read(backend / '.env', backend)),
        editorial_policy=fingerprint([REPORT_POLICY, REVIEW_POLICY]))


async def prepare(backend, case_path, review_archive, base, now):
    from app.services.editorial_policy import REPORT_POLICY
    from app.services.watchlist_repository import read_app_watchlist, watchlist_signature
    from app.services.prompt_reading import validate_input
    base.require_pause(backend)
    case_raw = read(case_path, case_path.parent)
    case = json.loads(case_raw)
    bundle, frozen = load_case(backend, case, review_archive)
    if watchlist_signature(await read_app_watchlist()) != watchlist_signature(bundle['watchlist']):
        raise ValueError('editorial_app_watchlist_changed')
    messages = writer_messages(bundle, REPORT_POLICY)
    size = validate_input(messages, limit=LIMITS['input_characters_per_request'])
    return dict(owner=OWNER, prepared_at=now.isoformat(), expires_at=(now + timedelta(hours=2)).isoformat(),
        case_sha256=sha(case_raw), environment=environment(backend, base), frozen=frozen,
        bundle=bundle, writer_messages=messages, writer_input_characters=size)


def public_preview(value, root):
    bundle = value['bundle']
    return dict(mode='free_saved_editorial_preview', owner=OWNER, input_sha256=fingerprint(value),
        ready_to_run=True, cutoff=bundle['cutoff'], historical_sample=True,
        prepared_at=value['prepared_at'], expires_at=value['expires_at'],
        watchlist=bundle['watchlist'], sources=[{k: v for k, v in s.items() if k != 'text'} for s in bundle['sources']],
        exclusions=bundle['excluded'], unresolved_tasks=bundle['unresolved_tasks'], upstream_usage=bundle['upstream_usage'],
        routes=value['environment']['routes'], limits=LIMITS, writer_input_characters=value['writer_input_characters'],
        result_directory=str(root), model_requests=0, search_requests=0, public_fetch_attempts=0, tts_requests=0,
        app_writes=0, production_pause_preserved=True,
        limitation='显式运行才收费：最多写稿一次、审稿一次；预留输出合计10000token不是金额上限。历史样稿独立记写稿用量，不清零取材费用，不改变原取材未通过状态。无自动修稿或重跑。')


async def execute(backend, value, root, base):
    from app.services import model_gateway as gateway
    from app.services.model_usage import record_usage
    from app.services.prompt_reading import validate_input
    from app.services.editorial_policy import REVIEW_POLICY
    from app.services.watchlist_repository import assert_watchlist_current, watchlist_signature
    from app.config import settings
    import httpx
    bundle = value['bundle']
    resume = value.get('resume')
    if resume:
        # The only continuation supported is the unspent review of one complete writer response.
        from resume_saved_editorial_review import prior_usage
        prior_usage(resume['prior_result'])
    signature = watchlist_signature(bundle['watchlist'])
    assert_frozen(value['frozen'])
    base.require_pause(backend)
    await assert_watchlist_current(signature)
    if environment(backend, base) != value['environment']:
        raise ValueError('editorial_environment_changed')
    create_once(root / 'started.json', json.dumps(dict(owner=OWNER, input_sha256=fingerprint(value))).encode())
    state = dict(owner=OWNER, input_sha256=fingerprint(value), status='started', usage=[], model_http_attempts=0,
        model_input_characters=0, reserved_output_tokens=0, source_cutoff=bundle['cutoff'],
        upstream_usage=bundle['upstream_usage'], app_written=False, tts_requests=0, search_requests=0,
        public_fetch_attempts=0, production_pause_preserved=True, publication_allowed=False,
        content_accepted=False, collection_accepted=False)
    if resume:
        previous = resume['prior_result']
        state.update(model_http_attempts=previous['model_http_attempts'],
            model_input_characters=previous['model_input_characters'],
            reserved_output_tokens=previous['reserved_output_tokens'],
            completed_phases=list(previous['completed_phases']),
            completed_source_deliveries=previous['completed_source_deliveries'],
            prior_editorial_usage=previous['usage'], prior_editorial_result_sha256=resume['result_sha256'])
    started = time.monotonic()
    write(root / 'result.json', state)

    async def call(task, messages, tokens):
        assert_frozen(value['frozen'])
        base.require_pause(backend)
        await assert_watchlist_current(signature)
        if environment(backend, base) != value['environment']:
            raise ValueError('editorial_environment_changed')
        size = validate_input(messages, limit=LIMITS['input_characters_per_request'])
        remaining = LIMITS['seconds'] - (resume['prior_result']['elapsed_seconds'] if resume else 0) - (time.monotonic() - started)
        if resume and task != 'review':
            raise ValueError('editorial_resume_review_only')
        if (state['model_http_attempts'] >= LIMITS['model_requests'] or remaining <= 0
                or state['model_input_characters'] + size > LIMITS['total_input_characters']
                or state['reserved_output_tokens'] + tokens > 10000):
            raise ValueError('editorial_budget_exhausted')
        state['model_http_attempts'] += 1
        state['model_input_characters'] += size
        state['reserved_output_tokens'] += tokens
        state['phase'] = task
        write(root / (task + '-request.json'), messages)
        write(root / 'result.json', state)
        route = gateway.resolve_route(task)
        url, headers, body = gateway.request_for(route, messages, tokens)
        response, error = None, None
        request_started = time.monotonic()
        try:
            print('[文字样稿] ' + task + '：' + str(state['model_http_attempts']), flush=True)
            async with httpx.AsyncClient(timeout=min(180, remaining, settings.ai_timeout_seconds), follow_redirects=False) as client:
                response = await asyncio.wait_for(client.post(url, headers=headers, json=body), timeout=remaining)
            if response.is_error:
                raise gateway.service_error(task, response)
            payload = response.json()
            # Preserve visible partial output before completeness/schema checks.
            if route.provider in {'anthropic', 'ofox_anthropic'}:
                visible = '\n'.join(x.get('text', '') for x in payload.get('content', []) if x.get('type') == 'text')
            else:
                choices = payload.get('choices') or []
                visible = choices[0].get('message', {}).get('content', '') if choices else ''
            write(root / (task + '-visible-response.json'), dict(text=visible))
            text = gateway.completed_text(route, payload)
            state.setdefault('completed_phases', []).append(task)
            if task == 'analysis':
                state['completed_source_deliveries'] = [dict(id=s['id'],
                    text_sha256=sha(s['text'].encode()), characters=len(s['text'])) for s in bundle['sources']]
            return text
        except BaseException as failure:
            error = failure
            raise
        finally:
            state['usage'].append(record_usage(task, route, tokens, response=response, error=error,
                elapsed=time.monotonic() - request_started, request_characters=size, directory=root))
            write(root / 'result.json', state)

    try:
        raw = resume['writer_text'] if resume else await call('analysis', value['writer_messages'], LIMITS['writer_output_tokens'])
        draft = validate_draft(raw, bundle, allow_unchecked=True)
        state['citation_audit'] = citation_audit(draft)
        if resume:
            write(root / 'analysis-visible-response.json', dict(text=raw, reused_saved_response=True))
        write(root / 'draft.json', draft)
        markdown = '# 未发布的历史文字样稿\n\n资料截止：' + bundle['cutoff'] + '\n\n# ' + draft['title'] + '\n\n' + draft['body']
        markdown += '\n\n## 编辑备注\n\n' + '\n'.join('- ' + note for note in draft['editor_notes'])
        markdown += '\n\n## 来源\n\n' + '\n'.join('- [' + s['id'] + '](' + s['url'] + ') ' + s['title'] for s in bundle['sources'])
        create_once(root / 'draft.md', (markdown + '\n').encode())
        state['draft_generated'] = True
        write(root / 'result.json', state)
        raw_review = await call('review', review_messages(bundle, draft, REVIEW_POLICY), LIMITS['review_output_tokens'])
        review = validate_review(raw_review, bundle, draft)
        write(root / 'review.json', review)
        await assert_watchlist_current(signature)
        if environment(backend, base) != value['environment']:
            raise ValueError('editorial_environment_changed')
        state.update(status='sample_reviewed_pending_human' if review['verdict'] == 'pass' else 'sample_needs_revision',
                     model_review_verdict=review['verdict'])
        state['citation_audit'] = citation_audit(draft, review)
        if state['citation_audit']['unchecked_source_ids'] and review['verdict'] == 'pass':
            state['status'] = 'sample_needs_citation_review'
    except Exception as error:
        state.update(status='failed_no_retry', error_type=type(error).__name__)
        code = str(error)
        if code.startswith('editorial_') and len(code) < 120:
            state['reason'] = code
    finally:
        from app.services.time_context import china_now
        state.update(elapsed_seconds=round(time.monotonic() - started, 2), finished_at=china_now().isoformat())
        state['new_model_http_attempts'] = state['model_http_attempts'] - (resume['prior_result']['model_http_attempts'] if resume else 0)
        state['total_editorial_elapsed_seconds'] = round(state['elapsed_seconds'] + (resume['prior_result']['elapsed_seconds'] if resume else 0), 2)
        try:
            assert_frozen(value['frozen'])
            state['original_files_unchanged'] = True
        except Exception:
            state.update(original_files_unchanged=False, status='source_changed_during_rehearsal')
        state['production_pause_preserved'] = (backend / 'data/.automation-paused').is_file()
        if not state['production_pause_preserved']:
            state['status'] = 'pause_changed_during_rehearsal'
        write(root / 'result.json', state)
    return state


def export_review(root, target):
    result = json.loads(read(root / 'result.json', root))
    if result.get('status') == 'started':
        raise ValueError('editorial_still_running')
    names = ['result.json', 'input.json', 'draft.json', 'draft.md', 'review.json',
             'analysis-visible-response.json', 'review-visible-response.json']
    # input.json has connection/env fingerprints: export the public source bundle only.
    value = json.loads(read(root / 'input.json', root))
    import io
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('source-bundle.json', json.dumps(value['bundle'], ensure_ascii=False, indent=2))
        for name in names:
            if name == 'input.json':
                continue
            path = root / name
            if path.is_file():
                archive.writestr(name, read(path, root))
    create_once(target, memory.getvalue())
    return dict(mode='offline_editorial_export', file=str(target), bytes=target.stat().st_size,
                model_requests=0, search_requests=0, public_fetch_attempts=0, tts_requests=0)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path('/var/www/finance-daily'))
    parser.add_argument('--case', type=Path, default=Path(__file__).with_name('editorial-case.json'))
    parser.add_argument('--offline-review', type=Path, default=Path('/tmp/daily-finance-v29-offline-review.zip'))
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--input-sha')
    parser.add_argument('--export-review', type=Path)
    args = parser.parse_args()
    if args.run and (not args.input_sha or args.export_review):
        parser.error('--run requires a reviewed --input-sha; export is separate')
    backend = args.project.absolute() / 'backend'
    sys.path.insert(0, str(backend))
    base = module(Path(__file__).with_name('run_progress_collection_once.py'))
    root = backend / 'data/diagnostics/saved-editorial-v1'
    if args.export_review:
        with base.single_run(root):
            print(json.dumps(export_review(root, args.export_review.absolute()), ensure_ascii=False, indent=2))
        return
    from app.services.time_context import china_now
    with base.single_run(root):
        if (root / 'started.json').exists():
            print(json.dumps(dict(status='already_attempted_no_retry', result_file=str(root / 'result.json')), ensure_ascii=False))
            return
        now = china_now()
        if args.run:
            value = json.loads(read(root / 'input.json', root))
            if fingerprint(value) != args.input_sha or not (datetime.fromisoformat(value['prepared_at']) <= now < datetime.fromisoformat(value['expires_at'])):
                raise ValueError('editorial_preview_changed_or_expired')
            rebuilt = await prepare(backend, args.case.absolute(), args.offline_review.absolute(), base,
                                     datetime.fromisoformat(value['prepared_at']))
            if rebuilt != value:
                raise ValueError('editorial_preview_inputs_changed')
            state = await execute(backend, value, root, base)
            print(json.dumps(state, ensure_ascii=False, indent=2))
        else:
            value = await prepare(backend, args.case.absolute(), args.offline_review.absolute(), base, now)
            write(root / 'input.json', value)
            preview = public_preview(value, root)
            write(root / 'preview.json', preview)
            print(json.dumps(preview, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as error:
        print(json.dumps(dict(status='stopped_no_retry', error_type=type(error).__name__,
            reason=str(error) if str(error).startswith('editorial_') else 'input_or_runtime_unavailable'), ensure_ascii=False))
        sys.exit(2)
