"""Read saved exposure audit only. No configuration, DB, network or model calls."""
import argparse
import json
from pathlib import Path


def check(path):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    usage=data.get('evidence_usage') or data.get('metadata',{}).get('evidence_usage')
    if 'confirmed_sources' in data and 'sources' in data:usage=data
    if not usage:
        return dict(status='unknown_historical_scope',
            limitation='旧诊断未记录实际入模字符范围，不能用收集数或正文状态倒推模型读过多少。')
    return dict(status='recorded',
        counts={key:usage.get(key) for key in ('pool_count','prepared_sources','confirmed_sources',
            'completed_analysis_rounds','cited_sources','decision_sources')},
        cited_without_confirmed_text=usage.get('cited_without_confirmed_text',[]),
        decision_sources_without_confirmed_text=usage.get('decision_sources_without_confirmed_text',[]),
        decisions=usage.get('decisions',[]),
        sources=[{key:row.get(key) for key in ('id','title','reading_scope','characters',
            'confirmed_stored_characters','model_input_scope','channels','cited')} for row in usage['sources']],
        limitation=usage.get('limitation'))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',required=True)
    args=parser.parse_args()
    print(json.dumps(check(args.case),ensure_ascii=False,indent=2))
