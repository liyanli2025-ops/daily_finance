"""Verify the standalone source diagnostic with fake responses and blocked sockets."""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    args=parser.parse_args();package=Path(__file__).parent.parent
    manifest=json.loads((package/'source-check-manifest.json').read_text())
    for name,expected in manifest['package_files'].items():
        file=package/name
        if any(p.is_symlink() for p in (file,*file.parents)) or hashlib.sha256(file.read_bytes()).hexdigest()!=expected:
            raise SystemExit('诊断交付文件不符：'+name)
    for name,expected in manifest['server_prerequisites'].items():
        file=args.project/name
        if any(p.is_symlink() for p in (file,*file.parents)) or not file.is_file() or hashlib.sha256(file.read_bytes().replace(b'\r\n',b'\n')).hexdigest()!=expected:
            raise SystemExit('服务器依赖版本不符：'+name)
    sys.path.insert(0,str(args.project/'backend'))
    def blocked(*args,**kwargs):raise AssertionError('offline source checks forbid network')
    with patch.object(socket.socket,'connect',blocked),patch.object(socket.socket,'connect_ex',blocked):
        suite=unittest.defaultTestLoader.discover(str(package/'backend/tests'),pattern='test_company_source_path.py')
        result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful() or result.testsRun!=manifest['test_count']:
        raise SystemExit('免费隔离检查未全部通过，停止，不允许继续联网诊断')
    print('10项离线边界检查通过；未安装源码、未重启服务、未联网。')


if __name__=='__main__':main()
