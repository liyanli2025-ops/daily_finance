"""One explicit text acceptance using the production EditionPipeline and ledger.

Default: local preview. --run accepts the supplied estimate for this process only.
Never removes the pause, changes .env, publishes to the App, or synthesizes audio.
"""
import argparse
import asyncio
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import time
import uuid
import zipfile

from .config import settings
from .edition_preflight import scenario_config
from .services import edition_pipeline as core
from .services.edition_budget import accounted, number
from .services.edition_manual import manual_text_scope, reviewed_search_permission
from .services.episode_workspace import EpisodeWorkspace
from .services.model_gateway import MODEL_PAUSE_FILE
from .services.research_hub import save_json
from .services.time_context import china_now
from .services.watchlist_repository import assert_watchlist_current, watchlist_signature
from .services.web_research import search_availability


def accepted_config(prices, maximum, original=settings):
    limit = number(maximum)
    if limit <= 0 or original.model_http_retries or original.report_auto_repair_enabled:
        raise ValueError('edition_manual_budget_or_retry_invalid')
    config = scenario_config(original, prices)
    return config.model_copy(update=dict(edition_estimated_limit_usd=str(limit),
        edition_estimate_accepted=True, edition_audio_enabled=False,
        research_web_search_enabled=True))


def require_pause():
    if not MODEL_PAUSE_FILE.is_file() or MODEL_PAUSE_FILE.is_symlink():
        raise RuntimeError('edition_manual_requires_existing_pause')


def identity(stocks, report_type, config):
    require_pause()
    _, signature, _ = core.environment(stocks, report_type, config=config)
    env = Path(__file__).parent.parent / '.env'
    if env.is_symlink():
        raise ValueError('edition_manual_env_symlink')
    return core.digest(dict(environment=signature,
        env_file=hashlib.sha256(env.read_bytes()).hexdigest() if env.is_file() else None,
        operator=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        reviewed_search=reviewed_search_permission(config)))


async def preview(config, report_type='morning'):
    require_pause()
    result = await core.preflight(report_type, config=config)
    result['blockers'] = [b for b in result['blockers'] if b != 'maintenance_paused']
    proof = reviewed_search_permission(config)
    availability = search_availability(config=config, manual_proof=proof)
    if not availability['available']:
        result['blockers'].append(availability['reason'])
    result.update(mode='manual_text_edition_preview',
        ready_to_run=not result['blockers'], search_route=availability,
        execution_sha256=identity(result['watchlist'], report_type, config),
        estimated_limit_usd=str(number(config.edition_estimated_limit_usd)),
        production_pause_preserved=True, live_settings_changed=False,
        reviewed_search_contract_reused=proof is not None,
        tts_requests=0, app_publication=False,
        limitation='仅本进程单次文字验收；模型与搜索合用估算预算，不是服务商硬账单上限。'
        '未知新资料可能使后续预留不足并停止，保留已有资料、稿件及用量，不自动重试。')
    return result


def summary(state, directory):
    reservations = state.get('reservations', [])
    return dict(mode='manual_text_edition_result', id=state['id'], status=state['status'],
        cutoff=state['cutoff'], estimated_limit_usd=state['policy']['estimated_limit_usd'],
        model_reservations=sum(r['kind'] == 'model' for r in reservations),
        model_http_attempts=state.get('model_http_attempts', 0),
        search_http_attempts=state.get('search_http_attempts', 0),
        public_fetch_attempts=state.get('public_fetch_attempts', 0),
        candidates=len(state.get('candidates', {})), bodies=len(state.get('sources', {})),
        accounted_estimate_usd=str(sum((accounted(r) for r in reservations), number(0))),
        original_reservations_usd=str(sum((number(r['estimated_usd']) for r in reservations), number(0))),
        events=[dict(id=e['id'], title=e['title'], importance=e['importance'],
                     evidence_status=next((r['status'] for r in state.get('assessment', {}).get('events', [])
                         if r['id'] == e['id']), 'not_assessed'),
                     fact_verified=False)
                for e in state.get('agenda', {}).get('events', [])],
        missing=state.get('missing'), missing_assessed='assessment' in state,
        error_type=state.get('error_type'),
        error_code=state.get('error_code'), error_http_status=state.get('error_http_status'),
        draft_saved=bool(state.get('draft')), text_accepted=state['status'] == 'reviewed_text',
        tts_requests=0, app_written=False, pause_preserved=MODEL_PAUSE_FILE.is_file(),
        result_file=str(directory / 'result.json'), receipt_file=str(directory / 'receipt.txt'),
        limitation='用量核算不是服务商账单；测试通过不代表真实覆盖充分。失败与费用记录保留，不自动续跑。')


