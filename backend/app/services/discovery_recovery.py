"""Prepare a separate saved-material continuation, without provider requests."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace

from .collection_time import policy,window,read_purpose
from .discovery_context import body_packets,subtract
from .discovery_feedback import body_records,build_feedback
from .discovery_budget import Limits
from .discovery_resume import stored_news
from .episode_workspace import EpisodeWorkspace
from .material_roles import assess_role
from .news_quality import excluded_reason,company_focus
from .primary_discovery import decode

OWNER='finance-snapshot-recovery-v1'
PARSER_FAILURES={'web_source_time_missing','web_source_time_invalid',
    'web_source_time_outside_window','web_source_day_window_boundary_requires_review',
    'web_source_article_title_missing','web_source_article_text_too_short',
    'web_source_article_structure_missing','web_source_generic_extractor_unavailable'}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,
        separators=(',',':')).encode()).hexdigest()


def file_bytes(path,root):
    if not path.is_relative_to(root) or any(p.is_symlink() for p in (path,*path.parents)) or not path.is_file():
        raise ValueError('discovery_recovery_path_invalid')
    return path.read_bytes()


def memory_workspace(source,cutoff):
    """Use the real read/range logic in memory; never write to source.path."""
    source=Path(source)
    rows=json.loads(file_bytes(source/'materials.json',source))
    news=[stored_news(row) for row in rows]
    if len({item.id for item in news})!=len(news):raise ValueError('discovery_recovery_duplicate_material')
    workspace=object.__new__(EpisodeWorkspace)
    workspace.path=source;workspace.root=source.parent;workspace.now=cutoff
    workspace.documents={item.id:item for item in news}
    workspace.document_hashes={item.id:hashlib.sha256(item.content.encode()).hexdigest() for item in news}
    workspace.catalogue_refs={};workspace.accessed={};workspace.prepared={};workspace.confirmed={}
    workspace.journal=[];workspace.completed_rounds=0;workspace.cited_ids=set();workspace.claim_refs=[]
    return workspace


def prepare_saved(result,source,parser=None):
    """Only normalize a proven complete response with identical duplicate keys.

    Reparse captured parser failures locally; leave actual HTTP failures alone.
    New ranges are charged to the existing local budget, never new URL calls.
    """
    from .web_research import parse_visible_article,failure_reason
    original=result['research']
    if (result.get('status')!='failed_no_retry' or not result.get('finished_at')
            or original.get('status')!='failed_no_retry'
            or original.get('error_code')!='discovery_duplicate_json_key'
            or original.get('phase')!='decode_model_response'):
        raise ValueError('discovery_recovery_stop_not_supported')
    if (not original.get('decisions') or not result.get('model_exposures')
            or len(result['model_exposures'])!=original['model_calls']
            or len(original['decisions'])!=original['model_calls']
            or not result['model_exposures'][-1]['completed_response']):
        raise ValueError('discovery_recovery_complete_response_missing')
    notes=[];decision=decode(original['decisions'][-1],normalizations=notes)
    if not notes:raise ValueError('discovery_recovery_normalization_missing')
    cutoff=datetime.fromisoformat(original['started_at'])
    if result.get('cutoff')!=cutoff.isoformat():raise ValueError('discovery_recovery_cutoff_changed')
    state=deepcopy(original);workspace=memory_workspace(Path(source),cutoff)
    if json.loads(file_bytes(Path(source)/'primary-discovery.json',Path(source)))!=original:
        raise ValueError('discovery_recovery_checkpoint_changed')
    for packet in body_packets(original):
        item=workspace.documents.get(packet['id'])
        if item is None or item.content[packet['offset']:packet['offset']+len(packet['text'])]!=packet['text']:
            raise ValueError('discovery_recovery_original_text_changed')
    initial_records=body_records(workspace,original['receipts'])
    state['time_policy']=policy(cutoff)
    state['recovered_decision']=dict(value=decision,normalizations=notes,
        status='normalized_only_not_accepted',source_response_sha256=hashlib.sha256(original['decisions'][-1].encode()).hexdigest())
    rows=[];seen=set();provided=set(state['provided_ids']);charged=0
    for receipt in original['receipts']:
        request,outcome=receipt['request'],receipt['result']
        if (request.get('tool')!='read' or outcome.get('reason') not in PARSER_FAILURES
                or not outcome.get('response_capture')):continue
        capture=outcome['response_capture']
        if not re.fullmatch(r'public-responses/[0-9a-f]{24}\.json',capture):
            raise ValueError('discovery_recovery_capture_path_invalid')
        if capture in seen:continue
        seen.add(capture)
        meta_path=Path(source)/capture
        metadata=json.loads(file_bytes(meta_path,Path(source)))
        raw=file_bytes(meta_path.with_suffix('.body'),Path(source))
        candidate=state['candidates'][request['candidate_id']]
        if (metadata.get('http_status')!=200 or metadata.get('snapshot_cutoff')!=cutoff.isoformat()
                or metadata.get('file')!=meta_path.with_suffix('.body').name
                or len(raw)!=metadata.get('bytes') or hashlib.sha256(raw).hexdigest()!=metadata.get('body_sha256')
                or hashlib.sha256(metadata['url'].encode()).hexdigest()[:24]!=meta_path.stem
                or metadata['url']!=candidate['url']):
            raise ValueError('discovery_recovery_capture_identity_changed')
        row=dict(candidate_id=request['candidate_id'],url=metadata['url'],previous_reason=outcome['reason'],
                 snapshot_sha256=metadata['body_sha256'],status='not_admitted')
        purpose=read_purpose(request,candidate)
        try:item=(parser or parse_visible_article)(raw,metadata['url'],now=cutoff,hours=window(cutoff,purpose)['hours'])
        except (ValueError,TypeError) as error:
            row['reason']=failure_reason(error);rows.append(row);continue
        if item.source_url!=metadata['url']:raise ValueError('discovery_recovery_parser_url_changed')
        row.update(id=item.id,title=item.title,characters=len(item.content),source_role=assess_role(item))
        excluded=excluded_reason(item)
        if excluded:
            row.update(status='excluded',reason=excluded);rows.append(row);continue
        role=assess_role(item)
        if purpose=='released_policy' and not role['original_policy_release_allowed'] or purpose=='latest_close' and not role['latest_close_allowed']:
            purpose='commentary'
        stock=next((stock for stock in state['watchlist'] if stock['market']+':'+stock['code']==request.get('scope')),None)
        direct=bool(stock and company_focus(item,SimpleNamespace(**stock)))
        wrong_company=request.get('relation')=='direct' and not direct
        if wrong_company:purpose='commentary'
        source_window=window(cutoff,purpose)
        from .news_selection import within_window
        if not within_window(item,cutoff,source_window['hours']):
            row.update(reason='web_source_time_outside_window');rows.append(row);continue
        if item.id in workspace.documents and workspace.documents[item.id].content!=item.content:
            raise ValueError('discovery_recovery_material_collision')
        remaining=state['limits']['local_read_characters']-state['local_read_characters']
        if remaining<=0:
            row.update(reason='discovery_recovery_local_budget_exhausted');rows.append(row);continue
        workspace.documents[item.id]=item
        workspace.document_hashes[item.id]=hashlib.sha256(item.content.encode()).hexdigest()
        material=workspace.read(item.id,characters=min(4000,remaining))
        prior=initial_records.get(item.id,{}).get('ranges',[])
        cost=sum(end-start for start,end in subtract(0,len(material['text']),prior))
        state['local_read_characters']+=cost;charged+=cost
        new_request=dict(request,purpose=purpose)
        if wrong_company:new_request.update(relation='market',scope=None)
        result_row=dict(status='ok',url=metadata['url'],material=material,source_window=source_window,
            response_capture=capture,observed_at=metadata['observed_at'],reused_from='verified_saved_response',
            research_links=[] if wrong_company else deepcopy(candidate.get('discovered_by',[])),
            source_role=role,http_requests_performed=0,available_at_cutoff_verified=False,
            rejected_company_scope=request.get('scope') if wrong_company else None,
            limitation='重新解析历史200快照，未请求远端；本地提供文字不代表模型已读或事实已核实。')
        state['receipts'].append(dict(request=new_request,result=result_row,origin='verified_snapshot_recovery',
            original_request=deepcopy(request),previous_status=outcome['status']))
        provided.add(item.id)
        row.update(status='recovered_pending_research',source_window=source_window,
            direct_company_eligible=direct if request.get('relation')=='direct' else None,
            company_scope_rejected=wrong_company,local_characters_charged=cost)
        rows.append(row)
    state['provided_ids']=sorted(provided)
    state['recovery']=dict(owner=OWNER,original_status=original['status'],original_error_code=original['error_code'],
        original_phase=original['phase'],original_no_progress_turns=original['no_progress_turns'],
        source_state_sha256=fingerprint(original),rows=rows,local_characters_charged=charged,
        source_cutoff=cutoff.isoformat(),new_model_calls=0,new_search_requests=0,new_public_fetch_attempts=0)
    state.update(status='recovered_saved_materials',phase='saved_materials_prepared_not_finished')
    if charged:state['no_progress_turns']=0  # actual new text, with original counter retained above
    for key in ('dossier','selected_ids','report_input','finish_feedback','event_review_problems','event_followup_tasks',
                'error_code','error_type','status_before_acceptance_failure'):
        if key in state:state.setdefault('pre_recovery_review',{})[key]=state.pop(key)
    state['event_review_problems']=[];state['event_followup_tasks']=[]
    state['effective_search_limit']=min(state['limits']['search_calls'],state['budget_plan']['ceiling']['search_calls'])
    workspace.web_search_attempts=state['search_tool_calls']
    state['collection_feedback']=build_feedback(workspace,state,state['watchlist'],Limits(**state['limits']))
    return workspace,state,fingerprint(state)


def validate_prepared(workspace,state,expected):
    recovery=state.get('recovery',{})
    if (recovery.get('owner')!=OWNER or recovery.get('original_status')!='failed_no_retry'
            or recovery.get('original_error_code')!='discovery_duplicate_json_key'
            or state.get('status')!='recovered_saved_materials' or expected!=fingerprint(state)
            or state.get('time_policy')!=policy(workspace.now) or state.get('dossier') is not None):
        raise ValueError('discovery_recovery_prepared_state_changed')
