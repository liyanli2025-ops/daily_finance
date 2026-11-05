"""Review a complete saved writer response with the one unspent editorial request.

Default: free preview. --run --input-sha consumes at most ONE review POST.
Old result/marker and source files stay unchanged; no rewriting, search or TTS.
"""
import argparse
import asyncio
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
import sys

import run_saved_editorial_once as runner
from saved_editorial import OWNER, LIMITS, fingerprint, sha, validate_draft, citation_audit, review_messages


def prior_usage(result):
    """A failed or uncertain transport cannot be treated as an unused writer call."""
    rows = result.get('usage', [])
    if (result.get('owner') != OWNER or result.get('status') != 'failed_no_retry'
            or result.get('reason') != 'editorial_unchecked_citation'
            or result.get('completed_phases') != ['analysis'] or result.get('phase') != 'analysis'
            or result.get('model_http_attempts') != 1 or len(rows) != 1
            or result.get('reserved_output_tokens') != LIMITS['writer_output_tokens']
            or not result.get('original_files_unchanged') or not result.get('production_pause_preserved')
            or any(result.get(k) for k in ('app_written', 'tts_requests', 'search_requests', 'public_fetch_attempts', 'publication_allowed', 'content_accepted'))):
        raise ValueError('editorial_no_unspent_review')
    row = rows[0]
    size = result.get('model_input_characters')
    elapsed = result.get('elapsed_seconds')
    if (row.get('task') != 'analysis' or row.get('http_status') != 200 or row.get('transport_error')
            or row.get('max_output_tokens') != LIMITS['writer_output_tokens']
            or type(size) is not int or not 0 < size <= LIMITS['input_characters_per_request']
            or row.get('request_characters') != size
            or type(elapsed) not in (int, float) or not math.isfinite(elapsed)
            or not 0 <= elapsed < LIMITS['seconds']):
        raise ValueError('editorial_prior_usage_invalid')
    return dict(model_requests=1, output_tokens=LIMITS['review_output_tokens'],
        total_input_characters=LIMITS['total_input_characters'] - size,
        input_characters_per_request=LIMITS['input_characters_per_request'],
        seconds=LIMITS['seconds'] - elapsed, retries=0)


def load_saved(backend, source, case, current_environment):
    if source.parent != backend / 'data/diagnostics':
        raise ValueError('editorial_saved_directory_invalid')
    raw = runner.read(source / 'result.json', source)
    if sha(raw) != case['result_sha256']:
        raise ValueError('editorial_saved_result_changed')
    result = json.loads(raw)
    remaining = prior_usage(result)
    value = json.loads(runner.read(source / 'input.json', source))
    marker = json.loads(runner.read(source / 'started.json', source))
    if (value.get('owner') != OWNER or marker.get('owner') != OWNER
            or fingerprint(value) != result['input_sha256'] or marker.get('input_sha256') != result['input_sha256']
            or result['input_sha256'] != case['writer_input_sha256']):
        raise ValueError('editorial_saved_identity_changed')
    # Exact approved old tools are allowed to differ; routes, key hash, .env and backend may not.
    old_environment = value['environment']
    if (old_environment.get('tools') != case['prior_tools']
            or {k: v for k, v in old_environment.items() if k != 'tools'} !=
               {k: v for k, v in current_environment.items() if k != 'tools'}):
        raise ValueError('editorial_saved_environment_changed')
    bundle = value['bundle']
    if (fingerprint(bundle) != case['bundle_sha256'] or bundle['limits'] != LIMITS
            or result['source_cutoff'] != bundle['cutoff'] or result['upstream_usage'] != bundle['upstream_usage']):
        raise ValueError('editorial_saved_bundle_changed')
    expected = [dict(id=s['id'], text_sha256=sha(s['text'].encode()), characters=len(s['text']))
                for s in bundle['sources']]
    if result['completed_source_deliveries'] != expected:
        raise ValueError('editorial_saved_delivery_unconfirmed')
    request = json.loads(runner.read(source / 'analysis-request.json', source))
    from app.services.prompt_reading import validate_input
    if (request != value['writer_messages'] or validate_input(request, limit=LIMITS['input_characters_per_request'])
            != result['model_input_characters']):
        raise ValueError('editorial_saved_request_changed')
    response = runner.read(source / 'analysis-visible-response.json', source)
    if sha(response) != case['writer_response_sha256']:
        raise ValueError('editorial_saved_response_changed')
    text = json.loads(response)['text']
    draft = validate_draft(text, bundle, allow_unchecked=True)
    if not citation_audit(draft)['unchecked_source_ids']:
        raise ValueError('editorial_saved_failure_not_reproduced')
    if any((source / name).exists() for name in ('review-request.json', 'review-visible-response.json', 'review.json')):
        raise ValueError('editorial_review_already_attempted')
    frozen = dict(value['frozen'])
    # Direct files only. The separate continuation subdirectory is never counted as old evidence.
    for path in sorted(source.iterdir()):
        if path.is_symlink():
            raise ValueError('editorial_saved_symlink')
        if path.is_file() and path.name != 'execution.lock':
            frozen[str(path)] = sha(runner.read(path, source))
    runner.assert_frozen(frozen)
    return dict(bundle=bundle, frozen=frozen, resume=dict(prior_result=result,
        result_sha256=sha(raw), writer_text=text, remaining=remaining))


