"""Standalone v18-compatible Tavily sample. Default preview never uses network.

--run: <=4 basic search POSTs, <=4 public body URLs (<=3 GETs each),
no retries, LLM, Tavily Extract/Research, TTS, App writes or scheduler changes.
"""
import argparse,asyncio,json,sys,time
from pathlib import Path
from unittest.mock import patch


def setup():
    cwd=Path.cwd()
    backend=cwd if (cwd/'app/config.py').is_file() else cwd/'backend'
    if not (backend/'app/config.py').is_file():raise RuntimeError('请先cd /var/www/finance-daily/backend')
    sys.path.insert(0,str(backend.resolve()))
    return backend.resolve()


def queries_for(stocks,now):
    day=now.strftime('%Y年%m月%d日')
    queries=[dict(lane='a_market',query=day+' A股 最近交易日 收盘 主要指数 成交额 板块异动'),
        dict(lane='hk_market',query=day+' 港股 最近交易日 收盘 恒生科技 重要消息'),
        dict(lane='us_market',query=now.strftime('%Y-%m-%d')+' US stock market latest close technology earnings AI')]
    if stocks:
        s=stocks[0]
        queries.append(dict(lane='watchlist_sample',scope=s['market']+':'+s['code'],
            query=day+' '+s['name']+' '+s['code']+' 重要消息 经营变化 行业风险'))
    else:queries.append(dict(lane='industry',query=day+' 半导体 电池 产业链 供需 重要变化'))
    return queries


def brief(result):
    return {key:result.get(key) for key in ('status','started_at','finished_at','queries_planned',
        'search_http_attempts','public_body_urls_attempted','readable_body_count','search_samples',
        'body_samples','not_tested_watchlist','model_requests','tts_requests','result_file',
        'workspace','limitation','error_type') if key in result}


def sample(workspace,queries,search,read_public,checkpoint,now,max_queries=4):
    """Injected adapters permit offline outcome tests, not vendor billing tests."""
    if type(max_queries) is not int or not 1<=max_queries<=4:raise ValueError('sample_search_budget_invalid')
    from app.services.source_health import PAUSED_PUBLIC_ARTICLES
    from app.services.event_observations import canonical
    from app.services.evidence import article_url
    result=dict(status='running',started_at=now.isoformat(),queries_planned=queries,
        search_http_attempts=0,public_body_urls_attempted=0,readable_body_count=0,
        search_samples=[],body_samples=[],search_results=[],body_results=[],model_requests=0,tts_requests=0,
        limitation='小样本联网/目录/正文验收，不代表全市场覆盖、搜索已充分或事实已独立核实。未测试的股票不等于没有新闻。')
    checkpoint(result);seen=set();deadline=time.monotonic()+100
    for query in queries[:max_queries]:
        if time.monotonic()>=deadline:break
        print('[搜索样本] '+query['lane']+'：开始',flush=True)
        before=getattr(workspace,'web_search_attempts',0)
        response=search(workspace,query['query'],hours=72,deadline=deadline)
        result['search_http_attempts']+=getattr(workspace,'web_search_attempts',0)-before
        result['search_results'].append(dict(plan=query,response=response))
        result['search_samples'].append(dict(lane=query['lane'],status=response.get('status'),
            reason=response.get('reason'),result_count=len(response.get('results',[])),
            first_results=[dict(title=row['title'],url=row['url'],published_hint=row.get('published_hint'))
                for row in response.get('results',[])[:3]]))
        checkpoint(result)
        print('[搜索样本] '+query['lane']+'：'+str(response.get('status'))+'，目录结果 '+str(len(response.get('results',[]))),flush=True)
        # Authentication/transport failures are paused by the existing adapter;
        # do not spend the other sample requests testing a known failed route.
        if response.get('status')!='ok':break
        candidate=None
        for row in response.get('results',[]):
            url=row.get('url')
            if not article_url(url):continue
            url=canonical(url) or url
            if url in seen or url in PAUSED_PUBLIC_ARTICLES:continue
            candidate=url;break
        if candidate is None:continue
        seen.add(candidate);result['public_body_urls_attempted']+=1
        body=read_public(workspace,candidate,hours=72,deadline=min(deadline,time.monotonic()+12),characters=1600)
        print('[正文样本] '+query['lane']+'：'+str(body.get('status'))+' '+str(body.get('reason') or ''),flush=True)
        result['body_results'].append(body)
        material=body.get('material') or {}
        if body.get('status')=='ok':result['readable_body_count']+=1
        result['body_samples'].append(dict(lane=query['lane'],status=body.get('status'),
            reason=body.get('reason'),url=body.get('url',candidate),title=material.get('title'),
            published=material.get('published'),provided_characters=len(material.get('text','')),
            has_more=material.get('has_more'),reading_scope=material.get('reading_scope'),
            excerpt=material.get('text','')[:120]))
        checkpoint(result)
    result['status']='completed_for_human_review' if len(result['search_results'])==len(queries[:max_queries]) and all(r['status']=='ok' for r in result['search_samples']) else 'partial_or_failed_no_retry'
    return result


