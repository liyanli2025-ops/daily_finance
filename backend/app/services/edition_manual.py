"""Process-local permission for one explicitly invoked, budgeted text edition."""
from contextlib import contextmanager
from contextvars import ContextVar
import re
import hashlib
import json
from datetime import datetime
from pathlib import Path

_manual = ContextVar('finance_manual_text_edition', default=None)
STAGES = {'agenda', 'assessment', 'patch_assessment', 'writing', 'review'}


def current_config(fallback):
    active = _manual.get()
    return active['config'] if active else fallback


def active():
    return _manual.get() is not None


def models_allowed():
    from .model_usage import _run, _edition_sink, _edition_start
    permission, attempt = _manual.get(), _run.get()
    return bool(permission and attempt and attempt.get('id') == permission['id']
        and attempt.get('phase') in STAGES and attempt.get('limit') == 1
        and attempt.get('calls') == 0 and callable(_edition_sink.get())
        and callable(_edition_start.get()))


def reviewed_search_permission(config, backend=None, research_root=None):
    """Reuse only the saved HTTP200 proof for the same previously failed account.

    Never clears a block. A later failure or edited proof revokes this permission.
    """
    from .source_health import state_path
    backend = Path(backend) if backend is not None else Path(__file__).resolve().parents[2]
    key = config.research_web_search_api_key
    if not key:
        return None
    credential = hashlib.sha256(key.get_secret_value().encode()).hexdigest()
    route = 'research-web-search:tavily:v1:' + credential[:12]
    blocked = state_path(research_root or backend / 'data/research', route)
    if not blocked.is_file():
        return None
    folder = backend / 'data/diagnostics/search-contract-diagnostic-v1'
    paths = [folder / name for name in ('input.json', 'result.json', 'started.json')] + [blocked]
    if any(p.is_symlink() or not p.is_file() for p in paths):
        return None
    raw = [p.read_bytes() for p in paths]
    try:
        prepared, result, marker, failure = map(json.loads, raw)
        fingerprint = hashlib.sha256(json.dumps(prepared, ensure_ascii=False, sort_keys=True,
            separators=(',', ':')).encode()).hexdigest()
        owner = 'finance-search-contract-diagnostic-v1'
        request = prepared['revised_request_parameters']
        previous = dict(request, time_range='week')
        if (any(row.get('owner') != owner for row in (prepared, result, marker))
                or result.get('status') != 'search_http_accepted_pending_review'
                or result['diagnostics']['http_status'] != 200
                or result['diagnostics']['request_parameters'] != request
                or result.get('search_http_attempts') != 1 or result.get('model_requests') != 0
                or result.get('public_fetch_attempts') != 0 or result.get('tts_requests') != 0
                or not result.get('pause_preserved') or marker.get('input_sha256') != fingerprint
                or prepared.get('credential_fingerprint') != credential
                or failure.get('status') != 'paused' or failure.get('automatic_retest') is not False
                or failure.get('detail_code') != 'http_400'
                or prepared.get('previous_request_parameters') != previous
                or datetime.fromisoformat(marker['started_at']) < datetime.fromisoformat(failure['at'])):
            return None
        from .web_research import search_request
        # The reviewed repair removed time_range from an absolute date window.
        # Discovery uses a relative window and cannot reconstruct that request.
        if 'time_range' in request or not {'start_date', 'end_date'} <= set(request):
            return None
        expected, _ = search_request(request['query'], 'latest_close',
            datetime.fromisoformat(prepared['prepared_at']), topic='news')
        approved_exclusions = request.get('exclude_domains')
        if (not isinstance(approved_exclusions, list)
                or not all(isinstance(host, str) for host in approved_exclusions)
                or len(set(approved_exclusions)) != len(approved_exclusions)
                or not set(approved_exclusions) <= set(expected['exclude_domains'])):
            return None
        # Later source filtering added social domains to the exclusion list.
        # Permit only those additions; all other HTTP parameters remain exact.
        expected['exclude_domains'] = approved_exclusions
        if expected != request:
            return None
    except (ValueError, KeyError, TypeError):
        return None
    return dict(route=route, blocked=str(blocked),
        frozen={str(p): hashlib.sha256(data).hexdigest() for p, data in zip(paths, raw)})


def ensure_search_active(root, key, proof=None, check=None):
    from .source_health import ensure_active, state_path, RetiredSourceError
    try:
        (check or ensure_active)(root, key)
    except RetiredSourceError:
        permission = _manual.get()
        proof = proof or (permission.get('search_proof') if permission else None)
        if (not proof or key != proof['route'] or str(state_path(root, key)) != proof['blocked']
                or any(Path(name).is_symlink() or not Path(name).is_file()
                    or hashlib.sha256(Path(name).read_bytes()).hexdigest() != expected
                    for name, expected in proof['frozen'].items())):
            raise


@contextmanager
def manual_text_scope(identifier, config, search_proof=None):
    if (_manual.get() is not None or not re.fullmatch(r'edition-[0-9a-f]{32}', identifier)
            or not config.edition_estimate_accepted or config.edition_audio_enabled
            or config.model_http_retries != 0 or config.report_auto_repair_enabled):
        raise ValueError('edition_manual_permission_invalid')
    token = _manual.set(dict(id=identifier, config=config, search_proof=search_proof))
    try:
        yield
    finally:
        _manual.reset(token)
