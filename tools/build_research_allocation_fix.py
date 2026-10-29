"""Build a narrowly scoped paused fix for the confirmed immutable v10 deployment."""
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
NAMES=('backend/app/services/research_hub.py','backend/app/research_input_check.py',
       'backend/app/services/research_reading.py','docs/AI_HANDOFF.md',
       'docs/research_allocation_fix_20261029.md')


def digest(value):return hashlib.sha256(value.replace(b'\r\n',b'\n')).hexdigest()


def build(output,baseline_archive):
    repo=Path(__file__).resolve().parents[1]
    if subprocess.check_output(['git','-C',str(repo),'status','--porcelain']).strip():
        raise RuntimeError('Commit reviewed sources before building')
    baseline_archive=Path(baseline_archive)
    if hashlib.sha256(baseline_archive.read_bytes()).hexdigest()!=V10_SHA:
        raise RuntimeError('Not the confirmed v10 immutable archive')
    with zipfile.ZipFile(baseline_archive) as delivered:
        prefix='finance-research-input-20261029-v10/'
        baseline=json.loads(delivered.read(prefix+'manifest.json'))
        with zipfile.ZipFile(io.BytesIO(delivered.read(prefix+'payload.zip'))) as payload:
            old={name:payload.read(name) if name in baseline['files'] else None for name in NAMES}
    for name,value in old.items():
        if value is not None and digest(value)!=baseline['files'][name]['new_sha256']:
            raise RuntimeError('Corrupt baseline source '+name)
    new={name:(repo/name).read_bytes() for name in NAMES}
    output=Path(output).resolve()
    if output.exists() or output.with_suffix('.zip').exists():raise RuntimeError('Immutable output exists')
    output.mkdir(parents=True)
    revision=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD']).decode().strip()
    manifest=dict(settings={},source_revision=revision,source_worktree_dirty=False,
        reviewed_installed_v10_artifact_sha256=V10_SHA,files={name:dict(old_sha256=digest(old[name]) if old[name] is not None else None,new_sha256=digest(value)) for name,value in new.items()})
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (output/'install_upgrade.py').write_bytes((repo/'tools/install_paused_upgrade.py').read_bytes())
    with zipfile.ZipFile(output/'payload.zip','w',zipfile.ZIP_DEFLATED) as payload:
        for name,value in new.items():payload.writestr(name,value)
    with tempfile.TemporaryDirectory(prefix='finance-allocation-release-') as temporary:
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
        other=Path(temporary)/'other-project/keep';other.parent.mkdir();other.write_bytes(b'untouched')
        command=[sys.executable,'-X','utf8',str(output/'install_upgrade.py'),'--project',str(root),'--backup-root',str(Path(temporary)/'backups')]
        # Unknown changes and a missing pause must stop before writes.
        first=root/NAMES[0];original=first.read_bytes();first.write_bytes(b'unknown-conflict')
        assert subprocess.run(command+['--apply'],capture_output=True).returncode!=0
        assert first.read_bytes()==b'unknown-conflict' and env.read_bytes()==env_value
        first.write_bytes(original);flag.rename(data/'pause-sentinel')
        assert subprocess.run(command+['--apply'],capture_output=True).returncode!=0
        (data/'pause-sentinel').rename(flag)
        for options in ([],['--apply'],['--apply']):subprocess.run(command+options,check=True)
        assert all((root/name).read_bytes()==value for name,value in new.items())
        assert env.read_bytes()==env_value and flag.read_bytes()==b'preserve-pause'
        assert other.read_bytes()==b'untouched'
        with closing(sqlite3.connect(db)) as connection:assert connection.execute('SELECT value FROM sentinel').fetchone()[0]=='preserved'
    with zipfile.ZipFile(output.with_suffix('.zip'),'w',zipfile.ZIP_DEFLATED) as archive:
        for path in output.iterdir():archive.write(path,output.name+'/'+path.name)
    return dict(file=str(output.with_suffix('.zip')),sha256=hashlib.sha256(output.with_suffix('.zip').read_bytes()).hexdigest(),files=len(NAMES),rehearsal='confirmed_v10_conflict_pause_apply_idempotence_preservation_passed_no_service_or_model_calls')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline-archive',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(build(args.output,args.baseline_archive),ensure_ascii=False,indent=2))
