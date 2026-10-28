"""Publish only the two confirmed finance Expo roots; no backend/model changes.

Default validation only. Keep old hashed assets for cached clients. Write new
assets before indexes. Back up all replaced files and roll back on exceptions.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from urllib.request import urlopen
import zipfile

from source_installer import atomic_write,destination

ROOTS=('mobile/dist','web')


def fingerprint(data):return hashlib.sha256(data).hexdigest()


def prepare(project,bundle,nginx_text,health):
    project=Path(project).resolve();bundle=Path(bundle)
    if health.get('status')!='healthy' or health.get('database')!='connected' or health.get('automation_paused') is not True or health.get('scheduler')!='stopped':
        raise RuntimeError('Backend must be healthy with automation paused')
    manifest=json.loads((bundle/'frontend-manifest.json').read_text(encoding='utf-8'))
    for name,expected in manifest['backend_prerequisites'].items():
        if fingerprint(destination(project,name).read_bytes().replace(b'\r\n',b'\n'))!=expected:
            raise RuntimeError('Consolidated backend not verified: '+name)
    targets=[]
    for relative in ROOTS:
        target=destination(project,relative)
        if any(parent.is_symlink() for parent in [target,*target.parents] if parent!=project.parent):
            raise RuntimeError('Symlink root is not supported')
        if not target.is_dir() or not (target/'index.html').is_file():
            raise RuntimeError('Existing finance frontend missing: '+relative)
        import re
        if not re.search(r'^\s*root\s+'+re.escape(target.as_posix())+r'\s*;',nginx_text,re.M):
            raise RuntimeError('Nginx root not confirmed: '+relative)
        targets.append(target)
    with zipfile.ZipFile(bundle/'frontend.zip') as archive:
        if len(archive.namelist())!=len(set(archive.namelist())) or set(archive.namelist())!=set(manifest['files']):
            raise RuntimeError('Frontend archive/manifest mismatch')
        content={}
        for name,expected in manifest['files'].items():
            if name.split('/')[0] not in {'_expo','assets','index.html','metadata.json','favicon.ico','manifest.json','apple-touch-icon.png'}:
                raise RuntimeError('Unexpected static path: '+name)
            for target in targets:
                path=destination(target,name)
                if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent.is_relative_to(target)):
                    raise RuntimeError('Symlink static path: '+name)
            data=archive.read(name)
            if fingerprint(data)!=expected:raise RuntimeError('Frontend checksum mismatch: '+name)
            content[name]=data
    if 'index.html' not in content or '_expo/' not in content['index.html'].decode('utf-8'):
        raise RuntimeError('Expo index missing')
    return targets,content


def publish(project,backup_root,targets,content):
    project=Path(project).resolve()
    backup=Path(backup_root)/('frontend-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(parents=True,mode=0o700)
    replaced={}
    # Complete every backup before replacing any live file.
    for target in targets:
        for name in content:
            path=destination(target,name);key=path.relative_to(project).as_posix()
            replaced[key]=path.is_file()
            if replaced[key]:
                copy=destination(backup,key);copy.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,copy)
    (backup/'restore-index.json').write_text(json.dumps(replaced),encoding='utf-8')
    try:
        for name in sorted(content,key=lambda name:(name=='index.html',name)):
            for target in targets:atomic_write(destination(target,name),content[name])
        for target in targets:
            for name,data in content.items():
                if fingerprint(destination(target,name).read_bytes())!=fingerprint(data):
                    raise RuntimeError('Published static verification failed')
    except Exception:
        for key,existed in replaced.items():
            path=destination(project,key)
            if existed:atomic_write(path,destination(backup,key).read_bytes())
            elif path.is_file():path.unlink()
        raise
    return backup


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    project=Path('/var/www/finance-daily');bundle=Path(__file__).resolve().parent
    nginx=subprocess.run(['nginx','-T'],capture_output=True,text=True,check=True).stdout
    with urlopen('http://127.0.0.1:8000/health',timeout=5) as response:health=json.load(response)
    targets,content=prepare(project,bundle,nginx,health)
    print('Frontend validation passed:',len(content),'files for mobile/dist and web')
    if not args.apply:
        print('Validation only. No files changed.');return
    backup=publish(project,Path('/var/backups/finance-daily'),targets,content)
    print('Private frontend backup:',backup)
    print('Frontend published. Backend, nginx config, database and automation pause were not changed.')


if __name__=='__main__':main()
