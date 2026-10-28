"""Read a saved review without calling models, collecting news or publishing."""
import argparse
import json
import os
from pathlib import Path

from .services.review_feedback import assess


def inspect(path,export_candidate=False):
    path=Path(path)
    case=json.loads(path.read_text(encoding='utf-8'))
    report=case['content']+'\n\n待核验的标题、摘要和核心观点：\n'+json.dumps(case.get('metadata',{}),ensure_ascii=False)
    evidence='\n'.join(case.get(key,'') for key in ('market_evidence','finance_evidence','cross_evidence'))
    review=case['review']
    result=dict(case=path.name,overall_quality=review.get('overall_quality'),
        issue_count=len(review['issues']),feedback_checks=assess(review['issues'],report,evidence),
        decision_notes=case.get('metadata',{}).get('decision_notes',[]),
        status='saved_case_for_human_review',
        limitation='旧意见缺锚点不等于意见错误，也不等于报告通过；只读检查不新增模型请求或App报告，不改变旧失败标记')
    if export_candidate:
        target=path.with_suffix('.candidate.md')
        text='未通过发布审核，仅供人工核对；不是已通过的App报告。\n\n'+case['content']
        if target.exists():
            if target.read_text(encoding='utf-8')!=text:raise RuntimeError('已有候选稿不同，停止覆盖')
        else:
            fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w',encoding='utf-8') as stream:stream.write(text)
        result['candidate_output']=str(target)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--case',required=True,type=Path)
    parser.add_argument('--export-candidate',action='store_true')
    args=parser.parse_args()
    print(json.dumps(inspect(args.case,args.export_candidate),ensure_ascii=False,indent=2))
