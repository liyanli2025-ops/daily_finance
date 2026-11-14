"""One bounded public-source diagnostic, without models, Tavily or edition writes."""
import argparse
import asyncio
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

LIST_URL = 'https://np-anotice-stock.eastmoney.com/api/security/ann'
BODY_URL = 'https://np-cnotice-stock.eastmoney.com/api/content/ann'
MAX_REQUESTS = 12
MAX_BYTES = 2 * 1024 * 1024


def regular(path):
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError('source_check_file_invalid')
    return path.read_bytes()


def write_json(path, value, *, exclusive=False):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('source_check_symlink')
    flags=os.O_WRONLY|os.O_CREAT|(os.O_EXCL if exclusive else os.O_TRUNC)
    fd=os.open(path,flags,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)


def prepare(project, identifier):
    if not re.fullmatch(r'edition-[0-9a-f]{32}', identifier):
        raise ValueError('source_check_edition_id_invalid')
    path=project/'backend/data/editions'/identifier/'result.json'
    raw=regular(path);state=json.loads(raw)
    stocks=state['watchlist']
    if (state.get('id')!=identifier or not state.get('manual_text_only')
            or state.get('app_written') or state.get('tts_attempts')
            or not stocks or len(stocks)>4
            or any(s['market']!='A' or not re.fullmatch(r'\d{6}',s['code']) for s in stocks)):
        raise ValueError('source_check_scope_invalid')
    return path,raw,state


def collect(state, collector, transport, now):
    from app.services.collection_time import window
    from app.services.primary_material_quality import review_body
    rows=[]
    for stock in state['watchlist']:
        try:
            items,status=collector(SimpleNamespace(**stock),now=now,
                hours=window(now,'company_event')['hours'],request_get=transport,
                max_announcements=1,max_pages=2,deadline=transport.deadline)
            rows.append(dict(stock=stock,status=status,articles=[dict(
                id=item.id,title=item.title,url=item.source_url,published_at=item.published_at.isoformat(),
                text=item.content,characters=len(item.content),body_quality=review_body(item.content),
                source_type='public_disclosure_mirror_not_exchange_original',
                used_for_edition=False,independently_verified=False) for item in items]))
        except Exception as error:
            rows.append(dict(stock=stock,status=dict(status='failed',error_type=type(error).__name__),articles=[]))
    return rows


