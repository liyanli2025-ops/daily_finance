"""Read-only replay of a saved paid assessment. No providers or state writes."""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch


def replay(directory):
    from app.services import edition_contract as contract
    from app.services.edition_budget import digest, accounted, number
    original = (directory / 'result.json').read_bytes()
    state = json.loads(original)
    stage = state.get('phase')
    responses = []
    for path in sorted(directory.glob('response-*.json')):
        if path.is_symlink():
            raise ValueError('saved_response_symlink')
        response = json.loads(path.read_bytes())
        if response.get('stage') == stage:
            responses.append((path, response))
    if stage not in {'assessment', 'patch_assessment'} or len(responses) != 1:
        raise ValueError('saved_assessment_response_not_unique')
    path, response = responses[0]
    assessment = contract.decode(response['text'])
    events = {row['id']: row for row in state['agenda']['events']}
    stocks = {row['market'] + ':' + row['code'] for row in state['watchlist']}
    delivered = state.get('delivered_sources', {}).get(stage, {})
    provided = {sid for sid, source in state['sources'].items()
                if delivered.get(sid) == digest(source['text'])}
    accepted, materials, validation = contract.prepare_assessment(
        assessment, events, state['sources'], stocks, provided)
    return dict(mode='offline_saved_assessment_replay', original_id=state['id'],
        original_status=state['status'], original_error=state.get('error_code'),
        original_sha256=hashlib.sha256(original).hexdigest(), response_file=path.name,
        original_usage=dict(model_http_attempts=state.get('model_http_attempts', 0),
            search_http_attempts=state.get('search_http_attempts', 0),
            public_fetch_attempts=state.get('public_fetch_attempts', 0),
            accounted_estimate_usd=str(sum((accounted(r) for r in state['reservations']), number(0)))),
        material_inventory=[dict(id=sid, title=s['title'], url=s['url'],
            body_characters=len(s['text']), original_event_ids=state['sources'][sid]['event_ids'],
            replay_event_ids=s['event_ids'], direct_scopes=s.get('direct_scopes', []))
            for sid, s in materials.items()],
        assessment=accepted, validation=validation,
        original_files_unchanged=(directory / 'result.json').read_bytes() == original,
        model_requests=0, search_requests=0, public_fetch_attempts=0, tts_requests=0,
        automatic_resume=False, text_accepted=False,
        limitation='仅离线核对原已付费回复；标题和引文匹配不等于事实成立或已独立核实。'
            '保留截止、失败、用量和暂停；不发起任何请求，不修改或续跑旧期。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--run-directory', type=Path, required=True)
    parser.add_argument('--summary', action='store_true')
    args = parser.parse_args()
    if args.run_directory.is_symlink() or (args.run_directory / 'result.json').is_symlink():
        raise SystemExit('输入路径含软链，停止')
    sys.path.insert(0, str(args.project / 'backend'))
    def no_network(*args, **kwargs):
        raise AssertionError('离线回放禁止网络连接')
    with patch.object(socket.socket, 'connect', no_network), patch.object(socket.socket, 'connect_ex', no_network):
        result = replay(args.run_directory)
    if args.summary:
        result = {key: result[key] for key in ('mode', 'original_id', 'original_status',
            'original_error', 'original_usage', 'material_inventory', 'original_files_unchanged',
            'model_requests', 'search_requests', 'public_fetch_attempts', 'tts_requests',
            'automatic_resume', 'text_accepted', 'limitation')} | dict(
                missing=result['validation']['missing'],
                event_evidence_status=[dict(id=row['id'], status=row['status']) for row in result['assessment']['events']],
                validation_issues=result['validation']['issues'],
                reused_body_event_links=len(result['validation']['reused_body_event_links']),
                restored_source_linebreaks=len(result['validation']['restored_source_quotes']))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
