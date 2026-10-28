"""Only the four new nonofficial sources; no App DB, LLM or TTS requests."""
import argparse
import json
from pathlib import Path

from .services.public_news_sources import PublicNewsCollector
from .services.research_hub import save_json
from .services.time_context import china_now
from .services.evidence import publication_label

PROVIDERS=('eeo','jiemian','smm','trendforce')
SNAPSHOT=Path(__file__).resolve().parents[1]/'data/radar/nonofficial-acceptance.json'


def inspect(hours=72):
    articles,coverage=PublicNewsCollector().collect([],{},hours=hours,budget=40,providers=list(PROVIDERS))
    return dict(collected_at=china_now().isoformat(),mode='只采新增四家，空自选股、无App数据库写入、无模型/TTS调用',
        window_hours=hours,read=len(articles),coverage=coverage,
        articles=[dict(id=item.id,source=item.source,title=item.title,url=item.source_url,
            published=publication_label(item),characters=len(item.content),body_preview=item.content[:160]) for item in articles],
        limitation='公开文章主体提取不等于事实核实、全站覆盖或投资价值验收；源无近期新增与读取失败分开。')


def summary(result):
    sources={}
    for key,row in result.get('coverage',{}).get('sources',{}).items():
        sources[key]={field:row.get(field) for field in ('status','candidates','attempted','read','excluded_old_or_future','not_attempted')}
        sources[key]['error_count']=len(row.get('errors',[]))
        sources[key]['error_samples']=row.get('errors',[])[:3]
    return dict(collected_at=result.get('collected_at'),mode=result.get('mode'),read=result.get('read'),
        sources=sources,titles=[row['title'] for row in result.get('articles',[])],
        snapshot_path=str(SNAPSHOT),limitation=result.get('limitation'))


def run(hours=72,saved=False):
    if saved:
        # Missing snapshots do not trigger paid or public requests implicitly.
        result=json.loads(SNAPSHOT.read_text(encoding='utf-8'))
    else:
        result=inspect(hours)
        save_json(SNAPSHOT,result)
    return summary(result)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hours',type=int,default=72,choices=range(1,169),metavar='1..168')
    parser.add_argument('--saved-summary',action='store_true',help='只读上次四源验收结果，不重新请求')
    args=parser.parse_args()
    print(json.dumps(run(args.hours,args.saved_summary),ensure_ascii=False,indent=2))