def export_review(directory, target):
    target = Path(target)
    if target.is_symlink():
        raise ValueError('edition_export_symlink')
    result_raw = (directory / 'result.json').read_bytes()
    if target.exists():
        with zipfile.ZipFile(target) as archive:
            if archive.read('result.json') != result_raw:
                raise ValueError('edition_export_existing_other_result')
        return target
    files = list(directory.rglob('*'))
    if any(p.is_symlink() for p in files):
        raise ValueError('edition_export_source_symlink')
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream, zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            if path.is_file():
                archive.write(path, path.relative_to(directory))
    return target


async def run_once(config, report_type='morning', root=core.ROOT):
    root = Path(root)
    with core.edition_lock(root):
        require_pause()
        marker = root / (china_now().date().isoformat() + '-' + report_type + '.started')
        if marker.is_symlink():
            raise ValueError('edition_manual_marker_symlink')
        if marker.exists():
            identifier = marker.read_text().strip()
            directory = core.run_path(identifier, root)
            return core.load_state(identifier, root), directory, True
        planned = await preview(config, report_type)
        if not planned['ready_to_run']:
            return planned, None, False
        if identity(planned['watchlist'], report_type, config) != planned['execution_sha256']:
            raise RuntimeError('edition_manual_environment_changed')
        identifier = 'edition-' + uuid.uuid4().hex
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(identifier)
        directory = core.run_path(identifier, root)
        directory.mkdir(mode=0o700)
        now = china_now()
        state = dict(id=identifier, owner='finance-unified-edition-v1', status='prepared',
            cutoff=now.isoformat(), report_type=report_type, watchlist=planned['watchlist'],
            policy=planned['policy'], environment_sha256=planned['environment_sha256'],
            execution_sha256=planned['execution_sha256'], manual_text_only=True,
            reservations=[], usage=[], candidates={}, sources={}, app_written=False, research_protocol=core.PROTOCOL, change_protocol='daily_changes_v1')
        save_json(directory / 'result.json', state)
        workspace = EpisodeWorkspace(root=directory / 'evidence', now=now)
        workspace.watchlist_signature = watchlist_signature(state['watchlist'])
        pipeline = None

        async def check():
            require_pause()
            await assert_watchlist_current(workspace.watchlist_signature)
            if identity(state['watchlist'], report_type, config) != state['execution_sha256']:
                raise RuntimeError('edition_manual_environment_changed')
            if china_now() > datetime.fromisoformat(state['cutoff']) + timedelta(hours=2):
                raise RuntimeError('edition_expired')
            if time.monotonic() >= pipeline.deadline:
                raise RuntimeError('edition_time_exhausted')

        pipeline = core.EditionPipeline(state, directory, workspace, check=check)
        pipeline.save()
        print('开始单次文字验收；模型和搜索共用估算预算 $' + state['policy']['estimated_limit_usd']
              + '；过程记录：' + str(directory / 'receipt.txt'), flush=True)
        with manual_text_scope(identifier, config, search_proof=reviewed_search_permission(config)):
            try:
                await pipeline.execute()
            except Exception:
                # execute has already saved visible responses, failure and usage.
                # Return/export that state; repeating --run never retries it.
                pass
        state['resume_allowed'] = False
        state['manual_run_finished'] = True
        pipeline.save()
        return state, directory, False


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prices', type=Path, required=True)
    parser.add_argument('--max-usd', required=True)
    parser.add_argument('--report-type', choices=('morning', 'evening'), default='morning')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--continue-id', help='复用同一期失败材料和预算；不重新开期')
    parser.add_argument('--export', type=Path, help='导出本次文字、完整来源、缺口及用量，不联网')
    args = parser.parse_args()
    config = accepted_config(json.loads(args.prices.read_text()), args.max_usd)
    if args.continue_id:
        from .services.edition_continuation import continue_once
        state, directory, reused = await continue_once(config, args.continue_id, run=args.run)
        if directory is None:
            print(json.dumps(state, ensure_ascii=False, indent=2)); return
        result = summary(state, directory)
        result['existing_continuation_reused_no_new_requests'] = reused
        if args.export:
            result['review_zip'] = str(export_review(directory, args.export))
        print(json.dumps(result, ensure_ascii=False, indent=2)); return
    if not args.run:
        print(json.dumps(await preview(config, args.report_type), ensure_ascii=False, indent=2))
        return
    state, directory, reused = await run_once(config, args.report_type)
    if directory is None:
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return
    result = summary(state, directory)
    result['existing_result_reused_no_new_requests'] = reused
    if args.export:
        result['review_zip'] = str(export_review(directory, args.export))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
