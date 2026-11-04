"""Free saved-material recovery preview; explicit --run uses remaining usage."""
import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
from unittest.mock import patch

SOURCE_RESULT_SHA='b96ea1a0285a93c16dbfdaa2042c606ce0b18f98add12878cd1e645fe9f4d3af'
# Exact implementations used by the successful, retained one-search probe.
PROBED_SOURCE={
    'primary_discovery.py':'f799e347ad686f440832f6f4a3286fa3f6a291e3714c4bb3d2a0f2f4fbe0e269',
    'web_research.py':'d5054b15254028721a1b6891eac5906dc40d9fd68cc35c1dbb3654cd4c10fbb3',
    'search_objectives.py':'6cff95ba005013ddd5ba4e836e43712372cb7483c6a646e9c935509e5d91ac5f',
}


def module(name,filename):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(filename))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def locations(backend):
    root=backend/'data/diagnostics/progress-collection-v1/continue-recovered-materials'
    return root,root/'input.json',root/'result.json',root/'started.json'


def verify_latest(result,value,marker,old,base):
    if (result.get('owner')!=base.OWNER or result.get('status')!='failed_no_retry'
            or not result.get('finished_at') or not result.get('pause_preserved')
            or result['input_sha256']!=base.fingerprint(value)
            or marker.get('owner')!=base.OWNER or marker.get('input_sha256')!=result['input_sha256']
            or marker.get('started_at')!=result['started_at']
            or result['watchlist']!=old['watchlist'] or result['watchlist']!=value['watchlist']
            or result['budget_plan']!=old['budget_plan'] or result['budget_plan']!=value['budget_plan']
            or result['continuation']!=old['continuation']
            or result['resume']['source_result_sha256']!=value['environment']['resume']['source_result_sha256']
            or result['resume']!=value['environment']['resume']):
        raise ValueError('Recovered continuation input/marker/history mismatch')
    prior_seconds=math.ceil((datetime.fromisoformat(old['finished_at'])-
                            datetime.fromisoformat(old['started_at'])).total_seconds())
    if (result['cutoff']!=old['cutoff'] or result['resume']['source_cutoff']!=old['cutoff']
            or result['resume']['prior_segment_active_seconds']!=prior_seconds
            or result['resume']['prior_segment_model_calls']!=old['model_http_attempts']
            or result['resume']['prior_segment_public_fetch_attempts']!=old['public_fetch_attempts']
            or type(result['public_fetch_attempts']) is not int
            or result['public_fetch_attempts']<old['public_fetch_attempts']):
        raise ValueError('Recovered continuation prior usage/cutoff mismatch')
    for outer,inner in (('model_http_attempts','model_calls'),('model_input_characters','model_input_characters'),
                        ('reserved_output_tokens','reserved_output_tokens'),('search_http_attempts','search_tool_calls')):
        if type(result[outer]) is not int or result[outer]<old[outer] or result[outer]!=result['research'][inner]:
            raise ValueError('Recovered continuation usage mismatch')
    for counter in ('body_url_calls','local_read_characters'):
        if type(result['research'][counter]) is not int or result['research'][counter]<old['research'][counter]:
            raise ValueError('Recovered continuation reading usage mismatch')
    seconds=(datetime.fromisoformat(result['finished_at'])-datetime.fromisoformat(result['started_at'])).total_seconds()
    if seconds<0:raise ValueError('Recovered continuation clock invalid')
    return result['resume']['prior_segment_active_seconds']+math.ceil(seconds)


def proof_for(backend,base,prior,saved):
    # Reuse all original account/config/probe/old-envelope checks. Only these
    # three reviewed source evolutions may differ from that probe's runtime.
    evidence=prior.evidence
    changes={name:(old,base.REVIEWED_RUNTIME['app/services/'+name]) for name,old in PROBED_SOURCE.items()}
    def reviewed(root,runner,unused=None):return evidence(root,runner,changes)
    with patch.object(prior,'evidence',reviewed):
        proof=saved.proof_for(backend,base,prior)
    old=proof['result']
    root=backend/'data/diagnostics/progress-collection-v1/resume-after-context-paging'
    paths=[root/name for name in ('result.json','input.json','started.json')]
    for p in paths:proof['frozen'][str(p)]=prior.sha(p)
    if proof['frozen'][str(paths[0])]!=SOURCE_RESULT_SHA:
        raise ValueError('Source is not the reviewed duplicate-key stop')
    result,value,marker=[json.loads(p.read_text(encoding='utf-8')) for p in paths]
    spent=verify_latest(result,value,marker,old,base)
    if result['resume']['source_result_sha256']!=saved.SOURCE_RESULT_SHA:
        raise ValueError('Earlier saved-context provenance changed')
    source=Path(result['workspace'])
    if source.parent!=backend/'data/episodes' or any(p.is_symlink() for p in (source,*source.parents)):
        raise ValueError('Recovered source must be a direct episode')
    files=[source/name for name in ('meta.json','materials.json','primary-discovery.json')]
    files += [p for p in (source/'public-responses').rglob('*') if p.is_file()]
    if sum(p.stat().st_size for p in files)>192*1024*1024:raise ValueError('Recovery source too large')
    for p in files:proof['frozen'][str(p)]=prior.sha(p)
    from app.services.discovery_recovery import prepare_saved
    memory,research,recovery_sha=prepare_saved(result,source)
    plan=result['budget_plan'];ceiling=plan['ceiling']
    if (spent>=research['limits']['seconds'] or research['no_progress_turns']>=2
            or result['model_input_characters']>=plan['total_input_characters']
            or result['reserved_output_tokens']+research['limits']['output_tokens']>plan['total_reserved_output_tokens']):
        raise ValueError('Original envelope cannot fund another research decision')
    public=dict(mode='continue_recovered_saved_materials_not_fresh_news',source_result_sha256=SOURCE_RESULT_SHA,
        source_cutoff=result['cutoff'],candidates_reused=len(research['candidates']),stored_bodies_reused=len(memory.documents),
        prior_segment_model_calls=result['model_http_attempts'],prior_segment_public_fetch_attempts=result['public_fetch_attempts'],
        prior_segment_active_seconds=spent,remaining_input_characters=plan['total_input_characters']-result['model_input_characters'],
        remaining_reserved_output_tokens=plan['total_reserved_output_tokens']-result['reserved_output_tokens'],
        remaining_search_http_attempts=ceiling['search_calls']-result['search_http_attempts'],
        remaining_body_urls=ceiling['body_urls']-research['body_url_calls'],
        remaining_local_read_characters=ceiling['local_read_characters']-research['local_read_characters'],
        remaining_active_seconds=ceiling['seconds']-spent,
        recovery_state_sha256=recovery_sha,recovery=research['recovery'],
        history_frozen_sha256=base.fingerprint(proof['frozen']),old_markers_preserved=True,old_episode_preserved=True,
        limitation='免费预览仅在内存恢复快照；正文尚未新增送达模型。显式--run才收费，沿用原截止、计数与剩余额度；不生成报告或音频、不恢复生产。')
    proof.update(result=result,workspace=source,elapsed=spent,memory=memory,research=research,
                 recovery_sha=recovery_sha,resume_public=public)
    return proof


