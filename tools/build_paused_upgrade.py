"""Build a strict, paused source release from the confirmed editorial-flow baseline.

No model, service, API or live database calls. Frontend source is included, but
compiled static roots are deliberately not overwritten by the source installer.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import zipfile

BASELINE='b04b35f'
# The delivered nine-file bundle contained this document before the later
# deployment-instruction commit. Verified against its immutable payload.zip.
DEPLOYED_FILE_REFS={'docs/AI_HANDOFF.md':'9ce43f4'}
PAUSED_HASHES={
    'backend/app/main.py':'deb38b6a26429701113cc3fcf8a995895f5fa1134261afbe02eb000f71f508d9',
    'backend/app/services/model_gateway.py':'b75c82b900fd563c5dcc12c5d22323b25ed475a4127d0170b1f82b2453ab4217'}


def digest(value):
    return hashlib.sha256(value.replace(b'\r\n',b'\n')).hexdigest() if value is not None else None


def build(output):
    repo=Path(__file__).resolve().parents[1]
    def git(*args):return subprocess.check_output(['git','-C',str(repo),*args])
    baseline=git('rev-parse',BASELINE).decode().strip()
    prefixes=('backend/app/','mobile/','docs/')
    changed=git('diff','--name-only',baseline,'--',*prefixes).decode().splitlines()
    added=git('ls-files','--others','--exclude-standard','--',*prefixes).decode().splitlines()
    names=sorted(set(changed+added))
    if any(not (repo/name).is_file() for name in names):raise RuntimeError('Source deletion needs an explicit migration')
    old={}
    for name in names:
        file_ref=DEPLOYED_FILE_REFS.get(name,baseline)
        result=subprocess.run(['git','-C',str(repo),'show',file_ref+':'+name],capture_output=True)
        old[name]=result.stdout if result.returncode==0 else None
    new={name:(repo/name).read_bytes() for name in names}
    output=Path(output).resolve()
    if output.exists() or output.with_suffix('.zip').exists():raise RuntimeError('Immutable output already exists')
    output.mkdir(parents=True)
    manifest=dict(settings={},baseline=baseline,source_revision=git('rev-parse','HEAD').decode().strip(),
        source_worktree_dirty=bool(git('status','--porcelain').strip()),deployed_file_refs=DEPLOYED_FILE_REFS,
        frontend_static_deployed=False,
        files={name:dict(old_sha256=digest(old[name]),new_sha256=digest(value),
            additional_old_sha256=[PAUSED_HASHES[name]] if name in PAUSED_HASHES else []) for name,value in new.items()})
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (output/'install_upgrade.py').write_bytes((repo/'tools/install_paused_upgrade.py').read_bytes())
    with zipfile.ZipFile(output/'payload.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for name,value in new.items():archive.writestr(name,value)
    (output/'README.txt').write_text(
        'Consolidated source release. Requires the existing maintenance pause. No tests, credentials, database, virtualenv, model calls or static-root replacement.\n'
        'Default validation only; --apply --restart backs up privately, changes only listed files, restarts finance-daily, and requires healthy database plus paused scheduler.\n'
        'Baseline: editorial-flow runtime installation plus its confirmed pause patch. Unexpected differences stop before writes; never bypass hashes.\n'
        'Mobile source is included, but installing this bundle does NOT publish the new UI. Built frontend is a separate preview artifact.\n'
        'Preserve every existing acceptance marker. Do not rerun the old source-patching pause tool. See docs/consolidated_progress_20261028.md.\n',encoding='utf-8')
    # Rehearse against a private throwaway project, never the real app database.
    with tempfile.TemporaryDirectory(prefix='finance-paused-release-') as temporary:
        root=Path(temporary)/'finance-daily'
        for name,value in old.items():
            if value is not None:
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(value)
        env=root/'backend/.env';env.parent.mkdir(parents=True,exist_ok=True)
        env_bytes=b'# preserved CRLF\r\nAI_MODEL=fixture\r\nOPENAI_API_KEY=fixture\r\n'
        env.write_bytes(env_bytes)
        data=root/'backend/data';data.mkdir()
        flag=data/'.automation-paused';flag.write_bytes(b'preserve-pause')
        db=data/'database.db'
        with closing(sqlite3.connect(db)) as connection,connection:
            connection.execute('CREATE TABLE stocks(code TEXT)');connection.execute("INSERT INTO stocks VALUES ('dynamic')")
        other=Path(temporary)/'other-project/keep';other.parent.mkdir();other.write_bytes(b'other-project')
        command=[sys.executable,'-X','utf8',str(output/'install_upgrade.py'),'--project',str(root),'--backup-root',str(Path(temporary)/'backups')]
        # Missing pause and a source conflict must both stop before mutations.
        flag.rename(data/'paused-sentinel')
        assert subprocess.run(command+['--apply'],capture_output=True).returncode!=0
        (data/'paused-sentinel').rename(flag)
        target=root/next(name for name,value in old.items() if value is not None)
        original=target.read_bytes();target.write_bytes(b'conflict')
        assert subprocess.run(command+['--apply'],capture_output=True).returncode!=0
        assert env.read_bytes()==env_bytes and target.read_bytes()==b'conflict'
        target.write_bytes(original)
        for options in ([],['--apply'],['--apply']):subprocess.run(command+options,check=True)
        assert env.read_bytes()==env_bytes and flag.read_bytes()==b'preserve-pause'
        assert other.read_bytes()==b'other-project'
        assert all((root/name).read_bytes()==value for name,value in new.items())
        with closing(sqlite3.connect(db)) as connection:
            assert connection.execute('SELECT code FROM stocks').fetchone()[0]=='dynamic'
    with zipfile.ZipFile(output.with_suffix('.zip'),'w',zipfile.ZIP_DEFLATED) as archive:
        for path in output.iterdir():archive.write(path,output.name+'/'+path.name)
    return dict(file=str(output.with_suffix('.zip')),sha256=hashlib.sha256(output.with_suffix('.zip').read_bytes()).hexdigest(),files=len(names),rehearsal='passed_no_service_or_model_calls')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True,type=Path)
    print(json.dumps(build(parser.parse_args().output),ensure_ascii=False,indent=2))
