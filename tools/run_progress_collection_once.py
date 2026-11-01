"""Preview a fresh progress-driven collection; --run --input-sha spends usage.

Run from a separate upload directory against the reviewed v21+v22+v23 backend. No service,
credential, scheduler, report, TTS or App database writes. Old trial markers and
source-failure ledgers remain authoritative and are never removed by this tool.
"""
import argparse
import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch
import zipfile

TRIAL = 'progress-collection-v1'
OWNER = 'finance-progress-collection-acceptance-v1'
# Filled from installed v21 plus the reviewed v22/v23 repairs. LF/CRLF only
# is normalized; unknown source changes are not silently accepted.
REVIEWED_RUNTIME = {
    "app/services/discovery_context.py": "8ee21b0d8fa064fcdfeba0a6ee078dd0ddbfc8546d22749e40259eb9b54fb2c8",
    "app/collection_review.py": "0c2a56ebac790e768f7ffd1112b96c444eb464dfe488009953cfe95589f57a8d",
    "app/config.py": "3c7aa5a7c9e679bad52a30fa70cdc9e67986a9b89548dc36c9941cca3cfbe104",
    "app/discovery_budget_check.py": "ce53a1f496170bf78c986086843060307debb82031a40ae667781758c265f8de",
    "app/primary_discovery_check.py": "ebf91e10a64956da3ca69869b5ab2434103666d795af6b816c797690f049bbd0",
    "app/primary_report_check.py": "fb0110bc127c6d670aec97ccfa2c6c54691b5d0ee52c22c5811e22fc0a82b96a",
    "app/reading_acceptance.py": "99b22e0ced2d1ed5645c29d16972024dc4771da482a14bb9cad291b9655c4b6a",
    "app/services/ai_analyzer.py": "c1d5184f50b66bd00da16866707ca0a74eb0e96926bc31ee03d7ea98770c9d44",
    "app/services/discovery_budget.py": "89c425916b7facd481df44a73a59a18b7bc50ef5f919ed1db8afb2378af95542",
    "app/services/discovery_completion.py": "bb462947db3ad3aaa9e0777f65b35e8cfd8aeaaad17fe620555a2d4d183570da",
    "app/services/discovery_feedback.py": "3f6a104f0b2b60c2de6dd98eeb749a3805a8f1445e5dab67b5a89c14386fe0ac",
    "app/services/episode_research.py": "b810755244f6816e54de7fb170cd59b33bf05e164bfbeda2336bf2a0bdb1faae",
    "app/services/episode_workspace.py": "180530fd20d85514ca70717ac3ff0f17d765a77302d7ff656842f3bea284edf0",
    "app/services/generic_extraction.py": "1b12efef7a6c1e748caf81733f7eb235e353244806a9e264415de5cf9f3365f8",
    "app/services/model_gateway.py": "af70135e8007cf2da9d52538a18bfd2b8b0dd0ed4e6ef42453e7e9fb952efbf2",
    "app/services/model_usage.py": "12e657d6652ad3c45d511c91b64756943062b99ebee261c1ba6da1c25c9bb502",
    "app/services/primary_discovery.py": "d889d8de9703f7be31eb4daa4c7c5e91a0de7a9bbdc2970aeb58545c29119f93",
    "app/services/primary_material_quality.py": "d0d282b2f7bf1995792a8ae0909098bb9a25631b6f7f64f65add6dc481d28ff8",
    "app/services/primary_report.py": "55d6c5dbbfa74fb0ed28e47253689895cffda9428ed99c7cbe2186af316b7b8c",
    "app/services/reading_acceptance.py": "4c457fa15ef27c19841711352de5c0c80407e36df835d2e1ff6a8c4d8c76b193",
    "app/services/search_objectives.py": "6cff95ba005013ddd5ba4e836e43712372cb7483c6a646e9c935509e5d91ac5f",
    "app/services/search_primary_collection.py": "e71098d1d165e1ffb64a7cd51b2f686e0b843b4936122b99dad6f0d1f10fd63a",
    "app/services/web_research.py": "d5054b15254028721a1b6891eac5906dc40d9fd68cc35c1dbb3654cd4c10fbb3"
}
POLICY_FIELDS = ('research_max_model_calls', 'research_total_input_characters',
                 'research_total_output_tokens', 'research_web_search_max_requests',
                 'research_body_max_urls', 'research_input_max_characters',
                 'research_local_read_max_characters', 'research_max_seconds',
                 'ai_timeout_seconds')


