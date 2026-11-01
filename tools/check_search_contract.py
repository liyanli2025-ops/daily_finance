"""Default: replay saved responses and preview one revised search, zero network I/O.

--run-search --input-sha explicitly authorizes one Tavily diagnostic attempt after
a reviewed request change. It never calls a model or removes any failure marker.
"""
import argparse
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import sys

OWNER = 'finance-search-contract-diagnostic-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()


def pause_required(backend):
    flag = backend / 'data/.automation-paused'
    if not flag.is_file() or flag.is_symlink():
        raise ValueError('Existing maintenance pause is required')


def prepare(backend, now):
    from app.config import settings
    from app.services.primary_discovery import decode
    from app.services.web_research import search_request
    pause_required(backend)
    prior = backend / 'data/diagnostics/progress-collection-v1/result.json'
    raw = prior.read_bytes()
    previous = json.loads(raw)
    if previous.get('owner') != 'finance-progress-collection-acceptance-v1' or not previous.get('finished_at'):
        raise ValueError('Expected a completed original acceptance result')
    failures = [receipt for receipt in previous['research']['receipts']
        if receipt['request'].get('tool') == 'search'
        and receipt['result'].get('status') == 'failed' and receipt['result'].get('reason') == 'http_400']
    if len(failures) != 1:
        raise ValueError('Expected one reviewed HTTP400 search failure; do not guess a retry scope')
    key = settings.research_web_search_api_key
    if not key or not key.get_secret_value().strip():
        raise ValueError('Search account is not configured')
    request = failures[0]['request']
    payload, _ = search_request(request['query'], request.get('purpose', 'discovery'), now,
                                topic=request.get('topic', 'news'))
    old, _ = search_request(request['query'], request.get('purpose', 'discovery'),
                           datetime.fromisoformat(previous['cutoff']), topic=request.get('topic', 'news'))
    old['time_range'] = 'week'
    if 'time_range' in payload or not {'start_date', 'end_date'} <= set(payload):
        raise ValueError('Expected the reviewed absolute-window request change')
    parsed = []
    for index, response in enumerate(previous['research']['decisions'], 1):
        try:
            data = decode(response)
            parsed.append(dict(response=index, parseable=True, action=data['action']))
        except ValueError as error:
            parsed.append(dict(response=index, parseable=False, error_type=type(error).__name__))
    source = {}
    for name in ('primary_discovery.py', 'web_research.py', 'search_objectives.py'):
        source[name] = hashlib.sha256((backend / 'app/services' / name).read_bytes()).hexdigest()
    env_file = backend / '.env'
    return dict(owner=OWNER, prepared_at=now.isoformat(),
        expires_at=(now+timedelta(hours=2)).isoformat(),
        prior_result_sha256=hashlib.sha256(raw).hexdigest(),
        credential_fingerprint=hashlib.sha256(key.get_secret_value().encode()).hexdigest(),
        env_file_sha256=hashlib.sha256(env_file.read_bytes()).hexdigest() if env_file.is_file() else None,
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), source_sha256=source,
        previous_request_parameters=old, revised_request_parameters=payload,
        saved_response_replay=parsed,
        previous_actual_usage=dict(model_http_attempts=previous['model_http_attempts'],
            search_http_attempts=previous['search_http_attempts'],
            public_fetch_attempts=previous['public_fetch_attempts']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path('/var/www/finance-daily'))
    parser.add_argument('--run-search', action='store_true')
    parser.add_argument('--input-sha')
    args = parser.parse_args()
    if args.run_search != bool(args.input_sha):
        parser.error('--run-search must be paired with --input-sha')
    backend = args.project.absolute() / 'backend'
    if not (backend / 'app/config.py').is_file():
        parser.error('Project backend not found')
    os.chdir(backend)
    sys.path.insert(0, str(backend))
    from app.config import settings
    from app.services.research_hub import save_json
    from app.services.time_context import china_now
    root = backend / 'data/diagnostics/search-contract-diagnostic-v1'
    input_file, result_file, marker = root / 'input.json', root / 'result.json', root / 'started.json'
    if marker.exists():
        print(json.dumps(dict(mode='already_attempted_no_retry', result_file=str(result_file)), indent=2))
        return
    now = china_now()
    if not args.run_search:
        value = prepare(backend, now)
        if input_file.is_file():
            old = json.loads(input_file.read_text(encoding='utf-8'))
            prepared = datetime.fromisoformat(old['prepared_at'])
            if prepared <= now < datetime.fromisoformat(old['expires_at']) and old == prepare(backend, prepared):
                value = old
        save_json(input_file, value)
        public = {key: value[key] for key in ('prepared_at', 'expires_at', 'saved_response_replay',
            'previous_actual_usage', 'previous_request_parameters', 'revised_request_parameters')}
        public.update(mode='free_saved_response_replay_and_search_preview', input_sha256=digest(value),
            model_requests=0, search_requests=0, public_fetch_attempts=0, tts_requests=0,
            max_search_attempts_if_explicitly_run=1, retries=0,
            production_search_route_resumed=False,
            limitation='离线回放不执行其中工具；参数收敛不是HTTP400根因已确定。'
                '只有--run-search与本次指纹才显式复核已失败路径，可能消耗一次搜索额度，'
                '不会调用模型或解除旧停用记录。')
        print(json.dumps(public, ensure_ascii=False, indent=2))
        return
    value = json.loads(input_file.read_text(encoding='utf-8'))
    prepared = datetime.fromisoformat(value['prepared_at'])
    if (value.get('owner') != OWNER or digest(value) != args.input_sha
            or not prepared <= now < datetime.fromisoformat(value['expires_at'])
            or value != prepare(backend, prepared)):
        raise ValueError('Preview expired or changed; no request sent')
    # This explicit revalidation deliberately leaves the original account block,
    # URL failures and collection marker untouched, even when the probe succeeds.
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(dict(owner=OWNER, input_sha256=args.input_sha, started_at=now.isoformat()), stream)
    state = dict(owner=OWNER, status='started', model_requests=0, search_http_attempts=0,
        public_fetch_attempts=0, tts_requests=0, production_search_route_resumed=False)
    save_json(result_file, state)
    response = None
    try:
        import requests
        from app.services.web_research import search_error_diagnostics
        pause_required(backend)
        state['search_http_attempts'] = 1
        save_json(result_file, state)
        response = requests.post('https://api.tavily.com/search',
            headers={'Authorization': 'Bearer ' + settings.research_web_search_api_key.get_secret_value()},
            json=value['revised_request_parameters'], timeout=15, allow_redirects=False)
        state['diagnostics'] = search_error_diagnostics(response, value['revised_request_parameters'])
        response.raise_for_status()
        data = response.json()
        if response.status_code != 200 or not isinstance(data, dict) or not isinstance(data.get('results'), list):
            raise ValueError('Search response shape invalid')
        state.update(status='search_http_accepted_pending_review', metadata_results=len(data['results']))
    except Exception as error:
        state.update(status='failed_no_retry', error_type=type(error).__name__,
                     http_status=getattr(response, 'status_code', None))
    finally:
        state['finished_at'] = china_now().isoformat()
        state['pause_preserved'] = (backend / 'data/.automation-paused').is_file()
        save_json(result_file, state)
        print(json.dumps(state, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('诊断入口停止：' + type(error).__name__
              + '；不重复请求，不删除旧标记。', file=sys.stderr)
        sys.exit(2)
