"""Offline audit of the reviewed finish loop; never resume or call a provider."""
import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

SOURCE_SHA='adb063b20e2aa4b9b7a04f2a47147e9346f0e28336595a3848efcd19d09fe49f'


def regular(path,root):
    if (not path.is_relative_to(root) or not path.is_file()
            or any(p.is_symlink() for p in (path,*path.parents))):
        raise ValueError('finish_replay_path_invalid')
    return path


def replay(result_path,source):
    raw=result_path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SOURCE_SHA:raise ValueError('finish_replay_source_changed')
    result=json.loads(raw);original=result['research']
    if result.get('status')!='stalled_no_new_evidence' or not result.get('finished_at'):
        raise ValueError('finish_replay_stop_changed')
    files=[result_path]+[p for p in source.rglob('*') if p.is_file()]
    before={str(p):hashlib.sha256(regular(p,source if p!=result_path else result_path.parent).read_bytes()).hexdigest()
            for p in files}
    verified=0
    for p in (source/'public-responses').glob('*.json'):
        metadata=json.loads(p.read_text());body=p.with_suffix('.body').read_bytes()
        if (metadata['file']!=p.with_suffix('.body').name or metadata['bytes']!=len(body)
                or metadata['body_sha256']!=hashlib.sha256(body).hexdigest()
                or p.stem!=hashlib.sha256(metadata['url'].encode()).hexdigest()[:24]):
            raise ValueError('finish_replay_capture_changed')
        verified+=1
    from app.services.discovery_recovery import memory_workspace
    from app.services.discovery_budget import Limits
    from app.services.discovery_feedback import build_feedback,assess_finish,complete_local_reads
    from app.services.discovery_action_plan import reject_finish,action_plan
    from app.services.discovery_completion import review_events
    from app.services.primary_discovery import decode,prompt,assemble_request
    state=deepcopy(original);workspace=memory_workspace(source,datetime.fromisoformat(result['cutoff']))
    if json.loads((source/'primary-discovery.json').read_text())!=original:
        raise ValueError('finish_replay_checkpoint_changed')
    for identifier,row in original['collection_feedback']['bodies'].items():
        if workspace.document_hashes.get(identifier)!=row['text_sha256']:
            raise ValueError('finish_replay_material_changed')
    limits=Limits(**state['limits'])
    state.pop('finish_loop_guard',None);state.pop('finish_repair',None)
    state['event_followup_tasks']=[]
    feedback=build_feedback(workspace,state,state['watchlist'],limits)
    state['collection_feedback']=feedback
    start=result['resume']['prior_segment_model_calls']
    new=[decode(raw) for raw in state['decisions'][start:]]
    if any(row['action']!='finish' for row in new):raise ValueError('finish_replay_sequence_not_finish_only')
    simulated=[]
    for number,value in enumerate(new,start+1):
        review=review_events(value,state['collection_feedback'])
        state['event_followup_tasks']=review['tasks']
        state['collection_feedback']=build_feedback(workspace,state,state['watchlist'],limits)
        assessed=assess_finish(value,state['collection_feedback'])
        assessed['problems'].extend(review['problems'])
        assessed['accepted']=assessed['accepted'] and not review['problems']
        if assessed['accepted']:
            simulated.append(dict(response=number,accepted=True));break
        guard=reject_finish(state)
        simulated.append(dict(response=number,accepted=False,problems=assessed['problems'],guard=guard))
        if guard['stop']:break
    repair=action_plan(state,state['collection_feedback'])
    before_local=state['local_read_characters']
    base=prompt(state['watchlist'],workspace.now,Limits(**state['budget_plan']['initial']))
    def room():
        try:return max(0,(limits.input_characters-len(assemble_request(base,state,limits,state['budget_plan'])[0])-4000)//2)
        except ValueError as error:
            if str(error)!='discovery_context_fixed_overhead':raise
            return 0
    # Separate local simulation: real result/counters/model exposure remain untouched.
    complete_local_reads(workspace,state,limits,room_for_text=room,checkpoint=lambda:None)
    after={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    if after!=before:raise ValueError('finish_replay_source_was_modified')
    prior_search=original['budget_plan']['ceiling']['search_calls']-result['resume']['remaining_search_http_attempts']
    return dict(mode='offline_finish_progress_replay',source_result_sha256=SOURCE_SHA,
        original_status=result['status'],snapshots_verified=verified,
        original_new_model_requests=result['model_http_attempts']-start,
        original_new_model_input_characters=sum(e['request_characters'] for e in result['model_exposures'][start:]),
        original_new_search_requests=result['search_http_attempts']-prior_search,
        original_new_public_fetch_attempts=result['public_fetch_attempts']-result['resume']['prior_segment_public_fetch_attempts'],
        original_new_action_types=[row['action'] for row in new],
        simulated_rejected_finishes=simulated,repair_plan=repair,
        local_simulation_newly_provided_characters=state['local_read_characters']-before_local,
        original_files_unchanged=True,actual_model_delivery_not_changed=True,
        model_requests=0,search_requests=0,public_fetch_attempts=0,tts_requests=0,
        production_pause_changed=False,real_collection_accepted=False,report_generated=False,
        limitation='仅对已保存的真实回复复核协议与本地补读。模拟提前停止不证明模型会选工具、补齐资料或给出合格底稿；未恢复旧收费试验，也不返还历史费用。')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,default=Path('/var/www/finance-daily'))
    parser.add_argument('--review',type=Path)
    args=parser.parse_args();backend=args.project.absolute()/'backend'
    sys.path.insert(0,str(backend))
    if args.review:
        root=args.review.absolute();result=regular(root/'result.json',root);source=root/'episode'
    else:
        root=backend/'data/diagnostics/progress-collection-v1/continue-recovered-materials'
        result=regular(root/'result.json',root)
        source=Path(json.loads(result.read_text())['workspace'])
        if source.parent!=backend/'data/episodes':raise ValueError('finish_replay_episode_invalid')
    if source.is_symlink() or not source.is_dir():raise ValueError('finish_replay_source_missing')
    print(json.dumps(replay(result,source),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
