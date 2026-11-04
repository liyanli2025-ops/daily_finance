"""Continue one failed collection after its explicit search revalidation.

Default is free preview. Old usage is subtracted; old results, markers and source
blocks remain unchanged. The narrow search permission exists only in this process.
"""
import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from unittest.mock import patch


def sha(path):
    if not path.is_file() or path.is_symlink():
        raise ValueError('Required evidence file is missing or is a symlink')
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_runner():
    path = Path(__file__).with_name('run_progress_collection_once.py')
    spec = importlib.util.spec_from_file_location('collection_acceptance_base', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def remaining_policy(config, original, diagnostic, diagnostic_marker):
    """Subtract prior attempts/reservations and active time, not the human wait."""
    plan = original['budget_plan']
    def number(value):
        if type(value) is not int or value < 0:
            raise ValueError('Invalid historical usage')
        return value
    search_spent = number(original['search_http_attempts']) + number(diagnostic['search_http_attempts'])
    elapsed = 0
    for start, end in ((original['started_at'], original['finished_at']),
                       (diagnostic_marker['started_at'], diagnostic['finished_at'])):
        seconds = (datetime.fromisoformat(end)-datetime.fromisoformat(start)).total_seconds()
        if seconds < 0:
            raise ValueError('Historical request clock invalid')
        elapsed += seconds
    spent = dict(model_requests=number(original['model_http_attempts']),
        model_input_characters=number(original['model_input_characters']),
        reserved_output_tokens=number(original['reserved_output_tokens']),
        search_http_attempts=search_spent,
        body_url_attempts=number(original['research']['body_url_calls']),
        local_read_characters=number(original['research']['local_read_characters']),
        active_seconds=math.ceil(elapsed))
    mapping = {
        'research_total_input_characters': min(config.research_total_input_characters,
            plan['total_input_characters'])-spent['model_input_characters'],
        'research_total_output_tokens': min(config.research_total_output_tokens,
            plan['total_reserved_output_tokens'])-spent['reserved_output_tokens'],
        'research_web_search_max_requests': min(config.research_web_search_max_requests,
            plan['ceiling']['search_calls'])-search_spent,
        'research_body_max_urls': min(config.research_body_max_urls,
            plan['ceiling']['body_urls'])-spent['body_url_attempts'],
        'research_local_read_max_characters': min(config.research_local_read_max_characters,
            plan['ceiling']['local_read_characters'])-spent['local_read_characters'],
        'research_max_seconds': min(config.research_max_seconds,
            plan['ceiling']['seconds'])-spent['active_seconds'],
    }
    caps = [v for v in (config.research_max_model_calls, plan.get('model_request_cap')) if v is not None]
    mapping['research_max_model_calls'] = min(caps)-spent['model_requests'] if caps else None
    if (mapping['research_total_input_characters'] < 12000
            or mapping['research_total_output_tokens'] < plan['initial']['output_tokens']
            or mapping['research_web_search_max_requests'] < 1
            or mapping['research_body_max_urls'] < 1
            or mapping['research_local_read_max_characters'] < 0
            or mapping['research_max_seconds'] < 30
            or mapping['research_max_model_calls'] is not None and mapping['research_max_model_calls'] < 1):
        raise ValueError('Original collection envelope has insufficient remaining usage')
    return mapping, spent


def verify_receipts(original, original_input, original_marker, diagnostic, diagnostic_input,
                    diagnostic_marker, fingerprint, credential_hash):
    if (original.get('owner') != 'finance-progress-collection-acceptance-v1'
            or original.get('status') != 'failed_no_retry'
            or original.get('error_type') != 'JSONDecodeError'
            or original['research'].get('candidates') or original['research'].get('provided_ids')
            or original['public_fetch_attempts'] != 0):
        raise ValueError('This continuation is limited to the reviewed failure before body collection')
    if (original_input.get('owner') != original['owner'] or original_marker.get('owner') != original['owner']
            or original['input_sha256'] != fingerprint(original_input)
            or original_marker['input_sha256'] != original['input_sha256']):
        raise ValueError('Original collection input/marker mismatch')
    if (diagnostic.get('owner') != 'finance-search-contract-diagnostic-v1'
            or diagnostic_input.get('owner') != diagnostic['owner']
            or diagnostic_marker.get('owner') != diagnostic['owner']
            or diagnostic.get('status') != 'search_http_accepted_pending_review'
            or diagnostic['diagnostics']['http_status'] != 200
            or diagnostic['search_http_attempts'] != 1 or diagnostic['model_requests'] != 0
            or diagnostic.get('public_fetch_attempts') != 0 or diagnostic.get('tts_requests') != 0
            or not diagnostic.get('pause_preserved')
            or diagnostic_marker['input_sha256'] != fingerprint(diagnostic_input)
            or diagnostic_input['credential_fingerprint'] != credential_hash
            or diagnostic['diagnostics']['request_parameters'] != diagnostic_input['revised_request_parameters']):
        raise ValueError('Search revalidation is not bound to this account/input and HTTP200 result')
    request = diagnostic_input['revised_request_parameters']
    failures = [row for row in original['research']['receipts']
                if row['request'].get('tool') == 'search' and row['result'].get('reason') == 'http_400']
    if (len(failures) != 1 or request['query'] != failures[0]['request']['query']
            or 'time_range' in request or not {'start_date', 'end_date'} <= set(request)
            or datetime.fromisoformat(diagnostic_marker['started_at']) < datetime.fromisoformat(original['finished_at'])):
        raise ValueError('Diagnostic does not cover the reviewed revised request')


def evidence(backend, base, reviewed_source_changes=None):
    from app.config import settings
    from app.services.research_hub import ResearchHub
    from app.services.source_health import state_path
    base.require_pause(backend)
    original_root = backend / 'data/diagnostics/progress-collection-v1'
    probe_root = backend / 'data/diagnostics/search-contract-diagnostic-v1'
    paths = [original_root / name for name in ('result.json', 'input.json', 'started.json')]
    paths += [probe_root / name for name in ('result.json', 'input.json', 'started.json')]
    frozen = {str(path): sha(path) for path in paths}
    original, old_input, old_marker, diagnostic, probe_input, probe_marker = [
        json.loads(path.read_text(encoding='utf-8')) for path in paths]
    key = settings.research_web_search_api_key
    if key is None:
        raise ValueError('Search account is not configured')
    credential_hash = hashlib.sha256(key.get_secret_value().encode()).hexdigest()
    verify_receipts(original, old_input, old_marker, diagnostic, probe_input,
                    probe_marker, base.fingerprint, credential_hash)
    if probe_input['prior_result_sha256'] != frozen[str(paths[0])]:
        raise ValueError('Diagnostic result is not bound to this failed collection')
    for name, expected in probe_input['source_sha256'].items():
        actual = sha(backend / 'app/services' / name)
        reviewed = (reviewed_source_changes or {}).get(name)
        if Path(name).name != name or (actual != expected and reviewed != (expected, actual)):
            raise ValueError('Runtime differs from the successfully revalidated source')
    if sha(backend / '.env') != probe_input['env_file_sha256']:
        raise ValueError('Configuration changed after successful search revalidation')
    route_key = 'research-web-search:tavily:v1:' + credential_hash[:12]
    blocked = state_path(ResearchHub().root, route_key)
    frozen[str(blocked)] = sha(blocked)
    record = json.loads(blocked.read_text(encoding='utf-8'))
    if record.get('status') != 'paused' or record.get('detail_code') != 'http_400':
        raise ValueError('Only the reviewed HTTP400 route block may be scoped for continuation')
    policy, spent = remaining_policy(settings, original, diagnostic, probe_marker)
    return dict(route_key=route_key, blocked_path=blocked, frozen=frozen, policy=policy,
        public=dict(stage='continuation_after_reviewed_search_revalidation',
            prior_usage=spent, remaining_policy=policy,
            proof_sha256=base.fingerprint(frozen),
            diagnostic_metadata_results=diagnostic.get('metadata_results'),
            diagnostic_candidates_saved=len(diagnostic.get('results', [])),
            original_failure_preserved=True, production_search_route_resumed=False,
            limitation='原失败前没有正文或候选可恢复；诊断只存数量时无法重建候选。'
                '这次重新编排取材，已扣旧用量，不重置总预算；旧结果和marker保留。'))


def assert_frozen(frozen):
    if any(sha(Path(path)) != expected for path, expected in frozen.items()):
        raise ValueError('Historical evidence or route block changed; stop before more usage')


def permit_reviewed_route(original, proof):
    """Delegate every other key; a new failure hash revokes this permission."""
    def checked(root, key):
        from app.services.source_health import state_path
        if key == proof['route_key'] and state_path(root, key) == proof['blocked_path']:
            assert_frozen(proof['frozen'])
            return
        return original(root, key)
    return checked


def continuation_paths(backend):
    root = backend / 'data/diagnostics/progress-collection-v1/continuation-after-search-check'
    return root, root / 'input.json', root / 'result.json', root / 'started.json'


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--project', type=Path, default=Path('/var/www/finance-daily'))
    parser.add_argument('--export-review')
    args, _ = parser.parse_known_args()
    backend = args.project.absolute() / 'backend'
    sys.path.insert(0, str(backend))
    base = load_runner()
    base.locations = continuation_paths
    # Existing continuation/exports remain inspectable even if a new failure
    # revoked the permission. Neither branch sends another network request.
    if args.export_review or continuation_paths(backend)[3].exists():
        base.main()
        return
    from app.config import settings
    from app.services import web_research as reader
    proof = evidence(backend, base)
    original_environment = base.environment
    def bound_environment(root):
        assert_frozen(proof['frozen'])
        return dict(original_environment(root), continuation=proof['public'],
                    continuation_runner_sha256=sha(Path(__file__)))
    with patch.multiple(settings, **proof['policy']), \
            patch.object(base, 'environment', bound_environment), \
            patch.object(reader, 'ensure_active', permit_reviewed_route(reader.ensure_active, proof)):
        base.main()


if __name__ == '__main__':
    try:
        main()
    except ValueError as error:
        print('续验检查未通过：' + str(error), file=sys.stderr)
        sys.exit(2)
    except Exception as error:
        print('续验入口停止：' + type(error).__name__
              + '；保留旧结果，不自动重试。', file=sys.stderr)
        sys.exit(2)
