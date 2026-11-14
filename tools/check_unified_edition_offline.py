"""Stage updated app files over existing server sources, run ONLY offline fakes.

No installation, service restart, dependency download, database or provider calls.
The temporary source copy is removed when the check finishes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, required=True)
    args = parser.parse_args()
    package = Path(__file__).resolve().parent.parent
    manifest = json.loads((package / 'upgrade-manifest.json').read_text())
    for name, expected in manifest.get('prerequisites', {}).items():
        target = args.project / name
        if target.is_symlink() or not target.is_file() or hashlib.sha256(target.read_bytes().replace(b'\r\n', b'\n')).hexdigest() != expected:
            raise SystemExit('服务器依赖源码与已知基线不符：' + name)
    with zipfile.ZipFile(package / 'payload.zip') as payload:
        if set(payload.namelist()) != {r['path'] for r in manifest['runtime_files']}:
            raise SystemExit('安装载荷与验收源码目录不符')
        for row in manifest['runtime_files']:
            if hashlib.sha256(payload.read(row['path'])).hexdigest() != row['sha256']:
                raise SystemExit('安装载荷指纹不符：' + row['path'])
    for row in manifest['runtime_files']:
        source = package / row['path']
        target = args.project / row['path']
        if source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest() != row['sha256']:
            raise SystemExit('交付文件指纹不符：' + row['path'])
        if target.is_symlink(): raise SystemExit('服务器文件含软链：' + row['path'])
        current = hashlib.sha256(target.read_bytes().replace(b'\r\n', b'\n')).hexdigest() if target.is_file() else None
        if current not in (row['base_sha256'], row['sha256'], *row.get('additional_old_sha256', [])):
            raise SystemExit('服务器存在其他修改，停止覆盖及运行：' + row['path'])
    with tempfile.TemporaryDirectory(prefix='finance-unified-offline-', dir=package.parent) as temporary:
        stage = Path(temporary) / 'backend'
        for directory, names, files in os.walk(args.project / 'backend/app', followlinks=False):
            if any((Path(directory) / name).is_symlink() for name in names + files):
                raise SystemExit('服务器app目录含软链，停止制作隔离副本')
        shutil.copytree(args.project / 'backend/app', stage / 'app',
            ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.env', 'data'))
        for row in manifest['runtime_files']:
            relative = Path(row['path'])
            if relative.parts[:2] != ('backend', 'app'): continue
            target = stage / Path(*relative.parts[1:]); target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(package / relative, target)
        for key, directory in [('DATA_DIR', 'data'), ('REPORTS_DIR', 'reports'), ('PODCASTS_DIR', 'podcasts')]:
            os.environ[key] = str(stage / directory)
        os.environ['DATABASE_URL'] = 'sqlite:///' + str(stage / 'offline-unused.db')
        sys.path.insert(0, str(stage))
        os.chdir(stage)
        def no_network(*args, **kwargs):
            raise AssertionError('离线验收禁止任何网络连接')
        # Blocking is outside the application. A test accidentally reaching a real
        # provider cannot charge an account, even if credentials are exported.
        with patch('socket.socket.connect', no_network), patch('socket.socket.connect_ex', no_network):
            suite = unittest.defaultTestLoader.discover(str(package / 'backend/tests'), pattern='test_unified_edition.py')
            if manifest.get('edition_read_selection_tests_required'):
                suite.addTests(unittest.defaultTestLoader.discover(str(package / 'backend/tests'),
                    pattern='test_edition_read_selection.py'))
            if manifest.get('edition_batch_budget_tests_required'):
                suite.addTests(unittest.defaultTestLoader.discover(str(package / 'backend/tests'),
                    pattern='test_edition_batch_budget.py'))
            if manifest.get('edition_manual_tests_required'):
                suite.addTests(unittest.defaultTestLoader.discover(str(package / 'backend/tests'),
                    pattern='test_edition_manual.py'))
            if manifest.get('article_publication_tests_required'):
                suite.addTests(unittest.defaultTestLoader.discover(str(package / 'backend/tests'),
                    pattern='test_article_publication.py'))
            result = unittest.TextTestRunner(verbosity=2).run(suite)
        os.chdir(package)
        print('生产源码、配置、数据库、暂停状态均未修改；临时源码副本将自动清理。')
        if not result.wasSuccessful(): raise SystemExit(1)
        if result.testsRun != manifest['test_count']:
            raise SystemExit('实际测试数量与交付清单不符，不生成验收回执')
        proof_files = ('upgrade-manifest.json', 'manifest.json', 'payload.zip',
                       'backend/tests/test_unified_edition.py', 'backend/tests/fixtures/unified_major_omission.json')
        if manifest.get('edition_cost_sample_required'):
            proof_files += ('backend/tests/fixtures/edition_cost_sample.json',)
        if manifest.get('edition_read_selection_tests_required'):
            proof_files += ('backend/tests/test_edition_read_selection.py',)
        if manifest.get('edition_batch_budget_tests_required'):
            proof_files += ('backend/tests/test_edition_batch_budget.py',)
        if manifest.get('edition_manual_tests_required'):
            proof_files += ('backend/tests/test_edition_manual.py',)
        if manifest.get('article_publication_tests_required'):
            proof_files += ('backend/tests/test_article_publication.py',)
        proof = dict(owner='finance-unified-offline-acceptance-v1', passed=True,
            test_count=result.testsRun,
            file_sha256={name: hashlib.sha256((package / name).read_bytes()).hexdigest() for name in
                proof_files})
        target = package / 'offline-acceptance.json'
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as stream: json.dump(proof, stream, ensure_ascii=False, indent=2)
        print('隔离验收回执：' + str(target))


if __name__ == '__main__':
    main()
