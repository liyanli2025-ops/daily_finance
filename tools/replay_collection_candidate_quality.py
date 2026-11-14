"""Read-only replay of actual collection failures. No --run or network actions."""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import socket
import sys
from unittest.mock import patch


def read_regular(path):
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError('replay_input_not_regular')
    return path.read_bytes()


def replay(directory):
    from bs4 import BeautifulSoup
    from app.services.edition_budget import accounted
    from app.services.edition_read_selection import patch_plan, fallback_plan, candidate_admission
    from app.services.search_objectives import metadata_blockers
    current_raw = read_regular(directory / 'result.json')
    before_raw = read_regular(directory / 'before-material-continuation.json')
    state, before = json.loads(current_raw), json.loads(before_raw)
    expected = state.get('material_continuation', {}).get('original_sha256')
    if hashlib.sha256(before_raw).hexdigest() != expected or state['id'] != before['id']:
        raise ValueError('replay_original_state_changed')
    if state['cutoff'] != before['cutoff'] or state['policy'] != before['policy']:
        raise ValueError('replay_cutoff_or_budget_changed')
    prepared = deepcopy(before)
    prepared.update(candidates=deepcopy(state['candidates']), assessment=deepcopy(state['assessment']))
    events = {r['id']: r for r in state['agenda']['events']}
    events.update(state.get('research_tasks', {}))
    assessment = prepared['assessment']
    jobs, trace = patch_plan(prepared, events, assessment, [])
    new_reads = state.get('read_receipts', [])[len(before.get('read_receipts', [])):]
    rejected = []
    for receipt in new_reads:
        cid, eid = receipt['candidate_id'], receipt['event_id']
        job = next((r for r in assessment.get('additional_searches', [])
                    if r['event_id'] == eid), receipt)
        job = dict(job, reason=receipt.get('selection_reason') or job.get('reason', ''))
        row = state['candidates'][cid]
        flags = metadata_blockers(row) + candidate_admission(state, events[eid], row, job)
        if flags:
            rejected.append(dict(candidate_id=cid, title=row['title'], url=row['url'], flags=flags,
                previous_reason=receipt.get('reason'), proposed_http_requests=0))
    alternatives = []
    for job in jobs:
        cid = job['candidate_id']
        failed = next((r for r in new_reads if r['candidate_id'] == cid and r['status'] != 'ok'), None)
        if not failed: continue
        scratch = deepcopy(prepared)
        scratch.setdefault('read_receipts', []).append(failed)
        alternate, selection = fallback_plan(scratch, events, job)
        if alternate:
            selected = state['candidates'][alternate['candidate_id']]
            alternatives.append(dict(event_id=job['event_id'], failed_candidate=cid,
                alternative_id=alternate['candidate_id'], title=selected['title'], url=selected['url'],
                max_additional_alternates=0, executed=False, body_admitted=False))
    captures = {Path(r['response_capture']).name: r for r in new_reads if r.get('response_capture')}
    snapshots = []
    cutoff = datetime.fromisoformat(state['cutoff'])
    for folder in sorted((directory / 'evidence').glob('*/public-responses')):
        for capture in folder.glob('*.json'):
            receipt = captures.get(capture.name)
            if not receipt: continue
            meta = json.loads(read_regular(capture))
            filename = meta.get('file')
            if not isinstance(filename,str) or Path(filename).name != filename or filename in {'.','..'}:
                raise ValueError('replay_capture_path_invalid')
            raw = read_regular(folder / filename)
            if (len(raw) != meta['bytes'] or hashlib.sha256(raw).hexdigest() != meta['body_sha256']
                    or meta['snapshot_cutoff'] != state['cutoff']):
                raise ValueError('replay_capture_integrity_mismatch')
            soup = BeautifulSoup(raw,'html.parser')
            match = re.search(r'公告日期\s*[:：]\s*(\d{4}-\d{2}-\d{2})',soup.get_text(' ',strip=True))
            snapshots.append(dict(candidate_id=receipt['candidate_id'], url=meta['url'],
                title=soup.title.get_text(' ',strip=True) if soup.title else None,
                snapshot_sha256=meta['body_sha256'], previous_reason=receipt.get('reason'),
                announced_day=match[1] if match else None,
                announcement_outside_company_window=(datetime.fromisoformat(match[1]) < cutoff-timedelta(
                    hours=168 if cutoff.weekday() >= 5 else 72)) if match else None,
                body_admitted=False))
    money = sum((accounted(r) for r in state['reservations']),Decimal(0))
    old_money = sum((accounted(r) for r in before['reservations']),Decimal(0))
    return dict(mode='offline_collection_candidate_quality_replay', id=state['id'],
        original_status=state['status'], stop_reason=state.get('stop_reason'), cutoff=state['cutoff'],
        actual_incremental_usage=dict(model_requests=state.get('model_http_attempts',0)-before.get('model_http_attempts',0),
            search_requests=state.get('search_http_attempts',0)-before.get('search_http_attempts',0),
            public_http_attempts=state.get('public_fetch_attempts',0)-before.get('public_fetch_attempts',0),
            candidate_delta=len(state['candidates'])-len(before['candidates']),
            body_delta=len(state['sources'])-len(before['sources']),estimated_usd=str(money-old_money)),
        accounted_total_usd=str(money), estimated_limit_usd=state['policy']['estimated_limit_usd'],
        rejected_previous_choices=rejected, simulated_alternatives=alternatives,
        simulated_jobs=[dict(candidate_id=j['candidate_id'],event_id=j['event_id'],
            one_alternative_allowed=j.get('allow_fallback',False)) for j in jobs],
        selection_trace=trace, new_snapshots=snapshots,
        original_files_unchanged=(read_regular(directory/'result.json')==current_raw
            and read_regular(directory/'before-material-continuation.json')==before_raw),
        model_requests=0,search_requests=0,public_fetch_attempts=0,tts_requests=0,
        actual_ledger_changed=False, old_markers_changed=False, continuation_resumed=False,
        manuscript_generated=False,content_accepted=False,
        limitation='只读已存结果、目录及HTML；元数据拦截可能漏判或误判，不认证来源或事实。'
        '替代候选只是本地模拟，仍未联网读取或补齐资料；不改变费用/截止/失败标记，不恢复收费任务。')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--run-directory',type=Path,required=True)
    parser.add_argument('--output',type=Path,help='可选保存这次免费回放JSON，独占创建')
    args=parser.parse_args()
    sys.path.insert(0,str(args.project/'backend'))
    def blocked(*args,**kwargs):raise AssertionError('offline replay forbids network')
    with patch.object(socket.socket,'connect',blocked),patch.object(socket.socket,'connect_ex',blocked):
        result=replay(args.run_directory)
    if args.output:
        with args.output.open('x',encoding='utf-8') as stream:
            json.dump(result,stream,ensure_ascii=False,indent=2)
    printed=dict(result)
    printed.pop('selection_trace',None)
    print(json.dumps(printed,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
