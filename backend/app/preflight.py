"""python -m app.preflight: inspect this deployment without exposing secrets."""
import asyncio
import json
import shutil

from .services.model_gateway import resolve_route
from .services.watchlist_repository import read_app_watchlist


async def check_model_access():
    """Explicit opt-in tiny request: not a full-report budget or accuracy test."""
    import httpx
    from .services.model_gateway import request_for, completed_text, service_error
    result={'scope':'一次短模型请求，会产生少量费用；成功不代表足够支付整期报告。'}
    try:
        route=resolve_route('analysis')
        url,headers,body=request_for(route,[{'role':'user','content':'Reply with OK only.'}],64)
        result.update(provider=route.provider,model=route.model)
        async with httpx.AsyncClient(timeout=30) as client:
            response=await client.post(url,headers=headers,json=body)
        result['http_status']=response.status_code
        if response.is_error:
            result.update(ready=False,reason=str(service_error('analysis',response)))
        else:
            text=completed_text(route,response.json())
            result.update(ready=True,reply='OK' if text.strip()=='OK' else '收到完整短回复')
    except Exception as error:
        result.update(ready=False,error=type(error).__name__)
    return result


async def check_market_sources():
    from .services.market_data_service import get_market_data_service
    overview=await get_market_data_service().get_market_overview()
    return dict(ready=bool(overview.indices),scope='仅公开指数来源检查，不调用模型，不写数据库',
                **overview.to_dict())


async def acceptance_without_models(news_hours=24):
    """One operator check for deployment and live public sources, with zero model/TTS calls."""
    local=await inspect()
    result=dict(local=local,scope='统一非付费检查：配置、数据库、音频依赖、公开行情及当前自选股资料；不调用模型或合成音频。',
                paid_acceptance_pending=True)
    if not local['watchlist'].get('readable'):
        result['ready']=False
        return result
    market=await check_market_sources()
    result['market']={key:market[key] for key in ('ready','date','indices','global_indices','source_status')}
    from .source_check import inspect as inspect_sources
    sources=await inspect_sources(research=True,hours=news_hours)
    result['news_window_hours']=news_hours
    result['stocks']=sources['stocks']
    result['research']=[dict(key=row['key'],coverage=row['coverage'],
        materials=[{key:doc.get(key) for key in ('title','kind','published_at','reading_status','source_url')}
                   for doc in row.get('materials',[])]) for row in sources['research']['stocks']]
    result['ready']=bool(local['ready'] and market['ready'])
    result['limitation']='ready只表示本次本地依赖与指数检查可用；资料缺口逐项列出，不代表分析准确或整期播客验收通过。'
    return result


async def inspect():
    result = {"ready": True, "models": {}, "watchlist": {}, "audio": {}}
    for task in ("analysis", "review", "extraction", "podcast"):
        try:
            route = resolve_route(task)
            result["models"][task] = {"provider": route.provider, "model": route.model,
                                      "effort": route.effort, "configured": True}
        except (RuntimeError, ValueError) as error:
            result["models"][task] = {"configured": False, "error": str(error)}
            result["ready"] = False
    try:
        stocks = await read_app_watchlist()
        result["watchlist"] = {"readable": True, "count": len(stocks), "stocks": stocks}
    except RuntimeError as error:
        result["watchlist"] = {"readable": False, "error": str(error)}
        result["ready"] = False
    for program in ("ffmpeg", "ffprobe"):
        result["audio"][program] = bool(shutil.which(program))
        if not result["audio"][program]:
            result["ready"] = False
    result["scope"] = "仅检查配置与本地依赖，未验证模型授权、网络服务、新闻源或音色"
    return result


if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser()
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--model-check',action='store_true')
    mode.add_argument('--acceptance',action='store_true')
    mode.add_argument('--market-check',action='store_true')
    parser.add_argument('--news-hours',type=int,default=24)
    args=parser.parse_args()
    if not 1<=args.news_hours<=168:
        parser.error('--news-hours must be between 1 and 168')
    result = asyncio.run(check_model_access() if args.model_check else
                         acceptance_without_models(args.news_hours) if args.acceptance else
                         check_market_sources() if args.market_check else inspect())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ready"] else 2)
