"""New dated episode, free by default; no historic resume or marker reset."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

TRIAL='fresh-collection-v28'
OWNER='finance-fresh-collection-acceptance-v1'
HISTORY_SHA='adb063b20e2aa4b9b7a04f2a47147e9346f0e28336595a3848efcd19d09fe49f'
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
    root=backend/'data/diagnostics'/TRIAL
    return root,root/'input.json',root/'result.json',root/'started.json'


def verify_history(result,value,marker,fingerprint):
    if (result.get('owner')!='finance-progress-collection-acceptance-v1'
            or result.get('status')!='stalled_no_new_evidence' or not result.get('finished_at')
            or not result.get('pause_preserved') or result['input_sha256']!=fingerprint(value)
            or marker.get('owner')!=result['owner'] or marker.get('input_sha256')!=result['input_sha256']
            or marker.get('started_at')!=result['started_at']
            or result.get('resume')!=value.get('environment',{}).get('resume')):
        raise ValueError('Fresh episode history/input/marker mismatch')
    if result['combined_usage']['model_http_attempts']<result['model_http_attempts']:
        raise ValueError('Historical usage cannot go backwards')


def proof_for(backend,base,prior):
    # Bind the original account, configuration, successful corrected search
    # response, and its exact failure ledger. Never clear or renew that ledger.
    changes={name:(old,base.REVIEWED_RUNTIME['app/services/'+name]) for name,old in PROBED_SOURCE.items()}
    proof=prior.evidence(backend,base,changes)
    root=backend/'data/diagnostics/progress-collection-v1/continue-recovered-materials'
    paths=[root/name for name in ('result.json','input.json','started.json')]
    for path in paths:proof['frozen'][str(path)]=prior.sha(path)
    if proof['frozen'][str(paths[0])]!=HISTORY_SHA:raise ValueError('Fresh episode requires reviewed historical stop')
    result,value,marker=[json.loads(path.read_text()) for path in paths]
    verify_history(result,value,marker,base.fingerprint)
    public=dict(mode='fresh_dated_episode_not_historical_resume',historical_result_sha256=HISTORY_SHA,
        historical_cutoff=result['cutoff'],historical_usage=result['combined_usage'],
        historical_public_fetch_attempts=result['public_fetch_attempts'],
        old_markers_preserved=True,old_failure_ledger_preserved=True,
        budget_policy='new_episode_current_settings_separate_from_preserved_historical_usage',
        historical_search_probe_only=True,production_search_route_resumed=False,
        limitation='独立新一期，预览读取当前App名单与截止时间；新预算单独展示，不返还或清零旧费用。'
            '旧搜索复核仅约束当前账户和已审阅参数，不是今日联网通过。显式运行才使用新的模型和搜索额度，'
            '不自动重试、不写报告音频、不恢复生产。')
    return dict(proof,fresh_public=public)


def main():
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--project',type=Path,default=Path('/var/www/finance-daily'))
    parser.add_argument('--export-review')
    args,_=parser.parse_known_args()
    backend=args.project.absolute()/'backend';os.chdir(backend);sys.path.insert(0,str(backend))
    base=module('fresh_collection_base','run_progress_collection_once.py')
    prior=module('fresh_collection_prior','continue_progress_collection.py')
    base.TRIAL=TRIAL;base.OWNER=OWNER;base.locations=locations
    if args.export_review or locations(backend)[3].exists():base.main();return
    from app.services import web_research as reader
    proof=proof_for(backend,base,prior)
    environment,model=base.environment,base.AcceptanceModel
    def bound_environment(root):
        prior.assert_frozen(proof['frozen'])
        return dict(environment(root),fresh_trial=proof['fresh_public'],
            fresh_runner_sha256=prior.sha(Path(__file__)),
            prior_runner_sha256=prior.sha(Path(__file__).with_name('continue_progress_collection.py')),
            history_frozen_sha256=base.fingerprint(proof['frozen']))
    class FreshModel(model):
        def __init__(self,backend,value,state,workspace,guard,save):
            # A genuinely new workspace starts with zero new-episode usage.
            # Historic usage remains explicit, separate and immutable.
            state['fresh_trial']=proof['fresh_public']
            super().__init__(backend,value,state,workspace,guard,save);save()
    with patch.object(base,'environment',bound_environment),patch.object(base,'AcceptanceModel',FreshModel), \
            patch.object(reader,'ensure_active',prior.permit_reviewed_route(reader.ensure_active,proof)):
        base.main()


if __name__=='__main__':
    try:main()
    except Exception as error:
        print('新一期入口停止：'+type(error).__name__+'；保留旧结果与标记，不自动重试。',file=sys.stderr)
        sys.exit(2)
