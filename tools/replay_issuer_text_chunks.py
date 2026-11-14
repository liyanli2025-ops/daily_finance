"""Reassemble the saved supplier chunks without networking or changing evidence."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from types import SimpleNamespace


def safe(path):
    if any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('issuer_replay_path_symlink')
    return path


def replay(review):
    from app.services.edition_issuer_desk import IssuerDesk, BODY_URL
    state=json.loads(safe(review/'transport.json').read_bytes())
    result=json.loads(safe(review/'result.json').read_bytes())
    if result.get('status')!='stored_pending_assessment' or result.get('supplier_text_complete') is not True:
        raise ValueError('issuer_replay_completed_capture_required')
    episodes=list(safe(review/'evidence').glob('episode-*'))
    if len(episodes)!=1:
        raise ValueError('issuer_replay_workspace_ambiguous')
    folder=safe(episodes[0]/'issuer-responses')
    materials=json.loads(safe(episodes[0]/'materials.json').read_bytes())
    old=next(m for m in materials if m['id']==result['source_id'])
    art=result['art_code']
    pages={}; cache={}
    for receipt in state['issuer_http_receipts']:
        params=receipt['parameters']
        if receipt['url']!=BODY_URL or params.get('art_code')!=art:
            continue
        name=receipt.get('capture','')
        if receipt.get('status')!='received' or not re.fullmatch(r'[a-f0-9]{64}\.json',name):
            raise ValueError('issuer_replay_capture_invalid')
        raw=safe(folder/name).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=receipt['sha256']:
            raise ValueError('issuer_replay_capture_changed')
        data=json.loads(raw)
        page=params['page_index']
        if page in pages:
            raise ValueError('issuer_replay_duplicate_capture')
        pages[page]=data['data']['notice_content']
        cache[json.dumps([BODY_URL,params],sort_keys=True)]=data
    if set(pages)!=set(range(1,result['supplier_text_pages']+1)):
        raise ValueError('issuer_replay_page_missing')
    documents={}
    # This is an assembly-only view, not a mutation or migration of the pool.
    workspace=SimpleNamespace(path=episodes[0],now=datetime.fromisoformat(state['cutoff']),
        documents=documents,public_fetch_attempts=state['public_fetch_attempts'])
    workspace.add=lambda items:documents.update({item.id:item for item in items})
    desk=IssuerDesk(state,workspace,lambda:None,time.monotonic()+1)
    def cached_only(url,params,**kwargs):
        key=json.dumps([url,params],sort_keys=True)
        if key not in cache:raise ValueError('issuer_replay_cache_miss_no_network')
        return cache[key]
    desk.request=cached_only
    value=desk.read(dict(title=old['title'],url=old['url'],issuer_document=dict(
        code=result['stock']['code'],art_code=art,published_at=old['published'])))
    text=documents[value['material']['id']].body
    exact=''.join(pages[n] for n in sorted(pages)).strip()
    if text!=exact:
        raise ValueError('issuer_replay_seam_not_preserved')
    return dict(mode='offline_saved_issuer_chunks_replay',title=old['title'],
        supplier_text_pages=len(pages),chunk_characters=[len(pages[n]) for n in sorted(pages)],
        previous_stored_characters=len(old['text']),reassembled_characters=len(text),
        exact_raw_chunk_concatenation=True,reassembled_sha256=hashlib.sha256(text.encode()).hexdigest(),
        original_material_sha256=hashlib.sha256(old['text'].encode()).hexdigest(),
        original_files_unchanged=True,original_pool_migrated=False,
        cumulative_public_http_requests=state['public_fetch_attempts'],new_public_http_requests=0,
        model_requests=0,search_requests=0,tts_requests=0,
        limitation='仅对已存完整供应商文本块做组装回放；没有改写旧正文/结果/费用/暂停状态。原件页码、表格及事实未独立核验，不证明模型已经阅读或选题重要。')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',type=Path,required=True)
    args=parser.parse_args()
    safe(args.project)
    sys.path.insert(0,str(args.project/'backend'))
    review=args.project/'backend/data/diagnostics/body-acquisition-v44/pagination-completion-v45'
    print(json.dumps(replay(review),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
