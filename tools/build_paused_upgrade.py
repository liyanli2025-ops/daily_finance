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
# Confirmed by the user's complete server mismatch scan on 2026-10-29.
# Every hash also matches the immutable spoken-integrity bundle and Git ref.
SPOKEN_REF='c89844a5e04511b787825665f78f81a821fc3fe3'
SPOKEN_HASHES={
    'backend/app/services/material_lifecycle.py':'3facaec5b8b31ffcb4cbdc1cfc06b317a17083a2843287b639b7d45c11b68825',
    'backend/app/services/podcast_generator.py':'df8b84a5ecaa1b56298a16284c50c954df34c41a985cd6f13c5b5bfe2417cccc',
    'backend/app/services/report_diagnostics.py':'86051b1bd0393ba9de257a94bfab2d74cbf0546a9183b6a08ed56a34ed6f8ff7',
    'backend/app/services/spoken_editing.py':'0f0525ba32a3c0f9fbcbbb313d7eb34cae09b72a4d254b9727ec3e7b1db15c26',
    'docs/AI_HANDOFF.md':'eb5e7dfd6c8021693fbb6d512dd82c852004c4aae5b645e149e807e04740abec',
    'docs/repair_roadmap.md':'81fc4c28c16d1c5aa78b96f46cdc6220705e8591f532eff65703eaba5cf33189',
    'docs/spoken_integrity_progress.md':'36c3f261c700d9077efe4f1d7861a1abe8163526514be9cea6cbf70a336c12f6'}


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
    spoken={name:git('show',SPOKEN_REF+':'+name) for name in SPOKEN_HASHES}
    if any(digest(value)!=SPOKEN_HASHES[name] for name,value in spoken.items()):
        raise RuntimeError('Reviewed spoken-integrity source no longer matches its fixed fingerprint')
    deployed=json.loads(Path(__file__).with_name('reviewed_finance_v4_baseline.json').read_text(encoding='utf-8'))
    v4={name:git('show',deployed['source_revision']+':'+name) for name in names if name in deployed['files']}
    if any(digest(value)!=deployed['files'][name] for name,value in v4.items()):
        raise RuntimeError('Reviewed installed v4 source does not match its release manifest')
    installed_v5=json.loads(Path(__file__).with_name('reviewed_finance_v5_baseline.json').read_text(encoding='utf-8'))
    v5={name:git('show',installed_v5['source_revision']+':'+name) for name in names if name in installed_v5['files']}
    if any(digest(value)!=installed_v5['files'][name] for name,value in v5.items()):
        raise RuntimeError('Reviewed installed v5 source does not match its release manifest')
    installed_v6=json.loads(Path(__file__).with_name('reviewed_finance_v6_baseline.json').read_text(encoding='utf-8'))
    v6={name:git('show',installed_v6['source_revision']+':'+name) for name in names if name in installed_v6['files']}
    if any(digest(value)!=installed_v6['files'][name] for name,value in v6.items()):
        raise RuntimeError('Reviewed installed v6 source does not match its release manifest')
    installed_v7=json.loads(Path(__file__).with_name('reviewed_finance_v7_baseline.json').read_text(encoding='utf-8'))
    v7={name:git('show',installed_v7['source_revision']+':'+name) for name in names if name in installed_v7['files']}
    if any(digest(value)!=installed_v7['files'][name] for name,value in v7.items()):
        raise RuntimeError('Reviewed installed v7 source does not match its release manifest')
    installed_v8=json.loads(Path(__file__).with_name('reviewed_finance_v8_baseline.json').read_text(encoding='utf-8'))
    v8={name:git('show',installed_v8['source_revision']+':'+name) for name in names if name in installed_v8['files']}
    if any(digest(value)!=installed_v8['files'][name] for name,value in v8.items()):
        raise RuntimeError('Reviewed installed v8 source does not match its release manifest')
    installed_v9=json.loads(Path(__file__).with_name('reviewed_finance_v9_baseline.json').read_text(encoding='utf-8'))
    v9={name:git('show',installed_v9['source_revision']+':'+name) for name in names if name in installed_v9['files']}
    if any(digest(value)!=installed_v9['files'][name] for name,value in v9.items()):
        raise RuntimeError('Reviewed installed v9 source does not match its release manifest')
    output=Path(output).resolve()
    if output.exists() or output.with_suffix('.zip').exists():raise RuntimeError('Immutable output already exists')
    output.mkdir(parents=True)
    manifest=dict(settings={},baseline=baseline,source_revision=git('rev-parse','HEAD').decode().strip(),
        source_worktree_dirty=bool(git('status','--porcelain').strip()),deployed_file_refs=DEPLOYED_FILE_REFS,
        frontend_static_deployed=False,reviewed_spoken_integrity_ref=SPOKEN_REF,
        reviewed_installed_v4_artifact_sha256=deployed['artifact_sha256'],
        reviewed_installed_v5_artifact_sha256=installed_v5['artifact_sha256'],
        reviewed_installed_v6_artifact_sha256=installed_v6['artifact_sha256'],
        reviewed_installed_v7_artifact_sha256=installed_v7['artifact_sha256'],
        reviewed_installed_v8_artifact_sha256=installed_v8['artifact_sha256'],
        reviewed_installed_v9_artifact_sha256=installed_v9['artifact_sha256'],
        files={name:dict(old_sha256=digest(old[name]),new_sha256=digest(value),
            additional_old_sha256=([PAUSED_HASHES[name]] if name in PAUSED_HASHES else [])+
                ([SPOKEN_HASHES[name]] if name in SPOKEN_HASHES else [])+
                ([digest(v4[name])] if name in v4 else [])+
                ([digest(v5[name])] if name in v5 else [])+
                ([digest(v6[name])] if name in v6 else [])+
                ([digest(v7[name])] if name in v7 else [])+
                ([digest(v8[name])] if name in v8 else [])+
                ([digest(v9[name])] if name in v9 else [])) for name,value in new.items()})
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
        # Rehearse the now-confirmed v4 installation as well, using only exact
        # files listed in that delivered artifact, not an arbitrary Git tree.
        for name,value in old.items():
            target=root/name
            if value is None:target.unlink()
            else:target.write_bytes(value)
        for name,value in v4.items():
            target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(value)
        for options in ([],['--apply']):subprocess.run(command+options,check=True)
        assert all((root/name).read_bytes()==value for name,value in new.items())
        assert env.read_bytes()==env_bytes and flag.read_bytes()==b'preserve-pause'
        assert other.read_bytes()==b'other-project'
        with closing(sqlite3.connect(db)) as connection:
            assert connection.execute('SELECT code FROM stocks').fetchone()[0]=='dynamic'
        # Rehearse the now-confirmed v5 installation as well, using only exact
        # files listed in that delivered artifact, not an arbitrary Git tree.
        for name,value in old.items():
            target=root/name
            if value is None:target.unlink()
            else:target.write_bytes(value)
        for name,value in v5.items():
            target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(value)
        for options in ([],['--apply']):subprocess.run(command+options,check=True)
        assert all((root/name).read_bytes()==value for name,value in new.items())
        assert env.read_bytes()==env_bytes and flag.read_bytes()==b'preserve-pause'
        assert other.read_bytes()==b'other-project'
        with closing(sqlite3.connect(db)) as connection:
            assert connection.execute('SELECT code FROM stocks').fetchone()[0]=='dynamic'
        # Rehearse the now-confirmed v6 installation as well, using only exact
        # files listed in that delivered artifact, not an arbitrary Git tree.
        for name,value in old.items():
            target=root/name
            if value is None:target.unlink()
            else:target.write_bytes(value)
        for name,value in v6.items():
            target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(value)
        for options in ([],['--apply']):subprocess.run(command+options,check=True)
        assert all((root/name).read_bytes()==value for name,value in new.items())
        assert env.read_bytes()==env_bytes and flag.read_bytes()==b'preserve-pause'
        assert other.read_bytes()==b'other-project'
        with closing(sqlite3.connect(db)) as connection:
            assert connection.execute('SELECT code FROM stocks').fetchone()[0]=='dynamic'
        # Rehearse the v7 speech-verified release installation as well, using only exact
        # files listed in that delivered artifact, not an arbitrary Git tree.
        for name,value in old.items():
            target=root/name
            if value is None:target.unlink()
            else:target.write_bytes(value)
        for name,value in v7.items():
            target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(value)
        for options in ([],['--apply']):subprocess.run(command+options,check=True)
        assert all((root/name).read_bytes()==value for name,value in new.items())
        assert env.read_bytes()==env_bytes and flag.read_bytes()==b'preserve-pause'
        assert other.read_bytes()==b'other-project'
        with closing(sqlite3.connect(db)) as connection:
            assert connection.execute('SELECT code FROM stocks').fetchone()[0]=='dynamic'
        # User's v8 reading ledger confirms the new runtime is active.
        # Reconstruct only files from that immutable delivered release.
        for name,value in old.items():
            target=root/name
            if value is None:target.unlink()
            else:target.write_bytes(value)
        for name,value in v8.items():
            target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(value)
        for options in ([],['--apply']):subprocess.run(command+options,check=True)
        assert all((root/name).read_bytes()==value for name,value in new.items())
        assert env.read_bytes()==env_bytes and flag.read_bytes()==b'preserve-pause'
        assert other.read_bytes()==b'other-project'
        with closing(sqlite3.connect(db)) as connection:
            assert connection.execute('SELECT code FROM stocks').fetchone()[0]=='dynamic'
        # Rehearse exact user-confirmed v9, not arbitrary current Git content.
        for name,value in old.items():
            target=root/name
            if value is None:target.unlink()
            else:target.write_bytes(value)
        for name,value in v9.items():
            target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(value)
        for options in ([],['--apply']):subprocess.run(command+options,check=True)
        assert all((root/name).read_bytes()==value for name,value in new.items())
        assert env.read_bytes()==env_bytes and flag.read_bytes()==b'preserve-pause'
        assert other.read_bytes()==b'other-project'
        with closing(sqlite3.connect(db)) as connection:
            assert connection.execute('SELECT code FROM stocks').fetchone()[0]=='dynamic'
        # Reconstruct the earlier baseline with the seven exact deployed spoken
        # files, then validate and apply together. Do not merely trust new code
        # idempotence as proof that the alternate old hashes are accepted.
        for name,value in old.items():
            target=root/name
            if value is None:target.unlink()
            else:target.write_bytes(value)
        for name,value in spoken.items():
            target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(value)
        for options in ([],['--apply']):subprocess.run(command+options,check=True)
        assert all((root/name).read_bytes()==value for name,value in new.items())
        assert env.read_bytes()==env_bytes and flag.read_bytes()==b'preserve-pause'
        assert other.read_bytes()==b'other-project'
        with closing(sqlite3.connect(db)) as connection:
            assert connection.execute('SELECT code FROM stocks').fetchone()[0]=='dynamic'
    with zipfile.ZipFile(output.with_suffix('.zip'),'w',zipfile.ZIP_DEFLATED) as archive:
        for path in output.iterdir():archive.write(path,output.name+'/'+path.name)
    return dict(file=str(output.with_suffix('.zip')),sha256=hashlib.sha256(output.with_suffix('.zip').read_bytes()).hexdigest(),files=len(names),rehearsal='baseline_spoken_and_installed_v4_v5_v6_v7_v8_v9_passed_no_service_or_model_calls')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True,type=Path)
    print(json.dumps(build(parser.parse_args().output),ensure_ascii=False,indent=2))
