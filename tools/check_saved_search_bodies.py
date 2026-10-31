"""Default offline plan; --run-public reads <=3 cached or untried saved URLs.

No model or search calls, no failed URL retest, no report/database/scheduler writes.
"""
import argparse
from datetime import datetime
import hashlib,json,os
from pathlib import Path
import sys,time


def plan(data):
    from app.services.primary_discovery import landing_page,unsupported_page
    from app.services.event_observations import canonical
    from app.services import public_news_sources,overseas_sources
    from app.services.web_research import archived_public_body
    research=data.get('research',{});candidates=research.get('candidates',{})
    attempted={r['request'].get('candidate_id') for r in research.get('receipts',[])
               if r['request'].get('tool')=='read'}
    attempted_urls={canonical(candidates[key]['url']) for key in attempted if key in candidates}
    targets=[];skipped=[];seen=set()
    for key,row in candidates.items():
        url=canonical(row['url']);reason=None
        stored=archived_public_body(url,datetime.fromisoformat(research['started_at'])) if url else None
        if not url:reason='invalid_url'
        elif url in attempted_urls and not stored:reason='previously_attempted_no_retest'
        elif url in seen:reason='duplicate_url'
        elif landing_page(url):reason='landing_page'
        elif unsupported_page(url):reason=unsupported_page(url)
        if reason:skipped.append(dict(candidate_id=key,reason=reason));continue
        seen.add(url)
        known=any(module.permitted(provider,url) for module in (public_news_sources,overseas_sources) for provider in module.SOURCES)
        targets.append(dict(candidate_id=key,title=row.get('title'),url=url,known_publisher_template=known,
                            mode='cached_only' if stored else 'untried_public'))
    targets.sort(key=lambda r:(r['mode']!='cached_only',not r['known_publisher_template']))
    diagnosis=dict(status='no_saved_response')
    if research.get('decisions'):
        from app.services.primary_discovery import decode,validate_finish
        try:
            last=decode(research['decisions'][-1]);diagnosis=dict(action=last['action'])
            if last['action']=='finish':
                validate_finish(last,set(research.get('provided_ids',[])),research.get('watchlist',[]),candidates)
                diagnosis['validation']='passed'
        except Exception as error:
            code=str(error)
            diagnosis.update(error_type=type(error).__name__,validation=code if code.startswith('discovery_') and len(code)<100 else 'reply_schema_or_json_invalid')
    return dict(targets=targets[:3],eligible_untried=len(targets),skipped=skipped,previous_finish_check=diagnosis,
                snapshot_cutoff=research.get('started_at'),max_url_reads=3,max_public_gets_including_redirects=9,
                model_requests=0,search_requests=0,tts_requests=0,
                limitation='只检查旧搜索结果中未尝试的链接，不是新采集或重要性验收；时间沿用旧资料截止，不重试已尝试链接。')


def fingerprint(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def execute(backend,value,expected,reader=None,workspace_factory=None):
    from app.services.web_research import read_public
    from app.services.episode_workspace import EpisodeWorkspace
    from app.services.research_hub import save_json
    from app.services.time_context import china_now
    if fingerprint(value)!=expected:raise RuntimeError('公共正文预检计划指纹不匹配')
    if not value['targets']:
        result=dict(status='no_cached_or_untried_eligible_links',model_requests=0,search_requests=0,http_requests=0)
        print(json.dumps(result,ensure_ascii=False));return result
    marker=backend/'data/diagnostics/saved-body-check-v1.started'
    result=backend/'data/radar/cache/saved-body-check-v1.result.json'
    marker.parent.mkdir(parents=True,exist_ok=True)
    try:fd=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:
        print('该公共正文检查已尝试，不重复请求。结果：'+str(result));return
    os.close(fd)
    workspace=(workspace_factory or EpisodeWorkspace)([],now=datetime.fromisoformat(value['snapshot_cutoff']))
    data=dict(owner='finance-saved-body-check-v1',collected_at=china_now().isoformat(),workspace=str(workspace.path),
              status='running',plan=value,results=[],model_requests=0,search_requests=0,tts_requests=0)
    save_json(result,data);deadline=time.monotonic()+50
    try:
        for row in value['targets']:
            if time.monotonic()>=deadline:break
            if row.get('mode')=='cached_only' and reader is None:
                from app.services.web_research import archived_public_body
                stored=archived_public_body(row['url'],workspace.now)
                if stored:
                    item,observed=stored;workspace.add([item])
                    response=dict(status='ok',material=workspace.read(item.id,characters=1800),cache_observed_at=observed,
                                  remote_version_checked=False,http_requests_performed=0)
                else:response=dict(status='unavailable',reason='cache_changed_no_network_fallback')
            else:response=(reader or read_public)(workspace,row['url'],hours=72,deadline=min(deadline,time.monotonic()+15),characters=1800)
            data['results'].append(dict(candidate=row,response=response));save_json(result,data)
        data['status']='completed_for_parser_review'
    except Exception as error:data.update(status='failed_no_retest',error_type=type(error).__name__)
    finally:save_json(result,data)
    summary=dict(status=data['status'],workspace=str(workspace.path),result_file=str(result),results=[])
    for row in data['results']:
        response=row['response'];material=response.get('material',{})
        summary['results'].append(dict(title=row['candidate']['title'],url=row['candidate']['url'],
            status=response.get('status'),reason=response.get('reason'),capture=response.get('response_capture'),
            characters=len(material.get('text','')),excerpt=material.get('text','')[:180]))
    print(json.dumps(summary,ensure_ascii=False,indent=2));return data


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-public',action='store_true');parser.add_argument('--input-sha')
    args=parser.parse_args();backend=Path.cwd().resolve()
    if not (backend/'app/config.py').is_file():raise RuntimeError('先cd /var/www/finance-daily/backend')
    sys.path.insert(0,str(backend))
    source=backend/'data/radar/cache/model-led-primary-v1.result.json'
    value=plan(json.loads(source.read_text(encoding='utf-8')))
    if args.run_public:
        print(json.dumps(dict(previous_finish_check=value['previous_finish_check'],eligible_untried=value['eligible_untried'],targets=value['targets']),ensure_ascii=False,indent=2),flush=True)
        execute(backend,value,args.input_sha or fingerprint(value))
    else:print(json.dumps(dict(mode='offline_plan_no_requests',input_sha256=fingerprint(value),**value),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