class PublicTransport:
    def __init__(self, folder, state, request_get=None, *, max_requests=MAX_REQUESTS):
        import requests
        self.folder,self.codes=folder,{s['code'] for s in state['watchlist']}
        self.allowed_articles=set();self.receipts=[];self.deadline=time.monotonic()+90
        self.max_requests=max_requests
        self.request_get=request_get or requests.get

    def __call__(self,url,**kwargs):
        if (url not in {LIST_URL,BODY_URL} or urlsplit(url).scheme!='https'
                or time.monotonic()>=self.deadline or len(self.receipts)>=self.max_requests):
            raise ValueError('source_check_request_boundary')
        params=kwargs.get('params',{})
        if url==LIST_URL:
            if (params.get('stock_list') not in self.codes or params.get('page_size')!=20
                    or params.get('page_index')!=1):
                raise ValueError('source_check_list_scope')
        elif (params.get('art_code') not in self.allowed_articles
                or params.get('page_index') not in {1,2}):
            raise ValueError('source_check_article_scope')
        signature=json.dumps([url,params],sort_keys=True)
        if any(row['signature']==signature for row in self.receipts):
            raise ValueError('source_check_no_retry')
        row=dict(number=len(self.receipts)+1,url=url,parameters=params,signature=signature,status='started')
        self.receipts.append(row);write_json(self.folder/'requests.json',self.receipts)
        response=None
        try:
            response=self.request_get(url,params=params,timeout=min(8,max(.1,self.deadline-time.monotonic())),
                headers={'User-Agent':'Mozilla/5.0'},allow_redirects=False,stream=True)
            row['http_status']=response.status_code
            if response.status_code!=200:raise ValueError('source_check_non_200')
            chunks=[];size=0
            for chunk in response.iter_content(65536):
                size+=len(chunk)
                if size>MAX_BYTES or time.monotonic()>=self.deadline:
                    raise ValueError('source_check_response_limit')
                chunks.append(chunk)
            raw=b''.join(chunks);data=json.loads(raw)
            filename='response-'+str(row['number'])+'.json'
            fd=os.open(self.folder/filename,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as stream:stream.write(raw)
            row.update(status='received',capture=filename,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
            if url==LIST_URL:
                listing=data.get('data',{}).get('list')
                if isinstance(listing,list):
                    for item in listing:
                        if (any(str(c.get('stock_code'))==params['stock_list'] for c in item.get('codes',[]))
                                and re.fullmatch(r'AN\d+',str(item.get('art_code','')))):
                            self.allowed_articles.add(item['art_code'])
            return SimpleNamespace(raise_for_status=lambda:None,json=lambda:data)
        except Exception as error:
            row.update(status='failed',error_type=type(error).__name__)
            raise
        finally:
            if response is not None:response.close()
            write_json(self.folder/'requests.json',self.receipts)


def load_collector():
    package=Path(__file__).parent.parent
    source=package/'backend/app/services/watchlist_sources.py'
    regular(source)
    spec=importlib.util.spec_from_file_location('app.services._company_source_diagnostic',source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.fetch_company_announcements


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--edition-id',required=True)
    parser.add_argument('--run-public',action='store_true')
    parser.add_argument('--export-review',type=Path)
    args=parser.parse_args()
    path,raw,state=prepare(args.project,args.edition_id)
    folder=args.project/'backend/data/diagnostics/company-source-path-v1'/args.edition_id
    if args.export_review:
        import zipfile
        if not (folder/'result.json').is_file():raise SystemExit('没有已完成的本地诊断结果')
        if args.export_review.is_symlink():raise SystemExit('导出路径不允许软链')
        with args.export_review.open('xb') as stream,zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(folder.iterdir()):
                if file.is_file():archive.writestr(file.name,regular(file))
        print(json.dumps(dict(mode='offline_export',file=str(args.export_review),model_requests=0,search_requests=0,public_requests=0),ensure_ascii=False));return
    if (folder/'result.json').is_file():
        result=json.loads(regular(folder/'result.json'));result['reused_without_requests']=True
        result.pop('requests',None)
        result['rows']=[dict(r,articles=[{k:v for k,v in item.items() if k!='text'}
            for item in r['articles']]) for r in result['rows']]
        result['result_file']=str(folder/'result.json')
        print(json.dumps(result,ensure_ascii=False,indent=2));return
    if (folder/'started.json').exists():raise SystemExit('这个诊断已开始但未完成；保留现场，不自动重试')
    plan=dict(mode='public_company_source_preview',edition_id=args.edition_id,
        cutoff=state['cutoff'],watchlist=state['watchlist'],max_public_http_requests=MAX_REQUESTS,
        per_company='1个公告列表，最多1份公告及2页完整正文；超过页数不当完整正文',
        model_requests=0,search_requests=0,tts_requests=0,edition_writes=0,
        limitation='尚未联网；只验证东方财富公告镜像通道，不证明所有新闻覆盖或官方原件核验。')
    if not args.run_public:print(json.dumps(plan,ensure_ascii=False,indent=2));return
    sys.path.insert(0,str(args.project/'backend'))
    from app.services.watchlist_repository import read_app_watchlist,watchlist_signature
    from app.services.model_gateway import MODEL_PAUSE_FILE
    if not MODEL_PAUSE_FILE.is_file():raise SystemExit('维护暂停未保留，停止诊断')
    if watchlist_signature(asyncio.run(read_app_watchlist()))!=watchlist_signature(state['watchlist']):
        raise SystemExit('当前App自选股与本期不一致，停止')
    if any(p.is_symlink() for p in (folder,*folder.parents)):raise SystemExit('诊断路径含软链')
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    write_json(folder/'started.json',dict(edition_id=args.edition_id,original_sha256=hashlib.sha256(raw).hexdigest()),exclusive=True)
    collector=load_collector();transport=PublicTransport(folder,state)
    rows=collect(state,collector,transport,datetime.fromisoformat(state['cutoff']))
    if regular(path)!=raw:raise SystemExit('原期结果发生变化，停止输出完成结论')
    result=dict(plan,mode='completed_public_company_source_check',rows=rows,
        public_http_requests=len(transport.receipts),requests=transport.receipts,
        full_texts=sum(len(r['articles']) for r in rows),original_result_unchanged=True,
        production_source_installed=False,edition_resumed=False,content_accepted=False,
        limitation='原截止的有限通道验证，公开观察发生在现在；不证明截止时已公开、重大性、事实或完整公司新闻覆盖。'
        '镜像不冒充交易所原件，空列表不代表没有事件；原费用/截止/失败标记不改。')
    write_json(folder/'result.json',result,exclusive=True)
    printed=dict(result)
    printed['rows']=[dict(r,articles=[{k:v for k,v in item.items() if k!='text'} for item in r['articles']]) for r in rows]
    printed['result_file']=str(folder/'result.json');printed.pop('requests')
    print(json.dumps(printed,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
