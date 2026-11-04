"""Resume the reviewed context-size stop, preserving saved evidence and usage.

Default is free preview. --run --input-sha spends model/search usage. This is an
historic episode acceptance, not fresh news for today's publication.
"""
import argparse
from copy import deepcopy
from datetime import datetime
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
from unittest.mock import patch

SOURCE_RESULT_SHA = '3bd722ed5f53480887d39d2abcf2dd2b25c55b2fd51d6f5566352bf14cbb7a2e'
REVALIDATED_DISCOVERY_SHA = 'f799e347ad686f440832f6f4a3286fa3f6a291e3714c4bb3d2a0f2f4fbe0e269'


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def locations(backend):
    root = backend/'data/diagnostics/progress-collection-v1/resume-after-context-paging'
    return root, root/'input.json', root/'result.json', root/'started.json'


def verify_saved(result, value, marker, base):
    if (result.get('owner') != base.OWNER or result.get('status') != 'input_budget_exhausted'
            or not result.get('finished_at') or not result.get('pause_preserved')
            or result['input_sha256'] != base.fingerprint(value)
            or marker.get('owner') != base.OWNER or marker['input_sha256'] != result['input_sha256']
            or marker['started_at'] != result['started_at']
            or value['watchlist'] != result['watchlist']
            or value['budget_plan'] != result['budget_plan']
            or result['cutoff'] != result['research']['started_at']):
        raise ValueError('Saved stop/input/marker is not the reviewed collection')
    for receipt, counter in (('model_http_attempts', 'model_calls'),
            ('model_input_characters', 'model_input_characters'),
            ('reserved_output_tokens', 'reserved_output_tokens')):
        if result[receipt] != result['research'][counter]:
            raise ValueError('Transport/controller counters disagree')
    if result['search_http_attempts'] != result['research']['search_tool_calls']:
        raise ValueError('Search HTTP accounting needs separate review')
    elapsed = (datetime.fromisoformat(result['finished_at'])-
               datetime.fromisoformat(result['started_at'])).total_seconds()
    if elapsed < 0:
        raise ValueError('Historical active time invalid')
    return math.ceil(elapsed)


def restore_transport(state, old, public):
    for key in ('model_http_attempts', 'model_input_characters', 'reserved_output_tokens',
                'search_http_attempts', 'public_fetch_attempts', 'usage', 'model_exposures'):
        state[key] = deepcopy(old[key])
    state['cutoff'] = old['cutoff']
    state['resume'] = public


