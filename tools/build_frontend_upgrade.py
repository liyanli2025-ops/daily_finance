"""Package an already built/tested Expo export and rehearse isolated publication."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import zipfile


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module;spec.loader.exec_module(module);return module


def build(assets,output):
    assets=Path(assets).resolve();output=Path(output).resolve();repo=Path(__file__).resolve().parents[1]
    if output.exists() or output.with_suffix('.zip').exists():raise RuntimeError('Immutable output exists')
    if not (assets/'index.html').is_file():raise RuntimeError('Build export missing')
    files={p.relative_to(assets).as_posix():p.read_bytes() for p in assets.rglob('*') if p.is_file()}
    sha=lambda data:hashlib.sha256(data).hexdigest()
    prerequisites={name:sha((repo/name).read_bytes().replace(b'\r\n',b'\n')) for name in (
        'backend/app/routers/stocks.py','backend/app/services/watchlist_preparation.py')}
    output.mkdir(parents=True)
    manifest=dict(files={name:sha(data) for name,data in files.items()},backend_prerequisites=prerequisites)
    (output/'frontend-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    with zipfile.ZipFile(output/'frontend.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in files.items():archive.writestr(name,data)
    (output/'install_frontend.py').write_bytes((repo/'tools/install_frontend_upgrade.py').read_bytes())
    (output/'source_installer.py').write_bytes((repo/'tools/install_paused_upgrade.py').read_bytes())
    load('source_installer',output/'source_installer.py');installer=load('frontend_installer_rehearsal',output/'install_frontend.py')
    health=dict(status='healthy',database='connected',scheduler='stopped',automation_paused=True)
    with tempfile.TemporaryDirectory(prefix='finance-frontend-rehearsal-') as folder:
        root=Path(folder)/'finance-daily';backup=Path(folder)/'backups'
        for name in prerequisites:
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((repo/name).read_bytes())
        roots=[root/name for name in installer.ROOTS]
        for target in roots:
            target.mkdir(parents=True);(target/'index.html').write_bytes(b'old-index');(target/'old-client-asset.js').write_bytes(b'keep')
        other=Path(folder)/'another-project';other.mkdir();(other/'index.html').write_bytes(b'other')
        flag=root/'backend/data/.automation-paused';flag.parent.mkdir();flag.write_bytes(b'paused')
        nginx='\n'.join('root '+path.as_posix()+';' for path in roots)
        before={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
        targets,content=installer.prepare(root,output,nginx,health)
        assert before=={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
        for bad_nginx,bad_health in [('',health),(nginx,dict(health,automation_paused=False))]:
            try:installer.prepare(root,output,bad_nginx,bad_health)
            except RuntimeError:pass
            else:raise AssertionError('Unconfirmed root or resumed backend accepted')
        original=installer.atomic_write;calls=0
        def fail_once(*args,**kwargs):
            nonlocal calls
            calls+=1
            if calls==3:raise OSError('simulated static write failure')
            return original(*args,**kwargs)
        with patch.object(installer,'atomic_write',side_effect=fail_once):
            try:installer.publish(root,backup,targets,content)
            except OSError:pass
            else:raise AssertionError('Fault injection failed')
        assert before=={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
        installer.publish(root,backup,targets,content);installer.publish(root,backup,targets,content)
        for target in targets:
            assert all((target/name).read_bytes()==data for name,data in content.items())
            assert (target/'old-client-asset.js').read_bytes()==b'keep'
        assert flag.read_bytes()==b'paused' and (other/'index.html').read_bytes()==b'other'
    (output/'README.txt').write_text('Validate: sudo python3 install_frontend.py\nApply after successful validation: sudo python3 install_frontend.py --apply\nOnly mobile/dist and web. Requires matching consolidated backend, existing nginx roots and paused health. Backs up replaced files; keeps old hashed assets. No nginx/service/database/model changes.\n',encoding='utf-8')
    with zipfile.ZipFile(output.with_suffix('.zip'),'w',zipfile.ZIP_DEFLATED) as archive:
        for path in output.iterdir():archive.write(path,output.name+'/'+path.name)
    return dict(file=str(output.with_suffix('.zip')),sha256=sha(output.with_suffix('.zip').read_bytes()),files=len(files),rehearsal='validation_no_write,wrong_root_and_pause_rejected,fault_rollback,repeated_publication,other_project_and_pause_preserved')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--assets',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();print(json.dumps(build(args.assets,args.output),indent=2))
