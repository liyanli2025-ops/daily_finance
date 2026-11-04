"""Replay saved responses/HTML offline. Never resume or promote a failed trial."""
import argparse
from contextlib import ExitStack
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
from unittest.mock import patch


def regular(path, root):
    if not path.is_relative_to(root) or any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('replay_path_not_regular')
    if not path.is_file():
        raise ValueError('replay_input_missing')
    return path


def replay(review, *, result_path=None, episode_path=None):
    """review contains only result.json and episode/public-responses copies."""
    result_file=regular(result_path or review/'result.json',review)
    raw_result=result_file.read_bytes()
    result=json.loads(raw_result)
    if not result.get('finished_at'):
        raise ValueError('replay_requires_finished_run')
    state=result['research']
    cutoff=datetime.fromisoformat(state['started_at'])
    from app.services.primary_discovery import decode
    from app.services.discovery_completion import review_events
    from app.services.collection_time import policy,window,read_purpose
    from app.services.news_quality import excluded_reason,company_focus
    from app.services.web_research import parse_visible_article
    decisions=[]
    for number,text in enumerate(state['decisions'],1):
        notes=[]
        try:
            value=decode(text,normalizations=notes)
            problems=(review_events(value,state['collection_feedback'])['problems']
                      if value['action']=='finish' else [])
            decisions.append(dict(response=number,parseable=True,action=value['action'],
                                  normalizations=notes,event_problems=problems))
        except (ValueError,TypeError,KeyError) as error:
            code=str(error)
            decisions.append(dict(response=number,parseable=False,error_type=type(error).__name__,
                reason=code if re.fullmatch(r'discovery_[a-z_]+',code) else 'saved_response_invalid'))
    folder=(episode_path or review/'episode')/'public-responses'
    if folder.is_symlink() or not folder.is_dir():raise ValueError('replay_snapshot_folder_missing')
    rows=[]
    for meta_file in sorted(folder.glob('*.json')):
        regular(meta_file,review)
        if not re.fullmatch(r'[0-9a-f]{24}\.json',meta_file.name):continue
        metadata=json.loads(meta_file.read_bytes())
        body_file=regular(meta_file.with_suffix('.body'),review)
        if metadata.get('file')!=body_file.name:raise ValueError('replay_snapshot_filename_changed')
        raw=body_file.read_bytes()
        if (len(raw)!=metadata['bytes'] or hashlib.sha256(raw).hexdigest()!=metadata['body_sha256']
                or hashlib.sha256(metadata['url'].encode()).hexdigest()[:24]!=meta_file.stem):
            raise ValueError('replay_snapshot_checksum_changed')
        capture='public-responses/'+meta_file.name
        receipt=next((row for row in state['receipts'] if row['request'].get('tool')=='read'
            and row['result'].get('response_capture')==capture),None)
        if receipt is None:
            receipt=next((row for row in state['receipts'] if row['request'].get('tool')=='read'
                and state['candidates'].get(row['request'].get('candidate_id'),{}).get('url')==metadata['url']),None)
        request=receipt['request'] if receipt else dict(relation='market')
        candidate=state['candidates'].get(request.get('candidate_id'),{})
        purpose=read_purpose(request,candidate)
        source_window=window(cutoff,purpose)
        row=dict(url=metadata['url'],snapshot_sha256=metadata['body_sha256'],
            original_status=receipt['result'].get('status') if receipt else 'snapshot_only',
            original_reason=receipt['result'].get('reason') if receipt else None,
            source_window=source_window,observed_at=metadata.get('observed_at'),
            available_at_cutoff_verified=False)
        try:
            item=parse_visible_article(raw,metadata['url'],now=cutoff,hours=source_window['hours'])
            excluded=excluded_reason(item)
            scope=request.get('scope')
            company=next((stock for stock in state['watchlist'] if stock['market']+':'+stock['code']==scope),None)
            subject=company_focus(item,SimpleNamespace(**company)) if company else None
            row.update(status='excluded' if excluded else 'parsed_pending_review',title=item.title,
                body_characters=len(item.content),publication_note=item.market_impact,
                excluded_reason=excluded,requested_scope=scope,company_primary_subject_hint=subject,
                direct_company_eligible=bool(not excluded and subject) if request.get('relation')=='direct' else None)
        except (ValueError,TypeError) as error:
            code=str(error)
            row.update(status='still_not_admitted',error_type=type(error).__name__,
                reason=code if re.fullmatch(r'web_source_[a-z_]+',code) else 'parser_error')
        rows.append(row)
        if body_file.read_bytes()!=raw:raise ValueError('replay_snapshot_changed_during_review')
    if result_file.read_bytes()!=raw_result:raise ValueError('replay_result_changed_during_review')
    if not rows:raise ValueError('replay_no_saved_snapshots')
    return dict(mode='offline_collection_repairs_replay',original_status=result['status'],
        original_result_sha256=hashlib.sha256(raw_result).hexdigest(),time_policy=policy(cutoff),
        decisions=decisions,snapshots=rows,original_files_unchanged=True,
        historical_window_reassessment_only=True,actual_model_delivery_not_changed=True,
        model_requests=0,search_requests=0,public_fetch_attempts=0,tts_requests=0,
        real_collection_accepted=False,content_accepted=False,report_generated=False,
        limitation='只复核已存回复和HTML。新时窗单独展示，不改旧回执、材料池、失败/started记录或截止；不证明当时已公开、模型理解、交易时段或事实正确。')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,default=Path('/var/www/finance-daily'))
    parser.add_argument('--review-directory',type=Path,
        help='Optional exported review directory containing result.json and episode/')
    args=parser.parse_args()
    backend=args.project.absolute()/'backend'
    sys.path.insert(0,str(backend))
    # Network denial covers imports, optional extractors and parser adapters.
    with ExitStack() as stack:
        for target in ('socket.create_connection','socket.socket.connect','socket.getaddrinfo',
                       'requests.sessions.Session.request','httpx.Client.send','httpx.AsyncClient.send'):
            stack.enter_context(patch(target,side_effect=RuntimeError('offline_replay_network_forbidden')))
        if args.review_directory is not None:
            output=replay(args.review_directory.absolute())
        else:
            result_file=regular(backend/'data/diagnostics/progress-collection-v1/resume-after-context-paging/result.json',backend)
            result=json.loads(result_file.read_bytes())
            episode=Path(result['workspace'])
            if episode.parent!=backend/'data/episodes' or any(p.is_symlink() for p in (episode,*episode.parents)):
                raise ValueError('replay_episode_outside_project')
            output=replay(backend,result_path=result_file,episode_path=episode)
    print(json.dumps(output,ensure_ascii=False,indent=2))


if __name__=='__main__':
    try:main()
    except Exception as error:
        print('离线复核停止：'+type(error).__name__+'；未发起模型、搜索或网页请求。',file=sys.stderr)
        sys.exit(2)
