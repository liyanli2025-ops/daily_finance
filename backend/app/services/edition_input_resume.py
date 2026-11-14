"""Explicit same-ledger continuation of a pre-HTTP input-capacity stop.

Never deletes a marker or fetches the already saved representative articles.
"""
import asyncio
from copy import deepcopy
from datetime import datetime,timedelta
import hashlib
import json
import os
import shutil
import time

from . import edition_pipeline as core, edition_contract as contract
from .edition_agenda_resume import regular,capture_files,background_pool
from .edition_inputs import assemble_request,edition_forecast
from .edition_budget import search_batch_plan,OUTPUTS
from .episode_workspace import EpisodeWorkspace
from .research_hub import save_json
from .time_context import china_now

CHILD='input-capacity-v48'


def saved(directory):
    raw=regular(directory/'result.json').read_bytes();state=json.loads(raw)
    models=[r for r in state['reservations'] if r['kind']=='model']
    if (state.get('status')!='failed' or state.get('phase')!='assessment'
            or state.get('error_code')!='edition_model_budget_exhausted'
            or not state.get('agenda_continuation') or state.get('assessment') or state.get('draft')
            or state.get('app_written') or state.get('tts_attempts')
            or len(models)!=1 or models[0]['stage']!='agenda'
            or state.get('model_http_attempts')!=1 or len(state.get('usage',[]))!=1
            or state['usage'][0].get('http_status')!=200):
        raise ValueError('edition_input_resume_source_not_eligible')
    pools=list((directory/'evidence').glob('episode-*/materials.json'))
    if len(pools)!=1:raise ValueError('edition_input_resume_pool_missing')
    pool=regular(pools[0]);rows=json.loads(pool.read_text())
    for sid,source in state['sources'].items():
        if not source.get('candidate_id'):continue
        matches=[r for r in rows if r['id']==sid]
        if len(matches)!=1 or matches[0]['text']!=source['text']:
            raise ValueError('edition_input_resume_body_changed')
    captures=capture_files(directory,state)
    for info in pool.parent.glob('public-responses/*.json'):
        data=json.loads(regular(info).read_text());name=data['file']
        from pathlib import Path
        if Path(name).name!=name:raise ValueError('edition_input_resume_capture_invalid')
        body=regular(info.parent/name)
        if hashlib.sha256(body.read_bytes()).hexdigest()!=data['body_sha256']:
            raise ValueError('edition_input_resume_capture_changed')
        captures.extend([info,body])
    _,background_proof=background_pool(directory,state)
    proof=dict(original_sha256=hashlib.sha256(raw).hexdigest(),
        material_pool_sha256=hashlib.sha256(pool.read_bytes()).hexdigest(),**background_proof)
    return deepcopy(state),proof,captures,pool


async def preview(config,directory):
    from .. import edition_once as entry
    entry.require_pause();state,proof,_,_=saved(directory)
    await entry.assert_watchlist_current(entry.watchlist_signature(state['watchlist']))
    policy,_,routes=core.environment(state['watchlist'],state['report_type'],config)
    if policy!=state['policy']:raise ValueError('edition_input_resume_policy_changed')
    if any(state['usage'][0].get(k)!=routes['analysis'][k] for k in ('provider','model')):
        raise ValueError('edition_input_resume_model_changed')
    now=datetime.fromisoformat(state['cutoff'])
    _,_,capacity=assemble_request('assessment',contract.ASSESS,core.packet(state,'assessment'),now,
        state['report_type'],policy['max_input_characters'])
    forecast=search_batch_plan(policy,edition_forecast(state,now),0,state['reservations'])
    blockers=[];models=[r for r in state['reservations'] if r['kind']=='model']
    if not capacity['fits_input']:blockers.append('edition_input_capacity_exhausted')
    if not forecast['fits_money']:blockers.append('edition_estimated_budget_exhausted')
    for row in forecast['model_stages']:
        if not row.get('fits_known_input',True):blockers.append('edition_future_input_capacity_exhausted:'+row['stage'])
    if policy['max_model_reservations']-len(models)<3:blockers.append('edition_model_reservations_insufficient')
    if policy['total_output_tokens']-sum(r['output_tokens'] for r in models)<sum(OUTPUTS[k] for k in ('assessment','writing','review')):
        blockers.append('edition_output_budget_insufficient')
    if capacity['request_characters']+sum(r['input_characters'] for r in models)>policy['total_input_characters']:
        blockers.append('edition_total_input_budget_exhausted')
    if state.get('active_seconds',0)>=config.research_max_seconds:blockers.append('edition_time_exhausted')
    identity=entry.identity(state['watchlist'],state['report_type'],config)
    from .edition_evidence_view import audit
    screening=audit(state['sources'])
    fingerprint=core.digest(dict(proof=proof,identity=identity,capacity=capacity,screening=screening))
    clock=china_now()
    return dict(mode='saved_bodies_input_capacity_preview',ready_to_run=not blockers,blockers=blockers,
        id=state['id'],prepared_at=clock.isoformat(),expires_at=(clock+timedelta(hours=2)).isoformat(),
        input_sha256=fingerprint,capacity=capacity,budget_forecast=forecast,evidence_screening=screening,
        original_cutoff=state['cutoff'],estimated_limit_usd=policy['estimated_limit_usd'],
        retained_article_bodies=sum(bool(s.get('candidate_id')) for s in state['sources'].values()),
        prior_model_http_attempts=state['model_http_attempts'],prior_search_http_attempts=state['search_http_attempts'],
        prior_public_fetch_attempts=state['public_fetch_attempts'],
        model_requests=0,search_requests=0,public_fetch_attempts=0,tts_requests=0,
        limitation='免费复核已存正文；原文完整保留，明确页面杂项只从阅读视图移出；待核和评论按用途限制。相同一期、截止与累计预算；真实内容质量仍待评估，未知补查和稿件可改变费用。'),state,proof,identity


