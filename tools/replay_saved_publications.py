"""Offline failed-page recovery using the production parser and unchanged cutoff."""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch


def replay(directory):
    from app.services.collection_time import window
    from app.services.reading_acceptance import replay as read_captures, local_time
    from app.services.primary_material_quality import review_body
    raw = (directory / 'result.json').read_bytes()
    state = json.loads(raw)
    cutoff = local_time(state['cutoff'])
    # Use the actual discovery window for this historical cutoff. Do not turn
    # a weekend replay into a wider or freshly dated news collection.
    hours = window(cutoff, 'discovery')['hours']
    previous = {Path(row['response_capture']).name: row for row in state.get('read_receipts', [])
                if row.get('response_capture')}
    recovered, reviewed = [], 0
    for folder in sorted((directory / 'evidence').glob('*/public-responses')):
        report = read_captures(folder, hours=hours)
        for row in report['rows']:
            prior = previous.get(row['capture'])
            if not prior or prior['status'] == 'ok':
                continue
            reviewed += 1
            if row.get('snapshot_cutoff') != state['cutoff']:
                raise ValueError('saved_capture_cutoff_changed')
            if row.get('url') != state['candidates'][prior['candidate_id']]['url']:
                raise ValueError('saved_capture_url_changed')
            text = row.get('text')
            if not text:
                recovered.append(dict(candidate_id=prior['candidate_id'],
                    original_reason=prior.get('reason'), status='still_unreadable',
                    reason=row.get('reason'), url=row.get('url')))
                continue
            quality = review_body(text)
            recovered.append(dict(candidate_id=prior['candidate_id'],
                original_reason=prior.get('reason'), title=row['title'], url=row['url'],
                published=row['published'], characters=len(text), text=text,
                text_sha256=row['text_sha256'], capture_sha256=row['body_sha256'],
                status='editorial_review_required' if quality['requires_editorial_review']
                    else 'parsed_pending_editorial_and_model_review',
                body_quality=quality, available_at_cutoff_verified=False,
                delivered_to_model=False, latest_session_verified=False, fact_verified=False))
    return dict(mode='offline_saved_publication_recovery', original_id=state['id'],
        original_status=state['status'], original_sha256=hashlib.sha256(raw).hexdigest(),
        original_cutoff=state['cutoff'], original_body_count=len(state['sources']),
        window_hours=hours, failed_captures_reviewed=reviewed,
        newly_parsed=sum('text' in row for row in recovered),
        unflagged_text_candidates=sum(row['status']=='parsed_pending_editorial_and_model_review' for row in recovered),
        flagged_text_candidates=sum(row['status']=='editorial_review_required' for row in recovered),
        rows=recovered, original_files_unchanged=(directory / 'result.json').read_bytes()==raw,
        model_requests=0, search_requests=0, public_fetch_attempts=0, tts_requests=0,
        production_pause_changed=False, original_material_pool_changed=False,
        content_accepted=False, automatic_resume=False,
        limitation='仅从已保存响应恢复显式发布时间和可见正文。原材料池仍为4篇，不冒称模型读过新文字；'
            '有推广须审查，评论/旧盘中稿不能变成最新收盘。失败、截止、费用和标记不变，不发起新请求。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--run-directory', type=Path, required=True)
    args = parser.parse_args()
    if args.run_directory.is_symlink() or (args.run_directory/'result.json').is_symlink():
        raise SystemExit('输入含软链，停止')
    sys.path.insert(0, str(args.project/'backend'))
    def no_network(*args, **kwargs):
        raise AssertionError('离线正文恢复禁止网络连接')
    with patch.object(socket.socket,'connect',no_network), patch.object(socket.socket,'connect_ex',no_network):
        result = replay(args.run_directory)
    for row in result['rows']:
        row.pop('text',None)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