async def prepare(backend, source, case_path, base, now):
    from app.services.editorial_policy import REVIEW_POLICY
    from app.services.prompt_reading import validate_input
    from app.services.watchlist_repository import read_app_watchlist, watchlist_signature
    base.require_pause(backend)
    raw = runner.read(case_path, case_path.parent)
    environment = runner.environment(backend, base)
    value = load_saved(backend, source, json.loads(raw), environment)
    if watchlist_signature(await read_app_watchlist()) != watchlist_signature(value['bundle']['watchlist']):
        raise ValueError('editorial_app_watchlist_changed')
    draft = validate_draft(value['resume']['writer_text'], value['bundle'], allow_unchecked=True)
    size = validate_input(review_messages(value['bundle'], draft, REVIEW_POLICY),
                          limit=LIMITS['input_characters_per_request'])
    if size > value['resume']['remaining']['total_input_characters']:
        raise ValueError('editorial_budget_exhausted')
    value['frozen'][str(case_path)] = sha(raw)
    value.update(owner=OWNER, mode='review_saved_draft_only', environment=environment,
        prepared_at=now.isoformat(), expires_at=(now + timedelta(hours=2)).isoformat(),
        review_input_characters=size)
    return value


def public_preview(value, root):
    return dict(mode='free_saved_draft_review_preview', ready_to_run=True,
        input_sha256=fingerprint(value), prepared_at=value['prepared_at'], expires_at=value['expires_at'],
        source_cutoff=value['bundle']['cutoff'], historical_sample=True,
        draft_title=validate_draft(value['resume']['writer_text'], value['bundle'], allow_unchecked=True)['title'],
        sources=len(value['bundle']['sources']), review_input_characters=value['review_input_characters'],
        prior_editorial_usage=value['resume']['prior_result']['usage'], remaining=value['resume']['remaining'],
        result_directory=str(root), model_requests=0, search_requests=0, public_fetch_attempts=0, tts_requests=0,
        production_pause_preserved=True, publication_allowed=False,
        limitation='只补做原两次封套中剩余的一次审稿；旧写稿已扣费且不会重跑。新预览有效期仅用于审阅历史稿件，不更新新闻截止。显式运行消耗模型额度，3500预留输出token不是金额上限。')


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path('/var/www/finance-daily'))
    parser.add_argument('--case', type=Path, default=Path(__file__).with_name('editorial-review-case.json'))
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--input-sha')
    parser.add_argument('--export-review', type=Path)
    args = parser.parse_args()
    if args.run and (not args.input_sha or args.export_review):
        parser.error('--run requires --input-sha; export is separate')
    backend = args.project.absolute() / 'backend'
    sys.path.insert(0, str(backend))
    base = runner.module(Path(__file__).with_name('run_progress_collection_once.py'))
    source = backend / 'data/diagnostics/saved-editorial-v1'
    root = source / 'review-continuation'
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError('editorial_saved_symlink')
    # Same old lock prevents overlap with a still-running v1; old result/marker stay untouched.
    with base.single_run(source), base.single_run(root):
        if args.export_review:
            print(json.dumps(runner.export_review(root, args.export_review.absolute()), ensure_ascii=False, indent=2))
            return
        if (root / 'started.json').exists():
            print(json.dumps(dict(status='already_attempted_no_retry', result_file=str(root / 'result.json')), ensure_ascii=False))
            return
        from app.services.time_context import china_now
        now = china_now()
        if args.run:
            value = json.loads(runner.read(root / 'input.json', root))
            prepared = datetime.fromisoformat(value['prepared_at'])
            if fingerprint(value) != args.input_sha or not prepared <= now < datetime.fromisoformat(value['expires_at']):
                raise ValueError('editorial_preview_changed_or_expired')
            if await prepare(backend, source, args.case.absolute(), base, prepared) != value:
                raise ValueError('editorial_preview_inputs_changed')
            state = await runner.execute(backend, value, root, base)
            print(json.dumps(state, ensure_ascii=False, indent=2))
        else:
            value = await prepare(backend, source, args.case.absolute(), base, now)
            runner.write(root / 'input.json', value)
            preview = public_preview(value, root)
            runner.write(root / 'preview.json', preview)
            print(json.dumps(preview, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as error:
        print(json.dumps(dict(status='stopped_no_retry', error_type=type(error).__name__,
            reason=str(error) if str(error).startswith('editorial_') else 'input_or_runtime_unavailable'), ensure_ascii=False))
        sys.exit(2)