async def continue_once(config,directory,*,run=False,input_sha=None):
    from .. import edition_once as entry
    with core.edition_lock(core.ROOT):
        entry.require_pause();child=directory/CHILD;marker=child/'continuation.started'
        if child.is_symlink():raise ValueError('edition_input_resume_path_invalid')
        if marker.exists():
            state=json.loads(regular(child/'result.json').read_text())
            proof=state['input_continuation']
            if (regular(marker).read_text()!=proof['input_sha256']
                    or hashlib.sha256(regular(directory/'result.json').read_bytes()).hexdigest()!=proof['original_sha256']):
                raise ValueError('edition_input_resume_history_changed')
            return state,child,True
        plan,state,proof,identity=await preview(config,directory)
        if not run or not plan['ready_to_run']:return plan,None,False
        if input_sha!=plan['input_sha256']:raise ValueError('edition_input_resume_preview_changed')
        if child.exists():raise ValueError('edition_input_resume_incomplete_directory')
        from .edition_release_gate import require_acceptance
        receipt=require_acceptance()
        _,_,captures,pool=saved(directory);background,_=background_pool(directory,state)
        child.mkdir(mode=0o700)
        state['input_continuation']=dict(proof,input_sha256=input_sha,release_acceptance=receipt,
            capacity=plan['capacity'],old_markers_preserved=True,old_bodies_preserved=True)
        state.update(status='prepared_saved_assessment',resume_allowed=False)
        for k in ('error_type','error_code','error_http_status','budget_block'):state.pop(k,None)
        save_json(child/'result.json',state)
        with os.fdopen(os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as stream:
            stream.write(input_sha);stream.flush();os.fsync(stream.fileno())
        pipeline=None
        try:
            ws=EpisodeWorkspace(root=child/'evidence',now=datetime.fromisoformat(state['cutoff']))
            ws.add(background)
            shutil.copyfile(pool,ws.path/'saved-materials.json')
            for capture in captures:
                target=ws.path/capture.parent.name/capture.name
                target.parent.mkdir(exist_ok=True,mode=0o700);shutil.copyfile(capture,target);target.chmod(0o600)
            ws.watchlist_signature=entry.watchlist_signature(state['watchlist'])
            ws.public_fetch_attempts=state['public_fetch_attempts'];ws.web_search_attempts=state['search_http_attempts']
            expiry=china_now()+timedelta(hours=2)
            async def check():
                entry.require_pause();await entry.assert_watchlist_current(ws.watchlist_signature)
                if entry.identity(state['watchlist'],state['report_type'],config)!=identity:
                    raise ValueError('edition_input_resume_environment_changed')
                if china_now()>expiry or time.monotonic()>=pipeline.deadline:raise ValueError('edition_time_exhausted')
                if hashlib.sha256(regular(directory/'result.json').read_bytes()).hexdigest()!=proof['original_sha256']:
                    raise ValueError('edition_input_resume_history_changed')
            pipeline=core.EditionPipeline(state,child,ws,check=check);pipeline.save()
            with entry.manual_text_scope(state['id'],config,search_proof=entry.reviewed_search_permission(config)):
                await check()
                assessment=await pipeline.call('assessment',contract.ASSESS,pipeline.packet('assessment'))
                events={r['id']:r for r in state['agenda']['events']}
                stocks={r['market']+':'+r['code'] for r in state['watchlist']}
                assessment,_=pipeline.validate_assessment(assessment,events,stocks)
                await pipeline.finish_materials(assessment,events,stocks)
        except (Exception,asyncio.CancelledError) as error:
            state.update(status='interrupted' if isinstance(error,asyncio.CancelledError) else 'failed',
                error_type=type(error).__name__,error_code=str(error) if str(error).startswith('edition_') else None)
            if pipeline:pipeline.save()
            else:save_json(child/'result.json',state)
            if isinstance(error,asyncio.CancelledError):raise
        state['manual_run_finished']=True
        if pipeline:pipeline.save()
        else:save_json(child/'result.json',state)
        return state,child,False
