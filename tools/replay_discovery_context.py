"""Read a finished private artifact and simulate context pages; never call tools.

Only copied in-memory delivery markers are advanced. Original results, source
failure ledgers, automation pause, database and runtime settings are untouched.
"""
import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,default=Path('/var/www/finance-daily'))
    parser.add_argument('--result',type=Path,default=Path('/var/www/finance-daily/backend/data/diagnostics/progress-collection-v1/continuation-after-search-check/result.json'))
    args=parser.parse_args()
    backend=args.project.absolute()/'backend'
    sys.path.insert(0,str(backend))
    if args.result.is_symlink():raise ValueError('Result must be a regular file')
    original=args.result.read_bytes();result=json.loads(original)
    if not result.get('finished_at'):raise ValueError('Do not replay an active run')
    workspace=Path(result['workspace'])
    if workspace.is_symlink() or workspace.resolve().parent!=(backend/'data/episodes').resolve():
        raise ValueError('Workspace must be a direct project episode')
    material_file=workspace/'materials.json'
    if material_file.is_symlink():raise ValueError('Materials must be a regular file')
    materials={row['id']:row for row in json.loads(material_file.read_text(encoding='utf-8'))}
    from app.services.discovery_context import body_packets,confirm,encoded,manifest,project,merged
    from app.services.primary_discovery import assemble_request,prompt,Limits
    from app.services.prompt_reading import input_characters
    state=deepcopy(result['research'])
    for packet in body_packets(state):
        text=materials[packet['id']]['text'];offset=packet['offset']
        if text[offset:offset+len(packet['text'])]!=packet['text']:
            raise ValueError('Saved tool text differs from stored source')
    # Reconstruct actual old exposure only from complete transport responses.
    delivery=dict(body_ranges={},candidate_ids=[])
    for exposure in result.get('model_exposures',[]):
        if not exposure['completed_response']:continue
        for key,ranges in exposure['body_ranges'].items():
            delivery['body_ranges'][key]=merged(delivery['body_ranges'].get(key,[])+ranges)
    state['context_delivery']=delivery
    state.pop('context_focus',None)
    limits=Limits(**state['limits']);plan=state['budget_plan']
    initial=Limits(**plan['initial'])
    base=prompt(state['watchlist'],datetime.fromisoformat(state['started_at']),initial)
    request,sent=assemble_request(base,state,limits,plan)
    request_size=input_characters([dict(role='user',content=request)])
    if request_size>limits.input_characters:raise ValueError('Next request still exceeds configured input limit')
    pages=[]
    for _ in range(256):
        request,current=assemble_request(base,state,limits,plan)
        size=input_characters([dict(role='user',content=request)])
        if size>limits.input_characters:raise ValueError('A simulated page exceeds configured input limit')
        before=encoded(state['context_delivery'])
        # Simulation only: no provider, controller tools or saved state mutation.
        confirm(state,current)
        pages.append(dict(request_characters=size,body_ranges=current['body_ranges'],
                          candidate_ids=current['candidate_ids']))
        pending=manifest(project(state,limits.input_characters//2))['counts']['unexposed_returned_characters']
        unseen=set(state['candidates'])-set(state['context_delivery']['candidate_ids'])
        if not pending and not unseen:break
        if before==encoded(state['context_delivery']):
            raise ValueError('Saved context paging made no progress; no paid retry')
    else:raise ValueError('Offline page simulation limit reached')
    if args.result.read_bytes()!=original:raise ValueError('Result changed during offline replay')
    print(json.dumps(dict(mode='offline_saved_context_replay',source_result_sha256=hashlib.sha256(original).hexdigest(),
        original_status=result['status'],original_candidates=len(state['candidates']),stored_bodies=len(materials),
        current_input_limit=limits.input_characters,next_request_characters=request_size,
        next_request_body_ranges=sent['body_ranges'],simulated_pages=pages,
        simulated_only=True,actual_model_delivery_not_changed=True,original_result_unchanged=True,
        model_requests=0,search_requests=0,public_fetch_attempts=0,tts_requests=0,
        real_collection_accepted=False,content_accepted=False,
        limitation='离线模拟只检查组装长度、分页进展和文字区间，不能证明模型理解、资料覆盖或事实正确。'),
        ensure_ascii=False,indent=2))


if __name__=='__main__':
    try:main()
    except Exception as error:
        print('离线回放停止：'+type(error).__name__+'；未请求模型或搜索。',file=sys.stderr)
        sys.exit(2)