def main():
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--project',type=Path,default=Path('/var/www/finance-daily'))
    parser.add_argument('--export-review')
    args,_=parser.parse_known_args()
    backend=args.project.absolute()/'backend';os.chdir(backend);sys.path.insert(0,str(backend))
    base=module('recovered_collection_base','run_progress_collection_once.py')
    prior=module('recovered_collection_prior','continue_progress_collection.py')
    saved=module('recovered_collection_saved','resume_saved_collection.py')
    base.locations=locations
    if args.export_review or locations(backend)[3].exists():
        base.main();return
    from app.config import settings
    from app.services import primary_discovery as discovery,web_research as reader,episode_workspace as episodes
    from app.services.discovery_resume import clone_workspace
    from app.services.research_hub import save_json
    from app.services.time_context import china_now
    proof=proof_for(backend,base,prior,saved);old=proof['result']
    original_environment,original_inputs=base.environment,base.inputs
    original_discover,original_model=discovery.discover,base.AcceptanceModel
    workspace_type=episodes.EpisodeWorkspace
    def bound_environment(root):
        prior.assert_frozen(proof['frozen'])
        return dict(original_environment(root),continuation=old['continuation'],resume=proof['resume_public'],
            recovery_runner_sha256=prior.sha(Path(__file__)),
            saved_runner_sha256=prior.sha(Path(__file__).with_name('resume_saved_collection.py')),
            continuation_runner_sha256=prior.sha(Path(__file__).with_name('continue_progress_collection.py')))
    async def bound_inputs(root,now):
        value=await original_inputs(root,now)
        if value['watchlist']!=old['watchlist']:raise ValueError('App watchlist changed; no historic continuation')
        value['budget_plan']=old['budget_plan']
        value['prompt']=discovery.prompt(old['watchlist'],datetime.fromisoformat(old['cutoff']),
            discovery.Limits(**old['budget_plan']['initial']))
        value['public_fetch_ceiling']=3*old['budget_plan']['ceiling']['body_urls']
        return value
    def restored_workspace(*args,**kwargs):
        prior.assert_frozen(proof['frozen'])
        workspace=clone_workspace(proof['workspace'],china_now(),workspace_type=workspace_type)
        workspace.documents=dict(proof['memory'].documents)
        workspace.document_hashes=dict(proof['memory'].document_hashes)
        workspace.web_search_attempts=old['search_http_attempts']
        save_json(workspace.path/'materials.json',[dict(**workspace.metadata(item),text=item.content)
            for item in workspace.documents.values()])
        save_json(workspace.path/'recovery.json',proof['research']['recovery'])
        return workspace
    class RecoveredModel(original_model):
        def __init__(self,backend,value,state,workspace,guard,save):
            saved.restore_transport(state,old,proof['resume_public'])
            super().__init__(backend,value,state,workspace,guard,save);save()
    async def recovered_discover(workspace,stocks,**kwargs):
        return await original_discover(workspace,stocks,resume=dict(research=proof['research'],
            model_exposures=old['model_exposures'],active_seconds=proof['elapsed'],
            search_http_attempts=old['search_http_attempts'],recovery_state_sha256=proof['recovery_sha']),**kwargs)
    with patch.multiple(settings,**proof['policy']),patch.object(base,'environment',bound_environment), \
            patch.object(base,'inputs',bound_inputs),patch.object(base,'AcceptanceModel',RecoveredModel), \
            patch.object(episodes,'EpisodeWorkspace',restored_workspace),patch.object(discovery,'discover',recovered_discover), \
            patch.object(reader,'ensure_active',prior.permit_reviewed_route(reader.ensure_active,proof)):
        base.main()


if __name__=='__main__':
    try:main()
    except Exception as error:
        # Do not expose credential-bound preview fields or provider responses.
        print('资料恢复入口停止：'+type(error).__name__+'；保留旧结果和标记，不自动重试。',file=sys.stderr)
        sys.exit(2)
