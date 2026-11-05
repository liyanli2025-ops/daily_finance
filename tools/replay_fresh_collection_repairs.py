"""Offline recheck of saved v28 material; no collection or paid execution flag."""
import argparse
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from unittest.mock import patch
import zipfile

SOURCE_SHA='413bd71898c35a17d1181e7b1b814b260c75478bda5a2a8a50e4c368cc4c2cae'


def regular(path,root):
    if (not path.is_relative_to(root) or not path.is_file()
            or any(p.is_symlink() for p in (path,*path.parents))):
        raise ValueError('fresh_replay_path_invalid')
    return path


def replay(result_path,source):
    raw=regular(result_path,result_path.parent).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=SOURCE_SHA:raise ValueError('fresh_replay_result_changed')
    result=json.loads(raw)
    if result.get('trial')!='fresh-collection-v28' or not result.get('finished_at'):
        raise ValueError('fresh_replay_unfinished_or_different_trial')
    files=[result_path]+[p for p in source.rglob('*') if p.is_file()]
    before={str(p):hashlib.sha256(regular(p,source if p!=result_path else result_path.parent).read_bytes()).hexdigest() for p in files}
    if json.loads((source/'primary-discovery.json').read_text())!=result['research']:
        raise ValueError('fresh_replay_checkpoint_changed')
    from app.services.discovery_recovery import memory_workspace
    from app.services.discovery_feedback import build_feedback,assess_finish
    from app.services.discovery_budget import Limits,resource_review,task_has_capacity,matching_proposal,expand_budget
    from app.services.primary_material_quality import review_body
    from app.services.material_roles import assess_role
    from app.services.reading_acceptance import validate_metadata
    from app.services.web_research import parse_visible_article,failure_reason
    cutoff=datetime.fromisoformat(result['cutoff']);state=deepcopy(result['research'])
    workspace=memory_workspace(source,cutoff)
    for identifier,record in state['collection_feedback']['bodies'].items():
        if workspace.document_hashes.get(identifier)!=record['text_sha256']:raise ValueError('fresh_replay_body_changed')
    plan=state['budget_plan'];limits=Limits(**state['limits']);ceiling=Limits(**plan['ceiling'])
    elapsed=(datetime.fromisoformat(result['finished_at'])-datetime.fromisoformat(result['started_at'])).total_seconds()
    feedback=build_feedback(workspace,state,state['watchlist'],limits)
    resources=resource_review(limits,ceiling,state,elapsed=elapsed,
        total_input=plan['total_input_characters'],total_output=plan['total_reserved_output_tokens'])
    feedback['resource_review']=resources
    for task in feedback['tasks']:
        if not task.get('executable') and task_has_capacity(task,resources):task.update(executable=True,requires_budget_extension=True)
    state['collection_feedback']=feedback
    finish=assess_finish(state['dossier'],feedback)
    # Demonstrate capacity mechanics using an already saved model-selected
    # tool packet, without executing or endorsing those old source choices.
    packets=[json.loads(raw) for raw in state['decisions'] if json.loads(raw)['action']=='tools']
    selected=packets[-1]['requests'];proposal=matching_proposal(state,selected,limits)
    expanded=None
    if proposal:
        _,expanded=expand_budget(limits,ceiling,state,proposal,requests=selected,elapsed=elapsed,input_characters=result['usage'][-1]['request_characters'])
    captures=[]
    for metadata_path in sorted((source/'public-responses').glob('*.json')):
        meta=json.loads(metadata_path.read_text());validate_metadata(meta)
        body_path=regular(metadata_path.with_suffix('.body'),source);body=body_path.read_bytes()
        if (meta['file']!=body_path.name or meta['bytes']!=len(body)
                or hashlib.sha256(body).hexdigest()!=meta['body_sha256']
                or metadata_path.stem!=hashlib.sha256(meta['url'].encode()).hexdigest()[:24]):
            raise ValueError('fresh_replay_capture_changed')
        receipt=next((r for r in state['receipts'] if r['request'].get('tool')=='read'
            and state['candidates'].get(r['request'].get('candidate_id'),{}).get('url')==meta['url']),None)
        row=dict(url=meta['url'],snapshot_sha256=meta['body_sha256'],
            original_status=receipt['result']['status'] if receipt else None,
            original_reason=receipt['result'].get('reason') if receipt else None,
            observed_at=meta['observed_at'],available_at_cutoff_verified=False)
        try:
            item=parse_visible_article(body,meta['url'],now=cutoff,hours=result['research']['time_policy']['hours']['discovery'])
            row.update(status='parsed_pending_review',title=item.title,characters=len(item.content),text=item.content,
                publication_note=item.market_impact,body_quality=review_body(item.content),source_role=assess_role(item))
        except (ValueError,RuntimeError) as error:
            row.update(status='not_admitted',reason=failure_reason(error))
        captures.append(row)
    after={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    if after!=before:raise ValueError('fresh_replay_original_modified')
    return dict(mode='offline_fresh_collection_repairs',source_result_sha256=SOURCE_SHA,
        original_status=result['status'],snapshots_verified=len(captures),historical_usage={
            k:result[k] for k in ('model_http_attempts','model_input_characters','reserved_output_tokens','search_http_attempts','public_fetch_attempts')},
        original_total_model_input_tokens=sum(x.get('input_tokens') or 0 for x in result['usage']),
        original_total_model_output_tokens=sum(x.get('output_tokens') or 0 for x in result['usage']),
        active_seconds=math.ceil(elapsed),resources=resources,reassessed_finish=finish,
        simulated_saved_tool_packet_expansion=expanded,tool_execution_performed=False,
        saved_body_quality={key:review_body(item.content) for key,item in workspace.documents.items()},
        saved_source_roles={key:assess_role(item) for key,item in workspace.documents.items()},captures=captures,
        original_files_unchanged=True,actual_model_delivery_not_changed=True,model_requests=0,search_requests=0,
        public_fetch_attempts=0,tts_requests=0,production_pause_changed=False,report_generated=False,
        content_accepted=False,real_collection_accepted=False,
        limitation='仅复核已保存的同一期资料；新解析文本未进入原材料池或模型，不证明模型选材、理解、时段或事实正确。保留原截止、用量和标记；没有收费运行参数。')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,default=Path('/var/www/finance-daily'))
    parser.add_argument('--review',type=Path)
    parser.add_argument('--export-review',type=Path)
    args=parser.parse_args();backend=args.project.absolute()/'backend';sys.path.insert(0,str(backend))
    if args.review:
        root=args.review.absolute();result=regular(root/'result.json',root);source=root/'episode'
    else:
        root=backend/'data/diagnostics/fresh-collection-v28';result=regular(root/'result.json',root)
        source=Path(json.loads(result.read_text())['workspace'])
        if source.parent!=backend/'data/episodes':raise ValueError('fresh_replay_episode_invalid')
    if source.is_symlink() or not source.is_dir():raise ValueError('fresh_replay_episode_missing')
    with ExitStack() as stack:
        stack.enter_context(patch('socket.socket.connect',side_effect=RuntimeError('offline_network_forbidden')))
        stack.enter_context(patch('requests.sessions.Session.request',side_effect=RuntimeError('offline_network_forbidden')))
        value=replay(result,source)
    if args.export_review:
        output=args.export_review.absolute()
        fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream,zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('offline-review.json',json.dumps(value,ensure_ascii=False,indent=2))
        value['review_file']=str(output)
    summary=dict(value,captures=[{k:v for k,v in row.items() if k!='text'} for row in value['captures']])
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