class CheckError(RuntimeError):
    """Only messages generated here, without provider responses or secrets."""


def fingerprint(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def source_snapshot(backend):
    for relative, expected in REVIEWED_RUNTIME.items():
        path = backend / relative
        if (not path.is_file() or path.is_symlink()
                or hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest() != expected):
            raise CheckError('源码与已审阅v21+v22+v23不符，停止：' + relative)
    # Also detect drift in imported support modules between preview and run.
    files = sorted((backend / 'app').rglob('*.py'))
    if any(p.is_symlink() for p in files):
        raise CheckError('后端源码包含软链，需先核对')
    return {str(p.relative_to(backend)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in files}


def route_metadata(route):
    return {key: getattr(route, key) for key in ('provider', 'model', 'base_url', 'effort')}


def environment(backend):
    from app.config import settings
    from app.services.generic_extraction import runtime_status
    from app.services.model_gateway import resolve_route
    route = resolve_route('analysis')
    key = settings.research_web_search_api_key
    # Private opaque drift check only; never export credential values or hashes.
    connection = fingerprint([route.api_key, key.get_secret_value() if key else None,
                              settings.database_url])
    return dict(source=fingerprint(source_snapshot(backend)),
                runner=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                env_file=(hashlib.sha256((backend / '.env').read_bytes()).hexdigest()
                          if (backend / '.env').is_file() else None),
                route=route_metadata(route), connection=connection,
                policy={key: getattr(settings, key) for key in POLICY_FIELDS},
                extractor=runtime_status())


def locations(backend):
    root = backend / 'data/diagnostics' / TRIAL
    return root, root / 'input.json', root / 'result.json', root / 'started.json'


def require_pause(backend):
    flag = backend / 'data/.automation-paused'
    if not flag.is_file() or flag.is_symlink():
        raise CheckError('要求保留现有维护暂停标记')


def search_status():
    from app.config import settings
    from app.services.web_research import search_availability
    # Only this isolated process may use the configured search account.
    with patch.object(settings, 'research_web_search_enabled', True):
        return search_availability()


async def inputs(backend, now):
    from app.config import settings
    from app.services.discovery_budget import plan_budget
    from app.services.discovery_completion import CONTRACT
    from app.services.primary_discovery import prompt
    from app.services.search_primary_collection import LANES
    from app.services.watchlist_repository import read_app_watchlist
    require_pause(backend)
    env = environment(backend)
    stocks = await read_app_watchlist()
    initial, ceiling, plan = plan_budget(len(stocks), len(LANES), settings)
    return dict(owner=OWNER, prepared_at=now.isoformat(),
                expires_at=(now + timedelta(hours=2)).isoformat(), watchlist=stocks,
                environment=env, budget_plan=plan, contract=CONTRACT,
                prompt=prompt(stocks, now, initial),
                public_fetch_ceiling=3 * ceiling.body_urls,
                production_search_enabled=settings.research_web_search_enabled)


async def preview(backend):
    from app.services.research_hub import save_json
    from app.services.time_context import china_now
    root, input_file, result_file, marker = locations(backend)
    if marker.exists():
        print(json.dumps(dict(mode='already_attempted_no_retry', result_file=str(result_file)),
                         ensure_ascii=False, indent=2))
        return
    now = china_now()
    value = await inputs(backend, now)
    available = search_status()
    blockers = []
    if not value['environment']['extractor'].get('ready'):
        blockers.append('通用提取依赖不可导入；先加载已验收的独立依赖目录')
    if not available['available']:
        blockers.append(available['reason'])
    # Keep a still-current preview stable, without refreshing its cutoff/expiry.
    if input_file.is_file():
        previous = json.loads(input_file.read_text(encoding='utf-8'))
        prepared = datetime.fromisoformat(previous['prepared_at'])
        if (prepared <= now < datetime.fromisoformat(previous['expires_at'])
                and previous == await inputs(backend, prepared)):
            value = previous
    save_json(input_file, value)
    plan = value['budget_plan']
    max_by_output = plan['total_reserved_output_tokens'] // plan['initial']['output_tokens']
    configured_cap = plan['model_request_cap']
    print(json.dumps(dict(mode='free_progress_collection_preview', trial=TRIAL,
        ready_to_run=not blockers, blockers=blockers, input_sha256=fingerprint(value),
        prepared_at=value['prepared_at'], expires_at=value['expires_at'],
        watchlist=value['watchlist'], route=value['environment']['route'], budget_plan=plan,
        max_model_requests_from_output_reservation=(min(max_by_output, configured_cap)
            if configured_cap is not None else max_by_output),
        max_public_fetch_attempts_including_redirects=value['public_fetch_ceiling'],
        max_search_http_requests=plan['ceiling']['search_calls'],
        production_search_enabled=value['production_search_enabled'],
        trial_search_enabled_only_inside_this_process=True,
        extractor=value['environment']['extractor'], retries=0,
        model_requests_performed=0, search_requests_performed=0, public_fetch_attempts=0,
        tts_requests=0, production_pause_preserved=True,
        result_file=str(result_file),
        continuation=value['environment'].get('continuation'),
        limitation='这只是本地预览，尚未联网。运行会使用模型及Tavily账户额度；'
            '字符与预留输出不是金额上限，也不保证达到上限才结束。'
            '模型请求数由累计输出上限推导，未新增固定取材轮次。'
            '不生成报告或音频，不恢复自动化。'), ensure_ascii=False, indent=2))


@contextmanager
def single_run(root):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(root / 'execution.lock', os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CheckError('本验收已有进程运行，不并发执行') from None
        yield
    finally:
        os.close(fd)


def body_exposure(workspace, research):
    if research.get('request_context', {}).get('codec') == 'finance-discovery-context-v1':
        return research['request_context']['body_ranges']
    from app.services.discovery_feedback import body_records
    return {key: row['ranges'] for key, row in
            body_records(workspace, research.get('receipts', [])).items() if row['eligible']}


class AcceptanceModel:
    """One-shot transport with cumulative guards; no retries or pause mutation."""
    def __init__(self, backend, value, state, workspace, guard, save):
        self.backend, self.value, self.state = backend, value, state
        self.workspace, self.guard, self.save = workspace, guard, save

    async def __call__(self, task, messages, max_tokens):
        import httpx
        from app.config import settings
        from app.services import model_gateway as gateway
        from app.services.model_usage import record_usage
        from app.services.prompt_reading import validate_input
        from app.services.watchlist_repository import assert_watchlist_current, watchlist_signature
        await assert_watchlist_current(watchlist_signature(self.value['watchlist']))
        self.guard()
        plan = self.value['budget_plan']
        current = self.state['research']['limits']
        size = validate_input(messages, limit=current['input_characters'])
        if task != 'analysis' or type(max_tokens) is not int or max_tokens != current['output_tokens']:
            raise CheckError('验收模型请求不符合取材协议')
        calls = self.state['model_http_attempts']
        if (plan['model_request_cap'] is not None and calls >= plan['model_request_cap']
                or self.state['model_input_characters'] + size > plan['total_input_characters']
                or self.state['reserved_output_tokens'] + max_tokens > plan['total_reserved_output_tokens']):
            raise CheckError('验收累计模型用量边界已到，停止')
        route = gateway.resolve_route(task)
        url, headers, body = gateway.request_for(route, messages, max_tokens)
        exposure = dict(attempt=calls + 1, request_characters=size,
                        body_ranges=body_exposure(self.workspace, self.state['research']),
                        completed_response=False)
        self.state['model_http_attempts'] += 1
        self.state['model_input_characters'] += size
        self.state['reserved_output_tokens'] += max_tokens
        self.state['model_exposures'].append(exposure)
        self.save()  # Failed requests can still be billed: reserve before POST.
        response, error = None, None
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=settings.ai_timeout_seconds,
                                         follow_redirects=False) as client:
                self.guard()
                response = await client.post(url, headers=headers, json=body)
            if response.is_error:
                raise gateway.service_error(task, response)
            result = gateway.completed_text(route, response.json())
            exposure['completed_response'] = True
            print('[取材] 模型完整响应：' + str(calls + 1), file=sys.stderr, flush=True)
            return result
        except BaseException as failure:
            error = failure
            raise
        finally:
            self.state['usage'].append(record_usage(task, route, max_tokens, response=response,
                error=error, elapsed=time.monotonic() - started, request_characters=size))
            self.save()


def write_review(workspace, state):
    from app.services.discovery_feedback import body_records
    from app.services.research_hub import save_json
    research = state.get('research', {})
    records = body_records(workspace, research.get('receipts', []))
    confirmed = {}
    for exposure in state['model_exposures']:
        if exposure['completed_response']:
            for key, ranges in exposure['body_ranges'].items():
                confirmed.setdefault(key, []).extend(ranges)
    rows = []
    for key, item in workspace.documents.items():
        ranges = workspace.merged_ranges(confirmed.get(key, []))
        rows.append(dict(id=key, title=item.title, url=item.source_url,
            stored_characters=len(item.content),
            tool_provided_ranges=records.get(key, {}).get('ranges', []),
            completed_request_ranges=ranges,
            completed_request_characters=sum(end-start for start, end in ranges),
            limitation='区间表示请求完整返回，不证明模型认真阅读或独立核实；图片及附件未读。'))
    state['reading_review'] = rows
    continuation = state.get('continuation')
    if continuation:
        prior = continuation['prior_usage']
        state['combined_usage'] = dict(
            model_http_attempts=prior['model_requests']+state['model_http_attempts'],
            model_input_characters=prior['model_input_characters']+state['model_input_characters'],
            reserved_output_tokens=prior['reserved_output_tokens']+state['reserved_output_tokens'],
            search_http_attempts=prior['search_http_attempts']+state['search_http_attempts'])
    save_json(workspace.path / 'acceptance-review.json', state)
    lines = ['# 自主取材验收底稿', '', '状态：' + state['status'], '',
        '这是待人工核对的私人底稿，不代表覆盖充分或可直接发布。', '',
        '## 本段实际用量', '',
        json.dumps({key: state[key] for key in ('model_http_attempts', 'model_input_characters',
            'reserved_output_tokens', 'search_http_attempts', 'public_fetch_attempts')}, ensure_ascii=False),
        '', '## 实际正文与入模范围', '']
    if continuation:
        lines[lines.index('## 实际正文与入模范围'):lines.index('## 实际正文与入模范围')] = [
            '## 含原失败与单次搜索诊断的累计用量', '',
            json.dumps(state['combined_usage'], ensure_ascii=False), '',
            '预留输出不是实际输出token或金额；旧明细保留在原结果中。', '']
    for row in rows:
        lines.extend([row['title'], row['url'],
            '保存文字：' + str(row['stored_characters']) + '；有完整响应的请求包含字符：'
                + str(row['completed_request_characters']),
            '已提供区间：' + json.dumps(row['tool_provided_ranges'])
                + '；完整响应对应区间：' + json.dumps(row['completed_request_ranges']), ''])
    for title, data in [('重要事件与研究检查', research.get('dossier', research.get('proposed_dossier'))),
                         ('未解决缺口', research.get('collection_completion')),
                         ('实际检索及失败回执', [r for r in research.get('receipts', [])
                                              if r.get('request', {}).get('tool') == 'search'])]:
        lines.extend(['## ' + title, '', '```json', json.dumps(data, ensure_ascii=False, indent=2), '```', ''])
    path = workspace.path / 'acceptance-review.md'
    path.write_text('\n'.join(lines), encoding='utf-8')
    path.chmod(0o600)


async def execute(backend, input_sha):
    from app.config import settings
    from app.services import web_research as reader
    from app.services.episode_workspace import EpisodeWorkspace
    from app.services.model_usage import collection_usage_scope
    from app.services.primary_discovery import discover
    from app.services.primary_report import save_discovery_input
    from app.services.research_hub import save_json
    from app.services.time_context import china_now
    from app.services.watchlist_repository import read_app_watchlist, watchlist_signature
    root, input_file, result_file, marker = locations(backend)
    with single_run(root):
        if marker.exists():
            raise CheckError('本验收已开始过，不重复扣费；请导出已有结果')
        value = json.loads(input_file.read_text(encoding='utf-8'))
        if value.get('owner') != OWNER or fingerprint(value) != input_sha:
            raise CheckError('预览指纹不匹配，未发请求')
        now = china_now()
        prepared = datetime.fromisoformat(value['prepared_at'])
        if not prepared <= now < datetime.fromisoformat(value['expires_at']):
            raise CheckError('预览超过2小时或来自未来，请先免费重新预览')
        if value != await inputs(backend, prepared):
            raise CheckError('源码、依赖、配置、提示词或App名单已变化，请免费重新预览')
        if not value['environment']['extractor'].get('ready') or not search_status()['available']:
            raise CheckError('提取依赖或搜索路径不可用，未发请求')
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(dict(owner=OWNER, input_sha256=input_sha, started_at=now.isoformat()), stream)
        state = dict(owner=OWNER, trial=TRIAL, status='started', input_sha256=input_sha,
            started_at=now.isoformat(), cutoff=prepared.isoformat(), watchlist=value['watchlist'],
            budget_plan=value['budget_plan'], model_http_attempts=0, model_input_characters=0,
            reserved_output_tokens=0, search_http_attempts=0, public_fetch_attempts=0,
            usage=[], model_exposures=[], research={}, report_generated=False, tts_requests=0,
            content_accepted=False, automation_resumed=False)
        state['continuation'] = value['environment'].get('continuation')
        mutex = threading.RLock()
        def save():
            with mutex:
                save_json(result_file, state)
        save()
        workspace = None
        started = time.monotonic()
        def guard():
            require_pause(backend)
            if time.monotonic() - started >= value['budget_plan']['ceiling']['seconds']:
                raise CheckError('验收总时长硬上限已到')
            if environment(backend) != value['environment']:
                raise CheckError('运行期间源码、依赖或模型配置已变化，停止')
        original_fetch = reader.fetch_html_once
        def fetch(url, deadline=None):
            guard()
            if state['public_fetch_attempts'] >= value['public_fetch_ceiling']:
                raise ValueError('public_read_budget_exhausted')
            state['public_fetch_attempts'] += 1
            save()
            return original_fetch(url, deadline)
        def search(*args, **kwargs):
            guard()
            try:
                return reader.search(*args, **kwargs)
            finally:
                state['search_http_attempts'] = getattr(workspace, 'web_search_attempts', 0)
                save()
        def read(*args, **kwargs):
            guard()
            return reader.read_public(*args, **kwargs)
        def checkpoint(research):
            state['research'] = research
            if workspace is not None:
                save_json(workspace.path / 'primary-discovery.json', research)
            save()
        try:
            workspace = EpisodeWorkspace([], now=prepared)
            state['workspace'] = str(workspace.path)
            save()
            model = AcceptanceModel(backend, value, state, workspace, guard, save)
            # Deliberately omit explicit Limits: retain the real dynamic plan,
            # extension logic, completion contract and no-progress stops.
            with patch.object(settings, 'research_web_search_enabled', True), \
                    patch.object(reader, 'fetch_html_once', fetch), \
                    collection_usage_scope(value['budget_plan']['ceiling']['input_characters']):
                research = await discover(workspace, value['watchlist'], model=model,
                    search=search, read=read, checkpoint=checkpoint)
            if watchlist_signature(value['watchlist']) != watchlist_signature(await read_app_watchlist()):
                research['status'] = 'watchlist_changed_not_accepted'
            state['status'] = research['status']
            checkpoint(research)
            handoff = save_discovery_input(workspace, research)
            if handoff is not None:
                state['report_input'] = handoff
        except BaseException as error:
            state.update(status='interrupted_no_retry' if isinstance(error, (KeyboardInterrupt, asyncio.CancelledError))
                         else 'failed_no_retry', error_type=type(error).__name__)
            if isinstance(error, CheckError):
                state['error_code'] = str(error)
            if state['research']:
                state['research']['status_before_acceptance_failure'] = state['research']['status']
                state['research']['status'] = state['status']
            if isinstance(error, (KeyboardInterrupt, asyncio.CancelledError)):
                raise
        finally:
            state['finished_at'] = china_now().isoformat()
            state['pause_preserved'] = (backend / 'data/.automation-paused').is_file()
            state['search_http_attempts'] = getattr(workspace, 'web_search_attempts', 0)
            save()
            if workspace is not None:
                if state['research']:
                    save_json(workspace.path / 'primary-discovery.json', state['research'])
                write_review(workspace, state)
                save()
            print(json.dumps({key: state[key] for key in ('status', 'model_http_attempts',
                'model_input_characters', 'reserved_output_tokens', 'search_http_attempts',
                'public_fetch_attempts', 'pause_preserved', 'workspace', 'error_type', 'error_code')
                if key in state}, ensure_ascii=False, indent=2), flush=True)


def export_review(backend, output):
    """One private archive, with no credentials/input preview/production DB."""
    _, _, result_file, _ = locations(backend)
    state = json.loads(result_file.read_text(encoding='utf-8'))
    if not state.get('finished_at'):
        raise CheckError('结果尚未结束，不导出运行中的底稿')
    workspace = Path(state['workspace'])
    episodes = (backend / 'data/episodes').resolve()
    if workspace.is_symlink() or workspace.resolve().parent != episodes:
        raise CheckError('结果工作集不属于本项目episodes目录')
    names = ('materials.json', 'primary-discovery.json', 'report-input.json',
             'acceptance-review.json', 'acceptance-review.md', 'meta.json')
    files = [p for p in (workspace / name for name in names) if p.is_file()]
    files += [p for p in (workspace / 'public-responses').glob('*')
              if p.is_file() and p.suffix in {'.body', '.json'}]
    if (any(p.is_symlink() for p in files)
            or result_file.stat().st_size + sum(p.stat().st_size for p in files) > 192 * 1024 * 1024):
        raise CheckError('审阅文件含软链或超过192MiB，不自动导出')
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.write(result_file, 'result.json')
            for path in files:
                archive.write(path, 'episode/' + str(path.relative_to(workspace)))
    print(json.dumps(dict(mode='offline_export', file=str(output), bytes=output.stat().st_size,
                         model_requests=0, search_requests=0, http_requests=0), ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path('/var/www/finance-daily'))
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--run', action='store_true')
    group.add_argument('--export-review', type=Path)
    parser.add_argument('--input-sha')
    args = parser.parse_args()
    if bool(args.input_sha) != args.run:
        parser.error('--input-sha只能并且必须与--run一起使用')
    backend = args.project.absolute() / 'backend'
    if not (backend / 'app/config.py').is_file():
        parser.error('Project backend not found')
    export = args.export_review.absolute() if args.export_review else None
    os.chdir(backend)
    sys.path.insert(0, str(backend))
    if export:
        export_review(backend, export)
    elif args.run:
        asyncio.run(execute(backend, args.input_sha))
    else:
        with single_run(locations(backend)[0]):
            asyncio.run(preview(backend))


if __name__ == '__main__':
    try:
        main()
    except CheckError as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
    except Exception as error:
        print('入口停止：' + type(error).__name__
              + '；如已开始，请保留标记并导出已有结果，不自动重跑。', file=sys.stderr)
        sys.exit(2)
