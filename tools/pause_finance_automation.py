"""Checksum-protected pause: App reading stays available, no model calls."""
import ast
from datetime import datetime,timezone
import hashlib
import os
from pathlib import Path
import shutil
import tempfile

PATCHES={'backend/app/main.py': {'before': '0bba37766ac5baf2a3fe5535f6455eef65bbcf4bc9c1749511fc0772cce8ae07', 'after': 'deb38b6a26429701113cc3fcf8a995895f5fa1134261afbe02eb000f71f508d9', 'edits': [(31, 31, "def automation_paused():\n    return (Path(__file__).resolve().parents[1]/'data'/'.automation-paused').exists()\n\n\n"), (49, 50, "    if automation_paused():\n        print('[维护暂停] 财经自动采集和定时生成未启动')\n    else:\n        await scheduler_service.start()\n"), (51, 52, "    print('[OK] 定时调度器状态：'+('运行' if scheduler_service.is_running else '已暂停'))\n"), (129, 130, '        "scheduler": "running" if scheduler_service and scheduler_service.is_running else "stopped",\n        "automation_paused": automation_paused()\n')]}, 'backend/app/services/model_gateway.py': {'before': '10baa1be7535abca8eafe261608f1b4a3029f685dde4baf18cb3569999aff48a', 'after': 'b75c82b900fd563c5dcc12c5d22323b25ed475a4127d0170b1f82b2453ab4217', 'edits': [(9, 9, 'from pathlib import Path\n'), (17, 17, "MODEL_PAUSE_FILE=Path(__file__).resolve().parents[2]/'data'/'.automation-paused'\n\n\ndef ensure_models_enabled():\n    if MODEL_PAUSE_FILE.exists():\n        raise RuntimeError('维护暂停：全部模型请求已阻止，等待用户明确恢复')\n"), (150, 150, '    ensure_models_enabled()\n'), (159, 159, '            ensure_models_enabled()\n')]}}


def pause(project,backup_root,patches=PATCHES):
    project=Path(project).resolve()
    prepared=[]
    for name,item in patches.items():
        path=project/name
        if path.is_symlink() or not path.resolve().is_relative_to(project):raise RuntimeError('Unexpected target path')
        raw=path.read_bytes().replace(b'\r\n',b'\n')
        digest=hashlib.sha256(raw).hexdigest()
        if digest not in {item['before'],item['after']}:raise RuntimeError('Source differs; no changes: '+name)
        if digest==item['before']:
            lines=raw.decode('utf-8').splitlines(keepends=True)
            for start,end,text in reversed(item['edits']):lines[start:end]=[text]
            raw=''.join(lines).encode('utf-8')
        if hashlib.sha256(raw).hexdigest()!=item['after']:raise RuntimeError('Patch checksum failed')
        ast.parse(raw.decode('utf-8'),filename=name)
        prepared.append((name,path,raw))
    flag=project/'backend/data/.automation-paused'
    if flag.is_symlink() or not flag.parent.resolve().is_relative_to(project):raise RuntimeError('Unexpected pause path')
    backup=Path(backup_root)/('automation-pause-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(parents=True,mode=0o700)
    for name,path,raw in prepared:
        target=backup/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    flag.parent.mkdir(parents=True,exist_ok=True)
    descriptor=os.open(flag,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600);os.close(descriptor)
    for name,path,raw in prepared:
        stat=path.stat();descriptor,temporary=tempfile.mkstemp(prefix='.automation-pause-',dir=path.parent)
        try:
            with os.fdopen(descriptor,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
            os.chmod(temporary,stat.st_mode & 0o777)
            if hasattr(os,'geteuid') and os.geteuid()==0:os.chown(temporary,stat.st_uid,stat.st_gid)
            os.replace(temporary,path)
        finally:
            if os.path.exists(temporary):os.unlink(temporary)
    return backup
