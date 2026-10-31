"""Prepare one consolidated source upgrade from the immutable installed v20.

Does not install, rehearse, run tests, restart services, install dependencies or
make network/model calls. The existing paused installer validates actual server
files before writes. No substitute baseline or arbitrary Git ref is accepted.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile

BASELINE_SHA256 = '133dd38ec86f85377ec5c396c93bc4fc2a380b22a1c59dabc56230913aba7804'
PREFIX = 'finance-reading-pipeline-20261031-v20/'
NAMES = (
    'backend/app/services/web_research.py',
    'backend/app/services/primary_discovery.py',
    'backend/app/services/discovery_budget.py',
    'backend/app/services/discovery_completion.py',
    'backend/app/services/model_usage.py',
    'backend/app/services/model_gateway.py',
    'backend/app/config.py',
    'backend/app/primary_discovery_check.py',
    'backend/app/discovery_budget_check.py',
    'backend/app/collection_review.py',
    'backend/app/services/discovery_feedback.py',
    'backend/app/services/search_objectives.py',
    'backend/app/services/generic_extraction.py',
    'backend/app/services/reading_acceptance.py',
    'backend/app/reading_acceptance.py',
    'backend/app/services/primary_report.py',
    'backend/app/services/primary_material_quality.py',
    'backend/app/services/search_primary_collection.py',
    'backend/app/primary_report_check.py',
    'backend/app/services/ai_analyzer.py',
    'backend/app/services/episode_workspace.py',
    'backend/app/services/episode_research.py',
    'backend/requirements-extraction.txt',
    'tools/run_primary_collection_once.py',
    'tools/check_saved_search_bodies.py',
    'tools/replay_search_objectives.py',
    'docs/search_objectives_20261031.md',
    'docs/generic_extraction_replay_20261031.md',
    'docs/reading_acceptance_20261031.md',
    'docs/primary_report_flow_20261031.md',
    'docs/primary_material_quality_20261031.md',
    'docs/discovery_feedback_loop_20261031.md',
    'docs/discovery_reading_budget_20261101.md',
    'docs/discovery_adaptive_budget_20261101.md',
    'docs/discovery_progress_driven_20261101.md',
    'docs/server_collection_acceptance_20261101.md',
)


def digest(data):
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()


def prepare(output, baseline):
    repo = Path(__file__).resolve().parents[1]
    raw = Path(baseline).read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASELINE_SHA256:
        raise ValueError('需要用户确认安装的原始v20包；不能从Git版本猜测服务器基线')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        manifest = json.loads(archive.read(PREFIX + 'manifest.json'))
        with zipfile.ZipFile(io.BytesIO(archive.read(PREFIX + 'payload.zip'))) as payload:
            if set(payload.namelist()) != set(manifest['files']):
                raise ValueError('v20载荷与清单不符')
            old = {name: payload.read(name) for name in manifest['files']}
    for name, data in old.items():
        if digest(data) != manifest['files'][name]['new_sha256']:
            raise ValueError('v20载荷校验失败：' + name)
    # These files are confirmed to have been in the deployed repair, not
    # reconstructed from a mutable local worktree or an approximate Git tag.
    required = {'backend/app/services/web_research.py',
                'backend/app/services/primary_discovery.py', 'backend/app/config.py',
                'backend/app/primary_discovery_check.py',
                'backend/app/services/model_usage.py', 'backend/app/services/model_gateway.py',
                'tools/run_primary_collection_once.py', 'tools/check_saved_search_bodies.py',
                'backend/app/services/ai_analyzer.py', 'backend/app/services/episode_workspace.py',
                'backend/app/services/episode_research.py'}
    required.add('backend/app/services/search_primary_collection.py')
    if not required.issubset(old):
        raise ValueError('v20增量包缺少本轮修改的共享运行文件基线；需先审阅实际部署文件，不能将它们作为新增文件或用Git版本猜测')
    new = {name: (repo / name).read_bytes() for name in NAMES}
    git = lambda *args: subprocess.check_output(['git', '-C', str(repo), *args]).decode().strip()
    plan = dict(settings={}, reviewed_baseline_artifact_sha256=BASELINE_SHA256,
                source_revision=git('rev-parse', 'HEAD'),
                source_worktree_dirty=bool(git('status', '--porcelain')),
                dependencies_auto_installed=False, installation_rehearsed=False,
                tests_run=False, server_verified=False,
                files={name: dict(old_sha256=digest(old[name]) if name in old else None,
                                 new_sha256=digest(data)) for name, data in new.items()})
    output = Path(output)
    if output.exists() or output.with_suffix('.zip').exists():
        raise ValueError('不覆盖已有交付物')
    output.mkdir(parents=True, mode=0o700)
    (output / 'manifest.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
    (output / 'install_upgrade.py').write_bytes((repo / 'tools/install_paused_upgrade.py').read_bytes())
    with zipfile.ZipFile(output / 'payload.zip', 'w', zipfile.ZIP_DEFLATED) as payload:
        for name, data in new.items():
            payload.writestr(name, data)
    (output / 'README.txt').write_text(
        'Consolidated source update against the immutable installed v20 archive.\n'
        'Preparation is NOT installation, rehearsal, dependency compatibility or server acceptance.\n'
        'Installer defaults to validation only; unknown server differences STOP before writes.\n'
        'Keep .env, database, pause and every trial marker. No automatic dependency installation.\n'
        'Review optional extraction requirements in an isolated project runtime first.\n'
        'Then inspect imports and replay actual captures using python -m app.reading_acceptance.\n'
        'No paid trial, TTS or automation resumption is authorized by this archive.\n'
        'Read docs/reading_acceptance_20261031.md before applying.\n', encoding='utf-8')
    archive_path = output.with_suffix('.zip')
    with zipfile.ZipFile(archive_path, 'x', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.iterdir()):
            archive.write(path, output.name + '/' + path.name)
    return dict(file=str(archive_path), sha256=hashlib.sha256(archive_path.read_bytes()).hexdigest(),
                files=len(new), installation_rehearsed=False, tests_run=False,
                model_requests=0, search_requests=0, tts_requests=0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.output, args.baseline), ensure_ascii=False, indent=2))
