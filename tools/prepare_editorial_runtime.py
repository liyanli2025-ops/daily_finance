"""Derive a runtime-only staging bundle from one checksum-pinned release.

Never changes the source ZIP, project files, old hashes or installer protections.
"""
import argparse
from io import BytesIO
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile

EXPECTED='fea5019be7f81a2361381c4b3fd43e2516d05ad34f234a8f64a4fee31a5a93d1'
PREFIX='finance-editorial-flow-upgrade/'


def prepare(source,output,expected=EXPECTED):
    raw=Path(source).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected:
        raise RuntimeError('原升级包校验不匹配，停止；不修改服务器项目')
    output=Path(output)
    if output.exists() and any(output.iterdir()):raise RuntimeError('目标暂存目录非空，停止覆盖')
    with zipfile.ZipFile(BytesIO(raw)) as outer:
        manifest=json.loads(outer.read(PREFIX+'manifest.json'))
        installer=outer.read(PREFIX+'install_upgrade.py')
        with zipfile.ZipFile(BytesIO(outer.read(PREFIX+'payload.zip'))) as payload:
            if set(payload.namelist())!=set(manifest['files']):raise RuntimeError('原清单与文件不一致')
            kept={key:value for key,value in manifest['files'].items() if not key.startswith('backend/tests/')}
            bodies={key:payload.read(key) for key in kept}
    output.mkdir(parents=True,exist_ok=True,mode=0o700)
    manifest['files']=kept
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    (output/'install_upgrade.py').write_bytes(installer)
    with zipfile.ZipFile(output/'payload.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for key,value in bodies.items():archive.writestr(key,value)
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('source',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    output=args.output or Path(tempfile.mkdtemp(prefix='finance-editorial-runtime-'))
    print(prepare(args.source,output))
