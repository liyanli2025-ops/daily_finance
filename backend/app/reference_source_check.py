"""Explicit one-shot public source checks; no model, credentials, or App writes."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import feedparser
import requests

from .services.overseas_sources import SOURCES, discover, parse_article, permitted

ENDPOINTS = {
    'fastbull': SOURCES['fastbull']['index'],
    'techcrunch': SOURCES['techcrunch']['index'],
    'mktnews': 'https://api.mktnews.net/api/flash?type=0&limit=50',
    'google_news': 'https://news.google.com/rss/search?q=China+Hong+Kong+markets+when:1d&hl=en-US&gl=US&ceid=US:en',
}
# Rest of World timed out in the reviewed local run. Existing failed
# BBC/Guardian/Reuters/Bloomberg/WSJ routes are not retested here either.
SKIPPED = dict(rest_of_world='observed_local_timeout_no_automatic_retest',
               legacy_failed_routes='use_existing_failure_ledger_no_retest')


def get(url):
    session = requests.Session()
    session.headers['User-Agent'] = 'Mozilla/5.0 (compatible; FinanceSourceAcceptance/1.0)'
    session.mount('https://', requests.adapters.HTTPAdapter(max_retries=0))
    response = session.get(url, timeout=(8, 12), allow_redirects=False)
    response.raise_for_status()
    if response.status_code != 200 or len(response.content) > 4*1024*1024:
        raise ValueError('reference_response_invalid')
    response.encoding = 'utf-8'
    return response


def inspect_one(name, root):
    path = root / (name + '.json')
    if path.exists():return json.loads(path.read_text(encoding='utf-8'))
    # Exclusive marker survives interruption. Never repeat network on rerun.
    marker = path.with_suffix('.started')
    try:
        with marker.open('x', encoding='utf-8') as stream:stream.write(datetime.now(timezone.utc).isoformat())
    except FileExistsError:return dict(source=name,status='interrupted_or_running_no_retest')
    row = dict(source=name, endpoint=ENDPOINTS[name], observed_at=datetime.now(timezone.utc).isoformat(),
               automatic_retries=0, http_requests=0, bodies=[])
    start=time.monotonic()
    try:
        row['http_requests']+=1
        response=get(ENDPOINTS[name]);row['http_status']=response.status_code
        if name in {'fastbull','techcrunch'}:
            entries=discover(name,response.text)
            row['discovery_count']=len(entries)
            # Deliberately limited source acceptance samples, not episode reading caps.
            for entry in entries[:2]:
                if not permitted(name,entry['url']):continue
                row['http_requests']+=1
                try:
                    detail=get(entry['url']);article=parse_article(name,detail.text,entry['url'])
                    row['bodies'].append(dict(title=article['title'],url=entry['url'],
                        characters=len(article['body']),published=article['published'],precision=article['precision']))
                except Exception as error:row['bodies'].append(dict(url=entry['url'],error_type=type(error).__name__))
            row['status']='body_samples_observed' if any(x.get('characters') for x in row['bodies']) else 'body_not_verified'
        elif name=='mktnews':
            entries=response.json().get('data',[])
            rows=[dict(title=(x.get('data') or {}).get('title') or (x.get('data') or {}).get('content','')[:160],
                       source_time=x.get('time'),wire_characters=len((x.get('data') or {}).get('content','')))
                  for x in entries if isinstance(x,dict)]
            row.update(status='wire_only_not_article_body',discovery_count=len(rows),examples=rows[:5])
        else:
            entries=feedparser.parse(response.content).entries
            row.update(status='directory_only_original_links_and_bodies_not_verified',discovery_count=len(entries),
                       examples=[dict(title=x.get('title'),source_time=x.get('published')) for x in entries[:5]])
    except Exception as error:
        row.update(status='failed_this_environment_no_retest',error_type=type(error).__name__,
                   http_status=getattr(getattr(error,'response',None),'status_code',None))
    finally:
        row['elapsed_seconds']=round(time.monotonic()-start,2)
        path.write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
    return row


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--run',action='store_true')
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent.parent/'data/diagnostics/reference-source-check')
    args=parser.parse_args()
    preview=dict(mode='explicit_public_collection' if args.run else 'free_preview_no_network',
                 endpoints=ENDPOINTS,skipped=SKIPPED,max_http_requests=8,model_requests=0,
                 limitation='一次公开入口与少量正文样本；本机结果不代表其他网络或全时段稳定。无自动重试、搜索补读、LLM、TTS、App写入或调度恢复。')
    if args.run:
        args.root.mkdir(parents=True,exist_ok=True)
        with ThreadPoolExecutor(max_workers=4) as pool:
            preview['results']=list(pool.map(lambda name:inspect_one(name,args.root),ENDPOINTS))
        (args.root/'summary.json').write_text(json.dumps(preview,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(preview,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
