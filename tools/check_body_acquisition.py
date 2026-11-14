"""Saved failure replay by default; explicit bounded public issuer transport probe."""
import argparse
import asyncio
from datetime import datetime
import json
import re
from pathlib import Path
import sys
import time


def replay(package):
    from app.services.search_objectives import metadata_blockers
    from app.services.body_acquisition import read_target, failure_class
    from app.services.web_research import parse_visible_article
    sample = json.loads((package / 'backend/tests/fixtures/body_acquisition_sample.json').read_text())
    output = []
    for row in sample['rows']:
        item = row['candidate']; url = item['url']
        output.append(dict(candidate_id=row['candidate_id'], previous_reason=row['receipt']['reason'],
            previous_failure_class=failure_class(row['receipt']['reason']),
            pre_read_flags=metadata_blockers(item),
            read_target_changed=read_target(url) != url))
    old = next(row for row in sample['rows'] if row['candidate_id'] == 'S80')
    try:
        parse_visible_article((package / 'backend/tests/fixtures/sina_announcement_identity.body').read_bytes(),
            old['candidate']['url'], now=datetime.fromisoformat(sample['cutoff']), hours=168)
        announcement = 'unexpectedly_admitted_requires_review'
    except ValueError as error:
        announcement = str(error)
    return dict(mode='offline_saved_failure_replay', rows=output,
        old_announcement_current_reason=announcement, original_files_unchanged=True,
        network_requests=0, model_requests=0, search_requests=0, tts_requests=0,
        limitation='回放仅说明规则如何处理旧失败；不证明今天的连接、正文取得或事实正确。')


async def public_probe(project):
    from app.services.episode_workspace import EpisodeWorkspace, body
    from app.services.edition_pipeline import read_app_watchlist
    from app.services.edition_issuer_desk import IssuerDesk
    from app.services.model_gateway import MODEL_PAUSE_FILE
    from app.services.research_hub import save_json
    from app.services.time_context import china_now
    folder = project / 'backend/data/diagnostics/body-acquisition-v44'
    result_file = folder / 'result.json'
    if folder.is_symlink(): raise SystemExit('诊断目录含软链，停止')
    if folder.exists():
        if not result_file.is_file(): raise SystemExit('本次诊断已有started记录，不自动重跑；请保留并贴回输出。')
        return dict(json.loads(result_file.read_text()), reused_saved_result=True, new_http_requests=0)
    stocks = [s for s in await read_app_watchlist() if s['market'] == 'A'][:4]
    now = china_now()
    # New independent diagnostic; never alter/resume the paid episode's markers.
    folder.mkdir(parents=True, exist_ok=False, mode=0o700)
    save_json(folder / 'started.json', dict(at=now.isoformat(), max_public_http_requests=12, max_seconds=90))
    pause_files = [MODEL_PAUSE_FILE, project / 'backend/data/.automation-paused']
    before = [p.exists() for p in pause_files]
    state = dict(policy=dict(max_body_urls=4), watchlist=stocks, cutoff=now.isoformat(), rows=[])
    workspace = EpisodeWorkspace(root=folder / 'evidence', now=now)
    def save(): save_json(folder / 'transport.json', state)
    desk = IssuerDesk(state, workspace, save, time.monotonic() + 90)
    for stock in stocks:
        row = dict(stock=stock, status='started'); state['rows'].append(row)
        try:
            result = desk.catalogue(stock)
            row['catalogue_entries'] = result['catalogue_size']
            row['recent_candidates'] = len(result['results'])
            if not result['results']:
                row.update(status='no_recent_disclosure', reason='有限近期目录为空，不等于公司无新闻')
                continue
            # This is explicitly a transport sample, not editorial story selection.
            candidate = max(result['results'], key=lambda c: (c['published_hint'], c['url']))
            row['selected_title'], row['url'] = candidate['title'], candidate['url']
            read = desk.read(candidate)
            row.update(status=read.get('status'), reason=read.get('reason'))
            identifier = read.get('material', {}).get('id')
            if identifier in workspace.documents:
                item = workspace.documents[identifier]
                row.update(status='stored_pending_assessment', title=item.title,
                    source_id=identifier, body_characters=len(body(item)),
                    sample_beginning=body(item)[:200])
        except Exception as error:
            # Error text from remote providers is intentionally not exported.
            code = str(error)
            row.update(status='failed', error_type=type(error).__name__,
                reason=code if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,95}', code) else 'transport_or_structure_failure_see_private_receipt')
        finally: save()
    result = dict(mode='public_issuer_body_probe', cutoff=now.isoformat(), rows=state['rows'],
        public_http_requests=getattr(workspace, 'public_fetch_attempts', 0),
        stored_bodies=sum(r['status']=='stored_pending_assessment' for r in state['rows']),
        model_requests=0, search_requests=0, tts_requests=0,
        production_pause_preserved=before == [p.exists() for p in pause_files],
        result_file=str(result_file),
        limitation='最多4家公司、12次公开请求和90秒；每家仅选近期目录最新公告验证传输，不是选题判断或全面收集；镜像不是交易所原件。只保存独立诊断，不写日报、不生成音频、不恢复自动化。')
    save_json(result_file, result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--run-public', action='store_true')
    args = parser.parse_args()
    sys.path.insert(0, str(args.project / 'backend'))
    package = Path(__file__).resolve().parent.parent
    result = asyncio.run(public_probe(args.project)) if args.run_public else replay(package)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
