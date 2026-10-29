"""Build the consolidated analysis/speech release from exact confirmed v10 + allocation archives."""
import argparse
from contextlib import closing
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import zipfile

V10_SHA='94554a1b14e16fa70f91cb5290571902a9c9962964bfe272f07c7e9d63b7efb5'
ALLOCATION_SHA='c2f08e103293aea7a51a029d31c62a4b124c95354705de2edf674f57fca9e4e7'


def digest(value):return hashlib.sha256(value.replace(b'\r\n',b'\n')).hexdigest()


def build(output,baseline_archive,allocation_archive):
    repo=Path(__file__).resolve().parents[1]
    if subprocess.check_output(['git','-C',str(repo),'status','--porcelain']).strip():
        raise RuntimeError('Commit reviewed sources before building')
    baseline_archive=Path(baseline_archive)
    if hashlib.sha256(baseline_archive.read_bytes()).hexdigest()!=V10_SHA:
        raise RuntimeError('Not the confirmed v10 immutable archive')
    def read_bundle(path,prefix,expected):
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=expected:
            raise RuntimeError('Unexpected confirmed artifact: '+str(path))
        with zipfile.ZipFile(path) as archive:
            manifest=json.loads(archive.read(prefix+'/manifest.json'))
            with zipfile.ZipFile(io.BytesIO(archive.read(prefix+'/payload.zip'))) as payload:
                values={name:payload.read(name) for name in manifest['files']}
        if any(digest(value)!=manifest['files'][name]['new_sha256'] for name,value in values.items()):
            raise RuntimeError('Corrupt confirmed artifact')
        return manifest,values
    baseline,v10=read_bundle(baseline_archive,'finance-research-input-20261029-v10',V10_SHA)
    patch,allocated=read_bundle(allocation_archive,'finance-research-allocation-fix-20261029',ALLOCATION_SHA)
    revision=baseline['source_revision']
    def git(*args):return subprocess.check_output(['git','-C',str(repo),*args])
    names=git('diff','--name-only',revision,'HEAD','--','backend/app/','docs/').decode().splitlines()
    if not names or any(not (repo/name).is_file() for name in names):
        raise RuntimeError('Empty release or source deletion requires explicit review')
    tracked=set(git('ls-tree','-r','--name-only',revision).decode().splitlines())
    prior={name:v10[name] if name in v10 else git('show',revision+':'+name) if name in tracked else None for name in names}
    for name,value in allocated.items():
        original=prior.get(name,v10.get(name))
        if original is not None and digest(original)!=patch['files'][name]['old_sha256']:
            raise RuntimeError('Allocation baseline does not match confirmed v10: '+name)
    old={name:allocated.get(name,prior[name]) for name in names}
    new={name:(repo/name).read_bytes() for name in names}
    output=Path(output).resolve()
    if output.exists() or output.with_suffix('.zip').exists():raise RuntimeError('Immutable output exists')
    output.mkdir(parents=True)
    revision=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD']).decode().strip()
    manifest=dict(settings={},source_revision=revision,source_worktree_dirty=False,
        reviewed_installed_v10_artifact_sha256=V10_SHA,reviewed_allocation_artifact_sha256=ALLOCATION_SHA,files={name:dict(old_sha256=digest(old[name]) if old[name] is not None else None,new_sha256=digest(value),additional_old_sha256=[digest(prior[name])] if prior[name] is not None else []) for name,value in new.items()})
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (output/'install_upgrade.py').write_bytes((repo/'tools/install_paused_upgrade.py').read_bytes())
    with zipfile.ZipFile(output/'payload.zip','w',zipfile.ZIP_DEFLATED) as payload:
        for name,value in new.items():payload.writestr(name,value)
    (output/'README.txt').write_text('合并源码更新：资料去重/阅读分配、经营证据定位、RSI分类、口播审查对照及免费回放。只接受已确认v10/分配修复基线或本包新文件；冲突停止，不能绕过。\n默认只验证；--apply --restart私有备份并仅重启finance-daily，要求暂停与数据库健康。\n不改.env、数据库、前端静态文件或其他项目，不调用模型/TTS，不恢复定时任务。保留所有旧付费验收标记。\n安装后仅运行app.selection_check和app.research_input_check免费回放；禁止重跑旧付费试验。\n',encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='finance-consolidated-quality-') as temporary:
        root=Path(temporary)/'finance-daily'
        for name,value in old.items():
            if value is not None:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value)
        env=root/'backend/.env';env.parent.mkdir(parents=True,exist_ok=True)
        env_value=b'AI_MODEL=fixture\r\nOPENAI_API_KEY=fixture\r\n';env.write_bytes(env_value)
        data=root/'backend/data';data.mkdir()
        flag=data/'.automation-paused';flag.write_bytes(b'preserve-pause')
        db=data/'database.db'
        with closing(sqlite3.connect(db)) as connection,connection:
            connection.execute('CREATE TABLE sentinel(value TEXT)');connection.execute("INSERT INTO sentinel VALUES ('preserved')")
        marker=data/'real-report.started';marker.write_bytes(b'never-rebill')
        other=Path(temporary)/'other-project/keep';other.parent.mkdir();other.write_bytes(b'untouched')
        command=[sys.executable,'-X','utf8',str(output/'install_upgrade.py'),'--project',str(root),'--backup-root',str(Path(temporary)/'backups')]
        # Unknown changes and a missing pause must stop before writes.
        first=root/names[0];original=first.read_bytes();first.write_bytes(b'unknown-conflict')
        assert subprocess.run(command+['--apply'],capture_output=True).returncode!=0
        assert first.read_bytes()==b'unknown-conflict' and env.read_bytes()==env_value
        first.write_bytes(original);flag.rename(data/'pause-sentinel')
        assert subprocess.run(command+['--apply'],capture_output=True).returncode!=0
        (data/'pause-sentinel').rename(flag)
        for options in ([],['--apply'],['--apply']):subprocess.run(command+options,check=True)
        assert all((root/name).read_bytes()==value for name,value in new.items())
        assert env.read_bytes()==env_value and flag.read_bytes()==b'preserve-pause'
        assert other.read_bytes()==b'untouched' and marker.read_bytes()==b'never-rebill'
        with closing(sqlite3.connect(db)) as connection:assert connection.execute('SELECT value FROM sentinel').fetchone()[0]=='preserved'
        # Exact v10 baseline without the small allocation patch is supported too.
        for name,value in prior.items():
            path=root/name
            if value is None: path.unlink(missing_ok=True)
            else: path.write_bytes(value)
        for options in ([],['--apply']):subprocess.run(command+options,check=True)
        assert all((root/name).read_bytes()==value for name,value in new.items())
        assert env.read_bytes()==env_value and flag.read_bytes()==b'preserve-pause' and marker.read_bytes()==b'never-rebill'
    with zipfile.ZipFile(output.with_suffix('.zip'),'w',zipfile.ZIP_DEFLATED) as archive:
        for path in output.iterdir():archive.write(path,output.name+'/'+path.name)
    return dict(file=str(output.with_suffix('.zip')),sha256=hashlib.sha256(output.with_suffix('.zip').read_bytes()).hexdigest(),files=len(names),rehearsal='v10_and_allocation_conflict_pause_apply_idempotence_and_preservation_passed_no_service_or_model_calls')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline-archive',type=Path,required=True)
    parser.add_argument('--allocation-archive',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(build(args.output,args.baseline_archive,args.allocation_archive),ensure_ascii=False,indent=2))
