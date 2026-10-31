"""Reproduce old/new parsing on saved HTML, not on the live Internet."""
import argparse
from datetime import datetime
import hashlib,json
from pathlib import Path
import subprocess,sys,types
from unittest.mock import patch


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',required=True,type=Path)
    parser.add_argument('--archive-root',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--dependencies',type=Path);args=parser.parse_args()
    repo=Path(__file__).resolve().parents[1]
    if args.dependencies:sys.path.insert(0,str(args.dependencies.resolve()))
    sys.path.insert(0,str(repo/'backend'))
    from app.services.web_research import parse_visible_article
    from app.services.generic_extraction import extract_main_text,reader_kind
    source=subprocess.check_output(['git','-C',str(repo),'show','f24230c:backend/app/services/web_research.py'])
    baseline=types.ModuleType('app.services._frozen_baseline_reader');baseline.__package__='app.services'
    exec(compile(source,'reviewed-f24230c-web_research.py','exec'),baseline.__dict__)
    root=args.archive_root.resolve();rows=[];cutoff=datetime(2026,10,31,16)
    with (patch('requests.get',side_effect=AssertionError('offline replay')),
          patch('requests.post',side_effect=AssertionError('offline replay')),
          patch('socket.create_connection',side_effect=AssertionError('offline replay'))):
        for original in json.loads(args.manifest.read_text(encoding='utf-8')):
            path=(root/original['file']).resolve()
            if not path.is_relative_to(root) or path.suffix!='.html':raise ValueError('replay_path_invalid')
            raw=path.read_bytes();url=original['url']
            row=dict(file=original['file'],url=url,html_sha256=hashlib.sha256(raw).hexdigest(),kind=reader_kind(url))
            for name,parse in [('old',baseline.parse_visible_article),('new',parse_visible_article)]:
                try:
                    item=parse(raw,url,cutoff)
                    row[name]=dict(status='admitted',title=item.title,characters=len(item.content),source=item.source,time_note=item.market_impact)
                except Exception as error:
                    row[name]=dict(status='not_admitted',reason=str(error) if len(str(error))<100 else type(error).__name__)
            candidate=extract_main_text(raw,url)
            row['generic']={key:value for key,value in candidate.items() if key!='text'}
            row['generic']['characters']=len(candidate.get('text',''));rows.append(row)
    old={r['file'] for r in rows if r['old']['status']=='admitted'}
    new={r['file'] for r in rows if r['new']['status']=='admitted'}
    result=dict(mode='saved_html_no_network',cutoff=cutoff.isoformat(),baseline_revision='f24230c',documents=len(rows),
        old_admitted=len(old),new_admitted=len(new),recovered=sorted(new-old),regressed=sorted(old-new),
        model_requests=0,search_requests=0,publisher_http_requests=0,rows=rows,
        limitation='同一批曾成功下载的HTML；不代表服务器联网、失败URL已修复或内容正确。文本提取与日期/权限准入分开统计。')
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
