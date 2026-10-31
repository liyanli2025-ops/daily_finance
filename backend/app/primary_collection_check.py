"""Default offline review. --run-public explicitly adds public supplements only."""
import argparse,asyncio,hashlib,json
from pathlib import Path
from .services.search_primary_collection import prepare,collect
from .services.research_hub import save_json


async def preview():
    from .services.web_research import capabilities
    from .services.watchlist_repository import read_app_watchlist
    from .services.search_primary_collection import search_agenda
    from .services.time_context import china_now
    try:stocks=await read_app_watchlist();status='read_from_app_database'
    except RuntimeError:stocks=[];status='unavailable_no_cached_fallback'
    return dict(mode='free_capability_preview',search=capabilities(),watchlist_status=status,
        watchlist=stocks,planned_searches=search_agenda(stocks,china_now()),
        http_requests_performed=0,model_requests_performed=0,tts_requests_performed=0,
        automation_changed=False,
        limitation='只读本地配置/数据库并展示检索计划，没有执行搜索或采集；配置可用性和来源质量尚未网络验证。')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path)
    parser.add_argument('--run-public',action='store_true');parser.add_argument('--input-sha256')
    args=parser.parse_args()
    if args.input is None:
        if args.run_public or args.input_sha256:parser.error('执行联合采集必须先提供实际资料包')
        print(json.dumps(asyncio.run(preview()),ensure_ascii=False,indent=2));return
    raw=args.input.read_bytes();sha=hashlib.sha256(raw).hexdigest()
    bundle=json.loads(raw)
    if args.run_public:
        if args.input_sha256!=sha:parser.error('--run-public须提供本次输入SHA256，防止误用旧资料')
        data=Path(__file__).resolve().parents[1]/'data'
        # Stable attempt marker: reconnect cannot repeat even a failed run.
        marker=data/'diagnostics'/('primary-collection-'+sha+'.started')
        if marker.exists():raise RuntimeError('本输入已尝试联合采集；保留开始标记，不重复请求')
        prepare(bundle)  # Stale/malformed input must fail before any network.
        marker.parent.mkdir(parents=True,exist_ok=True)
        with marker.open('x',encoding='utf-8') as f:f.write(sha)
        result=asyncio.run(collect(bundle));save_json(data/'radar'/'search-primary-check.json',result)
        result={key:value for key,value in result.items() if key not in {'news','technical','microstructure','coverage'}}
    else:
        _,result=prepare(bundle);result.update(mode='offline_intake_review',input_sha256=sha)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