async def main(run=False):
    backend=setup()
    from app.config import settings
    from app.services.time_context import china_now
    from app.services.watchlist_repository import read_app_watchlist,watchlist_signature
    from app.services.web_research import capabilities,search,read_public
    from app.services.research_hub import save_json
    now=china_now();stocks=await read_app_watchlist();queries=queries_for(stocks,now)
    maximum=min(4,settings.research_web_search_max_requests)
    print(json.dumps(dict(mode='controlled_search_run' if run else 'free_preview',configured=capabilities()['configured'],
        search_temporarily_enabled_in_this_process_only=bool(run),max_search_http_requests=maximum,
        search_depth='basic',reference_max_tavily_search_credits=maximum,
        max_public_body_urls=maximum,max_public_gets_including_redirects=maximum*3,
        model_requests=0,tts_requests=0,queries=queries[:maximum],
        limitation='额度不是账单保证；只调用Search，不调用Tavily Extract/Research。原.env开关和运行中的服务不改变。'),ensure_ascii=False,indent=2),flush=True)
    if not run:return
    if not capabilities()['configured']:raise RuntimeError('缺少Tavily密钥，未发起网络请求')
    root=backend/'data';marker=root/'diagnostics'/'tavily-acceptance-v1.started'
    output=root/'radar/cache'/'tavily-acceptance-v1.json'
    if marker.exists():
        print('本试验已尝试，不重复消耗积分。结果：'+str(output),flush=True)
        if output.exists():print(json.dumps(brief(json.loads(output.read_text(encoding='utf-8'))),ensure_ascii=False,indent=2))
        return
    marker.parent.mkdir(parents=True,exist_ok=True)
    with marker.open('x',encoding='utf-8') as f:f.write(now.isoformat())
    from app.services.episode_workspace import EpisodeWorkspace
    workspace=EpisodeWorkspace([],now=now)
    result={}
    def checkpoint(data):
        nonlocal result
        result=data
        tested={r['plan'].get('scope') for r in data.get('search_results',[]) if r['response'].get('status')=='ok'}
        data.update(owner='finance-tavily-acceptance-v1',collected_at=now.isoformat(),
            result_file=str(output),workspace=str(workspace.path),
            not_tested_watchlist=[s['market']+':'+s['code'] for s in stocks if s['market']+':'+s['code'] not in tested])
        save_json(output,data)
    try:
        # Process-local override is explicit, scoped, restored even on failure.
        with patch.object(settings,'research_web_search_enabled',True),patch.object(settings,'research_web_search_max_requests',maximum):
            result=sample(workspace,queries,search,read_public,checkpoint,now,maximum)
        if watchlist_signature(await read_app_watchlist())!=watchlist_signature(stocks):
            result['status']='watchlist_changed_not_accepted'
        result['finished_at']=china_now().isoformat();checkpoint(result)
        workspace.meta['status']='sampled_for_human_review';save_json(workspace.path/'meta.json',workspace.meta)
        print(json.dumps(brief(result),ensure_ascii=False,indent=2),flush=True)
    except Exception as error:
        result['search_http_attempts']=getattr(workspace,'web_search_attempts',result.get('search_http_attempts',0))
        result.update(status='failed_no_retry',error_type=type(error).__name__);checkpoint(result)
        print(json.dumps(brief(result),ensure_ascii=False,indent=2),flush=True)
        raise RuntimeError('试验已停止；保留开始标记，不重复运行扣积分。错误类型：'+type(error).__name__) from None


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true');args=parser.parse_args()
    asyncio.run(main(args.run))
