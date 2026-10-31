"""Offline audit of saved search metadata; never imports a model/network client."""
import argparse,json,sys
from pathlib import Path


def replay(data):
    from app.services.search_objectives import infer_purpose,assess,executed_coverage
    research=data.get('research',data);rows=[]
    for key,item in research.get('candidates',{}).items():
        inspections=[]
        for origin in item.get('discovered_by',[]):
            purpose=origin.get('purpose') or infer_purpose(origin['query'],origin['lane'])
            inspections.append(dict(lane=origin['lane'],query=origin['query'],**assess(item,purpose,origin['lane'])))
        rows.append(dict(id=key,title=item['title'],url=item['url'],inspections=inspections))
    return dict(mode='metadata_replay_no_requests',candidates=rows,
        executed_coverage=executed_coverage(research.get('receipts',[]),research.get('watchlist',[])),
        model_requests=0,search_requests=0,http_requests=0,
        limitation='旧标题与链接回放，不补造发布时间，不代表已读正文或判断过投资价值；检索方向不等于实际内容归属。')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,required=True);args=parser.parse_args()
    backend=Path.cwd()
    if not (backend/'app/config.py').is_file():raise RuntimeError('先进入backend目录')
    sys.path.insert(0,str(backend))
    print(json.dumps(replay(json.loads(args.input.read_text(encoding='utf-8'))),ensure_ascii=False,indent=2))
