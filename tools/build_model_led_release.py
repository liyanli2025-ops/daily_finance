"""Build/rehearse a narrow upgrade against the user's immutable v18 archive."""
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

BASELINE_SHA='7f509ba026ac0f3923140a32b8276ebf691263cf67543996130db2bdc7069a50'
NAMES=('backend/app/services/web_research.py','backend/app/services/primary_discovery.py',
       'backend/app/primary_discovery_check.py','tools/run_primary_collection_once.py',
       'docs/model_led_collection_20261031.md','docs/primary_discovery_release_v19.md')


def digest(data):return hashlib.sha256(data.replace(b'\r\n',b'\n')).hexdigest()


def build(output,baseline,*,expected_sha=BASELINE_SHA,prefix="finance-search-primary-20261031-v18/",names=NAMES):
    repo=Path(__file__).resolve().parents[1];baseline=Path(baseline);output=Path(output).resolve()
    if subprocess.check_output(['git','-C',str(repo),'status','--porcelain']).strip():raise RuntimeError('先提交审阅源码')
    if hashlib.sha256(baseline.read_bytes()).hexdigest()!=expected_sha:raise RuntimeError('不是用户已确认安装的原始基线包')
    with zipfile.ZipFile(baseline) as archive:
        manifest=json.loads(archive.read(prefix+'manifest.json'))
        with zipfile.ZipFile(io.BytesIO(archive.read(prefix+'payload.zip'))) as payload:
            old={name:payload.read(name) if name in manifest['files'] else None for name in names}
    for name,value in old.items():
        if value is not None and digest(value)!=manifest['files'][name]['new_sha256']:raise RuntimeError('基线载荷损坏：'+name)
    new={name:(repo/name).read_bytes() for name in names}
    if output.exists() or output.with_suffix('.zip').exists():raise RuntimeError('不覆盖已生成的交付包')
    output.mkdir(parents=True)
    plan=dict(settings={},reviewed_baseline_artifact_sha256=expected_sha,
        source_revision=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD']).decode().strip(),
        source_worktree_dirty=False,files={name:dict(old_sha256=digest(old[name]) if old[name] is not None else None,
                                                   new_sha256=digest(value)) for name,value in new.items()})
    (output/'manifest.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    installer=output/'install_upgrade.py';installer.write_bytes((repo/'tools/install_paused_upgrade.py').read_bytes())
    with zipfile.ZipFile(output/'payload.zip','w',zipfile.ZIP_DEFLATED) as payload:
        for name,value in new.items():payload.writestr(name,value)
    with tempfile.TemporaryDirectory(prefix='finance-v19-rehearsal-') as folder:
        base=Path(folder);root=base/'finance-daily'
        for name,value in old.items():
            if value is not None:
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(value)
        env=root/'backend/.env';env.parent.mkdir(parents=True,exist_ok=True)
        original_env=b'AI_MODEL=fixture\nRESEARCH_WEB_SEARCH_ENABLED=false\nRESEARCH_WEB_SEARCH_API_KEY=private-fixture\n'
        env.write_bytes(original_env);data=root/'backend/data';data.mkdir()
        pause=data/'.automation-paused';pause.write_bytes(b'preserved')
        database=data/'database.db'
        with closing(sqlite3.connect(database)) as connection,connection:
            connection.execute('CREATE TABLE sentinel(v TEXT)');connection.execute("INSERT INTO sentinel VALUES ('keep')")
        other=base/'another-project/keep.txt';other.parent.mkdir();other.write_bytes(b'untouched')
        command=[sys.executable,'-X','utf8',str(installer),'--project',str(root),'--backup-root',str(base/'backups')]
        first=root/names[0];original=first.read_bytes();first.write_bytes(b'unknown-server-change')
        assert subprocess.run(command+['--apply'],capture_output=True).returncode!=0
        assert first.read_bytes()==b'unknown-server-change' and env.read_bytes()==original_env
        first.write_bytes(original);pause.rename(data/'held-pause')
        assert subprocess.run(command+['--apply'],capture_output=True).returncode!=0
        (data/'held-pause').rename(pause)
        for options in ([],['--apply'],['--apply']):subprocess.run(command+options,check=True)
        assert all((root/name).read_bytes()==value for name,value in new.items())
        assert env.read_bytes()==original_env and pause.read_bytes()==b'preserved' and other.read_bytes()==b'untouched'
        with closing(sqlite3.connect(database)) as connection:assert connection.execute('SELECT v FROM sentinel').fetchone()[0]=='keep'
    with zipfile.ZipFile(output.with_suffix('.zip'),'w',zipfile.ZIP_DEFLATED) as archive:
        for target in output.iterdir():archive.write(target,output.name+'/'+target.name)
    return dict(file=str(output.with_suffix('.zip')),sha256=hashlib.sha256(output.with_suffix('.zip').read_bytes()).hexdigest(),
                files=len(names),rehearsal='reviewed_baseline_conflict_pause_apply_idempotence_env_database_other_project_preserved',
                model_requests=0,search_requests=0)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--baseline',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(build(args.output,args.baseline),ensure_ascii=False,indent=2))
