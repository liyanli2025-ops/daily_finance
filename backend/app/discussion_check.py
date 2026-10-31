"""Default: free capability preview. --samples: offline replay. --run: one public sample.

No LLM/TTS, report publication, App writes or scheduler changes.
"""
import argparse,asyncio,json
from pathlib import Path

from .services.community_sources import CommunityCollector,INDEXES,NAMES,provider_for,discover,parse_thread
from .services.research_hub import save_json
from .services.time_context import china_now

DATA=Path(__file__).resolve().parents[1]/'data'
OUTPUT=DATA/'radar'/'discussion-check.json'


def summary(data):
    return {key:data.get(key) for key in ('mode','collected_at','directories','threads','statements',
        'statements_with_author','distinct_display_names','replies','source_counts','read','status','limitation')}


def replay(folder):
    directories=[];threads=[];rejected=[]
    for path in sorted(Path(folder).glob('*.json')):
        try:row=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):continue
        if not isinstance(row,dict) or not row.get('url') or not row.get('id'):continue
        page=Path(folder)/(row['id']+'.html')
        if not page.exists():continue
        url=row['url']
        try:
            try:provider=provider_for(url,True);index=True
            except ValueError:provider=provider_for(url);index=False
            raw=page.read_text(encoding='utf-8')
            if index:directories.append(dict(url=url,provider=provider,candidates=discover(provider,raw,url)))
            else:threads.append(parse_thread(raw,url))
        except ValueError as error:rejected.append(dict(url=url,reason=str(error)))
    records=[s for t in threads for s in t['statements']]
    from collections import Counter
    result=dict(owner='finance-discussion-check-v1',mode='saved_public_pages_offline_replay',
        collected_at=china_now().isoformat(),directories=len(directories),threads=len(threads),
        statements=len(records),statements_with_author=sum(bool(s['author']) for s in records),
        distinct_display_names=len({s['author'] for s in records if s['author']}),
        replies=sum(s['position'].startswith(('answer:','reply')) for s in records),
        source_counts=dict(Counter(t['provider'] for t in threads)),
        directory_records=directories,thread_records=threads,rejected=rejected,
        http_requests=0,model_requests=0,
        limitation='已保存公开HTML的解析回放，不是新网络请求或全量论坛覆盖。用户说法未核实，缺日期/身份不补猜。')
    save_json(OUTPUT,result);return result


async def run():
    from .services.watchlist_repository import read_app_watchlist
    from .services.watchlist_service import WatchlistStock
    # An immutable attempt marker prevents terminal reconnects from starting a
    # second sample. It contains no post text and does not enable scheduling.
    marker=DATA/'diagnostics'/'discussion-network-sample-v1.started'
    marker.parent.mkdir(parents=True,exist_ok=True)
    if marker.exists():return dict(status='sample_already_attempted_no_repeat',output=str(OUTPUT))
    rows=await read_app_watchlist()
    stocks=[WatchlistStock(row['code'],row['name'],row['market']) for row in rows]
    with marker.open('x',encoding='utf-8') as f:f.write(china_now().isoformat())
    news,coverage=await asyncio.to_thread(CommunityCollector().collect,stocks)
    result=dict(owner='finance-discussion-check-v1',mode='public_network_sample',
        collected_at=china_now().isoformat(),**coverage)
    save_json(OUTPUT,result);return result


def main():
    parser=argparse.ArgumentParser()
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--samples');mode.add_argument('--run',action='store_true')
    args=parser.parse_args()
    if args.samples:result=replay(args.samples)
    elif args.run:result=asyncio.run(run())
    else:
        result=dict(mode='free_preview',providers=NAMES,indexes=INDEXES,
            local_body_samples_verified=['guba','jisilu','taoguba','tradingview'],
            server_network_verified=False,http_requests=0,model_requests=0,
            note='--samples仅回放已有HTML；--run读取App动态名单并做一次公开网络样本，不生成节目或恢复调度。')
        print(json.dumps(result,ensure_ascii=False,indent=2));return
    print(json.dumps(dict(**summary(result),output=str(OUTPUT)),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
