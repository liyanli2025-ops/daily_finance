"""Offline recovery of an already-paid v49 reply. No provider or tool execution."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil

from .edition_agenda_resume import regular,capture_files
from .edition_assessment_protocol import validate
from .edition_budget import digest
from .research_hub import save_json

CHILD='assessment-recovery-v50'


def load(directory):
    directory=Path(directory)
    original=json.loads(regular(directory/'result.json').read_text())
    response=json.loads(regular(directory/'response-2.json').read_text())
    models=[r for r in original.get('reservations',[]) if r.get('kind')=='model']
    if (original.get('status')!='failed' or original.get('phase')!='assessment'
            or original.get('error_code')!='edition_change_checks_missing'
            or original.get('assessment') or original.get('draft') or original.get('app_written')
            or original.get('tts_attempts') or original.get('model_http_attempts')!=2
            or [r['stage'] for r in models]!=['agenda','assessment']
            or len(original.get('usage',[]))!=2 or any(r.get('http_status')!=200 for r in original['usage'])
            or response.get('stage')!='assessment' or original.get('change_protocol')!='daily_changes_v1'):
        raise ValueError('edition_assessment_replay_source_not_eligible')
    from .edition_contract import decode
    reply=decode(response['text'])
    pools=list((directory/'evidence').glob('episode-*/saved-materials.json'))
    if len(pools)!=1:raise ValueError('edition_assessment_replay_pool_missing')
    rows=json.loads(regular(pools[0]).read_text())
    for sid,source in original['sources'].items():
        if source.get('candidate_id'):
            matches=[r for r in rows if r.get('id')==sid]
            if len(matches)!=1 or matches[0]['text']!=source['text']:
                raise ValueError('edition_assessment_replay_body_changed')
        delivered=original.get('delivered_sources',{}).get('assessment',{}).get(sid)
        if delivered is not None and delivered!=digest(source['text']):
            raise ValueError('edition_assessment_replay_delivered_body_changed')
    capture_files(directory,original)
    for meta in (directory/'evidence').glob('episode-*/public-responses/*.json'):
        row=json.loads(regular(meta).read_text());name=row['file']
        if not isinstance(name,str) or Path(name).name!=name:raise ValueError('edition_assessment_replay_capture_invalid')
        if hashlib.sha256(regular(meta.parent/name).read_bytes()).hexdigest()!=row['body_sha256']:
            raise ValueError('edition_assessment_replay_capture_changed')
    files={p.relative_to(directory).as_posix():hashlib.sha256(regular(p).read_bytes()).hexdigest()
        for p in directory.rglob('*') if CHILD not in p.relative_to(directory).parts and p.is_file()}
    # Directory symlinks must not escape enumeration or be copied into evidence.
    if any(p.is_symlink() for p in directory.rglob('*')):raise ValueError('edition_assessment_replay_path_invalid')
    return original,reply,files


def readable(state):
    p=state['assessment_protocol'];lines=['已付费评估的免费恢复结果','这不是成稿，也不是独立事实核验。',
        '原累计估算与失败记录保留；本次模型、搜索、网页、TTS请求均为0。','']
    titles={r['id']:r['title'] for r in state['agenda']['events']}
    for r in state['assessment']['events']:
        lines.extend([r['id']+' '+titles[r['id']]+'：'+{'ready':'证据检查暂通过（未独立核实）','missing':'缺证据','excluded':'不纳入'}[r['status']],r['reason']])
        for e in r.get('evidence',[]):lines.append('原文依据 ['+e['source_id']+'] '+e['quote'])
        lines.append('')
    lines.extend(['输出协议漏项/参数问题（全部列出）：']+[r['path']+'：'+r['code'] for r in p['issues']])
    lines.extend(['','补查参数原样保留但没有执行：',json.dumps(p['rejected_research_actions'],ensure_ascii=False,indent=2),
        '', '未完成核对：']+[r['task_id']+'：'+r['status']+'；'+r['reason'] for r in state['assessment'].get('change_checks',[])])
    lines.extend([r['candidate_id']+' / '+r['topic']+'：'+r['status'] for r in state['assessment'].get('change_topic_checks',[])])
    return '\n'.join(lines)+'\n'


def recover(directory):
    """Create a separate, private, idempotent result; never rewrite source files."""
    directory=Path(directory);original,reply,files=load(directory)
    from .edition_pipeline import source_signature
    identity=dict(owner='finance-saved-assessment-replay-v1',source_files=files,source_signature=source_signature())
    fingerprint=digest(identity);child=directory/CHILD
    if child.exists():
        state=json.loads(regular(child/'result.json').read_text())
        if state.get('assessment_recovery')!=dict(identity,input_sha256=fingerprint):
            raise ValueError('edition_assessment_replay_history_changed')
        if regular(child/'recovery.started').read_text()!=fingerprint:
            raise ValueError('edition_assessment_replay_marker_changed')
        return state,child,True
    state=deepcopy(original)
    accepted,validation=validate(state,reply,'assessment')
    # This recovery only admits incomplete replies as partial material. A full
    # release/writing transition requires a separate reviewed operation.
    state.update(status='partial_materials',stop_reason='assessment_protocol_incomplete' if not state['assessment_protocol']['complete']
        else 'offline_assessment_replayed_only',missing=validation['missing'],resume_allowed=False,
        assessment_recovery=dict(identity,input_sha256=fingerprint))
    state.setdefault('assessment_validation',[]).append(dict(stage='assessment',**validation))
    for key in ('error_type','error_code','error_http_status'):state.pop(key,None)
    child.mkdir(mode=0o700)
    # Copy immutable captures for an independently reviewable export. Original
    # result/receipt/markers remain at their original paths with original hashes.
    for name in files:
        if name=='response-2.json' or name.startswith('evidence/'):
            target=child/name;target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            shutil.copyfile(regular(directory/name),target);target.chmod(0o600)
    save_json(child/'result.json',state)
    for name,text in [('recovery.started',fingerprint),('assessment-readable.txt',readable(state)),('receipt.txt',readable(state))]:
        with os.fdopen(os.open(child/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as f:f.write(text)
    return state,child,False
