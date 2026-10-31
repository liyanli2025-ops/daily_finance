"""Read-only capabilities/preflight; never searches or invokes a model."""
import argparse,json
from pathlib import Path
from .services.research_desk import AREAS,INSTRUCTIONS
from .services.web_research import capabilities

def inspect(snapshot=None):
    result=dict(mode='research_desk_free_preflight',external_model_requests=0,search_requests=0,
        public_article_requests=0,app_writes=0,automation_resumed=False,
        required_research_areas=list(AREAS),research_instruction_characters=len(INSTRUCTIONS),
        model_calls='沿用既有最多3次analysis调用；底稿和报告可在同一次回复交付，不加固定编辑调用',
        tools=capabilities(),limitation='能力配置/文件检查，不是搜索相关性、正文可读性、研究覆盖或报告质量验收。')
    if snapshot:
        data=json.loads(Path(snapshot).read_text(encoding='utf-8'))
        rows=data.get('raw_articles') or []
        result['snapshot']=dict(collected_at=data.get('collected_at'),stored_items=len(rows),
            stored_text_items=sum(bool(row.get('content')) for row in rows),
            note='存有文本不代表完整文章、有效增量、独立来源或模型读过；不刷新资料。')
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--snapshot');args=parser.parse_args()
    print(json.dumps(inspect(args.snapshot),ensure_ascii=False,indent=2))
