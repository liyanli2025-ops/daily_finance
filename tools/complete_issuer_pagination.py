"""Complete only missing issuer text chunks from the saved public probe.

Default is offline preview. Received pages are reused, not downloaded again.
"""
import argparse
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import time
import zipfile


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def safe(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('pagination_path_symlink')
    return path


def load_probe(project):
    from app.services.edition_issuer_desk import BODY_URL, MAX_DOCUMENT_PAGES
    folder = safe(project / 'backend/data/diagnostics/body-acquisition-v44')
    state_path = safe(folder / 'transport.json')
    state = json.loads(state_path.read_bytes())
    results = json.loads(safe(folder / 'result.json').read_bytes())
    if results.get('mode') != 'public_issuer_body_probe':
        raise ValueError('pagination_original_probe_invalid')
    episodes = list(safe(folder / 'evidence').glob('episode-*'))
    if len(episodes) != 1:
        raise ValueError('pagination_original_workspace_ambiguous')
    captures = safe(episodes[0] / 'issuer-responses')
    fingerprints = {'transport.json': digest(state_path.read_bytes()),
        'result.json': digest((folder / 'result.json').read_bytes())}
    previous = state.get('issuer_http_receipts', [])
    if state.get('public_fetch_attempts') != len(previous):
        raise ValueError('pagination_original_counter_mismatch')
    for row in previous:
        name = row.get('capture', '')
        if (row.get('status') != 'received' or name != row['key'] + '.json'
                or not re.fullmatch(r'[a-f0-9]{64}\.json', name)):
            raise ValueError('pagination_original_capture_unavailable')
        raw = safe(captures / name).read_bytes()
        if digest(raw) != row['sha256']:
            raise ValueError('pagination_original_capture_changed')
        fingerprints['issuer-responses/' + name] = digest(raw)
    failed = [r for r in state['rows'] if r.get('reason') == 'edition_issuer_full_document_unavailable']
    if len(failed) != 1:
        raise ValueError('pagination_expected_one_failed_document')
    row = failed[0]
    art = row['url'].rsplit('/', 1)[-1].removesuffix('.html')
    first = next((r for r in previous if r['url'] == BODY_URL
        and r['parameters'].get('art_code') == art and r['parameters'].get('page_index') == 1), None)
    if not first:
        raise ValueError('pagination_first_page_missing')
    detail = json.loads((captures / first['capture']).read_bytes()).get('data', {})
    count = detail.get('page_size')
    if (detail.get('art_code') != art or type(count) not in (int, str)
            or not re.fullmatch(r'[1-9]\d*', str(count)) or not 3 <= int(count) <= MAX_DOCUMENT_PAGES
            or not isinstance(detail.get('notice_content'), str) or len(detail['notice_content'].strip()) < 40):
        raise ValueError('pagination_saved_response_not_supported')
    # This continuation cannot reset the original 12-request diagnostic cap.
    remaining = state['policy']['max_body_urls'] * 3 - state['public_fetch_attempts']
    if int(count) - 1 > remaining:
        raise ValueError('pagination_remaining_public_budget_insufficient')
    fingerprint = digest(json.dumps(fingerprints, sort_keys=True).encode())
    plan = dict(mode='offline_issuer_pagination_preview', stock=row['stock'], title=row['selected_title'],
        art_code=art, supplier_text_pages=int(count), saved_first_page_characters=len(detail['notice_content']),
        original_public_http_requests=state['public_fetch_attempts'], max_new_public_http_requests=int(count)-1,
        original_public_http_limit=state['policy']['max_body_urls']*3, source_sha256=fingerprint,
        original_cutoff=state['cutoff'], model_requests=0, search_requests=0, tts_requests=0,
        new_public_http_requests=0, whole_document_verified=False,
        limitation='现有第1个文本分页有效，旧代码只接收1～2页而误拒3页；后续分页尚未读取。文本分页不等于PDF物理页数。')
    return folder, state, captures, fingerprints, row, plan


def complete(project, run):
    from app.services.edition_issuer_desk import IssuerDesk, LIST_URL, BODY_URL
    from app.services.episode_workspace import EpisodeWorkspace, body
    from app.services.model_gateway import MODEL_PAUSE_FILE
    from app.services.research_hub import save_json
    folder, original, captures, fingerprints, row, plan = load_probe(project)
    if not run:
        return plan
    stage = safe(folder / 'pagination-completion-v45')
    if stage.exists():
        result = safe(stage / 'result.json')
        if not result.is_file():
            raise ValueError('pagination_started_no_result_no_automatic_retry')
        saved = json.loads(result.read_bytes())
        if saved.get('source_sha256') != plan['source_sha256']:
            raise ValueError('pagination_saved_source_mismatch')
        return dict(saved, reused_saved_result=True, new_public_http_requests=0)
    stage.mkdir(mode=0o700)
    save_json(stage / 'started.json', plan)
    paused = [MODEL_PAUSE_FILE, project / 'backend/data/.automation-paused']
    before = [p.exists() for p in paused]
    state = copy.deepcopy(original)
    state['completion_source_sha256'] = plan['source_sha256']
    workspace = EpisodeWorkspace(root=stage / 'evidence', now=datetime.fromisoformat(original['cutoff']))
    workspace.public_fetch_attempts = original['public_fetch_attempts']
    def save(): save_json(stage / 'transport.json', state)
    desk = IssuerDesk(state, workspace, save, time.monotonic() + 60)
    desk.folder.mkdir(mode=0o700)
    for receipt in original['issuer_http_receipts']:
        shutil.copyfile(captures / receipt['capture'], desk.folder / receipt['capture'])
    save()
    original_request = desk.request
    def bounded_request(url, params, **kwargs):
        key = digest(json.dumps([url, params], sort_keys=True).encode())
        cached = any(r['key'] == key and r['status'] == 'received' for r in state['issuer_http_receipts'])
        if url not in {LIST_URL, BODY_URL}:
            raise ValueError('pagination_unexpected_endpoint')
        if not cached:
            if (url != BODY_URL or params.get('art_code') != plan['art_code']
                    or workspace.public_fetch_attempts - original['public_fetch_attempts'] >= plan['max_new_public_http_requests']):
                raise ValueError('pagination_new_request_limit')
        return original_request(url, params, **kwargs)
    desk.request = bounded_request
    result = dict(plan, mode='public_issuer_missing_pages_completion', status='started')
    try:
        # Catalogue and page 1 are hash-verified cache hits, never new requests.
        candidates = desk.catalogue(row['stock'])['results']
        candidate = next(c for c in candidates if c['url'] == row['url'])
        value = desk.read(candidate)
        item = workspace.documents[value['material']['id']]
        result.update(status='stored_pending_assessment', source_id=item.id, title=item.title,
            body_characters=len(body(item)), supplier_text_pages=value['supplier_text_pages'],
            supplier_text_complete=True, independently_verified=False)
    except Exception as error:
        code = str(error)
        result.update(status='failed_no_retry', error_type=type(error).__name__,
            reason=code if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,95}',code) else 'pagination_completion_failed')
    finally:
        _, _, _, after, _, _ = load_probe(project)
        result.update(new_public_http_requests=workspace.public_fetch_attempts-original['public_fetch_attempts'],
            cumulative_public_http_requests=workspace.public_fetch_attempts,
            original_files_unchanged=fingerprints == after,
            production_pause_preserved=before == [p.exists() for p in paused],
            workspace=str(workspace.path), whole_document_verified=False,
            limitation='只补齐同一公告的缺失供应商文本分页。保留旧截止、6次请求及失败结果；不下载PDF、不调用模型/搜索/TTS、不写报告或音频，不恢复自动化。取得全文不代表选题重要或事实独立核实。')
        save(); save_json(stage / 'result.json', result)
    return result


def export_review(project, output):
    folder = safe(project / 'backend/data/diagnostics/body-acquisition-v44/pagination-completion-v45')
    safe(output)
    if not safe(folder / 'result.json').is_file():
        raise ValueError('pagination_no_result_to_export')
    files = []
    for path in sorted(folder.rglob('*')):
        safe(path)
        if path.is_file(): files.append(path)
    if output.exists():
        with zipfile.ZipFile(output) as archive:
            expected = {p.relative_to(folder).as_posix(): p for p in files}
            if (len(archive.namelist()) != len(expected) or set(archive.namelist()) != set(expected)
                    or any(digest(archive.read(name)) != digest(path.read_bytes()) for name,path in expected.items())):
                raise ValueError('pagination_existing_export_mismatch')
        return dict(mode='offline_export', file=str(output), bytes=output.stat().st_size,
            reused_saved_export=True, model_requests=0, search_requests=0, public_http_requests=0, tts_requests=0)
    # Exclusive creation prevents overwriting a prior evidence bundle.
    with output.open('xb') as stream:
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, path.relative_to(folder))
    output.chmod(0o600)
    return dict(mode='offline_export', file=str(output), bytes=output.stat().st_size,
        model_requests=0, search_requests=0, public_http_requests=0, tts_requests=0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--run-public', action='store_true')
    parser.add_argument('--export-review', type=Path)
    args = parser.parse_args()
    if args.run_public and args.export_review:
        parser.error('联网补读与离线导出须分步执行')
    safe(args.project)
    sys.path.insert(0, str(args.project / 'backend'))
    result = export_review(args.project, args.export_review) if args.export_review else complete(args.project, args.run_public)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