def proof_for(backend, base, prior):
    # Only the reviewed discovery upgrade differs from the successful v22
    # search proof. Search implementation/objectives/config/account stay bound.
    current = base.REVIEWED_RUNTIME['app/services/primary_discovery.py']
    proof = prior.evidence(backend, base, {'primary_discovery.py':
        (REVALIDATED_DISCOVERY_SHA, current)})
    old_root = backend/'data/diagnostics/progress-collection-v1/continuation-after-search-check'
    paths = [old_root/name for name in ('result.json', 'input.json', 'started.json')]
    for path in paths:
        proof['frozen'][str(path)] = prior.sha(path)
    if proof['frozen'][str(paths[0])] != SOURCE_RESULT_SHA:
        raise ValueError('Saved result is not the supplied reviewed context stop')
    result, value, marker = [json.loads(p.read_text(encoding='utf-8')) for p in paths]
    elapsed = verify_saved(result, value, marker, base)
    continuation = result['continuation']
    if (continuation['proof_sha256'] != proof['public']['proof_sha256']
            or continuation['prior_usage'] != proof['public']['prior_usage']
            or continuation['remaining_policy'] != proof['policy']):
        raise ValueError('Previous continuation envelope differs from original accounting')
    source = Path(result['workspace'])
    episodes = backend/'data/episodes'
    if source.is_symlink() or source.resolve().parent != episodes.resolve():
        raise ValueError('Source workspace is not a direct project episode')
    files = [source/'materials.json', source/'meta.json', source/'primary-discovery.json']
    files += [p for p in (source/'public-responses').rglob('*') if p.is_file()]
    if sum(p.stat().st_size for p in files) > 192*1024*1024:
        raise ValueError('Historic workspace is too large to fork automatically')
    for path in files:
        proof['frozen'][str(path)] = prior.sha(path)
    if json.loads((source/'primary-discovery.json').read_text(encoding='utf-8')) != result['research']:
        raise ValueError('Historic checkpoint differs from finished result')
    from app.services.discovery_context import body_packets
    from app.services.discovery_resume import stored_news
    materials = json.loads((source/'materials.json').read_text(encoding='utf-8'))
    news = {row['id']:stored_news(row) for row in materials}
    for packet in body_packets(result['research']):
        text, offset = packet['text'], packet['offset']
        if news[packet['id']].content[offset:offset+len(text)] != text:
            raise ValueError('Saved tool text differs from stored body')
    proof.update(result=result, elapsed=elapsed, workspace=source)
    plan = result['budget_plan']; research = result['research']
    if (elapsed >= research['limits']['seconds'] or result['model_input_characters'] >= plan['total_input_characters']
            or result['reserved_output_tokens']+research['limits']['output_tokens'] > plan['total_reserved_output_tokens']):
        raise ValueError('Original envelope cannot fund another decision')
    proof['resume_public'] = dict(
        mode='resume_saved_context_not_fresh_collection', source_result_sha256=SOURCE_RESULT_SHA,
        source_cutoff=result['cutoff'], candidates_reused=len(research['candidates']),
        stored_bodies_reused=len(materials), prior_segment_model_calls=result['model_http_attempts'],
        prior_segment_public_fetch_attempts=result['public_fetch_attempts'],
        prior_segment_active_seconds=elapsed,
        remaining_input_characters=plan['total_input_characters']-result['model_input_characters'],
        remaining_reserved_output_tokens=plan['total_reserved_output_tokens']-result['reserved_output_tokens'],
        remaining_search_http_attempts=plan['ceiling']['search_calls']-result['search_http_attempts'],
        remaining_body_urls=plan['ceiling']['body_urls']-research['body_url_calls'],
        remaining_local_read_characters=plan['ceiling']['local_read_characters']-research['local_read_characters'],
        remaining_active_seconds=plan['ceiling']['seconds']-elapsed,
        history_frozen_sha256=base.fingerprint(proof['frozen']),
        old_episode_preserved=True, old_markers_preserved=True,
        limitation='同一期历史验收，不更新截止日、不冒充今日新闻；新请求不证明资料在旧截止日前已公开。'
                    '周末参照最近交易日并保留市场时段。预览不收费，显式运行消耗模型和搜索账户额度。')
    return proof


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--project', type=Path, default=Path('/var/www/finance-daily'))
    parser.add_argument('--export-review')
    args, _ = parser.parse_known_args()
    backend = args.project.absolute()/'backend'
    os.chdir(backend)
    sys.path.insert(0, str(backend))
    base = module('saved_collection_base', 'run_progress_collection_once.py')
    prior = module('saved_collection_prior', 'continue_progress_collection.py')
    base.locations = locations
    if args.export_review or locations(backend)[3].exists():
        base.main()
        return
    from app.config import settings
    from app.services import web_research as reader, primary_discovery as discovery
    from app.services import episode_workspace as episodes
    from app.services.discovery_resume import clone_workspace
    from app.services.time_context import china_now
    proof = proof_for(backend, base, prior)
    old = proof['result']
    original_environment, original_inputs = base.environment, base.inputs
    original_discover, original_model = discovery.discover, base.AcceptanceModel
    workspace_type = episodes.EpisodeWorkspace

    def bound_environment(root):
        prior.assert_frozen(proof['frozen'])
        return dict(original_environment(root), continuation=old['continuation'],
            resume=proof['resume_public'],
            resume_runner_sha256=prior.sha(Path(__file__)),
            continuation_runner_sha256=prior.sha(Path(__file__).with_name('continue_progress_collection.py')))

    async def bound_inputs(root, now):
        value = await original_inputs(root, now)
        if value['watchlist'] != old['watchlist']:
            raise ValueError('App watchlist changed; no automatic historic continuation')
        value['budget_plan'] = old['budget_plan']
        value['prompt'] = discovery.prompt(old['watchlist'], datetime.fromisoformat(old['cutoff']),
                                          discovery.Limits(**old['budget_plan']['initial']))
        value['public_fetch_ceiling'] = 3*old['budget_plan']['ceiling']['body_urls']
        return value

    def restored_workspace(*args, **kwargs):
        prior.assert_frozen(proof['frozen'])
        workspace = clone_workspace(proof['workspace'], china_now(), workspace_type=workspace_type)
        workspace.web_search_attempts = old['search_http_attempts']
        return workspace

    class RestoredModel(original_model):
        def __init__(self, backend, value, state, workspace, guard, save):
            # Counters still describe the same segment, not a new budget.
            restore_transport(state, old, proof['resume_public'])
            super().__init__(backend, value, state, workspace, guard, save)
            save()

    async def resumed_discover(workspace, stocks, **kwargs):
        return await original_discover(workspace, stocks, resume=dict(research=old['research'],
            model_exposures=old['model_exposures'], active_seconds=proof['elapsed'],
            search_http_attempts=old['search_http_attempts']), **kwargs)

    with patch.multiple(settings, **proof['policy']), \
            patch.object(base, 'environment', bound_environment), \
            patch.object(base, 'inputs', bound_inputs), \
            patch.object(base, 'AcceptanceModel', RestoredModel), \
            patch.object(episodes, 'EpisodeWorkspace', restored_workspace), \
            patch.object(discovery, 'discover', resumed_discover), \
            patch.object(reader, 'ensure_active', prior.permit_reviewed_route(reader.ensure_active, proof)):
        base.main()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('保存资料续跑入口停止：'+type(error).__name__+
              ('：'+str(error) if isinstance(error, (ValueError,)) else '')+
              '；不自动重试，不清理旧结果。', file=sys.stderr)
        sys.exit(2)
